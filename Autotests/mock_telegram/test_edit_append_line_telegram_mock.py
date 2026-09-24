"""
Mock variant of test_edit_append_line.

The harness pre-creates a 3-line file. The mocked LLM response appends
exactly one line ("Delta") via shell, leaving the original three lines
unchanged.

Run:
    pytest test_edit_append_line_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, make_prompt, wait_for_file,
)
from tg_helpers import tg_send_prompt

TARGET_DIR = "/tmp/test_edit_append"
TARGET_FILE = "/tmp/test_edit_append/data.txt"
LINE1 = "Alpha"
LINE2 = "Bravo"
LINE3 = "Charlie"
LINE4_EXPECTED = "Delta"


def test_edit_append_line_telegram_mock(llm, tg):
    with Checker("edit append line (telegram mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: append line telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        c.step("pre-create file with 3 lines")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("sh", "-c",
                   f'printf "%s\\n%s\\n%s\\n" "{LINE1}" "{LINE2}" "{LINE3}" > {TARGET_FILE}')
        dexec_root("chmod", "777", TARGET_DIR)
        dexec_root("chmod", "666", TARGET_FILE)
        if dexec("cat", TARGET_FILE).returncode != 0:
            c.fail("pre-create", "could not create file")
        c.ok("pre-create")

        precreate_mtime = int(dexec("stat", "-c", "%Y", TARGET_FILE).stdout.strip())
        time.sleep(2)

        c.step("send prompt via Telegram with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Append exactly the word Delta as a new fourth line at the end "
            f"of the file {TARGET_FILE}. Do not modify the existing 3 lines.",
        )
        llm.set_answer(
            prompt,
            [("shell", { "cmd": f"printf '%s\\\\n' {LINE4_EXPECTED} >> {TARGET_FILE}" })],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step(f"wait for {TARGET_FILE} to be modified")
        mtime = wait_for_file(TARGET_FILE, precreate_mtime + 1, timeout=30)
        if mtime is None:
            c.fail("file modified", f"{TARGET_FILE} not modified within timeout")
        c.ok("file modified", f"after {mtime - precreate_mtime}s")

        c.step("check file has 4 lines")
        content = dexec("cat", TARGET_FILE).stdout
        lines = [l for l in content.strip().split("\n") if l]
        if len(lines) != 4:
            c.fail("line count", f"expected 4, got {len(lines)}: {repr(content)}")
        c.ok("line count", f"{len(lines)} lines")

        c.step("check first 3 lines unchanged")
        expected = [LINE1, LINE2, LINE3]
        for i, (got, exp) in enumerate(zip(lines[:3], expected)):
            if got.strip() != exp:
                c.fail("original lines", f"line {i+1}: expected {repr(exp)}, got {repr(got)}")
        c.ok("original lines", "unchanged")

        c.step("check 4th line is Delta")
        if lines[3].strip() != LINE4_EXPECTED:
            c.fail("4th line", f"expected {repr(LINE4_EXPECTED)}, got {repr(lines[3])}")
        c.ok("4th line", repr(lines[3].strip()))

        c.done()
