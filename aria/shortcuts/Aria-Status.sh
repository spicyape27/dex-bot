#!/data/data/com.termux/files/usr/bin/sh
# One-tap status: shows a notification with brain/aria state, RAM, battery,
# disk, and the last log line. Place as a Termux:Widget next to Aria-Voice.
B=$(curl -sf -m 3 http://127.0.0.1:8080/health >/dev/null && echo "brain UP" || echo "brain DOWN")
curl -s -m 3 -o /dev/null http://127.0.0.1:8100/health
[ $? -ne 7 ] && A="aria UP" || A="aria DOWN"
M=$(free -m | awk '/^Mem/{print $7" MB free"}')
BAT=$(termux-battery-status 2>/dev/null | python -c "import sys,json;d=json.load(sys.stdin);print(f\"{d['percentage']}% {d['temperature']:.0f}C {d['status'].lower()}\")" 2>/dev/null)
D=$(df -h "$PREFIX" | awk 'NR==2{print $4" disk"}')
if [ -r "$PREFIX/var/log/sv/llama/current" ]; then
    E=$(tail -1 "$PREFIX/var/log/sv/llama/current" | cut -c1-60)
else
    E=$(tail -1 "$HOME/.aria/logs/aria.log" 2>/dev/null | cut -c1-60)
fi
V=$(python "$HOME/aria/edge_assistant.py" --version 2>/dev/null)
termux-notification -t "Aria: $B / $A" -c "$V
$M | $BAT | $D
last: $E"
