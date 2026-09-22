#!/usr/bin/env python3
"""Finner liga-ID-ene vi trenger hos API-Football og OddsPapi, med så få kall
som mulig. Kjøres manuelt gjennom .github/workflows/discover-sources.yml, der
nøklene ligger som secrets -- ikke lokalt, og nøklene skrives aldri ut.

Kall som brukes:
  API-Football   1 kall:  /leagues?country=Norway            (av 100 i døgnet)
  OddsPapi       2 kall:  /v4/sports og /v4/tournaments      (av 250 i måneden)
                          -- /v4/historical-odds er alltid gratis, se docs

Skriver bare ut det vi leter etter (norske ligaer), ikke hele svaret.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

AF_BASE = "https://v3.football.api-sports.io"
OP_BASE = "https://api.oddspapi.io"
TIMEOUT = 30


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def api_football(key):
    print("== API-Football: norske ligaer (1 kall) ==")
    try:
        d = get(f"{AF_BASE}/leagues?country=Norway", {"x-apisports-key": key})
    except urllib.error.HTTPError as e:
        print(f"  FEIL {e.code}: {e.reason}")
        return
    except Exception as e:  # nettverk, tidsavbrudd
        print(f"  FEIL: {type(e).__name__}: {e}")
        return
    errs = d.get("errors")
    if errs:
        print(f"  API svarte med feil: {errs}")
        return
    rows = d.get("response", [])
    print(f"  {len(rows)} ligaer i Norge, {d.get('results')} treff")
    for r in rows:
        lg, seasons = r["league"], r.get("seasons", [])
        years = [s["year"] for s in seasons]
        cur = [s["year"] for s in seasons if s.get("current")]
        has26 = 2026 in years
        print(f"  id={lg['id']:>5}  {lg['name']:<28} type={lg.get('type','?'):<8} "
              f"sesonger={min(years) if years else '-'}-{max(years) if years else '-'} "
              f"({len(years)} stk){'  2026 FINNES' if has26 else ''}"
              f"{'  NÅVÆRENDE=' + str(cur[0]) if cur else ''}")
        if has26:
            s26 = next(s for s in seasons if s["year"] == 2026)
            cov = s26.get("coverage", {}).get("fixtures", {})
            print(f"         2026: {s26.get('start')} til {s26.get('end')}, "
                  f"dekning: resultater={cov.get('events')}, "
                  f"statistikk={cov.get('statistics_fixtures')}, tabell={s26.get('coverage',{}).get('standings')}")


def oddspapi(key):
    print("\n== OddsPapi: turneringer (2 kall) ==")
    try:
        sports = get(f"{OP_BASE}/v4/sports?apiKey={urllib.parse.quote(key)}")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        print(f"  FEIL {e.code} på /v4/sports: {e.reason} {body}")
        return
    except Exception as e:
        print(f"  FEIL: {type(e).__name__}: {e}")
        return
    items = sports if isinstance(sports, list) else sports.get("data", sports.get("sports", []))
    foot = [s for s in items if "foot" in json.dumps(s).lower() or "soccer" in json.dumps(s).lower()]
    print(f"  {len(items)} idretter, fotball-treff: {[{k: v for k, v in s.items() if k in ('id', 'name', 'slug')} for s in foot][:4]}")
    if not foot:
        print("  Fant ingen fotball-idrett -- skriver ut de fem første for å se formatet:")
        for s in items[:5]:
            print(f"    {s}")
        return
    sport_id = foot[0].get("id")
    try:
        tour = get(f"{OP_BASE}/v4/tournaments?sportId={sport_id}&apiKey={urllib.parse.quote(key)}")
    except urllib.error.HTTPError as e:
        print(f"  FEIL {e.code} på /v4/tournaments: {e.reason}")
        return
    tl = tour if isinstance(tour, list) else tour.get("data", tour.get("tournaments", []))
    print(f"  {len(tl)} turneringer for sportId={sport_id}")
    hits = [t for t in tl if any(w in json.dumps(t, ensure_ascii=False).lower()
            for w in ("norway", "norge", "eliteserien", "obos", "divisjon", "division 1", "1. division"))]
    for t in hits:
        print(f"    {json.dumps({k: v for k, v in t.items() if k in ('id', 'name', 'slug', 'countryName', 'country', 'categoryName')}, ensure_ascii=False)}")
    if not hits:
        print("  Ingen norske treff. Fem første turneringer, for å se formatet:")
        for t in tl[:5]:
            print(f"    {json.dumps(t, ensure_ascii=False)[:200]}")


def main():
    af = os.environ.get("API_FOOTBALL_KEY", "").strip()
    op = os.environ.get("ODDSPAPI_KEY", "").strip()
    if af:
        api_football(af)
    else:
        print("== API-Football: hopper over, API_FOOTBALL_KEY er ikke satt ==")
    if op:
        oddspapi(op)
    else:
        print("\n== OddsPapi: hopper over, ODDSPAPI_KEY er ikke satt ==")
        print("   Legg nøkkelen inn som secret (Settings -> Secrets and variables -> Actions)")
        print("   og kjør denne workflowen på nytt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
