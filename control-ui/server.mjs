import { randomInt } from "node:crypto";
import { spawn } from "node:child_process";
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.PORT || 3210);
const DIST_DIR = fileURLToPath(new URL("./dist/", import.meta.url));
const COMPOSE_FILE = process.env.COMPOSE_FILE || "/opt/omegaclaw/compose.yaml";
const PROJECT_NAME = process.env.COMPOSE_PROJECT_NAME || "omegaclaw";
const AGENT_CONTAINER = process.env.OMEGACLAW_CONTAINER_NAME || "omegaclaw";
const MAX_BODY_BYTES = 32 * 1024;
const MAX_COMMAND_OUTPUT = 64 * 1024;

const CHANNELS = new Set(["irc", "telegram", "slack", "websocket", "mattermost"]);
const PROVIDERS = new Set([
  "Anthropic",
  "OpenAI",
  "ASICloud",
  "ASIOne",
  "OpenRouter",
  "OpenAIAPI",
]);
const REASONING_MODES = new Set(["low", "medium", "high"]);
const API_KEY_ENV = {
  Anthropic: "ANTHROPIC_API_KEY",
  OpenAI: "OPENAI_API_KEY",
  ASICloud: "ASI_API_KEY",
  ASIOne: "ASIONE_API_KEY",
  OpenRouter: "OPENROUTER_API_KEY",
  OpenAIAPI: "OPENAIAPI_API_KEY",
};

const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};

let operation = null;

export class ValidationError extends Error {}

function text(value, field, { required = true, max = 512 } = {}) {
  const result = String(value ?? "").trim();
  if (required && !result) {
    throw new ValidationError(`${field} is required.`);
  }
  if (result.length > max) {
    throw new ValidationError(`${field} is too long.`);
  }
  if (/[\0\r\n]/.test(result)) {
    throw new ValidationError(`${field} contains unsupported characters.`);
  }
  return result;
}

function enumValue(value, values, field) {
  const result = text(value, field);
  if (!values.has(result)) {
    throw new ValidationError(`${field} is not supported.`);
  }
  return result;
}

function urlValue(value, field, protocols) {
  const result = text(value, field, { max: 2048 });
  let parsed;
  try {
    parsed = new URL(result);
  } catch {
    throw new ValidationError(`${field} must be a valid URL.`);
  }
  if (!protocols.includes(parsed.protocol)) {
    throw new ValidationError(`${field} must use ${protocols.join(" or ")}.`);
  }
  return result.replace(/\/$/, "");
}

export function validateConfiguration(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new ValidationError("A configuration object is required.");
  }

  const channel = enumValue(input.channel, CHANNELS, "Channel");
  const provider = enumValue(input.provider, PROVIDERS, "LLM provider");
  const model = text(input.model, "Model", { max: 256 });
  const apiKey = text(input.apiKey, "API key", { max: 4096 });
  const authSecret = text(input.authSecret, "Authentication code", { max: 128 });
  if (authSecret.length < 4) {
    throw new ValidationError("Authentication code must contain at least 4 characters.");
  }

  const reasoningMode = enumValue(
    input.reasoningMode || "medium",
    REASONING_MODES,
    "Reasoning mode",
  );
  const maxOutputToken = Number(input.maxOutputToken || 6000);
  if (!Number.isInteger(maxOutputToken) || maxOutputToken < 128 || maxOutputToken > 32000) {
    throw new ValidationError("Max output tokens must be an integer from 128 to 32000.");
  }

  const config = {
    channel,
    provider,
    model,
    apiKey,
    authSecret,
    reasoningMode,
    maxOutputToken,
    importKnowledge: input.importKnowledge === true,
    openaiApiUrl: "http://host.docker.internal:11434/v1",
    ircChannel: "##omegaclaw",
    ircServer: "irc.quakenet.org",
    ircPort: "6667",
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

  if (provider === "OpenAIAPI") {
    config.openaiApiUrl = urlValue(input.openaiApiUrl, "OpenAI API endpoint", ["http:", "https:"]);
  }

  if (channel === "irc") {
    config.ircChannel = text(input.ircChannel, "IRC channel", { max: 128 });
    config.ircServer = text(input.ircServer || config.ircServer, "IRC server", { max: 253 });
    const port = Number(input.ircPort || 6667);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      throw new ValidationError("IRC port must be from 1 to 65535.");
    }
    config.ircPort = String(port);
    config.ircUser = text(input.ircUser || config.ircUser, "IRC nickname", { max: 64 });
  }

  if (channel === "telegram") {
    config.telegramBotToken = text(input.telegramBotToken, "Telegram bot token", { max: 512 });
    config.telegramChatId = text(input.telegramChatId, "Telegram chat ID", {
      required: false,
      max: 128,
    });
  }

  if (channel === "slack") {
    config.slackBotToken = text(input.slackBotToken, "Slack bot token", { max: 512 });
    config.slackChannelId = text(input.slackChannelId, "Slack channel ID", {
      required: false,
      max: 128,
    });
  }

  if (channel === "websocket") {
    config.websocketUrl = urlValue(input.websocketUrl, "WebSocket URL", ["ws:", "wss:"]);
    config.websocketToken = text(input.websocketToken, "WebSocket token", {
      required: false,
      max: 2048,
    });
  }

  if (channel === "mattermost") {
    config.mattermostUrl = urlValue(input.mattermostUrl, "Mattermost URL", ["http:", "https:"]);
    config.mattermostChannelId = text(input.mattermostChannelId, "Mattermost channel ID", {
      max: 128,
    });
    config.mattermostBotToken = text(input.mattermostBotToken, "Mattermost bot token", {
      max: 512,
    });
  }

  return config;
}

export function configurationEnvironment(config) {
  const environment = {
    ANTHROPIC_API_KEY: "",
    OPENAI_API_KEY: "",
    ASI_API_KEY: "",
    ASIONE_API_KEY: "",
    OPENROUTER_API_KEY: "",
    OPENAIAPI_API_KEY: "",
    TG_BOT_TOKEN: config.telegramBotToken,
    SL_BOT_TOKEN: config.slackBotToken,
    MM_BOT_TOKEN: config.mattermostBotToken,
    OMEGACLAW_AUTH_SECRET: config.authSecret,
    IMPORT_KB_ON_START: config.importKnowledge ? "1" : "0",
    OMEGACLAW_CHANNEL: config.channel,
    OMEGACLAW_PROVIDER: config.provider,
    OMEGACLAW_EMBEDDING_PROVIDER: config.provider === "OpenAI" ? "OpenAI" : "Local",
    OMEGACLAW_MODEL: config.model,
    OMEGACLAW_REASONING_MODE: config.reasoningMode,
    OMEGACLAW_MAX_OUTPUT_TOKEN: String(config.maxOutputToken),
    OMEGACLAW_OPENAIAPI_URL: config.openaiApiUrl,
    OMEGACLAW_IRC_CHANNEL: config.ircChannel,
    OMEGACLAW_IRC_SERVER: config.ircServer,
    OMEGACLAW_IRC_PORT: config.ircPort,
    OMEGACLAW_IRC_USER: config.ircUser,
    OMEGACLAW_TG_CHAT_ID: config.telegramChatId,
    OMEGACLAW_SL_CHANNEL_ID: config.slackChannelId,
    OMEGACLAW_WS_URL: config.websocketUrl,
    OMEGACLAW_WS_TOKEN: config.websocketToken,
    OMEGACLAW_MM_URL: config.mattermostUrl,
    OMEGACLAW_MM_CHANNEL_ID: config.mattermostChannelId,
  };
  environment[API_KEY_ENV[config.provider]] = config.apiKey;
  return environment;
}

function run(command, args, { environment = {}, timeout = 600_000 } = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      env: { ...process.env, ...environment },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;

    const append = (current, chunk) => (current + chunk.toString()).slice(-MAX_COMMAND_OUTPUT);
    child.stdout.on("data", (chunk) => {
      stdout = append(stdout, chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr = append(stderr, chunk);
    });

    const timer = setTimeout(() => {
      if (!settled) {
        child.kill("SIGKILL");
        reject(new Error(`${command} timed out.`));
      }
    }, timeout);

    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });

    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code === 0) {
        resolvePromise({ stdout: stdout.trim(), stderr: stderr.trim() });
      } else {
        const detail = stderr.trim().split("\n").slice(-6).join("\n");
        reject(new Error(detail || `${command} exited with status ${code}.`));
      }
    });
  });
}

function composeArgs(...args) {
  return ["compose", "--project-name", PROJECT_NAME, "--file", COMPOSE_FILE, ...args];
}

async function agentStatus() {
  const { stdout: containerId } = await run(
    "docker",
    ["ps", "--all", "--quiet", "--filter", `name=^/${AGENT_CONTAINER}$`],
    { timeout: 10_000 },
  );
  if (!containerId) {
    return {
      running: false,
      status: "not_created",
      startedAt: null,
      finishedAt: null,
      exitCode: null,
      error: "",
      configuration: { channel: null, provider: null, model: null },
      operation,
    };
  }

  const { stdout } = await run("docker", ["inspect", containerId], { timeout: 10_000 });
  const [container] = JSON.parse(stdout);
  const labels = container?.Config?.Labels || {};
  const state = container?.State || {};
  return {
    running: state.Running === true,
    status: state.Status || "unknown",
    startedAt: state.StartedAt || null,
    finishedAt: state.FinishedAt || null,
    exitCode: state.ExitCode ?? null,
    error: state.Error || "",
    configuration: {
      channel: labels["io.omegaclaw.control.channel"] || null,
      provider: labels["io.omegaclaw.control.provider"] || null,
      model: labels["io.omegaclaw.control.model"] || null,
    },
    operation,
  };
}

function securityHeaders(response) {
  response.setHeader("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");
  response.setHeader("Referrer-Policy", "no-referrer");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("X-Frame-Options", "DENY");
}

function json(response, statusCode, body) {
  securityHeaders(response);
  response.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(body));
}

async function readJson(request) {
  const contentType = String(request.headers["content-type"] || "");
  if (!contentType.toLowerCase().startsWith("application/json")) {
    throw new ValidationError("Content-Type must be application/json.");
  }

  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) {
      throw new ValidationError("Request body is too large.");
    }
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ValidationError("Request body must contain valid JSON.");
  }
}

function requireControlRequest(request) {
  if (request.headers["x-omega-control"] !== "browser") {
    throw new ValidationError("Missing control request header.");
  }
}

async function startAgent(request, response) {
  if (operation) {
    return json(response, 409, { error: `A ${operation} operation is already in progress.` });
  }

  operation = "start";
  try {
    const config = validateConfiguration(await readJson(request));
    await run(
      "docker",
      composeArgs("--profile", "agent", "up", "--detach", "--force-recreate", "--no-deps", "--pull", "missing", "omegaclaw"),
      {
        environment: configurationEnvironment(config),
        timeout: 30 * 60_000,
      },
    );
    operation = null;
    const status = await agentStatus();
    return json(response, 200, {
      ...status,
      authSecret: config.authSecret,
      message: "OmegaClaw started with the new configuration.",
    });
  } finally {
    operation = null;
  }
}

async function stopAgent(response) {
  if (operation) {
    return json(response, 409, { error: `A ${operation} operation is already in progress.` });
  }

  operation = "stop";
  try {
    await run("docker", composeArgs("--profile", "agent", "stop", "--timeout", "20", "omegaclaw"), {
      timeout: 60_000,
    });
    operation = null;
    return json(response, 200, {
      ...(await agentStatus()),
      message: "OmegaClaw stopped safely.",
    });
  } finally {
    operation = null;
  }
}

function serveStatic(request, response) {
  const requestUrl = new URL(request.url, "http://localhost");
  const requestedPath = requestUrl.pathname === "/" ? "/index.html" : requestUrl.pathname;
  let filePath = resolve(DIST_DIR, `.${decodeURIComponent(requestedPath)}`);
  if (!filePath.startsWith(`${resolve(DIST_DIR)}${sep}`)) {
    return json(response, 404, { error: "Not found." });
  }
  if (!existsSync(filePath)) {
    filePath = resolve(DIST_DIR, "index.html");
  }

  securityHeaders(response);
  response.writeHead(200, {
    "Cache-Control": extname(filePath) === ".html" ? "no-cache" : "public, max-age=31536000, immutable",
    "Content-Type": MIME_TYPES[extname(filePath)] || "application/octet-stream",
  });
  createReadStream(filePath).pipe(response);
}

export function createControlServer() {
  return createServer(async (request, response) => {
    try {
      const requestUrl = new URL(request.url, "http://localhost");

      if (request.method === "GET" && requestUrl.pathname === "/api/health") {
        return json(response, 200, { ok: true });
      }
      if (request.method === "GET" && requestUrl.pathname === "/api/status") {
        return json(response, 200, await agentStatus());
      }
      if (request.method === "POST" && requestUrl.pathname === "/api/start") {
        requireControlRequest(request);
        return await startAgent(request, response);
      }
      if (request.method === "POST" && requestUrl.pathname === "/api/stop") {
        requireControlRequest(request);
        return await stopAgent(response);
      }
      if (requestUrl.pathname.startsWith("/api/")) {
        return json(response, 404, { error: "API endpoint not found." });
      }
      if (request.method !== "GET" && request.method !== "HEAD") {
        return json(response, 405, { error: "Method not allowed." });
      }
      return serveStatic(request, response);
    } catch (error) {
      const statusCode = error instanceof ValidationError ? 400 : 500;
      const message = statusCode === 400 ? error.message : "The container operation failed. Check Docker Desktop and try again.";
      if (statusCode === 500) {
        console.error(`[control-api] ${error.message}`);
      }
      if (!response.headersSent) {
        return json(response, statusCode, { error: message });
      }
      response.end();
    }
  });
}

if (process.env.NODE_ENV !== "test") {
  const server = createControlServer();
  server.listen(PORT, "0.0.0.0", () => {
    console.log(`Omega Control is ready on port ${PORT}.`);
  });

  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => server.close(() => process.exit(0)));
  }
}

export function randomAuthSecret() {
  return String(randomInt(100000, 1000000));
}
