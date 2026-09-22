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


# Settes øverst i den genererte filen, rett etter <!DOCTYPE html>, så ingen
# redigerer den i den tro at endringen overlever neste bygg.
BANNER = """<!--
  GENERERT FIL -- IKKE REDIGER.

  Bygget av scripts/build_league.py fra eliteserien/index.html, som er kilden
  til all sidekode. Alt som skiller ligaene ligger i {dir}/page/ og byttes inn
  i merkede regioner. Endrer du noe her, blir det borte neste gang noen kjører
  bygget.

  Endre i stedet:
    eliteserien/index.html  -- felles kode, markup og CSS
    {dir}/page/league.js  -- soner, farger, merker og ord for denne ligaen
    {dir}/page/*.html  -- head, tittel og forklaringstekstene

  Bygg på nytt med:   python3 scripts/build_league.py {dir}
  tests/failsafe.py feiler hvis denne filen ikke er bygget fra dagens kilde.
-->
"""


def render(league):
    """Bygger siden og returnerer innholdet, uten å skrive noe."""
    src = SRC.read_text(encoding="utf-8")
    page_dir = ROOT / league / "page"
    out = src
    for start, end, fname in REGIONS:
        f = page_dir / fname
        if not f.exists():
            raise FileNotFoundError(f.relative_to(ROOT))
        i = out.index(start)
        j = out.index(end, i) + len(end)
        out = out[:i] + f.read_text(encoding="utf-8").rstrip("\n") + out[j:]
    doctype = "<!DOCTYPE html>\n"
    if out.startswith(doctype):
        out = doctype + BANNER.format(dir=league) + out[len(doctype):]
    return out


def build(league, check=False):
    try:
        out = render(league)
    except FileNotFoundError as e:
        print(f"  mangler {e}", file=sys.stderr)
        return 1
    dest = ROOT / league / "index.html"
    if check:
        # Brukes av tests/failsafe.py og av workflowen: er den innsjekkede
        # filen bygget fra dagens kilde?
        have = dest.read_text(encoding="utf-8") if dest.exists() else None
        if have == out:
            print(f"{dest.relative_to(ROOT)} er bygget fra dagens kilde.")
            return 0
        print(f"{dest.relative_to(ROOT)} er IKKE bygget fra dagens kilde.\n"
              f"  Kjør: python3 scripts/build_league.py {league}", file=sys.stderr)
        return 1
    dest.write_text(out, encoding="utf-8")
    print(f"Skrev {dest.relative_to(ROOT)} ({len(out)} tegn)")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    sys.exit(build(args[0] if args else "obos", check="--check" in sys.argv))
