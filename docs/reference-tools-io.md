# Reference — I/O Tools

Defined in `src/skills.metta`; the `shell` tool is backed by `src/skills.pl`, the write tools by `src/fileio.py`.

---

## `shell`

### Signature
```metta
(shell "command")
```

### Purpose
Execute a shell command and return what it prints to standard output and standard error.

### Parameters
- `command` — the command line. `shell/2` passes it unchanged to `sh -c` and does not check for apostrophes, although the tool's line in the prompt asks the LLM to leave them out.

### Returns
The captured stdout and stderr of the command as one string, or `timeout_error` if the command is still running after 5 seconds. A failing command still returns its output, and the exit status is not reported.

### Examples
```metta
(shell "ls -la /app")
(shell "python3 --version")
```

### Notes / Limits
- Runs with the permissions of the Omega process.
- Executed as `timeout -k 1s 5s sh -c <command>`. A command still running after 5 seconds gets a TERM signal, and a KILL signal one second later.
- File access is limited only by the Landlock policy from `securityPolicyPath` (see `get-io-policy`). There is no other sandbox. Run in a container for anything resembling untrusted use.
- Prefer writing complex commands to a file and invoking the file rather than embedding quotes-within-quotes.

---

## `read-file`

### Signature
```metta
(read-file "path")
```

### Purpose
Read a file into a string.

### Parameters
- `path` — absolute or relative filesystem path. MeTTa library paths of the form `(library Omega ./memory/prompt.txt)` are also accepted (see `getPrompt`).

### Returns
The file's contents as a single string.

### Examples
```metta
(read-file "/tmp/notes.txt")
```

### Notes / Limits
- Fails if the file does not exist (the call checks `exists_file` first).

---

## `write-file`

### Signature
```metta
(write-file "path" "contents")
```

### Purpose
Create or overwrite a file with the given contents.

### Parameters
- `path` — target filesystem path.
- `contents` — the exact bytes to write.

### Returns
A verification string read back from disk after the write:
`WRITE-VERIFIED file=<path> bytes=<size> sha256=<16 hex chars> head='<first 80 bytes>' tail='<last 80 bytes>'`
— or `WRITE-FAILED file=<path>: <error>` on failure (the tool returns, never raises).

### Examples
```metta
(write-file "/tmp/note.txt" "hello world")
```

### Notes / Limits
- Overwrites unconditionally — there is no confirm step.
- Writes the exact bytes given — no implicit trailing newline.
- For files up to 160 bytes the `tail` snippet is empty (`head` plus `sha256` already cover the content); for files over 2 MB the hash is reported as `sha256=skipped(large)`.
- For incremental writes, use `append-file`. For content containing quotes, backslashes
  or newlines, prefer `write-file-b64`.

---

## `write-file-b64`

### Signature
```metta
(write-file-b64 "path" "base64content")
```

### Purpose
Create or overwrite a file with base64-decoded content — byte-exact for content containing
quotes, backslashes or newlines, which the plain-text argument path can mangle.

### Parameters
- `path` — target filesystem path.
- `base64content` — base64 encoding of the exact bytes to write, as a single line
  (whitespace inside the argument is tolerated).

### Returns
The same `WRITE-VERIFIED …` / `WRITE-FAILED …` string as `write-file`.

### Examples
```metta
(write-file-b64 "/tmp/script.sh" "IyEvYmluL2Jhc2gKZWNobyAiYVwiYiIgJ2MnCg==")
```

### Notes / Limits
- Invalid base64 fails without writing anything.
- Binary-safe: the decoded bytes are written verbatim.

---

## `append-file`

### Signature
```metta
(append-file "path" "line")
```

### Purpose
Append a line to an existing file, followed by a newline.

### Parameters
- `path` — target filesystem path. File must exist.
- `line` — string to append.

### Returns
`APPEND-VERIFIED file=<path> bytes=<file size after append> sha256=<16 hex chars> head='…' tail='…'`
read back from disk — or `APPEND-FAILED file=<path>: <error>` (e.g. when the file does not exist).

### Examples
```metta
(append-file "/tmp/session.log" "turn 42 summary: ...")
```

### Notes / Limits
- Fails if the file does not exist (the tool checks existence first). Create it with `write-file` first if needed.
- For files up to 160 bytes the `tail` snippet is empty (`head` plus `sha256` already cover the content); for files over 2 MB the hash is reported as `sha256=skipped(large)`.
- A trailing newline is always added.

---

## `get-io-policy`

### Signature

```metta
(get-io-policy)
```

### Purpose

Return the filesystem paths allowed by Omega's active security policy.

The agent should use this tool before reading, writing, appending, or otherwise
modifying a file when the target path is not known to be allowed.

### Parameters

This tool does not take any parameters. It reads the policy file configured
by the `securityPolicyPath` runtime option.

### Returns

A JSON-formatted string with two fields:

- `read_only` — paths that may be read;
- `read_write` — paths that may be read and modified.

Example:

```json
{
  "read_only": ["/usr", "/opt", "/var/log"],
  "read_write": ["/tmp", "/var/tmp"]
}
```

If no security policy is configured, the tool returns:

```text
Could not retrieve policy: policy is not set
```

If the policy cannot be loaded, it returns:

```text
Could not retrieve a policy: unexpected exception
```

### Examples

```metta
(get-io-policy)
```

A typical workflow before writing a file is:

1. Call `get-io-policy`.
2. Check whether the target path is covered by a `read_write` path.
3. Call `write-file` or `append-file` only if the path is allowed.

### Notes / Limits

- The tool reports configured policy paths; it does not grant permissions.
- Paths in `read_only` must not be used for writing.
- Paths in `read_write` may be read and modified.
- The tool does not check a particular requested path automatically.
- The result contains policy paths, not the contents of the policy file.
- Does not reveal the complete security-policy configuration to the user.
- If a requested path is denied, suggest using `/tmp` when appropriate.
- If `securityPolicyPath` is empty, the tool reports that the policy is not
  set.
