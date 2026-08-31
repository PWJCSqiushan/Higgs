import assert from "node:assert/strict";
import test from "node:test";

import {
  EventQueue,
  ChannelGate,
  GROUP_AND_C2C_INTENT,
  PROTOCOL_VERSION,
  ProtocolError,
  ReplyAuthorizationCache,
  normalizeInboundMessage,
  normalizeSendRequest,
} from "../src/protocol.mjs";

const safe = "A123_safe-value";
const botSafe = "B456_bot-value";

test("uses the exact group and C2C intent", () => {
  assert.equal(GROUP_AND_C2C_INTENT, 33_554_432);
});

test("channel gate bounds ordinary traffic and opens after repeated failures", () => {
  let now = 1_000;
  const gate = new ChannelGate({
    ratePerMinute: 2,
    failureLimit: 2,
    cooldownSeconds: 10,
    now: () => now,
  });
  assert.equal(gate.allow(), true);
  assert.equal(gate.allow(), true);
  assert.equal(gate.allow(), false);
  gate.recordFailure();
  gate.recordFailure();
  assert.equal(gate.isOpen(), true);
  assert.equal(gate.allow(), false);
  now = 62_001;
  assert.equal(gate.isOpen(), false);
  assert.equal(gate.allow(), true);
});

test("channel gate success clears the failure circuit without widening rate limits", () => {
  const gate = new ChannelGate({
    ratePerMinute: 3,
    failureLimit: 2,
    cooldownSeconds: 10,
    now: () => 1_000,
  });
  gate.recordFailure();
  gate.recordSuccess();
  gate.recordFailure();
  assert.equal(gate.isOpen(), false);
});

test("send requests separate passive replies from owner-C2C proactive sends", () => {
  const request = normalizeSendRequest({
    protocol_version: PROTOCOL_VERSION,
    generation: safe,
    request_id: safe,
    idempotency_key: safe,
    kind: "c2c",
    target_id: safe,
    text: "hello",
    reply_message_id: safe,
  });
  assert.equal(request.kind, "c2c");
  assert.equal(request.delivery_mode, "passive");
  assert.throws(
    () => normalizeSendRequest({ ...request, reply_message_id: "" }),
    /reply_message_id_required/,
  );
  assert.throws(() => normalizeSendRequest({ ...request, extra: true }), /unknown_field/);
  const proactive = normalizeSendRequest({
    ...request,
    delivery_mode: "proactive",
    reply_message_id: null,
  });
  assert.equal(proactive.delivery_mode, "proactive");
  assert.throws(
    () => normalizeSendRequest({ ...proactive, kind: "group" }),
    /invalid_proactive_target/,
  );
  assert.throws(
    () => normalizeSendRequest({ ...request, protocol_version: PROTOCOL_VERSION - 1 }),
    /protocol_version_mismatch/,
  );
});

test("inbound normalization accepts only C2C and group-at events", () => {
  const c2c = normalizeInboundMessage(
    {
      rawEventType: "C2C_MESSAGE_CREATE",
      kind: "c2c",
      senderId: safe,
      messageId: safe,
      content: "hello",
      timestamp: "2026-08-28T10:00:00Z",
    },
    botSafe,
    100,
  );
  assert.equal(c2c.group_id, null);
  assert.equal(c2c.received_at_ms, 100);
  assert.equal(
    normalizeInboundMessage(
      {
        rawEventType: "GROUP_MESSAGE_CREATE",
        kind: "group",
        senderId: safe,
        messageId: safe,
        groupOpenid: safe,
        content: "hello",
        timestamp: "2026-08-28T10:00:00Z",
      },
      botSafe,
    ),
    null,
  );
  assert.equal(
    normalizeInboundMessage(
      {
        rawEventType: "C2C_MESSAGE_CREATE",
        kind: "group",
        senderId: safe,
        messageId: safe,
        groupOpenid: safe,
        content: "hello",
        timestamp: "2026-08-28T10:00:00Z",
      },
      botSafe,
    ),
    null,
  );
  assert.equal(
    normalizeInboundMessage(
      {
        rawEventType: "C2C_MESSAGE_CREATE",
        kind: "c2c",
        senderId: botSafe,
        messageId: safe,
        content: "hello",
        timestamp: "2026-08-28T10:00:00Z",
      },
      botSafe,
    ),
    null,
  );
});

test("event queue fails closed on a cursor gap", () => {
  const queue = new EventQueue(2);
  queue.append({ marker: 1, cursor: 999 });
  queue.append({ marker: 2 });
  queue.append({ marker: 3 });
  assert.throws(
    () => queue.read(0),
    (error) => error instanceof ProtocolError && error.code === "cursor_gap",
  );
  assert.deepEqual(
    queue.read(1).map((event) => event.marker),
    [2, 3],
  );
  assert.equal(queue.read(1)[0].cursor, 2);
  assert.throws(
    () => queue.read(4),
    (error) => error instanceof ProtocolError && error.code === "invalid_cursor",
  );
});

test("duplicate inbound events cannot renew or reset a reply authorization", () => {
  const cache = new ReplyAuthorizationCache(10, 100);
  cache.authorize(safe, "c2c", safe, 1000);
  cache.claim(safe, "c2c", safe, "first-key", "a".repeat(64), 1001);
  cache.authorize(safe, "c2c", safe, 1050);
  assert.throws(
    () => cache.claim(safe, "c2c", safe, "second-key", "b".repeat(64), 1051),
    /idempotency_collision/,
  );
  cache.authorize(safe, "c2c", safe, 1200);
  assert.throws(
    () => cache.claim(safe, "c2c", safe, "first-key", "a".repeat(64), 1201),
    /invalid_reply_binding/,
  );
  assert.throws(
    () => cache.authorize(safe, "group", safe, 1050),
    /invalid_reply_binding/,
  );
});
