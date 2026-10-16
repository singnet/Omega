"""Installing the dependencies each plugin declares.

A plugin is a directory under plugins/ that core loads at startup, and until now
the one thing it could not say was what it needs to import. Only core's own
requirements.txt reached pip, so a plugin's imports either happened to be
satisfied by core's tree or the loader failed and took start-up with it.
plugins/openclaw/openclaw.py imports requests, which no requirements file
declares; it works because chromadb pulls it in.

scripts/install_dependencies.sh walks whatever plugins are present and adds each
requirements.txt it finds to the same pip invocation as core's own. Two details
carry most of the weight, so most of these tests are about them: the invocation
is single, and pip check runs after it.

The script is the one definition of what installing Omega's dependencies means.
The image build and the README's source install both call it, and the last two
tests are what stops either of them growing a second, quietly different copy.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "install_dependencies.sh"
DOCKERFILE = REPO_ROOT / "Dockerfile"
README = REPO_ROOT / "README.md"
PLUGIN_API_DOC = REPO_ROOT / "docs" / "reference-plugin-api.md"
CORE_REQUIREMENTS = REPO_ROOT / "requirements.txt"


def _fake_repo(root, plugins):
    """A tree shaped like core, holding the script and the requirements it walks.

    `plugins` maps a plugin directory name to the text of its requirements.txt,
    or to None for a plugin that ships none. Omit plugins entirely by passing
    None instead of a mapping, which leaves out the plugins directory.
    """
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / SCRIPT.name)
    (root / "requirements.txt").write_text("chromadb==1.3.0\n", encoding="utf-8")

    if plugins is not None:
        (root / "plugins").mkdir()
        for name, requirements in plugins.items():
            (root / "plugins" / name).mkdir()
            if requirements is not None:
                (root / "plugins" / name / "requirements.txt").write_text(
                    requirements, encoding="utf-8"
                )
    return root


def _stub_pip(bin_dir, log, failing_subcommand):
    """A python3 on PATH that records how pip was called instead of calling it."""
    bin_dir.mkdir()
    stub = bin_dir / "python3"
    fail = ""
    if failing_subcommand:
        fail = f'case " $* " in *" {failing_subcommand} "*) exit 1 ;; esac\n'
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        f"{fail}"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return bin_dir


def _install(tmp_path, plugins, *pip_options, failing_subcommand=None):
    """Run the script against a made-up tree; hand back its exit and pip's calls."""
    repo = _fake_repo(tmp_path / "omega", plugins)
    log = tmp_path / "pip.log"
    bin_dir = _stub_pip(tmp_path / "bin", log, failing_subcommand)

    result = subprocess.run(
        [str(repo / "scripts" / SCRIPT.name), *pip_options],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return repo, result, calls


def _installs(calls):
    """Just the install calls, leaving out pip check and anything else."""
    return [call for call in calls if "pip install" in call]


def _unwrapped(text):
    """The text's lines, with a command wrapped over several read as the one it is.

    A shell command wraps with a trailing backslash, in the README and in the
    Dockerfile alike, so what a command carries often sits on a different line
    from the command's name.
    """
    commands = []
    for line in text.splitlines():
        if commands and commands[-1].endswith("\\"):
            commands[-1] = commands[-1][:-1].rstrip() + " " + line.strip()
        else:
            commands.append(line)
    return commands


def test_core_and_every_plugin_resolve_in_one_invocation(tmp_path):
    """Separate pip runs resolve separately, and the loser is silent.

    A plugin that pins a version core also pins would, in its own invocation,
    replace core's copy without complaint: core is not a pip distribution, so no
    metadata records what it needed and nothing warns. Resolving everything at
    once turns that into a failure instead.
    """
    repo, result, calls = _install(
        tmp_path, {"telegram": "aiogram>=3.0.0\n", "openclaw": "requests>=2.31.0\n"}
    )

    assert result.returncode == 0, result.stderr
    assert len(_installs(calls)) == 1, calls
    installed = _installs(calls)[0]
    assert f"-r {repo}/requirements.txt" in installed
    assert f"-r {repo}/plugins/telegram/requirements.txt" in installed
    assert f"-r {repo}/plugins/openclaw/requirements.txt" in installed


def test_a_plugin_that_declares_nothing_costs_nothing(tmp_path):
    """Neither plugin core ships today has a requirements.txt, so this is the
    ordinary case, not an edge one."""
    repo, result, calls = _install(tmp_path, {"openclaw": None, "workflow": None})

    assert result.returncode == 0, result.stderr
    assert _installs(calls) == [
        f"-m pip install -r {repo}/requirements.txt"
    ]


def test_a_tree_with_no_plugins_at_all_still_installs(tmp_path):
    """A glob that matches nothing is a literal string in sh, which must not be
    passed to pip or tested as a file. Neither an empty plugins directory nor a
    missing one is an error: core's dependencies still install."""
    for plugins in ({}, None):
        repo, result, calls = _install(tmp_path / str(plugins), plugins)

        assert result.returncode == 0, result.stderr
        assert _installs(calls) == [f"-m pip install -r {repo}/requirements.txt"]


def test_pip_options_reach_pip(tmp_path):
    """The image build needs its own flags, and passing them through is what
    lets it share this script with a source install that wants none of them."""
    _, result, calls = _install(
        tmp_path, {}, "--no-cache-dir", "--break-system-packages"
    )

    assert result.returncode == 0, result.stderr
    assert _installs(calls)[0].startswith(
        "-m pip install --no-cache-dir --break-system-packages -r "
    )


def test_the_result_is_checked(tmp_path):
    """pip resolves what it was asked for and reports conflicts it could not
    avoid; pip check is what turns the second into a failure."""
    _, result, calls = _install(tmp_path, {"telegram": "aiogram>=3.0.0\n"})

    assert result.returncode == 0, result.stderr
    assert calls[-1].split() == ["-m", "pip", "check"]


def test_an_unsatisfied_dependency_fails(tmp_path):
    """The point of the check is the exit code, so the script has to stop on it."""
    _, result, _ = _install(
        tmp_path, {"telegram": "aiogram>=3.0.0\n"}, failing_subcommand="check"
    )

    assert result.returncode != 0


def test_an_install_failure_stops_before_the_check(tmp_path):
    """A conflict pip refuses outright must not be followed by a check that
    passes on the packages that did land."""
    _, result, calls = _install(
        tmp_path, {"telegram": "aiogram>=3.0.0\n"}, failing_subcommand="install"
    )

    assert result.returncode != 0
    assert not [call for call in calls if "pip check" in call]


def test_a_plugin_cannot_choose_where_packages_come_from(tmp_path):
    """pip reads an option written inside a requirements file as an instruction
    for the whole invocation, and it beats the same option on the command line.
    A plugin shipping one picks the index core's own pinned packages come from,
    and the install still succeeds, so the file is refused before pip runs."""
    hijack = "--index-url https://elsewhere.example/simple\nrequests\n"
    _, result, calls = _install(tmp_path, {"greedy": hijack})

    assert result.returncode != 0, "the install went ahead"
    assert not _installs(calls), "pip installed something anyway"


def test_the_refused_line_is_quoted(tmp_path):
    """Whoever wrote the plugin has to be able to find it, so core names the
    file, the line number and the line itself."""
    carried = "requests\n--extra-index-url https://elsewhere.example\n"
    _, result, _ = _install(tmp_path, {"greedy": carried})

    assert "plugins/greedy/requirements.txt" in result.stderr
    assert "2:--extra-index-url https://elsewhere.example" in result.stderr


def test_a_comment_is_not_an_option(tmp_path):
    """Refusing options must not refuse an ordinary file that explains itself."""
    ordinary = "# what the plugin imports\n\nrequests>=2.0\n"
    _, result, calls = _install(tmp_path, {"polite": ordinary})

    assert result.returncode == 0, result.stderr
    assert _installs(calls), "an ordinary plugin file was not installed"


def test_the_script_names_no_plugin():
    """Core walks whatever is there. Naming a plugin would make the next one a
    core change again, which is the whole problem."""
    present = sorted(
        path.name for path in (REPO_ROOT / "plugins").iterdir() if path.is_dir()
    )
    assert present, "no plugins in the tree; this test has nothing to check"
    text = SCRIPT.read_text(encoding="utf-8") + DOCKERFILE.read_text(encoding="utf-8")
    named = [
        name for name in present
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text)
    ]
    assert not named, f"plugins named by hand: {named}"


def test_the_image_build_installs_through_the_script():
    """A second copy of the walk in the Dockerfile is a second definition of what
    Omega depends on, and the two would drift."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert SCRIPT.name in dockerfile
    assert not re.search(r"-r\s+\S*requirements\.txt", dockerfile), \
        "the Dockerfile installs a requirements file itself"
    assert os.access(SCRIPT, os.X_OK), "the build runs the script directly"


def _install_step():
    """The Dockerfile's line that runs the script, wrapping read as one line."""
    for command in _unwrapped(DOCKERFILE.read_text(encoding="utf-8")):
        if SCRIPT.name in command and command.lstrip().startswith("RUN"):
            return command
    raise AssertionError("the Dockerfile does not run the script")


def test_editing_a_plugin_does_not_reinstall_everything():
    """The install step pulls down torch and transformers, so what its cache
    turns on matters. Reading plugins/ here would key it on every file a plugin
    carries, and editing a line of plugin code would fetch the lot again. It
    sees a stage holding the declared requirements and nothing else."""
    step = _install_step()

    assert "source=plugins" not in step, \
        "the install step reads plugins/ and reinstalls on any change under it"
    assert "from=plugin-requirements" in step, \
        "the install step does not read the collected requirements"


def test_the_collected_requirements_keep_their_plugin_directories():
    """The script walks plugins/*/requirements.txt, so flattening the files into
    one directory would leave it finding nothing and quietly installing less."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "FROM scratch AS plugin-requirements\n" in dockerfile, \
        "the collected requirements are not a stage of their own"
    assert re.search(r'/plugin-requirements/\$plugin', dockerfile), \
        "the collected files do not keep a directory per plugin"


def test_the_source_install_goes_through_the_script():
    """The README is the other install path, and it is the one that was wrong:
    it installed core's requirements and no plugin's."""
    readme = README.read_text(encoding="utf-8")
    assert f"scripts/{SCRIPT.name}" in readme
    assert not re.search(r"-r\s+\S*requirements\.txt", readme), \
        "the README installs a requirements file itself"


def test_the_torch_version_is_pinned_in_one_place():
    """Torch installs separately because it comes from the CPU wheel index, and
    the step after it installs requirements.txt, which pins torch too. A second
    copy of the version in the Dockerfile would drift, and the drift is silent:
    pip replaces the CPU build with PyPI's CUDA one and the build still passes.
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert not re.search(r"torch[=<>!~]", dockerfile), \
        "the Dockerfile pins a torch version of its own"
    assert re.search(r"^torch[=<>!~]", CORE_REQUIREMENTS.read_text(encoding="utf-8"), re.M), \
        "the CPU-index step reads torch's version from requirements.txt, which does not pin it"


def test_the_readme_installs_the_torch_version_core_pins():
    """The CPU wheel index serves a newer torch than core pins, so installing it
    unpinned and then installing requirements.txt swaps the CPU build for PyPI's
    CUDA one — a multi-gigabyte download, no error, and the wrong wheel."""
    for command in _unwrapped(README.read_text(encoding="utf-8")):
        if "download.pytorch.org" in command:
            assert "requirements.txt" in command, \
                f"README installs torch without core's pin: {command}"


def test_the_plugin_api_documents_declaring_dependencies():
    """The contract a plugin author reads. Without it the file is a convention
    that happens to work, which is how the gap went unnoticed."""
    doc = PLUGIN_API_DOC.read_text(encoding="utf-8")
    assert "requirements.txt" in doc
    assert SCRIPT.name in doc
