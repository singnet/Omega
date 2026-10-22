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

## `lib_llm_ext.py`

LLM and embedding bridges.

| Function | Purpose |
|---|---|
| `useClaude(prompt)` | Call an Anthropic Claude model. Used when `provider = Anthropic`. |
| `useMiniMax(prompt)` | Call MiniMax. Used when `provider = ASICloud` (or similar routing). |
| `useAsi1(prompt)` | Call ASI1. Used when `provider = ASIOne`. |
| `useLocalEmbedding(str)` | Compute an embedding with a locally loaded model. Used when `embeddingprovider = Local`. |
| `initLocalEmbedding()` | Load the local embedding model once at startup. |

OpenAI calls go through MeTTa-side helpers (`useGPT`, `useGPTEmbedding`) that are defined elsewhere in the library but use the same LLM call pattern.

## `src/helper.py`

String and time utilities used by the loop.

| Function | Purpose |
|---|---|
| `normalize_string(obj)` | Render a skill return value into a string safe to embed in the next prompt. |
| `around_time(ts, n)` | Backs `(episodes ts)` — returns `n` lines of `memory/history.metta` around `ts`. |

## `src/skills.pl`

Prolog helpers imported via `import_prolog_functions_from_file`.

| Predicate | Purpose |
|---|---|
| `shell/2` | Run a shell command and capture stdout. Rejects apostrophes. |
| `first_char/2` | Return the first character of a string — used by the loop to detect whether the LLM produced a valid s-expression. |

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
