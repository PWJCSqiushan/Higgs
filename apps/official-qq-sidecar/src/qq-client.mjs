import { QQBot } from "@tencent-connect/qqbot-nodejs";
import { readFileSync } from "node:fs";

import {
  EventQueue,
  ChannelGate,
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

function isSafePolicyId(value) {
  return isSafeId(value) && !value.includes("*");
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
    "heartbeat_pending",
    "heartbeat_ack_timeout",
    "reconnect_budget_exhausted",
    "session_store_error",
    "delivery_store_error",
    "owner_bind_error",
    "private_capture_error",
    "private_allowlist_bot_mismatch",
    "private_allowlist_config_mismatch",
    "group_bind_error",
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
    proactiveEnabled = false,
    BotClass = QQBot,
    now = () => Date.now(),
    watchdogIntervalMs = 1000,
    heartbeatAckTimeoutMs = DEFAULT_ACK_TIMEOUT_MS,
    reconnectWindowMs = DEFAULT_RECONNECT_WINDOW_MS,
    maxReconnects = DEFAULT_MAX_RECONNECTS,
    sendTimeoutMs = DEFAULT_SEND_TIMEOUT_MS,
    ownerOpenId = null,
    allowedPrivateOpenIds = [],
    allowedGroupOpenIds = [],
    ordinaryPrivateEnabled = false,
    groupEnabled = false,
    privateRatePerMinute = 30,
    groupRatePerMinute = 60,
    privateCircuitFailureLimit = 5,
    groupCircuitFailureLimit = 5,
    privateCircuitCooldownSeconds = 300,
    groupCircuitCooldownSeconds = 300,
    privateAllowlist = null,
    requirePrivateAllowlist = false,
    onPrivateCandidate = null,
    onOwnerCandidate = null,
    onGroupCandidate = null,
    groupBindPhrase = null,
    onFatal = () => {},
    sessionStore = null,
    deliveryStore = null,
  }) {
    this.appId = appId;
    this.appSecret = appSecret;
    this.enabled = enabled;
    this.captureOnly = captureOnly;
    this.proactiveEnabled = proactiveEnabled;
    this.BotClass = BotClass;
    this.now = now;
    this.watchdogIntervalMs = watchdogIntervalMs;
    this.heartbeatAckTimeoutMs = heartbeatAckTimeoutMs;
    this.reconnectWindowMs = reconnectWindowMs;
    this.maxReconnects = maxReconnects;
    this.sendTimeoutMs = sendTimeoutMs;
    this.ownerOpenId = ownerOpenId;
    this.allowedPrivateOpenIds = new Set(allowedPrivateOpenIds);
    if (isSafeId(ownerOpenId)) this.allowedPrivateOpenIds.add(ownerOpenId);
    this.allowedGroupOpenIds = new Set(allowedGroupOpenIds);
    this.ordinaryPrivateEnabled = ordinaryPrivateEnabled;
    this.groupEnabled = groupEnabled;
    this.privateAllowlist = privateAllowlist;
    this.requirePrivateAllowlist = requirePrivateAllowlist;
    this.privateBotBinding = null;
    this.privateGate = new ChannelGate({
      ratePerMinute: privateRatePerMinute,
      failureLimit: privateCircuitFailureLimit,
      cooldownSeconds: privateCircuitCooldownSeconds,
      now,
    });
    this.groupGate = new ChannelGate({
      ratePerMinute: groupRatePerMinute,
      failureLimit: groupCircuitFailureLimit,
      cooldownSeconds: groupCircuitCooldownSeconds,
      now,
    });
    this.onPrivateCandidate = onPrivateCandidate;
    this.onOwnerCandidate = onOwnerCandidate;
    this.onGroupCandidate = onGroupCandidate;
    this.groupBindPhrase = groupBindPhrase;
    this.onFatal = onFatal;
    this.sessionStore = sessionStore;
    this.deliveryStore = deliveryStore;
    this.generation = newGeneration();
    this.bot = null;
    this.startTask = null;
    this.events = deliveryStore ?? new EventQueue();
    this.receipts = deliveryStore ?? new ReceiptCache();
    this.replyAuthorizations = deliveryStore ?? new ReplyAuthorizationCache();
    this.pendingSends = new Map();
    this.watchdogTimer = null;
    this.observedWs = null;
    this.readyAtMs = null;
    this.pendingAuthReason = null;
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
    this.pendingAuthReason = null;
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
    this.pendingAuthReason = null;
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
          return;
        }
        if (
          this.pendingAuthReason &&
          this.state.gateway_connected &&
          isSafeId(this.state.bot_id)
        ) {
          this.state.authenticated = true;
          this.state.reason = this.pendingAuthReason;
          this.pendingAuthReason = null;
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
      this.pendingAuthReason = null;
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
    if (!this.state.authenticated && this.readyAtMs !== null) {
      if (this.now() - this.readyAtMs > this.heartbeatAckTimeoutMs) {
        this._failFatal("heartbeat_ack_timeout");
      }
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
    if (this.requirePrivateAllowlist) {
      if (
        !this.privateAllowlist ||
        this.privateAllowlist.app_id !== this.appId ||
        !isSafePolicyId(this.privateAllowlist.bot_id) ||
        !Array.isArray(this.privateAllowlist.openids) ||
        this.privateAllowlist.openids.some(
          (value) => !isSafePolicyId(value),
        )
      ) {
        throw new ProtocolError("private_allowlist_unavailable", 503);
      }
      const configuredOpenIds = new Set(this.allowedPrivateOpenIds);
      const frozenOpenIds = new Set(this.privateAllowlist.openids);
      if (isSafeId(this.ownerOpenId)) configuredOpenIds.add(this.ownerOpenId);
      if (isSafeId(this.ownerOpenId)) frozenOpenIds.add(this.ownerOpenId);
      if (
        configuredOpenIds.size !== frozenOpenIds.size ||
        [...configuredOpenIds].some((value) => !frozenOpenIds.has(value))
      ) {
        throw new ProtocolError("private_allowlist_config_mismatch", 503);
      }
      this.privateBotBinding = this.privateAllowlist.bot_id;
      this.allowedPrivateOpenIds = frozenOpenIds;
      if (isSafeId(this.ownerOpenId)) this.allowedPrivateOpenIds.add(this.ownerOpenId);
    }

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
      if (this.requirePrivateAllowlist && botId !== this.privateBotBinding) {
        this.state.bot_id = null;
        this._failFatal("private_allowlist_bot_mismatch");
        return;
      }
      const persistedBotId = this.sessionStore?.getBotId();
      if (persistedBotId && persistedBotId !== botId) {
        this.sessionStore?.clear();
        this._failFatal("ready_identity_invalid");
        return;
      }
      this.state.gateway_connected = true;
      this.state.authenticated = false;
      this.state.bot_id = botId;
      try {
        this.sessionStore?.saveBotId(botId);
      } catch {
        this._failFatal("session_store_error");
        return;
      }
      this.state.reason = "heartbeat_pending";
      this.pendingAuthReason = "ready";
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
      if (this.requirePrivateAllowlist && restoredBotId !== this.privateBotBinding) {
        this._failFatal("private_allowlist_bot_mismatch");
        return;
      }
      this.state.gateway_connected = true;
      this.state.authenticated = false;
      this.state.bot_id = restoredBotId;
      this.state.reason = "heartbeat_pending";
      this.pendingAuthReason = "resumed";
      this.readyAtMs = this.now();
      this.connectDeadlineAtMs = null;
    });
    bot.on("error", () => {
      this.state.gateway_connected = false;
      this.state.authenticated = false;
      this.state.reason = "gateway_error";
      this.readyAtMs = null;
      this.pendingAuthReason = null;
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
        this.captureOnly &&
        normalized.kind === "c2c" &&
        typeof this.onPrivateCandidate === "function"
      ) {
        try {
          // Deliberately pass only identities needed by the private capture
          // store.  The callback cannot observe message content or IDs.
          this.onPrivateCandidate(normalized.sender_id, this.state.bot_id);
        } catch {
          this._failFatal("private_capture_error");
          return;
        }
      }
      if (
        this.captureOnly &&
        normalized.kind === "group" &&
        typeof this.onGroupCandidate === "function" &&
        isSafeId(this.ownerOpenId) &&
        normalized.sender_id === this.ownerOpenId &&
        typeof this.groupBindPhrase === "string" &&
        this.groupBindPhrase.length >= 4 &&
        normalized.text.includes(this.groupBindPhrase)
      ) {
        try {
          this.onGroupCandidate(normalized.group_id);
        } catch {
          this._failFatal("group_bind_error");
          return;
        }
      }
      if (
        !this.captureOnly &&
        ((normalized.kind === "c2c" &&
          (normalized.sender_id !== this.ownerOpenId &&
            (!this.ordinaryPrivateEnabled ||
              !this.allowedPrivateOpenIds.has(normalized.sender_id) ||
              !this.privateGate.allow()))) ||
          (normalized.kind === "group" &&
            (!this.groupEnabled ||
              !this.allowedGroupOpenIds.has(normalized.group_id) ||
              !this.groupGate.allow())))
      ) {
        return;
      }
      const storedEvent = this.captureOnly
        ? {
            event_type: normalized.event_type,
            kind: normalized.kind,
            received_at_ms: normalized.received_at_ms,
          }
        : normalized;
      if (!this.captureOnly && this.deliveryStore) {
        try {
          this.deliveryStore.appendAuthorized(storedEvent, this.now());
        } catch {
          this._failFatal("delivery_store_error");
          return;
        }
      } else {
        this.events.append(storedEvent);
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
    this.pendingAuthReason = null;
    this.connectDeadlineAtMs = null;
  }

  readEvents(after, limit) {
    return this.events.read(after, limit);
  }

  eventBaseCursor() {
    return this.events.baseCursor();
  }

  ackEvents(generation, cursor) {
    if (generation !== this.generation) {
      throw new ProtocolError("stale_generation", 409);
    }
    return this.events.ack(cursor);
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
    let newlyClaimed;
    if (request.delivery_mode === "proactive") {
      if (!this.proactiveEnabled) {
        throw new ProtocolError("proactive_disabled", 403);
      }
      if (
        request.kind !== "c2c" ||
        request.target_id !== this.ownerOpenId ||
        request.reply_message_id !== null
      ) {
        throw new ProtocolError("invalid_proactive_target", 403);
      }
      newlyClaimed = this.receipts.claimProactive(
        request.idempotency_key,
        fingerprint,
      );
    } else {
      if (request.kind === "c2c") {
        const isOwner = request.target_id === this.ownerOpenId;
        if (
          (!isOwner &&
            (!this.ordinaryPrivateEnabled ||
              !this.allowedPrivateOpenIds.has(request.target_id))) ||
          (!isOwner && this.privateGate.isOpen())
        ) {
          throw new ProtocolError("private_channel_disabled", 403);
        }
      } else if (!this.groupEnabled || !this.allowedGroupOpenIds.has(request.target_id)) {
        throw new ProtocolError("group_channel_disabled", 403);
      } else if (this.groupGate.isOpen()) {
        throw new ProtocolError("channel_circuit_open", 403);
      }
      newlyClaimed = this.replyAuthorizations.claim(
        request.reply_message_id,
        request.kind,
        request.target_id,
        request.idempotency_key,
        fingerprint,
        this.now(),
      );
    }
    if (!newlyClaimed) {
      const receipt = Object.freeze({ state: "unknown", provider_message_id: null });
      this.receipts.put(request.idempotency_key, fingerprint, receipt);
      return Object.freeze({ request_id: request.request_id, ...receipt });
    }

    const promise = (async () => {
      try {
        let timeoutId;
        const providerCall = Promise.resolve()
          .then(() =>
            this.bot.sendText(
              {
                scope: request.kind,
                targetId: request.target_id,
                ...(request.delivery_mode === "passive"
                  ? { msgId: request.reply_message_id }
                  : {}),
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
        const ordinary =
          request.kind !== "c2c" || request.target_id !== this.ownerOpenId;
        const gate = request.kind === "c2c" ? this.privateGate : this.groupGate;
        if (ordinary) {
          if (isSafeId(result?.id)) gate.recordSuccess();
          else gate.recordFailure();
        }
        return Object.freeze({
          state: isSafeId(result?.id) ? "sent" : "unknown",
          provider_message_id: isSafeId(result?.id) ? result.id : null,
        });
      } catch {
        if (request.kind !== "c2c" || request.target_id !== this.ownerOpenId) {
          (request.kind === "c2c" ? this.privateGate : this.groupGate).recordFailure();
        }
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
