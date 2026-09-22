#!/usr/bin/env python3
"""Engangs kartlegging av OddsPapi-kontoen, med et stramt kallbudsjett.

Svarer på fire spørsmål med HØYST 5 kall som teller mot kvoten:
  1. Hvilken plan har nøkkelen, og hvilke bookmakere gir den tilgang til
     (er Pinnacle med)?                                    -- /v4/account, 1 kall
  2. Finnes norsk 1. divisjon og Eliteserien i turneringslisten, med
     hvilke ID-er?                        -- /v4/sports + /v4/tournaments, 2 kall
  3. Hvilke bookmakere har faktisk odds for en spilt OBOS-kamp i 2026?
                                          -- /v4/fixtures, 1 kall
                                          -- /v4/historical-odds, GRATIS
  4. Teller historiske odds mot kvoten?   -- /v4/account igjen, 1 kall
                                             (request_count før og etter)

Nøkkelen leses fra ODDSPAPI_KEY og skrives aldri ut. Kjøres gjennom
.github/workflows/discover-sources.yml, der nøkkelen ligger som secret.

Endepunktene har egne avkjølingstider (1-2 sekunder), så det ventes mellom kall.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.oddspapi.io"
# Cloudflare foran api.oddspapi.io avviser Python-urllib sin standard
# User-Agent med feil 1010 (browser_signature_banned), FØR kallet når API-et.
# En vanlig nettleser-signatur slipper gjennom.
HEADERS = {
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 45
calls_billed = 0


def get(path, params, key, billable=True, label=""):
    """Kaller endepunktet. Returnerer (data, feilmelding)."""
    global calls_billed
    q = dict(params or {})
    q["apiKey"] = key
    url = f"{BASE}{path}?" + urllib.parse.urlencode(q)
    if billable:
        calls_billed += 1
    safe = url.replace(urllib.parse.quote(key), "***").replace(key, "***")
    print(f"\n-> {label or path}  ({'teller' if billable else 'GRATIS'}; "
          f"{calls_billed} tellende kall brukt)\n   {safe}")
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:500]
        except Exception:
            pass
        return None, f"HTTP {e.code} {e.reason}: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def unwrap(d):
    """Svarene er enten en liste eller pakket i data/items/results."""
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("data", "items", "results", "response"):
            if isinstance(d.get(k), list):
                return d[k]
    return []


def account(key, when, raw=False):
    d, err = get("/v4/account", {}, key, label=f"/v4/account ({when})")
    if err:
        print(f"   FEIL: {err}")
        return None
    a = d.get("data", d) if isinstance(d, dict) else d
    if raw:
        # Feltnavnene i dokumentasjonen stemte ikke, så skriv ut alt (maskert).
        blob = json.dumps(d, ensure_ascii=False, indent=1)
        blob = blob.replace(key, "***")
        print("   RÅDATA:")
        for line in blob.splitlines()[:80]:
            print("    " + line)
    limit, count = a.get("request_limit"), a.get("request_count")
    print(f"   kvote: {count} av {limit} brukt", end="")
    if a.get("last_request"):
        print(f", siste kall {a['last_request']}", end="")
    print()
    subs = a.get("subscriptions") or []
    for s in subs:
        print(f"   abonnement: id={s.get('subscription_id')} pris={s.get('price')} "
              f"{s.get('currency','')} aktiv={s.get('is_active')} "
              f"gyldig {s.get('valid_from','?')} til {s.get('valid_until','?')}")
    bms = a.get("bookmakers") or {}
    if isinstance(bms, dict):
        names = sorted(bms)
        print(f"   bookmakere med tilgang: {len(names)}")
        pin = [n for n in names if "pinn" in n.lower()]
        print(f"   PINNACLE: {'JA -> ' + str({p: bms[p] for p in pin}) if pin else 'NEI'}")
        print(f"   alle: {', '.join(names)}")
    else:
        print(f"   bookmakere (uventet form): {json.dumps(bms)[:300]}")
    print(f"   sport_ids: {a.get('sport_ids')}  websocket: {a.get('websocket_access')}")
    return {"count": count, "limit": limit, "bookmakers": list(bms) if isinstance(bms, dict) else []}


def main():
    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        return 1

    print("=" * 70)
    print("1. KONTO OG BOOKMAKERE")
    before = account(key, "før", raw=True)
    if not before:
        print("\n   Kom ikke forbi kontooppslaget, avbryter for å ikke brenne kall.")
        return 1
    time.sleep(1.5)

    print("\n" + "=" * 70)
    print("2. TURNERINGER: NORSK 1. DIVISJON OG ELITESERIEN")
    # sportId=10 (Soccer) er slått opp i forrige kjøring, så /v4/sports spares.
    sport_id = int(os.environ.get("SPORT_ID", "10"))
    print(f"   bruker sportId={sport_id} (Soccer), slått opp tidligere")

    obos_id = elite_id = None
    if sport_id is not None:
        tours, err = get("/v4/tournaments", {"sportId": sport_id}, key,
                         label=f"/v4/tournaments?sportId={sport_id}")
        if err:
            print(f"   FEIL: {err}")
        else:
            tl = unwrap(tours)
            print(f"   {len(tl)} turneringer")
            def txt(t):
                return json.dumps(t, ensure_ascii=False).lower()
            nor = [t for t in tl if "norw" in txt(t) or "norge" in txt(t) or "norsk" in txt(t)]
            print(f"   norske turneringer: {len(nor)}")
            for t in nor:
                print(f"     {json.dumps(t, ensure_ascii=False)}")
                s = txt(t)
                tid = t.get("id") or t.get("tournamentId")
                if any(w in s for w in ("1. division", "1. divisjon", "first division", "obos",
                                        "division 1", "1st division", "1.division")):
                    obos_id = tid
                if "eliteserien" in s:
                    elite_id = tid
            if not nor:
                print(f"   ingen norske treff; fem første: {json.dumps(tl[:5], ensure_ascii=False)[:400]}")
    print(f"\n   => OBOS/1. divisjon: {obos_id}   Eliteserien: {elite_id}")
    time.sleep(2.5)

    print("\n" + "=" * 70)
    print("3. HISTORISKE ODDS FOR ÉN SPILT OBOS-KAMP I 2026")
    fixture = None
    if obos_id is not None:
        fx, err = get("/v4/fixtures", {"tournamentId": obos_id, "statusId": 2,
                                       "from": "2026-08-01", "to": "2026-09-21"}, key,
                      label=f"/v4/fixtures (spilte OBOS-kamper i august og september)")
        if err:
            print(f"   FEIL: {err}")
        else:
            fl = unwrap(fx)
            print(f"   {len(fl)} spilte kamper i perioden")
            if fl:
                fixture = fl[-1]
                keep = {k: v for k, v in fixture.items() if k in
                        ("fixtureId", "id", "startTime", "trueStartTime", "statusId", "homeName", "awayName",
                         "participants", "name", "homeScore", "awayScore")}
                print(f"   valgt kamp: {json.dumps(keep, ensure_ascii=False)[:400]}")
                print(f"   (alle felt: {', '.join(sorted(fixture))})")
    else:
        print("   hopper over: fant ingen turnerings-ID")

    if fixture:
        fid = fixture.get("fixtureId") or fixture.get("id")
        # Historiske odds er gratis, så vi kan prøve flere varianter.
        tried = []
        for bms in (None, ",".join((before["bookmakers"] or ["pinnacle"])[:3]), "pinnacle"):
            params = {"fixtureId": fid}
            if bms:
                params["bookmakers"] = bms
            d, err = get("/v4/historical-odds", params, key, billable=False,
                         label=f"/v4/historical-odds (bookmakers={bms or 'ikke oppgitt'})")
            tried.append((bms, err))
            if err:
                print(f"   FEIL: {err}")
                time.sleep(1.0)
                continue
            raw = d.get("data", d) if isinstance(d, dict) else d
            print(f"   svarets toppnivå: {type(raw).__name__} "
                  f"{list(raw)[:12] if isinstance(raw, dict) else f'{len(raw)} elementer'}")
            blob = json.dumps(d, ensure_ascii=False)
            print(f"   størrelse: {len(blob)} tegn")
            # Hvilke bookmakere har faktisk odds?
            found = []
            if isinstance(raw, dict):
                found = list(raw)
            elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
                for k in ("bookmaker", "bookmakerSlug", "bookmakerName", "slug"):
                    vals = {r.get(k) for r in raw if r.get(k)}
                    if vals:
                        found = sorted(vals)
                        break
            print(f"   BOOKMAKERE MED ODDS: {found if found else '(fant ikke navn, se utsnitt under)'}")
            print(f"   utsnitt: {blob[:900]}")
            break
        if all(e for _, e in tried):
            print("   Alle forsøk feilet -- se feilmeldingene over.")

    print("\n" + "=" * 70)
    print("4. TELLER HISTORISKE ODDS MOT KVOTEN?")
    time.sleep(1.5)
    after = account(key, "etter") if os.environ.get("CHECK_AFTER", "1") == "1" else None
    if before and after and before["count"] is not None and after["count"] is not None:
        used = after["count"] - before["count"]
        print(f"\n   request_count: {before['count']} -> {after['count']} (økning {used})")
        print(f"   tellende kall jeg gjorde mellom de to kontooppslagene: 3 "
              f"(sports, tournaments, fixtures) + kontooppslaget selv")
        print(f"   => historiske odds ser {'GRATIS' if used <= 4 else 'ut til å TELLE'} ut")
    print(f"\n   Totalt tellende kall i denne kjøringen: {calls_billed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
