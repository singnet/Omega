# Tutorial 01 — Teaching Memories

**Goal:** understand and exercise the four memory skills: `remember`, `query`, `episodes`, and `pin`.

## Prerequisites

- A running Omega (see [Usage](/README.md#usage)).

## Background

Omega uses a **three-tier memory architecture**:

1. **Working memory** — `pin` (volatile, single slot, session-local).
2. **Long-term embedding memory** — `remember` / `query` (persistent across sessions).
3. **AtomSpace** — atomized truth-valued atoms used by the reasoning engines. Separate; see [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md).

This tutorial covers tiers 1 and 2. For the full model, see [reference-internals-memory-store.md](./reference-internals-memory-store.md).

Long-term memory uses an embedding index. Each `(remember str)` stores the triplet `(timestamp, atom, embedding)` via the Python ChromaDB bridge. Each `(query str)` embeds the query string and returns the top `maxRecallItems` nearest items.

Alongside the embedding store, a plain-text **episodic trace** at `memory/history.metta` is appended to on every turn. `(episodes time)` reads lines around a timestamp from it.

## 1. Store a fact

Message the agent:

```
remember that the morning standup is at 10am
```

The LLM will emit something like `(remember "morning standup at 10am")`. Confirm in logs.

## 2. Recall by meaning

Ask later:

```
when is the team sync?
```

Even though you never said "sync" or "team", the embedding similarity should surface the stored fact.

## 3. Recall by time window

```
what happened around 2026-04-15 14:30:00?
```

This triggers `(episodes "2026-04-15 14:30:00")` which reads `maxEpisodeRecallLines` lines around that timestamp from the episodic trace.

## 4. Working memory with `pin`

Ask for a multi-step task:

```
draft three subject lines for a release announcement, pick the best, then send it
```

Well-behaved behavior is to `pin` the candidate list so the next turn can refer to it, then `send` the winner.

## Relevant configuration

From `src/memory.metta`:

- `maxRecallItems` — how many items `query` returns (default 20).
- `maxEpisodeRecallLines` — how many lines `episodes` returns (default 20).
- `maxHistory` — characters of history fed back into the prompt (default 30000).
- `embeddingprovider` — `OpenAI`, `ASICloud` or `Local`.

Change any of these by editing the `configure` calls in `initMemory` or passing command-line overrides — see [reference-configuration.md](./reference-configuration.md).

## Verification

- After `remember`, logs shows the ChromaDB write.
- A semantically related question (not keyword match) recalls the fact.
- `episodes` returns a contiguous block of history around the requested timestamp.

## Next steps

- [reference-skills-memory.md](./reference-skills-memory.md) — precise signatures and limits.
- [reference-internals-memory-store.md](./reference-internals-memory-store.md) — the triplet layout in detail.
