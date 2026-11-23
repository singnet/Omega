"""Builds the list of available workflows from the frontmatter of SKILL.md files.

A workflow is a skill in the Agent Skills format
(https://agentskills.io/specification): a directory with a SKILL.md file that
starts with YAML frontmatter. The `name` and `description` fields of that
frontmatter are what the agent sees before it loads a workflow, so the
description is kept in one place only.

A workflow is left out of the list when its SKILL.md cannot be read, its
frontmatter cannot be parsed, it has no description, or it is too big for the
prompt: a description over 1024 characters or a file over 500 lines. The same
rules decide whether workflow-load-instructions may load it, because a loaded
workflow keeps its whole SKILL.md in the prompt. Problems with the name are
only logged as warnings. A broken file is skipped and the other workflows are
still listed. Every problem is logged with the path of the SKILL.md file.

The MeTTa side calls two functions with plain strings:

    (py-call (skill_catalog.catalog_prompt "/path/to/instructions"))
    (py-call (skill_catalog.load_problem "/path/to/instructions/research-workflow"))
"""

import html
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional, Union

import yaml


logger = logging.getLogger(__name__)

SKILL_FILE = "SKILL.md"
LEGACY_DESCRIPTION_FILE = "description.txt"

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_SKILL_LINES = 500
VALID_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# A top-level `key: value` line whose value is not quoted and is not a block
# scalar. Used to quote values that contain ": ", which plain YAML rejects.
_PLAIN_VALUE_LINE = re.compile(r"^([A-Za-z0-9_-]+):[ \t]+([^'\"|>].*?)\s*$")

PROMPT_HEADER = (
    "The following skills provide specialized instructions for specific tasks.\n"
    "When a task matches a skill's description, call `workflow-load-instructions <workflow_name>`\n"
    "replacing `<workflow_name>` with the value of that skill's `<name>` field."
)


@dataclass(frozen=True)
class CatalogEntry:
    """One workflow as the agent sees it before loading it.

    `name` is the directory name, because that is the name
    workflow-load-instructions accepts. Build entries with `read_entry`, which
    guarantees a non-empty description within the size limits."""
    name: str
    description: str

    def to_prompt(self) -> str:
        return (f"<skill><name>{html.escape(self.name, quote=False)}</name>"
                f"<description>{html.escape(self.description, quote=False)}</description></skill>")


@dataclass(frozen=True)
class Rejected:
    """Why the workflow whose SKILL.md is at `path` cannot be listed or loaded."""
    path: str
    reason: str

    def message(self) -> str:
        hint = ""
        legacy = os.path.join(os.path.dirname(self.path), LEGACY_DESCRIPTION_FILE)
        if os.path.exists(legacy):
            hint = (f". {LEGACY_DESCRIPTION_FILE} is no longer read: move its text"
                    f" into the description field of the {SKILL_FILE} frontmatter")
        return f"{self.path}: {self.reason}{hint}"


def _split_frontmatter(text: str) -> Optional[str]:
    """Return the text between the opening and closing `---` lines, or None
    when the file does not start with frontmatter. Only a `---` at the start
    of a line counts, so an indented `---` inside a block value stays part of
    the value."""
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return None
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            return "\n".join(lines[1:i])
    return None


def _quote_plain_values(frontmatter: str) -> str:
    """Quote unquoted top-level values that contain ": ", the most common
    reason hand-written frontmatter fails to parse."""
    def quote(line: str) -> str:
        match = _PLAIN_VALUE_LINE.match(line)
        if not match or ": " not in match.group(2):
            return line
        value = match.group(2).replace("\\", "\\\\").replace('"', '\\"')
        return f'{match.group(1)}: "{value}"'
    return "\n".join(quote(line) for line in frontmatter.splitlines())


def _parse_frontmatter(frontmatter: str) -> Union[dict, str]:
    """Parse frontmatter YAML, retrying once with plain values quoted. Returns
    the fields, or the parser's error message when both attempts fail.
    PyYAML raises ValueError, not YAMLError, for values such as the date
    2026-02-30, so both are caught."""
    error = "the frontmatter is not a mapping of fields"
    for candidate in (frontmatter, _quote_plain_values(frontmatter)):
        try:
            fields = yaml.safe_load(candidate)
        except (yaml.YAMLError, ValueError) as e:
            error = f"the frontmatter is not valid YAML ({' '.join(str(e).split())})"
            continue
        if isinstance(fields, dict):
            return fields
    return error


def _warn_about_name(path: str, directory: str, name) -> None:
    """Log the ways the frontmatter name breaks the Agent Skills rules."""
    if name is None:
        logger.warning(f"Workflow {path}: frontmatter has no name, using the directory name '{directory}'")
        return
    name = str(name)
    if name != directory:
        logger.warning(f"Workflow {path}: frontmatter name '{name}' differs from the directory name,"
                       f" the workflow is listed as '{directory}'")
    if len(name) > MAX_NAME_LENGTH:
        logger.warning(f"Workflow {path}: name is longer than {MAX_NAME_LENGTH} characters")
    if not VALID_NAME.match(name):
        logger.warning(f"Workflow {path}: name may only contain lowercase letters, digits"
                       f" and single hyphens between them")


def read_entry(skill_dir: str) -> Union[CatalogEntry, Rejected]:
    """Read the catalog entry of the workflow in skill_dir, or the reason it
    cannot be listed. Logs warnings about the name; the caller reports a
    rejection."""
    path = os.path.join(skill_dir, SKILL_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError as e:
        return Rejected(path, f"the file is not valid UTF-8 ({e.reason} at byte {e.start})")
    except OSError as e:
        return Rejected(path, f"cannot read the file ({e.strerror or e})")

    line_count = len(text.splitlines())
    if line_count > MAX_SKILL_LINES:
        return Rejected(path, f"the file has {line_count} lines, more than the limit of {MAX_SKILL_LINES};"
                              f" move details into separate files")
    frontmatter = _split_frontmatter(text)
    if frontmatter is None:
        return Rejected(path, "the file does not start with YAML frontmatter between '---' lines")
    fields = _parse_frontmatter(frontmatter)
    if isinstance(fields, str):
        return Rejected(path, fields)

    description = fields.get("description")
    if not isinstance(description, str) or not description.strip():
        return Rejected(path, "the frontmatter has no description")
    description = description.strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return Rejected(path, f"the description has {len(description)} characters,"
                              f" more than the limit of {MAX_DESCRIPTION_LENGTH}")

    directory = os.path.basename(os.path.normpath(skill_dir))
    _warn_about_name(path, directory, fields.get("name"))
    return CatalogEntry(directory, description)


def read_catalog(base_dir: str) -> list[CatalogEntry]:
    """Read the entries of all workflows in base_dir, sorted by name. A
    workflow is a direct subdirectory that contains a SKILL.md file; other
    entries are ignored. Every workflow left out is logged as an error."""
    try:
        names = sorted(os.listdir(base_dir))
    except OSError as e:
        logger.error(f"Cannot list workflows in {base_dir}: {e.strerror or e}")
        return []
    entries = []
    for name in names:
        skill_dir = os.path.join(base_dir, name)
        if name.startswith(".") or not os.path.isfile(os.path.join(skill_dir, SKILL_FILE)):
            continue
        result = read_entry(skill_dir)
        if isinstance(result, Rejected):
            logger.error(f"Skipping workflow {result.message()}")
        else:
            entries.append(result)
    return entries


def catalog_prompt(base_dir: str) -> str:
    """Return the prompt text that lists the workflows in base_dir, or an empty
    string when there are none."""
    entries = read_catalog(str(base_dir))
    if not entries:
        return ""
    skills = "\n".join(entry.to_prompt() for entry in entries)
    return f"{PROMPT_HEADER}\n<available_skills>\n{skills}\n</available_skills>"


def load_problem(skill_dir: str) -> str:
    """Return why the workflow in skill_dir may not be loaded, or an empty
    string when it may. A workflow may be loaded exactly when it would be
    listed."""
    result = read_entry(str(skill_dir))
    if isinstance(result, Rejected):
        logger.error(f"Refusing to load workflow {result.message()}")
        return result.message()
    return ""
