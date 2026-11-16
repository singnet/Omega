# Reference — Reasoning Tool

Defined in `src/skills.metta`. Backed by two reasoning engines in `lib_nal.metta` and `lib_pln.metta`.

---

## `metta`

### Signature
```metta
(metta sexpression)
```

### Purpose
Evaluate an arbitrary MeTTa s-expression in the agent's AtomSpace. Primary use is to invoke **NAL** (`|-`) or **PLN** (`|~`) inference from within the agent loop.

### Parameters
- `sexpression` — a MeTTa s-expression. Read by `sread`, evaluated by `eval`.

### Returns
Whatever the inner expression returns. For NAL/PLN calls, this is a conclusion atom paired with an `(stv frequency confidence)` truth value.

### Examples

**NAL — deduction:**
```metta
(metta (|- ((--> (× sam garfield) friend) (stv 1.0 0.9))
           ((--> garfield animal)         (stv 1.0 0.9))))
```

**NAL — implication with a variable (note `$1`):**
```metta
(metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))
           ((--> (× tiger elephant) eat)                            (stv 1.0 0.9))))
```

**NAL — revision** (same term, two sources): `|-` merges the evidence.

**PLN — forward chaining:**
```metta
(metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))
                         (Inheritance $1 Bird)) (stv 1.0 0.9))
           ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9))))
```

---

## Engine selection, stopping criteria, action thresholds

These are policy decisions, not part of the `metta` tool's API. See [reference-orchestration.md](./reference-orchestration.md) for the full tables and rationale (pattern → engine mapping, halt conditions, ACT / HYPOTHESIZE / IGNORE tiers).

---

## Notes / limits

- Independent variables are written `$1`, `$2`, …
- Negated knowledge uses `(stv 0.0 c)`.
- `metta` evaluates **any** MeTTa expression, not just reasoning calls. Malformed input reports errors through `&error` on the next turn.
- Confidence decays ~10% per deduction hop. Chains past 3 hops usually fall below the ACT threshold — see [tutorial-08-reliable-reasoning.md](./tutorial-08-reliable-reasoning.md).
- Premise formulation is the primary failure surface. Verify term order, copula, and granularity before trusting a conclusion. See [reference-failure-modes.md](./reference-failure-modes.md).

---

## See also

- [reference-lib-nal.md](./reference-lib-nal.md) — NAL rule catalogue.
- [reference-lib-pln.md](./reference-lib-pln.md) — PLN rule catalogue.
- [reference-lib-ona.md](./reference-lib-ona.md) — ONA temporal reasoning (experimental, not installed).
- [reference-orchestration.md](./reference-orchestration.md) — full orchestration policy.
- [tutorial-05-reasoning-with-nal-pln.md](./tutorial-05-reasoning-with-nal-pln.md) — worked examples.
