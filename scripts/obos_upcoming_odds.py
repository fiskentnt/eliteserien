#!/usr/bin/env python3
"""Odds for kommende OBOS-kamper, fra OddsPapi, til obos/data/odds_upcoming.json.

Siden blander disse oddsene inn per kamp (samme mekanikk som Eliteserien, se
ODDS_W i index.html). Filen har samme form som eliteserien/data/odds_upcoming.json,
så sidekoden er felles.

Kilderekkefølge: Pinnacle, ellers bet365, ellers Unibet. ALDRI et snitt av
flere bookmakere -- én kilde per kamp, og hvilken står i filen.

Kallbruk: terminlisten (/v4/fixtures) koster 1 tellende kall og mellomlagres
en time; oddsoppslagene (/v4/historical-odds) er gratis. Spilte kamper ryddes
ut ved hver kjøring, også når hentingen feiler.

  python3 scripts/obos_upcoming_odds.py
  python3 scripts/obos_upcoming_odds.py --days 14
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
from obos_closing_odds import (BOOKMAKERS, OBOS_TOURNAMENT, closing_from, fetch_markets,
                               find_1x2, load_name_map, match_fixtures, csv_2026)

ROOT = Path(__file__).parent.parent
DATA = ROOT / "obos" / "data"
OUT_PATH = DATA / "odds_upcoming.json"
UPCOMING_CACHE = DATA / "oddspapi_upcoming_fixtures.json"
CACHE_MINUTES = 60
COOLDOWN = 4.5


def fetch_upcoming_fixtures(key, frm, to, force=False):
    """Kommende kamper hos OddsPapi. 1 tellende kall, mellomlagret en time, så
    en tettere kjøreplan ikke spiser kvoten."""
    if UPCOMING_CACHE.exists() and not force:
        d = json.loads(UPCOMING_CACHE.read_text(encoding="utf-8"))
        alder = datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched_at"])
        if alder < timedelta(minutes=CACHE_MINUTES) and d.get("from") == frm and d.get("to") == to:
            print(f"  terminliste fra mellomlager ({len(d['fixtures'])} kamper, "
                  f"{int(alder.total_seconds()/60)} min gammel)")
            return d["fixtures"]
    print("  henter kommende kamper fra OddsPapi (1 tellende kall)")
    d, err = oddspapi.call("/v4/fixtures", {"tournamentId": OBOS_TOURNAMENT,
                                            "from": frm, "to": to}, key)
    if err and "FIXTURE_NOT_FOUND" in str(err):
        # Ingen kamper i vinduet er et gyldig svar (landskampspause), ikke en feil.
        print("  ingen OBOS-kamper i vinduet")
        d = {"data": []}
    elif err:
        print(f"  FEIL: {err}")
        return None
    fl = oddspapi.unwrap(d)
    DATA.mkdir(parents=True, exist_ok=True)
    UPCOMING_CACHE.write_text(json.dumps(
        {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "from": frm, "to": to, "fixtures": fl}, ensure_ascii=False, indent=1), encoding="utf-8")
    return fl


def les_gammel():
    if OUT_PATH.exists():
        try:
            return json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"matches": [], "fetched_at": None}


def uten_spilte(d, played):
    """Spilte kamper hører ikke hjemme i "kommende". Kamper kjennes på lagene,
    aldri på datoen -- en flyttet kamp er den samme kampen."""
    beholdt = [m for m in d.get("matches", []) if (m["home"], m["away"]) not in played]
    return beholdt, len(d.get("matches", [])) - len(beholdt)


def skriv(matches, fetched_at):
    DATA.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"fetched_at": fetched_at, "matches": matches},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14, help="hvor langt fram vi henter (to uker: OBOS har ofte ti dager mellom rundene)")
    ap.add_argument("--refresh", action="store_true", help="se bort fra mellomlageret")
    args = ap.parse_args()

    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    rows = csv_2026()
    played = {(m["home"], m["away"]) for m in rows if m["hg"] is not None}
    gammel = les_gammel()

    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        beholdt, fjernet = uten_spilte(gammel, played)
        if fjernet:
            print(f"  ryddet likevel ut {fjernet} spilte kamper")
            skriv(beholdt, gammel.get("fetched_at"))
        return 1

    now = datetime.now(timezone.utc)
    frm, to = now.date().isoformat(), (now + timedelta(days=args.days)).date().isoformat()
    print(f"Kommende OBOS-kamper {frm} til {to}")
    fixtures = fetch_upcoming_fixtures(key, frm, to, force=args.refresh)
    if fixtures is None:
        beholdt, fjernet = uten_spilte(gammel, played)
        if fjernet:
            print(f"  hentingen feilet, men ryddet ut {fjernet} spilte kamper")
            skriv(beholdt, gammel.get("fetched_at"))
        return 1

    links, only_odds, only_csv = match_fixtures(rows, fixtures, load_name_map())
    kommende = [(r, f) for r, f in links if (r["home"], r["away"]) not in played]
    print(f"  {len(fixtures)} kamper hos OddsPapi, {len(kommende)} uspilte og koblet til terminlisten")
    for x in only_odds:
        print(f"  BARE HOS ODDSPAPI: {x}")

    mkt = find_1x2(fetch_markets(key))
    mkt_id = (mkt or {}).get("marketId") or (mkt or {}).get("id")
    if mkt_id is None:
        print("  fant ikke 1X2-markedet -- henter ingen odds")
        return 1

    ut = []
    for r, f in kommende:
        bm, odds, stamp = closing_from(oddspapi.call(
            "/v4/historical-odds",
            {"fixtureId": f.get("fixtureId"), "bookmakers": ",".join(BOOKMAKERS)}, key)[0] or {},
            market_id=mkt_id, kickoff=None)
        if not bm:
            print(f"  {r['home']} mot {r['away']}: ingen odds fra {', '.join(BOOKMAKERS)}")
            time.sleep(COOLDOWN)
            continue
        # Margin fjernet, så tallene er sannsynligheter og kan blandes med modellen.
        H, D, A = oddslib.devig(odds["H"], odds["U"], odds["B"])
        ut.append({
            "home": r["home"], "away": r["away"],
            "commence_time": (f.get("startTime") or "")[:19] + "Z",
            "H": round(H, 4), "D": round(D, 4), "A": round(A, 4),
            # Én kilde per kamp, aldri et snitt. n_bookmakers=1 er det siden viser.
            "n_bookmakers": 1, "bookmaker": bm, "priced_at": stamp,
        })
        print(f"  {r['home']} mot {r['away']}: {bm}  {H:.0%}/{D:.0%}/{A:.0%}")
        time.sleep(COOLDOWN)

    # Ikke bytt gode data mot tomme: er svaret tomt mens vi fortsatt har odds
    # for uspilte kamper, beholdes de (men spilte ryddes ut uansett).
    beholdt, fjernet = uten_spilte(gammel, played)
    if fjernet:
        print(f"  ryddet ut {fjernet} spilte kamper fra forrige kjøring")
    if not ut and beholdt:
        print("  0 kamper med odds nå -- beholder de forrige for uspilte kamper")
        skriv(beholdt, gammel.get("fetched_at"))
        return 0

    skriv(ut, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    used, limit = oddspapi.usage()
    print(f"\nSkrev {len(ut)} kommende kamper med odds til {OUT_PATH.relative_to(ROOT)}")
    print(f"  OddsPapi-forbruk denne måneden: {used} av {limit} tellende kall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
