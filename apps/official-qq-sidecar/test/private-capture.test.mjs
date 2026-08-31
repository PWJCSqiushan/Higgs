import assert from "node:assert/strict";
import {
  chmodSync,
  mkdtempSync,
  writeFileSync,
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
import { computeAllowlistFingerprint } from "../src/allowlist.mjs";

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

test("repeated epochs merge from an explicit baseline and retain an opaque history", () => {
  const paths = capturePaths("higgs-private-capture-epochs-");
  const first = new PrivateUserCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 1_000,
    windowDeadlineAtMs: 2_000,
    now: () => 1_500,
  });
  const firstEpoch = first.open();
  assert.match(firstEpoch, /^[0-9a-f-]{36}$/u);
  first.recordCandidate(firstUser, botId, 1_100);
  first.close(1_400);
  freezePrivateAllowlist(paths.capture, 1, paths.allowlist, 1_500);
  const firstAllowlist = readFrozenPrivateAllowlist(paths.allowlist);
  assert.equal(firstAllowlist.allowlist_version, 1);
  assert.equal(firstAllowlist.previous_version, null);
  assert.match(firstAllowlist.fingerprint, /^[0-9a-f]{64}$/u);

  const second = new PrivateUserCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 3_000,
    windowDeadlineAtMs: 4_000,
    baselineAllowlistVersion: firstAllowlist.allowlist_version,
    baselineAllowlistFingerprint: firstAllowlist.fingerprint,
    now: () => 3_500,
  });
  const secondEpoch = second.open();
  assert.notEqual(secondEpoch, firstEpoch);
  assert.equal(second.summary().baseline_allowlist_version, 1);
  const captureState = JSON.parse(readFileSync(paths.capture, "utf8"));
  assert.equal(captureState.history.length, 1);
  assert.equal(captureState.history[0].epoch_id, firstEpoch);
  assert.equal(Object.hasOwn(captureState.history[0], "candidates"), false);
  second.recordCandidate(secondUser, botId, 3_100);
  second.close(3_400);
  freezePrivateAllowlist(paths.capture, 1, paths.allowlist, 3_500);
  const merged = readFrozenPrivateAllowlist(paths.allowlist);
  assert.equal(merged.allowlist_version, 2);
  assert.equal(merged.previous_version, 1);
  assert.equal(merged.previous_fingerprint, firstAllowlist.fingerprint);
  assert.deepEqual(merged.openids, [firstUser, secondUser]);
  assert.equal(
    merged.fingerprint,
    computeAllowlistFingerprint({
      scope: "private",
      appId,
      botId,
      allowlistVersion: 2,
      openids: [firstUser, secondUser],
    }),
  );
});

test("baseline drift, cross-Bot capture, and tampered fingerprints fail closed", () => {
  const paths = capturePaths("higgs-private-capture-baseline-");
  const first = store(paths);
  first.open();
  first.recordCandidate(firstUser, botId, 1_100);
  first.close(1_400);
  freezePrivateAllowlist(paths.capture, 1, paths.allowlist, 1_500);
  const baseline = readFrozenPrivateAllowlist(paths.allowlist);

  const drifted = new PrivateUserCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 3_000,
    windowDeadlineAtMs: 4_000,
    baselineAllowlistVersion: baseline.allowlist_version,
    baselineAllowlistFingerprint: "0".repeat(64),
    now: () => 3_500,
  });
  drifted.open();
  drifted.recordCandidate(secondUser, botId, 3_100);
  drifted.close(3_400);
  assert.throws(
    () => freezePrivateAllowlist(paths.capture, 1, paths.allowlist, 3_500),
    /baseline_mismatch/,
  );

  const botDrift = new PrivateUserCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 5_000,
    windowDeadlineAtMs: 6_000,
    baselineAllowlistVersion: baseline.allowlist_version,
    baselineAllowlistFingerprint: baseline.fingerprint,
    now: () => 5_500,
  });
  botDrift.open();
  botDrift.recordCandidate(firstUser, botId, 5_100);
  assert.throws(() => botDrift.recordCandidate(secondUser, "other-bot", 5_100), /bot_mismatch/);

  const raw = JSON.parse(readFileSync(paths.allowlist, "utf8"));
  raw.fingerprint = "f".repeat(64);
  chmodSync(paths.allowlist, 0o600);
  writeFileSync(paths.allowlist, `${JSON.stringify(raw)}\n`, "utf8");
  assert.throws(() => readFrozenPrivateAllowlist(paths.allowlist), /invalid_private_capture_state/);
});

test("legacy v1 state is never auto-activated", () => {
  const paths = capturePaths("higgs-private-capture-legacy-");
  writeFileSync(
    paths.capture,
    `${JSON.stringify({
      version: 1,
      status: "frozen",
      app_id: appId,
      bot_id: botId,
      window_started_at_ms: 1_000,
      window_deadline_at_ms: 2_000,
      candidates: [firstUser],
    })}\n`,
    "utf8",
  );
  chmodSync(paths.capture, 0o600);
  const captureStore = new PrivateUserCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 3_000,
    windowDeadlineAtMs: 4_000,
  });
  assert.throws(() => captureStore.open(), /legacy_state_requires_import/);
  writeFileSync(
    paths.allowlist,
    `${JSON.stringify({
      version: 1,
      app_id: appId,
      bot_id: botId,
      frozen_at_ms: 1_500,
      openids: [firstUser],
    })}\n`,
    "utf8",
  );
  chmodSync(paths.allowlist, 0o600);
  assert.throws(() => readFrozenPrivateAllowlist(paths.allowlist), /legacy_requires_explicit_import/);
});

test("an epoch expires after its deadline and cannot collect candidates", () => {
  const paths = capturePaths("higgs-private-capture-expired-");
  let now = 1_500;
  const captureStore = new PrivateUserCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 1_000,
    windowDeadlineAtMs: 2_000,
    now: () => now,
  });
  captureStore.open();
  now = 2_001;
  assert.equal(captureStore.recordCandidate(firstUser, botId), false);
  assert.equal(captureStore.summary().status, "open");
  assert.throws(
    () => freezePrivateAllowlist(paths.capture, 0, paths.allowlist, now),
    /must_be_closed/,
  );
});
