# Introduction

Omega is a **hybrid agentic AI framework** implemented in MeTTa on OpenCog Hyperon. A large language model (LLM) works together with formal logic engines — **NAL** and **PLN** — to reason about the world, track uncertainty, combine evidence, and produce conclusions that are mathematically grounded rather than just plausible-sounding.

The core agent loop is approximately **200 lines of MeTTa**.

> Most AI assistants generate answers that sound right. Omega-hosted agents generate answers that come with a **mathematical receipt** showing exactly how confident each conclusion is and what evidence supports it. When the agent says it is 72% confident, that number comes from formal inference — not a feeling.

This page is the conceptual introduction: what Omega is, why the hybrid architecture exists, how the pieces connect at runtime, the vocabulary used throughout the rest of the docs, and the honest limits of the current system. For getting a running instance, see [installation instruction](/README.md#installation). For hands-on walkthroughs, see the tutorials listed at the end.

---

## What Omega does

- Runs a token-efficient agentic loop that receives messages, selects tools and skills, and acts.
- Delegates reasoning to one of two formal engines, orchestrated by the LLM:
  - **NAL** — Non-Axiomatic Logic, symbolic inference under uncertainty.
  - **PLN** — Probabilistic Logic Networks, probabilistic higher-order reasoning.
  - ONA (OpenNARS for Applications) is a planned third engine but is **not installed by default** — see [reference-lib-ona.md](./reference-lib-ona.md) for the current experimental status.
- Maintains a **three-tier memory** architecture (working, long-term, AtomSpace — described below).
- Exposes an extensible **set of tools** covering memory, shell and file I/O, communication channels, web search, remote agents, and formal reasoning.
- Loads **skills** (step-by-step instructions for a task, in the [Agent Skills](https://agentskills.io/specification) format) through the workflow plugin. A loaded skill adds its instructions to the prompt and its own tools to the request, as the bundled research workflow does (see [Skills](#skills)).

---

## The hybrid thesis

### Two kinds of reasoning, one pipeline

| Aspect | LLM (neural) | Formal engine (symbolic) |
|---|---|---|
| Natural language understanding | ✅ | ❌ |
| Premise formulation from text | ✅ | ❌ |
| Inference orchestration (which rule when) | ✅ | ❌ |
| Truth-value propagation | ❌ | ✅ |
| Confidence decay through chains | ❌ | ✅ |
| Formal contradiction detection | ❌ | ✅ |
| Auditable conclusion path | ❌ | ✅ |

The LLM turns ambiguous natural language into structured atoms with explicit truth values. The formal engine takes those atoms and applies rules whose truth-value arithmetic is deterministic and auditable.

When the agent outputs a conclusion, you can trace it back through every step: which premises fed into which rule, what truth value each premise carried, and what the math produced.

### The orchestration cycle (call-and-wait)

Each reasoning hop is a synchronous five-step dance:

```
1. NEURAL PHASE
   LLM synthesizes context, emits a tool call
   (e.g. metta with the expression (|- ...))

2. CONVERSION
   The agent framework turns the tool call from the
   response into an s-expression; LLM generation
   is suspended.

3. SYMBOLIC PHASE
   Framework passes the s-expression to the MeTTa /
   Hyperon interpreter. The engine executes logic
   independently of the LLM.

4. RESULT CAPTURE
   Engine returns deterministic result atoms
   (e.g. (robin --> animal) (stv 0.72 0.32)).

5. INJECTION & RESUMPTION
   Results go back to the LLM as immutable data, in
   messages with role `tool`. The LLM resumes, reads them,
   and decides the next move.
```

Step 3 is **opaque to the LLM in a useful way** — the LLM cannot tamper with the truth-value math. Confidence cannot be inflated by rhetoric.

---

## Architecture

A thin MeTTa core drives the two formal reasoning engines and a handful of Python bridges for LLM calls, embeddings, and network I/O.

### Layered view

```
┌─────────────────────────────────────────────────┐
│  LLM Layer                                      │
│  - Natural language understanding               │
│  - Premise formulation (atomization)            │
│  - Inference orchestration                      │
│  - Contextual steering                          │
└────────────────────┬────────────────────────────┘
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
┌──────────┐                 ┌──────────┐
│ NAL   |- │                 │ PLN   |~ │
│ Engine   │                 │ Engine   │
└────┬─────┘                 └────┬─────┘
     │                            │
     └─────────────┬──────────────┘
                   │
       ┌────────────┴────────────┐
       ▼                         ▼
┌────────────────┐     ┌──────────────────┐
│ Memory 3-tier  │     │ Shell / Files /  │
│ - pin  (ST)    │     │ Channels / Web   │
│ - remember LT  │     │                  │
│ - AtomSpace    │     │                  │
└────────────────┘     └──────────────────┘
```

The **LLM layer** is opaque and creative. The **engine layer** is deterministic and auditable.

### Module map

```
run.metta                     entry point: (omega)
lib_omega.metta               loads all submodules
├── src/loop.metta            agentic loop, turn structure
├── src/memory.metta          long-term memory + history
├── src/skills.metta          tool list and built-in tools
├── src/channels.metta        receive/send dispatch
├── src/utils.metta           utility, string ops, time
├── src/config.metta          configure
├── src/helper.py             string normalization, time helpers
├── src/providers.py          tool schemas, response checks, call conversion
├── src/skills.pl             Prolog helpers (shell, first_char)
├── src/websearch.py          web search
├── lib_nal.metta             NAL truth functions
├── lib_pln.metta             PLN rules
└── providers/lib_llm_ext.py  OpenAI-compatible LLM clients, local embeddings

channels/irc.py               IRC adapter
channels/telegram.py          Telegram adapter
channels/slack.py             Slack adapter
channels/mattermost.py        Mattermost adapter

memory/prompt.txt             system prompt (agent identity + values)
memory/history.metta          episodic trace (written at runtime)
```

### The agentic turn

Each iteration of `(omega $k)` in `src/loop.metta` performs:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. getContext()     PROMPT + SKILLS rules + extensions +    │
│                     HISTORY + TIME                          │
│ 2. receive()        pull latest message from channel        │
│ 3. LLM call         request with tool schemas to the        │
│                     provider (Anthropic, OpenAI, ASICloud,  │
│                     ASI:One, OpenRouter, ...)               │
│ 4. llmResponseToSExpr + sread                               │
│                     tool calls into s-exprs                 │
│ 5. eval each call   (remember ...), (metta ...), ...,       │
│                     result sent as a tool message           │
│ 6. addToHistory     append human msg + tool calls +         │
│                     any errors                              │
│ 7. sleep            sleepInterval seconds                   │
│ 8. recurse          (omega (+ 1 $k))                        │
└─────────────────────────────────────────────────────────────┘
```

If no new message arrives and the `loops` counter hits zero, the agent idles until `nextWakeAt`, then runs one wake loop for background work.

The neural↔symbolic sub-cycle described in [The hybrid thesis](#the-hybrid-thesis) above kicks in **inside** step 5 whenever a tool call is `metta (|- ...)` or `metta (|~ ...)`.

### Division of labor

| Controlled by the LLM (opaque) | Controlled by the engine (transparent) |
|---|---|
| Which premises to include | How truth values propagate |
| Initial `(stv f c)` assignments | Confidence decay through chains |
| Which inference rule to invoke | The math of the rule |
| When to stop reasoning | Whether the conclusion follows |

See [reference-orchestration.md](./reference-orchestration.md) for the LLM's side of the policy.

### Data flow — a grounded memory write

```
user message
   │
   ▼
(receive) ─► channel adapter ─► loop input
                                   │
                                   ▼
                            LLM atomizes:
                            (remember "...")
                                   │
                                   ▼
              src/memory.metta ─► embed() ─► lib_llm_ext ─► vector
                                   │
                                   ▼
                  lib_chromadb.remember(str, vec, timestamp)
```

For a **grounded** write with provenance, the pattern is the same, but the LLM first queries memory, then fetches from a verified source before calling `remember`. See [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md).

### Three-tier memory interaction

A reasoning-heavy turn typically uses all three memory tiers:

```
1. query long-term memory for relevant past findings
        │
        ▼
2. atomize relevant knowledge into AtomSpace
        │
        ▼
3. reason over atoms via (metta (|- ...)) or (|~ ...)
        │
        ▼
4. remember novel conclusions with provenance
        │
        ▼
5. pin reasoning state for the next cycle
```

### Configuration

Runtime parameters are declared as `(empty)` at module top and filled by `configure` calls during `initLoop`, `initMemory`, and `initChannels`. Command-line overrides are accepted via the `argk` helper in `src/utils.metta`. Full list in [reference-configuration.md](./reference-configuration.md).

---

## Core concepts

Vocabulary used throughout the rest of the documentation. Skim once; come back when a term shows up in another page.

### AtomSpace

The knowledge substrate provided by Hyperon / MeTTa. Every fact, memory item, and program fragment in Omega lives in the same AtomSpace, so memory is directly interrogable by other Hyperon components.

### Atomization

The act of converting natural-language facts into AtomSpace atoms with explicit truth values. Example:

Natural: *"Sam and Garfield are friends, and Garfield is an animal."*

Atomized:

```metta
(--> (× sam garfield) friend)  (stv 1.0 0.9)
(--> garfield animal)          (stv 1.0 0.9)
```

Atomization is a first-class step — raw text cannot participate in formal inference. Each atom carries an **explicit relationship type** (inheritance, implication, similarity) and an **explicit truth value**.

### `stv` — subjective truth value

Every atom carries `(stv frequency confidence)`:

- **frequency** ∈ [0.0, 1.0] — how often the statement held among observed evidence.
- **confidence** ∈ [0.0, 1.0] — how much evidence we have.

Negation is `(stv 0.0 c)` — strong evidence *against* the statement.

### Expectation

A scalar derived from `(stv f c)`:

```
exp = c × (f - 0.5) + 0.5
```

Maps an `(f, c)` pair to a single value in `[0, 1]`, useful for priority queues and ranking.

### The reasoning engines

| Engine | MeTTa operator | Strength |
|---|---|---|
| **NAL** — Non-Axiomatic Logic | `\|-` | Symbolic inference under uncertainty, revision, evidence merging |
| **PLN** — Probabilistic Logic Networks | `\|~` | Probabilistic higher-order reasoning |

Dedicated pages: [reference-lib-nal.md](./reference-lib-nal.md), [reference-lib-pln.md](./reference-lib-pln.md), [reference-lib-ona.md](./reference-lib-ona.md) (experimental, not installed).

### Three-tier memory

Three distinct stores with different semantics:

1. **Working memory (`pin`)** — notes kept in the episodic trace. A `pin` call is part of the reply that `addToHistory` appends to `memory/history.metta`, and it stays in `HISTORY` until newer entries push it out of the last `maxHistory` characters.
2. **Long-term embedding memory (`remember` / `query`)** — persistent semantic recall. Survives restarts.
3. **AtomSpace** — atomized, truth-valued knowledge used by NAL and PLN.

Full detail in [reference-internals-memory-store.md](./reference-internals-memory-store.md).

### Tools

A tool is an action the agent can take during a turn, such as `send`, `shell`, `remember`, `query`, or `metta`. A tool has a name, a one-line description, and a list of arguments, and it runs as a MeTTa function. Built-in tools and tools from plugins are registered the same way, with `add-skill`. Built-in ones are registered in `src/skills.metta`, and `remove-skill` unregisters a tool. Each turn the registered tools go to the LLM in the `tools` field of the request, one schema per tool with a string parameter for every argument. The `SKILLS:` part of the system message holds only extra rules for some tools.

A tool call is the LLM's request to run a tool. The request requires the model to call at least one tool, and the text the model writes next to its calls is not used. `llmResponseToSExpr` in `src/providers.py` turns each call into a MeTTa expression, so a `send` call with the content `Hello` becomes `(send "Hello")`, and Omega evaluates it. A reply with no tool calls, or a call to a tool that is not registered, is reported as an error. The value a tool returns is its tool result. Omega cuts each result to its last `maxFeedback` characters and sends it back as a message with role `tool` and the id of the call, and the model reads it on the next turn.

### Skills

A skill is a directory with a `SKILL.md` file in the [Agent Skills](https://agentskills.io/specification) format. The file holds Markdown instructions that tell the agent how to carry out a task step by step, and the directory can also hold a `skill.metta` file with the tools the skill needs. The workflow plugin loads skills and refers to a loaded skill as the active workflow. While a skill is loaded, its instructions are part of the prompt and its tools are added to the request. See [plugins/workflow/README.md](../plugins/workflow/README.md).

The word `skill` means a tool in some identifiers from the code: `add-skill`, `remove-skill`, `dynamic-skill`, `getSkills`, `getSkillRules`, `src/skills.metta`, `src/skills.pl`, `skill.metta` with its `(skill ...)` entries, `&workflow_skills`, the `SKILLS:` label in the prompt, and the log lines `Add skill:`. The documentation quotes these names as they are.

The texts the model reads at run time (`memory/prompt*.txt`, `memory/tg_prompt.txt`, the `SKILLS:` section of the prompt, and the workflow `description.txt` files) sometimes use `skill` for a tool as well. The documentation quotes them unchanged.

### Channels

Abstract communication endpoints. `(send ...)` and `(receive)` delegate to the active channel adapter (IRC, Telegram, Slack, Mattermost, or WebSocket). See [reference-channels.md](./reference-channels.md).

### Orchestration

The LLM's policy for picking which engine (or no engine) to invoke for a given task, plus when to stop reasoning. Full table in [reference-orchestration.md](./reference-orchestration.md).

### Action thresholds

Three decision tiers applied to any `(f, c)` before acting on the conclusion:

| Tier | Gate |
|---|---|
| ACT | `f ≥ 0.6 AND c ≥ 0.5` |
| HYPOTHESIZE | `f ≥ 0.3 AND c ≥ 0.2` |
| IGNORE | below |

Full context in [reference-orchestration.md](./reference-orchestration.md).

### The defense stack

Four layers applied to every piece of incoming evidence to resist noise and adversarial input:

1. **Novelty modulation** — new claims enter with `c × (1 − novelty)`.
2. **Action thresholds** — the tiers above.
3. **Attention budgeting** — priority queue by expectation, with per-cycle step limits.
4. **Adversarial premise testing** — regression suite for confident lies, contradictions, and gradual poisoning.

See [reference-orchestration.md](./reference-orchestration.md) for each layer.

### External grounding

The pattern of anchoring a premise's confidence on a verified external source rather than the LLM's prior. The primary mitigation for premise-formulation errors. See [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md).

### Revision

An inference rule that merges independent evidence about the same statement. Increases confidence when sources agree; produces a middle frequency with high confidence when they disagree, making contradiction visible.

### GIGO amplification

The failure mode where a flawed premise is run through the formal engine and emerges with a mathematically-authoritative-looking conclusion. Why the mitigations matter. See [reference-failure-modes.md](./reference-failure-modes.md).

## Design goals and honest limits

### Design goals

- **Transparency by design, not by post-hoc explanation.** Every conclusion can be traced to its premises, rule, and truth-value math.
- **Simplicity.** A small core that is readable end-to-end.
- **Extensibility.** New tools, skills, channels, and engines are short additions — see [reference-internals-extension-points.md](./reference-internals-extension-points.md).
- **Flexibility in memory representation.** Memory items coexist with other Hyperon components in the same AtomSpace; no single representation is hardcoded.

### When to use Omega

- a small, auditable agent that can explain **why** it reached a conclusion;
- reasoning with explicit uncertainty (`stv frequency confidence`) rather than opaque probabilities;
- a platform for experimenting with NAL and PLN inside an agent loop;
- a chat-facing agent over IRC, Telegram, Mattermost, or a channel you add yourself.

### Honest limits

The hybrid design moves the failure mode — it does not eliminate it. Known issues, quantified on the reference deployment:

- LLM premise formulation errors (up to ~16.6% on asymmetric relations).
- LLM confidence overestimation (~15 percentage points on self-assigned truth values).
- Confidence decays ~10% per inference hop; by the third hop, `c` typically drops below 0.5.

**Garbage In, Garbage Out** applies with a twist: the formal engine does not merely pass through garbage, it **amplifies** it by lending mathematical authority to conclusions derived from flawed premises.

The mitigations (external grounding, revision, action thresholds, the defense stack) are documented and non-optional for production use. See [reference-failure-modes.md](./reference-failure-modes.md) for the full catalogue and [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md) for strategy.

---

## Where to go next

- [tutorial-01-teaching-memories.md](./tutorial-01-teaching-memories.md) — hands-on first session.
- [reference-orchestration.md](./reference-orchestration.md) — engine selection, stopping criteria, action thresholds, defense stack.
- [reference-internals-loop.md](./reference-internals-loop.md) — turn structure in detail.
- [reference-internals-memory-store.md](./reference-internals-memory-store.md) — the three memory tiers.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — where to plug in new behavior.
