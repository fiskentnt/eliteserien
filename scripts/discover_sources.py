#!/usr/bin/env python3
"""Finner turnerings-ID-ene vi trenger hos OddsPapi, med så få kall som
mulig. Kjøres manuelt gjennom .github/workflows/discover-sources.yml, der
nøkkelen ligger som secret -- ikke lokalt, og nøkkelen skrives aldri ut.

Kall som brukes:
  OddsPapi       2 kall:  /v4/sports og /v4/tournaments      (av 250 i måneden)
                          -- /v4/historical-odds er alltid gratis, se docs

API-Football er fjernet (3.10.2026): gratisplanen gir bare sesongene
2022-2024, og nøkkelen ble ikke brukt til noe annet.

Skriver bare ut det vi leter etter (norske ligaer), ikke hele svaret.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

OP_BASE = "https://api.oddspapi.io"
TIMEOUT = 30


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


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
    op = os.environ.get("ODDSPAPI_KEY", "").strip()
    if op:
        oddspapi(op)
    else:
        print("\n== OddsPapi: hopper over, ODDSPAPI_KEY er ikke satt ==")
        print("   Legg nøkkelen inn som secret (Settings -> Secrets and variables -> Actions)")
        print("   og kjør denne workflowen på nytt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
