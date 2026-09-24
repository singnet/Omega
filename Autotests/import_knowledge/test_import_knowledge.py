"""
Test: scripts/import_knowledge.sh provider branching, sentinel skip/force logic
and the OpenAI key check, with import-knowledge stubbed on PATH.

Run:
    cd Autotests && pytest -s import_knowledge/test_import_knowledge.py
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "import_knowledge.sh"


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "import_called"
    stub = bindir / "import-knowledge"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{marker}"\n'
        "exit 0\n"
    )
    stub.chmod(0o755)

    chroma = tmp_path / "chroma"
    e = dict(os.environ)
    e["PATH"] = f"{bindir}:{e['PATH']}"
    e["CHROMA_DB_PATH"] = str(chroma)
    e.pop("IMPORT_KB_FORCE", None)
    e.pop("OPENAI_API_KEY", None)
    e.pop("ASI_API_KEY", None)
    e.pop("EMBEDDING_PROVIDER", None)
    e.pop("EMBEDDING_MODEL", None)
    return {"env": e, "marker": marker, "chroma": chroma}


def run(env):
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True
    )


# Local provider runs the import and leaves the local sentinel behind.
def test_local_runs_import_and_writes_sentinel(env):
    env["env"]["EMBEDDING_PROVIDER"] = "Local"
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert env["marker"].exists()
    assert "--local" in env["marker"].read_text()
    assert (env["chroma"] / ".import-kb.local.done").exists()
    assert "Import complete" in r.stdout


# OpenAI with a key set imports and leaves the openai sentinel.
def test_openai_with_key_runs_import_and_writes_sentinel(env):
    env["env"]["EMBEDDING_PROVIDER"] = "OpenAI"
    env["env"]["OPENAI_API_KEY"] = "dummy-key"
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert env["marker"].exists()
    assert env["marker"].read_text().strip() == "--provider openai"
    assert (env["chroma"] / ".import-kb.openai.done").exists()


# OpenAI without a key stops at exit 1 and imports nothing.
def test_openai_without_key_exit1(env):
    env["env"]["EMBEDDING_PROVIDER"] = "OpenAI"
    r = run(env["env"])
    assert r.returncode == 1
    assert "OPENAI_API_KEY is required" in r.stderr
    assert not env["marker"].exists()


# A provider the script doesn't know is rejected with exit 1.
def test_unknown_provider_exit1(env):
    env["env"]["EMBEDDING_PROVIDER"] = "Cohere"
    r = run(env["env"])
    assert r.returncode == 1
    assert "Unsupported" in r.stderr
    assert not env["marker"].exists()


# The provider name is matched no matter how it's cased.
@pytest.mark.parametrize(
    "provider,sentinel",
    [
        ("openai", ".import-kb.openai.done"),
        ("OpenAI", ".import-kb.openai.done"),
        ("OPENAI", ".import-kb.openai.done"),
        ("local", ".import-kb.local.done"),
        ("Local", ".import-kb.local.done"),
        ("LOCAL", ".import-kb.local.done"),
    ],
)
def test_provider_case_insensitive(env, provider, sentinel):
    env["env"]["EMBEDDING_PROVIDER"] = provider
    if provider.lower() == "openai":
        env["env"]["OPENAI_API_KEY"] = "dummy-key"
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert (env["chroma"] / sentinel).exists()


# If the matching sentinel is already there, the import is skipped.
def test_existing_sentinel_skips_import(env):
    env["env"]["EMBEDDING_PROVIDER"] = "Local"
    env["chroma"].mkdir(parents=True)
    (env["chroma"] / ".import-kb.local.done").write_text("2026-01-01T00:00:00")
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert "skipping" in r.stdout.lower()
    assert not env["marker"].exists()


# IMPORT_KB_FORCE=1 re-runs the import even with the sentinel present.
def test_force_reimports_despite_sentinel(env):
    env["env"]["EMBEDDING_PROVIDER"] = "Local"
    env["env"]["IMPORT_KB_FORCE"] = "1"
    env["chroma"].mkdir(parents=True)
    (env["chroma"] / ".import-kb.local.done").write_text("old")
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert env["marker"].exists()
    assert "--local" in env["marker"].read_text()


# Local and OpenAI track separate sentinels, so one being done doesn't block the other.
def test_local_openai_sentinels_independent(env):
    env["env"]["EMBEDDING_PROVIDER"] = "OpenAI"
    env["env"]["OPENAI_API_KEY"] = "dummy-key"
    env["chroma"].mkdir(parents=True)
    (env["chroma"] / ".import-kb.local.done").write_text("local-done")
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert env["marker"].exists()
    assert (env["chroma"] / ".import-kb.openai.done").exists()


# CHROMA_DB_PATH sends the DB and its sentinel to a custom directory.
def test_custom_chroma_path(env, tmp_path):
    custom = tmp_path / "custom_chroma"
    env["env"]["CHROMA_DB_PATH"] = str(custom)
    env["env"]["EMBEDDING_PROVIDER"] = "Local"
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert custom.is_dir()
    assert (custom / ".import-kb.local.done").exists()


# When the import fails, no sentinel is written, so the next start tries again.
def test_failed_import_does_not_write_sentinel(env):
    env["env"]["EMBEDDING_PROVIDER"] = "Local"
    stub = env["marker"].parent / "bin" / "import-knowledge"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{env["marker"]}"\n'
        "exit 3\n"
    )
    stub.chmod(0o755)
    r = run(env["env"])
    assert r.returncode != 0
    assert env["marker"].exists()
    assert not (env["chroma"] / ".import-kb.local.done").exists()


def test_asicloud_with_key_runs_import_and_writes_sentinel(env):
    env["env"]["EMBEDDING_PROVIDER"] = "ASICloud"
    env["env"]["ASI_API_KEY"] = "dummy-key"
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert env["marker"].read_text().strip() == "--provider asicloud"
    assert (env["chroma"] / ".import-kb.asicloud.done").exists()


def test_asicloud_without_key_exit1(env):
    env["env"]["EMBEDDING_PROVIDER"] = "ASICloud"
    r = run(env["env"])
    assert r.returncode == 1
    assert "ASI_API_KEY is required" in r.stderr
    assert not env["marker"].exists()


def test_embedding_model_is_passed_to_the_import(env):
    env["env"]["EMBEDDING_PROVIDER"] = "ASICloud"
    env["env"]["ASI_API_KEY"] = "dummy-key"
    env["env"]["EMBEDDING_MODEL"] = "BAAI/bge-base-en-v1.5"
    r = run(env["env"])
    assert r.returncode == 0, r.stderr
    assert env["marker"].read_text().strip() == (
        "--provider asicloud --model BAAI/bge-base-en-v1.5"
    )
