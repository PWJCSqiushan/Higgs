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
import { basename, dirname, isAbsolute, resolve } from "node:path";

import {
  ALLOWLIST_FINGERPRINT_PATTERN,
  ALLOWLIST_SCHEMA_VERSION,
  MAX_ALLOWLIST_ENTRIES,
  createAllowlistVersion,
  createCaptureEpoch,
  isSafeInteger,
  isSafePolicyId,
  validateAllowlist,
  validateCaptureEpoch,
} from "./allowlist.mjs";

/**
 * Versioned capture for GROUP_AT_MESSAGE_CREATE audiences.
 *
 * The old binder writes `group.openid`, which is intentionally not read by
 * this module. A v1 file, a create-once binding, or a malformed v2 envelope
 * therefore cannot silently become a production allowlist.
 */
export const GROUP_CAPTURE_FILE_NAME = "group-capture.json";
export const GROUP_ALLOWLIST_FILE_NAME = "allowed-group-openids.json";
export const DEFAULT_GROUP_MAX_CANDIDATES = 1;

const MAX_FILE_BYTES = 256 * 1024;
const MAX_EPOCH_HISTORY = 64;
const LEGACY_VERSION = 1;

function invalidState(reason = "invalid_group_capture_state") {
  throw new Error(reason);
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

function assertNoLegacyBinding(path) {
  const legacyPath = resolve(dirname(path), "group.openid");
  try {
    lstatSync(legacyPath);
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
  // The v1 binder's create-once output has no App/Bot/version binding. It is
  // never implicitly imported or merged into the v2 audience.
  invalidState("group_bind_legacy_requires_explicit_import");
}

function groupFile(path, expectedName) {
  if (!isAbsolute(path) || basename(path) !== expectedName) {
    invalidState("invalid_group_capture_path");
  }
  const target = resolve(path);
  assertNoLegacyBinding(target);
  return target;
}

function validateGroupDirectory(path) {
  const stat = lstatSync(dirname(path));
  const expectedUid = typeof process.getuid === "function" ? process.getuid() : null;
  if (
    stat.isSymbolicLink() ||
    !stat.isDirectory() ||
    (expectedUid !== null && stat.uid !== expectedUid) ||
    (process.platform !== "win32" && (stat.mode & 0o777) !== 0o700)
  ) {
    invalidState("unsafe_group_capture_directory");
  }
}

function validateHistory(value) {
  if (!Array.isArray(value) || value.length > MAX_EPOCH_HISTORY) {
    invalidState();
  }
  const seen = new Set();
  return value.map((entry) => {
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
      "candidate_count",
      "baseline_allowlist_version",
      "baseline_allowlist_fingerprint",
      "frozen_allowlist_version",
      "frozen_allowlist_fingerprint",
    ]);
    if (!exactKeys(entry, keys) || entry.version !== ALLOWLIST_SCHEMA_VERSION || entry.scope !== "group") {
      invalidState();
    }
    const normalized = validateCaptureEpoch(
      {
        version: entry.version,
        scope: entry.scope,
        status: entry.status,
        epoch_id: entry.epoch_id,
        nonce: entry.nonce,
        app_id: entry.app_id,
        bot_id: entry.bot_id,
        window_started_at_ms: entry.window_started_at_ms,
        window_deadline_at_ms: entry.window_deadline_at_ms,
        max_candidates: entry.max_candidates,
        candidates: [],
        baseline_allowlist_version: entry.baseline_allowlist_version,
        baseline_allowlist_fingerprint: entry.baseline_allowlist_fingerprint,
        frozen_allowlist_version: entry.frozen_allowlist_version,
        frozen_allowlist_fingerprint: entry.frozen_allowlist_fingerprint,
        history: [],
      },
      "group",
    );
    if (
      !isSafeInteger(entry.candidate_count) ||
      entry.candidate_count > entry.max_candidates
    ) {
      invalidState();
    }
    if (seen.has(normalized.epoch_id)) invalidState();
    seen.add(normalized.epoch_id);
    // History deliberately contains metadata and counts only, never group
    // identities or message content.
    return { ...entry, bot_id: normalized.bot_id };
  });
}

function validateState(value) {
  if (value?.version === LEGACY_VERSION) {
    invalidState("group_capture_legacy_state_requires_import");
  }
  let normalized;
  try {
    normalized = validateCaptureEpoch(value, "group");
  } catch {
    invalidState();
  }
  return { ...normalized, history: validateHistory(value.history) };
}

function writeGroupFile(path, value, expectedName) {
  const target = groupFile(path, expectedName);
  validateGroupDirectory(target);
  const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
  const descriptor = openSync(temporary, "wx", 0o600);
  try {
    fchmodSync(descriptor, 0o600);
    writeFileSync(descriptor, `${JSON.stringify(value)}\n`, "utf8");
    fsyncSync(descriptor);
    const stat = fstatSync(descriptor);
    if (
      (process.platform !== "win32" && (stat.mode & 0o777) !== 0o600) ||
      stat.size > MAX_FILE_BYTES
    ) {
      invalidState("unsafe_group_capture_file");
    }
  } finally {
    closeSync(descriptor);
  }
  renameSync(temporary, target);
  if (process.platform !== "win32") {
    const directory = openSync(dirname(target), "r");
    try {
      fsyncSync(directory);
    } finally {
      closeSync(directory);
    }
  }
}

function readRawGroupFile(path, expectedName) {
  const target = groupFile(path, expectedName);
  validateGroupDirectory(target);
  let stat;
  try {
    stat = lstatSync(target);
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
  const expectedUid = typeof process.getuid === "function" ? process.getuid() : null;
  if (
    stat.isSymbolicLink() ||
    !stat.isFile() ||
    stat.size > MAX_FILE_BYTES ||
    (expectedUid !== null && stat.uid !== expectedUid) ||
    (process.platform !== "win32" && (stat.mode & 0o777) !== 0o600)
  ) {
    invalidState("unsafe_group_capture_file");
  }
  try {
    return JSON.parse(readFileSync(target, "utf8"));
  } catch {
    invalidState();
  }
}

function readGroupFile(path, expectedName) {
  const value = readRawGroupFile(path, expectedName);
  return value === null ? null : validateState(value);
}

function epochHistoryEntry(value) {
  return {
    version: value.version,
    scope: value.scope,
    status: value.status,
    epoch_id: value.epoch_id,
    nonce: value.nonce,
    app_id: value.app_id,
    bot_id: value.bot_id,
    window_started_at_ms: value.window_started_at_ms,
    window_deadline_at_ms: value.window_deadline_at_ms,
    max_candidates: value.max_candidates,
    candidate_count: value.candidates.length,
    baseline_allowlist_version: value.baseline_allowlist_version,
    baseline_allowlist_fingerprint: value.baseline_allowlist_fingerprint,
    frozen_allowlist_version: value.frozen_allowlist_version,
    frozen_allowlist_fingerprint: value.frozen_allowlist_fingerprint,
  };
}

function readExistingGroupAllowlist(path) {
  const raw = readRawGroupFile(path, GROUP_ALLOWLIST_FILE_NAME);
  if (raw === null) return null;
  if (raw?.version === LEGACY_VERSION) {
    invalidState("group_allowlist_legacy_requires_explicit_import");
  }
  try {
    return validateAllowlist(raw, "group");
  } catch {
    invalidState("invalid_group_allowlist");
  }
}

/** A repeatable, account-bound capture window for one or more groups. */
export class GroupCaptureStore {
  constructor(
    path,
    {
      appId,
      windowStartedAtMs,
      windowDeadlineAtMs,
      maxCandidates = DEFAULT_GROUP_MAX_CANDIDATES,
      baselineAllowlistVersion = null,
      baselineAllowlistFingerprint = null,
      now = () => Date.now(),
    },
  ) {
    this.path = groupFile(path, GROUP_CAPTURE_FILE_NAME);
    this.appId = String(appId ?? "");
    if (!/^\d{5,32}$/u.test(this.appId)) {
      invalidState("invalid_group_capture_app_id");
    }
    if (
      !isSafeInteger(windowStartedAtMs) ||
      !isSafeInteger(windowDeadlineAtMs) ||
      windowDeadlineAtMs <= windowStartedAtMs
    ) {
      invalidState("invalid_group_capture_window");
    }
    if (!isSafeInteger(maxCandidates, 1) || maxCandidates > MAX_ALLOWLIST_ENTRIES) {
      invalidState("invalid_group_capture_limit");
    }
    if (
      (baselineAllowlistVersion !== null && !isSafeInteger(baselineAllowlistVersion, 1)) ||
      (baselineAllowlistFingerprint !== null &&
        (typeof baselineAllowlistFingerprint !== "string" ||
          !ALLOWLIST_FINGERPRINT_PATTERN.test(baselineAllowlistFingerprint))) ||
      (baselineAllowlistVersion === null) !== (baselineAllowlistFingerprint === null)
    ) {
      invalidState("invalid_group_capture_baseline");
    }
    this.windowStartedAtMs = windowStartedAtMs;
    this.windowDeadlineAtMs = windowDeadlineAtMs;
    this.maxCandidates = maxCandidates;
    this.baselineAllowlistVersion = baselineAllowlistVersion;
    this.baselineAllowlistFingerprint = baselineAllowlistFingerprint;
    this.now = now;
  }

  _read() {
    const value = readGroupFile(this.path, GROUP_CAPTURE_FILE_NAME);
    if (value === null) invalidState("group_capture_not_started");
    if (
      value.app_id !== this.appId ||
      value.window_started_at_ms !== this.windowStartedAtMs ||
      value.window_deadline_at_ms !== this.windowDeadlineAtMs
    ) {
      invalidState("group_capture_window_mismatch");
    }
    return value;
  }

  open() {
    const existing = readGroupFile(this.path, GROUP_CAPTURE_FILE_NAME);
    if (existing !== null) {
      const now = this.now();
      if (
        (existing.status === "open" || existing.status === "closed") &&
        now <= existing.window_deadline_at_ms
      ) {
        invalidState("group_capture_already_started");
      }
      const history = [...existing.history, epochHistoryEntry(existing)].slice(-MAX_EPOCH_HISTORY);
      const next = createCaptureEpoch({
        scope: "group",
        appId: this.appId,
        windowStartedAtMs: this.windowStartedAtMs,
        windowDeadlineAtMs: this.windowDeadlineAtMs,
        maxCandidates: this.maxCandidates,
        baselineAllowlistVersion: this.baselineAllowlistVersion,
        baselineAllowlistFingerprint: this.baselineAllowlistFingerprint,
        history,
      });
      writeGroupFile(this.path, next, GROUP_CAPTURE_FILE_NAME);
      return next.epoch_id;
    }
    const next = createCaptureEpoch({
      scope: "group",
      appId: this.appId,
      windowStartedAtMs: this.windowStartedAtMs,
      windowDeadlineAtMs: this.windowDeadlineAtMs,
      maxCandidates: this.maxCandidates,
      baselineAllowlistVersion: this.baselineAllowlistVersion,
      baselineAllowlistFingerprint: this.baselineAllowlistFingerprint,
    });
    writeGroupFile(this.path, next, GROUP_CAPTURE_FILE_NAME);
    return next.epoch_id;
  }

  recordCandidate(groupOpenId, botId, now = this.now()) {
    if (!isSafePolicyId(groupOpenId) || !isSafePolicyId(botId) || !isSafeInteger(now)) {
      invalidState("invalid_group_capture_candidate");
    }
    const value = this._read();
    if (value.status !== "open") return false;
    if (now < value.window_started_at_ms || now > value.window_deadline_at_ms) return false;
    if (value.bot_id !== null && value.bot_id !== botId) {
      invalidState("group_capture_bot_mismatch");
    }
    if (value.bot_id === null) value.bot_id = botId;
    if (!value.candidates.includes(groupOpenId)) {
      if (value.candidates.length >= value.max_candidates) {
        invalidState("group_capture_limit");
      }
      value.candidates = [...value.candidates, groupOpenId].sort();
    }
    writeGroupFile(this.path, value, GROUP_CAPTURE_FILE_NAME);
    return true;
  }

  close() {
    const value = this._read();
    if (value.status === "frozen") invalidState("group_capture_already_frozen");
    if (value.status === "expired") return;
    value.status = "closed";
    writeGroupFile(this.path, value, GROUP_CAPTURE_FILE_NAME);
  }

  freeze(expectedCount, allowlistPath, now = this.now()) {
    freezeGroupAllowlist(this.path, expectedCount, allowlistPath, now);
  }

  summary() {
    const value = this._read();
    const now = this.now();
    return Object.freeze({
      status: value.status,
      epoch_id: value.epoch_id,
      candidate_count: value.candidates.length,
      max_candidates: value.max_candidates,
      bot_bound: value.bot_id !== null,
      baseline_allowlist_version: value.baseline_allowlist_version,
      baseline_allowlist_fingerprint: value.baseline_allowlist_fingerprint,
      window_active:
        value.status === "open" &&
        now >= value.window_started_at_ms &&
        now <= value.window_deadline_at_ms,
    });
  }
}

export function freezeGroupAllowlist(
  capturePath,
  expectedCount,
  allowlistPath,
  now = Date.now(),
) {
  if (!isSafeInteger(expectedCount) || expectedCount > MAX_ALLOWLIST_ENTRIES) {
    invalidState("invalid_group_capture_count");
  }
  if (!isSafeInteger(now)) invalidState("invalid_group_capture_time");
  const capture = readGroupFile(capturePath, GROUP_CAPTURE_FILE_NAME);
  if (capture === null || capture.status !== "closed") {
    invalidState("group_capture_must_be_closed");
  }
  if (!isSafePolicyId(capture.bot_id)) invalidState("group_capture_bot_unbound");
  if (expectedCount !== capture.candidates.length) {
    invalidState("group_capture_count_mismatch");
  }
  const target = groupFile(allowlistPath, GROUP_ALLOWLIST_FILE_NAME);
  const previous = readExistingGroupAllowlist(target);
  if (
    previous &&
    (capture.baseline_allowlist_version !== previous.allowlist_version ||
      capture.baseline_allowlist_fingerprint !== previous.fingerprint)
  ) {
    invalidState("group_capture_baseline_mismatch");
  }
  if (
    !previous &&
    (capture.baseline_allowlist_version !== null ||
      capture.baseline_allowlist_fingerprint !== null)
  ) {
    invalidState("group_capture_baseline_missing");
  }
  const next = createAllowlistVersion({
    scope: "group",
    capture,
    previous,
    frozenAtMs: now,
  });
  writeGroupFile(target, next, GROUP_ALLOWLIST_FILE_NAME);
  capture.status = "frozen";
  capture.frozen_allowlist_version = next.allowlist_version;
  capture.frozen_allowlist_fingerprint = next.fingerprint;
  writeGroupFile(capturePath, capture, GROUP_CAPTURE_FILE_NAME);
}

export function readFrozenGroupAllowlist(path) {
  const value = readRawGroupFile(path, GROUP_ALLOWLIST_FILE_NAME);
  if (value === null) invalidState("group_allowlist_missing");
  if (value?.version === LEGACY_VERSION) {
    invalidState("group_allowlist_legacy_requires_explicit_import");
  }
  try {
    return Object.freeze(validateAllowlist(value, "group"));
  } catch {
    invalidState("invalid_group_allowlist");
  }
}

export function readGroupCapture(path) {
  const value = readGroupFile(path, GROUP_CAPTURE_FILE_NAME);
  if (value === null) invalidState("group_capture_missing");
  return Object.freeze(value);
}
