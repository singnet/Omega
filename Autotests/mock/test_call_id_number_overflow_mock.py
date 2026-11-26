import time

from helpers import Checker, make_prompt
from request_log import docker_logs, exists, request_after, wait_for


def run_turn(llm, comm, c, label, answer):
    token = f"{c.run_id}{label}"
    prompt = make_prompt(c.run_id, f"Turn {token} please proceed.")
    llm.set_answer(prompt, answer)
    if not comm.send_message(prompt):
        c.fail("comm", f"could not deliver the {label} prompt within 60s")
    request = wait_for(lambda: request_after(token))
    if request is None:
        c.fail(f"{label} processed", "the mock LLM got no request after the one carrying the prompt")
    return request


def wait_exists(path, timeout=25):
    deadline = time.time() + timeout
    while not exists(path) and time.time() < deadline:
        time.sleep(1)
    return exists(path)


def test_call_id_number_overflow_turn_survives_mock(llm, comm):
    with Checker("a float-shaped call id does not lose the whole turn (mock)") as c:
        print(f"\n=== Omega: call id float_overflow (run-id {c.run_id}) ===", flush=True)
        c.total = 3
        control = f"/tmp/qa608-did-ctl-{c.run_id}"
        marker = f"/tmp/qa608-did-{c.run_id}"
        c.add_cleanup_dir(control)
        c.add_cleanup_dir(marker)

        c.step("prove the agent acts with a plain write-file call")
        run_turn(llm, comm, c, "ctl", [("write-file", {"filename": control, "content": "ok"})])
        if not wait_exists(control):
            c.fail("agent can write", f"control write-file could not create {control}")
        c.ok("agent can write", control)

        c.step("return a write-file call whose id is 1e999")
        run_turn(llm, comm, c, "fid",
                 [("write-file", {"filename": marker, "content": "x"}, "1e999")])
        overflow = any("float_overflow" in b for b in docker_logs())
        print(f"       float_overflow in log: {overflow}", flush=True)

        c.step("the call must still run (its marker must appear)")
        if not wait_exists(marker, timeout=25):
            c.fail("float id turn processed",
                   f"{marker} absent: the whole turn was dropped (float_overflow={overflow})")
        c.ok("float id turn processed", marker)
        c.done()
