# Internals — Tool Dispatch

This page traces what happens between an LLM response landing in the loop and a tool actually running.

## Tool schema

Each turn the loop sends the model the list of tools as structured data. `collectTools` calls `providers.getTools` with the result of `getSkills`, the list of `(name description arguments)` triples that `add-skill` registered. Every triple becomes one schema:

- the tool name and its description;
- one parameter per argument name, each of type `string` and all required;
- no other properties (`additionalProperties: false`);
- `strict: true`.

The request also sets `tool_choice: required`, so the model has to call at least one tool. The Chat Completions providers build this in `AIProvider.convert_tool` and `convert_request` (`providers/lib_llm_ext.py`). The OpenAI provider sends the same fields in the flat Responses API form (`providers/omega_openai.py`).

The model answers with tool calls, each holding an id, a tool name, and a value for every parameter. The text the model writes next to the calls is not read. The prompt does not limit the number of calls per turn, and the loop runs every call in the reply.

## Response checks

`llmProviderChat` passes the provider's `LLMResponse` through `_validate_response` (`src/providers.py`):

- A response with no calls and no error becomes the error `List of tool calls is empty`. The one exception is a reply cut off by the output limit, which the provider turns into a `send` call with a fixed message.
- A call to a name that is not in the request gets the error `Unknown tool: '<name>'`.
- A call without a parameter from the schema gets `Call tool parameter is not set: ...`.
- A parameter whose value is not a string gets `Call tool parameter is not a string: ...`.

`llmResponseToSExpr` turns the checked response into text. A response error becomes `(Error () "<text>")`. Otherwise the text is a list of `(<id> (<name> "arg1" "arg2" ...))` pairs with the arguments in schema order. Only `"` and `\` are escaped in the strings, so `$x` and parentheses in an argument are plain text. Arguments that are not in the schema are dropped. A call with an error becomes `(<id> (Error (<name> ...) "<text>"))`.

For example, the calls `send` with `content` set to `Checking the disk` and `shell` with `cmd` set to `df -h /tmp` become `((id1 (send "Checking the disk")) (id2 (shell "df -h /tmp")))`.

## Step-by-step dispatch

From `src/loop.metta`:

1. **Request** — `llmRequest` combines the system message, the messages in `&messages_all`, and `(collectTools)`. `llmProviderChat` sends it and checks the response.
2. **Convert** — `providers.llmResponseToSExpr` gives `$respstr`, and `catch (sread $respstr)` gives `$resp`. If `$resp` is an `(Error ...)`, `HandleError` records the error, and no `assistant` or `tool` messages are added.
3. **Assistant message** — one message with role `assistant` carries the calls of the response (`llmResponseCalls`) and the text `[TOOL CALL]`.
4. **Fan out** — `(superpose $resp)` produces one binding of `($callid $s)` per call.
5. **Evaluate each** — an `$s` that is an `(Error ...)` goes to `HandleError`. Any other `$s` runs as `(catch (let $R (collapse (eval $s)) ...))`, and the value is normalized with `helper.normalize_string`. An error from `eval` goes to `HandleError`. A normal result gets the prefix `SUCCESS, RETURN: `.
6. **Feedback** — `(llmToolCallResponseMessage role "tool" callid $callid content (last_chars $result (maxFeedback)))` adds the result to the request for every call, so each call id gets an answer.
7. **History** — the list of calls without ids and without results is stored with `addToHistory`.

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

For an `(Error ...)` value, `HandleError` appends the message and the command to the `&error` state, binds the string `ALERT_FAILED` followed by the written `(Error ...)` expression to its second argument, and returns `True`. The loop uses that string in place of the result, so it reaches the model in the `tool` message for that call. When `addToHistory` runs, if `&error` is non-empty it is concatenated as `ERROR_FEEDBACK:`. On the next turn the agent sees the error and has the opportunity to correct course.

## See also

- [reference-internals-loop.md](./reference-internals-loop.md) — the full turn structure.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — where to hook in new tools.
- [tutorial-03-writing-a-custom-tool.md](./tutorial-03-writing-a-custom-tool.md) — end-to-end tool addition.
