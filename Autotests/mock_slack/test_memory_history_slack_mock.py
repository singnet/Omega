"""
Mock variant of test_memory_history.

The mocked LLM response sends back a (send ...) acknowledgement carrying
our REQ-tag. The history.metta file is written for real by the agent
loop after each iteration; the mock only fixes the agent's reply so the
test can verify the bookkeeping deterministically.

Run:
    pytest test_memory_history_mock.py -s
"""
import time


from helpers import (
    HISTORY_FILE, Checker, _history_block_for_run_id, find_skill_calls,
    get_mtime, get_size, make_prompt, read_history, wait_for_skill_call,
)
from slack_helpers import sl_send_prompt


def test_memory_history_slack_mock(llm, sl):
    with Checker("history append (slack mock)") as c:
        print(f"\n=== Omega: history append slack mock (run-id {c.run_id}) ===",
              flush=True)

        c.step("capture initial history state")
        mtime_before = get_mtime(HISTORY_FILE)
        size_before = get_size(HISTORY_FILE)
        if mtime_before is None or size_before is None:
            c.fail("history", f"{HISTORY_FILE} missing or inaccessible")
        c.ok("history initial", f"mtime={mtime_before}, size={size_before}")

        time.sleep(2)

        c.step("send prompt via Slack with mocked acknowledgement")
        prompt = make_prompt(
            c.run_id,
            f"Acknowledge with one short line that you received marker {c.run_id}.",
        )
        ack = f"Marker {c.run_id} received. REQ-{c.run_id} acknowledged."
        llm.set_answer(prompt, [("send", { "content": f"{ack}" })])
        sl_send_prompt(sl, prompt)
        c.ok("slack", f"run-id={c.run_id}")

        c.step("verify history contains an s-exp record quoting our REQ-tag")
        deadline = time.time() + 60
        block = None
        while time.time() < deadline:
            block = _history_block_for_run_id(read_history(), c.run_id)
            if block:
                break
            time.sleep(2)
        if not block:
            c.fail("history record",
                   f"no s-exp record referencing REQ-{c.run_id}")
        c.ok("history record",
             f"{len(block)} chars since first REQ-{c.run_id}")

        c.step("verify history contains (send ...) for our run_id")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30)
        if send_arg is None:
            c.fail("agent s-exp",
                   "no (send ...) call recorded in history for our run_id")
        c.ok("agent s-exp", f"send len={len(send_arg)}")

        c.step("check history mtime and size grew")
        mtime_after = get_mtime(HISTORY_FILE)
        size_after = get_size(HISTORY_FILE)
        if mtime_after is None or mtime_after <= mtime_before:
            c.fail("history mtime", f"before={mtime_before}, after={mtime_after}")
        if size_after is None or size_after <= size_before:
            c.fail("history size", f"before={size_before}, after={size_after}")
        c.ok("history grew",
             f"mtime {mtime_before}->{mtime_after}, "
             f"size +{size_after - size_before} bytes")

        c.done()
