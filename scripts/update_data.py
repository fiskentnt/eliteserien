#!/usr/bin/env python3
"""Bygger data/matches.json og data/fixtures.json for Eliteserien 2026.

To kilder, ingen nøkler:
  - ffksupporter.net (ffk_source.py): fasit. Har hele sesongens kampoppsett
    (runde + dato for alle 240 kamper), og resultat for de som er spilt.
  - ESPN sitt åpne API (espn_source.py): raskere med ferske resultater, men
    har vist seg å kunne gi feil resultat for enkeltkamper. Brukes derfor kun
    til å fylle inn resultater ffksupporter ikke har lagt inn ennå.

Kjøres av GitHub Actions-workflowen (.github/workflows/update-data.yml) og
lokalt for verifisering. Skriver kun til disk — commit/push håndteres av
workflowen (kun hvis noe faktisk endret seg).
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import ffk_source
import espn_source
import should_fetch
import ntf_source
import nff_source
from reconcile_ny import (bare_aktiv_sesong, behold_eksisterende, bekreft_datoer,
                          reconcile as reconcile_kilder, rimelige_datoer, uten_lagret_dato)
import flytting
import fetch_odds_history
import merge_odds
import fit_model
import leaguedata

ROOT = Path(__file__).parent.parent
LEAGUE = ROOT / "eliteserien"  # ligamappen (data/ ligger under den, så flere ligaer kan komme ved siden av)
OSLO = ZoneInfo("Europe/Oslo")

FFK_CACHE_PATH = LEAGUE / "data" / "ffk_cache.json"
LIGA = "eliteserien"
FFK_MIN_INTERVAL_MIN = 60  # ffksupporter.net skrapes (16 sider) maks én gang i timen
STATUS_PATH = LEAGUE / "data" / "status.json"
AUDIT_STATE_PATH = LEAGUE / "data" / "audit_state.json"
# Advarsler fra denne kjøringen (17.10.2026): datovakten (over 25 % av datoene
# utenfor sesongen) og ESPN-data som ikke kan tolkes. De gjør ikke rødt, men
# står i status.json og går med livstegnet (write_status). Nullstilles i main.
KJORINGENS_ADVARSLER = []


DATOVAKT_BESKJED = {
    "ingen_autoritet": (
        "Sesongregisteret (data/sesonger.json) mangler, kan ikke leses eller "
        "har ingen aktiv sesong for ligaen. Uten det kan datovakten ikke "
        "kontrollere datoene, så ingenting er skrevet. Kjør: "
        "python3 scripts/sesong.py . init <liga> <år>"),
    "ingen_runder": (
        "De lagrede kampene mangler rundenummer, så sesongvinduet kan ikke "
        "regnes og datovakten ikke kontrollere datoene. Ingenting er skrevet. "
        "Sjekk matches.json og fixtures.json."),
    "sesongskifte_mangler": (
        "Terminlisten er for en annen sesong enn registeret sier. "
        "Sesongskiftet er ikke kjørt, så datovakten sto over -- den ville "
        "ellers skrevet hele den nye sesongen tilbake til fjorårets datoer. "
        "Ingenting er skrevet. Kjør: python3 scripts/sesong.py . bytt --utfor"),
}


class DataAuditError(Exception):
    """Avvik funnet i den daglige kontrollen mot ffksupporter.net (se
    run_daily_audit). Skal feile kjøringen synlig, som EspnDataError."""
    pass


def reconcile(ntf_rows, nff_rows, ffk_rows, espn_rows, log=lambda s: None):
    """Ligasiden er fasit for terminliste, runde, dato og avspark.
    fotball.no er uavhengig offisiell kontroll og reserve. ffksupporter er
    degradert til siste utvei, ESPN er resultatkontroll. Se reconcile_ny.py."""
    return reconcile_kilder(
        ntf_rows, nff_rows,
        reserver=[("ffksupporter", ffk_rows)],
        resultatkontroll=[("ESPN", espn_rows)],
        log=log)


def reconcile_gammel(ffk_rows, espn_rows, log=lambda s: None):
    """Slår sammen kilder per kamp (nøkkel: lagpar, unikt i en dobbel serie).
    Runde og dato kommer alltid fra ffksupporter (har hele sesongoppsettet).
    Resultat: ffksupporter hvis satt, ellers ESPN. Uenighet mellom kildene
    når begge har et resultat logges, men ffksupporter vinner alltid."""
    espn_by_pair = {(r["home"], r["away"]): r for r in espn_rows}

    merged = []
    for r in ffk_rows:
        pair = (r["home"], r["away"])
        espn = espn_by_pair.get(pair)
        hg, ag, src = r["hg"], r["ag"], "ffk"

        if hg is None and espn and espn["hg"] is not None:
            if espn.get("suspect"):
                log(f"ADVARSEL: ESPN har mistenkelig resultat for {pair} (0-0 med vinner merket), "
                    f"hopper over og venter på ffksupporter.net")
            else:
                hg, ag, src = espn["hg"], espn["ag"], "espn"
        elif hg is not None and espn and espn["hg"] is not None and (hg, ag) != (espn["hg"], espn["ag"]):
            log(f"ADVARSEL: uenighet for {pair} runde {r['round']}: "
                f"ffksupporter={hg}-{ag} ESPN={espn['hg']}-{espn['ag']} — bruker ffksupporter")

        merged.append({"date": r["date"], "time": r.get("time"), "round": r["round"], "home": r["home"],
                        "away": r["away"], "hg": hg, "ag": ag, "src": src if hg is not None else None})
    return merged


def build(merged):
    """matches.json og fixtures.json. Reglene er felles for ligaene, se
    scripts/leaguedata.py."""
    return leaguedata.build_matches(merged), leaguedata.build_fixtures(merged)


def write_json(path, data):
    leaguedata.write_json(path, data)


def dagens_revisjonsavvik(now):
    """Antall kritiske avvik i DAGENS revisjon, eller 0 hvis den ikke er
    kjørt i dag.

    Revisjonen kjører én gang per kalenderdag. Finner den et kritisk avvik,
    feiler kjøringen og stempelet blir rødt -- men NESTE kjøring samme dag
    hopper over revisjonen, og uten dette ville den skrevet ok=True og gjort
    stempelet grønt igjen mens avviket fortsatt sto. Med en utløser hvert
    tiende minutt ville det skjedd innen en time."""
    if not AUDIT_STATE_PATH.exists():
        return 0
    try:
        st = json.loads(AUDIT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if st.get("checked_date") != now.astimezone(OSLO).strftime("%Y-%m-%d"):
        return 0
    return int(st.get("errors") or 0)


# Høyst så mange advarsler i audit_state.json og status.json.
ADVARSLER_MAKS = 10


def dagens_revisjonsadvarsler(now):
    """Advarslene fra DAGENS kontroll mot ffksupporter.net (17.10.2026), til
    status.json og livstegnet: et resultat kilden mangler, men en annen
    uavhengig kilde bekrefter, eller at kilden har stoppet. Gjør aldri rødt."""
    try:
        st = json.loads(AUDIT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if st.get("checked_date") != now.astimezone(OSLO).strftime("%Y-%m-%d"):
        return []
    return [str(a) for a in st.get("advarsler") or []]


def ligasiden_eller_reserve(cache_dir=None, log=lambda s: None):
    """Kampene fra ligasiden. RESERVE (regelen fra 1.10.2026, se
    nff_source.py): BARE naar ligasiden ikke svarer, hentes fotball.no --
    hoeyst ett forsok per dogn, ellers det som ligger i cachen. Svarer
    ligasiden, men vi ikke forstaar den, er det en feil hos oss, og den skal
    ikke skjules bak en annen kilde."""
    global LIGAKILDE
    try:
        rader = ntf_source.fetch_all(LIGA, cache_dir=cache_dir, log=log)
        LIGAKILDE = "ligasiden"
        return rader
    except Exception as e:
        log(f"ADVARSEL: ligasiden feilet ({type(e).__name__}: {e}).")
        # RESERVEKJEDEN (3.10.2026, terminliste_reserve.py): kalenderfeeden,
        # ESPN, Highlightly og til slutt den siste gyldige terminlisten.
        # Feilen hos ligasiden står i hentelogget og gjør kjøringen rød der.
        import sesong as _ses
        forrige = leaguedata.forrige_terminliste(LEAGUE / "data", _ses.aktiv_sesong(ROOT, LIGA, log=log), log=log)
        from ligaer import ANTALL_KAMPER
        if forrige and len(forrige) == ANTALL_KAMPER:
            import terminliste_reserve
            rader, LIGAKILDE = terminliste_reserve.kjede(LIGA, forrige, datetime.now(timezone.utc), log=log)
            return rader
        # Uten den siste gyldige terminlisten: fotball.no bare når ligasiden
        # ikke svarer (krise). Svarer den, men kan ikke leses, er det en feil
        # hos oss, og den skal ikke skjules bak en annen kilde.
        if not isinstance(e, ntf_source.SvarerIkke):
            raise
        log("ADVARSEL: ligasiden svarte ikke -- bruker fotball.no som reserve.")
        rader = nff_source.fetch_all(LIGA, log=log)
        if not rader:
            raise
        LIGAKILDE = "fotball.no"
        return rader


# Hvilken kilde ligasiden_eller_reserve() ga radene fra: "ligasiden", eller
# "fotball.no" når ligasiden ikke svarte. Samme leverandør (NTF) i
# resultatregel.py, men fotball.no er ikke den offisielle ligasiden.
LIGAKILDE = "ligasiden"
STATE = LEAGUE / "data" / "results_state.json"


def kontroller_nye_resultater(merged, tidligere, liga_rader, espn_rader, ffk_rader, now, log=lambda s: None,
                              hl_dag=None, espn_sesong=None, state_sti=None, hl_bruk=None):
    """Regelen i resultatregel.py for resultatene som er NYE i denne
    kjøringen: stemmene (17.10.2026), ett resultat publiseres når minst to
    leverandører er enige og ingen annen stilling har like mange. Ligasiden
    kan bli overstemt (advarsel, "overstemt" i tilstanden), og en kamp som er
    over, publiseres også før ligasiden har resultatet når ESPN og Highlightly
    er enige. Bare ferdigspilte kamper gir stemme: ESPN completed og ikke
    "suspect", Highlightly "Finished". Ellers står kampen som uspilt (vent)
    eller holdes tilbake (konflikt). Publiserte resultater røres ikke
    (behold_eksisterende). Bare ligasiden kan publisere alene, etter 24
    timer, og står da som ukontrollert i results_state.json til ESPN,
    Highlightly eller ffksupporter bekrefter det.

    Kildene: ligasiden (eller fotball.no, LIGAKILDE), ESPN (hele sesongen i
    ett kall, siden dagens rundetavle ikke ser en kamp fra i går), Highlightly
    (per dato, ett kall per kampdag), ffksupporter. hl_dag og espn_sesong kan
    byttes ut i testene. Returnerer (merged, state).

    Loggen (4.10.2026): én linje per nytt resultat, også når det holdes
    tilbake (resultatregel.resultatlinje), og når hver kilde først hadde
    resultatet (resultatregel.forst_sett). For det siste spørres Highlightly
    også for kamper som er over, men ikke har resultat ennå, bare under
    highlightly_source.LOGG_TAK kall i døgnet (hl_bruk teller dem; byttes i
    testene). Regelen for publisering endres ikke."""
    import resultatregel
    hl_dag = hl_dag or (lambda d: __import__("highlightly_source").hent_dag(d, ligaer=("eliteserien",))["eliteserien"])
    espn_sesong = espn_sesong or (lambda aar: espn_source.fetch_season(aar, log=log))
    state_sti = state_sti or STATE
    try:
        gml = json.loads(state_sti.read_text(encoding="utf-8"))
    except Exception:
        gml = {}
    ukontr = {tuple(k.split("|")): tuple(v) for k, v in (gml.get("ukontrollert") or {}).items()}
    sist = gml.get("ukontrollert_sjekket")
    sjekk_ukontr = bool(ukontr) and (not sist or now - datetime.fromisoformat(sist) >= timedelta(hours=1))

    publisert = {(m["home"], m["away"]) for m in tidligere if m.get("hg") is not None}
    nye = [r for r in merged if r.get("hg") is not None and (r["home"], r["away"]) not in publisert]
    resultat = lambda rader: {(r["home"], r["away"]): (r["hg"], r["ag"]) for r in rader
                              if r.get("hg") is not None and not r.get("suspect")}

    def _avspark(r):
        try:
            return _kickoff_utc(r["date"], r["time"]) if r.get("time") else None
        except Exception:
            return None
    # Kamper som er over (105 minutter etter avspark, som porten) uten
    # publisert resultat: til loggen over hvilken kilde som har det først.
    ventende = [r for r in merged if (r["home"], r["away"]) not in publisert and _avspark(r)
                and now - timedelta(days=3) <= _avspark(r) <= now - timedelta(minutes=105)]
    forst_gml = {n: v for n, v in (gml.get("forst_sett") or {}).items() if tuple(n.split("|")) not in publisert}
    # Publisert før (også før ligasiden hadde resultatet), og ligasiden viser
    # nå noe annet: overstemt når resultatet vårt er bekreftet utenfor NTF
    # (resultatregel.overstemt_etterpaa, 17.10.2026).
    vaare_pub = {(m["home"], m["away"]): (m["hg"], m["ag"]) for m in tidligere if m.get("hg") is not None}
    _bekr0 = resultatregel.bekreftet_tilstand(gml.get("bekreftet"), {}, now)
    _lig0 = resultat(liga_rader)
    # behold_eksisterende bruker ligasidens NYE resultat når den endrer et
    # publisert. Er vårt bekreftet utenfor NTF (eller kampen alt overstemt),
    # beholdes vårt: ligasiden er én stemme mot to (17.10.2026).
    _etter = resultatregel.overstemt_etterpaa(vaare_pub, _lig0, _bekr0)
    _behold = set(_etter) | {tuple(n.split("|")) for n, v in (gml.get("overstemt") or {}).items()
                             if tuple(v.get("resultat") or ()) == vaare_pub.get(tuple(n.split("|")))}

    def _vaart_resultat(r):
        k = (r["home"], r["away"])
        if (k in _behold and r.get("hg") is not None and vaare_pub.get(k)
                and (r["hg"], r["ag"]) != vaare_pub[k]):
            log(f"  ADVARSEL {k[0]}-{k[1]}: ligasiden viser nå {r['hg']}-{r['ag']}, beholder "
                f"{vaare_pub[k][0]}-{vaare_pub[k][1]} (bekreftet utenfor NTF, ligasiden overstemt)")
            return {**r, "hg": vaare_pub[k][0], "ag": vaare_pub[k][1], "src": "overstemt"}
        return r
    merged = [_vaart_resultat(r) for r in merged]
    if not nye and not sjekk_ukontr and not ventende:
        return merged, {"conflicts": [], "waiting": [], "ukontrollert": ukontr, "ukontrollert_sjekket": sist,
                        "forst_sett": forst_gml,
                        "bekreftet": _bekr0,
                        "overstemt": resultatregel.overstemt_tilstand(gml.get("overstemt"), _etter, _lig0, now)}

    kilder = {LIGAKILDE: resultat(liga_rader), "ffksupporter": resultat(ffk_rader) if ffk_rader else None}
    try:
        espn = espn_sesong(now.astimezone(OSLO).year)
        kilder["espn"] = resultat(espn)
    except Exception as e:
        log(f"  ESPN (sesongen) feilet ({type(e).__name__}: {e}) -- fortsetter uten")
        kilder["espn"] = resultat(espn_rader) if espn_rader else None
    datoer = {r["date"] for r in nye} | ({m["date"] for m in tidligere if (m["home"], m["away"]) in ukontr}
                                         if sjekk_ukontr else set())
    ekstra = {r["date"] for r in ventende} - datoer
    if ekstra:
        try:
            bruk = (hl_bruk or __import__("highlightly_source").dagsbruk)()
            if bruk < __import__("highlightly_source").LOGG_TAK:
                datoer |= ekstra
            else:
                log(f"  Highlightly: {bruk} kall i dag, over LOGG_TAK: spør ikke bare for loggen")
        except Exception:
            pass
    datoer = sorted(datoer)
    hl, svarte = {}, False
    for d in datoer:
        try:
            hl.update(resultat([r for r in hl_dag(d) if r.get("ferdig")]))
            svarte = True
        except Exception as e:
            log(f"  Highlightly {d}: {type(e).__name__}: {e}")
    kilder["highlightly"] = hl if svarte else None
    oppe = {k for k, v in kilder.items() if v is not None}

    waiting, conflicts, nye_ukontr, linjer = [], [], {}, []
    # Hvilke kilder utenfor NTF som hadde resultatet da det ble publisert
    # (12.10.2026), til tabellkontrollen rett etter kampslutt.
    nye_bekr = {}
    # Publisert mot ligasidens stemme (17.10.2026): advarsel, og tabellkontrollen
    # fører kampen som venter så lenge ligasiden er uenig.
    nye_overstemt = {}
    ut = []
    nye_k = {(r["home"], r["away"]) for r in nye}
    for r in merged:
        k = (r["home"], r["away"])
        if r.get("hg") is None or k in publisert:
            # Over, men ligasiden har ikke resultatet: stemmene avgjør likevel
            # (17.10.2026). To enige kilder utenfor NTF publiserer; uten kontroll
            # (bare ligasiden) gjelder bare når ligasiden har det.
            if k not in publisert and r in ventende:
                svar = {kilde: v[k] for kilde, v in kilder.items() if v and k in v}
                if svar:
                    u = resultatregel.avgjor("eliteserien", svar, oppe, avspark=_avspark(r), naa=now)
                    linjer.append(resultatregel.resultatlinje("eliteserien", k, u, svar))
                    if u["utfall"] == "publiser" and not u["ukontrollert"]:
                        ut.append({**r, "hg": u["resultat"][0], "ag": u["resultat"][1], "src": u["hoved"]})
                        nye_bekr[k] = (u["resultat"], resultatregel.uavhengige_enige(svar, u["resultat"]))
                        log(f"  {k[0]}-{k[1]}: {u['grunn']}, publisert før ligasiden har resultatet")
                        continue
            ut.append(r)
            continue
        avspark = _avspark(r)
        svar = {kilde: v[k] for kilde, v in kilder.items() if v and k in v}
        u = resultatregel.avgjor("eliteserien", svar, oppe, avspark=avspark, naa=now)
        linjer.append(resultatregel.resultatlinje("eliteserien", k, u, svar))
        hvem = f"{k[0]}-{k[1]}"
        if u["utfall"] == "publiser":
            ut.append({**r, "hg": u["resultat"][0], "ag": u["resultat"][1]})
            if u["ukontrollert"]:
                nye_ukontr[k] = u["resultat"]
            else:
                nye_bekr[k] = (u["resultat"], resultatregel.uavhengige_enige(svar, u["resultat"]))
            if u["overstemt"] and svar.get(LIGAKILDE) is not None:
                nye_overstemt[k] = (u["resultat"], svar[LIGAKILDE], resultatregel.uavhengige_enige(svar, u["resultat"]))
                log(f"  ADVARSEL {hvem}: publisert {u['resultat'][0]}-{u['resultat'][1]} mot ligasidens "
                    f"{svar[LIGAKILDE][0]}-{svar[LIGAKILDE][1]} ({u['grunn']})")
            if u["uenige"] or u["ukontrollert"]:
                log(f"  {hvem}: {u['grunn']}")
            continue
        (conflicts if u["utfall"] == "konflikt" else waiting).append(f"{hvem}: {u['grunn']}")
        ut.append({**r, "hg": None, "ag": None, "src": None})
    if sjekk_ukontr:
        svar_pk = {k: {kilde: v[k] for kilde, v in kilder.items() if v and k in v} for k in ukontr}
        ukontr, bekreftet, uenige = resultatregel.kontroller_ukontrollerte("eliteserien", ukontr, svar_pk)
        for k in bekreftet:
            log(f"  {k[0]}-{k[1]}: publisert uten kontroll, nå bekreftet")
            _r = next(((m["hg"], m["ag"]) for m in tidligere if (m["home"], m["away"]) == k), None)
            if _r is not None:
                nye_bekr[k] = (_r, resultatregel.uavhengige_enige(svar_pk.get(k), _r))
        for k, rr, uavh in uenige:
            conflicts.append(f"{k[0]}-{k[1]}: publisert {rr[0]}-{rr[1]} uten kontroll, men "
                             + ", ".join(f"{kilde} har {v[0]}-{v[1]}" for kilde, v in uavh.items()))
    ukontr.update(nye_ukontr)
    for c in conflicts:
        log(f"  KONFLIKT {c}")
    for w in waiting:
        log(f"  venter: {w}")
    # Én linje per nytt resultat, og når hver kilde først hadde det (4.10.2026).
    if linjer:
        log("  Resultatene:")
        for l2 in linjer:
            log(f"    {l2}")
    aktuelle = nye_k | {(r["home"], r["away"]) for r in ventende}
    forst, forst_linjer = resultatregel.forst_sett(
        forst_gml, {k: {kilde: (v or {}).get(k) for kilde, v in kilder.items()} for k in aktuelle}, now, publisert)
    if forst_linjer:
        log("  Først hos kilden (kjøringen som så det):")
        for l2 in forst_linjer:
            log(f"    {l2}")
    _bekr = resultatregel.bekreftet_tilstand(gml.get("bekreftet"), nye_bekr, now)
    for k, v in resultatregel.overstemt_etterpaa(vaare_pub, kilder.get(LIGAKILDE), _bekr).items():
        nye_overstemt.setdefault(k, v)
    return ut, {"conflicts": conflicts, "waiting": waiting, "ukontrollert": ukontr,
                "ukontrollert_sjekket": now.isoformat(timespec="seconds") if sjekk_ukontr else sist,
                "forst_sett": forst,
                "bekreftet": _bekr,
                "overstemt": resultatregel.overstemt_tilstand(gml.get("overstemt"), nye_overstemt,
                                                              kilder.get(LIGAKILDE), now)}


def skriv_state(state, now, state_sti=None):
    (state_sti or STATE).write_text(json.dumps({
        "checked_at": now.isoformat(timespec="seconds"),
        "conflicts": state["conflicts"], "waiting": state["waiting"],
        "ukontrollert": {f"{k[0]}|{k[1]}": list(v) for k, v in state["ukontrollert"].items()},
        "ukontrollert_sjekket": state["ukontrollert_sjekket"],
        "forst_sett": state.get("forst_sett") or {},
        # Kildene utenfor NTF som hadde resultatet da det ble publisert
        # (resultatregel.bekreftet_tilstand), til tabellkontrollen.
        "bekreftet": state.get("bekreftet") or {},
        # Publisert mot ligasidens stemme, så lenge ligasiden er uenig
        # (resultatregel.overstemt_tilstand, 17.10.2026).
        "overstemt": state.get("overstemt") or {},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_status(ok, now, error=None):
    """data/status.json -- leses av index.html sitt stempel. Skrives KUN her,
    dvs. bare når update_data.py faktisk har kjørt (ikke når should_fetch.py
    avsluttet kjøringen tidlig uten å hente noe), slik at "Sist sjekket" i
    stempelet bare oppdateres ved reelle sjekker.

    Dagens revisjon er sannhetskilden for om stempelet kan være grønt: står
    det kritiske avvik fra revisjonen i dag, forblir det rødt uansett hvor
    fint resten av kjøringen gikk. Det blir grønt igjen først når en NY
    revisjon faktisk bekrefter at avviket er borte."""
    avvik = dagens_revisjonsavvik(now)
    # Terminlisterevisjonen (daglig_revisjon.py) skriver sin egen tilstand.
    # Den maa med her, ellers ville denne kjoringen overskrevet et rodt
    # stempel med ok=True.
    try:
        import daglig_revisjon
        avvik += daglig_revisjon.dagens_avvik(LIGA, now)
    except Exception:
        pass
    # Tabellkontrollen (tabellkontroll.py) likedan: et rodt stempel fra den
    # skal ikke overskrives av neste kjoring.
    try:
        import tabellkontroll
        avvik += tabellkontroll.avvik(LIGA)
    except Exception:
        pass
    if ok and avvik:
        ok = False
        error = error or (f"{avvik} kritisk(e) avvik i dagens revisjon står "
                          f"fortsatt uløst (se audit_state.json)")
    data = {"last_checked": now.isoformat(timespec="seconds"), "ok": ok}
    if error:
        data["error"] = str(error)[:300]
    if avvik:
        data["revisjon_avvik"] = avvik
    # Advarsler fra dagens kontroll (17.10.2026): gjør ikke statusen rød, men
    # står her og går med livstegnet (livstegn.py).
    advarsler = list(KJORINGENS_ADVARSLER) + dagens_revisjonsadvarsler(now)
    # Resultater publisert mot ligasidens stemme (17.10.2026).
    try:
        import resultatregel
        advarsler = resultatregel.overstemt_tekster(LIGA, state_sti=STATE) + advarsler
    except Exception:
        pass
    if advarsler:
        data["advarsler"] = advarsler
    STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_ffk_rows(cache_dir, log):
    """Henter ffksupporter.net sine 16 sider maks én gang i timen (se
    FFK_MIN_INTERVAL_MIN) — resten av tiden gjenbrukes mellomlagrede rader
    fra forrige skraping (data/ffk_cache.json, committes av workflowen så den
    overlever til neste kjøring). ESPN (ett kall, se main()) dekker friskhet
    i mellomtiden; ffksupporter er fortsatt fasit når begge har et resultat."""
    cached = json.loads(FFK_CACHE_PATH.read_text(encoding="utf-8")) if FFK_CACHE_PATH.exists() else None
    now = datetime.now(timezone.utc)
    age_min = (now - datetime.fromisoformat(cached["fetched_at"])).total_seconds() / 60 if cached else None
    due = cached is None or age_min >= FFK_MIN_INTERVAL_MIN

    if due:
        try:
            rows, warnings = ffk_source.fetch_all(cache_dir=cache_dir, log=log)
            for key, prev, r in warnings:
                log(f"ADVARSEL ffksupporter: uenighet mellom lagenes sider for {key}: {prev} vs {r}")
            FFK_CACHE_PATH.write_text(json.dumps(
                {"fetched_at": now.isoformat(timespec="seconds"), "rows": rows}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            return rows
        except Exception as e:
            wait_msg = "venter til neste times-sjekk" if isinstance(e, ffk_source.RateLimited) else "prøver igjen neste kjøring"
            log(f"ADVARSEL: ffksupporter.net feilet ({e}) -- {wait_msg}.")
            if cached:
                log(f"Bruker mellomlagrede ffksupporter-data fra for {age_min:.0f} min siden i mellomtiden.")
                return cached["rows"]
            raise  # ingen mellomlagrede data å falle tilbake på -- da skal kjøringen faktisk feile synlig

    log(f"ffksupporter.net sjekket for {age_min:.0f} min siden (maks én gang i timen) -- bruker mellomlagrede data.")
    return cached["rows"]


def _kickoff_utc(date_str, time_str):
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=OSLO).astimezone(timezone.utc)


def _vaare_spilte(matches_out):
    """De spilte kampene med avspark som datetime (None uten gyldig tid), til
    resultatregel.revider_kilde og kilde_stoppet."""
    ut = []
    for m in matches_out:
        try:
            avspark = _kickoff_utc(m["date"], m["time"]) if m.get("time") else None
        except ValueError:
            avspark = None
        ut.append({**m, "avspark": avspark})
    return ut


def _ffk_resultater(ffk_rows):
    """{(hjemme, borte): (hg, ag) eller None} fra ffksupporter-radene."""
    return {(r["home"], r["away"]): ((r["hg"], r["ag"]) if r["hg"] is not None and r["ag"] is not None else None)
            for r in ffk_rows}


def kontroll_bekreftere(now, log=lambda s: None):
    """De uavhengige kildene som kan bekrefte et resultat ffksupporter.net
    mangler (17.10.2026), uten tellende kall:
      * football-data.co.uk: hele sesongen, hentet i dag av fetch_odds_history
        (odds_fd.json, før kontrollene i etter_skriving).
      * ESPN: hele sesongen i ett gratis kall. ESPN har hatt feil 0-0, men her
        teller bare nøyaktig samme resultat som vårt.
      * Kildene utenfor NTF som bekreftet resultatet da det ble publisert
        (results_state.json, "bekreftet", 48 timer).
    Kalles bare når ffksupporter mangler en kamp (resultatregel.revider_kilde).
    Returnerer {kilde: {(hjemme, borte): (hg, ag)}}."""
    ut = {}
    try:
        fd = json.loads((LEAGUE / "data" / "odds_fd.json").read_text(encoding="utf-8"))
        ut["football-data"] = {(m["home"], m["away"]): (m["hg"], m["ag"]) for m in fd.get("matches") or []
                               if m.get("hg") is not None and m.get("ag") is not None}
    except Exception as e:
        log(f"  kontrollen: football-data.co.uk kunne ikke leses ({type(e).__name__}: {e})")
    try:
        for n, v in (json.loads(STATE.read_text(encoding="utf-8")).get("bekreftet") or {}).items():
            for kilde in v.get("kilder") or []:
                ut.setdefault(kilde, {})[tuple(n.split("|"))] = tuple(v["resultat"])
    except Exception:
        pass
    try:
        import sesong as _ses
        aar = _ses.aktiv_sesong(ROOT, LIGA, log=lambda _s: None) or now.astimezone(OSLO).year
        ut.setdefault("espn", {}).update({(r["home"], r["away"]): (r["hg"], r["ag"])
                                          for r in espn_source.fetch_season(aar, log=log)
                                          if r.get("hg") is not None and r.get("ag") is not None})
    except Exception as e:
        log(f"  kontrollen: ESPN-sesongen kunne ikke hentes ({type(e).__name__}: {e})")
    return ut


def audit_against_ffk(matches_out, ffk_rows, now, bekreftere=None):
    """Sammenligner ALLE spilte kamper i matches_out (vår fasit akkurat nå,
    uansett hvilken kilde hvert resultat kom fra) mot ffksupporter.net sin
    egen liste (ffk_rows, fra denne kjøringens get_ffk_rows()), med regelen i
    resultatregel.revider_kilde (17.10.2026):
      1. Begge kilder har et resultat, men de er ULIKE -- feil med en gang.
      2. ffksupporter.net mangler resultatet (eller kampen), men en annen
         uavhengig kilde (kontroll_bekreftere) har samme resultat som oss --
         advarsel. ffksupporter oppdateres for hånd og ligger ofte etter.
         Før 17.10. ble dette rødt etter 72 timer uansett: KFUM Oslo-Vålerenga
         (12.10.) holdt statusen rød fra 16.10., og da varslet ingenting annet.
      3. Mangler den, og ingen uavhengig kilde bekrefter: advarsel til 72
         timer etter avspark, så feil.
      4. ffksupporter.net har et resultat vi mangler helt -- feil med en
         gang (et tegn på en reell feil i sammenslåingen).
    bekreftere: som i revider_kilde; uten hentes kontroll_bekreftere når
    det trengs. Returnerer (errors, warnings), begge lister med tekst."""
    import resultatregel
    matches_by_pair = {(m["home"], m["away"]): m for m in matches_out}
    errors, warnings = resultatregel.revider_kilde(
        "ffksupporter", _vaare_spilte(matches_out), _ffk_resultater(ffk_rows),
        bekreftere if bekreftere is not None else (lambda: kontroll_bekreftere(now)), now,
        navn="ffksupporter.net")

    for r in ffk_rows:
        if r["hg"] is None or r["ag"] is None:
            continue
        if (r["home"], r["away"]) not in matches_by_pair:
            errors.append(f"{r['home']}-{r['away']} ({r['date']}): kontrollkilden har {r['hg']}-{r['ag']}, vi mangler kampen helt")

    return errors, warnings


def run_daily_audit(matches_out, ffk_rows, now, log, bekreftere=None):
    """Én gang i døgnet: full kontroll av alle spilte kamper mot
    ffksupporter.net. Kjøres på den første kjøringen som når hit hver dag --
    egen dato-sperre her, ikke avhengig av noe bestemt klokkeslett. Kritiske
    avvik feiler kjøringen (stempelet blir rødt); et resultat ffksupporter
    mangler er en advarsel når en annen uavhengig kilde bekrefter det, og
    ellers til 72 timer etter avspark (audit_against_ffk). Har ffksupporter
    ikke registrert noe på flere døgn, er det en advarsel om at kilden har
    stoppet (resultatregel.kilde_stoppet). Advarslene lagres i
    audit_state.json og står i status.json resten av dagen.
    "Sjekket i dag"-merket settes uansett utfall, så en reell feil ikke
    spammer hvert kvarter resten av dagen."""
    today = now.astimezone(OSLO).strftime("%Y-%m-%d")
    state = json.loads(AUDIT_STATE_PATH.read_text(encoding="utf-8")) if AUDIT_STATE_PATH.exists() else {}
    if state.get("checked_date") == today and not int(state.get("errors") or 0):
        # Gjort i dag OG ren. Revisjonen har sin egen DATO-sperre, mens porten
        # bruker en 20-TIMERS klokke. Returnerte vi False her, ville siste_ok
        # aldri blitt satt paa en dag der revisjonen alt var kjort, og porten
        # ville proevd hver time resten av dagen.
        log("Daglig kontroll: alt gjort i dag uten avvik -- hopper over.")
        return True

    if state.get("checked_date") == today:
        # Gjort i dag, MEN med kritiske avvik. Da skal den kjores paa nytt,
        # ikke regnes som gjort: et avvik kan vaere rettet hos kontrollkilden
        # i mellomtiden. Sperren paa en time i porten (should_fetch.py)
        # hindrer at dette skjer oftere enn det er vits i.
        log(f"Daglig kontroll: {state['errors']} avvik fra tidligere i dag "
            f"-- kjører revisjonen på nytt.")
    log(f"--- Daglig kontroll: {len(matches_out)} spilte kamper mot ffksupporter.net ---")
    import resultatregel
    errors, warnings = audit_against_ffk(matches_out, ffk_rows, now, bekreftere=bekreftere)
    kilder = dict(state.get("kilder") or {})
    kilder["ffksupporter"], stoppet = resultatregel.kilde_stoppet(
        "ffksupporter.net", _vaare_spilte(matches_out), _ffk_resultater(ffk_rows), kilder.get("ffksupporter"), now)
    if stoppet:
        warnings.insert(0, stoppet)
    AUDIT_STATE_PATH.write_text(json.dumps(
        {"checked_date": today, "errors": len(errors), "warnings": len(warnings),
         # Til status.json og livstegnet (write_status, livstegn.py).
         "advarsler": warnings[:ADVARSLER_MAKS],
         # Når hver kontrollkilde sist registrerte noe nytt (kilde_stoppet).
         "kilder": kilder}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    for w in warnings:
        log(f"ADVARSEL: {w}")
    if errors:
        for e in errors:
            log(f"AVVIK: {e}")
        raise DataAuditError(f"{len(errors)} avvik mellom matches.json og kontrollkilden:\n" + "\n".join(errors))
    log(f"Daglig kontroll: ingen kritiske avvik ({len(warnings)} advarsel(er)).")
    return True


RESULTAT_FRIST_TIMER = 3


def sjekk_manglende_resultat(fixtures_out, now, log):
    """Står en kamp uten sluttresultat mer enn tre timer etter avspark, er
    noe galt -- og da skal kjøringen feile synlig samme kveld, ikke bare
    legge en linje i loggen som ingen leser. Alternativet er at tabellen står
    feil til noen tilfeldigvis oppdager det.

    Kaster DataAuditError, som allerede gjør stempelet rødt."""
    sent = []
    for runde in fixtures_out:
        for m in runde.get("matches", []):
            if m.get("played"):
                continue
            if not m.get("date") or not m.get("time"):
                continue  # uten avspark kan vi ikke vite om fristen er ute
            avspark = _kickoff_utc(m["date"], m["time"])
            timer = (now - avspark).total_seconds() / 3600
            if timer > RESULTAT_FRIST_TIMER:
                sent.append(f"{m['home']}-{m['away']} ({m['date']} {m.get('time')}): "
                            f"{timer:.1f} timer siden avspark, fortsatt uten sluttresultat")
    if sent:
        for e in sent:
            log(f"AVVIK: {e}")
        raise DataAuditError(
            f"{len(sent)} kamp(er) mangler sluttresultat mer enn "
            f"{RESULTAT_FRIST_TIMER} timer etter avspark:\n" + "\n".join(sent))
    return 0


def samlet_feiltekst(feil):
    """Feilteksten når kontrollene til slutt slo ut. feil: [(kontroll, tekst)].
    Én kontroll gir teksten dens uendret; flere gir en første linje som
    nevner alle (den linjen går i e-posten fra healthchecks, se livstegn.py)."""
    if len(feil) == 1:
        return feil[0][1]
    return (f"{len(feil)} kontroller fant avvik: " + "; ".join(n for n, _ in feil) + "\n"
            + "\n".join(f"{n}: {tekst}" for n, tekst in feil))


def etter_skriving(matches_out, fixtures_out, merged, utenfor, datofeil, tk, kontroll, now, log):
    """Alt etter at kampene og terminlisten er skrevet (12.10.2026): FØRST
    arbeidet -- sluttodds, sammenslåing av odds, modellen -- SÅ kontrollene.

    Før stoppet «mangler sluttresultat» og datovaktene kjøringen før
    sluttoddsen og modellen, og en rød kontroll hoppet over historikken,
    treffsikkerhetsloggen og revisjonen i workflowen. Nå kjøres alle
    kontrollene til slutt, ingen stopper de andre, og kjøringen blir rød med
    alle som slo ut (DataAuditError).

    Kontrollene avgjør bare om kjøringen blir rød. Det som skal hindre at
    gale data kommer ut, har skjedd FØR skrivingen: rimelige_datoer() har
    beholdt de gamle datoene, og «terminlisten hører til en annen sesong»
    stopper i main() før noe skrives.

    tk er svaret fra tabellkontroll.kontroller (regnet rett etter skrivingen,
    siden et nytt poengtrekk må inn før modellen). kontroll er radene til den
    daglige kontrollen."""
    log("--- Sluttodds (football-data.co.uk, maks én gang i døgnet) ---")
    fetch_odds_history.main()
    # Sluttodds fra OddsPapi-vinduet: 60 til 15 minutter før avspark, den
    # eneste kilden vi vet tidspunktet for. Gratis oppslag, og bare for
    # kamper som ikke alt er hentet. Skal ALDRI kunne stoppe kjeden: uten
    # nøkkel eller ved feil faller alt tilbake på football-data.
    if os.environ.get("ODDSPAPI_KEY", "").strip():
        log("--- Sluttodds (OddsPapi, vinduet 60-15 min før avspark) ---")
        try:
            import elite_closing_odds
            elite_closing_odds.main([])
        except Exception as e:
            log(f"  OddsPapi-sluttodds feilet ({type(e).__name__}: {e}) "
                f"-- fortsetter med football-data")
    log("--- Slår sammen oddskilder ---")
    merge_odds.main()
    log("--- Tilpasser modellen ---")
    fit_model.main()
    # Til workflowen: dataene og modellen er skrevet. Stegene etter dette
    # skriptet (historikken, treffsikkerhetsloggen, delingsbildet, revisjonen)
    # kjøres da også når kontrollene under gjør skriptet rødt.
    leaguedata.meld_data_skrevet()

    log("--- Kontrollene ---")
    feil = []   # [(kontroll, tekst)]

    def _kontroll(navn, funksjon):
        try:
            return funksjon()
        except DataAuditError as e:
            feil.append((navn, str(e)))
            return None

    # En kamp som mangler resultat lenge etter avspark.
    _kontroll("mangler sluttresultat", lambda: sjekk_manglende_resultat(fixtures_out, now, log))
    # Datovaktene. Mange datoer utenfor sesongen er ikke enkeltfeil -- da er
    # det noe galt med kilden, typisk en markupendring. Datoene med lagret
    # verdi i samme sesong er alt beholdt (før skrivingen); dette sier bare
    # fra.
    # 17.10.2026: en advarsel, ikke rødt. Datoene er alt beholdt fra før
    # (rimelige_datoer, før skrivingen), så siden er riktig; kilden må sjekkes.
    if utenfor and len(utenfor) > len(merged) * 0.25:
        tekst = (f"{len(utenfor)} av {len(merged)} kamper hadde dato utenfor sesongen hos ligasiden; "
                 f"datoene er beholdt fra før, kilden må sjekkes (f.eks. {utenfor[0]})")
        log(f"ADVARSEL: {tekst}")
        KJORINGENS_ADVARSLER.append(tekst)
    # Den daglige kontrollen mot kontrollkilden (ffksupporter.net; fotball.no
    # er ikke med i den daglige kjeden). Slår den ut, er det daglige
    # vedlikeholdet ikke utført, og 20-timersklokka nullstilles ikke.
    gjorde_daglig = _kontroll("daglig kontroll", lambda: run_daily_audit(matches_out, kontroll, now, log))
    # Tabellkontrollen mot tabellen på ligasiden.
    if tk and tk.get("errors"):
        feil.append(("tabellkontroll", f"{tk['errors']} kritisk(e) avvik mellom tabellen vår og tabellen "
                                       f"på ligasiden: {tk['avvik'][0]}"))

    # BARE naar det daglige vedlikeholdet faktisk ble utfort i denne
    # kjoringen. En vanlig resultatkjoring midt paa dagen skal ikke
    # nullstille 20-timersklokka -- da ville revisjonen og
    # football-data-sjekken kunne bli utsatt i det uendelige.
    if gjorde_daglig:
        should_fetch.merk_ok(LIGA, now)
        log("Daglig vedlikehold utfort -- 20-timersklokka nullstilt.")
    if feil:
        for navn, tekst in feil:
            log(f"KONTROLL RØD: {navn}: {tekst.splitlines()[0]}")
        raise DataAuditError(samlet_feiltekst(feil))
    write_status(ok=True, now=now)
    return 0


def main(cache_dir=None, now=None):
    log = lambda s: print(s, file=sys.stderr)
    now = now or datetime.now(timezone.utc)   # now kan settes i testene
    KJORINGENS_ADVARSLER.clear()

    # En frossen sesong er uforanderlig. Rundt aarsskiftet viser kildene
    # NESTE sesong, saa en kjoring her ville skrevet neste sesongs kamper inn
    # i den frosne. Vi venter paa at bytt() gjor jobben 1. januar.
    import sesong as _ses
    _aktiv0 = _ses.aktiv_sesong(ROOT, LIGA, log=log)
    if _aktiv0 and _ses.er_frosset(ROOT, LIGA, _aktiv0):
        log(f"Sesongen {_aktiv0} er frosset -- rører ingenting. "
            f"Venter på sesongskiftet.")
        return 0

    try:
        # Uten sesongregister skrives INGENTING (13.10.2026). Før sto
        # datovakten over, dataene ble skrevet som normalt, og kjøringen ble
        # rød til slutt: en gal dato fra kilden ville da kommet ut. Vakten
        # skal aldri stå over i stillhet.
        if _aktiv0 is None:
            raise DataAuditError(DATOVAKT_BESKJED["ingen_autoritet"])
        try:
            espn_rows = espn_source.fetch_all(cache_dir=cache_dir, log=log)
        except espn_source.EspnDataError as e:
            # Datakvalitetsproblem (ferdigspilt kamp som ikke lot seg tolke).
            # Skal ikke skjules, men gjør ikke lenger kjøringen rød (17.10.2026):
            # ESPN er én stemme blant flere, og resultatregelen krever to
            # enige, så ingenting feil kan publiseres av at ESPN utelates.
            # Advarsel i status.json og livstegnet; kildevakten (hentelogg)
            # teller feilen. 20.9.2026 hoppet koden stille over et ekte
            # resultat -- derfor står det synlig.
            tekst = f"ESPN-data kunne ikke tolkes ({str(e).splitlines()[0]}) -- ESPN utelatt denne kjøringen"
            log(f"ADVARSEL: {tekst}")
            KJORINGENS_ADVARSLER.append(tekst)
            espn_rows = []
        except Exception as e:
            # Alt annet (429, 400, timeout, DNS...) er bare ESPN som er
            # utilgjengelig -- ffksupporter.net er fasit uansett, så dette
            # skal aldri felle hele kjøringen.
            log(f"ADVARSEL: ESPN feilet ({e}) -- fortsetter uten ESPN denne runden (ffksupporter dekker fortsatt resultatet).")
            espn_rows = []

        # Hovedkilde: ligasiden. Uten den kan vi ikke bygge terminlisten.
        ntf_rows = ligasiden_eller_reserve(cache_dir, log)

        # SESONGGRENSEN, eksplisitt og for avstemmingen. Ligasiden viser
        # bade fjoraaret og neste sesong i vinduet for frysingen, med de
        # samme lagparene. Kaster FeilSesong ved 0 aktive rader -- og det
        # skjer HER, lenge for write_json under, saa de eksisterende filene
        # staar urort.
        ntf_rows, _fordeling = bare_aktiv_sesong(ntf_rows, _aktiv0, log=log)

        # fotball.no er ikke med i den daglige kjeden (1.10.2026): bare som
        # reserve over, naar ligasiden ikke svarer. Den daglige kontrollen
        # under gaar mot ffksupporter.
        nff_rows = []

        # Reserve. Feiler den, er det ikke lenger kritisk.
        try:
            ffk_rows = get_ffk_rows(cache_dir, log)
        except Exception as e:
            log(f"ADVARSEL: ffksupporter (reserve) feilet ({e}) -- fortsetter.")
            ffk_rows = []

        # fotball.no er IKKE med i avstemmingen. Cachen kan vaere opptil 20
        # timer gammel, og da ville et ferskt avspark eller resultat fra
        # ligasiden gitt en falsk advarsel i hver kjoring i 20 timer.
        # Ligasiden ville vunnet uansett -- stoyen var hele problemet.
        # Kontrollen mot fotball.no skjer i den daglige revisjonen i stedet,
        # der dataene er like gamle paa begge sider.
        merged = reconcile(ntf_rows, [], ffk_rows, espn_rows, log=log)

        # Et publisert resultat skal aldri forsvinne fordi en kilde midlertidig
        # ikke melder kampen som ferdig. Se behold_eksisterende().
        tidligere = json.loads((LEAGUE / "data" / "matches.json").read_text(encoding="utf-8")) \
            if (LEAGUE / "data" / "matches.json").exists() else []
        merged = behold_eksisterende(merged, tidligere, log=log)
        # En dato utenfor sesongens vindu er alltid feil hos kilden, aldri
        # hos oss. Se rimelige_datoer() for hendelsen som gjorde den
        # nodvendig. Sesongen kommer fra registeret, ikke fra dataene.
        import sesong as _sesong
        _aktiv = _sesong.aktiv_sesong(ROOT, LIGA, log=log)
        # Forrige verdi er HELE terminlisten vi sist skrev (spilte fra
        # matches.json, uspilte fra fixtures.json), som i OBOS. Med bare
        # matches.json hadde ingen uspilt kamp en forrige dato, og vinduet sluttet
        # 45 dager etter siste SPILTE runde. 9.10.2026 viste ligasiden
        # Rosenborg-Start (runde 26, 7.11.) som 7.1., og det slapp gjennom.
        _forrige_liste = leaguedata.forrige_terminliste(LEAGUE / "data", _aktiv, log=log) if _aktiv else None
        merged, utenfor, _datofeil = rimelige_datoer(merged, _forrige_liste or tidligere, _aktiv, log=log)
        # Kan vakten ikke kontrollere datoene, skrives ingenting.
        if _datofeil in ("sesongskifte_mangler", "ingen_runder", "ingen_autoritet"):
            raise DataAuditError(DATOVAKT_BESKJED[_datofeil])
        # Ingen enkeltkilde setter eller flytter datoen for en uspilt kamp
        # (10.10. og 13.10.2026, reconcile_ny.bekreft_datoer): ligasiden viste
        # Rosenborg-Start (7.11.) som 18.11., innenfor sesongvinduet. En
        # flytting gjennomføres bare når ESPN (sesongkallet, gratis) viser
        # samme nye dato og tid; svarer ikke ESPN, avgjør kalenderfeeden.
        # Ellers beholdes datoen vi har, og flyttingen venter
        # (flytting_venter.json). En NY kamp uten brukbar lagret dato må
        # bekreftes på samme måte; kan den ikke det, skrives ingenting.
        # Avgjørelser for hånd står i flytting_overstyring.json.
        def _espn_fasit():
            return {(r["home"], r["away"]): (r["date"], r.get("time"))
                    for r in espn_source.fetch_season(_aktiv, log=log)}

        def _kalender_fasit():
            return {(r["home"], r["away"]): (r["date"], r.get("time"))
                    for r in ntf_source.parse_kalender(ntf_source.hent_kalender(LIGA, log=log), LIGA)}
        _lagret = _forrige_liste or tidligere
        merged, _flytting = bekreft_datoer(
            merged, _forrige_liste, [("ESPN", _espn_fasit), ("kalenderfeeden", _kalender_fasit)], log=log,
            nye=uten_lagret_dato(merged, _lagret, _aktiv),
            overstyringer=flytting.les_overstyringer(LEAGUE / "data", {(r["home"], r["away"]) for r in merged}, log=log), naa=now)
        _ubekreftet = [u for u in _flytting if u["utfall"] == "ubekreftet"]
        if _ubekreftet:
            raise DataAuditError(
                f"{len(_ubekreftet)} ny(e) kamp(er) uten lagret dato er ikke bekreftet av en uavhengig kilde. "
                f"Ingenting er skrevet:\n" + "\n".join(
                    f"{u['kamp']}: ligasiden viser {u['ny'][0]} {u['ny'][1]}; {u['hva']}. Godta for hånd i "
                    f"eliteserien/data/{flytting.OVERSTYRING}: "
                    f"{flytting.linje(u['nokkel'][0], u['nokkel'][1], 'godta', u['ny'][0], u['ny'][1])}"
                    for u in _ubekreftet[:10]))
        # Regelen for nye resultater (resultatregel.py): hovedkilden og en
        # annen leverandør må være enige. Publiserte resultater røres ikke.
        merged, _resstate = kontroller_nye_resultater(merged, tidligere, ntf_rows, espn_rows, ffk_rows, now, log=log)

        # FOR SKRIVINGEN, ikke etter. "sesongskifte_mangler" betyr at
        # terminlisten hoerer til en ANNEN sesong enn registeret sier -- altsaa
        # at disse dataene ikke skal publiseres. Kontrollen laa nedenfor
        # write_json, saa 2027-datoer ble skrevet og pushet FOR kjoringen ble
        # rod. Etter sesonggrensen over skal den ikke kunne utloses; den staar
        # som andre ben, og da maa den staa paa riktig side av skrivingen.
        if _datofeil == "sesongskifte_mangler":
            raise DataAuditError(DATOVAKT_BESKJED["sesongskifte_mangler"])

        matches_out, fixtures_out = build(merged)

        fordeling = {}
        for r in merged:
            if r["src"]:
                fordeling[r["src"]] = fordeling.get(r["src"], 0) + 1
        log(f"Ferdig: {len(matches_out)} spilte kamper ({fordeling}), "
            f"{len(fixtures_out)} runder med gjenstående kamper.")

        data_dir = LEAGUE / "data"
        data_dir.mkdir(exist_ok=True)
        write_json(data_dir / "matches.json", matches_out)
        write_json(data_dir / "fixtures.json", fixtures_out)
        skriv_state(_resstate, now)
        # Flyttingene som ble holdt tilbake, til den daglige revisjonen.
        flytting.skriv_venter(data_dir, _flytting, now)

        # Tabellkontrollen mot tabellen paa ligasiden, fra samme henting
        # (scripts/tabellkontroll.py). Et nytt poengtrekk legges inn i
        # justeringer.json her, foer modellen og grunnlaget. Avvik i kamper,
        # maal eller V/U/T feiler kjoringen nederst, etter at alt annet er
        # skrevet.
        # Rett etter kampslutt (12.10.2026): et avvik som bare gjelder en
        # fersk kamp med resultat bekreftet utenfor NTF, er en advarsel og en
        # ny sjekk i neste kjøring (ferske), se tabellkontroll.py.
        import tabellkontroll
        import resultatregel
        _t = ntf_source.siste_tabell(LIGA)
        _tk = tabellkontroll.kontroller(
            LIGA, _aktiv or now.astimezone(timezone.utc).year, matches_out,
            _t.get("tabell") if _t and "tabell" in _t else _t, naa=now, data_dir=data_dir,
            kilde_url=_t.get("kilde") if _t else None, kjoring=_ses.kjoring_id(), log=log,
            ferske=resultatregel.ferske_bekreftede(LIGA, matches_out, now, state_sti=STATE))

        # Resten: først arbeidet (sluttodds, odds, modell), så kontrollene.
        # Datovaktene har alt beholdt de gamle datoene i rimelige_datoer()
        # over, FØR skrivingen; her avgjøres bare om kjøringen blir rød.
        etter_skriving(matches_out, fixtures_out, merged, utenfor, _datofeil, _tk,
                       nff_rows or ffk_rows, now, log)
    except Exception as e:
        write_status(ok=False, now=now, error=e)
        raise


if __name__ == "__main__":
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    main(cache_dir=cache)
