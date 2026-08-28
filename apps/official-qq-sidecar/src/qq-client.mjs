import { QQBot } from "@tencent-connect/qqbot-nodejs";
import { readFileSync } from "node:fs";

import {
  EventQueue,
  GROUP_AND_C2C_INTENT,
  ProtocolError,
  ReceiptCache,
  ReplyAuthorizationCache,
  isSafeId,
  newGeneration,
  normalizeInboundMessage,
  requestFingerprint,
} from "./protocol.mjs";

const noopLogger = Object.freeze({
  debug() {},
  info() {},
  warn() {},
  error() {},
});

const HEARTBEAT_ACK = 11;
const INVALID_SESSION = 9;
const DEFAULT_ACK_TIMEOUT_MS = 90_000;
const DEFAULT_RECONNECT_WINDOW_MS = 10 * 60_000;
const DEFAULT_MAX_RECONNECTS = 5;
const DEFAULT_SEND_TIMEOUT_MS = 10_000;
const PINNED_SDK_VERSION = "1.0.4";

const sdkPackage = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.resolve("@tencent-connect/qqbot-nodejs")), "utf8"),
);
if (sdkPackage?.version !== PINNED_SDK_VERSION) {
  throw new Error("unsupported_official_qq_sdk_version");
}

function readyBotId(value) {
  if (!value || typeof value !== "object") return null;
  const user = value.user;
  if (!user || typeof user !== "object") return null;
  return isSafeId(user.id) ? user.id : null;
}

function boundedReason(value) {
  const allowed = new Set([
    "disabled",
    "starting",
    "ready",
    "resumed",
    "ready_identity_invalid",
    "gateway_error",
    "gateway_reconnecting",
    "gateway_stopped",
    "heartbeat_ack_timeout",
    "reconnect_budget_exhausted",
    "session_store_error",
    "owner_bind_error",
    "protocol_error",
    "stopped",
  ]);
  return allowed.has(value) ? value : "gateway_error";
}

export class OfficialQQClient {
  constructor({
    appId,
    appSecret,
    enabled = false,
    captureOnly = true,
    BotClass = QQBot,
    now = () => Date.now(),
    watchdogIntervalMs = 1000,
    heartbeatAckTimeoutMs = DEFAULT_ACK_TIMEOUT_MS,
    reconnectWindowMs = DEFAULT_RECONNECT_WINDOW_MS,
    maxReconnects = DEFAULT_MAX_RECONNECTS,
    sendTimeoutMs = DEFAULT_SEND_TIMEOUT_MS,
    ownerOpenId = null,
    allowedGroupOpenIds = [],
    onOwnerCandidate = null,
    onFatal = () => {},
    sessionStore = null,
  }) {
    this.appId = appId;
    this.appSecret = appSecret;
    this.enabled = enabled;
    this.captureOnly = captureOnly;
    this.BotClass = BotClass;
    this.now = now;
    this.watchdogIntervalMs = watchdogIntervalMs;
    this.heartbeatAckTimeoutMs = heartbeatAckTimeoutMs;
    this.reconnectWindowMs = reconnectWindowMs;
    this.maxReconnects = maxReconnects;
    this.sendTimeoutMs = sendTimeoutMs;
    this.ownerOpenId = ownerOpenId;
    this.allowedGroupOpenIds = new Set(allowedGroupOpenIds);
    this.onOwnerCandidate = onOwnerCandidate;
    this.onFatal = onFatal;
    this.sessionStore = sessionStore;
    this.generation = newGeneration();
    this.bot = null;
    this.startTask = null;
    this.events = new EventQueue();
    this.receipts = new ReceiptCache();
    this.replyAuthorizations = new ReplyAuthorizationCache();
    this.pendingSends = new Map();
    this.watchdogTimer = null;
    this.observedWs = null;
    this.readyAtMs = null;
    this.connectDeadlineAtMs = null;
    this.closeTimes = [];
    this.fatal = false;
    this.state = {
      configured: Boolean(appId && appSecret),
      gateway_connected: false,
      authenticated: false,
      bot_id: null,
      last_event_at_ms: null,
      last_heartbeat_ack_at_ms: null,
      heartbeat_ack_observable: false,
      reason: enabled ? "starting" : "disabled",
    };
  }

  status() {
    return Object.freeze({
      generation: this.generation,
      ...this.state,
      capture_only: this.captureOnly,
      bot_id: this.captureOnly ? null : this.state.bot_id,
      reason: boundedReason(this.state.reason),
    });
  }

  _failFatal(reason) {
    if (this.fatal) return;
    this.fatal = true;
    this.state.gateway_connected = false;
    this.state.authenticated = false;
    this.state.reason = boundedReason(reason);
    this.bot?.stop();
    this.onFatal(this.state.reason);
  }

  _attachGatewaySocket() {
    const gateway = this.bot?.gateway;
    const ws = gateway?.currentWs;
    if (!ws || typeof ws.on !== "function") return false;
    if (ws === this.observedWs) return true;
    this.observedWs = ws;
    this.state.gateway_connected = false;
    this.state.authenticated = false;
    this.state.last_heartbeat_ack_at_ms = null;
    this.state.heartbeat_ack_observable = true;
    ws.on("message", (data) => {
      let payload;
      try {
        payload = JSON.parse(Buffer.isBuffer(data) ? data.toString("utf8") : String(data));
      } catch {
        // The SDK remains the protocol parser. This observer extracts only
        // the two control frames needed for fail-closed supervision.
        return;
      }
      if (payload?.op === HEARTBEAT_ACK) {
        this.state.last_heartbeat_ack_at_ms = this.now();
        try {
          this.sessionStore?.touch();
        } catch {
          this._failFatal("session_store_error");
        }
      } else if (payload?.op === INVALID_SESSION && typeof payload?.d !== "boolean") {
        this._failFatal("protocol_error");
      }
    });
    ws.on("close", () => {
      if (this.observedWs !== ws) return;
      this.state.gateway_connected = false;
      this.state.authenticated = false;
      this.state.reason = "gateway_reconnecting";
      this.readyAtMs = null;
      this.connectDeadlineAtMs = this.now() + 120_000;
      const cutoff = this.now() - this.reconnectWindowMs;
      this.closeTimes = this.closeTimes.filter((value) => value >= cutoff);
      this.closeTimes.push(this.now());
      if (this.closeTimes.length >= this.maxReconnects) {
        this._failFatal("reconnect_budget_exhausted");
      }
    });
    return true;
  }

  _watchGateway() {
    if (!this.bot || this.fatal) return;
    const socketAttached = this._attachGatewaySocket();
    if (this.state.authenticated && !socketAttached) {
      this._failFatal("gateway_error");
      return;
    }
    const gateway = this.bot.gateway;
    if (gateway?.reconnect?.isExhausted?.()) {
      this._failFatal("reconnect_budget_exhausted");
      return;
    }
    if (
      !this.state.authenticated &&
      this.connectDeadlineAtMs !== null &&
      this.now() > this.connectDeadlineAtMs
    ) {
      this._failFatal("gateway_error");
      return;
    }
    if (!this.state.authenticated || this.readyAtMs === null) return;
    const latest = this.state.last_heartbeat_ack_at_ms ?? this.readyAtMs;
    if (this.now() - latest > this.heartbeatAckTimeoutMs) {
      this._failFatal("heartbeat_ack_timeout");
    }
  }

  async start() {
    if (!this.enabled) return;
    if (!this.state.configured) throw new ProtocolError("sidecar_not_configured", 503);
    if (this.bot) throw new ProtocolError("sidecar_already_started", 409);

    const bot = new this.BotClass({
      appId: this.appId,
      appSecret: this.appSecret,
      accountId: "higgs-official",
      intents: GROUP_AND_C2C_INTENT,
      logger: noopLogger,
      markdownSupport: false,
      tokenPrefetch: "sync",
      transport: "websocket",
      sessionPersistence: this.sessionStore ?? undefined,
    });
    this.bot = bot;
    this.state.reason = "starting";
    this.connectDeadlineAtMs = this.now() + 120_000;
    this.watchdogTimer = setInterval(() => this._watchGateway(), this.watchdogIntervalMs);

    bot.on("ready", (data) => {
      if (!this._attachGatewaySocket()) {
        this._failFatal("gateway_error");
        return;
      }
      const botId = readyBotId(data);
      if (!botId) {
        this.state.bot_id = null;
        this._failFatal("ready_identity_invalid");
        return;
      }
      const persistedBotId = this.sessionStore?.getBotId();
      if (persistedBotId && persistedBotId !== botId) {
        this.sessionStore?.clear();
        this._failFatal("ready_identity_invalid");
        return;
      }
      this.state.gateway_connected = true;
      this.state.authenticated = true;
      this.state.bot_id = botId;
      try {
        this.sessionStore?.saveBotId(botId);
      } catch {
        this._failFatal("session_store_error");
        return;
      }
      this.state.reason = "ready";
      this.readyAtMs = this.now();
      this.connectDeadlineAtMs = null;
    });
    bot.on("resumed", () => {
      if (!this._attachGatewaySocket()) {
        this._failFatal("gateway_error");
        return;
      }
      const restoredBotId = this.state.bot_id ?? this.sessionStore?.getBotId();
      if (!isSafeId(restoredBotId)) {
        this._failFatal("ready_identity_invalid");
        return;
      }
      this.state.gateway_connected = true;
      this.state.authenticated = true;
      this.state.bot_id = restoredBotId;
      this.state.reason = "resumed";
      this.readyAtMs = this.now();
      this.connectDeadlineAtMs = null;
    });
    bot.on("error", () => {
      this.state.gateway_connected = false;
      this.state.authenticated = false;
      this.state.reason = "gateway_error";
      this.readyAtMs = null;
      this.connectDeadlineAtMs = this.now() + 30_000;
    });
    bot.on("message", (_context, message) => {
      if (!this.state.authenticated || !isSafeId(this.state.bot_id)) return;
      const normalized = normalizeInboundMessage(message, this.state.bot_id, this.now());
      if (!normalized) return;
      if (
        this.captureOnly &&
        normalized.kind === "c2c" &&
        typeof this.onOwnerCandidate === "function"
      ) {
        try {
          this.onOwnerCandidate(normalized.sender_id);
        } catch {
          this._failFatal("owner_bind_error");
          return;
        }
      }
      if (
        !this.captureOnly &&
        ((normalized.kind === "c2c" && normalized.sender_id !== this.ownerOpenId) ||
          (normalized.kind === "group" && !this.allowedGroupOpenIds.has(normalized.group_id)))
      ) {
        return;
      }
      this.events.append(
        this.captureOnly
          ? {
              event_type: normalized.event_type,
              kind: normalized.kind,
              received_at_ms: normalized.received_at_ms,
            }
          : normalized,
      );
      if (!this.captureOnly) {
        try {
          this.replyAuthorizations.authorize(
            normalized.message_id,
            normalized.kind,
            normalized.kind === "group" ? normalized.group_id : normalized.sender_id,
            this.now(),
          );
        } catch {
          this._failFatal("protocol_error");
          return;
        }
      }
      this.state.last_event_at_ms = this.now();
    });

    this.startTask = Promise.resolve(bot.start()).then(
      () => {
        if (
          this.bot === bot &&
          this.state.reason !== "ready_identity_invalid" &&
          !this.fatal
        ) {
          this.state.gateway_connected = false;
          this.state.authenticated = false;
          this.state.reason = "gateway_stopped";
          this._failFatal("gateway_stopped");
        }
      },
      () => {
        if (this.bot === bot) {
          this._failFatal("gateway_error");
        }
      },
    );
  }

  async stop() {
    const bot = this.bot;
    this.bot = null;
    if (this.watchdogTimer) clearInterval(this.watchdogTimer);
    this.watchdogTimer = null;
    this.observedWs = null;
    bot?.stop();
    await Promise.race([
      this.startTask ?? Promise.resolve(),
      new Promise((resolve) => setTimeout(resolve, 2000)),
    ]);
    this.startTask = null;
    this.state.gateway_connected = false;
    this.state.authenticated = false;
    this.state.bot_id = null;
    this.state.reason = "stopped";
    this.readyAtMs = null;
    this.connectDeadlineAtMs = null;
  }

  readEvents(after, limit) {
    return this.events.read(after, limit);
  }

  async send(request) {
    if (this.captureOnly) {
      throw new ProtocolError("capture_only", 403);
    }
    if (request.generation !== this.generation) {
      throw new ProtocolError("stale_generation", 409);
    }
    const fingerprint = requestFingerprint(request);
    const cached = this.receipts.get(request.idempotency_key, fingerprint);
    if (cached) return Object.freeze({ request_id: request.request_id, ...cached });
    const pending = this.pendingSends.get(request.idempotency_key);
    if (pending) {
      if (pending.fingerprint !== fingerprint) {
        throw new ProtocolError("idempotency_collision", 409);
      }
      const outcome = await pending.promise;
      return Object.freeze({ request_id: request.request_id, ...outcome });
    }
    this._watchGateway();
    const currentWs = this.bot?.gateway?.currentWs;
    const ackAt = this.state.last_heartbeat_ack_at_ms;
    const ackAge = ackAt === null ? Number.POSITIVE_INFINITY : this.now() - ackAt;
    if (
      !this.bot ||
      this.fatal ||
      !this.state.gateway_connected ||
      !this.state.authenticated ||
      currentWs !== this.observedWs ||
      currentWs?.readyState !== 1 ||
      this.state.heartbeat_ack_observable !== true ||
      !Number.isFinite(ackAge) ||
      ackAge < 0 ||
      ackAge > this.heartbeatAckTimeoutMs
    ) {
      throw new ProtocolError("gateway_unavailable", 503);
    }
    this.replyAuthorizations.claim(
      request.reply_message_id,
      request.kind,
      request.target_id,
      request.idempotency_key,
      this.now(),
    );

    const promise = (async () => {
      try {
        let timeoutId;
        const providerCall = Promise.resolve()
          .then(() =>
            this.bot.sendText(
              {
                scope: request.kind,
                targetId: request.target_id,
                msgId: request.reply_message_id,
              },
              request.text,
            ),
          )
          .then(
            (result) => ({ kind: "result", result }),
            () => ({ kind: "error", result: null }),
          );
        const timeout = new Promise((resolve) => {
          timeoutId = setTimeout(
            () => resolve({ kind: "timeout", result: null }),
            this.sendTimeoutMs,
          );
        });
        const settled = await Promise.race([providerCall, timeout]);
        clearTimeout(timeoutId);
        if (settled.kind !== "result") {
          return Object.freeze({ state: "unknown", provider_message_id: null });
        }
        const result = settled.result;
        return Object.freeze({
          state: isSafeId(result?.id) ? "sent" : "unknown",
          provider_message_id: isSafeId(result?.id) ? result.id : null,
        });
      } catch {
        return Object.freeze({ state: "unknown", provider_message_id: null });
      }
    })();
    this.pendingSends.set(request.idempotency_key, { fingerprint, promise });
    try {
      const outcome = await promise;
      this.receipts.put(request.idempotency_key, fingerprint, outcome);
      return Object.freeze({ request_id: request.request_id, ...outcome });
    } finally {
      const current = this.pendingSends.get(request.idempotency_key);
      if (current?.promise === promise) this.pendingSends.delete(request.idempotency_key);
    }
  }
}

export { PINNED_SDK_VERSION, readyBotId };
