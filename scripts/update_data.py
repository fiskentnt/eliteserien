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
from reconcile_ny import (bare_aktiv_sesong, behold_eksisterende,
                          reconcile as reconcile_kilder, rimelige_datoer)
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


DATOVAKT_BESKJED = {
    "ingen_autoritet": (
        "Ingen autoritativ sesong i data/sesonger.json, så datovakten sto "
        "over. Dataene er skrevet som normalt, men en gal dato fra kilden "
        "ville ikke blitt fanget. Kjør: python3 scripts/sesong.py . init "
        "<liga> <år>"),
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
    except ntf_source.SvarerIkke as e:
        log(f"ADVARSEL: ligasiden svarte ikke ({e}) -- bruker fotball.no som reserve.")
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
                              hl_dag=None, espn_sesong=None, state_sti=None):
    """Regelen i resultatregel.py (3.10.2026) for resultatene som er NYE i
    denne kjøringen: et resultat publiseres når hovedkilden og minst én kilde
    fra en annen leverandør er enige. Ellers står kampen som uspilt (vent)
    eller holdes tilbake (konflikt). Publiserte resultater røres ikke
    (behold_eksisterende). Bare ligasiden kan publisere alene, etter 24
    timer, og står da som ukontrollert i results_state.json til ESPN,
    Highlightly eller ffksupporter bekrefter det.

    Kildene: ligasiden (eller fotball.no, LIGAKILDE), ESPN (hele sesongen i
    ett kall, siden dagens rundetavle ikke ser en kamp fra i går), Highlightly
    (per dato, ett kall per kampdag), ffksupporter. hl_dag og espn_sesong kan
    byttes ut i testene. Returnerer (merged, state)."""
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
    if not nye and not sjekk_ukontr:
        return merged, {"conflicts": [], "waiting": [], "ukontrollert": ukontr, "ukontrollert_sjekket": sist}

    kilder = {LIGAKILDE: resultat(liga_rader), "ffksupporter": resultat(ffk_rader) if ffk_rader else None}
    try:
        espn = espn_sesong(now.astimezone(OSLO).year)
        kilder["espn"] = resultat(espn)
    except Exception as e:
        log(f"  ESPN (sesongen) feilet ({type(e).__name__}: {e}) -- fortsetter uten")
        kilder["espn"] = resultat(espn_rader) if espn_rader else None
    datoer = sorted({r["date"] for r in nye} | ({m["date"] for m in tidligere if (m["home"], m["away"]) in ukontr}
                                                if sjekk_ukontr else set()))
    hl, svarte = {}, False
    for d in datoer:
        try:
            hl.update(resultat([r for r in hl_dag(d) if r.get("ferdig")]))
            svarte = True
        except Exception as e:
            log(f"  Highlightly {d}: {type(e).__name__}: {e}")
    kilder["highlightly"] = hl if svarte else None
    oppe = {k for k, v in kilder.items() if v is not None}

    waiting, conflicts, nye_ukontr = [], [], {}
    ut = []
    for r in merged:
        k = (r["home"], r["away"])
        if r.get("hg") is None or k in publisert:
            ut.append(r)
            continue
        try:
            avspark = _kickoff_utc(r["date"], r["time"]) if r.get("time") else None
        except Exception:
            avspark = None
        svar = {kilde: v[k] for kilde, v in kilder.items() if v and k in v}
        u = resultatregel.avgjor("eliteserien", svar, oppe, avspark=avspark, naa=now)
        hvem = f"{k[0]}-{k[1]}"
        if u["utfall"] == "publiser":
            ut.append({**r, "hg": u["resultat"][0], "ag": u["resultat"][1]})
            if u["ukontrollert"]:
                nye_ukontr[k] = u["resultat"]
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
        for k, rr, uavh in uenige:
            conflicts.append(f"{k[0]}-{k[1]}: publisert {rr[0]}-{rr[1]} uten kontroll, men "
                             + ", ".join(f"{kilde} har {v[0]}-{v[1]}" for kilde, v in uavh.items()))
    ukontr.update(nye_ukontr)
    for c in conflicts:
        log(f"  KONFLIKT {c}")
    for w in waiting:
        log(f"  venter: {w}")
    return ut, {"conflicts": conflicts, "waiting": waiting, "ukontrollert": ukontr,
                "ukontrollert_sjekket": now.isoformat(timespec="seconds") if sjekk_ukontr else sist}


def skriv_state(state, now, state_sti=None):
    (state_sti or STATE).write_text(json.dumps({
        "checked_at": now.isoformat(timespec="seconds"),
        "conflicts": state["conflicts"], "waiting": state["waiting"],
        "ukontrollert": {f"{k[0]}|{k[1]}": list(v) for k, v in state["ukontrollert"].items()},
        "ukontrollert_sjekket": state["ukontrollert_sjekket"],
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


def audit_against_ffk(matches_out, ffk_rows, now):
    """Sammenligner ALLE spilte kamper i matches_out (vår fasit akkurat nå,
    uansett hvilken kilde hvert resultat kom fra) mot ffksupporter.net sin
    egen liste (ffk_rows, fra denne kjøringens get_ffk_rows()). ffksupporter
    oppdateres for hånd og ligger ofte etter, så avvik deles i to
    alvorlighetsgrader:
      1. Begge kilder har et resultat, men de er ULIKE -- feil med en gang.
      2. Vi har et resultat (typisk fra ESPN) som ffksupporter.net ikke har
         registrert ennå -- bare en advarsel, siden dette er normalt og
         forbigående. Blir en feil først når det er over 72 timer siden
         avspark og ffksupporter.net FORTSATT ikke har det.
      3. ffksupporter.net har et resultat vi mangler helt -- feil med en
         gang (skal være umulig gitt at reconcile() alltid bruker
         ffksupporter sitt tall når det finnes, så dette er et tegn på en
         reell feil i sammenslåingen).
    Returnerer (errors, warnings), begge lister med tekst."""
    ffk_by_pair = {(r["home"], r["away"]): r for r in ffk_rows}
    matches_by_pair = {(m["home"], m["away"]): m for m in matches_out}
    errors, warnings = [], []

    for m in matches_out:
        ffk = ffk_by_pair.get((m["home"], m["away"]))
        if ffk is None:
            errors.append(f"{m['home']}-{m['away']} ({m['date']}): finnes hos oss, men ikke i det hele tatt hos ffksupporter.net")
        elif ffk["hg"] is None or ffk["ag"] is None:
            hours_since = None
            if m.get("time"):
                try:
                    hours_since = (now - _kickoff_utc(m["date"], m["time"])).total_seconds() / 3600
                except ValueError:
                    hours_since = None
            if hours_since is not None and hours_since > 72:
                errors.append(f"{m['home']}-{m['away']} ({m['date']}): vi har {m['hg']}-{m['ag']}, "
                               f"ffksupporter.net har fortsatt ikke registrert resultat {hours_since:.0f} timer etter avspark")
            else:
                suffix = f" ({hours_since:.0f}t siden avspark)" if hours_since is not None else ""
                warnings.append(f"{m['home']}-{m['away']} ({m['date']}): vi har {m['hg']}-{m['ag']}, "
                                 f"kontrollkilden har ikke registrert resultat ennå{suffix}")
        elif (ffk["hg"], ffk["ag"]) != (m["hg"], m["ag"]):
            errors.append(f"{m['home']}-{m['away']} ({m['date']}): vi har {m['hg']}-{m['ag']}, kontrollkilden har {ffk['hg']}-{ffk['ag']}")

    for r in ffk_rows:
        if r["hg"] is None or r["ag"] is None:
            continue
        if (r["home"], r["away"]) not in matches_by_pair:
            errors.append(f"{r['home']}-{r['away']} ({r['date']}): kontrollkilden har {r['hg']}-{r['ag']}, vi mangler kampen helt")

    return errors, warnings


def run_daily_audit(matches_out, ffk_rows, now, log):
    """Én gang i døgnet: full kontroll av alle spilte kamper mot
    ffksupporter.net. Kjøres på den første kjøringen som når hit hver dag --
    egen dato-sperre her, ikke avhengig av noe bestemt klokkeslett. Kritiske
    avvik feiler kjøringen (stempelet blir rødt); "ikke registrert ennå" er
    bare en advarsel i loggen med mindre den har stått i over 72 timer.
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
    errors, warnings = audit_against_ffk(matches_out, ffk_rows, now)
    AUDIT_STATE_PATH.write_text(json.dumps(
        {"checked_date": today, "errors": len(errors), "warnings": len(warnings)}, ensure_ascii=False, indent=2) + "\n",
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


def main(cache_dir=None):
    log = lambda s: print(s, file=sys.stderr)
    now = datetime.now(timezone.utc)

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
        try:
            espn_rows = espn_source.fetch_all(cache_dir=cache_dir, log=log)
        except espn_source.EspnDataError:
            # Datakvalitetsproblem (ferdigspilt kamp som ikke lot seg tolke),
            # ikke en vanlig nettverks-/API-feil -- skal IKKE skjules. Feiler
            # kjøringen synlig (stempelet blir rødt) i stedet for å risikere
            # å bare hoppe stille over et ekte resultat, slik det gjorde
            # 20. september 2026 (se git-historikken for den hendelsen).
            raise
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
        merged, utenfor, _datofeil = rimelige_datoer(merged, tidligere, _aktiv, log=log)
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

        # Tabellkontrollen mot tabellen paa ligasiden, fra samme henting
        # (scripts/tabellkontroll.py). Et nytt poengtrekk legges inn i
        # justeringer.json her, foer modellen og grunnlaget. Avvik i kamper,
        # maal eller V/U/T feiler kjoringen nederst, etter at alt annet er
        # skrevet.
        import tabellkontroll
        _t = ntf_source.siste_tabell(LIGA)
        _tk = tabellkontroll.kontroller(
            LIGA, _aktiv or now.astimezone(timezone.utc).year, matches_out,
            _t.get("tabell") if _t and "tabell" in _t else _t, naa=now,
            kilde_url=_t.get("kilde") if _t else None, kjoring=_ses.kjoring_id(), log=log)

        # Etter skriving: filene er riktige så langt kildene rekker, men en
        # kamp som mangler resultat lenge etter avspark skal stoppe kjøringen.
        sjekk_manglende_resultat(fixtures_out, now, log)

        # Mange datoer utenfor sesongen er ikke enkeltfeil -- da er det noe
        # galt med kilden, typisk en markupendring. Datoene er rettet over,
        # men kjoringen skal feile synlig.
        # ETTER skrivingen, med vilje: dataene er skrevet som normalt, og
        # dette sier bare at vi ikke kunne kontrollere datoene.
        if _datofeil == "ingen_autoritet":
            raise DataAuditError(DATOVAKT_BESKJED["ingen_autoritet"])
        # ETTER skrivingen: naar denne slaar ut, er datoene med lagret verdi
        # i samme sesong ALT rettet av rimelige_datoer(). Det som er skrevet
        # er altsaa den lagrede verdien, ikke kildens gale dato. AA ikke
        # skrive ville bare latt de eksisterende filene staa -- det er ikke
        # galt, men det retter ingenting, og kilden maa uansett sjekkes.
        if len(utenfor) > len(merged) * 0.25:
            raise DataAuditError(
                f"{len(utenfor)} av {len(merged)} kamper hadde dato utenfor "
                f"sesongen. Datoene er beholdt fra før, men kilden må sjekkes:\n"
                + "\n".join(utenfor[:10]))

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

        # Etter alt det normale arbeidet er gjort og lagret: den daglige
        # kontrollen mot ffksupporter.net. Kan fortsatt feile KJØRINGEN
        # (stempelet blir rødt), men hindrer ikke dagens resultater/odds/
        # modell i å bli skrevet og committet først.
        # Den daglige kontrollen går nå mot fotball.no (NFF), ikke mot
        # ffksupporter. Den er offisiell, uavhengig av ligasiden vi bygger
        # fra, og komplett for hele sesongen. Faller den ut, bruker vi
        # ffksupporter som før, slik at kontrollen aldri blir helt borte.
        kontroll = nff_rows or ffk_rows
        gjorde_daglig = run_daily_audit(matches_out, kontroll, now, log)

        write_status(ok=True, now=now)
        # BARE naar det daglige vedlikeholdet faktisk ble utfort i denne
        # kjoringen. En vanlig resultatkjoring midt paa dagen skal ikke
        # nullstille 20-timersklokka -- da ville revisjonen og
        # football-data-sjekken kunne bli utsatt i det uendelige.
        if gjorde_daglig:
            should_fetch.merk_ok(LIGA, now)
            log("Daglig vedlikehold utfort -- 20-timersklokka nullstilt.")
        if _tk["errors"]:
            raise DataAuditError(f"{_tk['errors']} kritisk(e) avvik mellom tabellen vår og tabellen "
                                 f"på ligasiden: {_tk['avvik'][0]}")
    except Exception as e:
        write_status(ok=False, now=now, error=e)
        raise


if __name__ == "__main__":
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    main(cache_dir=cache)
