"""Unit tests for the LLM provider routes in proxy/nginx.conf.template.

In the Docker image every LLM request goes through this proxy. When a route
gives up before the provider answers, nginx returns 504, the provider call
fails and the agent sends nothing back to the user (#321). The OpenAI client
used by the providers waits up to 600 seconds, so each LLM route has to wait
at least as long.

No container, no network: the template is read as text.
"""
import os
import re

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TEMPLATE = os.path.join(_REPO_ROOT, "proxy", "nginx.conf.template")

LLM_ROUTES = ["anthropic", "asicloud", "openai", "asione", "openaiapi", "openrouter"]
CLIENT_TIMEOUT_SECONDS = 600

_UNITS = {"s": 1, "m": 60, "h": 3600}


def _seconds(value):
    match = re.fullmatch(r"(\d+)([smh]?)", value)
    assert match, f"unsupported nginx time value: {value}"
    return int(match.group(1)) * _UNITS.get(match.group(2) or "s")


def _directive(text, name):
    match = re.search(rf"^\s*{name}\s+(\S+);", text, re.MULTILINE)
    return match.group(1) if match else None


@pytest.fixture(scope="module")
def template():
    with open(_TEMPLATE, encoding="utf-8") as f:
        return f.read()


def _route_block(template, route):
    match = re.search(rf"location /{route}/ \{{\n(.*?)\n\s*\}}\n", template, re.DOTALL)
    assert match, f"no location block for /{route}/"
    return match.group(1)


def _effective(template, route, name):
    http_defaults = template.split("server {", 1)[0]
    value = _directive(_route_block(template, route), name) or _directive(http_defaults, name)
    assert value, f"{name} is not set for /{route}/"
    return _seconds(value)


@pytest.mark.parametrize("route", LLM_ROUTES)
def test_llm_route_waits_as_long_as_the_client_for_a_response(template, route):
    assert _effective(template, route, "proxy_read_timeout") >= CLIENT_TIMEOUT_SECONDS


@pytest.mark.parametrize("route", LLM_ROUTES)
def test_llm_route_waits_as_long_as_the_client_to_send_the_request(template, route):
    assert _effective(template, route, "proxy_send_timeout") >= CLIENT_TIMEOUT_SECONDS
