# Context frames

This plugin supplies frame-based working context, frame management tools, and
frame result recording. It owns the frame state, Python helpers, relation
backend, and runtime prompt in this directory.

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
The frame prompt includes `ITERATION`, the current main-loop iteration number
(including idle passes), and `LOOPS_REMAINING`, the active iterations available
before going idle, including the current iteration.
When disabled, it registers nothing and the default context provider remains
active.

The callback interface and ordinary history/message behavior live in
[`src/context_provider.metta`](../../src/context_provider.metta).

See the [context provider API](../../docs/reference-plugin-api.md#context-providers)
for the interface between the plugin and the core loop.
