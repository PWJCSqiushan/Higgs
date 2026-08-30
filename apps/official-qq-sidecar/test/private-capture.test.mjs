import assert from "node:assert/strict";
import {
  chmodSync,
  mkdtempSync,
  readFileSync,
  statSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  PrivateUserCaptureStore,
  freezePrivateAllowlist,
  readFrozenPrivateAllowlist,
} from "../src/private-capture.mjs";

const appId = "123456789";
const botId = "bot-openid";
const firstUser = "user-openid-1";
const secondUser = "user-openid-2";
const unixOnly = { skip: process.platform === "win32" };

function capturePaths(prefix = "higgs-private-capture-") {
  const directory = mkdtempSync(join(tmpdir(), prefix));
  chmodSync(directory, 0o700);
  return {
    directory,
    capture: join(directory, "private-users-capture.json"),
    allowlist: join(directory, "allowed-private-openids.json"),
  };
}

function store(paths, now = () => 1_500) {
  return new PrivateUserCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 1_000,
    windowDeadlineAtMs: 2_000,
    now,
  });
}

test("bounded capture stores only unique bot-bound OpenIDs and freezes atomically", unixOnly, () => {
  const paths = capturePaths();
  const captureStore = store(paths);
  captureStore.open();
  assert.equal(captureStore.recordCandidate(firstUser, botId, 1_100), true);
  assert.equal(captureStore.recordCandidate(firstUser, botId, 1_200), true);
  assert.equal(captureStore.recordCandidate(secondUser, botId, 1_300), true);
  captureStore.close(1_400);

  const rawCapture = readFileSync(paths.capture, "utf8");
  assert.equal(rawCapture.includes(firstUser), true);
  assert.equal(rawCapture.includes("message"), false);
  assert.equal(rawCapture.includes("content"), false);
  assert.equal(statSync(paths.capture).mode & 0o777, 0o600);

  freezePrivateAllowlist(paths.capture, 2, paths.allowlist, 1_500);
  const frozen = readFrozenPrivateAllowlist(paths.allowlist);
  assert.equal(frozen.app_id, appId);
  assert.equal(frozen.bot_id, botId);
  assert.deepEqual(frozen.openids, [firstUser, secondUser]);
  assert.equal(statSync(paths.allowlist).mode & 0o777, 0o600);
  assert.match(readFileSync(paths.capture, "utf8"), /"status":"frozen"/);
});

test("capture expires, rejects bot changes, and requires exact freeze count", () => {
  const paths = capturePaths("higgs-private-capture-errors-");
  let now = 1_100;
  const captureStore = store(paths, () => now);
  captureStore.open();
  assert.equal(captureStore.recordCandidate(firstUser, botId), true);
  assert.throws(
    () => captureStore.recordCandidate(secondUser, "other-bot"),
    /bot_mismatch/,
  );
  now = 2_001;
  assert.equal(captureStore.recordCandidate(secondUser, botId), false);
  captureStore.close();
  assert.throws(
    () => freezePrivateAllowlist(paths.capture, 2, paths.allowlist),
    /count_mismatch/,
  );
  freezePrivateAllowlist(paths.capture, 1, paths.allowlist);
  assert.throws(
    () => freezePrivateAllowlist(paths.capture, 1, paths.allowlist),
    /must_be_closed/,
  );
});

test("capture refuses wildcard identities and cannot be started twice", () => {
  const paths = capturePaths("higgs-private-capture-policy-");
  const captureStore = store(paths);
  captureStore.open();
  assert.throws(
    () => captureStore.recordCandidate("*", botId),
    /invalid_private_capture_candidate/,
  );
  assert.throws(() => captureStore.open(), /already_started/);
});
