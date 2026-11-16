from helpers import dexec

OMEGA_DIR = "/PeTTa/repos/Omega"

PRELUDE = f"""
!(import! &self ./tests/res/router_setup)
!(import! &self {OMEGA_DIR}/src/utils.py)
!(import! &self {OMEGA_DIR}/src/providers.py)
!(import! &self ./src/providers)
!(import! &self {OMEGA_DIR}/tests/res/router_recorder.py)

(= (listOf $a) (py-call (utils.listAppend (py-call (utils.listNew)) $a)))
(= (listOf $a $b) (py-call (utils.listAppend (listOf $a) $b)))
(= (listOf $a $b $c) (py-call (utils.listAppend (listOf $a $b) $c)))
(= (userMsg $text) (llmRequestMessage role "user" content $text))
(= (toolMsg $text) (llmToolCallResponseMessage role "tool" callid "call#0" content $text))
(= (assistantMsg) (llmToolCallMessage role "assistant" calls (py-call (utils.listNew)) content "[TOOL CALL]"))
(= (pingRequest $episodes)
   (llmRequest (llmRequestMessage role "system" content "system prompt")
               $episodes 100 medium (py-call (router_recorder.tools))))
(= (serve $router $request)
   (let* (($_ (py-call (router_recorder.reset)))
          ($response (llmProviderChat $request $router)))
     (py-call (router_recorder.served))))
(= (serveEmpty $router $request)
   (llmResponseIsEmpty (llmProviderChat $request $router)))
(= (startBothRoles)
   (let* (($_ (py-call (router_recorder.register "Recorder")))
          ($_ (py-call (providers.llmProvidersInitDict))))
     (llmProvidersStartEntries
        ((routine ((provider Recorder) (model "routine-model") (api_token_var ROUTINE_KEY) (openaiapi_url none)))
         (premium ((provider Recorder) (model "premium-model") (api_token_var PREMIUM_KEY) (openaiapi_url none)))))))
"""

CONFIG_PRELUDE = f"""
(= (provider) (empty))
(= (router) (empty))
!(import! &self {OMEGA_DIR}/src/helper.py)
!(import! &self {OMEGA_DIR}/src/config.py)
!(import! &self ./src/config)
"""

ROUTINE_SERVED = "catalog/routine@routine-model@None"
PREMIUM_SERVED = "catalog/premium@premium-model@PREMIUM_KEY"


def _run_probe(source):
    probe = f"""
import os
from pathlib import Path
import subprocess
import tempfile

with tempfile.TemporaryDirectory(prefix='omega-router-probe-') as directory:
    path = Path(directory) / 'probe.metta'
    path.write_text({source!r}, encoding='utf-8')
    runner = Path(os.environ.get('PETTA_PATH', '/PeTTa')) / 'run.sh'
    env = dict(os.environ, PYTHONPATH='{OMEGA_DIR}:{OMEGA_DIR}/src')
    result = subprocess.run(
        ['sh', str(runner), str(path)], cwd='{OMEGA_DIR}', env=env,
        capture_output=True, text=True, timeout=90,
    )
    print(result.stdout)
    print(result.stderr)
    raise SystemExit(result.returncode)
"""
    result = dexec('python3', '-c', probe)
    return result.returncode, result.stdout + result.stderr


def _checks(output):
    return [line for line in output.splitlines() if ' should ' in line]


def _assert_all_passed(returncode, output, expected):
    assert returncode == 0, output
    checks = _checks(output)
    assert not any('❌' in line for line in checks), output
    assert sum('✅' in line for line in checks) == expected, output


def _rejected_for_missing_premium(returncode, output):
    if returncode == 0:
        return False
    errors = [line.lower() for line in output.splitlines() if line.startswith('ERROR: [Thread main]')]
    for line in errors:
        if 'premium' not in line:
            continue
        if 'role' in line or 'router' in line or 'valueerror' in line or 'runtimeerror' in line:
            return True
    return False


def _assert_served_by_routine_or_rejected(returncode, output):
    if _rejected_for_missing_premium(returncode, output):
        return
    _assert_all_passed(returncode, output, 2)


SINGLE_ROLE_START = """
(= (command-line)
   ("config=./tests/res/router_config_empty_catalog.yaml"
    "provider=Recorder"
    "model=routine-model"
    "router=default"
    "routerCatalogFile=none"))
!(initConfig)
!(configure provider none)
!(configure router none)
!(configure routerCatalogFile none)
!(py-call (router_recorder.register "Recorder"))
!(llmProvidersInitialize)
"""


def test_single_role_catalog_serves_slash_premium_from_routine():
    source = PRELUDE + CONFIG_PRELUDE + SINGLE_ROLE_START + f"""
!(test (serveEmpty (router) (pingRequest (listOf (userMsg "please use /premium now")))) False)
!(test (serve (router) (pingRequest (listOf (userMsg "please use /premium now")))) {ROUTINE_SERVED})
"""
    _assert_served_by_routine_or_rejected(*_run_probe(source))


def test_single_role_catalog_serves_tool_failure_from_routine():
    failure = "ALERT_FAILED(Error (python_error RuntimeError boom))"
    request = f'(pingRequest (listOf (userMsg "check the disk") (assistantMsg) (toolMsg "{failure}")))'
    source = PRELUDE + CONFIG_PRELUDE + SINGLE_ROLE_START + f"""
!(test (serveEmpty (router) {request}) False)
!(test (serve (router) {request}) {ROUTINE_SERVED})
"""
    _assert_served_by_routine_or_rejected(*_run_probe(source))


def test_two_authors_in_one_irc_batch_select_premium():
    source = PRELUDE + f"""
!(import! &self {OMEGA_DIR}/src/channels.py)
!(import! &self ./src/plugin)
!(loadPlugin (python "irc" "./channels"))
!(py-call (router_recorder.select_irc_channel))
!(py-call (irc._set_last "alice: hi"))
!(py-call (irc._set_last "bob: yo"))
(= (received) (string-safe (repr (py-call (channels.commChannelReceive)))))
!(startBothRoles)
!(test (serve default (pingRequest (listOf (userMsg (received))))) {PREMIUM_SERVED})
"""
    _assert_all_passed(*_run_probe(source), 1)
