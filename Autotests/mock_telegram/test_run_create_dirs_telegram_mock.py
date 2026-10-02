"""
Mock variant of test_run_create_dirs.

The mocked LLM response writes mkdirs.sh (shebang + mkdir for the three
target directories on a single line via \\n in the body), makes it
executable, and runs it. Behaviour matches the live test's success path:
the agent uses one (write-file ...) call and (shell ...) calls to chmod
and execute the script.

Run:
    pytest test_run_create_dirs_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, find_skill_calls, make_prompt,
    wait_for_file,
)
from tg_helpers import tg_send_prompt

TARGET_DIR = "/tmp/test_dirs"
SCRIPT_PATH = f"{TARGET_DIR}/mkdirs.sh"
EXPECTED_DIRS = ["test1", "test2", "test3"]


def test_run_create_dirs_telegram_mock(llm, tg):
    with Checker("create dirs script (telegram mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== Omega: create dirs telegram mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        c.step("pre-create target dir 0777")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("chmod", "777", TARGET_DIR)
        c.ok("pre-create dir", TARGET_DIR)

        start_ts = int(time.time()) - 1

        c.step("send prompt via Telegram with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Create script {SCRIPT_PATH} that creates dirs test1, test2, "
            f"test3 inside {TARGET_DIR}/. Make it executable, then run it.",
        )
        mkdir_args = " ".join(f"{TARGET_DIR}/{d}" for d in EXPECTED_DIRS)
        llm.set_answer(
            prompt,
            [
                ("write-file", { "filename": f"{SCRIPT_PATH}", "content": f"#!/bin/bash\\nmkdir -p {mkdir_args}\\n" }),
                ("shell", { "cmd": f"chmod +x {SCRIPT_PATH}" }),
                ("shell", { "cmd": f"sh {SCRIPT_PATH}" }),
            ],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step(f"wait for {SCRIPT_PATH}")
        mtime = wait_for_file(SCRIPT_PATH, start_ts, timeout=30)
        if mtime is None:
            c.fail("script created", f"{SCRIPT_PATH} not created within timeout")
        c.ok("script created", f"after {mtime - start_ts}s")

        c.step("verify all expected dirs exist")
        deadline = time.time() + 30
        while time.time() < deadline:
            existing = [
                n for n in EXPECTED_DIRS
                if dexec("test", "-d", f"{TARGET_DIR}/{n}").returncode == 0
            ]
            if len(existing) == len(EXPECTED_DIRS):
                break
            time.sleep(1)
        if existing != EXPECTED_DIRS:
            missing = [n for n in EXPECTED_DIRS if n not in existing]
            wf = find_skill_calls(c.run_id, "write-file") or []
            sh = find_skill_calls(c.run_id, "shell") or []
            perms = (
                dexec("stat", "-c", "%A", SCRIPT_PATH).stdout.strip()
                if dexec("test", "-f", SCRIPT_PATH).returncode == 0
                else "<no script>"
            )
            c.fail(
                "dirs exist",
                f"missing: {missing}. wf={len(wf)} sh={len(sh)} perms={perms}",
            )
        c.ok("dirs exist", f"{EXPECTED_DIRS}")

        c.step("verify (write-file ...) targeted mkdirs.sh")
        wf = find_skill_calls(c.run_id, "write-file") or []
        if not any(SCRIPT_PATH in a or "mkdirs.sh" in a for a in wf):
            c.fail("write-file mkdirs.sh", f"no write-file mentioned mkdirs.sh: {wf[:3]}")
        c.ok("write-file mkdirs.sh", f"{len(wf)} write-file calls")

        c.step("verify (shell ...) ran the script")
        sh = find_skill_calls(c.run_id, "shell") or []
        if not any("mkdirs.sh" in a or SCRIPT_PATH in a for a in sh):
            c.fail("shell invoked", f"no shell call referencing mkdirs.sh: {sh[:3]}")
        c.ok("shell invoked", f"{len(sh)} shell calls")

        c.step("check directory mtimes are fresh")
        for name in EXPECTED_DIRS:
            res = dexec("stat", "-c", "%Y", f"{TARGET_DIR}/{name}")
            if res.returncode != 0 or int(res.stdout.strip()) < start_ts:
                c.fail("dir timestamps", f"{name} has stale or missing mtime")
        c.ok("dir timestamps", f"all >= {start_ts}")

        c.done()
