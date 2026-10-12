# Internals — Tool Dispatch

This page traces what happens between an LLM response landing in the loop and a tool actually running.

## Expected LLM output shape

The `OUTPUT_FORMAT` section of the prompt asks for "Up to 5 lines, do not wrap quotes around args, do not use variables" and shows this template:

```
toolName1 arg1
toolName2 arg2
toolName3 arg3
toolName4 arg4
toolName5 arg5
```

Each tool call starts on a new line with the tool name, followed by its arguments. The limit of 5 exists only in the prompt. Nothing counts the calls, and the loop runs every call in a longer reply.

Despite its name, `helper.balance_parentheses` does not balance parentheses. It turns the reply into one s-expression with a sub-expression per call:

- A call starts at a line whose first word, after an optional `(`, is a known tool name (`LLM_COMMANDS`). The lines that follow, up to the next such line, belong to the same call, so an argument can span several lines.
- Parentheses around a call are optional, so `send Hello` and `(send "Hello")` give the same call.
- If the reply does not start with a tool name, the text up to the first call becomes `(Error UNKNOWN_SKILL_CALL "<text>")` and does not run. Commentary after a call stays in that call's argument.
- `write-file`, `append-file`, and `write-file-b64` (`TWO_ARG_COMMANDS`) get two arguments: the file name (the first word, or a quoted name) and the text after it as content.
- Every other tool gets everything after its name as one string, quoted by the helper. If that text starts and ends with `"` and has no line break, the helper keeps it unchanged, which lets a tool receive several arguments, for example `research-start "q1" "topic x"`.
- If the reply starts with `-` or `(-`, the text up to the first call becomes a `pin` call instead of an `UNKNOWN_SKILL_CALL` error. A `-` line after a call stays in that call's argument.

For example, the reply

```
send Checking the disk
shell df -h /tmp
```

becomes `((send "Checking the disk") (shell "df -h /tmp"))`.

## Step-by-step dispatch

From `src/loop.metta`:

1. **Raw LLM string** → `$respi`, the reply returned by `llmProviderChat`.
2. **Conversion** — `helper.balance_parentheses $respi` → `$resp`, as described above.
3. **First-character check** — if `$resp` does not start with `(`, the loop logs it and parses the reminder `(REMEMBER:OUTPUT_NOTHING_ELSE_THAN: ((skill arg) ...))` instead. The conversion always returns a string that starts with `(`, so this branch does not fire.
4. **Parse** — `catch (sread $response)` → `$sexpr`. On parse failure, `HandleError` records `MULTI_COMMAND_FAILURE_...` and no call runs.
5. **Fan out** — `(superpose $sexpr)` produces one binding per tool call in `$sexpr`. A call that the conversion turned into `(Error UNKNOWN_SKILL_CALL ...)` is recorded by `HandleError` and not evaluated.
6. **Evaluate each** — `(catch (eval $s))`. On success, the result is normalized via `helper.normalize_string`. On failure, `HandleError` records `SINGLE_COMMAND_ERROR_...`.
7. **Aggregate** — all results are collapsed into `RESULTS: ((COMMAND_RETURN: (cmd result)) ...)`.
8. **Feedback** — stored as `&lastresults`, fed back into the next prompt as `LAST_SKILL_USE_RESULTS`, cut to its last `maxFeedback` characters.

## How `eval $s` resolves to a tool

MeTTa evaluates the head of the expression against the AtomSpace. Most tools are defined as plain equations, and their arguments arrive as strings:

```metta
(= (remember $str)   ...)
(= (read-file $file) ...)
(= (metta $str)      ...)
```

So `(read-file "/tmp/notes.txt")` matches the equation for `read-file` and runs its body. `metta` parses its string with `sread` before it evaluates it. `shell` has no MeTTa equation. Instead, `src/skills.metta` imports the Prolog predicate `shell/2` from `src/skills.pl` as a function with `import_prolog_functions_from_file`.

Bridges enter via:

- `(py-call (module.function args))` for Python.
- `(translatePredicate (predicate ...))` and `!(import_prolog_function name)` for Prolog.

## Errors propagate via `&error`

`HandleError` appends to the `&error` state and returns `(ALERT_FAILED ...)` in place of the result, so the error also reaches `LAST_SKILL_USE_RESULTS` in the next prompt. When `addToHistory` runs, if `&error` is non-empty it is concatenated as `ERROR_FEEDBACK:`. On the next turn the agent sees the error and has the opportunity to correct course.

## See also

- [reference-internals-loop.md](./reference-internals-loop.md) — the full turn structure.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — where to hook in new tools.
- [tutorial-03-writing-a-custom-tool.md](./tutorial-03-writing-a-custom-tool.md) — end-to-end tool addition.
