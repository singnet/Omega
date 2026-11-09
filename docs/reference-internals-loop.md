# Internals — `src/loop.metta`

The heart of Omega. One function, `omega`, tail-recurses forever.

## Entry

```metta
(= (omega) (omega 1))
```

Outer `run.metta` simply calls `(omega)`.

## On turn 1 (`$k == 1`)

Initializes state:

- `(initLoop)` — configures all loop parameters (see [reference-configuration.md](./reference-configuration.md)).
- `(initMemory)` — configures memory parameters and loads the embedding model.
- `(initPlugins)` — loads the plugins listed in `config/plugins.yaml`. Their `loadOmegaPlugin` functions register channels and LLM providers and add plugin tools with `add-skill`.
- `(initChannels)` — opens the active communication channel.
- `(llmProviderStart (provider))` — starts the LLM provider named by `provider`.

Also creates shared state slots:

- `&prevmsg` — last received human message.
- `&lastresults` — previous turn's tool results, for the next prompt.
- `&loops` — countdown until the agent goes idle.

## Every turn

1. **Decrement `&loops`** (turns > 1 only).
2. **Build the prompt** — `getContext` assembles `PROMPT + SKILLS + HISTORY + TIME`, plus information about previous tool calls if any and list of available tools.
3. **Receive** — `(receive)` via the active channel.
4. **Detect new input** — compare against `&prevmsg`. If different and non-empty, reset `&loops` to `maxNewInputLoops`.
5. **Set next wake** — `&nextWakeAt := now + wakeupInterval`.
6. **Call the LLM** — `(llmProviderChat $request)` passes the request with the tool definitions to the provider started on turn 1. Providers are plugins registered with `registerLLMProvider` (see [reference-plugin-api.md](./reference-plugin-api.md#llm-provider-integration)).
7. **Parse** — the reply is converted to an s-expression of tool calls by `providers.llmResponseToSExpr`, then `sread` parses it.
8. **Dispatch tool calls** — `(superpose $resp)` runs each tool call, capturing errors via `HandleError`.
10. **Record** — `addToHistory` appends human message + response + any errors to `memory/history.metta`, provided something new happened.
11. **Save last results** — into `&lastresults` for the next turn's prompt.
12. **Sleep** — `(sleep (sleepInterval))`.
13. **Recurse** — `(omega (+ 1 $k))`.

## Idle behavior

When `&loops` hits zero and no new message has arrived, the loop skips the LLM call. When `now > &nextWakeAt`, it grants `maxWakeLoops + 1` extra turns so the agent can do self-initiated work (cleanup, summarization, etc.).

## Error handling

Two kinds of error are reported back into `&error`:

- **Parse failure** (`MULTI_COMMAND_FAILURE_...`) — `sread` could not parse the converted reply, and no call ran.
- **Tool call failure** (`UNKNOWN_SKILL_CALL` or `SINGLE_COMMAND_ERROR_...`) — `UNKNOWN_SKILL_CALL` marks text at the start of the reply that does not begin with a known tool name, and `SINGLE_COMMAND_ERROR_...` marks a call whose evaluation raised an error. A line with an unknown name after a call is not reported, because it becomes part of that call's argument.

Errors are appended to the episodic trace as `ERROR_FEEDBACK:` and come back as `ALERT_FAILED` in the next prompt's `LAST_SKILL_USE_RESULTS`, so the agent sees them and can self-correct.

## See also

- [introduction.md#architecture](./introduction.md#architecture) — the architecture diagram.
- [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md) — how individual tool calls resolve.
