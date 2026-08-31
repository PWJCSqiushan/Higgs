# Personal Memory V5

Personal Memory V5 is the governed ordinary-user lane for explicit remembering,
repeated self-observations, corrections, and forget requests. It uses the existing
`memory.sqlite`; it does not add a fourteenth database.

## Rollout gates

```dotenv
R_AGENT_PERSONAL_MEMORY_SCHEMA_V5_ENABLED=false
R_AGENT_PERSONAL_MEMORY_MODE=off
```

`off` neither migrates nor processes this lane. `shadow` requires schema v5 but may
only record content-free intent decisions; it cannot activate or invalidate a memory.
`active` is a separately approved production step.

## Trust boundary

- The authenticated runtime supplies principal, Bot account, channel and source IDs.
- Chat text and model output cannot supply a principal, memory item ID, status or scope.
- Only ordinary-user (`role=user`) observations enter this lane. Owner governance keeps
  using the existing owner-only commands.
- Every query and write is restricted to the exact current principal. Account-scoped
  official identities prevent two Bots from silently sharing an OpenID memory.
- Sensitive, identity, permission and prompt-injection content is quarantined.

## Decisions

- `explicit_remember`: one low-risk first-person fact or preference may activate once.
- `repeated_observation`: requires confidence at least `0.94` and two distinct source
  observations for the same normalized statement.
- `correction`: an exact unique active predecessor is atomically invalidated when its
  successor becomes active. Missing or ambiguous targets do not guess.
- `forget_request`: an exact unique current item is logically invalidated; no physical
  deletion occurs.

Replayed observations are idempotent. Reuse of an idempotency key with different
normalized input fails closed. Plaintext remains in `memory_items`; the v5 intent and
evidence tables store hashes and content-free governance metadata rather than a second
copy of chat text.

## Recall and recovery

Recall continues to read only active records in the exact principal scope. A predecessor
cannot be restored while an active successor points to it, which prevents two conflicting
versions from becoming simultaneously recallable. Backups, schema activation and
production mode changes remain separately approved operations.
