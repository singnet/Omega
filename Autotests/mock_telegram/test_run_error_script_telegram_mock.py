"""
Mock variant of test_run_error_script.

The harness pre-creates a syntactically broken script. The mocked LLM
response runs it with a 2>&1 redirect into output.txt so both the
"start" stdout and the shell error message land in the file.

Run:
    pytest test_run_error_script_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, make_prompt, wait_for_file,
)
from tg_helpers import tg_send_prompt

TARGET_DIR = "/tmp/test_error"
SCRIPT_FILE = "/tmp/test_error/broken.sh"
OUTPUT_FILE = "/tmp/test_error/output.txt"

BROKEN_SCRIPT = """#!/bin/sh
echo "start"
if [
echo "unreachable"
"""


def test_run_error_script_telegram_mock(llm, tg):
    with Checker("run error script (telegram mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: error script telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        c.step("pre-create broken script")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("sh", "-c",
                   f"cat > {SCRIPT_FILE} << 'ENDOFFILE'\n{BROKEN_SCRIPT}ENDOFFILE")
        dexec_root("chmod", "777", TARGET_DIR)
        dexec_root("chmod", "755", SCRIPT_FILE)
        if dexec("test", "-f", SCRIPT_FILE).returncode != 0:
            c.fail("pre-create", "could not create broken script")
        c.ok("pre-create")

        start_ts = int(time.time()) - 1

        c.step("send prompt via Telegram with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Run the script {SCRIPT_FILE} and save BOTH stdout and stderr "
            f"to {OUTPUT_FILE}. Use shell redirection `2>&1` so every error "
            f"message lands in the file too. Do not fix the script.",
        )
        llm.set_answer(
            prompt,
            [("shell", { "cmd": f"sh {SCRIPT_FILE} > {OUTPUT_FILE} 2>&1" })],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step(f"wait for {OUTPUT_FILE}")
        mtime = wait_for_file(OUTPUT_FILE, start_ts, timeout=30)
        if mtime is None:
            c.fail("output created", f"{OUTPUT_FILE} not created within timeout")
        c.ok("output created", f"after {mtime - start_ts}s")

        c.step("check output contains stdout and error indication")
        content = dexec("cat", OUTPUT_FILE).stdout
        content_lc = content.lower()
        if "start" not in content_lc:
            c.fail("stdout captured", f"stdout not found: {repr(content[:300])}")
        c.ok("stdout captured", "'start' found")

        error_indicators = ["error", "syntax", "unexpected", "missing", "not found"]
        found = [w for w in error_indicators if w in content_lc]
        if not found:
            c.fail("error reported", f"no error keywords: {repr(content[:300])}")
        c.ok("error reported", f"found: {', '.join(found)}")

        c.step("check container still running")
        res = dexec("echo", "alive")
        if res.returncode != 0 or "alive" not in res.stdout:
            c.fail("container alive", "container not responding")
        c.ok("container alive")

        c.done()
