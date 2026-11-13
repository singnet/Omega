# Context frames

This plugin supplies frame-based working context, frame management tools, and
frame result recording. It owns the frame state, Python helpers, relation
backend, and runtime prompt in this directory.

Relationship classification requests JSON text through the selected provider's
configured connection, without defining a tool. The plugin parses the response;
classification failures are logged and leave the new frame without relations.
Query IDs must match the submitted frame. Retrieved candidates use current-session
status and results when available; retrieval still uses the stored embeddings.

The prompt includes compact content from up to five distinct frames linked from
the current frame. Working context covers `ContinuationOf`, `FollowUp`,
`DuplicateOf`, `SubgoalOf` and `ParentOf`. Dependency context (`DependsOn`,
`Blocks`) supplies task descriptions, status, results and summaries without
adopting goals or constraints. Reference context (`SameProject`,
`SameFailureCluster`, `Supersedes`) omits goals, constraints and deliverables;
`Supersedes` also omits history to avoid carrying earlier directives forward.
`RelatedButSeparate`, `Unrelated` and unknown classes are excluded. For conflicting
labels on one pair, exclusion takes precedence, followed by `Supersedes`, then
Working, Dependency and Reference context.

Related content retains its source frame, status and relation direction.
Composition does not merge goals, change focus or complete related frames. It uses
the current session's active and completed frame spaces; links to older Chroma
sketches without a full frame in those spaces do not contribute content.
Related history includes recorded tool batches, including the batch that completed
the frame.

The [entry point](context.metta) handles plugin startup and configuration.
[contextframe.metta](contextframe.metta) owns frame state and operations;
[contextframeskill.metta](contextframeskill.metta) registers the frame tools
and provides their wrappers and usage guidance.

Context frames are disabled by default. The interactive launcher asks whether
to enable them. For an explicit startup selection, use:

```sh
scripts/omega start -d omega:dev -p OpenAI -t telegram --context-frame enabled
```

Use `--context-frame disabled` for ordinary conversation history and direct
user messages. Changing the selection requires restarting Omega; existing
containers retain their startup selection.

When enabled, a missing or broken frame dependency stops startup and reports
the import error instead of falling back to ordinary conversation history.

For standalone startup, pass `contextFrame=enabled`, set
`OMEGA_contextFrame=enabled`, or set `contextFrame: enabled` in
`config/config.yaml`. The launcher also forwards `OMEGA_contextFrame` when set.
Explicit launcher selection takes precedence over environment and YAML values.
The plugin must remain listed in `config/plugins.yaml` to enable frame mode.

If you customized `memory/prompt_context_frame.txt`, copy those changes to
`plugins/context/prompt_context_frame.txt` before rebuilding the image. Frame
mode now reads its runtime prompt from the plugin directory.

When enabled, `loadOmegaPlugin` initializes frame state, registers frame tools,
and selects the frame context provider. The provider admits input before the
prompt is built, renders the current projection on every request, records tool
results against their originating frame, and handles Fast/Slow idle behavior.
The frame prompt includes `LOOPS_REMAINING`, the active iterations available
before going idle, including the current iteration.
Detailed frame history is capped per frame by `maxFrameHistoryEvents` (default
100 in `config/config.yaml`). Older events are archived in `memory/history.metta`
before pruning; the frame summary retains a bounded directive/decision/outcome
rollup and timestamp range. Use the `episodes` skill with a timestamp from the
pruning notice to retrieve archived details.
When disabled, it registers nothing and the default context provider remains
active.

The callback interface and ordinary history/message behavior live in
[`src/context_provider.metta`](../../src/context_provider.metta).

See the [context provider API](../../docs/reference-plugin-api.md#context-providers)
for the interface between the plugin and the core loop.
