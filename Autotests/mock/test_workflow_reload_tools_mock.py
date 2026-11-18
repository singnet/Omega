import re
import subprocess
import time
from collections import Counter

from helpers import CONTAINER, Checker, make_prompt

WORKFLOW = "test-workflow"
WORKFLOW_SKILL = "test-skill"
VALID_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def docker_logs():
    res = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, text=True, errors="replace")
    return ((res.stdout or "") + (res.stderr or "")).split("\n")


def request_after(tag):
    lines = docker_logs()
    first = next((i for i, l in enumerate(lines) if "REQUEST:" in l and tag in l), None)
    if first is None:
        return None
    return next((l for l in lines[first + 1:] if "REQUEST:" in l), None)


def wait_request_after(tag, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        request = request_after(tag)
        if request is not None:
            return request
        time.sleep(2)
    return None


def tool_names(request):
    return re.findall(r"LLMTool\[name='([^']*)'", request)


def tool_names_after(tag, timeout=30):
    request = wait_request_after(tag, timeout)
    if request is None:
        return None
    return tool_names(request)


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


def test_workflow_reload_tools_mock(llm, comm):
    with Checker("Reloading a workflow does not duplicate tools (mock)") as c:
        print(f"\n=== Omega: workflow reload tools (run-id {c.run_id}) ===", flush=True)
        ids = [c.run_id + n for n in range(8)]
        for run_id in ids:
            c.add_cleanup_marker(str(run_id))
        loaded = False

        def turn(run_id, task, calls, needle):
            _flush(comm)
            prompt = make_prompt(run_id, task)
            llm.set_answer(prompt, calls)
            if not comm.send_message(prompt):
                c.fail(f"comm-{run_id}", "could not deliver the prompt within 60s")
            msg = _recv_contains(comm, needle, timeout=60)
            if msg is None:
                c.fail(f"turn-{run_id}", f"the channel never got {needle!r}")
            time.sleep(5)
            return msg

        def load(run_id):
            nonlocal loaded
            loaded = True
            turn(run_id, f"Load the {WORKFLOW} instructions.",
                 [("workflow-load-instructions", {"workflow_name": WORKFLOW})],
                 f"Loaded workflow: {WORKFLOW}")

        def unload(run_id):
            nonlocal loaded
            turn(run_id, "The workflow is done, unload it now.",
                 [("workflow-unload-instructions", {})],
                 f"Unloaded workflow: {WORKFLOW}")
            loaded = False

        c.step("start without an active workflow")
        _flush(comm)
        prompt = make_prompt(ids[6], "Unload the active workflow if there is one.")
        llm.set_answer(prompt, [("workflow-unload-instructions", {})])
        if not comm.send_message(prompt):
            c.fail("comm-clean", "could not deliver the prompt within 60s")
        _recv_contains(comm, "Unloaded workflow:", timeout=15)
        time.sleep(5)
        _flush(comm)
        c.ok("clean start", "no active workflow")

        try:
            c.step("load the workflow and read the tools of the next request")
            load(ids[0])
            first = tool_names_after(f"REQ-{ids[0]}")
            if first is None:
                c.fail("first tools", "no REQUEST line after the load turn")
            assert first is not None
            if not first:
                c.fail("first tools", "the request carries no tools")
            invalid = [name for name in first if not VALID_TOOL_NAME.match(name)]
            if invalid:
                c.fail("tool names", f"names outside {VALID_TOOL_NAME.pattern}: {invalid}")
            counts = Counter(first)
            if counts[WORKFLOW_SKILL] != 1:
                c.fail("first tools", f"{WORKFLOW_SKILL} appears {counts[WORKFLOW_SKILL]} times in {first}")
            c.ok("first tools", f"{len(first)} tools, {WORKFLOW_SKILL} once")

            c.step("unload the workflow and read the tools of the next request")
            unload(ids[1])
            second = tool_names_after(f"REQ-{ids[1]}")
            if second is None:
                c.fail("tools after unload", "no REQUEST line after the unload turn")
            assert second is not None
            if WORKFLOW_SKILL in second:
                c.fail("tools after unload", f"{WORKFLOW_SKILL} is still in {second}")
            c.ok("tools after unload", f"{len(second)} tools, no {WORKFLOW_SKILL}")

            c.step("load the workflow again and read the tools of the next request")
            load(ids[2])
            third = tool_names_after(f"REQ-{ids[2]}")
            if third is None:
                c.fail("tools after reload", "no REQUEST line after the second load turn")
            assert third is not None
            if WORKFLOW_SKILL not in third:
                c.fail("tools after reload", f"{WORKFLOW_SKILL} is missing from {third}")
            if set(third) != set(first):
                c.fail("tools after reload",
                       f"first load only {sorted(set(first) - set(third))}, "
                       f"reload only {sorted(set(third) - set(first))}")
            c.ok("tools after reload", f"{len(third)} tools, same names as after the first load")

            c.step("load the workflow once more without unloading it")
            _flush(comm)
            prompt = make_prompt(ids[7], f"Load the {WORKFLOW} instructions once more.")
            llm.set_answer(prompt, [("workflow-load-instructions", {"workflow_name": WORKFLOW})])
            if not comm.send_message(prompt):
                c.fail(f"comm-{ids[7]}", "could not deliver the prompt within 60s")
            request = wait_request_after(f"REQ-{ids[7]}", timeout=60)
            if request is None:
                c.fail("double load", "no REQUEST line after the double load turn")
            assert request is not None
            if f"There is an active workflow: {WORKFLOW}" not in request:
                c.fail("double load", "the second load was not rejected")
            doubled = tool_names(request)
            if Counter(doubled)[WORKFLOW_SKILL] != 1:
                c.fail("double load",
                       f"{WORKFLOW_SKILL} appears {Counter(doubled)[WORKFLOW_SKILL]} times in {doubled}")
            time.sleep(5)
            _flush(comm)
            c.ok("double load", f"rejected, {WORKFLOW_SKILL} once")

            c.step("one more turn, the tools of the last request")
            turn(ids[3], "Say that the workflow is ready.",
                 [("send", {"content": f"ready {c.run_id}"})], f"ready {c.run_id}")
            last = tool_names_after(f"REQ-{ids[3]}")
            if last is None:
                c.fail("last tools", "no REQUEST line after the last turn")
            assert last is not None
            if set(last) != set(first):
                c.fail("last tools", f"{sorted(set(last) ^ set(first))} differ from the first load")
            c.ok("last tools", f"{len(last)} tools, same names as after the first load")

            c.step("every name appears once in all five requests")
            for label, names in (("first", first), ("second", second), ("third", third),
                                 ("double", doubled), ("last", last)):
                duplicates = {name: n for name, n in Counter(names).items() if n > 1}
                if duplicates:
                    c.fail("unique names", f"the {label} request repeats {duplicates}")
            c.ok("unique names", "first, second, third, double, last")

            c.step("unload the workflow so that the next tests start clean")
            unload(ids[4])
            c.ok("workflow unloaded", WORKFLOW)
        finally:
            if loaded:
                try:
                    unload(ids[5])
                except BaseException:
                    pass
        c.done()
