# Internals — Memory Store

Omega uses a **three-tier memory architecture**. Each tier has distinct semantics, persistence, and purpose. Choosing the wrong tier is one of the easier performance and reliability foot-guns.

## Overview

| Tier | Skill | Persistence | Role |
|---|---|---|---|
| 1. Working memory | `pin` | Single slot, overwritten per cycle, session-local | Task state — "what am I doing right now?" |
| 2. Long-term embedding memory | `remember` / `query` | Persistent across sessions | Accumulated knowledge, semantic recall |
| 3. AtomSpace | `(metta ...)` | Per-invocation (fresh AtomSpace each `\|-` call) | Formal reasoning over truth-valued atoms |

---

## 1. Working memory — `pin`

### Purpose
Holds the agent's current task state: what it is doing, what step comes next, what intermediate results matter.

### Characteristics
- **Limited, volatile, constantly updated.**
- Each cycle can overwrite the previous pin.
- Does **not** persist across sessions.
- Analogous to human working memory.

### Use it for
- Multi-step plans currently in flight.
- Intermediate results the next turn needs to see.
- Checklists that do not need to outlive the current task.

### Do not use it for
- Anything that must survive a restart — use `remember` instead.
- Structured knowledge the reasoner should act on — atomize into AtomSpace via `(metta ...)`.

---

## 2. Long-term embedding memory — `remember` / `query`

Backed by ChromaDB via a Python bridge (`lib_chromadb`, invoked from `src/memory.metta`).

### Storage format
Each item is the triplet:

```
(timestamp, atom, embedding)
```

- `timestamp` — produced by `get_time_as_string`, format `"%Y-%m-%d %H:%M:%S"`.
- `atom` — the raw string, post-`string-safe` (escapes `"`, newlines, `'`).
- `embedding` — vector from `embed $str`, dispatching on `embeddingprovider`:
  - `Local` → `lib_llm_ext.useLocalEmbedding`.
  - Cloud providers → `rag.cloud_embed`.

The embedding provider and model must remain compatible with those used to
create the existing collection. Changing them can cause write and search errors
or unreliable search results, even when vector dimensions match.

### Collection embedding profile

The collection metadata stores `omega_embedding_provider` and
`omega_embedding_model`. In `src/rag.py`, `ensure_embedding_profile()` records
the configured provider and model when the collection is empty, replacing any
different or incomplete profile while preserving other collection metadata.
If the profile already matches, no metadata update is made. Nonempty collections
keep their existing metadata; a missing or incomplete profile remains unknown
to avoid labeling old vectors with the current configuration.

`check_embedding_profile()` calls this function and then compares the stored
and configured profiles. Both the launcher's `ltm_precheck` and
`rag.init_knowledge()` call the shared check, before starting the agent container
and before runtime knowledge indexing respectively. A matching profile produces
no warning; an unknown or mismatching profile produces a warning without stopping
startup or re-embedding stored vectors. Standalone startup runs the same check.
When using the launcher, a warning can appear both in the launcher console and
in the agent's configured logs.

On a new volume, a successful precheck creates and labels the collection before
the optional startup knowledge import. The importer reuses that collection
without validating or overwriting its profile. Nonempty collections keep their
profile, and a warning alone does not prevent an import with incompatible
embeddings. See [startup memory profile check](reference-configuration.md#startup-memory-profile-check)
for launcher behavior when the check fails.

### Write path

```
(remember $str)
  → py-call (lib_chromadb.remember $str (embed $str) (get_time_as_string))
```

Returns `REMEMBER-SUCCESS` after a successful write or a MeTTa `Error` if
embedding or the write raises an exception.

### Semantic read

```
(query $str)
  → py-call (lib_chromadb.query (embed $str) (maxRecallItems))
```

Returns the top-`k` items by embedding similarity, or a MeTTa `Error` if embedding
or the search raises an exception. **Known issue:** query can miss relevant results
when embedding similarity thresholds do not match the query phrasing.

### Time-window read

```
(episodes $time)
  → py-call (helper.around_time $time (maxEpisodeRecallLines))
```

Reads lines around `$time` from `memory/history.metta` — the **episodic trace**, not the embedding store. See §4 below.

### Startup knowledge priors

At startup, Omega also checks for a folder named `knowledge-priors` in the Omega project root. If that folder exists and contains Markdown files (`*.md`), their contents are chunked, embedded, and loaded into the ChromaDB `memories` collection for semantic lookup.

The loader skips the step when the folder is missing, or when the folder exists but has no `.md` files. Indexed chunks are tagged with `time = knowledge_prior` instead of an actual time.

### Use it for
- Facts that must persist across sessions.
- Verified, grounded premises (attach provenance in the atom body).
- Accumulated user preferences, skills learned, lessons.

### Do not use it for
- Ephemeral scratchpad state — use `pin`.
- Knowledge you intend to reason over in the same turn — atomize via `(metta ...)`.

---

## 3. AtomSpace — where reasoning happens

### Purpose
When the agent needs to **reason rather than just recall**, knowledge must be decomposed into atomic logical statements and loaded into MeTTa's AtomSpace.

### Atomization

Natural-language fact:

> Sam and Garfield are friends, and Garfield is an animal.

Atomized:

```metta
(--> (× sam garfield) friend)  (stv 1.0 0.9)
(--> garfield animal)          (stv 1.0 0.9)
```

Each atom has an **explicit relationship type** and an **explicit truth value**. This is not formatting — it unlocks operations impossible on raw text:

1. **Composable inference** — atoms combined by the engine to derive new knowledge.
2. **Evidence tracking** — when two sources confirm the same fact, revision merges them into stronger belief.
3. **Formal contradiction detection** — an atom with `(stv 0.0 0.9)` explicitly represents strong evidence of negation.
4. **Surgical updates** — individual atoms can be revised without touching the rest of the knowledge base.

### Critical structural constraint

> Each `(metta (|- ...))` call **starts with a fresh AtomSpace.** Knowledge does not persist between invocations.

This means multi-step reasoning requires the LLM to manually carry results forward — pin them, or write them back to long-term memory and re-load on the next cycle.

---

## 4. The episodic trace

A fourth, plainer store lives alongside the three tiers above: the plain-text file `memory/history.metta`, appended to by `appendToHistory` at the end of each turn.

Each appended block contains:

- Timestamp.
- `HUMAN_MESSAGE:` line when new input arrived.
- The LLM's response s-expression.
- `ERROR_FEEDBACK:` when the loop captured an error.

The trailing `maxHistory` characters are loaded back into the prompt as `HISTORY` context. `(episodes ts)` reads lines around a timestamp.

The episodic trace is not a separate "tier" in the same sense — it is the running log that makes the short-horizon loop work. `pin` writes into it; `remember` writes around it.

---

## The three-tier interaction loop

A reasoning-heavy turn typically cycles through all three tiers:

```
1. query     — recall relevant past findings (Tier 2)
2. atomize   — convert relevant knowledge into MeTTa atoms (Tier 3)
3. reason    — (metta (|- ...)) over atoms
4. remember  — store novel conclusions with provenance (Tier 2)
5. pin       — capture reasoning state for next cycle (Tier 1)
```

---

## Why two persistent stores

- **Long-term memory** uses embeddings for semantic recall across arbitrary time spans. Content is natural language.
- **AtomSpace** uses formal atoms with explicit truth values for inference. Content is structured, not text.

They are complementary, not overlapping. Long-term memory *feeds* the AtomSpace by supplying candidate facts; the AtomSpace *reasons over* them; novel conclusions are *stored back* into long-term memory as atomized strings.

---

## See also

- [reference-skills-memory.md](./reference-skills-memory.md) — user-facing surface.
- [reference-configuration.md](./reference-configuration.md) — memory tunables.
- [introduction.md#the-hybrid-thesis](./introduction.md#the-hybrid-thesis) — why this layout exists.
- [tutorial-01-teaching-memories.md](./tutorial-01-teaching-memories.md) — hands-on use.
- [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md) — storing facts with provenance.
