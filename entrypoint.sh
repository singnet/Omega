#!/usr/bin/env bash
set -euo pipefail

# Adds slash at the end which is critical to Nginx configuration work properly
nginx_url() {
    text=$1
    [[ ${text} != */ ]] && text="${text}/"
    echo "${text}"
}

cd /PeTTa

EMBEDDING_PROVIDER="${EMBEDDING_PROVIDER:-Local}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-}"
MM_URL="http://localhost:8080/" # dummy value
OPENCLAW_URL="http://localhost:8080/" # dummy value
router_catalog=""
legacy_llm_args=()
agent_args=()
for arg in "$@"; do
  case "$arg" in
    router_catalog=*) router_catalog="${arg#*=}"; continue ;;
    openaiapi_url=*) legacy_llm_args+=("$arg"); continue ;;
    provider=*|model=*) legacy_llm_args+=("$arg") ;;
    routerCatalogFile=*) continue ;;
  esac
  agent_args+=("$arg")
  if [[ "$arg" == embeddingprovider=* ]]; then
    EMBEDDING_PROVIDER="${arg#*=}"
  fi
  if [[ "$arg" == embeddingModel=* ]]; then
    EMBEDDING_MODEL="${arg#*=}"
  fi
  # URL to redirect Mattermost communication channel requests
  if [[ "$arg" == MM_URL=* ]]; then
    MM_URL=$(nginx_url "${arg#*=}")
  fi
  # URL to redirect OpenClaw Gateway requests
  if [[ "$arg" == openclaw_url=* ]]; then
    OPENCLAW_URL=$(nginx_url "${arg#*=}")
  fi
done
export EMBEDDING_PROVIDER EMBEDDING_MODEL MM_URL OPENCLAW_URL

if [[ -z "$router_catalog" ]]; then
  # Adapt legacy provider/model arguments and API-key environment variables to
  # the same single-record catalog used by non-routing launches.
  router_catalog="$(python3 - "${legacy_llm_args[@]}" <<'PY'
import json
import os
import sys

settings = dict(arg.split("=", 1) for arg in sys.argv[1:])
provider = settings.get("provider", "ASICloud")
token_vars = {
    "Anthropic": "ANTHROPIC_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
    "ASICloud": "ASI_API_KEY",
    "ASIOne": "ASIONE_API_KEY",
    "OpenRouter": "OPENROUTER_API_KEY",
    "OpenAIAPI": "OPENAIAPI_API_KEY",
}
if provider not in token_vars:
    raise SystemExit("Unsupported legacy LLM provider")
token_var = token_vars[provider]
token = os.environ.get(token_var, "")
if not token:
    raise SystemExit(f"{token_var} is required for legacy LLM configuration")
print(json.dumps({"routine": {
    "provider": provider,
    "api_token_var": token_var,
    "model": settings.get("model", ""),
    "openaiapi_url": settings.get("openaiapi_url", "http://localhost:8080/"),
    "token": token,
}}))
PY
)"
fi
catalog_file=/tmp/omega-router-catalog.json
printf '%s' "$router_catalog" | python3 "${OMEGA_DIR}/src/router_catalog.py" \
  /opt/nginx/router.conf "$catalog_file" "$EMBEDDING_PROVIDER"
chown www-data:www-data /opt/nginx/router.conf
set -- "${agent_args[@]}" "routerCatalogFile=$catalog_file"
unset router_catalog legacy_llm_args agent_args arg

agent_su=(su --group nogroup nobody)

su www-data -s /bin/sh -c "sh /opt/nginx/nginx.sh"

# Optional knowledge-base import
if [[ "${IMPORT_KB_ON_START}" == "1" ]]; then
  su nobody -s /bin/sh -c "${OMEGA_DIR}/scripts/import_knowledge.sh"
fi

MEMORY_PORTABILITY_PYTHON='import os
import sys
from config import init_config
from memory_export import create_memory_store
from memory_portability import MemoryTransfer

init_config(sys.argv[1:])
transfer = MemoryTransfer(
    transfer_dir="/memory-transfer",
    store=create_memory_store(),
)
operation = os.environ["MEMORY_PORTABILITY_OPERATION"]
if operation == "recover":
    transfer.recover()
elif operation == "import":
    transfer.import_archive(
        os.environ["MEMORY_IMPORT_FILE"],
        mode=os.environ.get("MEMORY_IMPORT_MODE", "overwrite"),
        include_history=os.environ.get("MEMORY_IMPORT_NO_HISTORY") != "1",
        include_vectors=os.environ.get("MEMORY_IMPORT_NO_VECTOR") != "1",
    )
else:
    raise ValueError(f"Unsupported memory portability operation: {operation!r}")'
export MEMORY_PORTABILITY_PYTHON
export PYTHONPATH="${OMEGA_DIR}:${OMEGA_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

export MEMORY_PORTABILITY_OPERATION=recover
"${agent_su[@]}" -s /bin/sh -c 'exec python3 -c "$MEMORY_PORTABILITY_PYTHON" "$@"' sh "$@" \
  || { echo "Memory import recovery failed. Aborting startup." >&2; exit 1; }

if [[ -n "${MEMORY_IMPORT_FILE:-}" ]]; then
  echo "memory_portability: importing ${MEMORY_IMPORT_FILE}"
  export MEMORY_PORTABILITY_OPERATION=import
  "${agent_su[@]}" -s /bin/sh -c 'exec python3 -c "$MEMORY_PORTABILITY_PYTHON" "$@"' sh "$@" \
    || { echo "Memory import failed. Aborting startup." >&2; exit 1; }
  echo "memory_portability: import complete"
fi
unset MEMORY_PORTABILITY_OPERATION MEMORY_PORTABILITY_PYTHON PYTHONPATH

# Scrub environment: only allowlisted vars survive.
SAFE_VARS="HOME USER PATH HOSTNAME TERM LANG LC_ALL \
  PYTHONDONTWRITEBYTECODE PYTHONUNBUFFERED \
  HF_HOME SENTENCE_TRANSFORMERS_HOME HF_HUB_OFFLINE TRANSFORMERS_OFFLINE \
  CHROMA_DB_PATH EMBEDDING_PROVIDER OMEGA_DIR MEMORY_DIR TEST_SERVER_IP"

env_args=()
for var in $SAFE_VARS; do
  eval val=\${$var:-}
  if [ -n "$val" ]; then
    env_args+=("$var=$val")
  fi
done

# BEGIN TEMPORARY DEBUG: dump agent inputs and full nginx configuration.
printf 'Environment passed to agent:\n'
printf '  %q\n' "${env_args[@]}"
printf 'run.metta arguments:\n'
printf '  %q\n' 'GATEWAY_URL=http://localhost:8080' "$@"
printf 'Sanitized JSON catalog:\n'
cat -- "$catalog_file"

printf 'Full nginx configuration, including included files (includes API tokens):\n'
su www-data -s /bin/sh -c 'nginx -T -c "${NGINX_CONFIG:-/opt/nginx/nginx.conf}"' 2>&1
# END TEMPORARY DEBUG: configuration dumps.

exec env -i "${env_args[@]}" "${agent_su[@]}" -s /bin/sh -c 'exec sh run.sh run.metta GATEWAY_URL=http://localhost:8080 "$@"' sh "$@"
