import assert from "node:assert/strict";
import test from "node:test";

import { OfficialQQClient } from "../src/qq-client.mjs";
import { GROUP_AND_C2C_INTENT, PROTOCOL_VERSION } from "../src/protocol.mjs";

const safe = "A123_safe-value";

class FakeBot {
  static instances = [];

  constructor(options) {
    this.options = options;
    this.handlers = new Map();
    this.sent = [];
    this.result = { id: safe };
    this.done = new Promise((resolve) => {
      this.finish = resolve;
    });
    FakeBot.instances.push(this);
  }

  on(name, handler) {
    this.handlers.set(name, handler);
    return this;
  }

  start() {
    return this.done;
  }

  stop() {
    this.finish();
  }

  emit(name, ...args) {
    return this.handlers.get(name)?.(...args);
  }

  async sendText(target, text) {
    this.sent.push({ target, text });
    return this.result;
  }
}

function newClient() {
  FakeBot.instances = [];
  return new OfficialQQClient({
    appId: "123456789",
    appSecret: "0123456789abcdef",
    enabled: true,
    captureOnly: false,
    BotClass: FakeBot,
    now: () => 1234,
  });
}

test("capture-only mode retains no identity or message content and disables send", async () => {
  FakeBot.instances = [];
  const client = new OfficialQQClient({
    appId: "123456789",
    appSecret: "0123456789abcdef",
    enabled: true,
    captureOnly: true,
    BotClass: FakeBot,
    now: () => 1234,
  });
  await client.start();
  const bot = FakeBot.instances[0];
  bot.emit("ready", { user: { id: safe } });
  bot.emit("message", {}, {
    rawEventType: "C2C_MESSAGE_CREATE",
    kind: "c2c",
    senderId: safe,
    messageId: safe,
    content: "must-not-be-retained",
    timestamp: "2026-08-28T10:00:00Z",
  });
  assert.equal(client.status().bot_id, null);
  assert.deepEqual(client.readEvents(0, 10), [
    {
      cursor: 1,
      event_type: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      received_at_ms: 1234,
    },
  ]);
  await assert.rejects(client.send(sendRequest(client)), /capture_only/);
  await client.stop();
});

function sendRequest(client, overrides = {}) {
  return {
    protocol_version: PROTOCOL_VERSION,
    generation: client.generation,
    request_id: safe,
    idempotency_key: safe,
    kind: "c2c",
    target_id: safe,
    text: "reply",
    reply_message_id: safe,
    ...overrides,
  };
}

test("disabled client never constructs the SDK", async () => {
  FakeBot.instances = [];
  const client = new OfficialQQClient({ appId: "", appSecret: "", BotClass: FakeBot });
  await client.start();
  assert.equal(FakeBot.instances.length, 0);
  assert.equal(client.status().reason, "disabled");
});

test("SDK is configured with exact intent and silent logger", async () => {
  const client = newClient();
  await client.start();
  const bot = FakeBot.instances[0];
  assert.equal(bot.options.intents, GROUP_AND_C2C_INTENT);
  assert.equal(bot.options.transport, "websocket");
  assert.equal(bot.options.markdownSupport, false);
  assert.equal(typeof bot.options.logger.debug, "function");
  await client.stop();
});

test("READY identity is mandatory before events or sends", async () => {
  const client = newClient();
  await client.start();
  const bot = FakeBot.instances[0];
  bot.emit("message", {}, {
    rawEventType: "C2C_MESSAGE_CREATE",
    kind: "c2c",
    senderId: safe,
    messageId: safe,
    content: "before-ready",
    timestamp: "2026-08-28T10:00:00Z",
  });
  assert.equal(client.readEvents(0, 10).length, 0);
  await assert.rejects(client.send(sendRequest(client)), /gateway_unavailable/);

  bot.emit("ready", { user: { id: safe } });
  bot.emit("message", {}, {
    rawEventType: "C2C_MESSAGE_CREATE",
    kind: "c2c",
    senderId: safe,
    messageId: safe,
    content: "after-ready",
    timestamp: "2026-08-28T10:00:00Z",
  });
  assert.equal(client.status().authenticated, true);
  assert.equal(client.readEvents(0, 10).length, 1);
  await client.stop();
});

test("invalid READY identity stops fail-closed", async () => {
  const client = newClient();
  await client.start();
  const bot = FakeBot.instances[0];
  bot.emit("ready", { user: { id: "bad id" } });
  assert.equal(client.status().authenticated, false);
  assert.equal(client.status().reason, "ready_identity_invalid");
  await client.stop();
});

test("missing provider id is UNKNOWN and idempotency collisions are rejected", async () => {
  const client = newClient();
  await client.start();
  const bot = FakeBot.instances[0];
  bot.emit("ready", { user: { id: safe } });
  bot.result = {};
  const first = await client.send(sendRequest(client));
  assert.equal(first.state, "unknown");
  assert.equal(bot.sent.length, 1);
  const repeated = await client.send(sendRequest(client));
  assert.equal(repeated, first);
  assert.equal(bot.sent.length, 1);
  await assert.rejects(
    client.send(sendRequest(client, { text: "different" })),
    /idempotency_collision/,
  );
  await client.stop();
});

test("stale generation is rejected", async () => {
  const client = newClient();
  await client.start();
  FakeBot.instances[0].emit("ready", { user: { id: safe } });
  await assert.rejects(
    client.send(sendRequest(client, { generation: "different-generation" })),
    /stale_generation/,
  );
  await client.stop();
});
