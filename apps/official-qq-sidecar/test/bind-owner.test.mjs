import assert from "node:assert/strict";
import { chmodSync, lstatSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { bindOwner, writeOwnerBinding } from "../src/bind-owner.mjs";

test("owner binding is a private create-once file", () => {
  const directory = mkdtempSync(join(tmpdir(), "higgs-owner-bind-"));
  chmodSync(directory, 0o700);
  const target = join(directory, "owner.openid");
  writeOwnerBinding(target, "owner:value/with+platform=characters");
  assert.equal(readFileSync(target, "ascii"), "owner:value/with+platform=characters\n");
  if (process.platform !== "win32") {
    assert.equal(lstatSync(target).mode & 0o777, 0o600);
  }
  assert.throws(() => writeOwnerBinding(target, "second-owner"), /target_exists/);
});

test("binder exposes no identity and stops after the first candidate", async () => {
  const directory = mkdtempSync(join(tmpdir(), "higgs-owner-bind-"));
  chmodSync(directory, 0o700);
  const target = join(directory, "owner.openid");
  const seen = [];
  class FakeClient {
    constructor(options) {
      this.options = options;
    }

    async start() {
      seen.push("started");
      this.options.onOwnerCandidate("owner:id");
      this.options.onOwnerCandidate("ignored:id");
    }

    async stop() {
      seen.push("stopped");
    }
  }
  await bindOwner(
    {
      QQBOT_APP_ID: "123456789",
      QQBOT_APP_SECRET: "0123456789abcdef",
      HIGGS_OFFICIAL_QQ_BIND_OWNER_FILE: target,
      HIGGS_OFFICIAL_QQ_BIND_TIMEOUT_MS: "10000",
    },
    FakeClient,
  );
  assert.deepEqual(seen, ["started", "stopped"]);
  assert.equal(readFileSync(target, "ascii"), "owner:id\n");
});
