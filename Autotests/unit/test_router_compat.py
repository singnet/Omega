import importlib.util
import json
import os

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TEMPLATE = os.path.join(_REPO_ROOT, "proxy", "nginx.conf.template")
_ROUTER_CATALOG = os.path.join(_REPO_ROOT, "src", "router_catalog.py")


@pytest.fixture(scope="module")
def router_catalog():
    spec = importlib.util.spec_from_file_location("router_catalog", _ROUTER_CATALOG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(provider, var, token):
    return {"provider": provider, "api_token_var": var, "model": "m",
            "openaiapi_url": "http://localhost:8080/", "token": token}



def test_asicloud_embeddings_route_is_part_of_the_assembled_gateway_configuration(router_catalog, tmp_path, monkeypatch):
    monkeypatch.setenv("ASI_API_KEY", "fake-token-43")
    catalog = {"routine": _record("Anthropic", "ANTHROPIC_API_KEY", "fake-token-routine")}
    routes = tmp_path / "router.conf"
    router_catalog.prepare(json.dumps(catalog), str(routes), str(tmp_path / "catalog.json"), "ASICloud")
    with open(_TEMPLATE, encoding="utf-8") as f:
        template = f.read()

    assembled = template.replace("include /opt/nginx/router.conf;", routes.read_text(encoding="utf-8"))

    assert "location /asicloud/ {" in assembled
