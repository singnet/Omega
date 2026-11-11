# Tutorial 08 — Strategies for Reliable Reasoning

**Goal:** a practical playbook for getting trustworthy conclusions out of the hybrid system, drawing on the failure modes measured in [reference-failure-modes.md](./reference-failure-modes.md).

Treat this as a checklist you apply to any reasoning task that matters.

---

## 1. Keep chains short

**Rule:** 2–3 inference hops per chain. Insert revision (see §3) to go further.

**Why:** deduction confidence is `c_out = f₁ × f₂ × c₁ × c₂`. There is no threshold effect, no floor. Confidence drops roughly 10% per hop. Starting at `c = 0.9`:

| Hop | Confidence |
|---|---|
| 1 | 0.81 |
| 2 | 0.73 |
| 3 | below 0.5 |
| 4 | ~0.25 |

A 4-hop chain bottoms out below the IGNORE threshold — the conclusion is unreliable regardless of how confident the LLM sounds.

## 2. Ground premises externally

**Rule:** before feeding a premise into a chain, verify it against an external source and set confidence from source quality.

See [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md). In short: primary sources → `c ≈ 0.9`; secondary → `c ≈ 0.7`; LLM prior alone → treat as overconfident by 15 percentage points.

## 3. Use revision to restore confidence

**Rule:** when a chain degrades below `c = 0.5`, merge in independent evidence via revision.

Revision formula:

```
w = c / (1 - c)     (per premise)
w_total = Σ w_i
c_out = w_total / (w_total + 1)
f_out = weighted average of f_i by w_i
```

**Example — three independent sources each at `(stv 1.0 0.45)`:**

```
→ revised:  (stv 1.0 0.647)
```

**Five sources:**

```
→ revised:  (stv 0.848 0.937)
```

Two sources that disagree also revise — the output `f` drifts toward the middle, but `c` grows. Contradiction becomes a first-class signal, not a silent failure.

## 4. Respect the action thresholds

**Rule:** gate every downstream action on the `(f, c)` pair.

| Tier | Gate | Do |
|---|---|---|
| **ACT** | `f ≥ 0.6 AND c ≥ 0.5` | Take the step. |
| **HYPOTHESIZE** | `f ≥ 0.3 AND c ≥ 0.2` | Gather more evidence. |
| **IGNORE** | below both | Do not use. |

If a conclusion falls into HYPOTHESIZE, don't suppress it — **pin it and seek corroboration** through another source or another reasoning path.

## 5. Atomize carefully

The LLM's premise formulation is the largest error surface (up to 16.6% swap rate on asymmetric relations). Before committing to a chain, double-check:

- **Term order** — is `(--> A B)` actually what the fact says, or is the direction reversed?
- **Copula** — inheritance `-->`, implication `==>`, similarity `<->` are not interchangeable.
- **Granularity** — are distinct concepts being collapsed into a single atom?

When possible, write premises in two ways and see if both produce the same conclusion.

## 6. Structure multi-cycle reasoning

**Rule:** budget cycles — one cycle cannot both gather data and act on it because the LLM commits all tool calls before seeing results.

A canonical decomposition for a non-trivial question:

| Cycle | Tool calls |
|---|---|
| 1 | `query` memory, `websearch` for missing facts, `pin` the plan. |
| 2 | Atomize verified facts, run first `(metta (\|- ...))` step. |
| 3 | Revision with independent evidence; follow-up inference. |
| 4 | Threshold check; `send` the answer with provenance. |

## 7. Avoid post-hoc rationalization

**Rule:** reasoning must be in-loop from the start, not retroactive.

Measured bias: running the reasoning *after* committing to a conclusion shifts results — frequency drops ~50%, confidence inflates +14% vs. pre-committed values. Ask the engine first, then synthesize the answer, not the other way around.

## 8. Detect contradiction, don't hide it

**Rule:** when revision produces a frequency near 0.5 with non-trivial confidence, **report the disagreement** rather than forcing a single answer.

Example — cat dangerousness with conflicting sources:

```
(--> cat dangerous) (stv 0.2 0.8)   ; most cats not dangerous
(--> cat dangerous) (stv 0.9 0.5)   ; claim: dangerous
revision → (stv 0.395 0.875)
```

The revised `f = 0.395` with `c = 0.875` is the math saying: *"substantial but conflicting evidence."* Surface that to the user with both source citations; don't pick a winner arbitrarily.

## 9. Cache and reuse verified premises

**Rule:** after grounding a fact, `remember` it with provenance. Subsequent chains should `query` first and fetch only on miss.

This is the flywheel effect: reliability compounds with use, because verified premises accumulate in the long-term knowledge graph.

## 10. Report the proof trail

When the answer leaves the agent, include:

1. The conclusion and its `(stv ...)`.
2. The direct premises used, each with their `(stv ...)`.
3. The inference rule applied (deduction, revision, abduction, …).
4. The provenance of each premise — external source, LLM prior, memory hit.
5. The threshold tier (ACT / HYPOTHESIZE / IGNORE).

A conclusion without this trail is just an assertion; a conclusion with it is auditable.

---

## Anti-patterns to avoid

- **Single long chain** — multi-hop deduction without revision.
- **Self-supplied confidence** — LLM states both the fact and the `c` with no external check.
- **Suppressed contradictions** — forcing a single answer when revision revealed disagreement.
- **Confabulation under mathematical cover** — accepting an LLM-fabricated premise and treating the deduction output as authoritative.
- **Retroactive reasoning** — running `(metta ...)` to justify a conclusion the LLM already wrote.

---

## See also

- [reference-orchestration.md](./reference-orchestration.md) — stopping criteria, thresholds, defense stack.
- [reference-failure-modes.md](./reference-failure-modes.md) — measured failure rates.
- [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md) — external grounding.
- [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md) — the underlying mechanics.
