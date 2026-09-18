"""
Mock tests for prompt file resilience.

Verifies the agent's ability to gracefully handle missing essential files:
  1. Fallback behavior when the default prompt.txt is missing.
  2. Fallback behavior when a provider-specific prompt (prompt_Test.txt)
     is missing.

The LLM responses are mocked to return simple acknowledgments, allowing
the test to focus purely on file I/O safety and fallback mechanics without 
testing LLM behavior.

Run:
    pytest test_prompt_missing_files_mock.py -s
"""
from helpers import Checker, dexec_root, make_prompt, wait_for_skill_call


PROMPT_FILE = "/PeTTa/repos/Omega/memory/prompt.txt"
PROMPT_BAK = "/tmp/prompt.txt.bak"

PROMPT_PROVIDER_FILE = "/PeTTa/repos/Omega/memory/prompt_Test.txt"
PROMPT_PROVIDER_BAK = "/tmp/prompt_Test.txt.bak"


def test_missing_default_prompt_mock(llm, comm):
    with Checker("missing default prompt fallback") as c:
        print(f"\n=== Omega: missing prompt mock (run-id {c.run_id}) ===", flush=True)

        try:
            c.step("Move prompt.txt to a temporary backup")
            dexec_root("mv", PROMPT_FILE, PROMPT_BAK)
            if dexec_root("test", "-f", PROMPT_FILE).returncode == 0:
                c.fail("move", "Failed to remove prompt.txt")
            c.ok("move", "prompt.txt temporarily removed")

            c.step("Send message to agent")
            prompt = make_prompt(c.run_id, "Testing missing default prompt.")
            llm.set_answer(prompt, [
                ("send", { "content": f"Prompt tested {c.run_id}" })
            ])
            comm.send_message(prompt)

            c.step("Verify agent survived and responded")
            send_arg = wait_for_skill_call(c.run_id, "send", timeout=30)
            if send_arg is None:
                c.fail("send", "Agent crashed or failed to respond due to missing prompt")
            c.ok("send", "Agent successfully processed with an empty prompt string")

        finally:
            c.step("Teardown: restore prompt.txt")
            dexec_root("mv", PROMPT_BAK, PROMPT_FILE)
            
        c.done()


def test_missing_provider_prompt_mock(llm, comm):
    with Checker("missing provider prompt fallback") as c:
        print(f"\n=== Omega: provider prompt fallback (run-id {c.run_id}) ===", flush=True)

        try:
            c.step("Ensure provider prompt is missing (move if it exists)")
            dexec_root("sh", "-c", f"mv {PROMPT_PROVIDER_FILE} {PROMPT_PROVIDER_BAK} 2>/dev/null || true")
            
            c.step("Send message to agent")
            prompt = make_prompt(c.run_id, "Testing fallback to default prompt.")
            llm.set_answer(prompt, [("send", { "content": f"Fallback tested {c.run_id}" })])
            comm.send_message(prompt)

            c.step("Verify agent successfully used fallback prompt")
            send_arg = wait_for_skill_call(c.run_id, "send", timeout=30)
            if send_arg is None:
                c.fail("send", "Agent did not respond")
            c.ok("send", "Fallback to default prompt worked successfully")

        finally:
            c.step("Teardown: restore provider prompt if it existed")
            dexec_root("sh", "-c", f"mv {PROMPT_PROVIDER_BAK} {PROMPT_PROVIDER_FILE} 2>/dev/null || true")
            
        c.done()
