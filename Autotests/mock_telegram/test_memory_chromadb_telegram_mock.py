"""
Mock variant of test_memory_chromadb.

The mocked LLM response invokes (remember "...") with the unique
CI marker. The remember skill itself runs for real: it embeds the
content via the local sentence-transformers model and writes to
ChromaDB. The mock only removes the LLM nondeterminism.

Run:
    pytest test_memory_chromadb_mock.py -s
"""
import subprocess
import time


from helpers import (
    CHROMA_SQLITE, CONTAINER, Checker, find_skill_calls,
    make_prompt, wait_for_skill_call,
)
from tg_helpers import tg_send_prompt


def chromadb_vector_count():
    """Query chroma.sqlite3 via python3 sqlite3 module inside the container."""
    py = (
        "import sqlite3;"
        f"c=sqlite3.connect('{CHROMA_SQLITE}');"
        "print(c.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0])"
    )
    res = subprocess.run(
        ["docker", "exec", CONTAINER, "python3", "-c", py],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    try:
        return int(res.stdout.strip())
    except ValueError:
        return None


def test_memory_chromadb_telegram_mock(llm, tg):
    with Checker("chromadb vector write (telegram mock)") as c:
        print(f"\n=== Omega: chromadb telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.step("count chromadb vectors before")
        count_before = chromadb_vector_count()
        if count_before is None:
            c.fail("chromadb", f"cannot query {CHROMA_SQLITE}")
        c.ok("chromadb before", f"{count_before} vectors")

        c.step("send remember prompt via Telegram with mocked response")
        marker = f"CI-SMOKE-{c.run_id}"
        c.add_cleanup_marker(marker)
        prompt = make_prompt(
            c.run_id,
            f"Please remember this exact fact using the remember skill: "
            f"'Unique smoke marker {marker} was emitted by CI.'",
        )
        llm.set_answer(
            prompt,
            [("remember", { "content": f"Unique smoke marker {marker} was emitted by CI." })],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step("verify agent invoked (remember ...) with our marker")
        arg = wait_for_skill_call(
            c.run_id, "remember", timeout=30, arg_substr=marker,
        )
        if arg is None:
            all_calls = find_skill_calls(c.run_id, "remember") or []
            c.fail(
                "remember invoked",
                f"no (remember ...) with marker {marker}. Got: "
                f"{[a[:80] for a in all_calls[:3]]}",
            )
        c.ok("remember invoked", f"arg contains marker (len={len(arg)})")

        c.step("wait for chromadb vector count to grow")
        deadline = time.time() + 60
        count_after = count_before
        while time.time() < deadline:
            count_after = chromadb_vector_count()
            if count_after is not None and count_after > count_before:
                break
            time.sleep(2)
        if count_after is None or count_after <= count_before:
            c.fail("chromadb grew", f"count stayed {count_before} (is {count_after})")
        c.ok("chromadb grew",
             f"{count_before} -> {count_after} (+{count_after - count_before})")

        c.done()
