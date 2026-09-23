#!/usr/bin/env python3
"""Henter oddsen på nytt like før avspark, for tallene siden viser.

De vanlige jobbene går på faste klokkeslett og treffer derfor ofte kampen
timer før avspark -- median 6,8 timer i Eliteserien og 7,4 i OBOS. Da er
laguttaket ikke priset inn. Denne jobben går tett i kampvinduet og oppdaterer
<liga>/data/odds_upcoming.json for kampene som starter om 15 til 60 minutter,
med siste pris i det samme vinduet som definerer sluttodds (oddswindow.py).

Den rører ingenting annet: bare radene for kampene som er nær avspark, og
bare når det faktisk finnes en pris i vinduet. Finnes det ikke, står den
gamle raden -- det siden viser før kampen er et levende tall, ikke sluttodds,
og der er en eldre pris bedre enn ingen.

Kallbruk: 0 tellende kall i normal drift. Terminlisten leses fra mellomlager
og markedslisten fra disk; /v4/historical-odds er gratis. Mangler en kamp som
starter snart i terminlisten, hentes lista på nytt -- høyst én gang i døgnet,
styrt av --refresh-max-age.

  python3 scripts/prekick_odds.py eliteserien
  python3 scripts/prekick_odds.py obos --dry-run
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi
import oddslib
import oddswindow
from obos_closing_odds import BOOKMAKERS, COOLDOWN, OBOS_TOURNAMENT, find_1x2, norm

ROOT = Path(__file__).parent.parent
ELITE_TOURNAMENT = 20
SEASON = 2026
TOURNAMENT = {"eliteserien": ELITE_TOURNAMENT, "obos": OBOS_TOURNAMENT}


def paths(liga):
    d = ROOT / liga / "data"
    return {
        "upcoming": d / "odds_upcoming.json",
        "fixtures": d / "oddspapi_fixtures_2026.json",
        "markets": (ROOT / "obos" / "data" / "oddspapi_markets.json"),
        "namemap": (d / "oddspapi_name_map.json" if liga == "eliteserien"
                    else d / "name_map.json"),
    }


def load_name_map(p):
    if not p.exists():
        return {}
    return {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items()
            if not k.startswith("_")}


def fixtures_for(liga, key, max_age_hours, force=False):
    """Terminlisten fra mellomlager. Henter bare når den er for gammel."""
    p = paths(liga)["fixtures"]
    if p.exists() and not force:
        d = json.loads(p.read_text(encoding="utf-8"))
        alder = datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched_at"])
        if alder < timedelta(hours=max_age_hours):
            return d.get("fixtures") or [], False
    print("  terminlisten er for gammel -- henter (1 tellende kall)")
    d, err = oddspapi.call("/v4/fixtures", {"tournamentId": TOURNAMENT[liga],
                                            "from": f"{SEASON}-01-01",
                                            "to": f"{SEASON}-12-31"}, key)
    if err:
        print(f"  FEIL ved terminliste: {err}")
        gammel = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return gammel.get("fixtures") or [], False
    fl = oddspapi.unwrap(d)
    p.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "tournamentId": TOURNAMENT[liga], "fixtures": fl},
                            ensure_ascii=False, indent=1), encoding="utf-8")
    return fl, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("liga", choices=["eliteserien", "obos"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh-max-age", type=float, default=24.0,
                    help="timer før terminlisten hentes på nytt (sikkerhetsventil)")
    args = ap.parse_args()

    P = paths(args.liga)
    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        return 1

    now = datetime.now(timezone.utc)
    fra = now + timedelta(minutes=oddswindow.CLOSE_TO_MIN)
    til = now + timedelta(minutes=oddswindow.CLOSE_FROM_MIN)
    print(f"{args.liga}: kamper med avspark mellom {fra:%H:%M} og {til:%H:%M} UTC")

    if not P["upcoming"].exists():
        print("  ingen odds_upcoming.json -- ingenting å oppdatere")
        return 0
    opp = json.loads(P["upcoming"].read_text(encoding="utf-8"))
    rader = opp.get("matches") or []
    if not rader:
        print("  odds_upcoming.json er tom")
        return 0

    # Hvilke av radene starter i vinduet? Dette avgjøres uten et eneste kall.
    naa_aktuelle = []
    for m in rader:
        ko = oddswindow._parse(m.get("commence_time"))
        if ko and fra <= ko <= til:
            naa_aktuelle.append(m)
    if not naa_aktuelle:
        print("  ingen kamper i vinduet nå. 0 kall.")
        return 0
    print(f"  {len(naa_aktuelle)} kamp(er) i vinduet")

    fixtures, hentet = fixtures_for(args.liga, key, args.refresh_max_age)
    nm = load_name_map(P["namemap"])
    navn = lambda x: nm.get(x, x)
    by_pair = {(norm(navn(f.get("participant1Name"))), norm(navn(f.get("participant2Name")))): f
               for f in fixtures}
    # Sikkerhetsventil: mangler en av kampene i lista, kan den være ny. Hent én
    # gang til -- men bare hvis vi ikke nettopp hentet.
    if not hentet and any((norm(m["home"]), norm(m["away"])) not in by_pair for m in naa_aktuelle):
        fixtures, _ = fixtures_for(args.liga, key, args.refresh_max_age, force=True)
        by_pair = {(norm(navn(f.get("participant1Name"))), norm(navn(f.get("participant2Name")))): f
                   for f in fixtures}

    mkt = find_1x2(json.loads(P["markets"].read_text(encoding="utf-8"))
                   if P["markets"].exists() else None)
    mkt_id = (mkt or {}).get("marketId") or (mkt or {}).get("id")
    if mkt_id is None:
        print("  fant ikke 1X2-markedet -- gjør ingenting")
        return 1

    endret = 0
    for m in naa_aktuelle:
        f = by_pair.get((norm(m["home"]), norm(m["away"])))
        if not f:
            print(f"  {m['home']} mot {m['away']}: ikke i terminlisten -- hoppet over")
            continue
        d, err = oddspapi.call("/v4/historical-odds",
                               {"fixtureId": f.get("fixtureId"),
                                "bookmakers": ",".join(BOOKMAKERS)}, key)
        if err and "RATE_LIMITED" in str(err):
            time.sleep(COOLDOWN)
            d, err = oddspapi.call("/v4/historical-odds",
                                   {"fixtureId": f.get("fixtureId"),
                                    "bookmakers": ",".join(BOOKMAKERS)}, key)
        if err:
            print(f"  {m['home']} mot {m['away']}: FEIL {err}")
            time.sleep(COOLDOWN)
            continue
        # Samme vindu som sluttodds, men taket er NÅ: en pris fra framtiden
        # finnes ikke, og en fra en kamp som pågår skal ikke inn.
        ko = m.get("commence_time")
        gulv, _tak = oddswindow.bounds(ko)
        root = d.get("data", d) if isinstance(d, dict) else {}
        books = root.get("bookmakers") or {}
        naa_iso = now.strftime("%Y-%m-%dT%H:%M:%S.999Z")
        traff = None
        for bm in BOOKMAKERS:
            node = books.get(bm)
            if not isinstance(node, dict):
                continue
            mk = (node.get("markets") or {}).get(str(mkt_id))
            vals, stamp = oddswindow.prices_in_window((mk or {}).get("outcomes"), gulv, naa_iso)
            if vals:
                traff = (bm, vals, stamp)
                break
        if not traff:
            print(f"  {m['home']} mot {m['away']}: ingen pris i vinduet ennå -- lar raden stå")
            time.sleep(COOLDOWN)
            continue
        bm, vals, stamp = traff
        pH, pU, pB = oddslib.devig(*vals)
        fra_f = f"{m.get('H')}/{m.get('D')}/{m.get('A')}"
        m.update({"H": round(pH, 4), "D": round(pU, 4), "A": round(pB, 4),
                  "n_bookmakers": 1, "bookmaker": bm, "priced_at": stamp,
                  "prekick": True,
                  "minutter_for": round(oddswindow.minutter_for(ko, stamp) or 0, 1)})
        endret += 1
        print(f"  {m['home']} mot {m['away']}: {bm}, {m['minutter_for']:.0f} min før avspark. "
              f"{fra_f} -> {m['H']}/{m['D']}/{m['A']}")
        time.sleep(COOLDOWN)

    if endret and not args.dry_run:
        opp["fetched_at"] = now.isoformat(timespec="seconds")
        opp["prekick_at"] = now.isoformat(timespec="seconds")
        P["upcoming"].write_text(json.dumps(opp, ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")
        print(f"\n{endret} rad(er) oppdatert i {P['upcoming'].name}")
    elif endret:
        print(f"\n{endret} rad(er) VILLE blitt oppdatert (--dry-run)")
    else:
        print("\nIngenting endret.")
    used, limit = oddspapi.usage()
    print(f"Tellende kall denne måneden: {used} av {limit}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
