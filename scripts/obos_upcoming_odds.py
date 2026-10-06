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

Varselet (7.10.2026): mangler en uspilt kamp odds når det er under et døgn
til avspark, skrives en ADVARSEL (og ::warning i GitHub Actions). Ingen
linje når alt er i orden. Se varsle_manglende_odds().

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
# Varselet: en kamp uten odds når det er så kort tid til avspark.
VARSEL_FOR = timedelta(hours=24)
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
    if SEASON_CACHE.exists() and not force:
        d = json.loads(SEASON_CACHE.read_text(encoding="utf-8"))
        alder = datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched_at"])
        if alder < timedelta(hours=SEASON_CACHE_HOURS):
            i_vinduet = [f for f in (d.get("fixtures") or [])
                         if frm <= (f.get("startTime") or "")[:10] <= to]
            print(f"  terminliste fra sesonglisten ({len(i_vinduet)} kamper i vinduet, "
                  f"{int(alder.total_seconds()/3600)} t gammel, 0 tellende kall)")
            return i_vinduet
    print("  sesonglisten mangler eller er for gammel -- henter vinduet (1 tellende kall)")
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


def _klokke(t):
    from zoneinfo import ZoneInfo
    t = t.astimezone(ZoneInfo("Europe/Oslo"))
    return f"{t.day}.{t.month}. kl. {t.strftime('%H.%M')}"


def alle_kamper():
    """Hele sesongen med dagens datoer (matches.json og fixtures.json), ikke
    CSV-en: den har de opprinnelige datoene, også for flyttede kamper."""
    spilt = json.loads((DATA / "matches.json").read_text(encoding="utf-8"))
    fx = json.loads((DATA / "fixtures.json").read_text(encoding="utf-8"))
    sett = {(m["home"], m["away"]) for m in spilt}
    return [dict(m) for m in spilt] + [dict(m, round=r["round"]) for r in fx for m in r["matches"]
                                       if (m["home"], m["away"]) not in sett]


def manglende_odds(naa, kamper, med_odds):
    """Uspilte kamper med avspark innen VARSEL_FOR (og ikke startet) som ikke
    har odds. kamper: [{home, away, date, time, hg}] som alle_kamper();
    med_odds: {(hjemme, borte)}. Uten klokkeslett regnes avspark fra
    midnatt, så varselet heller kommer for tidlig enn for sent. Returnerer
    [(kamp, avspark)] i avsparkrekkefølge."""
    from zoneinfo import ZoneInfo
    oslo = ZoneInfo("Europe/Oslo")
    ut = []
    for m in kamper:
        if m.get("hg") is not None or (m["home"], m["away"]) in med_odds:
            continue
        a = datetime.fromisoformat(f"{m['date']}T{m.get('time') or '00:00'}:00").replace(tzinfo=oslo)
        if naa < a <= naa + VARSEL_FOR:
            ut.append((m, a))
    return sorted(ut, key=lambda x: x[1])


def _om(a, naa):
    """"23 t", "45 min"."""
    sek = (a - naa).total_seconds()
    return f"{int(sek // 3600)} t" if sek >= 3600 else f"{max(1, int(sek // 60))} min"


def varsle_manglende_odds(naa, grunner, played):
    """ADVARSEL for hver uspilt kamp uten odds i odds_upcoming.json (det
    siden bruker) når det er under et døgn til avspark, med grunnen når
    kjøringen vet den (grunner[(hjemme, borte)], ellers grunner["*"]).
    Ingen linje når alt er i orden.

    Erstatter (7.10.2026) målingen av når OddsPapi fikk oddsen, i forhold til
    når runden før var spilt (odds_aapning.json, 4.10.): med varselet et døgn
    før avspark spiller det ingen rolle hvor lenge det er mellom rundene."""
    try:
        kamper = [m for m in alle_kamper() if (m["home"], m["away"]) not in played]
    except Exception as e:
        print(f"  ADVARSEL: terminlisten kunne ikke leses, så manglende odds er ikke sjekket ({type(e).__name__}: {e})")
        return
    med = {(m["home"], m["away"]) for m in les_gammel().get("matches", [])}
    for m, a in manglende_odds(naa, kamper, med):
        grunn = grunner.get((m["home"], m["away"])) or grunner.get("*")
        melding = (f"{m['home']} mot {m['away']} har ikke odds, og det er {_om(a, naa)} til avspark ({_klokke(a)})"
                   + (f": {grunn}" if grunn else ""))
        print(f"  ADVARSEL: {melding}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=OddsPapi: odds mangler før avspark::{melding}")


def main():
    grunner, played = {}, set()
    kode = hent(grunner, played)
    varsle_manglende_odds(datetime.now(timezone.utc), grunner, played)
    return kode


def hent(grunner, played):
    """Henter oddsen og skriver odds_upcoming.json. Fyller grunner med hvorfor
    en kamp mangler odds, og played med de spilte kampene, til varselet."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14, help="hvor langt fram vi henter (to uker: OBOS har ofte ti dager mellom rundene)")
    ap.add_argument("--refresh", action="store_true", help="se bort fra mellomlageret")
    args = ap.parse_args()

    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    rows = csv_2026()
    played.update((m["home"], m["away"]) for m in rows if m["hg"] is not None)
    gammel = les_gammel()

    if not key:
        print("ODDSPAPI_KEY er ikke satt.")
        grunner["*"] = "oddsen ble ikke hentet (ODDSPAPI_KEY er ikke satt)"
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
            grunner["*"] = f"oddsen ble ikke hentet ({hvorfor})"
            return 0
        grunner["*"] = "kamplisten fra OddsPapi kunne ikke hentes"
        return 1

    links, only_odds, only_csv = match_fixtures(rows, fixtures, load_name_map())
    # Bare kamper som ikke har startet: oddsen under en kamp kjenner stillingen.
    naa = datetime.now(timezone.utc).isoformat(timespec="seconds")[:19]
    kommende = [(r, f) for r, f in links if (r["home"], r["away"]) not in played
                and (f.get("startTime") or "")[:19] > naa]
    print(f"  {len(fixtures)} kamper hos OddsPapi, {len(kommende)} uspilte og koblet til terminlisten")
    # hasOdds (4.10.2026): OddsPapi sier selv om de har odds for kampen. Uten
    # slås den ikke opp (svaret er 404 "No historical odds found"), og det
    # skrives ingen linje: at kamper langt fram mangler odds, er normalt.
    # Varselet et døgn før avspark tar dem som fortsatt mangler.
    uten = [(r, f) for r, f in kommende if f.get("hasOdds") is False]
    kommende = [(r, f) for r, f in kommende if f.get("hasOdds") is not False]
    for r, _ in uten:
        grunner[(r["home"], r["away"])] = "OddsPapi har ikke odds for kampen ennå"
    koblet = {(r["home"], r["away"]) for r, _ in links}
    for r in rows:
        if (r["home"], r["away"]) not in koblet:
            grunner.setdefault((r["home"], r["away"]), "kampen finnes ikke i kamplisten hos OddsPapi")
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
            grunner["*"] = f"oddsen ble ikke hentet ({hvorfor})"
            return 0
        print("  fant ikke 1X2-markedet -- henter ingen odds")
        grunner["*"] = "fant ikke 1X2-markedet hos OddsPapi"
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
                grunner[(r["home"], r["away"])] = "OddsPapi sier at kampen har odds, men oppslaget gir 404"
            else:
                print(f"  {r['home']} mot {r['away']}: FEIL {err}")
                grunner[(r["home"], r["away"])] = f"oppslaget feilet ({err})"
            time.sleep(COOLDOWN)
            continue
        bm, odds, stamp = closing_from(svar or {},
            market_id=mkt_id, kickoff=f.get("startTime"))   # aldri priser etter avspark
        if not bm:
            print(f"  {r['home']} mot {r['away']}: ingen odds fra {', '.join(BOOKMAKERS)}")
            grunner[(r["home"], r["away"])] = f"ingen odds fra {', '.join(BOOKMAKERS)}"
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
