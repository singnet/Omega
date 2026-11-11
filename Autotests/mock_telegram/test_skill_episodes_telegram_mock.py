"""
Mock variant of test_skill_episodes.

Two-turn flow with mocked LLM:

  1. Seed: agent acknowledges a unique BEACON marker via send.
  2. Recall: after a settle pause, agent invokes (episodes ...) at the
     captured timestamp and sends a reply naming the BEACON.

history.metta is written for real by the agent loop; only the LLM
choice is mocked.

Run:
    pytest test_skill_episodes_mock.py -s
"""
import datetime
import time


from helpers import (
    Checker, find_skill_calls, make_prompt, wait_for_skill_call, wait_for_skill_match,
)
from tg_helpers import tg_send_prompt


def test_skill_episodes_telegram_mock(llm, tg):
    with Checker("episodes skill recall (telegram mock)") as c:
        print(f"\n=== Omega: episodes telegram mock (run-id {c.run_id}) ===",
              flush=True)

        marker = f"BEACON-{c.run_id}"
        c.add_cleanup_marker(marker)

        # ---------- seed turn ----------
        seed_id = c.run_id
        c.step("seed: send a uniquely-marked message and capture timestamp")
        seed_time = datetime.datetime.now()
        seed_prompt = make_prompt(
            seed_id,
            f"Please acknowledge with one short send that you just heard "
            f"the keyword {marker} from me. No need to remember it — just "
            f"reply once.",
        )
        llm.set_answer(seed_prompt, [("send", { "content": f"Acknowledged keyword {marker}." })])
        tg_send_prompt(tg, seed_prompt)
        c.ok("irc-seed", f"run-id={seed_id}, time={seed_time:%H:%M:%S}")

        c.step("seed: wait for agent reply (history records the turn)")
        seed_send = wait_for_skill_call(seed_id, "send", timeout=30)
        if seed_send is None:
            c.fail("seed reply", "agent did not reply to seed within timeout")
        c.ok("seed reply", f"reply={seed_send[:80]!r}")

        c.step("wait 5s so the seed turn is clearly in past history")
        time.sleep(5)
        c.ok("waited", "5s")

        # ---------- recall turn ----------
        recall_id = c.run_id + 1
        c.add_cleanup_marker(str(recall_id))
        c.step("recall: ask agent to use episodes at the seed timestamp")
        time_str = seed_time.strftime("%Y-%m-%d %H:%M")
        recall_prompt = make_prompt(
            recall_id,
            f"Use your `episodes` skill (timestamp lookup, not query) to "
            f"look up what we were discussing around {time_str}, then tell "
            f"me the unique keyword I mentioned then. Reply with one short "
            f"send.",
        )
        llm.set_answer(
            recall_prompt,
            [
                ("episodes", { "timestamp": f"{time_str}" }),
                ("send", { "content": f"The unique keyword was {marker}." }),
            ],
        )
        tg_send_prompt(tg, recall_prompt)
        c.ok("irc-recall", f"run-id={recall_id}")

        c.step("verify agent invoked (episodes ...)")
        ep_arg = wait_for_skill_call(recall_id, "episodes", timeout=30)
        if ep_arg is None:
            c.fail("episodes invoked", "no (episodes ...) call within timeout")
        c.ok("episodes invoked", f"arg={ep_arg[:80]!r}")

        c.step("verify agent's send surfaces the seed marker")

        def has_marker(s):
            low = s.lower()
            return marker.lower() in low or "beacon" in low

        send_arg = wait_for_skill_match(
            recall_id, "send", has_marker, timeout=30,
        )
        if send_arg is None:
            sends = find_skill_calls(recall_id, "send") or []
            last = sends[-1] if sends else "<none>"
            c.fail("send mentions marker",
                   f"no send referenced {marker!r}. "
                   f"Got {len(sends)} send(s), last: {last!r}")
        c.ok("send mentions marker", f"reply={send_arg[:120]!r}")

        c.done()
