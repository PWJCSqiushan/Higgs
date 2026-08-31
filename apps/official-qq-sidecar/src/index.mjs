import { chmodSync, lstatSync, unlinkSync } from "node:fs";
import { createServer } from "node:http";
import { basename, dirname, isAbsolute, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { OfficialQQClient } from "./qq-client.mjs";
import { SecureDeliveryStore } from "./delivery-store.mjs";
import { readFrozenPrivateAllowlist } from "./private-capture.mjs";
import { SecureOfficialQQSessionStore } from "./session-store.mjs";
import {
  MAX_BODY_BYTES,
  PROTOCOL_VERSION,
  ProtocolError,
  isSafeId,
  normalizeEventAck,
  normalizeSendRequest,
} from "./protocol.mjs";

function boolEnv(value, fallback = false) {
  if (value === undefined || value === "") return fallback;
  if (value === "true") return true;
  if (value === "false") return false;
  throw new Error("invalid boolean configuration");
}

function boundedNumber(value, fallback, minimum, maximum, name) {
  if (value === undefined || value === "") return fallback;
  if (!/^\d+$/u.test(String(value))) throw new Error(`invalid ${name} configuration`);
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`invalid ${name} configuration`);
  }
  return parsed;
}

const ALLOWLIST_FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/u;

function optionalAllowlistVersion(value) {
  if (value === undefined || value === "") return null;
  if (!/^\d+$/u.test(String(value))) {
    throw new Error("invalid private allowlist version configuration");
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new Error("invalid private allowlist version configuration");
  }
  return parsed;
}

function optionalAllowlistFingerprint(value) {
  if (value === undefined || value === "") return null;
  if (!ALLOWLIST_FINGERPRINT_PATTERN.test(String(value))) {
    throw new Error("invalid private allowlist fingerprint configuration");
  }
  return String(value);
}

function safeIdList(value) {
  return [...new Set(
    String(value ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  )];
}

function isSafePolicyId(value) {
  return isSafeId(value) && !value.includes("*");
}

export function loadConfig(env = process.env) {
  const enabled = boolEnv(env.HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED, false);
  const captureOnly = boolEnv(env.HIGGS_OFFICIAL_QQ_CAPTURE_ONLY, true);
  const proactiveEnabled = boolEnv(env.HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED, false);
  const ordinaryPrivateEnabled = boolEnv(
    env.HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED,
    false,
  );
  const groupEnabled = boolEnv(env.HIGGS_OFFICIAL_QQ_GROUP_ENABLED, false);
  const appId = String(env.QQBOT_APP_ID ?? "").trim();
  const appSecret = String(env.QQBOT_APP_SECRET ?? "").trim();
  const ownerOpenId = String(env.HIGGS_OFFICIAL_QQ_OWNER_OPENID ?? "").trim();
  const allowedPrivateOpenIds = safeIdList(
    env.HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS,
  );
  const allowedGroupOpenIds = Object.freeze(
    String(env.HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
  const socketPath = resolve(env.HIGGS_OFFICIAL_QQ_SOCKET ?? "/run/higgs-official/sidecar.sock");
  const sessionValue = env.HIGGS_OFFICIAL_QQ_SESSION_FILE ?? "/var/lib/higgs-official/session.json";
  if (!isAbsolute(sessionValue) || basename(sessionValue) !== "session.json") {
    throw new Error("invalid session file configuration");
  }
  const sessionFile = resolve(sessionValue);
  const deliveryValue =
    env.HIGGS_OFFICIAL_QQ_DELIVERY_STATE_FILE ??
    "/var/lib/higgs-official/delivery-state.json";
  if (!isAbsolute(deliveryValue) || basename(deliveryValue) !== "delivery-state.json") {
    throw new Error("invalid delivery state configuration");
  }
  const deliveryStateFile = resolve(deliveryValue);
  const privateAllowlistValue =
    env.HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FILE ??
    "/var/lib/higgs-official/allowed-private-openids.json";
  if (
    !isAbsolute(privateAllowlistValue) ||
    basename(privateAllowlistValue) !== "allowed-private-openids.json"
  ) {
    throw new Error("invalid private allowlist configuration");
  }
  const privateAllowlistFile = resolve(privateAllowlistValue);
  const configuredPrivateAllowlistVersion = optionalAllowlistVersion(
    env.HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION,
  );
  const configuredPrivateAllowlistFingerprint = optionalAllowlistFingerprint(
    env.HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT,
  );
  if (proactiveEnabled && (!enabled || captureOnly)) {
    throw new Error("proactive sends require enabled full mode");
  }
  if (enabled) {
    if (!/^\d{5,32}$/u.test(appId)) throw new Error("invalid AppID configuration");
    if (appSecret.length < 16 || appSecret.length > 512) {
      throw new Error("invalid AppSecret configuration");
    }
    if (!captureOnly && !isSafePolicyId(ownerOpenId)) {
      throw new Error("invalid owner OpenID configuration");
    }
  }
  if (ownerOpenId && !isSafePolicyId(ownerOpenId)) {
    throw new Error("invalid owner OpenID configuration");
  }
  if (allowedPrivateOpenIds.some((value) => !isSafePolicyId(value))) {
    throw new Error("invalid private OpenID configuration");
  }
  if (allowedGroupOpenIds.some((value) => !isSafePolicyId(value))) {
    throw new Error("invalid group OpenID configuration");
  }
  if (!enabled && (ordinaryPrivateEnabled || groupEnabled)) {
    throw new Error("official channel switches require an enabled sidecar");
  }
  if (captureOnly && (ordinaryPrivateEnabled || groupEnabled)) {
    throw new Error("ordinary and group channels require full mode");
  }
  if (ordinaryPrivateEnabled && !isSafePolicyId(ownerOpenId)) {
    throw new Error("ordinary private channel requires an owner OpenID");
  }
  if (
    ordinaryPrivateEnabled &&
    (configuredPrivateAllowlistVersion === null ||
      configuredPrivateAllowlistFingerprint === null)
  ) {
    throw new Error("private allowlist metadata required");
  }
  const privatePolicy = new Set(allowedPrivateOpenIds);
  if (isSafePolicyId(ownerOpenId)) privatePolicy.add(ownerOpenId);
  return Object.freeze({
    enabled,
    captureOnly,
    proactiveEnabled,
    ordinaryPrivateEnabled,
    groupEnabled,
    appId,
    appSecret,
    ownerOpenId,
    allowedPrivateOpenIds: Object.freeze([...privatePolicy]),
    privateAllowlistFile,
    privateAllowlistVersion: ordinaryPrivateEnabled
      ? configuredPrivateAllowlistVersion
      : null,
    privateAllowlistFingerprint: ordinaryPrivateEnabled
      ? configuredPrivateAllowlistFingerprint
      : null,
    requirePrivateAllowlist: ordinaryPrivateEnabled,
    allowedGroupOpenIds,
    privateRatePerMinute: boundedNumber(
      env.HIGGS_OFFICIAL_QQ_PRIVATE_RATE_PER_MINUTE,
      30,
      1,
      120,
      "private rate",
    ),
    groupRatePerMinute: boundedNumber(
      env.HIGGS_OFFICIAL_QQ_GROUP_RATE_PER_MINUTE,
      60,
      1,
      240,
      "group rate",
    ),
    privateCircuitFailureLimit: boundedNumber(
      env.HIGGS_OFFICIAL_QQ_PRIVATE_CIRCUIT_FAILURE_LIMIT,
      5,
      1,
      20,
      "private circuit failure limit",
    ),
    groupCircuitFailureLimit: boundedNumber(
      env.HIGGS_OFFICIAL_QQ_GROUP_CIRCUIT_FAILURE_LIMIT,
      5,
      1,
      20,
      "group circuit failure limit",
    ),
    privateCircuitCooldownSeconds: boundedNumber(
      env.HIGGS_OFFICIAL_QQ_PRIVATE_CIRCUIT_COOLDOWN_SECONDS,
      300,
      1,
      3600,
      "private circuit cooldown",
    ),
    groupCircuitCooldownSeconds: boundedNumber(
      env.HIGGS_OFFICIAL_QQ_GROUP_CIRCUIT_COOLDOWN_SECONDS,
      300,
      1,
      3600,
      "group circuit cooldown",
    ),
    socketPath,
    sessionFile,
    deliveryStateFile,
  });
}

export function validateSocketDirectory(parent, expectedUid) {
  if (
    parent.isSymbolicLink() ||
    !parent.isDirectory() ||
    (expectedUid !== null && parent.uid !== expectedUid) ||
    (parent.mode & 0o077) !== 0
  ) {
    throw new Error("unsafe_socket_directory");
  }
}

export function validateSocketInode(existing, expectedUid = null, requirePrivateMode = false) {
  if (
    existing.isSymbolicLink() ||
    !existing.isSocket() ||
    (expectedUid !== null && existing.uid !== expectedUid) ||
    (requirePrivateMode && (existing.mode & 0o777) !== 0o600)
  ) {
    throw new Error("unsafe_existing_socket_path");
  }
}

export function prepareSocketPath(socketPath) {
  const parent = lstatSync(dirname(socketPath));
  const expectedUid = typeof process.getuid === "function" ? process.getuid() : null;
  validateSocketDirectory(parent, expectedUid);
  try {
    const existing = lstatSync(socketPath);
    validateSocketInode(existing, expectedUid, true);
    unlinkSync(socketPath);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

export function removeSocketPath(socketPath) {
  const expectedUid = typeof process.getuid === "function" ? process.getuid() : null;
  try {
    const existing = lstatSync(socketPath);
    validateSocketInode(existing, expectedUid, true);
    unlinkSync(socketPath);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function jsonResponse(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

async function readJson(request) {
  let size = 0;
  const chunks = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new ProtocolError("body_too_large", 413);
    chunks.push(chunk);
  }
  if (size === 0) throw new ProtocolError("empty_body");
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ProtocolError("invalid_json");
  }
}

export function createHandler(client) {
  return async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://sidecar.local");
      if (request.method === "GET" && url.pathname === "/v1/hello") {
        const status = client.status();
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          generation: client.generation,
          event_cursor: client.eventBaseCursor(),
          private_allowlist_version: status.private_allowlist_version ?? null,
          private_allowlist_fingerprint: status.private_allowlist_fingerprint ?? null,
        });
      }
      if (request.method === "GET" && url.pathname === "/v1/status") {
        const status = client.status();
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          ...status,
          private_allowlist_version: status.private_allowlist_version ?? null,
          private_allowlist_fingerprint: status.private_allowlist_fingerprint ?? null,
        });
      }
      if (request.method === "GET" && url.pathname === "/v1/events") {
        const after = Number(url.searchParams.get("after") ?? "0");
        const limit = Number(url.searchParams.get("limit") ?? "32");
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          generation: client.generation,
          events: client.readEvents(after, limit),
        });
      }
      if (request.method === "POST" && url.pathname === "/v1/send") {
        const payload = normalizeSendRequest(await readJson(request));
        const receipt = await client.send(payload);
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          generation: client.generation,
          receipt,
        });
      }
      if (request.method === "POST" && url.pathname === "/v1/events/ack") {
        const payload = normalizeEventAck(await readJson(request));
        const cursor = client.ackEvents(payload.generation, payload.cursor);
        return jsonResponse(response, 200, {
          protocol_version: PROTOCOL_VERSION,
          generation: client.generation,
          event_cursor: cursor,
        });
      }
      return jsonResponse(response, 404, { error: "not_found" });
    } catch (error) {
      if (error instanceof ProtocolError) {
        return jsonResponse(response, error.status, { error: error.code });
      }
      return jsonResponse(response, 500, { error: "internal_error" });
    }
  };
}

export async function run(env = process.env) {
  const config = loadConfig(env);
  process.umask(0o077);
  prepareSocketPath(config.socketPath);
  let fatalRequested = false;
  let shutdown = async () => {};
  let clientReference = null;
  const sessionStore = config.enabled && !config.captureOnly
    ? new SecureOfficialQQSessionStore(config.sessionFile, {
        onFailure: () => clientReference?._failFatal("session_store_error"),
      })
    : null;
  const deliveryStore = config.enabled && !config.captureOnly
    ? new SecureDeliveryStore(config.deliveryStateFile, {
        onFailure: () => clientReference?._failFatal("delivery_store_error"),
      })
    : null;
  const privateAllowlist = config.ordinaryPrivateEnabled
    ? readFrozenPrivateAllowlist(config.privateAllowlistFile)
    : null;
  if (
    config.ordinaryPrivateEnabled &&
    (privateAllowlist.allowlist_version !== config.privateAllowlistVersion ||
      privateAllowlist.fingerprint !== config.privateAllowlistFingerprint)
  ) {
    throw new ProtocolError("private_allowlist_metadata_mismatch", 503);
  }
  const client = new OfficialQQClient({
    ...config,
    sessionStore,
    deliveryStore,
    privateAllowlist,
    privateAllowlistVersion: config.privateAllowlistVersion,
    privateAllowlistFingerprint: config.privateAllowlistFingerprint,
    requirePrivateAllowlist: config.requirePrivateAllowlist,
    onFatal: () => {
      fatalRequested = true;
      process.exitCode = 1;
      queueMicrotask(() => void shutdown());
    },
  });
  clientReference = client;
  const server = createServer(createHandler(client));
  server.requestTimeout = 5000;
  server.headersTimeout = 5000;
  server.keepAliveTimeout = 2000;
  server.maxRequestsPerSocket = 100;

  try {
    await new Promise((resolveListen, rejectListen) => {
      server.once("error", rejectListen);
      server.listen(config.socketPath, () => {
        server.off("error", rejectListen);
        try {
          chmodSync(config.socketPath, 0o600);
          validateSocketInode(
            lstatSync(config.socketPath),
            typeof process.getuid === "function" ? process.getuid() : null,
            true,
          );
          resolveListen();
        } catch (error) {
          rejectListen(error);
        }
      });
    });
  } catch {
    if (server.listening) {
      await new Promise((resolveClose) => server.close(resolveClose));
    }
    removeSocketPath(config.socketPath);
    throw new Error("sidecar_listen_failed");
  }

  try {
    await client.start();
  } catch {
    await new Promise((resolveClose) => server.close(resolveClose));
    removeSocketPath(config.socketPath);
    throw new Error("sidecar_start_failed");
  }

  let shutdownPromise = null;
  shutdown = () => {
    shutdownPromise ??= (async () => {
      server.closeIdleConnections();
      await new Promise((resolveClose) => server.close(resolveClose));
      removeSocketPath(config.socketPath);
      await client.stop();
    })();
    return shutdownPromise;
  };
  process.once("SIGTERM", () => void shutdown());
  process.once("SIGINT", () => void shutdown());
  if (fatalRequested) void shutdown();
  return { client, server, shutdown };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  run().catch(() => {
    process.exitCode = 1;
  });
}
