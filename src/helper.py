import json
import os
import re
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from src.logger import get_logger
except ModuleNotFoundError:  # running this file directly as a script
    from logger import get_logger

logger = get_logger(__name__)

TS_RE = re.compile(r'^\("(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"')
LLM_COMMANDS = {
    "append-file",
    "clear-frame-junk",
    "compact-frame",
    "complete-goals-ltm",
    "complete-goals-stm",
    "ctx-add-hypothesis",
    "ctx-add-result",
    "episodes",
    "metta",
    "new-autonomous-frame",
    "new-frame",
    "pin",
    "query",
    "read-file",
    "remember",
    "websearch",
    "send",
    "send_probe",
    "shell",
    "show-active-framespace",
    "show-completed-framespace",
    "show-current-frame",
    "show-frame-index",
    "show-frame-relation",
    "show-root-frame",
    "switch-frame",
    "switch-mode",
    "tavily-search",
    "technical-analysis",
    "write-file",
    "get-io-policy",
    "write-file-b64",
}
TWO_ARG_COMMANDS = {
    "write-file",
    "append-file",
    "write-file-b64",
    "ctx-add-hypothesis",
    "ctx-add-result",
}

def make_id(prefix="id"):
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{stamp}"


def extract_timestamp(line):
    m = TS_RE.search(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        logger.error(f"Line does not carry a parsable timestamp: {e}")
        return None


def _episode_page(
    text: str, timestamp: str, offset: int, max_lines: int, max_chars: int,
) -> str | None:
    """Return bounded history text with a continuation into the same selection."""
    if offset >= len(text):
        return None
    lines = text[offset:offset + max_chars].splitlines(keepends=True)
    length = sum(map(len, lines[:max_lines]))
    while length:
        end = offset + length
        page = text[offset:end]
        if end < len(text):
            page += f'\nMORE HISTORY: (episodes "{timestamp}#{end}")\n'
        # The loop wraps this string in a list and adds "SUCCESS, RETURN: ".
        # Account for escaping and leave 32 characters for that wrapper.
        if len(repr(page)) + 32 <= max_chars:
            return page
        length //= 2
    raise ValueError("maxFeedback is too small for an episodes page and continuation.")


def around_time(needle_time_str: str, k: int, max_chars: int = 50000) -> str | None:
    """Recall matching audit neighborhoods, following an optional ``#offset`` cursor."""
    needle_time_str = needle_time_str.replace(r'\"', '').replace('"', '').strip()
    timestamp, separator, cursor = needle_time_str.partition("#")
    offset = int(cursor) if separator else 0
    if offset < 0:
        raise ValueError("episodes cursor must be a non-negative character offset.")
    filename = "repos/Omega/memory/history.metta"
    target = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    best_diff = None
    buffer = []
    best_idx = None
    exact_indices = []
    with open(filename, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            buffer.append((lineno, line))
            ts = extract_timestamp(line)
            if ts is None:
                continue
            if ts == target:
                exact_indices.append(len(buffer) - 1)
            diff = abs((ts - target).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_idx = len(buffer) - 1
    if best_idx is None:
        return None

    # Include original audit entries as well as archives sharing the timestamp.
    radius = max(0, int(k))
    selected_indices = set()
    for index in exact_indices or [best_idx]:
        start = max(0, index - radius)
        end = min(len(buffer), index + radius + 1)
        if index + 1 < len(buffer) and "PRUNED_FRAME_EVENT:" in buffer[index + 1][1]:
            end = min(len(buffer), max(end, index + 3))
        selected_indices.update(range(start, end))
    text = "".join(
        f"{buffer[index][0]}:{buffer[index][1]}"
        for index in sorted(selected_indices)
    )
    return _episode_page(text, timestamp, offset, 2 * radius + 1, int(max_chars))


def quote_arg(x):
    if x.startswith('"') and x.endswith('"') and "\n" not in x:
        return x
    else:
        return json.dumps(x, ensure_ascii=False)

def starts_command_line(line):
    s = line.lstrip()
    if not s:
        return False
    # allow "(send ...)" as command start too
    if s.startswith("("):
        s = s[1:].lstrip()
    if not s:
        return False
    first = s.split(maxsplit=1)[0].rstrip(")")
    return first in LLM_COMMANDS

def split_toplevel_forms(line):
    """Split a line holding several complete s-expressions into separate forms.

    Parentheses inside string literals are ignored. A line that is not a plain
    sequence of balanced top-level forms is returned unchanged, so single-form
    answers and free text keep their previous handling.
    """
    forms = []
    depth = 0
    start = None
    in_string = False
    escaped = False
    for i, ch in enumerate(line):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start is not None:
                forms.append(line[start:i + 1])
                start = None
            elif depth < 0:
                return [line]
        elif depth == 0 and not ch.isspace():
            return [line]
    if depth != 0 or len(forms) < 2:
        return [line]
    return forms


def split_command_blocks(s):
    blocks = []
    cur = []
    for raw in s.splitlines():
        if not raw.strip():
            if cur:
                cur.append(raw)
            continue
        if starts_command_line(raw) and cur:
            blocks.append("\n".join(cur).strip())
            cur = [raw]
        else:
            cur.append(raw)
    if cur:
        blocks.append("\n".join(cur).strip())
    expanded = []
    for block in blocks:
        expanded.extend(split_toplevel_forms(block.strip()))
    return expanded

def balance_parentheses(s):
    s = s.replace("_quote_", '"').replace("_newline_", "\n")
    sexprs = []
    for line in split_command_blocks(s):
        line = line.strip()
        if not line:
            continue
        if line.startswith("(-"):
            line = "(pin " + line[2:]
        elif line.startswith("-"):
            line = "pin " + line[1:]
        # remove one outer (...) if present
        if line.startswith("(") and line.endswith(")"):
            line = line[1:-1].strip()
        elif line.startswith("("):
            line = line[1:].strip()
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        cmd = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if cmd in TWO_ARG_COMMANDS:
            if not rest:
                sexprs.append(f"({cmd})")
                continue
            # filename is first token unless already quoted
            if rest.startswith('"'):
                end = 1
                escaped = False
                while end < len(rest):
                    ch = rest[end]
                    if ch == '"' and not escaped:
                        break
                    escaped = (ch == '\\' and not escaped)
                    if ch != '\\':
                        escaped = False
                    end += 1
                if end < len(rest) and rest[end] == '"':
                    filename = rest[:end+1]
                    content = rest[end+1:].strip()
                else:
                    filename = quote_arg(rest[1:])
                    content = ""
            else:
                split_rest = rest.split(maxsplit=1)
                filename = quote_arg(split_rest[0])
                content = split_rest[1].strip() if len(split_rest) > 1 else ""
            if content:
                sexprs.append(f"({cmd} {filename} {quote_arg(content)})")
            else:
                sexprs.append(f"({cmd} {filename})")
            continue
        if rest:
            sexprs.append(f"({cmd} {quote_arg(rest)})")
        else:
            sexprs.append(f"({cmd})")
    ret = " ".join(sexprs)
    return "(" + ret + ")"

def normalize_string(x):
    try:
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="ignore")
        return str(x).encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    except Exception as e:
        logger.debug(f"Could not normalize value, using its plain string form: {e}")
        return str(x)

def joinPath(parts):
    return os.path.join(*parts)

def projectRootDirectory():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_balance_parenthesis():
    assert balance_parentheses('(write-file test.txt hello world)') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('(append-file test.txt hello world)') == '((append-file "test.txt" "hello world"))'
    assert balance_parentheses('(write-file-b64 test.txt aGVsbG8=)') == '((write-file-b64 "test.txt" "aGVsbG8="))'
    assert balance_parentheses('write-file-b64 test.txt aGVsbG8=') == '((write-file-b64 "test.txt" "aGVsbG8="))'
    assert balance_parentheses('(write-file "test.txt" hello world)') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('(write-file "test.txt" "hello world")') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('(write-file test.txt "hello world")') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('(send test.xt hello world)') == '((send "test.xt hello world"))'
    assert balance_parentheses('write-file test.txt hello world') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('append-file test.txt hello world') == '((append-file "test.txt" "hello world"))'
    assert balance_parentheses('write-file "test.txt" hello world') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('write-file "test.txt" "hello world"') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('write-file test.txt "hello world"') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('send test.xt hello world') == '((send "test.xt hello world"))'
    assert balance_parentheses('send Here are the planets:\n1. Mercury\n2. Venus') == '((send "Here are the planets:\\n1. Mercury\\n2. Venus"))'
    assert balance_parentheses('send Here are the options:\n- MacBook Air\n- ThinkPad X1\npin done') == '((send "Here are the options:\\n- MacBook Air\\n- ThinkPad X1") (pin "done"))'
    assert balance_parentheses('send "Plain text version:"\n**Mars** - red planet\nNote: Pluto is a dwarf planet') == '((send "\\\"Plain text version:\\\"\\n**Mars** - red planet\\nNote: Pluto is a dwarf planet"))'
    assert balance_parentheses('(send Here are the planets:\n1. Mercury\n2. Venus)') == '((send "Here are the planets:\\n1. Mercury\\n2. Venus"))'
    assert balance_parentheses('send "hello" world') == '((send "\\"hello\\" world"))'
    assert balance_parentheses('send "Hello"\nHow are you?') == '((send "\\"Hello\\"\\nHow are you?"))'
    # bare "()" lines yield no tokens after _strip_outer_parens and must be skipped, not crash
    assert balance_parentheses('()') == '()'
    assert balance_parentheses('') == '()'
    assert balance_parentheses('   ') == '()'
    assert balance_parentheses('()\nsend hello') == '((send "hello"))'
    assert balance_parentheses('write-file "test.txt" hello\nworld') == '((write-file "test.txt" "hello\\nworld"))'
    assert balance_parentheses('- Found a bug') == '((pin "Found a bug"))'
    assert balance_parentheses('(- Found a bug)') == '((pin "Found a bug"))'
    assert balance_parentheses('- Found\na\nbug') == '((pin "Found\\na\\nbug"))'
    assert balance_parentheses('(- Found a bug') == '((pin "Found a bug"))'

def _format_omega_version(version: str) -> str | None:
    version = version.strip()
    if not version:
        return None
    if version.startswith("Omega version="):
        return version
    if version.startswith("Omega "):
        version = version[len("Omega "):]
    return f"Omega version={version}"


def omega_version(repo_root: str | os.PathLike | None = None) -> str:
    """Return the checkout version, falling back to the baked version file."""
    root = Path(repo_root) if repo_root is not None else Path(projectRootDirectory())

    try:
        # Prevent `git -C` from walking up to a parent repository such as /PeTTa.
        if not (root / ".git").exists():
            raise FileNotFoundError
        result = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--dirty", "--always"],
            check=False,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            version = _format_omega_version(result.stdout)
            if version is not None:
                return version
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        version = _format_omega_version(
            (root / "version").read_text(encoding="utf-8")
        )
        if version is not None:
            return version
    except OSError:
        pass

    return "Omega unknown"


def test_omega_version():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        assert omega_version(root) == "Omega unknown"

        (root / "version").write_text("v1.2.3-4-g1234567\n", encoding="utf-8")
        assert omega_version(root) == "Omega version=v1.2.3-4-g1234567"

        (root / "version").write_text("Omega v1.2.3\n", encoding="utf-8")
        assert omega_version(root) == "Omega version=v1.2.3"

if __name__ == "__main__":
    test_omega_version()
