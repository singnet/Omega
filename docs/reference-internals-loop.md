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
- `(initContext)` — provided by [`src/context_provider.metta`](../src/context_provider.metta)
  and called by `initLoop`, selects the default message/history provider before
  plugins load. An enabled context plugin can replace it at startup.
- `(initMemory)` — configures memory parameters and loads the embedding model.
- `(initPlugins)` — loads the plugins listed in `config/plugins.yaml`. Their `loadOmegaPlugin` functions register channels and LLM providers and add plugin tools with `add-skill`.
- `(initChannels)` — opens the active communication channel.
- `(llmProviderStart (provider))` — starts the LLM provider named by `provider`.

Also creates shared state slots:

- `&prevmsg` — last received human message.
- `&messages_all` — the list of messages for the next LLM request. `messagesClear` empties it, `messagesAppend` adds a message, and `messagesGet` returns it.
- `&error` — errors of the current turn, reset after each LLM reply.
- `&loops` — countdown until the agent goes idle.
- `&nextWakeAt` — time of the next wake-up while the agent is idle.

## Every turn

1. **Decrement `&loops`** (turns > 1 only).
2. **Receive** — `(receive)` via the active channel.
3. **Admit input** — detect new input, pass it to `(context-event (Input $msg $msgnew))`, and reset `&loops` to `maxNewInputLoops` on later turns with new input.
4. **Build the system message** — `getContext` assembles `PROMPT + selected context + SKILLS + prompt extensions + SAVE_PERMANENT_FILES_DIR + LAST_SKILL_USE_RESULTS + TIME`. The `SKILLS:` part holds only the extra rules from `getSkillRules`; tool schemas are supplied separately.
5. **Set next wake** — `&nextWakeAt := now + wakeupInterval`.
6. **Add the input signal** — the selected context provider's input signal goes into `&messages_all` with role `user`. The default provider supplies the human message or an autonomous-work instruction; frame mode supplies a signal after admitting the message into frame state.
7. **Call the LLM** — `llmRequest` combines the system message, `&messages_all`, and the tool schemas from `collectTools`. `(llmProviderChat $request)` sends it to the provider started on turn 1 and checks the response. Providers are plugins registered with `registerLLMProvider` (see [reference-plugin-api.md](./reference-plugin-api.md#llm-provider-integration)).
8. **Convert** — `providers.llmResponseToSExpr` turns the calls of the response into an s-expression, and `sread` parses it. `&error` and `&messages_all` are reset at this point.
9. **Dispatch tool calls** — one `assistant` message with the calls is added to `&messages_all`. Then `(superpose $resp)` runs each tool call, capturing errors via `HandleError`.
10. **Return results** — every call adds a message with role `tool`, the call id, and the result, cut to the last `maxFeedback` characters. The messages stay in `&messages_all` for the next request.
11. **Record** — `addToHistory` appends human message + tool calls + any errors to `memory/history.metta`, provided something new happened.
12. **Sleep** — `(sleep (sleepInterval))`.
13. **Recurse** — `(omega (+ 1 $k))`.

The default context provider supplies conversation history; the enabled context
plugin supplies the current frame projection. Before each LLM call, the provider
supplies a token that is passed back with the completed tool batch. The core
does not read frame state. See the
[context provider API](./reference-plugin-api.md#context-providers).

See [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md) for the schema, the response checks, and the dispatch steps.

## Idle behavior

When `&loops` hits zero and no new message has arrived, the loop skips the LLM call. When `now > &nextWakeAt`, it grants `maxWakeLoops + 1` extra turns so the agent can do self-initiated work (cleanup, summarization, etc.).

When no wake-up is due, the loop calls `(context-event Idle)` for
context-specific idle maintenance.

## Error handling

Errors are reported back into `&error` at two levels:

- **Response failure** — the provider returned an error, the response has no tool calls (`List of tool calls is empty`), or the converted reply could not be parsed. No call runs, and no `assistant` or `tool` messages are added. An exception that leaves the provider `chat` is different: the reply is empty and has no error, so `&error` stays empty and the turn runs no calls.
- **Tool call failure** — a call to an unknown tool (`Unknown tool`), a call with a missing or non-string parameter, or a call whose evaluation raised an error. The other calls of the reply still run.

For a failed call, `HandleError` binds the string `ALERT_FAILED` followed by the written `(Error ...)` expression to its second argument, and the loop uses that string as the result. This result goes to the model in the `tool` message of that call. Errors are also appended to the episodic trace as `ERROR_FEEDBACK:`, so the agent sees them and can self-correct.

## See also

- [introduction.md#architecture](./introduction.md#architecture) — the architecture diagram.
- [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md) — how individual tool calls resolve.
