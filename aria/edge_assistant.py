#!/usr/bin/env python3
"""Aria — sovereign, fully offline voice assistant for Termux on Android.

Single-file by design: one artifact to deploy, one thing to `git pull`.
Everything talks to a local llama.cpp `llama-server` (OpenAI-compatible API)
and whisper.cpp for STT. Device control goes through Termux:API. No cloud.

Modes:
  --voice       wake-word voice loop (started from the Termux:Widget shortcut)
  --serve       loopback HTTP endpoint on :8100 (POST /ask, token-protected)
  --ask TEXT    one-shot text query (full pipeline minus the microphone)
  --selftest    verify every dependency and print PASS/FAIL per check
  --version     print version + sha256 self-hash (the anti-stale-file check)

Config lives in ~/.aria.conf (see aria.conf.example); every value has an
in-code default so a fresh install runs with no config file at all.
"""

__version__ = "7.0.0"

import argparse
import array
import configparser
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import queue
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler

try:
    import httpx
except ImportError:  # only Brain/serve need it; tests + routes work without
    httpx = None

# --------------------------------------------------------------------------
# Paths & configuration
# --------------------------------------------------------------------------

HOME = os.path.expanduser("~")
DATA_DIR = os.path.join(HOME, ".aria")
TMP_DIR = os.path.join(HOME, ".assistant_tmp")
LOG_DIR = os.path.join(DATA_DIR, "logs")
CONF_PATH = os.environ.get("ARIA_CONF", os.path.join(HOME, ".aria.conf"))
TOKEN_PATH = os.path.join(HOME, ".aria_token")
DB_PATH = os.path.join(DATA_DIR, "aria.db")

DEFAULTS = {
    "server": {
        "llama_url": "http://127.0.0.1:8080",
        "serve_host": "127.0.0.1",
        "serve_port": "8100",
    },
    "models": {
        "whisper_bin": os.path.join(HOME, "whisper.cpp/build/bin/whisper-cli"),
        "whisper_model": os.path.join(HOME, "whisper.cpp/models/ggml-tiny.en.bin"),
        # better-WER model used for the full question once the turn is captured;
        # falls back to whisper_model if the file doesn't exist
        "whisper_model_long": os.path.join(HOME, "whisper.cpp/models/ggml-base.en.bin"),
        "whisper_threads": "4",
        # optional Silero VAD model for whisper-cli --vad (empty = off)
        "whisper_vad_model": "",
    },
    "voice": {
        "wake_words": "aria, arya, aria,, aria!, area, ariya",
        # audio backend: "termux" = termux-microphone-record chunks (safe default)
        #                "pulse"  = continuous gapless capture via parecord (needs
        #                           `pkg install pulseaudio` + module-sles-source; see RUNBOOK)
        "backend": "termux",
        "idle_listen_seconds": "4",
        "chunk_seconds": "5",
        "max_chunks": "6",
        "follow_up_seconds": "8",
        # pulse backend tuning
        "vad_rms_threshold": "500",
        "vad_silence_ms": "700",
        "vad_max_utterance_s": "30",
    },
    "llm": {
        "temperature": "0.6",
        "max_tokens": "300",
        "max_tool_rounds": "3",
        "timeout_seconds": "120",
        "stream": "true",
        "history_turns": "6",
        # send the shared token as an API key to llama-server (requires --api-key
        # in the boot script; /health stays public either way)
        "use_api_key": "true",
    },
    "memory": {
        "enabled": "true",
        "max_facts_in_prompt": "12",
    },
}

CFG = configparser.ConfigParser()
CFG.read_dict(DEFAULTS)
CFG.read(CONF_PATH)

log = logging.getLogger("aria")


def setup_logging(debug: bool = False) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    fh = RotatingFileHandler(
        os.path.join(LOG_DIR, "aria.log"), maxBytes=512 * 1024, backupCount=3
    )
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(sh)


def get_token() -> str:
    """Shared secret for :8100 auth (and llama-server --api-key). Auto-created.

    Lives in Termux private storage, unreadable by other Android apps — this is
    what closes the app→localhost attack surface.
    """
    if not os.path.exists(TOKEN_PATH):
        tok = hashlib.sha256(os.urandom(32)).hexdigest()
        with open(TOKEN_PATH, "w") as f:
            f.write(tok)
        os.chmod(TOKEN_PATH, 0o600)
        return tok
    with open(TOKEN_PATH) as f:
        return f.read().strip()


def self_hash() -> str:
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def clean_tmp(max_age_min: int = 0) -> None:
    """Delete transient audio clips. Voice recordings are the most sensitive
    exhaust this program produces; never let them accumulate."""
    if not os.path.isdir(TMP_DIR):
        os.makedirs(TMP_DIR, exist_ok=True)
        return
    now = time.time()
    for name in os.listdir(TMP_DIR):
        p = os.path.join(TMP_DIR, name)
        try:
            if max_age_min == 0 or now - os.path.getmtime(p) > max_age_min * 60:
                os.remove(p)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Termux:API bridge
# --------------------------------------------------------------------------


def run(cmd, timeout=15, input_text=None):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, input=input_text
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {' '.join(cmd)}"
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"


def battery_status() -> dict:
    rc, out, _ = run(["termux-battery-status"], timeout=8)
    return json.loads(out) if rc == 0 and out else {}


def speak(text: str) -> None:
    if not text:
        return
    log.debug("tts: %s", text)
    run(["termux-tts-speak", text], timeout=120)


def vibrate(ms: int = 200) -> None:
    run(["termux-vibrate", "-d", str(ms)], timeout=5)


def notify(title: str, content: str) -> None:
    run(["termux-notification", "-t", title, "-c", content], timeout=8)


def torch(on: bool) -> None:
    run(["termux-torch", "on" if on else "off"], timeout=8)


def clipboard_get() -> str:
    rc, out, _ = run(["termux-clipboard-get"], timeout=8)
    return out if rc == 0 else ""


def clipboard_set(text: str) -> None:
    run(["termux-clipboard-set"], timeout=8, input_text=text)


def wifi_info() -> dict:
    rc, out, _ = run(["termux-wifi-connectioninfo"], timeout=8)
    return json.loads(out) if rc == 0 and out else {}


def set_volume(level_pct: int) -> None:
    # termux-volume takes an absolute step; music stream is 0..15 on most devices
    step = max(0, min(15, round(level_pct * 15 / 100)))
    run(["termux-volume", "music", str(step)], timeout=8)


def set_brightness(level_pct: int) -> None:
    val = max(0, min(255, round(level_pct * 255 / 100)))
    run(["termux-brightness", str(val)], timeout=8)


# --------------------------------------------------------------------------
# Memory (SQLite, stdlib only)
# --------------------------------------------------------------------------


class Memory:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS turns(
                ts REAL, mode TEXT, user_text TEXT, route TEXT, reply TEXT);
            CREATE TABLE IF NOT EXISTS facts(
                ts REAL, fact TEXT UNIQUE);
            """
        )
        self.db.commit()

    def log_turn(self, mode, user_text, route, reply):
        with self.lock:
            self.db.execute(
                "INSERT INTO turns VALUES(?,?,?,?,?)",
                (time.time(), mode, user_text, route, reply),
            )
            self.db.commit()

    def remember(self, fact: str) -> None:
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO facts VALUES(?,?)", (time.time(), fact.strip())
            )
            self.db.commit()

    def facts(self, limit=None) -> list:
        limit = limit or CFG.getint("memory", "max_facts_in_prompt")
        with self.lock:
            rows = self.db.execute(
                "SELECT fact FROM facts ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [r[0] for r in rows]

    def facts_block(self) -> str:
        facts = self.facts()
        if not facts:
            return ""
        return "Known facts about the user:\n" + "\n".join(f"- {f}" for f in facts)

    def recent_turns(self, n) -> list:
        with self.lock:
            rows = self.db.execute(
                "SELECT user_text, reply FROM turns ORDER BY ts DESC LIMIT ?", (n,)
            ).fetchall()
        return list(reversed(rows))


# --------------------------------------------------------------------------
# LLM tools (kept to 8 — beyond that a small model's tool-picking degrades)
# --------------------------------------------------------------------------

TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "get_battery_status",
        "description": "Get the phone's battery percentage, temperature and charging state.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_current_time",
        "description": "Get the current local date and time.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "set_torch",
        "description": "Turn the phone flashlight (torch) on or off.",
        "parameters": {"type": "object", "properties": {
            "on": {"type": "boolean", "description": "true = on, false = off"}},
            "required": ["on"]}}},
    {"type": "function", "function": {
        "name": "get_clipboard",
        "description": "Read the current contents of the phone clipboard.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "set_clipboard",
        "description": "Put text on the phone clipboard.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "send_notification",
        "description": "Show a persistent Android notification (good for reminders).",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "content": {"type": "string"}},
            "required": ["title", "content"]}}},
    {"type": "function", "function": {
        "name": "get_wifi_info",
        "description": "Get the current WiFi network name and signal strength.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "remember_fact",
        "description": "Store a fact about the user in long-term memory.",
        "parameters": {"type": "object", "properties": {
            "fact": {"type": "string"}}, "required": ["fact"]}}},
]


def _tool_battery(_args, _mem):
    b = battery_status()
    if not b:
        return "battery status unavailable"
    return json.dumps({"percentage": b.get("percentage"),
                       "status": b.get("status"),
                       "temperature_c": b.get("temperature")})


def _tool_time(_args, _mem):
    return time.strftime("%A %B %d %Y, %I:%M %p")


def _tool_torch(args, _mem):
    torch(bool(args.get("on")))
    return "torch " + ("on" if args.get("on") else "off")


def _tool_clip_get(_args, _mem):
    return clipboard_get() or "(clipboard empty)"


def _tool_clip_set(args, _mem):
    clipboard_set(args.get("text", ""))
    return "copied"


def _tool_notify(args, _mem):
    notify(args.get("title", "Aria"), args.get("content", ""))
    return "notification sent"


def _tool_wifi(_args, _mem):
    w = wifi_info()
    return json.dumps({"ssid": w.get("ssid"), "rssi_dbm": w.get("rssi"),
                       "link_speed_mbps": w.get("link_speed")}) if w else "wifi info unavailable"


def _tool_remember(args, mem):
    fact = args.get("fact", "").strip()
    if fact and mem:
        mem.remember(fact)
        return "remembered"
    return "nothing to remember"


TOOL_IMPLS = {
    "get_battery_status": _tool_battery,
    "get_current_time": _tool_time,
    "set_torch": _tool_torch,
    "get_clipboard": _tool_clip_get,
    "set_clipboard": _tool_clip_set,
    "send_notification": _tool_notify,
    "get_wifi_info": _tool_wifi,
    "remember_fact": _tool_remember,
}

# --------------------------------------------------------------------------
# Direct routes — regex → deterministic handler. Essentials must never depend
# on a 3B model's tool-picking judgment. Declarative so they're testable.
# Each entry: (name, [patterns], handler(match, full_text, mem) -> reply str)
# --------------------------------------------------------------------------


def _route_battery(_m, _t, _mem):
    b = battery_status()
    if not b:
        return "I couldn't read the battery."
    state = {"CHARGING": "and charging", "FULL": "and full",
             "DISCHARGING": ""}.get(b.get("status", ""), "")
    return f"Battery is at {b.get('percentage')} percent {state}".strip() + "."


def _route_time(_m, _t, _mem):
    return "It's " + time.strftime("%I:%M %p").lstrip("0") + "."


def _route_date(_m, _t, _mem):
    return "Today is " + time.strftime("%A, %B %d") + "."


def _route_torch_on(_m, _t, _mem):
    torch(True)
    return "Flashlight on."


def _route_torch_off(_m, _t, _mem):
    torch(False)
    return "Flashlight off."


def _route_volume(m, _t, _mem):
    pct = int(m.group("pct"))
    set_volume(pct)
    return f"Volume set to {pct} percent."


def _route_brightness(m, _t, _mem):
    pct = int(m.group("pct"))
    set_brightness(pct)
    return f"Brightness set to {pct} percent."


def _route_wifi(_m, _t, _mem):
    w = wifi_info()
    if not w or not w.get("ssid"):
        return "I don't see a WiFi connection."
    return f"You're on {w['ssid'].strip(chr(34))}, signal {w.get('rssi', '?')} dBm."


def _route_clip_read(_m, _t, _mem):
    c = clipboard_get()
    return ("Clipboard says: " + c[:300]) if c else "The clipboard is empty."


def _route_remember(m, _t, mem):
    fact = m.group("fact").strip().rstrip(".")
    if mem:
        mem.remember(fact)
        return "Okay, I'll remember that."
    return "Memory is disabled."


def _route_recall(_m, _t, mem):
    facts = mem.facts() if mem else []
    if not facts:
        return "I don't have anything remembered yet."
    return "Here's what I remember: " + ". ".join(facts[:5]) + "."


DIRECT_ROUTES = [
    ("battery",
     [r"\bbatter(y|ies)\b"],
     _route_battery),
    ("time",
     [r"\bwhat(?:'s| is)? the time\b", r"\bwhat time is it\b", r"^time$"],
     _route_time),
    ("date",
     [r"\bwhat(?:'s| is)? (the date|today'?s date)\b", r"\bwhat day is (it|today)\b"],
     _route_date),
    ("torch_on",
     [r"\b(turn|switch) on (the )?(flash\s?light|torch)\b",
      r"\b(flash\s?light|torch) on\b"],
     _route_torch_on),
    ("torch_off",
     [r"\b(turn|switch) off (the )?(flash\s?light|torch)\b",
      r"\b(flash\s?light|torch) off\b"],
     _route_torch_off),
    ("volume",
     [r"\b(?:set )?volume (?:to )?(?P<pct>\d{1,3})\b"],
     _route_volume),
    ("brightness",
     [r"\b(?:set )?brightness (?:to )?(?P<pct>\d{1,3})\b"],
     _route_brightness),
    ("wifi",
     [r"\bwhat wi-?fi\b", r"\bwi-?fi (network|signal|info)\b",
      r"\bwhich (wi-?fi|network) am i on\b"],
     _route_wifi),
    ("clip_read",
     [r"\b(read|what'?s? (?:on|in)) (?:the |my )?clipboard\b"],
     _route_clip_read),
    ("remember",
     [r"^remember (?:that )?(?P<fact>.+)$"],
     _route_remember),
    ("recall",
     [r"\bwhat do you (remember|know) about me\b", r"\bwhat'?s in your memory\b"],
     _route_recall),
]

_COMPILED_ROUTES = [
    (name, [re.compile(p, re.IGNORECASE) for p in pats], handler)
    for name, pats, handler in DIRECT_ROUTES
]


def match_direct_route(text: str):
    """Return (route_name, handler, match) or None."""
    t = text.strip().rstrip(".!?")
    for name, patterns, handler in _COMPILED_ROUTES:
        for pat in patterns:
            m = pat.search(t)
            if m:
                return name, handler, m
    return None


# --------------------------------------------------------------------------
# Transcript hygiene — whisper hallucinates on silence; never let those
# reach the LLM (they produce spoken non-sequiturs).
# --------------------------------------------------------------------------

HALLUCINATIONS = {
    "", ".", "you", "thank you", "thank you.", "thanks for watching",
    "thanks for watching!", "thank you for watching", "[blank_audio]",
    "[silence]", "(silence)", "[inaudible]", "[music]", "(music)", "bye",
    "so", "the", "uh", "um",
}


def clean_transcript(text: str) -> str:
    t = re.sub(r"\[.*?\]|\(.*?\)", " ", text)  # bracketed annotations
    t = re.sub(r"\s+", " ", t).strip()
    if t.lower().strip(".!,? ") in HALLUCINATIONS:
        return ""
    return t


WAKE_WORDS = [w.strip().lower() for w in CFG.get("voice", "wake_words").split(",") if w.strip()]


def strip_wake_word(text: str):
    """Return (woke, remainder). One-breath mode: 'Aria what's my battery'."""
    t = text.strip()
    low = t.lower()
    for w in sorted(WAKE_WORDS, key=len, reverse=True):
        idx = low.find(w)
        if idx != -1:
            remainder = (t[:idx] + " " + t[idx + len(w):]).strip(" ,.!?")
            return True, remainder
    return False, t


# --------------------------------------------------------------------------
# Whisper STT
# --------------------------------------------------------------------------


def transcribe(wav_path: str, long_form: bool = False) -> str:
    model = CFG.get("models", "whisper_model")
    if long_form:
        long_model = CFG.get("models", "whisper_model_long")
        if os.path.exists(long_model):
            model = long_model
    cmd = [
        CFG.get("models", "whisper_bin"), "-m", model, "-f", wav_path,
        "-t", CFG.get("models", "whisper_threads"), "-nt", "-np",
    ]
    vad_model = CFG.get("models", "whisper_vad_model")
    if vad_model and os.path.exists(vad_model):
        cmd += ["--vad", "--vad-model", vad_model]
    rc, out, err = run(cmd, timeout=120)
    if rc != 0:
        log.warning("whisper failed rc=%s err=%s", rc, err[:200])
        return ""
    return clean_transcript(out)


# --------------------------------------------------------------------------
# Audio capture backends
# --------------------------------------------------------------------------


class TermuxRecorder:
    """Chunked capture via termux-microphone-record (safe default).

    Known limitation: ~1-2s gap between chunks (recorder stop/start). The
    pulse backend removes this entirely — see RUNBOOK.md for the spike test.
    """

    def record_clip(self, seconds: int) -> str:
        clean_tmp(max_age_min=10)
        m4a = os.path.join(TMP_DIR, f"clip_{int(time.time()*1000)}.m4a")
        wav = m4a.replace(".m4a", ".wav")
        run(["termux-microphone-record", "-f", m4a, "-l", str(seconds)], timeout=8)
        time.sleep(seconds + 0.4)
        run(["termux-microphone-record", "-q"], timeout=8)
        rc, _, err = run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", m4a,
             "-ar", "16000", "-ac", "1", wav], timeout=30)
        try:
            os.remove(m4a)
        except OSError:
            pass
        if rc != 0:
            log.warning("ffmpeg convert failed: %s", err[:200])
            return ""
        return wav

    def stop(self):
        run(["termux-microphone-record", "-q"], timeout=5)


class PulseListener:
    """Continuous gapless PCM capture via PulseAudio module-sles-source.

    Setup (once):  pkg install pulseaudio
                   pulseaudio --start --exit-idle-time=-1
                   pactl load-module module-sles-source
    Then set  [voice] backend = pulse  in ~/.aria.conf.

    Uses simple RMS energy VAD for utterance endpointing — no extra deps.
    """

    RATE = 16000
    FRAME_MS = 30

    def __init__(self):
        self.frame_bytes = self.RATE * 2 * self.FRAME_MS // 1000
        self.proc = subprocess.Popen(
            ["parecord", "--format=s16le", f"--rate={self.RATE}",
             "--channels=1", "--raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.threshold = CFG.getint("voice", "vad_rms_threshold")
        self.silence_frames = CFG.getint("voice", "vad_silence_ms") // self.FRAME_MS
        self.max_frames = CFG.getint("voice", "vad_max_utterance_s") * 1000 // self.FRAME_MS

    @staticmethod
    def _rms(frame: bytes) -> float:
        samples = array.array("h")
        samples.frombytes(frame[: len(frame) - len(frame) % 2])
        if not samples:
            return 0.0
        return (sum(s * s for s in samples) / len(samples)) ** 0.5

    def _read_frame(self):
        data = self.proc.stdout.read(self.frame_bytes)
        return data if data and len(data) == self.frame_bytes else None

    def wait_utterance(self, timeout_s: float):
        """Block until a spoken utterance is captured; return wav path or None."""
        deadline = time.time() + timeout_s
        # wait for speech onset
        while time.time() < deadline:
            frame = self._read_frame()
            if frame is None:
                return None
            if self._rms(frame) >= self.threshold:
                break
        else:
            return None
        # collect until trailing silence
        frames = [frame]
        silent = 0
        while len(frames) < self.max_frames:
            frame = self._read_frame()
            if frame is None:
                break
            frames.append(frame)
            if self._rms(frame) < self.threshold:
                silent += 1
                if silent >= self.silence_frames:
                    break
            else:
                silent = 0
        wav_path = os.path.join(TMP_DIR, f"utt_{int(time.time()*1000)}.wav")
        os.makedirs(TMP_DIR, exist_ok=True)
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.RATE)
            w.writeframes(b"".join(frames))
        return wav_path

    def stop(self):
        try:
            self.proc.terminate()
        except OSError:
            pass


# --------------------------------------------------------------------------
# Brain — llama-server client with tool loop + sentence-streaming
# --------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are Aria, a concise voice assistant running fully offline on the "
    "user's phone. Answers are spoken aloud, so keep them to one or two short "
    "sentences unless asked for detail. Use tools when they apply. Never "
    "mention being an AI model or apologize excessively."
)

_SENTENCE_END = re.compile(r"([.!?])(\s|$)")


class Brain:
    def __init__(self, mem=None):
        if httpx is None:
            sys.exit("httpx is required: pip install httpx")
        self.base = CFG.get("server", "llama_url").rstrip("/")
        self.mem = mem
        headers = {}
        if CFG.getboolean("llm", "use_api_key"):
            headers["Authorization"] = f"Bearer {get_token()}"
        self.client = httpx.Client(
            timeout=CFG.getfloat("llm", "timeout_seconds"), headers=headers)

    def health(self) -> bool:
        try:
            r = httpx.get(self.base + "/health", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def _messages(self, user_text: str) -> list:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.mem:
            facts = self.mem.facts_block()
            if facts:
                msgs.append({"role": "system", "content": facts})
            for u, a in self.mem.recent_turns(CFG.getint("llm", "history_turns")):
                if u:
                    msgs.append({"role": "user", "content": u})
                if a:
                    msgs.append({"role": "assistant", "content": a})
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def ask(self, user_text: str, sentence_cb=None) -> str:
        """Run the tool loop. If sentence_cb is given, completed sentences are
        delivered as they stream (spoken while the rest still generates)."""
        msgs = self._messages(user_text)
        for _ in range(CFG.getint("llm", "max_tool_rounds") + 1):
            content, tool_calls = self._completion(msgs, sentence_cb)
            if not tool_calls:
                return content
            msgs.append({"role": "assistant", "content": content or None,
                         "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                impl = TOOL_IMPLS.get(name)
                result = impl(args, self.mem) if impl else f"unknown tool {name}"
                log.info("tool %s(%s) -> %s", name, args, str(result)[:120])
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", name),
                             "content": str(result)})
        return content or "I couldn't finish that."

    def _completion(self, msgs, sentence_cb):
        payload = {
            "model": "local",
            "messages": msgs,
            "tools": TOOLS_SPEC,
            "temperature": CFG.getfloat("llm", "temperature"),
            "max_tokens": CFG.getint("llm", "max_tokens"),
        }
        if not (CFG.getboolean("llm", "stream") and sentence_cb):
            r = self.client.post(self.base + "/v1/chat/completions", json=payload)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            return msg.get("content") or "", msg.get("tool_calls") or []

        # streaming: speak sentences as they arrive; accumulate tool calls
        payload["stream"] = True
        content, buf = "", ""
        tool_calls = {}
        with self.client.stream(
            "POST", self.base + "/v1/chat/completions", json=payload
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                piece = delta.get("content") or ""
                if piece:
                    content += piece
                    buf += piece
                    m = _SENTENCE_END.search(buf)
                    while m:
                        sentence, buf = buf[: m.end()].strip(), buf[m.end():]
                        if sentence:
                            sentence_cb(sentence)
                        m = _SENTENCE_END.search(buf)
                for tcd in delta.get("tool_calls") or []:
                    i = tcd.get("index", 0)
                    slot = tool_calls.setdefault(
                        i, {"id": tcd.get("id", f"call_{i}"), "type": "function",
                            "function": {"name": "", "arguments": ""}})
                    fn = tcd.get("function", {})
                    if fn.get("name"):
                        slot["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]
        if buf.strip() and not tool_calls:
            sentence_cb(buf.strip())
        return content, [tool_calls[i] for i in sorted(tool_calls)]


# --------------------------------------------------------------------------
# Query handling (shared by voice / serve / ask)
# --------------------------------------------------------------------------


def handle_query(text: str, brain: Brain, mem, mode: str, sentence_cb=None) -> str:
    text = clean_transcript(text)
    if not text:
        return ""
    routed = match_direct_route(text)
    if routed:
        name, handler, m = routed
        try:
            reply = handler(m, text, mem)
        except Exception:
            log.exception("direct route %s failed", name)
            reply = "That didn't work, sorry."
        log.info("[%s] route=%s q=%r a=%r", mode, name, text, reply)
        if mem:
            mem.log_turn(mode, text, name, reply)
        if sentence_cb and reply:
            sentence_cb(reply)
        return reply
    t0 = time.time()
    try:
        reply = brain.ask(text, sentence_cb=sentence_cb)
    except httpx.HTTPError as e:
        log.error("llm error: %s", e)
        reply = "The brain isn't answering right now."
        if sentence_cb:
            sentence_cb(reply)
    log.info("[%s] route=llm %.1fs q=%r a=%r", mode, time.time() - t0, text, reply)
    if mem:
        mem.log_turn(mode, text, "llm", reply)
    return reply


class Speaker:
    """Background TTS queue: speak sentence N while N+1 generates."""

    def __init__(self):
        self.q = queue.Queue()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        while True:
            text = self.q.get()
            if text is None:
                return
            speak(text)
            self.q.task_done()

    def say(self, text):
        self.q.put(text)

    def wait(self):
        self.q.join()


# --------------------------------------------------------------------------
# Voice loop
# --------------------------------------------------------------------------


def voice_loop():
    clean_tmp()
    mem = Memory() if CFG.getboolean("memory", "enabled") else None
    brain = Brain(mem)
    speaker = Speaker()
    backend = CFG.get("voice", "backend")
    recorder = None
    listener = None
    if backend == "pulse":
        try:
            listener = PulseListener()
            log.info("voice loop: pulse backend (gapless)")
        except FileNotFoundError:
            log.warning("parecord not found — falling back to termux backend")
            backend = "termux"
    if backend == "termux":
        recorder = TermuxRecorder()
        log.info("voice loop: termux backend (chunked)")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    def capture_utterance(timeout_s, chunked_max=None):
        """One user utterance as text. Uses gapless VAD capture on pulse,
        rolling chunks (the v6 _listen_free approach) on termux."""
        if listener:
            wav = listener.wait_utterance(timeout_s)
            if not wav:
                return ""
            text = transcribe(wav, long_form=True)
            try:
                os.remove(wav)
            except OSError:
                pass
            return text
        return _listen_free(recorder, chunked_max)

    def _listen_free(rec, max_chunks=None):
        """Free-length listening: rolling chunks until silence ends the turn."""
        max_chunks = max_chunks or CFG.getint("voice", "max_chunks")
        chunk_s = CFG.getint("voice", "chunk_seconds")
        parts = []
        for _ in range(max_chunks):
            if stop.is_set():
                break
            wav = rec.record_clip(chunk_s)
            if not wav:
                break
            text = transcribe(wav, long_form=True)
            try:
                os.remove(wav)
            except OSError:
                pass
            if not text:
                break  # silence = end of turn
            parts.append(text)
        return " ".join(parts).strip()

    vibrate(150)
    notify("Aria", f"Voice mode active (v{__version__})")
    log.info("voice loop started v%s hash=%s", __version__, self_hash())

    while not stop.is_set():
        # ---- wake phase -------------------------------------------------
        if listener:
            wav = listener.wait_utterance(timeout_s=30)
            if not wav:
                continue
            heard = transcribe(wav)
            try:
                os.remove(wav)
            except OSError:
                pass
        else:
            wav = recorder.record_clip(CFG.getint("voice", "idle_listen_seconds"))
            heard = transcribe(wav) if wav else ""
            if wav:
                try:
                    os.remove(wav)
                except OSError:
                    pass
        if not heard:
            continue
        woke, remainder = strip_wake_word(heard)
        if not woke:
            continue

        # ---- question phase ---------------------------------------------
        if len(remainder.split()) >= 3:
            question = remainder  # one-breath: "Aria what's my battery at"
        else:
            speak("Yes?")
            vibrate(120)
            question = capture_utterance(timeout_s=10)
        if not question:
            speak("Say that again?")
            question = capture_utterance(timeout_s=10)
            if not question:
                continue

        # ---- answer phase -------------------------------------------------
        vibrate(80)
        time.sleep(0.1)
        vibrate(80)  # double-buzz thinking cue
        handle_query(question, brain, mem, "voice", sentence_cb=speaker.say)
        speaker.wait()

        # ---- follow-up window: stay hot, no re-wake needed ---------------
        follow_s = CFG.getint("voice", "follow_up_seconds")
        if follow_s > 0:
            vibrate(60)
            follow = capture_utterance(timeout_s=follow_s, chunked_max=2)
            if follow:
                woke2, rem2 = strip_wake_word(follow)
                q2 = rem2 if woke2 else follow
                if q2 and clean_transcript(q2):
                    vibrate(80)
                    handle_query(q2, brain, mem, "voice", sentence_cb=speaker.say)
                    speaker.wait()

    if recorder:
        recorder.stop()
    if listener:
        listener.stop()
    clean_tmp()
    log.info("voice loop stopped")


# --------------------------------------------------------------------------
# Serve mode — loopback HTTP with shared-token auth
# --------------------------------------------------------------------------


def serve():
    mem = Memory() if CFG.getboolean("memory", "enabled") else None
    brain = Brain(mem)
    token = get_token()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("http: " + fmt, *args)

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"ok": True, "version": __version__,
                                 "hash": self_hash(), "brain": brain.health()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.headers.get("X-Aria-Token") != token:
                self._send(401, {"error": "missing or bad X-Aria-Token"})
                return
            if self.path != "/ask":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                text = str(data.get("text", ""))[:2000]
            except (ValueError, json.JSONDecodeError):
                self._send(400, {"error": "bad json"})
                return
            reply = handle_query(text, brain, mem, "http")
            self._send(200, {"reply": reply})

    host = CFG.get("server", "serve_host")
    port = CFG.getint("server", "serve_port")
    httpd = ThreadingHTTPServer((host, port), Handler)
    log.info("serving on %s:%s (token auth, v%s)", host, port, __version__)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------


def selftest() -> int:
    results = []

    def check(name, fn, hint):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001 — selftest must never crash
            ok, detail = False, str(e)[:120]
        results.append((ok, name, detail, hint))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            print(f"        fix: {hint}")

    print(f"Aria selftest v{__version__} hash={self_hash()}")
    print(f"config: {CONF_PATH} ({'found' if os.path.exists(CONF_PATH) else 'defaults only'})")

    check("llama-server /health",
          lambda: (Brain().health(), CFG.get("server", "llama_url")),
          "start it: sv up llama  (or run the boot script); model may still be loading")

    def _toolcheck():
        b = Brain()
        r = b.client.post(b.base + "/v1/chat/completions", json={
            "model": "local", "max_tokens": 40,
            "messages": [{"role": "user",
                          "content": "Call the ping tool now."}],
            "tools": [{"type": "function", "function": {
                "name": "ping", "description": "test tool",
                "parameters": {"type": "object", "properties": {}}}}]})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        called = bool(msg.get("tool_calls"))
        return called, "tool_calls returned" if called else "no tool_calls — is --jinja set?"
    check("tool-calling round-trip", _toolcheck,
          "llama-server MUST run with --jinja or the model never sees its tools")

    check("whisper binary",
          lambda: (os.access(CFG.get("models", "whisper_bin"), os.X_OK),
                   CFG.get("models", "whisper_bin")),
          "build whisper.cpp: cmake -B build && cmake --build build -j 4")
    check("whisper model",
          lambda: (os.path.exists(CFG.get("models", "whisper_model")),
                   os.path.basename(CFG.get("models", "whisper_model"))),
          "sh ~/whisper.cpp/models/download-ggml-model.sh tiny.en")
    check("termux-api (battery)",
          lambda: (bool(battery_status()), ""),
          "install Termux:API app from F-Droid + pkg install termux-api; grant mic permission")
    check("tts",
          lambda: (run(["termux-tts-speak", "self test passed"], timeout=30)[0] == 0, ""),
          "termux-tts-speak failed — check Termux:API app")
    check("token file",
          lambda: (oct(os.stat(TOKEN_PATH).st_mode)[-3:] == "600" if os.path.exists(TOKEN_PATH)
                   else bool(get_token()), TOKEN_PATH),
          "chmod 600 ~/.aria_token")
    check("sqlite memory",
          lambda: (bool(Memory().db.execute("SELECT 1").fetchone()), DB_PATH),
          "check ~/.aria is writable")

    def _serve_check():
        try:
            r = httpx.get(f"http://127.0.0.1:{CFG.get('server', 'serve_port')}/health",
                          timeout=3)
            return r.status_code == 200, f"v{r.json().get('version', '?')}"
        except httpx.HTTPError:
            return False, "not running (fine if --serve isn't supposed to be up)"
    check("serve endpoint :" + CFG.get("server", "serve_port"), _serve_check,
          "sv up aria  (or python edge_assistant.py --serve &)")

    rc, out, _ = run(["git", "-C", os.path.dirname(os.path.abspath(__file__)),
                      "log", "-1", "--oneline"], timeout=5)
    if rc == 0:
        print(f"  git: {out}")

    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description="Aria — offline voice assistant")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--voice", action="store_true", help="voice loop")
    mode.add_argument("--serve", action="store_true", help="HTTP endpoint")
    mode.add_argument("--ask", metavar="TEXT", help="one-shot text query")
    mode.add_argument("--selftest", action="store_true", help="verify install")
    mode.add_argument("--version", action="store_true", help="print version + hash")
    ap.add_argument("--debug", action="store_true", help="verbose logging")
    args = ap.parse_args()

    if args.version:
        print(f"aria {__version__} {self_hash()}")
        return 0

    setup_logging(args.debug)

    if args.selftest:
        return selftest()
    if args.ask:
        mem = Memory() if CFG.getboolean("memory", "enabled") else None
        reply = handle_query(args.ask, Brain(mem), mem, "cli")
        print(reply)
        return 0
    if args.serve:
        serve()
        return 0
    if args.voice:
        voice_loop()
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
