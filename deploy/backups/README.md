# Backup policy

Higgs uses four layers:

1. SQLite-consistent application backups every six hours.
2. A daily encrypted archive staged under `/srv/backups/outbox`.
3. A private Beijing COS bucket with SSE-COS AES-256 and a 30-day lifecycle.
4. A monthly restore drill into a new temporary directory.

The COS CAM identity must be restricted to writing a single backup prefix. It
must not have object deletion permission. The `age` recipient public key may be
stored on the server; the corresponding private key stays offline on the user's
computer and in a second offline copy.

Never upload raw `.env`, API keys or a decryption private key unencrypted. Server
snapshots complement these backups but are not their replacement.
