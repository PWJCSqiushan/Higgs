# Higgs on the existing 2-core / 2-GB Lighthouse host

This profile is intentionally smaller than the normal production profile. It
coexists with BaoTa, Nginx, FurColor, and Chaoxing without changing their
configuration.

## Security boundaries

- NapCat WebUI is published only on `127.0.0.1:16099`.
- OneBot port `3001` exists only on Docker's internal `onebot` network.
- Higgs has no inbound host port.
- The public firewall and BaoTa/Nginx virtual hosts do not need to change.
- Real API keys, QQ identifiers, tokens, persona files, login state, and
  databases live under `/srv/secrets/higgs` or `/srv/data/higgs`; they are not
  included in the release archive or Git.
- `higgs.env` is read again by the unprivileged Agent through the private
  runtime mount. Keep it mode `0600` and owned by the Agent runtime identity
  (`10001:10001`). Atomic env updates, backups, restores, and release rollback
  must preserve each source file's existing numeric owner instead of forcing
  every private env file to `root:root`.
- The OneBot server uses a 64-character random token, reports no self messages,
  and has no HTTP server, HTTP client, or reverse WebSocket client.

NapCat v4.18.13 may create an empty current-schema `onebot11_<QQ>.json` even
when legacy Docker environment variables are present. Configure the current
schema before the first login:

```bash
python3 ./configure_napcat_onebot.py
```

The script reads the account and token from the private `stack.env`, never
prints either secret, and moves any previous configuration into `/srv/trash`.

To open the WebUI from Windows:

```powershell
ssh -i 'C:\path\to\deployment-key.pem' -L 16099:127.0.0.1:16099 root@SERVER_IP
```

Then visit `http://127.0.0.1:16099/webui` while the SSH session remains open.
The WebUI token must be pasted into the login page; this NapCat version does
not automatically accept it from a `?token=` query parameter.

## Resource envelope

- NapCat: 960 MB hard limit, 0.80 CPU.
- Higgs: 384 MB hard limit, 0.50 CPU.
- Docker logs: 8 MB × 3 files per container.
- The host should retain at least 3 GB total swap while using this profile.

If NapCat repeatedly reaches its hard memory limit, stop this stack and migrate
to the planned 4-core / 8-GB server instead of removing the limit.

## Daily-plan rollout

The agent now keeps twelve consistent SQLite stores. In addition to the ten
planner-era stores, `transport.sqlite` contains anonymous channel state and
`tool_audit.sqlite` contains hashed tool decisions/receipts. All twelve are
included in startup and periodic recovery snapshots. Start
the planner in `shadow` mode on this 2-GB host:

```dotenv
R_AGENT_DAILY_PLAN_MODE=shadow
R_AGENT_DAILY_PLAN_DRAFTS_PER_DAY=10
R_AGENT_DAILY_PLAN_MAP_OPTIMIZATIONS_PER_DAY=3
```

Do not configure `R_AGENT_AMAP_WEB_KEY` until Amap Web Service access is ready.
The key belongs only in `/srv/secrets/higgs/higgs.env`.
Use `configure_daily_plan.py --image higgs-agent:<40-character-commit> --mode shadow`
to back up both private env files to `/srv/trash` and update them atomically without
printing any existing secret.

## Read-only host status tool

Stage 3 adds one deliberately narrow owner command:

```text
/higgs server status
```

Install the host-side timer once from the active release:

```bash
install -m 0644 higgs-server-status.service /etc/systemd/system/
install -m 0644 higgs-server-status.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now higgs-server-status.timer
systemctl start higgs-server-status.service
```

The timer writes only `/srv/data/higgs/server-status/status.json`. The agent
bind-mounts that directory read-only at `/run/higgs-server-status`; it has no
Docker socket, host shell, or general path reader. A missing, malformed, linked,
or older-than-180-seconds snapshot is reported as unavailable. The command is
owner-only and model shadow requests cannot execute it.

## One-shot official owner capture

Keep `R_AGENT_OFFICIAL_QQ_ENABLED=false` while binding the official sandbox
owner. Before the capture window, verify in the QQ Bot console that the owner is
the only test user. Then run the bounded helper from the active release:

```bash
bash run_official_owner_capture.sh ONLY_OWNER_IS_TEST_USER
```

The helper takes an exclusive host lock, starts one temporary `agent` container
with `--no-deps`, ignores group and pre-READY events, and accepts only the first
C2C sender. It never prints the OpenID, credentials, message ID, or message
content. The old private environment is copied to a mode-`0600` backup, the
owner binding is replaced atomically, and the script proves that the official
channel is still disabled before returning. A timeout stops the temporary
Gateway without adding a binding. Do not run the helper unless the platform
test-user list contains exactly one owner entry.

## Operator commands

Once the official shadow is approved, install and enable
`higgs-existing-official.service` in place of `higgs-existing.service`. The
official unit owns the complete base-plus-overlay Compose command and runs the
runtime-directory preflight before every start. During the one-time migration,
disable the legacy unit **without stopping it**, then enable and start the
official unit. The units deliberately do not declare `Conflicts=` because
stopping the legacy `RemainAfterExit` unit would execute its complete-stack
`ExecStop` and interrupt NapCat. Never re-enable or reload the legacy unit after
migration. Keep the reply gate false through the first shadow and supervised
Resume observation.

The migration sequence is:

```bash
systemctl disable higgs-existing.service
systemctl enable higgs-existing-official.service
systemctl start higgs-existing-official.service
```

Do not use `systemctl stop`, `disable --now`, or `restart` on the legacy unit
during migration. Record the NapCat container identity and start time before
the sequence and prove both are unchanged afterward.

If the anonymous Node capture succeeded but no owner OpenID was retained, use
the audited one-shot Node binder before enabling shadow ingestion. First prove
that the QQ Bot platform test-user list contains only the owner, then run:

```bash
sh run_official_node_owner_bind.sh ONLY_OWNER_IS_TEST_USER higgs-official-qq:<commit>
```

The binder accepts only the first authenticated C2C sender, writes the OpenID
directly into a private `0600` file, atomically updates both private environment
files, moves the intermediate file to `/srv/trash`, and exits. It never exposes
the OpenID, message ID, content, credentials, or attachments and never enables
the official Agent transport. A separate deployment gate is still required.

## Bounded official ordinary-user capture

Ordinary C2C is a separate opt-in gate. A missing or empty allowlist never
disables the already-bound owner C2C, but it also never acts as a wildcard for
other users. Before capture, migrate only the identity schema while every
ordinary/group audience and Persona gate remains disabled:

```bash
sh migrate_official_identity_v2.sh \
  MIGRATE_OFFICIAL_IDENTITY_V2 \
  PRODUCTION_IDENTITY_MIGRATION_CONFIRMED
```

This operation takes a SQLite-consistent identity backup, binds the configured
owner to the currently authenticated Bot account without changing the existing
principal, and recreates only the Agent. The official sidecar and NapCat must
retain their container identity, start time, and restart count. Any failure
restores both `higgs.env` and `identity.sqlite` from the private recycle archive.
It never opens ordinary C2C, group, or their Persona gates.

After that migration has been reviewed separately, capture the QQ Bot platform
test users from the active release:

```bash
sh run_official_node_private_capture.sh \
  CAPTURE_OFFICIAL_TEST_USERS \
  higgs-official-qq:<40-character-commit>
```

The helper briefly stops only the production sidecar, runs one capture-only
Gateway, and restores the owner transport before it exits; Agent and NapCat
must remain unchanged. It accepts C2C events only during its 10--900 second window. It stores
only unique, Bot-account-bound OpenIDs in a private `0600` state file; message
content, message IDs, and platform receipts are never written. It refuses to
overwrite an existing capture or frozen list and leaves ordinary C2C disabled.
After reviewing the candidate count out of band, freeze exactly that count:

```bash
sh freeze_official_private_users.sh \
  FREEZE_OFFICIAL_TEST_USERS \
  <candidate-count> \
  higgs-official-qq:<40-character-commit>
```

Freezing writes an atomic `0600` allowlist bound to the captured AppID and Bot
account, then copies the same OpenID set into both private environment files.
The ordinary switch remains false, so this step does not activate any new
user. Before a later activation, validate the two files without printing
their values:

```bash
python3 validate_official_channels.py
```

Use `--release` only as a separate, explicitly reviewed preflight; it fails
closed while the sidecar is capture-only or either official transport is off.
The runtime checks the frozen AppID and Bot identity on READY/RESUMED before
it can admit ordinary C2C. It also requires the frozen OpenID set to exactly
match the private environment allowlist (after the owner union); any file/env
drift or wildcard fails closed. Changing to another Bot therefore cannot reuse
an old private allowlist.

Audience activation is a later, separately confirmed action. It now refuses to
migrate identity implicitly: `R_AGENT_IDENTITY_SCHEMA_V2_ENABLED=true` must
already be present and verified. Activation may then open only the selected
versioned audience and its Persona gate; its existing identity backup remains a
rollback snapshot for any principal rows created during the activation window.

## Anonymous official-channel observation

After the first real passive reply succeeds, run a bounded 72-hour observation
before allowlisting a test group. Supply UTC epoch milliseconds for the exact
window boundaries:

```bash
bash observe_official_stability.sh <window-start-epoch-ms> <window-end-epoch-ms>
```

The helper is read-only. It checks the three container health states and restart
counts, a single official Gateway, the private reply gate, the anonymous
`qq_official` transport state and freshness, bounded transition counters, and
the number of active durable batches. SQLite is opened with `mode=ro` and
`query_only`; the script does not read logs or print container IDs, identities,
message content, platform message IDs, receipt IDs, or credentials. It never
sends a message, restarts a container, changes configuration, or logs in.

Treat any rejected or fatal transition, account mismatch, non-singleton
Gateway, stale health receipt, unhealthy container, or durable batch that does
not converge as an incident requiring manual review. A recovered reconnect is
still evidence to retain in the final observation result; do not erase it by
resetting the observation start time.

## Owner-only proactive reminders

Keep both proactive gates false during the fixed 72-hour observation:

```text
R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED=false
HIGGS_OFFICIAL_QQ_PROACTIVE_ENABLED=false
```

They are independent fail-closed gates in the Agent and sidecar private
environment files. Enabling only one cannot send an official proactive message.
Official reminders must originate in the owner's C2C conversation and persist
an explicit official channel, private surface, current Bot account, and owner
target. Pre-migration reminder approvals are version 1 and remain eligible only
for their historical OneBot target; they can never migrate into the official
channel. New approvals are version 2 and cover the full delivery binding.

Do not enable either gate until the 72-hour result is accepted, the active
legacy-binding count has been reviewed, and a separate production change is
approved. The audited activation entry point is:

```bash
sh activate_official_owner_proactive.sh \
  ACTIVATE_OWNER_PROACTIVE \
  STABILITY_72H_ACCEPTED
```

It updates both private files atomically, recreates only the official sidecar
and Agent, and rolls back both gates together if the single Gateway, verified
transport, reminder schema, or zero-active-batch checks fail. NapCat is checked
before and after and must not be restarted as part of this change.

## Versioned official test-group capture and freeze

Group onboarding is a bounded, repeatable `CaptureEpoch` followed by a
versioned `AllowlistVersion`. It does not require a fixed 72-hour observation.
The capture helper briefly stops only the official sidecar, runs one
capture-only Gateway, and restores the owner transport before it exits; Agent
and NapCat must retain their identity, start time, and restart count:

```bash
sh run_official_node_group_bind.sh \
  CAPTURE_OFFICIAL_TEST_GROUP \
  higgs-official-qq:<40-character-commit>
```

The private state directory contains `group-capture.json` and
`allowed-group-openids.json`, both v2 envelopes with App/Bot binding, nonce,
deadline, monotonic version, previous-version/fingerprint, canonical sorted
identities, and a recomputable SHA-256 fingerprint. The default limit is one
group per epoch. Existing v2 allowlists are used as the explicit baseline on
the next epoch; a legacy `group.openid` or v1 file fails closed and is never
silently imported. No identity or message content is printed.

After reviewing the closed capture, freeze the next immutable version while
all ordinary/group and corresponding Persona gates remain disabled. Identity
schema v2 may already be enabled by its separately approved migration:

```bash
sh freeze_official_group.sh \
  FREEZE_OFFICIAL_TEST_GROUP \
  1 \
  higgs-official-qq:<40-character-commit>
```

The freeze wrapper moves the previous allowlist to a timestamped
`/srv/trash/higgs-official-group-freeze-*` archive before staging it as the
Node baseline. Any failed freeze restores that allowlist, capture, and private
environment files from the archive; successful freeze synchronizes only the
group IDs, version, and fingerprint in Agent and sidecar configuration. The
owner official transport may remain enabled and running. Production group
activation is a separate follow-up slice and is intentionally not performed
by these wrappers. Only `GROUP_AT_MESSAGE_CREATE` is accepted for future
group activation, so ordinary non-mention messages never enter the pipeline.

Run these from `/srv/apps/higgs/current/deploy/existing-server`:

```bash
docker compose --env-file /srv/secrets/higgs/stack.env ps
docker compose --env-file /srv/secrets/higgs/stack.env logs --tail=120 napcat
docker compose --env-file /srv/secrets/higgs/stack.env logs --tail=120 agent
systemctl reload higgs-existing-official.service
systemctl status higgs-existing-official.service --no-pager
```

Do not publish ports `3001` or `6099`, and do not add a public Nginx route for
NapCat or Higgs management functions.
