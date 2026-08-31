import { OfficialQQClient } from "./qq-client.mjs";
import {
  PrivateUserCaptureStore,
  readFrozenPrivateAllowlist,
} from "./private-capture.mjs";

const appId = String(process.env.QQBOT_APP_ID ?? "").trim();
const appSecret = String(process.env.QQBOT_APP_SECRET ?? "").trim();
const capturePath =
  process.env.HIGGS_OFFICIAL_QQ_PRIVATE_CAPTURE_FILE ??
  "/var/lib/higgs-official/private-users-capture.json";
const allowlistPath =
  process.env.HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FILE ??
  "/var/lib/higgs-official/allowed-private-openids.json";
const requestedSeconds = Number(process.env.HIGGS_OFFICIAL_QQ_CAPTURE_WINDOW_SECONDS ?? "300");
const maxCandidates = Number(
  process.env.HIGGS_OFFICIAL_QQ_CAPTURE_MAX_CANDIDATES ?? "128",
);
if (!/^\d{5,32}$/u.test(appId) || appSecret.length < 16 || appSecret.length > 512) {
  throw new Error("private_capture_not_configured");
}
if (!Number.isSafeInteger(requestedSeconds) || requestedSeconds < 10 || requestedSeconds > 900) {
  throw new Error("private_capture_invalid_window");
}
if (!Number.isSafeInteger(maxCandidates) || maxCandidates < 1 || maxCandidates > 128) {
  throw new Error("private_capture_invalid_limit");
}

let baselineAllowlistVersion = null;
let baselineAllowlistFingerprint = null;
try {
  const baseline = readFrozenPrivateAllowlist(allowlistPath);
  baselineAllowlistVersion = baseline.allowlist_version;
  baselineAllowlistFingerprint = baseline.fingerprint;
} catch (error) {
  if (error?.message !== "private_allowlist_missing") throw error;
}

const windowStartedAtMs = Date.now();
const windowDeadlineAtMs = windowStartedAtMs + requestedSeconds * 1000;
const store = new PrivateUserCaptureStore(capturePath, {
  appId,
  windowStartedAtMs,
  windowDeadlineAtMs,
  maxCandidates,
  baselineAllowlistVersion,
  baselineAllowlistFingerprint,
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
    onPrivateCandidate: (openId, botId) => store.recordCandidate(openId, botId),
    onFatal: (reason) => {
      fatalReason = typeof reason === "string" ? reason : "gateway_error";
    },
  });
  await client.start();
  while (Date.now() < windowDeadlineAtMs && fatalReason === null) {
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  if (fatalReason !== null) throw new Error("private_capture_gateway_failed");
} finally {
  try {
    if (client !== null) await client.stop();
  } finally {
    if (opened) store.close();
  }
}
process.stdout.write(`${JSON.stringify({ status: "closed", ...store.summary() })}\n`);
