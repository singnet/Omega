import re
import subprocess
import time

from helpers import CONTAINER, Checker, make_prompt

IDLE_MESSAGE = "[NO NEW USER INPUT. CONTINUE AUTONOMOUS WORK. DO NOT REPEAT THE PREVIOUS RESPONSE. ONLY USE send FOR GENUINELY NEW INFORMATION OR WHEN USER INPUT IS NEEDED.]"
NO_ANSWER = "Mock doesn't have answer for"


def docker_logs(since):
    res = subprocess.run(["docker", "logs", "--since", f"{since:.3f}", CONTAINER],
                         capture_output=True, text=True, errors="replace")
    return ((res.stdout or "") + (res.stderr or "")).split("\n")


def _flush(comm):
    while comm.getLastMessage():
        pass


def _recv_contains(comm, needle, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = comm.getLastMessage()
        if msg:
            if needle in msg:
                return msg
            continue
        time.sleep(0.5)
    return None


def nop_request(lines):
    for line in lines:
        if "REQUEST:" not in line:
            continue
        call = re.search(r"LLMToolCall\[id='([^']*)',name='nop'", line)
        if call is None:
            continue
        result = re.search(
            r"LLMToolCallResponseMessage\[role='tool',content=(.*?),callid='"
            + re.escape(call.group(1)) + r"'\]", line)
        if result is not None:
            return line, result.group(1)
    return None


def test_idle_nop_mock(llm, comm):
    with Checker("The nop tool works on an idle turn (mock)") as c:
        print(f"\n=== Omega: idle nop (run-id {c.run_id}) ===", flush=True)
        c.add_cleanup_marker(str(c.run_id))
        answer_set = False
        cleared = True
        try:
            c.step("an ordinary turn, so that the next iterations are idle")
            _flush(comm)
            prompt = make_prompt(c.run_id, "Say that you are ready.")
            llm.set_answer(prompt, [("send", {"content": f"ready {c.run_id}"})])
            if not comm.send_message(prompt):
                c.fail("comm", "could not deliver the prompt within 60s")
            if _recv_contains(comm, f"ready {c.run_id}", timeout=60) is None:
                c.fail("ordinary turn", "the agent did not answer the ordinary turn")
            c.ok("ordinary turn", f"run-id={c.run_id}")

            c.step("answer the idle message with nop")
            time.sleep(5)
            _flush(comm)
            begin = time.time()
            answer_set = True
            if not llm.set_answer(IDLE_MESSAGE, [("nop", {})]):
                c.fail("set answer", "the mock did not take the idle answer")
            c.ok("set answer", "nop")

            c.step("wait for a request carrying the nop result")
            found = None
            deadline = time.time() + 60
            while found is None and time.time() < deadline:
                time.sleep(2)
                found = nop_request(docker_logs(begin))
            if found is None:
                c.fail("nop request", "no request carried a tool result for nop")
            assert found is not None
            request, content = found
            c.ok("nop request", content)

            c.step("nop is among the tools of that request")
            names = re.findall(r"LLMTool\[name='([^']*)'", request)
            if names.count("nop") != 1:
                c.fail("nop tool", f"nop appears {names.count('nop')} times in {names}")
            c.ok("nop tool", f"{len(names)} tools")

            c.step("the nop result is not an error")
            if "Error" in content or "SUCCESS, RETURN" not in content:
                c.fail("nop result", f"unexpected result {content}")
            c.ok("nop result", content)

            c.step("nothing reached the channel while the agent idled with nop")
            time.sleep(5)
            stray = []
            while True:
                msg = comm.getLastMessage()
                if not msg:
                    break
                stray.append(msg)
            if stray:
                c.fail("channel", f"the idle turns sent {stray}")
            c.ok("channel", "no messages")
        finally:
            if answer_set:
                cleared = llm.clear_answer(IDLE_MESSAGE)
        if not cleared:
            c.fail("clear answer", "mock agent did not confirm clear_answer")

        c.step("a new ordinary turn restarts the idle iteration count")
        fresh_id = c.run_id + 1
        c.add_cleanup_marker(str(fresh_id))
        _flush(comm)
        prompt = make_prompt(fresh_id, "Say that you are ready again.")
        llm.set_answer(prompt, [("send", {"content": f"ready again {fresh_id}"})])
        if not comm.send_message(prompt):
            c.fail("comm-again", "could not deliver the prompt within 60s")
        if _recv_contains(comm, f"ready again {fresh_id}", timeout=60) is None:
            c.fail("second ordinary turn", "the agent did not answer the second ordinary turn")
        c.ok("second ordinary turn", f"run-id={fresh_id}")

        c.step("after clear_answer the idle requests have no answer again")
        begin = time.time()
        silent = False
        deadline = time.time() + 60
        while not silent and time.time() < deadline:
            time.sleep(2)
            silent = any(NO_ANSWER in line and "NO NEW USER INPUT" in line
                         for line in docker_logs(begin))
        if not silent:
            c.fail("answer cleared", "the idle requests were still answered after clear_answer")
        c.ok("answer cleared", NO_ANSWER)
        c.done()
