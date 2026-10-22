"""
Mock variant of test_search_weather.

Same scoping note as the other search mocks: the LLM dispatch is
mocked, the search skill is not. To keep the mock variant
deterministic and offline the test fixes a synthetic reference
temperature instead of querying open-meteo (the live test still
exercises the real cross-check).

Run:
    pytest test_search_weather_mock.py -s
"""
import re

from helpers import (
    Checker, find_skill_calls, make_prompt, wait_for_skill_match,
)
from tg_helpers import tg_send_prompt

REF_TEMP_C = 18.0


def test_search_weather_telegram_mock(llm, tg):
    with Checker("search weather valencia (telegram mock)") as c:
        print(f"\n=== Omega: Valencia weather telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.step("send prompt via Telegram with mocked send response")
        prompt = make_prompt(
            c.run_id,
            "What's the weather in Valencia Spain today? "
            "Search the web and tell me temperature in Celsius.",
        )
        mocked_reply = (
            f"Current weather in Valencia, Spain: about {REF_TEMP_C:.1f}°C."
        )
        llm.set_answer(prompt, [("send", { "content": f"{mocked_reply}" })])
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step("verify (send ...) carries a plausible Celsius temperature")

        def has_plausible_temp(s):
            return any(-20 <= float(n) <= 50
                       for n in re.findall(r"-?\d+(?:\.\d+)?", s))

        send_arg = wait_for_skill_match(
            c.run_id, "send", has_plausible_temp, timeout=30,
        )
        if send_arg is None:
            all_sends = find_skill_calls(c.run_id, "send") or []
            last = all_sends[-1] if all_sends else "<none>"
            c.fail("send with temp", f"no send with plausible temp. Last: {last!r}")
        c.ok("send invoked", f"{len(send_arg)} chars")

        c.step(f"cross-check temperature against synthetic ref {REF_TEMP_C}°C (±10°C)")
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", send_arg)
                if -20 <= float(n) <= 50]
        in_range = [n for n in nums if abs(n - REF_TEMP_C) <= 10]
        if not in_range:
            c.fail("cross-check",
                   f"agent temps {nums} vs reference {REF_TEMP_C}°C")
        c.ok("cross-check", f"{in_range} within ±10°C of {REF_TEMP_C}°C")

        c.done()
