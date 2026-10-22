"""
Mock variant of test_git_pull_public.

The mocked LLM response issues a single (shell ...) call performing
`git clone <remote> <target>`. Cloning still requires real network
access to GitHub — only the LLM dispatch is mocked.

Run:
    pytest test_git_pull_public_mock.py -s
"""
import time


from helpers import (
    Checker, dexec, dexec_root, find_skill_calls, get_git_remote,
    make_prompt, )
from tg_helpers import tg_send_prompt

TARGET_DIR = "/tmp/git_pull"


def _normalize_git_url(url: str) -> str:
    url = (url or "").strip()
    if url.endswith("/"):
        url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


def test_git_pull_public_telegram_mock(llm, tg):
    remote = get_git_remote()

    with Checker("git pull public (telegram mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== git pull public mock (run-id {c.run_id}) ===", flush=True)

        c.verify_clean()

        c.step("pre-create parent dir")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("chmod", "777", TARGET_DIR)
        # Hand the directory to the agent's UID so it can rm -rf and
        # re-create inside /tmp (sticky bit).
        dexec_root("chown", "65534:65534", TARGET_DIR)
        dexec_root("git", "config", "--global", "--add", "safe.directory", TARGET_DIR)
        c.ok("pre-create dir", TARGET_DIR)

        c.step("send prompt via Telegram with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Clone the public git repository {remote} into {TARGET_DIR}/. "
            "Use anonymous HTTPS, no credentials are needed.",
        )
        # Need an empty target dir for `git clone .` form. Use a
        # ./tmp_clone shim then move contents — simpler: rm -rf then
        # clone into the path directly.
        llm.set_answer(
            prompt,
            [("shell", { "cmd": f"rm -rf {TARGET_DIR} && git clone {remote} {TARGET_DIR}" })],
        )
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step("wait for valid cloned repository")
        deadline = time.time() + 60
        valid = False
        while time.time() < deadline:
            if dexec("test", "-d", f"{TARGET_DIR}/.git").returncode == 0:
                head = dexec_root("git", "-C", TARGET_DIR, "rev-parse",
                                  "--verify", "HEAD")
                files = dexec_root("git", "-C", TARGET_DIR, "ls-tree", "-r",
                                   "--name-only", "HEAD")
                origin = dexec_root("git", "-C", TARGET_DIR, "remote",
                                    "get-url", "origin")
                if (head.returncode == 0 and head.stdout.strip()
                        and files.returncode == 0 and files.stdout.strip()
                        and origin.returncode == 0 and origin.stdout.strip()):
                    if _normalize_git_url(origin.stdout.strip()) == _normalize_git_url(remote):
                        valid = True
                        break
            time.sleep(1)
        if not valid:
            c.fail("clone", f"valid clone not present at {TARGET_DIR} within timeout")
        c.ok("clone", "valid cloned repository present")

        c.step("verify clone has at least one tracked file")
        ls = dexec_root("git", "-C", TARGET_DIR, "ls-tree", "-r",
                        "--name-only", "HEAD")
        files = [f for f in ls.stdout.split() if f]
        if not files:
            c.fail("tracked files", f"no files in HEAD: {ls.stdout!r}")
        c.ok("tracked files", f"{len(files)} files, e.g. {files[:3]}")

        c.step("verify HEAD has a commit")
        log = dexec_root("git", "-C", TARGET_DIR, "log", "--format=%H %s", "-1")
        head = log.stdout.strip()
        if not head:
            c.fail("HEAD", f"no commits visible: {log.stderr!r}")
        c.ok("HEAD", head[:80])

        c.step("verify origin remote")
        origin = dexec_root("git", "-C", TARGET_DIR, "remote",
                            "get-url", "origin")
        actual = _normalize_git_url(origin.stdout.strip())
        expected = _normalize_git_url(remote)
        if origin.returncode != 0 or actual != expected:
            c.fail("origin", f"expected={expected!r}, actual={actual!r}")
        c.ok("origin", actual)

        c.step("verify agent invoked shell with git clone")
        sh_calls = find_skill_calls(c.run_id, "shell") or []
        if not any("git" in a and "clone" in a for a in sh_calls):
            c.fail("shell clone", f"no shell call combined 'git' and 'clone': {sh_calls[:3]}")
        c.ok("shell clone", f"{len(sh_calls)} shell calls")

        c.done()
