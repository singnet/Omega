"""
Mock test for history.metta recreation.

Verifies the agent's resilience when the main history file is missing. 
The test temporarily moves the existing history.metta to a backup, sends 
a message to trigger the agent's read/write cycle, and ensures that the 
agent does not crash but successfully creates a new history file. 
The original history is safely restored during teardown regardless of the test outcome.

Run:
    pytest test_memory_missing_history_file_mock.py -s
"""
from helpers import (
    Checker, dexec_root, make_prompt, wait_for_skill_call, HISTORY_FILE
)

HISTORY_BAK = "/tmp/history.metta.bak"

def test_history_recreation_mock(llm, comm):
    with Checker("history recreation on missing file") as c:
        print(f"\n=== Omega: history recreation mock (run-id {c.run_id}) ===", flush=True)

        try:
            c.step("Move history.metta to a temporary backup")
            dexec_root("sh", "-c", f"mv -f {HISTORY_FILE} {HISTORY_BAK} 2>/dev/null || true")
            
            if dexec_root("test", "-f", HISTORY_FILE).returncode == 0:
                c.fail("move", "Failed to move history.metta")
            c.ok("move", "history.metta successfully moved to backup")

            c.step("Send message to trigger read and write")
            prompt = make_prompt(c.run_id, "Testing history recreation.")
            llm.set_answer(prompt, [("send", { "content": f"History tested {c.run_id}" })])
            
            if not comm.send_message(prompt):
                c.fail("comm", "Failed to deliver prompt")
            c.ok("comm", f"run-id={c.run_id}")

            c.step("Wait for agent to process message without crashing")
            send_arg = wait_for_skill_call(c.run_id, "send", timeout=30)
            if send_arg is None:
                c.fail("send", "Agent did not respond (might have crashed on read/write)")
            c.ok("send", f"Response received: {send_arg[:30]}...")

            c.step("Verify history.metta was recreated")
            if dexec_root("test", "-f", HISTORY_FILE).returncode != 0:
                c.fail("recreate", "history.metta was not recreated")
            c.ok("recreate", "history.metta successfully recreated")
        
        finally:
            c.step("Teardown: restore history.metta from backup")
            dexec_root("sh", "-c", f"mv -f {HISTORY_BAK} {HISTORY_FILE} 2>/dev/null || true")
        
        c.done()
