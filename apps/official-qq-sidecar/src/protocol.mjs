import { createHash, randomUUID } from "node:crypto";

export const PROTOCOL_VERSION = 1;
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
  if (
    typeof value.text !== "string" ||
    value.text.length === 0 ||
    value.text.length > MAX_TEXT_LENGTH
  ) {
    throw new ProtocolError("invalid_text");
  }
  if (!isSafeId(value.reply_message_id)) {
    throw new ProtocolError("reply_message_id_required");
  }
  return Object.freeze({
    protocol_version: PROTOCOL_VERSION,
    generation: value.generation,
    request_id: value.request_id,
    idempotency_key: value.idempotency_key,
    kind: value.kind,
    target_id: value.target_id,
    text: value.text,
    reply_message_id: value.reply_message_id,
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
  if (typeof message.content !== "string" || message.content.length > MAX_TEXT_LENGTH) return null;

  const occurredAt = Date.parse(message.timestamp);
  if (!Number.isFinite(occurredAt)) return null;
  const groupId = message.kind === "group" ? message.groupOpenid : null;
  if (message.kind === "group" && !isSafeId(groupId)) return null;
  if (message.kind === "c2c" && groupId !== null) return null;

  const attachments = Array.isArray(message.attachments)
    ? message.attachments.slice(0, 8).map((attachment) => ({
        content_type:
          typeof attachment?.content_type === "string"
            ? attachment.content_type.slice(0, 120)
            : "application/octet-stream",
        filename:
          typeof attachment?.filename === "string" ? attachment.filename.slice(0, 255) : null,
        size:
          Number.isSafeInteger(attachment?.size) && attachment.size >= 0 ? attachment.size : null,
      }))
    : [];

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
    const stored = Object.freeze({ cursor: this.cursor, ...event });
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
    if (after < first - 1) {
      throw new ProtocolError("cursor_gap", 409);
    }
    return this.events.filter((event) => event.cursor > after).slice(0, limit);
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
}

export function newGeneration() {
  return randomUUID();
}
