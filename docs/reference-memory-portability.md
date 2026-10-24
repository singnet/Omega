# Reference - Memory Portability

Memory portability lets an operator export persistent user memory from one
deployment and restore it before another agent starts. It is an operator
workflow, not an LLM skill.

## Setup

The launcher stores archives in the Docker-managed volume
`omega-memory-transfer`, mounted at the fixed container path `/memory-transfer`.
It is separate from `omega-memory`, which holds the agent's live memory. No
host bind mount, private host group, or host-directory permissions are needed.
The volume directory belongs to the `nobody` agent user (`65534:65534`) with
mode `0700`.

Use Docker with Linux containers on Linux or macOS. On Windows, run the Bash
launcher in WSL2 with Docker Desktop's WSL integration enabled. Host paths in
the commands below are paths visible to that shell, such as `/mnt/c/Users/...`
for Windows files. Native PowerShell and Git Bash are not supported launchers.

```sh
scripts/omega start -p OpenAI -t telegram \
  --enable-memory-export
```

`--enable-memory-export` is required because export is disabled by default.
The agent mounts the archive volume only when export is enabled or
`--memory-import` is requested. Import does not require enabling export.
To use a different archive volume, pass `--memory-transfer-volume <name>` to
startup and each archive command. A volume name is required, not a host path.
The live-memory volume names `omega-memory` and `omegaclaw-memory` are reserved.

Archive commands use a temporary helper container from the selected image;
they work without a running agent and do not require API keys. Docker uses the
local image when available and pulls it automatically if missing. Pass
`-d <image>` to select an image, including a locally built `omega:dev`;
the default is `singularitynet/omega:latest`.

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
record count, size, and SHA-256. Use that exact filename to download the archive
to an existing host directory or a new host file:

```sh
scripts/omega memory-list
archive="omega-memory-<UTC timestamp>-<ID>.tar.gz"  # Replace with the filename from the export reply.
mkdir -p "$HOME/Downloads"
scripts/omega memory-download "$archive" "$HOME/Downloads"
```

Downloads leave the archive in the volume and refuse to overwrite an existing
destination. A failed download removes its partial host file.

Archive names use `omega-memory-<UTC timestamp>-<ID>.tar.gz`, where the ID is
eight hexadecimal characters derived from UUIDv4. Use the returned filename
when importing an archive.

Archives contain selected persistent user memory only:

```text
manifest.json
history/history.metta
vector/collections.json
vector/records.jsonl
```

History is the conversation trace. LTM is logical user-memory records from
ChromaDB. Prompts, credentials, logs, skills, and other operational state are
not exported. SHA-256 detects corruption, not archive authorship.

## Import

Import is an administrative startup operation. Upload a host archive into the
volume first:

```sh
image="singularitynet/omega:<tag>"
archive="omega-memory-<UTC timestamp>-<ID>.tar.gz"  # Replace with your archive's filename.
scripts/omega memory-upload "$HOME/Downloads/$archive" -d "$image"
```

The upload command stores the file with mode `0600` as `nobody`. It rejects
symbolic links and an existing archive filename. Files become available only
after the upload completes. A forced interruption can leave hidden staging
data, but the same archive filename can be retried. Uploading alone does not
change live memory. The archive argument for startup is a plain filename in
the chosen volume:

```sh
scripts/omega start -d "$image" -p OpenAI -t telegram \
  --memory-import "$archive" \
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

Archives are private operator data. Keep downloaded host copies protected and
use the launcher to access the volume. Archive helpers run as `nobody`
and mount only the archive volume. The agent's Landlock policy is preserved.
The root entrypoint continues to initialize Nginx and startup services normally.
Memory export is denied when channel authentication is disabled, no authenticated
channel user has been persisted, or WebSocket has no `WS_TOKEN`.

## Persistence and migration

Archives survive container stops, recreation, and `scripts/omega clean`.
`clean` still removes the agent's live memory volume. To permanently delete one
archive, use its plain filename:

```sh
scripts/omega memory-delete "$archive"
```

This deletes only the named archive from the selected transfer volume. Other
archives and live memory are preserved. Remove the archive volume
explicitly with `docker volume rm omega-memory-transfer` only when you no longer
need its contents and no container is using it.

The old `--memory-transfer-dir` and `--memory-transfer-gid` options are replaced
by `--memory-transfer-volume`. To migrate an existing host archive, upload it:

```sh
scripts/omega memory-upload "$HOME/omega-transfers/$archive"
```

This leaves the original host file intact. For an archive already exported
into the volume, no upload is needed before `--memory-import`.
