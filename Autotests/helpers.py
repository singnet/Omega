"""Shared test infrastructure for Omega smoke tests."""
import atexit
import inspect
import os
import re
import socket
import subprocess
import threading
import time

import pytest

CHANNEL = os.environ.get("OMEGA_IRC_CHANNEL") or "#metaclaw777"
CONTAINER = os.environ.get("OMEGA_CONTAINER") or "omega"
IRC_SERVER = "irc.quakenet.org"
IRC_PORT = 6667
WAIT = 30
POLL = 3

HISTORY_FILE = "/PeTTa/repos/Omega/memory/history.metta"
CHROMA_SQLITE = "/PeTTa/chroma_db/chroma.sqlite3"

GIT_TOKEN_ENV = "OMEGA_GIT_TOKEN"
GIT_REMOTE_ENV = "OMEGA_GIT_REMOTE"
GIT_DEFAULT_REMOTE = "https://github.com/OmegaSing/Test-Repopo"
GIT_AUTHOR_NAME = "Omega Test"
GIT_AUTHOR_EMAIL = "test@omega.local"
GIT_CREDENTIALS_PATH = "/etc/git-credentials"


def dexec(*args):
    """
    Executes a command inside the Docker container as the default user.
    Prints the command being executed and explicitly logs any standard error (stderr)
    to the console. This helps surface hidden failures (like missing commands or 
    runtime crashes) immediately during test execution.
    """
    cmd = ["docker", "exec", CONTAINER, *args]
    print(f"       $ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stderr:
        print(f"[ERROR]:\n{result.stderr}", flush=True)
    return result


def dexec_root(*args):
    """
    Executes a command inside the Docker container as the 'root' user.
    Prints the command being executed and explicitly logs any standard error (stderr)
    to the console. This helps surface hidden failures (like missing commands or 
    runtime crashes) immediately during test execution.
    """
    cmd = ["docker", "exec", "-u", "root", CONTAINER, *args]
    print(f"       $ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stderr:
        print(f"[ERROR]:\n{result.stderr}", flush=True)
    return result


IRC_RETRIES = 3
IRC_RETRY_DELAY = 10

# Stable nick for the whole pytest session. The agent's IRC channel binds
# `auth 0000` to the FIRST nick that presents the secret; any subsequent nick
# sending the same secret is rejected ("ignore"), so per-test nicks would
# silently fail IRC delivery for every test after the first. Generating once
# at import time guarantees all tests share a single authenticated identity.
SESSION_NICK = f"qa{int(time.time()) % 100000}"


# --- Persistent IRC session --------------------------------------------------
#
# Prior design opened a new socket per test, registered, joined channel, sent
# auth + prompt, then QUIT. With 19 tests that's 19 full register cycles in a
# 13-minute window — quakenet rate-limits these and drops them with
# `Connection reset by peer` under load. We keep one socket alive for the
# whole pytest session instead: register + auth once, then just PRIVMSG per
# test. A daemon reader thread handles server PINGs so we don't get dropped
# during idle periods between tests. On socket death (quakenet disconnect,
# network flake) the next send_prompt() transparently reopens and re-auths.

_irc_lock = threading.Lock()  # guards all sends to the shared socket
_irc_sock = None              # live socket once authed, else None
_irc_reader = None            # daemon PING/PONG handler, one per live socket


def _reader_loop(sock):
    buf = ""
    try:
        while True:
            try:
                data = sock.recv(4096)
            except OSError:
                return
            if not data:
                return
            buf += data.decode(errors="ignore")
            while "\r\n" in buf:
                line, buf = buf.split("\r\n", 1)
                if line.startswith("PING"):
                    token = line.split(" ", 1)[1] if " " in line else ":?"
                    try:
                        with _irc_lock:
                            sock.sendall(f"PONG {token}\r\n".encode())
                    except OSError:
                        return
    finally:
        pass


def _open_session():
    """Connect, register, JOIN channel, send `auth 0000`. Must be called with
    _irc_lock held. Returns the live socket or None on failure."""
    nick = SESSION_NICK
    sock = socket.create_connection((IRC_SERVER, IRC_PORT), timeout=30)
    sock.settimeout(30)
    sock.sendall(f"NICK {nick}\r\nUSER {nick} 0 * :{nick}\r\n".encode())

    buf = ""
    joined = False
    deadline = time.time() + 60
    while time.time() < deadline and not joined:
        try:
            data = sock.recv(4096)
        except OSError:
            sock.close()
            return None
        if not data:
            sock.close()
            return None
        buf += data.decode(errors="ignore")
        while "\r\n" in buf:
            line, buf = buf.split("\r\n", 1)
            if line.startswith("PING"):
                token = line.split(" ", 1)[1] if " " in line else ":?"
                sock.sendall(f"PONG {token}\r\n".encode())
            elif " 001 " in line:
                sock.sendall(f"JOIN {CHANNEL}\r\n".encode())
            elif " 366 " in line:
                # End of NAMES list — we're in the channel.
                sock.sendall(f"PRIVMSG {CHANNEL} :auth 0000\r\n".encode())
                joined = True
                break
    if not joined:
        try: sock.close()
        except OSError: pass
        return None

    sock.settimeout(None)  # reader thread blocks on recv, writes go via lock
    return sock


def _kill_session_locked():
    """Close the current socket without re-raising. Must be called with
    _irc_lock held."""
    global _irc_sock, _irc_reader
    if _irc_sock is not None:
        try: _irc_sock.sendall(b"QUIT :bye\r\n")
        except OSError: pass
        try: _irc_sock.close()
        except OSError: pass
    _irc_sock = None
    _irc_reader = None


def _ensure_session_locked():
    """Open a session if none is live. Must be called with _irc_lock held.
    Returns True on success."""
    global _irc_sock, _irc_reader
    if _irc_sock is not None:
        return True
    sock = _open_session()
    if sock is None:
        return False
    _irc_sock = sock
    _irc_reader = threading.Thread(target=_reader_loop, args=(sock,), daemon=True)
    _irc_reader.start()
    return True


def send_prompt(prompt):
    """Deliver a PRIVMSG to the agent's channel over the persistent session.
    Auto-opens the session on first call and auto-reconnects on socket errors.
    Returns True on success."""
    global _irc_sock
    for attempt in range(IRC_RETRIES):
        with _irc_lock:
            if not _ensure_session_locked():
                print(
                    f"       IRC session open attempt {attempt + 1}/{IRC_RETRIES} failed",
                    flush=True,
                )
                if attempt < IRC_RETRIES - 1:
                    # Release lock for backoff sleep below.
                    pass
            else:
                try:
                    _irc_sock.sendall(f"PRIVMSG {CHANNEL} :{prompt}\r\n".encode())
                    return True
                except (ConnectionResetError, ConnectionRefusedError,
                        socket.timeout, BrokenPipeError, OSError) as e:
                    print(
                        f"       IRC send attempt {attempt + 1}/{IRC_RETRIES} failed: {e}",
                        flush=True,
                    )
                    _kill_session_locked()
        if attempt < IRC_RETRIES - 1:
            time.sleep(IRC_RETRY_DELAY)
    return False


@atexit.register
def _irc_session_shutdown():
    with _irc_lock:
        _kill_session_locked()


def wait_for_file(path, after_ts, timeout=WAIT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = dexec("stat", "-c", "%Y", path)
        if res.returncode == 0:
            mtime = int(res.stdout.strip())
            if mtime >= after_ts:
                return mtime
        time.sleep(POLL)
    return None


def cleanup_dir(path):
    subprocess.run(
        ["docker", "exec", "-u", "root", CONTAINER, "rm", "-rf", path],
        capture_output=True, text=True,
    )


def history_cleanup_by_markers(markers):
    """Remove top-level s-exp records from history.metta whose text contains
    any of the given markers. A record starts with `("YYYY-MM-DD...` at a line
    boundary and ends at the next such start (or EOF). Any trailing
    ERROR_FEEDBACK text belongs to the preceding record.
    Idempotent. Runs python3 inside the container as root.
    """
    if not markers:
        return 0
    py = (
        "import re, sys\n"
        f"path = {HISTORY_FILE!r}\n"
        f"markers = {list(markers)!r}\n"
        "try:\n"
        "    with open(path) as f: content = f.read()\n"
        "except FileNotFoundError:\n"
        "    print('0'); sys.exit(0)\n"
        "markers_lc = [m.lower() for m in markers]\n"
        "starts = [m.start() for m in re.finditer(r'\\(\"\\d{4}-\\d{2}-\\d{2}', content)]\n"
        "if not starts:\n"
        "    print('0'); sys.exit(0)\n"
        "prefix = content[:starts[0]]\n"
        "ends = starts[1:] + [len(content)]\n"
        "kept = [prefix]\n"
        "removed = 0\n"
        "for s, e in zip(starts, ends):\n"
        "    block = content[s:e]\n"
        "    if any(m in block.lower() for m in markers_lc):\n"
        "        removed += 1\n"
        "    else:\n"
        "        kept.append(block)\n"
        "new_content = ''.join(kept)\n"
        "if new_content != content:\n"
        "    with open(path, 'w') as f: f.write(new_content)\n"
        "print(removed)\n"
    )
    res = dexec_root("python3", "-c", py)
    try:
        return int(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def chromadb_cleanup_by_markers(markers):
    """Delete chromadb entries whose document contains any of the given markers.
    Uses ChromaDB Python API inside the container. Returns total deleted count.
    """
    if not markers:
        return 0
    py = (
        "import chromadb\n"
        "client = chromadb.PersistentClient(path='/PeTTa/chroma_db')\n"
        f"markers = {list(markers)!r}\n"
        "markers_lc = [m.lower() for m in markers]\n"
        "total = 0\n"
        "for coll in client.list_collections():\n"
        "    c = client.get_collection(coll.name)\n"
        "    data = c.get()\n"
        "    ids = data.get('ids') or []\n"
        "    docs = data.get('documents') or []\n"
        "    to_del = [ids[i] for i, d in enumerate(docs)\n"
        "              if d and any(m in d.lower() for m in markers_lc)]\n"
        "    if to_del:\n"
        "        c.delete(ids=to_del)\n"
        "        total += len(to_del)\n"
        "print(total)\n"
    )
    res = dexec("python3", "-c", py)
    try:
        return int(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def read_history():
    return dexec("cat", HISTORY_FILE).stdout


def get_mtime(path):
    res = dexec("stat", "-c", "%Y", path)
    if res.returncode != 0:
        return None
    try:
        return int(res.stdout.strip())
    except ValueError:
        return None


def get_size(path):
    res = dexec("stat", "-c", "%s", path)
    if res.returncode != 0:
        return None
    try:
        return int(res.stdout.strip())
    except ValueError:
        return None


def _prompt_tag(run_id):
    """Unique short tag the agent is expected to quote at least once in a
    skill argument. Used to locate the response window in history.metta.
    """
    return f"REQ-{run_id}"


def _history_block_for_run_id(content, run_id):
    """Same as _response_window: slice from first reference onward. Kept as a
    public helper because some tests import it directly.
    """
    return _response_window(content, run_id)


def wait_for_history_keyword(run_id, keywords, timeout=WAIT, require_all=False):
    """Wait until at least one keyword (case-insensitive) appears in history
    after the first mention of our prompt tag for this run_id.
    If require_all=True, waits until ALL keywords are present.
    Returns list of matched keywords, or None on timeout.
    """
    deadline = time.time() + timeout
    kws_lower = [k.lower() for k in keywords]
    while time.time() < deadline:
        block = _history_block_for_run_id(read_history(), run_id)
        if block:
            blk_lower = block.lower()
            matched = [k for k, kl in zip(keywords, kws_lower) if kl in blk_lower]
            if require_all and len(matched) == len(keywords):
                return matched
            if not require_all and matched:
                return matched
        time.sleep(POLL)
    return None


def wait_for_history_block(run_id, timeout=WAIT):
    """Wait until the agent mentions our prompt tag in history. Returns the
    slice from the first tag occurrence to EOF, or None on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        block = _history_block_for_run_id(read_history(), run_id)
        if block:
            return block
        time.sleep(POLL)
    return None


def wait_for_file_mtime_change(path, initial_mtime, timeout=WAIT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        m = get_mtime(path)
        if m is not None and (initial_mtime is None or m > initial_mtime):
            return m
        time.sleep(POLL)
    return None


def _response_window(content, run_id):
    """Return the slice of history.metta starting at the first place the agent
    references this run. Preferred anchor is the explicit REQ-{run_id} tag;
    fallback to the bare run_id number (the agent sometimes quotes just that
    when it rejects or abbreviates). Window is open-ended to EOF — the new
    agent format has no turn terminator.
    """
    for anchor in (_prompt_tag(run_id), str(run_id)):
        idx = content.find(anchor)
        if idx != -1:
            return content[idx:]
    return None


_SKILL_ARG_RE = {}


def _skill_regex(skill):
    if skill not in _SKILL_ARG_RE:
        _SKILL_ARG_RE[skill] = re.compile(
            r"\(" + re.escape(skill) + r"\s+\"((?:[^\"\\]|\\.)*)\"",
            re.DOTALL,
        )
    return _SKILL_ARG_RE[skill]


def find_skill_calls(run_id, skill_name):
    """Return list of argument strings for every (<skill_name> "...") call
    the agent made in its response window for this run_id. Empty list if none.
    None if no response block exists yet.
    """
    window = _response_window(read_history(), run_id)
    if window is None:
        return None
    return _skill_regex(skill_name).findall(window)


def wait_for_skill_call(run_id, skill_name, timeout=WAIT, arg_substr=None):
    """Wait until the agent invokes (<skill_name> "...") in its response to run_id.
    If arg_substr is given, require that substring (case-insensitive) in the
    skill argument. Returns the matching argument on success, None on timeout.
    """
    deadline = time.time() + timeout
    needle = arg_substr.lower() if arg_substr else None
    while time.time() < deadline:
        calls = find_skill_calls(run_id, skill_name)
        if calls:
            if needle is None:
                return calls[0]
            for a in calls:
                if needle in a.lower():
                    return a
        time.sleep(POLL)
    return None


def wait_for_skill_match(run_id, skill_name, predicate, timeout=WAIT):
    """Wait until any (<skill_name> "...") call in the response window satisfies
    predicate(arg) -> bool. Returns the matching argument, None on timeout.

    Useful for multi-turn tests where the agent sends a preliminary reply
    ("will search...") and only a later (send ...) contains the final answer.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        calls = find_skill_calls(run_id, skill_name) or []
        for a in calls:
            if predicate(a):
                return a
        time.sleep(POLL)
    return None


def wait_for_any_skill_call(run_id, skill_names, timeout=WAIT, arg_substr=None):
    """Wait for a call to any of the given skills. Returns (skill_name, arg) tuple
    on success, (None, None) on timeout.
    """
    deadline = time.time() + timeout
    needle = arg_substr.lower() if arg_substr else None
    while time.time() < deadline:
        for skill in skill_names:
            calls = find_skill_calls(run_id, skill)
            if calls:
                if needle is None:
                    return skill, calls[0]
                for a in calls:
                    if needle in a.lower():
                        return skill, a
        time.sleep(POLL)
    return None, None


def make_prompt(run_id, task):
    """Wrap a task in a minimal envelope: a unique tag the agent is expected
    to quote in a skill argument (used by helpers to locate the response
    window), followed by the task itself. Phrasing is deliberately plain —
    earlier envelopes with words like "CI smoke test", "do not consult
    memory", and a literal "auth 0000" matched the agent's anti-social-
    engineering heuristic and got every test rejected.
    """
    return f"[{_prompt_tag(run_id)}] {task}"


class Checker:
    # Grade: 1 = solved on first try, 2 = after clarifying prompt, 0 = failed.
    GRADE_FIRST_TRY = 1
    GRADE_AFTER_CLARIFY = 2
    GRADE_FAIL = 0

    def __init__(self, name, cleanup_dirs=None):
        self.name = name
        self.total = 0
        self.passed = 0
        self.run_id = int(time.time())
        self.grade = None
        self._cleanup_dirs = cleanup_dirs or []
        self._cleanup_markers = [_prompt_tag(self.run_id), str(self.run_id)]

    def set_grade(self, level):
        self.grade = level
        label = {1: "FIRST TRY", 2: "AFTER CLARIFY", 0: "FAIL"}.get(level, str(level))
        print(f"       [GRADE] level={level} ({label})", flush=True)

    def add_cleanup_dir(self, path):
        self._cleanup_dirs.append(path)

    def add_cleanup_marker(self, marker):
        """Register an extra string to match in chromadb docs / history records
        during teardown. The default prompt tag is always added.
        """
        if marker and marker not in self._cleanup_markers:
            self._cleanup_markers.append(marker)

    def __enter__(self):
        frame = inspect.currentframe().f_back
        try:
            source = inspect.getsource(frame.f_code)
            self.total = source.count(".step(") + source.count(".verify_clean(")
        except OSError:
            self.total = 0
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        # Agent runs a continuous loop; ask it to drop pinned tasks before
        # we wipe the filesystem, otherwise it recreates files mid-teardown.
        if self._cleanup_dirs:
            self.step("teardown: cancel agent's pending work")
            send_prompt(make_prompt(
                self.run_id,
                f"All tasks for run-id {self.run_id} are CANCELLED. Stop "
                f"writing to {', '.join(self._cleanup_dirs)}. "
                f"Acknowledge with one short send and then idle.",
            ))
            time.sleep(15)

        self.step("teardown: cleanup test artifacts")
        for path in self._cleanup_dirs:
            cleanup_dir(path)
            time.sleep(3)
            cleanup_dir(path)
            if dexec("test", "-e", path).returncode == 0:
                print(f"       [WARN] {path} still exists", flush=True)
            else:
                print(f"       removed {path}", flush=True)
        h_removed = history_cleanup_by_markers(self._cleanup_markers)
        print(f"       history: {h_removed} blocks removed", flush=True)
        c_removed = chromadb_cleanup_by_markers(self._cleanup_markers)
        print(f"       chromadb: {c_removed} vectors removed", flush=True)
        return False

    def verify_clean(self):
        self.step("verify target dirs are clean")
        for path in self._cleanup_dirs:
            if dexec("test", "-e", path).returncode == 0:
                print(f"       {path} exists, cleaning up leftover", flush=True)
                cleanup_dir(path)
                if dexec("test", "-e", path).returncode == 0:
                    self.fail("verify clean", f"cannot remove leftover {path}")
        self.ok("verify clean")

    def step(self, name):
        print(f"\n>> {name}", flush=True)

    def ok(self, name, detail=""):
        self.passed += 1
        extra = f" -- {detail}" if detail else ""
        print(f"[ OK ] {name}{extra}", flush=True)

    def fail(self, name, detail):
        # If a graded step succeeded earlier but a later step fails the
        # test, the grade is no longer meaningful — collapse it to FAIL so
        # the printed result matches the test outcome.
        if self.grade is not None and self.grade != self.GRADE_FAIL:
            self.grade = self.GRADE_FAIL
        grade_str = f" [grade={self.grade}]" if self.grade is not None else ""
        print(f"[FAIL] {name} -- {detail}", flush=True)
        print(f"\n[FAIL] {self.passed}/{self.total} checks passed{grade_str}\n", flush=True)
        pytest.fail(f"{name}: {detail}", pytrace=False)

    def done(self):
        grade_str = f" [grade={self.grade}]" if self.grade is not None else ""
        print(f"\n[PASS] {self.passed}/{self.total} checks passed{grade_str}\n", flush=True)


def get_git_token():
    return os.environ.get(GIT_TOKEN_ENV)


def get_git_remote():
    return os.environ.get(GIT_REMOTE_ENV) or GIT_DEFAULT_REMOTE


def setup_git_in_container(token):
    """Install HTTPS credential helper and author identity inside the
    container so the agent can `git push` without seeing the token."""
    creds_line = f"https://x-access-token:{token}@github.com\n"
    py = (
        "import os\n"
        f"with open({GIT_CREDENTIALS_PATH!r}, 'w') as f: f.write({creds_line!r})\n"
        f"os.chmod({GIT_CREDENTIALS_PATH!r}, 0o644)\n"
    )
    res = dexec_root("python3", "-c", py)
    if res.returncode != 0:
        return False, f"writing creds failed: {res.stderr!r}"

    for args in (
        ["git", "config", "--system", "credential.helper",
         f"store --file={GIT_CREDENTIALS_PATH}"],
        ["git", "config", "--system", "user.email", GIT_AUTHOR_EMAIL],
        ["git", "config", "--system", "user.name", GIT_AUTHOR_NAME],
        ["git", "config", "--system", "init.defaultBranch", "main"],
        ["git", "config", "--system", "safe.directory", "*"],
    ):
        res = dexec_root(*args)
        if res.returncode != 0:
            return False, f"{args!r} failed: {res.stderr!r}"
    return True, "ok"


def teardown_git_in_container():
    dexec_root("rm", "-f", GIT_CREDENTIALS_PATH)
    for key in ("credential.helper", "user.email", "user.name",
                "init.defaultBranch", "safe.directory"):
        dexec_root("git", "config", "--system", "--unset-all", key)


def try_with_clarification(c, ready_check, clarification_prompt,
                           timeout_first=120, timeout_second=240):
    """Poll ready_check; on first-attempt timeout, send clarification and
    retry. Returns (grade, value) — grade 1/2 on success, 0 on final fail."""
    deadline = time.time() + timeout_first
    while time.time() < deadline:
        result = ready_check()
        if result is not None:
            return Checker.GRADE_FIRST_TRY, result
        time.sleep(POLL)

    print(f"\n>> first attempt timed out after {timeout_first}s — sending clarification",
          flush=True)
    follow = make_prompt(c.run_id, clarification_prompt)
    if not send_prompt(follow):
        print("       [WARN] could not deliver clarification IRC message", flush=True)
        return Checker.GRADE_FAIL, None

    deadline = time.time() + timeout_second
    while time.time() < deadline:
        result = ready_check()
        if result is not None:
            return Checker.GRADE_AFTER_CLARIFY, result
        time.sleep(POLL)

    return Checker.GRADE_FAIL, None
