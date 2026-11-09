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

String, time, path, and version utilities used by the loop and the tools.

| Function | Purpose |
|---|---|
| `extract_timestamp(line)` | Parse the timestamp in a `memory/history.metta` line, or return `None`. |
| `around_time(ts, n)` | Backs `(episodes ts)`. Finds the line of `memory/history.metta` whose timestamp is closest to `ts` and returns it with up to `n` lines before and after it, at most `2n+1` lines, each prefixed with its line number. |
| `normalize_string(obj)` | Render a tool result into a string. Bytes are decoded as UTF-8, and characters that are not valid UTF-8 are dropped. |
| `joinPath(parts)` | Join path parts with `os.path.join`. |
| `projectRootDirectory()` | Return the repository root. |
| `omega_version(repo_root)` | Return the Omega version string. |

## `src/providers.py`

Request and response types for the LLM, the provider registry, and the conversion between MeTTa and tool calls. The MeTTa side calls it through `src/providers.metta` and `src/loop.metta`.

| Name | Purpose |
|---|---|
| `LLMTool`, `LLMToolParameter` | A tool schema: name, description, and parameters that have only a name. |
| `LLMToolCall`, `LLMResponse` | One call from the model (id, name, arguments, error) and a response (calls, error). |
| `LLMMessage`, `LLMToolCallMessage`, `LLMToolCallResponseMessage` | Messages of a request with roles `user`, `assistant`, and `tool`. |
| `LLMRequest`, `LLMProvider` | A request (messages, tools, token limit, reasoning mode) and the base class of provider plugins. |
| `registerLLMProvider(id, provider)` | Register a provider under the name used by `provider`. |
| `llmProviderStart(provider)` | Start the selected provider. |
| `llmProviderChat(request)` | Send a request to the selected provider and check the response with `_validate_response`. Returns an empty `LLMResponse` if the provider raises an exception. |
| `getTools(skills)` | Turn the `(name description arguments)` triples from `getSkills` into `LLMTool` objects. |
| `llmRequestMessage`, `llmToolCallMessage`, `llmToolCallResponseMessage` | Build a message of the types above. |
| `llmRequest(prompt, episodes, max_tokens, reasoning_mode, tools)` | Build a request from the system message, the other messages, and the tools. |
| `llmResponseCalls`, `llmResponseIsEmpty`, `llmResponseIsError`, `llmResponseGetError` | Read a response. |
| `llmToolCallGetName`, `llmToolCallGetId`, `llmToolCallGetArguments`, `llmToolCallIsError`, `llmToolCallGetError` | Read a tool call. |
| `llmToolCallToSExpr(call)` | Write one call as `(<id> (<name> "arg" ...))`, or as an `Error` form if the call has an error. |
| `llmResponseToSExpr(response)` | Write a response as a list of such pairs, or as `(Error () "<text>")` if the response has an error. |

## `src/utils.py`

List helpers for the message list of the loop: `listNew`, `listAppend`, and `listSlice`.

## `src/skills.pl`

Prolog helpers imported via `import_prolog_functions_from_file`.

| Predicate | Purpose |
|---|---|
| `shell/2` | Run a shell command as `timeout -k 1s 5s sh -c <command>`, passing the command unchanged, and capture stdout and stderr together. Returns `timeout_error` if the command is still running after 5 seconds. |
| `first_char/2` | Return the first character of a string. `src/skills.metta` imports it, and no code calls it. |

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
