import importlib.util
from pathlib import Path

import pytest

_SOURCE = Path(__file__).resolve().parents[2] / "tests" / "test_omega_launcher_migration.py"
_spec = importlib.util.spec_from_file_location("launcher_migration_harness", _SOURCE)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

docker_root = harness.docker_root


def test_append_import_without_only_flags_keeps_memory_on_new_volume_after_interrupted_copy(docker_root, tmp_path):
    old, new = harness._interrupted_migration(docker_root, image_files=True)
    kept = {
        "history.metta": b"(history written on the new volume)\n",
        "chroma_db/chroma.sqlite3": b"vector memory written on the new volume\n",
    }
    for name, contents in kept.items():
        (new / name).write_bytes(contents)

    result = harness._launcher(
        docker_root,
        *harness._memory_import_arguments(docker_root, tmp_path),
        "--memory-mode",
        "append",
    )

    for name, contents in kept.items():
        path = new / name
        assert path.is_file(), f"{name} was deleted from the new volume"
        assert path.read_bytes() == contents, f"{name} was changed on the new volume"
    import_runs = [call for call in harness._calls(docker_root) if call.startswith("run -d")]
    if result.returncode == 0:
        assert any("MEMORY_IMPORT_MODE=append" in call.split() for call in import_runs), import_runs
    else:
        assert not import_runs, import_runs
        assert (old / ".migration-started").exists(), "the refusal removed the migration marker from the old volume"


@pytest.mark.parametrize("flags", [
    ("--memory-mode", "append"),
    ("--only-history",),
    ("--only-vector",),
    ("--memory-mode", "overwrite"),
])
def test_import_removes_running_copy_container_before_starting_the_agent(docker_root, tmp_path, flags):
    harness._interrupted_migration(docker_root, image_files=True)
    harness._container_on_volume(
        docker_root, "musing_haslett", "running", "omegaclaw-memory omega-memory", label=harness.MIGRATION_LABEL
    )

    result = harness._launcher(docker_root, *harness._memory_import_arguments(docker_root, tmp_path), *flags)

    assert result.returncode == 0, result.stderr
    assert not (docker_root / "containers" / "musing_haslett").exists()
    calls = harness._calls(docker_root)
    removals = [index for index, call in enumerate(calls) if call.startswith("rm ") and "musing_haslett" in call.split()]
    starts = [index for index, call in enumerate(calls) if call.startswith("run -d")]
    assert removals, calls
    assert starts, calls
    assert removals[0] < starts[0], calls
