import json
import shlex

import router_harness as rh

ROUTINE_TOKEN = "fake-routine-token"
PREMIUM_TOKEN = "fake-premium-token"
AGENT_ENVIRON = (
    r'for p in /proc/[0-9]*; do '
    r'[ "$p" = "/proc/$$" ] && continue; '
    r'case "$(tr "\0" " " < $p/cmdline 2>/dev/null)" in '
    r'*run.sh*|*swipl*) tr "\0" "\n" < $p/environ;; '
    r'esac; done'
)

TEST_CHANNEL = ["commchannel=test", "embeddingprovider=Local"]
SWITCH_TIMEOUT = rh.STARTUP_TIMEOUT + rh.REQUEST_TIMEOUT


def two_role_catalog(routine_stub, premium_stub, routine_model="model-routine", premium_model="model-premium"):
    return rh.catalog(
        (routine_stub, routine_model, ROUTINE_TOKEN),
        (premium_stub, premium_model, PREMIUM_TOKEN),
    )


def start_two_roles(start_agent, make_stub, routine_script=None, premium_script=None):
    timeline = rh.Timeline()
    routine = make_stub("routine", routine_script, timeline)
    premium = make_stub("premium", premium_script, timeline)
    agent = start_agent(
        ["router=default", *TEST_CHANNEL],
        env={"OMEGA_ROUTER_CATALOG": json.dumps(two_role_catalog(routine, premium))},
    )
    return agent, routine, premium, timeline


def test_router_none_openaiapi_serves_request_and_logs_single_role(start_agent, make_stub):
    stub = make_stub("only")
    agent = start_agent(
        ["router=none", "provider=OpenAIAPI", "model=model-r67", f"openaiapi_url={rh.stub_url(stub)}", *TEST_CHANNEL],
        env={"OPENAIAPI_API_KEY": ROUTINE_TOKEN},
    )
    assert agent.wait_stub_request(stub, SWITCH_TIMEOUT), "stub received no request; " + agent.describe()
    request = stub.requests[0]
    assert request["path"].endswith("/chat/completions")
    assert request["body"]["model"] == "model-r67"
    assert request["body"]["tool_choice"] == "required"
    assert request["authorization"] == f"Bearer {ROUTINE_TOKEN}"
    started = agent.runtime_lines("providers", r"Started LLM provider ")
    assert len(started) == 1, started
    assert "role=routine provider=OpenAIAPI model=model-r67" in started[0]


def test_failed_tool_call_switches_to_premium_and_back(start_agent, make_stub):
    agent, routine, premium, timeline = start_two_roles(
        start_agent, make_stub,
        routine_script=lambda _number: rh.failing_calls(),
        premium_script=lambda _number: rh.pin_calls(1),
    )
    assert timeline.wait_len(3, SWITCH_TIMEOUT), (
        f"timeline={timeline.snapshot()}; " + agent.describe())
    assert timeline.snapshot()[:3] == ["routine", "premium", "routine"]
    assert routine.requests[0]["body"]["model"] == "model-routine"
    assert routine.requests[0]["authorization"] == f"Bearer {ROUTINE_TOKEN}"
    assert premium.requests[0]["body"]["model"] == "model-premium"
    assert premium.requests[0]["authorization"] == f"Bearer {PREMIUM_TOKEN}"
    assert routine.requests[1]["body"]["model"] == "model-routine"


def test_eight_tool_results_keep_routine_role(start_agent, make_stub):
    agent, routine, premium, timeline = start_two_roles(
        start_agent, make_stub,
        routine_script=lambda number: rh.pin_calls(8) if number == 1 else rh.pin_calls(1),
        premium_script=lambda _number: rh.pin_calls(1),
    )
    assert timeline.wait_len(2, SWITCH_TIMEOUT), (
        f"timeline={timeline.snapshot()}; " + agent.describe())
    assert timeline.snapshot()[:2] == ["routine", "routine"]


def test_nine_tool_results_switch_to_premium_role(start_agent, make_stub):
    agent, routine, premium, timeline = start_two_roles(
        start_agent, make_stub,
        routine_script=lambda number: rh.pin_calls(9) if number == 1 else rh.pin_calls(1),
        premium_script=lambda _number: rh.pin_calls(1),
    )
    assert timeline.wait_len(3, SWITCH_TIMEOUT), (
        f"timeline={timeline.snapshot()}; " + agent.describe())
    assert timeline.snapshot()[:3] == ["routine", "premium", "routine"]
    assert premium.requests[0]["body"]["model"] == "model-premium"


def test_two_roles_log_started_lines_and_agent_process_cannot_see_keys(start_agent, make_stub):
    agent, routine, _premium, _timeline = start_two_roles(start_agent, make_stub)
    assert routine.wait_requests(1, SWITCH_TIMEOUT), agent.describe()

    started = agent.runtime_lines("providers", r"Started LLM provider ")
    assert len(started) == 2, started
    routine_lines = [line for line in started if "role=routine " in line]
    premium_lines = [line for line in started if "role=premium " in line]
    assert len(routine_lines) == 1 and "provider=OpenAIAPI model=model-routine" in routine_lines[0], started
    assert len(premium_lines) == 1 and "provider=OpenAIAPI model=model-premium" in premium_lines[0], started

    environ = agent.exec("sh", "-c", AGENT_ENVIRON, user="nobody").stdout
    assert "PATH=" in environ, "environment of the agent process was not read"
    for secret in (ROUTINE_TOKEN, PREMIUM_TOKEN, "OMEGA_ROUTER_CATALOG", "OPENAIAPI_API_KEY"):
        assert secret not in environ, f"{secret} visible in environment of agent process"

    denied = agent.exec("cat", "/opt/nginx/router.conf", user="nobody")
    assert denied.returncode != 0
    assert "Permission denied" in denied.stderr + denied.stdout
    assert ROUTINE_TOKEN not in denied.stdout + denied.stderr

    sanitized = agent.exec("cat", "/tmp/omega-router-catalog.json").stdout
    assert ROUTINE_TOKEN not in sanitized and PREMIUM_TOKEN not in sanitized
    assert sorted(json.loads(sanitized)) == ["premium", "routine"]

    log = agent.tail.text()
    assert "Sanitized JSON catalog:" in log
    assert ROUTINE_TOKEN not in log and PREMIUM_TOKEN not in log


def test_standalone_config_with_catalog_file_starts_both_roles(start_agent, make_stub):
    routine = make_stub("routine")
    premium = make_stub("premium")
    catalog_json = json.dumps(two_role_catalog(routine, premium, "model-sa-routine", "model-sa-premium"))
    script = (
        "cd /PeTTa && printf '%s' \"$CATALOG_JSON\" > /tmp/standalone-catalog.json && "
        "sed -e 's|^router:.*|router: default|' "
        "-e 's|^routerCatalogFile:.*|routerCatalogFile: /tmp/standalone-catalog.json|' "
        "/PeTTa/repos/Omega/config/config.yaml > /tmp/standalone-config.yaml && "
        f"exec sh run.sh run.metta config=/tmp/standalone-config.yaml {' '.join(shlex.quote(a) for a in TEST_CHANNEL)}"
    )
    agent = start_agent(
        ["-c", script],
        env={"CATALOG_JSON": catalog_json, "OPENAIAPI_API_KEY": ROUTINE_TOKEN},
        entrypoint="sh",
    )
    agent.wait_iteration_1()
    started = agent.runtime_lines("providers", r"Started LLM provider ")
    assert len(started) == 2, started
    assert any("role=routine provider=OpenAIAPI model=model-sa-routine" in line for line in started)
    assert any("role=premium provider=OpenAIAPI model=model-sa-premium" in line for line in started)
