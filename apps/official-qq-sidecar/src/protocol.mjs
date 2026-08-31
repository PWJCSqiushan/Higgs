import { createHash, randomUUID } from "node:crypto";

// The sidecar envelope is versioned independently from the QQ SDK.  Version
// two adds content-free allowlist provenance to hello/status so the Agent can
// fail closed when its private-user policy drifts.
export const PROTOCOL_VERSION = 2;
export const GROUP_AND_C2C_INTENT = 1 << 25;
export const MAX_BODY_BYTES = 16 * 1024;
export const MAX_EVENT_QUEUE = 128;
export const MAX_TEXT_LENGTH = 4000;

const ID_PATTERN = /^[!-~]{1,256}$/u;
const EVENT_TYPES = new Set(["C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"]);
const KINDS = new Set(["c2c", "group"]);

export class ProtocolError extends Error {
  constructor(code, status = 400) {
    super(code);
    this.name = "ProtocolError";
    this.code = code;
    this.status = status;
  }
}

export function isSafeId(value) {
  return typeof value === "string" && ID_PATTERN.test(value);
}

function exactKeys(value, allowed) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ProtocolError("invalid_object");
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) {
      throw new ProtocolError("unknown_field");
    }
  }
}

export function normalizeSendRequest(value) {
  exactKeys(
    value,
    new Set([
      "protocol_version",
      "generation",
      "request_id",
      "idempotency_key",
      "delivery_mode",
      "kind",
      "target_id",
      "text",
      "reply_message_id",
    ]),
  );
  if (value.protocol_version !== PROTOCOL_VERSION) {
    throw new ProtocolError("protocol_version_mismatch", 409);
  }
  if (!isSafeId(value.generation) || !isSafeId(value.request_id)) {
    throw new ProtocolError("invalid_request_identity");
  }
  if (!isSafeId(value.idempotency_key) || value.idempotency_key.length > 200) {
    throw new ProtocolError("invalid_idempotency_key");
  }
  if (!KINDS.has(value.kind) || !isSafeId(value.target_id)) {
    throw new ProtocolError("invalid_target");
  }
  const deliveryMode = value.delivery_mode ?? "passive";
  if (!new Set(["passive", "proactive"]).has(deliveryMode)) {
    throw new ProtocolError("invalid_delivery_mode");
  }
  if (
    typeof value.text !== "string" ||
    value.text.length === 0 ||
    value.text.length > MAX_TEXT_LENGTH
  ) {
    throw new ProtocolError("invalid_text");
  }
  if (deliveryMode === "passive" && !isSafeId(value.reply_message_id)) {
    throw new ProtocolError("reply_message_id_required");
  }
  if (
    deliveryMode === "proactive" &&
    (value.kind !== "c2c" || value.reply_message_id !== null)
  ) {
    throw new ProtocolError("invalid_proactive_target", 403);
  }
  return Object.freeze({
    protocol_version: PROTOCOL_VERSION,
    generation: value.generation,
    request_id: value.request_id,
    idempotency_key: value.idempotency_key,
    delivery_mode: deliveryMode,
    kind: value.kind,
    target_id: value.target_id,
    text: value.text,
    reply_message_id: value.reply_message_id,
  });
}

export function normalizeEventAck(value) {
  exactKeys(value, new Set(["protocol_version", "generation", "cursor"]));
  if (value.protocol_version !== PROTOCOL_VERSION) {
    throw new ProtocolError("protocol_version_mismatch", 409);
  }
  if (!isSafeId(value.generation)) {
    throw new ProtocolError("invalid_request_identity");
  }
  if (!Number.isSafeInteger(value.cursor) || value.cursor < 0) {
    throw new ProtocolError("invalid_cursor");
  }
  return Object.freeze({
    protocol_version: PROTOCOL_VERSION,
    generation: value.generation,
    cursor: value.cursor,
  });
}

export function requestFingerprint(request) {
  return createHash("sha256")
    .update(
      JSON.stringify([
        request.kind,
        request.target_id,
        request.text,
        request.reply_message_id,
        request.delivery_mode,
      ]),
      "utf8",
    )
    .digest("hex");
}

export function normalizeInboundMessage(message, botId, receivedAt = Date.now()) {
  if (!message || typeof message !== "object") return null;
  if (!EVENT_TYPES.has(message.rawEventType)) return null;
  if (!KINDS.has(message.kind) || !isSafeId(botId)) return null;
  if (!isSafeId(message.senderId) || !isSafeId(message.messageId)) return null;
  if (message.senderId === botId) return null;
  if (
    (message.rawEventType === "C2C_MESSAGE_CREATE" && message.kind !== "c2c") ||
    (message.rawEventType === "GROUP_AT_MESSAGE_CREATE" && message.kind !== "group")
  ) {
    return null;
  }
  if (
    typeof message.content !== "string" ||
    message.content.trim().length === 0 ||
    message.content.length > MAX_TEXT_LENGTH
  ) {
    return null;
  }

  const occurredAt = Date.parse(message.timestamp);
  if (!Number.isFinite(occurredAt)) return null;
  const groupId = message.kind === "group" ? message.groupOpenid : null;
  if (message.kind === "group" && !isSafeId(groupId)) return null;
  if (message.kind === "c2c" && groupId !== null) return null;

  if (message.attachments !== undefined && !Array.isArray(message.attachments)) return null;
  const attachmentValues = message.attachments ?? [];
  if (attachmentValues.length > 8) return null;
  const attachments = [];
  for (const attachment of attachmentValues) {
    if (!attachment || typeof attachment !== "object" || Array.isArray(attachment)) return null;
    const keys = Object.keys(attachment);
    if (keys.some((key) => !new Set(["content_type", "filename", "size"]).has(key))) return null;
    if (
      typeof attachment.content_type !== "string" ||
      attachment.content_type.length === 0 ||
      attachment.content_type.length > 120
    ) {
      return null;
    }
    if (
      attachment.filename !== null &&
      attachment.filename !== undefined &&
      (typeof attachment.filename !== "string" || attachment.filename.length > 255)
    ) {
      return null;
    }
    if (
      attachment.size !== null &&
      attachment.size !== undefined &&
      (!Number.isSafeInteger(attachment.size) || attachment.size < 0)
    ) {
      return null;
    }
    attachments.push({
      content_type: attachment.content_type,
      filename: attachment.filename ?? null,
      size: attachment.size ?? null,
    });
  }

  return Object.freeze({
    event_type: message.rawEventType,
    kind: message.kind,
    bot_id: botId,
    sender_id: message.senderId,
    group_id: groupId,
    message_id: message.messageId,
    occurred_at_ms: occurredAt,
    received_at_ms: receivedAt,
    text: message.content,
    attachments,
  });
}

export class EventQueue {
  constructor(limit = MAX_EVENT_QUEUE) {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 1024) {
      throw new TypeError("invalid queue limit");
    }
    this.limit = limit;
    this.cursor = 0;
    this.events = [];
  }

  append(event) {
    this.cursor += 1;
    const stored = Object.freeze({ ...event, cursor: this.cursor });
    this.events.push(stored);
    if (this.events.length > this.limit) this.events.shift();
    return stored;
  }

  read(after, limit = 32) {
    if (!Number.isSafeInteger(after) || after < 0) {
      throw new ProtocolError("invalid_cursor");
    }
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 64) {
      throw new ProtocolError("invalid_limit");
    }
    const first = this.events[0]?.cursor ?? this.cursor + 1;
    if (after > this.cursor) {
      throw new ProtocolError("invalid_cursor");
    }
    if (after < first - 1) {
      throw new ProtocolError("cursor_gap", 409);
    }
    return this.events.filter((event) => event.cursor > after).slice(0, limit);
  }

  baseCursor() {
    const first = this.events[0];
    return first ? first.cursor - 1 : this.cursor;
  }

  ack(cursor) {
    if (!Number.isSafeInteger(cursor) || cursor < this.baseCursor() || cursor > this.cursor) {
      throw new ProtocolError("invalid_cursor");
    }
    this.events = this.events.filter((event) => event.cursor > cursor);
    return cursor;
  }
}

export class ReceiptCache {
  constructor(limit = 256) {
    this.limit = limit;
    this.items = new Map();
  }

  get(key, fingerprint) {
    const found = this.items.get(key);
    if (!found) return null;
    if (found.fingerprint !== fingerprint) {
      throw new ProtocolError("idempotency_collision", 409);
    }
    return found.receipt;
  }

  put(key, fingerprint, receipt) {
    this.items.set(key, { fingerprint, receipt });
    while (this.items.size > this.limit) {
      this.items.delete(this.items.keys().next().value);
    }
  }

  claimProactive(key, fingerprint) {
    const found = this.items.get(key);
    if (found) {
      if (found.fingerprint !== fingerprint) {
        throw new ProtocolError("idempotency_collision", 409);
      }
      return false;
    }
    this.put(key, fingerprint, { state: "unknown", provider_message_id: null });
    return true;
  }
}

export class ReplyAuthorizationCache {
  constructor(limit = 256, ttlMs = 15 * 60 * 1000) {
    this.limit = limit;
    this.ttlMs = ttlMs;
    this.items = new Map();
  }

  authorize(messageId, kind, targetId, now = Date.now()) {
    if (!isSafeId(messageId) || !KINDS.has(kind) || !isSafeId(targetId)) return;
    const existing = this.items.get(messageId);
    if (existing) {
      if (existing.kind !== kind || existing.targetId !== targetId) {
        throw new ProtocolError("invalid_reply_binding", 403);
      }
      // Duplicate delivery must not renew an expired authorization or clear
      // the idempotency key that already claimed it.
      return;
    }
    this.items.set(messageId, {
      kind,
      targetId,
      expiresAt: now + this.ttlMs,
      claimedBy: null,
      claimedFingerprint: null,
    });
    while (this.items.size > this.limit) {
      this.items.delete(this.items.keys().next().value);
    }
  }

  claim(messageId, kind, targetId, idempotencyKey, fingerprint, now = Date.now()) {
    const item = this.items.get(messageId);
    if (!item || item.expiresAt < now || !/^[0-9a-f]{64}$/u.test(fingerprint)) {
      throw new ProtocolError("invalid_reply_binding", 403);
    }
    if (item.kind !== kind || item.targetId !== targetId) {
      throw new ProtocolError("invalid_reply_binding", 403);
    }
    if (item.claimedBy !== null) {
      if (item.claimedBy !== idempotencyKey || item.claimedFingerprint !== fingerprint) {
        throw new ProtocolError("idempotency_collision", 409);
      }
      return false;
    }
    item.claimedBy = idempotencyKey;
    item.claimedFingerprint = fingerprint;
    return true;
  }
}

export class ChannelGate {
  constructor({
    ratePerMinute,
    failureLimit,
    cooldownSeconds,
    now = () => Date.now(),
  }) {
    if (
      !Number.isSafeInteger(ratePerMinute) ||
      ratePerMinute < 1 ||
      !Number.isSafeInteger(failureLimit) ||
      failureLimit < 1 ||
      !Number.isSafeInteger(cooldownSeconds) ||
      cooldownSeconds < 1
    ) {
      throw new TypeError("invalid channel gate limits");
    }
    this.ratePerMinute = ratePerMinute;
    this.failureLimit = failureLimit;
    this.cooldownMs = cooldownSeconds * 1000;
    this.now = now;
    this.events = [];
    this.failures = 0;
    this.openUntil = 0;
  }

  allow(now = this.now()) {
    if (!Number.isSafeInteger(now) || now < 0) return false;
    if (now < this.openUntil) return false;
    if (this.openUntil !== 0) {
      this.openUntil = 0;
      this.failures = 0;
    }
    const cutoff = now - 60_000;
    this.events = this.events.filter((value) => value > cutoff);
    if (this.events.length >= this.ratePerMinute) return false;
    this.events.push(now);
    return true;
  }

  recordFailure(now = this.now()) {
    if (!Number.isSafeInteger(now) || now < 0) return;
    this.failures += 1;
    if (this.failures >= this.failureLimit) this.openUntil = now + this.cooldownMs;
  }

  recordSuccess() {
    this.failures = 0;
  }

  isOpen(now = this.now()) {
    return Number.isSafeInteger(now) && now >= 0 && now < this.openUntil;
  }
}

export function newGeneration() {
  return randomUUID();
}
