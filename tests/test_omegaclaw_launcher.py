import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "omega"
FAKE_DOCKER = """\
#!/bin/sh
is_version_probe=0
for arg in "$@"; do
  case "$arg" in
    /PeTTa/repos/Omega/version|--version)
      is_version_probe=1
      ;;
  esac
done
if [ "$is_version_probe" -eq 1 ]; then
  printf '%s\\n' "${OMEGA_TEST_IMAGE_VERSION}"
  exit 0
fi
printf 'docker'
printf ' <%s>' "$@"
printf '\\n'
"""


def _host_omega_version() -> str:
    result = subprocess.run(
        [
            "python3",
            "-c",
            "from src.helper import omega_version; print(omega_version())",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _run_launcher(
    tmp_path: Path,
    *component_options: str,
    image_version: str | None = None,
) -> subprocess.CompletedProcess:
    archive = tmp_path / "memory.tar.gz"
    archive.touch()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)

    environment = os.environ.copy()
    environment["ASI_API_KEY"] = "test-token"
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    environment["OMEGA_TEST_IMAGE_VERSION"] = (
        image_version if image_version is not None else _host_omega_version()
    )

    return subprocess.run(
        [
            str(LAUNCHER),
            "start",
            "--memory-transfer-dir",
            str(tmp_path),
            "--memory-import",
            archive.name,
            *component_options,
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


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
