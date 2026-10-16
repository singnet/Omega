import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "omega"
IMAGE = "test/omega:new"
MIGRATION_LABEL = "omega.memory-migration"

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
mounts_dir = root / "mounts"
labels_dir = root / "labels"
args = sys.argv[1:]

with open(root / "calls.log", "a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")


def volume(name):
    return volumes / name


def containers_using(name):
    return sorted(
        path.name for path in mounts_dir.iterdir()
        if name in path.read_text().split()
    )


if args[:2] == ["volume", "inspect"]:
    sys.exit(0 if volume(args[2]).is_dir() else 1)
if args[:2] == ["volume", "create"]:
    volume(args[2]).mkdir(parents=True, exist_ok=True)
    print(args[2])
    sys.exit(0)
if args[:2] == ["volume", "rm"]:
    if os.environ.get("FAKE_DOCKER_FAIL_VOLUME_RM") or not volume(args[2]).is_dir():
        sys.exit(1)
    users = containers_using(args[2])
    if users:
        ids = ", ".join(format(abs(hash(user)), "x") for user in users)
        print(f"Error response from daemon: remove {args[2]}: volume is in use - [{ids}]", file=sys.stderr)
        sys.exit(1)
    shutil.rmtree(volume(args[2]))
    sys.exit(0)
if args[:1] == ["rm"]:
    name = args[-1]
    if not (containers / name).exists():
        print(f"Error response from daemon: No such container: {name}", file=sys.stderr)
        sys.exit(0 if "-f" in args else 1)
    (containers / name).unlink()
    (mounts_dir / name).unlink(missing_ok=True)
    (labels_dir / name).unlink(missing_ok=True)
    sys.exit(0)
if args[:1] == ["ps"]:
    filters = [args[index + 1].split("=", 1) for index, option in enumerate(args) if option == "--filter"]
    names = sorted(path.name for path in containers.iterdir())
    for key, value in filters:
        if key == "volume":
            names = [user for user in containers_using(value) if user in names]
        elif key == "label":
            names = [name for name in names
                     if (labels_dir / name).exists() and value in (labels_dir / name).read_text().split()]
    print("\n".join(names))
    sys.exit(0)
if args[:2] == ["container", "inspect"]:
    sys.exit(0 if (containers / args[-1]).exists() else 1)
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
    container_name = None
    index = 1
    while index < len(args):
        option = args[index]
        if option in ("--volume", "-v"):
            source, target = args[index + 1].split(":")[:2]
            mounts[target] = source
            index += 2
        elif option in ("--entrypoint", "--user", "--group-add", "-e", "--name", "--security-opt", "--tmpfs", "--label"):
            if option == "--entrypoint":
                entrypoint = args[index + 1]
            if option == "--name":
                container_name = args[index + 1]
            index += 2
        elif option.startswith("-"):
            index += 1
        else:
            break
    command = args[index + 1:]
    sources = set(mounts.values())
    if os.environ.get("FAKE_DOCKER_FAIL_MARKER_CHECK") and "echo migrated" in " ".join(command):
        sys.exit(1)
    if os.environ.get("FAKE_DOCKER_FAIL_COPY") and {"omegaclaw-memory", "omega-memory"} <= sources:
        sys.exit(1)
    for target, source in mounts.items():
        if "/" in source:
            continue
        volume(source).mkdir(parents=True, exist_ok=True)
        if target == MEMORY_PATH and not any(volume(source).iterdir()):
            shutil.copytree(root / "image-memory", volume(source), dirs_exist_ok=True)
    if container_name:
        (containers / container_name).write_text("running")
        (mounts_dir / container_name).write_text(
            "\n".join(source for source in mounts.values() if "/" not in source)
        )
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
    (root / "mounts").mkdir()
    (root / "labels").mkdir()
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


def _launcher(root, *arguments, fail_copy=False, fail_cp=False, fail_volume_rm=False, fail_marker_check=False):
    environment = os.environ.copy()
    environment["PATH"] = f"{root.parent / 'bin'}{os.pathsep}{environment['PATH']}"
    environment["FAKE_DOCKER_ROOT"] = str(root)
    environment["ASI_API_KEY"] = "test-token"
    if fail_copy:
        environment["FAKE_DOCKER_FAIL_COPY"] = "1"
    if fail_cp:
        environment["FAKE_DOCKER_CP_FAILS"] = "1"
    if fail_volume_rm:
        environment["FAKE_DOCKER_FAIL_VOLUME_RM"] = "1"
    if fail_marker_check:
        environment["FAKE_DOCKER_FAIL_MARKER_CHECK"] = "1"
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


def _memory_import_arguments(docker_root, tmp_path):
    transfer = tmp_path / "transfer"
    transfer.mkdir()
    transfer.chmod(0o2770)
    (transfer / "memory.tar.gz").touch()
    python3 = docker_root.parent / "bin" / "python3"
    python3.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *omega-memory-transfer-validator*) exit 0 ;;\n"
        "esac\n"
        f"exec {sys.executable!s} \"$@\"\n",
        encoding="utf-8",
    )
    python3.chmod(0o755)
    return (
        "start",
        "-d",
        IMAGE,
        "--memory-transfer-dir",
        str(transfer),
        "--memory-transfer-gid",
        str(transfer.stat().st_gid),
        "--memory-import",
        "memory.tar.gz",
    )


def test_memory_import_skips_migration(docker_root, tmp_path):
    _install_omegaclaw(docker_root)

    result = _launcher(docker_root, *_memory_import_arguments(docker_root, tmp_path))

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


def _interrupted_migration(root, image_files):
    old = _install_omegaclaw(root, running=False)
    (old / ".migration-started").write_text("")
    new = root / "volumes" / "omega-memory"
    new.mkdir()
    if image_files:
        shutil.copytree(root / "image-memory", new, dirs_exist_ok=True)
    return old, new


def test_interrupted_copy_is_redone(docker_root):
    old, new = _interrupted_migration(docker_root, image_files=True)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _read(new / "history.metta") == "(old history)\n"
    assert _read(new / "chroma_db" / "chroma.sqlite3") == "old long-term memory"
    assert _read(new / "prompt.txt") == "omega prompt\n"
    assert (old / ".migrated-to-omega").exists()
    assert _started_agent(docker_root)


def _container_on_volume(root, name, state, volume_names, label=None):
    (root / "containers" / name).write_text(state)
    (root / "mounts" / name).write_text(volume_names)
    if label:
        (root / "labels" / name).write_text(label)


@pytest.mark.parametrize("state", ["exited", "running"])
def test_interrupted_copy_is_redone_while_omega_container_holds_new_volume(docker_root, state):
    old, new = _interrupted_migration(docker_root, image_files=True)
    _container_on_volume(docker_root, "omega", state, "omega-memory")

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert "volume is in use" not in result.stderr
    assert "Removed container omega, it used the partly copied volume omega-memory" in result.stdout
    assert _read(new / "history.metta") == "(old history)\n"
    assert _read(new / "chroma_db" / "chroma.sqlite3") == "old long-term memory"
    assert (old / ".migrated-to-omega").exists()
    assert _started_agent(docker_root)


def test_interrupted_copy_names_other_containers_on_new_volume(docker_root):
    old, new = _interrupted_migration(docker_root, image_files=True)
    _container_on_volume(docker_root, "omega-leftover", "exited", "omega-memory")
    before = _snapshot(new)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode != 0
    assert "omega-leftover" in result.stderr
    assert _snapshot(new) == before
    assert (docker_root / "containers" / "omega-leftover").exists()
    assert not (old / ".migrated-to-omega").exists()
    assert not _started_agent(docker_root)


def test_interrupted_copy_keeps_omega_while_another_container_holds_the_volume(docker_root):
    old, new = _interrupted_migration(docker_root, image_files=True)
    _container_on_volume(docker_root, "omega", "running", "omega-memory")
    _container_on_volume(docker_root, "omega-leftover", "exited", "omega-memory")
    before = _snapshot(new)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode != 0
    assert "it is used by containers: omega-leftover." in result.stderr
    assert _container_state(docker_root, "omega") == "running"
    assert _snapshot(new) == before
    assert not _started_agent(docker_root)


def test_interrupted_copy_removes_leftover_copy_containers(docker_root):
    old, new = _interrupted_migration(docker_root, image_files=True)
    _container_on_volume(docker_root, "musing_haslett", "running", "omegaclaw-memory omega-memory", label=MIGRATION_LABEL)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _read(new / "history.metta") == "(old history)\n"
    assert (old / ".migrated-to-omega").exists()
    assert not (docker_root / "containers" / "musing_haslett").exists()
    assert _started_agent(docker_root)


def test_interrupted_copy_keeps_labelled_containers_on_other_volumes(docker_root):
    old, new = _interrupted_migration(docker_root, image_files=True)
    _container_on_volume(docker_root, "other_copier", "running", "omegaclaw-memory", label=MIGRATION_LABEL)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _read(new / "history.metta") == "(old history)\n"
    assert (docker_root / "containers" / "other_copier").exists()


def test_migration_containers_carry_the_label(docker_root):
    _install_omegaclaw(docker_root)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    helper_runs = [call for call in _calls(docker_root) if call.startswith("run --rm")]
    assert len(helper_runs) >= 4
    assert all(f"--label {MIGRATION_LABEL}" in call for call in helper_runs)


def test_memory_import_replaces_an_interrupted_copy(docker_root, tmp_path):
    old, new = _interrupted_migration(docker_root, image_files=True)
    (new / "history.metta").write_text("(partly copied)\n")
    _container_on_volume(docker_root, "omega", "exited", "omega-memory")

    result = _launcher(docker_root, *_memory_import_arguments(docker_root, tmp_path))

    assert result.returncode == 0, result.stderr
    assert _read(new / "history.metta") == ""
    assert not (old / ".migration-started").exists()
    assert not (old / ".migrated-to-omega").exists()
    assert _started_agent(docker_root)

    (new / "history.metta").write_text("(imported and used)\n")
    again = _launcher(docker_root, "start", "-d", IMAGE)

    assert again.returncode == 0, again.stderr
    assert _read(new / "history.metta") == "(imported and used)\n"


def test_memory_import_keeps_the_interrupted_state_when_the_volume_cannot_be_removed(docker_root, tmp_path):
    old, new = _interrupted_migration(docker_root, image_files=True)
    (new / "history.metta").write_text("(partly copied)\n")

    result = _launcher(docker_root, *_memory_import_arguments(docker_root, tmp_path), fail_volume_rm=True)

    assert result.returncode != 0
    assert (old / ".migration-started").exists()
    assert _read(new / "history.metta") == "(partly copied)\n"
    assert not _started_agent(docker_root)


def test_run_interrupted_before_the_image_files_is_redone(docker_root):
    old, new = _interrupted_migration(docker_root, image_files=False)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _read(new / "history.metta") == "(old history)\n"
    assert _read(new / "prompt.txt") == "omega prompt\n"
    assert _started_agent(docker_root)


def test_start_marker_stays_out_of_new_volume(docker_root):
    _install_omegaclaw(docker_root)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert not (docker_root / "volumes" / "omega-memory" / ".migration-started").exists()


def test_copy_is_redone_after_new_volume_could_not_be_removed(docker_root):
    old = _install_omegaclaw(docker_root, running=True)

    failed = _launcher(docker_root, "start", "-d", IMAGE, fail_copy=True, fail_volume_rm=True)

    assert failed.returncode != 0
    assert (old / ".migration-started").exists()
    assert not _started_agent(docker_root)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _read(docker_root / "volumes" / "omega-memory" / "history.metta") == "(old history)\n"
    assert _started_agent(docker_root)


def test_start_stops_when_markers_cannot_be_read(docker_root):
    _, new = _interrupted_migration(docker_root, image_files=True)
    before = _snapshot(new)

    result = _launcher(docker_root, "start", "-d", IMAGE, fail_marker_check=True)

    assert result.returncode != 0
    assert not _started_agent(docker_root)
    assert _snapshot(new) == before


def test_memory_import_stops_when_markers_cannot_be_read(docker_root, tmp_path):
    old, new = _interrupted_migration(docker_root, image_files=True)
    (new / "history.metta").write_text("(partly copied)\n")
    before = _snapshot(new)

    result = _launcher(docker_root, *_memory_import_arguments(docker_root, tmp_path), fail_marker_check=True)

    assert result.returncode != 0
    assert "Could not read the migration markers" in result.stderr
    assert (old / ".migration-started").exists()
    assert _snapshot(new) == before
    assert not _started_agent(docker_root)


@pytest.mark.parametrize("history", ["(old hi", None])
def test_interrupted_copy_with_partly_copied_history_is_redone(docker_root, history):
    old, new = _interrupted_migration(docker_root, image_files=True)
    if history is None:
        (new / "history.metta").unlink()
    else:
        (new / "history.metta").write_text(history)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode == 0, result.stderr
    assert _read(new / "history.metta") == "(old history)\n"
    assert (old / ".migrated-to-omega").exists()
    assert _started_agent(docker_root)


@pytest.mark.parametrize("history", ["(imported and used)\n", "(old history)\n(used after import)\n"])
def test_interrupted_copy_keeps_memory_that_is_not_a_partial_copy(docker_root, history):
    old, new = _interrupted_migration(docker_root, image_files=True)
    (new / "history.metta").write_text(history)
    _container_on_volume(docker_root, "omega", "exited", "omega-memory")
    before = _snapshot(new)

    result = _launcher(docker_root, "start", "-d", IMAGE)

    assert result.returncode != 0
    assert "docker volume rm omega-memory" in result.stderr
    assert ".migration-started" in result.stderr
    assert _snapshot(new) == before
    assert (old / ".migration-started").exists()
    assert _container_state(docker_root, "omega") == "exited"
    assert not _started_agent(docker_root)
