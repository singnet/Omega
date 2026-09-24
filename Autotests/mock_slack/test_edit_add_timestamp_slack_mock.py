"""
Mock variant of test_edit_add_timestamp.

The host harness pre-creates note.txt with the initial line. The mocked
LLM response uses (shell ...) to append a real ISO-8601 timestamp via
`date -Iseconds`, so the resulting last line carries a genuine
timestamp produced inside the container at test time.

Run:
    pytest test_edit_add_timestamp_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, make_prompt, wait_for_file,
)
from slack_helpers import sl_send_prompt

TARGET_DIR = "/tmp/test_edit_ts"
TARGET_FILE = "/tmp/test_edit_ts/note.txt"
INITIAL_CONTENT = "This is a test note.\n"


def test_edit_add_timestamp_slack_mock(llm, sl):
    with Checker("edit add timestamp (slack mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: add timestamp slack mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        c.step("pre-create file")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("sh", "-c", f"echo -n '{INITIAL_CONTENT}' > {TARGET_FILE}")
        dexec_root("chmod", "777", TARGET_DIR)
        dexec_root("chmod", "666", TARGET_FILE)
        if dexec("cat", TARGET_FILE).returncode != 0:
            c.fail("pre-create", f"could not create {TARGET_FILE}")
        c.ok("pre-create")

        precreate_mtime = int(dexec("stat", "-c", "%Y", TARGET_FILE).stdout.strip())
        time.sleep(2)

        c.step("send prompt via Slack with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Add the current timestamp to the file {TARGET_FILE}. "
            "Append it as a new line at the end of the file.",
        )
        # Use shell to append a real timestamp produced by the container.
        # The mock could equally write a fixed string, but a live `date`
        # exercises append-vs-overwrite semantics in the same shape as the
        # real test.
        llm.set_answer(
            prompt,
            [("shell", { "cmd": f"date -Iseconds >> {TARGET_FILE}" })],
        )
        sl_send_prompt(sl, prompt)
        c.ok("slack", f"run-id={c.run_id}")

        c.step(f"wait for {TARGET_FILE} to be modified")
        mtime = wait_for_file(TARGET_FILE, precreate_mtime + 1, timeout=30)
        if mtime is None:
            c.fail("file modified", f"{TARGET_FILE} not modified within timeout")
        c.ok("file modified", f"mtime={mtime}")

        c.step("check last line contains timestamp")
        content = dexec("cat", TARGET_FILE).stdout
        lines = content.strip().split("\n")
        if len(lines) < 2:
            c.fail("timestamp", f"expected at least 2 lines, got {len(lines)}")
        last_line = lines[-1]
        has_digits = sum(ch.isdigit() for ch in last_line) >= 4
        if not has_digits:
            c.fail("timestamp", f"last line has no timestamp-like data: {repr(last_line)}")
        c.ok("timestamp", repr(last_line))

        c.done()
