import { randomUUID } from "node:crypto";
import {
  closeSync,
  fchmodSync,
  fsyncSync,
  fstatSync,
  lstatSync,
  openSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, isAbsolute } from "node:path";

import { ProtocolError, isSafeId } from "./protocol.mjs";

const VERSION = 1;
const MAX_FILE_BYTES = 4 * 1024 * 1024;
const KINDS = new Set(["c2c", "group"]);
const RECEIPT_STATES = new Set(["sent", "unknown"]);

function exactKeys(value, keys) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.size &&
    Object.keys(value).every((key) => keys.has(key))
  );
}

function safeInteger(value, minimum = 0) {
  return Number.isSafeInteger(value) && value >= minimum;
}

function validateEvent(event) {
  if (
    !exactKeys(
      event,
      new Set([
        "event_type",
        "kind",
        "bot_id",
        "sender_id",
        "group_id",
        "message_id",
        "occurred_at_ms",
        "received_at_ms",
        "text",
        "attachments",
      ]),
    ) ||
    !new Set(["C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"]).has(event.event_type) ||
    !KINDS.has(event.kind) ||
    !isSafeId(event.bot_id) ||
    !isSafeId(event.sender_id) ||
    !isSafeId(event.message_id) ||
    !safeInteger(event.occurred_at_ms) ||
    !safeInteger(event.received_at_ms) ||
    typeof event.text !== "string" ||
    event.text.length > 4000 ||
    !Array.isArray(event.attachments) ||
    event.attachments.length > 8
  ) {
    throw new Error("invalid_delivery_state");
  }
  if (
    (event.kind === "c2c" && event.group_id !== null) ||
    (event.kind === "group" && !isSafeId(event.group_id))
  ) {
    throw new Error("invalid_delivery_state");
  }
  for (const attachment of event.attachments) {
    if (
      !exactKeys(attachment, new Set(["content_type", "filename", "size"])) ||
      typeof attachment.content_type !== "string" ||
      attachment.content_type.length < 1 ||
      attachment.content_type.length > 120 ||
      (attachment.filename !== null &&
        (typeof attachment.filename !== "string" || attachment.filename.length > 255)) ||
      (attachment.size !== null && !safeInteger(attachment.size))
    ) {
      throw new Error("invalid_delivery_state");
    }
  }
}

function validateReceipt(receipt) {
  if (
    !exactKeys(
      receipt,
      new Set(["key", "fingerprint", "state", "provider_message_id"]),
    ) ||
    !isSafeId(receipt.key) ||
    receipt.key.length > 200 ||
    !/^[0-9a-f]{64}$/u.test(receipt.fingerprint) ||
    !RECEIPT_STATES.has(receipt.state) ||
    (receipt.provider_message_id !== null && !isSafeId(receipt.provider_message_id)) ||
    (receipt.state === "sent" && receipt.provider_message_id === null)
  ) {
    throw new Error("invalid_delivery_state");
  }
}

function validateAuthorization(authorization) {
  if (
    !exactKeys(
      authorization,
      new Set([
        "message_id",
        "kind",
        "target_id",
        "expires_at_ms",
        "claimed_by",
        "claimed_fingerprint",
      ]),
    ) ||
    !isSafeId(authorization.message_id) ||
    !KINDS.has(authorization.kind) ||
    !isSafeId(authorization.target_id) ||
    !safeInteger(authorization.expires_at_ms) ||
    (authorization.claimed_by !== null &&
      (!isSafeId(authorization.claimed_by) || authorization.claimed_by.length > 200)) ||
    (authorization.claimed_fingerprint !== null &&
      !/^[0-9a-f]{64}$/u.test(authorization.claimed_fingerprint)) ||
    ((authorization.claimed_by === null) !== (authorization.claimed_fingerprint === null))
  ) {
    throw new Error("invalid_delivery_state");
  }
}

export class SecureDeliveryStore {
  constructor(
    path,
    {
      now = () => Date.now(),
      eventLimit = 128,
      receiptLimit = 1024,
      authorizationLimit = 256,
      authorizationTtlMs = 15 * 60 * 1000,
      onFailure = () => {},
    } = {},
  ) {
    if (!isAbsolute(path) || basename(path) !== "delivery-state.json") {
      throw new Error("invalid_delivery_state_path");
    }
    if (
      !safeInteger(eventLimit, 1) ||
      eventLimit > 1024 ||
      !safeInteger(receiptLimit, 1) ||
      receiptLimit > 4096 ||
      !safeInteger(authorizationLimit, 1) ||
      authorizationLimit > 1024 ||
      !safeInteger(authorizationTtlMs, 1000)
    ) {
      throw new Error("invalid_delivery_state_limits");
    }
    this.path = path;
    this.now = now;
    this.eventLimit = eventLimit;
    this.receiptLimit = receiptLimit;
    this.authorizationLimit = authorizationLimit;
    this.authorizationTtlMs = authorizationTtlMs;
    this.onFailure = onFailure;
    this.cursor = 0;
    this.ackedCursor = 0;
    this.events = [];
    this.receipts = new Map();
    this.authorizations = new Map();
    this._guard(() => this._load());
  }

  _expectedUid() {
    return typeof process.getuid === "function" ? process.getuid() : null;
  }

  _validateDirectory() {
    const stat = lstatSync(dirname(this.path));
    const expectedUid = this._expectedUid();
    if (
      stat.isSymbolicLink() ||
      !stat.isDirectory() ||
      (expectedUid !== null && stat.uid !== expectedUid) ||
      (stat.mode & 0o777) !== 0o700
    ) {
      throw new Error("unsafe_delivery_state_directory");
    }
  }

  _empty() {
    return { version: VERSION, events: [], receipts: [], authorizations: [] };
  }

  _read() {
    this._validateDirectory();
    let stat;
    try {
      stat = lstatSync(this.path);
    } catch (error) {
      if (error?.code === "ENOENT") return this._empty();
      throw error;
    }
    const expectedUid = this._expectedUid();
    if (
      stat.isSymbolicLink() ||
      !stat.isFile() ||
      stat.size > MAX_FILE_BYTES ||
      (expectedUid !== null && stat.uid !== expectedUid) ||
      (stat.mode & 0o777) !== 0o600
    ) {
      throw new Error("unsafe_delivery_state_file");
    }
    const value = JSON.parse(readFileSync(this.path, "utf8"));
    if (
      !exactKeys(value, new Set(["version", "events", "receipts", "authorizations"])) ||
      value.version !== VERSION ||
      !Array.isArray(value.events) ||
      value.events.length > this.eventLimit ||
      !Array.isArray(value.receipts) ||
      value.receipts.length > this.receiptLimit ||
      !Array.isArray(value.authorizations) ||
      value.authorizations.length > this.authorizationLimit
    ) {
      throw new Error("invalid_delivery_state");
    }
    value.events.forEach(validateEvent);
    value.receipts.forEach(validateReceipt);
    value.authorizations.forEach(validateAuthorization);
    return value;
  }

  _snapshot() {
    return {
      version: VERSION,
      events: this.events.map(({ cursor: _cursor, ...event }) => event),
      receipts: [...this.receipts.entries()].map(([key, value]) => ({ key, ...value })),
      authorizations: [...this.authorizations.entries()].map(([message_id, value]) => ({
        message_id,
        ...value,
      })),
    };
  }

  _write() {
    this._validateDirectory();
    const temporary = `${this.path}.${process.pid}.${randomUUID()}.tmp`;
    const fd = openSync(temporary, "wx", 0o600);
    try {
      fchmodSync(fd, 0o600);
      writeFileSync(fd, `${JSON.stringify(this._snapshot())}\n`, "utf8");
      fsyncSync(fd);
      const stat = fstatSync(fd);
      if ((stat.mode & 0o777) !== 0o600 || stat.size > MAX_FILE_BYTES) {
        throw new Error("unsafe_delivery_state_file");
      }
    } finally {
      closeSync(fd);
    }
    renameSync(temporary, this.path);
    let directoryFd = null;
    try {
      directoryFd = openSync(dirname(this.path), "r");
      fsyncSync(directoryFd);
    } finally {
      if (directoryFd !== null) closeSync(directoryFd);
    }
  }

  _guard(operation) {
    try {
      return operation();
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }

  _load() {
    const value = this._read();
    const now = this.now();
    this.events = value.events.map((event, index) =>
      Object.freeze({ ...event, cursor: index + 1 }),
    );
    this.cursor = this.events.length;
    this.ackedCursor = 0;
    for (const receipt of value.receipts) {
      const { key, ...stored } = receipt;
      if (this.receipts.has(key)) throw new Error("invalid_delivery_state");
      this.receipts.set(key, Object.freeze(stored));
    }
    for (const authorization of value.authorizations) {
      const { message_id: messageId, ...stored } = authorization;
      if (this.authorizations.has(messageId)) throw new Error("invalid_delivery_state");
      if (stored.expires_at_ms >= now) this.authorizations.set(messageId, stored);
    }
    if (this.authorizations.size !== value.authorizations.length) this._write();
  }

  baseCursor() {
    return this.ackedCursor;
  }

  _pruneAuthorizations(now) {
    for (const [messageId, authorization] of this.authorizations) {
      if (authorization.expires_at_ms < now) this.authorizations.delete(messageId);
    }
  }

  appendAuthorized(event, now = this.now()) {
    return this._guard(() => {
      validateEvent(event);
      this._pruneAuthorizations(now);
      if (this.events.length >= this.eventLimit) {
        throw new ProtocolError("event_queue_full", 503);
      }
      const targetId = event.kind === "group" ? event.group_id : event.sender_id;
      const existing = this.authorizations.get(event.message_id);
      if (
        existing &&
        (existing.kind !== event.kind || existing.target_id !== targetId)
      ) {
        throw new ProtocolError("invalid_reply_binding", 403);
      }
      if (!existing) {
        if (this.authorizations.size >= this.authorizationLimit) {
          throw new ProtocolError("authorization_queue_full", 503);
        }
        this.authorizations.set(event.message_id, {
          kind: event.kind,
          target_id: targetId,
          expires_at_ms: now + this.authorizationTtlMs,
          claimed_by: null,
          claimed_fingerprint: null,
        });
      }
      this.cursor += 1;
      const stored = Object.freeze({ ...event, cursor: this.cursor });
      this.events.push(stored);
      this._write();
      return stored;
    });
  }

  read(after, limit = 32) {
    if (!safeInteger(after) || !safeInteger(limit, 1) || limit > 64) {
      throw new ProtocolError("invalid_cursor");
    }
    if (after < this.ackedCursor || after > this.cursor) {
      throw new ProtocolError("invalid_cursor");
    }
    return this.events.filter((event) => event.cursor > after).slice(0, limit);
  }

  ack(cursor) {
    return this._guard(() => {
      if (!safeInteger(cursor) || cursor < this.ackedCursor || cursor > this.cursor) {
        throw new ProtocolError("invalid_cursor");
      }
      this.events = this.events.filter((event) => event.cursor > cursor);
      this.ackedCursor = cursor;
      this._write();
      return this.ackedCursor;
    });
  }

  get(key, fingerprint) {
    const found = this.receipts.get(key);
    if (!found) return null;
    if (found.fingerprint !== fingerprint) {
      throw new ProtocolError("idempotency_collision", 409);
    }
    return Object.freeze({
      state: found.state,
      provider_message_id: found.provider_message_id,
    });
  }

  put(key, fingerprint, receipt) {
    return this._guard(() => {
      validateReceipt({ key, fingerprint, ...receipt });
      this.receipts.set(
        key,
        Object.freeze({
          fingerprint,
          state: receipt.state,
          provider_message_id: receipt.provider_message_id,
        }),
      );
      while (this.receipts.size > this.receiptLimit) {
        this.receipts.delete(this.receipts.keys().next().value);
      }
      this._write();
    });
  }

  claimProactive(key, fingerprint) {
    return this._guard(() => {
      if (!isSafeId(key) || key.length > 200 || !/^[0-9a-f]{64}$/u.test(fingerprint)) {
        throw new ProtocolError("invalid_idempotency_key");
      }
      const found = this.receipts.get(key);
      if (found) {
        if (found.fingerprint !== fingerprint) {
          throw new ProtocolError("idempotency_collision", 409);
        }
        return false;
      }
+      this.receipts.set(
        key,
        Object.freeze({
          fingerprint,
          state: "unknown",
          provider_message_id: null,
        }),
      );
      while (this.receipts.size > this.receiptLimit) {
        this.receipts.delete(this.receipts.keys().next().value);
      }
      this._write();
      return true;
    });
  }

  claim(messageId, kind, targetId, idempotencyKey, fingerprint, now = this.now()) {
    return this._guard(() => {
      this._pruneAuthorizations(now);
      const item = this.authorizations.get(messageId);
      if (!item || item.expires_at_ms < now || !/^[0-9a-f]{64}$/u.test(fingerprint)) {
        throw new ProtocolError("invalid_reply_binding", 403);
      }
      if (item.kind !== kind || item.target_id !== targetId) {
        throw new ProtocolError("invalid_reply_binding", 403);
      }
      if (item.claimed_by !== null) {
        if (item.claimed_by !== idempotencyKey || item.claimed_fingerprint !== fingerprint) {
          throw new ProtocolError("idempotency_collision", 409);
        }
        return false;
      }
      item.claimed_by = idempotencyKey;
      item.claimed_fingerprint = fingerprint;
      this._write();
      return true;
    });
  }
}
