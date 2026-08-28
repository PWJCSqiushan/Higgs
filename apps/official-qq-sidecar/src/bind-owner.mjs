import {
  chmodSync,
  closeSync,
  constants,
  fsyncSync,
  lstatSync,
  openSync,
  renameSync,
  writeSync,
} from "node:fs";
import { basename, dirname, isAbsolute, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { OfficialQQClient } from "./qq-client.mjs";
import { isSafeId } from "./protocol.mjs";

const DEFAULT_TIMEOUT_MS = 120_000;

function requiredTimeout(value) {
  if (value === undefined || value === "") return DEFAULT_TIMEOUT_MS;
  if (!/^\d+$/u.test(value)) throw new Error("owner_bind_invalid_timeout");
  const timeout = Number(value);
  if (!Number.isSafeInteger(timeout) || timeout < 10_000 || timeout > 300_000) {
    throw new Error("owner_bind_invalid_timeout");
  }
  return timeout;
}

function assertPrivateDirectory(path, expectedUid) {
  const state = lstatSync(path);
  const enforcePosixMode = process.platform !== "win32";
  if (
    state.isSymbolicLink() ||
    !state.isDirectory() ||
    (expectedUid !== null && state.uid !== expectedUid) ||
    (enforcePosixMode && (state.mode & 0o077) !== 0)
  ) {
    throw new Error("owner_bind_unsafe_directory");
  }
}

export function writeOwnerBinding(targetValue, ownerOpenId) {
  if (!isSafeId(ownerOpenId)) throw new Error("owner_bind_invalid_identity");
  if (!isAbsolute(targetValue) || basename(targetValue) !== "owner.openid") {
    throw new Error("owner_bind_invalid_target");
  }
  const target = resolve(targetValue);
  const parent = dirname(target);
  const expectedUid = typeof process.getuid === "function" ? process.getuid() : null;
  assertPrivateDirectory(parent, expectedUid);
  try {
    lstatSync(target);
    throw new Error("owner_bind_target_exists");
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }

  const temporary = resolve(parent, `.owner.openid.${process.pid}.tmp`);
  let descriptor = null;
  try {
    descriptor = openSync(
      temporary,
      constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY,
      0o600,
    );
    writeSync(descriptor, `${ownerOpenId}\n`, null, "ascii");
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = null;
    chmodSync(temporary, 0o600);
    const state = lstatSync(temporary);
    const enforcePosixMode = process.platform !== "win32";
    if (
      state.isSymbolicLink() ||
      !state.isFile() ||
      (expectedUid !== null && state.uid !== expectedUid) ||
      (enforcePosixMode && (state.mode & 0o777) !== 0o600)
    ) {
      throw new Error("owner_bind_unsafe_output");
    }
    renameSync(temporary, target);
    if (process.platform !== "win32") {
      const directoryDescriptor = openSync(parent, constants.O_RDONLY);
      try {
        fsyncSync(directoryDescriptor);
      } finally {
        closeSync(directoryDescriptor);
      }
    }
  } catch (error) {
    if (descriptor !== null) closeSync(descriptor);
    const failed = resolve(parent, `.owner.openid.failed.${process.pid}`);
    try {
      renameSync(temporary, failed);
    } catch (cleanupError) {
      if (cleanupError?.code !== "ENOENT") throw cleanupError;
      try {
        renameSync(target, failed);
      } catch (targetCleanupError) {
        if (targetCleanupError?.code !== "ENOENT") throw targetCleanupError;
      }
    }
    throw error;
  }
}

export async function bindOwner(env = process.env, ClientClass = OfficialQQClient) {
  const appId = String(env.QQBOT_APP_ID ?? "").trim();
  const appSecret = String(env.QQBOT_APP_SECRET ?? "").trim();
  if (!/^\d{5,32}$/u.test(appId) || appSecret.length < 16 || appSecret.length > 512) {
    throw new Error("owner_bind_not_configured");
  }
  const target = String(env.HIGGS_OFFICIAL_QQ_BIND_OWNER_FILE ?? "").trim();
  const timeoutMs = requiredTimeout(env.HIGGS_OFFICIAL_QQ_BIND_TIMEOUT_MS);
  let resolveOwner;
  let rejectOwner;
  const ownerPromise = new Promise((resolvePromise, rejectPromise) => {
    resolveOwner = resolvePromise;
    rejectOwner = rejectPromise;
  });
  let completed = false;
  const client = new ClientClass({
    appId,
    appSecret,
    enabled: true,
    captureOnly: true,
    onOwnerCandidate: (ownerOpenId) => {
      if (completed) return;
      writeOwnerBinding(target, ownerOpenId);
      completed = true;
      resolveOwner();
    },
    onFatal: () => rejectOwner(new Error("owner_bind_gateway_failed")),
  });
  let timer;
  try {
    await client.start();
    await Promise.race([
      ownerPromise,
      new Promise((_, rejectPromise) => {
        timer = setTimeout(
          () => rejectPromise(new Error("owner_bind_timeout")),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    clearTimeout(timer);
    await client.stop();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  bindOwner().then(
    () => console.log("owner_bind=written"),
    () => {
      console.error("owner_bind=failed");
      process.exitCode = 1;
    },
  );
}
