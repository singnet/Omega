# Internals — Skill Dispatch

This page traces what happens between an LLM response landing in the loop and a skill actually running.

## Expected LLM output shape

The prompt demands a tuple of up to 5 skill s-expressions:

```
((skillName1 "arg1") (skillName2 "arg2") ...)
```

With the hard rules that every argument is a quoted string and no MeTTa variables may appear.

## Step-by-step dispatch

From `src/loop.metta`:

1. **Raw LLM string** → `$respstr`.
2. **Parse** — `catch (sread $respstr)` → `$resp`. On parse failure, `HandleError` records error.
3. **Fan out** — `(superpose $resp)` produces one binding per tool call in the tuple.
4. **Evaluate each** — `(catch (eval $s))`. On success, the result is normalized via `helper.normalize_string`. On failure, `HandleError` records error. 
5. **Feedback** - `(llmToolCallResponseMessage role "tool" callid $callid content (last_chars $result (maxFeedback)))`. Add tool call result to the request.
6. **Aggregate** — all results are collapsed into `$sexpr`.
7. **History** — `$sexpr` is stored in the history.

## How `eval $s` resolves to a skill

MeTTa evaluates the head of the expression against the AtomSpace. Skills are defined as plain equations:

```metta
(= (remember $str) ...)
(= (shell $cmd)    ...)
(= (metta $expr)   ...)
```

So `(shell "ls")` matches the equation for `shell` and runs its body.

Bridges enter via:

- `(py-call (module.function args))` for Python.
- `(translatePredicate (predicate ...))` and `!(import_prolog_function name)` for Prolog.

## Errors propagate via `&error`

`HandleError` appends to the `&error` state. When `addToHistory` runs, if `&error` is non-empty it is concatenated as `ERROR_FEEDBACK:`. On the next turn the agent sees the error and has the opportunity to correct course.

## See also

- [reference-internals-loop.md](./reference-internals-loop.md) — the full turn structure.
- [reference-internals-extension-points.md](./reference-internals-extension-points.md) — where to hook in new skills.
- [tutorial-03-writing-a-custom-skill.md](./tutorial-03-writing-a-custom-skill.md) — end-to-end skill addition.
