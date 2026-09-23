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

    todo = [(r, f) for r, f in links if match_id(r) not in ut["matches"]]
    print(f"Sluttodds: {len(ut['matches'])} fra før, {len(todo)} gjenstår "
          f"(henter høyst {args.max} nå)\n")

    done = tomt = fail = 0
    for r, f in todo[:args.max]:
        mid, fid, ko = match_id(r), f.get("fixtureId"), f.get("startTime")
        d, err = oddspapi.call("/v4/historical-odds",
                               {"fixtureId": fid, "bookmakers": ",".join(BOOKMAKERS)}, key)
        if err and "RATE_LIMITED" in str(err):
            time.sleep(COOLDOWN)
            d, err = oddspapi.call("/v4/historical-odds",
                                   {"fixtureId": fid, "bookmakers": ",".join(BOOKMAKERS)}, key)
        if err:
            print(f"  FEIL {mid}: {err}")
            fail += 1
            time.sleep(COOLDOWN)
            continue
        bm, odds, stamp = oddswindow.closing_from(d, mkt_id, ko, BOOKMAKERS)
        rad = {"fixtureId": fid, "start": (ko or "")[:16], "bookmaker": bm,
               "odds": odds, "priced_at": stamp, "result": f"{r['hg']}-{r['ag']}"}
        if bm:
            pH, pU, pB = oddslib.devig(odds["H"], odds["U"], odds["B"])
            rad["H"], rad["U"], rad["B"] = round(pH, 4), round(pU, 4), round(pB, 4)
            rad["minutter_for"] = round(oddswindow.minutter_for(ko, stamp) or 0, 1)
            done += 1
            print(f"  {mid}  {bm}  H {odds['H']}  U {odds['U']}  B {odds['B']}  "
                  f"({rad['minutter_for']:.0f} min før)")
        else:
            rad["uten_sluttodds"] = True
            tomt += 1
            print(f"  {mid}  INGEN sluttodds: ingen pris i vinduet")
        ut["matches"][mid] = rad
        ut["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        OUT_PATH.write_text(json.dumps(ut, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        time.sleep(COOLDOWN)

    med = sum(1 for v in ut["matches"].values() if v.get("bookmaker"))
    print(f"\n{done} hentet nå, {tomt} uten pris i vinduet, {fail} feil.")
    print(f"{med} av {len(ut['matches'])} kamper i filen har sluttodds.")
    used, limit = oddspapi.usage()
    print(f"Tellende kall denne måneden: {used} av {limit}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
