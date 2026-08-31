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
  computeAllowlistFingerprint,
  createAllowlistVersion,
  createCaptureEpoch,
  isSafeInteger,
  isSafePolicyId,
  validateAllowlist,
  validateCaptureEpoch,
} from "./allowlist.mjs";

const VERSION = ALLOWLIST_SCHEMA_VERSION;
const MAX_FILE_BYTES = 256 * 1024;
const MAX_EPOCH_HISTORY = 64;
const LEGACY_VERSION = 1;

function exactKeys(value, keys) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.size &&
    Object.keys(value).every((key) => keys.has(key))
  );
}

function privateFile(path, expectedName) {
  if (!isAbsolute(path) || basename(path) !== expectedName) {
    throw new Error("invalid_private_capture_path");
  }
  return resolve(path);
}

function validatePrivateDirectory(path) {
  const stat = lstatSync(dirname(path));
  const expectedUid = typeof process.getuid === "function" ? process.getuid() : null;
  if (
    stat.isSymbolicLink() ||
    !stat.isDirectory() ||
    (expectedUid !== null && stat.uid !== expectedUid) ||
    (process.platform !== "win32" && (stat.mode & 0o777) !== 0o700)
  ) {
    throw new Error("unsafe_private_capture_directory");
  }
}

function validateHistory(value) {
  if (!Array.isArray(value) || value.length > MAX_EPOCH_HISTORY) {
    throw new Error("invalid_private_capture_state");
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
    if (!exactKeys(entry, keys) || entry.version !== VERSION || entry.scope !== "private") {
      throw new Error("invalid_private_capture_state");
    }
    // History deliberately contains metadata and counts only, not message
    // text or candidate identities. It is retained to prevent epoch overwrite.
    const normalized = validateCaptureEpoch({
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
    });
    if (!isSafeInteger(entry.candidate_count) || entry.candidate_count > entry.max_candidates) {
      throw new Error("invalid_private_capture_state");
    }
    if (seen.has(normalized.epoch_id)) throw new Error("invalid_private_capture_state");
    seen.add(normalized.epoch_id);
    return { ...entry, bot_id: normalized.bot_id };
  });
}

function validateState(value) {
  if (value?.version === LEGACY_VERSION) {
    throw new Error("private_capture_legacy_state_requires_import");
  }
  const normalized = validateCaptureEpoch(value, "private");
  const history = validateHistory(value.history);
  return { ...normalized, history };
}

function writePrivateFile(path, value, expectedName) {
  const target = privateFile(path, expectedName);
  validatePrivateDirectory(target);
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
      throw new Error("unsafe_private_capture_file");
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

function readRawPrivateFile(path, expectedName) {
  const target = privateFile(path, expectedName);
  validatePrivateDirectory(target);
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
    throw new Error("unsafe_private_capture_file");
  }
  try {
    return JSON.parse(readFileSync(target, "utf8"));
  } catch {
    throw new Error("invalid_private_capture_state");
  }
}

function readPrivateFile(path, expectedName) {
  const value = readRawPrivateFile(path, expectedName);
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

function readExistingAllowlist(path) {
  const raw = readRawPrivateFile(path, "allowed-private-openids.json");
  if (raw === null) return null;
  if (raw?.version === LEGACY_VERSION) {
    throw new Error("private_allowlist_legacy_requires_explicit_import");
  }
  return validateAllowlist(raw, "private");
}

export class PrivateUserCaptureStore {
  constructor(
    path,
    {
      appId,
      windowStartedAtMs,
      windowDeadlineAtMs,
      maxCandidates = MAX_ALLOWLIST_ENTRIES,
      baselineAllowlistVersion = null,
      baselineAllowlistFingerprint = null,
      now = () => Date.now(),
    },
  ) {
    this.path = privateFile(path, "private-users-capture.json");
    this.appId = String(appId ?? "");
    if (!/^\d{5,32}$/u.test(this.appId)) {
      throw new Error("invalid_private_capture_app_id");
    }
    if (
      !isSafeInteger(windowStartedAtMs) ||
      !isSafeInteger(windowDeadlineAtMs) ||
      windowDeadlineAtMs <= windowStartedAtMs
    ) {
      throw new Error("invalid_private_capture_window");
    }
    if (!isSafeInteger(maxCandidates, 1) || maxCandidates > MAX_ALLOWLIST_ENTRIES) {
      throw new Error("invalid_private_capture_limit");
    }
    if (
      (baselineAllowlistVersion !== null && !isSafeInteger(baselineAllowlistVersion, 1)) ||
      (baselineAllowlistFingerprint !== null &&
        (typeof baselineAllowlistFingerprint !== "string" ||
          !ALLOWLIST_FINGERPRINT_PATTERN.test(baselineAllowlistFingerprint))) ||
      (baselineAllowlistVersion === null) !== (baselineAllowlistFingerprint === null)
    ) {
      throw new Error("invalid_private_capture_baseline");
    }
    this.windowStartedAtMs = windowStartedAtMs;
    this.windowDeadlineAtMs = windowDeadlineAtMs;
    this.maxCandidates = maxCandidates;
    this.baselineAllowlistVersion = baselineAllowlistVersion;
    this.baselineAllowlistFingerprint = baselineAllowlistFingerprint;
    this.now = now;
  }

  _read() {
    const value = readPrivateFile(this.path, "private-users-capture.json");
    if (value === null) throw new Error("private_capture_not_started");
    if (
      value.app_id !== this.appId ||
      value.window_started_at_ms !== this.windowStartedAtMs ||
      value.window_deadline_at_ms !== this.windowDeadlineAtMs
    ) {
      throw new Error("private_capture_window_mismatch");
    }
    return value;
  }

  open() {
    const existing = readPrivateFile(this.path, "private-users-capture.json");
    if (existing !== null) {
      const now = this.now();
      if (
        (existing.status === "open" || existing.status === "closed") &&
        now <= existing.window_deadline_at_ms
      ) {
        throw new Error("private_capture_already_started");
      }
      // A completed epoch is retained in the manifest history. The new epoch
      // is never written over it without retaining its opaque metadata.
      const history = [...existing.history, epochHistoryEntry(existing)].slice(-MAX_EPOCH_HISTORY);
      const next = createCaptureEpoch({
        appId: this.appId,
        windowStartedAtMs: this.windowStartedAtMs,
        windowDeadlineAtMs: this.windowDeadlineAtMs,
        maxCandidates: this.maxCandidates,
        baselineAllowlistVersion: this.baselineAllowlistVersion,
        baselineAllowlistFingerprint: this.baselineAllowlistFingerprint,
        history,
      });
      writePrivateFile(this.path, next, "private-users-capture.json");
      return next.epoch_id;
    }
    const next = createCaptureEpoch({
      appId: this.appId,
      windowStartedAtMs: this.windowStartedAtMs,
      windowDeadlineAtMs: this.windowDeadlineAtMs,
      maxCandidates: this.maxCandidates,
      baselineAllowlistVersion: this.baselineAllowlistVersion,
      baselineAllowlistFingerprint: this.baselineAllowlistFingerprint,
    });
    writePrivateFile(this.path, next, "private-users-capture.json");
    return next.epoch_id;
  }

  recordCandidate(openId, botId, now = this.now()) {
    if (!isSafePolicyId(openId) || !isSafePolicyId(botId) || !isSafeInteger(now)) {
      throw new Error("invalid_private_capture_candidate");
    }
    const value = this._read();
    if (value.status !== "open") return false;
    if (now < value.window_started_at_ms) {
      return false;
    }
    if (now > value.window_deadline_at_ms) return false;
    if (value.bot_id !== null && value.bot_id !== botId) {
      throw new Error("private_capture_bot_mismatch");
    }
    if (value.bot_id === null) value.bot_id = botId;
    if (!value.candidates.includes(openId)) {
      if (value.candidates.length >= value.max_candidates) {
        throw new Error("private_capture_limit");
      }
      value.candidates = [...value.candidates, openId].sort();
    }
    writePrivateFile(this.path, value, "private-users-capture.json");
    return true;
  }

  close(now = this.now()) {
    if (!isSafeInteger(now)) throw new Error("invalid_private_capture_time");
    const value = this._read();
    if (value.status === "frozen") throw new Error("private_capture_already_frozen");
    if (value.status === "expired") return;
    value.status = "closed";
    writePrivateFile(this.path, value, "private-users-capture.json");
  }

  freeze(expectedCount, allowlistPath, now = this.now()) {
    if (!isSafeInteger(expectedCount) || expectedCount > MAX_ALLOWLIST_ENTRIES) {
      throw new Error("invalid_private_capture_count");
    }
    freezePrivateAllowlist(this.path, expectedCount, allowlistPath, now);
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
        value.status === "open" && now >= value.window_started_at_ms && now <= value.window_deadline_at_ms,
    });
  }
}

export function freezePrivateAllowlist(
  capturePath,
  expectedCount,
  allowlistPath,
  now = Date.now(),
) {
  if (!isSafeInteger(expectedCount) || expectedCount > MAX_ALLOWLIST_ENTRIES) {
    throw new Error("invalid_private_capture_count");
  }
  if (!isSafeInteger(now)) throw new Error("invalid_private_capture_time");
  const capture = readPrivateFile(capturePath, "private-users-capture.json");
  if (capture === null || capture.status !== "closed") {
    throw new Error("private_capture_must_be_closed");
  }
  if (!isSafePolicyId(capture.bot_id)) throw new Error("private_capture_bot_unbound");
  if (expectedCount !== capture.candidates.length) {
    throw new Error("private_capture_count_mismatch");
  }
  const target = privateFile(allowlistPath, "allowed-private-openids.json");
  const previous = readExistingAllowlist(target);
  if (
    previous &&
    (capture.baseline_allowlist_version !== previous.allowlist_version ||
      capture.baseline_allowlist_fingerprint !== previous.fingerprint)
  ) {
    throw new Error("private_capture_baseline_mismatch");
  }
  if (
    !previous &&
    (capture.baseline_allowlist_version !== null || capture.baseline_allowlist_fingerprint !== null)
  ) {
    throw new Error("private_capture_baseline_missing");
  }
  const next = createAllowlistVersion({
    scope: "private",
    capture,
    previous,
    frozenAtMs: now,
  });
  writePrivateFile(target, next, "allowed-private-openids.json");
  capture.status = "frozen";
  capture.frozen_allowlist_version = next.allowlist_version;
  capture.frozen_allowlist_fingerprint = next.fingerprint;
  writePrivateFile(capturePath, capture, "private-users-capture.json");
}

export function readFrozenPrivateAllowlist(path) {
  const value = readRawPrivateFile(path, "allowed-private-openids.json");
  if (value === null) throw new Error("private_allowlist_missing");
  if (value?.version === LEGACY_VERSION) {
    throw new Error("private_allowlist_legacy_requires_explicit_import");
  }
  return Object.freeze(validateAllowlist(value, "private"));
}

export function allowlistFingerprintForConfig({ appId, botId, allowlistVersion, openids }) {
  return computeAllowlistFingerprint({
    scope: "private",
    appId,
    botId,
    allowlistVersion,
    openids,
  });
}
