"""
Mock variant of test_create_empty_file.

The agent is fed a deterministic s-exp response that creates the target
directory and an empty file. All artefact assertions remain identical to
the live-LLM version — only the LLM dispatch is mocked.

Run:
    pytest test_create_empty_file_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, make_prompt, wait_for_file,
)
from tg_helpers import tg_send_prompt

TARGET_DIR = "/tmp/test_empty"
TARGET_FILE = "/tmp/test_empty/hello.txt"
WAIT = 30


def test_create_empty_file_telegram_mock(llm, tg):
    with Checker("create empty file (telegram mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: create empty file telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        start_ts = int(time.time()) - 1

        c.step("send prompt via Telegram with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Create file hello.txt in {TARGET_DIR}/ directory "
            "(create the directory if needed). The file can be empty.",
        )
        llm.set_answer(
            prompt,
            [
                ("shell", { "cmd": f"mkdir -p {TARGET_DIR}" }),
                ("write-file", { "filename": f"{TARGET_FILE}", "content": "" }),
            ],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step(f"wait for {TARGET_FILE}")
        mtime = wait_for_file(TARGET_FILE, start_ts, timeout=WAIT)
        if mtime is None:
            c.fail("file created", f"{TARGET_FILE} not created within {WAIT}s")
        c.ok("file created", f"after {mtime - start_ts}s")

        c.step("verify file exists via cat")
        res = dexec("cat", TARGET_FILE)
        if res.returncode != 0:
            c.fail("cat", f"cat failed: {res.stderr.strip()}")
        c.ok("cat", repr(res.stdout))

        c.step("verify file is empty (or only contains a trailing newline)")
        size_res = dexec("stat", "-c", "%s", TARGET_FILE)
        if size_res.returncode != 0:
            c.fail("size check", f"stat failed: {size_res.stderr.strip()}")
        try:
            size = int(size_res.stdout.strip())
        except ValueError:
            c.fail("size check", f"unparseable size: {size_res.stdout!r}")
        if size > 1:
            c.fail(
                "empty content",
                f"file is not empty: {size} bytes, content={res.stdout!r}",
            )
        c.ok("empty content", f"{size} bytes")

        c.done()
