"""
Mock variant of test_skill_metta.

The mocked LLM response invokes (metta ...) on a tiny arithmetic
expression and sends back a reply that quotes the result. The metta
skill itself runs for real inside the agent's PeTTa runtime.

Run:
    pytest test_skill_metta_mock.py -s
"""
import re


from helpers import (
    Checker, find_skill_calls, make_prompt, wait_for_skill_call,
)
from tg_helpers import tg_send_prompt


def test_skill_metta_telegram_mock(llm, tg):
    with Checker("metta skill invocation (telegram mock)") as c:
        print(f"\n=== Omega: metta telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.step("send prompt via Telegram with mocked metta + send response")
        prompt = make_prompt(
            c.run_id,
            "Please demonstrate your `metta` skill: pick any short MeTTa "
            "expression you like, evaluate it via the metta skill, and tell "
            "me what it returned. One short reply is enough.",
        )
        # Evaluate (+ 2 2) via metta and report result of 4. The agent's
        # send carries the literal value so the assertion can verify a
        # concrete number is communicated back.
        llm.set_answer(
            prompt,
            [
                ("metta", { "sexpression": "(+ 2 2)" }),
                ("send", { "content": "The metta skill evaluated (+ 2 2) and returned 4." }),
            ],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step("verify agent invoked (metta ...)")
        metta_arg = wait_for_skill_call(c.run_id, "metta", timeout=30)
        if metta_arg is None:
            calls = find_skill_calls(c.run_id, "metta") or []
            c.fail("metta invoked",
                   f"no (metta ...) within timeout. Got: {calls[:2]}")
        c.ok("metta invoked", f"arg={metta_arg[:80]!r}")

        c.step("verify agent then sent a reply that references the result")
        send_arg = wait_for_skill_call(c.run_id, "send", timeout=30)
        if send_arg is None:
            c.fail("send invoked", "agent did not send a reply after metta")
        if not re.search(r"\d", send_arg):
            c.fail("send result",
                   f"reply has no numeric/result reference: {send_arg!r}")
        c.ok("send result", f"reply={send_arg[:120]!r}")

        c.done()
