"""Prepare private nginx routes and a credential-free JSON catalog."""

import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


PROVIDER_URLS = {
    "OpenAI": "https://api.openai.com/v1/",
    "Anthropic": "https://api.anthropic.com/v1/",
    "ASICloud": "https://inference.asicloud.cudos.org/v1/",
    "ASIOne": "https://api.asi1.ai/v1/",
    "OpenRouter": "https://openrouter.ai/api/v1/",
}


def nginx_literal(value):
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Control characters are not allowed in gateway settings")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$') + '"'


def route(path, base, token):
    url = urlsplit(base)
    if (url.scheme not in ("http", "https") or not url.hostname
            or url.username or url.password or url.query or url.fragment):
        raise ValueError("Provider URL must be HTTP(S), without credentials, query or fragment")
    return f'''location /{path}/ {{
    proxy_pass {nginx_literal(base.rstrip('/') + '/')};
    proxy_set_header Authorization {nginx_literal('Bearer ' + token)};
    proxy_set_header Host {nginx_literal(url.netloc)};
    proxy_set_header Content-Type $content_type;
    proxy_ssl_server_name on;
    proxy_ssl_name {nginx_literal(url.hostname)};
    proxy_ssl_protocols TLSv1.2 TLSv1.3;
    proxy_http_version 1.1;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
}}'''


def prepare(raw, routes_path, catalog_path, embeddings="Local"):
    catalog = json.loads(raw)
    if not isinstance(catalog, dict) or set(catalog) not in (
            {"routine"}, {"routine", "premium"}):
        raise ValueError("Catalog requires routine and optionally premium")
    routes, records = [], {}
    openai_selection = None
    for role, record in catalog.items():
        if not isinstance(record, dict):
            raise ValueError("Catalog entries must be records")
        provider = record.get("provider")
        if provider not in (*PROVIDER_URLS, "OpenAIAPI", "Test"):
            raise ValueError("Unsupported catalog provider")
        fields = ("api_token_var", "model", "openaiapi_url", "token")
        if any(not isinstance(record.get(field), str) for field in fields):
            raise ValueError("Catalog fields must be strings")
        if provider != "Test":
            if not record["token"]:
                raise ValueError("Catalog token must not be empty")
            base = record["openaiapi_url"] if provider == "OpenAIAPI" else PROVIDER_URLS[provider]
            routes.append(route(f"catalog/{role}", base, record["token"]))
            if provider == "OpenAI" and openai_selection is None:
                openai_selection = (base, record["token"])
        # Only known, credential-free fields enter the agent's catalog.
        records[role] = {
            field: record[field]
            for field in ("provider", "api_token_var", "model", "openaiapi_url")
        }
    if embeddings == "OpenAI":
        if openai_selection is None:
            raise ValueError("OpenAI embeddings require a selected OpenAI provider")
        routes.append(route("openai", *openai_selection))
    # Set permissions at creation, before writing any credentials.
    fd = os.open(routes_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write("\n\n".join(routes) + "\n")
    Path(catalog_path).write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(catalog_path, 0o644)


if __name__ == "__main__":
    try:
        prepare(sys.stdin.read(), *sys.argv[1:])
    except (ValueError, TypeError, KeyError, OSError):
        # Never echo the raw catalog or credentials in startup errors.
        raise SystemExit("Unable to prepare router catalog; check catalog fields and output paths")
