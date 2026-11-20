"""
Mock variant of test_skill_query.

Two-turn flow with mocked LLM:

  1. Seed: agent stores "My favorite color is azure-{run_id}." via remember.
  2. Recall: agent invokes (query ...) and sends back a reply naming
     the colour.

ChromaDB is real; only the LLM dispatch is mocked.

Run:
    pytest test_skill_query_mock.py -s
"""
import time


from helpers import (
    Checker, find_skill_calls, make_prompt, wait_for_skill_call, wait_for_skill_match,
)
from tg_helpers import tg_send_prompt


def test_skill_query_telegram_mock(llm, tg):
    with Checker("query skill recall (telegram mock)") as c:
        print(f"\n=== Omega: query telegram mock (run-id {c.run_id}) ===",
              flush=True)

        secret_color = f"azure-{c.run_id}"
        c.add_cleanup_marker(secret_color)
        c.add_cleanup_marker(str(c.run_id + 1))

        # ---------- seed turn ----------
        seed_id = c.run_id
        c.step("seed: ask agent to remember a unique color")
        seed_prompt = make_prompt(
            seed_id,
            f"Please use your `remember` skill to store this exact fact "
            f"verbatim: 'My favorite color is {secret_color}.' Acknowledge "
            f"with one short send.",
        )
        llm.set_answer(
            seed_prompt,
            [
                ("remember", { "content": f"My favorite color is {secret_color}." }),
                ("send", { "content": f"Stored: favorite colour is {secret_color}." }),
            ],
        )
        tg_send_prompt(tg, seed_prompt)
        c.ok("irc-seed", f"run-id={seed_id}")

        c.step("seed: verify (remember ...) carries the secret color")

        def has_color(arg):
            return secret_color.lower() in arg.lower()

        remember_arg = wait_for_skill_match(
            seed_id, "remember", has_color, timeout=30,
        )
        if remember_arg is None:
            calls = find_skill_calls(seed_id, "remember") or []
            c.fail("remember planted",
                   f"no (remember ...) carrying {secret_color!r}. "
                   f"Got: {[a[:80] for a in calls[:3]]}")
        c.ok("remember planted", f"len={len(remember_arg)}")

        c.step("wait 5s for memory to settle")
        time.sleep(5)

        # ---------- recall turn ----------
        recall_id = c.run_id + 1
        c.step("recall: ask agent to look up the color via query skill")
        recall_prompt = make_prompt(
            recall_id,
            "Earlier I told you my favorite color. Use your `query` skill "
            "(short phrase, embedding lookup) to recall it from long-term "
            "memory and tell me the exact color name.",
        )
        llm.set_answer(
            recall_prompt,
            [
                ("query", { "content": "favorite color" }),
                ("send", { "content": f"Your favorite color is {secret_color}." }),
            ],
        )
        tg_send_prompt(tg, recall_prompt)
        c.ok("irc-recall", f"run-id={recall_id}")

        c.step("verify agent invoked (query ...)")
        q_arg = wait_for_skill_call(recall_id, "query", timeout=30)
        if q_arg is None:
            c.fail("query invoked", "no (query ...) call within timeout")
        c.ok("query invoked", f"arg={q_arg[:80]!r}")

        c.step("verify agent sent a reply mentioning the secret color")
        send_arg = wait_for_skill_match(
            recall_id, "send",
            lambda a: secret_color.lower() in a.lower(),
            timeout=30,
        )
        if send_arg is None:
            sends = find_skill_calls(recall_id, "send") or []
            c.fail("send mentions color",
                   f"no send carries {secret_color!r}. "
                   f"Got: {[a[:80] for a in sends[:3]]}")
        c.ok("send mentions color", f"reply={send_arg[:80]!r}")

        c.done()
