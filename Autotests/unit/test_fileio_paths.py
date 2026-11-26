"""Unit tests for the filesystem primitives used by the research workflow."""
import errno
import os
import stat
import struct
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import fileio


def test_make_dirs_creates_parents_and_accepts_existing_directories(tmp_path):
    target = tmp_path / "project" / "src"

    assert fileio.make_dirs(target) is True
    assert target.is_dir()
    assert fileio.make_dirs(target) is True


def test_make_dirs_returns_false_for_a_path_blocked_by_a_file(tmp_path):
    blocker = tmp_path / "project"
    blocker.touch()

    assert fileio.make_dirs(blocker) is False
    assert fileio.make_dirs(blocker / "src") is False


@pytest.mark.parametrize("name", ["A", "7", "research-workflow", "02_plan.md", "exp.v0.2.json", "a" * 128])
def test_valid_path_segment(name):
    assert fileio.validate_file_or_folder_name(name) is True


@pytest.mark.parametrize(
    "name",
    ["", "a b", "a\t", "a\n", "a;", "a&&", "a|", "a$()", "a`", "-rf", ".env",
     ".", "..", "a..b", "a/b", r"a\b", "café", "a" * 129],
)
def test_invalid_path_segment(name):
    assert fileio.validate_file_or_folder_name(name) is False


def test_safe_subpath_resolves_missing_paths_under_canonical_base(tmp_path):
    base = tmp_path / "research"
    base.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(base, target_is_directory=True)

    assert fileio.safe_subpath(alias, "study.v0.2", "02_plan.md") == str(
        base.resolve() / "study.v0.2" / "02_plan.md"
    )


def test_safe_subpath_rejects_invalid_segments_and_empty_base(tmp_path):
    assert fileio.safe_subpath(tmp_path, "../study", "plan.md") == ""
    assert fileio.safe_subpath(tmp_path, "study", "../plan.md") == ""
    assert fileio.safe_subpath("", "study", "plan.md") == ""


def test_safe_subpath_rejects_escaping_links_and_links_to_parent(tmp_path):
    base = tmp_path / "research"
    project = base / "study"
    project.mkdir(parents=True)
    outside = tmp_path / "research-other"
    outside.mkdir()
    outside_file = outside / "plan.md"
    outside_file.touch()

    (base / "external-study").symlink_to(outside, target_is_directory=True)
    (base / "same-as-base").symlink_to(base, target_is_directory=True)
    (project / "external.md").symlink_to(outside_file)
    (project / "missing.md").symlink_to(outside / "missing.md")
    (project / "parent").symlink_to(project, target_is_directory=True)

    assert fileio.safe_subpath(base, "external-study", "plan.md") == ""
    assert fileio.safe_subpath(base, "same-as-base", "plan.md") == ""
    for name in ("external.md", "missing.md", "parent"):
        assert fileio.safe_subpath(base, "study", name) == ""


def test_safe_subpath_allows_links_inside_the_research_project(tmp_path):
    project = tmp_path / "study"
    project.mkdir()
    plan = project / "plan.md"
    plan.touch()
    (project / "local.md").symlink_to(plan)

    assert fileio.safe_subpath(tmp_path, "study", "local.md") == str(plan.resolve())


@pytest.fixture
def workflow_dir(tmp_path):
    path = tmp_path / "workflow_space"
    path.mkdir()
    return path


def test_research_write_keeps_file_on_encoding_error(tmp_path, workflow_dir):
    fileio.start_research(tmp_path, workflow_dir, "study", "Original")
    project = workflow_dir / "research" / "study"
    for name in ("topic.txt", "new.txt"):
        result = fileio.write_research_file(tmp_path, workflow_dir, "study", name, chr(0xD800))
        assert result.startswith("WRITE-FAILED")
    assert (project / "topic.txt").read_text() == "Original"
    assert not (project / "new.txt").exists()


@pytest.mark.parametrize("failed_call", ["fsync", "replace"])
def test_research_write_publishes_only_after_success(tmp_path, workflow_dir, monkeypatch, failed_call):
    fileio.start_research(tmp_path, workflow_dir, "study", "Original")
    project = workflow_dir / "research" / "study"
    topic = project / "topic.txt"
    entries = set(project.iterdir())

    def fail_before_commit(*args, **kwargs):
        assert topic.read_text() == "Original"
        raise OSError(f"{failed_call} failed")

    with monkeypatch.context() as patch:
        patch.setattr(os, failed_call, fail_before_commit)
        assert fileio.start_research(tmp_path, workflow_dir, "study", "Retry").startswith("WRITE-FAILED")
    assert set(project.iterdir()) == entries
    assert topic.read_text() == "Original"

    topic.chmod(0o640)
    with topic.open() as old_version:
        result = fileio.write_research_file(tmp_path, workflow_dir, "study", "topic.txt", "Updated")
        assert old_version.read() == "Original"
    assert "head='Updated'" in result
    assert topic.read_text() == "Updated"
    assert stat.S_IMODE(topic.stat().st_mode) == 0o640


def test_research_write_preserves_access_acl(tmp_path, workflow_dir):
    assert fileio.start_research(tmp_path, workflow_dir, "study", "Original").startswith("Created project:")
    topic = workflow_dir / "research" / "study" / "topic.txt"
    if sys.platform == "darwin":
        subprocess.run(["/bin/chmod", "+a", "nobody deny read", str(topic)], check=True)

        def acl():
            return subprocess.check_output(["/bin/ls", "-le", str(topic)], text=True).splitlines()[1:]
    elif sys.platform == "linux":
        attribute = "system.posix_acl_access"
        other_uid = 65534 if os.geteuid() != 65534 else 65533
        # Linux POSIX ACL xattr v2: owner, named user, owning group, mask, other.
        entries = ((1, 6, -1), (2, 4, other_uid), (4, 0, -1), (16, 4, -1), (32, 0, -1))
        value = struct.pack("<I", 2) + b"".join(struct.pack("<HHi", *entry) for entry in entries)
        try:
            os.setxattr(topic, attribute, value)
        except OSError as exc:
            if exc.errno == errno.ENOTSUP:
                pytest.skip("filesystem does not support POSIX ACLs")
            raise

        def acl():
            return os.getxattr(topic, attribute)
    else:
        pytest.skip("ACL fixture is supported on Linux and macOS")

    before = acl()
    assert before
    with topic.open() as old_version:
        result = fileio.write_research_file(tmp_path, workflow_dir, "study", "topic.txt", "Updated")
        assert old_version.read() == "Original"
    assert result.startswith("WRITE-VERIFIED")
    assert topic.read_text() == "Updated"
    assert acl() == before


@pytest.mark.parametrize("fail_sync", [False, True])
def test_research_write_keeps_inode_when_replacement_permissions_fail(tmp_path, workflow_dir, monkeypatch, fail_sync):
    assert fileio.start_research(tmp_path, workflow_dir, "study", "Original topic").startswith("Created project:")
    topic = workflow_dir / "research" / "study" / "topic.txt"
    before = topic.stat()

    def deny_metadata(*args):
        raise PermissionError(errno.EPERM, "cannot preserve permissions on replacement")

    monkeypatch.setattr(os, "fchmod", deny_metadata)
    if fail_sync:
        sync = os.fsync

        def fail_first_sync(fd):
            monkeypatch.setattr(os, "fsync", sync)
            assert topic.read_text() == "Updated"
            raise OSError(errno.EIO, "could not sync updated contents")

        monkeypatch.setattr(os, "fsync", fail_first_sync)

    result = fileio.write_research_file(tmp_path, workflow_dir, "study", "topic.txt", "Updated")

    assert result.startswith("WRITE-FAILED" if fail_sync else "WRITE-VERIFIED")
    assert topic.read_text() == ("Original topic" if fail_sync else "Updated")
    assert os.path.samestat(before, topic.stat())
    assert not list(topic.parent.glob(".research-*.tmp"))


def test_research_files_support_local_links_and_nested_paths(tmp_path, workflow_dir):
    assert fileio.start_research(tmp_path, workflow_dir, "study", "Topic").startswith("Created project:")
    project = workflow_dir / "research" / "study"
    (project / "plan.md").symlink_to("runs/plan.md")
    text = "Первая строка\nSecond line"

    result = fileio.write_research_file(tmp_path, workflow_dir, "study", "plan.md", text)

    assert result.startswith("WRITE-VERIFIED")
    assert (project / "runs" / "plan.md").read_text() == text
    assert fileio.read_research_instructions(tmp_path, workflow_dir, "study", "plan.md") == ["ok", text]
    assert fileio.write_research_file(tmp_path, workflow_dir, "study", "../plan.md", text).startswith("WRITE-FAILED")
    assert not (project.parent / "plan.md").exists()


@pytest.mark.parametrize("operation", ["start", "write", "read"])
def test_research_io_uses_the_open_project_after_a_rename(tmp_path, workflow_dir, monkeypatch, operation):
    fileio.start_research(tmp_path, workflow_dir, "study", "Original")
    project = workflow_dir / "research" / "study"
    moved = project.with_name("moved")
    # Each operation must use the project it opened, even if the same name
    # now identifies a different directory. All fixtures stay in tmp_path.
    resolve = fileio._relative_target

    def resolve_then_rename(base, *segments):
        target = resolve(base, *segments)
        if base == str(project.resolve()) and not moved.exists():
            project.rename(moved)
            project.mkdir()
            (project / "topic.txt").write_text("Replacement")
        return target

    monkeypatch.setattr(fileio, "_relative_target", resolve_then_rename)
    if operation == "start":
        result = fileio.start_research(tmp_path, workflow_dir, "study", "New topic")
        assert result.startswith("Created project:")
        assert not (project / "src").exists()
        assert (moved / "topic.txt").read_text() == "New topic"
    elif operation == "write":
        result = fileio.write_research_file(tmp_path, workflow_dir, "study", "topic.txt", "Updated")
        assert "head='Updated'" in result
        assert (moved / "topic.txt").read_text() == "Updated"
    else:
        assert fileio.read_research_instructions(tmp_path, workflow_dir, "study", "topic.txt") == ["ok", "Original"]
    assert (project / "topic.txt").read_text() == "Replacement"


def test_custom_workflow_directory_must_stay_inside_memory(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    workflow = memory / "nested" / "workflows"

    assert fileio.prepare_workflow_directory(memory, workflow) is True
    assert fileio.prepare_workflow_directory(memory, workflow) is True
    assert workflow.is_dir()
    assert fileio.prepare_workflow_directory(memory, memory) is False
    assert fileio.prepare_workflow_directory(memory, tmp_path / "outside") is False
    assert not (tmp_path / "outside").exists()


def test_workflow_accepts_both_spellings_of_a_linked_memory_root(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    memory = tmp_path / "memory"
    memory.symlink_to(storage, target_is_directory=True)
    for root in (memory, storage, storage.resolve()):
        workflow = root / "workflows"
        assert fileio.prepare_workflow_directory(memory, workflow)
        assert fileio.start_research(memory, workflow, "study", "Topic").startswith("Created project:")
        assert fileio.research_directory(memory, workflow) == str(storage.resolve() / "workflows" / "research")

    (storage / "link").symlink_to(storage / "workflows", target_is_directory=True)
    for root in (memory, storage.resolve()):
        assert not fileio.prepare_workflow_directory(memory, root / "link" / "nested")
    assert not (storage / "workflows" / "nested").exists()


@pytest.mark.parametrize("target_inside_memory", [False, True])
def test_research_io_rejects_a_symlink_at_the_workflow_boundary(tmp_path, target_inside_memory):
    memory = tmp_path / "memory"
    memory.mkdir()
    workflow = memory / "workflow_space"
    target = (memory if target_inside_memory else tmp_path) / "other-workspace"
    project = target / "research" / "study"
    project.mkdir(parents=True)
    (project / "topic.txt").write_text("Fixture", encoding="utf-8")
    workflow.symlink_to(target, target_is_directory=True)

    assert fileio.prepare_workflow_directory(memory, workflow) is False
    assert fileio.research_directory(memory, workflow) == ""
    assert fileio.start_research(memory, workflow, "new-study", "Topic").startswith("ERROR:")
    assert fileio.write_research_file(memory, workflow, "study", "topic.txt", "New topic").startswith("WRITE-FAILED")
    assert fileio.read_research_instructions(memory, workflow, "study", "topic.txt")[0] == "error"
    assert (project / "topic.txt").read_text(encoding="utf-8") == "Fixture"
    assert not (target / "research" / "new-study").exists()
