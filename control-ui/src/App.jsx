import { useCallback, useEffect, useMemo, useState } from "react";

const CHANNELS = [
  { id: "irc", name: "IRC", note: "Simple, open chat" },
  { id: "telegram", name: "Telegram", note: "Talk to your bot" },
  { id: "slack", name: "Slack", note: "Connect a workspace" },
  { id: "websocket", name: "WebSocket", note: "Bring your own client" },
  { id: "mattermost", name: "Mattermost", note: "Self-hosted teams" },
];

const PROVIDERS = [
  { id: "Anthropic", name: "Anthropic", model: "claude-opus-4-8", mark: "A" },
  { id: "OpenAI", name: "OpenAI", model: "gpt-5.5", mark: "O" },
  { id: "ASICloud", name: "ASI Cloud", model: "minimax/minimax-m3", mark: "AC" },
  { id: "ASIOne", name: "ASI:One", model: "asi1-ultra", mark: "A1" },
  { id: "OpenRouter", name: "OpenRouter", model: "z-ai/glm-5.2", mark: "OR" },
  { id: "OpenAIAPI", name: "Custom API", model: "qwen3.5:9b", mark: "<>" },
];

function generateAuthCode() {
  const values = new Uint32Array(1);
  window.crypto.getRandomValues(values);
  return String(100000 + (values[0] % 900000));
}

const initialForm = {
  channel: "irc",
  provider: "Anthropic",
  model: "claude-opus-4-8",
  apiKey: "",
  authSecret: generateAuthCode(),
  reasoningMode: "medium",
  maxOutputToken: 6000,
  importKnowledge: false,
  openaiApiUrl: "http://host.docker.internal:11434/v1",
  ircChannel: "##omegaclaw",
  ircServer: "irc.quakenet.org",
  ircPort: 6667,
  ircUser: "omegaclaw",
  telegramBotToken: "",
  telegramChatId: "",
  slackBotToken: "",
  slackChannelId: "",
  websocketUrl: "",
  websocketToken: "",
  mattermostUrl: "https://chat.singularitynet.io",
  mattermostChannelId: "",
  mattermostBotToken: "",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.method === "POST" ? { "X-Omega-Control": "browser" } : {}),
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || "The request failed.");
  }
  return body;
}

function Icon({ name }) {
  const paths = {
    channel: <><path d="M5 6.5h14v9H9l-4 3v-12Z" /><path d="M9 10h6M9 13h4" /></>,
    brain: <><path d="M9.5 5.2A3.2 3.2 0 0 0 4.8 8a3.3 3.3 0 0 0 .7 6.3A3.5 3.5 0 0 0 12 16V8" /><path d="M14.5 5.2A3.2 3.2 0 0 1 19.2 8a3.3 3.3 0 0 1-.7 6.3A3.5 3.5 0 0 1 12 16M8 9.5h4m4-1.5v3.5" /></>,
    play: <path d="m9 7 8 5-8 5V7Z" />,
    stop: <rect x="7.5" y="7.5" width="9" height="9" rx="1.5" />,
    key: <><circle cx="8.5" cy="11.5" r="3.2" /><path d="m11 9 6-6m-2 2 2 2m-4 0 2 2" /></>,
    refresh: <><path d="M19 7v5h-5" /><path d="M17.7 16A7 7 0 1 1 19 12" /></>,
    eye: <><path d="M3 12s3.2-5 9-5 9 5 9 5-3.2 5-9 5-9-5-9-5Z" /><circle cx="12" cy="12" r="2.2" /></>,
    eyeOff: <><path d="m4 4 16 16M9.8 7.2A8.8 8.8 0 0 1 12 7c5.8 0 9 5 9 5a14 14 0 0 1-2.1 2.6M14.1 14.2A3 3 0 0 1 9.8 10M6.2 8.1A14.8 14.8 0 0 0 3 12s3.2 5 9 5a9 9 0 0 0 2.2-.3" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    spark: <><path d="m12 3 1.3 4.1L17 9l-3.7 1.9L12 15l-1.3-4.1L7 9l3.7-1.9L12 3Z" /><path d="m18.5 15 .6 1.9 1.9.6-1.9.6-.6 1.9-.6-1.9-1.9-.6 1.9-.6.6-1.9Z" /></>,
  };
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function Field({ label, hint, children, wide = false }) {
  return (
    <label className={`field ${wide ? "field-wide" : ""}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

function SecretInput({ id, value, onChange, placeholder, required = false, autoComplete = "new-password" }) {
  const [visible, setVisible] = useState(false);
  return (
    <span className="secret-input">
      <input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
        autoComplete={autoComplete}
        spellCheck="false"
      />
      <button
        className="icon-button"
        type="button"
        aria-label={visible ? "Hide secret" : "Show secret"}
        onClick={() => setVisible((current) => !current)}
      >
        <Icon name={visible ? "eyeOff" : "eye"} />
      </button>
    </span>
  );
}

function ChannelFields({ form, setField }) {
  if (form.channel === "irc") {
    return (
      <div className="field-grid">
        <Field label="IRC channel" hint="Pick a unique channel name, including #.">
          <input value={form.ircChannel} onChange={(event) => setField("ircChannel", event.target.value)} required />
        </Field>
        <Field label="Nickname">
          <input value={form.ircUser} onChange={(event) => setField("ircUser", event.target.value)} required />
        </Field>
        <Field label="Server">
          <input value={form.ircServer} onChange={(event) => setField("ircServer", event.target.value)} required />
        </Field>
        <Field label="Port">
          <input type="number" min="1" max="65535" value={form.ircPort} onChange={(event) => setField("ircPort", event.target.value)} required />
        </Field>
      </div>
    );
  }

  if (form.channel === "telegram") {
    return (
      <div className="field-grid">
        <Field label="Bot token" hint="Create a bot with BotFather, then paste its token." wide>
          <SecretInput value={form.telegramBotToken} onChange={(event) => setField("telegramBotToken", event.target.value)} placeholder="123456:AA..." required />
        </Field>
        <Field label="Chat ID" hint="Optional — leave blank to bind the first authenticated chat." wide>
          <input value={form.telegramChatId} onChange={(event) => setField("telegramChatId", event.target.value)} placeholder="Auto-bind" />
        </Field>
      </div>
    );
  }

  if (form.channel === "slack") {
    return (
      <div className="field-grid">
        <Field label="Bot token" hint="Use a Slack bot token beginning with xoxb-." wide>
          <SecretInput value={form.slackBotToken} onChange={(event) => setField("slackBotToken", event.target.value)} placeholder="xoxb-..." required />
        </Field>
        <Field label="Channel ID" hint="Optional — leave blank to bind the first authenticated channel." wide>
          <input value={form.slackChannelId} onChange={(event) => setField("slackChannelId", event.target.value)} placeholder="C0123456789" />
        </Field>
      </div>
    );
  }

  if (form.channel === "websocket") {
    return (
      <div className="field-grid">
        <Field label="WebSocket URL" hint="The endpoint OmegaClaw should connect to." wide>
          <input type="url" value={form.websocketUrl} onChange={(event) => setField("websocketUrl", event.target.value)} placeholder="wss://chat.example.com/agent" required />
        </Field>
        <Field label="Bearer token" hint="Optional authentication for the WebSocket endpoint." wide>
          <SecretInput value={form.websocketToken} onChange={(event) => setField("websocketToken", event.target.value)} placeholder="Optional" />
        </Field>
      </div>
    );
  }

  return (
    <div className="field-grid">
      <Field label="Mattermost URL" wide>
        <input type="url" value={form.mattermostUrl} onChange={(event) => setField("mattermostUrl", event.target.value)} required />
      </Field>
      <Field label="Channel ID">
        <input value={form.mattermostChannelId} onChange={(event) => setField("mattermostChannelId", event.target.value)} required />
      </Field>
      <Field label="Bot token">
        <SecretInput value={form.mattermostBotToken} onChange={(event) => setField("mattermostBotToken", event.target.value)} required />
      </Field>
    </div>
  );
}

function StatusPill({ status, loading }) {
  const running = status?.running;
  return (
    <div className={`status-pill ${running ? "is-running" : "is-stopped"}`} role="status">
      <span className="status-dot" />
      <span>{loading ? "Checking" : running ? "OmegaClaw online" : "OmegaClaw stopped"}</span>
    </div>
  );
}

function InteractionGuide({ started }) {
  if (!started) return null;
  const channel = CHANNELS.find((item) => item.id === started.channel)?.name || started.channel;
  return (
    <section className="ready-card" aria-live="polite">
      <div className="ready-icon"><Icon name="check" /></div>
      <div>
        <p className="eyebrow">Connection ready</p>
        <h2>Meet your claw in {channel}</h2>
        <p>
          Send <code>auth {started.authSecret}</code> as the first message. The first user who authenticates becomes the owner of this OmegaClaw memory.
        </p>
        {started.channel === "irc" && (
          <a href="https://webchat.quakenet.org/" target="_blank" rel="noreferrer">Open QuakeNet web chat ↗</a>
        )}
      </div>
      <div className="auth-ticket">
        <span>One-time auth code</span>
        <strong>{started.authSecret}</strong>
      </div>
    </section>
  );
}

export default function App() {
  const [form, setForm] = useState(initialForm);
  const [status, setStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState(null);
  const [accepted, setAccepted] = useState(false);
  const [started, setStarted] = useState(null);
  const [showApiKey, setShowApiKey] = useState(false);

  const selectedProvider = useMemo(
    () => PROVIDERS.find((provider) => provider.id === form.provider),
    [form.provider],
  );

  const setField = useCallback((field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
  }, []);

  const refreshStatus = useCallback(async (quiet = false) => {
    if (!quiet) setStatusLoading(true);
    try {
      const nextStatus = await api("/api/status");
      setStatus(nextStatus);
    } catch (error) {
      if (!quiet) setNotice({ type: "error", text: error.message });
    } finally {
      if (!quiet) setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    const timer = window.setInterval(() => refreshStatus(true), 4000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  function chooseProvider(provider) {
    setForm((current) => ({ ...current, provider: provider.id, model: provider.model }));
  }

  async function handleStart(event) {
    event.preventDefault();
    setBusy("start");
    setNotice(null);
    try {
      const result = await api("/api/start", {
        method: "POST",
        body: JSON.stringify(form),
      });
      setStatus(result);
      setStarted({ channel: form.channel, authSecret: result.authSecret });
      setNotice({ type: "success", text: result.message });
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    } finally {
      setBusy("");
    }
  }

  async function handleStop() {
    setBusy("stop");
    setNotice(null);
    try {
      const result = await api("/api/stop", { method: "POST" });
      setStatus(result);
      setStarted(null);
      setNotice({ type: "success", text: result.message });
    } catch (error) {
      setNotice({ type: "error", text: error.message });
    } finally {
      setBusy("");
    }
  }

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Omega Control home">
          <span className="brand-mark">Ω</span>
          <span>Omega <b>Control</b></span>
        </a>
        <div className="topbar-actions">
          <button className="refresh-button" type="button" onClick={() => refreshStatus()} aria-label="Refresh container status">
            <Icon name="refresh" />
          </button>
          <StatusPill status={status} loading={statusLoading} />
        </div>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow"><span>Local control plane</span> / OmegaClaw</p>
          <h1>Give your claw<br /><em>a voice and a mind.</em></h1>
          <p className="hero-lede">
            Choose where it listens, choose how it thinks, then bring the agent online. Your credentials stay in the local Docker runtime.
          </p>
        </div>
        <div className="hero-orbit" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="core-mark">Ω</div>
          <span className="orbit-label label-channel">CHANNEL</span>
          <span className="orbit-label label-model">MODEL</span>
        </div>
      </section>

      <form onSubmit={handleStart}>
        <div className="configuration-grid">
          <section className="config-card channel-card">
            <div className="card-heading">
              <span className="step-number">01</span>
              <div className="heading-icon"><Icon name="channel" /></div>
              <div>
                <p className="eyebrow">Connection</p>
                <h2>Channel</h2>
                <p>Where should OmegaClaw listen?</p>
              </div>
            </div>

            <div className="channel-options" role="radiogroup" aria-label="Communication channel">
              {CHANNELS.map((channel) => (
                <button
                  key={channel.id}
                  className={`channel-option ${form.channel === channel.id ? "selected" : ""}`}
                  type="button"
                  role="radio"
                  aria-checked={form.channel === channel.id}
                  onClick={() => setField("channel", channel.id)}
                >
                  <span>{channel.name}</span>
                  <small>{channel.note}</small>
                  <i><Icon name="check" /></i>
                </button>
              ))}
            </div>

            <div className="section-divider"><span>{CHANNELS.find((channel) => channel.id === form.channel)?.name} details</span></div>
            <ChannelFields form={form} setField={setField} />

            <div className="auth-row">
              <div className="auth-row-icon"><Icon name="key" /></div>
              <Field label="Owner authentication code" hint="Share this only with the person who should own the agent.">
                <div className="inline-control">
                  <input value={form.authSecret} onChange={(event) => setField("authSecret", event.target.value)} minLength="4" required />
                  <button type="button" onClick={() => setField("authSecret", generateAuthCode())}>Regenerate</button>
                </div>
              </Field>
            </div>
          </section>

          <section className="config-card llm-card">
            <div className="card-heading">
              <span className="step-number">02</span>
              <div className="heading-icon"><Icon name="brain" /></div>
              <div>
                <p className="eyebrow">Intelligence</p>
                <h2>LLM</h2>
                <p>Which model should power the agent?</p>
              </div>
            </div>

            <div className="provider-grid" role="radiogroup" aria-label="LLM provider">
              {PROVIDERS.map((provider) => (
                <button
                  key={provider.id}
                  className={`provider-option ${form.provider === provider.id ? "selected" : ""}`}
                  type="button"
                  role="radio"
                  aria-checked={form.provider === provider.id}
                  onClick={() => chooseProvider(provider)}
                >
                  <span className="provider-mark">{provider.mark}</span>
                  <span>{provider.name}</span>
                  <i><Icon name="check" /></i>
                </button>
              ))}
            </div>

            <div className="llm-fields">
              <Field label={`${selectedProvider?.name || "Provider"} API key`} hint="Used at runtime and never saved in browser storage." wide>
                <span className="secret-input api-key-input">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={form.apiKey}
                    onChange={(event) => setField("apiKey", event.target.value)}
                    placeholder="Paste API key"
                    autoComplete="new-password"
                    spellCheck="false"
                    required
                  />
                  <button className="icon-button" type="button" aria-label={showApiKey ? "Hide API key" : "Show API key"} onClick={() => setShowApiKey((current) => !current)}>
                    <Icon name={showApiKey ? "eyeOff" : "eye"} />
                  </button>
                </span>
              </Field>
              <Field label="Model" wide>
                <input value={form.model} onChange={(event) => setField("model", event.target.value)} required />
              </Field>
              {form.provider === "OpenAIAPI" && (
                <Field label="OpenAI-compatible endpoint" hint="Use host.docker.internal to reach a model server on this computer." wide>
                  <input type="url" value={form.openaiApiUrl} onChange={(event) => setField("openaiApiUrl", event.target.value)} required />
                </Field>
              )}
            </div>

            <details className="advanced-settings">
              <summary>Runtime tuning <span>Optional</span></summary>
              <div className="field-grid advanced-grid">
                <Field label="Reasoning effort">
                  <select value={form.reasoningMode} onChange={(event) => setField("reasoningMode", event.target.value)}>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </Field>
                <Field label="Max output tokens">
                  <input type="number" min="128" max="32000" step="1" value={form.maxOutputToken} onChange={(event) => setField("maxOutputToken", event.target.value)} />
                </Field>
                <label className="toggle-row field-wide">
                  <input type="checkbox" checked={form.importKnowledge} onChange={(event) => setField("importKnowledge", event.target.checked)} />
                  <span className="toggle-track"><i /></span>
                  <span><b>Import knowledge on first start</b><small>Can take about 30 minutes.</small></span>
                </label>
              </div>
            </details>
          </section>
        </div>

        <section className="control-deck">
          <div className="control-copy">
            <p className="eyebrow">03 / Launch</p>
            <h2>{status?.running ? "OmegaClaw is active" : "Ready when you are"}</h2>
            <p>
              {status?.running && status.configuration?.provider
                ? `${status.configuration.channel} · ${status.configuration.provider} · ${status.configuration.model}`
                : "Review the settings, accept the notice, and start the agent."}
            </p>
          </div>
          <label className="acceptance">
            <input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} />
            <span><Icon name="check" /></span>
            <small>I understand OmegaClaw is autonomous software and should run with minimum permissions.</small>
          </label>
          <div className="large-actions">
            <button className="start-button" type="submit" disabled={!accepted || Boolean(busy)}>
              <span className="button-icon"><Icon name={busy === "start" ? "spark" : "play"} /></span>
              <span><b>{busy === "start" ? "Starting…" : status?.running ? "Restart with settings" : "Start OmegaClaw"}</b><small>Apply this configuration</small></span>
            </button>
            <button className="stop-button" type="button" onClick={handleStop} disabled={!status?.running || Boolean(busy)}>
              <span className="button-icon"><Icon name="stop" /></span>
              <span><b>{busy === "stop" ? "Stopping…" : "Stop"}</b><small>Keep memory safe</small></span>
            </button>
          </div>
          {notice && <div className={`notice ${notice.type}`} role="alert">{notice.text}</div>}
        </section>
      </form>

      <InteractionGuide started={started} />

      <footer>
        <span className="brand-mark small">Ω</span>
        <p>Runs locally through Docker Compose. Secrets are placed only in the managed container environment.</p>
        <span>OmegaClaw Control / 0.1</span>
      </footer>
    </main>
  );
}
