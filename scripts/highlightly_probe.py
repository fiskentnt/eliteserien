#!/usr/bin/env python3
"""Kartlegging av Highlightly før kilden tas i bruk (3.10.2026). Kjøres
manuelt gjennom .github/workflows/highlightly-probe.yml, der nøkkelen ligger
som secret (HIGHLIGHTLY_API_KEY) -- ikke lokalt, og nøkkelen skrives aldri ut.

Høyst 8 kall (av 100 i døgnet). Med --datoer (eller DATOER) hentes bare de
dagene, ett kall per dag, til testdataene. Ellers:
  1  /matches?date=2026-10-03&countryName=Norway   dagens OBOS-kamper og ligaens id
  2  /matches?date=2026-10-21&countryName=Norway   Sogndal-Raufoss, flyttet til 21.10.
  3-5  OBOS-sesongen 2026 (leagueId, limit 100, offset 0/100/200)
  6-8  Eliteserien-sesongen 2026 (leagueName=Eliteserien, countryName=Norway)

Tidene fra Highlightly er UTC (timezone er ikke satt); de regnes om til
Europe/Oslo her. Skriver i loggen: lagnavnene og hva de blir hos oss, ligaens
id og navn, runde-feltet, dato/tid for de flyttede kampene (Sogndal-Raufoss,
Eliteserien runde 12) og alle avvik mot terminlisten og resultatene våre.
Svarene lagres i --ut (bare feltene vi bruker), som artefakt i workflowen,
til testene med lagrede svar.
"""
import argparse
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://soccer.highlightly.net"
ROT = Path(__file__).resolve().parent.parent
OSLO = ZoneInfo("Europe/Oslo")
MAKS_KALL = 8
kall = 0

# Navnene fra testene 20.9 og 3.10, og normaliseringen under for resten.
KJENTE = {"Haugesund FK": "Haugesund", "ODD Ballklubb": "Odd", "Strommen": "Strømmen",
          "Sandnes ULF": "Sandnes Ulf", "Kongsvinger IL": "Kongsvinger", "Tromsø IL": "Tromsø"}


def norm(t):
    t = unicodedata.normalize("NFKD", t.lower().replace("ø", "o").replace("æ", "ae").replace("å", "a").replace("aa", "a"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = f" {t} "
    for bort in (" fotballklubb ", " ballklubb ", " fotball ", " fk ", " il ", " bk ", " if ", " tf ", " ff ", " sk "):
        t = t.replace(bort, " ")
    return " ".join(t.split())


def hent(sti, param, nokkel):
    global kall
    if kall >= MAKS_KALL:
        raise SystemExit(f"STOPP: over {MAKS_KALL} kall")
    kall += 1
    url = f"{BASE}{sti}?{urllib.parse.urlencode(param)}"
    req = urllib.request.Request(url, headers={"x-rapidapi-key": nokkel, "User-Agent": "tabellkalkulator.no"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            hode = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower() or "remaining" in k.lower()}
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  kall {kall}: {sti} {param} -> HTTP {e.code} {e.reason} {e.read()[:300]!r}")
        return None
    print(f"  kall {kall}: {sti} {param} -> {len(data.get('data', []))} kamper, "
          f"pagination {data.get('pagination')}, grense {hode or '(ingen hoder)'}")
    return data


def kort(m):
    """Bare feltene vi bruker, til testdataene."""
    s = m.get("state") or {}
    return {"id": m.get("id"), "date": m.get("date"), "round": m.get("round"),
            "league": {k: (m.get("league") or {}).get(k) for k in ("id", "name", "season")},
            "homeTeam": {"name": (m.get("homeTeam") or {}).get("name")},
            "awayTeam": {"name": (m.get("awayTeam") or {}).get("name")},
            "state": {"description": s.get("description"), "score": {"current": (s.get("score") or {}).get("current")}}}


def vaare(liga):
    data = ROT / liga / "data"
    ut = {}
    for m in json.loads((data / "matches.json").read_text(encoding="utf-8")):
        ut[(m["home"], m["away"])] = {"round": m["round"], "date": m["date"], "time": m.get("time"), "hg": m["hg"], "ag": m["ag"]}
    for r in json.loads((data / "fixtures.json").read_text(encoding="utf-8")):
        for m in r["matches"]:
            ut.setdefault((m["home"], m["away"]), {"round": r["round"], "date": m["date"], "time": m.get("time"), "hg": None, "ag": None})
    return ut


def oversett(navn, lag):
    if navn in KJENTE:
        return KJENTE[navn]
    kand = [t for t in lag if norm(t) == norm(navn)] or [t for t in lag if norm(t) == norm(navn).rstrip("s")]
    return kand[0] if len(kand) == 1 else None


def sammenlign(liga, kamper):
    v = vaare(liga)
    lag = sorted({t for k in v for t in k})
    navn = sorted({m["homeTeam"]["name"] for m in kamper} | {m["awayTeam"]["name"] for m in kamper})
    kart = {n: oversett(n, lag) for n in navn}
    print(f"\n  Lagnavn hos Highlightly ({len(navn)}):")
    for n in navn:
        print(f"    {n!r} -> {kart[n] or 'UKJENT'}")
    hl = {}
    for m in kamper:
        h, b = kart.get(m["homeTeam"]["name"]), kart.get(m["awayTeam"]["name"])
        if not h or not b:
            continue
        t = datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(OSLO)
        sc = (m["state"]["score"]["current"] or "").replace(" ", "")
        ferdig = (m["state"]["description"] or "").startswith("Finished")
        hg = ag = None
        if ferdig and "-" in sc:
            hg, ag = (int(x) for x in sc.split("-"))
        hl[(h, b)] = {"date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"), "round": m["round"],
                      "state": m["state"]["description"], "hg": hg, "ag": ag}
    print(f"\n  {len(hl)} kamper koblet, {len(v)} hos oss")
    mangler = [k for k in v if k not in hl]
    ekstra = [k for k in hl if k not in v]
    dato = [(k, (v[k]["date"], v[k]["time"]), (hl[k]["date"], hl[k]["time"])) for k in v if k in hl and v[k]["date"] != hl[k]["date"]]
    tid = [(k, v[k]["time"], hl[k]["time"]) for k in v if k in hl and v[k]["date"] == hl[k]["date"] and v[k]["time"] != hl[k]["time"]]
    res = [(k, (v[k]["hg"], v[k]["ag"]), (hl[k]["hg"], hl[k]["ag"]), hl[k]["state"]) for k in v
           if k in hl and v[k]["hg"] is not None and (v[k]["hg"], v[k]["ag"]) != (hl[k]["hg"], hl[k]["ag"])]
    runde = [(k, v[k]["round"], hl[k]["round"]) for k in v if k in hl and str(v[k]["round"]) not in str(hl[k]["round"] or "").split()[-1:]]
    for navn_, liste in (("mangler hos Highlightly", mangler), ("bare hos Highlightly", ekstra), ("ulik dato", dato),
                         ("ulik tid (norsk tid)", tid), ("ulikt resultat", res), ("ulik runde", runde)):
        print(f"  {navn_}: {len(liste)}")
        for x in liste[:12]:
            print(f"    {x}")
    return hl, kart


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ut", default="highlightly-svar")
    ap.add_argument("--datoer", default=os.environ.get("DATOER", ""),
                    help="bare disse dagene (YYYY-MM-DD, kommaskilt), ett kall per dag, til testdataene")
    a = ap.parse_args()
    nokkel = os.environ.get("HIGHLIGHTLY_API_KEY", "").strip()
    if not nokkel:
        print("HIGHLIGHTLY_API_KEY er ikke satt -- legg den inn som secret og kjør på nytt.")
        return 1
    ut = Path(a.ut)
    ut.mkdir(parents=True, exist_ok=True)
    lagre = lambda navn, d: (ut / f"{navn}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    if a.datoer.strip():
        for dato in [x.strip() for x in a.datoer.split(",") if x.strip()]:
            d = hent("/matches", {"date": dato, "countryName": "Norway", "limit": 100}, nokkel)
            dk = [kort(m) for m in (d or {}).get("data", [])]
            lagre(f"dag_{dato}", dk)
            for m in dk:
                print(f"  {m['league']['name']} (id {m['league']['id']}): {m['homeTeam']['name']} - {m['awayTeam']['name']} "
                      f"{m['date']} {m['round']!r} {m['state']['description']} {m['state']['score']['current']}")
        print(f"\nKall brukt: {kall} av høyst {MAKS_KALL}.")
        return 0

    print("== Én dag, alle norske kamper ==")
    d1 = hent("/matches", {"date": "2026-10-03", "countryName": "Norway", "limit": 100}, nokkel)
    d1k = [kort(m) for m in (d1 or {}).get("data", [])]
    lagre("dag_2026-10-03", d1k)
    for m in d1k:
        print(f"  {m['league']['name']} (id {m['league']['id']}, sesong {m['league']['season']}): "
              f"{m['homeTeam']['name']} - {m['awayTeam']['name']} {m['date']} {m['round']!r} "
              f"{m['state']['description']} {m['state']['score']['current']}")
    obos_vaare = {t for k in vaare("obos") for t in k}
    obos_id = next((m["league"]["id"] for m in d1k
                    if oversett(m["homeTeam"]["name"], sorted(obos_vaare)) in obos_vaare), None)
    print(f"  OBOS-ligaen hos Highlightly: id {obos_id}")

    print("\n== 21.10.: Sogndal-Raufoss (flyttet) ==")
    d2 = hent("/matches", {"date": "2026-10-21", "countryName": "Norway", "limit": 100}, nokkel)
    d2k = [kort(m) for m in (d2 or {}).get("data", [])]
    lagre("dag_2026-10-21", d2k)
    for m in d2k:
        print(f"  {m['league']['name']}: {m['homeTeam']['name']} - {m['awayTeam']['name']} {m['date']} {m['round']!r} {m['state']['description']}")

    for liga, param in (("obos", {"leagueId": obos_id} if obos_id else None),
                        ("eliteserien", {"leagueName": "Eliteserien", "countryName": "Norway"})):
        print(f"\n== Sesongen 2026, {liga} ==")
        if not param:
            print("  fant ikke ligaens id -- hopper over")
            continue
        alle = []
        for offset in (0, 100, 200):
            d = hent("/matches", {**param, "season": 2026, "limit": 100, "offset": offset}, nokkel)
            if not d:
                break
            alle += [kort(m) for m in d.get("data", [])]
            if len(d.get("data", [])) < 100:
                break
        lagre(f"sesong_{liga}_2026", alle)
        if not alle:
            continue
        print(f"  {len(alle)} kamper; ligaer: {sorted({(m['league']['id'], m['league']['name'], m['league']['season']) for m in alle})}")
        hl, _ = sammenlign(liga, alle)
        if liga == "obos":
            print(f"\n  Sogndal-Raufoss: {hl.get(('Sogndal', 'Raufoss'))}")
        else:
            r12 = [(k, x) for k, x in hl.items() if vaare('eliteserien').get(k, {}).get('round') == 12]
            print(f"\n  Runde 12 ({len(r12)} kamper):")
            for k, x in r12:
                print(f"    {k[0]}-{k[1]}: {x['date']} {x['time']} {x['round']!r} {x['state']}")
    print(f"\nKall brukt: {kall} av høyst {MAKS_KALL}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
