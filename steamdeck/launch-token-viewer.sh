#!/usr/bin/env bash
# Launch the Claude Token Viewer on a Steam Deck.
# Starts the local server, opens a browser pointed at it, and shuts the
# server down again when the browser closes. Add this script to Steam as a
# non-Steam game to use it from Gaming Mode.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${TOKEN_VIEWER_PORT:-8484}"
URL="http://127.0.0.1:${PORT}"

python3 "$DIR/token-viewer.py" --port "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null' EXIT

# Wait (up to ~10s) for the server to accept connections.
for _ in $(seq 1 50); do
  if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.2)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${PORT}))==0 else 1)"; then
    break
  fi
  sleep 0.2
done

# Prefer a fullscreen/kiosk chromium-family browser (nicest in Gaming Mode),
# then Firefox, then whatever the desktop default is.
if flatpak info com.google.Chrome >/dev/null 2>&1; then
  flatpak run com.google.Chrome --kiosk --no-first-run "$URL"
elif flatpak info org.chromium.Chromium >/dev/null 2>&1; then
  flatpak run org.chromium.Chromium --kiosk --no-first-run "$URL"
elif command -v chromium >/dev/null 2>&1; then
  chromium --kiosk --no-first-run "$URL"
elif flatpak info org.mozilla.firefox >/dev/null 2>&1; then
  flatpak run org.mozilla.firefox --kiosk "$URL"
elif command -v firefox >/dev/null 2>&1; then
  firefox --kiosk "$URL"
else
  xdg-open "$URL"
  # xdg-open returns immediately; keep the server alive until interrupted.
  wait "$SERVER_PID"
fi
