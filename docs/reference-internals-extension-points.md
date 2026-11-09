# Internals — Extension Points

Where to plug in new behavior, in order of increasing depth.

## Add a tool

Most common extension. A built-in tool takes two edits in `src/skills.metta`:

1. A registration line `!(add-skill my-tool "<description>" (<argument> ...))` next to the existing `!(add-skill ...)` lines. The description goes into the tool schema sent to the LLM, and each element of the argument tuple becomes a string parameter of that schema.
2. A `(= (my-tool $arg) ...)` definition, either pure MeTTa or a `py-call` / `translatePredicate`.

A MeTTa plugin does the same from its `loadOmegaPlugin`: it calls `add-skill` and defines the function in its own file (see [reference-plugin-api.md](./reference-plugin-api.md#other-agent-related-apis)). `remove-skill` unregisters a tool, built-in ones included.

Full walkthrough: [tutorial-03-writing-a-custom-tool.md](./tutorial-03-writing-a-custom-tool.md).

## Add a channel

Three touch points:

1. New Python module `channels/myadapter.py` implementing `start_*`, `getLastMessage`, `send_message`.
2. A new branch in `initChannels`, `(receive)`, and `(send $msg)` in `src/channels.metta`.
3. New parameters declared via `(= (MY_*) (empty))` and bound by `configure`.

Full walkthrough: [tutorial-04-adding-a-channel.md](./tutorial-04-adding-a-channel.md).

## Add an LLM provider

In `src/loop.metta`, the LLM call is:

```metta
($request (llmRequest $system (messagesGet) (maxOutputToken) (reasoningMode) (collectTools)))
($response (llmProviderChat $request))
```

`llmRequest` builds an `LLMRequest` from the system message, the message list, the output limits and the tool schemas from `collectTools`. `llmProviderChat` (`src/providers.metta`, `src/providers.py`) hands the request to the provider that `llmProviderStart` selected on turn 1 and validates the `LLMResponse` it returns. Providers are plugins, so the loop has no branch per provider.

To add a provider:

1. Implement a class derived from `providers.LLMProvider` with a `chat(self, request: LLMRequest) -> LLMResponse` method (see [reference-plugin-api.md](./reference-plugin-api.md#llm-provider-integration)).
2. Register it with `providers.registerLLMProvider` in the plugin's `loadOmegaPlugin`, and list the plugin in `config/plugins.yaml`.
3. Use the new provider name in the `configure provider ...` line or via command-line `provider=...`.

## Change the prompt

The agent's identity and values are in `memory/prompt.txt`. The run-time prompt template that sandwiches it is in `getContext` in `src/loop.metta`. Edit carefully. The tool schemas tell the LLM how to call tools (see [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md)).

## Change the embedding model

In `src/memory.metta`, the `embed` function dispatches on `embeddingprovider`:

```metta
(= (embed $str)
   (if (== (embeddingprovider) Local)
       (py-call (lib_llm_ext.useLocalEmbedding (string-safe $str)))
       (py-call (rag.cloud_embed (string-safe $str)))))
```

Any value other than `Local` is a provider id: the remote branch posts
`embeddingModel` to `<GATEWAY_URL>/<embeddingprovider lowercased>/`, the
location that already injects that provider's key. Switching vendor is
configuration, not code — provided the vendor serves embeddings at all. It
changes the vector space, so reset the ChromaDB store when you do.

## Change the reasoning library

`lib_nal.metta` and `lib_pln.metta` are plain MeTTa files loaded by `lib_omega.metta`. Add new rule definitions directly, or swap in a different logic library entirely — the only required surface is whatever operator the LLM invokes through the `metta` tool.

## See also

- [reference-internals-loop.md](./reference-internals-loop.md) — the loop is the host for all of the above.
- [reference-python-bridges.md](./reference-python-bridges.md) — bridge conventions.
