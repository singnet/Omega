# Reference — `lib_nal.metta`

Non-Axiomatic Logic (NAL) — a logic of uncertain reasoning with explicit evidence-based truth values. NAL is the primary symbolic engine for Omega's inheritance and implication reasoning.

---

## Truth value format

Every NAL statement carries `(stv frequency confidence)`:

- `frequency` ∈ [0.0, 1.0] — how often the statement held among observed evidence.
- `confidence` ∈ [0.0, 1.0] — how much evidence supports that frequency.

**Negation** is `(stv 0.0 c)`.

`w2c` in the formulas below denotes the NAL evidence-weight-to-confidence mapping; it is the standard NAL formula.

---

## Core relations

| Relation | Meaning |
|---|---|
| `-->` | **Inheritance.** `(--> a b)` ≈ "`a` is a kind of `b`". Asymmetric. |
| `==>` | **Implication.** `(==> P Q)` ≈ "if `P` then `Q`". |
| `<->` | **Similarity.** `(<-> a b)` ≈ "`a` and `b` are similar". Symmetric in principle but see limits below. |
| `×` | **Product.** `(× sam garfield)` ≈ the ordered pair. |
| `[]` | **Property set.** `([] dangerous)` ≈ the set of dangerous things. |
| `IntSet` | **Intensional set** — members share a property (also used by PLN). |

---

## The `|-` operator

`|-` applies NAL inference. Omega selects the appropriate rule automatically based on premise shape.

---

## Rule catalogue

### Deduction — the workhorse

**Shape:** `(--> A B)` and `(--> B C)` ⊢ `(--> A C)`.

**Truth function:**

```
f = f₁ × f₂
c = f₁ × f₂ × c₁ × c₂
```

Deduction also emits the **exemplification** conclusion alongside the primary one (for `-->` only).

### Abduction

**Shape:** `(--> A B)` and `(--> A C)` ⊢ `(--> B C)` (seeking cause from effect).

**Truth function:**

```
f = f₂
c = w2c(f₁ × c₁ × c₂)
```

**Known limit:** practical **confidence ceiling at ~0.45**.

### Induction

**Shape:** `(--> A B)` and `(--> C B)` ⊢ `(--> A C)` (generalizing from multiple instances).

**Truth function (symmetric to abduction):**

```
f = f₁
c = w2c(f₂ × c₁ × c₂)
```

Two instances of the same generalization at `c = 0.42` revise to `c ≈ 0.59` — use revision to combine multiple instances.

### Revision — merging independent evidence

**Shape:** two beliefs about the same statement.

**Truth function:**

```
w = c / (1 - c)            per premise
w_total = Σ w_i
c_out = w_total / (w_total + 1)
f_out = weighted average of f_i by w_i
```

Produces strictly higher confidence when evidence agrees. When evidence disagrees, frequency drifts toward the middle while confidence grows — contradiction becomes mathematically visible.

**Empirical check points:**

- Three sources at `(stv 1.0 0.45)` revise to `(stv 1.0 0.647)`.
- Five sources at `(stv 1.0 0.45)` revise to `(stv 0.848 0.937)`.

### Exemplification

**Shape:** produced alongside deduction for `-->` premises.

**Truth function:**

```
f = 1.0
c = w2c(f₁ × f₂ × c₁ × c₂)
```

### Conditional deduction (modus ponens)

**Shape:** `(==> P Q)` and `P` ⊢ `Q`.

**Truth function:** same as deduction (`f = f₁ × f₂, c = f₁ × f₂ × c₁ × c₂`).

### Conditional syllogism (`==>` chaining)

Works with nested `-->` inside `==>`. Same deduction-style formula.

### Conditional abduction

**Shape:** `(==> P Q)` + observed `Q` ⊢ `P`.

Empirical output shape: `(stv 0.9 0.408)` on typical inputs — confidence under the abduction ceiling.

### Implication chaining

Two `==>` sharing a middle term. Works with nested `-->` inside `==>`.

### Multi-instance induction

Two instances each at `c ≈ 0.42` revise to `c ≈ 0.59` — verified empirically. Combine induction with revision to build up evidence.

### Higher-order via proxy

Use atomic labels for rules as subjects. Pattern confirmed: `birdRule --> reliable --> trustworthy` compiles and reasons.

### Negation

Via `(stv 0.0 c)`. Propagates through deduction as expected.

### Similarity (`<->`)

Works via NAL-2 rules (cycle 2260). **Asymmetric in practice** — only matches when the shared term occupies a specific argument position. Do not assume full symmetry.

### Analogy

Works via the NAL-2 analogy rule (cycle 2260). Same positional asymmetry as similarity.

---

## Rules NOT to rely on

| Pattern | Status |
|---|---|
| **NAL-3 decomposition** | Non-functional — compounds are fully opaque. |
| **Implication chaining** (automatic transitive) | Two `==>` sharing a middle term do *not* automatically chain. Walk the chain manually. |
| **Contrapositive** | Partial. Negated consequent + conditional yields the antecedent but with `c = 0.0`. |
| **Conjunctive antecedents** | Unsupported — `A AND B ==> C` cannot be directly represented. |
| **Similarity / analogy (full symmetry)** | Argument-position-sensitive despite theoretical symmetry. |

---

## Invocation

NAL is reached through the `(metta ...)` tool. Variables use `$1`, `$2`, …

### Deduction

```metta
(metta (|- ((--> sam human)         (stv 1.0 0.9))
           ((--> human mortal)      (stv 1.0 0.9))))
```

### Implication with variable unification

```metta
(metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))
           ((--> (× tiger elephant) eat)                            (stv 1.0 0.9))))
```

### Revision on shared term

```metta
(metta (|- ((--> wolf animal) (stv 1.0 0.45))
           ((--> wolf animal) (stv 1.0 0.45))))
```

Output: `(--> wolf animal) (stv 1.0 ~0.62)`.

---

## Multi-hop degradation — in numbers

Starting each premise at `c = 0.9`:

| Hop | Output `c` |
|---|---|
| 1 | 0.81 |
| 2 | 0.73 |
| 3 | < 0.5 |
| 4 | ~0.25 |

This is a **feature, not a bug** — the math honestly represents diminishing certainty. Practical implication: keep chains to 2–3 hops, insert revision to restore confidence.

---

## See also

- [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md) — worked examples for each rule.
- [reference-lib-pln.md](./reference-lib-pln.md) — the probabilistic counterpart.
- [reference-lib-ona.md](./reference-lib-ona.md) — planned real-time / temporal engine (experimental, not installed).
- [reference-orchestration.md](./reference-orchestration.md) — when to pick NAL vs. PLN.
- [reference-failure-modes.md](./reference-failure-modes.md) — known failure rates for NAL-using chains.
