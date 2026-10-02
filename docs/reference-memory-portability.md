# Reference - Memory Portability

Memory portability lets an operator export persistent user memory from one
deployment and restore it before another agent starts. It is an operator
workflow, not a tool the LLM calls.

## Setup

Choose an absolute host directory for archives. The launcher creates it when
needed and mounts it at the fixed container path `/memory-transfer`; the agent
never accepts arbitrary runtime export paths.

```sh
scripts/omega start -p OpenAI -t telegram \
  --memory-transfer-dir "$HOME/omega-transfers" \
  --enable-memory-export
```

`--enable-memory-export` is required because export is disabled by default.
The transfer directory must be writable by the container's agent user.

## Export

In the active chat, request one component. The export runs immediately. For IRC,
Telegram, Slack, and Mattermost, the export handler requires the authenticated
user ID persisted by the channel authorization layer. WebSocket export requires
a configured `WS_TOKEN`; the handler derives a non-reversible principal from the
token so the credential itself is never used as an identifier:

```text
/memory-export history
/memory-export ltm
/memory-export both
```

Completion is delivered through the active channel and includes the filename,
record count, size, and SHA-256.

Archives contain selected persistent user memory only:

```text
manifest.json
history/history.metta
vector/collections.json
vector/records.jsonl
```

History is the conversation trace. LTM is logical user-memory records from
ChromaDB. Prompts, credentials, logs, tools, and other operational state are
not exported. SHA-256 detects corruption, not archive authorship.

## Import

Import is an administrative startup operation. The archive argument is a plain
filename in the chosen transfer directory:

```sh
scripts/omega start -d singularitynet/omega:<tag> -p OpenAI -t telegram \
  --memory-transfer-dir "$HOME/omega-transfers" \
  --memory-import omegaclaw-memory-<timestamp>.tar.gz \
  --memory-mode overwrite
```

`overwrite` replaces the selected components after validation and rollback
preparation. `append` preserves existing history and adds imported LTM records
under new IDs. Select a single component with `--only-history` or
`--only-vector`. Without either option, both components are imported.

The importer validates archive paths, checksums, manifest metadata, record
counts, and embedding compatibility before changing live memory. It runs before
the agent loop starts. A receipt prevents a completed archive import from
running again on container restart.

## Security

Archives are private operator data; keep the host transfer directory protected.
Memory export is denied when channel authentication is disabled, no authenticated
channel user has been persisted, or WebSocket has no `WS_TOKEN`.
