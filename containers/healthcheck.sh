#!/bin/bash
SIGNAL_API="http://localhost:8080"
SIGNAL_NUMBER="+447963511525"
HC_PING="https://hc-ping.com/662d8f4b-56f1-46ee-9cac-2bc82567be0b"

fail() {
  local msg="$1"
  curl -fsS -m 10 "${HC_PING}/fail" > /dev/null
  curl -s -X POST "$SIGNAL_API/v2/send" \
    -H "Content-Type: application/json" \
    -d "{\"number\": \"$SIGNAL_NUMBER\", \"recipients\": [\"$SIGNAL_NUMBER\"], \"message\": \"⚠️ peachhouse: $msg\"}" > /dev/null
  exit 1
}

containers=("adguard-adguard-1" "caddy-caddy-1" "homepage" "immich-server" "immich-postgres" "immich-redis" "immich-machine-learning" "plex" "signal-signal-api-1" "syncthing-syncthing-1" "gluetun" "qbittorrent" "prowlarr" "radarr" "sonarr" "overseerr" "bazarr" "code-server" "nextcloud" "nextcloud-db" "nextcloud-redis")
for c in "${containers[@]}"; do
  if ! docker inspect --format='{{.State.Running}}' "$c" 2>/dev/null | grep -q true; then
    fail "container '$c' is down!"
  fi
done

# Disk space: alert if /mnt/peach_storage exceeds 85% used
disk_pct=$(df --output=pcent /mnt/peach_storage | tail -1 | tr -d ' %')
if [ "$disk_pct" -gt 85 ]; then
  fail "disk /mnt/peach_storage is ${disk_pct}% full!"
fi

# Tailscale connectivity
if ! tailscale status --json 2>/dev/null | grep -q '"BackendState": "Running"'; then
  fail "Tailscale is not connected!"
fi

# Signal backup freshness: alert if no backup in last 14 days
latest_backup=$(find /mnt/peach_storage/syncthing/signal-backups -name "*.backup" -mtime -14 2>/dev/null | sort | tail -1)
if [ -z "$latest_backup" ]; then
  fail "no Signal backup in the last 14 days!"
fi

# Ollama (Server) only — desktop GPU proxy (11435) is on-demand, not monitored
if ! curl -fsS -m 5 "http://localhost:11434/api/tags" > /dev/null 2>&1; then
  fail "Ollama (Server) is not reachable!"
fi

curl -fsS -m 10 "$HC_PING" > /dev/null
