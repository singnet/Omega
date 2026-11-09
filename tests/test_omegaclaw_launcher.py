import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "omega"
CONTAINER_TEST_IMAGE = os.environ.get("OMEGA_LAUNCHER_TEST_IMAGE", "")
UPLOAD_PREFIX_SIZE = 1024
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
    tmp_path: Path, script_version: str | None = None
) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    if script_version is not None:
        real_git = shutil.which("git")
        git = bin_dir / "git"
        git.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-C\" ] && [ \"$3\" = \"describe\" ]; then\n"
            f"  printf '%s\\n' {shlex.quote(script_version)}\n"
            "  exit 0\n"
            "fi\n"
            f"exec {shlex.quote(real_git)} \"$@\"\n",
            encoding="utf-8",
        )
        git.chmod(0o755)
    environment = os.environ.copy()
    environment["ASI_API_KEY"] = "test-token"
    environment["PATH"] = (
        f"{bin_dir}{os.pathsep}{Path(sys.executable).parent}"
        f"{os.pathsep}{environment['PATH']}"
    )
    return environment


def _run_launcher(
    tmp_path: Path,
    *options: str,
    memory_import: bool = True,
    image_version: str | None = None,
    legacy_version: str | None = None,
    script_version: str | None = None,
) -> subprocess.CompletedProcess:
    import_options = ["--memory-import", "memory.tar.gz"] if memory_import else []
    environment = _stub_docker_environment(tmp_path, script_version=script_version)
    if legacy_version is not None:
        environment["OMEGA_TEST_OMEGA_VERSION"] = ""
        environment["OMEGA_TEST_LEGACY_VERSION"] = legacy_version
    else:
        environment["OMEGA_TEST_IMAGE_VERSION"] = (
            image_version if image_version is not None else _host_omega_version()
        )
    return subprocess.run(
        [str(LAUNCHER), "start", *import_options, *options],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _memory_upload_command(directory: Path, size: int) -> list[str]:
    source = LAUNCHER.read_text(encoding="utf-8").split("memory_upload() {", 1)[1]
    script = source.split("memory_transfer_run rw -c '\n", 1)[1].split("\n' ", 1)[0]
    return [
        sys.executable, "-B", "-c", script.replace("/memory-transfer", str(directory)),
        "memory.tar.gz", str(size),
    ]


@pytest.fixture
def pending_upload(tmp_path):
    content = b"(memory archive)\x00\xff\n" * 8192
    command = _memory_upload_command(tmp_path, len(content))
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        process.stdin.write(content[:UPLOAD_PREFIX_SIZE])
        process.stdin.flush()
        deadline = time.monotonic() + 5
        while not any(tmp_path.rglob("*.tar.gz")):
            assert process.poll() is None
            if time.monotonic() >= deadline:
                pytest.fail("upload did not start")
            time.sleep(0.01)
        assert not (tmp_path / "memory.tar.gz").exists()
        yield process, command, content
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize("enabled", ["0", "1"])
def test_installer_preserves_volume_and_explicit_export_setting(tmp_path, monkeypatch, enabled):
    installer = _load_installer_namespace()
    monkeypatch.setitem(installer, "require_license_acceptance", lambda: None)
    monkeypatch.setitem(installer, "_choose_channel", lambda: {"commchannel": "test"})
    monkeypatch.setitem(
        installer, "_choose_provider", lambda: ("Test", "Local", "TEST_SERVER_IP", "", "", "localhost")
    )
    monkeypatch.setitem(installer, "_choose_import_kb", lambda: "0")
    monkeypatch.setattr(
        "builtins.input", lambda _: "n" if enabled == "0" else pytest.fail("unexpected prompt")
    )
    output = tmp_path / "config"

    installer["config_run_omega"](str(output), "test-archives", enabled)

    config = output.read_text(encoding="utf-8")
    assert "memory_transfer_volume_name=test-archives\n" in config
    assert f"memory_export_enabled={enabled}\n" in config


@pytest.mark.parametrize("export_enabled", [False, True])
@pytest.mark.parametrize("memory_import", [False, True])
def test_launcher_mounts_archive_volume_only_for_export_or_import(
    tmp_path, export_enabled, memory_import
):
    options = ["--memory-transfer-volume", "test-archives"]
    if export_enabled:
        options.append("--enable-memory-export")
    result = _run_launcher(
        tmp_path, *options, memory_import=memory_import
    )

    assert result.returncode == 0, result.stderr
    agent_run = next(
        line for line in result.stdout.splitlines()
        if line.startswith("docker <run> ") and "<--name> <omega>" in line
    )
    uses_archive_volume = export_enabled or memory_import
    assert (
        "<type=volume,source=test-archives,target=/memory-transfer>" in agent_run
    ) == uses_archive_volume
    if uses_archive_volume:
        assert "<--user> <65534:65534>" in result.stdout
    else:
        assert "/memory-transfer" not in result.stdout
    assert ("<memoryExportEnabled=true>" in agent_run) == export_enabled
    assert ("<MEMORY_IMPORT_FILE=memory.tar.gz>" in agent_run) == memory_import
    assert "MEMORY_TRANSFER_GID" not in result.stdout


@pytest.mark.parametrize("volume", ["/tmp/archives", "../archives", "archives:/host", "archives,readonly"])
def test_launcher_rejects_host_paths_as_volume_names(tmp_path, volume):
    result = _run_launcher(tmp_path, "--memory-transfer-volume", volume, memory_import=False)

    assert result.returncode != 0
    assert "must be a Docker volume name" in result.stderr
    assert "docker <" not in result.stdout


@pytest.mark.parametrize("volume", ["omega-memory", "omegaclaw-memory"])
def test_launcher_rejects_live_memory_volume_names(tmp_path, volume):
    result = _run_launcher(tmp_path, "--memory-transfer-volume", volume, memory_import=False)

    assert result.returncode != 0
    assert "must not use a live memory volume" in result.stderr
    assert "docker <" not in result.stdout


@pytest.mark.parametrize("option", ["--memory-transfer-dir", "--memory-transfer-gid"])
def test_launcher_explains_migration_from_bind_mount_options(tmp_path, option):
    result = _run_launcher(tmp_path, option, "old-value", memory_import=False)

    assert result.returncode != 0
    assert "has been replaced by --memory-transfer-volume" in result.stderr
    assert "docker <" not in result.stdout


def test_clean_preserves_memory_archives(tmp_path):
    result = subprocess.run(
        [str(LAUNCHER), "clean"], env=_stub_docker_environment(tmp_path), capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert "docker <volume> <rm> <omega-memory>" in result.stdout
    assert "omega-memory-transfer" not in result.stdout


@pytest.mark.parametrize("command", ["memory-download", "memory-delete"])
@pytest.mark.parametrize("filename", ["../memory.tar.gz", "/tmp/memory.tar.gz", "*.tar.gz", "memory.txt"])
def test_archive_commands_reject_invalid_filenames(tmp_path, command, filename):
    arguments = [filename]
    if command == "memory-download":
        arguments.append(str(tmp_path / "download"))
    result = subprocess.run(
        [str(LAUNCHER), command, *arguments],
        env=_stub_docker_environment(tmp_path), capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "must be a plain .tar.gz filename" in result.stderr
    assert "docker <" not in result.stdout


@pytest.mark.parametrize("command", ["memory-upload", "memory-download", "memory-delete"])
def test_archive_commands_require_arguments_before_docker(tmp_path, command):
    result = subprocess.run(
        [str(LAUNCHER), command], env=_stub_docker_environment(tmp_path),
        capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert f"{command} requires" in result.stderr
    assert "docker <" not in result.stdout


def test_memory_delete_rejects_extra_filenames(tmp_path):
    result = subprocess.run(
        [str(LAUNCHER), "memory-delete", "first.tar.gz", "second.tar.gz"],
        env=_stub_docker_environment(tmp_path), capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "memory-delete requires one archive filename" in result.stderr
    assert "docker <" not in result.stdout


def test_download_preserves_existing_destination(tmp_path):
    destination = tmp_path / "memory.tar.gz"
    destination.write_bytes(b"existing archive")
    result = subprocess.run(
        [str(LAUNCHER), "memory-download", "memory.tar.gz", str(destination)],
        env=_stub_docker_environment(tmp_path), capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "destination already exists" in result.stderr
    assert destination.read_bytes() == b"existing archive"


def test_failed_download_removes_partial_destination(tmp_path):
    environment = _stub_docker_environment(tmp_path)
    (tmp_path / "bin" / "docker").write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  volume) exit 0 ;;\n"
        "  run) printf partial; exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    destination = tmp_path / "download.tar.gz"
    result = subprocess.run(
        [str(LAUNCHER), "memory-download", "memory.tar.gz", str(destination)],
        env=environment, capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert not destination.exists()


def test_launcher_warns_before_overwrite_memory_import(tmp_path):
    result = _run_launcher(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "WARNING: --memory-mode overwrite will replace the selected current memory components" in result.stderr


def test_launcher_does_not_warn_for_append_memory_import(tmp_path):
    result = _run_launcher(tmp_path, "--memory-mode", "append")

    assert result.returncode == 0, result.stderr
    assert "WARNING:" not in result.stderr


def test_upload_publishes_only_completed_archive(pending_upload, tmp_path):
    process, _, content = pending_upload
    _, error = process.communicate(input=content[UPLOAD_PREFIX_SIZE:], timeout=5)

    assert process.returncode == 0, error.decode()
    assert (tmp_path / "memory.tar.gz").read_bytes() == content
    assert [path.name for path in tmp_path.iterdir()] == ["memory.tar.gz"]


def test_incomplete_upload_is_cleaned_up(pending_upload, tmp_path):
    process, _, _ = pending_upload
    _, error = process.communicate(timeout=5)

    assert process.returncode != 0
    assert b"Archive upload was incomplete" in error
    assert not list(tmp_path.iterdir())


def test_interrupted_upload_can_be_retried(pending_upload, tmp_path):
    process, command, content = pending_upload
    process.kill()
    process.communicate(timeout=5)
    assert not (tmp_path / "memory.tar.gz").exists()

    result = subprocess.run(command, input=content, capture_output=True, timeout=5)

    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / "memory.tar.gz").read_bytes() == content


def test_upload_preserves_competing_archive(pending_upload, tmp_path):
    process, command, content = pending_upload
    competing = b"B" * len(content)
    result = subprocess.run(command, input=competing, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr.decode()

    _, error = process.communicate(input=content[UPLOAD_PREFIX_SIZE:], timeout=5)

    assert process.returncode != 0
    assert b"Archive already exists" in error
    assert (tmp_path / "memory.tar.gz").read_bytes() == competing
    assert [path.name for path in tmp_path.iterdir()] == ["memory.tar.gz"]


@pytest.mark.skipif(
    not CONTAINER_TEST_IMAGE or shutil.which("docker") is None,
    reason="needs Docker and OMEGA_LAUNCHER_TEST_IMAGE",
)
def test_memory_volume_upload_download_round_trip(tmp_path):
    volume = "omega-transfer-test-" + uuid.uuid4().hex
    directory = tmp_path / "archives with spaces"
    directory.mkdir()
    content = directory / "history.metta"
    content.write_bytes(b"(sample history)\n\x00\xff\r\n")
    source = directory / "memory.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        archive.add(content, arcname="history.metta")
    original = source.read_bytes()

    def run(command, *arguments):
        return subprocess.run(
            [str(LAUNCHER), command, *map(str, arguments), "-d", CONTAINER_TEST_IMAGE,
             "--memory-transfer-volume", volume],
            capture_output=True, text=True, check=False,
        )

    try:
        uploaded = run("memory-upload", source)
        assert uploaded.returncode == 0, uploaded.stderr
        listed = run("memory-list")
        assert listed.returncode == 0, listed.stderr
        assert listed.stdout.strip() == source.name

        permissions = subprocess.run(
            ["docker", "run", "--rm", "--pull=never", "--user", "65534:65534",
             "--mount", f"type=volume,source={volume},target=/memory-transfer,readonly",
             "--entrypoint", "/bin/sh", CONTAINER_TEST_IMAGE, "-c",
             "stat -c '%u:%g %a' /memory-transfer /memory-transfer/memory.tar.gz"],
            capture_output=True, text=True, check=False,
        )
        assert permissions.returncode == 0, permissions.stderr
        assert permissions.stdout.splitlines() == ["65534:65534 700", "65534:65534 600"]

        source.write_bytes(b"replacement must not overwrite the archive")
        duplicate = run("memory-upload", source)
        assert duplicate.returncode != 0
        assert "Archive already exists" in duplicate.stderr

        destination = directory / "downloaded archive.tar.gz"
        downloaded = run("memory-download", source.name, destination)
        assert downloaded.returncode == 0, downloaded.stderr
        assert destination.read_bytes() == original
        assert destination.stat().st_mode & 0o777 == 0o600
        existing = run("memory-download", source.name, destination)
        assert existing.returncode != 0
        assert destination.read_bytes() == original

        missing = directory / "missing archive.tar.gz"
        failed = run("memory-download", "missing.tar.gz", missing)
        assert failed.returncode != 0
        assert not missing.exists()

        kept = directory / "kept.tar.gz"
        kept.write_bytes(original)
        uploaded = run("memory-upload", kept)
        assert uploaded.returncode == 0, uploaded.stderr
        deleted = run("memory-delete", source.name)
        assert deleted.returncode == 0, deleted.stderr
        listed = run("memory-list")
        assert listed.returncode == 0, listed.stderr
        assert listed.stdout.strip() == kept.name
        kept_destination = directory / "kept copy.tar.gz"
        downloaded = run("memory-download", kept.name, kept_destination)
        assert downloaded.returncode == 0, downloaded.stderr
        assert kept_destination.read_bytes() == original
    finally:
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True, check=False)


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


@pytest.mark.parametrize("command", ["start", "stop", "clean", "memory-download", "memory-delete"])
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


def _describe_commit(version: str) -> tuple[str, str] | None:
    described = re.fullmatch(r"(.+-\d+-g)([0-9a-fA-F]{7,})", version.removesuffix("-dirty"))
    if described is None:
        return None
    return described.group(1), described.group(2)


def test_longer_abbreviation_matches_same_commit(tmp_path):
    described = _describe_commit(_host_omega_version())
    if described is None:
        pytest.skip("checkout describe has no commit abbreviation")
    prefix, commit = described
    result = _run_launcher(
        tmp_path,
        script_version=f"{prefix}{commit}705ea",
        image_version=f"{prefix}{commit}",
    )

    assert result.returncode == 0, result.stderr
    assert "The launcher script and Docker image versions do not match." not in result.stderr
    assert "docker <rm>" in result.stdout


def test_shallow_clone_hash_matches_described_commit(tmp_path):
    described = _describe_commit(_host_omega_version())
    if described is None:
        pytest.skip("checkout describe has no commit abbreviation")
    prefix, commit = described
    result = _run_launcher(
        tmp_path,
        script_version=commit,
        image_version=f"{prefix}{commit}",
    )

    assert result.returncode == 0, result.stderr
    assert "The launcher script and Docker image versions do not match." not in result.stderr
    assert "docker <rm>" in result.stdout


def test_different_commit_abbreviation_is_refused(tmp_path):
    result = _run_launcher(
        tmp_path,
        script_version="v0.1.20-11-g9cdcbfe705ea",
        image_version="v0.1.20-11-gdeadbee",
    )

    assert result.returncode != 0
    assert "Omega version=v0.1.20-11-g9cdcbfe705ea" in result.stderr
    assert "Omega version=v0.1.20-11-gdeadbee" in result.stderr
    assert "docker <rm>" not in result.stdout


def test_legacy_image_path_version_is_compared(tmp_path):
    result = _run_launcher(tmp_path, legacy_version="v0.0.0-test")

    assert result.returncode != 0
    assert "Omega version=v0.0.0-test" in result.stderr
    assert "Could not determine the Docker image version" not in result.stderr
    assert "docker <rm>" not in result.stdout
