# Higgs cloud deployment

This directory is the version-controlled, secret-free deployment skeleton for the
new Tencent Cloud Lighthouse instance. It targets Ubuntu Server 24.04 LTS with
Docker CE. **Do not run these scripts on the existing rollback server.**

## Layout

```text
/srv/
├── platform/       # Caddy and shared edge network
├── apps/higgs/     # active Higgs Compose release
├── data/higgs/     # NapCat and agent persistent data
├── releases/       # immutable releases named by Git commit
├── backups/        # local backup output
├── secrets/        # chmod 700, never committed
└── trash/          # replaced releases and files; never delete directly
```

- `platform/`: Caddy only. Higgs and NapCat have no public route.
- `higgs/`: isolated NapCat/agent Compose stack with resource and log limits.
- `server/`: one-time bootstrap, systemd units and release activation.
- `backups/`: encrypted off-site backup templates.

## Deployment order

1. Purchase the new Beijing Lighthouse and keep the old instance unchanged.
2. Log in once as the image-provided administrator and run
   `server/bootstrap_ubuntu.sh` with the new deploy public key.
3. Reconnect as `deploy` and verify key login before closing the original session.
4. Resolve every container tag to a repository digest. Put only the resulting
   `name@sha256:...` values in `/srv/secrets/*/stack.env`.
5. Copy `higgs/.env.server.example` to `/srv/secrets/higgs/stack.env`, copy the
   application `.env` to `/srv/secrets/higgs/higgs.env`, and set all secret files
   to mode `600`.
6. Install and enable `server/higgs-stack.service`.
7. Open the NapCat WebUI only through an SSH tunnel:

   ```bash
   ssh -L 16099:127.0.0.1:16099 deploy@SERVER_IP
   ```

8. Scan a fresh QQ QR code on the Linux host. Never copy the Windows QQ login
   directory to the server.
9. Run the private-chat, group-chat, memory, backup and reboot acceptance tests
   before stopping the local Windows instance.

The public repository never contains `.env`, access tokens, QQ state, databases,
backups, COS credentials, private keys, API keys or production photographs.
