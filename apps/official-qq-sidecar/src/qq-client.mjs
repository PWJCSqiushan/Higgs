import { QQBot } from "@tencent-connect/qqbot-nodejs";

import {
  EventQueue,
  GROUP_AND_C2C_INTENT,
  ProtocolError,
  ReceiptCache,
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
    "gateway_stopped",
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
  }) {
    this.appId = appId;
    this.appSecret = appSecret;
    this.enabled = enabled;
    this.captureOnly = captureOnly;
    this.BotClass = BotClass;
    this.now = now;
    this.generation = newGeneration();
    this.bot = null;
    this.startTask = null;
    this.events = new EventQueue();
    this.receipts = new ReceiptCache();
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
      bot_id: this.captureOnly ? null : this.state.bot_id,
      reason: boundedReason(this.state.reason),
    });
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
    });
    this.bot = bot;
    this.state.reason = "starting";

    bot.on("ready", (data) => {
      const botId = readyBotId(data);
      if (!botId) {
        this.state.gateway_connected = false;
        this.state.authenticated = false;
        this.state.bot_id = null;
        this.state.reason = "ready_identity_invalid";
        bot.stop();
        return;
      }
      this.state.gateway_connected = true;
      this.state.authenticated = true;
      this.state.bot_id = botId;
      this.state.reason = "ready";
    });
    bot.on("resumed", () => {
      if (!isSafeId(this.state.bot_id)) {
        this.state.gateway_connected = false;
        this.state.authenticated = false;
        this.state.reason = "ready_identity_invalid";
        bot.stop();
        return;
      }
      this.state.gateway_connected = true;
      this.state.authenticated = true;
      this.state.reason = "resumed";
    });
    bot.on("error", () => {
      this.state.gateway_connected = false;
      this.state.authenticated = false;
      this.state.reason = "gateway_error";
    });
    bot.on("message", (_context, message) => {
      if (!this.state.authenticated || !isSafeId(this.state.bot_id)) return;
      const normalized = normalizeInboundMessage(message, this.state.bot_id, this.now());
      if (!normalized) return;
      this.events.append(
        this.captureOnly
          ? {
              event_type: normalized.event_type,
              kind: normalized.kind,
              received_at_ms: normalized.received_at_ms,
            }
          : normalized,
      );
      this.state.last_event_at_ms = this.now();
    });

    this.startTask = Promise.resolve(bot.start()).then(
      () => {
        if (this.bot === bot && this.state.reason !== "ready_identity_invalid") {
          this.state.gateway_connected = false;
          this.state.authenticated = false;
          this.state.reason = "gateway_stopped";
        }
      },
      () => {
        if (this.bot === bot) {
          this.state.gateway_connected = false;
          this.state.authenticated = false;
          this.state.reason = "gateway_error";
        }
      },
    );
  }

  async stop() {
    const bot = this.bot;
    this.bot = null;
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
    if (!this.bot || !this.state.gateway_connected || !this.state.authenticated) {
      throw new ProtocolError("gateway_unavailable", 503);
    }
    const fingerprint = requestFingerprint(request);
    const cached = this.receipts.get(request.idempotency_key, fingerprint);
    if (cached) return cached;

    let receipt;
    try {
      const result = await this.bot.sendText(
        {
          scope: request.kind,
          targetId: request.target_id,
          msgId: request.reply_message_id,
        },
        request.text,
      );
      receipt = Object.freeze({
        request_id: request.request_id,
        state: isSafeId(result?.id) ? "sent" : "unknown",
        provider_message_id: isSafeId(result?.id) ? result.id : null,
      });
    } catch {
      receipt = Object.freeze({
        request_id: request.request_id,
        state: "unknown",
        provider_message_id: null,
      });
    }
    this.receipts.put(request.idempotency_key, fingerprint, receipt);
    return receipt;
  }
}

export { readyBotId };
