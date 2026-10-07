"""
Mock test: a marker pushed out of the trailing maxHistory bytes is still
recoverable via the episodes skill (timestamp-based history scan).

Turn 1: agent sends a BEACON marker; we capture the timestamp.
Turn 2: agent writes ~35K bytes of padding to evict the BEACON from
        the trailing HISTORY window.
Turn 3: agent invokes (episodes "<seed_ts>"); we verify the call
        happened with the captured timestamp.

The episodes return value is mock-irrelevant here — what matters is
that the skill was invoked correctly against history that the agent
itself can no longer see in HISTORY.

Run:
    pytest test_transition_episodes_after_eviction_mock.py -s
"""
import datetime
import time

from helpers import (
    Checker, HISTORY_FILE, dexec, find_skill_calls, make_prompt,
    send_prompt, wait_for_skill_call,
)

MAX_HISTORY_BYTES = 30000
PADDING_BYTES = 35000


def history_tail(n):
    res = dexec("sh", "-c", f"tail -c {n} {HISTORY_FILE}")
    return res.stdout if res.returncode == 0 else ""


def test_transition_episodes_after_eviction_mock(llm, comm):
    with Checker("episodes retrieves evicted block (mock)") as c:
        print(f"\n=== Omega: episodes after eviction (run-id {c.run_id}) ===",
              flush=True)

        beacon_marker = f"BEACON-{c.run_id}"
        c.add_cleanup_marker(beacon_marker)

        # ---------- turn 1: seed BEACON ----------
        seed_time = datetime.datetime.now()
        c.step("turn 1: emit BEACON via short (send ...)")
        prompt1 = make_prompt(
            c.run_id,
            f"Send back exactly this token in a single send: {beacon_marker}",
        )
        llm.set_answer(prompt1, [("send", { "content": f"{beacon_marker}" })])
        if not comm.send_message(prompt1):
            c.fail("comm-1", "could not deliver seed prompt within 60s")
        c.ok("comm-1",
             f"run-id={c.run_id}, seed_time={seed_time:%Y-%m-%d %H:%M:%S}")

        send_arg = wait_for_skill_call(
            c.run_id, "send", timeout=60, arg_substr=beacon_marker,
        )
        if send_arg is None:
            c.fail("seed send", "BEACON was not emitted")
        c.ok("seed send", f"reply={send_arg[:60]!r}")

        # ---------- turn 2: padding to evict BEACON ----------
        padding_marker = f"PADDING-{c.run_id}"
        c.add_cleanup_marker(padding_marker)
        padding_body = padding_marker + ("A" * (PADDING_BYTES - len(padding_marker)))
        pad_id = c.run_id + 1
        c.add_cleanup_marker(str(pad_id))
        c.step(f"turn 2: write {PADDING_BYTES} bytes of padding to evict BEACON")
        prompt2 = make_prompt(
            pad_id,
            "Write a long padding entry to long-term memory via remember. "
            "Acknowledge with a short send.",
        )
        llm.set_answer(
            prompt2,
            [("remember", { "content": f"{padding_body}" })]
        )
        if not comm.send_message(prompt2):
            c.fail("comm-2", "could not deliver padding prompt within 60s")
        c.ok("comm-2", f"run-id={pad_id}")

        rem_arg = wait_for_skill_call(
            pad_id, "remember", timeout=120, arg_substr=padding_marker,
        )
        if rem_arg is None:
            c.fail("padding landed", "remember with padding marker not seen")
        c.ok("padding landed", f"len(arg)={len(rem_arg)}")

        c.step("wait for padding to flush to history.metta")
        time.sleep(15)
        tail = history_tail(MAX_HISTORY_BYTES)
        if beacon_marker in tail:
            c.fail("beacon evicted",
                   f"BEACON still inside last {MAX_HISTORY_BYTES} bytes; "
                   f"padding insufficient")
        c.ok("beacon evicted",
             f"BEACON outside trailing {MAX_HISTORY_BYTES} bytes (only via episodes now)")

        # ---------- turn 3: episodes recall ----------
        recall_id = c.run_id + 2
        c.add_cleanup_marker(str(recall_id))
        c.step("turn 3: ask the agent to recall the seed time via episodes")
        seed_ts_str = seed_time.strftime("%Y-%m-%d %H:%M:%S")
        prompt3 = make_prompt(
            recall_id,
            f"Use the episodes skill to look up what happened around "
            f"{seed_ts_str}, then report what marker you found in a short send.",
        )
        llm.set_answer(
            prompt3,
            [("episodes", { "timestamp": f"{seed_ts_str}" }),
             ("send", { "content": f"Recalled {beacon_marker}." })]
        )
        if not comm.send_message(prompt3):
            c.fail("comm-3", "could not deliver recall prompt within 60s")
        c.ok("comm-3", f"run-id={recall_id}")

        c.step("verify (episodes ...) was invoked with seed timestamp")
        ep_arg = wait_for_skill_call(
            recall_id, "episodes", timeout=60, arg_substr=seed_time.strftime("%Y-%m-%d %H:%M"),
        )
        if ep_arg is None:
            calls = find_skill_calls(recall_id, "episodes") or []
            c.fail("episodes invoked",
                   f"no (episodes ...) with seed-time prefix. "
                   f"Got: {[a[:80] for a in calls[:3]]}")
        c.ok("episodes invoked", f"arg={ep_arg!r}")

        c.step("verify recall (send ...) referenced BEACON")
        send_arg = wait_for_skill_call(
            recall_id, "send", timeout=60, arg_substr=beacon_marker,
        )
        if send_arg is None:
            c.fail("recall send",
                   "agent did not reference BEACON in (send ...) after episodes")
        c.ok("recall send", f"reply={send_arg[:80]!r}")

        c.done()
