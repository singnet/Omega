# Reference — Failure Modes and Mitigations

Omega has been exercised for thousands of continuous cycles on the reference deployment (the **Max Botnick** agent — see [Empirical context](#empirical-context) below). The failures in this page are observed and quantified, not hypothetical.

A hybrid LLM + formal-logic system can fail in at least three places: premise formulation, confidence propagation, and orchestration. This page catalogues each category, cites measured rates where available, and points to the mitigations.

---

## 1. Premise formulation errors

The LLM converts natural language into atoms. This is where the most common — and highest-impact — errors occur.

| Error | Observed rate | Example |
|---|---|---|
| **Asymmetric relationship swap** | up to **16.6%** on swap-sensitive relations | writes `(--> A B)` when the domain fact is `(--> B A)` |
| **Granularity mismatch** | qualitative | collapses distinct concepts into a single atom |
| **Copula selection error** | qualitative | uses `-->` (inheritance) when `<->` (similarity) or `==>` (implication) is correct |
| **LLM factual-claim accuracy** | **~55%** against verified sources | LLM-provided facts are wrong nearly half the time |
| **Confidence overestimation** | **~15 percentage points** | LLM-assigned `c = 0.70` averages ~0.55 against ground truth |

> The symbolic engine **cannot detect these errors** — they look well-formed to it. Premise formulation is the primary failure surface.

**Mitigations:**

- External grounding — see [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md).
- Discount LLM-originated confidence by 10–15 percentage points before feeding into the chain.
- Systematic checks for term order, copula, and granularity at the point of formulation.

---

## 2. Confidence-propagation errors

Once premises are wrong, the formal engine **amplifies** the error rather than absorbing it.

### The GIGO amplification problem

> The formal engine does not merely pass through garbage — it **amplifies** it by lending mathematical authority to conclusions derived from flawed premises. A conclusion stamped with `(stv 0.81 0.73)` looks rigorous regardless of whether the input premises were accurate.

The most dangerous variant is **confabulation under mathematical cover** — the LLM fabricates a plausible-sounding premise, the engine runs deduction on it, and the output carries a seemingly authoritative truth value.

### Confidence decay is linear, not forgiving

Deduction truth formula:

```
c_out = f₁ × f₂ × c₁ × c₂
```

No threshold effects. No safety margin where small input errors wash out. Starting at `c = 0.9` per premise, a four-step chain degrades to roughly `c ≈ 0.25`.

| Hop | Approx. confidence (starting c=0.9) |
|---|---|
| 1 | 0.81 |
| 2 | 0.73 |
| 3 | **< 0.5** (below `c_actionable`) |
| 4 | ~0.25 |

**Mitigations:**

- Keep chains to 2–3 hops.
- Inject a **revision** step with independent evidence to restore confidence.
- Enforce the action thresholds (ACT / HYPOTHESIZE / IGNORE) — see [reference-orchestration.md](./reference-orchestration.md).

### Abduction confidence ceiling

Abduction (`f = f₂, c = w2c(f₁ × c₁ × c₂)`) has a practical **confidence ceiling at ~0.45**. Do not expect abduced conclusions to clear the ACT threshold on their own — follow up with revision or external verification.

---

## 3. Missing or partial inference patterns

Some rules are implemented but behave in unexpected ways. Know these before writing premises.

| Pattern | Status |
|---|---|
| **NAL-3 decomposition** | Not functional — compounds are fully opaque. |
| **Implication chaining** | Two `==>` premises sharing a middle term do **not** automatically produce a transitive conclusion. Chain manually. |
| **Contrapositive** | Partial — negated consequent plus conditional yields the antecedent but with `c = 0.0`. |
| **Analogy (`<->`)** | Asymmetric — only matches when the shared term occupies specific argument position. |
| **Conjunctive antecedents** | Unsupported — `A AND B ==> C` cannot be directly represented. |
| **PLN abduction** | Theoretically supported but returns empty in practice. |
| **PLN** generally | Forward inference only in the current deployment. |

---

## 4. Orchestration failures

Measured across 4,500+ operational cycles, the top error categories are:

1. **Commands not executed** (`NOTHING_WAS_DONE`) — the LLM produced output that was not a valid skill tuple.
2. **Multi-command parsing failures.**

These are **the most frequent failure mode in the entire system**, not occasional glitches.

### Context-switching corruption

When a new human message arrives during autonomous work, the LLM attempts to simultaneously acknowledge and maintain task state. The error rate during these **social-response cycles is measurably higher** than during purely autonomous cycles.

### Bandwidth constraint

The 5-command-per-cycle limit means complex reasoning chains require 10–20 cycles. Budget accordingly.

### State fragility

Working memory depends on:

- `pin` — volatile, single-slot, overwritten each cycle;
- `/tmp` files — lost on restart.

Anything you need to keep across sessions must go through `remember`.

---

## 5. Variance and confirmation bias

**Independent runs on ambiguous claims** show up to **3× greater assignment variance** compared to unambiguous claims. Example measurement: `ostrich --> dangerous` assigned `(stv 0.567 ± 0.103)` across runs.

**Post-hoc rationalization** of a conclusion produces more extreme values (frequency lowered by ~50%) with artificially inflated confidence (+14%) compared to pre-committed values. This is why **reasoning must be in-loop from the start, not retroactive**.

---

## 6. Self-improvement limitations

Attempts by the agent to patch its own behavior have produced mixed results:

- A confabulation mitigation script was created but not invoked during actual confabulation episodes.
- A self-model query tool was built with incorrect file paths and crashed on use.
- A MeTTa analogy patch was attempted but returned `True` instead of derived conclusions.

Take self-authored improvements seriously as signals, but validate externally before relying on them.

---

## 7. The defense stack (summary)

Four layers designed to hold the system together despite the above. Each is described in full in [reference-orchestration.md](./reference-orchestration.md).

1. **Novelty modulation** — `c_new = c × (1 - novelty)` for new claims.
2. **Action thresholds** — ACT / HYPOTHESIZE / IGNORE tiers gate downstream action.
3. **Attention budgeting** — priority queue by NAL expectation, with hard step limits.
4. **Adversarial premise testing** — regression suite covering confident lies, direct contradictions, and gradual poisoning. The stack correctly downgrades adversarial inputs in all tested cases.

---

## 8. Practical checklist

Before trusting a conclusion:

- [ ] Were premises externally grounded? If not, reduce confidence.
- [ ] Was the chain ≤ 3 hops, or was revision used to restore confidence?
- [ ] Did the conclusion clear the ACT threshold (`f ≥ 0.6, c ≥ 0.5`)?
- [ ] Are premises stored in memory with provenance?
- [ ] On a re-run, does the answer reproduce (low variance)?

---

## Empirical context

The numbers on this page come from operational experience with **Max Botnick**, an Omega-hosted agent used by the project maintainers for internal reasoning experiments. Max ran **3,100+ continuous cycles minimum** (4,500+ cycles with full error instrumentation) and self-authored the whitepaper from which this documentation draws. The measurements are therefore Omega-on-Omega evaluations, with all the caveats that implies — they are indicative of the framework under realistic workloads but not a formal benchmark.

## See also

- [introduction.md#the-hybrid-thesis](./introduction.md#the-hybrid-thesis) — why the hybrid architecture fails this way.
- [reference-orchestration.md](./reference-orchestration.md) — the defense stack and thresholds in detail.
- [tutorial-07-grounded-reasoning.md](./tutorial-07-grounded-reasoning.md) — external grounding walkthrough.
- [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md) — strategic advice for getting reliable outputs.
