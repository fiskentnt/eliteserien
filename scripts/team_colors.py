#!/usr/bin/env python3
"""Lager de sju fargevariantene hvert lag trenger, fra én draktfarge.

Eliteserien-fargene ble laget for hånd da mørk modus kom. Dette scriptet er
den samme metoden skrevet ned, så OBOS (og senere ligaer) får varianter som
oppfører seg likt, og så alt kan kontrolleres på nytt når som helst.

  fill        draktens hovedfarge, slik den er
  deep        fill gjort mørkere (L x 0,72), til kanter og hover
  fillText    hvit eller nesten sort oppa fill -- den som gir best kontrast
  textLight   fill som SKRIFT mot hvitt panel, mørknet til minst 4,5:1
  textDark    fill som SKRIFT mot mørkt panel (#111c2e), lysnet til minst 4,5:1
  topDark     fill dempet for toppbanneret i mørk modus (L x 0,573, S x 0,722)
  topDeepDark det samme gjort med deep

  python3 scripts/team_colors.py --check          # kontroller dagens farger
  python3 scripts/team_colors.py "#c5111d" ...    # lag varianter for en farge

Kravene, som --check håndhever:
  fillText mot fill            >= 4,5:1
  textLight mot #ffffff        >= 4,5:1
  textDark mot #111c2e         >= 4,5:1
  hvit tekst mot topDark       >= 4,5:1 (banneret bruker alltid hvit i mørk modus)
"""
import argparse
import colorsys
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PANEL_LIGHT = "#ffffff"
PANEL_DARK = "#111c2e"
INK_DARK = "#15191c"
WHITE = "#ffffff"

DEEP_L = 0.72          # deep = fill med denne lysstyrkefaktoren
TOP_L, TOP_S = 0.573, 0.722   # dempingen banneret bruker i mørk modus


def to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


def to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def luminance(h):
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in to_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def scale_hls(h, lf=1.0, sf=1.0):
    r, g, b = to_rgb(h)
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    return to_hex(colorsys.hls_to_rgb(hh, max(0.0, min(1.0, ll * lf)), max(0.0, min(1.0, ss * sf))))


def toward(h, target_l, steps=400):
    """Flytter lysstyrken mot target_l i små steg, med fargetonen i behold."""
    r, g, b = to_rgb(h)
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    out = []
    for i in range(steps + 1):
        l = ll + (target_l - ll) * i / steps
        out.append(to_hex(colorsys.hls_to_rgb(hh, l, ss)))
    return out


def text_against(fill, bg, need=4.5):
    """Draktfargen som skrift mot bg: brukes uendret hvis den holder, ellers
    mørknes (mot hvit bakgrunn) eller lysnes (mot mørk) til den gjør det."""
    if contrast(fill, bg) >= need:
        return fill
    target = 0.0 if luminance(bg) > 0.5 else 1.0
    for c in toward(fill, target):
        if contrast(c, bg) >= need:
            return c
    return to_hex((0, 0, 0)) if target == 0.0 else WHITE


def variants(fill):
    deep = scale_hls(fill, lf=DEEP_L)
    return {
        "fill": fill,
        "deep": deep,
        "fillText": WHITE if contrast(WHITE, fill) >= contrast(INK_DARK, fill) else INK_DARK,
        "textLight": text_against(fill, PANEL_LIGHT),
        "textDark": text_against(fill, PANEL_DARK),
        "topDark": scale_hls(fill, lf=TOP_L, sf=TOP_S),
        "topDeepDark": scale_hls(deep, lf=TOP_L, sf=TOP_S),
    }


def audit(name, v):
    """Returnerer listen over krav som IKKE er oppfylt."""
    feil = []
    c = contrast(v["fillText"], v["fill"])
    if c < 4.5:
        feil.append(f"fillText mot fill {c:.2f}:1")
    c = contrast(v["textLight"], PANEL_LIGHT)
    if c < 4.5:
        feil.append(f"textLight mot lyst panel {c:.2f}:1")
    c = contrast(v["textDark"], PANEL_DARK)
    if c < 4.5:
        feil.append(f"textDark mot mørkt panel {c:.2f}:1")
    c = contrast(WHITE, v["topDark"])
    if c < 4.5:
        feil.append(f"hvit tekst mot topDark {c:.2f}:1")
    return feil


def notes(v):
    """Ting som holder kravet, men er verdt å vite."""
    ut = []
    c = contrast(WHITE, v["topDark"])
    if c < 6.0:
        ut.append(f"hvit tekst mot topDark bare {c:.2f}:1 (kravet er 4,5)")
    return ut


def read_league_colors(path, label):
    """Plukker teamColors ut av en ligafil uten å kjøre JS."""
    s = path.read_text(encoding="utf-8")
    if "teamColors: {" not in s:
        return {}
    i = s.index("teamColors: {")
    j = s.index("\n  },", i)
    out = {}
    for m in re.finditer(r'"([^"]+)":\s*\{([^}]*)\}', s[i:j]):
        fields = dict(re.findall(r'(\w+):"(#[0-9a-fA-F]{6})"', m.group(2)))
        out[m.group(1)] = fields
    return out


def cmd_check():
    kilder = [(ROOT / "eliteserien" / "index.html", "Eliteserien"),
              (ROOT / "obos" / "page" / "league.js", "OBOS-ligaen")]
    bad = 0
    for path, label in kilder:
        if not path.exists():
            continue
        cols = read_league_colors(path, label)
        if not cols:
            print(f"\n{label}: ingen teamColors funnet")
            continue
        print(f"\n{label}: {len(cols)} lag")
        for name, v in sorted(cols.items()):
            feil = audit(name, v)
            # Stemmer variantene med det generatoren ville laget fra fill?
            gen = variants(v["fill"])
            avvik = [k for k in gen if gen[k] != v.get(k)]
            mark = "  " if not feil else "X "
            note = ""
            if avvik:
                note = f"   (håndjustert: {', '.join(avvik)})"
            print(f"  {mark}{name:<16} {v['fill']}{note}")
            for f in feil:
                print(f"      KRAV IKKE OPPFYLT: {f}")
                bad += 1
            for n in notes(v):
                print(f"      merk: {n}")
        # Lag med nesten samme farge: de vises aldri side om side (bare ett lag
        # følges om gangen), men listes så det er et bevisst valg.
        names = sorted(cols)
        nær = []
        for a in range(len(names)):
            for b in range(a + 1, len(names)):
                d = sum((x - y) ** 2 for x, y in
                        zip(to_rgb(cols[names[a]]["fill"]), to_rgb(cols[names[b]]["fill"]))) ** 0.5
                if d < 0.15:
                    nær.append(f"{names[a]} og {names[b]} (avstand {d:.3f})")
        print(f"  nesten like farger: {'; '.join(nær) if nær else 'ingen'}")
    print(f"\n{'ALLE KRAV OPPFYLT' if not bad else str(bad) + ' KRAV IKKE OPPFYLT'}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="kontroller fargene som ligger i ligaene")
    ap.add_argument("--json", action="store_true", help="skriv ut som JS-linjer klare til innliming")
    ap.add_argument("farger", nargs="*", help='"Lagnavn=#rrggbb" eller bare "#rrggbb"')
    args = ap.parse_args()
    if args.check:
        return cmd_check()
    if not args.farger:
        ap.print_help()
        return 1
    for arg in args.farger:
        name, _, hexv = arg.rpartition("=")
        v = variants(hexv if hexv.startswith("#") else "#" + hexv)
        feil = audit(name, v)
        if args.json:
            body = ", ".join(f'{k}:"{v[k]}"' for k in
                             ("fill", "deep", "fillText", "textLight", "textDark", "topDark", "topDeepDark"))
            print(f'    "{name}": {{{body}}},')
        else:
            print(f"{name or hexv}: {json.dumps(v, ensure_ascii=False)}")
        for f in feil:
            print(f"    KRAV IKKE OPPFYLT: {f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
