# Reference — Memory Tools

`remember`, `query`, and `episodes` are defined in `src/memory.metta`, `pin` in `src/skills.metta`. All four are registered with `add-skill` in `src/skills.metta`.

Each of the four tools takes one string parameter, which the model sets as a separate field of the tool call: `content` for `remember` and `query`, `timestamp` for `episodes`, `message` for `pin`.

---

## `remember`

### Signature
```metta
(remember "content")
```

### Purpose
Store a string in long-term embedding memory as the triplet `(timestamp, atom, embedding)`.

### Parameters
- `content` — the text to remember. Use short, self-contained phrases for best recall.

### Returns
The symbol `REMEMBER-SUCCESS`, returned after the ChromaDB write.

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
(query "content")
```

### Purpose
Return up to `maxRecallItems` memory entries whose embeddings are closest to the embedding of `content`.

### Parameters
- `content` — a short descriptive phrase. Over-long queries dilute similarity scores.

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
(pin "message")
```

### Purpose
Make a working-memory note visible to the next turn in `HISTORY`.

### Parameters
- `message` — the note. Typical uses: intermediate results, plans for the next turn, checklists.

### Returns
The symbol `PIN-SUCCESS`. `pin` stores nothing itself. The note reaches `HISTORY` because `addToHistory` appends the whole reply, the `pin` call included, to `memory/history.metta`.

### Examples
```metta
(pin "candidates: A) Launch Day B) We're Live C) Out Now")
(pin "next step: pick best candidate and send")
```

### Notes / Limits
- `pin` is not semantically indexed — it only influences the next few turns through the rolling `HISTORY` window (`maxHistory` characters).
- For anything you want to recall days later, use `remember` instead.
