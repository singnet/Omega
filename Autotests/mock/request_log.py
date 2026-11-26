import re
import subprocess
import time

from helpers import CONTAINER, dexec

EVENT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| ")


def docker_logs():
    res = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, text=True, errors="replace")
    return ((res.stdout or "") + (res.stderr or "")).split("\n")


def request_blocks(lines):
    blocks = []
    for line in lines:
        if EVENT.match(line):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return ["\n".join(b) for b in blocks]


def requests_from(token, count):
    blocks = [b for b in request_blocks(docker_logs()) if "REQUEST: LLMRequest" in b[:200]]
    first = next((i for i, b in enumerate(blocks) if token in b), None)
    if first is None or len(blocks) < first + count:
        return None
    return blocks[first:first + count]


def request_after(token):
    found = requests_from(token, 2)
    return found[1] if found else None


def wait_for(read, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = read()
        if found is not None:
            return found
        time.sleep(2)
    return None


def exists(path):
    return dexec("test", "-e", path).returncode == 0
