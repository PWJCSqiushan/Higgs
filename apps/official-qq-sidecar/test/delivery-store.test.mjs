import assert from "node:assert/strict";
import {
  chmodSync,
  lstatSync,
  mkdtempSync,
  readFileSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { SecureDeliveryStore } from "../src/delivery-store.mjs";

const unixOnly = { skip: process.platform === "win32" };

function inbound(messageId = "message-id") {
  return {
    event_type: "C2C_MESSAGE_CREATE",
    kind: "c2c",
    bot_id: "bot-id",
    sender_id: "owner-id",
    group_id: null,
    message_id: messageId,
    occurred_at_ms: 1000,
    received_at_ms: 1001,
    text: "private test payload",
    attachments: [],
  };
}

function privateDirectory(prefix) {
  const directory = mkdtempSync(join(tmpdir(), prefix));
  chmodSync(directory, 0o700);
  return directory;
}

test("durable events, reply claims, and receipts survive process replacement", unixOnly, () => {
  const directory = privateDirectory("higgs-official-delivery-");
  const path = join(directory, "delivery-state.json");
  const first = new SecureDeliveryStore(path, { now: () => 1000 });
  first.appendAuthorized(inbound(), 1000);
  first.claim("message-id", "c2c", "owner-id", "reply-key", "a".repeat(64), 1001);
  first.put("reply-key", "a".repeat(64), {
    state: "sent",
    provider_message_id: "provider-id",
  });

  const restored = new SecureDeliveryStore(path, { now: () => 1002 });
  assert.equal(restored.baseCursor(), 0);
  assert.equal(restored.read(0, 32)[0].cursor, 1);
  assert.deepEqual(restored.get("reply-key", "a".repeat(64)), {
    state: "sent",
    provider_message_id: "provider-id",
  });
  assert.doesNotThrow(() =>
    restored.claim(
      "message-id",
      "c2c",
      "owner-id",
      "reply-key",
      "a".repeat(64),
      1002,
    ),
  );
  assert.equal(restored.ack(1), 1);

  const afterAck = new SecureDeliveryStore(path, { now: () => 1003 });
  assert.deepEqual(afterAck.read(0, 32), []);
  assert.equal(lstatSync(path).mode & 0o777, 0o600);
  assert.doesNotMatch(readFileSync(path, "utf8"), /cursor/u);
});

test("queue saturation and idempotency conflicts fail closed", unixOnly, () => {
  const directory = privateDirectory("higgs-official-delivery-limit-");
  const store = new SecureDeliveryStore(join(directory, "delivery-state.json"), {
    now: () => 1000,
    eventLimit: 1,
  });
  store.appendAuthorized(inbound("message-1"), 1000);
  assert.throws(() => store.appendAuthorized(inbound("message-2"), 1000), /event_queue_full/u);
  store.put("reply-key", "a".repeat(64), {
    state: "unknown",
    provider_message_id: null,
  });
  assert.throws(() => store.get("reply-key", "b".repeat(64)), /idempotency_collision/u);
});

test("unsafe or malformed delivery state is rejected", unixOnly, () => {
  const directory = privateDirectory("higgs-official-delivery-invalid-");
  const path = join(directory, "delivery-state.json");
  writeFileSync(path, "{}\n", { encoding: "utf8", mode: 0o600 });
  chmodSync(path, 0o600);
  assert.throws(() => new SecureDeliveryStore(path), /invalid_delivery_state/u);

  const target = join(directory, "target.json");
  writeFileSync(target, "{}\n", { encoding: "utf8", mode: 0o600 });
  const link = join(directory, "delivery-state-link.json");
  symlinkSync(target, link);
  assert.throws(
    () => new SecureDeliveryStore(link),
    /invalid_delivery_state_path|unsafe_delivery_state_file/u,
  );
});
