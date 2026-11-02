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
2. **Receive** — `(receive)` via the active channel.
3. **Detect new input** — compare against `&prevmsg`. If different and non-empty, reset `&loops` to `maxNewInputLoops`.
4. **Prepare context** — the selected context provider processes input and supplies working context to `getContext`. The default uses conversation history; the optional frame provider uses the current frame projection.
5. **Set next wake** — `&nextWakeAt := now + wakeupInterval`.
6. **Call the LLM** — `llmProviderChat` sends the request to the registered provider selected at startup.
7. **Parse** — `providers.llmResponseToSExpr` converts the structured response to an s-expression string; `catch (sread $respstr)` parses it.
8. **Dispatch skills** — `(superpose $resp)` yields each tool call for evaluation, with errors captured via `HandleError`.
9. **Record** — `addToHistory` appends human message + response + any errors to `memory/history.metta`, provided something new happened.
10. **Save last results** — into `&lastresults` for the next turn's prompt.
11. **Sleep** — `(sleep (sleepInterval))`.
12. **Recurse** — `(omega (+ 1 $k))`.

The context provider processes input before the prompt is built. Before each
LLM call, it supplies a token that is passed back with the completed tool batch.
The core does not read frame state. See the
[context provider API](./reference-plugin-api.md#context-providers).

## Idle behavior

When `&loops` hits zero and no new message has arrived, the loop skips the LLM call. When `now > &nextWakeAt`, it grants `maxWakeLoops + 1` extra turns so the agent can do self-initiated work (cleanup, summarization, etc.).

When no wake-up is due, the loop calls `(context-event Idle)` for
context-specific idle maintenance.

## Error handling

`HandleError` records `(Error command message)` results in `&error`:

- **Response or parse failure** — response validation reports an error, or parsing the response s-expression fails.
- **Per-skill failure** — a tool call fails validation or an error is caught while evaluating a skill.

Errors are appended to the episodic trace so the agent sees them and can self-correct.

## See also

- [introduction.md#architecture](./introduction.md#architecture) — the architecture diagram.
- [reference-internals-skill-dispatch.md](./reference-internals-skill-dispatch.md) — how individual skills resolve.
