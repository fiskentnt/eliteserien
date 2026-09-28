#!/usr/bin/env python3
"""Avgjør om update-odds.yml skal kjøre The Odds API-hentingen. Kjøres FØR
pip install (ingen avhengigheter utover standardbiblioteket).

Kjører videre hvis ALT dette holder:
  - det finnes minst én uspilt kamp i data/fixtures.json innen 7 dager (ellers
    er det ingen vits i å bruke kreditter i en landskampspause),
  - vi ikke har stanset kvoten for denne måneden (se data/odds_quota.json,
    skrevet av fetch_odds_upcoming.py når x-requests-remaining < 100),
  - forrige forsøk ikke feilet for under en time siden (SPERRE_TIMER),
  - det ikke er hentet i dag (norsk tid), ELLER en kamp starter om 15-60
    minutter og det ikke er hentet i det vinduet -- TIDSPORTEN under,
med mindre FORCE_FETCH=true (manuell workflow_dispatch uten planlagt=true).

TIDSPORTEN: én vellykket henting per døgn, og på kampdager i tillegg
SLUTTODDSEN. Den eksterne planleggeren (planlegger/worker.js) starter
workflowen hvert tiende minutt i 09-21 UTC, og GitHub sin egen cron (08:13 og
16:13 UTC) er reserve; porten slipper gjennom
  - den første kjøringen hver dag (norsk tid) som finner at det ikke er
    hentet ennå, og
  - én kjøring i vinduet 60-15 minutter før hvert avspark (samme vindu som
    prekick-odds.yml). Den siste oddsen hentet FØR avspark blir kampens
    sluttodds i odds_captured.json (reserve for kalibreringen, se
    fetch_odds_upcoming.py); uten denne hentingen ville den vært fra
    morgenen. Avspark som ligger tett, dekkes av samme henting.
Hvert kall koster én kreditt (regions=eu, markets=h2h); gratisnivået er 500 i
måneden. BUDSJETTVAKTEN: ligger gjenstående kreditter (fra samme måned) under
100 + 4 per dag som er igjen av måneden, hentes det bare annenhver dag, og
ikke sluttodds.

Tidspunktet for siste vellykkede henting er checked_at i odds_quota.json
(skrives bare når API-et har svart). Siste forsøk skrives til
data/odds_hentestatus.json i det porten åpner, før arbeidet gjøres; er det
nyere enn siste vellykkede, feilet forsøket (eller pågår).
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
LEAGUE = ROOT / "eliteserien"  # ligamappen (data/ ligger under den, så flere ligaer kan komme ved siden av)
QUOTA_PATH = LEAGUE / "data" / "odds_quota.json"
FIXTURES_PATH = LEAGUE / "data" / "fixtures.json"
STATUS_PATH = LEAGUE / "data" / "odds_hentestatus.json"
OSLO = ZoneInfo("Europe/Oslo")

HORISONT_DAGER = 7
SLUTT_FRA_MIN, SLUTT_TIL_MIN = 60, 15   # sluttoddsvinduet før avspark
SPERRE_TIMER = 1
BUDSJETT_DAGER = 2        # under budsjettvakten: høyst annenhver dag
KVOTE_GULV = 100          # samme som QUOTA_FLOOR i fetch_odds_upcoming.py
KVOTE_PER_DAG = 4


def _tid(s):
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def avspark_utc(dato, tid):
    """Avspark i UTC fra terminlistens dato og klokkeslett (norsk tid).
    Mangler klokkeslettet, regnes 00:00 norsk tid: heller for tidlig enn for
    sent, som i frysregelen for prognosene."""
    naiv = datetime.strptime(f"{dato} {tid or '00:00'}", "%Y-%m-%d %H:%M")
    return naiv.replace(tzinfo=OSLO).astimezone(timezone.utc)


def sluttvindu(now, fixtures):
    """Tidligste uspilte avspark K der now ligger i [K-60 min, K-15 min), eller None."""
    ks = [avspark_utc(m["date"], m.get("time")) for r in fixtures for m in r["matches"] if not m.get("played")]
    ks = [k for k in ks if k - timedelta(minutes=SLUTT_FRA_MIN) <= now < k - timedelta(minutes=SLUTT_TIL_MIN)]
    return min(ks) if ks else None


def dag_oslo(t):
    """Kalenderdagen i norsk tid for et UTC-tidspunkt."""
    return t.astimezone(OSLO).date()


def vurder(now, fixtures, quota, status, force=False):
    """Selve avgjørelsen, uten filer (testes i tests/failsafe.py).
    Returnerer (ok, grunn)."""
    if force:
        return True, "manuelt trigget (workflow_dispatch)"
    quota = quota or {}
    status = status or {}
    if quota.get("stopped_until_month") == now.strftime("%Y-%m"):
        return False, (f"kvoten ble lav denne måneden ({quota.get('remaining')} igjen "
                       f"{quota.get('checked_at')}), venter til neste måned")
    if fixtures is None:
        return True, "data/fixtures.json finnes ikke ennå"
    horisont = (now + timedelta(days=HORISONT_DAGER)).strftime("%Y-%m-%d")
    innen = [m for r in fixtures for m in r["matches"] if not m.get("played") and m["date"] <= horisont]
    if not innen:
        return False, f"ingen uspilte kamper de neste {HORISONT_DAGER} dagene -- sparer kreditter"

    # Tidsporten: én henting per døgn (norsk tid); under budsjettvakten
    # annenhver dag. Budsjettvakten: bare gjenstående fra SAMME måned teller
    # (kvoten fornyes månedlig, og et lavt tall fra forrige måned sier
    # ingenting om denne).
    dager = 1
    grunn_int = "én henting per døgn"
    sjekket = _tid(quota.get("checked_at"))
    igjen_kred = quota.get("remaining")
    if igjen_kred is not None and sjekket and sjekket.strftime("%Y-%m") == now.strftime("%Y-%m"):
        neste_mnd = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
        dager_igjen = (neste_mnd.date() - now.date()).days
        krav = KVOTE_GULV + KVOTE_PER_DAG * dager_igjen
        if igjen_kred < krav:
            dager = BUDSJETT_DAGER
            grunn_int = (f"budsjettvakten: {igjen_kred} kreditter igjen, under {krav} "
                         f"({dager_igjen} dager igjen), derfor bare annenhver dag")

    forsok = _tid(status.get("siste_forsok"))
    if forsok and (sjekket is None or forsok > sjekket) and now - forsok < timedelta(hours=SPERRE_TIMER):
        return False, (f"forrige forsøk ({forsok.isoformat(timespec='minutes')}) ga ingen vellykket henting; "
                       f"venter minst {SPERRE_TIMER} time mellom forsøk")
    # Sluttodds: en kamp starter om 15-60 minutter, og siste henting er fra
    # før vinduet åpnet. Ikke under budsjettvakten.
    k = sluttvindu(now, fixtures)
    if k and dager == 1 and (sjekket is None or sjekket < k - timedelta(minutes=SLUTT_FRA_MIN)):
        return True, f"sluttodds før avspark {k.astimezone(OSLO).strftime('%d.%m %H:%M')} norsk tid"
    if sjekket and (dag_oslo(now) - dag_oslo(sjekket)).days < dager:
        return False, f"hentet {sjekket.astimezone(OSLO).strftime('%d.%m %H:%M')} norsk tid; {grunn_int}"
    return True, f"{len(innen)} uspilt(e) kamp(er) innen {HORISONT_DAGER} dager; {grunn_int}"


def _les(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def should_fetch_odds(now=None):
    now = now or datetime.now(timezone.utc)
    return vurder(now, _les(FIXTURES_PATH), _les(QUOTA_PATH), _les(STATUS_PATH),
                  force=os.environ.get("FORCE_FETCH") == "true")


def merk_forsok(now):
    """Skrives i det porten åpner, FØR hentingen. Committes av workflowen
    også når hentingen feiler, så sperren virker på tvers av kjøringer."""
    STATUS_PATH.write_text(json.dumps({"siste_forsok": now.isoformat(timespec="seconds")}, indent=1) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    ok, reason = should_fetch_odds(now)
    print(reason, file=sys.stderr)
    if ok:
        merk_forsok(now)
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"should_fetch={'true' if ok else 'false'}\n")
    print(f"should_fetch={ok}")
