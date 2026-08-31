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
release risk; expanding replies beyond the already accepted owner C2C surface
still requires an explicit production confirmation.

The sidecar is not the Higgs brain. It must not receive identity, memory,
journal, model, tool, Docker Socket, NapCat, or host filesystem access. Its
only persistent filesystem access is the dedicated private credential file and
the sidecar-owned session/delivery state directory; neither is shared with the
Agent.

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
- Accepts only C2C and group-at events. In full mode it atomically stores a
  bounded event queue and the matching passive-reply authorization before the
  SDK callback returns. Queue saturation or a persistence error stops the
  channel fail-closed instead of discarding an event.
- In full mode the sidecar independently enforces the private owner and group
  allowlist before queueing an event or creating a reply authorization. The
  Python process applies the same policy again.
- Ordinary C2C and group audiences each use a Bot-bound v2 capture epoch and
  immutable allowlist version. Repeated capture is incremental: the previous
  version and fingerprint form an explicit chain, while old files are archived
  by deployment wrappers before replacement. The sidecar verifies scope,
  AppID, READY/RESUME Bot identity, configured IDs, version and canonical
  SHA-256 before either audience can start.
- `/v1/hello` and `/v1/status` expose only the content-free active allowlist
  version and fingerprint for each audience. Closed audiences expose `null`;
  Agent/sidecar drift is a terminal protocol failure.
- Sending is passive-reply-only. A reply message ID is mandatory, target and
  payload fields are strictly validated, and a bounded authorization cache
  binds that message ID to its original conversation. Concurrent identical
  sends collapse to one provider call; idempotency collisions are rejected.
- The Agent acknowledges each event only after its handler returns. The
  sidecar deletes acknowledged queue entries, exposes the current ACK cursor
  during the versioned hello, and safely rebases unacknowledged entries after
  a sidecar restart. A claimed send without a durable receipt is recovered as
  `unknown` and is never issued to the provider a second time.
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
  process restart can Resume from the fresh private state. The sidecar's event
  queue, passive authorization claims, and delivery receipts share a separate
  atomic `0600` file in the same private directory. The Agent now persists its
  quiet window, prepared reply, risk reservation, send/finalize lifecycle and
  source tombstone in `official_processing.sqlite`. Owner C2C passive replies
  have passed real end-to-end acceptance; ordinary users, groups and proactive
  delivery remain behind separate default-off gates. Persona, identity schema,
  ordinary C2C and group activation are independent release gates.

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
The second gate defaults to false. Production currently enables it only for the
explicitly bound owner C2C surface; changing the audience remains a separate
operation even when the Node Gateway and UDS adapter are healthy.

Owner proactive delivery has two additional independent gates:
`R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED` in the Agent and
`HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED` in the sidecar. Both default to false and
require separate production acceptance. When separately approved, proactive
sends are limited to the explicitly bound owner C2C target,
omit `msgId`, and durably claim the idempotency key as `UNKNOWN` before crossing
the provider boundary. They never provide a transparent fallback to OneBot.

Ordinary-user proactive delivery is a different pair of gates:
`R_AGENT_OFFICIAL_QQ_ORDINARY_PROACTIVE_ENABLED` and
`HIGGS_OFFICIAL_QQ_ORDINARY_PROACTIVE_ENABLED`. Both also default to false and
require the ordinary-private audience to be enabled from the same frozen,
Bot-bound allowlist. Enabling the ordinary pair cannot enable owner delivery,
and enabling the owner pair cannot send to an ordinary target. Group proactive
delivery remains forbidden.
