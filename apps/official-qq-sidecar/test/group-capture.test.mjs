import assert from "node:assert/strict";
import {
  chmodSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  statSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { computeAllowlistFingerprint } from "../src/allowlist.mjs";
import {
  DEFAULT_GROUP_MAX_CANDIDATES,
  GROUP_ALLOWLIST_FILE_NAME,
  GROUP_CAPTURE_FILE_NAME,
  GroupCaptureStore,
  freezeGroupAllowlist,
  readFrozenGroupAllowlist,
  readGroupCapture,
} from "../src/group-capture.mjs";

const appId = "123456789";
const otherAppId = "987654321";
const botId = "bot:alpha";
const otherBotId = "bot:beta";
const firstGroup = "group:one";
const secondGroup = "group:two";

function capturePaths(prefix = "higgs-group-capture-") {
  const directory = mkdtempSync(join(tmpdir(), prefix));
  chmodSync(directory, 0o700);
  return {
    directory,
    capture: join(directory, GROUP_CAPTURE_FILE_NAME),
    allowlist: join(directory, GROUP_ALLOWLIST_FILE_NAME),
  };
}

function store(paths, options = {}) {
  return new GroupCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 1_000,
    windowDeadlineAtMs: 2_000,
    now: () => 1_500,
    ...options,
  });
}

test("group capture creates a v2 epoch, binds one Bot, and freezes canonically", () => {
  const paths = capturePaths();
  const captureStore = store(paths);
  const epochId = captureStore.open();
  assert.match(epochId, /^[0-9a-f-]{36}$/u);

  const opened = JSON.parse(readFileSync(paths.capture, "utf8"));
  assert.equal(opened.version, 2);
  assert.equal(opened.scope, "group");
  assert.equal(opened.status, "open");
  assert.match(opened.nonce, /^[0-9a-f]{64}$/u);
  assert.equal(opened.max_candidates, DEFAULT_GROUP_MAX_CANDIDATES);
  assert.deepEqual(opened.candidates, []);

  assert.equal(captureStore.recordCandidate(firstGroup, botId, 1_600), true);
  assert.equal(captureStore.recordCandidate(firstGroup, botId, 1_700), true);
  assert.throws(
    () => captureStore.recordCandidate(secondGroup, botId, 1_700),
    /group_capture_limit/,
  );
  captureStore.close();
  freezeGroupAllowlist(paths.capture, 1, paths.allowlist, 1_800);

  const frozen = readFrozenGroupAllowlist(paths.allowlist);
  assert.equal(frozen.scope, "group");
  assert.equal(frozen.app_id, appId);
  assert.equal(frozen.bot_id, botId);
  assert.equal(frozen.allowlist_version, 1);
  assert.equal(frozen.previous_version, null);
  assert.deepEqual(frozen.openids, [firstGroup]);
  assert.equal(
    frozen.fingerprint,
    computeAllowlistFingerprint({
      scope: "group",
      appId,
      botId,
      allowlistVersion: 1,
      openids: [firstGroup],
    }),
  );
  if (process.platform !== "win32") {
    assert.equal(statSync(paths.capture).mode & 0o777, 0o600);
    assert.equal(statSync(paths.allowlist).mode & 0o777, 0o600);
  }
  assert.equal(JSON.parse(readFileSync(paths.capture, "utf8")).status, "frozen");
});

test("repeated group epochs merge incrementally and retain rollback metadata", () => {
  const paths = capturePaths("higgs-group-capture-epochs-");
  const first = store(paths);
  const firstEpoch = first.open();
  first.recordCandidate(firstGroup, botId, 1_100);
  first.close();
  freezeGroupAllowlist(paths.capture, 1, paths.allowlist, 1_500);
  const previous = readFrozenGroupAllowlist(paths.allowlist);

  const second = new GroupCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 3_000,
    windowDeadlineAtMs: 4_000,
    maxCandidates: 1,
    baselineAllowlistVersion: previous.allowlist_version,
    baselineAllowlistFingerprint: previous.fingerprint,
    now: () => 3_500,
  });
  const secondEpoch = second.open();
  assert.notEqual(secondEpoch, firstEpoch);
  const state = readGroupCapture(paths.capture);
  assert.equal(state.history.length, 1);
  assert.equal(state.history[0].epoch_id, firstEpoch);
  assert.equal(Object.hasOwn(state.history[0], "candidates"), false);
  second.recordCandidate(secondGroup, botId, 3_100);
  second.close();
  freezeGroupAllowlist(paths.capture, 1, paths.allowlist, 3_500);

  const merged = readFrozenGroupAllowlist(paths.allowlist);
  assert.equal(merged.allowlist_version, 2);
  assert.equal(merged.previous_version, 1);
  assert.equal(merged.previous_fingerprint, previous.fingerprint);
  assert.deepEqual(merged.openids, [firstGroup, secondGroup]);
  assert.equal(
    merged.fingerprint,
    computeAllowlistFingerprint({
      scope: "group",
      appId,
      botId,
      allowlistVersion: 2,
      openids: [firstGroup, secondGroup],
    }),
  );
});

test("group epochs are idempotent and reject wrong Bot, App, nonce, and baselines", () => {
  const paths = capturePaths("higgs-group-capture-policy-");
  const captureStore = store(paths);
  captureStore.open();
  assert.equal(captureStore.recordCandidate(firstGroup, botId, 1_100), true);
  assert.equal(captureStore.recordCandidate(firstGroup, botId, 1_200), true);
  assert.throws(
    () => captureStore.recordCandidate(secondGroup, otherBotId, 1_200),
    /group_capture_bot_mismatch/,
  );
  assert.throws(() => captureStore.open(), /group_capture_already_started/);
  captureStore.close();
  freezeGroupAllowlist(paths.capture, 1, paths.allowlist, 1_500);
  const first = readFrozenGroupAllowlist(paths.allowlist);

  const drifted = new GroupCaptureStore(paths.capture, {
    appId,
    windowStartedAtMs: 3_000,
    windowDeadlineAtMs: 4_000,
    baselineAllowlistVersion: first.allowlist_version,
    baselineAllowlistFingerprint: "0".repeat(64),
    now: () => 3_500,
  });
  drifted.open();
  drifted.recordCandidate(secondGroup, botId, 3_100);
  drifted.close();
  assert.throws(
    () => freezeGroupAllowlist(paths.capture, 1, paths.allowlist, 3_500),
    /group_capture_baseline_mismatch/,
  );

  const raw = JSON.parse(readFileSync(paths.capture, "utf8"));
  raw.nonce = "wrong-nonce";
  writeFileSync(paths.capture, `${JSON.stringify(raw)}\n`, "utf8");
  chmodSync(paths.capture, 0o600);
  assert.throws(() => readGroupCapture(paths.capture), /invalid_group_capture_state/);

  const otherPaths = capturePaths("higgs-group-capture-app-");
  const other = new GroupCaptureStore(otherPaths.capture, {
    appId: otherAppId,
    windowStartedAtMs: 1_000,
    windowDeadlineAtMs: 2_000,
    baselineAllowlistVersion: first.allowlist_version,
    baselineAllowlistFingerprint: first.fingerprint,
    now: () => 1_500,
  });
  other.open();
  other.recordCandidate(firstGroup, botId, 1_100);
  other.close();
  assert.throws(
    () => freezeGroupAllowlist(otherPaths.capture, 1, paths.allowlist, 1_600),
    /binding_mismatch/,
  );
});

test("legacy v1 and create-once group bindings never activate", () => {
  const paths = capturePaths("higgs-group-capture-legacy-");
  writeFileSync(
    paths.capture,
    `${JSON.stringify({
      version: 1,
      status: "frozen",
      app_id: appId,
      bot_id: botId,
      window_started_at_ms: 1_000,
      window_deadline_at_ms: 2_000,
      candidates: [firstGroup],
    })}\n`,
    "utf8",
  );
  chmodSync(paths.capture, 0o600);
  assert.throws(
    () => readGroupCapture(paths.capture),
    /group_capture_legacy_state_requires_import/,
  );

  writeFileSync(
    paths.allowlist,
    `${JSON.stringify({
      version: 1,
      app_id: appId,
      bot_id: botId,
      frozen_at_ms: 1_500,
      openids: [firstGroup],
    })}\n`,
    "utf8",
  );
  chmodSync(paths.allowlist, 0o600);
  assert.throws(
    () => readFrozenGroupAllowlist(paths.allowlist),
    /group_allowlist_legacy_requires_explicit_import/,
  );
  assert.throws(
    () => readFrozenGroupAllowlist(join(paths.directory, "group.openid")),
    /invalid_group_capture_path/,
  );

  const legacyBindingPath = join(paths.directory, "group.openid");
  writeFileSync(legacyBindingPath, `${firstGroup}\n`, "utf8");
  assert.throws(
    () =>
      new GroupCaptureStore(join(paths.directory, GROUP_CAPTURE_FILE_NAME), {
        appId,
        windowStartedAtMs: 3_000,
        windowDeadlineAtMs: 4_000,
      }),
    /group_bind_legacy_requires_explicit_import/,
  );
});
