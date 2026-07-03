# Claude Token Viewer for Steam Deck

A visual dashboard for watching your Claude Code token usage on a Steam Deck —
today's estimated cost as a hero number, a daily cost chart (7/14/30 days), a
per-model breakdown, and a full daily token table. Dark theme sized for the
Deck's 1280×800 screen, works with touch, trackpads, or the D-pad.

It's a **single Python file with zero dependencies** — SteamOS already ships
Python 3, so nothing needs to be installed.

## How it works

Claude Code logs every API turn (with token usage per model) to JSONL
transcript files under `~/.claude/projects/`. `token-viewer.py` scans those
files, de-duplicates and aggregates them, estimates cost from per-model list
prices (input / output / cache-write at 1.25× / cache-read at 0.1×), and
serves the dashboard on `http://localhost:8484`. It re-scans on every refresh
(only re-reading files that changed), and the page auto-refreshes every 60
seconds — so you can leave it open and literally watch usage tick up while
Claude works.

> If you're on a Pro/Max subscription the dollar figures are the
> *API-equivalent* value of your usage, not a bill — still the best single
> number for "how hard am I driving it today".

## Setup on the Deck

1. Switch to **Desktop Mode** (Power button → Switch to Desktop).
2. Get this folder onto the Deck, e.g. in Konsole:

   ```bash
   git clone https://github.com/spicyape27/dex-bot.git ~/dex-bot
   cd ~/dex-bot && git checkout claude/steam-deck-token-viewer-oam8z9
   chmod +x ~/dex-bot/steamdeck/launch-token-viewer.sh
   ```

3. Test it: `~/dex-bot/steamdeck/launch-token-viewer.sh` — a browser should
   open showing the dashboard. (Or run `python3 steamdeck/token-viewer.py`
   and browse to <http://localhost:8484> yourself.)

### Add it to Gaming Mode

1. Still in Desktop Mode, open **Steam → Games → Add a Non-Steam Game to My
   Library → Browse**, set the file filter to *All Files*, and pick
   `~/dex-bot/steamdeck/launch-token-viewer.sh`.
2. Rename the shortcut to "Claude Token Viewer" if you like, then switch back
   to Gaming Mode — it's now in your library like any game.
3. First launch in Gaming Mode: open the shortcut's controller settings and
   pick the **Web Browser** template so the trackpad is a mouse and the D-pad
   sends arrow keys.

Controls: **R** (or the on-screen button) refreshes immediately, **←/→**
(D-pad) switches the chart between 7/14/30 days, and tapping a bar shows the
full token breakdown for that day.

### Desktop shortcut (optional)

Copy `claude-token-viewer.desktop` to `~/Desktop/` (or
`~/.local/share/applications/`). Edit the `Exec=` line if you cloned the repo
somewhere other than `/home/deck/dex-bot`.

## Watching usage from another machine

If Claude Code runs on your PC rather than the Deck itself, run the server on
the PC and open it from the Deck's browser:

```bash
python3 token-viewer.py --host 0.0.0.0 --port 8484
# on the Deck, browse to http://<your-pc-ip>:8484
```

## Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--port` | `8484` | Port to serve on (`TOKEN_VIEWER_PORT` works for the launcher) |
| `--host` | `127.0.0.1` | Bind address; use `0.0.0.0` to allow other devices |
| `--claude-dir` | `~/.claude`, `~/.config/claude` | Where to look for `projects/*.jsonl` (repeatable) |

Models without a pricing entry still have their tokens counted; they're
marked with `*` in the model chart and excluded from cost totals.
