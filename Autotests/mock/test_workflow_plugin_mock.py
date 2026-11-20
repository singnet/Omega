"""
Mock tests for the workflow plugin.

The workflow plugin lets skills be added via MarkDown workflows under
plugins/workflow/instructions/<name>/ (SKILL.md + optional skill.metta). These
tests drive shipped workflows with a mocked LLM, so only the plugin machinery
is exercised: the LLM decision is scripted, the skills run for real inside the
agent and their output is observed on the test comm channel.

  - load + skill: load test-workflow, then run its workflow-only skill
                  test-skill (defined in
                  plugins/workflow/instructions/test-workflow/skill.metta).
                  test-skill is callable only after the workflow is loaded, so
                  its message reaching the channel proves a MarkDown-defined
                  skill is registered and executed.
  - unload:       load test-workflow, unload it, then confirm the
                  workflow-only skill no longer runs.
  - research-workflow: load research-workflow and run its research-start
                  skill; the confirmation on the channel and the project tree
                  written under the memory volume prove a second MarkDown
                  workflow works end to end.

Run:
    pytest test_workflow_plugin_mock.py -s
"""
import time

from helpers import Checker, dexec, make_prompt

WORKFLOW = "test-workflow"
WORKFLOW_SKILL = "test-skill"
DEMO_MESSAGE = "This is a test workflow demonstration"

RESEARCH_WORKFLOW = "research-workflow"
RESEARCH_DIR = "/PeTTa/repos/Omega/memory/workflow_space/research"
RESEARCH_NAME = "qa-research-autotest"


def _flush(comm):
    """Drop any messages left in the shared queue by earlier turns/tests."""
    while comm.getLastMessage():
        pass


def _recv_contains(comm, needle, timeout=60):
    """Poll the comm channel until the agent sends a message containing needle.
    Returns the matching message, or None on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = comm.getLastMessage()
        if msg:
            if needle in msg:
                return msg
            continue
        time.sleep(0.5)
    return None


class TestWorkflowPlugin:

    def test_load_and_skill(self, llm, comm):
        with Checker("workflow load + skill (mock)") as c:
            print(f"\n=== Omega: workflow load + skill (run-id {c.run_id}) ===",
                  flush=True)
            c.add_cleanup_marker(str(c.run_id))
            c.add_cleanup_marker(str(c.run_id + 1))
            _flush(comm)

            # ---------- turn 1: load the workflow ----------
            c.step("turn 1: load the test-workflow")
            prompt1 = make_prompt(
                c.run_id,
                "Demonstrate the workflow plugin: load the test-workflow "
                "instructions.",
            )
            llm.set_answer(prompt1,
                [("workflow-load-instructions", { "workflow_name": f"{WORKFLOW}" })]
            )
            if not comm.send_message(prompt1):
                c.fail("comm-1", "could not deliver turn 1 prompt within 60s")
            loaded = _recv_contains(comm, f"Loaded workflow: {WORKFLOW}", timeout=60)
            if loaded is None:
                c.fail("workflow loaded",
                       f"agent never confirmed loading {WORKFLOW}")
            c.ok("workflow loaded", f"{loaded[:80]!r}")

            # ---------- turn 2: run the workflow-registered skill ----------
            skill_id = c.run_id + 1
            c.step("turn 2: call the workflow-registered test-skill")
            time.sleep(5)
            prompt2 = make_prompt(skill_id, "Continue the workflow: perform step 1.")
            llm.set_answer(
                prompt2,
                [(f"{WORKFLOW_SKILL}", { "message": f"{DEMO_MESSAGE}" }),
                ("workflow-unload-instructions", {})]
            )
            if not comm.send_message(prompt2):
                c.fail("comm-2", "could not deliver turn 2 prompt within 60s")
            echoed = _recv_contains(comm, DEMO_MESSAGE, timeout=60)
            if echoed is None:
                c.fail("test-skill executed",
                       f"{WORKFLOW_SKILL} did not deliver its message; the "
                       "workflow skill was not registered/executed")
            c.ok("test-skill executed", f"{echoed[:80]!r}")

            c.done()

    def test_unload_removes_skill(self, llm, comm):
        # Verifies unload behaviourally: after unloading, the workflow-only
        # skill is gone and no longer produces output. This does not depend on
        # the unload confirmation message.
        with Checker("workflow unload removes its skill (mock)") as c:
            print(f"\n=== Omega: workflow unload (run-id {c.run_id}) ===",
                  flush=True)
            c.add_cleanup_marker(str(c.run_id))
            c.add_cleanup_marker(str(c.run_id + 1))
            c.add_cleanup_marker(str(c.run_id + 2))
            _flush(comm)

            c.step("turn 1: load the test-workflow")
            prompt1 = make_prompt(c.run_id, "Load the test-workflow instructions.")
            llm.set_answer(prompt1, [("workflow-load-instructions", { "workflow_name": f"{WORKFLOW}" })])
            if not comm.send_message(prompt1):
                c.fail("comm-1", "could not deliver turn 1 prompt within 60s")
            if _recv_contains(comm, f"Loaded workflow: {WORKFLOW}", timeout=60) is None:
                c.fail("workflow loaded", "workflow was not loaded, cannot test unload")
            c.ok("workflow loaded", WORKFLOW)

            c.step("turn 2: unload the active workflow")
            unload_id = c.run_id + 1
            time.sleep(5)
            prompt2 = make_prompt(unload_id, "The workflow is done, unload it now.")
            llm.set_answer(prompt2, [("workflow-unload-instructions", {})])
            if not comm.send_message(prompt2):
                c.fail("comm-2", "could not deliver turn 2 prompt within 60s")
            time.sleep(12)   # let the unload turn complete
            _flush(comm)     # drop anything emitted by the unload turn
            c.ok("unload requested", "workflow-unload-instructions sent")

            c.step("turn 3: the workflow-only skill must no longer run")
            gone_id = c.run_id + 2
            marker = f"gone-{c.run_id}"
            time.sleep(2)
            prompt3 = make_prompt(gone_id, "Please run the workflow step again.")
            llm.set_answer(prompt3, [(f"{WORKFLOW_SKILL}", { "message": f"{marker}" })])
            if not comm.send_message(prompt3):
                c.fail("comm-3", "could not deliver turn 3 prompt within 60s")
            still = _recv_contains(comm, marker, timeout=25)
            if still is not None:
                c.fail("skill removed",
                       f"{WORKFLOW_SKILL} still executed after unload: {still[:80]!r}")
            c.ok("skill removed", f"{WORKFLOW_SKILL} no longer runs after unload")

            c.done()

    def test_research_workflow(self, llm, comm):
        project = f"{RESEARCH_DIR}/{RESEARCH_NAME}"
        with Checker("research-workflow start (mock)", cleanup_dirs=[project]) as c:
            print(f"\n=== Omega: research-workflow (run-id {c.run_id}) ===",
                  flush=True)
            c.add_cleanup_marker(str(c.run_id))
            c.add_cleanup_marker(str(c.run_id + 1))
            _flush(comm)

            c.step("turn 1: load research-workflow")
            prompt1 = make_prompt(c.run_id, f"Load the {RESEARCH_WORKFLOW} instructions.")
            llm.set_answer(prompt1, [("workflow-load-instructions", { "workflow_name": f"{RESEARCH_WORKFLOW}" })])
            if not comm.send_message(prompt1):
                c.fail("comm-1", "could not deliver turn 1 prompt within 60s")
            if _recv_contains(comm, f"Loaded workflow: {RESEARCH_WORKFLOW}", timeout=60) is None:
                c.fail("workflow loaded", f"{RESEARCH_WORKFLOW} was not loaded")
            c.ok("workflow loaded", RESEARCH_WORKFLOW)

            c.step("turn 2: research-start creates the project")
            start_id = c.run_id + 1
            topic = f"iris via mock {c.run_id}"
            time.sleep(5)
            prompt2 = make_prompt(start_id, "Start the research project.")
            llm.set_answer(prompt2, [("research-start", {
                "research_name": f"{RESEARCH_NAME}",
                "topic": f"{topic}"
            })])
            if not comm.send_message(prompt2):
                c.fail("comm-2", "could not deliver turn 2 prompt within 60s")
            created = _recv_contains(comm, "Created project:", timeout=60)
            if created is None:
                c.fail("research-start ran", "research-start did not confirm creation")
            c.ok("research-start ran", f"{created[:80]!r}")

            c.step("verify the project tree and topic.txt exist on disk")
            got = None
            deadline = time.time() + 20
            while time.time() < deadline:
                res = dexec("cat", f"{project}/topic.txt")
                if res.returncode == 0 and res.stdout.strip() == topic:
                    got = res.stdout.strip()
                    break
                time.sleep(1)
            if got is None:
                c.fail("topic.txt", f"{project}/topic.txt missing or wrong content")
            c.ok("topic.txt", f"{got!r}")
            for sub in ("src", "data", "runs", "figures"):
                if dexec("test", "-d", f"{project}/{sub}").returncode != 0:
                    c.fail("project dirs", f"{sub}/ not created")
            c.ok("project dirs", "src/ data/ runs/ figures/ present")

            c.done()
