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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
OSLO = ZoneInfo("Europe/Oslo")

# Ligamappen velges av argumentet, med Eliteserien som standard slik at
# eksisterende kall uten argument oppfører seg som før.
LIGAER = {"eliteserien": ROOT / "eliteserien", "obos": ROOT / "obos"}

# Daglig vedlikehold (football-data.co.uk, revisjonen mot kontrollkilden)
# styres av NAAR DET SIST GIKK BRA, ikke av klokkeslettet.
#
# Den gamle regelen var "time 06, minutt under 10". Den har aldri slaatt til:
# GitHub sine planlagte kjoringer i 06-timen landet paa minutt 33-43 hver
# eneste dag 21.-24. september, og falt dermed utenfor vinduet. Med en
# ekstern utloser hvert tiende minutt blir et smalt klokkeslettvindu enda mer
# tilfeldig -- det avhenger av at en kjoering treffer akkurat da.
DAGLIG_TIMER = 20

# Etter et MISLYKKET forsok maa det gaa minst saa lenge for vi proever igjen.
# Uten denne ville den eksterne utloseren proevd hvert tiende minutt saa
# lenge feilen varer, og brent baade kjoretid og eventuelle API-kall.
DAGLIG_SPERRE_TIMER = 1


def daglig_sti(liga):
    return LIGAER[liga] / "data" / "daglig_state.json"


def les_daglig(liga):
    p = daglig_sti(liga)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tid(x):
    try:
        return datetime.fromisoformat(x) if x else None
    except ValueError:
        return None


def merk_forsok(liga, now):
    """Skrives NAAR porten aapner for daglig vedlikehold, for arbeidet gjores.
    Da teller et forsok som feiler ogsaa, og sperren paa en time gjelder."""
    d = les_daglig(liga)
    d["siste_forsok"] = now.isoformat(timespec="seconds")
    p = daglig_sti(liga)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def merk_ok(liga, now=None):
    """Skrives av update_data.py naar en kjoring er ferdig uten feil."""
    now = now or datetime.now(timezone.utc)
    d = les_daglig(liga)
    d["siste_ok"] = now.isoformat(timespec="seconds")
    p = daglig_sti(liga)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def daglig_forfalt(liga, now):
    """(slipp gjennom?, begrunnelse)"""
    d = les_daglig(liga)
    ok, forsok = _tid(d.get("siste_ok")), _tid(d.get("siste_forsok"))
    if forsok and (now - forsok) < timedelta(hours=DAGLIG_SPERRE_TIMER):
        minutter = (now - forsok).total_seconds() / 60
        return False, (f"daglig vedlikehold forsøkt for {minutter:.0f} min siden, "
                       f"venter minst {DAGLIG_SPERRE_TIMER} time mellom forsøk")
    if ok is None:
        return True, "daglig vedlikehold har aldri kjørt"
    timer = (now - ok).total_seconds() / 3600
    if timer >= DAGLIG_TIMER:
        return True, f"daglig vedlikehold: siste vellykkede kjøring var {timer:.0f} timer siden"
    return False, f"daglig vedlikehold gjort for {timer:.0f} timer siden"


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
    forfalt, hvorfor = daglig_forfalt(liga, now)
    if forfalt:
        merk_forsok(liga, now)
        return True, f"ingen ventende kamper, men {hvorfor}"
    return False, f"ingen kamper har startet for over 105 minutter siden uten resultat ({hvorfor})"


if __name__ == "__main__":
    liga = sys.argv[1] if len(sys.argv) > 1 else "eliteserien"
    ok, reason = should_fetch(liga=liga)
    print(f"[{liga}] {reason}", file=sys.stderr)
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"should_fetch={'true' if ok else 'false'}\n")
    print(f"should_fetch={ok}")
