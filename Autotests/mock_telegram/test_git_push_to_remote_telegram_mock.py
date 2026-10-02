"""
Mock variant of test_git_push_to_remote.

The mocked LLM response performs the full clone + branch + write +
commit + push sequence in a single shell call. Cloning and pushing
still require network access plus a real GitHub PAT
(OMEGA_GIT_TOKEN) — the mock controls only the LLM dispatch.

Run:
    pytest test_git_push_to_remote_mock.py -s
"""
import json
import time
import urllib.error
import urllib.request

import pytest


from helpers import (
    Checker, dexec, dexec_root, find_skill_calls, get_git_remote,
    get_git_token, make_prompt, setup_git_in_container,
    teardown_git_in_container, wait_for_file,
)
from tg_helpers import tg_send_prompt

TARGET_DIR = "/tmp/git_push"


def _gh(method, url, token, body=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    data = json.dumps(body).encode() if body is not None else None
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=20) as r:
            text = r.read().decode()
            try:
                return r.status, json.loads(text) if text else None
            except json.JSONDecodeError:
                return r.status, text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")


def _api_base(remote_url):
    path = remote_url.rstrip("/").removesuffix(".git")
    parts = path.split("github.com/", 1)
    if len(parts) != 2:
        raise ValueError(f"unsupported remote url: {remote_url!r}")
    return f"https://api.github.com/repos/{parts[1]}"


def test_git_push_to_remote_telegram_mock(llm, tg):
    token = get_git_token()
    if not token:
        pytest.skip("OMEGA_GIT_TOKEN not set")
    remote = get_git_remote()
    api = _api_base(remote)
    branch = f"qa/run-{int(time.time())}-mock"

    with Checker("git push to remote (telegram mock)", cleanup_dirs=[TARGET_DIR]) as c:
        print(f"\n=== git push mock (run-id {c.run_id}, branch {branch}) ===",
              flush=True)

        c.verify_clean()

        c.step("provision git credentials in container")
        ok, detail = setup_git_in_container(token)
        if not ok:
            c.fail("git setup", detail)
        c.ok("git setup")

        c.step("pre-create target dir")
        dexec_root("mkdir", "-p", TARGET_DIR)
        dexec_root("chmod", "777", TARGET_DIR)
        # Hand the directory to the agent's UID so it can rm -rf and
        # re-create inside /tmp (sticky bit prevents nobody from
        # removing root-owned dirs even with 0777 perms).
        dexec_root("chown", "65534:65534", TARGET_DIR)
        c.ok("pre-create dir", TARGET_DIR)

        unique_file = f"qa-run-{c.run_id}.txt"
        marker = f"omega push run {c.run_id}"
        c.add_cleanup_marker(marker)
        start_ts = int(time.time()) - 1

        c.step("send prompt via Telegram with mocked response")
        prompt = make_prompt(
            c.run_id,
            f"Clone {remote} into {TARGET_DIR}/ and check out a NEW branch "
            f"named '{branch}'. Create file {TARGET_DIR}/{unique_file} with "
            f"content '{marker}'. Run git add, commit, then push the branch.",
        )
        file_path = f"{TARGET_DIR}/{unique_file}"
        # All in one shell call: clean dir, clone, branch, write, add,
        # commit, push.
        chain = (
            f"rm -rf {TARGET_DIR} && "
            f"git clone {remote} {TARGET_DIR} && "
            f"cd {TARGET_DIR} && "
            f"git checkout -b {branch} && "
            f"printf '%s' '{marker}' > {unique_file} && "
            f"git add -A && "
            f"git commit -m 'qa run {c.run_id}' && "
            f"git push -u origin {branch}"
        )
        llm.set_answer(prompt, [("shell", { "cmd": f"{chain}" })])
        tg_send_prompt(tg, prompt)
        c.ok("telegram", f"run-id={c.run_id}")

        c.step(f"wait for {unique_file} on disk")
        mtime = wait_for_file(file_path, start_ts, timeout=60)
        if mtime is None:
            c.fail(unique_file, f"{unique_file} not created within timeout")
        c.ok(unique_file, f"after {mtime - start_ts}s")

        c.step("wait for branch on remote")
        deadline = time.time() + 120
        ok_branch = False
        while time.time() < deadline:
            status, _ = _gh("GET", f"{api}/branches/{branch}", token)
            if status == 200:
                ok_branch = True
                break
            time.sleep(2)
        if not ok_branch:
            c.fail("remote branch", f"{branch} not visible on remote within timeout")
        c.ok("remote branch", f"{branch} pushed")

        c.step("verify file is present on remote branch")
        status, body = _gh("GET", f"{api}/contents/{unique_file}?ref={branch}", token)
        if status != 200 or not isinstance(body, dict):
            c.fail("remote file", f"GET contents failed: status={status} body={body!r}")
        c.ok("remote file", f"sha={body.get('sha', '')[:8]}")

        c.step("verify agent invoked git push")
        sh_calls = find_skill_calls(c.run_id, "shell") or []
        if not any("push" in a and "git" in a for a in sh_calls):
            c.fail("shell push", f"no shell call with git+push: {sh_calls[:3]}")
        c.ok("shell push", f"{len(sh_calls)} shell calls")

        c.step(f"teardown: delete remote branch {branch}")
        status, body = _gh("DELETE", f"{api}/git/refs/heads/{branch}", token)
        if status not in (204, 422):
            c.fail("delete branch", f"status={status} body={body!r}")
        c.ok("delete branch", f"removed {branch}")

        c.step("teardown: wipe container git credentials")
        teardown_git_in_container()
        if dexec("test", "-f", "/etc/git-credentials").returncode == 0:
            c.fail("creds wiped", "/etc/git-credentials still present")
        c.ok("creds wiped")

        c.done()
