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
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi
import oddswindow

ROOT = Path(__file__).parent.parent
DATA = ROOT / "obos" / "data"
CSV_PATH = DATA / "obos_2012-2026.csv"
# SESONGEN kjoringen gjelder. 2026 er inneverende og beholder de opprinnelige
# filnavnene; eldre sesonger er TILBAKEFYLL og legges under odds-historikk/,
# en fil per sesong, slik at jobben kan gjenopptas og to kjoringer aldri
# skriver i samme fil.
SESONG = "2026"
FIXTURES_CACHE = DATA / "oddspapi_fixtures_2026.json"
OUT_PATH = DATA / "odds_closing.json"


def sett_sesong(aar):
    """Peker stiene til den oppgitte sesongen. 2026 er uendret."""
    global SESONG, FIXTURES_CACHE, OUT_PATH
    SESONG = str(aar)
    if SESONG == "2026":
        FIXTURES_CACHE = DATA / "oddspapi_fixtures_2026.json"
        OUT_PATH = DATA / "odds_closing.json"
    else:
        h = DATA / "odds-historikk"
        FIXTURES_CACHE = h / f"oppslag_{SESONG}.json"
        OUT_PATH = h / f"{SESONG}.json"
MARKETS_CACHE = DATA / "oddspapi_markets.json"
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


def oslo_of(iso):
    """UTC-tidspunkt fra OddsPapi til norsk dato og klokkeslett."""
    if not iso or len(iso) < 16:
        return None, None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Oslo"))
    except Exception:
        return None, None
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def load_name_map():
    if NAME_MAP_PATH.exists():
        return json.loads(NAME_MAP_PATH.read_text(encoding="utf-8"))
    return {}


def get(path, params, key, timeout=TIMEOUT):
    """Går gjennom felles klient, som teller kallene (se scripts/oddspapi.py)."""
    return oddspapi.call(path, params, key, timeout=timeout)


unwrap = oddspapi.unwrap


def csv_2026():
    """Terminlisten for 2026, med resultatene fra resultatkjeden lagt oppå.

    CSV-en er terminlisten og står stille etter at sesongen er i gang, så
    resultatene hentes fra matches.json når den finnes. Uten dette ville en
    planlagt kjøring aldri se kampene som er spilt siden CSV-en ble laget.
    """
    rows = []
    for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")):
        if r["sesong"] != SESONG:
            continue
        rows.append({
            "round": int(r["runde"]), "date": r["dato"], "time": r["tid"],
            "home": r["hjemme"], "away": r["borte"],
            "hg": int(float(r["hjemmemaal"])) if r["hjemmemaal"] else None,
            "ag": int(float(r["bortemaal"])) if r["bortemaal"] else None,
        })
    # Resultatoverlegget gjelder bare inneverende sesong. For en ferdigspilt
    # sesong staar resultatene i CSV-en, og matches.json inneholder en annen
    # sesong -- aa legge den oppaa ville blandet to sesonger.
    pub_path = DATA / "matches.json"
    if pub_path.exists() and SESONG == "2026":
        pub = {(m["home"], m["away"]): (m["hg"], m["ag"])
               for m in json.loads(pub_path.read_text(encoding="utf-8"))}
        extra = 0
        for r in rows:
            v = pub.get((r["home"], r["away"]))
            if v and r["hg"] is None:
                extra += 1
            if v:
                r["hg"], r["ag"] = v
        print(f"  {len(pub)} resultater fra matches.json ({extra} flere enn CSV-en)")
    return rows


def match_id(row):
    """Nøkkelen en kamp lagres under: sesong, hjemmelag og bortelag.

    Datoen er ikke med. En flyttet kamp er den samme kampen, og skal aldri bli
    to rader i filen.
    """
    return f"{SESONG}|{row['home']}|{row['away']}"


def fetch_fixtures(key, force=False):
    """Terminlisten hos OddsPapi for hele 2026: 1 tellende kall, mellomlagret."""
    if FIXTURES_CACHE.exists() and not force:
        d = json.loads(FIXTURES_CACHE.read_text(encoding="utf-8"))
        print(f"  terminliste fra mellomlager ({len(d['fixtures'])} kamper, hentet {d['fetched_at']})")
        return d["fixtures"]
    print("  henter terminlisten fra OddsPapi (1 tellende kall)")
    d, err = get("/v4/fixtures", {"tournamentId": OBOS_TOURNAMENT,
                                  "from": f"{SESONG}-01-01",
                                  "to": f"{SESONG}-12-31"}, key)
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
    """Kobler OddsPapi-kamper til terminlisten på lagnavn. Navnetabellen brukes
    på BEGGE sider, så både «Stroemsgodset IF» og «Strømsgodset» ender på samme
    navn. Returnerer (koblinger, bare hos OddsPapi, bare i terminlisten)."""
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


MARKEDSCACHE_DAGER = 30


def fetch_markets(key):
    """Markedslisten: 1 tellende kall, mellomlagret. Trengs for å vite HVILKET
    marked som er 1X2 -- flere markeder har tre utfall, og et feil valg ga
    uavgjort til 1,61 i første forsøk.

    Vi lagrer BARE det ene markedet vi bruker, ikke hele listen. Hele svaret
    er 11 MB, og filen ligger under <liga>/data/ som publiseres på siden --
    altså 11 MB lastet ned av alle som henter datafilene, for å spare ett
    API-kall i døgnet. find_1x2() leser bare marketId og navnefeltene, og de
    beholdes i sin helhet slik at valget kan etterprøves.

    Cachen utløper etter 30 dager. Uten utløp ville en endret markeds-id hos
    OddsPapi aldri blitt oppdaget."""
    if MARKETS_CACHE.exists():
        d = json.loads(MARKETS_CACHE.read_text(encoding="utf-8"))
        hentet = d.get("hentet") if isinstance(d, dict) else None
        if hentet is None:
            return d      # gammelt format (hele listen) -- fortsatt brukbart
        alder = datetime.now(timezone.utc) - datetime.fromisoformat(hentet)
        if alder < timedelta(days=MARKEDSCACHE_DAGER):
            return d
        print(f"  markedscachen er {alder.days} dager gammel -- henter på nytt")

    d, err = oddspapi.call("/v4/markets", {}, key)
    if err:
        print(f"  FEIL ved markedsliste: {err}")
        return None
    m = find_1x2(d)
    if m is None:
        # Kjente vi ikke igjen 1X2, skal vi ikke laase en tom cache -- da
        # ville vi aldri proevd igjen.
        print("  fant ikke 1X2 i markedslisten -- cacher ikke")
        return d
    liten = {"hentet": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "note": ("Bare 1X2-markedet. Hele listen er 11 MB og ligger i en "
                      "mappe som publiseres. find_1x2() leser marketId og "
                      "navnefeltene, som er beholdt."),
             "data": [m]}
    MARKETS_CACHE.write_text(json.dumps(liten, ensure_ascii=False, indent=1), encoding="utf-8")
    return liten


def find_1x2(markets):
    """Finner markedsid-en for vanlig 1X2 (hjemme/uavgjort/borte i full tid),
    og rekkefølgen på utfallene."""
    if not markets:
        return None
    for m in oddspapi.unwrap(markets):
        name = " ".join(str(m.get(k, "")) for k in ("marketName", "name", "slug")).lower()
        if any(w in name for w in ("1x2", "match winner", "full time result", "match result",
                                   "three way", "3way", "moneyline 3")):
            if "half" in name or "period" in name or "corner" in name or "booking" in name:
                continue
            return m
    return None


def closing_from(payload, market_id=None, kickoff=None):
    """Plukker sluttoddsen fra svaret. Strukturen er
    bookmakers -> slug -> markets -> markedsid -> outcomes -> utfallsid ->
    players -> "0" -> liste av priser med createdAt.

    1X2-markedet kjennes igjen på at det har nøyaktig tre utfall; utfallene
    kommer i rekkefølgen hjemme, uavgjort, borte sortert på utfallsid (bekreftet
    mot oddsnivåene: favoritten har lavest pris). Returnerer
    (bookmaker, {H,U,B}, tidspunkt) for den best rangerte bookmakeren med odds.
    """
    root = payload.get("data", payload) if isinstance(payload, dict) else {}
    books = root.get("bookmakers") or {}
    for bm in BOOKMAKERS:
        node = books.get(bm)
        if not isinstance(node, dict):
            continue
        markets = node.get("markets") or {}
        ids = [str(market_id)] if market_id is not None and str(market_id) in markets else []
        if not ids:
            continue   # uten kjent 1X2-marked gjettes det ikke
        for mid in ids:
            m = markets.get(mid)
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
                # Sluttodds = siste pris FØR avspark. Uten dette filteret kommer
                # priser fra mens kampen pågår med, og de kjenner resultatet.
                if kickoff:
                    entries = [e for e in entries if (e.get("createdAt") or "") <= kickoff]
                if not entries:
                    vals = []
                    break
                last = max(entries, key=lambda e: e.get("createdAt") or "")
                vals.append(float(last["price"]))
                stamp = max(stamp or "", last.get("createdAt") or "")
            if len(vals) == 3:
                return bm, {"H": vals[0], "U": vals[1], "B": vals[2]}, stamp
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=250, help="høyst så mange kamper denne kjøringen")
    ap.add_argument("--report", action="store_true", help="bare navnesjekk, hent ingen odds")
    ap.add_argument("--refresh-fixtures", action="store_true", help="hent terminlisten på nytt (1 tellende kall)")
    ap.add_argument("--sesong", default="2026",
                    help="hvilken sesong. 2026 er inneværende og uendret; "
                         "eldre år er tilbakefyll til obos/data/odds-historikk/")
    args = ap.parse_args()
    sett_sesong(args.sesong)
    if args.sesong != "2026":
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"TILBAKEFYLL for {args.sesong}: skriver til "
              f"{OUT_PATH.relative_to(ROOT)}")

    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        return 1

    rows = csv_2026()
    played = [r for r in rows if r["hg"] is not None]
    print(f"Terminliste: {len(rows)} kamper i {SESONG}, {len(played)} spilte")

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
    # OddsPapi oppgir UTC, terminlisten norsk tid, så tiden må regnes om først.
    moved = []
    for r, f in links:
        d, t = oslo_of(f.get("startTime"))
        if not d:
            continue
        if d != r["date"] or t != r["time"]:
            moved.append(f"{r['home']} mot {r['away']}: {r['date']} {r['time']} -> {d} {t}")
    print(f"\nFlyttede kamper i oddssvaret: {len(moved)}")
    for m in moved[:20]:
        print(f"    {m}")

    if args.report:
        return 0

    markets = fetch_markets(key)
    mkt = find_1x2(markets)
    mkt_id = (mkt or {}).get("marketId") or (mkt or {}).get("id")
    print(f"\n1X2-marked: {json.dumps({k:v for k,v in (mkt or {}).items() if k in ('marketId','id','marketName','name','slug')}, ensure_ascii=False) if mkt else 'IKKE FUNNET -- henter ingen odds'}")
    if mkt_id is None:
        return 1
    definisjon = (f"siste observasjon {oddswindow.CLOSE_FROM_MIN} til "
                  f"{oddswindow.CLOSE_TO_MIN} minutter før avspark")
    out = {"version": 2, "source": "OddsPapi /v4/historical-odds",
           "note": ("Sluttodds er " + definisjon + ". Kamper uten observasjon i "
                    "vinduet står med bookmaker null og odds null -- de har INGEN "
                    "sluttodds, og skal ikke erstattes med en eldre pris. "
                    "Utfallene er hjemme, uavgjort, borte."),
           "definisjon": definisjon,
           "market": mkt_id, "bookmakers": BOOKMAKERS, "matches": {}}
    if OUT_PATH.exists():
        gammel = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        if gammel.get("definisjon") == definisjon:
            out = gammel
            out.setdefault("matches", {})
        else:
            # Definisjonen er endret. De gamle radene er sluttodds etter en
            # annen regel, og å blande to regler i samme fil ville gitt et
            # tall ingen kan gjøre rede for. Alt hentes på nytt -- gratis.
            print(f"  definisjonen er endret til: {definisjon}")
            print(f"  henter alle {len(gammel.get('matches', {}))} kampene på nytt "
                  f"(/v4/historical-odds er gratis)")
    # Eldre filer brukte dato i nøkkelen. Skriv dem om, så en flyttet kamp ikke
    # blir liggende to ganger.
    old = [k for k in out["matches"] if not k.startswith("2026|") or k.count("|") != 2
           or k.split("|")[0] != "2026"]
    for k in old:
        parts = k.split("|")
        out["matches"][f"2026|{parts[-2]}|{parts[-1]}"] = out["matches"].pop(k)
    if old:
        print(f"  skrev om {len(old)} gamle nøkler til sesong|hjemme|borte")
    # OddsPapi har av og til flere oppføringer for samme kamp (3 i denne
    # sesongen). Uten gruppering avgjorde den første oppføringen alene, og var
    # den tom, ble kampen stående uten sluttodds selv om den andre hadde pris.
    per_kamp = {}
    for r, f in links:
        if r["hg"] is None:
            continue
        per_kamp.setdefault(match_id(r), (r, []))[1].append(f)

    def maa_hentes(mid):
        rad = out["matches"].get(mid)
        if rad is None:
            return True
        if rad.get("bookmaker") or rad.get("uten_sluttodds"):
            return False
        return rad.get("forsok", 0) < 3

    todo = [mid for mid in per_kamp if maa_hentes(mid)]
    print(f"\nSluttodds: {len(out['matches'])} hentet før, {len(todo)} gjenstår "
          f"(henter høyst {args.max} nå)")

    done = fail = 0
    for mid in todo[:args.max]:
        r, fs = per_kamp[mid]
        truffet, siste_feil = None, None
        for f in fs:
            d, err = oddspapi.call_retry("/v4/historical-odds",
                                         {"fixtureId": f.get("fixtureId"),
                                          "bookmakers": ",".join(BOOKMAKERS)}, key)
            if err:
                siste_feil = str(err)[:120]
                time.sleep(COOLDOWN * (2 if "RATE_LIMITED" in str(err) or "429" in str(err) else 1))
                continue
            time.sleep(COOLDOWN)
            ko = f.get("startTime")
            bm, odds, stamp = oddswindow.closing_from(d, mkt_id, ko, BOOKMAKERS)
            siste_feil = None
            if bm:
                truffet = (f, bm, odds, stamp)
                break

        if truffet:
            f, bm, odds, stamp = truffet
            ko = f.get("startTime")
            out["matches"][mid] = {
                "fixtureId": f.get("fixtureId"), "round": r["round"], "start": (ko or "")[:16],
                "bookmaker": bm, "odds": odds, "priced_at": stamp,
                "result": f"{r['hg']}-{r['ag']}",
                "minutter_for": round(oddswindow.minutter_for(ko, stamp) or 0, 1)}
            done += 1
            print(f"  {mid}  {bm}  H {odds['H']}  U {odds['U']}  B {odds['B']}  "
                  f"({out['matches'][mid]['minutter_for']:.0f} min før)")
        elif siste_feil:
            rad = out["matches"].get(mid) or {"round": r["round"],
                                              "start": (fs[0].get("startTime") or "")[:16],
                                              "result": f"{r['hg']}-{r['ag']}"}
            rad.update({"bookmaker": None, "odds": None,
                        "feil": siste_feil, "forsok": rad.get("forsok", 0) + 1})
            out["matches"][mid] = rad
            fail += 1
            print(f"  {mid}  FEIL (forsøk {rad['forsok']} av 3): {siste_feil}")
        else:
            out["matches"][mid] = {
                "fixtureId": fs[0].get("fixtureId"), "round": r["round"],
                "start": (fs[0].get("startTime") or "")[:16], "bookmaker": None, "odds": None,
                "result": f"{r['hg']}-{r['ag']}", "uten_sluttodds": True}
            print(f"  {mid}  INGEN sluttodds: ingen pris i vinduet "
                  f"({oddswindow.CLOSE_FROM_MIN}-{oddswindow.CLOSE_TO_MIN} min før avspark)")
        # Lagre etter hver kamp, så en avbrutt kjøring kan fortsette.
        out["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

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
