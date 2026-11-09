"""
Mock variant of test_git_local_commit.

The mocked LLM response runs `git init`, writes hello.txt, and produces
a commit whose subject contains the run_id — all via shell calls. The
host harness still installs the git author identity inside the
container before the test runs (as in the live variant).

Run:
    pytest test_git_local_commit_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, find_skill_calls, make_prompt, send_prompt,
    setup_git_in_container, teardown_git_in_container, wait_for_file,
)

TARGET_DIR = "/tmp/git_local"
COMMIT_FILE = "hello.txt"


def test_git_local_commit_mock(llm, comm):
    with Checker("git local commit (mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== git local commit mock (run-id {c.run_id}) ===", flush=True)

        c.verify_clean()

        c.step("pre-create target dir + git author identity")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("chmod", "777", TARGET_DIR)
        ok, detail = setup_git_in_container(token="dummy-not-used-here")
        if not ok:
            c.fail("git setup", detail)
        c.ok("git setup")

        start_ts = int(time.time()) - 1
        marker = f"omega run {c.run_id}"
        c.add_cleanup_marker(marker)

        c.step("send prompt via comm channel with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Initialise a new git repository at {TARGET_DIR}/. "
            f"Create file {TARGET_DIR}/{COMMIT_FILE} with content "
            f"'{marker}'. Then run `git add` and `git commit` with "
            f"message 'add hello {c.run_id}'.",
        )
        commit_path = f"{TARGET_DIR}/{COMMIT_FILE}"
        # The whole sequence in one LLM response: init, write content,
        # add, commit. Quote handling is tricky here — git commit -m
        # needs the message in single-quoted shell string while the s-exp
        # arg itself is double-quoted, so we escape inner quotes.
        llm.set_answer(
            prompt, [
                ("shell", { "cmd": f"git -C {TARGET_DIR} init" }),
                ("write-file", { "filename": f"{commit_path}", "content": f"{marker}" }),
                ("shell", { "cmd": f"git -C {TARGET_DIR} add -A" }),
                ("shell", { "cmd": f'git -C {TARGET_DIR} commit -m "add hello {c.run_id}"' })
            ]
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within 60s")
        c.ok("comm", f"run-id={c.run_id}")

        c.step(f"wait for {COMMIT_FILE} on disk")
        mtime = wait_for_file(commit_path, start_ts, timeout=30)
        if mtime is None:
            c.fail(COMMIT_FILE, f"{COMMIT_FILE} not created within timeout")
        c.ok(COMMIT_FILE, f"after {mtime - start_ts}s")

        c.step("wait for .git directory and at least one commit")
        deadline = time.time() + 30
        head = ""
        while time.time() < deadline:
            if dexec("test", "-d", f"{TARGET_DIR}/.git").returncode == 0:
                res = dexec_root("git", "-C", TARGET_DIR, "log",
                                 "--format=%H %s", "-1")
                if res.returncode == 0 and res.stdout.strip():
                    head = res.stdout.strip()
                    break
            time.sleep(1)
        if not head:
            c.fail("git commit", "no commit in repo within timeout")
        c.ok("git commit", f"HEAD={head!r}")

        c.step("verify commit message contains run_id")
        msg = dexec_root("git", "-C", TARGET_DIR, "log",
                         "--format=%s", "-1").stdout
        if str(c.run_id) not in msg:
            c.fail("commit message", f"run_id missing in subject: {msg.strip()!r}")
        c.ok("commit message", msg.strip())

        c.step(f"verify {COMMIT_FILE} is tracked in HEAD")
        ls = dexec_root("git", "-C", TARGET_DIR, "ls-tree", "-r",
                        "--name-only", "HEAD")
        if COMMIT_FILE not in ls.stdout.split():
            c.fail("tracked file", f"{COMMIT_FILE} not in HEAD: {ls.stdout!r}")
        c.ok("tracked file", COMMIT_FILE)

        c.step("verify agent invoked shell with git commands")
        sh_calls = find_skill_calls(c.run_id, "shell") or []
        git_calls = [a for a in sh_calls if "git " in a or a.strip().startswith("git")]
        if not git_calls:
            c.fail("shell git", "no shell call mentioned 'git'")
        c.ok("shell git", f"{len(git_calls)}/{len(sh_calls)} shell calls used git")

        teardown_git_in_container()
        c.done()
