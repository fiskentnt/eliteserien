#!/usr/bin/env python3
"""Port for prekick-odds: er det en kamp i sluttoddsvinduet nå?

Sluttodds er siste gyldige pris mellom 60 og 15 minutter før avspark (se
oddswindow.py). Vinduet er 45 minutter langt, og GitHub sin egen cron har
vist forsinkelser på flere timer -- den kan derfor ikke brukes til å treffe
det. Den eksterne planleggeren kaller hvert tiende minutt i stedet, og denne
porten avgjør om det faktisk er noe å gjøre.

Leser bare terminlisten fra disk. Ingen nettverkskall, ingen avhengigheter
utover standardbiblioteket, og ingenting som teller mot OddsPapi-kvoten.

Marginen: vi åpner porten litt før vinduet og lar den stå litt etter, slik at
en kjøring som blir forsinket noen minutter fortsatt rekker innenfor.

Bruk:  python3 scripts/prekick_vindu.py [liga ...]
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
OSLO = ZoneInfo("Europe/Oslo")
LIGAER = {"eliteserien": ROOT / "eliteserien", "obos": ROOT / "obos"}

FRA_MIN = 60 + 10   # åpne 70 minutter før avspark
TIL_MIN = 15 - 5    # og hold åpen til 10 minutter før


def kamper_i_vinduet(liga, naa):
    sti = LIGAER[liga] / "data" / "fixtures.json"
    if not sti.exists():
        return []
    try:
        fx = json.loads(sti.read_text(encoding="utf-8"))
    except Exception:
        return []
    ut = []
    for runde in fx:
        for m in runde.get("matches", []):
            if m.get("played") or not m.get("date") or not m.get("time"):
                continue
            try:
                avspark = datetime.fromisoformat(
                    f"{m['date']}T{m['time']}:00").replace(tzinfo=OSLO)
            except ValueError:
                continue
            minutter = (avspark - naa).total_seconds() / 60
            if TIL_MIN <= minutter <= FRA_MIN:
                ut.append((m["home"], m["away"], minutter))
    return ut


def main(argv):
    if os.environ.get("FORCE_FETCH") == "true":
        grunn = "manuelt trigget (workflow_dispatch uten planlagt=true)"
        traff = True
    else:
        naa = datetime.now(timezone.utc)
        ligaer = argv or list(LIGAER)
        alle = [(liga, *k) for liga in ligaer for k in kamper_i_vinduet(liga, naa)]
        traff = bool(alle)
        if traff:
            grunn = "; ".join(f"{liga}: {h} - {b} om {m:.0f} min" for liga, h, b, m in alle)
        else:
            grunn = f"ingen kamp mellom {TIL_MIN} og {FRA_MIN} minutter før avspark"

    print(grunn, file=sys.stderr)
    ut = os.environ.get("GITHUB_OUTPUT")
    if ut:
        with open(ut, "a", encoding="utf-8") as f:
            f.write(f"should_fetch={'true' if traff else 'false'}\n")
    print(f"should_fetch={traff}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
