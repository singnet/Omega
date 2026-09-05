import assert from "node:assert/strict";
import test from "node:test";

process.env.NODE_ENV = "test";
const { configurationEnvironment, validateConfiguration, ValidationError } = await import("./server.mjs");

const valid = {
  channel: "telegram",
  provider: "OpenAI",
  model: "gpt-5.5",
  apiKey: "secret-key",
  authSecret: "123456",
  reasoningMode: "medium",
  maxOutputToken: 6000,
  telegramBotToken: "123:telegram-secret",
  telegramChatId: "",
};

test("validates and maps a supported configuration", () => {
  const config = validateConfiguration(valid);
  const environment = configurationEnvironment(config);

  assert.equal(config.channel, "telegram");
  assert.equal(environment.OPENAI_API_KEY, "secret-key");
  assert.equal(environment.ANTHROPIC_API_KEY, "");
  assert.equal(environment.TG_BOT_TOKEN, "123:telegram-secret");
  assert.equal(environment.OMEGACLAW_EMBEDDING_PROVIDER, "OpenAI");
});

test("rejects unsupported providers", () => {
  assert.throws(
    () => validateConfiguration({ ...valid, provider: "UnknownAI" }),
    (error) => error instanceof ValidationError && /not supported/.test(error.message),
  );
});

test("requires channel-specific credentials", () => {
  assert.throws(
    () => validateConfiguration({ ...valid, telegramBotToken: "" }),
    (error) => error instanceof ValidationError && /Telegram bot token is required/.test(error.message),
  );
});

test("rejects control characters in Compose values", () => {
  assert.throws(
    () => validateConfiguration({ ...valid, model: "gpt-safe\nINJECTED=value" }),
    (error) => error instanceof ValidationError && /unsupported characters/.test(error.message),
  );
});
