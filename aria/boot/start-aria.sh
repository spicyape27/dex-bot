#!/data/data/com.termux/files/usr/bin/sh
# Aria boot script — installed to ~/.termux/boot/start-aria.sh by install.sh
# Idempotent: safe if Termux:Boot runs it twice.

mkdir -p "$HOME/.aria/logs"
exec >> "$HOME/.aria/logs/boot.log" 2>&1
echo "== boot $(date -Is) =="

termux-wake-lock

# Preferred path: termux-services (runit) supervises everything —
# auto-restart on crash + rotated logs in $PREFIX/var/log/sv/*/current
if [ -x "$PREFIX/bin/sv" ] && [ -d "$PREFIX/var/service/llama" ]; then
    . "$PREFIX/etc/profile.d/start-services.sh"
    echo "started via termux-services"
    exit 0
fi

# Legacy fallback (no termux-services installed): manual start with a real
# readiness poll instead of the old `sleep 15` race.
echo "termux-services not found — legacy start"
TOKEN=$(cat "$HOME/.aria_token" 2>/dev/null)

if ! curl -sf -m 3 http://127.0.0.1:8080/health >/dev/null; then
    cd "$HOME/llama.cpp" || exit 1
    nohup ./build/bin/llama-server \
        -m "$HOME/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf" \
        -c 4096 --host 127.0.0.1 --port 8080 --jinja \
        -t 4 --cache-reuse 256 --cache-ram 512 -np 1 \
        ${TOKEN:+--api-key "$TOKEN"} \
        >> "$HOME/.aria/logs/llama.log" 2>&1 &
fi

# /health returns 503 while the model loads, 200 when ready
n=0
until curl -sf -m 3 http://127.0.0.1:8080/health >/dev/null; do
    n=$((n+1))
    if [ "$n" -gt 90 ]; then
        echo "$(date -Is) brain never became ready"
        break
    fi
    sleep 2
done

if ! curl -s -m 3 -o /dev/null http://127.0.0.1:8100/health; then
    nohup python "$HOME/aria/edge_assistant.py" --serve \
        >> "$HOME/.aria/logs/serve.log" 2>&1 &
fi
echo "legacy start done (brain ready after ${n}x2s)"
