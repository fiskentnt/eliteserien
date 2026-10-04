#!/usr/bin/env python3
"""Odds for kommende OBOS-kamper, fra OddsPapi, til obos/data/odds_upcoming.json.

Siden blander disse oddsene inn per kamp (samme mekanikk som Eliteserien, se
ODDS_W i index.html). Filen har samme form som eliteserien/data/odds_upcoming.json,
så sidekoden er felles.

Kilderekkefølge: Pinnacle, ellers bet365, ellers Unibet. ALDRI et snitt av
flere bookmakere -- én kilde per kamp, og hvilken står i filen.

Kallbruk: 0 tellende kall i normal drift. Terminlisten leses fra sesonglisten
obos_results.py oppdaterer i samme kjøring, og oddsoppslagene
(/v4/historical-odds) er gratis. Spilte kamper ryddes
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
SEASON_CACHE = DATA / "oddspapi_fixtures_2026.json"
# Når OddsPapi først hadde odds for hver kamp (hasOdds), og hvor lenge etter
# at runden før var spilt (4.10.2026). Se oddsaapning().
AAPNING_PATH = DATA / "odds_aapning.json"
# Når kamplisten (med hasOdds) ble hentet: fetch_upcoming_fixtures setter den.
LISTE_TID = None
SEASON_CACHE_HOURS = 30   # obos_results.py oppdaterer den hver dag
COOLDOWN = 4.5


def fetch_upcoming_fixtures(key, frm, to, force=False):
    """Kommende kamper hos OddsPapi.

    Sesongens terminliste ligger alt i obos/data/oddspapi_fixtures_2026.json,
    hentet av obos_results.py i samme kjøring, minutter før denne. Vi hentet
    likevel en EGEN liste her, med eget mellomlager på en time -- 30 tellende
    kall i måneden for en liste vi allerede hadde. Nå leses sesonglisten, og
    kampene i vinduet plukkes ut av den. 0 tellende kall.

    Er sesonglisten borte eller for gammel, hentes vinduet som før.
    """
    global LISTE_TID
    if SEASON_CACHE.exists() and not force:
        d = json.loads(SEASON_CACHE.read_text(encoding="utf-8"))
        alder = datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched_at"])
        if alder < timedelta(hours=SEASON_CACHE_HOURS):
            LISTE_TID = datetime.fromisoformat(d["fetched_at"])
            i_vinduet = [f for f in (d.get("fixtures") or [])
                         if frm <= (f.get("startTime") or "")[:10] <= to]
            print(f"  terminliste fra sesonglisten ({len(i_vinduet)} kamper i vinduet, "
                  f"{int(alder.total_seconds()/3600)} t gammel, 0 tellende kall)")
            return i_vinduet
    print("  sesonglisten mangler eller er for gammel -- henter vinduet (1 tellende kall)")
    LISTE_TID = datetime.now(timezone.utc)
    d, err = oddspapi.call("/v4/fixtures", {"tournamentId": OBOS_TOURNAMENT,
                                            "from": frm, "to": to}, key)
    if err and "FIXTURE_NOT_FOUND" in str(err):
        # Ingen kamper i vinduet er et gyldig svar (landskampspause), ikke en feil.
        print("  ingen OBOS-kamper i vinduet")
        d = {"data": []}
    elif err:
        print(f"  FEIL: {err}")
        return None
    return oddspapi.unwrap(d)


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


def _dagspenn(datoer):
    """"11. til 18.10.", "28.9. til 2.10.", "11.10."."""
    a, b = min(datoer), max(datoer)
    d = lambda x, mnd=True: f"{int(x[8:10])}." + (f"{int(x[5:7])}." if mnd else "")
    if a == b:
        return d(a)
    return f"{d(a, a[5:7] != b[5:7])} til {d(b)}"


def _klokke(t):
    from zoneinfo import ZoneInfo
    t = t.astimezone(ZoneInfo("Europe/Oslo"))
    return f"{t.day}.{t.month}. kl. {t.strftime('%H.%M')}"


def _varighet(sek):
    t, m = int(sek // 3600), int(sek % 3600 // 60)
    return f"{t} t {m} min" if t else f"{m} min"


def alle_kamper():
    """Hele sesongen med dagens datoer (matches.json og fixtures.json), ikke
    CSV-en: den har de opprinnelige datoene, også for flyttede kamper."""
    spilt = json.loads((DATA / "matches.json").read_text(encoding="utf-8"))
    fx = json.loads((DATA / "fixtures.json").read_text(encoding="utf-8"))
    sett = {(m["home"], m["away"]) for m in spilt}
    return [dict(m) for m in spilt] + [dict(m, round=r["round"]) for r in fx for m in r["matches"]
                                       if (m["home"], m["away"]) not in sett]


def oddsaapning(koblet, forventet, liste_tid, gml):
    """Når OddsPapi først hadde odds (hasOdds) for hver kamp, og hvor lenge
    etter at runden før var spilt (4.10.2026). Tidspunktet er når kamplisten
    ble hentet (liste_tid), så målingen er ikke mer nøyaktig enn hvor ofte
    listen hentes (omtrent én gang i døgnet). En kamp som hadde odds alt
    første gang vi så den, får "alt_ved_forste".

    koblet: [(rad, fixture)] for de uspilte kampene; gml: forrige tilstand,
    som glemmes ved ny sesong (samme lag møtes igjen neste år).
    Returnerer (ny tilstand, linjer per runde)."""
    gml = gml if (gml or {}).get("sesong") == liste_tid.year else {}
    kamper = dict(gml.get("kamper") or {})
    for r, f in koblet:
        n = f"{r['home']}|{r['away']}"
        fv = forventet.get((r["home"], r["away"]))
        k = kamper.setdefault(n, {"runde": r["round"]})
        if fv:
            k.update(forrige=fv["forrige"], forrige_kamp=fv["kamp"], forrige_slutt=fv["slutt"].isoformat(timespec="seconds"))
        if f.get("hasOdds") and not k.get("odds_fra"):
            k["odds_fra"] = liste_tid.isoformat(timespec="seconds")
            k["alt_ved_forste"] = "sett_uten" not in k
        elif not f.get("hasOdds"):
            k["sett_uten"] = liste_tid.isoformat(timespec="seconds")
    linjer = []
    per, foerst = {}, {}
    for r, f in koblet:
        k = kamper[f"{r['home']}|{r['away']}"]
        # En utsatt kamp har en senere runde før seg enn sin egen: egen gruppe.
        utsatt = bool(k.get("forrige") and k["forrige"] > r["round"])
        per.setdefault((r["round"], utsatt), []).append(k)
        a = f"{r.get('date') or ''} {r.get('time') or ''}"
        foerst[(r["round"], utsatt)] = min(foerst.get((r["round"], utsatt), a), a)
    # I den rekkefølgen de spilles: den utsatte kampen der den nå ligger.
    for (runde, utsatt) in sorted(per, key=lambda g: (foerst[g], g)):
        ks = per[(runde, utsatt)]
        med = [k for k in ks if k.get("odds_fra")]
        k0 = ks[0]
        navn = (f"Utsatt{'e' if len(ks) > 1 else ''} kamp{'er' if len(ks) > 1 else ''} fra runde {runde}" if utsatt else f"Runde {runde}")
        ref = (f"runde {k0['forrige']} var spilt ({k0['forrige_kamp']}, ferdig {_klokke(datetime.fromisoformat(k0['forrige_slutt']))})"
               if k0.get("forrige_slutt") else "runden før var spilt")
        if not med:
            hvor_mange = "ingen odds ennå" if len(ks) == 1 else f"odds for 0 av {len(ks)} kamper ennå"
            linjer.append(f"{navn}: {hvor_mange}; alarm et døgn etter at {ref}")
            continue
        maalt = [k for k in med if not k.get("alt_ved_forste") and k.get("forrige_slutt")]
        tekst = (f"{navn}: odds for kampen" if len(ks) == 1 else
                 f"{navn}: odds for {'alle' if len(med) == len(ks) else str(len(med)) + ' av'} {len(ks)} kamper")
        if maalt:
            tider = sorted((datetime.fromisoformat(k["odds_fra"]) - datetime.fromisoformat(k["forrige_slutt"])).total_seconds() for k in maalt)
            tekst += (f", {_varighet(tider[0])} etter at {ref}" if len(tider) == 1 else
                      f", den første {_varighet(tider[0])} og den siste {_varighet(tider[-1])} etter at {ref}")
        if len(maalt) < len(med):
            tekst += (" (hadde odds alt første gang vi så kamplisten)" if len(med) == 1
                      else f" ({len(med) - len(maalt)} hadde odds alt første gang vi så kamplisten)")
        linjer.append(tekst)
    return {"sesong": liste_tid.year, "oppdatert": liste_tid.isoformat(timespec="seconds"), "kamper": kamper}, linjer


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
        # En budsjettsperre er et VALG vi har tatt, ikke en feil. Gir vi
        # feilkode, regnes det daglige vedlikeholdet som mislykket, og
        # kjoringen proever igjen hver time resten av dagen uten at noe kan
        # bli bedre. Se ogsaa markedslisten lenger nede.
        stopp, hvorfor = oddspapi.budsjett_stopp()
        if stopp:
            print(f"  hopper over kamplisten: {hvorfor}")
            return 0
        return 1

    links, only_odds, only_csv = match_fixtures(rows, fixtures, load_name_map())
    # Bare kamper som ikke har startet: oddsen under en kamp kjenner stillingen.
    naa = datetime.now(timezone.utc).isoformat(timespec="seconds")[:19]
    kommende = [(r, f) for r, f in links if (r["home"], r["away"]) not in played
                and (f.get("startTime") or "")[:19] > naa]
    print(f"  {len(fixtures)} kamper hos OddsPapi, {len(kommende)} uspilte og koblet til terminlisten")
    # hasOdds (4.10.2026): OddsPapi sier selv om de har odds for kampen. Uten
    # slås den ikke opp (svaret er 404 "No historical odds found"); de samles
    # i én linje. Oddsen for en runde kommer når de ordinære kampene i runden
    # før er spilt (leaguedata.odds_forventet). Mangler en kamp fortsatt odds
    # et døgn etter det, er det en advarsel -- men bare når kamplisten er
    # hentet etter grensen, ellers vet vi ikke.
    import leaguedata
    liste_tid = LISTE_TID or datetime.now(timezone.utc)
    try:
        forventet = leaguedata.odds_forventet(alle_kamper())
        dagens = {(m["home"], m["away"]): m for m in alle_kamper()}
    except Exception as e:
        print(f"  (runde-tidslinjen kunne ikke leses: {type(e).__name__}: {e})")
        forventet, dagens = {}, {}
    uten = [(r, f) for r, f in kommende if f.get("hasOdds") is False]
    kommende = [(r, f) for r, f in kommende if f.get("hasOdds") is not False]
    if uten:
        datoer = [(dagens.get((r["home"], r["away"])) or r)["date"] for r, _ in uten]
        print(f"  OddsPapi har ikke odds ennå for {len(uten)} kamper, {_dagspenn(datoer)}")
    for_gammel = []
    for r, f in uten:
        fv = forventet.get((r["home"], r["away"]))
        if not fv or now < fv["alarm"]:
            continue
        if liste_tid >= fv["alarm"]:
            melding = (f"OddsPapi har fortsatt ikke odds for {r['home']} mot {r['away']}, mer enn et døgn etter at "
                       f"runde {fv['forrige']} var spilt ({fv['kamp']}, ferdig {_klokke(fv['slutt'])})")
            print(f"  ADVARSEL: {melding}")
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::warning title=OddsPapi: odds mangler::{melding}")
        else:
            for_gammel.append(f"{r['home']} mot {r['away']}")
    if for_gammel:
        print(f"  {len(for_gammel)} kamp(er) uten odds etter alarmgrensen, men kamplisten er fra {_klokke(liste_tid)}, "
              f"før grensen -- avgjøres når den er hentet på nytt: {', '.join(for_gammel[:4])}")
    # Når oddsen kom, per runde, for kampene i vinduet.
    try:
        gml_aapning = json.loads(AAPNING_PATH.read_text(encoding="utf-8")) if AAPNING_PATH.exists() else {}
    except Exception:
        gml_aapning = {}
    # Runde, dato og avspark fra terminlisten slik den er nå (CSV-en har de
    # opprinnelige datoene).
    koblet = [(dict(r, **{n: v for n, v in (dagens.get((r["home"], r["away"])) or {}).items() if n in ("round", "date", "time")}), f)
              for r, f in kommende + uten]
    aapning, aapning_linjer = oddsaapning(koblet, forventet, liste_tid, gml_aapning)
    for l in aapning_linjer:
        print(f"  {l}")
    AAPNING_PATH.write_text(json.dumps(aapning, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for x in only_odds:
        print(f"  BARE HOS ODDSPAPI: {x}")

    mkt = find_1x2(fetch_markets(key))
    mkt_id = (mkt or {}).get("marketId") or (mkt or {}).get("id")
    if mkt_id is None:
        # En BUDSJETTSPERRE er ikke en feil: vi har med vilje bestemt at vi
        # ikke skal bruke flere tellende kall i dag. Gir vi feilkode her,
        # regnes det daglige vedlikeholdet som mislykket, og kjoringen proever
        # igjen hver time resten av dagen uten at noe kan bli bedre.
        stopp, hvorfor = oddspapi.budsjett_stopp()
        if stopp:
            print(f"  hopper over odds: {hvorfor}")
            return 0
        print("  fant ikke 1X2-markedet -- henter ingen odds")
        return 1

    ut = []
    for r, f in kommende:
        params = {"fixtureId": f.get("fixtureId"), "bookmakers": ",".join(BOOKMAKERS)}
        # call_retry følger serverens egen ventetid ved 429. En fast pause og
        # ett forsøk til holdt ikke: da samme kjøring nettopp hadde hentet
        # sluttodds fra samme endepunkt, falt seks av åtte kamper ut.
        # Bare uspilte kamper her (kommende), saa 404 "No historical odds
        # found" betyr at markedet ikke er aapnet ennaa -- logges som hoppet,
        # ikke feil. Det var den eneste grunnen til at kildevakten meldte
        # oddspapi-historical-odds som ute i OBOS-jobben.
        svar, err = oddspapi.call_retry("/v4/historical-odds", params, key,
                                        ikke_funnet_er_hoppet=True)
        if err:
            if str(err).startswith("HTTP 404") and "No historical odds found" in str(err):
                melding = f"{r['home']} mot {r['away']}: OddsPapi sier at kampen har odds (hasOdds), men oppslaget gir 404"
                print(f"  ADVARSEL: {melding}")
                if os.environ.get("GITHUB_ACTIONS"):
                    print(f"::warning title=OddsPapi: 404 med hasOdds::{melding}")
            else:
                print(f"  {r['home']} mot {r['away']}: FEIL {err}")
            time.sleep(COOLDOWN)
            continue
        bm, odds, stamp = closing_from(svar or {},
            market_id=mkt_id, kickoff=f.get("startTime"))   # aldri priser etter avspark
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
            # Desimaloddsen slik bookmakeren satte den, med margin. Bare til
            # visning: sannsynlighetene over er marginfrie, som før.
            "odds": {"H": odds["H"], "U": odds["U"], "B": odds["B"]},
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
