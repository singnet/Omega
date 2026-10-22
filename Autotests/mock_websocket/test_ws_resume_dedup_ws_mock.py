"""
WebSocket resume + dedup: after a forced reconnect the agent sends resume with
the advanced last_seen_seq; a frame with seq <= last_seen_seq is dropped by the
agent's dedup. The dedup is isolated from the send-level &lastsend guard by
replaying a distinct text under an already-seen seq: if the frame were not
deduped it would produce a new, non-suppressed answer.

Run:
    pytest test_ws_resume_dedup_ws_mock.py -s
"""
import json
import time

from helpers import Checker, make_prompt


WAIT = 30


def _wait_for_reply(ws, needle, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        client_seq, text = ws.pop_agent_reply(timeout=max(1, int(deadline - time.time())))
        if text is None:
            break
        if needle in text:
            return client_seq, text
    return None, None


def test_ws_resume_dedup_ws_mock(llm, ws):
    with Checker("ws resume + dedup") as c:
        print(f"\n=== Omega: ws resume dedup (run-id {c.run_id}) ===", flush=True)

        c.step("wait for agent WebSocket connection")
        if not ws.wait_for_connection(timeout=60):
            c.fail("connection", "agent did not connect to the mock WS server")
        c.ok("connection")
        ws.clear()

        c.step("deliver one prompt and get the single reply")
        answer = f"WS-ONCE-{c.run_id}"
        prompt = make_prompt(c.run_id, f"Reply once with the send skill: {answer}")
        llm.set_answer(prompt, [("send", { "content": f"{answer}" })])
        seq = ws.inject_user_message(prompt)
        client_seq, text = _wait_for_reply(ws, answer, WAIT)
        if text is None:
            c.fail("first reply", f"no reply containing {answer!r} within {WAIT}s")
        c.ok("first reply", f"seq={seq} client_seq={client_seq}")
        ws.clear()

        c.step("register a distinct answer for a poisoned replay at the seen seq")
        poison = f"WS-POISON-{c.run_id}"
        poison_prompt = make_prompt(c.run_id, f"Poisoned replay must be dropped: {poison}")
        llm.set_answer(poison_prompt, [("send", { "content": f"{poison}" })])
        c.ok("poison registered")

        c.step("force reconnect; agent must resume with the advanced last_seen_seq")
        base = ws.resume_count()
        ws.drop_connection()
        last_seen = ws.wait_for_resume(min_count=base + 1, timeout=30)
        if last_seen != seq:
            c.fail("resume last_seen_seq", f"expected {seq}, resume carried {last_seen!r}")
        c.ok("resume last_seen_seq", f"resume carried last_seen_seq={seq}")

        c.step("replay a distinct text under the already-seen seq; dedup must drop it")
        if not ws.wait_for_connection(timeout=30):
            c.fail("reconnect", "agent did not reconnect after drop")
        ws.inject_raw(json.dumps({"type": "user_message", "seq": seq, "text": poison_prompt}))
        extras = ws.drain_agent_replies(max_wait=WAIT // 3 or 5)
        leaked = [t for _, t in extras if t and (poison in t or answer in t)]
        if leaked:
            c.fail(
                "dedup",
                f"agent processed a frame with seq={seq} <= last_seen_seq={seq}: {leaked}",
            )
        c.ok("dedup", "replayed / poisoned frame at seen seq was dropped")

        c.done()
