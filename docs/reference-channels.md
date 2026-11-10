# Reference — Channels

Channels are the I/O surface the agent uses to talk to the outside world. Adapters live in `channels/`; MeTTa-side dispatch lives in `src/channels.metta`.

## The adapter contract

Each adapter exposes:

| Function | Purpose |
|---|---|
| `start_<name>(...)` | Called once from `initChannels`. Opens sockets / spawns listener threads as needed. |
| `getLastMessage()` | Returns the next unread inbound message as a string. Returns `""` if none. |
| `send_message(str)` | Posts an outbound message. |

The MeTTa side reads `commchannel` and branches:

```metta
(= (receive)
   (if (== (commchannel) websocket)
       (py-call (wschat.getLastMessage))
       (if (== (commchannel) irc)
           (py-call (irc.getLastMessage))
           (if (== (commchannel) telegram)
               (py-call (telegram.getLastMessage))
               (if (== (commchannel) slack)
                   (py-call (slack.getLastMessage))
                   (if (== (commchannel) mattermost)
                       (py-call (mattermost.getLastMessage))
                       (py-call (mock.getLastMessage))))))))
```

The final branch falls through to `channels/mock.py`, the in-process test channel used when no real channel is selected.

## `channels/irc.py`

IRC adapter with simple one-time-secret authentication.

- `start_irc(channel, server, port, user)` — connect and join.
- Inbound traffic is filtered to the first user who types `auth <one-time-secret>`. All other speakers are ignored.
- Uses QuakeNet (`irc.quakenet.org`) by default.

## `channels/mattermost.py`

Mattermost adapter using a bot token.

- `start_mattermost(url, channel_id)` — connect to a Mattermost instance.
- Requires `MM_BOT_TOKEN` environment variable.

## `channels/telegram.py`

Telegram adapter using Bot API long polling.

- `start_telegram(chat_id, allowed_chat_ids, poll_timeout)` — validates saved authorization state and starts the poll loop.
- With authentication enabled, the owner authenticates with `auth <secret>` in a private DM. That DM becomes the default destination for startup, heartbeat, and other proactive messages and is restored from persisted owner state after restart.
- The owner uses `/bind` in a group to add its chat ID to the runtime and persisted allowed-group sets. `/unbind` removes the current group; `/unbind <group_id>` performs the same operation from the owner's DM. Targeted forms such as `/bind@BotName` and `/unbind@BotName` are supported.
- `TG_ALLOWED_CHAT_IDS` supplies initial operator-configured chat IDs. Runtime `/bind` additions and `/unbind` removals are persisted in `memory/.channel/authenticated-group.json`; the YAML file itself is never rewritten.
- Each inbound message is delivered to the agent as `[chat_id] [message_id] message`. Dequeueing does not depend on the model producing or successfully delivering a reply, so a no-response turn cannot freeze later inbound messages.
- Outbound replies use the same `[chat_id] [message_id] message` envelope. An empty target falls back to the owner DM, and an empty message ID sends without Telegram reply metadata. Legacy plain outbound text also uses the owner-DM fallback.
- Explicit LLM-generated targets are accepted only for the owner DM or a currently authorized group. Group chat IDs may be negative.
- Outbound messages are split into Telegram-safe chunks and retained with their destination and reply ID for retry after transient delivery failures.
- When `commchannel=telegram`, startup registers the routing instructions from `memory/tg_prompt.txt` through `add-prompt-extension`. Other channels do not receive this prompt section.

## `channels/slack.py`

Slack adapter using Slack Web API polling.

- `start_slack(channel_id, poll_interval)` — starts a poll loop.
- `SL_CHANNEL_ID` is optional.
- The bot user must already be invited to the target channel.
- If `SL_CHANNEL_ID` is empty, the adapter auto-binds to the first channel where auth succeeds.
- Adapter respects Slack `Retry-After` backoff on HTTP 429 and enforces a minimum 60s poll interval.
- Uses the same one-time `auth <secret>` ownership gate as the other adapters.

## `channels/wschat.py`

Minimal JSON chat adapter over a WebSocket connection. Selected with `commchannel=websocket` — the Python module is `wschat`, exposing `start_websocket` / `stop_websocket` alongside the usual `getLastMessage` / `send_message`.

- `start_websocket(ws_url, ws_token)` — connect and spawn the listener thread. URL and optional token are read from `WS_URL` / `WS_TOKEN`, or passed directly. `WS_URL` is required when `commchannel=websocket`; if it is missing, Omega still starts, the adapter logs that the WebSocket channel is disabled, and the process continues without an active WebSocket connection.
- `stop_websocket()` — stop the listener thread and close the socket.
- Requires the `websockets` Python package.
- When `WS_TOKEN` is set it is sent as an `Authorization: Bearer <token>` header. Unlike the IRC/Telegram/Slack adapters there is no one-time `auth <secret>` gate — trust is established by the endpoint URL and bearer token.
- Supports immediate `/memory-export history|ltm|both` commands when memory export is enabled and `WS_TOKEN` is configured. The export handler uses a SHA-256-derived connection principal and never exposes the bearer token. Protect the endpoint with `wss://` and server-side access controls because WebSocket does not have the per-user ownership gate used by the other channels.
- Reconnects automatically with exponential backoff (1s → 30s, ±20% jitter) and is safe to start once at process startup.

### Frame protocol

All frames are UTF-8 JSON objects with a `type` field; unknown types are logged and ignored.

| Direction | `type` | Payload |
|---|---|---|
| server → client | `user_message` | `{seq, text}` — a new inbound message. `seq` is a server-assigned, monotonically increasing integer used for ordering and dedup. |
| server → client | `ack` | `{seq, client_seq}` — acknowledges a previously sent `agent_message`. Informational; logged only. |
| server → client | `error` | `{code, message}` — server-side error. Logged; the connection is left open. |
| client → server | `agent_message` | `{client_seq, text}` — an outbound message. `client_seq` is a client-generated UUID idempotency key so the server can dedupe retries after reconnect. |
| client → server | `resume` | `{last_seen_seq}` — sent on every (re)connect so the server can replay any `user_message` with `seq > last_seen_seq` (null on the first connect). |

### Delivery semantics

- Inbound messages buffer in a bounded inbox (256 entries). `getLastMessage` drains it, joins pending texts with `" | "`, and advances `last_seen_seq`.
- Outbound messages produced while disconnected queue in a bounded outbox (100 entries) and flush after the next successful connect, before any new inbound traffic is processed.
- Duplicate `user_message` frames (`seq <= last_seen_seq`, or already buffered) are dropped, so server replays after `resume` are idempotent.

## `src/websearch.py`

Not a communication channel in the `send`/`receive` sense. This is the backend for the `websearch` tool and exposes `search(query, max_results=10)`.

## Adding a new channel

See [tutorial-04-adding-a-channel.md](./tutorial-04-adding-a-channel.md).

## Related reference

- [reference-tools-communication.md](./reference-tools-communication.md) — the MeTTa surface (`send`, `receive`, `websearch`).
- [reference-configuration.md](./reference-configuration.md) — channel parameters.
