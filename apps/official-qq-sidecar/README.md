# Higgs official QQ sidecar

This is an opt-in, fail-closed protocol boundary for the official QQ Bot. It
uses the Tencent-maintained `@tencent-connect/qqbot-nodejs` package at exactly
version 1.0.4 and requests only `1 << 25`, the group-at and C2C event intent.

The npm artifact is locked to integrity
`sha512-gU5HySLplczZXMUjM7NtiUACY7YfX9YlI/R9PKzCLMgLmHvwsX9L2sitsrYPMentGUr9b8NLfSaSTsndF77NBA==`
and its registry signature verifies. Its published `gitHead` is not present in
the public GitHub history and the public source snapshot differs in package
metadata. The production adapter therefore keeps this package inside a
least-privilege sidecar and treats that unresolved provenance gap as a tracked
release risk; enabling real replies still requires an explicit production
confirmation.

The sidecar is not the Higgs brain. It must not receive identity, memory,
journal, model, tool, Docker Socket, NapCat, or host filesystem access. Its
only persistent authority is the official platform credential supplied through
the dedicated private `official-qq.env` file.

## Safety boundary

- Disabled unless `HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED=true` is explicitly set.
- Binds an HTTP/1.1 API to a Unix Domain Socket with mode `0600` inside a
  UID-owned `0700` host runtime directory. The same path is mounted read-only
  into the Agent; no TCP port is published. The sidecar rejects a symlink,
  regular file, unsafe parent mode, or wrong owner at the socket path.
- Emits no SDK logs. The anonymous capture CLI reports booleans, a bounded
  reason, and event counts only.
- Defaults to `HIGGS_OFFICIAL_QQ_CAPTURE_ONLY=true`; in this mode queued events
  contain only the event type, conversation kind, receive time, and cursor.
  Identity, message IDs, content, group IDs, and attachment metadata are not
  retained or returned, and sending is disabled.
- Accepts only C2C and group-at events and keeps a bounded in-memory queue.
- In full mode the sidecar independently enforces the private owner and group
  allowlist before queueing an event or creating a reply authorization. The
  Python process applies the same policy again.
- Sending is passive-reply-only. A reply message ID is mandatory, target and
  payload fields are strictly validated, and a bounded authorization cache
  binds that message ID to its original conversation. Concurrent identical
  sends collapse to one provider call; idempotency collisions are rejected.
- An HTTP success without a non-empty platform message ID is `unknown`, never
  `sent`.
- SDK 1.0.4 does not expose close or heartbeat-ACK callbacks through `QQBot`.
  Because the version is pinned, the sidecar attaches a read-only observer to
  that exact build's internal WebSocket, records only opcode 11 timestamps,
  clears authentication on close, applies a five-close rolling reconnect
  budget, and exits non-zero on a stale ACK or exhausted budget. Missing or
  incompatible internals therefore fail closed.
- Docker readiness requires a configured, authenticated Gateway and a fresh
  heartbeat ACK; `/v1/hello` alone is not considered healthy.
- Gateway session and verified bot identity are atomically persisted in a
  sidecar-only `0600` state file with a five-minute freshness window. The Agent
  cannot mount this directory. A sidecar generation change is terminal to an
  already-running Agent instead of silently resetting cursors; a coordinated
  process restart can Resume from the fresh private state. The event queue and
  send receipt cache are still in-memory, and the pinned SDK advances its
  Gateway sequence before the sidecar callback. Therefore replies must remain
  disabled until coordinated crash recovery is implemented and a real
  supervised restart/Resume test passes. Higgs' persistent inbound journal and
  deterministic request identity prevent automatic resend after an `unknown`
  outcome once an event has reached the Agent.

## Local verification

```text
npm ci --omit=optional --ignore-scripts
npm run check
npm test
```

## Deployment status

`deploy/existing-server/compose.official-qq.yml` is an explicit Compose overlay
behind the `official-qq` profile. Adding the file to a release does not start a
container. Before applying the overlay, run
`deploy/existing-server/prepare_official_qq_runtime.sh` as root; it creates and
verifies the shared runtime and private session directories as `10001:10001`
with mode `0700`. A deployment must stop if this preflight fails. Use the
reviewed `HIGGS_OFFICIAL_QQ_NODE_IMAGE` digest from `stack.env.example`; a
mutable Node tag is not an acceptable production build input.

Before any real diagnostic run, create a separate root-owned `0600`
`official-qq.env`, build an immutable sidecar image, and obtain a separate
operator confirmation. The Node and Python Gateways must never connect with the
same AppID at the same time. In sidecar mode the Agent environment contains the
owner/group allowlist and socket path, but must not contain the AppID or secret.
The sidecar-only `official-qq-private` directory must never be mounted into the
Agent or included in ordinary application backups.

The Agent has two independent gates: `R_AGENT_OFFICIAL_QQ_ENABLED` permits
ingestion, while `R_AGENT_OFFICIAL_QQ_REPLY_ENABLED` permits passive replies.
The second gate defaults to false and stays false for the first shadow/Resume
deployment even if the Node Gateway and UDS adapter are online.
