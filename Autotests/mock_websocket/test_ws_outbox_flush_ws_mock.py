"""
WebSocket outbox flush: an answer produced while the socket is down is buffered
and delivered after reconnect, exactly once (single client_seq).

The prompt is delivered while connected; the connection is then dropped and
reconnects refused for a short window. The agent drains its inbox and produces
the reply while disconnected, so send_message buffers it in the outbox; on
reconnect the outbox is flushed before any new inbound traffic.

Run:
    pytest test_ws_outbox_flush_ws_mock.py -s
"""
import time

from helpers import Checker, make_prompt


WAIT = 40


def test_ws_outbox_flush_ws_mock(llm, ws):
    with Checker("ws outbox flush after reconnect") as c:
        print(f"\n=== Omega: ws outbox flush (run-id {c.run_id}) ===", flush=True)

        c.step("wait for agent WebSocket connection")
        if not ws.wait_for_connection(timeout=60):
            c.fail("connection", "agent did not connect to the mock WS server")
        c.ok("connection")
        ws.clear()

        c.step("deliver prompt, then drop and refuse reconnects while the agent replies")
        answer = f"WS-BUFFERED-{c.run_id}"
        prompt = make_prompt(c.run_id, f"Reply with the send skill: {answer}")
        llm.set_answer(prompt, [("send", { "content": f"{answer}" })])
        ws.inject_user_message(prompt)
        ws.block_connections()
        c.ok("dropped", "connection dropped, reconnects blocked")

        c.step("hold the outage so the reply is produced while disconnected")
        time.sleep(6)
        ws.unblock_connections()
        c.ok("released", "reconnects allowed again")

        c.step("wait for the buffered agent_message after reconnect")
        if not ws.wait_for_connection(timeout=30):
            c.fail("reconnect", "agent did not reconnect after the outage")
        got = None
        deadline = time.time() + WAIT
        while time.time() < deadline:
            client_seq, text = ws.pop_agent_reply(timeout=max(1, int(deadline - time.time())))
            if text is None:
                break
            if answer in text:
                got = (client_seq, text)
                break
        if got is None:
            c.fail("buffered reply", f"no reply containing {answer!r} within {WAIT}s after reconnect")
        c.ok("buffered reply", f"client_seq={got[0]} text={got[1]!r}")

        c.step("no duplicate delivery of the buffered message")
        extras = ws.drain_agent_replies(max_wait=6)
        dupes = [(cs, t) for cs, t in extras if t and answer in t]
        if dupes:
            c.fail("no duplicate", f"buffered message delivered more than once: {dupes}")
        c.ok("no duplicate", "buffered message delivered exactly once")

        c.done()
