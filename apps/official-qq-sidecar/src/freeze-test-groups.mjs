import {
  freezeGroupAllowlist,
  readFrozenGroupAllowlist,
} from "./group-capture.mjs";

const expectedCount = Number(process.argv[2] ?? "NaN");
const capturePath =
  process.env.HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_FILE ??
  "/var/lib/higgs-official/group-capture.json";
const allowlistPath =
  process.env.HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_FILE ??
  "/var/lib/higgs-official/allowed-group-openids.json";
if (!Number.isSafeInteger(expectedCount) || expectedCount < 1 || expectedCount > 128) {
  throw new Error("group_freeze_invalid_count");
}
freezeGroupAllowlist(capturePath, expectedCount, allowlistPath);
const frozen = readFrozenGroupAllowlist(allowlistPath);
process.stdout.write(
  `${JSON.stringify({
    status: "frozen",
    candidate_count: frozen.openids.length,
    allowlist_version: frozen.allowlist_version,
    bot_bound: true,
  })}\n`,
);
