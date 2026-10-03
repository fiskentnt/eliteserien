#!/usr/bin/env python3
"""Reservekjeden for terminlisten når ligasiden ikke kan brukes (3.10.2026).

  Eliteserien: kalenderfeeden, ESPN, Highlightly, siste gyldige terminliste
  OBOS:        kalenderfeeden, Highlightly, siste gyldige terminliste
  (fotball.no bare i krise, hos kalleren: ligasiden svarer ikke og den
  siste gyldige terminlisten finnes ikke.)

Den siste gyldige terminlisten (leaguedata.forrige_terminliste: fixtures.json
og matches.json) er grunnlaget. En reserve legges oppå den:
  * Spilte kamper står ALLTID som hos oss. En reserve endrer aldri et
    publisert resultat (ESPN har feil 0-0 for to spilte kamper 29.5.).
  * En kamp som har startet hos oss, beholder dato og avspark som sist
    (kalenderfeeden viser avsparket i UTC for kamper NTF har endret ved
    kampslutt), men får resultatet fra reserven -- det går gjennom regelen i
    resultatregel.py før det publiseres.
  * Kommende kamper får dato, avspark og runde fra reserven. ESPN har ingen
    runde; den tas fra den lagrede terminlisten.
  * En reserve brukes bare når den har ALLE de kommende kampene våre; ellers
    prøves neste. Den siste gyldige terminlisten står igjen til slutt.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")


def _avspark(m):
    try:
        return datetime.fromisoformat(f"{m['date']}T{m.get('time') or '00:00'}:00").replace(tzinfo=OSLO)
    except Exception:
        return None


def bygg(forrige, rader, naa, runde_fra_kilde=True):
    """Den siste gyldige terminlisten med reservens rader lagt oppå, eller None
    når reserven mangler en kommende kamp. rader: {home, away, date, time,
    round?, hg?, ag?} (resultat bare for ferdigspilte)."""
    ix = {(r["home"], r["away"]): r for r in rader if r.get("date")}
    kommende = [m for m in forrige if m.get("hg") is None and _avspark(m) and _avspark(m) > naa]
    mangler = [(m["home"], m["away"]) for m in kommende if (m["home"], m["away"]) not in ix]
    if mangler:
        return None, mangler
    ut = []
    for m in forrige:
        k = (m["home"], m["away"])
        r = ix.get(k)
        if m.get("hg") is not None or r is None:
            ut.append(dict(m))
            continue
        hg, ag = (r.get("hg"), r.get("ag")) if r.get("hg") is not None and not r.get("suspect") else (None, None)
        if _avspark(m) and _avspark(m) <= naa:
            ut.append({**m, "hg": hg, "ag": ag})
            continue
        runde = r.get("round") if runde_fra_kilde and r.get("round") else m["round"]
        ut.append({**m, "date": r["date"], "time": r.get("time") or m.get("time"), "round": runde, "hg": hg, "ag": ag})
    return ut, []


def kjede(liga, forrige, naa, log=lambda s: None, hent=None):
    """(rader, kilde): den første reserven som har hele terminlisten, ellers den
    siste gyldige. hent: {kilde: funksjon som gir radene} (byttes i testene)."""
    aar = naa.astimezone(OSLO).year
    kjente_datoer = {(m["home"], m["away"]): m["date"] for m in forrige}
    if hent is None:
        def _kal():
            import ntf_source
            return ntf_source.parse_kalender(ntf_source.hent_kalender(liga), liga)

        def _espn():
            import espn_source
            return espn_source.fetch_season(aar, log=log)

        def _hl():
            import highlightly_source
            return highlightly_source.hent_sesong(liga, aar, kjente_datoer)
        hent = {"kalenderfeeden": _kal, "espn": _espn, "highlightly": _hl}
    rekke = ["kalenderfeeden"] + (["espn"] if liga == "eliteserien" else []) + ["highlightly"]
    for navn in rekke:
        if navn not in hent:
            continue
        try:
            rader = hent[navn]()
        except Exception as e:
            log(f"  reserve for terminlisten: {navn} feilet ({type(e).__name__}: {e})")
            continue
        ut, mangler = bygg(forrige, rader, naa, runde_fra_kilde=(navn != "espn"))
        if ut is None:
            log(f"  reserve for terminlisten: {navn} mangler {len(mangler)} kommende kamp(er) "
                f"({', '.join(f'{h}-{b}' for h, b in mangler[:3])}) -- prøver neste")
            continue
        log(f"ADVARSEL: ligasiden kan ikke brukes -- terminlisten fra {navn} denne kjøringen "
            f"(lagt oppå den siste gyldige; spilte kamper som hos oss).")
        return ut, navn
    log("ADVARSEL: ligasiden og reservene kan ikke brukes -- den siste gyldige terminlisten "
        "(fixtures.json og matches.json) står denne kjøringen.")
    return [dict(m) for m in forrige], "forrige terminliste"
