#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'usage: %s <window-start-epoch-ms> <window-end-epoch-ms>\n' "$0" >&2
    exit 64
}

[[ $# -eq 2 ]] || usage
window_start_ms="$1"
window_end_ms="$2"
[[ "${window_start_ms}" =~ ^[0-9]{13}$ ]] || usage
[[ "${window_end_ms}" =~ ^[0-9]{13}$ ]] || usage
(( window_end_ms > window_start_ms )) || usage

current="/srv/apps/higgs/current"
stack_env="/srv/secrets/higgs/stack.env"
cd "${current}/deploy/existing-server"
compose=(
    docker compose --env-file "${stack_env}"
    -f compose.yml -f compose.official-qq.yml --profile official-qq
)

"${compose[@]}" config --quiet
agent_id="$(${compose[@]} ps -q agent)"
sidecar_id="$(${compose[@]} ps -q official-qq-sidecar)"
napcat_id="$(${compose[@]} ps -q napcat)"
[[ -n "${agent_id}" && -n "${sidecar_id}" && -n "${napcat_id}" ]]

now_ms="$(( $(date +%s) * 1000 ))"
elapsed_ms="$(( now_ms - window_start_ms ))"
remaining_ms="$(( window_end_ms - now_ms ))"
if (( elapsed_ms < 0 )); then
    printf 'observation_result=invalid_window\n'
    exit 65
fi

agent_health="$(docker inspect --format '{{.State.Health.Status}}' "${agent_id}")"
sidecar_health="$(docker inspect --format '{{.State.Health.Status}}' "${sidecar_id}")"
napcat_health="$(docker inspect --format '{{.State.Health.Status}}' "${napcat_id}")"
agent_restarts="$(docker inspect --format '{{.RestartCount}}' "${agent_id}")"
sidecar_restarts="$(docker inspect --format '{{.RestartCount}}' "${sidecar_id}")"
napcat_restarts="$(docker inspect --format '{{.RestartCount}}' "${napcat_id}")"
agent_started_ms="$(( $(date -d "$(docker inspect --format '{{.State.StartedAt}}' "${agent_id}")" +%s) * 1000 ))"
sidecar_started_ms="$(( $(date -d "$(docker inspect --format '{{.State.StartedAt}}' "${sidecar_id}")" +%s) * 1000 ))"
napcat_started_ms="$(( $(date -d "$(docker inspect --format '{{.State.StartedAt}}' "${napcat_id}")" +%s) * 1000 ))"
gateway_count="$(
    docker ps --filter label=com.docker.compose.service=official-qq-sidecar \
        --format '{{.ID}}' | wc -l
)"
reply_enabled=false
if docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${agent_id}" \
    | grep -qx 'R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=true'; then
    reply_enabled=true
fi

db_result="$(docker exec -i \
    -e HIGGS_OBSERVE_START_MS="${window_start_ms}" \
    -e HIGGS_OBSERVE_NOW_MS="${now_ms}" \
    "${agent_id}" python - <<'PY'
import os
import sqlite3

start_ms = int(os.environ["HIGGS_OBSERVE_START_MS"])
now_ms = int(os.environ["HIGGS_OBSERVE_NOW_MS"])


def connect_read_only(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.execute("PRAGMA query_only = ON")
    return conn


with connect_read_only("/var/lib/higgs/transport.sqlite") as conn:
    state = conn.execute(
        """
        SELECT state, onebot_reachable, qq_online, account_match,
               last_health_state, last_health_at_ms
        FROM transport_state WHERE channel='qq_official'
        """
    ).fetchone()
    counts = conn.execute(
        """
        SELECT COUNT(*),
               COALESCE(SUM(to_state='pending'), 0),
               COALESCE(SUM(to_state='rejected'), 0),
               COALESCE(SUM(to_state='verified'), 0),
               COALESCE(SUM(reason='resumed'), 0),
               COALESCE(SUM(reason='ready'), 0),
               COALESCE(SUM(reason='gateway_reconnecting'), 0),
               COALESCE(SUM(reason IN (
                   'protocol_error', 'heartbeat_ack_timeout',
                   'account_mismatch', 'kicked_offline', 'risk_control'
               )), 0)
        FROM transport_transitions
        WHERE channel='qq_official' AND started_at_ms >= ?
        """,
        (start_ms,),
    ).fetchone()

with connect_read_only("/var/lib/higgs/official_processing.sqlite") as conn:
    active_batches = conn.execute(
        "SELECT COUNT(*) FROM official_processing_batches WHERE state!='complete'"
    ).fetchone()[0]

if state is None:
    raise SystemExit("official transport state is absent")

health_age_ms = -1
if state[5] is not None:
    health_age_ms = max(0, now_ms - int(state[5]))

print(f"transport_state={state[0]}")
print(f"transport_connected={str(bool(state[1])).lower()}")
print(f"transport_authenticated={str(bool(state[2])).lower()}")
print(f"transport_account_match={str(state[3] == 1).lower()}")
print(f"transport_health={state[4]}")
print(f"transport_health_age_ms={health_age_ms}")
print(f"transition_count={counts[0]}")
print(f"pending_transition_count={counts[1]}")
print(f"rejected_transition_count={counts[2]}")
print(f"verified_transition_count={counts[3]}")
print(f"resume_transition_count={counts[4]}")
print(f"ready_transition_count={counts[5]}")
print(f"reconnect_transition_count={counts[6]}")
print(f"fatal_transition_count={counts[7]}")
print(f"active_batches={active_batches}")
PY
)"

printf 'observation_result=checkpoint\n'
printf 'window_elapsed_ms=%s\n' "${elapsed_ms}"
printf 'window_remaining_ms=%s\n' "${remaining_ms}"
printf 'agent_health=%s\n' "${agent_health}"
printf 'agent_restart_count=%s\n' "${agent_restarts}"
printf 'agent_recreated_during_window=%s\n' "$(( agent_started_ms > window_start_ms ))"
printf 'official_sidecar_health=%s\n' "${sidecar_health}"
printf 'official_sidecar_restart_count=%s\n' "${sidecar_restarts}"
printf 'official_sidecar_recreated_during_window=%s\n' "$(( sidecar_started_ms > window_start_ms ))"
printf 'official_gateway_count=%s\n' "${gateway_count}"
printf 'official_reply=%s\n' "${reply_enabled}"
printf 'napcat_container_health=%s\n' "${napcat_health}"
printf 'napcat_container_restart_count=%s\n' "${napcat_restarts}"
printf 'napcat_recreated_during_window=%s\n' "$(( napcat_started_ms > window_start_ms ))"
printf '%s\n' "${db_result}"

[[ "${agent_health}" == "healthy" ]]
[[ "${sidecar_health}" == "healthy" ]]
[[ "${napcat_health}" == "healthy" ]]
[[ "${gateway_count}" -eq 1 ]]
[[ "${reply_enabled}" == "true" ]]
(( agent_started_ms <= window_start_ms ))
(( sidecar_started_ms <= window_start_ms ))
(( napcat_started_ms <= window_start_ms ))
grep -qx 'transport_state=verified' <<<"${db_result}"
grep -qx 'transport_connected=true' <<<"${db_result}"
grep -qx 'transport_authenticated=true' <<<"${db_result}"
grep -qx 'transport_account_match=true' <<<"${db_result}"
grep -qx 'transport_health=ok' <<<"${db_result}"
rejected_count="$(sed -n 's/^rejected_transition_count=//p' <<<"${db_result}")"
fatal_count="$(sed -n 's/^fatal_transition_count=//p' <<<"${db_result}")"
[[ "${rejected_count}" =~ ^[0-9]+$ && "${fatal_count}" =~ ^[0-9]+$ ]]
(( rejected_count == 0 ))
(( fatal_count == 0 ))
health_age_ms="$(sed -n 's/^transport_health_age_ms=//p' <<<"${db_result}")"
[[ "${health_age_ms}" =~ ^[0-9]+$ ]]
(( health_age_ms <= 120000 ))

if (( now_ms >= window_end_ms )); then
    printf 'observation_window=complete\n'
else
    printf 'observation_window=in_progress\n'
fi
