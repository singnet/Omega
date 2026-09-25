"""
Mock test: history.metta is a sliding byte-window. A marker placed early
in the trace, then pushed past the maxHistory boundary by a large
follow-up entry, must remain in the file on disk yet be absent from the
trailing maxHistory bytes (the slice fed back to the agent as HISTORY).

This test does not require the agent to "behave intelligently" — it
verifies the file-level truncation mechanic that getHistory relies on.

Run:
    pytest test_memory_history_byte_window_truncation_mock.py -s
"""
import time

from helpers import (
    Checker, HISTORY_FILE, dexec, find_skill_calls, make_prompt,
    send_prompt, wait_for_skill_call,
)

MAX_HISTORY_BYTES = 30000
PADDING_BYTES = 35000  # >maxHistory so the early marker is guaranteed to fall out


def history_file_size():
    res = dexec("wc", "-c", HISTORY_FILE)
    try:
        return int(res.stdout.split()[0])
    except (ValueError, IndexError):
        return 0


def history_tail(n):
    res = dexec("sh", "-c", f"tail -c {n} {HISTORY_FILE}")
    return res.stdout if res.returncode == 0 else ""


def test_memory_history_byte_window_truncation_mock(llm, comm):
    with Checker("history.metta byte-window truncation (mock)") as c:
        print(f"\n=== Omega: history window truncation (run-id {c.run_id}) ===",
              flush=True)

        early_marker = f"EARLY-{c.run_id}"
        c.add_cleanup_marker(early_marker)

        size_before = history_file_size()
        c.ok("history baseline", f"file size {size_before} bytes")

        # ---------- turn 1: write the EARLY marker ----------
        c.step("turn 1: send EARLY marker via a short (send ...)")
        prompt1 = make_prompt(
            c.run_id,
            f"Send back exactly this token in a single send: {early_marker}",
        )
        llm.set_answer(prompt1, [("send", { "content": f"{early_marker}" })])
        if not comm.send_message(prompt1):
            c.fail("comm-1", "could not deliver turn 1 prompt within 60s")
        c.ok("comm-1", f"run-id={c.run_id}")

        send_arg = wait_for_skill_call(
            c.run_id, "send", timeout=60, arg_substr=early_marker,
        )
        if send_arg is None:
            c.fail("send fired", "agent did not emit EARLY send")
        c.ok("send fired", f"reply={send_arg[:60]!r}")

        c.step("verify EARLY marker is in last 30K bytes (still visible to HISTORY)")
        time.sleep(3)
        if early_marker not in history_tail(MAX_HISTORY_BYTES):
            c.fail("early in tail",
                   "marker missing from tail before padding — test cannot proceed")
        c.ok("early in tail", "marker visible inside HISTORY window")

        # ---------- turn 2: write the padding ----------
        padding_marker = f"PADDING-{c.run_id}"
        c.add_cleanup_marker(padding_marker)
        padding_body = padding_marker + ("A" * (PADDING_BYTES - len(padding_marker)))
        c.step(f"turn 2: write {PADDING_BYTES} bytes of padding via (remember ...)")
        prompt2 = make_prompt(
            c.run_id + 1,
            "Please write a long padding entry to long-term memory using the "
            "remember skill. The next message contains the exact string to "
            "remember verbatim. Acknowledge with a short send.",
        )
        c.add_cleanup_marker(str(c.run_id + 1))
        llm.set_answer(
            prompt2,
            [("remember", { "content": f"{padding_body}" })]
        )
        if not comm.send_message(prompt2):
            c.fail("comm-2", "could not deliver padding prompt within 60s")
        c.ok("comm-2", f"run-id={c.run_id + 1}")

        c.step("verify the padding (remember ...) call landed")
        rem_arg = wait_for_skill_call(
            c.run_id + 1, "remember", timeout=120, arg_substr=padding_marker,
        )
        if rem_arg is None:
            c.fail("padding remember",
                   "agent did not invoke remember with padding marker")
        c.ok("padding remember", f"len(arg)={len(rem_arg)}")

        c.step("wait for the padding block to be appended to history.metta")
        time.sleep(15)
        size_after = history_file_size()
        if size_after - size_before < PADDING_BYTES:
            c.fail("file grew",
                   f"file size delta {size_after - size_before} < {PADDING_BYTES}; "
                   f"padding did not land")
        c.ok("file grew", f"{size_before} -> {size_after} bytes")

        c.step("verify EARLY marker still in the file on disk")
        res = dexec("grep", "-c", early_marker, HISTORY_FILE)
        try:
            disk_hits = int(res.stdout.strip())
        except ValueError:
            disk_hits = 0
        if disk_hits < 1:
            c.fail("early on disk", "marker disappeared from file — eviction is wrong")
        c.ok("early on disk", f"{disk_hits} occurrence(s)")

        c.step("verify EARLY marker is OUTSIDE last 30K bytes (evicted from HISTORY)")
        tail = history_tail(MAX_HISTORY_BYTES)
        if early_marker in tail:
            c.fail("early evicted",
                   f"marker still inside last {MAX_HISTORY_BYTES} bytes — "
                   f"padding insufficient or window math wrong")
        c.ok("early evicted",
             f"marker outside last {MAX_HISTORY_BYTES} bytes (only via episodes now)")

        c.done()
