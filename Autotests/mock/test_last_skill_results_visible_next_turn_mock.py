"""
Mock test: results of skill calls in turn N are exposed to the LLM at
turn N+1 via the LAST_SKILL_USE_RESULTS section of the assembled prompt.
This is a one-iteration carry that lets the agent reference the output
of (metta ...), (query ...), (shell ...) etc. without persisting it.

Turn 1 mock answer dictates a metta computation. We then read the
docker log to find the REQUEST line for the NEXT iteration and
confirm it contains the last tool call results marker.

Run:
    pytest test_last_skill_results_visible_next_turn_mock.py -s
"""
import subprocess
import time

from helpers import (
    CONTAINER, Checker, make_prompt, send_prompt, wait_for_skill_call,
)


def docker_logs():
    res = subprocess.run(
        ["docker", "logs", CONTAINER],
        capture_output=True, text=True,
    )
    return (res.stdout or "") + (res.stderr or "")


def test_last_skill_results_visible_next_turn_mock(llm, comm):
    with Checker("LAST_SKILL_USE_RESULTS carries to next iteration (mock)") as c:
        print(f"\n=== Omega: lastresults carry (run-id {c.run_id}) ===",
              flush=True)

        sentinel = f"UNIQ{c.run_id}"  # appears in the metta expression
        c.add_cleanup_marker(sentinel)

        # ---------- turn 1: produce a value via metta ----------
        c.step("turn 1: ask the agent to evaluate a metta expression")
        prompt1 = make_prompt(
            c.run_id,
            f"Use the metta skill to evaluate the s-expression "
            f"(+ {c.run_id} 1). Then acknowledge with a short send.",
        )
        # Mock answer uses the sentinel inside metta so we can locate it in
        # the next iteration's LAST_SKILL_USE_RESULTS.
        llm.set_answer(
            prompt1,
            [
                ("metta", { "sexpression": f"(quote {sentinel})" }),
                ("send", { "content": "computed" })
            ]
        )
        if not comm.send_message(prompt1):
            c.fail("comm-1", "could not deliver turn 1 prompt within 60s")
        c.ok("comm-1", f"run-id={c.run_id}")

        c.step("verify (metta ...) was invoked")
        metta_arg = wait_for_skill_call(
            c.run_id, "metta", timeout=60, arg_substr=sentinel,
        )
        if metta_arg is None:
            c.fail("metta invoked",
                   f"no (metta ...) with sentinel {sentinel!r}")
        c.ok("metta invoked", f"arg={metta_arg!r}")

        send_arg = wait_for_skill_call(c.run_id, "send", timeout=60)
        if send_arg is None:
            c.fail("send fired", "agent did not acknowledge")
        c.ok("send fired", f"reply={send_arg[:60]!r}")

        c.step("wait for the agent to start a fresh iteration")
        time.sleep(20)

        c.step("verify next iteration's REQUEST contains tool call results with sentinel")
        logs = docker_logs()
        # We look for any REQUEST line after our metta call that carries
        # the sentinel inside the tool call results section.
        chars_sent_lines = [
            ln for ln in logs.split("\n")
            if "REQUEST:" in ln and "[TOOL CALL]" in ln
        ]
        relevant = [
            ln for ln in chars_sent_lines
            if sentinel in ln
        ]
        if not relevant:
            c.fail("sentinel in lastresults",
                   f"no REQUEST line carries {sentinel!r} in "
                   f"tool call results. Total REQUEST lines "
                   f"checked: {len(chars_sent_lines)}")
        c.ok("sentinel in lastresults",
             f"found in {len(relevant)} subsequent iteration prompt(s)")

        deprecated_instruction = "you must rectify ALERT_FAILED skill use cases"
        if any(deprecated_instruction in ln for ln in relevant):
            c.fail("no unconditional failure instruction",
                   f"found deprecated prompt text: {deprecated_instruction!r}")
        c.ok("no unconditional failure instruction",
             "tool call results contains feedback without failure guidance")

        c.done()
