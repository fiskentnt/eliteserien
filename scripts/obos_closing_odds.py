#!/usr/bin/env python3
"""Henter sluttodds for OBOS-ligaen 2026 fra OddsPapi, én kamp per kall.

Kallbruk: /v4/historical-odds er GRATIS og teller ikke mot kvoten. Bare
oppslaget av terminlisten (/v4/fixtures) teller, og det gjøres én gang og
mellomlagres, så gjentatte kjøringer koster 0 tellende kall.

Bookmakere: pinnacle, bet365 og unibet i samme kall (API-et tillater maks tre).
Pinnacle brukes når den finnes, ellers bet365, ellers unibet.

Lagring underveis: hver ferdige kamp skrives til obos/data/odds_closing.json,
så en avbrutt kjøring fortsetter der den slapp. Kamper som alt er hentet,
hoppes over.

  python3 scripts/obos_closing_odds.py            # alle spilte kamper
  python3 scripts/obos_closing_odds.py --max 50   # høyst 50 denne kjøringen
  python3 scripts/obos_closing_odds.py --report    # bare navnesjekk, ingen odds

Nøkkel: ODDSPAPI_KEY som miljøvariabel (secret i workflowen).
"""
import argparse
import csv
import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi

ROOT = Path(__file__).parent.parent
DATA = ROOT / "obos" / "data"
CSV_PATH = DATA / "obos_2012-2026.csv"
FIXTURES_CACHE = DATA / "oddspapi_fixtures_2026.json"
OUT_PATH = DATA / "odds_closing.json"
NAME_MAP_PATH = DATA / "name_map.json"

OBOS_TOURNAMENT = 22          # "1st Division", menn -- 19272 er kvinneligaen
BOOKMAKERS = ["pinnacle", "bet365", "unibet"]
COOLDOWN = 4.5                # /v4/historical-odds har rundt 4 sekunders avkjøling
TIMEOUT = 45


def norm(name):
    """Sammenligningsform for lagnavn: uten aksenter, små bokstaver, uten
    vanlige klubbord. «Strømsgodset IF» og «Stromsgodset» blir like."""
    s = unicodedata.normalize("NFKD", (name or "").lower())
    s = s.replace("ø", "o").replace("æ", "ae").replace("å", "a")
    s = "".join(c for c in s if not unicodedata.combining(c))
    for w in (" fotball", " fotballklubb", " toppfotball", " fk", " if", " il", " ik",
              " sk", " bk", " ff", " fc", " 2", " ii"):
        if s.endswith(w):
            s = s[: -len(w)]
    return " ".join(s.split())


def load_name_map():
    if NAME_MAP_PATH.exists():
        return json.loads(NAME_MAP_PATH.read_text(encoding="utf-8"))
    return {}


def get(path, params, key, timeout=TIMEOUT):
    """Går gjennom felles klient, som teller kallene (se scripts/oddspapi.py)."""
    return oddspapi.call(path, params, key, timeout=timeout)


unwrap = oddspapi.unwrap


def csv_2026():
    rows = []
    for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")):
        if r["sesong"] != "2026":
            continue
        rows.append({
            "round": int(r["runde"]), "date": r["dato"], "time": r["tid"],
            "home": r["hjemme"], "away": r["borte"],
            "hg": int(float(r["hjemmemaal"])) if r["hjemmemaal"] else None,
            "ag": int(float(r["bortemaal"])) if r["bortemaal"] else None,
        })
    return rows


def fetch_fixtures(key, force=False):
    """Terminlisten hos OddsPapi for hele 2026: 1 tellende kall, mellomlagret."""
    if FIXTURES_CACHE.exists() and not force:
        d = json.loads(FIXTURES_CACHE.read_text(encoding="utf-8"))
        print(f"  terminliste fra mellomlager ({len(d['fixtures'])} kamper, hentet {d['fetched_at']})")
        return d["fixtures"]
    print("  henter terminlisten fra OddsPapi (1 tellende kall)")
    d, err = get("/v4/fixtures", {"tournamentId": OBOS_TOURNAMENT,
                                  "from": "2026-01-01", "to": "2026-12-31"}, key)
    if err:
        print(f"  FEIL: {err}")
        return None
    fl = unwrap(d)
    DATA.mkdir(parents=True, exist_ok=True)
    FIXTURES_CACHE.write_text(json.dumps(
        {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "tournamentId": OBOS_TOURNAMENT, "fixtures": fl}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {len(fl)} kamper, lagret i {FIXTURES_CACHE.relative_to(ROOT)}")
    return fl


def match_fixtures(rows, fixtures, name_map):
    """Kobler OddsPapi-kamper til terminlisten på lagnavn. Returnerer
    (koblinger, kamper bare hos OddsPapi, kamper bare i terminlisten)."""
    def key_of(h, a):
        return (norm(name_map.get(h, h)), norm(name_map.get(a, a)))

    by_pair = {}
    for r in rows:
        by_pair.setdefault(key_of(r["home"], r["away"]), []).append(r)
    links, only_odds = [], []
    used = set()
    for f in fixtures:
        h, a = f.get("participant1Name"), f.get("participant2Name")
        k = key_of(h, a)
        cands = by_pair.get(k) or []
        # Samme lagpar møtes to ganger i sesongen, men aldri med samme hjemmelag
        # mer enn én gang, så lagparet i riktig retning er unikt.
        cand = cands[0] if cands else None
        if cand is None:
            only_odds.append(f"{h} mot {a} ({(f.get('startTime') or '')[:10]})")
            continue
        links.append((cand, f))
        used.add(id(cand))
    only_csv = [f"{r['home']} mot {r['away']} ({r['date']})" for r in rows if id(r) not in used]
    return links, only_odds, only_csv


def closing_from(payload):
    """Plukker sluttoddsen: siste pris per utfall, fra den best rangerte
    bookmakeren som har odds (pinnacle, så bet365, så unibet). Returnerer
    (bookmaker, {H,U,B}, tidspunkt) eller (None, None, None)."""
    raw = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw, dict):
        return None, None, None
    for bm in BOOKMAKERS:
        node = raw.get(bm)
        if not node:
            continue
        # Struktur: bookmaker -> marked -> utfall -> liste av priser med createdAt.
        best = {}
        stamp = None
        for market, outcomes in (node.items() if isinstance(node, dict) else []):
            if not isinstance(outcomes, dict):
                continue
            # 1X2-markedet kan hete ulike ting; ta det som har tre utfall der
            # navnene ser ut som hjemme/uavgjort/borte.
            names = {k.lower(): k for k in outcomes}
            trio = None
            for h, d, a in (("1", "x", "2"), ("home", "draw", "away")):
                if h in names and d in names and a in names:
                    trio = (names[h], names[d], names[a])
                    break
            if not trio:
                continue
            vals = []
            for key in trio:
                entries = outcomes[key]
                if isinstance(entries, dict):
                    entries = entries.get("prices") or entries.get("history") or []
                if not isinstance(entries, list) or not entries:
                    vals = []
                    break
                last = sorted(entries, key=lambda e: e.get("createdAt") or "")[-1]
                price = last.get("price")
                if price in (None, 0):
                    vals = []
                    break
                vals.append(float(price))
                stamp = max(stamp or "", last.get("createdAt") or "")
            if len(vals) == 3:
                best = {"H": vals[0], "U": vals[1], "B": vals[2]}
                break
        if best:
            return bm, best, stamp
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=250, help="høyst så mange kamper denne kjøringen")
    ap.add_argument("--report", action="store_true", help="bare navnesjekk, hent ingen odds")
    ap.add_argument("--refresh-fixtures", action="store_true", help="hent terminlisten på nytt (1 tellende kall)")
    args = ap.parse_args()

    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        return 1

    rows = csv_2026()
    played = [r for r in rows if r["hg"] is not None]
    print(f"Terminliste: {len(rows)} kamper i 2026, {len(played)} spilte")

    fixtures = fetch_fixtures(key, force=args.refresh_fixtures)
    if fixtures is None:
        return 1

    name_map = load_name_map()
    links, only_odds, only_csv = match_fixtures(rows, fixtures, name_map)
    print(f"\nNavnesjekk: {len(links)} av {len(fixtures)} oddskamper koblet til terminlisten")
    if only_odds:
        print(f"  BARE HOS ODDSPAPI ({len(only_odds)}):")
        for x in only_odds[:20]:
            print(f"    {x}")
    if only_csv:
        print(f"  BARE I TERMINLISTEN ({len(only_csv)}):")
        for x in only_csv[:20]:
            print(f"    {x}")
    if not only_odds and not only_csv:
        print("  alle kamper stemmer på begge sider")
    op_names = sorted({f.get("participant1Name") for f in fixtures} | {f.get("participant2Name") for f in fixtures})
    print(f"  lagnavn hos OddsPapi: {[n for n in op_names if n]}")

    # Kampflytting: oddssvaret har tidspunktet, terminlisten kan være utdatert.
    moved = []
    for r, f in links:
        st = f.get("startTime") or ""
        if len(st) < 16:
            continue
        d, t = st[:10], st[11:16]
        if d != r["date"] or t != r["time"]:
            moved.append(f"{r['home']} mot {r['away']}: {r['date']} {r['time']} -> {d} {t}")
    print(f"\nFlyttede kamper i oddssvaret: {len(moved)}")
    for m in moved[:20]:
        print(f"    {m}")

    if args.report:
        return 0

    out = {"version": 1, "source": "OddsPapi /v4/historical-odds",
           "bookmakers": BOOKMAKERS, "matches": {}}
    if OUT_PATH.exists():
        out = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        out.setdefault("matches", {})
    have = set(out["matches"])
    todo = [(r, f) for r, f in links if r["hg"] is not None
            and f"{r['date']}|{r['home']}|{r['away']}" not in have]
    print(f"\nSluttodds: {len(have)} hentet før, {len(todo)} gjenstår "
          f"(henter høyst {args.max} nå)")

    done = fail = 0
    for r, f in todo[:args.max]:
        mid = f"{r['date']}|{r['home']}|{r['away']}"
        fid = f.get("fixtureId")
        d, err = get("/v4/historical-odds", {"fixtureId": fid, "bookmakers": ",".join(BOOKMAKERS)}, key)
        if err:
            print(f"  FEIL {mid}: {err}")
            fail += 1
            if "RATE_LIMITED" in str(err) or "429" in str(err):
                time.sleep(COOLDOWN * 2)
            else:
                time.sleep(COOLDOWN)
            continue
        bm, odds, stamp = closing_from(d)
        out["matches"][mid] = {
            "fixtureId": fid, "round": r["round"], "start": (f.get("startTime") or "")[:16],
            "bookmaker": bm, "odds": odds, "priced_at": stamp,
            "result": f"{r['hg']}-{r['ag']}",
        }
        if bm:
            done += 1
            print(f"  {mid}  {bm}  H {odds['H']}  U {odds['U']}  B {odds['B']}")
        else:
            print(f"  {mid}  ingen odds fra {', '.join(BOOKMAKERS)}"
                  f"{' (svar: ' + json.dumps(d, ensure_ascii=False)[:160] + ')' if done + fail == 0 else ''}")
        # Lagre etter hver kamp, så en avbrutt kjøring kan fortsette.
        out["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        time.sleep(COOLDOWN)

    used, limit = oddspapi.usage()
    print(f"\n  OddsPapi-forbruk denne måneden: {used} av {limit} tellende kall")
    withodds = sum(1 for v in out["matches"].values() if v.get("bookmaker"))
    bms = {}
    for v in out["matches"].values():
        if v.get("bookmaker"):
            bms[v["bookmaker"]] = bms.get(v["bookmaker"], 0) + 1
    print(f"\nFerdig: {len(out['matches'])} kamper i filen, {withodds} med odds, {fail} feil")
    print(f"  per bookmaker: {bms}")
    print(f"  fil: {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
