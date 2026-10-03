#!/usr/bin/env python3
"""Highlightly (soccer.highlightly.net): resultater og terminliste for begge
ligaene, fra én leverandør uavhengig av NTF og fotball.no.

Kartlagt 3.10.2026 (scripts/highlightly_probe.py, workflowen
highlightly-probe.yml): begge sesongene har 240 kamper, med 0 avvik i dato,
tid, runde og resultat mot våre, og de flyttede kampene (Sogndal-Raufoss
21.10., Eliteserien runde 12 24.-25.10.) står riktig. Runden står i kampen
("Regular Season - 24"), så den brukes direkte.

TO REGLER fra kartleggingen:
  * Tidene er UTC (timezone settes ikke) og regnes om til Europe/Oslo her.
  * Sidedelingen (offset) er USTABIL: kamper med samme avspark kom to ganger
    eller manglet (Egersund-Stabæk, Sandefjord-Brann, Vålerenga-Molde). Derfor
      - resultater hentes per dato, ett kall per kampdag (hent_dag), og
      - en hel sesong (hent_sesong) får dublettene fjernet på kamp-id, og det
        som mangler hentes per dato. Er det ikke ANTALL_KAMPER unike kamper
        etterpå, er svaret ufullstendig og kastes (Ufullstendig).

Nøkkelen er HIGHLIGHTLY_API_KEY (GitHub-secret), i headeren x-rapidapi-key.
100 kall i døgnet; vi stopper ved DAGSTAK. Hvert kall telles i
data/highlightly-bruk/<dato>/<kjøring>.json FØR det går ut, og logges i
hentelogget som highlightly-matches.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import hentelogg

BASE = "https://soccer.highlightly.net"
OSLO = ZoneInfo("Europe/Oslo")
ROT = Path(__file__).resolve().parent.parent
ANTALL_KAMPER = 240
DAGSTAK = 60          # av 100 i døgnet hos Highlightly
TIMEOUT = 30

# Ligaenes id hos Highlightly (kartleggingen 3.10.2026).
LIGA_ID = {"eliteserien": 88437, "obos": 89288}

# Lagnavnene hos Highlightly -> våre. Bare navnene som ER ulike; et navn som
# er likt vårt, står ikke her. Et ukjent navn i ligaen stopper hentingen
# (HighlightlyDataError) -- vi gjetter ikke.
NAVN = {
    "obos": {"Haugesund FK": "Haugesund", "Kongsvinger IL": "Kongsvinger", "ODD Ballklubb": "Odd",
             "Sandnes ULF": "Sandnes Ulf", "Strommen": "Strømmen"},
    "eliteserien": {"Kristiansund BK": "Kristiansund", "Rosenborg BK": "Rosenborg", "Tromsø IL": "Tromsø"},
}
LAG = {
    "obos": {"Bryne", "Egersund", "Haugesund", "Hødd", "Kongsvinger", "Lyn", "Moss", "Odd", "Ranheim",
             "Raufoss", "Sandnes Ulf", "Sogndal", "Stabæk", "Strømmen", "Strømsgodset", "Åsane"},
    "eliteserien": {"Aalesund", "Bodø/Glimt", "Brann", "Fredrikstad", "HamKam", "KFUM Oslo", "Kristiansund",
                    "Lillestrøm", "Molde", "Rosenborg", "Sandefjord", "Sarpsborg 08", "Start", "Tromsø",
                    "Viking", "Vålerenga"},
}

BRUK_KATALOG = Path(os.environ.get("HIGHLIGHTLY_BRUK_KATALOG") or ROT / "data" / "highlightly-bruk")


class HighlightlyDataError(Exception):
    """Svaret kan ikke brukes som det er: ukjent lag, uleselig resultat."""


class Ufullstendig(HighlightlyDataError):
    """En hel sesong uten nøyaktig ANTALL_KAMPER unike kamper."""


class Budsjett(Exception):
    """Dagstaket er nådd: vi spør ikke mer i dag."""


def _kjoring_id():
    rid = os.environ.get("GITHUB_RUN_ID")
    if rid:
        return f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f"lokal-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{os.getpid()}"


def dagsbruk(dag=None):
    """Kall i dag (UTC), summert over alle kjøringers filer."""
    dag = dag or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    katalog = BRUK_KATALOG / dag
    n = 0
    if katalog.exists():
        for f in katalog.glob("*.json"):
            try:
                n += json.loads(f.read_text(encoding="utf-8")).get("kall", 0)
            except Exception:
                continue
    return n


def _tell():
    """Teller kallet FØR det går ut: et kall som sendes, men aldri svarer,
    er også brukt."""
    dag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fil = BRUK_KATALOG / dag / f"{_kjoring_id()}.json"
    d = {}
    if fil.exists():
        try:
            d = json.loads(fil.read_text(encoding="utf-8"))
        except Exception:
            d = {}
    d["kall"] = d.get("kall", 0) + 1
    d["last"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fil.parent.mkdir(parents=True, exist_ok=True)
    fil.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _http(sti, param):
    """Ett kall. Byttes ut i testene (lagrede svar)."""
    nokkel = os.environ.get("HIGHLIGHTLY_API_KEY", "").strip()
    if not nokkel:
        raise HighlightlyDataError("HIGHLIGHTLY_API_KEY er ikke satt")
    url = f"{BASE}{sti}?{urllib.parse.urlencode(param)}"
    req = urllib.request.Request(url, headers={"x-rapidapi-key": nokkel, "User-Agent": "tabellkalkulator.no"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def kall(sti, param, liga="alle"):
    """Ett tellende kall, med tak og hentelogg."""
    if dagsbruk() >= DAGSTAK:
        raise Budsjett(f"dagstaket er nådd ({DAGSTAK} kall i dag)")
    _tell()
    try:
        d = _http(sti, param)
    except Exception as e:
        hentelogg.logg(liga, "highlightly-matches", "feil", melding=f"{type(e).__name__}: {e}"[:200])
        raise
    hentelogg.logg(liga, "highlightly-matches", "ok", kamper=len(d.get("data", [])))
    return d


def _lag(navn, liga):
    v = NAVN[liga].get(navn, navn)
    if v not in LAG[liga]:
        raise HighlightlyDataError(f"ukjent lag hos Highlightly ({liga}): {navn!r}")
    return v


RUNDE_RE = re.compile(r"(\d+)\s*$")
RESULTAT_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def parse_kamp(m, liga):
    """Én kamp fra Highlightly -> vår radform, med tiden i norsk tid.
    ferdig bare for "Finished" (ikke etter ekstraomganger/straffer, som ikke
    finnes i serien); da må resultatet kunne leses."""
    t = datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(OSLO)
    r = RUNDE_RE.search(m.get("round") or "")
    st = (m.get("state") or {})
    status = st.get("description") or ""
    ferdig = status == "Finished"
    hg = ag = None
    if ferdig:
        sc = RESULTAT_RE.match(((st.get("score") or {}).get("current")) or "")
        if not sc:
            raise HighlightlyDataError(f"ferdigspilt kamp uten lesbart resultat: {m.get('id')} {st}")
        hg, ag = int(sc.group(1)), int(sc.group(2))
    return {"id": m.get("id"), "date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"),
            "round": int(r.group(1)) if r else None,
            "home": _lag(m["homeTeam"]["name"], liga), "away": _lag(m["awayTeam"]["name"], liga),
            "hg": hg, "ag": ag, "ferdig": ferdig, "status": status}


def _ligaens(rader, liga):
    return [m for m in rader if (m.get("league") or {}).get("id") == LIGA_ID[liga]]


def hent_dag(dato, ligaer=("eliteserien", "obos")):
    """Alle kampene i ligaene én dag (YYYY-MM-DD, norsk tid), ett kall for alle
    norske kamper. {liga: [rad]}. Brukes til resultatene: ingen sidedeling.

    Dagen hos Highlightly er i UTC. En kamp etter midnatt norsk tid er før
    midnatt UTC bare om sommeren mellom 00:00 og 02:00 -- ingen seriekamper
    spilles da, så dato er dato."""
    d = kall("/matches", {"date": dato, "countryName": "Norway", "limit": 100})
    if (d.get("pagination") or {}).get("totalCount", 0) > 100:
        raise HighlightlyDataError(f"over 100 norske kamper {dato}: sidedeling trengs, og den er ustabil")
    rader = d.get("data", [])
    return {liga: [parse_kamp(m, liga) for m in _ligaens(rader, liga)] for liga in ligaer}


def hent_sesong(liga, sesong, kjente_datoer):
    """Hele sesongen for ligaen: sidene med offset, dublettene fjernet på
    kamp-id, og det som mangler hentet per dato.

    kjente_datoer: {(hjemme, borte): dato} fra vår terminliste, så vi vet
    hvilke dager en manglende kamp skal hentes fra. Er det ikke
    ANTALL_KAMPER unike kamper etterpå, kastes Ufullstendig: et halvt svar
    skal ikke brukes."""
    unike, offset = {}, 0
    while True:
        d = kall("/matches", {"leagueId": LIGA_ID[liga], "season": sesong, "limit": 100, "offset": offset}, liga)
        side = d.get("data", [])
        for m in side:
            unike.setdefault(m.get("id"), m)
        total = (d.get("pagination") or {}).get("totalCount", len(side))
        offset += 100
        if not side or offset >= total:
            break
    par = {(_lag(m["homeTeam"]["name"], liga), _lag(m["awayTeam"]["name"], liga)) for m in unike.values()}
    mangler = sorted({kjente_datoer[k] for k in kjente_datoer if k not in par and kjente_datoer[k]})
    for dato in mangler:
        d = kall("/matches", {"date": dato, "countryName": "Norway", "limit": 100}, liga)
        for m in _ligaens(d.get("data", []), liga):
            unike.setdefault(m.get("id"), m)
    rader = [parse_kamp(m, liga) for m in unike.values()]
    nokler = {(r["home"], r["away"]) for r in rader}
    if len(rader) != ANTALL_KAMPER or len(nokler) != ANTALL_KAMPER:
        raise Ufullstendig(f"Highlightly {liga} {sesong}: {len(rader)} unike kamper ({len(nokler)} lagpar) "
                           f"etter {len(mangler)} dager hentet på nytt, ventet {ANTALL_KAMPER}")
    return sorted(rader, key=lambda r: (r["date"], r["time"], r["home"]))
