# Governed skills and reminder binding

## Reminder safety boundary

Reminder creation remains owner-only. Every job records its source channel, private/group
surface, conversation ID, and source message ID. A bare `确认` or `收到` is accepted only
when exactly one eligible reminder exists in the same source conversation. A quoted source
request or quoted delivered reminder can select that exact job. A generic acknowledgement
in another group never affects it.

When more than one job is eligible, the action fails closed. Use an explicit command:

```text
/higgs remind confirm 8位短ID
/higgs remind ack 8位短ID
/higgs remind cancel 8位短ID
/higgs remind snooze 8位短ID 10m
```

The scheduler stores one occurrence key per `(job UUID, attempt)`. States are `prepared`,
`sent`, `failed`, or `unknown`. A crash-interrupted `prepared` occurrence is eventually
marked `unknown`, never blindly repeated. QQ-offline periods do not prepare a send. The four
delivery times remain due time, +5, +15, and +30 minutes; after the final acknowledgement
window the job becomes `missed`. An acknowledged job produces no further occurrences.

## Skill registry

`r_agent.skills` is metadata and authorization infrastructure, not autonomous execution.
Each descriptor declares its JSON-like input schema, allowed caller roles and surfaces,
external side effects, approval mode, idempotency strategy, audit policy, and timeout.

The reminder descriptor is enabled for the owner on private and group surfaces. The first
future descriptors—server alert, group summary, study/training plan, and FurColor status—are
metadata-only and disabled. Registration alone cannot execute them.

Approvals are keyed by both skill name and the SHA-256 hash of canonical JSON parameters.
Changing any parameter requires a new approval. Unknown skills, disabled skills, database
errors, wrong roles/surfaces, expired approvals, and revoked approvals all fail closed.
Approval rows do not retain parameter plaintext.

Before a due reminder is prepared for delivery, the scheduler recomputes the approved
parameter hash from its content, time, and origin. A mismatched or missing hash moves the
job to `failed`; storage changes can never silently inherit an earlier confirmation.
