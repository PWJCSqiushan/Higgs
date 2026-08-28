import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import { createHandler, loadConfig } from "../src/index.mjs";

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
  assert.throws(
    () => loadConfig({ HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "true" }),
    /invalid AppID/,
  );
});

test("status and events expose only versioned protocol envelopes", async () => {
  const client = {
    generation: "generation",
    status: () => ({ configured: false, reason: "disabled" }),
    readEvents: () => [],
  };
  await withServer(client, async (base) => {
    const hello = await (await fetch(`${base}/v1/hello`)).json();
    assert.equal(hello.protocol_version, 1);
    assert.equal(hello.generation, "generation");
    const events = await (await fetch(`${base}/v1/events?after=0&limit=1`)).json();
    assert.deepEqual(events.events, []);
  });
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
