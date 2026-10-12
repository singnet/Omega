# Tutorial 03 — Writing a Custom Tool

**Goal:** add a new tool the agent can call, end-to-end.

## Prerequisites

- A local clone of Omega (so you can edit MeTTa source).
- Familiarity with running the agent — see [Usage](/README.md#usage).

## The anatomy of a tool

A tool is three things:

1. **An entry in the tool list** in `src/skills.metta` (the `getStaticSkills` list) so the LLM learns the tool exists. The tool name must also be in `STATIC_LLM_COMMANDS` in `src/helper.py` so the parser accepts calls to it.
2. **A MeTTa definition** of how the tool executes. Pure-MeTTa tools are written directly; tools that need system access delegate to Python or Prolog.
3. **Optional Python/Prolog glue** imported through `py-call` or `translatePredicate`.

A MeTTa plugin can add a tool without editing `src/skills.metta` or `src/helper.py`. It defines the tool in its own `.metta` file and calls `add-skill` from its `loadOmegaPlugin`. `add-skill` adds the tool's line to the prompt and registers the name with the parser (see [reference-plugin-api.md](./reference-plugin-api.md#other-agent-related-apis)). For the `word-count` example below, the call would be `(add-skill word-count "Count space-separated words in a string" (string))`.

## Example: a `word-count` tool

We'll add `word-count`, which returns the number of space-separated words in its argument.

### Step 1 — Declare it in `getStaticSkills`

Open `src/skills.metta` and add this line inside the `getStaticSkills` list, after the `version` line:

```metta
"- Count space-separated words in a string: word-count string"
```

This text goes into the `SKILLS:` section of the prompt, so the LLM knows the tool is callable.

### Step 2 — Register the name with the parser

Open `src/helper.py` and add `"word-count",` to the `STATIC_LLM_COMMANDS` set. Without it the parser does not know `word-count` as a tool name. A `word-count` line at the start of the reply becomes `(Error UNKNOWN_SKILL_CALL "...")`, and a `word-count` line after another call is added to that call's argument. In both cases the loop does not run `word-count`.

### Step 3 — Define the implementation

Back in `src/skills.metta`, add at the end of the file:

```metta
(= (word-count $str)
   (progn (translatePredicate (split_string $str " " "" $parts))
          (translatePredicate (length $parts $count))
          $count))
```

If you prefer Python, register a function in a `.py` module and call `(py-call (mymodule.word_count $str))`.

### Step 4 — Test

Restart the agent with the command you started it with (`sh run.sh run.metta ...` from the PeTTa folder; see [Usage](/README.md#usage)). Ask:

```
how many words are in "the quick brown fox"?
```

The LLM should reply with the line `word-count the quick brown fox`, with or without quotes around the text. The parser turns it into `(word-count "the quick brown fox")`. The result `4` comes back in `LAST_SKILL_USE_RESULTS` on the next turn, and the agent answers with `send`.

## Conventions

- Tool names are lowercase, hyphen-separated.
- The tool gets everything after its name as one string, because the parser adds the quotes. The prompt tells the LLM not to quote arguments and not to use variables. Nothing checks this. A `$x` arrives as plain text, except when the argument is a single line that starts and ends with a double quote and the `$x` stands outside the quoted parts, as in `word-count "a" $x "b"`. The parser keeps such an argument as written.
- A tool that takes a file name and content also needs its name in `TWO_ARG_COMMANDS` in `src/helper.py`. Any other tool gets several arguments only when the LLM puts each one in double quotes.
- Return a value that is safe to render into the `LAST_SKILL_USE_RESULTS` context — the loop runs the result through `helper.normalize_string`.
- If your tool may fail, wrap error-producing subcalls in `catch` or let them fall through to the loop's `HandleError`.

## Verification

- The new tool appears in the prompt (search the `CHARS_SENT:` log lines for `word-count`).
- The LLM invokes it without prompting tweaks.
- The return value shows up in `LAST_SKILL_USE_RESULTS` on the next turn.

## Next steps

- [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md) — how dispatch works.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — other places to hook in.
