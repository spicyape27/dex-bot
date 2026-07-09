"""Pure-logic tests for edge_assistant.py — runnable on the phone or any
laptop (no Termux needed): python -m pytest aria/tests -q
Covers exactly the code that changes most: direct routes, wake-word
stripping, and the transcript hallucination filter.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import edge_assistant as ea  # noqa: E402


# ---- direct route matching -------------------------------------------------

def route_name(text):
    r = ea.match_direct_route(text)
    return r[0] if r else None


def test_battery_routes():
    assert route_name("what's my battery at") == "battery"
    assert route_name("battery percentage please") == "battery"
    assert route_name("How much battery do I have?") == "battery"


def test_battery_negative():
    # 'battery' in an unrelated sense should still route (single-user tradeoff),
    # but pure non-battery questions must not
    assert route_name("what's the capital of France") is None
    assert route_name("tell me a joke") is None


def test_time_and_date():
    assert route_name("what time is it") == "time"
    assert route_name("what's the time") == "time"
    assert route_name("what day is it") == "date"
    assert route_name("what's today's date") == "date"
    # "timer" must not hit the time route
    assert route_name("set a timer for ten minutes") is None


def test_torch():
    assert route_name("turn on the flashlight") == "torch_on"
    assert route_name("flashlight off") == "torch_off"
    assert route_name("switch on the torch") == "torch_on"
    assert route_name("is a torch waterproof") is None


def test_volume_brightness_capture():
    r = ea.match_direct_route("set volume to 50")
    assert r[0] == "volume" and r[2].group("pct") == "50"
    r = ea.match_direct_route("brightness 80")
    assert r[0] == "brightness" and r[2].group("pct") == "80"


def test_wifi_and_clipboard():
    assert route_name("what wifi am I on") == "wifi"
    assert route_name("read my clipboard") == "clip_read"
    assert route_name("what's on the clipboard") == "clip_read"


def test_remember_capture():
    r = ea.match_direct_route("remember that my anniversary is June 3rd")
    assert r[0] == "remember"
    assert r[2].group("fact") == "my anniversary is June 3rd"
    assert route_name("what do you remember about me") == "recall"
    # mid-sentence 'remember' must NOT trigger storage
    assert route_name("do you remember the movie we watched") != "remember"


# ---- wake word --------------------------------------------------------------

def test_wake_variants():
    for heard in ["Aria", "arya!", "Hey Aria,", "ARIA what's up"]:
        woke, _ = ea.strip_wake_word(heard)
        assert woke, heard


def test_wake_one_breath():
    woke, rest = ea.strip_wake_word("Aria what's my battery at")
    assert woke and rest == "what's my battery at"


def test_no_false_wake():
    woke, _ = ea.strip_wake_word("the weather is nice today")
    assert not woke


# ---- hallucination filter ---------------------------------------------------

def test_hallucinations_dropped():
    for junk in ["", " ", "Thank you.", "[BLANK_AUDIO]", "Thanks for watching!",
                 "(music)", "you", "Um."]:
        assert ea.clean_transcript(junk) == "", repr(junk)


def test_real_speech_kept():
    assert ea.clean_transcript("  what's my battery at  ") == "what's my battery at"
    assert ea.clean_transcript("turn on [inaudible] the torch") == "turn on the torch"


# ---- misc -------------------------------------------------------------------

def test_version_and_hash():
    assert ea.__version__
    assert len(ea.self_hash()) == 12


def test_tool_specs_within_small_model_budget():
    # >8 tools degrades 3B-class tool selection; the direct-route layer is
    # what makes capability growth safe. Enforce the ceiling.
    assert len(ea.TOOLS_SPEC) <= 8
    assert set(ea.TOOL_IMPLS) == {t["function"]["name"] for t in ea.TOOLS_SPEC}
