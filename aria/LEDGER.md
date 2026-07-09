# PROJECT LEDGER — Aria (Sovereign Phone Assistant)

> Single source of truth. With this repo you can resume the project or rebuild it from scratch.

- **Version:** v2 · **Last updated:** 2026-07-09
- **Goal (one line):** WiFi-only, no-SIM Motorola Edge 2024 running a fully offline voice assistant ("Aria") — local LLM brain, local ears, device control, zero cloud.
- **Status:** v7 delivered in-repo (supersedes v6); on-device install + Phase 1 hardening pending — see RUNBOOK.md
- **Owner:** ByJulius

---

## 1. QUICK RESUME
- **The code now lives in this git repo** — `edge_assistant.py` (v7) plus every boot/service/shortcut script. The chat-file-card era is over.
- **Update flow:** `cd ~/aria && git pull && sh install.sh` (idempotent; ends with `--selftest`).
- **Version check:** `python ~/aria/edge_assistant.py --version` (prints version + self-hash) and `git log -1`.
- **Rollback:** `git checkout <tag> -- edge_assistant.py && sv restart aria`.
- **Exact next step:** clone this repo to the phone, run `sh install.sh`, then RUNBOOK Phase 1 (phantom-process-killer fix — CRITICAL).
- **Status view:** tap the Aria-Status widget, or `sv status llama aria`.
- **Logs:** `$PREFIX/var/log/sv/{llama,aria}/current` (services), `~/.aria/logs/` (assistant, boot, watchdog).

## 2. REBUILD FROM ZERO
On a factory-reset Motorola Edge 2024 (8GB):

1. **Phone prep:** No SIM. Android setup on WiFi only. No phone number on any account.
2. **F-Droid:** Chrome → f-droid.org → APK → install. From F-Droid (ONLY F-Droid — GitHub builds have incompatible signatures): Termux, Termux:API, Termux:Boot, Termux:Widget. Open Termux:Boot once.
3. **Android settings:** Termux + Termux:Boot: battery → "Allow background usage" ON, "Manage app if unused" OFF. Termux:API → Microphone permission. Then RUNBOOK Phase 1a (phantom process killer) — do it now, not later.
4. **Termux base:**
   ```
   pkg update && pkg upgrade -y
   pkg install -y git cmake clang python termux-api termux-services ffmpeg wget curl
   pip install httpx
   termux-setup-storage
   termux-wake-lock
   ```
   (No fastapi/uvicorn — pydantic-core needs Rust and won't build. Not needed.)
5. **Build the brain:**
   ```
   cd ~ && git clone https://github.com/ggml-org/llama.cpp
   cd llama.cpp && git checkout <PINNED_COMMIT — see §4>
   cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CPU_KLEIDIAI=ON
   cmake --build build --config Release -j 4        # -j 4 or OOM
   ```
6. **Model (~2GB, WiFi; prefer Q4_0 — ARM fast path):**
   ```
   mkdir -p ~/models
   wget -c -O ~/models/<MODEL>.gguf "<HF URL — see §4>"
   sha256sum ~/models/<MODEL>.gguf    # MUST match models.sha256 / HF file page
   ```
7. **Build the ears:**
   ```
   cd ~ && git clone https://github.com/ggml-org/whisper.cpp
   cd whisper.cpp && git checkout <PINNED_COMMIT — see §4>
   cmake -B build && cmake --build build --config Release -j 4
   sh ./models/download-ggml-model.sh tiny.en
   sh ./models/download-ggml-model.sh base.en
   ```
8. **Install Aria:**
   ```
   git clone <PRIVATE_REMOTE_URL> ~/aria
   cd ~/aria && sh install.sh
   ```
9. **Verify:** `python ~/aria/edge_assistant.py --selftest` all-PASS → reboot phone → wait 2 min → Aria-Status widget shows brain UP / aria UP → tap Aria-Voice → "Aria" → "Yes?" → "what's my battery at?" → spoken real percentage.

## 3. ARCHITECTURE
- **Stack:** Android (stock, no root) → Termux → llama.cpp `llama-server` (OpenAI-compatible, :8080, `--jinja --api-key`) + whisper.cpp (STT) + Termux:API (device bridge) → `edge_assistant.py` v7 (single file: config, logging, direct routes, tool loop, SQLite memory, voice loop, token-protected HTTP :8100) — all supervised by termux-services (runit) with a job-scheduler watchdog.

```
                     boot (Termux:Boot)
                          │ wake-lock + start-services
        ┌─────────────────┴─────────────────┐
   runit: llama (:8080)              runit: aria --serve (:8100)
   llama-server --jinja --api-key    token-auth POST /ask, GET /health
        ▲          ▲                        ▲
        │          │                        │  X-Aria-Token
        │   widget tap: --voice             │
        │   ┌──────────────────────┐   any local caller
        │   │ mic → wake("aria")   │
        │   │  → capture utterance │   watchdog (Android job-scheduler,
        │   │  → whisper STT       │   15 min): /health → sv restart,
        │   │  → clean/filter      │   tmp cleanup
        │   │  → DIRECT_ROUTES ────┼─► deterministic tools (battery, torch…)
        └───┼─ else LLM tool loop  │
            │  → sentences stream  │
            │  → TTS speaks each   │
            │  → follow-up window  │
            └──────────────────────┘
   SQLite ~/.aria/aria.db: turns log + user facts (injected into prompt)
```

- **File tree (phone):**
  ```
  ~/aria/                    # THIS REPO = deployment
  ~/.aria.conf               # live config (untracked; from aria.conf.example)
  ~/.aria_token              # shared secret (0600, auto-generated)
  ~/.aria/{aria.db,logs/}    # memory + logs
  ~/.assistant_tmp/          # transient clips (auto-cleaned)
  ~/models/*.gguf            # LLM weights (checksummed in models.sha256)
  ~/llama.cpp/build/bin/llama-server
  ~/whisper.cpp/build/bin/whisper-cli + models/ggml-*.bin
  $PREFIX/var/service/{llama,aria}/   # runit services (from services/)
  ~/.termux/boot/start-aria.sh, ~/.shortcuts/Aria-*.sh, ~/bin/aria-watchdog.sh
  ```

## 4. DEPENDENCIES (pin on device, then fill in)
- LLM GGUF: Llama-3.2-3B-Instruct **Q4_0** (bartowski) — sha256: `models.sha256`. Bake-off candidates: Qwen3-4B-Instruct-2507, LFM2-2.6B (RUNBOOK Phase 3).
- whisper models: tiny.en (wake), base.en (questions) — sha256: `models.sha256`
- llama.cpp commit: `<FILL: git -C ~/llama.cpp rev-parse HEAD>`
- whisper.cpp commit: `<FILL: git -C ~/whisper.cpp rev-parse HEAD>`
- pkg: git cmake clang python termux-api termux-services ffmpeg wget curl
- pip: httpx `<FILL: pip show httpx>`; dev-only: pytest
- Apps (F-Droid ONLY): Termux, Termux:API, Termux:Boot, Termux:Widget — auto-update ON

## 5. SECRETS
| Name | Purpose | Where | Regenerate |
|------|---------|-------|------------|
| aria token | auth for :8100 /ask + llama --api-key | `~/.aria_token` (0600, Termux-private) | delete file; install.sh or first run recreates |

No cloud keys, no accounts. The token never leaves the device.

## 6. OUT-OF-REPO / INFRASTRUCTURE STATE
- **Services:** runit-supervised `llama` (:8080) and `aria` (:8100), loopback only, auto-restart; watchdog via termux-job-scheduler every 15 min.
- **Android state:** Termux/Termux:Boot battery exemptions; Termux:API mic permission; storage bridge; **PPK mitigation applied: `<FILL: yes/no + method>`**; Developer Options wireless debugging (only while applying 1a).
- **Measured:** idle drain `<FILL %/hr>`; llama-bench `<FILL tok/s pre/post KleidiAI>`; whisper-bench `<FILL>`; soak test `<FILL date + result>`; pulse backend works on this firmware: `<FILL yes/no>`.
- **Privacy tier applied:** `<FILL: none / T1 / T1+T2>` (RUNBOOK Phase 5).

## 7. DECISION LOG
| Date | Decision | Reason | Rejected |
|------|----------|--------|----------|
| 2026-07-09 | No root / no custom ROM (Phase 5 deferred) | stock Android suffices for now | LineageOS now |
| 2026-07-09 | llama.cpp in Termux | ownership + OpenAI API | app runners, Ollama-in-proot |
| 2026-07-09 | 3B-class Q4 model | 8GB RAM (~4.5 usable) | 1B (weak), 7-8B (RAM/speed) |
| 2026-07-09 | Direct routes for essentials | 3B tool-picking is flaky | pure model tool-calling |
| 2026-07-09 | Voice on-demand (widget) | always-on = battery drain | voice at boot |
| 2026-07-09 | **Git repo = code home + update channel** | v6 lived only in chat cards; Downloads-copy already caused a stale-file incident | hand-copy from Downloads |
| 2026-07-09 | **termux-services supervision + job-scheduler watchdog** | fire-and-forget `&` left crashes dead until manual reboot | bare boot script |
| 2026-07-09 | **Token auth on :8100 and llama `--api-key`** | any installed app can reach localhost (localmess-class abuse is real) | unauthenticated loopback |
| 2026-07-09 | **Q4_0 quant + KleidiAI build target** | ARM runtime-repack fast path is Q4_0-only; Adreno 710 GPU offload is a verified dead end | Q4_K_M, OpenCL/Vulkan |
| 2026-07-09 | **Sentence-streaming TTS** | time-to-first-audio ~15s → ~2-3s at 4 tok/s | speak-after-full-generation |
| 2026-07-09 | **SQLite memory (stdlib)** | facts + history make it an assistant, not a toy; zero new deps | embeddings RAG first |
| 2026-07-09 | ≤8 LLM tools, everything also direct-routed | >8 tools degrades 3B selection | unbounded tool growth |
| 2026-07-09 | Never `termux-speech-to-text` | it's Google's cloud recognizer | — |
| 2026-07-09 | Pulse backend optional, termux chunks default | module-sles-source unverified on Moto firmware | forcing gapless everywhere |

## 8. CHANGE LOG (newest first)
### 2026-07-09 — v7: full rewrite implementing the 5-lens deep-dive
- **Did:** moved project into git (this repo). Rewrote assistant from the v6 spec with: `~/.aria.conf` config, rotating logs, `--version` (self-hash) + `--selftest` + `--ask`, token auth on :8100, declarative DIRECT_ROUTES (+torch/volume/brightness/wifi/clipboard/remember), 8 LLM tools, SQLite memory (turns + facts injected into prompt), whisper hallucination filter, one-breath wake, follow-up window, sentence-streaming TTS via SSE, optional gapless pulse audio backend with RMS VAD, tmp-clip hygiene. Added runit services with readiness poll (replaces `sleep 15`), job-scheduler watchdog, status widget, idempotent installer, pytest suite, tool-call bake-off benchmark, model checksum manifest, RUNBOOK.
- **Note:** v7 is a fresh implementation — v6 itself was unrecoverable from chat. If a v6 copy surfaces, archive it in-repo.
- **Next:** on-device install + RUNBOOK Phase 1 (PPK), then Phase 2 (KleidiAI rebuild, Q4_0, pulse spike).

### 2026-07-09 — Ledger v1 adopted (pre-repo era)
- Phases 0–4 complete; reboot test PASSED; v6 delivered via chat file cards (install unverified); known issues: mic-gap seams, whisper wake-word cost, no supervision, unpinned deps.

## 9. ARCHIVED LOG
- 2026-07-09 — Phase 1: Termux env, llama.cpp built (OOM → `-j 4`), model via wget (hf CLI fails on Termux), ~4 tok/s.
- 2026-07-09 — Phase 2: v1-v3; fastapi bypassed (httpx only); `--jinja` + direct routes fixed tool flakiness.
- 2026-07-09 — Phase 3: whisper.cpp built; wake-word variants; first voice round-trip.
- 2026-07-09 — Phase 4: boot script + shortcuts; Moto battery settings mapped; reboot test PASSED.
- 2026-07-09 — v5: vibration cues, one-breath wake. v6: rolling-chunk listening (chat-card only; superseded by v7).

## 10. KNOWN ISSUES / TODO
- [ ] On-device: clone repo, `sh install.sh`, all selftests PASS
- [ ] RUNBOOK Phase 1: PPK mitigation + 24-48h soak test → record in §6
- [ ] RUNBOOK Phase 2: KleidiAI rebuild, Q4_0 model, benchmark, pin commits → §4/§6
- [ ] RUNBOOK Phase 2d: pulse backend go/no-go on Moto firmware → §6
- [ ] RUNBOOK Phase 3: model bake-off (Qwen3-4B vs LFM2-2.6B) → §7
- [ ] RUNBOOK Phase 4: TTS engine APK; openWakeWord (train "Aria" model on Mac)
- [ ] RUNBOOK Phase 5: privacy tier 1 + NetGuard; LineageOS (`avatrn` supported) later
- [ ] Push this repo to a private remote and record the URL in §2 step 8
- [ ] Measure idle battery drain (post-build honest number) → §6
- [ ] Mac Mini offload (opportunistic LAN fast lane) — design in deep-dive report, not started
- [ ] Barge-in (needs killable TTS player — Piper+paplay path, after pulse backend lands)
