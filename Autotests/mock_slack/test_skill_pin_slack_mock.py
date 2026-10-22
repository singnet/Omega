"""
Mock variant of test_skill_pin.

The mocked LLM response invokes (pin ...) capturing the alpha/beta/gamma
checklist progress, and sends a short acknowledgement.

Run:
    pytest test_skill_pin_mock.py -s
"""

from helpers import (
    Checker, find_skill_calls, make_prompt, wait_for_skill_call,
    wait_for_skill_match,
)
from slack_helpers import sl_send_prompt

STEP_KEYWORDS = ("step", "alpha", "beta", "gamma", "restart", "server", "done")


def test_skill_pin_slack_mock(llm, sl):
    with Checker("pin skill invocation (slack mock)") as c:
        print(f"\n=== Omega: pin slack mock (run-id {c.run_id}) ===", flush=True)

        c.step("send prompt with mocked pin + send response")
        prompt = make_prompt(
            c.run_id,
            "I'm restarting three servers in order: alpha, beta, gamma. "
            "I just finished restarting alpha. Use the `pin` skill to keep "
            "track of where I am in this checklist so we don't lose state, "
            "and acknowledge with one short send.",
        )
        llm.set_answer(
            prompt,
            [
                ("pin", { "message": "Server restart progress: alpha done; beta and gamma pending." }),
                ("send", { "content": "Tracking: alpha done, beta and gamma pending." })
            ]
        )
        sl_send_prompt(sl, prompt)
        c.ok("slack", f"run-id={c.run_id}")

        c.step("verify agent invoked (pin ...) with task-state content")

        def is_task_state_pin(arg):
            low = arg.lower()
            return any(kw in low for kw in STEP_KEYWORDS) or str(c.run_id) in arg

        pin_arg = wait_for_skill_match(
            c.run_id, "pin", is_task_state_pin, timeout=30,
        )
        if pin_arg is None:
            calls = find_skill_calls(c.run_id, "pin") or []
            c.fail("pin invoked",
                   f"no (pin ...) referencing servers/steps. "
                   f"Got: {[a[:80] for a in calls[:3]]}")
        matched = [kw for kw in STEP_KEYWORDS if kw in pin_arg.lower()]
        c.ok("pin invoked", f"matched={matched}, arg={pin_arg[:80]!r}")

        c.step("verify agent acknowledged via (send ...)")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30)
        if send_arg is None:
            c.fail("send invoked", "agent did not acknowledge via send")
        c.ok("send invoked", f"reply={send_arg[:80]!r}")

        c.done()
