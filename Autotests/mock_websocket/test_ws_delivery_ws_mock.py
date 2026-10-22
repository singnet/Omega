"""
WebSocket delivery round-trip: a user_message reaches the agent, the agent
replies with a valid agent_message (uuid client_seq), the mock acks it.

Run:
    pytest test_ws_delivery_ws_mock.py -s
"""
import uuid

from helpers import Checker, make_prompt
from ws_helpers import ws_send_prompt

WAIT = 30


def _is_uuid_hex(value):
    try:
        uuid.UUID(hex=str(value))
        return True
    except (ValueError, TypeError):
        return False


def _wait_for_reply(ws, needle, timeout):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        client_seq, text = ws.pop_agent_reply(timeout=max(1, int(deadline - time.time())))
        if text is None:
            break
        if needle in text:
            return client_seq, text
    return None, None


def test_ws_delivery_ws_mock(llm, ws):
    with Checker("ws delivery round-trip") as c:
        print(f"\n=== Omega: ws delivery (run-id {c.run_id}) ===", flush=True)

        c.step("wait for agent WebSocket connection")
        if not ws.wait_for_connection(timeout=60):
            c.fail("connection", "agent did not connect to the mock WS server")
        c.ok("connection")
        ws.clear()

        c.step("register answer and inject user_message")
        answer = f"WS-PONG-{c.run_id}"
        prompt = make_prompt(c.run_id, f"Reply with exactly this token using the send skill: {answer}")
        llm.set_answer(prompt, [("send", { "content": f"{answer}" })])
        ws_send_prompt(ws, prompt)
        c.ok("injected", f"run-id={c.run_id}")

        c.step("wait for agent_message with our token")
        client_seq, text = _wait_for_reply(ws, answer, WAIT)
        if text is None:
            c.fail("agent_message", f"no reply containing {answer!r} within {WAIT}s")
        c.ok("agent_message", f"text={text!r}")

        c.step("check client_seq is a valid uuid hex")
        if not _is_uuid_hex(client_seq):
            c.fail("client_seq", f"not a uuid hex: {client_seq!r}")
        c.ok("client_seq", client_seq)

        c.step("check mock acked the agent_message")
        if client_seq not in ws._acks:
            c.fail("ack", f"{client_seq} not in acked set {ws._acks}")
        c.ok("ack", f"acked client_seq={client_seq}")

        c.done()
