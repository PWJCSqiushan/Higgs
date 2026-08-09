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

The agent now keeps ten consistent SQLite stores. `agenda.sqlite` contains
principal-isolated daily plans and `skills.sqlite` contains exact-parameter
approvals; both are included in startup and periodic recovery snapshots. Start
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

## Operator commands

Run these from `/srv/apps/higgs/current/deploy/existing-server`:

```bash
docker compose --env-file /srv/secrets/higgs/stack.env ps
docker compose --env-file /srv/secrets/higgs/stack.env logs --tail=120 napcat
docker compose --env-file /srv/secrets/higgs/stack.env logs --tail=120 agent
systemctl stop higgs-existing.service
systemctl start higgs-existing.service
```

Do not publish ports `3001` or `6099`, and do not add a public Nginx route for
NapCat or Higgs management functions.
