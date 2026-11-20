import re
import shlex
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
README = REPO_ROOT / "README.md"


def dockerfile_petta_ref():
    text = DOCKERFILE.read_text(encoding="utf-8")
    arg = re.search(r"^ARG\s+PETTA_REF=(\S+)\s*$", text, re.MULTILINE)
    uses_arg = re.search(
        r"git clone\b[^\n]*--branch\s+\"?\$\{PETTA_REF\}\"?", text
    )
    assert arg and uses_arg, (
        "PeTTa pin not found in Dockerfile: expected ARG PETTA_REF=<ref> "
        "and git clone --branch \"${PETTA_REF}\""
    )
    return arg.group(1).strip("\"'")


def readme_petta_clones():
    clones = []
    pending = None
    for number, line in enumerate(
        README.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if pending is None:
            pending = (number, "")
        start, text = pending
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            pending = (start, text + stripped[:-1].rstrip() + " ")
            continue
        command = (text + stripped).strip()
        pending = None
        for fragment in re.split(r"&&|\|\||;|\|", command):
            fragment = fragment.strip()
            if "git clone" in fragment and "trueagi-io/PeTTa" in fragment:
                clones.append((start, fragment))
    return clones


def clone_ref(command):
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens):
        if token in ("--branch", "-b") and index + 1 < len(tokens):
            return tokens[index + 1].strip("\"'")
        if token.startswith("--branch="):
            return token.split("=", 1)[1].strip("\"'")
    return None


def test_readme_clones_petta_at_dockerfile_pin():
    pin = dockerfile_petta_ref()
    clones = readme_petta_clones()
    assert clones, "README has no git clone command for trueagi-io/PeTTa"
    for number, command in clones:
        ref = clone_ref(command)
        if ref is None:
            raise AssertionError(
                f"README.md:{number} clones PeTTa without --branch, "
                f"Dockerfile pins {pin!r}: {command}"
            )
        assert ref == pin, (
            f"README.md:{number} clones PeTTa at {ref!r}, "
            f"Dockerfile pins {pin!r}: {command}"
        )
