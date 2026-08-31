import { createHash, randomBytes, randomUUID } from "node:crypto";

import { isSafeId } from "./protocol.mjs";

export const ALLOWLIST_SCHEMA_VERSION = 2;
export const MAX_ALLOWLIST_ENTRIES = 128;
export const ALLOWLIST_FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/u;

const APP_ID_PATTERN = /^\d{5,32}$/u;
const NONCE_PATTERN = /^[0-9a-f]{64}$/u;
const SCOPES = new Set(["private"]);

export function isSafePolicyId(value) {
  return isSafeId(value) && !value.includes("*");
}

export function isSafeInteger(value, minimum = 0) {
  return Number.isSafeInteger(value) && value >= minimum;
}

function exactKeys(value, keys) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.size &&
    Object.keys(value).every((key) => keys.has(key))
  );
}

function invalidState() {
  throw new Error("invalid_private_capture_state");
}

export function normalizeOpenIds(values, maxEntries = MAX_ALLOWLIST_ENTRIES) {
  if (!Array.isArray(values) || !isSafeInteger(maxEntries, 1) || maxEntries > MAX_ALLOWLIST_ENTRIES) {
    invalidState();
  }
  const seen = new Set();
  for (const value of values) {
    if (!isSafePolicyId(value) || seen.has(value)) invalidState();
    seen.add(value);
  }
  if (seen.size > maxEntries) invalidState();
  return [...seen].sort();
}

function validateScope(scope) {
  if (!SCOPES.has(scope)) invalidState();
  return scope;
}

function validateAppId(appId) {
  if (!APP_ID_PATTERN.test(String(appId ?? ""))) invalidState();
  return String(appId);
}

function validateEpochId(epochId) {
  if (!isSafePolicyId(epochId)) invalidState();
  return epochId;
}

function validateNonce(nonce) {
  if (typeof nonce !== "string" || !NONCE_PATTERN.test(nonce)) invalidState();
  return nonce;
}

export function canonicalAllowlistPayload({
  scope = "private",
  appId,
  botId,
  allowlistVersion,
  openids,
}) {
  const normalizedScope = validateScope(scope);
  const normalizedAppId = validateAppId(appId);
  if (!isSafePolicyId(botId)) invalidState();
  if (!isSafeInteger(allowlistVersion, 1)) invalidState();
  const normalizedOpenIds = normalizeOpenIds(openids);
  // Object insertion order is deliberate: this is the cross-runtime canonical
  // representation used by the deployment verifier and the Python adapter.
  return JSON.stringify({
    scope: normalizedScope,
    app_id: normalizedAppId,
    bot_id: botId,
    allowlist_version: allowlistVersion,
    openids: normalizedOpenIds,
  });
}

export function computeAllowlistFingerprint(fields) {
  return createHash("sha256")
    .update(canonicalAllowlistPayload(fields), "utf8")
    .digest("hex");
}

export function createCaptureEpoch({
  scope = "private",
  appId,
  botId = null,
  windowStartedAtMs,
  windowDeadlineAtMs,
  maxCandidates = MAX_ALLOWLIST_ENTRIES,
  baselineAllowlistVersion = null,
  baselineAllowlistFingerprint = null,
  history = [],
}) {
  validateScope(scope);
  const normalizedAppId = validateAppId(appId);
  if (botId !== null && !isSafePolicyId(botId)) invalidState();
  if (
    !isSafeInteger(windowStartedAtMs) ||
    !isSafeInteger(windowDeadlineAtMs) ||
    windowDeadlineAtMs <= windowStartedAtMs
  ) {
    invalidState();
  }
  if (!isSafeInteger(maxCandidates, 1) || maxCandidates > MAX_ALLOWLIST_ENTRIES) {
    invalidState();
  }
  if (
    (baselineAllowlistVersion !== null &&
      !isSafeInteger(baselineAllowlistVersion, 1)) ||
    (baselineAllowlistFingerprint !== null &&
      (typeof baselineAllowlistFingerprint !== "string" ||
        !ALLOWLIST_FINGERPRINT_PATTERN.test(baselineAllowlistFingerprint))) ||
    (baselineAllowlistVersion === null) !== (baselineAllowlistFingerprint === null) ||
    !Array.isArray(history) ||
    history.length > 64
  ) {
    invalidState();
  }
  return {
    version: ALLOWLIST_SCHEMA_VERSION,
    scope,
    status: "open",
    epoch_id: randomUUID(),
    nonce: randomBytes(32).toString("hex"),
    app_id: normalizedAppId,
    bot_id: botId,
    window_started_at_ms: windowStartedAtMs,
    window_deadline_at_ms: windowDeadlineAtMs,
    max_candidates: maxCandidates,
    candidates: [],
    baseline_allowlist_version: baselineAllowlistVersion,
    baseline_allowlist_fingerprint: baselineAllowlistFingerprint,
    frozen_allowlist_version: null,
    frozen_allowlist_fingerprint: null,
    history,
  };
}

export function validateCaptureEpoch(value, expectedScope = "private") {
  const keys = new Set([
    "version",
    "scope",
    "status",
    "epoch_id",
    "nonce",
    "app_id",
    "bot_id",
    "window_started_at_ms",
    "window_deadline_at_ms",
    "max_candidates",
    "candidates",
    "baseline_allowlist_version",
    "baseline_allowlist_fingerprint",
    "frozen_allowlist_version",
    "frozen_allowlist_fingerprint",
    "history",
  ]);
  if (!exactKeys(value, keys) || value.version !== ALLOWLIST_SCHEMA_VERSION) invalidState();
  if (value.scope !== expectedScope) invalidState();
  if (!new Set(["open", "closed", "expired", "frozen"]).has(value.status)) invalidState();
  validateEpochId(value.epoch_id);
  validateNonce(value.nonce);
  validateAppId(value.app_id);
  if (value.bot_id !== null && !isSafePolicyId(value.bot_id)) invalidState();
  if (
    !isSafeInteger(value.window_started_at_ms) ||
    !isSafeInteger(value.window_deadline_at_ms) ||
    value.window_deadline_at_ms <= value.window_started_at_ms
  ) {
    invalidState();
  }
  if (!isSafeInteger(value.max_candidates, 1) || value.max_candidates > MAX_ALLOWLIST_ENTRIES) {
    invalidState();
  }
  const candidates = normalizeOpenIds(value.candidates, value.max_candidates);
  if (
    (value.baseline_allowlist_version !== null &&
      !isSafeInteger(value.baseline_allowlist_version, 1)) ||
    (value.baseline_allowlist_fingerprint !== null &&
      (typeof value.baseline_allowlist_fingerprint !== "string" ||
        !ALLOWLIST_FINGERPRINT_PATTERN.test(value.baseline_allowlist_fingerprint))) ||
    (value.baseline_allowlist_version === null) !==
      (value.baseline_allowlist_fingerprint === null) ||
    (value.frozen_allowlist_version !== null &&
      !isSafeInteger(value.frozen_allowlist_version, 1)) ||
    (value.frozen_allowlist_fingerprint !== null &&
      (typeof value.frozen_allowlist_fingerprint !== "string" ||
        !ALLOWLIST_FINGERPRINT_PATTERN.test(value.frozen_allowlist_fingerprint))) ||
    (value.frozen_allowlist_version === null) !==
      (value.frozen_allowlist_fingerprint === null) ||
    !Array.isArray(value.history) ||
    value.history.length > 64
  ) {
    invalidState();
  }
  return { ...value, candidates };
}

export function validateAllowlist(value, expectedScope = "private") {
  const keys = new Set([
    "version",
    "scope",
    "allowlist_version",
    "epoch_id",
    "nonce",
    "app_id",
    "bot_id",
    "frozen_at_ms",
    "previous_version",
    "previous_fingerprint",
    "fingerprint",
    "openids",
  ]);
  if (!exactKeys(value, keys) || value.version !== ALLOWLIST_SCHEMA_VERSION) invalidState();
  if (value.scope !== expectedScope) invalidState();
  validateEpochId(value.epoch_id);
  validateNonce(value.nonce);
  const appId = validateAppId(value.app_id);
  if (!isSafePolicyId(value.bot_id)) invalidState();
  if (!isSafeInteger(value.allowlist_version, 1)) invalidState();
  if (!isSafeInteger(value.frozen_at_ms)) invalidState();
  if (value.previous_version !== null) {
    if (
      !isSafeInteger(value.previous_version, 1) ||
      value.previous_version !== value.allowlist_version - 1
    ) {
      invalidState();
    }
  }
  if (value.previous_version === null && value.allowlist_version !== 1) {
    invalidState();
  }
  if (
    value.previous_fingerprint !== null &&
    (typeof value.previous_fingerprint !== "string" ||
      !ALLOWLIST_FINGERPRINT_PATTERN.test(value.previous_fingerprint))
  ) {
    invalidState();
  }
  if (
    (value.previous_version === null) !== (value.previous_fingerprint === null) ||
    typeof value.fingerprint !== "string" ||
    !ALLOWLIST_FINGERPRINT_PATTERN.test(value.fingerprint)
  ) {
    invalidState();
  }
  const openids = normalizeOpenIds(value.openids);
  const expectedFingerprint = computeAllowlistFingerprint({
    scope: value.scope,
    appId,
    botId: value.bot_id,
    allowlistVersion: value.allowlist_version,
    openids,
  });
  if (value.fingerprint !== expectedFingerprint) invalidState();
  return { ...value, openids: Object.freeze(openids) };
}

export function createAllowlistVersion({ scope = "private", capture, previous = null, frozenAtMs }) {
  const epoch = validateCaptureEpoch(capture, scope);
  if (epoch.status !== "closed") invalidState();
  if (!isSafeInteger(frozenAtMs)) invalidState();
  if (!isSafePolicyId(epoch.bot_id)) throw new Error("private_capture_bot_unbound");
  const prior = previous === null ? null : validateAllowlist(previous, scope);
  if (prior) {
    if (prior.app_id !== epoch.app_id || prior.bot_id !== epoch.bot_id) {
      throw new Error("private_allowlist_binding_mismatch");
    }
    if (prior.allowlist_version >= Number.MAX_SAFE_INTEGER) invalidState();
  }
  const allowlistVersion = prior === null ? 1 : prior.allowlist_version + 1;
  const openids = normalizeOpenIds(
    [...(prior?.openids ?? []), ...epoch.candidates],
    MAX_ALLOWLIST_ENTRIES,
  );
  const fingerprint = computeAllowlistFingerprint({
    scope,
    appId: epoch.app_id,
    botId: epoch.bot_id,
    allowlistVersion,
    openids,
  });
  return {
    version: ALLOWLIST_SCHEMA_VERSION,
    scope,
    allowlist_version: allowlistVersion,
    epoch_id: epoch.epoch_id,
    nonce: epoch.nonce,
    app_id: epoch.app_id,
    bot_id: epoch.bot_id,
    frozen_at_ms: frozenAtMs,
    previous_version: prior?.allowlist_version ?? null,
    previous_fingerprint: prior?.fingerprint ?? null,
    fingerprint,
    openids,
  };
}
