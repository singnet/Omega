import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"
TOKEN_VARS = {
    "Anthropic": "ANTHROPIC_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
    "ASICloud": "ASI_API_KEY",
    "ASIOne": "ASIONE_API_KEY",
    "OpenRouter": "OPENROUTER_API_KEY",
    "OpenAIAPI": "OPENAIAPI_API_KEY",
}


def _legacy_fragment():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    return source.split("python3 - \"${legacy_llm_args[@]}\" <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


def _run(*arguments, **environment):
    return subprocess.run(
        [sys.executable, "-I", "-", *arguments],
        input=_legacy_fragment(),
        env={**{k: os.environ[k] for k in ("PATH", "SYSTEMROOT") if k in os.environ}, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def _catalog(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("provider, token_var", sorted(TOKEN_VARS.items()))
def test_legacy_arguments_become_one_routine_record_with_the_provider_token(provider, token_var):
    result = _run(f"provider={provider}", "model=model-x", **{token_var: "fake-token-53"})
    catalog = _catalog(result)
    assert list(catalog) == ["routine"]
    record = catalog["routine"]
    assert record["provider"] == provider
    assert record["api_token_var"] == token_var
    assert record["model"] == "model-x"
    assert record["token"] == "fake-token-53"


def test_legacy_record_uses_the_key_of_the_chosen_provider_only():
    result = _run("provider=OpenAI", ANTHROPIC_API_KEY="fake-token-a", OPENAI_API_KEY="fake-token-o")
    record = _catalog(result)["routine"]
    assert (record["api_token_var"], record["token"]) == ("OPENAI_API_KEY", "fake-token-o")



def test_unknown_provider_is_rejected_with_a_message():
    result = _run("provider=Bogus", ANTHROPIC_API_KEY="fake-token-55")
    assert result.returncode != 0
    assert "Unsupported legacy LLM provider" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("provider, token_var", sorted(TOKEN_VARS.items()))
def test_missing_key_is_rejected_naming_the_variable_and_not_printing_other_keys(provider, token_var):
    others = {var: f"fake-token-other-{var}" for var in TOKEN_VARS.values() if var != token_var}
    result = _run(f"provider={provider}", **others)
    assert result.returncode != 0
    assert f"{token_var} is required for legacy LLM configuration" in result.stderr
    assert result.stdout == ""
    assert "fake-token" not in result.stderr


def test_empty_key_is_rejected_like_a_missing_one():
    result = _run("provider=Anthropic", ANTHROPIC_API_KEY="")
    assert result.returncode != 0
    assert "ANTHROPIC_API_KEY is required" in result.stderr
    assert result.stdout == ""


def test_test_provider_passes_without_a_key():
    result = _run("provider=Test")
    record = _catalog(result)["routine"]
    assert record["provider"] == "Test"
    assert record["token"] == ""


def test_url_and_model_arguments_reach_the_record_and_the_token_is_printed_once():
    result = _run(
        "provider=OpenAIAPI", "model=model-x", "openaiapi_url=http://stub.example:19101/v1",
        OPENAIAPI_API_KEY="fake-token-58",
    )
    record = _catalog(result)["routine"]
    assert record["model"] == "model-x"
    assert record["openaiapi_url"] == "http://stub.example:19101/v1"
    assert record["token"] == "fake-token-58"
    assert result.stdout.count("fake-token-58") == 1
    assert result.stderr == ""
