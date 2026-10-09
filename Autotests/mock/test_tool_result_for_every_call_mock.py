import re
import subprocess
import time

from helpers import CONTAINER, Checker, make_prompt, wait_for_skill_call


def docker_logs():
    res = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, text=True)
    return ((res.stdout or "") + (res.stderr or "")).split("\n")


def request_after(tag):
    lines = docker_logs()
    first = next((i for i, l in enumerate(lines) if "REQUEST:" in l and tag in l), None)
    if first is None:
        return None
    return next((l for l in lines[first + 1:] if "REQUEST:" in l), None)


def test_tool_result_for_every_call_mock(llm, comm):
    with Checker("Every tool call gets a result in the next request (mock)") as c:
        print(f"\n=== Omega: tool result for every call (run-id {c.run_id}) ===", flush=True)
        missing = f"/tmp/omega-missing-{c.run_id}.txt"
        prompt = make_prompt(c.run_id, f"Read the file {missing}, then say done.")
        llm.set_answer(prompt, [
            ("read-file", {"filename": missing}),
            ("send", {"content": f"done {c.run_id}"}),
        ])

        c.step("send the prompt")
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver the prompt within 60s")
        c.ok("comm", f"run-id={c.run_id}")

        c.step("wait for the send")
        if wait_for_skill_call(c.run_id, "send", timeout=60) is None:
            c.fail("send fired", "the agent did not run the send after read-file")
        c.ok("send fired")

        c.step("read the next request")
        deadline = time.time() + 30
        request = None
        while request is None and time.time() < deadline:
            time.sleep(2)
            request = request_after(f"REQ-{c.run_id}")
        if request is None:
            c.fail("next request", "no REQUEST line after the one carrying the prompt")
        calls = re.findall(r"LLMToolCall\[id='([^']*)',name='([^']*)'", request)
        results = dict((callid, content) for content, callid in re.findall(
            r"LLMToolCallResponseMessage\[role='tool',content=(.*?),callid='([^']*)'\]", request))
        if [name for _, name in calls] != ["read-file", "send"]:
            c.fail("assistant calls", f"expected the read-file and send calls of the answer, got {calls}")
        c.ok("assistant calls", f"{calls}")
        if sorted(results) != sorted(callid for callid, _ in calls):
            c.fail("one result per call", f"calls {calls}, tool results {results}")
        c.ok("one result per call", f"{sorted(results)}")
        read_id, send_id = calls[0][0], calls[1][0]
        if "SUCCESS, RETURN" not in results[send_id]:
            c.fail("send result", f"the send result is not its own: {results[send_id]}")
        c.ok("send result", results[send_id])
        if "no value" not in results[read_id].lower():
            c.fail("read-file result", f"the missing result is not reported: {results[read_id]}")
        c.ok("read-file result", results[read_id])
        c.done()
