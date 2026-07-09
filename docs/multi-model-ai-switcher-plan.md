# Multi-Model AI Switcher for macOS + Aria Upgrade Plan

**Goal:** One Mac setup where you can (1) use your Claude, ChatGPT, and Grok
subscriptions to their fullest, (2) switch between the three providers *and*
between each provider's sub-models instantly while coding, running agents, and
building, and (3) grow your local voice agent **Aria** into the layer that
navigates windows and models for you.

---

## 1. The key insight: subscriptions vs. API keys

Your three subscriptions each unlock a **first-party terminal coding agent**
that bills against the subscription, not per-token:

| Provider | Subscription | Coding agent (CLI) | Sub-model switching |
|---|---|---|---|
| Anthropic | Claude Pro / Max | **Claude Code** | `/model` in-session, `claude --model`, per-project `settings.json` |
| OpenAI | ChatGPT Plus / Pro | **Codex CLI** (sign in with ChatGPT account) | `/model` in-session, `codex --model`, `~/.codex/config.toml` |
| xAI | SuperGrok / X Premium+ | **Grok Build** (beta, May 2026) | `/model` in-session, CLI flag/config |

This means the core "use all three subscriptions to the fullest" system is
**not** a custom app — it is three official CLIs installed side by side, plus a
thin switching layer (shell + hotkeys + Aria) on top. API keys are only needed
for the programmatic/agent layer (section 4) and for Aria's own brain.

**Two planes to build:**

- **Plane A — Interactive coding (subscription-billed):** Claude Code, Codex
  CLI, Grok Build in the terminal/IDE. This is where you burn subscription
  quota, not API dollars.
- **Plane B — Programmatic/agents (API-billed):** a local model router
  (LiteLLM) exposing one OpenAI-compatible endpoint that fronts all three
  providers' APIs, used by your own scripts, agents, and Aria.

---

## 2. Phase 1 — Install and normalize the three coding agents (Day 1)

### 2.1 Install

```bash
# Claude Code
npm install -g @anthropic-ai/claude-code   # or: brew install --cask claude-code
claude   # first run: sign in with your Claude subscription account

# Codex CLI
npm install -g @openai/codex               # or: brew install codex
codex    # first run: choose "Sign in with ChatGPT"

# Grok Build
curl -fsSL https://x.ai/cli/install.sh | bash
grok     # first run: sign in with your SuperGrok / X Premium+ account
```

Verify each is on subscription auth (not an API key) so usage draws from the
plan you already pay for.

### 2.2 Sub-model switching in each CLI

- **Claude Code:** `/model` mid-session to pick (e.g. Opus for hard design
  work, Sonnet for routine edits, Haiku for cheap bulk tasks). Set a
  per-project default in `.claude/settings.json` (`"model": "..."`), or launch
  with `claude --model <id>`.
- **Codex CLI:** `/model` mid-session; set `model = "..."` and
  `model_reasoning_effort` in `~/.codex/config.toml`; per-invocation
  `codex --model <id>`. Use high-reasoning models for planning, faster/lighter
  ones for mechanical edits.
- **Grok Build:** `/model` mid-session and config-file default; use Plan Mode +
  subagents for large parallel tasks (its differentiator).

### 2.3 One set of project instructions for all three

Keep a single source of truth per repo:

- Write **`AGENTS.md`** (Codex's native file) and symlink or mirror it to
  **`CLAUDE.md`**. Grok Build reads `CLAUDE.md` natively, so all three agents
  share the same project brief with zero duplication:

```bash
# in each repo
ln -s AGENTS.md CLAUDE.md   # Codex reads AGENTS.md; Claude Code & Grok Build read CLAUDE.md
```

- Result: swap agents mid-project and every one of them knows the same build
  commands, conventions, and constraints.

### 2.4 MCP servers shared across agents

All three CLIs support MCP. Define your MCP servers once (filesystem, GitHub,
browser, project-specific tools) and register the same set in each CLI's
config so tools/context don't change when you swap models.

---

## 3. Phase 2 — The switching layer (Week 1)

Fast, muscle-memory switching in three places: shell, hotkeys, and IDE.

### 3.1 Shell: one `ai` command

A small zsh function/dispatcher so switching is one word, with sub-model as an
optional second argument:

```bash
# ~/.zshrc (sketch)
ai() {
  local agent="$1"; shift
  case "$agent" in
    c|claude)  claude ${1:+--model "$1"} ;;          # ai c opus
    g|gpt)     codex  ${1:+--model "$1"} ;;          # ai g high
    x|grok)    grok   ${1:+--model "$1"} ;;          # ai x fast
    *)         echo "usage: ai {claude|gpt|grok} [model]" ;;
  esac
}
```

Add per-provider aliases for your favorite sub-model presets
(`alias planning='claude --model opus'`, `alias grind='codex --model <fast>'`).

Because all three read the same `CLAUDE.md`/`AGENTS.md` and the session state
lives in git (branches, worktrees), "swapping while building" is: exit or
background one agent, launch another in the same directory, and it picks up
the same project context. Use **git worktrees** when you want two agents
working the same repo simultaneously without stomping each other.

### 3.2 Hotkeys and launcher: Raycast (or Hammerspoon)

- **Raycast script commands**: "Claude Code here", "Codex here", "Grok here" —
  each opens a terminal tab in the frontmost Finder/IDE project directory with
  the chosen agent + sub-model. Bind to hotkeys (e.g. ⌥⌘1/2/3).
- **Hammerspoon** (you'll want it for Aria anyway, section 5): window layout
  presets — e.g. one hotkey arranges iTerm (agent) + browser + editor; another
  cycles which agent pane is focused.
- **tmux layout** (optional power move): one session with three panes, one
  agent per pane, hotkeys to focus each. All three subscriptions literally on
  screen at once; give the same task to two agents and keep the better diff.

### 3.3 IDE

Install the Claude Code and Codex IDE extensions (VS Code / JetBrains) signed
into the same subscription accounts. Same model pickers, same quota. Keep the
terminal as the common denominator since Grok Build is terminal-first.

### 3.4 Getting the most from each subscription (routing doctrine)

Write this down and let it drive habit (and later, Aria's routing hints):

- **Architecture, thorny debugging, long-context refactors** → Claude Code on
  the top Claude model; drop to a mid-tier model for routine edits to stretch
  Max quota.
- **Quick scripts, mechanical transforms, second opinions on diffs** → Codex
  CLI; adjust reasoning effort per task.
- **Parallel/batch work and plan-review-approve flows** → Grok Build subagents;
  also useful as the "third vote" when Claude and GPT disagree.
- **Quota rotation:** when one plan's agentic limit is hit mid-day, swap to the
  next provider with the same `CLAUDE.md`/`AGENTS.md` context instead of
  stopping work. Three subscriptions ≈ three tanks of fuel for one pipeline.

---

## 4. Phase 3 — Unified API router for agents & Aria (Week 2)

Interactive CLIs cover coding. For **your own agents and Aria**, run a local
**LiteLLM proxy** that exposes a single OpenAI-compatible endpoint and fans
out to Anthropic, OpenAI, and xAI APIs (these are API-key billed — separate
from subscriptions, so keep budgets on them):

```yaml
# ~/ai-router/litellm.yaml (sketch)
model_list:
  - model_name: best        # alias Aria/agents use
    litellm_params: { model: anthropic/<top-claude-model>, api_key: os.environ/ANTHROPIC_API_KEY }
  - model_name: fast
    litellm_params: { model: openai/<fast-gpt-model>, api_key: os.environ/OPENAI_API_KEY }
  - model_name: realtime-x
    litellm_params: { model: xai/<grok-model>, api_key: os.environ/XAI_API_KEY }
router_settings:
  fallbacks: [{ best: [fast] }]   # auto-failover on rate limits/outages
```

Run it as a `launchd` service on `localhost:4000`. Benefits:

- **One endpoint, every model** — Aria and any script switch models by
  changing a string, not an SDK.
- **Aliases as policy** — remap `best`/`fast`/`cheap` to new model IDs in one
  file whenever providers ship new sub-models.
- **Fallbacks + spend tracking** built in.

(Alternative: OpenRouter if you'd rather not self-host; local LiteLLM keeps
keys and logs on your Mac.)

---

## 5. Phase 4 — Aria v2: voice-driven window & model navigation (Weeks 3–6)

Aria today: wake-word activation + a few multi-step macOS actions. Target: a
resident agent that hears "Aria…", routes the request to the right model via
the LiteLLM proxy, and drives macOS windows/apps — including launching and
switching your coding agents.

### 5.1 Architecture

```
 mic ──► wake word ──► STT ──► intent router ──► ┌ action executor (macOS)
        (Porcupine /  (whisper.cpp,              │  AppleScript/JXA, Hammerspoon,
         openWakeWord) local, fast)              │  Shortcuts, Accessibility API
                                                 └ LLM calls (LiteLLM :4000)
                                                       │
                                                 TTS response (say / Piper)
```

- **Wake word:** keep/upgrade with **openWakeWord** (free, trainable "Aria"
  model) or **Picovoice Porcupine** (custom keyword, very low false-positive).
  Runs 24/7 locally, near-zero CPU.
- **STT:** **whisper.cpp** with Metal acceleration — fully local, fast on
  Apple Silicon. Stream after wake word, endpoint on silence.
- **Intent router (two tiers):**
  - *Tier 1 (local, instant):* pattern/embedding match for known commands —
    "switch to Claude", "focus the terminal", "use the fast model", window
    layouts. No network round trip.
  - *Tier 2 (LLM):* anything else goes to the LiteLLM proxy (`fast` alias) with
    a tool-use schema of Aria's actions; the model returns which actions to
    run. Escalate to `best` for multi-step planning.
- **Action executor — the macOS hands:**
  - **Hammerspoon** as the primary driver: window moves/focus/layouts, app
    launching, keystroke injection, URL/event triggers. Expose a small local
    HTTP or IPC surface so Aria's Python process calls named actions.
  - **AppleScript/JXA** for app-specific verbs (new iTerm tab in a directory,
    frontmost Finder path, browser tabs).
  - **macOS Shortcuts** for anything already automated there (`shortcuts run`).
  - Represent every action as a declarative **skill** (name, args, description)
    so the same registry serves Tier 1 matching and Tier 2 tool-calling.
- **TTS:** macOS `say` to start; upgrade to Piper or a provider TTS for
  quality.

### 5.2 Aria's model-switching skills (ties the whole system together)

First-class skills to build:

- `open_agent(provider, model, path)` — "Aria, open Claude Code on dex-bot
  with Opus" → new iTerm tab, `cd`, launch `claude --model ...`.
- `switch_agent(provider)` — focuses (or opens) that agent's pane/tab; with
  tmux, sends the pane-focus keys.
- `set_model(model_alias)` — types `/model <x>` into the focused agent session.
- `layout(name)` — Hammerspoon window presets ("coding", "research", "review").
- `handoff()` — copies current task summary to clipboard, opens the next
  provider's agent so you can paste context and continue when quota runs out.

### 5.3 Permissions & safety

- Grant Aria's runner + Hammerspoon: **Accessibility**, **Microphone**, and
  (only if screen-reading is added later) **Screen Recording** in
  System Settings → Privacy & Security.
- Confirm-before-execute for destructive verbs (closing windows, deleting,
  sending anything). Log every action to a local file for review.
- Keep all audio processing local (wake word + whisper.cpp); only the final
  text intent ever reaches a cloud model, via your own proxy.

### 5.4 Milestones

| Milestone | Deliverable |
|---|---|
| A1 | Aria repo scaffold: wake word + whisper.cpp streaming + `say` echo loop |
| A2 | Skill registry + Hammerspoon bridge; 10 window/app actions voice-driven |
| A3 | Tier-2 LLM routing via LiteLLM with tool-calling over the skill registry |
| A4 | Agent-switching skills (`open_agent`, `switch_agent`, `set_model`, `handoff`) |
| A5 | Multi-step plans: "Aria, set up my coding layout and start Claude on dex-bot" executes 4–5 chained actions with confirmation |

---

## 6. Roadmap summary

| Phase | When | Outcome |
|---|---|---|
| 1. Three CLIs installed & normalized | Day 1 | All 3 subscriptions usable from terminal; shared `CLAUDE.md`/`AGENTS.md`; sub-model switching learned |
| 2. Switching layer | Week 1 | `ai` command, Raycast/Hammerspoon hotkeys, tmux tri-pane, quota-rotation habit |
| 3. LiteLLM router | Week 2 | One local endpoint for all APIs; aliases, fallbacks, spend tracking |
| 4. Aria v2 | Weeks 3–6 | Voice-driven window + model navigation; multi-step macOS actions; agent handoff |

## 7. Risks / gotchas

- **Quota semantics differ** (Claude Max 5-hour windows vs. ChatGPT agentic
  limits vs. Grok Build beta limits) — the rotation habit (§3.4) is the hedge.
- **Grok Build is beta** — expect churn in flags/config; keep its role
  "parallel work + third opinion" until it stabilizes.
- **API ≠ subscription billing** — Plane B costs real money per token; set
  LiteLLM budgets/alerts so Aria can't silently run up a bill.
- **Model IDs churn** — that's why every layer (CLI configs, LiteLLM aliases,
  Aria skills) references *aliases* you control, never hardcoded IDs.
