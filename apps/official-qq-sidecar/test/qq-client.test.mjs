import assert from "node:assert/strict";
import { chmodSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { SecureDeliveryStore } from "../src/delivery-store.mjs";
import { OfficialQQClient, PINNED_SDK_VERSION } from "../src/qq-client.mjs";
import {
  GROUP_AND_C2C_INTENT,
  PROTOCOL_VERSION,
  requestFingerprint,
} from "../src/protocol.mjs";

const safe = "A123_safe-value";
const senderSafe = "B456_sender-value";
const unixOnly = { skip: process.platform === "win32" };

function durableStore(prefix) {
  const directory = mkdtempSync(join(tmpdir(), prefix));
  chmodSync(directory, 0o700);
  return new SecureDeliveryStore(join(directory, "delivery-state.json"), {
    now: () => 1234,
  });
}

function durableInbound() {
  return {
    event_type: "C2C_MESSAGE_CREATE",
    kind: "c2c",
    bot_id: safe,
    sender_id: safe,
    group_id: null,
    message_id: safe,
    occurred_at_ms: 1000,
    received_at_ms: 1001,
    text: "private test payload",
    attachments: [],
  };
}

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
    allowedPrivateOpenIds: [senderSafe, safe],
    allowedGroupOpenIds: [safe],
    ordinaryPrivateEnabled: true,
    groupEnabled: true,
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
  bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
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
    bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
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
    bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
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

test("group binding callback requires authenticated owner group-at and fixed phrase", async () => {
  const candidates = [];
  const client = newClient({
    captureOnly: true,
    groupBindPhrase: "绑定测试群",
    onGroupCandidate: (value) => candidates.push(value),
  });
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    const groupMessage = (overrides = {}) => ({
      rawEventType: "GROUP_AT_MESSAGE_CREATE",
      kind: "group",
      senderId: senderSafe,
      groupOpenid: safe,
      messageId: safe,
      content: "@Higgs 绑定测试群",
      timestamp: "2026-08-30T01:00:00Z",
      ...overrides,
    });
    bot.emit("message", {}, groupMessage());
    bot.emit("ready", { user: { id: safe } });
    bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
    bot.emit("message", {}, groupMessage({ senderId: "not-owner" }));
    bot.emit("message", {}, groupMessage({ content: "@Higgs 普通测试" }));
    bot.emit("message", {}, groupMessage());
    bot.emit("message", {}, groupMessage({ groupOpenid: "ignored-group" }));
    assert.deepEqual(candidates, [safe, "ignored-group"]);
    assert.equal(
      client.readEvents(0, 10).every((event) => event.sender_id === undefined),
      true,
    );
  } finally {
    await client.stop();
  }
});

test("group binding callback failure stops the client fail-closed", async () => {
  const client = newClient({
    captureOnly: true,
    groupBindPhrase: "绑定测试群",
    onGroupCandidate: () => {
      throw new Error("private write failed");
    },
  });
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    bot.emit("ready", { user: { id: safe } });
    bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
    bot.emit("message", {}, {
      rawEventType: "GROUP_AT_MESSAGE_CREATE",
      kind: "group",
      senderId: senderSafe,
      groupOpenid: safe,
      messageId: safe,
      content: "@Higgs 绑定测试群",
      timestamp: "2026-08-30T01:00:00Z",
    });
    assert.equal(client.status().authenticated, false);
    assert.equal(client.status().reason, "group_bind_error");
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
  try {
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
    assert.equal(client.status().authenticated, false);
    assert.equal(client.status().reason, "heartbeat_pending");
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: senderSafe,
      messageId: safe,
      content: "after-ready",
      timestamp: "2026-08-28T10:00:00Z",
    });
    assert.equal(client.readEvents(0, 10).length, 0);
    bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: senderSafe,
      messageId: safe,
      content: "after-heartbeat",
      timestamp: "2026-08-28T10:00:00Z",
    });
    assert.equal(client.status().authenticated, true);
    assert.equal(client.status().reason, "ready");
    assert.equal(client.readEvents(0, 10).length, 1);
  } finally {
    await client.stop();
  }
});

test("ordinary private allowlist is bound to the same Bot account", async () => {
  const client = newClient({
    ordinaryPrivateEnabled: true,
    allowedPrivateOpenIds: [senderSafe],
    requirePrivateAllowlist: true,
    privateAllowlist: {
      app_id: "123456789",
      bot_id: safe,
      openids: [senderSafe],
    },
  });
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    readyForSend(bot);
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: senderSafe,
      messageId: "bound-user-message",
      content: "bound",
      timestamp: "2026-08-28T10:00:00Z",
    });
    assert.equal(client.readEvents(0, 10).length, 1);
  } finally {
    await client.stop();
  }

  const mismatched = newClient({
    ordinaryPrivateEnabled: true,
    allowedPrivateOpenIds: [senderSafe],
    requirePrivateAllowlist: true,
    privateAllowlist: {
      app_id: "123456789",
      bot_id: safe,
      openids: [senderSafe],
    },
  });
  try {
    await mismatched.start();
    FakeBot.instances[0].emit("ready", { user: { id: "different-bot" } });
    assert.equal(mismatched.status().authenticated, false);
    assert.equal(mismatched.status().reason, "private_allowlist_bot_mismatch");
  } finally {
    await mismatched.stop();
  }

  const drifted = newClient({
    ordinaryPrivateEnabled: true,
    allowedPrivateOpenIds: [senderSafe, "env-only-user"],
    requirePrivateAllowlist: true,
    privateAllowlist: {
      app_id: "123456789",
      bot_id: safe,
      openids: [senderSafe],
    },
  });
  await assert.rejects(
    drifted.start(),
    /private_allowlist_config_mismatch/,
  );

  const wildcard = newClient({
    ordinaryPrivateEnabled: true,
    allowedPrivateOpenIds: [senderSafe],
    requirePrivateAllowlist: true,
    privateAllowlist: {
      app_id: "123456789",
      bot_id: safe,
      openids: ["*"],
    },
  });
  await assert.rejects(wildcard.start(), /private_allowlist_unavailable/);

  const wildcardBot = newClient({
    ordinaryPrivateEnabled: true,
    allowedPrivateOpenIds: [senderSafe],
    requirePrivateAllowlist: true,
    privateAllowlist: {
      app_id: "123456789",
      bot_id: "*",
      openids: [senderSafe],
    },
  });
  await assert.rejects(wildcardBot.start(), /private_allowlist_unavailable/);
});

test("full mode drops and never authorizes non-owner or non-allowlisted events", async () => {
  const client = newClient();
  await client.start();
  const bot = FakeBot.instances[0];
  readyForSend(bot);
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
    () =>
      client.replyAuthorizations.claim(
        safe,
        "c2c",
        "not-the-owner",
        safe,
        "a".repeat(64),
        1234,
      ),
    /invalid_reply_binding/,
  );
  await client.stop();
});

test("owner C2C remains available when ordinary C2C and group gates are omitted", async () => {
  const client = newClient({
    ordinaryPrivateEnabled: false,
    groupEnabled: false,
    allowedPrivateOpenIds: [],
    allowedGroupOpenIds: [safe],
  });
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    readyForSend(bot);
    for (let index = 0; index < 5; index += 1) client.privateGate.recordFailure();
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: senderSafe,
      messageId: "owner-message",
      content: "owner remains enabled",
      timestamp: "2026-08-28T10:00:00Z",
    });
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: "ordinary-user",
      messageId: "ordinary-message",
      content: "ordinary is disabled",
      timestamp: "2026-08-28T10:00:01Z",
    });
    bot.emit("message", {}, {
      rawEventType: "GROUP_AT_MESSAGE_CREATE",
      kind: "group",
      senderId: senderSafe,
      groupOpenid: safe,
      messageId: "group-message",
      content: "group is disabled",
      timestamp: "2026-08-28T10:00:02Z",
    });
    assert.deepEqual(
      client.readEvents(0, 10).map((event) => event.sender_id),
      [senderSafe],
    );
  } finally {
    await client.stop();
  }
});

test("ordinary C2C requires explicit switch and allowlist before enqueue", async () => {
  const ordinary = "ordinary-user";
  const client = newClient({
    ordinaryPrivateEnabled: true,
    allowedPrivateOpenIds: [ordinary],
    groupEnabled: false,
  });
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    readyForSend(bot);
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: ordinary,
      messageId: "ordinary-message",
      content: "allowed ordinary",
      timestamp: "2026-08-28T10:00:00Z",
    });
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: "unknown-user",
      messageId: "unknown-message",
      content: "must be dropped",
      timestamp: "2026-08-28T10:00:01Z",
    });
    assert.deepEqual(
      client.readEvents(0, 10).map((event) => event.sender_id),
      [ordinary],
    );
  } finally {
    await client.stop();
  }
});

test("private capture callback receives only bot-bound identities", async () => {
  const candidates = [];
  FakeBot.instances = [];
  const client = new OfficialQQClient({
    appId: "123456789",
    appSecret: "0123456789abcdef",
    enabled: true,
    captureOnly: true,
    BotClass: FakeBot,
    now: () => 1234,
    onPrivateCandidate: (openId, botId) => candidates.push({ openId, botId }),
  });
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    bot.emit("ready", { user: { id: safe } });
    bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
    bot.emit("message", {}, {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: senderSafe,
      messageId: "private-message-id",
      content: "private message body must not reach callback",
      timestamp: "2026-08-28T10:00:00Z",
    });
    assert.deepEqual(candidates, [{ openId: senderSafe, botId: safe }]);
    assert.deepEqual(client.readEvents(0, 10), [
      {
        cursor: 1,
        event_type: "C2C_MESSAGE_CREATE",
        kind: "c2c",
        received_at_ms: 1234,
      },
    ]);
  } finally {
    await client.stop();
  }
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

test("proactive send is separately gated, owner-C2C only, and omits msgId", async () => {
  const disabled = newClient();
  await disabled.start();
  readyForSend(FakeBot.instances[0]);
  await assert.rejects(
    disabled.send(
      sendRequest(disabled, {
        delivery_mode: "proactive",
        target_id: senderSafe,
        reply_message_id: null,
      }),
    ),
    /proactive_disabled/,
  );
  await disabled.stop();

  const client = newClient({ proactiveEnabled: true });
  await client.start();
  const bot = FakeBot.instances[0];
  readyForSend(bot);
  const request = sendRequest(client, {
    delivery_mode: "proactive",
    target_id: senderSafe,
    reply_message_id: null,
  });
  const first = await client.send(request);
  const repeated = await client.send(request);
  assert.equal(first.state, "sent");
  assert.deepEqual(repeated, first);
  assert.equal(bot.sent.length, 1);
  assert.deepEqual(bot.sent[0].target, { scope: "c2c", targetId: senderSafe });
  await assert.rejects(
    client.send({ ...request, idempotency_key: "other-key", target_id: safe }),
    /invalid_proactive_target/,
  );
  await client.stop();
});

test(
  "a durable proactive claim becomes UNKNOWN after process replacement without resending",
  unixOnly,
  async () => {
    const store = durableStore("higgs-official-proactive-crash-");
    const first = newClient({ deliveryStore: store, proactiveEnabled: true });
    const request = sendRequest(first, {
      delivery_mode: "proactive",
      target_id: senderSafe,
      reply_message_id: null,
    });
    assert.equal(store.claimProactive(request.idempotency_key, requestFingerprint(request)), true);

    const restoredStore = new SecureDeliveryStore(store.path, { now: () => 1234 });
    const restored = newClient({ deliveryStore: restoredStore, proactiveEnabled: true });
    await restored.start();
    const bot = FakeBot.instances[0];
    readyForSend(bot);
    const receipt = await restored.send({ ...request, generation: restored.generation });
    assert.equal(receipt.state, "unknown");
    assert.equal(bot.sent.length, 0);
    await restored.stop();
  },
);

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

test("READY without a first heartbeat ACK stays pending and times out fail-closed", async () => {
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
  assert.equal(client.status().authenticated, false);
  assert.equal(client.status().reason, "heartbeat_pending");

  now = 1101;
  client._watchGateway();

  assert.equal(fatalReason, "heartbeat_ack_timeout");
  assert.equal(client.status().authenticated, false);
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

test("a durable pre-crash send claim is recovered as UNKNOWN without another provider call", async () => {
  const storedReceipts = new Map();
  const deliveryStore = {
    appendAuthorized() {},
    read: () => [],
    baseCursor: () => 0,
    ack: (cursor) => cursor,
    get: (key) => storedReceipts.get(key) ?? null,
    put: (key, _fingerprint, receipt) => storedReceipts.set(key, receipt),
    claim: () => false,
  };
  const client = newClient({ deliveryStore });
  await client.start();
  const bot = FakeBot.instances[0];
  readyForSend(bot);

  const receipt = await client.send(sendRequest(client));

  assert.equal(receipt.state, "unknown");
  assert.equal(bot.sent.length, 0);
  await client.stop();
});

test(
  "a real durable claim survives process replacement as UNKNOWN with zero provider calls",
  unixOnly,
  async () => {
    const firstStore = durableStore("higgs-official-claim-crash-");
    firstStore.appendAuthorized(durableInbound(), 1234);
    const firstClient = newClient({ deliveryStore: firstStore });
    await firstClient.start();
    const request = sendRequest(firstClient);
    firstStore.claim(
      request.reply_message_id,
      request.kind,
      request.target_id,
      request.idempotency_key,
      requestFingerprint(request),
      1234,
    );
    await firstClient.stop();

    const restoredStore = new SecureDeliveryStore(firstStore.path, { now: () => 1235 });
    const restoredClient = newClient({ deliveryStore: restoredStore, now: () => 1235 });
    await restoredClient.start();
    const restoredBot = FakeBot.instances[0];
    readyForSend(restoredBot);
    const receipt = await restoredClient.send(sendRequest(restoredClient));

    assert.equal(receipt.state, "unknown");
    assert.equal(restoredBot.sent.length, 0);
    await restoredClient.stop();
  },
);

test(
  "a real durable receipt is reused after process replacement with one provider call total",
  unixOnly,
  async () => {
    const firstStore = durableStore("higgs-official-receipt-crash-");
    firstStore.appendAuthorized(durableInbound(), 1234);
    const firstClient = newClient({ deliveryStore: firstStore });
    await firstClient.start();
    const firstBot = FakeBot.instances[0];
    readyForSend(firstBot);
    const firstReceipt = await firstClient.send(sendRequest(firstClient));
    assert.equal(firstReceipt.state, "sent");
    assert.equal(firstBot.sent.length, 1);
    await firstClient.stop();

    const restoredStore = new SecureDeliveryStore(firstStore.path, { now: () => 1235 });
    const restoredClient = newClient({ deliveryStore: restoredStore, now: () => 1235 });
    await restoredClient.start();
    const restoredBot = FakeBot.instances[0];
    readyForSend(restoredBot);
    const restoredReceipt = await restoredClient.send(sendRequest(restoredClient));

    assert.equal(restoredReceipt.state, "sent");
    assert.equal(restoredReceipt.provider_message_id, firstReceipt.provider_message_id);
    assert.equal(restoredBot.sent.length, 0);
    await restoredClient.stop();
  },
);

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
  try {
    await client.start();
    const bot = FakeBot.instances[0];
    assert.equal(bot.options.sessionPersistence, sessionStore);
    bot.emit("resumed");
    assert.equal(client.status().authenticated, false);
    assert.equal(client.status().reason, "heartbeat_pending");
    assert.equal(client.status().bot_id, safe);
    bot.gateway.currentWs.emit("message", Buffer.from('{"op":11}'));
    assert.equal(client.status().authenticated, true);
    assert.equal(client.status().reason, "resumed");
  } finally {
    await client.stop();
  }
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
