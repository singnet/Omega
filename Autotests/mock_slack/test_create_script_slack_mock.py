"""
Mock variant of test_create_script.

The agent is fed a deterministic response that writes a two-line shell
script (shebang + date), makes it executable, and runs it. The hardened
runtime assertions of the live test are kept: the file must be
executable, run without error, and its output must contain the current
year.

Run:
    pytest test_create_script_mock.py -s
"""
import time
from datetime import datetime, timezone


from helpers import (
    Checker, dexec, make_prompt, wait_for_file,
)
from slack_helpers import sl_send_prompt

TARGET_DIR = "/tmp/test_script"
TARGET_FILE = "/tmp/test_script/date.sh"
WAIT = 30


def _current_year_strs():
    return {
        datetime.now(timezone.utc).strftime("%Y"),
        datetime.now().strftime("%Y"),
    }


def test_create_date_script_slack_mock(llm, sl):
    with Checker("create date.sh (slack mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: create date.sh slack mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        start_ts = int(time.time()) - 1

        c.step("send prompt via Slack with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Create a file {TARGET_FILE} with a shell script inside that "
            "will display the current date. Make it executable. "
            "Create the directory if needed.",
        )
        llm.set_answer(
            prompt,
            [
                ("shell", { "cmd": f"mkdir -p {TARGET_DIR}" }),
                ("write-file", { "filename": f"{TARGET_FILE}", "content": "#!/bin/bash\\ndate\\n" }),
                ("shell", { "cmd": f"chmod +x {TARGET_FILE}" }),
            ],
        )
        sl_send_prompt(sl, prompt)
        c.ok("slack", f"run-id={c.run_id}")

        c.step(f"wait for {TARGET_FILE}")
        mtime = wait_for_file(TARGET_FILE, start_ts, timeout=WAIT)
        if mtime is None:
            c.fail("file created", f"{TARGET_FILE} not created within {WAIT}s")
        c.ok("file created", f"after {mtime - start_ts}s")

        c.step("check file is executable")
        # The chmod command runs after write-file in the same response;
        # give a short polling window so we don't race the mode change.
        deadline = time.time() + 10
        perms = ""
        while time.time() < deadline:
            perms = dexec("stat", "-c", "%A", TARGET_FILE).stdout.strip()
            if "x" in perms:
                break
            time.sleep(0.5)
        if "x" not in perms:
            c.fail("permissions", f"not executable: {perms}")
        c.ok("permissions", perms)

        c.step("run script and check output contains current year")
        res = dexec("sh", TARGET_FILE)
        if res.returncode != 0:
            c.fail("run script", f"exit code {res.returncode}: {res.stderr.strip()}")
        output = res.stdout.strip()
        years = _current_year_strs()
        if not any(y in output for y in years):
            c.fail("date check", f"output does not contain current year: {output!r}")
        c.ok("date check", repr(output))

        c.done()
