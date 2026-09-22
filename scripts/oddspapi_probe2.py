#!/usr/bin/env python3
"""Runde to av OddsPapi-kartleggingen. Bruker 2 kall som teller.

Runde én (scripts/oddspapi_probe.py) ga:
  sportId 10 = Soccer
  tournamentId 20 = Eliteserien, 22 = 1st Division (OBOS, 56 gjenstående)
  19272 = 1st Division Women -- ikke vår liga, den lurte søkeordene først
  /v4/historical-odds KREVER bookmakers (maks 3) og har en egen
  avkjøling på rundt 4 sekunder mellom kall
  request_limit/request_count finnes IKKE i /v4/account -- docs tok feil

Det som gjenstår:
  1. hele listen over bookmakere nøkkelen har tilgang til (er Pinnacle med?)
     -- ligger under subscriptions[0].bookmakers, ikke på toppnivå   1 kall
  2. at tournamentId 22 virkelig er OBOS-ligaen (lagnavn)           1 kall
  3. hvilke av bookmakerne som faktisk har odds for en OBOS-kamp
     -- /v4/historical-odds, gratis, i grupper på tre
  4. om noen svarhoder forteller om kvoten
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.oddspapi.io"
HEADERS = {
    "Accept": "application/json",
    # Cloudflare avviser Python-urllib sin standard signatur (feil 1010).
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
}
TIMEOUT = 45
OBOS, ELITE = 22, 20
billed = 0


def get(path, params, key, billable=True, label="", show_headers=False):
    global billed
    q = dict(params or {})
    q["apiKey"] = key
    url = f"{BASE}{path}?" + urllib.parse.urlencode(q)
    if billable:
        billed += 1
    print(f"\n-> {label or path}  ({'TELLER, nr ' + str(billed) if billable else 'gratis'})")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=TIMEOUT) as r:
            if show_headers:
                intr = {k: v for k, v in r.headers.items()
                        if any(w in k.lower() for w in ("rate", "limit", "quota", "remain", "request", "usage"))}
                print(f"   svarhoder om kvote: {intr if intr else 'ingen'}")
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:400]
        except Exception:
            pass
        return None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def unwrap(d):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("data", "items", "results", "response", "fixtures"):
            if isinstance(d.get(k), list):
                return d[k]
    return []


def main():
    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        return 1

    # ---- 1. bookmakere med tilgang ----
    print("=" * 70)
    print("1. BOOKMAKERE NØKKELEN HAR TILGANG TIL")
    d, err = get("/v4/account", {}, key, label="/v4/account", show_headers=True)
    avail = []
    if err:
        print(f"   FEIL: {err}")
    else:
        a = d.get("data", d)
        print(f"   felt på toppnivå: {sorted(a)}")
        subs = a.get("subscriptions") or []
        bms = (subs[0].get("bookmakers") if subs else None) or a.get("bookmakers") or {}
        avail = sorted(bms) if isinstance(bms, dict) else []
        print(f"   ANTALL BOOKMAKERE: {len(avail)}")
        pin = [b for b in avail if "pinn" in b.lower()]
        print(f"   PINNACLE: {'JA (' + ', '.join(pin) + ')' if pin else 'NEI'}")
        for i in range(0, len(avail), 8):
            print(f"     {', '.join(avail[i:i+8])}")
        if subs:
            s0 = subs[0]
            print(f"   abonnement: pris={s0.get('price')} {s0.get('currency','')} "
                  f"aktiv={s0.get('is_active')} auto_renew={s0.get('auto_renew')} "
                  f"sport_ids={s0.get('sport_ids')}")
    time.sleep(2)

    # ---- 2. er tournamentId 22 OBOS-ligaen? ----
    print("\n" + "=" * 70)
    print(f"2. KAMPER I TURNERING {OBOS} (skal være OBOS-ligaen, menn)")
    fx, err = get("/v4/fixtures", {"tournamentId": OBOS, "from": "2026-09-01", "to": "2026-09-22"},
                  key, label=f"/v4/fixtures tournamentId={OBOS}", show_headers=True)
    played = []
    if err:
        print(f"   FEIL: {err}")
    else:
        fl = unwrap(fx)
        print(f"   {len(fl)} kamper 1.-22. september")
        teams = sorted({f.get("participant1Name") for f in fl} | {f.get("participant2Name") for f in fl})
        print(f"   lag: {[t for t in teams if t]}")
        print(f"   turneringsnavn i svaret: {sorted({f.get('tournamentName') for f in fl})}")
        for f in fl[:6]:
            print(f"     {f.get('startTime','')[:16]}  {f.get('participant1Name')} mot {f.get('participant2Name')}"
                  f"  status={f.get('statusName')}  hasOdds={f.get('hasOdds')}  id={f.get('fixtureId')}")
        played = [f for f in fl if f.get("statusId") == 2]
        print(f"   ferdigspilte: {len(played)}")

    # ---- 3. hvilke bookmakere har odds for en OBOS-kamp? (gratis) ----
    print("\n" + "=" * 70)
    print("3. HVILKE BOOKMAKERE HAR ODDS FOR EN SPILT OBOS-KAMP")
    if not played:
        print("   ingen ferdigspilt kamp å prøve")
    else:
        f = played[-1]
        fid = f.get("fixtureId")
        print(f"   kamp: {f.get('participant1Name')} mot {f.get('participant2Name')} "
              f"{f.get('startTime','')[:16]}  ({fid})")
        cands = avail or ["bet365", "unibet", "williamhill"]
        has, empty = [], []
        for i in range(0, len(cands), 3):
            grp = cands[i:i + 3]
            d, err = get("/v4/historical-odds", {"fixtureId": fid, "bookmakers": ",".join(grp)},
                         key, billable=False, label=f"historiske odds: {', '.join(grp)}",
                         show_headers=(i == 0))
            if err:
                print(f"   FEIL: {err}")
                time.sleep(5)
                continue
            raw = d.get("data", d) if isinstance(d, dict) else d
            if isinstance(raw, dict) and raw:
                for bm, v in raw.items():
                    n = len(json.dumps(v))
                    (has if n > 40 else empty).append(f"{bm} ({n} tegn)")
                if i == 0:
                    print(f"   struktur: {json.dumps(raw, ensure_ascii=False)[:700]}")
            else:
                empty.extend(grp)
                if i == 0:
                    print(f"   tomt svar: {json.dumps(d, ensure_ascii=False)[:300]}")
            print(f"   -> med odds: {has if has else 'ingen ennå'}")
            time.sleep(5)
        print(f"\n   MED ODDS: {has}")
        print(f"   UTEN ODDS: {empty}")

    print(f"\n   Tellende kall i denne kjøringen: {billed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
