# Aria — sovereign offline voice assistant (Termux / Android)

Fully offline voice assistant on a no-SIM Motorola Edge 2024: local LLM
(llama.cpp), local STT (whisper.cpp), device control via Termux:API,
zero cloud. Works in airplane mode.

- **`edge_assistant.py`** — the entire assistant (single file by design).
  Modes: `--voice`, `--serve`, `--ask "…"`, `--selftest`, `--version`.
- **`install.sh`** — idempotent installer/updater. `git pull && sh install.sh`.
- **`RUNBOOK.md`** — phased on-device steps (survival hardening → speed →
  model bake-off → voice UX → privacy) + troubleshooting table.
- **`LEDGER.md`** — project source of truth: architecture, decisions, rebuild-from-zero.
- **`services/`, `boot/`, `shortcuts/`, `bin/`** — runit supervision, boot
  script, home-screen widgets, watchdog (installed by install.sh).
- **`tests/`** — pure-logic pytest suite (`python -m pytest tests -q`, runs anywhere).
- **`bench/toolcall_bench.py`** — tool-calling bake-off for candidate models.

Quick start on the phone:

```sh
git clone <this-repo> ~/aria
cd ~/aria && sh install.sh      # ends with a full selftest
```

Then do **RUNBOOK.md Phase 1** (phantom-process-killer fix) — it's the
difference between "works in demos" and "survives a week unattended".
