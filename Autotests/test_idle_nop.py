import re
import subprocess
import time
from collections import Counter

from helpers import CONTAINER, Checker, make_prompt, send_prompt

IDLE_ITERATIONS = 20
MAX_QUERIES = 10
ANSWER_TIMEOUT = 300
IDLE_TIMEOUT = 600

LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \| \w+\s*\| (\S+) \| (.*)$")
ITERATION = re.compile(r"^\(---------iteration (\d+)\)$")
CALL = re.compile(r"LLMToolCall\[id='[^']*',name='([^']*)',arguments=(.*?),error=")
IDLE_MARKER = "[NO NEW USER INPUT."


def docker_logs():
    res = subprocess.run(["docker", "logs", CONTAINER], capture_output=True,
                         text=True, errors="replace")
    return (res.stdout or "") + (res.stderr or "")


def parse_iterations(text):
    iterations = []
    current = None
    for raw in text.split("\n"):
        m = LINE.match(raw)
        if not m or m.group(1) != "loop":
            continue
        msg = m.group(2)
        if ITERATION.match(msg):
            current = {"idle": None, "message": "", "calls": [], "responses": 0}
            iterations.append(current)
        elif current is None:
            continue
        elif current["idle"] is None and not msg.startswith("("):
            current["idle"] = IDLE_MARKER in msg
            current["message"] = msg
        elif msg.startswith("(RESPONSE: LLMResponse["):
            current["responses"] += 1
            current["calls"].extend(CALL.findall(msg))
    return iterations


def locate(iterations, run_id):
    question = next((i for i, it in enumerate(iterations)
                     if it["idle"] is False and str(run_id) in it["message"]), None)
    if question is None:
        return None, None
    answer = next((i for i in range(question, len(iterations))
                   if any(name == "send" and str(run_id) in args
                          for name, args in iterations[i]["calls"])), None)
    return question, answer


def idle_window(iterations, answer):
    return [it for it in iterations[answer + 1:] if it["idle"] is True and it["responses"] > 0]


def test_idle_nop():
    with Checker("The agent idles with nop instead of looping on query") as c:
        print(f"\n=== Omega: idle nop (run-id {c.run_id}) ===", flush=True)

        c.step("send a question that needs one short answer")
        prompt = make_prompt(
            c.run_id,
            f"What is the capital of France? Answer in one short sentence "
            f"that also contains the number {c.run_id}.",
        )
        if not send_prompt(prompt):
            c.fail("irc", "could not deliver prompt within 60s")
        c.ok("irc", f"run-id={c.run_id}")

        c.step("wait for the iteration that answers with send")
        deadline = time.time() + ANSWER_TIMEOUT
        iterations = []
        answer = None
        while time.time() < deadline:
            iterations = parse_iterations(docker_logs())
            _, answer = locate(iterations, c.run_id)
            if answer is not None:
                break
            time.sleep(5)
        if answer is None:
            c.fail("answer", f"no send with run-id {c.run_id} within {ANSWER_TIMEOUT}s")
        c.ok("answer", f"iteration index {answer}")

        c.step(f"wait for {IDLE_ITERATIONS} idle iterations after the answer")
        deadline = time.time() + IDLE_TIMEOUT
        window = []
        while time.time() < deadline:
            iterations = parse_iterations(docker_logs())
            _, answer = locate(iterations, c.run_id)
            window = idle_window(iterations, answer)
            if len(window) >= IDLE_ITERATIONS:
                break
            time.sleep(5)
        if len(window) < IDLE_ITERATIONS:
            c.fail("idle window", f"{len(window)} idle iterations in {IDLE_TIMEOUT}s")
        c.ok("idle window", f"{IDLE_ITERATIONS} idle iterations")
        window = window[:IDLE_ITERATIONS]
        calls = Counter(name for it in window for name, _ in it["calls"])
        empty = sum(1 for it in window if not it["calls"])
        sends = [args for it in window for name, args in it["calls"] if name == "send"]
        answer_sends = [args for name, args in iterations[answer]["calls"] if name == "send"]
        repeats = len(sends + answer_sends) - len(set(sends + answer_sends))
        summary = (f"iterations={len(window)} query={calls['query']} nop={calls['nop']} "
                   f"send={calls['send']} other="
                   f"{ {k: v for k, v in calls.items() if k not in ('query', 'nop', 'send')} } "
                   f"empty={empty} repeated_send={repeats}")
        print(f"       {summary}", flush=True)

        c.step("nop is called at least once in the window")
        if calls["nop"] < 1:
            c.fail("nop", f"nop was never called; {summary}")
        c.ok("nop", f"{calls['nop']} calls")

        c.step(f"query is called at most {MAX_QUERIES} times in the window")
        if calls["query"] > MAX_QUERIES:
            c.fail("query", f"{calls['query']} query calls exceed {MAX_QUERIES}; {summary}")
        c.ok("query", f"{calls['query']} calls")

        c.step("the agent does not repeat its answer to the channel")
        if repeats:
            c.fail("repeated send", f"{repeats} repeated send calls; {summary}")
        c.ok("repeated send", "none")

        c.done()
