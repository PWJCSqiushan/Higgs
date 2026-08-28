import { getJson } from "./uds-client.mjs";

const socketPath = process.env.HIGGS_OFFICIAL_QQ_SOCKET ?? "/run/higgs-official/sidecar.sock";
const requestedSeconds = Number(process.argv[2] ?? "120");
const seconds = Number.isSafeInteger(requestedSeconds)
  ? Math.min(300, Math.max(1, requestedSeconds))
  : 120;
const deadline = Date.now() + seconds * 1000;
let cursor = 0;
let eventSeen = false;
let eventCount = 0;
let finalStatus = null;
let outcome = "timeout";

while (Date.now() < deadline) {
  try {
    finalStatus = await getJson(socketPath, "/v1/status");
    const response = await getJson(socketPath, `/v1/events?after=${cursor}&limit=32`);
    for (const event of response.events ?? []) {
      if (Number.isSafeInteger(event.cursor)) cursor = Math.max(cursor, event.cursor);
      eventCount += 1;
      eventSeen = true;
    }
    if (eventSeen) {
      outcome = "event_seen";
      break;
    }
  } catch {
    outcome = "sidecar_unavailable";
  }
  await new Promise((resolve) => setTimeout(resolve, 1000));
}

process.stdout.write(
  `${JSON.stringify({
    outcome,
    event_seen: eventSeen,
    event_count: eventCount,
    configured: finalStatus?.configured === true,
    gateway_connected: finalStatus?.gateway_connected === true,
    authenticated: finalStatus?.authenticated === true,
    reason:
      typeof finalStatus?.reason === "string" ? finalStatus.reason.slice(0, 64) : "unknown",
  })}\n`,
);
process.exitCode = eventSeen ? 0 : 2;
