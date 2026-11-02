"""
Mock test for the security policy path resolution.

profile/policy.py resolves the policy paths before Landlock sees them: a
glob pattern is expanded to the paths present on the host machine, and a
path matching nothing is dropped, because Landlock cannot add a rule for
a path which does not exist. The resolution is checked inside the
container, the only place where py_landlock is installed.

pytest test_policy_resolve_mock.py -s
"""
import json

from helpers import Checker, dexec

NODES_DIR = "/tmp/policy_nodes"
POLICY_PATHS = [f"{NODES_DIR}/node[0-9]", f"{NODES_DIR}/absent*",
                f"{NODES_DIR}/absent"]
EXPECTED_PATHS = [f"{NODES_DIR}/node0", f"{NODES_DIR}/node1"]
PROBE = (
    "import json, sys;"
    "sys.path[:0] = ['/PeTTa/repos/Omega/profile', '/PeTTa/repos/Omega',"
    " '/PeTTa/repos/Omega/src'];"
    "import policy;"
    "p = policy.FileSystemPolicy();"
    "p.load_dict({'version': 1, 'filesystem_policy': {'read_write': "
    f"{POLICY_PATHS}"
    "}});"
    "print(json.dumps([str(path) for path in p._resolve_paths(p._read_write)]))"
)


def test_policy_resolves_paths():
    with Checker("policy path resolution mock", cleanup_dirs=[NODES_DIR]) as c:
        c.step("create the paths the policy pattern must match")
        result = dexec("mkdir", "-p", NODES_DIR)
        if result.returncode != 0:
            c.fail("nodes", f"could not create {NODES_DIR}")
        result = dexec("touch", f"{NODES_DIR}/node0", f"{NODES_DIR}/node1")
        if result.returncode != 0:
            c.fail("nodes", f"could not create files in {NODES_DIR}")
        c.ok("nodes", f"{NODES_DIR} contains node0 and node1")

        c.step("resolve the policy paths inside the container")
        result = dexec("python3", "-c", PROBE)
        if result.returncode != 0:
            c.fail("probe", f"policy module failed to resolve paths: {result.stderr}")
        try:
            resolved = json.loads(result.stdout.strip())
        except json.JSONDecodeError as e:
            c.fail("probe", f"could not parse the resolved paths: {e}\nOutput was: {result.stdout}")
        c.ok("probe", f"resolved {resolved}")

        c.step("compare the resolved paths with the expected ones")
        if sorted(resolved) != sorted(EXPECTED_PATHS):
            c.fail(
                name="resolve",
                detail=(
                    f"Path resolution mismatch! The policy paths {POLICY_PATHS} "
                    f"resolved to {sorted(resolved)}, expected {sorted(EXPECTED_PATHS)}."
                )
            )
        c.ok("resolve", "the pattern is expanded and paths matching nothing are dropped")
        c.done()


PROBE_PREFIX = (
    "import json, sys\n"
    "sys.path[:0] = ['/PeTTa/repos/Omega/profile', '/PeTTa/repos/Omega',"
    " '/PeTTa/repos/Omega/src']\n"
    "import policy\n"
)
MISSING_REQUIRED = ["/qa-policy-missing-a", "/qa-policy-missing-b"]
MISSING_OPTIONAL = ["/run/nvidia-persistenced", "/dev/nvidia-qa9", "/usr/lib/wsl-qa"]
VALIDATE_PROBE = PROBE_PREFIX + (
    "p = policy.FileSystemPolicy()\n"
    "p.load_dict({'version': 1, 'filesystem_policy': {"
    f"'read_only': {[MISSING_REQUIRED[0]] + MISSING_OPTIONAL[:2]}, "
    f"'read_write': {[MISSING_REQUIRED[1], MISSING_OPTIONAL[2]]}"
    "}})\n"
    "try:\n"
    "    p.validate()\n"
    "    print('VALIDATE_OK')\n"
    "except ValueError as e:\n"
    "    print('VALIDATE_ERROR ' + str(e))\n"
)
APPLIED_POLICY_FILE = f"{NODES_DIR}/policy.yaml"
APPLIED_POLICY_YAML = (
    "version: 1\n"
    "filesystem_policy:\n"
    "  read_only:\n"
    f"  - {APPLIED_POLICY_FILE}\n"
    "  read_write:\n"
    f"  - {NODES_DIR}/node[0-9]\n"
)
SKILL_AFTER_APPLY_PROBE = PROBE_PREFIX + (
    f"policy.apply_security_policy('{APPLIED_POLICY_FILE}')\n"
    f"print(policy.get_allowed_policy_paths('{APPLIED_POLICY_FILE}'))\n"
    f"print(policy.get_allowed_policy_paths('\"{APPLIED_POLICY_FILE}\"'))\n"
)
SKIPPED_LINE = "Skipped missing optional policy paths"
SKIPPED_PROBE = PROBE_PREFIX + (
    "from src.logger import setup_logging\n"
    "setup_logging()\n"
    "p = policy.FileSystemPolicy()\n"
    "p.load_dict({'version': 1, 'filesystem_policy': {"
    f"'read_only': ['{MISSING_OPTIONAL[2]}'], "
    f"'read_write': ['{MISSING_OPTIONAL[1]}', '{NODES_DIR}/node0']"
    "}})\n"
    "p.apply()\n"
    "print('APPLIED')\n"
)


def test_policy_validation_lists_required_paths_only():
    with Checker("policy validation mock") as c:
        c.step("validate a policy with missing required and optional paths")
        result = dexec("python3", "-c", VALIDATE_PROBE)
        if result.returncode != 0:
            c.fail("probe", f"policy module failed: {result.stderr}")
        output = result.stdout.strip()
        if not output.startswith("VALIDATE_ERROR"):
            c.fail("validate", f"a missing required path did not stop the policy: {output}")
        missed = [p for p in MISSING_REQUIRED if p not in output]
        if missed:
            c.fail("required", f"the error does not name {missed}: {output}")
        wrongly_named = [p for p in MISSING_OPTIONAL if p in output]
        if wrongly_named:
            c.fail("optional", f"optional paths {wrongly_named} are reported as errors: {output}")
        c.ok("validate", "every missing required path is named and optional paths are not")
        c.done()


def test_policy_skill_paths_after_apply():
    with Checker("policy skill after apply mock", cleanup_dirs=[NODES_DIR]) as c:
        c.step("create the policy file and the paths its pattern must match")
        result = dexec("mkdir", "-p", NODES_DIR)
        if result.returncode != 0:
            c.fail("nodes", f"could not create {NODES_DIR}")
        result = dexec("touch", f"{NODES_DIR}/node0", f"{NODES_DIR}/node1")
        if result.returncode != 0:
            c.fail("nodes", f"could not create files in {NODES_DIR}")
        result = dexec("sh", "-c", f"printf '%s' '{APPLIED_POLICY_YAML}' > {APPLIED_POLICY_FILE}")
        if result.returncode != 0:
            c.fail("policy", f"could not write {APPLIED_POLICY_FILE}")
        c.ok("nodes", f"{NODES_DIR} contains node0, node1 and the policy file")

        c.step("apply the policy, then ask for the allowed paths in the same process")
        result = dexec("python3", "-c", SKILL_AFTER_APPLY_PROBE)
        if result.returncode != 0:
            c.fail("probe", f"policy module failed: {result.stderr}")
        try:
            reports = [json.loads(line) for line in result.stdout.strip().splitlines()[-2:]]
        except json.JSONDecodeError as e:
            c.fail("probe", f"could not parse the skill output: {e}\nOutput was: {result.stdout}")
        if len(reports) != 2:
            c.fail("probe", f"expected two skill outputs, got: {result.stdout}")
        for form, reported in zip(("plain", "quoted"), reports):
            if sorted(reported.get("read_write", [])) != sorted(EXPECTED_PATHS):
                c.fail(
                    name="skill",
                    detail=(
                        f"After the policy is applied the skill called with the {form} path "
                        f"reports read_write {reported.get('read_write')}, "
                        f"expected {sorted(EXPECTED_PATHS)}."
                    )
                )
        c.ok("skill", "the skill reports the paths the pattern resolved to when the policy was applied")
        c.done()


def test_policy_skipped_paths_logged_once():
    with Checker("policy skipped paths log mock", cleanup_dirs=[NODES_DIR]) as c:
        c.step("create the one existing path of the policy")
        result = dexec("mkdir", "-p", NODES_DIR)
        if result.returncode != 0:
            c.fail("nodes", f"could not create {NODES_DIR}")
        result = dexec("touch", f"{NODES_DIR}/node0")
        if result.returncode != 0:
            c.fail("nodes", f"could not create {NODES_DIR}/node0")
        c.ok("nodes", f"{NODES_DIR}/node0 exists")

        c.step("apply a policy with missing optional paths in both lists")
        result = dexec("python3", "-c", SKIPPED_PROBE)
        if result.returncode != 0 or "APPLIED" not in result.stdout:
            c.fail("probe", f"policy module failed: {result.stderr}")
        output = result.stdout + result.stderr
        lines = [line for line in output.splitlines() if SKIPPED_LINE in line]
        if len(lines) != 1:
            c.fail("log", f"expected one '{SKIPPED_LINE}' line, got {len(lines)}: {lines}")
        missed = [p for p in (MISSING_OPTIONAL[1], MISSING_OPTIONAL[2]) if p not in lines[0]]
        if missed:
            c.fail("log", f"the line does not name {missed}: {lines[0]}")
        if f"{NODES_DIR}/node0" in lines[0]:
            c.fail("log", f"the line names the existing path {NODES_DIR}/node0: {lines[0]}")
        c.ok("log", "one line names the skipped paths of both lists")
        c.done()
