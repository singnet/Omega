"""
Mock test for the get-io-policy skill.

This test verifies that the agent can successfully execute the 
get-io-policy skill without crashing and can process the returned JSON.

pytest test_io_policy_skill_mock.py -s
"""
import json
import yaml
from helpers import Checker, dexec, make_prompt, wait_for_skill_call


JSON_POLICY_OUTPUT_PATH = "/tmp/policy_out.json"
YAML_POLICY_INPUT_PATH = "/PeTTa/repos/Omega/profile/policy.yaml"
EXPECTED_READ_ONLY = [
    "/PeTTa",
    "/bin",
    "/dev/urandom",
    "/etc",
    "/lib",
    "/opt",
    "/proc",
    "/sys/devices/system",
    "/usr",
    "/var/log",
]
EXPECTED_READ_WRITE = [
    "/PeTTa/repos/Omega/memory",
    "/dev/null",
    "/dev/shm",
    "/memory-transfer",
    "/opt/huggingface",
    "/opt/sentence_transformers",
    "/tmp",
    "/var/tmp",
]
GLOB_CHARACTERS = "*?["


def test_get_io_policy_mock(llm, comm):
    with Checker("get-io-policy skill mock") as c:
        print(f"\n=== Omega: get-io-policy mock (run-id {c.run_id}) ===", flush=True)
        
        ####################################
        # Phase 1: check isolated skill call
        ####################################
        
        c.step("send prompt to check isolated skill invocation")
        prompt = make_prompt(c.run_id, "Check your IO policy.")
        llm.set_answer(
            request=prompt,
            response=([
                ("send", { "content": f"Checking my io policy {c.run_id}" }),
                ("get-io-policy", {})
            ])
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within timeout")
            
        c.step("verify send message does not absorb the skill")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30, arg_substr="Checking my io policy")
        if not send_arg:
            c.fail("send", "Agent did not respond to first prompt.")
        if "get-io-policy" in send_arg:
            c.fail("parser", f"Bug regression: get-io-policy was absorbed into the send message.")
        c.ok("parser", "get-io-policy was correctly parsed as a separate command.")
        
        ##########################
        # Phase 2: data validation
        ##########################
        
        c.step("send prompt asking to check IO policy")
        prompt = make_prompt(c.run_id, "Retrieve the current filesystem access policy.")
        llm.set_answer(
            request=prompt,
            response=([
                ("metta", { "sexpression":  f'(write-file "{JSON_POLICY_OUTPUT_PATH}" (get-io-policy))' }),
                ("send", { "content": f"Policy checked for {c.run_id}" })
            ])
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within timeout")
        c.ok("comm", f"run-id={c.run_id}")
        
        c.step("wait for agent to execute skills and respond")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30, arg_substr="Policy checked")
        if not send_arg:
            c.fail("send", "Agent did not respond. It might have crashed.")
        c.ok("send", "Agent successfully completed the chain.")
        
        c.step("read and parse the saved JSON from the container")
        policy_output = dexec("cat", JSON_POLICY_OUTPUT_PATH).stdout.strip()
        if not policy_output:
            c.fail("file_read", f'"{JSON_POLICY_OUTPUT_PATH}" is empty or was not created')
        try:
            policy_json = json.loads(policy_output)
        except json.JSONDecodeError as e:
            c.fail("json", f"Failed to parse JSON output: {e}\nOutput was: {policy_output}")
        c.ok("json_parse", "json with get-io-policy result successfully parsed")
        
        c.step("read and parse original policy.yaml")
        yaml_content = dexec("cat", YAML_POLICY_INPUT_PATH).stdout
        try:
            parsed_yaml = yaml.safe_load(yaml_content) or {}
        except yaml.YAMLError as e:
            c.fail("yaml_parse", f"Failed to parse policy.yaml: {e}")
        c.ok("yaml_parse", "policy.yaml successfully parsed")

        c.step("compare policy.yaml with the pinned default policy")
        fs_policy_yaml = parsed_yaml.get("filesystem_policy", {})
        for category, expected in (("read_only", EXPECTED_READ_ONLY),
                                   ("read_write", EXPECTED_READ_WRITE)):
            actual = fs_policy_yaml.get(category, [])
            if sorted(actual) != sorted(expected):
                c.fail(
                    name=f"pinned_{category}",
                    detail=(
                        f"Default policy changed! policy.yaml {category} is {sorted(actual)}, "
                        f"the test expects {sorted(expected)}. Update the test if the "
                        "change is intended."
                    )
                )
        c.ok("pinned", "policy.yaml matches the pinned default policy")

        c.step("compare get-io-policy skill result with the pinned default policy")
        for category, expected in (("read_only", EXPECTED_READ_ONLY),
                                   ("read_write", EXPECTED_READ_WRITE)):
            reported = policy_json.get(category, [])
            missing_paths = set(expected) - set(reported)
            extra_paths = set(reported) - set(expected)
            if missing_paths:
                c.fail(
                    name=f"compare_{category}",
                    detail=f"{category} permissions mismatch! Missing from JSON: {missing_paths}"
                )
            if extra_paths:
                c.fail(
                    name=f"compare_{category}",
                    detail=f"{category} permissions mismatch! Extra in JSON: {extra_paths}"
                )
            unresolved = [p for p in reported if any(ch in p for ch in GLOB_CHARACTERS)]
            if unresolved:
                c.fail(
                    name=f"resolved_{category}",
                    detail=(
                        f"{category} contains unresolved glob patterns: {unresolved}. "
                        "The skill must report the paths the policy resolves to."
                    )
                )
        c.ok("compare", "get-io-policy skill result exactly matches the pinned default policy.")
        
        c.done()
