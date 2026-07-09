#!/data/data/com.termux/files/usr/bin/sh
# Watchdog fired by termux-job-scheduler (Android schedules it, so it runs
# even if everything inside Termux was killed). Registered by install.sh.
LOG="$HOME/.aria/logs/watchdog.log"
mkdir -p "$HOME/.aria/logs"

if ! curl -sf -m 5 http://127.0.0.1:8080/health >/dev/null; then
    echo "$(date -Is) llama DOWN — restarting" >> "$LOG"
    termux-wake-lock
    if [ -x "$PREFIX/bin/sv" ]; then
        . "$PREFIX/etc/profile.d/start-services.sh"   # revives runsvdir if dead
        sv restart llama aria >> "$LOG" 2>&1
    else
        sh "$HOME/.termux/boot/start-aria.sh"
    fi
    termux-notification -t "Aria" -c "Brain was down — restarted" 2>/dev/null
fi

# housekeeping: transient audio clips never accumulate
find "$HOME/.assistant_tmp" -type f -mmin +120 -delete 2>/dev/null
