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
- `(initChannels)` — opens the active communication channel.

Also creates shared state slots:

- `&prevmsg` — last received human message.
- `&lastresults` — previous turn's skill results, for the next prompt.
- `&loops` — countdown until the agent goes idle.

## Every turn

1. **Decrement `&loops`** (turns > 1 only).
2. **Build the prompt** — `getContext` assembles `PROMPT + SKILLS + TIME` and context from the selected provider, plus information about previous tool calls if any and list of available tools.
3. **Receive** — `(receive)` via the active channel.
4. **Detect new input** — compare against `&prevmsg`. If different and non-empty, reset `&loops` to `maxNewInputLoops`.
5. **Set next wake** — `&nextWakeAt := now + wakeupInterval`.
6. **Call the LLM** — dispatches on `provider`:
   - `OpenAI` → `useGPT`
   - `Anthropic` → `lib_llm_ext.useClaude`
   - `ASICloud` → `lib_llm_ext.useMiniMax`
   - else → `lib_llm_ext.useAsi1`
8. **Parse** — `sread` on the repaired string; if it does not start with `(`, the loop feeds back a reminder prompt.
9. **Dispatch skills** — `(superpose $sexpr)` runs each skill, capturing errors via `HandleError`.
10. **Record** — `addToHistory` appends human message + response + any errors to `memory/history.metta`, provided something new happened.
11. **Save last results** — into `&lastresults` for the next turn's prompt.
12. **Sleep** — `(sleep (sleepInterval))`.
13. **Recurse** — `(omega (+ 1 $k))`.

The default context provider supplies conversation history; the enabled context
plugin supplies the current frame projection. Before each LLM call, the provider
supplies a token that is passed back with the completed tool batch. The core
does not read frame state. See the
[context provider API](./reference-plugin-api.md#context-providers).

## Idle behavior

When `&loops` hits zero and no new message has arrived, the loop skips the LLM call. When `now > &nextWakeAt`, it grants `maxWakeLoops + 1` extra turns so the agent can do self-initiated work (cleanup, summarization, etc.).

When no wake-up is due, the loop calls `(context-event Idle)` for
context-specific idle maintenance.

## Error handling

Two kinds of error are reported back into `&error`:

- **Parse failure** (`MULTI_COMMAND_FAILURE_...`) — the LLM did not produce a valid s-expression.
- **Per-skill failure** (`SINGLE_COMMAND_FORMAT_ERROR_...`) — one skill call failed.

Errors are appended to the episodic trace so the agent sees them and can self-correct.

## See also

- [introduction.md#architecture](./introduction.md#architecture) — the architecture diagram.
- [reference-internals-skill-dispatch.md](./reference-internals-skill-dispatch.md) — how individual skills resolve.
