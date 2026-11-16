import importlib.util
import json
import os
import re
import stat
from pathlib import Path

import pytest

import config


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "proxy" / "nginx.conf.template"


def _load_router_catalog():
    spec = importlib.util.spec_from_file_location("router_catalog", REPO_ROOT / "src" / "router_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


router_catalog = _load_router_catalog()

PROVIDER_URLS = {
    "Anthropic": "https://api.anthropic.com/v1/",
    "OpenAI": "https://api.openai.com/v1/",
    "ASICloud": "https://inference.asicloud.cudos.org/v1/",
    "ASIOne": "https://api.asi1.ai/v1/",
    "OpenRouter": "https://openrouter.ai/api/v1/",
}
TOKEN_VARS = {
    "Anthropic": "ANTHROPIC_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
    "ASICloud": "ASI_API_KEY",
    "ASIOne": "ASIONE_API_KEY",
    "OpenRouter": "OPENROUTER_API_KEY",
    "OpenAIAPI": "OPENAIAPI_API_KEY",
    "Test": "",
}


def _record(provider="Anthropic", token="fake-token-1", model="model-a", url=""):
    return {
        "provider": provider,
        "api_token_var": TOKEN_VARS[provider],
        "model": model,
        "openaiapi_url": url,
        "token": token,
    }


def _prepare(tmp_path, catalog, embeddings="Local"):
    routes = tmp_path / "router.conf"
    published = tmp_path / "catalog.json"
    router_catalog.prepare(json.dumps(catalog), str(routes), str(published), embeddings)
    return routes.read_text(encoding="utf-8"), published.read_text(encoding="utf-8")


def _blocks(routes_text):
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r"location /(\S+?)/ \{\n(.*?)\n\}", routes_text, re.DOTALL)
    }


def _header(block, name):
    match = re.search(rf"^\s*proxy_set_header {name} (.*);$", block, re.MULTILINE)
    assert match, f"no {name} header in block"
    return match.group(1)


def _proxy_pass(block):
    return re.search(r"^\s*proxy_pass (.*);$", block, re.MULTILINE).group(1)


def test_one_record_makes_one_routine_route_and_a_one_role_catalog(tmp_path):
    routes, published = _prepare(tmp_path, {"routine": _record()})
    assert list(_blocks(routes)) == ["catalog/routine"]
    assert "catalog/premium" not in routes
    assert list(json.loads(published)) == ["routine"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_routes_are_private_and_the_published_catalog_is_readable(tmp_path):
    _prepare(tmp_path, {"routine": _record()})
    assert stat.S_IMODE(os.stat(tmp_path / "router.conf").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "catalog.json").st_mode) == 0o644


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_routes_file_that_already_exists_becomes_private_again(tmp_path):
    existing = tmp_path / "router.conf"
    existing.write_text("old")
    existing.chmod(0o666)
    _prepare(tmp_path, {"routine": _record()})
    assert stat.S_IMODE(os.stat(existing).st_mode) == 0o600


def test_each_role_route_carries_its_own_token_and_provider_url(tmp_path):
    routes, _ = _prepare(tmp_path, {
        "routine": _record("Anthropic", "fake-token-routine"),
        "premium": _record("OpenRouter", "fake-token-premium"),
    })
    blocks = _blocks(routes)
    assert set(blocks) == {"catalog/routine", "catalog/premium"}
    assert _header(blocks["catalog/routine"], "Authorization") == '"Bearer fake-token-routine"'
    assert _header(blocks["catalog/premium"], "Authorization") == '"Bearer fake-token-premium"'
    assert _proxy_pass(blocks["catalog/routine"]) == f'"{PROVIDER_URLS["Anthropic"]}"'
    assert _proxy_pass(blocks["catalog/premium"]) == f'"{PROVIDER_URLS["OpenRouter"]}"'
    assert "fake-token-premium" not in blocks["catalog/routine"]
    assert "fake-token-routine" not in blocks["catalog/premium"]


@pytest.mark.parametrize("provider", sorted(PROVIDER_URLS))
def test_every_hosted_provider_routes_to_its_own_url(tmp_path, provider):
    routes, _ = _prepare(tmp_path, {"routine": _record(provider)})
    block = _blocks(routes)["catalog/routine"]
    assert _proxy_pass(block) == f'"{PROVIDER_URLS[provider]}"'
    assert _header(block, "Host") == f'"{PROVIDER_URLS[provider].split("/")[2]}"'


def test_tokens_never_reach_the_published_catalog(tmp_path):
    routes, published = _prepare(tmp_path, {
        "routine": _record("Anthropic", "fake-token-routine"),
        "premium": _record("OpenAI", "fake-token-premium"),
    })
    assert "fake-token-routine" in routes
    assert "fake-token-premium" in routes
    assert "fake-token" not in published
    for record in json.loads(published).values():
        assert set(record) == {"provider", "api_token_var", "model", "openaiapi_url"}


def test_published_catalog_keeps_provider_model_variable_and_url_of_each_role(tmp_path):
    _, published = _prepare(tmp_path, {
        "routine": _record("OpenAIAPI", model="budget", url="http://stub.example:19101/v1"),
        "premium": _record("OpenAI", model="deep"),
    })
    assert json.loads(published) == {
        "routine": {"provider": "OpenAIAPI", "api_token_var": "OPENAIAPI_API_KEY",
                    "model": "budget", "openaiapi_url": "http://stub.example:19101/v1"},
        "premium": {"provider": "OpenAI", "api_token_var": "OPENAI_API_KEY",
                    "model": "deep", "openaiapi_url": ""},
    }


def test_unknown_record_fields_are_not_published(tmp_path):
    record = _record()
    record["note"] = "fake-token-note"
    _, published = _prepare(tmp_path, {"routine": record})
    assert "fake-token-note" not in published


INVALID_CATALOGS = {
    "premium-without-routine": {"premium": _record()},
    "unknown-role": {"routine": _record(), "backup": _record()},
    "unknown-role-only": {"backup": _record()},
    "three-roles": {"routine": _record(), "premium": _record(), "backup": _record()},
    "empty-object": {},
    "not-an-object": [_record()],
    "record-is-not-an-object": {"routine": "Anthropic"},
    "unknown-provider": {"routine": {**_record(), "provider": "Bogus"}},
    "empty-token": {"routine": _record(token="")},
    "missing-token": {"routine": {k: v for k, v in _record().items() if k != "token"}},
    "missing-model": {"routine": {k: v for k, v in _record().items() if k != "model"}},
    "numeric-model": {"routine": {**_record(), "model": 5}},
    "null-url": {"routine": {**_record(), "openaiapi_url": None}},
    "numeric-token": {"routine": {**_record(), "token": 12345}},
}


@pytest.mark.parametrize("catalog", INVALID_CATALOGS.values(), ids=INVALID_CATALOGS.keys())
def test_invalid_catalog_is_rejected_and_nothing_is_written(tmp_path, catalog):
    with pytest.raises(ValueError):
        router_catalog.prepare(json.dumps(catalog), str(tmp_path / "router.conf"), str(tmp_path / "catalog.json"))
    assert not (tmp_path / "router.conf").exists()
    assert not (tmp_path / "catalog.json").exists()


def test_test_provider_needs_no_token_and_gets_no_route(tmp_path):
    routes, published = _prepare(tmp_path, {"routine": _record("Test", token="")})
    assert _blocks(routes) == {}
    assert json.loads(published)["routine"]["provider"] == "Test"


def test_test_role_is_skipped_while_the_other_role_keeps_its_route(tmp_path):
    routes, _ = _prepare(tmp_path, {
        "routine": _record("Test", token=""),
        "premium": _record("Anthropic", "fake-token-premium"),
    })
    assert list(_blocks(routes)) == ["catalog/premium"]


def test_openaiapi_role_proxies_to_the_url_of_its_own_record(tmp_path):
    routes, _ = _prepare(tmp_path, {
        "routine": _record("OpenAIAPI", "fake-token-routine", url="http://stub-a.example:19101/v1"),
        "premium": _record("OpenAIAPI", "fake-token-premium", url="https://stub-b.example/api"),
    })
    blocks = _blocks(routes)
    assert _proxy_pass(blocks["catalog/routine"]) == '"http://stub-a.example:19101/v1/"'
    assert _header(blocks["catalog/routine"], "Host") == '"stub-a.example:19101"'
    assert _proxy_pass(blocks["catalog/premium"]) == '"https://stub-b.example/api/"'
    assert _header(blocks["catalog/premium"], "Host") == '"stub-b.example"'


def test_token_with_special_characters_is_escaped_in_the_authorization_header(tmp_path):
    routes, _ = _prepare(tmp_path, {"routine": _record(token='test"fake\\token$x;}')})
    block = _blocks(routes)["catalog/routine"]
    assert _header(block, "Authorization") == '"Bearer test\\"fake\\\\token\\$x;}"'


@pytest.mark.parametrize("control", ["\n", "\r", "\x00", "\t", "\x7f"], ids=["lf", "cr", "nul", "tab", "del"])
def test_token_with_a_control_character_is_rejected(tmp_path, control):
    with pytest.raises(ValueError):
        router_catalog.prepare(
            json.dumps({"routine": _record(token=f"fake{control}token")}),
            str(tmp_path / "router.conf"), str(tmp_path / "catalog.json"))
    assert not (tmp_path / "router.conf").exists()


@pytest.mark.parametrize("url", [
    "http://user:pass@stub.example/v1",
    "http://user@stub.example/v1",
    "http://stub.example/v1?key=value",
    "http://stub.example/v1#fragment",
    "ftp://stub.example/v1",
    "stub.example/v1",
    "http:///v1",
], ids=["login-and-password", "login", "query", "fragment", "other-scheme", "no-scheme", "no-host"])
def test_unsafe_provider_url_is_rejected(tmp_path, url):
    with pytest.raises(ValueError):
        router_catalog.prepare(
            json.dumps({"routine": _record("OpenAIAPI", url=url)}),
            str(tmp_path / "router.conf"), str(tmp_path / "catalog.json"))
    assert not (tmp_path / "router.conf").exists()


def test_openai_embeddings_route_uses_the_token_of_the_openai_role(tmp_path):
    routes, _ = _prepare(tmp_path, {
        "routine": _record("Anthropic", "fake-token-routine"),
        "premium": _record("OpenAI", "fake-token-openai"),
    }, embeddings="OpenAI")
    blocks = _blocks(routes)
    assert set(blocks) == {"catalog/routine", "catalog/premium", "openai"}
    assert _header(blocks["openai"], "Authorization") == '"Bearer fake-token-openai"'
    assert _proxy_pass(blocks["openai"]) == f'"{PROVIDER_URLS["OpenAI"]}"'


def test_openai_embeddings_route_with_a_single_openai_role(tmp_path):
    routes, _ = _prepare(tmp_path, {"routine": _record("OpenAI", "fake-token-openai")}, embeddings="OpenAI")
    blocks = _blocks(routes)
    assert set(blocks) == {"catalog/routine", "openai"}
    assert _header(blocks["openai"], "Authorization") == '"Bearer fake-token-openai"'


@pytest.mark.parametrize("embeddings", ["Local", "ASICloud"])
def test_no_openai_route_unless_openai_embeddings_are_selected(tmp_path, embeddings):
    routes, _ = _prepare(tmp_path, {"routine": _record("OpenAI")}, embeddings=embeddings)
    assert "openai" not in _blocks(routes)


NON_LLM_LOCATIONS = [
    "location = /openclaw/v1/responses",
    "location /telegram/",
    "location /telegram-file/",
    "location /mattermost/",
    "location /slack/",
    "location /slack-files/",
    "location = /auth/status",
    "location = /auth/verify",
    "location /health",
]


@pytest.mark.parametrize("location", NON_LLM_LOCATIONS)
def test_non_llm_locations_of_the_template_are_kept(location):
    assert re.search(rf"^\s*{re.escape(location)} \{{$", TEMPLATE.read_text(encoding="utf-8"), re.MULTILINE)


def test_template_includes_the_generated_routes_inside_the_server_block():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.count("include /opt/nginx/router.conf;") == 1
    assert text.index("server {") < text.index("include /opt/nginx/router.conf;")


def _catalog_file(tmp_path, content):
    path = tmp_path / "catalog.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return str(path)


def test_read_router_catalog_turns_two_roles_into_one_metta_expression(tmp_path):
    path = _catalog_file(tmp_path, {
        "routine": {"provider": "Anthropic", "model": "claude"},
        "premium": {"provider": "OpenAI", "model": "gpt"},
    })
    assert config.read_router_catalog(path) == (
        '(routerCatalog ((routine ((provider "Anthropic") (model "claude"))) '
        '(premium ((provider "OpenAI") (model "gpt")))))'
    )


def test_read_router_catalog_keeps_quotes_spaces_and_unicode_inside_one_string(tmp_path):
    path = _catalog_file(tmp_path, {"routine": {"model": 'say "hi" (now) ünï 世界'}})
    assert config.read_router_catalog(path) == '(routerCatalog ((routine ((model "say \\"hi\\" (now) ünï 世界")))))'


def test_read_router_catalog_reads_what_prepare_publishes(tmp_path):
    _prepare(tmp_path, {
        "routine": _record("OpenAIAPI", model="budget", url="http://stub.example:19101/v1"),
        "premium": _record("OpenAI", model="deep"),
    })
    text = config.read_router_catalog(str(tmp_path / "catalog.json"))
    for fragment in ('(routine ((provider "OpenAIAPI")', '(model "budget")',
                     '(openaiapi_url "http://stub.example:19101/v1")',
                     '(premium ((provider "OpenAI")', '(api_token_var "OPENAI_API_KEY")'):
        assert fragment in text


def test_read_router_catalog_reports_a_missing_file(tmp_path):
    with pytest.raises(ValueError, match="Could not load router catalog"):
        config.read_router_catalog(str(tmp_path / "absent.json"))


def test_read_router_catalog_reports_an_empty_path():
    with pytest.raises(ValueError, match="Could not load router catalog"):
        config.read_router_catalog("")


def test_read_router_catalog_reports_a_file_that_is_not_json(tmp_path):
    with pytest.raises(ValueError, match="Could not load router catalog"):
        config.read_router_catalog(_catalog_file(tmp_path, "{not json"))


@pytest.mark.parametrize("content", [
    ([{"provider": "Anthropic"}]),
    ("\"routine\""),
    ({"routine": "Anthropic"}),
    ({"routine": {"model": 5}}),
    ({"routine": {"model": None}}),
    ({"routine": {"model": ["a"]}}),
    ({"rou tine": {"model": "m"}}),
    ({"routine) (evil": {"model": "m"}}),
    ({"1routine": {"model": "m"}}),
    ({"": {"model": "m"}}),
    ({"routine": {"mo del": "m"}}),
    ({"routine": {"model) (evil": "m"}}),
    ({"routine": {"model-x": "m"}}),
])
def test_read_router_catalog_rejects_what_could_inject_into_metta(tmp_path, content):
    with pytest.raises(ValueError):
        config.read_router_catalog(_catalog_file(tmp_path, content))
