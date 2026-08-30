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
  assert.equal(loadConfig({}).enabled, false);
  assert.equal(loadConfig({}).captureOnly, true);
  assert.equal(loadConfig({}).proactiveEnabled, false);
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
    assert.equal(hello.protocol_version, 1);
    assert.equal(hello.generation, "generation");
    assert.equal(hello.event_cursor, 0);
    const events = await (await fetch(`${base}/v1/events?after=0&limit=1`)).json();
    assert.deepEqual(events.events, []);
    const ack = await fetch(`${base}/v1/events/ack`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        protocol_version: 1,
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
    protocol_version: 1,
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
