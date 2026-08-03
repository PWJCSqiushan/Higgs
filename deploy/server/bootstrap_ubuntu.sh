#!/usr/bin/env bash
set -euo pipefail

# Run only on the NEW Ubuntu 24.04 Lighthouse as root:
#   DEPLOY_PUBLIC_KEY='ssh-ed25519 ...' bash bootstrap_ubuntu.sh

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on the new server." >&2
  exit 1
fi
if [[ -z "${DEPLOY_PUBLIC_KEY:-}" || ! "${DEPLOY_PUBLIC_KEY}" =~ ^ssh-(ed25519|rsa)[[:space:]] ]]; then
  echo "Set DEPLOY_PUBLIC_KEY to the public key for the deploy account." >&2
  exit 1
fi
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "This bootstrap is restricted to Ubuntu 24.04." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y age ca-certificates curl gnupg jq ufw unattended-upgrades zstd

if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  arch="$(dpkg --print-architecture)"
  codename="${VERSION_CODENAME}"
  echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if ! id deploy >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash deploy
fi
usermod -aG docker deploy
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
key_file=/home/deploy/.ssh/authorized_keys
touch "${key_file}"
chown deploy:deploy "${key_file}"
chmod 0600 "${key_file}"
if ! grep -Fqx "${DEPLOY_PUBLIC_KEY}" "${key_file}"; then
  printf '%s\n' "${DEPLOY_PUBLIC_KEY}" >> "${key_file}"
fi

install -d -m 0755 -o deploy -g deploy \
  /srv/platform /srv/apps /srv/apps/higgs /srv/data /srv/data/higgs \
  /srv/releases /srv/backups /srv/trash
install -d -m 0700 -o deploy -g deploy /srv/secrets /srv/secrets/higgs

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

hardening=/etc/ssh/sshd_config.d/60-higgs-hardening.conf
cat > "${hardening}" <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
sshd -t
systemctl reload ssh
systemctl enable --now docker

echo "Bootstrap complete. Keep this session open and verify a new deploy SSH login now."
