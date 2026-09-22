#!/usr/bin/env python3
"""Kjører OddsPapi og The Odds API side om side for Eliteserien.

Modellen bruker fortsatt The Odds API. Dette skriptet bare SAMLER, så kildene
kan sammenlignes på ekte kamper før vi bestemmer hovedkilde:

  eliteserien/data/odds_sources.json
    én rad per kamp, med Pinnacle, bet365 og The Odds API-snittet hver for seg,
    margin fjernet, og tidspunktet hver av dem ble hentet. Raden fryses når
    kampen er spilt, og resultatet føres på, så log loss kan regnes senere.

Kallbruk: terminlisten hos OddsPapi koster 1 tellende kall og mellomlagres en
time. Oddsoppslagene (/v4/historical-odds) er gratis. The Odds API leses fra
filen fetch_odds_upcoming.py allerede skriver -- ingen ekstra kall der.

  python3 scripts/odds_compare.py            # samle inn
  python3 scripts/odds_compare.py --report   # log loss per kilde, ingen henting
"""
import argparse
import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi
import oddslib

ROOT = Path(__file__).parent.parent
DATA = ROOT / "eliteserien" / "data"
OUT_PATH = DATA / "odds_sources.json"
UPCOMING_PATH = DATA / "odds_upcoming.json"
MATCHES_PATH = DATA / "matches.json"
NAME_MAP_PATH = DATA / "oddspapi_name_map.json"
FIXTURES_CACHE = DATA / "oddspapi_fixtures.json"

ELITE_TOURNAMENT = 20
# Rekkefølgen kildene rangeres i, lik i begge ligaene. The Odds API er reserve
# og finnes bare for Eliteserien.
BOOKMAKERS = ["pinnacle", "bet365", "unibet"]
KILDER = BOOKMAKERS + ["oddsapi"]
COOLDOWN = 4.5
CACHE_MINUTES = 60
SEASON = 2026


def norm(name):
    s = unicodedata.normalize("NFKD", (name or "").lower())
    s = s.replace("ø", "o").replace("æ", "ae").replace("å", "a")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def load_name_map():
    if not NAME_MAP_PATH.exists():
        return {}
    return {k: v for k, v in json.loads(NAME_MAP_PATH.read_text(encoding="utf-8")).items()
            if not k.startswith("_")}


def key_of(home, away):
    """Kamper identifiseres på sesong, hjemmelag og bortelag -- aldri dato."""
    return f"{SEASON}|{home}|{away}"


def fetch_fixtures(key, force=False):
    if FIXTURES_CACHE.exists() and not force:
        d = json.loads(FIXTURES_CACHE.read_text(encoding="utf-8"))
        alder = datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched_at"])
        if alder < timedelta(minutes=CACHE_MINUTES):
            print(f"  terminliste fra mellomlager ({len(d['fixtures'])} kamper, "
                  f"{int(alder.total_seconds()/60)} min gammel)")
            return d["fixtures"]
    now = datetime.now(timezone.utc)
    print("  henter terminlisten fra OddsPapi (1 tellende kall)")
    d, err = oddspapi.call("/v4/fixtures", {
        "tournamentId": ELITE_TOURNAMENT,
        "from": now.date().isoformat(),
        "to": (now + timedelta(days=21)).date().isoformat()}, key)
    if err:
        print(f"  FEIL: {err}")
        return None
    fl = oddspapi.unwrap(d)
    FIXTURES_CACHE.write_text(json.dumps(
        {"fetched_at": now.isoformat(timespec="seconds"), "fixtures": fl},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return fl


def alle_bookmakere(payload, market_id, kickoff=None):
    """Sluttodds per bookmaker, ikke bare den best rangerte: {bm: (H,U,B,tid)}.

    Samme struktur som scripts/obos_closing_odds.py leser, men her beholdes
    ALLE, siden hele poenget er å sammenligne dem.
    """
    root = payload.get("data", payload) if isinstance(payload, dict) else {}
    books = root.get("bookmakers") or {}
    ut = {}
    for bm in BOOKMAKERS:
        node = books.get(bm)
        if not isinstance(node, dict):
            continue
        m = (node.get("markets") or {}).get(str(market_id))
        outcomes = (m or {}).get("outcomes") or {}
        if len(outcomes) != 3:
            continue
        vals, stamp = [], None
        for oid in sorted(outcomes, key=lambda x: str(x)):
            players = (outcomes[oid] or {}).get("players") or {}
            entries = []
            for plist in players.values():
                if isinstance(plist, list):
                    entries.extend(plist)
            entries = [e for e in entries if isinstance(e, dict) and e.get("price")]
            if kickoff:
                entries = [e for e in entries if (e.get("createdAt") or "") <= kickoff]
            if not entries:
                vals = []
                break
            last = max(entries, key=lambda e: e.get("createdAt") or "")
            vals.append(float(last["price"]))
            stamp = max(stamp or "", last.get("createdAt") or "")
        if len(vals) == 3:
            ut[bm] = (vals[0], vals[1], vals[2], stamp)
    return ut


def les_ut():
    if OUT_PATH.exists():
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "matches": {}}


def skriv_ut(d):
    d["note"] = ("Kildene side om side for hver kamp, med margin fjernet. Modellen bruker "
                 "fortsatt The Odds API; denne filen finnes for å sammenligne dem. "
                 "Raden fryses når kampen er spilt.")
    d["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def logloss(p, utfall):
    import math
    return -math.log(max(p[utfall], 1e-9))


def rapport(d):
    """Log loss per kilde, på kampene der kilden faktisk hadde odds."""
    import math
    spilte = [(k, v) for k, v in d["matches"].items() if v.get("resultat")]
    if not spilte:
        print("Ingen spilte kamper med lagrede odds ennå.")
        return 0
    print(f"{len(spilte)} spilte kamper med lagrede odds\n")
    print(f"{'kilde':<12} {'kamper':>7} {'log loss':>10} {'traff':>8}")
    tall = {}
    for kilde in KILDER:
        rader = [(k, v) for k, v in spilte if v["kilder"].get(kilde)]
        if not rader:
            print(f"{kilde:<12} {0:>7}          -        -")
            continue
        ll, hit = 0.0, 0
        for _, v in rader:
            p = v["kilder"][kilde]
            u = v["resultat"]["utfall"]
            ll += logloss(p, u)
            hit += 1 if max("HUB", key=lambda x: p[x]) == u else 0
        tall[kilde] = [v["kilder"][kilde] for _, v in rader], rader
        print(f"{kilde:<12} {len(rader):>7} {ll/len(rader):>10.4f} {hit/len(rader)*100:>7.1f} %")

    # Parvis, på kampene BEGGE kildene har: det er den eneste rettferdige
    # sammenligningen, og standardfeilen sier om forskjellen er reell.
    print("\nParvis, bare kamper begge kildene har:")
    for a in KILDER:
        for b in KILDER:
            if a >= b:
                continue
            felles = [v for _, v in spilte if v["kilder"].get(a) and v["kilder"].get(b)]
            if len(felles) < 2:
                continue
            d_ = [logloss(v["kilder"][a], v["resultat"]["utfall"])
                  - logloss(v["kilder"][b], v["resultat"]["utfall"]) for v in felles]
            md = sum(d_) / len(d_)
            sd = math.sqrt(sum((x - md) ** 2 for x in d_) / (len(d_) - 1))
            se = sd / math.sqrt(len(d_))
            bedre = b if md > 0 else a
            print(f"  {a} mot {b}: {md:+.4f} ± {se:.4f} på {len(felles)} kamper "
                  f"({abs(md/se) if se > 1e-12 else 0:.1f} SE, {bedre} best) "
                  f"-- {'reell' if se > 1e-12 and abs(md/se) > 2 else 'innenfor støyen'}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="bare rapport, ingen henting")
    ap.add_argument("--refresh", action="store_true", help="se bort fra mellomlageret")
    args = ap.parse_args()

    d = les_ut()
    d.setdefault("matches", {})

    # Resultater inn på kampene som er spilt, og raden fryses.
    if MATCHES_PATH.exists():
        for m in json.loads(MATCHES_PATH.read_text(encoding="utf-8")):
            k = key_of(m["home"], m["away"])
            if k in d["matches"] and not d["matches"][k].get("resultat"):
                u = "H" if m["hg"] > m["ag"] else ("U" if m["hg"] == m["ag"] else "B")
                d["matches"][k]["resultat"] = {"hg": m["hg"], "ag": m["ag"], "utfall": u}
                d["matches"][k]["frosset"] = True

    if args.report:
        skriv_ut(d)
        return rapport(d)

    # The Odds API: leses fra filen som alt hentes, ingen nye kall.
    n_api = 0
    if UPCOMING_PATH.exists():
        up = json.loads(UPCOMING_PATH.read_text(encoding="utf-8"))
        for m in up.get("matches", []):
            if m.get("H") is None:
                continue
            k = key_of(m["home"], m["away"])
            rad = d["matches"].setdefault(k, {"home": m["home"], "away": m["away"], "kilder": {}})
            if rad.get("frosset"):
                continue
            rad["kilder"]["oddsapi"] = {"H": m["H"], "U": m["D"], "B": m["A"],
                                        "n_bookmakers": m.get("n_bookmakers"),
                                        "hentet": up.get("fetched_at")}
            n_api += 1
    print(f"The Odds API: {n_api} kamper fra {UPCOMING_PATH.name}")

    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt -- lagrer bare The Odds API denne gangen.")
        skriv_ut(d)
        return 0

    fixtures = fetch_fixtures(key, force=args.refresh)
    if fixtures is None:
        skriv_ut(d)
        return 1
    nm = load_name_map()
    navn = lambda x: nm.get(x, x)
    spilte_keys = set()
    if MATCHES_PATH.exists():
        spilte_keys = {key_of(m["home"], m["away"])
                       for m in json.loads(MATCHES_PATH.read_text(encoding="utf-8"))}

    markets, err = oddspapi.call("/v4/markets", {"sportId": 10}, key)
    mkt_id = None
    if not err:
        for m in oddspapi.unwrap(markets):
            if "full time result" in (m.get("marketName") or m.get("name") or "").lower():
                mkt_id = m.get("marketId") or m.get("id")
                break
    if mkt_id is None:
        print("  fant ikke 1X2-markedet")
        skriv_ut(d)
        return 1

    ukjente = set()
    n_op = 0
    for f in fixtures:
        h, a = navn(f.get("participant1Name")), navn(f.get("participant2Name"))
        k = key_of(h, a)
        if k in spilte_keys and d["matches"].get(k, {}).get("frosset"):
            continue
        if norm(h) == norm(f.get("participant1Name") or "") and h not in nm.values():
            ukjente.add(f.get("participant1Name"))
        o, err = oddspapi.call("/v4/historical-odds",
                               {"fixtureId": f.get("fixtureId"), "bookmakers": ",".join(BOOKMAKERS)}, key)
        if err:
            print(f"  {h} mot {a}: FEIL {err}")
            time.sleep(COOLDOWN)
            continue
        bms = alle_bookmakere(o or {}, mkt_id, kickoff=None)
        rad = d["matches"].setdefault(k, {"home": h, "away": a, "kilder": {}})
        rad.setdefault("kickoff", (f.get("startTime") or "")[:19])
        for bm, (H, U, B, stamp) in bms.items():
            pH, pU, pB = oddslib.devig(H, U, B)
            rad["kilder"][bm] = {"H": round(pH, 4), "U": round(pU, 4), "B": round(pB, 4),
                                 "desimal": {"H": H, "U": U, "B": B}, "hentet": stamp}
        if bms:
            n_op += 1
        print(f"  {h} mot {a}: {', '.join(bms) if bms else 'ingen av de tre'}")
        time.sleep(COOLDOWN)

    if ukjente:
        print(f"  UKJENTE LAGNAVN (legg dem i {NAME_MAP_PATH.name}): {sorted(ukjente)}")
    skriv_ut(d)
    used, limit = oddspapi.usage()
    print(f"\n{n_op} kamper med OddsPapi-odds, {len(d['matches'])} kamper i filen.")
    print(f"OddsPapi-forbruk denne måneden: {used} av {limit} tellende kall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
