"""
Mock test (negative): a (pin ...) emitted within an iteration is NOT
visible inside the same iteration's HISTORY context. The prompt is
assembled BEFORE skill evaluation, so the pin block — written by
addToHistory at the END of the iteration — only enters HISTORY at the
next prompt-build.

Verification reads the docker log: the REQUEST line that carries
the PROMPT for the iteration containing our pin must NOT contain the
pin's unique marker; the NEXT REQUEST line (next iteration) must.

Run:
    pytest test_pin_invisible_within_iteration_mock.py -s
"""
import subprocess
import time

from helpers import (
    CONTAINER, Checker, find_skill_calls, make_prompt, send_prompt,
    wait_for_skill_call,
)


def docker_logs():
    res = subprocess.run(
        ["docker", "logs", CONTAINER],
        capture_output=True, text=True,
    )
    return (res.stdout or "") + (res.stderr or "")


def chars_sent_lines():
    return [
        ln for ln in docker_logs().split("\n")
        if "REQUEST:" in ln
    ]


def test_pin_invisible_within_iteration_mock(llm, comm):
    with Checker("pin not visible inside its own iteration (mock)") as c:
        print(f"\n=== Omega: pin within-iteration (run-id {c.run_id}) ===",
              flush=True)

        marker = f"XENO-{c.run_id}"
        c.add_cleanup_marker(marker)

        baseline_count = len(chars_sent_lines())
        c.ok("docker log baseline", f"{baseline_count} REQUEST lines so far")

        c.step("send a prompt; mock answers with (pin ...) + (send ...)")
        # IMPORTANT: marker must NOT appear in HUMAN_MESSAGE. Otherwise it
        # ends up in REQUEST for the current iteration via the prompt
        # body itself, defeating the within-iteration visibility check.
        # We ask the agent to "track progress with a short code"; the mock
        # answer supplies the actual marker only inside (pin ...).
        prompt = make_prompt(
            c.run_id,
            "Pin a short progress code for the current task. "
            "Then acknowledge with one short send.",
        )
        llm.set_answer(
            prompt,
            [("pin", { "message": f"{marker}" })]
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within 60s")
        c.ok("comm", f"run-id={c.run_id}")

        c.step("verify (pin ...) was actually invoked with the marker")
        pin_arg = wait_for_skill_call(
            c.run_id, "pin", timeout=60, arg_substr=marker,
        )
        if pin_arg is None:
            calls = find_skill_calls(c.run_id, "pin") or []
            c.fail("pin invoked",
                   f"no (pin ...) with {marker!r}. "
                   f"Got: {[a[:60] for a in calls[:3]]}")
        c.ok("pin invoked", f"arg={pin_arg[:80]!r}")

        c.step("wait so the next iteration definitely starts and logs its PROMPT")
        time.sleep(30)

        c.step("split REQUEST lines into before-pin and after-pin")
        all_lines = chars_sent_lines()
        # Find the iteration that received our HUMAN_MESSAGE (it carries
        # REQ-{run_id} in the prompt).
        owning_idx = None
        for i, ln in enumerate(all_lines):
            if f"REQ-{c.run_id}" in ln:
                owning_idx = i
                break
        if owning_idx is None:
            c.fail("locate iteration",
                   f"no REQUEST line carries REQ-{c.run_id} — "
                   f"prompt never reached agent loop")
        c.ok("locate iteration",
             f"PROMPT carrying our REQ at log index {owning_idx} "
             f"(of {len(all_lines)} total)")

        c.step(
            "verify the PROMPT that triggered our pin does NOT contain the marker "
            "(prompt was built BEFORE pin was evaluated)"
        )
        own_prompt = all_lines[owning_idx]
        if marker in own_prompt:
            c.fail(
                "pin absent in own prompt",
                f"marker {marker!r} found inside the very PROMPT that triggered "
                f"the pin — build-before-eval semantics is broken",
            )
        c.ok("pin absent in own prompt",
             f"marker not in own iteration's PROMPT — as expected")

        c.step(
            "verify SOME later REQUEST line DOES carry the marker "
            "(pin became visible on a subsequent iteration)"
        )
        later_hits = [
            i for i, ln in enumerate(all_lines)
            if i > owning_idx and marker in ln
        ]
        if not later_hits:
            c.fail(
                "pin appears later",
                f"no later REQUEST contains {marker!r}; pin did not propagate "
                f"to subsequent HISTORY",
            )
        c.ok("pin appears later",
             f"marker found in subsequent PROMPT at indices {later_hits[:3]}")

        c.done()
