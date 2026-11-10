# Reference — `lib_pln.metta`

Probabilistic Logic Networks (PLN) — a higher-order probabilistic reasoning framework compatible with the AtomSpace. PLN is the engine to reach for when a problem is best expressed as **property-based categorical inference** rather than the asymmetric inheritance chains NAL specializes in.

---

## Relations

| Atom | Meaning |
|---|---|
| `Inheritance` | Probabilistic "is-a" relation. |
| `Implication` | Conditional probability — `(Implication P Q)` ≈ `P(Q | P)`. |
| `IntSet` | Intensional set — members share a property. |

Truth values share NAL's `(stv frequency confidence)` format, interpreted probabilistically.

---

## The `|~` operator

`|~` applies PLN rules. Omega's current deployment supports a useful subset; the rest are left to NAL or future work.

---

## Rule catalogue — confirmed

### Modus Ponens

**Primary PLN inference.**

**Shape:** `(Implication P Q)` and `P` ⊢ `Q`.

**Truth function:**

```
f = f₁ × f₂
c = f₁ × f₂ × c₁ × c₂
```

Same shape as NAL deduction — confidence decays linearly.

### Abduction (on Inheritance premises)

**Shape:** supports abduction over `Inheritance` premises.

**Empirical check:** `(Inheritance bird flyer)` + `(Inheritance robin flyer)` ⊢ `(Inheritance robin bird) (stv 0.767 0.422)`.

Note the output confidence `0.422` — comparable to NAL's abduction ceiling (~0.45). Abduction produces *hypotheses worth testing*, not *actionable conclusions*.

### Revision

**Shape:** two beliefs about the same statement.

**Truth function:** identical to NAL revision.

```
w = c / (1 - c)
w_total = Σ w_i
c_out = w_total / (w_total + 1)
f_out = weighted average of f_i by w_i
```

Use revision to merge evidence across PLN conclusions, across NAL conclusions, or across both — the math is the same.

---

## What does NOT work in PLN (current deployment)

| Pattern | Status |
|---|---|
| **PLN abduction** (general case beyond confirmed shapes) | Returns empty in practice despite theoretical support. |
| **Backward inference** | Forward inference only. |

If PLN returns empty, reformulate as NAL or try a different premise shape. See recovery guidance in [reference-orchestration.md](./reference-orchestration.md).

---

## Invocation

Through the `(metta ...)` tool. Variables use `$1`, `$2`, …

### Modus Ponens example

```metta
(metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))
                         (Inheritance $1 Bird)) (stv 1.0 0.9))
           ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9))))
```

Conclusion: `(Inheritance Pingu Bird)` with a derived `(stv ...)`.

### Abduction example

```metta
(metta (|~ ((Inheritance bird flyer)  (stv 1.0 0.9))
           ((Inheritance robin flyer) (stv 1.0 0.9))))
```

Conclusion: `(Inheritance robin bird) (stv 0.767 0.422)`.

---

## NAL vs. PLN — which to use

| Situation | Engine |
|---|---|
| Asymmetric chain `A → B → C` | NAL `\|-` |
| Observed effect, seeking cause (simple) | NAL `\|-` abduction |
| Merging independent evidence | Either (identical formula) |
| Property-based categorical inference | PLN `\|~` |
| Higher-order structures (`Implication` over `Inheritance`) | PLN `\|~` |
| Real-time or temporal reasoning | Not served by a stock engine — ONA is the planned future target (see [reference-lib-ona.md](./reference-lib-ona.md), experimental, not installed). Current fallback: NAL with external temporal grounding. |

When in doubt, try NAL first; PLN shines on `Implication` over `Inheritance` chains.

---

## See also

- [reference-lib-nal.md](./reference-lib-nal.md) — sibling symbolic engine.
- [reference-lib-ona.md](./reference-lib-ona.md) — planned temporal engine (experimental, not installed).
- [reference-orchestration.md](./reference-orchestration.md) — engine selection.
- [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md) — worked examples.
