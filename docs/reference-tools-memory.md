# Reference — Memory Tools

`remember`, `query`, and `episodes` are defined in `src/memory.metta`, `pin` in `src/skills.metta`. All four are listed in `getStaticSkills` in `src/skills.metta`.

Each of the four tools takes one string argument. The LLM writes it after the tool name without quotes, for example `remember user prefers dark mode`, and the parser turns the line into `(remember "user prefers dark mode")`. The prompt asks the LLM not to use variables. A `$x` in the line arrives as plain text, unless the argument is a single line that starts and ends with a double quote, as in `remember "a" $x "b"`. The parser keeps such an argument as written, and `sread` then reads the `$x` outside the quotes as a variable.

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
Return the line of the episodic trace whose timestamp is closest to the given one, with up to `maxEpisodeRecallLines` lines before and after it (at most 41 lines with the default of 20).

### Parameters
- `timestamp` — must match the format produced by `get_time_as_string`.

### Returns
A block of lines from `memory/history.metta`.

### Examples
```metta
(episodes "2026-04-15 14:30:00")
```

### Notes / Limits
- Implemented by `helper.around_time`.
- Useful for answering questions like "what was I doing around X?"

---

## `pin`

### Signature
```metta
(pin "string")
```

### Purpose
Make a working-memory note visible to the next turn in `HISTORY`.

### Parameters
- `string` — the note. Typical uses: intermediate results, plans for the next turn, checklists.

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
