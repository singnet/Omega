# Tutorial 02 — Shell and Files

**Goal:** let Omega inspect and modify its environment using `shell`, `read-file`, `write-file`, and `append-file`.

## Prerequisites

- A running Omega (see [Usage](/README.md#usage)).
- Awareness that these tools run with the permissions of the Omega process.

## The four I/O tools

| Tool | Purpose |
|---|---|
| `(shell "cmd")` | Run a shell command; returns stdout and stderr. |
| `(read-file "path")` | Return the file contents as a string. |
| `(write-file "path" "contents")` | Overwrite the file. |
| `(append-file "path" "line")` | Append a line (with trailing newline) to the file. |

See [reference-tools-io.md](./reference-tools-io.md) for exact signatures.

## 1. Inspect the environment

```
what version of python is available?
```

Expected tool call: `shell` with the parameter `cmd` set to `python3 --version`. In the logs, the second `RESPONSE:` line shows `(<id> (shell "python3 --version"))`, and the `COMMAND_RETURN:` line shows the output after `SUCCESS, RETURN: `.

## 2. Produce a file

```
write a haiku about reasoning under uncertainty to /tmp/haiku.txt
```

Expected tool calls: `write-file` with `filename` set to `/tmp/haiku.txt` and `content` set to the haiku, then on the next turn `read-file` with `filename` set to `/tmp/haiku.txt` to confirm.

## 3. Keep a running log

```
start a log at /tmp/session.log and append a line summarizing every turn
```

The agent should call `append-file` with `filename` set to `/tmp/session.log` and `content` set to the summary line on each subsequent turn. Inspect cat `/tmp/session.log`.

## Safety notes

- Apostrophes in `shell` commands are not checked by the Prolog-side `shell` helper, which passes the command to `sh -c` unchanged. An apostrophe inside a single-quoted shell string ends it. Write such text to a file first and operate on the file.
- **There is no sandbox beyond the Landlock policy.** File access is limited only by the policy from `securityPolicyPath` (see `get-io-policy` in [reference-tools-io.md](./reference-tools-io.md#get-io-policy)). If you expose destructive commands (`rm -rf`, etc.) through the shell you will get what you ask for. Run in Docker and treat the container as ephemeral.
- File paths are resolved relative to the Omega working directory unless absolute.

## Verification

- Log shows a `(shell ...)` call and its captured stdout and stderr.
- Files created by `write-file` / `append-file` exist on disk inside the container.

## Next steps

- [tutorial-03-writing-a-custom-tool.md](./tutorial-03-writing-a-custom-tool.md) — add your own tool.
- [reference-tools-io.md](./reference-tools-io.md) — full details and edge cases.
