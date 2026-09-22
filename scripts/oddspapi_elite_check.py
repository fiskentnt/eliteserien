#!/usr/bin/env python3
"""Har OddsPapi kommende Eliteserien-kamper, og hvilke bookmakere har odds?

Bruker ETT tellende kall (/v4/fixtures for Eliteserien i en dato-luke) og
deretter gratis oppslag (/v4/historical-odds) for å se hvem som faktisk har
priser på de kommende kampene. Svarer på om OddsPapi kan brukes som kilde for
Eliteserien ved siden av The Odds API.

  python3 scripts/oddspapi_elite_check.py --from 2026-10-01 --to 2026-10-15
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi

ELITE_TOURNAMENT = 20
BOOKMAKERS = ["pinnacle", "bet365", "unibet"]
COOLDOWN = 4.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default="2026-10-01")
    ap.add_argument("--to", dest="to", default="2026-10-15")
    ap.add_argument("--max", type=int, default=8, help="høyst så mange kamper å prøve odds for")
    args = ap.parse_args()

    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        return 1

    print(f"Kommende Eliteserien-kamper hos OddsPapi, {args.frm} til {args.to} (1 tellende kall)")
    d, err = oddspapi.call("/v4/fixtures", {"tournamentId": ELITE_TOURNAMENT,
                                            "from": args.frm, "to": args.to}, key)
    if err:
        print(f"FEIL: {err}")
        return 1
    fx = oddspapi.unwrap(d)
    print(f"  {len(fx)} kamper\n")
    for f in fx:
        print(f"  {(f.get('startTime') or '')[:16]}  {f.get('participant1Name')} mot "
              f"{f.get('participant2Name')}  status={f.get('statusName')}  "
              f"hasOdds={f.get('hasOdds')}  id={f.get('fixtureId')}")

    # Markedet: samme 1X2-marked som OBOS bruker.
    markets, err = oddspapi.call("/v4/markets", {"sportId": 10}, key)
    mkt_id = None
    if not err:
        for m in oddspapi.unwrap(markets):
            name = (m.get("marketName") or m.get("name") or "").lower()
            if "full time result" in name:
                mkt_id = m.get("marketId") or m.get("id")
                break
    print(f"\n1X2-marked: {mkt_id}")

    print(f"\nHvem har priser? (gratis oppslag, høyst {args.max} kamper)")
    treff = {}
    for f in fx[:args.max]:
        fid = f.get("fixtureId")
        o, err = oddspapi.call("/v4/historical-odds",
                               {"fixtureId": fid, "bookmakers": ",".join(BOOKMAKERS)}, key)
        navn = f"{f.get('participant1Name')} mot {f.get('participant2Name')}"
        if err:
            print(f"  {navn}: FEIL {err}")
            time.sleep(COOLDOWN)
            continue
        root = o.get("data", o) if isinstance(o, dict) else {}
        books = root.get("bookmakers") or {}
        har = []
        for bm in BOOKMAKERS:
            node = books.get(bm) or {}
            mkts = (node.get("markets") or {})
            if str(mkt_id) in mkts and len((mkts[str(mkt_id)] or {}).get("outcomes") or {}) == 3:
                har.append(bm)
                treff[bm] = treff.get(bm, 0) + 1
        print(f"  {navn}: {', '.join(har) if har else 'ingen av de tre'}")
        time.sleep(COOLDOWN)

    print(f"\nOppsummert: {treff if treff else 'ingen bookmakere hadde 1X2 på de kommende kampene'}")
    used, limit = oddspapi.usage()
    print(f"OddsPapi-forbruk denne måneden: {used} av {limit} tellende kall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
