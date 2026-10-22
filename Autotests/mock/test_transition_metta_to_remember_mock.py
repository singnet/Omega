"""
Mock test: Tier-3 -> Tier-2 transition. A reasoning conclusion produced
inside an AtomSpace via (metta ...) is ephemeral by design; if the agent
wants to keep it, it must call (remember ...) on the conclusion.

Turn 1 mock answer dictates a metta inference call AND a remember call
with the conclusion. Verification confirms both fired and the ChromaDB
vector count grew by one.

Run:
    pytest test_transition_metta_to_remember_mock.py -s
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


def test_transition_metta_to_remember_mock(llm, comm):
    with Checker("metta reasoning -> remember (mock)") as c:
        print(f"\n=== Omega: metta->remember (run-id {c.run_id}) ===",
              flush=True)

        conclusion_marker = f"conclusion-{c.run_id}"
        c.add_cleanup_marker(conclusion_marker)

        count_before = chromadb_vector_count()
        if count_before is None:
            c.fail("chromadb", "cannot read vector count")
        c.ok("chromadb before", f"{count_before} vectors")

        c.step("send reasoning prompt; mock answers with (metta ...) + (remember ...)")
        prompt = make_prompt(
            c.run_id,
            f"Premises: 'Sam and Garfield are friends', and "
            f"'Garfield is an animal'. Use the metta skill to combine them "
            f"with NAL inheritance, then commit the conclusion to long-term "
            f"memory tagged '{conclusion_marker}'.",
        )
        metta_call = (
            "(|- ((--> sam friend) (stv 1.0 0.9)) "
            "((--> garfield animal) (stv 1.0 0.9)))"
        )
        remember_call = (
            f"{conclusion_marker}: Sam is friend of an animal "
            "(derived via NAL inheritance)."
        )
        llm.set_answer(
            prompt,
            [
                ("metta", { "sexpression": metta_call }),
                ("remember", { "content": remember_call }),
                ("send", { "content": "Reasoned and remembered." })
            ]
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within 60s")
        c.ok("comm", f"run-id={c.run_id}")

        c.step("verify (metta ...) was invoked")
        metta_arg = wait_for_skill_call(c.run_id, "metta", timeout=60)
        if metta_arg is None:
            c.fail("metta invoked", "no (metta ...) call observed")
        c.ok("metta invoked", f"arg={metta_arg[:80]!r}")

        c.step("verify (remember ...) was invoked with conclusion marker")
        rem_arg = wait_for_skill_call(
            c.run_id, "remember", timeout=60, arg_substr=conclusion_marker,
        )
        if rem_arg is None:
            calls = find_skill_calls(c.run_id, "remember") or []
            c.fail("remember invoked",
                   f"no (remember ...) with {conclusion_marker!r}. "
                   f"Got: {[a[:60] for a in calls[:3]]}")
        c.ok("remember invoked", f"arg={rem_arg[:80]!r}")

        c.step("verify ChromaDB grew by 1 (conclusion persisted)")
        deadline = time.time() + 60
        count_after = count_before
        while time.time() < deadline:
            count_after = chromadb_vector_count()
            if count_after is not None and count_after > count_before:
                break
            time.sleep(2)
        if count_after is None or count_after <= count_before:
            c.fail("chromadb grew",
                   f"vector count stayed {count_before} (is {count_after}) — "
                   f"metta conclusion was not actually persisted")
        c.ok("chromadb grew",
             f"{count_before} -> {count_after} "
             f"(+{count_after - count_before}, expected +1)")

        c.done()
