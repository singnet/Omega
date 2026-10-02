# Internals — Extension Points

Where to plug in new behavior, in order of increasing depth.

## Add a tool

Most common extension. A built-in tool takes three edits:

1. A line in `getStaticSkills` (`src/skills.metta`) so the LLM knows the tool exists. It follows the form of the lines already in that function, `"- <description>: <name> <argument>"`.
2. The tool name in `STATIC_LLM_COMMANDS` (`src/helper.py`) so the parser accepts calls to it. A tool that takes a file name and content also goes into `TWO_ARG_COMMANDS`.
3. A `(= (my-tool $arg) ...)` definition, either pure MeTTa or a `py-call` / `translatePredicate`.

A MeTTa plugin adds a tool with `add-skill` in its `loadOmegaPlugin` instead of edits 1 and 2. `add-skill` puts the tool's line into the prompt and registers the name with the parser (see [reference-plugin-api.md](./reference-plugin-api.md#other-agent-related-apis)).

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
($respi (llmProviderChat $send (maxOutputToken) (reasoningMode)))
```

`llmProviderChat` (`src/providers.metta`, `src/providers.py`) hands the call to the provider that `llmProviderStart` selected on turn 1. Providers are plugins, so the loop has no branch per provider.

To add a provider:

1. Implement a class derived from `providers.LLMProvider` with a `chat` method (see [reference-plugin-api.md](./reference-plugin-api.md#llm-provider-integration)).
2. Register it with `providers.registerLLMProvider` in the plugin's `loadOmegaPlugin`, and list the plugin in `config/plugins.yaml`.
3. Use the new provider name in the `configure provider ...` line or via command-line `provider=...`.

## Change the prompt

The agent's identity and values are in `memory/prompt.txt`. The run-time prompt template that sandwiches it is in `getContext` in `src/loop.metta`. Edit carefully — the `OUTPUT_FORMAT` instruction is what keeps the LLM writing tool calls in the line format that `helper.balance_parentheses` parses (see [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md)).

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
