"""
Mock test: explicit transition working-memory -> long-term memory.

Turn 1: the agent pins a checklist into working memory.
Turn 2: the agent is asked to commit the pin to long-term memory via
        the remember skill.

Verification: both skill calls landed, and the ChromaDB vector count
grew by exactly one — i.e., the working-memory item was promoted to
the persistent embedding store.

Run:
    pytest test_transition_pin_to_remember_mock.py -s
"""
import subprocess
import time

from helpers import (
    CHROMA_SQLITE, CONTAINER, Checker, find_skill_calls, make_prompt,
    send_prompt, wait_for_skill_call,
)


def chromadb_vector_count():
    py = (
        "import sqlite3;"
        f"c=sqlite3.connect('{CHROMA_SQLITE}');"
        "print(c.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0])"
    )
    res = subprocess.run(
        ["docker", "exec", CONTAINER, "python3", "-c", py],
        capture_output=True, text=True,
    )
    try:
        return int(res.stdout.strip())
    except ValueError:
        return None


def test_transition_pin_to_remember_mock(llm, comm):
    with Checker("pin -> remember transition (mock)") as c:
        print(f"\n=== Omega: pin->remember transition (run-id {c.run_id}) ===",
              flush=True)

        marker = f"candidate-set-{c.run_id}"
        c.add_cleanup_marker(marker)
        c.add_cleanup_marker(str(c.run_id + 1))

        # ---------- turn 1: pin ----------
        c.step("turn 1: pin three candidates")
        prompt1 = make_prompt(
            c.run_id,
            f"I have three release-name candidates I want you to track in "
            f"working memory: A, B, C. Tag the set as '{marker}'. Use the "
            f"pin skill and acknowledge with a short send.",
        )
        llm.set_answer(
            prompt1,
            [("pin", { "message": f"{marker}: candidates A, B, C" }),
             ("send", { "content": f"Pinned {marker}: A, B, C." })]
        )
        if not comm.send_message(prompt1):
            c.fail("comm-1", "could not deliver turn 1 prompt within 60s")
        c.ok("comm-1", f"run-id={c.run_id}")

        pin_arg = wait_for_skill_call(
            c.run_id, "pin", timeout=60, arg_substr=marker,
        )
        if pin_arg is None:
            calls = find_skill_calls(c.run_id, "pin") or []
            c.fail("pin invoked",
                   f"no (pin ...) with {marker!r}. "
                   f"Got: {[a[:60] for a in calls[:3]]}")
        c.ok("pin invoked", f"arg={pin_arg[:80]!r}")

        count_before = chromadb_vector_count()
        if count_before is None:
            c.fail("chromadb", "cannot read vector count")
        c.ok("chromadb before", f"{count_before} vectors")

        # ---------- turn 2: commit pin to long-term ----------
        recall_id = c.run_id + 1
        c.step("turn 2: ask the agent to commit the pin to long-term memory")
        time.sleep(5)
        prompt2 = make_prompt(
            recall_id,
            f"The pin tagged '{marker}' I gave you in the previous turn is "
            f"important — please commit it to long-term memory now using "
            f"the remember skill. Acknowledge with a short send.",
        )
        llm.set_answer(
            prompt2,
            [("remember", { "content": f"{marker}: candidates A, B, C" }),
             ("send", { "content": f"Committed {marker} to long-term memory." })]
        )
        if not comm.send_message(prompt2):
            c.fail("comm-2", "could not deliver turn 2 prompt within 60s")
        c.ok("comm-2", f"run-id={recall_id}")

        c.step("verify remember was invoked with the same marker")
        rem_arg = wait_for_skill_call(
            recall_id, "remember", timeout=60, arg_substr=marker,
        )
        if rem_arg is None:
            calls = find_skill_calls(recall_id, "remember") or []
            c.fail("remember invoked",
                   f"no (remember ...) with {marker!r}. "
                   f"Got: {[a[:60] for a in calls[:3]]}")
        c.ok("remember invoked", f"arg={rem_arg[:80]!r}")

        c.step("verify ChromaDB grew by 1 (working memory promoted)")
        deadline = time.time() + 60
        count_after = count_before
        while time.time() < deadline:
            count_after = chromadb_vector_count()
            if count_after is not None and count_after > count_before:
                break
            time.sleep(2)
        if count_after is None or count_after <= count_before:
            c.fail("chromadb grew",
                   f"vector count stayed at {count_before} (is {count_after})")
        c.ok("chromadb grew",
             f"{count_before} -> {count_after} "
             f"(+{count_after - count_before}, expected +1)")

        c.done()
