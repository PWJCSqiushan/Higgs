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

const VERSION = 1;
const DEFAULT_TTL_MS = 5 * 60 * 1000;
const MAX_FILE_BYTES = 4096;

function safeString(value, maximum = 512) {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= maximum &&
    !/[\u0000-\u001f\u007f]/u.test(value)
  );
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

export class SecureOfficialQQSessionStore {
  constructor(path, { now = () => Date.now(), ttlMs = DEFAULT_TTL_MS, onFailure = () => {} } = {}) {
    if (!isAbsolute(path) || basename(path) !== "session.json") {
      throw new Error("invalid_session_path");
    }
    this.path = path;
    this.now = now;
    this.ttlMs = ttlMs;
    this.onFailure = onFailure;
    this.cached = null;
    this.lastWriteAtMs = 0;
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
      throw new Error("unsafe_session_directory");
    }
  }

  _empty() {
    return { version: VERSION, session: null, bot_id: null, updated_at_ms: this.now() };
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
      throw new Error("unsafe_session_file");
    }
    const value = JSON.parse(readFileSync(this.path, "utf8"));
    if (
      !exactKeys(value, new Set(["version", "session", "bot_id", "updated_at_ms"])) ||
      value.version !== VERSION ||
      !Number.isSafeInteger(value.updated_at_ms) ||
      value.updated_at_ms < 0 ||
      (value.bot_id !== null && !safeString(value.bot_id, 256))
    ) {
      throw new Error("invalid_session_file");
    }
    if (value.session !== null) {
      if (
        !exactKeys(value.session, new Set(["sessionId", "lastSeq"])) ||
        !safeString(value.session.sessionId) ||
        (value.session.lastSeq !== null &&
          (!Number.isSafeInteger(value.session.lastSeq) || value.session.lastSeq < 0))
      ) {
        throw new Error("invalid_session_file");
      }
    }
    return value;
  }

  _write(value) {
    this._validateDirectory();
    const temporary = `${this.path}.${process.pid}.${randomUUID()}.tmp`;
    const fd = openSync(temporary, "wx", 0o600);
    try {
      fchmodSync(fd, 0o600);
      writeFileSync(fd, `${JSON.stringify(value)}\n`, "utf8");
      fsyncSync(fd);
      const stat = fstatSync(fd);
      if ((stat.mode & 0o777) !== 0o600) throw new Error("unsafe_session_file");
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
    this.cached = value;
    this.lastWriteAtMs = this.now();
  }

  _guard(operation) {
    try {
      return operation();
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }

  load() {
    return this._guard(() => {
      const value = this._read();
      const age = this.now() - value.updated_at_ms;
      const fresh = age >= 0 && age <= this.ttlMs;
      this.cached = fresh ? value : this._empty();
      return fresh && value.session && value.bot_id ? value.session : null;
    });
  }

  getBotId() {
    return this.cached?.bot_id ?? null;
  }

  save(session) {
    return this._guard(() => {
      if (
        !session ||
        !safeString(session.sessionId) ||
        (session.lastSeq !== null &&
          (!Number.isSafeInteger(session.lastSeq) || session.lastSeq < 0))
      ) {
        throw new Error("invalid_session_value");
      }
      const current = this.cached ?? this._read();
      this._write({
        version: VERSION,
        session: { sessionId: session.sessionId, lastSeq: session.lastSeq },
        bot_id: current.bot_id,
        updated_at_ms: this.now(),
      });
    });
  }

  saveBotId(botId) {
    return this._guard(() => {
      if (!safeString(botId, 256)) throw new Error("invalid_bot_identity");
      const current = this.cached ?? this._read();
      this._write({ ...current, bot_id: botId, updated_at_ms: this.now() });
    });
  }

  touch() {
    return this._guard(() => {
      const current = this.cached;
      if (!current?.session || !current.bot_id || this.now() - this.lastWriteAtMs < 60_000) return;
      this._write({ ...current, updated_at_ms: this.now() });
    });
  }

  clear() {
    return this._guard(() => this._write(this._empty()));
  }
}
