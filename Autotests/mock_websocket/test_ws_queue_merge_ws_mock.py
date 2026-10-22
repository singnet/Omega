"""
WebSocket queue merge: three user_message frames queued before the agent
drains are joined as "A | B | C" into one LLM input; last_seen_seq ends at 3.

Run:
    pytest test_ws_queue_merge_ws_mock.py -s
"""
import time

from helpers import Checker, make_prompt


WAIT = 40


def _wait_for_reply(ws, needle, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        client_seq, text = ws.pop_agent_reply(timeout=max(1, int(deadline - time.time())))
        if text is None:
            break
        if needle in text:
            return client_seq, text
    return None, None


def test_ws_queue_merge_ws_mock(llm, ws):
    with Checker("ws queue merge A | B | C") as c:
        print(f"\n=== Omega: ws queue merge (run-id {c.run_id}) ===", flush=True)

        c.step("wait for agent WebSocket connection")
        if not ws.wait_for_connection(timeout=60):
            c.fail("connection", "agent did not connect to the mock WS server")
        c.ok("connection")
        ws.clear()

        c.step("register merged answer and inject three user_messages back-to-back")
        answer = f"WS-MERGED-{c.run_id}"
        p1 = make_prompt(c.run_id, "fragment ALPHA")
        p2 = make_prompt(c.run_id, "fragment BRAVO")
        p3 = make_prompt(c.run_id, "fragment CHARLIE")
        joined = " | ".join([p1, p2, p3])
        llm.set_answer(joined, [("send", { "content": f"{answer}" })])
        s1 = ws.inject_user_message(p1)
        s2 = ws.inject_user_message(p2)
        s3 = ws.inject_user_message(p3)
        if not (s2 == s1 + 1 and s3 == s2 + 1):
            c.fail("seq assignment", f"expected contiguous seq, got {s1}/{s2}/{s3}")
        c.ok("injected", f"seq {s1}/{s2}/{s3}")

        c.step("wait for the single merged agent_message")
        client_seq, text = _wait_for_reply(ws, answer, WAIT)
        if text is None:
            c.fail(
                "merged reply",
                f"no reply for the joined 'A | B | C' input within {WAIT}s "
                "(the three frames were not merged into one LLM input)",
            )
        c.ok("merged reply", f"text={text!r}")

        c.step("force reconnect and read resume last_seen_seq")
        base = ws.resume_count()
        ws.drop_connection()
        last_seen = ws.wait_for_resume(min_count=base + 1, timeout=30)
        if last_seen != s3:
            c.fail("last_seen_seq", f"expected {s3} (last of the merged batch), resume carried {last_seen!r}")
        c.ok("last_seen_seq", f"resume carried last_seen_seq={s3}")

        c.done()
