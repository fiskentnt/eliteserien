#!/usr/bin/env python3
"""Lager de statiske delene av sidene fra <liga>/data/tekster.json (20.10.2026).

Chrome henter, Python lager sidene: scripts/lag_grunnlag.js skriver
tekster.json fra siden selv med den ferdige grunnlagsfilen (tabellen slik siden
viser den, overskriftene for sjansene, når det ble regnet). Dette skriptet
skriver ut fra den, uten Chrome og uten å regne noe:

  <liga>/index.html  regionene STATISK-KOLONNER, STATISK-TABELL og
                     STATISK-OPPDATERT (scripts/statisk_region.py): tabellen
                     med tall og sjanser i HTML-en, for søkemotorer og uten
                     JavaScript; render() på siden tar over

Kjøres av grunnlag-workflowen etter lag_grunnlag.js, og alt committes sammen.

  python3 scripts/lag_sider.py [liga ...]          skriv (standard: begge)
  python3 scripts/lag_sider.py --check [liga ...]  er sidene laget fra filen?
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from statisk_region import med_statiske, statiske  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIGAER = ("eliteserien", "obos")
MAANEDER = ("januar", "februar", "mars", "april", "mai", "juni", "juli", "august",
            "september", "oktober", "november", "desember")


def norsk_tid(iso):
    """'2026-10-20T02:42:09Z' -> '20. oktober 2026 kl. 04.42' (norsk tid)."""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Oslo"))
    return f"{t.day}. {MAANEDER[t.month - 1]} {t.year} kl. {t.hour:02d}.{t.minute:02d}"


def tall(n):
    """100000 -> '100 000' med hardt mellomrom, som på siden."""
    return f"{n:,}".replace(",", " ")


def liste(ord_):
    return ord_[0] if len(ord_) == 1 else ", ".join(ord_[:-1]) + " og " + ord_[-1]


def les(liga, root=ROOT):
    return json.loads((root / liga / "data" / "tekster.json").read_text(encoding="utf-8"))


def oppdatert(t):
    navn = [k["navn"][0].lower() + k["navn"][1:] for k in t["tabell"]["kolonner"]]
    return (f"Oppdatert {norsk_tid(t['laget'])}. Sjansene for {liste(navn)} er regnet fra "
            f"{tall(t['sesonger'])} simulerte sesonger.")


def ligaside(liga, root=ROOT):
    """Ligasiden med de statiske regionene fra tekster.json."""
    side = (root / liga / "index.html").read_text(encoding="utf-8")
    t = les(liga, root)
    return med_statiske(side, {**statiske(side),
                               "KOLONNER": t["tabell"]["kolonner_html"],
                               "TABELL": t["tabell"]["rader_html"],
                               "OPPDATERT": oppdatert(t)})


def main(argv):
    sjekk = "--check" in argv
    ligaer = [a for a in argv if not a.startswith("-")] or list(LIGAER)
    feil = 0
    for liga in ligaer:
        fil = ROOT / liga / "index.html"
        ny, gml = ligaside(liga), fil.read_text(encoding="utf-8")
        if sjekk:
            if ny == gml:
                print(f"{liga}/index.html er laget fra {liga}/data/tekster.json.")
            else:
                print(f"{liga}/index.html er IKKE laget fra {liga}/data/tekster.json.\n"
                      f"  Kjør: python3 scripts/lag_sider.py {liga}", file=sys.stderr)
                feil = 1
        elif ny != gml:
            fil.write_text(ny, encoding="utf-8")
            print(f"Skrev {liga}/index.html fra tekster.json.")
        else:
            print(f"{liga}/index.html var uendret.")
    return feil


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
