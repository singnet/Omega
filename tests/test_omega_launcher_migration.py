import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "omega"
IMAGE = "test/omega:new"

FAKE_DOCKER = r'''#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MEMORY_PATH = "/PeTTa/repos/Omega/memory"
root = Path(os.environ["FAKE_DOCKER_ROOT"])
volumes = root / "volumes"
containers = root / "containers"
args = sys.argv[1:]

with open(root / "calls.log", "a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")


def volume(name):
    return volumes / name


if args[:2] == ["volume", "inspect"]:
    sys.exit(0 if volume(args[2]).is_dir() else 1)
if args[:2] == ["volume", "create"]:
    volume(args[2]).mkdir(parents=True, exist_ok=True)
    print(args[2])
    sys.exit(0)
if args[:2] == ["volume", "rm"]:
    if not volume(args[2]).is_dir():
        sys.exit(1)
    shutil.rmtree(volume(args[2]))
    sys.exit(0)
if args[:1] == ["inspect"]:
    state = containers / args[-1]
    if not state.exists():
        sys.exit(1)
    print("true" if state.read_text().strip() == "running" else "false")
    sys.exit(0)
if args[:1] in (["stop"], ["start"]):
    state = containers / args[-1]
    if not state.exists():
        sys.exit(1)
    state.write_text("running" if args[0] == "start" else "exited")
    sys.exit(0)
if args[:1] == ["run"]:
    mounts = {}
    entrypoint = None
    index = 1
    while index < len(args):
        option = args[index]
        if option in ("--volume", "-v"):
            source, target = args[index + 1].split(":")[:2]
            mounts[target] = source
            index += 2
        elif option in ("--entrypoint", "--user", "-e", "--name", "--security-opt", "--tmpfs"):
            if option == "--entrypoint":
                entrypoint = args[index + 1]
            index += 2
        elif option.startswith("-"):
            index += 1
        else:
            break
    command = args[index + 1:]
    sources = set(mounts.values())
    if os.environ.get("FAKE_DOCKER_FAIL_COPY") and {"omegaclaw-memory", "omega-memory"} <= sources:
        sys.exit(1)
    for target, source in mounts.items():
        if "/" in source:
            continue
        volume(source).mkdir(parents=True, exist_ok=True)
        if target == MEMORY_PATH and not any(volume(source).iterdir()):
            shutil.copytree(root / "image-memory", volume(source), dirs_exist_ok=True)
    if entrypoint == "sh" and command[:1] == ["-c"]:
        script = command[1]
        for target in sorted(mounts, key=len, reverse=True):
            script = re.sub(re.escape(target) + r"(?=[/\"'\s;]|$)", str(volume(mounts[target])), script)
        environment = os.environ.copy()
        environment["TMPDIR"] = str(root)
        if os.environ.get("FAKE_DOCKER_CP_FAILS") and {"omegaclaw-memory", "omega-memory"} <= sources:
            failing_bin = root / "failing-bin"
            failing_bin.mkdir(exist_ok=True)
            failing_cp = failing_bin / "cp"
            failing_cp.write_text(
                "#!/bin/sh\n"
                f"if [ ! -e '{root / 'cp-failed'}' ]; then\n"
                f"    : > '{root / 'cp-failed'}'\n"
                "    echo 'cp: No space left on device' >&2\n"
                "    exit 1\n"
                "fi\n"
                f"exec '{shutil.which('cp')}' \"$@\"\n"
            )
            failing_cp.chmod(0o755)
            environment["PATH"] = f"{failing_bin}{os.pathsep}{environment['PATH']}"
        sys.exit(subprocess.run(["sh", "-c", script], env=environment).returncode)
sys.exit(0)
'''


@pytest.fixture
def docker_root(tmp_path):
    root = tmp_path / "docker"
    (root / "volumes").mkdir(parents=True)
    (root / "containers").mkdir()
    image_memory = root / "image-memory"
    (image_memory / "chroma_db").mkdir(parents=True)
    (image_memory / "history.metta").write_text("")
    (image_memory / "prompt.txt").write_text("omega prompt\n")
    (image_memory / "prompt_ASICloud.txt").write_text("omega asicloud prompt\n")
    (image_memory / "tg_prompt.txt").write_text("omega telegram prompt\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    return root


def _install_omegaclaw(root, running=True):
    old = root / "volumes" / "omegaclaw-memory"
    (old / "chroma_db").mkdir(parents=True)
    (old / "chroma_db" / "chroma.sqlite3").write_text("old long-term memory")
    (old / ".channel").mkdir()
    (old / ".channel" / "authenticated-user.json").write_text('{"user": "owner"}')
    (old / "history.metta").write_text("(old history)\n")
    (old / "prompt.txt").write_text("omegaclaw prompt\n")
    (old / "prompt_ASICloud.txt").write_text("omegaclaw asicloud prompt\n")
    (old / "saved note.txt").write_text("kept by the agent")
    (root / "containers" / "omegaclaw").write_text("running" if running else "exited")
    return old


def _snapshot(directory):
    return {
        str(path.relative_to(directory)): path.read_text() if path.is_file() else None
        for path in sorted(directory.rglob("*"))
    }


def _launcher(root, *arguments, fail_copy=False, fail_cp=False):
    environment = os.environ.copy()
    environment["PATH"] = f"{root.parent / 'bin'}{os.pathsep}{environment['PATH']}"
    environment["FAKE_DOCKER_ROOT"] = str(root)
    environment["ASI_API_KEY"] = "test-token"
    if fail_copy:
        environment["FAKE_DOCKER_FAIL_COPY"] = "1"
    if fail_cp:
        environment["FAKE_DOCKER_CP_FAILS"] = "1"
    return subprocess.run(
        [str(LAUNCHER), *arguments],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _calls(root):
    log = root / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _started_agent(root):
    return any(call.startswith("run -d") for call in _calls(root))


def _read(path):
    return path.read_text() if path.is_file() else None


def _container_state(root, name):
    return (root / "containers" / name).read_text()


def test_first_start_copies_old_memory_except_prompts(docker_root):
    _install_omegaclaw(docker_root)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    new = docker_root / "volumes" / "omega-memory"
    assert _read(new / "history.metta") == "(old history)\n"
    assert _read(new / "chroma_db" / "chroma.sqlite3") == "old long-term memory"
    assert _read(new / ".channel" / "authenticated-user.json") == '{"user": "owner"}'
    assert _read(new / "saved note.txt") == "kept by the agent"
    assert _read(new / "prompt.txt") == "omega prompt\n"
    assert _read(new / "prompt_ASICloud.txt") == "omega asicloud prompt\n"
    assert _read(new / "tg_prompt.txt") == "omega telegram prompt\n"
    assert _started_agent(docker_root)


def test_first_start_keeps_old_volume_contents(docker_root):
    old = _install_omegaclaw(docker_root)
    before = _snapshot(old)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    after = _snapshot(old)
    assert {path: after[path] for path in before} == before


def test_first_start_stops_running_old_container_before_copy(docker_root):
    _install_omegaclaw(docker_root, running=True)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _container_state(docker_root, "omegaclaw") == "exited"
    calls = _calls(docker_root)
    assert calls.index("stop omegaclaw") < calls.index("volume create omega-memory")


def test_stopped_old_container_stays_stopped(docker_root):
    _install_omegaclaw(docker_root, running=False)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _container_state(docker_root, "omegaclaw") == "exited"
    assert _read(docker_root / "volumes" / "omega-memory" / "history.metta") == "(old history)\n"


def test_start_after_clean_does_not_bring_old_memory_back(docker_root):
    _install_omegaclaw(docker_root)
    assert _launcher(docker_root, "start", "-d", IMAGE).returncode == 0
    assert _launcher(docker_root, "clean").returncode == 0

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _read(docker_root / "volumes" / "omega-memory" / "history.metta") == ""


def test_existing_new_volume_is_left_untouched(docker_root):
    _install_omegaclaw(docker_root)
    new = docker_root / "volumes" / "omega-memory"
    new.mkdir()
    (new / "history.metta").write_text("(new history)\n")

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _snapshot(new) == {"history.metta": "(new history)\n"}
    assert _container_state(docker_root, "omegaclaw") == "running"


def test_without_old_volume_agent_starts_on_image_memory(docker_root):
    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _started_agent(docker_root)
    assert _snapshot(docker_root / "volumes" / "omega-memory") == _snapshot(docker_root / "image-memory")
    assert not (docker_root / "volumes" / "omegaclaw-memory").exists()


def test_memory_import_skips_migration(docker_root, tmp_path):
    _install_omegaclaw(docker_root)
    transfer = tmp_path / "transfer"
    transfer.mkdir()
    (transfer / "memory.tar.gz").touch()

    result = _launcher(
        docker_root,
        "start",
        "-d",
        IMAGE,
        "--memory-transfer-dir",
        str(transfer),
        "--memory-import",
        "memory.tar.gz",
    )

    assert result.returncode == 0, result.stderr
    assert _read(docker_root / "volumes" / "omega-memory" / "history.metta") == ""
    assert _container_state(docker_root, "omegaclaw") == "running"


def test_failed_copy_restores_previous_state(docker_root):
    old = _install_omegaclaw(docker_root, running=True)
    before = _snapshot(old)

    result = _launcher(docker_root, "start", "-d", IMAGE, fail_copy=True)

    assert result.returncode != 0
    assert not (docker_root / "volumes" / "omega-memory").exists()
    assert _container_state(docker_root, "omegaclaw") == "running"
    assert _snapshot(old) == before
    assert not _started_agent(docker_root)


def test_failed_file_copy_restores_previous_state(docker_root):
    old = _install_omegaclaw(docker_root, running=True)
    before = _snapshot(old)

    result = _launcher(docker_root, "start", "-d", IMAGE, fail_cp=True)

    assert result.returncode != 0
    assert not (docker_root / "volumes" / "omega-memory").exists()
    assert _container_state(docker_root, "omegaclaw") == "running"
    assert _snapshot(old) == before
    assert not _started_agent(docker_root)


def test_telegram_prompt_comes_from_image(docker_root):
    old = _install_omegaclaw(docker_root)
    (old / "tg_prompt.txt").write_text("dev build telegram prompt\n")

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _read(docker_root / "volumes" / "omega-memory" / "tg_prompt.txt") == "omega telegram prompt\n"


def test_image_without_omega_memory_layout_aborts(docker_root):
    old = _install_omegaclaw(docker_root, running=True)
    before = _snapshot(old)
    shutil.rmtree(docker_root / "image-memory")
    (docker_root / "image-memory").mkdir()

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode != 0
    assert not (docker_root / "volumes" / "omega-memory").exists()
    assert _container_state(docker_root, "omegaclaw") == "running"
    assert _snapshot(old) == before
    assert not _started_agent(docker_root)
