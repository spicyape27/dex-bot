#!/usr/bin/env python3
"""Model bake-off: measure tool-call success rate + latency against the REAL
Aria tool schema. Run against llama-server with each candidate model:

  python bench/toolcall_bench.py                 # defaults to 127.0.0.1:8080
  python bench/toolcall_bench.py http://127.0.0.1:8081

Candidates worth testing (Q4_0 GGUFs — the ARM-optimized quant):
  - Llama-3.2-3B-Instruct (current baseline)
  - Qwen3-4B-Instruct-2507 (best sub-7B tool caller as of mid-2026)
  - LFM2-2.6B (fastest CPU decode; verify its tool format works via --jinja)
"""
import json
import sys
import time

import httpx

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), ".."))
from edge_assistant import TOOLS_SPEC, get_token  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")

# (prompt, expected tool or None if no tool should fire)
CASES = [
    ("What's my battery at?", "get_battery_status"),
    ("How much charge does the phone have left?", "get_battery_status"),
    ("Is the phone charging right now?", "get_battery_status"),
    ("What time is it?", "get_current_time"),
    ("Do you know today's date?", "get_current_time"),
    ("Turn on the flashlight.", "set_torch"),
    ("It's too bright, kill the torch.", "set_torch"),
    ("Read me whatever is on the clipboard.", "get_clipboard"),
    ("Copy 'milk, eggs, coffee' to my clipboard.", "set_clipboard"),
    ("Remind me to call mom — make it a notification.", "send_notification"),
    ("What WiFi network am I connected to?", "get_wifi_info"),
    ("How strong is my WiFi signal?", "get_wifi_info"),
    ("Remember that I park on level 3.", "remember_fact"),
    ("Please remember my locker code is 4482.", "remember_fact"),
    # negatives — the model must answer directly, not hallucinate a tool
    ("What's the capital of France?", None),
    ("Tell me a one-line joke.", None),
    ("How many days are in March?", None),
    ("What does RSVP stand for?", None),
    ("Spell the word 'necessary'.", None),
    ("What rhymes with orange?", None),
]


def main():
    client = httpx.Client(timeout=180,
                          headers={"Authorization": f"Bearer {get_token()}"})
    ok = 0
    latencies = []
    for prompt, expected in CASES:
        t0 = time.time()
        try:
            r = client.post(BASE + "/v1/chat/completions", json={
                "model": "local", "max_tokens": 120, "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
                "tools": TOOLS_SPEC})
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            got = calls[0]["function"]["name"] if calls else None
        except httpx.HTTPError as e:
            got = f"ERROR {e}"
        dt = time.time() - t0
        latencies.append(dt)
        hit = got == expected
        ok += hit
        print(f"{'PASS' if hit else 'FAIL'} {dt:5.1f}s  {prompt!r}"
              f"  -> {got}  (want {expected})")
    n = len(CASES)
    print(f"\n{ok}/{n} correct ({100*ok/n:.0f}%)  "
          f"median latency {sorted(latencies)[n//2]:.1f}s")
    print("Record model name + score + tok/s (from llama-bench) in LEDGER.md.")


if __name__ == "__main__":
    main()
