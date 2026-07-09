#!/data/data/com.termux/files/usr/bin/sh
# Aria installer/updater — run from the repo dir on the phone:
#   cd ~/aria && sh install.sh
# Idempotent: safe to re-run after every `git pull`.
set -e
REPO="$(cd "$(dirname "$0")" && pwd)"
echo "== Aria install from $REPO =="

# 0. sanity: are we on Termux?
[ -n "$PREFIX" ] || { echo "ERROR: run this inside Termux"; exit 1; }

# 1. packages (idempotent; termux-services gives supervised auto-restart)
pkg install -y termux-services termux-api curl >/dev/null 2>&1 || \
    echo "warn: pkg install failed — offline? continuing"
python -c "import httpx" 2>/dev/null || pip install httpx

# 2. syntax-check the assistant BEFORE touching anything live
python -m py_compile "$REPO/edge_assistant.py"
NEWV=$(python "$REPO/edge_assistant.py" --version)
echo "installing: $NEWV"

# 3. shared token (closes the app->localhost attack surface)
if [ ! -f "$HOME/.aria_token" ]; then
    head -c 32 /dev/urandom | sha256sum | cut -d' ' -f1 > "$HOME/.aria_token"
    chmod 600 "$HOME/.aria_token"
    echo "generated ~/.aria_token"
fi

# 4. config (never overwrite a live config)
[ -f "$HOME/.aria.conf" ] || { cp "$REPO/aria.conf.example" "$HOME/.aria.conf"; echo "created ~/.aria.conf"; }

# 5. runit services (auto-restart + rotated logs)
if [ -x "$PREFIX/bin/sv-enable" ]; then
    for svc in llama aria; do
        mkdir -p "$PREFIX/var/service/$svc/log"
        cp "$REPO/services/$svc/run" "$PREFIX/var/service/$svc/run"
        chmod +x "$PREFIX/var/service/$svc/run"
        ln -sf "$PREFIX/share/termux-services/svlogger" "$PREFIX/var/service/$svc/log/run"
    done
    sv-enable llama 2>/dev/null || true
    sv-enable aria  2>/dev/null || true
    echo "services installed (sv status llama aria)"
else
    echo "warn: termux-services missing — boot script will use legacy start"
fi

# 6. boot script + widget shortcuts
mkdir -p "$HOME/.termux/boot" "$HOME/.shortcuts" "$HOME/bin"
cp "$REPO/boot/start-aria.sh" "$HOME/.termux/boot/start-aria.sh"
cp "$REPO/shortcuts/Aria-Voice.sh" "$HOME/.shortcuts/Aria-Voice.sh"
cp "$REPO/shortcuts/Aria-Status.sh" "$HOME/.shortcuts/Aria-Status.sh"
cp "$REPO/bin/aria-watchdog.sh" "$HOME/bin/aria-watchdog.sh"
chmod +x "$HOME/.termux/boot/start-aria.sh" "$HOME/.shortcuts/"Aria-*.sh \
         "$HOME/bin/aria-watchdog.sh"

# 7. watchdog via Android's own scheduler (survives in-Termux kills), 15 min
termux-job-scheduler --script "$HOME/bin/aria-watchdog.sh" \
    --period-ms 900000 --persisted true >/dev/null 2>&1 && \
    echo "watchdog registered (every 15 min)" || \
    echo "warn: job-scheduler registration failed (Termux:API missing?)"

# 8. model checksums (fills models.sha256 on first run; verifies after)
if [ -s "$REPO/models.sha256" ] && ! grep -q FILL_ME "$REPO/models.sha256"; then
    (cd / && sha256sum -c "$REPO/models.sha256") && echo "model checksums OK" || \
        echo "WARN: MODEL CHECKSUM MISMATCH — re-download before trusting output"
else
    echo "recording model checksums into models.sha256 (commit this!)"
    { sha256sum "$HOME"/models/*.gguf 2>/dev/null;
      sha256sum "$HOME"/whisper.cpp/models/ggml-*.bin 2>/dev/null; } > "$REPO/models.sha256" || true
fi

# 9. restart the serve endpoint on the new code, then verify everything
command -v sv >/dev/null && sv restart aria 2>/dev/null || true
echo
python "$REPO/edge_assistant.py" --selftest || true

echo
echo "== done. Remaining MANUAL steps (once, see RUNBOOK.md phase 1): =="
echo "  1. Disable the phantom process killer (Developer Options or ADB) — CRITICAL"
echo "  2. Place the Termux:Widget shortcuts on the home screen"
echo "  3. Settings->Battery: enable Motorola Overcharge Protection if charger-parked"
