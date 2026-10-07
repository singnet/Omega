"""
Mock variant of test_run_repeated.

The harness pre-creates dateupdate.sh which appends `date` to update.txt.
The mocked LLM response issues ten consecutive (shell ...) calls,
producing ten date lines in update.txt.

Run:
    pytest test_run_repeated_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, make_prompt, send_prompt, wait_for_file,
)

TARGET_DIR = "/tmp/test_repeat"
SCRIPT_FILE = "/tmp/test_repeat/dateupdate.sh"
OUTPUT_FILE = "/tmp/test_repeat/update.txt"
SCRIPT_CONTENT = '#!/bin/sh\ndate >> /tmp/test_repeat/update.txt\n'
EXPECTED_RUNS = 10


def test_run_repeated_mock(llm, comm):
    with Checker("run repeated script (mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: run 10x mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        c.step("pre-create script")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("sh", "-c",
                   f"cat > {SCRIPT_FILE} << 'ENDOFFILE'\n{SCRIPT_CONTENT}ENDOFFILE")
        dexec_root("chmod", "777", TARGET_DIR)
        dexec_root("chmod", "755", SCRIPT_FILE)
        if dexec("test", "-f", SCRIPT_FILE).returncode != 0:
            c.fail("pre-create", "could not create script")
        c.ok("pre-create")

        start_ts = int(time.time()) - 1

        c.step("send prompt via comm channel with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Run the script {SCRIPT_FILE} exactly {EXPECTED_RUNS} times in "
            f"a row. The script appends a date line to {OUTPUT_FILE} each "
            "time it runs.",
        )
        repeated = [("shell", { "cmd": f"sh {SCRIPT_FILE}" }) for _ in range(EXPECTED_RUNS)]
        llm.set_answer(prompt, repeated)
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within 60s")
        c.ok("comm", f"run-id={c.run_id}")

        c.step(f"wait for {OUTPUT_FILE}")
        mtime = wait_for_file(OUTPUT_FILE, start_ts, timeout=30)
        if mtime is None:
            c.fail("file created", f"{OUTPUT_FILE} not created within timeout")
        c.ok("file created", f"after {mtime - start_ts}s")

        c.step(f"wait for {EXPECTED_RUNS} lines")
        deadline = time.time() + 60
        lines = []
        while time.time() < deadline:
            content = dexec("cat", OUTPUT_FILE).stdout
            lines = [l for l in content.strip().split("\n") if l.strip()]
            if len(lines) >= EXPECTED_RUNS:
                break
            time.sleep(2)
        if len(lines) < EXPECTED_RUNS:
            c.fail("line count", f"expected {EXPECTED_RUNS} lines, got {len(lines)}")
        c.ok("line count", f"{len(lines)} lines")

        c.step("check every line carries date-like data")
        bad = [l for l in lines[:EXPECTED_RUNS] if sum(ch.isdigit() for ch in l) < 2]
        if bad:
            c.fail("date content", f"lines without date data: {repr(bad)}")
        c.ok("date content", f"all {EXPECTED_RUNS} lines contain date info")

        c.done()
