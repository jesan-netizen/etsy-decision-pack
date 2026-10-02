#!/usr/bin/env bash
# tunnel_watchdog.sh — keep the Etsy decision pack reachable.
#
# Checks the Cloudflare quick tunnel every 5 minutes. If the tunnel process is
# gone, or its public URL no longer returns HTTP 200, it restarts cloudflared and
# writes the new trycloudflare URL to build/tunnel.url (the URL changes on every
# restart, so nothing downstream can hard-code it).
#
# Start once, detached:   nohup /home/ubuntu/etsy_research/site/tunnel_watchdog.sh &
# Logs:                   /home/ubuntu/etsy_research/site/build/watchdog.log
# Stop:                   pkill -f tunnel_watchdog.sh

set -uo pipefail

SITE_DIR="/home/ubuntu/etsy_research/site"
BUILD_DIR="$SITE_DIR/build"
PORT=8420
LOG="$BUILD_DIR/watchdog.log"
URL_FILE="$BUILD_DIR/tunnel.url"
TUNNEL_LOG="$BUILD_DIR/tunnel2.log"
INTERVAL=300          # 5 minutes
LOCK="/tmp/etsy_tunnel_watchdog.lock"

mkdir -p "$BUILD_DIR"

log() {
  printf '%s [watchdog] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >> "$LOG"
}

# Only one watchdog may run at a time.
exec 9>"$LOCK"
if ! flock -n 9; then
  log "another watchdog already holds the lock; exiting"
  exit 0
fi

log "watchdog started (interval ${INTERVAL}s, port $PORT)"

# The origin server must be up or no tunnel can help.
ensure_origin() {
  if ! curl -fsS -o /dev/null --max-time 10 "http://127.0.0.1:${PORT}/"; then
    log "origin :${PORT} is not answering; starting python3 -m http.server"
    # 9>&- : do not let the child inherit the flock fd, or the "watchdog" lock
    # stays held for the life of http.server and no watchdog can ever start.
    ( cd "$SITE_DIR" && nohup python3 -m http.server "$PORT" --bind 0.0.0.0 \
        >> "$BUILD_DIR/http.log" 2>&1 9>&- & )
    sleep 3
  fi
}

tunnel_pid() {
  pgrep -f "^/usr/local/bin/cloudflared tunnel --url http://localhost:${PORT}" | head -1
}

read_url() {
  [ -f "$URL_FILE" ] && tr -d '[:space:]' < "$URL_FILE" || true
}

# Pull the newest trycloudflare URL out of the tunnel log.
# $1 = byte offset to start reading from, so a restart only ever considers lines
# written by the NEW process. Without this, a restart can latch onto the PREVIOUS
# run's URL (the log is appended) and report a dead tunnel as healthy.
url_from_log() {
  local offset="${1:-0}"
  tail -c "+$((offset + 1))" "$TUNNEL_LOG" 2>/dev/null \
    | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1
}

# A candidate URL is only accepted once it actually serves the pack.
url_serves() {
  local url="$1"
  [ -n "$url" ] || return 1
  [ "$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 20 "$url/" || echo 000)" = "200" ]
}

tunnel_healthy() {
  local url="$1"
  [ -n "$url" ] || return 1
  [ -n "$(tunnel_pid)" ] || return 1
  url_serves "$url"
}

start_tunnel() {
  # Remember where the log ends so we only read what THIS process writes.
  local offset=0
  [ -f "$TUNNEL_LOG" ] && offset=$(wc -c < "$TUNNEL_LOG")
  log "starting cloudflared quick tunnel -> ${TUNNEL_LOG} (log offset ${offset})"
  nohup /usr/local/bin/cloudflared tunnel --url "http://localhost:${PORT}" \
      --no-autoupdate >> "$TUNNEL_LOG" 2>&1 9>&- &
  # cloudflared prints its URL a few seconds after launch; wait for it, then
  # confirm it actually serves before publishing it.
  local u=""
  for _ in $(seq 1 30); do
    sleep 2
    u=$(url_from_log "$offset")
    if [ -n "$u" ] && url_serves "$u"; then
      printf '%s' "$u" > "$URL_FILE"
      log "new tunnel URL: $u (verified HTTP 200)"
      return 0
    fi
  done
  log "ERROR: no verified trycloudflare URL after 60s (last candidate='${u}')"
  return 1
}

# Record the current URL on first run without restarting a healthy tunnel.
ensure_origin
CURRENT="$(read_url)"
if [ -z "$CURRENT" ] || ! url_serves "$CURRENT"; then
  # adopt the newest URL in the log, but only if it serves
  CAND="$(url_from_log 0)"
  if url_serves "$CAND"; then
    CURRENT="$CAND"
    printf '%s' "$CURRENT" > "$URL_FILE"
  else
    CURRENT=""
  fi
fi

if tunnel_healthy "$CURRENT"; then
  log "tunnel healthy on first check: $CURRENT"
else
  log "tunnel not healthy at start (url='${CURRENT}'); restarting"
  start_tunnel
fi

while true; do
  sleep "$INTERVAL"
  ensure_origin
  CURRENT="$(read_url)"
  if tunnel_healthy "$CURRENT"; then
    log "OK  $CURRENT (pid $(tunnel_pid))"
  else
    log "DEAD url='${CURRENT}' pid='$(tunnel_pid)' — restarting tunnel"
    # match the binary path, not the bare pattern: a bare pattern also matches
    # the shell that runs this script and kills the watchdog itself
    pkill -f "^/usr/local/bin/cloudflared tunnel --url http://localhost:${PORT}" 2>/dev/null
    sleep 3
    start_tunnel
  fi
done
