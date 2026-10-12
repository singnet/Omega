# Omega Documentation

This directory contains the full documentation for Omega. Every page is a sibling file — no subdirectories. Filename prefixes identify the section:

- `intro-*` — conceptual introduction
- `tutorial-NN-*` — numbered, task-oriented walkthroughs
- `reference-*` — API, engines, orchestration, failure modes, and internals

If you are new, read the Introduction in order, then pick tutorials that match what you want to build, and dip into the reference when you need details.

---

## Introduction

Start here to understand what Omega is, the hybrid reasoning thesis, how the pieces fit together, and how to get it running.

- [introduction.md](./introduction.md) — What Omega is, the hybrid thesis, architecture, core vocabulary, design goals, and honest limits (merged conceptual intro).
- [installation instruction](/README.md#installation) — Manual MeTTa setup, environment variables, API keys.

---

## Tutorials

Numbered in suggested reading order. Each tutorial is self-contained.

- [tutorial-01-teaching-memories.md](./tutorial-01-teaching-memories.md) — Use `remember`, `query`, `episodes`, and `pin`
- [tutorial-02-shell-and-files.md](./tutorial-02-shell-and-files.md) — `shell`, `read-file`, `write-file`, `append-file`
- [tutorial-03-writing-a-custom-tool.md](./tutorial-03-writing-a-custom-tool.md) — Add a new MeTTa tool end-to-end
- [tutorial-04-adding-a-channel.md](./tutorial-04-adding-a-channel.md) — Build a new communication channel adapter
- [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md) — Invoke NAL and PLN through `(metta ...)` with worked examples
- [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md) — External grounding — the primary reliability mitigation
- [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md) — Strategy playbook — chain depth, revision, thresholds, anti-patterns

---

## Reference

### Reasoning engines and orchestration

- [reference-lib-nal.md](./reference-lib-nal.md) — NAL rules with truth formulas; confirmed vs. non-functional patterns
- [reference-lib-pln.md](./reference-lib-pln.md) — Modus Ponens, abduction, revision; current limits
- [reference-lib-ona.md](./reference-lib-ona.md) — OpenNARS for Applications — planned real-time / temporal engine (experimental, not installed by default)
- [reference-orchestration.md](./reference-orchestration.md) — Engine selection, stopping criteria, action thresholds, defense stack
- [reference-failure-modes.md](./reference-failure-modes.md) — Documented failures, error rates, mitigations

### Tools

Built-in tools the agent can call. Each page follows the template **Signature → Purpose → Parameters → Returns → Examples → Notes/Limits**.

- [reference-tools-memory.md](./reference-tools-memory.md) — `remember`, `query`, `episodes`, `pin`
- [reference-tools-io.md](./reference-tools-io.md) — `shell`, `read-file`, `write-file`, `write-file-b64`, `append-file`, `get-io-policy`
- [reference-tools-communication.md](./reference-tools-communication.md) — `send`, `websearch`, and `receive` (called by the loop)
- [reference-tools-reasoning.md](./reference-tools-reasoning.md) — `metta` (NAL/PLN invocation surface)

`delete-file` and `version` are built-in tools too and have no reference page yet.

### Configuration & Adapters

- [reference-configuration.md](./reference-configuration.md) — `configure` form and all runtime parameters
- [reference-channels.md](./reference-channels.md) — IRC, Telegram, Slack, Mattermost, and WebSocket adapters plus the channel contract, and the backend of the `websearch` tool
- [reference-python-bridges.md](./reference-python-bridges.md) — `lib_llm_ext.py`, `src/helper.py`, `src/skills.pl`
- [reference-memory-portability.md](./reference-memory-portability.md) — Operator backup, restore, and archive-transfer workflow

### Plugin API

- [reference-plugin-api.md](./reference-plugin-api.md) - Plugin API documentation

### Plugin publishing

- [reference-plugins-publishing.md](./reference-plugins-publishing.md) — how to submit a plugin for the catalog

### Internals

- [reference-internals-loop.md](./reference-internals-loop.md) — `src/loop.metta` lifecycle and turn structure
- [reference-internals-memory-store.md](./reference-internals-memory-store.md) — The three-tier memory architecture, including `knowledge-priors` markdown seeding into ChromaDB
- [reference-internals-tool-dispatch.md](./reference-internals-tool-dispatch.md) — How tool calls are parsed and dispatched
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — Where to hook in new tools, channels, LLM providers, and engines
