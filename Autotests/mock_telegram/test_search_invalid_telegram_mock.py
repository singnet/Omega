"""
Mock variant of test_search_invalid.

The live test exercises the agent's behaviour on a gibberish query —
both the search skill call and the agent's "no results" relay. Under
the mock we skip the search skill (it would still hit the network) and
deliver the negation reply directly via (send ...). The mock variant
therefore narrows the assertion to the content of the relay; the live
variant remains the source of truth for end-to-end behaviour.

Run:
    pytest test_search_invalid_mock.py -s
"""

from helpers import (
    Checker, find_skill_calls, make_prompt, wait_for_skill_match,
)
from tg_helpers import tg_send_prompt

GIBBERISH = "dfghjkgkfjghj"


NEGATION_PHRASES = [
    "no results", "not found", "couldn't find", "could not find",
    "no information", "no matches", "no relevant", "unable to find",
    "nothing found", "no meaning", "nonsense", "random",
    "gibberish", "meaningless", "does not appear", "doesn't appear",
    "no data", "no specific", "unknown", "no coherent",
    "no hits", "returned nothing", "returned no",
]


def test_search_invalid_telegram_mock(llm, tg):
    with Checker("search invalid (telegram mock)") as c:
        print(f"\n=== Omega: invalid search telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.step("send prompt via Telegram with mocked negation response")
        prompt = make_prompt(
            c.run_id,
            f"What is {GIBBERISH}? Search the web. "
            "If nothing found, say so explicitly.",
        )
        llm.set_answer(
            prompt,
            [("send", { "content": f"No results found for {GIBBERISH}. The string appears to be gibberish — no meaningful matches." })],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step("verify (send ...) carries a negation phrase")

        def has_negation(s):
            low = s.lower()
            return any(p in low for p in NEGATION_PHRASES)

        send_arg = wait_for_skill_match(
            c.run_id, "send", has_negation, timeout=30,
        )
        if send_arg is None:
            all_sends = find_skill_calls(c.run_id, "send") or []
            last = all_sends[-1] if all_sends else "<none>"
            c.fail(
                "no-results reply",
                f"no negation phrase in any send. Got {len(all_sends)} "
                f"send(s), last: {last!r}",
            )
        matched = [p for p in NEGATION_PHRASES if p in send_arg.lower()]
        c.ok("no-results reply", f"matched: {', '.join(matched[:3])}")

        c.done()
