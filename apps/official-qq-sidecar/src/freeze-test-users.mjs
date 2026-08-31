import { freezePrivateAllowlist, readFrozenPrivateAllowlist } from "./private-capture.mjs";

const expectedCount = Number(process.argv[2] ?? "NaN");
const capturePath =
  process.env.HIGGS_OFFICIAL_QQ_PRIVATE_CAPTURE_FILE ??
  "/var/lib/higgs-official/private-users-capture.json";
const allowlistPath =
  process.env.HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FILE ??
  "/var/lib/higgs-official/allowed-private-openids.json";
const baselineAllowlistPath =
  process.env.HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_BASELINE_FILE ?? allowlistPath;
if (!Number.isSafeInteger(expectedCount) || expectedCount < 1 || expectedCount > 128) {
  throw new Error("private_freeze_invalid_count");
}
freezePrivateAllowlist(capturePath, expectedCount, allowlistPath, Date.now(), baselineAllowlistPath);
const frozen = readFrozenPrivateAllowlist(allowlistPath);
process.stdout.write(
  `${JSON.stringify({
    status: "frozen",
    candidate_count: frozen.openids.length,
    bot_bound: true,
    allowlist_version: frozen.allowlist_version,
    previous_version: frozen.previous_version,
    fingerprint: frozen.fingerprint,
    previous_fingerprint: frozen.previous_fingerprint,
  })}\n`,
);
