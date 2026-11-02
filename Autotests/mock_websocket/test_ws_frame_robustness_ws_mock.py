"""
WebSocket frame robustness: malformed / non-JSON / unknown-type / error frames
are dropped without crashing the channel; a following valid prompt is answered.

Run:
    pytest test_ws_frame_robustness_ws_mock.py -s
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


def test_ws_frame_robustness_ws_mock(llm, ws):
    with Checker("ws frame robustness") as c:
        print(f"\n=== Omega: ws frame robustness (run-id {c.run_id}) ===", flush=True)

        c.step("wait for agent WebSocket connection")
        if not ws.wait_for_connection(timeout=60):
            c.fail("connection", "agent did not connect to the mock WS server")
        c.ok("connection")
        ws.clear()

        c.step("send malformed / non-JSON / unknown / error frames")
        ws.inject_raw("this is not json <<<{")
        ws.inject_raw(json.dumps({"type": "user_message", "seq": "not-an-int", "text": 123}))
        ws.inject_raw(json.dumps({"type": "totally_unknown_type", "foo": 1}))
        ws.inject_raw(json.dumps({"type": "error", "code": "E_TEST", "message": "boom"}))
        ws.inject_raw(json.dumps(["not", "a", "dict"]))
        time.sleep(2)
        c.ok("bad frames sent", "5 malformed/invalid frames delivered")

        c.step("channel survives: connection still open")
        if not ws.wait_for_connection(timeout=5):
            c.fail("survived", "agent connection dropped after bad frames")
        c.ok("survived", "connection still open")

        c.step("a following valid prompt is answered")
        answer = f"WS-ALIVE-{c.run_id}"
        prompt = make_prompt(c.run_id, f"Reply with the send skill: {answer}")
        llm.set_answer(prompt, [("send", { "content": f"{answer}" })])
        ws.inject_user_message(prompt)
        client_seq, text = _wait_for_reply(ws, answer, WAIT)
        if text is None:
            c.fail("recovery", f"no reply containing {answer!r} within {WAIT}s after bad frames")
        c.ok("recovery", f"client_seq={client_seq} text={text!r}")

        c.done()
