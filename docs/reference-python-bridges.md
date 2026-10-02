# Reference — Python and Prolog Bridges

MeTTa handles reasoning and control flow; bridges handle everything that needs a library ecosystem.

## `src/logger.py`

Centralized logging setup. Called once at startup from `loop.metta`; all Python modules obtain a logger through `get_logger` rather than calling `logging.getLogger` directly.

| Function | Purpose |
|---|---|
| `setup_logging()` | Configures the root logger using the configuration script passed as a parameter. Idempotent — safe to import from multiple modules. Falls back to stdout-only if the configuration script is not found. |
| `get_logger(name)` | Returns `logging.getLogger(name)`. Use this instead of calling `logging.getLogger` directly so the relationship to the shared setup is explicit. |
| `log_debug(msg, module)` | MeTTa bridge — write a DEBUG entry under logger `module`. |
| `log_info(msg, module)` | MeTTa bridge — write an INFO entry under logger `module`. |
| `log_warning(msg, module)` | MeTTa bridge — write a WARNING entry under logger `module`. |
| `log_error(msg, module)` | MeTTa bridge — write an ERROR entry under logger `module`. |

The MeTTa bridge functions are invoked by calling `log` helper function defined in `src/log.metta`, passing the source filename as `module` so log lines are attributed correctly:

```metta
(log INFO "memory" "Initializing memory")
```

**Logging configuration** 

By default, logging is configured from:

```text
config/logging.conf
```

The default configuration writes logs to stderr using the format:

```text
YYYY-MM-DD HH:MM:SS | LEVEL    | module | message
```

Docker container stdout/stderr is captured automatically and can be viewed with:

```bash
docker logs -f omega
```

**Custom logging configuration**

Users can provide their own Python logging config file to control log levels, handlers, formatters, output destinations, and per-module logging behavior.

When starting Omega through the launcher script, pass:

```bash
scripts/omega start -l /path/to/logging.conf
```

For standalone runs without Docker, pass the config path to the MeTTa runtime:

```bash
sh run.sh run.metta logConfigPath=/path/to/logging.conf
```

If no custom config is provided, Omega uses `config/logging.conf`. If the configured file is missing, Omega falls back to basic stderr logging.

## `providers/lib_llm_ext.py`

Embedding bridges and the LLM clients that the provider plugins delegate to.

| Function | Purpose |
|---|---|
| `useLocalEmbedding(str)` | Compute an embedding with a locally loaded model. Used when `embeddingprovider = Local`. |
| `initLocalEmbedding()` | Load the local embedding model once at startup. |

The module also defines `AIProvider`, an OpenAI-compatible client, and its base class `AbstractAIProvider`. The provider plugins in `providers/` derive from `providers.LLMProvider` and delegate their chat calls to objects of these classes. The loop does not call this module for the LLM. It calls `llmProviderChat` (`src/providers.metta`), which goes to the provider plugin selected by `provider` (see [reference-plugin-api.md](./reference-plugin-api.md#llm-provider-integration)).

## `src/helper.py`

String and time utilities used by the loop, including the parser for tool calls.

| Function | Purpose |
|---|---|
| `balance_parentheses(str)` | Turn the LLM reply into one s-expression with a sub-expression per tool call and quote the arguments. Text up to the first call becomes an `UNKNOWN_SKILL_CALL` error, or a `pin` call when it starts with `-`. A line with an unknown name after a call stays in that call's argument. Despite the name, it does not balance parentheses (see [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md)). |
| `add_llm_command(name)` | Add a tool name to the names the parser accepts. Called by `add-skill`. |
| `remove_llm_command(name)` | Remove a name added by `add_llm_command`. Built-in names stay. Called by `remove-skill`. |
| `normalize_string(obj)` | Render a tool result into a string safe to embed in the next prompt. |
| `around_time(ts, n)` | Backs `(episodes ts)`. Finds the line of `memory/history.metta` whose timestamp is closest to `ts` and returns it with up to `n` lines before and after it, at most `2n+1` lines, each prefixed with its line number. |

The parser takes the built-in tool names from `STATIC_LLM_COMMANDS`. `TWO_ARG_COMMANDS` lists the tools that take a file name and content.

## `src/skills.pl`

Prolog helpers imported via `import_prolog_functions_from_file`.

| Predicate | Purpose |
|---|---|
| `shell/2` | Run a shell command as `timeout -k 1s 5s sh -c <command>`, passing the command unchanged, and capture stdout and stderr together. Returns `timeout_error` if the command is still running after 5 seconds. |
| `first_char/2` | Return the first character of a string — used by the loop to check that the converted reply starts with `(`. |

## `src/websearch.py`

A python helper for using ddgs to expose websearch to the agent.

| Function | Purpose |
|---|---|
| `search_(query, max_results=10)` | Performs a DuckDuckGo text search using `DDGS` and returns a list of result dictionaries containing `title`, `url`, and `snippet`.                                             |
| `search(query, max_results=10)`  | Wraps `search_` and formats the search results into a MeTTa-like parenthesized string containing each result’s title and snippet. Returns an empty string if the search fails. |

## Calling conventions

- MeTTa to Python: `(py-call (module.function arg1 arg2 ...))`.
- MeTTa to Prolog: `(translatePredicate (predicate ...))` for side-effecting predicates, or `!(import_prolog_function name)` to lift a Prolog function into MeTTa.

## See also

- [reference-internals-loop.md](./reference-internals-loop.md) — where these bridges are invoked.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — where to add new bridges.
