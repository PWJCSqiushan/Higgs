import assert from "node:assert/strict";
import test from "node:test";

import {
  EventQueue,
  GROUP_AND_C2C_INTENT,
  PROTOCOL_VERSION,
  ProtocolError,
  normalizeInboundMessage,
  normalizeSendRequest,
} from "../src/protocol.mjs";

const safe = "A123_safe-value";

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
    safe,
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
      safe,
    ),
    null,
  );
});

test("event queue fails closed on a cursor gap", () => {
  const queue = new EventQueue(2);
  queue.append({ marker: 1 });
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
});
