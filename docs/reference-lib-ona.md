# Reference — ONA (OpenNARS for Applications)

ONA is a lightweight, real-time implementation of NARS created by Dr. Patrick Hammer. **ONA is not installed by default in Omega.** There are no ONA bindings in the repository, no `lib_ona.metta`, and no dedicated operator in the `(metta ...)` tool. The stock install ships two formal engines — symbolic NAL (`|-`) and probabilistic PLN (`|~`).

This page exists because ONA is named in the project's architectural vision and has been an experimental target — see [Status](#status-partly-successful-self-building-experiment) below.

## What ONA would add, if wired up

- **Throughput** — ONA can process thousands of inference steps per second.
- **Temporal reasoning** — reasoning about before/after, cause-and-effect, and sensorimotor loops.
- **Real-time capability** — inference on a millisecond budget.

## When ONA would be the right engine

If ONA were installed, the following shapes would route to it:

| Situation | Engine (if installed) |
|---|---|
| Known chain `A → B → C`, static facts | NAL `\|-` |
| Property-based categorical inference | PLN `\|~` |
| **Event sequences, cause/effect from experience** | **ONA** |
| Real-time sensorimotor loops | **ONA** |

Today, with ONA absent, the current practical fallback for temporal questions is NAL plus external temporal grounding — have the agent fetch timestamps or event ordering through `(shell ...)` or `(websearch ...)` and atomize them into NAL premises. This is not equivalent to what ONA would provide, and the docs do not pretend otherwise.

## Invocation surface

**There is no stock invocation surface for ONA in Omega.** `lib_omega.metta` does not load ONA bindings. The `(metta ...)` tool has no ONA operator.

Any integration has to be built — either by calling an external ONA binary through `(shell ...)` and parsing its output, or by constructing MeTTa-side wrappers that emulate ONA's temporal operators. This is a non-trivial tools-authoring task and is the subject of the experiment described below.

## Status: partly-successful self-building experiment

Omega's architectural vision lists ONA as a third engine, but in practice ONA support has been pursued as an experiment in whether the agent can **itself build the tools** to interface with that reasoning system. Results so far: partly successful.

What this means concretely:

- The agent has been used to draft shell-callable wrappers and MeTTa-side glue code for ONA-style inference. Some components work in isolation; none are integrated into the default agent loop.
- Temporal inference is not meaningfully exposed in the current codebase.
- There is no native mechanism for belief revision triggered by time — confidence does not automatically decay for stale claims.
- Real-time feedback loops require careful phase tracking and frequently break due to state-management failures when the agent attempts to orchestrate them end-to-end.

Treat ONA in Omega as a research direction, not a feature. The limits of agent-authored self-improvement (which is effectively what this experiment is) are documented in [reference-failure-modes.md §6](./reference-failure-modes.md) — self-authored improvements should be taken as signals but validated externally before being relied upon.

## See also

- [reference-lib-nal.md](./reference-lib-nal.md) — the symbolic engine (installed).
- [reference-lib-pln.md](./reference-lib-pln.md) — the probabilistic engine (installed).
- [reference-orchestration.md](./reference-orchestration.md) — how the LLM picks between the installed engines.
- [reference-failure-modes.md](./reference-failure-modes.md) — §6 covers the self-improvement pattern this experiment fits into.
