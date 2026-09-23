#!/usr/bin/env python3
"""Sluttodds for spilte Eliteserien-kamper, fra OddsPapi, etter vindusregelen.

Sluttodds er siste observasjon 60 til 15 minutter før avspark -- se
scripts/oddswindow.py for hvorfor. Skriver eliteserien/data/odds_closing.json,
som scripts/merge_odds.py legger øverst i odds.json, over football-data.co.uk.

Hvorfor i det hele tatt, når football-data.co.uk alt gir sluttodds:
football-datas tall er et snitt over mange bookmakere, hentet en gang etter
kampen, uten tidsstempel. Vi kan ikke se HVOR sent de er satt, og kan derfor
ikke stå inne for at laguttaket er priset inn. Vinduet kan vi gjøre rede for,
kamp for kamp, med minuttet det ble satt. Der vinduet er tomt, faller kampen
tilbake på football-data -- det er bedre enn ingen odds, og kilden står i
filen.

Kallbruk: terminlisten og markedslisten leses fra mellomlager (0 tellende
kall), og /v4/historical-odds er gratis.

  python3 scripts/elite_closing_odds.py
  python3 scripts/elite_closing_odds.py --max 50 --refresh-fixtures
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi
import oddslib
import oddswindow
from obos_closing_odds import BOOKMAKERS, COOLDOWN, find_1x2, match_fixtures

ROOT = Path(__file__).parent.parent
DATA = ROOT / "eliteserien" / "data"
OUT_PATH = DATA / "odds_closing.json"
FIXTURES_CACHE = DATA / "oddspapi_fixtures_2026.json"
MARKETS_CACHE = DATA / "oddspapi_markets.json"
NAME_MAP_PATH = DATA / "oddspapi_name_map.json"
MATCHES_PATH = DATA / "matches.json"

ELITE_TOURNAMENT = 20
SEASON = 2026


def load_name_map():
    if not NAME_MAP_PATH.exists():
        return {}
    return {k: v for k, v in json.loads(NAME_MAP_PATH.read_text(encoding="utf-8")).items()
            if not k.startswith("_")}


def fetch_fixtures(key, refresh=False):
    """Sesongens terminliste. Fra mellomlager når den finnes: 0 tellende kall."""
    if FIXTURES_CACHE.exists() and not refresh:
        d = json.loads(FIXTURES_CACHE.read_text(encoding="utf-8"))
        fl = d.get("fixtures") or []
        print(f"  terminliste fra mellomlager: {len(fl)} kamper (0 tellende kall)")
        return fl
    print("  henter sesongens terminliste (1 tellende kall)")
    d, err = oddspapi.call("/v4/fixtures", {"tournamentId": ELITE_TOURNAMENT,
                                            "from": f"{SEASON}-01-01",
                                            "to": f"{SEASON}-12-31"}, key)
    if err:
        print(f"  FEIL: {err}")
        return None
    fl = oddspapi.unwrap(d)
    FIXTURES_CACHE.write_text(json.dumps(
        {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "tournamentId": ELITE_TOURNAMENT, "fixtures": fl},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return fl


def fetch_markets(key):
    """Markedslisten. Mellomlagres på disk, så den koster 1 kall én gang."""
    if MARKETS_CACHE.exists():
        return json.loads(MARKETS_CACHE.read_text(encoding="utf-8"))
    print("  henter markedslisten (1 tellende kall, mellomlagres)")
    d, err = oddspapi.call("/v4/markets", {"sportId": 10}, key)
    if err:
        print(f"  FEIL ved markedsliste: {err}")
        return None
    MARKETS_CACHE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def match_id(r):
    return f"{SEASON}|{r['home']}|{r['away']}"


def main(argv=None):
    """argv=[] når skriptet kalles fra update_data.py: da skal det IKKE lese
    kommandolinjen til den som kalte."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=400)
    ap.add_argument("--refresh-fixtures", action="store_true")
    args = ap.parse_args(argv)

    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        return 1

    rows = [m for m in json.loads(MATCHES_PATH.read_text(encoding="utf-8"))
            if m.get("hg") is not None]
    fixtures = fetch_fixtures(key, args.refresh_fixtures)
    if fixtures is None:
        return 1
    links, only_odds, only_csv = match_fixtures(rows, fixtures, load_name_map())
    print(f"{len(rows)} spilte kamper, {len(links)} koblet til OddsPapi")
    for x in only_csv[:10]:
        print(f"  ikke hos OddsPapi: {x}")

    mkt = find_1x2(fetch_markets(key))
    mkt_id = (mkt or {}).get("marketId") or (mkt or {}).get("id")
    if mkt_id is None:
        print("fant ikke 1X2-markedet")
        return 1

    definisjon = (f"siste observasjon {oddswindow.CLOSE_FROM_MIN} til "
                  f"{oddswindow.CLOSE_TO_MIN} minutter før avspark")
    ut = {"version": 1, "source": "OddsPapi /v4/historical-odds",
          "note": ("Sluttodds er " + definisjon + ". Kamper uten observasjon i "
                   "vinduet står med bookmaker null -- de har INGEN sluttodds, og "
                   "faller tilbake på football-data.co.uk i merge_odds.py. "
                   "Utfallene er hjemme, uavgjort, borte."),
          "definisjon": definisjon, "market": mkt_id,
          "bookmakers": BOOKMAKERS, "matches": {}}
    if OUT_PATH.exists():
        gammel = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        if gammel.get("definisjon") == definisjon:
            ut = gammel
            ut.setdefault("matches", {})
        else:
            print(f"  definisjonen er endret -- henter alle på nytt (gratis)")

    # OddsPapi har flere oppføringer for samme kamp: 176 fixtures for 168
    # spilte kamper i denne sesongen. Uten gruppering skrev den siste over den
    # første, og en tom oppføring kunne slette en ferdig sluttodds. Nå samles
    # de per kamp, og vi prøver oppføringene til én gir pris i vinduet.
    per_kamp = {}
    for r, f in links:
        per_kamp.setdefault(match_id(r), (r, []))[1].append(f)

    def maa_hentes(mid):
        rad = ut["matches"].get(mid)
        if rad is None:
            return True
        if rad.get("bookmaker"):
            return False              # ferdig
        # En kamp uten pris i vinduet er et endelig svar, ikke en feil.
        if rad.get("uten_sluttodds"):
            return False
        # Feil kan være forbigående, men ikke i det uendelige.
        return rad.get("forsok", 0) < 3

    todo = [mid for mid in per_kamp if maa_hentes(mid)]
    print(f"Sluttodds: {len(ut['matches'])} fra før, {len(todo)} gjenstår "
          f"(henter høyst {args.max} nå)\n")

    done = tomt = fail = 0
    for mid in todo[:args.max]:
        r, fs = per_kamp[mid]
        truffet, siste_feil = None, None
        for f in fs:
            fid, ko = f.get("fixtureId"), f.get("startTime")
            d, err = oddspapi.call_retry("/v4/historical-odds",
                                         {"fixtureId": fid, "bookmakers": ",".join(BOOKMAKERS)}, key)
            time.sleep(COOLDOWN)
            if err:
                siste_feil = str(err)[:120]
                continue
            bm, odds, stamp = oddswindow.closing_from(d, mkt_id, ko, BOOKMAKERS)
            if bm:
                truffet = (f, bm, odds, stamp)
                break
            siste_feil = None          # svar uten pris i vinduet er ikke en feil

        if truffet:
            f, bm, odds, stamp = truffet
            ko = f.get("startTime")
            pH, pU, pB = oddslib.devig(odds["H"], odds["U"], odds["B"])
            ut["matches"][mid] = {
                "fixtureId": f.get("fixtureId"), "start": (ko or "")[:16], "bookmaker": bm,
                "odds": odds, "priced_at": stamp, "result": f"{r['hg']}-{r['ag']}",
                "H": round(pH, 4), "U": round(pU, 4), "B": round(pB, 4),
                "minutter_for": round(oddswindow.minutter_for(ko, stamp) or 0, 1)}
            done += 1
            print(f"  {mid}  {bm}  H {odds['H']}  U {odds['U']}  B {odds['B']}  "
                  f"({ut['matches'][mid]['minutter_for']:.0f} min før)")
        elif siste_feil:
            rad = ut["matches"].get(mid) or {"start": (fs[0].get("startTime") or "")[:16],
                                             "result": f"{r['hg']}-{r['ag']}"}
            rad.update({"bookmaker": None, "odds": None,
                        "feil": siste_feil, "forsok": rad.get("forsok", 0) + 1})
            ut["matches"][mid] = rad
            fail += 1
            print(f"  {mid}  FEIL (forsøk {rad['forsok']} av 3): {siste_feil}")
        else:
            ut["matches"][mid] = {
                "fixtureId": fs[0].get("fixtureId"),
                "start": (fs[0].get("startTime") or "")[:16], "bookmaker": None, "odds": None,
                "result": f"{r['hg']}-{r['ag']}", "uten_sluttodds": True}
            tomt += 1
            print(f"  {mid}  INGEN sluttodds: ingen pris i vinduet")
        ut["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        OUT_PATH.write_text(json.dumps(ut, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    med = sum(1 for v in ut["matches"].values() if v.get("bookmaker"))
    print(f"\n{done} hentet nå, {tomt} uten pris i vinduet, {fail} feil.")
    print(f"{med} av {len(ut['matches'])} kamper i filen har sluttodds.")
    used, limit = oddspapi.usage()
    print(f"Tellende kall denne måneden: {used} av {limit}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
