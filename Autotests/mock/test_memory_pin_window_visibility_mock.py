"""
Mock test: a (pin ...) emitted in turn 1 must land in history.metta
and remain inside the agent's rolling HISTORY window when turn 2 fires.

The mock answer for turn 1 dictates the pin; the mock answer for turn 2
dictates a (send ...) acknowledgement. Verification reads history.metta
directly and confirms (a) the pin block is on disk and (b) it sits within
the trailing `maxHistory` byte window.

Run:
    pytest test_memory_pin_window_visibility_mock.py -s
"""
import time

from helpers import (
    Checker, HISTORY_FILE, dexec, find_skill_calls, make_prompt,
    send_prompt, wait_for_skill_call,
)

MAX_HISTORY_BYTES = 30000


def history_tail_bytes(n):
    """Return the last n bytes of HISTORY_FILE as seen by getHistory."""
    res = dexec("sh", "-c", f"tail -c {n} {HISTORY_FILE}")
    return res.stdout if res.returncode == 0 else ""


def test_memory_pin_window_visibility_mock(llm, comm):
    with Checker("pin visibility in HISTORY window (mock)") as c:
        print(f"\n=== Omega: pin window visibility (run-id {c.run_id}) ===",
              flush=True)

        pin_marker = f"alpha-{c.run_id}"
        c.add_cleanup_marker(pin_marker)

        # ---------- turn 1 ----------
        c.step("turn 1: send prompt; mock answers with (pin ...)")
        prompt1 = make_prompt(
            c.run_id,
            f"Please pin the working-memory note: '{pin_marker}'. "
            f"Acknowledge with one short send.",
        )
        llm.set_answer(
            prompt1,
            [("pin", { "message": f"{pin_marker}" }),
            ("send", { "content": f"Pinned {pin_marker}." })]
        )
        if not comm.send_message(prompt1):
            c.fail("comm-1", "could not deliver turn 1 prompt within 60s")
        c.ok("comm-1", f"run-id={c.run_id}")

        c.step("verify pin was invoked")
        pin_arg = wait_for_skill_call(
            c.run_id, "pin", timeout=60, arg_substr=pin_marker,
        )
        if pin_arg is None:
            calls = find_skill_calls(c.run_id, "pin") or []
            c.fail("pin invoked",
                   f"no (pin ...) with {pin_marker!r}. "
                   f"Got: {[a[:60] for a in calls[:3]]}")
        c.ok("pin invoked", f"arg={pin_arg[:80]!r}")

        c.step("verify pin block is in history.metta on disk")
        time.sleep(5)
        res = dexec("grep", "-c", pin_marker, HISTORY_FILE)
        try:
            on_disk_count = int(res.stdout.strip())
        except ValueError:
            on_disk_count = 0
        if on_disk_count < 1:
            c.fail("pin on disk",
                   f"marker {pin_marker!r} not found in {HISTORY_FILE}")
        c.ok("pin on disk", f"{on_disk_count} occurrence(s)")

        c.step("wait 60s so a fresh iteration could pick up HISTORY")
        time.sleep(60)

        c.step("verify pin block sits inside last maxHistory bytes (visible to getHistory)")
        tail = history_tail_bytes(MAX_HISTORY_BYTES)
        if pin_marker not in tail:
            c.fail("pin in tail",
                   f"marker {pin_marker!r} outside last {MAX_HISTORY_BYTES} "
                   f"bytes — agent's HISTORY window would not see it")
        c.ok("pin in tail",
             f"marker present in last {MAX_HISTORY_BYTES} bytes")

        # ---------- turn 2 ----------
        recall_id = c.run_id + 1
        c.add_cleanup_marker(str(recall_id))
        c.step("turn 2: ask the agent to recall its pinned note")
        prompt2 = make_prompt(
            recall_id,
            "What did you pin in your previous turn? Respond with one short send.",
        )
        llm.set_answer(
            prompt2,
            [("send", { "content": f"I pinned {pin_marker} previously." })]
        )
        if not comm.send_message(prompt2):
            c.fail("comm-2", "could not deliver turn 2 prompt within 60s")
        c.ok("comm-2", f"run-id={recall_id}")

        c.step("verify agent sent acknowledgement in turn 2")
        send_arg = wait_for_skill_call(recall_id, "send", timeout=60)
        if send_arg is None:
            c.fail("send invoked", "agent did not respond in turn 2")
        c.ok("send invoked", f"reply={send_arg[:80]!r}")

        c.done()
