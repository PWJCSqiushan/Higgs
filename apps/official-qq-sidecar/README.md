# Higgs official QQ sidecar

This is an opt-in, fail-closed protocol boundary for the official QQ Bot. It
uses the Tencent-maintained `@tencent-connect/qqbot-nodejs` package at exactly
version 1.0.4 and requests only `1 << 25`, the group-at and C2C event intent.

The npm artifact is locked to integrity
`sha512-gU5HySLplczZXMUjM7NtiUACY7YfX9YlI/R9PKzCLMgLmHvwsX9L2sitsrYPMentGUr9b8NLfSaSTsndF77NBA==`
and its registry signature verifies. Its published `gitHead` is not present in
the public GitHub history and the public source snapshot differs in package
metadata, so this slice remains diagnostic-only until that provenance gap is
explicitly accepted or resolved.

The sidecar is not the Higgs brain. It must not receive identity, memory,
journal, model, tool, Docker Socket, NapCat, or host filesystem access. Its
only persistent authority is the official platform credential supplied through
the dedicated private `official-qq.env` file.

## Safety boundary

- Disabled unless `HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED=true` is explicitly set.
- Binds an HTTP/1.1 API to a Unix Domain Socket with mode `0600` inside a
  UID-owned tmpfs; no TCP port is published or shared with the Agent in this
  diagnostic slice.
- Emits no SDK logs. The anonymous capture CLI reports booleans, a bounded
  reason, and event counts only.
- Defaults to `HIGGS_OFFICIAL_QQ_CAPTURE_ONLY=true`; in this mode queued events
  contain only the event type, conversation kind, receive time, and cursor.
  Identity, message IDs, content, group IDs, and attachment metadata are not
  retained or returned, and sending is disabled.
- Accepts only C2C and group-at events and keeps a bounded in-memory queue.
- Sending is passive-reply-only. A reply message ID is mandatory, target and
  payload fields are strictly validated, and idempotency collisions are
  rejected.
- An HTTP success without a non-empty platform message ID is `unknown`, never
  `sent`.
- The current slice intentionally has no session persistence and exposes no
  heartbeat-ACK claim because SDK 1.0.4 does not provide that callback.

## Local verification

```text
npm ci --omit=optional --ignore-scripts
npm run check
npm test
```

## Deployment status

`deploy/existing-server/compose.official-qq.yml` is an explicit Compose overlay
behind the `official-qq` profile. Adding the file to a release does not start a
container and does not change the existing Agent or NapCat stack.

Before any real diagnostic run, create a separate root-owned `0600`
`official-qq.env`, build an immutable sidecar image, and obtain a separate
operator confirmation. The Node and Python Gateways must never connect with the
same AppID at the same time.
