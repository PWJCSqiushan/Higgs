import assert from "node:assert/strict";
import test from "node:test";

import { OfficialQQClient, PINNED_SDK_VERSION } from "../src/qq-client.mjs";
import { GROUP_AND_C2C_INTENT, PROTOCOL_VERSION } from "../src/protocol.mjs";

const safe = "A123_safe-value";
const senderSafe = "B456_sender-value";

class FakeWs {
  constructor() {
    this.handlers = new Map();
    this.readyState = 1;
  }

  on(name, handler) {
    const handlers = this.handlers.get(name) ?? [];
    handlers.push(handler);
    this.handlers.set(name, handlers);
  }

  emit(name, ...args) {
    for (const handler of this.handlers.get(name) ?? []) handler(...args);
  }
}

class FakeBot {
  static instances = [];

  constructor(options) {
    this.options = options;
    this.handlers = new Map();
    this.sent = [];
    this.result = { id: safe };
    this.gateway = {
      currentWs: new FakeWs(),
      reconnect: { isExhausted: () => false },
    };
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

function newClient(overrides = {}) {
  FakeBot.instances = [];
  return new OfficialQQClient({
    appId: "123456789",
    appSecret: "0123456789abcdef",
    enabled: true,
    captureOnly: false,
    BotClass: FakeBot,
    now: () => 1234,
    ownerOpenId: senderSafe,
    allowedGroupOpenIds: [safe],
    ...overrides,
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
    senderId: senderSafe,
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

test("owner binding callback receives only an authenticated C2C sender", async () => {
  const candidates = [];
  const client = newClient({
    captureOnly: true,
    onOwnerCandidate: (value) => candidates.push(value),
  });
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: senderSafe,
      messageId: safe,
      content: "before-ready",
      timestamp: "2026-08-29T01:00:00Z",
    });
    bot.emit("ready", { user: { id: safe } });
    bot.emit("message", {}, {
      rawEventType: "GROUP_AT_MESSAGE_CREATE",
      kind: "group",
      senderId: senderSafe,
      groupOpenid: safe,
      messageId: safe,
      content: "group",
      timestamp: "2026-08-29T01:00:01Z",
    });
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: senderSafe,
      messageId: safe,
      content: "must-not-be-retained",
      timestamp: "2026-08-29T01:00:02Z",
    });
    assert.deepEqual(candidates, [senderSafe]);
    assert.equal(
      client.readEvents(0, 10).every((event) => event.sender_id === undefined),
      true,
    );
  } finally {
    await client.stop();
  }
});

test("owner binding callback failure stops the client fail-closed", async () => {
  const client = newClient({
    captureOnly: true,
    onOwnerCandidate: () => {
      throw new Error("private write failed");
    },
  });
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    bot.emit("ready", { user: { id: safe } });
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: senderSafe,
      messageId: safe,
      content: "must-not-be-retained",
      timestamp: "2026-08-29T01:00:00Z",
    });
    assert.equal(client.status().authenticated, false);
    assert.equal(client.status().reason, "owner_bind_error");
  } finally {
    await client.stop();
  }
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

function readyForSend(bot) {
  bot.emit("ready", { user: { id: safe } });
  bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
}

test("disabled client never constructs the SDK", async () => {
  FakeBot.instances = [];
  const client = new OfficialQQClient({ appId: "", appSecret: "", BotClass: FakeBot });
  await client.start();
  assert.equal(FakeBot.instances.length, 0);
  assert.equal(client.status().reason, "disabled");
});

test("SDK is configured with exact intent and silent logger", async () => {
  assert.equal(PINNED_SDK_VERSION, "1.0.4");
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
    senderId: senderSafe,
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
    senderId: senderSafe,
    messageId: safe,
    content: "after-ready",
    timestamp: "2026-08-28T10:00:00Z",
  });
  assert.equal(client.status().authenticated, true);
  assert.equal(client.readEvents(0, 10).length, 1);
  await client.stop();
});

test("full mode drops and never authorizes non-owner or non-allowlisted events", async () => {
  const client = newClient();
  await client.start();
  const bot = FakeBot.instances[0];
  bot.emit("ready", { user: { id: safe } });
  bot.emit("message", {}, {
    rawEventType: "C2C_MESSAGE_CREATE",
    kind: "c2c",
    senderId: "not-the-owner",
    messageId: safe,
    content: "ignored",
    timestamp: "2026-08-28T10:00:00Z",
  });
  bot.emit("message", {}, {
    rawEventType: "GROUP_AT_MESSAGE_CREATE",
    kind: "group",
    senderId: senderSafe,
    groupOpenid: "not-allowlisted",
    messageId: "group-message",
    content: "ignored",
    timestamp: "2026-08-28T10:00:00Z",
  });
  assert.equal(client.readEvents(0, 10).length, 0);
  assert.throws(
    () => client.replyAuthorizations.claim(safe, "c2c", "not-the-owner", safe, 1234),
    /invalid_reply_binding/,
  );
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
  readyForSend(bot);
  client.replyAuthorizations.authorize(safe, "c2c", safe, 1234);
  bot.result = {};
  const first = await client.send(sendRequest(client));
  assert.equal(first.state, "unknown");
  assert.equal(bot.sent.length, 1);
  const repeated = await client.send(sendRequest(client));
  assert.deepEqual(repeated, first);
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

test("send requires an inbound reply binding and serializes concurrent idempotent calls", async () => {
  const client = newClient();
  await client.start();
  const bot = FakeBot.instances[0];
  readyForSend(bot);
  await assert.rejects(client.send(sendRequest(client)), /invalid_reply_binding/);

  client.replyAuthorizations.authorize(safe, "c2c", safe, 1234);
  let release;
  bot.sendText = async (target, text) => {
    bot.sent.push({ target, text });
    await new Promise((resolve) => {
      release = resolve;
    });
    return { id: safe };
  };
  const first = client.send(sendRequest(client, { request_id: "request-one" }));
  const second = client.send(sendRequest(client, { request_id: "request-two" }));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(bot.sent.length, 1);
  release();
  const [firstReceipt, secondReceipt] = await Promise.all([first, second]);
  assert.equal(firstReceipt.request_id, "request-one");
  assert.equal(secondReceipt.request_id, "request-two");
  assert.equal(firstReceipt.provider_message_id, safe);
  await client.stop();
});

test("send requires a fresh observable heartbeat ACK", async () => {
  let now = 1000;
  const client = newClient({
    now: () => now,
    heartbeatAckTimeoutMs: 100,
    watchdogIntervalMs: 60_000,
  });
  await client.start();
  const bot = FakeBot.instances[0];
  bot.emit("ready", { user: { id: safe } });
  client.replyAuthorizations.authorize(safe, "c2c", safe, now);
  await assert.rejects(client.send(sendRequest(client)), /gateway_unavailable/);
  bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
  now = 1200;
  await assert.rejects(client.send(sendRequest(client)), /gateway_unavailable/);
  assert.equal(client.status().reason, "heartbeat_ack_timeout");
  await client.stop();
});

test("provider timeout returns UNKNOWN without hanging or retrying", async () => {
  const client = newClient({ sendTimeoutMs: 5 });
  await client.start();
  const bot = FakeBot.instances[0];
  readyForSend(bot);
  client.replyAuthorizations.authorize(safe, "c2c", safe, 1234);
  bot.sendText = () => new Promise(() => {});
  const receipt = await client.send(sendRequest(client));
  assert.equal(receipt.state, "unknown");
  const repeated = await client.send(sendRequest(client));
  assert.deepEqual(repeated, receipt);
  await client.stop();
});

test("gateway close clears authentication and heartbeat timeout is fatal", async () => {
  let now = 1000;
  let fatalReason = null;
  const client = newClient({
    now: () => now,
    heartbeatAckTimeoutMs: 100,
    watchdogIntervalMs: 60_000,
    onFatal: (reason) => {
      fatalReason = reason;
    },
  });
  await client.start();
  const bot = FakeBot.instances[0];
  bot.emit("ready", { user: { id: safe } });
  bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
  assert.equal(client.status().last_heartbeat_ack_at_ms, 1000);
  assert.equal(client.status().heartbeat_ack_observable, true);

  now = 1200;
  client._watchGateway();
  assert.equal(fatalReason, "heartbeat_ack_timeout");
  assert.equal(client.status().authenticated, false);
  await client.stop();
});

test("missing pinned WebSocket internals and session touch failures are fatal", async () => {
  let fatalReason = null;
  const missingSocketClient = newClient({
    onFatal: (reason) => {
      fatalReason = reason;
    },
  });
  await missingSocketClient.start();
  const missingSocketBot = FakeBot.instances[0];
  missingSocketBot.gateway.currentWs = null;
  missingSocketBot.emit("ready", { user: { id: safe } });
  assert.equal(fatalReason, "gateway_error");
  await missingSocketClient.stop();

  fatalReason = null;
  const sessionStore = {
    getBotId: () => null,
    saveBotId() {},
    touch() {
      throw new Error("disk unavailable");
    },
    load: () => null,
    save() {},
    clear() {},
  };
  const touchClient = newClient({
    sessionStore,
    onFatal: (reason) => {
      fatalReason = reason;
    },
  });
  await touchClient.start();
  const touchBot = FakeBot.instances[0];
  touchBot.emit("ready", { user: { id: safe } });
  touchBot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
  assert.equal(fatalReason, "session_store_error");
  await touchClient.stop();
});

test("RESUMED authenticates only with the bot identity bound to persisted session state", async () => {
  const sessionStore = {
    getBotId: () => safe,
    saveBotId() {},
    touch() {},
    load: () => ({ sessionId: safe, lastSeq: 1 }),
    save() {},
    clear() {},
  };
  const client = newClient({ sessionStore });
  await client.start();
  const bot = FakeBot.instances[0];
  assert.equal(bot.options.sessionPersistence, sessionStore);
  bot.emit("resumed");
  assert.equal(client.status().authenticated, true);
  assert.equal(client.status().bot_id, safe);
  await client.stop();
});

test("malformed INVALID_SESSION payload stops the pinned SDK wrapper fail-closed", async () => {
  let fatalReason = null;
  const client = newClient({
    onFatal: (reason) => {
      fatalReason = reason;
    },
  });
  await client.start();
  const bot = FakeBot.instances[0];
  bot.emit("ready", { user: { id: safe } });
  bot.gateway.currentWs.emit("message", Buffer.from('{"op":9,"d":{"bad":true}}'));
  assert.equal(fatalReason, "protocol_error");
  assert.equal(client.status().authenticated, false);
  await client.stop();
});
