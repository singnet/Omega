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
OPENAIAPI_URL="http://localhost:8080/" # dummy value
MM_URL="http://localhost:8080/" # dummy value
OPENCLAW_URL="http://localhost:8080/" # dummy value
for arg in "$@"; do
  if [[ "$arg" == embeddingprovider=* ]]; then
    EMBEDDING_PROVIDER="${arg#*=}"
  fi
  if [[ "$arg" == embeddingModel=* ]]; then
    EMBEDDING_MODEL="${arg#*=}"
  fi
  # URL to redirect OpenAIAPI provider requests
  if [[ "$arg" == openaiapi_url=* ]]; then
    OPENAIAPI_URL=$(nginx_url "${arg#*=}")
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
export EMBEDDING_PROVIDER EMBEDDING_MODEL OPENAIAPI_URL MM_URL OPENCLAW_URL

su www-data -s /bin/sh -c "sh /opt/nginx/nginx.sh"

# Optional knowledge-base import
if [[ "${IMPORT_KB_ON_START}" == "1" ]]; then
  su nobody -s /bin/sh -c "${OMEGA_DIR}/scripts/import_knowledge.sh"
fi

MEMORY_PORTABILITY_PYTHON='import os
from config import init_config
from memory_export import create_memory_store
from memory_portability import MemoryTransfer

init_config([])
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
su nobody -s /bin/sh -c 'exec python3 -c "$MEMORY_PORTABILITY_PYTHON"' \
  || { echo "Memory import recovery failed. Aborting startup." >&2; exit 1; }

if [[ -n "${MEMORY_IMPORT_FILE:-}" ]]; then
  echo "memory_portability: importing ${MEMORY_IMPORT_FILE}"
  export MEMORY_PORTABILITY_OPERATION=import
  su nobody -s /bin/sh -c 'exec python3 -c "$MEMORY_PORTABILITY_PYTHON"' \
    || { echo "Memory import failed. Aborting startup." >&2; exit 1; }
  echo "memory_portability: import complete"
fi
unset MEMORY_PORTABILITY_OPERATION MEMORY_PORTABILITY_PYTHON PYTHONPATH

# Scrub environment: only allowlisted vars survive.
SAFE_VARS="HOME USER PATH HOSTNAME TERM LANG LC_ALL \
  PYTHONDONTWRITEBYTECODE PYTHONUNBUFFERED \
  HF_HOME SENTENCE_TRANSFORMERS_HOME HF_HUB_OFFLINE TRANSFORMERS_OFFLINE \
  CHROMA_DB_PATH EMBEDDING_PROVIDER OMEGA_DIR MEMORY_DIR TEST_SERVER_IP"

env_args=""
for var in $SAFE_VARS; do
  eval val=\${$var:-}
  if [ -n "$val" ]; then
    env_args="$env_args $var=$val"
  fi
done

exec env -i $env_args su nobody -s /bin/sh -c "sh run.sh run.metta GATEWAY_URL="http://localhost:8080" $*"
