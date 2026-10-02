"""
Mock variant of test_search_basic.

Note on scope: the live test exercises both the search skill (network)
and the agent's ability to relay project-specific content. Under the
mock we control only the LLM dispatch вЂ” the search skill itself still
hits the network. To keep the mock variant deterministic and free of
network dependencies, the mocked response skips the search call and
delivers the answer directly via (send ...). This narrows the test to
content-relay verification; the live variant remains the source of
truth for end-to-end search behaviour.

Run:
    pytest test_search_basic_mock.py -s
"""

from helpers import (
    Checker, find_skill_calls, make_prompt, wait_for_history_keyword,
)
from slack_helpers import sl_send_prompt


SINGULARITYNET_DESCRIPTION = (
    "SingularityNet (SNET) is a decentralized AI marketplace founded by "
    "Ben Goertzel. Its native token AGIX powers a network of AI agents "
    "and services, and it is part of the broader ASI Alliance ecosystem."
)


def test_search_basic_slack_mock(llm, sl):
    with Checker("search singularitynet (slack mock)") as c:
        print(f"\n=== Omega: basic search slack mock (run-id {c.run_id}) ===",
              flush=True)

        c.step("send prompt via Slack with mocked send response")
        prompt = make_prompt(
            c.run_id,
            "What is SingularityNet? Search the web and give me a short description.",
        )
        llm.set_answer(prompt, [("send", { "content": f"{SINGULARITYNET_DESCRIPTION}" })])
        sl_send_prompt(sl, prompt)
        c.ok("slack", f"run-id={c.run_id}")

        c.step("verify (send ...) contains project-specific keywords")
        send_matched = wait_for_history_keyword(
            c.run_id,
            ["singularitynet", "singularity net", "singularitynet.io",
             "agix", "snet", "goertzel", "ben goertzel",
             "ai marketplace", "decentralized ai"],
            timeout=30,
        )
        if send_matched is None:
            sends = find_skill_calls(c.run_id, "send") or []
            last = sends[-1] if sends else "<none>"
            c.fail(
                "send content",
                f"no project-specific keyword in send. Last: {last!r}",
            )
        c.ok("send content", f"matched: {', '.join(send_matched[:4])}")

        c.done()
