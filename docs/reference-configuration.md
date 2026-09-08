# Reference — Configuration

Every tunable in Omega is declared as `(= (name) (empty))` and later bound by a `configure` call inside an `init*` function. The `configure` helper in `src/utils.metta` is:

```metta
(= (configure $name $default)
   (let $value (argk $name $default)
        (add-atom &self (= ($name) $value))))
```

This reads a command-line override via `argk` (`name=value` on the MeTTa command line) if present, otherwise falls back to the default.

## Loop (`src/loop.metta`, `initLoop`)

| Parameter | Default | Meaning |
|---|---|---|
| `maxNewInputLoops` | 50 | How many turns the agent keeps running after a new human message before idling. |
| `maxWakeLoops` | 1 | Extra turns granted on each scheduled wake-up. |
| `sleepInterval` | 1 (seconds) | Delay between loop iterations. |
| `LLM` | `gpt-5.4` | Model identifier passed to the provider. |
| `provider` | `Anthropic` | LLM provider — `Anthropic`, `OpenAI`, `ASICloud`, or `ASIOne`. |
| `maxOutputToken` | 6000 | Output cap passed to the provider. |
| `reasoningMode` | `medium` | Reasoning-effort hint passed to the provider. |
| `wakeupInterval` | 600 (seconds) | How long idle before the next scheduled wake-up. |

## Memory (`src/memory.metta`, `initMemory`)

| Parameter | Default | Meaning |
|---|---|---|
| `maxFeedback` | 50000 (chars) | Ceiling on `LAST_SKILL_USE_RESULTS` text fed back into the prompt. |
| `maxRecallItems` | 20 | Items returned by `query`. |
| `maxEpisodeRecallLines` | 20 | Lines returned by `episodes`. |
| `maxHistory` | 30000 (chars) | Tail of `memory/history.metta` included in the prompt. |
| `memoryDirectory` | `./repos/Omega/memory` | Directory containing persistent memory files such as `history.metta`. |
| `chromaDbPath` | `./chroma_db` | ChromaDB persistence directory used for memory backup and restore. |
| `embeddingprovider` | `Local` | `Local` (Python-side model), or the id of a provider that serves an OpenAI-compatible `/embeddings` endpoint — `OpenAI` and `ASICloud` are known to. The gateway supplies that provider's key. |
| `embeddingModel` | `text-embedding-3-large` | Model asked of a non-`Local` `embeddingprovider`. |

## Channels (`src/channels.metta`, `initChannels`)

| Parameter | Default | Meaning |
|---|---|---|
| `commchannel` | `irc` | Active channel — `irc`, `telegram`, `slack`, `mattermost`, or `websocket`. |
| `IRC_channel` | `##omega` | IRC channel to join. |
| `IRC_server` | `irc.quakenet.org` | IRC server hostname. |
| `IRC_port` | 6667 | IRC port. |
| `IRC_user` | `omega` | IRC nickname. |
| `TG_CHAT_ID` | *(empty)* | Legacy single-chat bootstrap/fallback, primarily for authentication-disabled deployments. With authentication enabled, the authenticated owner's DM becomes the proactive-message default. |
| `TG_ALLOWED_CHAT_IDS` | *(empty)* | Optional comma-separated initial allowed-chat set. The authenticated owner can add groups with `/bind` and remove them with `/unbind`; those changes are persisted in `memory/.channel/authenticated-group.json`, not written back to YAML. |
| `TG_POLL_TIMEOUT` | 20 | Telegram long-poll timeout in seconds. |
| `SL_CHANNEL_ID` | *(empty — auto-bind supported)* | Optional Slack channel ID where Omega reads/writes messages. Leave empty to auto-bind on first valid inbound auth/message. |
| `SL_POLL_INTERVAL` | 60 | Slack poll interval in seconds (minimum effective value is 60). |
| `MM_URL` | `https://chat.singularitynet.io` | Mattermost base URL. |
| `MM_CHANNEL_ID` | `8fjrmabjx7gupy7e5kjznpt5qh` | Target channel ID. |
| `WS_URL` | *(empty — set at runtime)* | WebSocket endpoint URL (`ws://` or `wss://`). Required when `commchannel=websocket`. |
| `WS_TOKEN` | *(empty — optional)* | Bearer token sent as `Authorization: Bearer <token>`. Leave empty for an unauthenticated endpoint. |

| Environment variable | Meaning |
|---|---|
| `TG_BOT_TOKEN` | Telegram bot token (from BotFather). |
| `OMEGA_AUTH_SECRET` | Enables the one-time owner-authentication handshake when non-empty. The owner sends `auth <secret>` in a private Telegram DM. |
| `MM_BOT_TOKEN` | Bot auth token. |
| `SL_BOT_TOKEN` | Slack bot token (`xoxb-...`). |

## Command-line overrides

Any `configure`d parameter can be overridden at startup:

```bash
metta run.metta provider=Anthropic LLM=claude-opus-4-6 commchannel=mattermost
```

Configuration values are resolved in this order: command-line `key=value`,
`OMEGA_<KEY>` environment variable, `config/config.yaml`, then the caller's
default. `TG_BOT_TOKEN` and `OMEGA_AUTH_SECRET` are read directly from the
environment and must be placed before the `metta`/`petta` command.

Telegram example:

```bash
TG_BOT_TOKEN=... OMEGA_AUTH_SECRET=... \
  metta run.metta commchannel=telegram
```

Slack example:

```bash
SL_BOT_TOKEN=xoxb-... metta run.metta commchannel=slack SL_CHANNEL_ID=C0123456789
```

WebSocket example:

```bash
metta run.metta commchannel=websocket WS_URL=wss://chat.example.com/agent WS_TOKEN=...
```

The `argk` helper parses `key=value` pairs from `argv`.
