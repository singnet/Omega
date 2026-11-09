"""
Test: Omega creates hello.txt with content "Hello" in /tmp/testcat.

Run:
    pytest test_create_file.py -s
"""
import time


from helpers import (
    Checker, dexec, make_prompt, wait_for_file,
)
from slack_helpers import sl_send_prompt

TARGET_DIR = "/tmp/testcat"
TARGET_FILE = "/tmp/testcat/hello.txt"
WAIT = 30


def test_hello_file_slack_mock(llm, sl):
    with Checker("create hello.txt", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega smoke test (run-id {c.run_id}) ===", flush=True)

        c.verify_clean()

        start_ts = int(time.time()) - 1

        c.step("connect to IRC and send prompt")
        prompt = make_prompt(
            c.run_id,
            f"Please overwrite {TARGET_FILE} so it contains exactly the single "
            "word Hello (no quotes, no extra newlines, create the directory if needed).",
        )
        llm.set_answer(prompt, [
            ("shell", { "cmd": "mkdir -p /tmp/testcat" }),
            ("write-file", { "filename": "/tmp/testcat/hello.txt", "content": "Hello" }),
        ])

        sl_send_prompt(sl, prompt)
        c.ok("slack", f"prompt delivered, run-id={c.run_id}")

        c.step(f"wait for {TARGET_FILE} (timeout {WAIT}s)")
        file_mtime = wait_for_file(TARGET_FILE, start_ts, timeout=WAIT)
        if file_mtime is None:
            c.fail("file created", f"{TARGET_FILE} not created within {WAIT}s")
        c.ok("file created", f"after {file_mtime - start_ts}s")

        c.step("check testcat exists in /tmp")
        if dexec("test", "-d", TARGET_DIR).returncode != 0:
            c.fail("dir exists", f"{TARGET_DIR} missing")
        c.ok("dir exists")

        c.step("check hello.txt exists in testcat")
        if dexec("test", "-f", TARGET_FILE).returncode != 0:
            c.fail("file exists", f"{TARGET_FILE} missing")
        c.ok("file exists")

        c.step("check mtime newer than test start")
        dir_mtime = int(dexec("stat", "-c", "%Y", TARGET_DIR).stdout.strip())
        if dir_mtime < start_ts:
            c.fail("dir mtime", f"{dir_mtime} < {start_ts}")
        if file_mtime < start_ts:
            c.fail("file mtime", f"{file_mtime} < {start_ts}")
        c.ok("mtime", f"start={start_ts} dir={dir_mtime} file={file_mtime}")

        c.step("check file permissions")
        perms = dexec("stat", "-c", "%A", TARGET_FILE).stdout.strip()
        if not perms.startswith("-rw"):
            c.fail("permissions", perms)
        c.ok("permissions", perms)

        c.step("check file content")
        content = dexec("cat", TARGET_FILE).stdout
        if content not in ("Hello", "Hello\n"):
            c.fail("content", repr(content))
        c.ok("content", repr(content))

        c.done()
