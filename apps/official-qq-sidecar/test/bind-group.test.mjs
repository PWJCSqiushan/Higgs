import assert from "node:assert/strict";
import { chmodSync, lstatSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  GROUP_BIND_PHRASE,
  bindGroup,
  writeGroupBinding,
} from "../src/bind-group.mjs";

test("group binding is a private create-once file", () => {
  const directory = mkdtempSync(join(tmpdir(), "higgs-group-bind-"));
  chmodSync(directory, 0o700);
  const target = join(directory, "group.openid");
  writeGroupBinding(target, "group:value/with+platform=characters");
  assert.equal(readFileSync(target, "ascii"), "group:value/with+platform=characters\n");
  if (process.platform !== "win32") {
    assert.equal(lstatSync(target).mode & 0o777, 0o600);
  }
  assert.throws(() => writeGroupBinding(target, "second-group"), /target_exists/);
});

test("binder passes only the private owner and fixed phrase to the client", async () => {
  const directory = mkdtempSync(join(tmpdir(), "higgs-group-bind-"));
  chmodSync(directory, 0o700);
  const target = join(directory, "group.openid");
  const seen = [];
  class FakeClient {
    constructor(options) {
      this.options = options;
      seen.push({
        captureOnly: options.captureOnly,
        ownerOpenId: options.ownerOpenId,
        phrase: options.groupBindPhrase,
      });
    }

    async start() {
      this.options.onGroupCandidate("group:id");
      this.options.onGroupCandidate("ignored:id");
    }

    async stop() {
      seen.push("stopped");
    }
  }
  await bindGroup(
    {
      QQBOT_APP_ID: "123456789",
      QQBOT_APP_SECRET: "0123456789abcdef",
      HIGGS_OFFICIAL_QQ_OWNER_OPENID: "owner:id",
      HIGGS_OFFICIAL_QQ_BIND_GROUP_FILE: target,
      HIGGS_OFFICIAL_QQ_BIND_TIMEOUT_MS: "10000",
    },
    FakeClient,
  );
  assert.deepEqual(seen, [
    {
      captureOnly: true,
      ownerOpenId: "owner:id",
      phrase: GROUP_BIND_PHRASE,
    },
    "stopped",
  ]);
  assert.equal(readFileSync(target, "ascii"), "group:id\n");
});

test("binder rejects missing owner identity before starting a Gateway", async () => {
  class ForbiddenClient {
    constructor() {
      throw new Error("must not construct");
    }
  }
  await assert.rejects(
    bindGroup(
      {
        QQBOT_APP_ID: "123456789",
        QQBOT_APP_SECRET: "0123456789abcdef",
        HIGGS_OFFICIAL_QQ_BIND_GROUP_FILE: "/private/group.openid",
      },
      ForbiddenClient,
    ),
    /not_configured/,
  );
});
