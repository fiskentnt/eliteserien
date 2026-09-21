#!/usr/bin/env python3
"""Lager delingsbildene (Open Graph / Twitter-kort, 1200 x 630).

  eliteserien/og.png   toppen av Eliteserien-tabellen, regnet ut fra
                       eliteserien/data/matches.json. Kjøres av workflowen etter
                       hver oppdatering av kampdata, så bildet alltid viser
                       dagens tabell.
  og.png               forsiden: navn og ikon (endres ikke av kampdata).

Bruk:
  python3 scripts/make_og.py            # begge
  python3 scripts/make_og.py --league   # bare Eliteserien
  python3 scripts/make_og.py --root     # bare forsiden

Trenger Pillow. Skriftene (Barlow, OFL) ligger i assets/fonts/, så bildene ser
ut som siden og ikke avhenger av hva som er installert på maskinen.
"""
import json
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent.parent
LEAGUE = ROOT / "eliteserien"
FONTS = ROOT / "assets" / "fonts"

W, H = 1200, 630
BG = (10, 18, 32)          # #0a1220
PANEL = (17, 28, 46)       # #111c2e
LINE = (42, 58, 84)        # #2a3a54
INK = (233, 239, 248)      # #e9eff8
MUTED = (147, 163, 186)    # #93a3ba
GREEN = (52, 211, 153)     # #34d399
NAVY = (19, 48, 95)        # #13305f
LIGHT = (232, 240, 252)    # #e8f0fc
RIM = (79, 127, 196)       # #4f7fc4

MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august",
          "september", "oktober", "november", "desember"]


def font(name, size):
    return ImageFont.truetype(str(FONTS / f"{name}.ttf"), size)


def icon(size):
    """Ikonet (samme som favicon.svg), tegnet på et 16-punkts rutenett og
    forstørret med utjevning, med gjennomsiktige hjørner."""
    k = 16
    s = 16 * k * 4  # tegnes i 4 x oppløsning og skaleres ned (jevne kanter)
    u = s / 16
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0.5 * u, 0.5 * u, 15.5 * u, 15.5 * u), radius=3.5 * u,
                        fill=NAVY + (255,), outline=RIM + (150,), width=max(1, int(u)))
    for (x, y, w, color) in [(3, 4, 10, GREEN), (3, 7, 7, LIGHT), (3, 10, 5, LIGHT)]:
        d.rounded_rectangle((x * u, y * u, (x + w) * u, (y + 2) * u), radius=u, fill=color + (255,))
    return im.resize((size, size), Image.LANCZOS)


def text_w(draw, text, fnt):
    return draw.textlength(text, font=fnt)


def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if text_w(draw, trial, fnt) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def standings(matches):
    t = {}
    for m in matches:
        for n in (m["home"], m["away"]):
            t.setdefault(n, {"name": n, "k": 0, "w": 0, "d": 0, "gf": 0, "ga": 0})
        h, a = t[m["home"]], t[m["away"]]
        h["k"] += 1; a["k"] += 1
        h["gf"] += m["hg"]; h["ga"] += m["ag"]; a["gf"] += m["ag"]; a["ga"] += m["hg"]
        if m["hg"] > m["ag"]: h["w"] += 1
        elif m["hg"] < m["ag"]: a["w"] += 1
        else: h["d"] += 1; a["d"] += 1
    rows = list(t.values())
    for r in rows:
        r["pts"] = r["w"] * 3 + r["d"]
        r["gd"] = r["gf"] - r["ga"]
    rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["name"]))
    return rows


def dato_no(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d}. {MONTHS[m - 1]}"


def league_card():
    matches = json.loads((LEAGUE / "data" / "matches.json").read_text(encoding="utf-8"))
    rows = standings(matches)[:8]
    last = max(matches, key=lambda m: (m["date"], m["round"]))
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # Venstre: navn og beskrivelse
    x0 = 56
    d.text((x0, 62), "Eliteserien", font=font("BarlowCondensed-ExtraBold", 104), fill=INK)
    d.text((x0, 168), "2026", font=font("BarlowCondensed-ExtraBold", 104), fill=GREEN)
    sub = font("Barlow-Medium", 31)
    y = 318
    for line in wrap(d, "Tabellkalkulator med sjanse for gull, Europa og nedrykk", sub, 400):
        d.text((x0, y), line, font=sub, fill=MUTED)
        y += 42
    im.paste(icon(52), (x0, 528), icon(52))
    d.text((x0 + 66, 534), "Tabellkalkulator", font=font("BarlowCondensed-Bold", 38), fill=INK)

    # Høyre: toppen av tabellen
    px0, py0, px1, py1 = 500, 44, 1152, 586
    d.rounded_rectangle((px0, py0, px1, py1), radius=22, fill=PANEL, outline=LINE, width=2)
    d.text((px0 + 30, py0 + 24), "Tabell", font=font("BarlowCondensed-ExtraBold", 40), fill=INK)
    etter = f"etter {dato_no(last['date'])}"
    d.text((px0 + 30 + 108, py0 + 36), etter, font=font("Barlow-Medium", 24), fill=MUTED)

    cols = {"k": px1 - 250, "mf": px1 - 150, "p": px1 - 34}
    head_y = py0 + 96
    hf = font("Barlow-SemiBold", 21)
    for key, label in (("k", "K"), ("mf", "MF"), ("p", "P")):
        d.text((cols[key], head_y), label, font=hf, fill=MUTED, anchor="ra")
    d.text((px0 + 92, head_y), "Lag", font=hf, fill=MUTED)
    d.line((px0 + 20, head_y + 34, px1 - 20, head_y + 34), fill=INK, width=2)

    rh = 48  # åtte rader skal ha luft under seg i panelet
    ry = head_y + 44
    tf, nf, pf = font("Barlow-SemiBold", 29), font("BarlowCondensed-Bold", 31), font("BarlowCondensed-ExtraBold", 36)
    for i, r in enumerate(rows):
        top = ry + i * rh
        mid = top + rh // 2
        if i < 4:  # Europa-plassene (1 til 4)
            d.rounded_rectangle((px0 + 20, top + 6, px0 + 25, top + rh - 6), radius=2, fill=GREEN)
        d.text((px0 + 52, mid), str(i + 1), font=nf, fill=GREEN if i < 4 else MUTED, anchor="mm")
        d.text((px0 + 92, mid), r["name"], font=tf, fill=INK, anchor="lm")
        d.text((cols["k"], mid), str(r["k"]), font=nf, fill=MUTED, anchor="rm")
        gd = f"+{r['gd']}" if r["gd"] > 0 else f"−{abs(r['gd'])}" if r["gd"] < 0 else "0"
        d.text((cols["mf"], mid), gd, font=nf, fill=MUTED, anchor="rm")
        d.text((cols["p"], mid), str(r["pts"]), font=pf, fill=INK, anchor="rm")
        if i < len(rows) - 1:
            d.line((px0 + 20, top + rh, px1 - 20, top + rh), fill=LINE, width=1)
    out = LEAGUE / "og.png"
    im.save(out, optimize=True)
    return out


def root_card():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    big = icon(300)
    im.paste(big, (90, 165), big)
    d.text((470, 200), "Tabellkalkulator", font=font("BarlowCondensed-ExtraBold", 100), fill=INK)
    d.text((474, 322), "Sannsynligheter for fotballigaer", font=font("Barlow-Medium", 42), fill=MUTED)
    d.text((474, 392), "Gull, Europa og nedrykk", font=font("Barlow-Medium", 34), fill=GREEN)
    d.text((W - 56, H - 44), "tabellkalkulator.no", font=font("Barlow-SemiBold", 28), fill=MUTED, anchor="rs")
    out = ROOT / "og.png"
    im.save(out, optimize=True)
    return out


if __name__ == "__main__":
    args = set(sys.argv[1:])
    do_league = "--league" in args or not args
    do_root = "--root" in args or not args
    if do_league:
        print("Skrev", league_card())
    if do_root:
        print("Skrev", root_card())
