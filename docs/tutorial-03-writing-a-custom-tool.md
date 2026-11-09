# Tutorial 03 — Writing a Custom Tool

**Goal:** add a new tool the agent can call, end-to-end.

## Prerequisites

- A local clone of Omega (so you can edit MeTTa source).
- Familiarity with running the agent — see [Usage](/README.md#usage).

## The anatomy of a tool

A tool is three things:

1. **A registration** that tells the LLM the tool exists: a line `!(add-skill <name> "<description>" (<argument> ...))`. The description goes into the `description` field of the tool schema sent with every request, and each element of the argument tuple becomes a string parameter of that schema. The name must match the MeTTa function that runs the tool. A tool without arguments takes `()`. Built-in tools are registered in `src/skills.metta` by the `!(add-skill ...)` lines under `Embedded skills`.
2. **A MeTTa definition** of how the tool executes. Pure-MeTTa tools are written directly; tools that need system access delegate to Python or Prolog.
3. **Optional Python/Prolog glue** imported through `py-call` or `translatePredicate`.

No other file needs an edit. The loop collects the registered tools before each request, so a new tool is visible to the LLM from the next iteration, and a call to a name that is not registered is rejected with `Unknown tool`.

A MeTTa plugin registers a tool the same way from its `loadOmegaPlugin`, without editing `src/skills.metta` (see [reference-plugin-api.md](./reference-plugin-api.md#other-agent-related-apis)). The [OpenClaw plugin](/plugins/openclaw/openclaw.metta) calls `add-skill` for `delegate-task-to-openclaw-agent` and defines the function in the same file, and the [workflow plugin](/plugins/workflow/workflow.metta) registers `workflow-load-instructions`, `workflow-unload-instructions` and `workflow-refresh-list` the same way.

## Example: a `word-count` tool

We'll add `word-count`, which returns the number of space-separated words in its argument.

### Step 1 — Register it with `add-skill`

Open `src/skills.metta` and add this line after the last `!(add-skill ...)` line (the `metta` tool), before the `; TODO` comment:

```metta
!(add-skill word-count "Count space-separated words in a string." (text))
```

The description becomes the `description` of the tool in the request. The tuple `(text)` gives the tool one string parameter named `text`, so the LLM passes the words to count as `text`.

### Step 2 — Define the implementation

Right below that line, add:

```metta
(= (word-count $text)
   (progn (translatePredicate (split_string $text " " "" $parts))
          (translatePredicate (length $parts $count))
          $count))
```

If you prefer Python, register a function in a `.py` module and call `(py-call (mymodule.word_count $text))`.

### Step 3 — Or add it from a plugin

The same tool as a plugin needs a MeTTa file `plugins/wordcount/wordcount.metta`:

```metta
(= (loadOmegaPlugin)
   (add-skill word-count "Count space-separated words in a string." (text)))

(= (word-count $text)
   (progn (translatePredicate (split_string $text " " "" $parts))
          (translatePredicate (length $parts $count))
          $count))
```

and an entry in [config/plugins.yaml](/config/plugins.yaml):

```yaml
- name: wordcount
  loader: metta
  location: "{REPO}/plugins/wordcount"
```

Use one of the two ways, not both: a second `add-skill` with the same name replaces the first.

### Step 4 — Test

Restart the agent with the command you started it with (`sh run.sh run.metta ...` from the PeTTa folder; see [Usage](/README.md#usage)). Ask:

```
how many words are in "the quick brown fox"?
```

The LLM calls the tool `word-count` with the parameter `text` set to `the quick brown fox`. The loop evaluates `(word-count "the quick brown fox")` and returns the result, 4, to the LLM in a message with the role `tool`. The agent then answers with `send`.

## Conventions

- Tool names consist of letters, digits, hyphens and underscores, up to 64 characters, as the LLM APIs expect. The built-in names are lowercase and hyphen-separated, such as `read-file`.
- Every element of the argument tuple is a separate string parameter, and the LLM must fill all of them. The element name is the parameter name in the schema, so choose a name that tells the LLM what to pass, such as `research_name` or `filename`.
- Arguments arrive as plain strings. A `$x`, brackets or quotes inside an argument are text, not MeTTa syntax.
- The loop runs the result through `helper.normalize_string`, puts `SUCCESS, RETURN: ` in front of it and cuts it to the last `maxFeedback` characters before sending it to the LLM, so return a value that is safe to render as text.
- If your tool may fail, wrap error-producing subcalls in `catch` or let them fall through to the loop's `HandleError`.

## Verification

Check the agent log. For `word-count`:

- The `REQUEST:` line of the iteration lists the tool: `LLMTool[name='word-count', description='Count space-separated words in a string.', parameters=[LLMToolParameter[name='text']]]`.
- The first `RESPONSE:` line after it holds the LLM's call: `LLMToolCall[id='...',name='word-count',arguments={'text': 'the quick brown fox'},error=None]`. The next `RESPONSE:` line shows the same call as the s-expression the loop evaluates: `(<id> (word-count "the quick brown fox"))`.
- A `COMMAND_RETURN:` line follows with the call and its result: `COMMAND_RETURN: ((word-count "the quick brown fox") "SUCCESS, RETURN: ...")`, where the result is 4.
- The next `REQUEST:` line contains the call result as a message with the role `tool`: `LLMToolCallResponseMessage[role='tool',content='SUCCESS, RETURN: ...',callid='<id>']`.

## Next steps

- [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md) — how dispatch works.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — other places to hook in.
