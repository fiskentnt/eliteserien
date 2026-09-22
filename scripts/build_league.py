#!/usr/bin/env python3
"""Bygger en ligaside fra eliteserien/index.html, som er kilden til koden.

Bare fire felt er ligaspesifikke, og de er merket med kommentarer i kilden:
  LIGAINNSTILLINGER   (JS-blokken med soner, farger, merker og ord)
  LIGA-HEAD           (<title>, meta, JSON-LD -- må være statisk for søk)
  LIGA-TITTEL         (overskriften på siden)
  LIGA-OM             ("Om siden"-teksten)

Alt annet kopieres ordrett, så de to sidene deler kode. tests/regression.js
sjekker at den delte delen er identisk.

  python3 scripts/build_league.py obos
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "eliteserien" / "index.html"

REGIONS = [
    ("// ==== LIGAINNSTILLINGER", "// ==== SLUTT PÅ LIGAINNSTILLINGER ===========================================", "league.js"),
    ("<!-- LIGA-HEAD", "<!-- /LIGA-HEAD -->", "head.html"),
    ("<!-- LIGA-TITTEL -->", "<!-- /LIGA-TITTEL -->", "tittel.html"),
    ("<!-- LIGA-OM", "<!-- /LIGA-OM -->", "om.html"),
    ("<!-- LIGA-SLIK -->", "<!-- /LIGA-SLIK -->", "slik.html"),
    ("<!-- LIGA-MODELLSJEKK -->", "<!-- /LIGA-MODELLSJEKK -->", "modellsjekk.html"),
]


def build(league):
    src = SRC.read_text(encoding="utf-8")
    page_dir = ROOT / league / "page"
    out = src
    for start, end, fname in REGIONS:
        f = page_dir / fname
        if not f.exists():
            print(f"  mangler {f.relative_to(ROOT)}", file=sys.stderr)
            return 1
        i = out.index(start)
        j = out.index(end, i) + len(end)
        out = out[:i] + f.read_text(encoding="utf-8").rstrip("\n") + out[j:]
    dest = ROOT / league / "index.html"
    dest.write_text(out, encoding="utf-8")
    print(f"Skrev {dest.relative_to(ROOT)} ({len(out)} tegn)")
    return 0


if __name__ == "__main__":
    sys.exit(build(sys.argv[1] if len(sys.argv) > 1 else "obos"))
