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
2. **Build the prompt** — `getContext` assembles `PROMPT + SKILLS + OUTPUT_FORMAT + SAVE_PERMANENT_FILES_DIR + LAST_SKILL_USE_RESULTS + HISTORY + TIME`, with the prompt extensions between `SKILLS` and `OUTPUT_FORMAT`. `SKILLS` is the tool list from `getSkills`, and `OUTPUT_FORMAT` asks for up to 5 lines with one tool call each, without quotes around arguments and without variables.
3. **Receive** — `(receive)` via the active channel.
4. **Detect new input** — compare against `&prevmsg`. If different and non-empty, reset `&loops` to `maxNewInputLoops`.
5. **Set next wake** — `&nextWakeAt := now + wakeupInterval`.
6. **Call the LLM** — `(llmProviderChat $send (maxOutputToken) (reasoningMode))` passes the prompt and the new message to the provider started on turn 1. Providers are plugins registered with `registerLLMProvider` (see [reference-plugin-api.md](./reference-plugin-api.md#llm-provider-integration)).
7. **Convert the reply** — `helper.balance_parentheses` turns the lines with tool calls into one s-expression with a sub-expression per call and quotes the arguments. If the reply does not start with a tool name, the text up to the first call becomes `(Error UNKNOWN_SKILL_CALL ...)`, or a `pin` call when that text starts with `-`.
8. **Parse** — `sread` on the converted string. The loop would feed back a reminder if the string did not start with `(`, but the converted string always does.
9. **Dispatch tool calls** — `(superpose $sexpr)` runs each call, capturing errors via `HandleError`. Calls marked `UNKNOWN_SKILL_CALL` are reported without running. Every other call runs, even when the reply holds more than 5.
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
