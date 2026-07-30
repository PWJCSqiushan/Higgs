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
- The first NapCat start generates its OneBot server configuration from the
  private `stack.env`: WebSocket enabled on `0.0.0.0:3001` inside Docker,
  self-message reporting disabled, and a 32+ character random access token.

To open the WebUI from Windows:

```powershell
ssh -i 'C:\path\to\deployment-key.pem' -L 16099:127.0.0.1:16099 root@SERVER_IP
```

Then visit `http://127.0.0.1:16099/` while the SSH session remains open.

## Resource envelope

- NapCat: 960 MB hard limit, 0.80 CPU.
- Higgs: 384 MB hard limit, 0.50 CPU.
- Docker logs: 8 MB × 3 files per container.
- The host should retain at least 3 GB total swap while using this profile.

If NapCat repeatedly reaches its hard memory limit, stop this stack and migrate
to the planned 4-core / 8-GB server instead of removing the limit.

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
