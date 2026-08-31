import { OfficialQQClient } from "./qq-client.mjs";
import { GROUP_BIND_PHRASE } from "./bind-group.mjs";
import {
  DEFAULT_GROUP_MAX_CANDIDATES,
  GroupCaptureStore,
} from "./group-capture.mjs";

const appId = String(process.env.QQBOT_APP_ID ?? "").trim();
const appSecret = String(process.env.QQBOT_APP_SECRET ?? "").trim();
const ownerOpenId = String(process.env.HIGGS_OFFICIAL_QQ_OWNER_OPENID ?? "").trim();
const capturePath =
  process.env.HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_FILE ??
  "/var/lib/higgs-official/group-capture.json";
const requestedSeconds = Number(
  process.env.HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_WINDOW_SECONDS ?? "300",
);
const maxCandidates = Number(
  process.env.HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_MAX_CANDIDATES ??
    String(DEFAULT_GROUP_MAX_CANDIDATES),
);
const baselineAllowlistVersionRaw = String(
  process.env.HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_BASELINE_VERSION ?? "",
).trim();
const baselineAllowlistFingerprint = String(
  process.env.HIGGS_OFFICIAL_QQ_GROUP_CAPTURE_BASELINE_FINGERPRINT ?? "",
).trim();
const baselineAllowlistVersion = baselineAllowlistVersionRaw
  ? Number(baselineAllowlistVersionRaw)
  : null;
if (
  !/^\d{5,32}$/u.test(appId) ||
  appSecret.length < 16 ||
  appSecret.length > 512 ||
  !ownerOpenId
) {
  throw new Error("group_capture_not_configured");
}
if (!Number.isSafeInteger(requestedSeconds) || requestedSeconds < 10 || requestedSeconds > 900) {
  throw new Error("group_capture_invalid_window");
}
if (!Number.isSafeInteger(maxCandidates) || maxCandidates < 1 || maxCandidates > 128) {
  throw new Error("group_capture_invalid_limit");
}
if (
  (baselineAllowlistVersion === null) !== (baselineAllowlistFingerprint.length === 0) ||
  (baselineAllowlistVersion !== null &&
    (!Number.isSafeInteger(baselineAllowlistVersion) || baselineAllowlistVersion < 1 ||
      !/^[0-9a-f]{64}$/u.test(baselineAllowlistFingerprint)))
) {
  throw new Error("group_capture_invalid_baseline");
}

const windowStartedAtMs = Date.now();
const windowDeadlineAtMs = windowStartedAtMs + requestedSeconds * 1000;
const store = new GroupCaptureStore(capturePath, {
  appId,
  windowStartedAtMs,
  windowDeadlineAtMs,
  maxCandidates,
  baselineAllowlistVersion,
  baselineAllowlistFingerprint: baselineAllowlistVersion === null
    ? null
    : baselineAllowlistFingerprint,
});
let opened = false;
let client = null;
let fatalReason = null;
try {
  store.open();
  opened = true;
  client = new OfficialQQClient({
    appId,
    appSecret,
    enabled: true,
    captureOnly: true,
    ownerOpenId,
    groupBindPhrase: GROUP_BIND_PHRASE,
    // The SDK callback intentionally exposes only the group identity. Read
    // the already-authenticated client state here so the capture envelope is
    // still bound to the Bot without widening the general event callback.
    onGroupCandidate: (groupOpenId) => store.recordCandidate(groupOpenId, client.state.bot_id),
    onFatal: (reason) => {
      fatalReason = typeof reason === "string" ? reason : "gateway_error";
    },
  });
  await client.start();
  while (Date.now() < windowDeadlineAtMs && fatalReason === null) {
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  if (fatalReason !== null) throw new Error("group_capture_gateway_failed");
} finally {
  try {
    if (client !== null) await client.stop();
  } finally {
    if (opened) store.close();
  }
}
const summary = store.summary();
process.stdout.write(
  `${JSON.stringify({
    status: "closed",
    candidate_count: summary.candidate_count,
    max_candidates: summary.max_candidates,
    bot_bound: summary.bot_bound,
  })}\n`,
);
