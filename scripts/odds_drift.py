#!/usr/bin/env python3
"""Hvor mye flytter oddsen seg fra dagen for til rett for avspark?

Sporsmalet bak: er det verdt a hente oddsen en gang til naer avspark, nar
laguttaket er kjent? Svaret males, ikke antas.

Malingen er mulig fordi /v4/historical-odds gir HELE prisrekken for en kamp,
ikke bare siste pris: hver pris har et createdAt. Vi kan derfor lese av hva
oddsen var pa et hvilket som helst tidspunkt for avspark, i etterkant, uten
a ha lagret noe selv. Endepunktet er gratis, sa malingen koster 0 tellende
kall; bare terminlisten og markedslisten koster, og begge leses fra
mellomlageret.

Fire avlesningspunkt per kamp:
  dagen for    siste pris minst 24 timer for avspark
  ordinaer     siste pris for den siste vanlige hentingen (08.13 eller 16.13 UTC)
  sluttodds    siste pris i vinduet 60 til 15 minutter for avspark
  avspark      siste pris for avspark, uansett hvor sen

"sluttodds" er definisjonen vi gar for: et fast vindu, ikke "det siste vi
tilfeldigvis har". En kamp uten pris i vinduet er en kamp UTEN sluttodds --
vi later ikke som om en pris fra i gar er en sluttodds.

Det som rapporteres:
  hvor mye desimaloddsen og sannsynlighetene (margin fjernet) flyttet seg,
  hvor ofte favoritten byttet, og om de sene tallene faktisk traff bedre --
  log loss mot resultatet, parvis med standardfeil. Flytting alene er ikke
  nok: oddsen kan bevege seg uten a bli bedre.

  python3 scripts/odds_drift.py obos
  python3 scripts/odds_drift.py eliteserien
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi
import oddslib
from obos_closing_odds import (BOOKMAKERS, COOLDOWN, OBOS_TOURNAMENT, csv_2026, find_1x2,
                               match_fixtures)

ROOT = Path(__file__).parent.parent
ELITE_TOURNAMENT = 20
# Nar de vanlige hentingene gar (UTC). Brukes til a regne ut hva vi FAKTISK
# ville fanget uten en ekstra henting naer avspark.
ORDINARY_UTC_HOURS = (8, 16)
# Sluttoddsvinduet: tidligst 60 minutter for avspark, senest 15 minutter for.
CLOSE_FROM_MIN, CLOSE_TO_MIN = 60, 15
MARKETS_CACHE = ROOT / "obos" / "data" / "oddspapi_markets.json"
PUNKT = ("dagen for", "ordinaer", "sluttodds", "avspark")


def series(payload, market_id):
    """{bookmaker: {utfallsid: [(tid, pris), ...]}} -- hele rekken, sortert."""
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
        per = {}
        for oid in sorted(outcomes, key=lambda x: str(x)):
            entries = []
            for plist in ((outcomes[oid] or {}).get("players") or {}).values():
                if isinstance(plist, list):
                    entries.extend(e for e in plist
                                   if isinstance(e, dict) and e.get("price") and e.get("createdAt"))
            if not entries:
                per = {}
                break
            per[oid] = sorted((e["createdAt"], float(e["price"])) for e in entries)
        if len(per) == 3:
            ut[bm] = per
    return ut


def snapshot(per_outcome, cutoff_iso, floor_iso=None):
    """Prisene slik de sto ved cutoff, eller None.

    floor_iso setter en nedre grense: en pris eldre enn den teller ikke. Det
    er det som skiller "sluttodds" fra "siste vi har" -- uten gulvet ville en
    pris fra dagen for sneket seg inn som sluttodds.
    """
    vals, stamp = [], None
    for oid in sorted(per_outcome, key=str):
        rows = [(t, p) for t, p in per_outcome[oid]
                if t <= cutoff_iso and (floor_iso is None or t >= floor_iso)]
        if not rows:
            return None
        t, p = rows[-1]
        vals.append(p)
        stamp = max(stamp or "", t)
    pH, pU, pB = oddslib.devig(*vals)
    return {"H": pH, "U": pU, "B": pB, "hentet": stamp,
            "dH": vals[0], "dU": vals[1], "dB": vals[2]}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.999Z")


def siste_ordinaere(ko):
    """Siste vanlige hentetidspunkt for avspark (08.13 eller 16.13 UTC)."""
    best = None
    for d in (0, 1):
        dag = (ko - timedelta(days=d)).date()
        for h in ORDINARY_UTC_HOURS:
            t = datetime(dag.year, dag.month, dag.day, h, 13, tzinfo=timezone.utc)
            if t < ko and (best is None or t > best):
                best = t
    return best


def mean_se(xs):
    n = len(xs)
    if n < 2:
        return (xs[0] if xs else 0.0), 0.0
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, sd / math.sqrt(n)


def load_fixtures(liga, key, refresh):
    """Terminlisten. Fra mellomlageret hvis den finnes -- 0 tellende kall."""
    if liga == "obos":
        cache = ROOT / "obos" / "data" / "oddspapi_fixtures_2026.json"
        params = {"tournamentId": OBOS_TOURNAMENT, "from": "2026-01-01", "to": "2026-12-31"}
    else:
        # Egen sesongliste. odds_compare.py sin oddspapi_fixtures.json dekker
        # bare tre uker fram og rores ikke her.
        cache = ROOT / "eliteserien" / "data" / "oddspapi_fixtures_2026.json"
        params = {"tournamentId": ELITE_TOURNAMENT, "from": "2026-01-01", "to": "2026-12-31"}
    if cache.exists() and not refresh:
        d = json.loads(cache.read_text(encoding="utf-8"))
        fl = d.get("fixtures") or []
        print(f"  terminliste fra mellomlager: {len(fl)} kamper (0 tellende kall)")
        return fl
    print("  henter terminliste (1 tellende kall)")
    d, err = oddspapi.call("/v4/fixtures", params, key)
    if err:
        print(f"  FEIL: {err}")
        return []
    fl = oddspapi.unwrap(d)
    cache.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "from": params["from"], "to": params["to"], "fixtures": fl},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    return fl


def load_name_map(liga):
    """Navnetabellen for ligaen: OddsPapi-navn til vare egne."""
    p = (ROOT / "obos" / "data" / "name_map.json" if liga == "obos"
         else ROOT / "eliteserien" / "data" / "oddspapi_name_map.json")
    if not p.exists():
        return {}
    return {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items()
            if not k.startswith("_")}


def load_rows(liga):
    """Spilte kamper med resultat."""
    if liga == "obos":
        return [r for r in csv_2026() if r["hg"] is not None]
    p = ROOT / "eliteserien" / "data" / "matches.json"
    return [dict(r) for r in json.loads(p.read_text(encoding="utf-8")) if r["hg"] is not None]


def favoritt(s):
    return max("HUB", key=lambda k: s[k])


def rapport(liga, data, mangler_vindu, n_koblet):
    n = len(data)
    print(f"\n=== {liga}: {n} kamper med pris pa alle fire tidspunkt "
          f"(av {n_koblet} koblede)\n")
    print(f"Kamper uten pris i sluttoddsvinduet ({CLOSE_FROM_MIN}-{CLOSE_TO_MIN} min "
          f"for avspark): {mangler_vindu}")
    if n < 5:
        print("For fa kamper til a si noe.")
        return

    def alder(d, k, enhet=60):
        return (d["ko"] - datetime.fromisoformat(
            d["snaps"][k]["hentet"].replace("Z", "+00:00"))).total_seconds() / enhet

    for k, enhet, navn in (("ordinaer", 3600, "timer"), ("sluttodds", 60, "min"),
                           ("avspark", 60, "min")):
        v = sorted(alder(d, k, enhet) for d in data)
        print(f"  {k:<10} median {v[n//2]:.1f} {navn} for avspark "
              f"(spenn {v[0]:.1f} til {v[-1]:.1f})")

    for fra, til in (("dagen for", "sluttodds"), ("ordinaer", "sluttodds")):
        print(f"\n--- {fra} mot {til} ---")
        dec = sorted(max(abs(d["snaps"][til]["d" + k] - d["snaps"][fra]["d" + k])
                         for k in "HUB") for d in data)
        m_dec, _ = mean_se(dec)
        print(f"  desimalodds, storste utslag per kamp: snitt {m_dec:.3f}, "
              f"median {dec[n//2]:.3f}, storst {dec[-1]:.2f}")
        rel = sorted(max(abs(d["snaps"][til]["d" + k] / d["snaps"][fra]["d" + k] - 1)
                         for k in "HUB") * 100 for d in data)
        m_rel, _ = mean_se(rel)
        print(f"  samme, i prosent av prisen:          snitt {m_rel:.1f} %, "
              f"median {rel[n//2]:.1f} %, storst {rel[-1]:.0f} %")
        pp = sorted(max(abs(d["snaps"][til][k] - d["snaps"][fra][k]) for k in "HUB") * 100
                    for d in data)
        m_pp, se_pp = mean_se(pp)
        print(f"  sannsynlighet, margin fjernet:       snitt {m_pp:.2f} pp "
              f"(+- {se_pp:.2f}), median {pp[n//2]:.2f}, storst {pp[-1]:.1f}")
        for grense in (2, 3, 5):
            print(f"    over {grense} pp: {100*sum(1 for x in pp if x >= grense)/n:.0f} % "
                  f"av kampene ({sum(1 for x in pp if x >= grense)} av {n})")
        bytter = sum(1 for d in data if favoritt(d["snaps"][fra]) != favoritt(d["snaps"][til]))
        print(f"  favoritten byttet:                   {bytter} av {n} "
              f"({100*bytter/n:.0f} %)")

    print("\nTraff de sene tallene bedre? Log loss mot resultatet:")
    tap = {k: [-math.log(max(d["snaps"][k][d["utfall"]], 1e-9)) for d in data] for k in PUNKT}
    treff = {k: [1 if favoritt(d["snaps"][k]) == d["utfall"] else 0 for d in data] for k in PUNKT}
    base = "sluttodds"
    for k in PUNKT:
        ll = sum(tap[k]) / n
        hit = 100 * sum(treff[k]) / n
        if k == base:
            print(f"  {k:<10} {ll:.4f}   treff {hit:.1f} %   (utgangspunktet)")
            continue
        d_ = [tap[k][i] - tap[base][i] for i in range(n)]
        md, se = mean_se(d_)
        retning = "darligere enn sluttodds" if md > 0 else "bedre enn sluttodds"
        print(f"  {k:<10} {ll:.4f}   treff {hit:.1f} %   {md:+.4f} +- {se:.4f} "
              f"({abs(md/se) if se > 1e-12 else 0:.1f} SE, {retning})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("liga", nargs="?", default="obos", choices=["obos", "eliteserien"])
    ap.add_argument("--max", type=int, default=400)
    ap.add_argument("--refresh-fixtures", action="store_true")
    ap.add_argument("--dump", default="", help="skriv radene til en json-fil")
    args = ap.parse_args()

    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        return 1

    rows = load_rows(args.liga)
    fixtures = load_fixtures(args.liga, key, args.refresh_fixtures)
    if not fixtures:
        return 1
    links, only_odds, only_csv = match_fixtures(rows, fixtures, load_name_map(args.liga))
    print(f"{len(rows)} spilte kamper, {len(links)} koblet til OddsPapi\n")

    mkt = find_1x2(json.loads(MARKETS_CACHE.read_text(encoding="utf-8"))
                   if MARKETS_CACHE.exists() else None)
    if not mkt:
        print("  markedslisten var ikke mellomlagret (1 tellende kall)")
        mkt = find_1x2(oddspapi.call("/v4/markets", {"sportId": 10}, key)[0])
    mkt_id = (mkt or {}).get("marketId") or (mkt or {}).get("id")
    if mkt_id is None:
        print("fant ikke 1X2-markedet")
        return 1

    data, mangler_vindu = [], 0
    for i, (r, f) in enumerate(links[:args.max]):
        fid = f.get("fixtureId")
        ko_s = f.get("startTime") or ""
        if not fid or not ko_s:
            continue
        ko = datetime.fromisoformat(ko_s.replace("Z", "+00:00"))
        if ko.tzinfo is None:
            ko = ko.replace(tzinfo=timezone.utc)
        params = {"fixtureId": fid, "bookmakers": ",".join(BOOKMAKERS)}
        o, err = oddspapi.call("/v4/historical-odds", params, key)
        if err and "RATE_LIMITED" in str(err):
            time.sleep(COOLDOWN)
            o, err = oddspapi.call("/v4/historical-odds", params, key)
        if err:
            print(f"  {r['home']} mot {r['away']}: FEIL {err}")
            time.sleep(COOLDOWN)
            continue
        ser = series(o or {}, mkt_id)
        bm = next((b for b in BOOKMAKERS if b in ser), None)
        if bm:
            ord_t = siste_ordinaere(ko)
            snaps = {
                "dagen for": snapshot(ser[bm], iso(ko - timedelta(hours=24))),
                "ordinaer": snapshot(ser[bm], iso(ord_t)) if ord_t else None,
                "sluttodds": snapshot(ser[bm], iso(ko - timedelta(minutes=CLOSE_TO_MIN)),
                                      floor_iso=iso(ko - timedelta(minutes=CLOSE_FROM_MIN))),
                "avspark": snapshot(ser[bm], iso(ko)),
            }
            if not snaps["sluttodds"]:
                mangler_vindu += 1
            if all(snaps[k] for k in PUNKT):
                utfall = "H" if r["hg"] > r["ag"] else ("U" if r["hg"] == r["ag"] else "B")
                data.append({"home": r["home"], "away": r["away"], "bm": bm, "ko": ko,
                             "utfall": utfall, "snaps": snaps})
        if (i + 1) % 20 == 0:
            print(f"  {i+1} av {len(links[:args.max])} ...")
        time.sleep(COOLDOWN)

    rapport(args.liga, data, mangler_vindu, len(links))
    if args.dump:
        Path(args.dump).write_text(json.dumps(
            [{**d, "ko": d["ko"].isoformat()} for d in data], ensure_ascii=False, indent=1),
            encoding="utf-8")
    used, limit = oddspapi.usage()
    print(f"\nTellende kall brukt denne maneden: {used} av {limit}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
