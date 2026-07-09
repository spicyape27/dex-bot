# Aria Runbook — on-device steps, phased

Everything the repo can't do for you. Work top to bottom; each phase is
independent, but Phase 1 is not optional. Full analysis behind every step is
in the deep-dive report (chat, 2026-07-09).

---

## Phase 0 — First install from this repo (10 min)

```sh
# on the phone, in Termux:
git clone <YOUR-PRIVATE-REMOTE-URL> ~/aria     # or: cd ~/aria && git pull
cd ~/aria && sh install.sh
```

`install.sh` is idempotent — rerun it after every `git pull`. It installs
supervised services, the boot script, widget shortcuts, the watchdog, token,
config, and runs `--selftest` at the end. All checks should PASS.

If you still have the old v6 file: `python ~/edge_assistant.py` is now retired;
the boot script and shortcuts point at `~/aria/edge_assistant.py`. Delete
`~/edge_assistant.py` and any copy in `~/storage/downloads/` once v7 passes
selftest. If you can still retrieve v6 from the chat file cards, commit it
first for history: `git add -f archive/edge_assistant_v6.py`.

**Update flow forever after:** `cd ~/aria && git pull && sh install.sh`.
Rollback: `git checkout <tag> -- edge_assistant.py && sv restart aria`.

---

## Phase 1 — Make it survive (30 min, CRITICAL)

### 1a. Disable the phantom process killer
Android ≥12 silently kills Termux child processes (llama-server is a prime
target: background + CPU-heavy). Current stability is luck from short sessions.

Try first (no computer needed): **Settings → Developer Options → "Disable
child process restrictions"** → ON → reboot. (Enable Developer Options by
tapping Build Number 7×.)

If Motorola's skin doesn't expose the toggle, do it via wireless ADB from the
phone itself:

```sh
pkg install android-tools
# Settings → Developer options → Wireless debugging → Pair device with pairing code
adb pair localhost:<pair-port>       # enter the code
adb connect localhost:<port>
adb shell "/system/bin/device_config set_sync_disabled_for_tests persistent"
adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
adb shell settings put global settings_enable_monitor_phantom_procs false
```

The `set_sync_disabled_for_tests persistent` line stops Google's server-side
flag sync from silently reverting the change.

### 1b. Verify supervision took over
```sh
sv status llama aria          # both "run"
sv restart llama              # watch it come back
tail $PREFIX/var/log/sv/llama/current
```

### 1c. Soak test
Leave the phone untouched 24–48 h, then check `sv status llama aria` and
`~/.aria/logs/watchdog.log` for restart entries. Zero silent deaths = pass.
Record the result in LEDGER.md §6.

### 1d. Battery & device longevity
- Park near a charger; **Settings → Battery → Overcharge Protection** ON
  (Moto holds 80% when plugged 3+ days — built for exactly this).
- Measure real idle drain for one day (Aria-Status widget shows %); record in
  LEDGER.md. The 55%-day-one number included compile marathons.

### 1e. Home screen
Long-press home → Widgets → Termux:Widget → place **Aria-Voice** and
**Aria-Status**.

---

## Phase 2 — Make it fast (an evening)

### 2a. Rebuild llama.cpp with ARM-optimized kernels
```sh
cd ~/llama.cpp
git rev-parse HEAD                       # record OLD commit in LEDGER first
git pull
cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CPU_KLEIDIAI=ON
cmake --build build --config Release -j 4    # -j 4 or the OOM killer strikes
git rev-parse HEAD                       # record NEW pinned commit in LEDGER
```

### 2b. Switch to a Q4_0 model file
The ARM runtime-repack fast path applies to **Q4_0**, not Q4_K_M:
```sh
wget -c -O ~/models/Llama-3.2-3B-Instruct-Q4_0.gguf \
  "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_0.gguf"
sha256sum ~/models/Llama-3.2-3B-Instruct-Q4_0.gguf   # compare vs HF file page!
```
Point `services/llama/run` at it (edit in the repo, commit, `sh install.sh`).

### 2c. Benchmark before/after
```sh
./build/bin/llama-bench -m ~/models/<model>.gguf -t 4 -p 512 -n 64
./build/bin/whisper-bench -m ~/whisper.cpp/models/ggml-tiny.en.bin -t 4
```
Record tok/s in LEDGER.md. Then A/B the commented flags in
`services/llama/run` (`-fa on -ctk q8_0 -ctv q8_0`, `-c 2048`) — flash
attention is not always a win on this class of hardware; keep what measures
faster.

### 2d. The gapless-audio spike (go/no-go for the voice roadmap)
```sh
pkg install pulseaudio
pulseaudio --start --exit-idle-time=-1
pactl load-module module-sles-source
parecord --format=s16le --rate=16000 --channels=1 --raw | head -c 320000 > /tmp/t.raw
ffmpeg -f s16le -ar 16000 -ac 1 -i /tmp/t.raw /tmp/t.wav && mpv /tmp/t.wav  # or termux-media-player
```
Speak while it records. If playback contains your voice → set
`backend = pulse` in `~/.aria.conf`: mic-gap seams disappear (RMS-VAD
endpointing is already implemented). If it records silence, stock Moto
firmware doesn't expose OpenSL ES capture — stay on `termux` backend and note
it in LEDGER.md (fallback: chunked mode still works as before).

### 2e. Optional STT quality bump
```sh
sh ~/whisper.cpp/models/download-ggml-model.sh base.en-q5_1
sh ~/whisper.cpp/models/download-vad-model.sh silero-v5.1.2 2>/dev/null || true
```
Set `whisper_model_long` (and `whisper_vad_model` if downloaded) in
`~/.aria.conf`. tiny.en stays the wake-phase model; base.en transcribes the
actual question.

---

## Phase 3 — Better brain (a weekend)

Run the bake-off against each candidate (restart llama with each model):

```sh
# Qwen3-4B-Instruct-2507 — best sub-7B tool caller (~2.4GB)
wget -c -O ~/models/Qwen3-4B-Instruct-2507-Q4_0.gguf \
  "https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen_Qwen3-4B-Instruct-2507-Q4_0.gguf"
# LFM2-2.6B — fastest CPU decode (~1.6GB); keep -np 1 (known slot bug)
wget -c -O ~/models/LFM2-2.6B-Q4_0.gguf \
  "https://huggingface.co/LiquidAI/LFM2-2.6B-GGUF/resolve/main/LFM2-2.6B-Q4_0.gguf"

sha256sum ~/models/*.gguf                      # verify vs HF, update models.sha256
python ~/aria/bench/toolcall_bench.py          # tool-call success rate
./build/bin/llama-bench -m <model> -t 4 -p 512 -n 64   # speed
```

Winner goes into `services/llama/run` (commit + `sh install.sh`). Record
scores + decision in LEDGER.md §7. Keep the loser files only if disk allows
(`df -h $PREFIX`; below ~2GB free, delete).

---

## Phase 4 — Voice UX upgrades (spread over evenings)

1. **Neural TTS with zero code changes:** install a sherpa-onnx TTS engine APK
   (k2-fsa publishes them; VoxSherpa bundles Kokoro-82M/Piper voices — same
   af_heart voice family as the Mac). Set it as the system TTS engine in
   Android settings; `termux-tts-speak` upgrades instantly. Sideloaded APK —
   vet the source before installing.
2. **Wake word done right (kills the battery burn + 4-6s wake latency):**
   openWakeWord runs in Termux via onnxruntime from the TUR repo:
   ```sh
   pip install --extra-index-url https://termux-user-repository.github.io/pypi/ onnxruntime
   pip install openwakeword
   ```
   Train a custom "Aria" model with openWakeWord's synthetic-training notebook
   on the Mac Mini (~1 hr), copy the .onnx over. Avoid Porcupine — it phones
   home to validate its license key. (Wiring it into the wake phase replaces
   the whisper-transcribe-4s-clips detector; the voice loop's capture/wake
   split makes this a contained change.)
3. **Never** use `termux-speech-to-text` — it's Google's cloud recognizer and
   violates the zero-cloud rule. (Noted so future-you doesn't "simplify".)

---

## Phase 5 — Privacy hardening (30 min + an afternoon)

Tier 1 (free, reversible, do now):
- Settings → Network → Private DNS → `dns.quad9.net` (or Mullvad).
- Google settings → disable Usage & diagnostics; Privacy → Ads → **Delete
  advertising ID**.
- Moto app → disable analytics/feedback. Disable the Google Assistant & Google
  app (a second, cloud-based always-on mic pipeline competing with Aria).

Tier 2 (an afternoon): **NetGuard** from F-Droid, default-deny, allow only
what you choose. Verified: loopback doesn't traverse the VPN — Aria keeps
working. Block Termux by default; temporarily allow it for `pkg upgrade` /
model downloads. This *enforces* "Aria never phones home."

Tier 3 (Phase-5-of-ledger, when ready): LineageOS officially supports this
phone (`avatrn` on the LineageOS wiki) — install **without GApps** for the
real de-Google. GrapheneOS is Pixel-only; not an option here. Note: bootloader
unlock is permanent on most Motos and weakens verified boot — a real tradeoff
to record in the decision log when the time comes.

Update policy: all four Termux APKs from **F-Droid only** (GitHub builds have
incompatible signatures — installs hard-fail); enable F-Droid auto-update for
them; `pkg update && pkg upgrade` monthly while NetGuard-allowed;
llama.cpp/whisper.cpp stay frozen at the pinned commits, re-pinned only
deliberately with a LEDGER entry.

---

## Troubleshooting (symptom → cause → fix)

| Symptom | Likely cause | Fix |
|---|---|---|
| Tools never fire / model ignores tools | `--jinja` missing from llama-server | it's in `services/llama/run`; `sv restart llama`; `--selftest` catches this |
| `[Process completed (signal 9)]`, servers dead after hours | phantom process killer | Phase 1a; check `~/.aria/logs/watchdog.log` for restarts |
| Build dies silently mid-compile | OOM (full-core build) | always `-j 4` |
| Old code running after update | stale copy | `python ~/aria/edge_assistant.py --version` vs `git log -1`; update = `git pull && sh install.sh` only |
| Boot didn't start servers | Termux:Boot never opened once, or battery settings | open Termux:Boot app once; battery → background usage ON; read `~/.aria/logs/boot.log` |
| Mic records nothing | Termux:API lacks Microphone permission | Android Settings → Apps → Termux:API → Permissions |
| "The brain isn't answering" | llama-server down or still loading (503) | `sv status llama`; `curl 127.0.0.1:8080/health`; watchdog restarts within 15 min |
| Voice loop answers gibberish to silence | hallucination filter miss | add the phrase to `HALLUCINATIONS` in edge_assistant.py, commit |
| Disk full / downloads fail | model files + build objects | `df -h $PREFIX`; `find ~/llama.cpp/build -name '*.o' -delete`; delete losing bake-off models |
| :8100 returns 401 | missing/wrong token header | send `X-Aria-Token: $(cat ~/.aria_token)` |
