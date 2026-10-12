# Reference — Communication Tools

`send` and `receive` are defined in `src/channels.metta`, `websearch` in `src/skills.metta`. The `commchannel` configuration parameter selects the channel that `send` and `receive` use (see [reference-configuration.md](./reference-configuration.md)).

---

## `send`

### Signature
```metta
(send "message")
```

### Purpose
Send a message to the currently active communication channel (IRC, Telegram, Slack, Mattermost, or WebSocket).

### Parameters
- `message` — the text to send. Newlines are replaced with `\n` before transmission.

### Returns
No meaningful return value. Used for its side effect.

### Examples
```metta
(send "Hello — deployment completed at 10:02.")
```

### Notes / Limits
- **Deduplication:** `send` silently drops the call if `message` is identical to the previous one (`&lastsend` state). Change the text to send a near-duplicate.
- Channel selection is set at `initChannels` time via `commchannel`.

---

## `receive`

### Signature
```metta
(receive)
```

### Purpose
Return the latest message received on the active channel since the previous call. `receive` is not a tool. It is not in the tool list or among the names the parser accepts, so the LLM cannot call it as a tool, only from inside a `metta` expression. `src/loop.metta` calls it once per loop iteration.

### Parameters
None.

### Returns
A string. Empty if nothing new has arrived.

### Examples
The loop calls `receive` itself:

```metta
(let $msgrcv (string-safe (repr (receive))) ...)
```

### Notes / Limits
- Delegates to `channels.commChannelReceive` in `src/channels.py`, which calls `receive` on the channel that the `commchannel` parameter selects (see [reference-plugin-api.md](./reference-plugin-api.md#communication-channel-integration)). The built-in channels implement it with their module's `getLastMessage`, for example `irc.getLastMessage`.
- The loop treats an unchanged message as "no new input" via the `&prevmsg` state.

---

## `websearch`

### Signature
```metta
(websearch "query")
```

### Purpose
Perform a web search through the `src/websearch.py` adapter.

### Parameters
- `query` — the search string.

### Returns
A string of search results suitable for feeding back into the prompt.

### Examples
```metta
(websearch "MeTTa AtomSpace tutorial")
```

### Notes / Limits
- Result format depends on the backend used by `websearch.search`.
