#!/usr/bin/env bash
set -euo pipefail

CHROMA_DB_PATH="${CHROMA_DB_PATH:-/PeTTa/chroma_db}"
IMPORT_KB_FORCE="${IMPORT_KB_FORCE:-0}"

normalize_provider() {
  echo "$1" | tr '[:upper:]' '[:lower:]'
}

mkdir -p "${CHROMA_DB_PATH}"

PROVIDER="$(normalize_provider "${EMBEDDING_PROVIDER}")"

case "${PROVIDER}" in
  openai|asicloud)
    case "${PROVIDER}" in
      openai) API_KEY_VAR="OPENAI_API_KEY" ;;
      asicloud) API_KEY_VAR="ASI_API_KEY" ;;
    esac

    if [[ -z "${!API_KEY_VAR:-}" ]]; then
      echo "ERROR: ${API_KEY_VAR} is required when EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER}." >&2
      exit 1
    fi

    SENTINEL="${CHROMA_DB_PATH}/.import-kb.${PROVIDER}.done"

    if [[ -f "${SENTINEL}" && "${IMPORT_KB_FORCE}" != "1" ]]; then
      echo "[import-kb] Already initialized with ${PROVIDER} embeddings; skipping."
    else
      echo "[import-kb] Running import-knowledge with ${PROVIDER} embeddings."
      echo "[import-kb] CHROMA_DB_PATH=${CHROMA_DB_PATH}"
      if [[ -n "${EMBEDDING_MODEL:-}" ]]; then
        import-knowledge --provider "${PROVIDER}" --model "${EMBEDDING_MODEL}"
      else
        import-knowledge --provider "${PROVIDER}"
      fi
      date -Iseconds > "${SENTINEL}"
      echo "[import-kb] Import complete."
    fi
    ;;

  local)
    SENTINEL="${CHROMA_DB_PATH}/.import-kb.local.done"

    if [[ -f "${SENTINEL}" && "${IMPORT_KB_FORCE}" != "1" ]]; then
      echo "[import-kb] Already initialized with local embeddings; skipping."
    else
      echo "[import-kb] Running import-knowledge with local embeddings."
      echo "[import-kb] CHROMA_DB_PATH=${CHROMA_DB_PATH}"
      import-knowledge --local
      date -Iseconds > "${SENTINEL}"
      echo "[import-kb] Import complete."
    fi
    ;;

  *)
    echo "ERROR: Unsupported embeddingprovider='${EMBEDDING_PROVIDER}'." >&2
    echo "Use embeddingprovider=OpenAI, embeddingprovider=ASICloud or embeddingprovider=Local." >&2
    exit 1
    ;;
esac
