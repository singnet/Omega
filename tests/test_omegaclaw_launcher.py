import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "omega"
CONTAINER_TEST_IMAGE = os.environ.get("OMEGA_LAUNCHER_TEST_IMAGE", "")
FAKE_DOCKER = """\
#!/bin/sh
version_path=""
for arg in "$@"; do
  case "$arg" in
    /PeTTa/repos/Omega/version|/PeTTa/repos/OmegaClaw-Core/version)
      version_path="$arg"
      ;;
  esac
done
if [ -n "$version_path" ]; then
  case "$version_path" in
    /PeTTa/repos/Omega/version)
      if [ -n "${OMEGA_TEST_OMEGA_VERSION+x}" ]; then
        printf '%s\\n' "${OMEGA_TEST_OMEGA_VERSION}"
      else
        printf '%s\\n' "${OMEGA_TEST_IMAGE_VERSION}"
      fi
      ;;
    *)
      printf '%s\\n' "${OMEGA_TEST_LEGACY_VERSION}"
      ;;
  esac
  exit 0
fi
printf 'docker'
printf ' <%s>' "$@"
printf '\\n'
"""


def _host_omega_version() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "describe", "--tags", "--dirty", "--always"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _load_installer_namespace():
    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    installer_source = launcher_source.split("cat >\"$tmp_py_file\" <<'PY'\n", 1)[1].split(
        "\nPY\n", 1
    )[0]
    namespace = {"__name__": "omega_installer"}
    exec(compile(installer_source, str(LAUNCHER), "exec"), namespace)
    return namespace


def _stub_docker_environment(
    tmp_path: Path, transfer_gid: int | None = None, stub_runtime_validator: bool = True
) -> dict:
    if transfer_gid is None:
        transfer_gid = tmp_path.stat().st_gid
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    uname = bin_dir / "uname"
    uname.write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
    uname.chmod(0o755)
    if stub_runtime_validator:
        python3 = bin_dir / "python3"
        python3.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  *omega-memory-transfer-validator*) exit 0 ;;\n"
            "esac\n"
            f"exec {sys.executable!s} \"$@\"\n",
            encoding="utf-8",
        )
        python3.chmod(0o755)
    environment = os.environ.copy()
    environment["ASI_API_KEY"] = "test-token"
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    return environment


def _run_launcher(
    tmp_path: Path,
    *component_options: str,
    transfer_dir: Path | None = None,
    transfer_gid: int | None = None,
    memory_import: bool = True,
    stub_runtime_validator: bool = True,
    image_version: str | None = None,
    legacy_version: str | None = None,
) -> subprocess.CompletedProcess:
    if transfer_dir is None:
        transfer_dir = tmp_path
        transfer_dir.chmod(0o2770)
    transfer_gid = transfer_gid if transfer_gid is not None else transfer_dir.stat().st_gid
    launcher_options = [
        "--memory-transfer-dir",
        str(transfer_dir),
        "--memory-transfer-gid",
        str(transfer_gid),
    ]
    if memory_import:
        archive = transfer_dir / "memory.tar.gz"
        archive.touch()
        launcher_options.extend(["--memory-import", archive.name])

    environment = _stub_docker_environment(
        tmp_path, transfer_gid, stub_runtime_validator=stub_runtime_validator
    )
    if legacy_version is not None:
        environment["OMEGA_TEST_OMEGA_VERSION"] = ""
        environment["OMEGA_TEST_LEGACY_VERSION"] = legacy_version
    else:
        environment["OMEGA_TEST_IMAGE_VERSION"] = (
            image_version if image_version is not None else _host_omega_version()
        )

    return subprocess.run(
        [
            str(LAUNCHER),
            "start",
            *launcher_options,
            *component_options,
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_runtime_validator(tmp_path: Path, transfer_dir: str, transfer_gid: int) -> subprocess.CompletedProcess:
    environment = _stub_docker_environment(
        tmp_path, transfer_gid, stub_runtime_validator=False
    )
    return subprocess.run(
        [
            str(LAUNCHER),
            "start",
            "--memory-transfer-dir",
            transfer_dir,
            "--memory-transfer-gid",
            str(transfer_gid),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_installer_records_private_group_for_existing_transfer_directory(tmp_path, monkeypatch):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    group_id = transfer_dir.stat().st_gid
    answers = iter(["y", str(transfer_dir), str(group_id), "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    installer = _load_installer_namespace()
    monkeypatch.setitem(installer, "validate_memory_transfer_dir", lambda *_: None)
    memory_transfer_dir, memory_transfer_gid, memory_export_enabled = installer["_choose_memory_transfer"]()

    assert memory_transfer_dir == str(transfer_dir)
    assert memory_transfer_gid == str(group_id)
    assert memory_export_enabled == "0"


def test_installer_explains_how_to_skip_unprepared_transfer_directory(tmp_path, monkeypatch, capsys):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    group_id = transfer_dir.stat().st_gid
    answers = iter(["y", str(transfer_dir), str(group_id)])
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or next(answers))
    installer = _load_installer_namespace()
    monkeypatch.setitem(
        installer,
        "validate_memory_transfer_dir",
        lambda *_: "--memory-transfer-dir must enable setgid",
    )

    with pytest.raises(StopIteration):
        installer["_choose_memory_transfer"]()

    assert "Enable memory export for this instance? [y/N]: " not in prompts
    error_output = capsys.readouterr().err
    assert "answer n at the next prompt to continue without memory transfer" in error_output
    assert "docs/reference-memory-portability.md" in error_output


def test_installer_uses_shared_memory_transfer_validator(tmp_path, monkeypatch):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    group_id = transfer_dir.stat().st_gid
    installer = _load_installer_namespace()
    captured = {}
    monkeypatch.setattr(
        installer["subprocess"],
        "run",
        lambda command, **kwargs: captured.update(command=command, kwargs=kwargs)
        or SimpleNamespace(returncode=0, stderr=""),
    )
    monkeypatch.setattr(installer["sys"], "argv", ["installer", "config", "", "", "", "validator"])

    assert installer["validate_memory_transfer_dir"](
        str(transfer_dir), str(group_id)
    ) is None
    assert captured["command"] == [
        sys.executable,
        "validator",
        str(transfer_dir),
        str(group_id),
    ]
    assert captured["kwargs"] == {"capture_output": True, "text": True, "check": False}


def test_installer_reports_shared_memory_transfer_validator_error(tmp_path, monkeypatch):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    installer = _load_installer_namespace()
    monkeypatch.setattr(
        installer["subprocess"],
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stderr="--memory-transfer-dir is supported only on Linux hosts\n"
        ),
    )
    monkeypatch.setattr(installer["sys"], "argv", ["installer", "config", "", "", "", "validator"])

    assert installer["validate_memory_transfer_dir"](
        str(transfer_dir), str(transfer_dir.stat().st_gid)
    ) == "--memory-transfer-dir is supported only on Linux hosts"


def test_launcher_uses_private_group_for_preflight_and_entrypoint(tmp_path):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    transfer_dir.chmod(0o2770)

    result = _run_launcher(tmp_path, transfer_dir=transfer_dir, memory_import=False)

    assert result.returncode == 0, result.stderr
    group_id = transfer_dir.stat().st_gid
    assert f"<--user> <65534:65534> <--group-add> <{group_id}>" in result.stdout
    assert f"<-e> <MEMORY_TRANSFER_GID={group_id}>" in result.stdout


@pytest.mark.skipif(sys.platform != "linux", reason="memory transfer directories are Linux-only")
def test_launcher_executes_runtime_memory_transfer_validation(tmp_path):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    transfer_dir.chmod(0o750)

    result = _run_launcher(
        tmp_path,
        transfer_dir=transfer_dir,
        memory_import=False,
        stub_runtime_validator=False,
    )

    assert result.returncode == 1
    assert "--memory-transfer-dir must enable setgid" in result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="memory transfer directories are Linux-only")
def test_launcher_rejects_root_as_transfer_group(tmp_path):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    transfer_dir.chmod(0o2770)

    result = _run_runtime_validator(tmp_path, str(transfer_dir), 0)

    assert result.returncode == 1
    assert "--memory-transfer-gid must be a non-zero numeric private group ID" in result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="memory transfer directories are Linux-only")
def test_launcher_rejects_symlink_with_trailing_slash(tmp_path):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    transfer_dir.chmod(0o2770)
    transfer_link = tmp_path / "memory-transfer-link"
    transfer_link.symlink_to(transfer_dir, target_is_directory=True)

    result = _run_runtime_validator(
        tmp_path, f"{transfer_link}/", transfer_dir.stat().st_gid
    )

    assert result.returncode == 1
    assert "--memory-transfer-dir must not be a symbolic link" in result.stderr


def test_launcher_warns_before_overwrite_memory_import(tmp_path):
    result = _run_launcher(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "WARNING: --memory-mode overwrite will replace the selected current memory components" in result.stderr


def test_launcher_does_not_warn_for_append_memory_import(tmp_path):
    result = _run_launcher(tmp_path, "--memory-mode", "append")

    assert result.returncode == 0, result.stderr
    assert "WARNING:" not in result.stderr


def test_entrypoint_resolves_transfer_gid_to_a_supplementary_group_name():
    entrypoint = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'getent group "${MEMORY_TRANSFER_GID}" 2>/dev/null || true' in entrypoint
    assert 'groupadd --gid "${MEMORY_TRANSFER_GID}" "${memory_transfer_group}"' in entrypoint
    assert 'su --group nogroup --supp-group "${memory_transfer_group}" nobody' in entrypoint


def test_entrypoint_rejects_root_as_transfer_group():
    entrypoint = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert '[[ ! "${MEMORY_TRANSFER_GID}" =~ ^[1-9][0-9]*$ ]]' in entrypoint


@pytest.mark.skipif(
    sys.platform != "linux" or not CONTAINER_TEST_IMAGE or shutil.which("docker") is None,
    reason="needs Linux, Docker, and OMEGA_LAUNCHER_TEST_IMAGE",
)
def test_container_user_can_write_group_protected_transfer_directory(tmp_path):
    transfer_dir = tmp_path / "memory-transfer"
    transfer_dir.mkdir()
    transfer_dir.chmod(0o2770)

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "65534:65534",
            "--group-add",
            str(transfer_dir.stat().st_gid),
            "--entrypoint",
            "/bin/sh",
            "--volume",
            f"{transfer_dir}:/memory-transfer",
            CONTAINER_TEST_IMAGE,
            "-c",
            (
                "touch /memory-transfer/probe && "
                f"test \"$(stat -c %g /memory-transfer/probe)\" = \"{transfer_dir.stat().st_gid}\" && "
                "rm /memory-transfer/probe"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("option", "included_environment", "excluded_environment"),
    [
        ("--only-history", "MEMORY_IMPORT_NO_VECTOR=1", "MEMORY_IMPORT_NO_HISTORY=1"),
        ("--only-vector", "MEMORY_IMPORT_NO_HISTORY=1", "MEMORY_IMPORT_NO_VECTOR=1"),
    ],
)
def test_only_component_options_select_one_import_component(
    tmp_path,
    option,
    included_environment,
    excluded_environment,
):
    result = _run_launcher(tmp_path, option)

    assert result.returncode == 0, result.stderr
    assert included_environment in result.stdout
    assert excluded_environment not in result.stdout


def test_only_component_options_are_mutually_exclusive(tmp_path):
    result = _run_launcher(tmp_path, "--only-history", "--only-vector")

    assert result.returncode != 0
    assert "--only-history and --only-vector cannot be combined" in result.stderr


@pytest.mark.parametrize("command", ["start", "stop", "clean"])
@pytest.mark.parametrize(
    ("flag", "expected_output"),
    [
        ("-h", "Usage:"),
        ("--help", "Usage:"),
        ("-v", "Omega version="),
        ("--version", "Omega version="),
    ],
)
def test_help_and_version_flags_do_not_run_the_command(tmp_path, command, flag, expected_output):
    result = subprocess.run(
        [str(LAUNCHER), command, flag],
        cwd=REPO_ROOT,
        env=_stub_docker_environment(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert expected_output in result.stdout
    assert "docker <" not in result.stdout


@pytest.mark.parametrize("removed_option", ["--no-history", "--no-vector"])
def test_removed_component_options_are_rejected(tmp_path, removed_option):
    result = _run_launcher(tmp_path, removed_option)

    assert result.returncode != 0
    assert "Usage:" in result.stdout
    assert "docker <" not in result.stdout


def test_matching_image_version_allows_start(tmp_path):
    result = _run_launcher(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "docker <rm>" in result.stdout
    assert "docker <run>" in result.stdout
    assert "The launcher script and Docker image versions do not match." not in result.stderr


def test_mismatched_image_version_aborts_before_container_replace(tmp_path):
    result = _run_launcher(tmp_path, image_version="v0.0.0-test")

    assert result.returncode != 0
    assert "The launcher script and Docker image versions do not match." in result.stderr
    assert "Omega version=v0.0.0-test" in result.stderr
    assert "docker <rm>" not in result.stdout
    assert "<--name>" not in result.stdout


def test_legacy_prefixed_image_version_prints_prefix_once(tmp_path):
    result = _run_launcher(tmp_path, image_version="Omega version=v0.0.0-test")

    assert result.returncode != 0
    assert "Omega version=v0.0.0-test" in result.stderr
    assert "Omega version=Omega version=" not in result.stderr
    assert "docker <rm>" not in result.stdout


def test_legacy_omegaclaw_prefix_prints_once(tmp_path):
    result = _run_launcher(tmp_path, image_version="OmegaClaw version=v0.1.19")

    assert result.returncode != 0
    assert "Image (singularitynet/omega:latest): Omega version=v0.1.19" in result.stderr
    assert "OmegaClaw version=" not in result.stderr
    assert "docker <rm>" not in result.stdout


def test_legacy_image_path_version_is_compared(tmp_path):
    result = _run_launcher(tmp_path, legacy_version="v0.0.0-test")

    assert result.returncode != 0
    assert "Omega version=v0.0.0-test" in result.stderr
    assert "Could not determine the Docker image version" not in result.stderr
    assert "docker <rm>" not in result.stdout
