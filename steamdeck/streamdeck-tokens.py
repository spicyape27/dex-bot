#!/usr/bin/env python3
"""Claude token usage on an Elgato Stream Deck.

Renders your Claude Code usage straight onto the key screens of a 15-key
Stream Deck (5x3 grid):

    row 1:  TODAY $ | TOKENS | OUTPUT | 7 DAYS $ | 30 DAYS $
    row 2:  a 15-day cost bar chart, drawn across all five keys
    row 3:  top four models by cost, plus a REFRESH key

Pressing any key refreshes immediately; otherwise it re-reads the logs every
60 seconds. Usage aggregation is shared with token-viewer.py (same folder).

Requires:  pip install streamdeck pillow      (plus the hidapi system lib)
Preview without hardware:  python3 streamdeck-tokens.py --preview out.png
"""

import argparse
import importlib.util
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Import the scanner/aggregator from token-viewer.py in this directory.
_spec = importlib.util.spec_from_file_location(
    "token_viewer", Path(__file__).resolve().parent / "token-viewer.py")
token_viewer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(token_viewer)

BG = (26, 26, 25)        # surface
INK = (255, 255, 255)    # primary
INK2 = (195, 194, 183)   # secondary
MUTED = (137, 135, 129)
BLUE = (57, 135, 229)    # series
BASELINE = (56, 56, 53)

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def font(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fmt_money(v):
    return "$" + (f"{v:.0f}" if v >= 100 else f"{v:.1f}" if v >= 10 else f"{v:.2f}")


def fmt_tok(v):
    if v >= 1e9:
        return f"{v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.0f}K"
    return str(int(v))


def fit_text(draw, text, max_w, start=22, floor=10):
    size = start
    while size > floor:
        f = font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return font(floor)


def stat_tile(w, h, label, value, accent=False):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.text((w // 2, 12), label.upper(), font=font(10), fill=MUTED, anchor="mm")
    vf = fit_text(d, value, w - 8, start=26 if accent else 22)
    d.text((w // 2, h // 2 + 8), value, font=vf,
           fill=BLUE if accent else INK, anchor="mm")
    return img


def model_tile(w, h, name, value):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    name = name.replace("claude-", "")
    nf = fit_text(d, name, w - 6, start=12, floor=8)
    d.text((w // 2, 16), name, font=nf, fill=INK2, anchor="mm")
    vf = fit_text(d, value, w - 8, start=20)
    d.text((w // 2, h // 2 + 12), value, font=vf, fill=INK, anchor="mm")
    return img


def refresh_tile(w, h, ts):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.ellipse((w // 2 - 12, 10, w // 2 + 12, 34), outline=BLUE, width=3)
    d.polygon([(w // 2 + 8, 6), (w // 2 + 20, 14), (w // 2 + 6, 20)], fill=BLUE)
    d.text((w // 2, h - 20), "REFRESH", font=font(10), fill=MUTED, anchor="mm")
    d.text((w // 2, h - 8), ts, font=font(9), fill=MUTED, anchor="mm")
    return img


def chart_strip(days, w, h):
    """One wide bar chart image, later sliced into per-key tiles."""
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    top, bottom = 12, h - 14
    max_cost = max((day["cost"] for day in days), default=0) or 0.01
    n = len(days)
    slot = w / n
    bw = max(3, int(slot * 0.55))
    d.line((0, bottom, w, bottom), fill=BASELINE, width=2)
    for i, day in enumerate(days):
        bh = int((day["cost"] / max_cost) * (bottom - top))
        x0 = int(slot * i + (slot - bw) / 2)
        if bh > 0:
            d.rounded_rectangle((x0, bottom - bh, x0 + bw, bottom),
                                radius=2, fill=BLUE)
    # Keep header text inside single key widths so slicing can't cut it.
    peak = max(days, key=lambda day: day["cost"])
    d.text((6, 2), f"{n} DAYS", font=font(9), fill=MUTED)
    d.text((w - 6, 2), f"peak {fmt_money(peak['cost'])}",
           font=font(9), fill=MUTED, anchor="ra")
    d.text((6, h - 11), days[0]["label"], font=font(9), fill=MUTED)
    d.text((w - 6, h - 11), "today", font=font(9), fill=MUTED, anchor="ra")
    return img


def build_key_images(summary, cols, rows, key_w, key_h, gap=12):
    """Return {key_index: PIL.Image} for a cols x rows deck."""
    t = summary["totals"]
    tiles = {}

    stats = [
        ("today", fmt_money(t["today"]["cost"]), True),
        ("tokens", fmt_tok(t["today"]["in"] + t["today"]["out"]
                           + t["today"]["cw"] + t["today"]["cr"]), False),
        ("output", fmt_tok(t["today"]["out"]), False),
        ("7 days", fmt_money(t["week"]["cost"]), False),
        ("30 days", fmt_money(t["month"]["cost"]), False),
    ]
    for c in range(min(cols, len(stats))):
        label, value, accent = stats[c]
        tiles[c] = stat_tile(key_w, key_h, label, value, accent)

    if rows >= 2:
        days = summary["days"][-(cols * 3):]
        strip_w = cols * key_w + (cols - 1) * gap
        strip = chart_strip(days, strip_w, key_h)
        for c in range(cols):
            x = c * (key_w + gap)
            tiles[cols + c] = strip.crop((x, 0, x + key_w, key_h))

    if rows >= 3:
        models = summary["models"][: cols - 1]
        for c in range(cols - 1):
            if c < len(models):
                m = models[c]
                val = fmt_money(m["cost"]) if m["known_pricing"] \
                    else fmt_tok(m["total"])
                tiles[2 * cols + c] = model_tile(key_w, key_h, m["model"], val)
            else:
                tiles[2 * cols + c] = Image.new("RGB", (key_w, key_h), BG)
        tiles[2 * cols + cols - 1] = refresh_tile(
            key_w, key_h, datetime.now().strftime("%H:%M"))
    return tiles


def preview(tiles, cols, rows, key_w, key_h, path, gap=12, pad=16):
    board = Image.new("RGB", (cols * key_w + (cols - 1) * gap + 2 * pad,
                              rows * key_h + (rows - 1) * gap + 2 * pad),
                      (13, 13, 13))
    for idx, img in tiles.items():
        r, c = divmod(idx, cols)
        board.paste(img, (pad + c * (key_w + gap), pad + r * (key_h + gap)))
    board.save(path)
    print(f"wrote preview to {path}")


def run_device(scanner, interval, brightness):
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.ImageHelpers import PILHelper

    decks = DeviceManager().enumerate()
    if not decks:
        sys.exit("No Stream Deck found. Is the Elgato software still holding "
                 "the device? Close it (or its agent) and retry.")
    deck = decks[0]
    deck.open()
    deck.reset()
    deck.set_brightness(brightness)
    rows, cols = deck.key_layout()
    key_w, key_h = deck.key_image_format()["size"]
    print(f"Connected: {deck.deck_type()} ({cols}x{rows}, {key_w}x{key_h}px keys)")

    refresh_now = {"flag": True}

    def on_key(_deck, _key, pressed):
        if pressed:
            refresh_now["flag"] = True

    deck.set_key_callback(on_key)

    try:
        last = 0.0
        while True:
            if refresh_now["flag"] or time.time() - last >= interval:
                refresh_now["flag"] = False
                last = time.time()
                summary = token_viewer.build_summary(scanner)
                tiles = build_key_images(summary, cols, rows, key_w, key_h)
                with deck:
                    for idx in range(deck.key_count()):
                        img = tiles.get(idx) or Image.new(
                            "RGB", (key_w, key_h), BG)
                        deck.set_key_image(
                            idx, PILHelper.to_native_key_format(deck, img))
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        with deck:
            deck.reset()
            deck.close()


def main():
    ap = argparse.ArgumentParser(
        description="Show Claude token usage on an Elgato Stream Deck")
    ap.add_argument("--interval", type=int, default=60,
                    help="seconds between refreshes (default 60)")
    ap.add_argument("--brightness", type=int, default=60)
    ap.add_argument("--claude-dir", action="append", default=None,
                    help="Claude data dir containing projects/ (repeatable)")
    ap.add_argument("--preview", metavar="PNG",
                    help="render the 5x3 board to a PNG instead of a device")
    args = ap.parse_args()

    dirs = [Path(d).expanduser() for d in args.claude_dir] if args.claude_dir \
        else token_viewer.default_claude_dirs()
    scanner = token_viewer.UsageScanner(dirs)

    if args.preview:
        summary = token_viewer.build_summary(scanner)
        tiles = build_key_images(summary, 5, 3, 72, 72)
        preview(tiles, 5, 3, 72, 72, args.preview)
        return

    run_device(scanner, args.interval, args.brightness)


if __name__ == "__main__":
    main()
