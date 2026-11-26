"""Unit tests for the filesystem primitives used by the research workflow."""
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


def test_research_files_support_local_links_and_nested_paths(tmp_path):
    assert fileio.start_research(tmp_path, "study", "Topic").startswith("Created project:")
    project = tmp_path / "research" / "study"
    (project / "plan.md").symlink_to("runs/plan.md")
    text = "Первая строка\nSecond line"

    result = fileio.write_research_file(tmp_path, "study", "plan.md", text)

    assert result.startswith("WRITE-VERIFIED")
    assert (project / "runs" / "plan.md").read_text() == text
    assert fileio.read_research_instructions(tmp_path, "study", "plan.md") == ["ok", text]
    assert fileio.write_research_file(tmp_path, "study", "../plan.md", text).startswith("WRITE-FAILED")
    assert not (project.parent / "plan.md").exists()


@pytest.mark.parametrize("operation", ["start", "write", "read"])
def test_research_io_uses_the_open_project_after_a_rename(tmp_path, monkeypatch, operation):
    fileio.start_research(tmp_path, "study", "Original")
    project = tmp_path / "research" / "study"
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
        result = fileio.start_research(tmp_path, "study", "New topic")
        assert result.startswith("Created project:")
        assert not (project / "src").exists()
        assert (moved / "topic.txt").read_text() == "New topic"
    elif operation == "write":
        result = fileio.write_research_file(tmp_path, "study", "topic.txt", "Updated")
        assert "head='Updated'" in result
        assert (moved / "topic.txt").read_text() == "Updated"
    else:
        assert fileio.read_research_instructions(tmp_path, "study", "topic.txt") == ["ok", "Original"]
    assert (project / "topic.txt").read_text() == "Replacement"
