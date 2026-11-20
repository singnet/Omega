"""Builds the list of available workflows from the frontmatter of SKILL.md files.

A workflow is a skill in the Agent Skills format
(https://agentskills.io/specification): a directory with a SKILL.md file that
starts with YAML frontmatter. The `name` and `description` fields of that
frontmatter are what the agent sees before it loads a workflow, so the
description is kept in one place only.

Loading is lenient, as the Agent Skills client guide recommends. A workflow is
left out of the list only when its frontmatter cannot be read or has no
description. Smaller problems, such as a name that differs from the directory
name, are logged as warnings and the workflow is still listed. Every problem is
logged with the path of the SKILL.md file.

The MeTTa side calls `catalog_prompt` with the workflows directory:

    (py-call (skill_catalog.catalog_prompt "/path/to/instructions"))
"""

import html
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

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
    "When a task matches a skill's description, call workflow-load-instructions\n"
    "with the skill's name to load its full instructions."
)


@dataclass(frozen=True)
class CatalogEntry:
    """One workflow as the agent sees it before loading it.

    `name` is the directory name, because that is the name
    workflow-load-instructions accepts. Build entries with `read_entry`, which
    guarantees a non-empty single-line description."""
    name: str
    description: str

    def to_prompt(self) -> str:
        return (f"<skill><name>{html.escape(self.name, quote=False)}</name>"
                f"<description>{html.escape(self.description, quote=False)}</description></skill>")


def _split_frontmatter(text: str) -> Optional[str]:
    """Return the text between the opening and closing `---` lines, or None
    when the file does not start with frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
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


def _parse_frontmatter(frontmatter: str) -> Optional[dict]:
    """Parse frontmatter YAML, retrying once with plain values quoted."""
    for candidate in (frontmatter, _quote_plain_values(frontmatter)):
        try:
            fields = yaml.safe_load(candidate)
        except yaml.YAMLError:
            continue
        if isinstance(fields, dict):
            return fields
    return None


def _skip(path: str, reason: str) -> None:
    """Log why the workflow at path is left out of the list."""
    hint = ""
    legacy = os.path.join(os.path.dirname(path), LEGACY_DESCRIPTION_FILE)
    if os.path.exists(legacy):
        hint = (f". {LEGACY_DESCRIPTION_FILE} is no longer read: move its text"
                f" into the description field of the {SKILL_FILE} frontmatter")
    logger.error(f"Skipping workflow {path}: {reason}{hint}")


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


def read_entry(skill_dir: str) -> Optional[CatalogEntry]:
    """Read the catalog entry of the workflow in skill_dir, or None when the
    workflow cannot be listed. Logs every problem it finds."""
    path = os.path.join(skill_dir, SKILL_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        _skip(path, f"cannot read the file ({e})")
        return None

    frontmatter = _split_frontmatter(text)
    if frontmatter is None:
        _skip(path, "the file does not start with YAML frontmatter between '---' lines")
        return None
    fields = _parse_frontmatter(frontmatter)
    if fields is None:
        _skip(path, "the frontmatter is not valid YAML")
        return None

    description = fields.get("description")
    if not isinstance(description, str) or not description.strip():
        _skip(path, "the frontmatter has no description")
        return None
    description = " ".join(description.split())

    directory = os.path.basename(os.path.normpath(skill_dir))
    _warn_about_name(path, directory, fields.get("name"))
    if len(description) > MAX_DESCRIPTION_LENGTH:
        logger.warning(f"Workflow {path}: description is longer than {MAX_DESCRIPTION_LENGTH} characters")
    if len(text.splitlines()) > MAX_SKILL_LINES:
        logger.warning(f"Workflow {path}: {SKILL_FILE} is longer than {MAX_SKILL_LINES} lines,"
                       f" consider moving details into separate files")
    return CatalogEntry(directory, description)


def read_catalog(base_dir: str) -> list[CatalogEntry]:
    """Read the entries of all workflows in base_dir, sorted by name. A
    workflow is a direct subdirectory that contains a SKILL.md file; other
    entries are ignored."""
    try:
        names = sorted(os.listdir(base_dir))
    except OSError as e:
        logger.error(f"Cannot list workflows in {base_dir}: {e}")
        return []
    entries = []
    for name in names:
        skill_dir = os.path.join(base_dir, name)
        if name.startswith(".") or not os.path.isfile(os.path.join(skill_dir, SKILL_FILE)):
            continue
        entry = read_entry(skill_dir)
        if entry is not None:
            entries.append(entry)
    return entries


def catalog_prompt(base_dir: str) -> str:
    """Return the prompt text that lists the workflows in base_dir, or an empty
    string when there are none."""
    entries = read_catalog(str(base_dir))
    if not entries:
        return ""
    skills = "\n".join(entry.to_prompt() for entry in entries)
    return f"{PROMPT_HEADER}\n<available_skills>\n{skills}\n</available_skills>"
