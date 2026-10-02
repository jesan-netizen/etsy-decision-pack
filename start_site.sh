#!/usr/bin/env bash
# Serve the Etsy Decision Pack site on port 8420.
#
#   ./start_site.sh              # foreground
#   ./start_site.sh --daemon     # background, writes site/build/server.pid
#
# Everything is static and self-contained: no CDN, no build step at serve time.

set -euo pipefail
SITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8420
BIND=0.0.0.0
LOG="$SITE_DIR/build/server.log"

if [[ "${1:-}" == "--daemon" ]]; then
  mkdir -p "$SITE_DIR/build"
  if [[ -f "$SITE_DIR/build/server.pid" ]] && kill -0 "$(cat "$SITE_DIR/build/server.pid")" 2>/dev/null; then
    echo "already running on port $PORT (pid $(cat "$SITE_DIR/build/server.pid"))"
    exit 0
  fi
  cd "$SITE_DIR"
  nohup python3 -m http.server "$PORT" --bind "$BIND" >"$LOG" 2>&1 &
  echo $! > "$SITE_DIR/build/server.pid"
  sleep 1
  echo "serving $SITE_DIR on http://0.0.0.0:$PORT  (pid $(cat "$SITE_DIR/build/server.pid"), log $LOG)"
  exit 0
fi

cd "$SITE_DIR"
echo "Serving $SITE_DIR"
echo "  http://localhost:$PORT/"
echo "Ctrl-C to stop."
exec python3 -m http.server "$PORT" --bind "$BIND"