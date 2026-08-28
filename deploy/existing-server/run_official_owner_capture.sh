#!/usr/bin/env bash
set -euo pipefail

confirmation="${1:-}"
if [[ "$confirmation" != "ONLY_OWNER_IS_TEST_USER" ]]; then
  echo "owner_capture: explicit single-test-user confirmation is required" >&2
  exit 2
fi

stack_env="${HIGGS_STACK_ENV:-/srv/secrets/higgs/stack.env}"
config_dir="${HIGGS_CONFIG_DIR:-/srv/secrets/higgs}"
compose_dir="${HIGGS_COMPOSE_DIR:-/srv/apps/higgs/current/deploy/existing-server}"
timeout_seconds="${HIGGS_OWNER_CAPTURE_TIMEOUT_SECONDS:-300}"
higgs_env="${config_dir}/higgs.env"

for command in docker flock stat awk grep; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "owner_capture: required command is unavailable" >&2
    exit 3
  fi
done
if [[ ! -f "$stack_env" || -L "$stack_env" || ! -f "$higgs_env" || -L "$higgs_env" ]]; then
  echo "owner_capture: private configuration is unavailable or unsafe" >&2
  exit 3
fi
if [[ "$(stat -c '%a' "$stack_env")" != "600" || "$(stat -c '%a' "$higgs_env")" != "600" ]]; then
  echo "owner_capture: private configuration must use mode 0600" >&2
  exit 3
fi
if ! [[ "$timeout_seconds" =~ ^[0-9]+$ ]] || (( timeout_seconds < 10 || timeout_seconds > 900 )); then
  echo "owner_capture: timeout must be an integer from 10 to 900" >&2
  exit 3
fi

owner_count="$(awk -F= '$1=="R_AGENT_OFFICIAL_QQ_OWNER_OPENID"{c++} END{print c+0}' "$higgs_env")"
app_count="$(awk -F= '$1=="R_AGENT_OFFICIAL_QQ_APP_ID"{c++} END{print c+0}' "$higgs_env")"
secret_count="$(awk -F= '$1=="R_AGENT_OFFICIAL_QQ_CLIENT_SECRET"{c++} END{print c+0}' "$higgs_env")"
if [[ "$owner_count" != "0" || "$app_count" != "1" || "$secret_count" != "1" ]]; then
  echo "owner_capture: official private configuration is not capture-ready" >&2
  exit 3
fi
if grep -Eqi '^R_AGENT_OFFICIAL_QQ_ENABLED=(true|1|yes|on)$' "$higgs_env"; then
  echo "owner_capture: official QQ must remain disabled" >&2
  exit 3
fi

exec 9>"${config_dir}/.official-owner-capture.lock"
chmod 600 "${config_dir}/.official-owner-capture.lock"
if ! flock -n 9; then
  echo "owner_capture: another capture process is active" >&2
  exit 4
fi

cd "$compose_dir"
docker compose --env-file "$stack_env" run --rm --no-deps \
  agent r-agent-official-owner-capture \
  --env-file /run/higgs-config/higgs.env \
  --data-dir /var/lib/higgs \
  --backup-dir /run/higgs-config/owner-capture-backups \
  --timeout-seconds "$timeout_seconds" \
  --confirm-single-test-user ONLY_OWNER_IS_TEST_USER

owner_count="$(awk -F= '$1=="R_AGENT_OFFICIAL_QQ_OWNER_OPENID"{c++} END{print c+0}' "$higgs_env")"
if [[ "$owner_count" != "1" ]] || grep -Eqi '^R_AGENT_OFFICIAL_QQ_ENABLED=(true|1|yes|on)$' "$higgs_env"; then
  echo "owner_capture: post-capture verification failed" >&2
  exit 5
fi
if [[ "$(stat -c '%a' "$higgs_env")" != "600" ]]; then
  echo "owner_capture: private configuration permissions changed" >&2
  exit 5
fi

echo "owner_capture: verified; official QQ remains disabled"
