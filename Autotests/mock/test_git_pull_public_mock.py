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
    make_prompt, send_prompt,
)

TARGET_DIR = "/tmp/git_pull"
CLONE_LOG = "/tmp/git_pull_clone.log"
CLONE_WAIT_SECONDS = 120


def _normalize_git_url(url: str) -> str:
    url = (url or "").strip()
    if url.endswith("/"):
        url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


def test_git_pull_public_mock(llm, comm):
    remote = get_git_remote()

    with Checker("git pull public (mock)", cleanup_dirs=[TARGET_DIR, CLONE_LOG]) as c:
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

        c.step("send prompt via comm channel with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Clone the public git repository {remote} into {TARGET_DIR}/. "
            "Use anonymous HTTPS, no credentials are needed.",
        )
        # The shell skill itself has a five-second timeout. Run the network
        # operation in a background worker so the shell call can return while
        # this test polls repository state. Keep each attempt bounded and
        # retry transient runner/network failures. A shallow clone is enough
        # because the assertions only require HEAD, tracked files and origin.
        clone_command = (
            f"rm -rf {TARGET_DIR} {CLONE_LOG}; "
            "(for attempt in 1 2 3; do "
            f"rm -rf {TARGET_DIR}; "
            "GIT_TERMINAL_PROMPT=0 timeout 35s "
            f"git clone --depth 1 {remote} {TARGET_DIR} && exit 0; "
            "sleep 2; "
            f"done; exit 1) > {CLONE_LOG} 2>&1 &"
        )
        llm.set_answer(
            prompt,
            [("shell", { "cmd": f"{clone_command}" })]
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within 60s")
        c.ok("comm", f"run-id={c.run_id}")

        c.step("wait for valid cloned repository")
        deadline = time.monotonic() + CLONE_WAIT_SECONDS
        valid = False
        while time.monotonic() < deadline:
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
            sh_calls = find_skill_calls(c.run_id, "shell") or []
            listing = dexec_root("ls", "-la", TARGET_DIR)
            clone_log = dexec_root("tail", "-n", "80", CLONE_LOG)
            head = dexec_root("git", "-C", TARGET_DIR, "rev-parse",
                              "--verify", "HEAD")
            origin = dexec_root("git", "-C", TARGET_DIR, "remote",
                                "get-url", "origin")
            c.fail(
                "clone",
                f"valid clone not present at {TARGET_DIR} within "
                f"{CLONE_WAIT_SECONDS}s; shell_calls={sh_calls[:3]!r}; "
                f"listing_rc={listing.returncode}, listing={listing.stdout[-1000:]!r}, "
                f"listing_error={listing.stderr[-500:]!r}; "
                f"clone_log_rc={clone_log.returncode}, "
                f"clone_log={clone_log.stdout[-2000:]!r}, "
                f"clone_log_error={clone_log.stderr[-500:]!r}; "
                f"head_rc={head.returncode}, head={head.stdout.strip()!r}, "
                f"head_error={head.stderr[-500:]!r}; "
                f"origin_rc={origin.returncode}, origin={origin.stdout.strip()!r}, "
                f"origin_error={origin.stderr[-500:]!r}",
            )
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
