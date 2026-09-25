#!/usr/bin/env python3
"""Avgjør om en tung kjøring (pip install, scraping, tellende API-kall) skal
kjøre i det hele tatt. Brukes av update-data.yml (Eliteserien) og
obos-results.yml (OBOS, der hvert kall mot OddsPapi teller mot en kvote på
250 i måneden). Leser bare data/fixtures.json fra den allerede
sjekket-ut repoen (ingen nettverkskall, ingen avhengigheter utover
standardbiblioteket) — kjøres som eget, raskt steg FØR pip install, slik at
de aller fleste av døgnets 96 kvarter-kjøringer kan avslutte umiddelbart.

Kjører videre hvis:
  - en kamp startet for over 105 minutter siden uten registrert resultat, og
    det er under 6 timer siden avspark (normal, hvert-kvarter-kadens), ELLER
  - alle ventende kamper er over 6 timer gamle, men vi er i den første
    kvarter-slotten etter en time (fanger dem opp uten å hamre hvert kvarter
    på en kamp som bare henger, se update_data.py sin log), ELLER
  - klokka er rundt 06 norsk tid (den daglige football-data.co.uk-sjekken,
    se fetch_odds_history.py — den trenger et vertskap selv på stille dager
    uten kamper), ELLER
  - FORCE_FETCH=true (manuell workflow_dispatch skal alltid kjøre).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
OSLO = ZoneInfo("Europe/Oslo")

# Ligamappen velges av argumentet, med Eliteserien som standard slik at
# eksisterende kall uten argument oppfører seg som før.
LIGAER = {"eliteserien": ROOT / "eliteserien", "obos": ROOT / "obos"}


def kickoff_utc(date_str, time_str):
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=OSLO).astimezone(timezone.utc)


def pending_elapsed_minutes(fixtures, now):
    out = []
    for r in fixtures:
        for m in r["matches"]:
            if m["played"] or not m.get("time"):
                continue
            elapsed = (now - kickoff_utc(m["date"], m["time"])).total_seconds() / 60
            if elapsed > 105:
                out.append(elapsed)
    return out


def should_fetch(now=None, liga="eliteserien"):
    if os.environ.get("FORCE_FETCH") == "true":
        return True, "manuelt trigget (workflow_dispatch uten planlagt=true)"
    now = now or datetime.now(timezone.utc)
    oslo_hour = now.astimezone(OSLO).hour

    path = LIGAER[liga] / "data" / "fixtures.json"
    if not path.exists():
        return True, "data/fixtures.json finnes ikke ennå"
    fixtures = json.loads(path.read_text(encoding="utf-8"))
    pending = pending_elapsed_minutes(fixtures, now)

    if pending and min(pending) <= 360:
        return True, f"{len(pending)} kamp(er) venter på resultat, ferskeste startet {min(pending):.0f} min siden"
    if pending:  # alle over 6 timer -- bare i time-slotten (kvarteret nærmest hel time)
        if now.minute < 10:
            return True, f"{len(pending)} kamp(er) over 6 timer uten resultat ('venter på resultat'), prøver i timeslotten"
        return False, f"{len(pending)} kamp(er) over 6 timer uten resultat, venter til neste timeslott"
    if oslo_hour == 6 and now.minute < 10:  # bare første slott i 06-timen
        return True, "ingen ventende kamper, men innenfor den daglige 06-sjekken (football-data.co.uk + ffk-revisjon)"
    return False, "ingen kamper har startet for over 105 minutter siden uten resultat"


if __name__ == "__main__":
    liga = sys.argv[1] if len(sys.argv) > 1 else "eliteserien"
    ok, reason = should_fetch(liga=liga)
    print(f"[{liga}] {reason}", file=sys.stderr)
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"should_fetch={'true' if ok else 'false'}\n")
    print(f"should_fetch={ok}")
