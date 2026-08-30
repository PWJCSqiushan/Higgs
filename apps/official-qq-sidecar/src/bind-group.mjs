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
export const GROUP_BIND_PHRASE = "绑定测试群";

function requiredTimeout(value) {
  if (value === undefined || value === "") return DEFAULT_TIMEOUT_MS;
  if (!/^\d+$/u.test(value)) throw new Error("group_bind_invalid_timeout");
  const timeout = Number(value);
  if (!Number.isSafeInteger(timeout) || timeout < 10_000 || timeout > 300_000) {
    throw new Error("group_bind_invalid_timeout");
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
    throw new Error("group_bind_unsafe_directory");
  }
}

export function writeGroupBinding(targetValue, groupOpenId) {
  if (!isSafeId(groupOpenId)) throw new Error("group_bind_invalid_identity");
  if (!isAbsolute(targetValue) || basename(targetValue) !== "group.openid") {
    throw new Error("group_bind_invalid_target");
  }
  const target = resolve(targetValue);
  const parent = dirname(target);
  const expectedUid = typeof process.getuid === "function" ? process.getuid() : null;
  assertPrivateDirectory(parent, expectedUid);
  try {
    lstatSync(target);
    throw new Error("group_bind_target_exists");
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }

  const temporary = resolve(parent, `.group.openid.${process.pid}.tmp`);
  let descriptor = null;
  try {
    descriptor = openSync(
      temporary,
      constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY,
      0o600,
    );
    writeSync(descriptor, `${groupOpenId}\n`, null, "ascii");
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
      throw new Error("group_bind_unsafe_output");
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
    const failed = resolve(parent, `.group.openid.failed.${process.pid}`);
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

export async function bindGroup(env = process.env, ClientClass = OfficialQQClient) {
  const appId = String(env.QQBOT_APP_ID ?? "").trim();
  const appSecret = String(env.QQBOT_APP_SECRET ?? "").trim();
  const ownerOpenId = String(env.HIGGS_OFFICIAL_QQ_OWNER_OPENID ?? "").trim();
  if (
    !/^\d{5,32}$/u.test(appId) ||
    appSecret.length < 16 ||
    appSecret.length > 512 ||
    !isSafeId(ownerOpenId)
  ) {
    throw new Error("group_bind_not_configured");
  }
  const target = String(env.HIGGS_OFFICIAL_QQ_BIND_GROUP_FILE ?? "").trim();
  const timeoutMs = requiredTimeout(env.HIGGS_OFFICIAL_QQ_BIND_TIMEOUT_MS);
  let resolveGroup;
  let rejectGroup;
  const groupPromise = new Promise((resolvePromise, rejectPromise) => {
    resolveGroup = resolvePromise;
    rejectGroup = rejectPromise;
  });
  let completed = false;
  const client = new ClientClass({
    appId,
    appSecret,
    enabled: true,
    captureOnly: true,
    ownerOpenId,
    groupBindPhrase: GROUP_BIND_PHRASE,
    onGroupCandidate: (groupOpenId) => {
      if (completed) return;
      writeGroupBinding(target, groupOpenId);
      completed = true;
      resolveGroup();
    },
    onFatal: () => rejectGroup(new Error("group_bind_gateway_failed")),
  });
  let timer;
  try {
    await client.start();
    await Promise.race([
      groupPromise,
      new Promise((_, rejectPromise) => {
        timer = setTimeout(
          () => rejectPromise(new Error("group_bind_timeout")),
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
  bindGroup().then(
    () => console.log("group_bind=written"),
    () => {
      console.error("group_bind=failed");
      process.exitCode = 1;
    },
  );
}
