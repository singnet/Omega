# Reference — Orchestration

Omega exposes two reasoning engines (NAL and PLN) plus direct memory recall. The LLM decides which to use, when to stop, and whether to act on a result. This page catalogues those decision policies. (ONA is a planned third engine — see [reference-lib-ona.md](./reference-lib-ona.md) for its experimental, not-installed status.)

---

## 1. Engine selection (pattern → engine)

The LLM uses **heuristic triage**: recognize the reasoning shape, then pick the engine.

| Situation | Pattern | Engine |
|---|---|---|
| Factual recall, no chains | Direct retrieval | `query` / `episodes` |
| Known chain `A → B → C` | Deduction | NAL `\|-` |
| Observed effect, seeking cause | Abduction | NAL `\|-` |
| Multiple instances → generalization | Induction + Revision | NAL `\|-` |
| Property-based categorical inference | Modus Ponens | PLN `\|~` |
| Independent evidence to merge | Revision | NAL or PLN |
| Real-time temporal sequences | Temporal inference | (no stock engine — ONA is the planned target but not installed; fall back to NAL with external temporal grounding) |
| Evidence conflicts | Revision | NAL / PLN |
| Novel hypothesis generation | Abduction / Induction | NAL |

Fallback rule: **if an engine returns empty, reformulate premises (fix term order or missing middle). If still empty, switch engine.**

---

## 2. Stopping criteria

Halt conditions the LLM is expected to monitor after each inference hop:

| Signal | Threshold | Action |
|---|---|---|
| Confidence floor | `c < 0.3` | **Halt.** Conclusion is unreliable. |
| Sufficiency threshold | `c ≥ 0.6` | Actionable for practical decisions. |
| Diminishing returns | New hop reduces confidence more than it adds information | Halt. |
| Resource budget | 5 tool calls per cycle | Ceiling the LLM is asked to keep. |

The per-cycle ceiling on tool calls is set in the output-format directive built by `getContext` in `src/loop.metta`. The loop does not enforce the ceiling and still runs every call in a longer reply.

---

## 3. Action thresholds (three-tier gating)

Once a truth value is in hand, compare it against these tiers before taking an action:

| Tier | Gate | Meaning |
|---|---|---|
| **ACT** | `f ≥ 0.6 AND c ≥ 0.5` | Actionable — take the step. |
| **HYPOTHESIZE** | `f ≥ 0.3 AND c ≥ 0.2` | Worth exploring — gather more evidence. |
| **IGNORE** | below both | Insufficient evidence — do nothing. |

The NAL **expectation** helper is useful for ranking candidates:

```
exp = c × (f - 0.5) + 0.5
```

It maps `(f, c)` to a single scalar in `[0, 1]` suitable for a priority queue.

---

## 4. Conflict resolution

When two results disagree:

1. **Prefer the higher-confidence result if frequencies agree.**
2. If **frequencies clash**, invoke revision to merge the premises as independent sources.
3. **Respect engine domains** — NAL for inheritance-style chains, PLN for property-based inference.

Revision produces a frequency that encodes the disagreement (drifts toward the middle) while confidence grows — the new truth value makes "substantial but conflicting evidence" explicit in the math.

---

## 5. The defense stack (four layers)

Omega assembles these layers to resist noisy or adversarial input:

### Layer 1 — Novelty modulation
New claims are discounted by their novelty:

```
c_new = c × (1 - novelty)
```

Claims without precedent in long-term memory enter the reasoner at reduced confidence.

### Layer 2 — Action thresholds
The ACT / HYPOTHESIZE / IGNORE gates above prevent low-evidence claims from reaching decisions.

### Layer 3 — Attention budgeting
A priority queue ranked by NAL expectation (`exp = c × (f - 0.5) + 0.5`) with hard step limits per cycle. Spend attention on the most promising inferences first.

### Layer 4 — Adversarial premise testing
Regression suite: confident lies, direct contradictions, and gradual poisoning are injected into the pipeline. The stack has been validated to downgrade adversarial inputs in all tested cases.

---

## 6. Multi-cycle reasoning pattern

Complex questions usually cannot fit in one cycle because the LLM must emit all tool calls before seeing results. A typical decomposition:

| Cycle | Purpose |
|---|---|
| 1 | Gather information — `query` memory, `websearch` web, read files, fetch external data. |
| 2 | Atomize the relevant knowledge; run the first NAL or PLN step. |
| 3 | Revision with independent evidence; follow-up inference. |
| 4 | Threshold check; decide whether to `send` an answer. |

The LLM is expected to **pin** state between cycles so the next turn can continue from the same plan. See [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md).

---

## 7. When automatic orchestration fails

If the LLM picks the wrong engine or formulates bad premises (see [reference-failure-modes.md](./reference-failure-modes.md) for measured rates), the observable symptoms are:

- Empty result from `|-` or `|~`.
- Result with suspiciously high confidence after many hops.
- Same question produces different truth values across runs (high variance).

Standard recovery:

1. Reformulate premises (fix term order, copula, granularity).
2. Switch engine if the pattern matches another.
3. Inject external grounding — see [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md).

---

## See also

- [reference-lib-nal.md](./reference-lib-nal.md) — NAL rules and truth formulas.
- [reference-lib-pln.md](./reference-lib-pln.md) — PLN rules.
- [reference-lib-ona.md](./reference-lib-ona.md) — ONA temporal reasoning (experimental, not installed).
- [reference-failure-modes.md](./reference-failure-modes.md) — documented failure modes and mitigations.
