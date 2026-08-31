import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import {
  createHandler,
  loadConfig,
  validateSocketDirectory,
  validateSocketInode,
} from "../src/index.mjs";
import { isReadyStatus } from "../src/health-status.mjs";
import { PROTOCOL_VERSION } from "../src/protocol.mjs";

async function withServer(client, callback) {
  const server = createServer(createHandler(client));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    await callback(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test("configuration is disabled by default and validates enabled secrets", () => {
  const defaults = loadConfig({});
  assert.equal(defaults.enabled, false);
  assert.equal(defaults.captureOnly, true);
  assert.equal(defaults.proactiveEnabled, false);
  assert.equal(defaults.ordinaryPrivateEnabled, false);
  assert.equal(defaults.groupEnabled, false);
  assert.deepEqual(defaults.allowedPrivateOpenIds, []);
  assert.equal(defaults.privateRatePerMinute, 30);
  assert.equal(defaults.groupRatePerMinute, 60);
  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED: "true" }),
    /enabled full mode/,
  );
  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "true" }),
    /invalid AppID/,
  );
  assert.throws(
    () =>
      loadConfig({
        HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "true",
        HIGGS_OFFICIAL_QQ_CAPTURE_ONLY: "false",
        QQBOT_APP_ID: "123456789",
        QQBOT_APP_SECRET: "0123456789abcdef",
      }),
    /invalid owner OpenID/,
  );
});

test("ordinary policy is explicit, bot-scoped, and owner remains enabled by default", () => {
  const config = loadConfig({
    HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "true",
    HIGGS_OFFICIAL_QQ_CAPTURE_ONLY: "false",
    HIGGS_OFFICIAL_QQ_OWNER_OPENID: "owner-openid",
    HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS: "member-openid,owner-openid,member-openid",
    HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED: "true",
    HIGGS_OFFICIAL_QQ_GROUP_ENABLED: "true",
    HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS: "group-openid",
    QQBOT_APP_ID: "123456789",
    QQBOT_APP_SECRET: "0123456789abcdef",
    HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION: "1",
    HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT: "0".repeat(64),
    HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION: "2",
    HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT: "1".repeat(64),
  });
  assert.equal(config.ordinaryPrivateEnabled, true);
  assert.equal(config.groupEnabled, true);
  assert.equal(config.privateAllowlistVersion, 1);
  assert.equal(config.privateAllowlistFingerprint, "0".repeat(64));
  assert.equal(config.groupAllowlistVersion, 2);
  assert.equal(config.groupAllowlistFingerprint, "1".repeat(64));
  assert.match(config.groupAllowlistFile, /allowed-group-openids\.json$/u);
  assert.deepEqual(new Set(config.allowedPrivateOpenIds), new Set(["owner-openid", "member-openid"]));

  assert.throws(
    () =>
      loadConfig({
        HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "true",
        HIGGS_OFFICIAL_QQ_CAPTURE_ONLY: "false",
        HIGGS_OFFICIAL_QQ_OWNER_OPENID: "owner-openid",
        HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED: "true",
        QQBOT_APP_ID: "123456789",
        QQBOT_APP_SECRET: "0123456789abcdef",
      }),
    /private allowlist metadata required/,
  );

  assert.throws(
    () =>
      loadConfig({
        HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "true",
        HIGGS_OFFICIAL_QQ_CAPTURE_ONLY: "false",
        HIGGS_OFFICIAL_QQ_OWNER_OPENID: "owner-openid",
        HIGGS_OFFICIAL_QQ_GROUP_ENABLED: "true",
        HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS: "group-openid",
        QQBOT_APP_ID: "123456789",
        QQBOT_APP_SECRET: "0123456789abcdef",
      }),
    /group allowlist metadata required/,
  );

  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_FILE: "/tmp/groups.json" }),
    /invalid group allowlist configuration/,
  );

  const ownerOnly = loadConfig({
    HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "true",
    HIGGS_OFFICIAL_QQ_CAPTURE_ONLY: "false",
    HIGGS_OFFICIAL_QQ_OWNER_OPENID: "owner-openid",
    QQBOT_APP_ID: "123456789",
    QQBOT_APP_SECRET: "0123456789abcdef",
  });
  assert.equal(ownerOnly.ordinaryPrivateEnabled, false);
  assert.deepEqual(ownerOnly.allowedPrivateOpenIds, ["owner-openid"]);
});

test("ordinary and group switches are fail-closed while disabled or capture-only", () => {
  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED: "true" }),
    /enabled sidecar/,
  );
  assert.throws(
    () =>
      loadConfig({
        HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "true",
        HIGGS_OFFICIAL_QQ_CAPTURE_ONLY: "true",
        HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED: "true",
        QQBOT_APP_ID: "123456789",
        QQBOT_APP_SECRET: "0123456789abcdef",
      }),
    /full mode/,
  );
  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS: "*" }),
    /invalid private OpenID/,
  );
  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS: "*" }),
    /invalid group OpenID/,
  );
  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_OWNER_OPENID: "*" }),
    /invalid owner OpenID/,
  );
  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_PRIVATE_RATE_PER_MINUTE: "0" }),
    /invalid private rate/,
  );
});

test("socket preparation rejects unsafe parent modes and non-socket paths", () => {
  const directory = (mode, uid = 10001) => ({
    mode,
    uid,
    isDirectory: () => true,
    isSymbolicLink: () => false,
  });
  assert.throws(() => validateSocketDirectory(directory(0o40755), 10001), /unsafe_socket/);
  assert.throws(() => validateSocketDirectory(directory(0o40700, 0), 10001), /unsafe_socket/);
  assert.throws(
    () =>
      validateSocketInode({
        mode: 0o100600,
        uid: 10001,
        isSymbolicLink: () => false,
        isSocket: () => false,
      }),
    /unsafe_existing_socket_path/,
  );
});

test("status and events expose only versioned protocol envelopes", async () => {
  let acknowledged = null;
  const client = {
    generation: "generation",
    eventBaseCursor: () => 0,
    status: () => ({ configured: false, reason: "disabled" }),
    readEvents: () => [],
    ackEvents: (generation, cursor) => {
      assert.equal(generation, "generation");
      acknowledged = cursor;
      return cursor;
    },
  };
  await withServer(client, async (base) => {
    const hello = await (await fetch(`${base}/v1/hello`)).json();
    assert.equal(hello.protocol_version, PROTOCOL_VERSION);
    assert.equal(hello.private_allowlist_version, null);
    assert.equal(hello.private_allowlist_fingerprint, null);
    assert.equal(hello.group_allowlist_version, null);
    assert.equal(hello.group_allowlist_fingerprint, null);
    assert.equal(hello.generation, "generation");
    assert.equal(hello.event_cursor, 0);
    const status = await (await fetch(`${base}/v1/status`)).json();
    assert.equal(status.protocol_version, PROTOCOL_VERSION);
    assert.equal(status.private_allowlist_version, null);
    assert.equal(status.private_allowlist_fingerprint, null);
    assert.equal(status.group_allowlist_version, null);
    assert.equal(status.group_allowlist_fingerprint, null);
    const events = await (await fetch(`${base}/v1/events?after=0&limit=1`)).json();
    assert.deepEqual(events.events, []);
    const ack = await fetch(`${base}/v1/events/ack`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        protocol_version: PROTOCOL_VERSION,
        generation: "generation",
        cursor: 0,
      }),
    });
    assert.equal(ack.status, 200);
    assert.equal((await ack.json()).event_cursor, 0);
    assert.equal(acknowledged, 0);
  });
});

test("health requires authenticated gateway and a fresh heartbeat ACK", () => {
  const status = {
    protocol_version: PROTOCOL_VERSION,
    generation: "generation",
    eventBaseCursor: () => 0,
    configured: true,
    gateway_connected: true,
    authenticated: true,
    capture_only: false,
    bot_id: "bot-id",
    heartbeat_ack_observable: true,
    last_heartbeat_ack_at_ms: 1000,
  };
  assert.equal(isReadyStatus(status, 1001), true);
  assert.equal(isReadyStatus({ ...status, authenticated: false }, 1001), false);
  assert.equal(isReadyStatus(status, 91_001), false);
});

test("send rejects malformed and oversized bodies without calling the client", async () => {
  let calls = 0;
  const client = {
    generation: "generation",
    status: () => ({}),
    readEvents: () => [],
    send: async () => {
      calls += 1;
    },
  };
  await withServer(client, async (base) => {
    const malformed = await fetch(`${base}/v1/send`, { method: "POST", body: "{" });
    assert.equal(malformed.status, 400);
    assert.deepEqual(await malformed.json(), { error: "invalid_json" });
    const oversized = await fetch(`${base}/v1/send`, {
      method: "POST",
      body: "x".repeat(17 * 1024),
    });
    assert.equal(oversized.status, 413);
  });
  assert.equal(calls, 0);
});
