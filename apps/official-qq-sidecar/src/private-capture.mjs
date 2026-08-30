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

import { isSafeId } from "./protocol.mjs";

const VERSION = 1;
const MAX_FILE_BYTES = 256 * 1024;
const MAX_CANDIDATES = 128;

function safeInteger(value, minimum = 0) {
  return Number.isSafeInteger(value) && value >= minimum;
}

function isSafePolicyId(value) {
  return isSafeId(value) && !value.includes("*");
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

function validateOpenIds(values) {
  if (!Array.isArray(values) || values.length > MAX_CANDIDATES) {
    throw new Error("invalid_private_capture_state");
  }
  const result = [];
  const seen = new Set();
  for (const value of values) {
    if (!isSafePolicyId(value) || seen.has(value)) {
      throw new Error("invalid_private_capture_state");
    }
    seen.add(value);
    result.push(value);
  }
  return result;
}

function validateState(value) {
  if (
    !exactKeys(
      value,
      new Set([
        "version",
        "status",
        "app_id",
        "bot_id",
        "window_started_at_ms",
        "window_deadline_at_ms",
        "candidates",
      ]),
    ) ||
    value.version !== VERSION ||
    !new Set(["open", "closed", "frozen"]).has(value.status) ||
    !/^\d{5,32}$/u.test(value.app_id) ||
    (value.bot_id !== null && !isSafePolicyId(value.bot_id)) ||
    !safeInteger(value.window_started_at_ms) ||
    !safeInteger(value.window_deadline_at_ms) ||
    value.window_deadline_at_ms <= value.window_started_at_ms
  ) {
    throw new Error("invalid_private_capture_state");
  }
  return {
    ...value,
    candidates: validateOpenIds(value.candidates),
  };
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
  return JSON.parse(readFileSync(target, "utf8"));
}

function readPrivateFile(path, expectedName) {
  const value = readRawPrivateFile(path, expectedName);
  return value === null ? null : validateState(value);
}

export class PrivateUserCaptureStore {
  constructor(
    path,
    {
      appId,
      windowStartedAtMs,
      windowDeadlineAtMs,
      now = () => Date.now(),
    },
  ) {
    this.path = privateFile(path, "private-users-capture.json");
    if (!/^\d{5,32}$/u.test(String(appId ?? ""))) {
      throw new Error("invalid_private_capture_app_id");
    }
    if (
      !safeInteger(windowStartedAtMs) ||
      !safeInteger(windowDeadlineAtMs) ||
      windowDeadlineAtMs <= windowStartedAtMs
    ) {
      throw new Error("invalid_private_capture_window");
    }
    this.appId = String(appId);
    this.windowStartedAtMs = windowStartedAtMs;
    this.windowDeadlineAtMs = windowDeadlineAtMs;
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
    if (readPrivateFile(this.path, "private-users-capture.json") !== null) {
      throw new Error("private_capture_already_started");
    }
    writePrivateFile(
      this.path,
      {
        version: VERSION,
        status: "open",
        app_id: this.appId,
        bot_id: null,
        window_started_at_ms: this.windowStartedAtMs,
        window_deadline_at_ms: this.windowDeadlineAtMs,
        candidates: [],
      },
      "private-users-capture.json",
    );
  }

  recordCandidate(openId, botId, now = this.now()) {
    if (!isSafePolicyId(openId) || !isSafePolicyId(botId) || !safeInteger(now)) {
      throw new Error("invalid_private_capture_candidate");
    }
    const value = this._read();
    if (value.status !== "open" || now < value.window_started_at_ms || now > value.window_deadline_at_ms) {
      return false;
    }
    if (value.bot_id !== null && value.bot_id !== botId) {
      throw new Error("private_capture_bot_mismatch");
    }
    const candidates = [...value.candidates];
    if (value.bot_id === null) value.bot_id = botId;
    if (!candidates.includes(openId)) {
      if (candidates.length >= MAX_CANDIDATES) throw new Error("private_capture_limit");
      candidates.push(openId);
      value.candidates = candidates;
    }
    writePrivateFile(this.path, value, "private-users-capture.json");
    return true;
  }

  close(now = this.now()) {
    if (!safeInteger(now)) throw new Error("invalid_private_capture_time");
    const value = this._read();
    if (value.status === "frozen") throw new Error("private_capture_already_frozen");
    value.status = "closed";
    writePrivateFile(this.path, value, "private-users-capture.json");
  }

  freeze(expectedCount, allowlistPath, now = this.now()) {
    if (!safeInteger(expectedCount) || expectedCount > MAX_CANDIDATES) {
      throw new Error("invalid_private_capture_count");
    }
    freezePrivateAllowlist(this.path, expectedCount, allowlistPath, now);
  }

  summary() {
    const value = this._read();
    const now = this.now();
    return Object.freeze({
      status: value.status,
      candidate_count: value.candidates.length,
      bot_bound: value.bot_id !== null,
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
  if (!safeInteger(expectedCount) || expectedCount > MAX_CANDIDATES) {
    throw new Error("invalid_private_capture_count");
  }
  if (!safeInteger(now)) throw new Error("invalid_private_capture_time");
  const capture = readPrivateFile(capturePath, "private-users-capture.json");
  if (capture === null || capture.status !== "closed") {
    throw new Error("private_capture_must_be_closed");
  }
  if (!isSafePolicyId(capture.bot_id)) throw new Error("private_capture_bot_unbound");
  if (expectedCount !== capture.candidates.length) {
    throw new Error("private_capture_count_mismatch");
  }
  const target = privateFile(allowlistPath, "allowed-private-openids.json");
  if (readRawPrivateFile(target, "allowed-private-openids.json") !== null) {
    throw new Error("private_allowlist_already_frozen");
  }
  writePrivateFile(
    target,
    {
      version: VERSION,
      app_id: capture.app_id,
      bot_id: capture.bot_id,
      frozen_at_ms: now,
      openids: capture.candidates,
    },
    "allowed-private-openids.json",
  );
  capture.status = "frozen";
  writePrivateFile(capturePath, capture, "private-users-capture.json");
}

export function readFrozenPrivateAllowlist(path) {
  const value = readRawPrivateFile(path, "allowed-private-openids.json");
  if (value === null || !exactKeys(value, new Set(["version", "app_id", "bot_id", "frozen_at_ms", "openids"]))) {
    throw new Error("invalid_private_allowlist");
  }
  if (
    value.version !== VERSION ||
    !/^\d{5,32}$/u.test(value.app_id) ||
    !isSafePolicyId(value.bot_id) ||
    !safeInteger(value.frozen_at_ms)
  ) {
    throw new Error("invalid_private_allowlist");
  }
  return Object.freeze({
    ...value,
    openids: Object.freeze(validateOpenIds(value.openids)),
  });
}
