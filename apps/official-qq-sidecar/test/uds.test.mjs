import assert from "node:assert/strict";
import { chmodSync, lstatSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { run } from "../src/index.mjs";
import { SecureOfficialQQSessionStore } from "../src/session-store.mjs";
import { getJson } from "../src/uds-client.mjs";

test(
  "real UDS serves the versioned protocol and removes its socket on shutdown",
  { skip: process.platform === "win32" },
  async () => {
    const directory = mkdtempSync(join(tmpdir(), "higgs-official-uds-"));
    chmodSync(directory, 0o700);
    const socketPath = join(directory, "sidecar.sock");
    const runtime = await run({
      HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED: "false",
      HIGGS_OFFICIAL_QQ_CAPTURE_ONLY: "true",
      HIGGS_OFFICIAL_QQ_SOCKET: socketPath,
    });
    const hello = await getJson(socketPath, "/v1/hello");
    const status = await getJson(socketPath, "/v1/status");
    assert.equal(hello.protocol_version, 2);
    assert.equal(hello.private_allowlist_version, null);
    assert.equal(hello.private_allowlist_fingerprint, null);
    assert.equal(status.reason, "disabled");
    await runtime.shutdown();
    assert.throws(() => lstatSync(socketPath), (error) => error?.code === "ENOENT");
  },
);

test(
  "secure session state survives a fresh store instance without exposing it over UDS",
  { skip: process.platform === "win32" },
  () => {
    const directory = mkdtempSync(join(tmpdir(), "higgs-official-session-"));
    chmodSync(directory, 0o700);
    const sessionPath = join(directory, "session.json");
    const first = new SecureOfficialQQSessionStore(sessionPath, { now: () => 1000 });
    assert.equal(first.load(), null);
    first.save({ sessionId: "session-id", lastSeq: 7 });
    first.saveBotId("bot-id");

    const restored = new SecureOfficialQQSessionStore(sessionPath, { now: () => 1001 });
    assert.deepEqual(restored.load(), { sessionId: "session-id", lastSeq: 7 });
    assert.equal(restored.getBotId(), "bot-id");
    restored.clear();
    assert.equal(new SecureOfficialQQSessionStore(sessionPath, { now: () => 1002 }).load(), null);
  },
);
