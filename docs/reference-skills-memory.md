# Reference — Memory Skills

Defined in `src/memory.metta` and catalogued in `src/skills.metta`.

All four skills accept quoted string arguments. Variables are not permitted in LLM-generated calls.

---

## `remember`

### Signature
```metta
(remember "string")
```

### Purpose
Store a string in long-term embedding memory as the triplet `(timestamp, atom, embedding)`.

### Parameters
- `string` — the text to remember. Use short, self-contained phrases for best recall.

### Returns
The result of the ChromaDB write (internally). The agent treats a successful call as an effectful step.

### Examples
```metta
(remember "user prefers dark mode")
(remember "to deploy: run make release then docker push")
```

### Notes / Limits
- Text is passed through `string-safe` before embedding, which escapes newlines, quotes, and apostrophes.
- Embedding provider is selected by `embeddingprovider`, the model by `embeddingModel`.
- Nothing deduplicates automatically — repeated `remember` calls store multiple items.

---

## `query`

### Signature
```metta
(query "string")
```

### Purpose
Return up to `maxRecallItems` memory entries whose embeddings are closest to the embedding of `string`.

### Parameters
- `string` — a short descriptive phrase. Over-long queries dilute similarity scores.

### Returns
A list-shaped result containing the nearest memory items.

### Examples
```metta
(query "deployment steps")
(query "user preferences")
```

### Notes / Limits
- `maxRecallItems` default is 20 (see `initMemory`).
- Similarity is purely embedding-based; exact string match is not guaranteed.

---

## `episodes`

### Signature
```metta
(episodes "YYYY-MM-DD HH:MM:SS")
```

### Purpose
Return bounded history around the given timestamp, including original audit
entries and pruned frame events. Without an exact match, use the nearest timestamp.

### Parameters
- `timestamp` — must match the format produced by `get_time_as_string`.
  Pass back the supplied `timestamp#offset` cursor unchanged to continue a result.

### Returns
Numbered history text from `memory/history.metta`. `MORE HISTORY` supplies the
next `episodes` call when additional matching context remains.

### Examples
```metta
(episodes "2026-04-15 14:30:00")
; Follow the exact cursor returned by MORE HISTORY, for example:
(episodes "2026-04-15 14:30:00#1500")
```

### Notes / Limits
- Implemented by `helper.around_time`.
- Pages contain at most `2 * maxEpisodeRecallLines + 1` history lines and fit
  within `maxFeedback`, including tool wrapping. Long lines can span pages.
- The cursor is a character offset into the selected history text. Rewriting
  history or changing the recall radius invalidates it.
- Useful for answering questions like "what was I doing around X?"

---

## `pin`

### Signature
```metta
(pin "string")
```

### Purpose
Append a working-memory note to the episodic trace so the next turn can see it in `HISTORY`.

### Parameters
- `string` — the note. Typical uses: intermediate results, plans for the next turn, checklists.

### Returns
Success / failure of the append.

### Examples
```metta
(pin "candidates: A) Launch Day B) We're Live C) Out Now")
(pin "next step: pick best candidate and send")
```

### Notes / Limits
- `pin` is not semantically indexed — it only influences the next few turns through the rolling `HISTORY` window (`maxHistory` characters).
- For anything you want to recall days later, use `remember` instead.
