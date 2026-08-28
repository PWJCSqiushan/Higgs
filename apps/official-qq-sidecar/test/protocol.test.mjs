import assert from "node:assert/strict";
import test from "node:test";

import {
  EventQueue,
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

test("send requests are versioned, passive-only, and reject unknown fields", () => {
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
  assert.throws(
    () => normalizeSendRequest({ ...request, reply_message_id: "" }),
    /reply_message_id_required/,
  );
  assert.throws(() => normalizeSendRequest({ ...request, extra: true }), /unknown_field/);
  assert.throws(
    () => normalizeSendRequest({ ...request, protocol_version: 2 }),
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
  cache.claim(safe, "c2c", safe, "first-key", 1001);
  cache.authorize(safe, "c2c", safe, 1050);
  assert.throws(
    () => cache.claim(safe, "c2c", safe, "second-key", 1051),
    /invalid_reply_binding/,
  );
  cache.authorize(safe, "c2c", safe, 1200);
  assert.throws(
    () => cache.claim(safe, "c2c", safe, "first-key", 1201),
    /invalid_reply_binding/,
  );
  assert.throws(
    () => cache.authorize(safe, "group", safe, 1050),
    /invalid_reply_binding/,
  );
});
