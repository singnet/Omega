"""
Mock variant of test_memory_episode.

Two-turn flow with mocked LLM dispatches:

  1. Seed: agent answers (remember "<fact>") on the vet/Barney prompt.
  2. Recall: agent answers (query "<phrase>") + (send "<reply>") on the
     follow-up. The reply text already contains the date and the
     dog/tooth keywords, so the recall does not depend on the agent's
     ability to compose a natural-language summary from the query
     result.

ChromaDB and history.metta are written for real — only the LLM
choice is mocked.

Run:
    pytest test_memory_episode_mock.py -s
"""
import datetime
import time


from helpers import (
    Checker, find_skill_calls, make_prompt, send_prompt,
    wait_for_skill_call, wait_for_skill_match,
)


def test_memory_episode_mock(llm, comm):
    with Checker("memory episode recall (mock)") as c:
        print(f"\n=== Omega: memory episode mock (run-id {c.run_id}) ===",
              flush=True)

        c.add_cleanup_marker("Barney")
        c.add_cleanup_marker(str(c.run_id + 1))

        # ---------- seed turn ----------
        fact_marker = c.run_id
        seed_time = datetime.datetime.now()
        c.step("seed: send 'dog lost tooth' fact with mocked remember response")
        prompt1 = make_prompt(
            fact_marker,
            "I just got back from the vet with my dog Barney — he lost his "
            "first baby tooth today. Could you jot this down in memory so I "
            "can ask you later? I keep forgetting dates like this.",
        )
        llm.set_answer(
            prompt1,
            [("remember", { "content": f"Barney the dog lost his first baby tooth at the vet today." })]
        )
        if not comm.send_message(prompt1):
            c.fail("comm-1", "could not deliver first prompt within 60s")
        c.ok("comm-1", f"run-id={fact_marker}")

        c.step("verify agent invoked (remember ...) with dog/tooth content")

        def is_barney_memory(s):
            low = s.lower()
            return "tooth" in low or "barney" in low

        remember_arg = wait_for_skill_match(
            fact_marker, "remember", is_barney_memory, timeout=120,
        )
        if remember_arg is None:
            calls = find_skill_calls(fact_marker, "remember") or []
            c.fail(
                "remember invoked",
                f"no (remember ...) with 'tooth' or 'Barney'. "
                f"Got: {[a[:80] for a in calls[:3]]}",
            )
        c.ok("remember invoked", f"arg matched (len={len(remember_arg)})")

        c.step("wait 5s for memory to settle")
        time.sleep(5)

        # ---------- recall turn ----------
        recall_marker = c.run_id + 1
        c.step("recall: ask when the dog lost a tooth, with mocked recall response")
        prompt2 = make_prompt(
            recall_marker,
            "Remember I mentioned my dog Barney losing a tooth earlier? "
            "Could you check your notes and tell me the exact date and time "
            "I told you about it?",
        )
        date_str = seed_time.strftime("%Y-%m-%d")
        recall_reply = (
            f"Barney the dog lost his first baby tooth on {date_str}. "
            "The milestone is recorded in my notes."
        )
        llm.set_answer(
            prompt2,
            [("query", { "content": "Barney tooth" }),
             ("send", { "content": f"{recall_reply}" })]
        )
        if not comm.send_message(prompt2):
            c.fail("comm-2", "could not deliver recall prompt within 60s")
        c.ok("comm-2", f"run-id={recall_marker}")

        c.step("verify agent invoked (query ...) or (episodes ...)")
        q_arg = wait_for_skill_call(recall_marker, "query", timeout=30)
        e_arg = wait_for_skill_call(recall_marker, "episodes", timeout=2)
        if q_arg is None and e_arg is None:
            c.fail("recall invoked",
                   "neither (query ...) nor (episodes ...) called")
        which = "query" if q_arg else "episodes"
        c.ok(f"{which} invoked", f"arg={(q_arg or e_arg)!r}")

        c.step("verify (send ...) mentions dog/tooth and the date")
        send_arg = wait_for_skill_call(recall_marker, "send", timeout=30)
        if send_arg is None:
            c.fail("send invoked", "agent did not send a recall reply")
        topic = [k for k in ("dog", "tooth", "lost") if k in send_arg.lower()]
        if not topic:
            c.fail("send topic", f"reply has no dog/tooth/lost: {send_arg!r}")
        if date_str not in send_arg:
            c.fail("send date",
                   f"date {date_str!r} missing from reply: {send_arg!r}")
        c.ok("send date", f"matched: {date_str}, topic={topic}")

        c.done()
