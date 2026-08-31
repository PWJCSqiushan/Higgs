export function isReadyStatus(value, now = Date.now()) {
  const ackAge = now - value?.last_heartbeat_ack_at_ms;
  const botIdentityReady =
    value?.capture_only === true ||
    (value?.capture_only === false &&
      typeof value?.bot_id === "string" &&
      /^[!-~]{1,256}$/u.test(value.bot_id));
  return (
    value?.protocol_version === 2 &&
    typeof value?.generation === "string" &&
    value.generation.length > 0 &&
    value?.configured === true &&
    value?.gateway_connected === true &&
    value?.authenticated === true &&
    botIdentityReady &&
    value?.heartbeat_ack_observable === true &&
    Number.isFinite(ackAge) &&
    ackAge >= 0 &&
    ackAge <= 90_000
  );
}
