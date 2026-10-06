"""
Mock variant of test_edit_delete_line.

The harness pre-creates a 3-line file. The mocked LLM response uses
sed to delete the second line in place, preserving lines 1 and 3.

Run:
    pytest test_edit_delete_line_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, make_prompt, wait_for_file,
)
from slack_helpers import sl_send_prompt

TARGET_DIR = "/tmp/test_edit_del"
TARGET_FILE = "/tmp/test_edit_del/data.txt"
LINE1 = "First line"
LINE2 = "Second line"
LINE3 = "Third line"


def test_edit_delete_line_slack_mock(llm, sl):
    with Checker("edit delete line (slack mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: delete second line slack mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        c.step("pre-create file with 3 lines")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("sh", "-c",
                   f'printf "%s\\n%s\\n%s\\n" "{LINE1}" "{LINE2}" "{LINE3}" > {TARGET_FILE}')
        dexec_root("chmod", "777", TARGET_DIR)
        dexec_root("chmod", "666", TARGET_FILE)
        content_before = dexec("cat", TARGET_FILE).stdout
        if LINE2 not in content_before:
            c.fail("pre-create", "file does not contain expected lines")
        c.ok("pre-create", f"{len(content_before.strip().splitlines())} lines")

        precreate_mtime = int(dexec("stat", "-c", "%Y", TARGET_FILE).stdout.strip())
        time.sleep(2)

        c.step("send prompt via Slack with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Delete the second line from the file {TARGET_FILE}. "
            "The file currently has 3 lines. Remove only the second line, "
            "keep the first and third lines intact.",
        )
        llm.set_answer(
            prompt,
            [("shell", { "cmd": f"sed -i 2d {TARGET_FILE}" })],
        )
        sl_send_prompt(sl, prompt)
        c.ok("slack", f"run-id={c.run_id}")

        c.step(f"wait for {TARGET_FILE} to be modified")
        mtime = wait_for_file(TARGET_FILE, precreate_mtime + 1, timeout=30)
        if mtime is None:
            c.fail("file modified", f"{TARGET_FILE} not modified within timeout")
        c.ok("file modified", f"after {mtime - precreate_mtime}s")

        c.step("check line count is 2")
        content = dexec("cat", TARGET_FILE).stdout
        lines = [l for l in content.strip().split("\n") if l]
        if len(lines) != 2:
            c.fail("line count", f"expected 2 lines, got {len(lines)}: {repr(content)}")
        c.ok("line count", f"{len(lines)} lines")

        c.step("check second line is removed, first and third remain")
        if LINE1 not in lines[0]:
            c.fail("content", f"first line mismatch: {repr(lines[0])}")
        if LINE3 not in lines[1]:
            c.fail("content", f"third line mismatch: {repr(lines[1])}")
        if LINE2 in content:
            c.fail("content", "second line still present")
        c.ok("content", f"[{repr(lines[0])}, {repr(lines[1])}]")

        c.done()
