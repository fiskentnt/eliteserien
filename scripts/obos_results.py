#!/usr/bin/env python3
"""Henter resultater for OBOS-ligaen og publiserer dem bare når de er trygge.

Kilder:
  OddsPapi  hovedkilde. Kamplisten hentes én gang per kjøring (1 tellende kall)
            og gir status og tidspunkt. For hver kamp som er ferdigspilt og
            mangler resultat hos oss, hentes resultatet med /v4/scores
            (1 tellende kall per kamp).
  Wikipedia kontroll og reserve. Gratis, ingen nøkkel. Resultatrutenettet på
            "OBOS-ligaen 2026" leses og sammenlignes.

Regler:
  * Kamper identifiseres på sesong, hjemmelag og bortelag. Dato og tid er
    metadata som kan endres -- en flyttet kamp blir aldri to kamper.
  * Ingenting publiseres før kampen er ferdigspilt hos minst én kilde, og
    aldri et delresultat. Utsatte og avbrutte kamper får ikke resultat.
  * Begge kilder har sluttresultat og er enige  -> publiser.
  * Begge har sluttresultat og er uenige        -> hold tilbake, logg konflikt.
  * Bare én kilde har det, under 24 timer siden -> vent (ikke en feil).
  * Bare én kilde har det, over 24 timer siden  -> publiser den kilden.

Failsafe: det nye datasettet valideres før noe skrives. Feiler valideringen,
beholdes forrige gyldige datasett uendret, og kjøringen sier fra.

  python3 scripts/obos_results.py            # hent og publiser
  python3 scripts/obos_results.py --dry-run  # vis hva som ville skjedd
  python3 scripts/obos_results.py --no-oddspapi   # bare Wikipedia (test)
"""
import argparse
import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi

ROOT = Path(__file__).parent.parent
DATA = ROOT / "obos" / "data"
MATCHES = DATA / "matches.json"
STATE = DATA / "results_state.json"
NAME_MAP = DATA / "name_map.json"
CSV_PATH = DATA / "obos_2012-2026.csv"
FIXTURES_CACHE = DATA / "oddspapi_fixtures_2026.json"

OBOS_TOURNAMENT = 22
SEASON = "2026"
WAIT_HOURS = 24
WIKI_PAGE = "OBOS-ligaen 2026"
WIKI_UA = "tabellkalkulator (+https://tabellkalkulator.no)"
STATUS_FINISHED = 2


def log(msg):
    print(msg, flush=True)


def norm(name):
    s = unicodedata.normalize("NFKD", (name or "").lower())
    s = s.replace("ø", "o").replace("æ", "ae").replace("å", "a")
    s = "".join(c for c in s if not unicodedata.combining(c))
    for w in (" fotball", " toppfotball", " fk", " if", " il", " ik", " sk", " bk", " ff", " fc"):
        if s.endswith(w):
            s = s[: -len(w)]
    return " ".join(s.split())


def load_names():
    m = json.loads(NAME_MAP.read_text(encoding="utf-8")) if NAME_MAP.exists() else {}
    return {k: v for k, v in m.items() if not k.startswith("_")}


def schedule():
    """Terminlisten: nøkkel (hjemme, borte) -> kamp.

    Runde, dato og avspark herfra skrives i matches.json for resultatene som
    publiseres, og avsparket avgjør ventetiden i decide(). Derfor den siste
    gyldige terminlisten vi selv har skrevet (fixtures.json og matches.json,
    leaguedata.forrige_terminliste), ikke CSV-en: den er fra sesongstart og
    har ikke flyttingene siden (3.10.2026). CSV-en bare når filene mangler
    eller ikke har hele terminlisten, som ved sesongstart."""
    import csv
    import leaguedata
    out = {}
    for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")):
        if r["sesong"] != SEASON:
            continue
        out[(r["hjemme"], r["borte"])] = {
            "round": int(r["runde"]), "date": r["dato"], "time": r["tid"],
            "home": r["hjemme"], "away": r["borte"],
        }
    forrige = leaguedata.forrige_terminliste(DATA, SEASON, forventet_par=set(out), log=log)
    if forrige:
        return {(m["home"], m["away"]): {"round": m["round"], "date": m["date"], "time": m["time"],
                                         "home": m["home"], "away": m["away"]} for m in forrige}
    log("  terminliste fra CSV-en (forrige terminliste finnes ikke eller er ufullstendig)")
    return out


def published():
    """Resultater vi alt har publisert: (hjemme, borte) -> (hg, ag)."""
    if not MATCHES.exists():
        return {}
    return {(m["home"], m["away"]): (m["hg"], m["ag"])
            for m in json.loads(MATCHES.read_text(encoding="utf-8"))}


# ---------------------------------------------------------------- OddsPapi
def oddspapi_fixtures(key, max_age_hours=20):
    """Kamplisten. Mellomlagres, så gjentatte kjøringer samme dag er gratis."""
    if FIXTURES_CACHE.exists():
        d = json.loads(FIXTURES_CACHE.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched_at"])
        if age < timedelta(hours=max_age_hours):
            log(f"  kampliste fra mellomlager ({len(d['fixtures'])} kamper, {age.seconds//3600} t gammel)")
            return d["fixtures"]
    d, err = oddspapi.call("/v4/fixtures", {"tournamentId": OBOS_TOURNAMENT,
                                            "from": f"{SEASON}-01-01", "to": f"{SEASON}-12-31"}, key)
    if err:
        log(f"  FEIL ved kampliste: {err}")
        return None
    fl = oddspapi.unwrap(d)
    FIXTURES_CACHE.write_text(json.dumps(
        {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "tournamentId": OBOS_TOURNAMENT, "fixtures": fl}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  kampliste hentet: {len(fl)} kamper (1 tellende kall)")
    return fl


def oddspapi_score(key, fixture_id):
    """Sluttresultatet for én kamp. Returnerer (hg, ag) eller None."""
    d, err = oddspapi.call("/v4/scores", {"fixtureId": fixture_id}, key)
    if err:
        log(f"    /v4/scores feilet: {err}")
        return None
    root = d.get("data", d) if isinstance(d, dict) else {}
    items = root if isinstance(root, list) else [root]
    for it in items:
        if not isinstance(it, dict):
            continue
        # Formen er scores -> periods -> result -> participant1Score/participant2Score.
        # BARE "result" brukes: det er sluttresultatet. Andre perioder er
        # omgangsresultater, og et delresultat skal aldri publiseres.
        per = ((it.get("scores") or {}).get("periods") or {})
        res = per.get("result")
        if isinstance(res, dict):
            h, a = res.get("participant1Score"), res.get("participant2Score")
            if isinstance(h, (int, float)) and isinstance(a, (int, float)):
                return int(h), int(a)
    log(f"    fant ikke sluttresultat i svaret: {json.dumps(d, ensure_ascii=False)[:200]}")
    return None


def finished_without_result(fixtures, prev, names, teams):
    """Kampene som er FERDIGSPILT hos OddsPapi og mangler resultat hos oss.

    Bare statusId 2 (ferdigspilt) er med: en kamp som pågår, er utsatt eller
    avbrutt skal aldri gi resultat. Kampen identifiseres på lagene, ikke dato,
    så en flyttet kamp ikke blir to."""
    hn = {norm(t): t for t in teams}
    out = []
    for f in fixtures:
        h = hn.get(norm(names.get(f.get("participant1Name"), f.get("participant1Name"))))
        a = hn.get(norm(names.get(f.get("participant2Name"), f.get("participant2Name"))))
        if not h or not a or (h, a) in prev:
            continue
        if f.get("statusId") != STATUS_FINISHED:
            continue
        out.append(((h, a), f))
    return out


def decide(off, op_scores, wiki, sched, prev, now, hl=None, nff=None, linjer=None):
    """Avgjør hva som kan publiseres, med regelen i resultatregel.py (3.10.2026):
    et resultat publiseres når hovedkilden og minst én kilde fra en annen
    leverandør er enige. Hovedkilden er den første som svarte i rekkefølgen
    ligasiden, Highlightly, OddsPapi, Wikipedia, fotball.no. fotball.no og
    ligasiden er samme leverandør (NTF). Uten uavhengig kilde publiseres
    ligasidens resultat alene etter 24 timer, og står da som ukontrollert til
    en uavhengig kilde bekrefter det; en annen enkeltkilde publiserer aldri.

    off (ligasiden), hl (Highlightly), op_scores (OddsPapi), wiki (Wikipedia),
    nff (fotball.no): {(hjemme, borte): (hg, ag)}, eller None når kilden ikke
    svarte. Returnerer (publiser, konflikter, venter, ukontrollert).
    linjer (en liste): får én linje per kamp som er ny eller venter
    (resultatregel.resultatlinje), også når den holdes tilbake."""
    import resultatregel
    kilder = {"ligasiden": off, "highlightly": hl, "oddspapi": op_scores, "wikipedia": wiki, "fotball.no": nff}
    oppe = {k for k, v in kilder.items() if v is not None}
    publish, conflicts, waiting, ukontrollert = dict(prev), [], [], {}
    cand = set()
    for v in kilder.values():
        cand |= set(v or {})
    for k in sorted(cand):
        if k in prev or k not in sched:
            continue
        s2 = sched[k]
        try:
            kickoff = datetime.fromisoformat(f"{s2['date']}T{s2['time']}").replace(
                tzinfo=ZoneInfo("Europe/Oslo")).astimezone(timezone.utc)
        except Exception:
            kickoff = None
        svar = {kilde: v[k] for kilde, v in kilder.items() if v and k in v and v[k] is not None}
        u = resultatregel.avgjor("obos", svar, oppe, avspark=kickoff, naa=now)
        if linjer is not None:
            linjer.append(resultatregel.resultatlinje("obos", k, u, svar))
        hvem = f"{k[0]} mot {k[1]}"
        if u["utfall"] == "publiser":
            publish[k] = u["resultat"]
            if u["ukontrollert"]:
                ukontrollert[k] = u["resultat"]
            if u["uenige"] or u["ukontrollert"]:
                log(f"  {hvem}: {u['grunn']}")
        elif u["utfall"] == "konflikt":
            conflicts.append(f"{hvem}: {u['grunn']}")
        else:
            waiting.append(f"{hvem}: {u['grunn']}")
    return publish, conflicts, waiting, ukontrollert


# ------------------------------------------------- offisielle ligakilder
def offisielle_resultater():
    """Ligasidens resultater, eller fotball.no sine når ligasiden ikke svarer
    (som før 3.10.2026, for kallerne som vil ha én liste). main() bruker
    ligasiden_og_reserve(), der de to står hver for seg."""
    off, nff = ligasiden_og_reserve()
    return off if off is not None else (nff or {})


def ligasiden_og_reserve():
    """(ligasiden, fotball.no): {(hjemme, borte): (hg, ag)} eller None når
    kilden ikke svarte. Gratis, ingen kvote. Holdes hver for seg fordi de er
    samme leverandør (NTF), se resultatregel.py.

    Etter kildebyttet er disse hovedkilden ogsaa for OBOS. De gjor
    /v4/scores unodvendig i normal drift: et tellende kall skal ikke brukes
    paa et resultat vi allerede har gratis fra to offisielle kilder.

    fotball.no er bare med som RESERVE naar ligasiden ikke svarer (regelen
    fra 1.10.2026, se nff_source.py), hoyst ett forsok per dogn, aldri
    ellers.

    Ligasiden gir bare resultat for rader som er eksplisitt merket
    ferdigspilt OG der det har gaatt lang nok tid siden avspark (se
    ntf_source.FERDIG_ETTER_MIN). En paagaaende kamp gir derfor ingenting."""
    try:
        import ntf_source
    except Exception as e:
        log(f"  ligasiden utilgjengelig ({type(e).__name__}: {e})")
        return None, None
    kilde = "ligasiden"
    try:
        ntf = ntf_source.fetch_all("obos", log=lambda _s: None)
    except Exception as e:
        log(f"  ligasiden feilet ({e})")
        # RESERVE (regelen fra 1.10.2026, se nff_source.py): BARE naar
        # ligasiden ikke svarer, brukes fotball.no -- hoeyst ett forsok per
        # dogn, ellers det som ligger i cachen. fotball.no har samme vern
        # mot en kamp underveis (nff_source.FERDIG_ETTER_MIN).
        if not isinstance(e, ntf_source.SvarerIkke):
            return None, None
        try:
            import nff_source
            ntf = nff_source.fetch_all("obos", log=lambda m: log(f"  {m}"))
        except Exception as e2:
            log(f"  fotball.no (reserve) feilet ({e2})")
            return None, None
        if not ntf:
            return None, None
        log("  bruker fotball.no som reserve for ligasiden")
        kilde = "fotball.no"

    # SESONGGRENSEN. Uten den var dette den verste veien inn: nokkelen er
    # (hjemme, borte), og radene kommer fra ligasiden uansett sesong. Etter
    # at kildene har flippet til neste sesong ville et 2027-resultat blitt
    # publisert som resultatet paa en 2026-kamp -- dato og runde hentes fra
    # var egen terminliste, saa ingenting hadde sett galt ut. decide() lar
    # ligasiden alene publisere, og behold_eksisterende() holder et publisert
    # resultat for godt. Rekkevidden var en UTSATT kamp: alt som er publisert
    # fra for hoppes over i decide(), men en kamp uten resultat ville fatt
    # neste sesongs.
    #
    # FeilSesong fanges IKKE her. Aa returnere {} ville latt decide() falle
    # tilbake paa Wikipedia og OddsPapi, og dermed skjult kildefeilen bak et
    # datasett som ser riktig ut. Den skal ut av main() for noe skrives.
    import sesong as _ses2
    from reconcile_ny import bare_aktiv_sesong
    ntf, _f = bare_aktiv_sesong(ntf, _ses2.aktiv_sesong(ROOT, "obos",
                                                        log=lambda _s: None),
                                log=lambda m: log(f"  {m}"))
    ut = {(r["home"], r["away"]): (r["hg"], r["ag"])
          for r in ntf if r.get("hg") is not None}
    log(f"  {kilde}: {len(ut)} ferdigspilte kamper")
    return (ut, None) if kilde == "ligasiden" else (None, ut)


def highlightly_resultater(datoer):
    """Ferdigspilte OBOS-kamper hos Highlightly for datoene (ett kall per
    dato), {(hjemme, borte): (hg, ag)}; None når Highlightly ikke svarte for
    noen av dem, eller ingen datoer trengs."""
    if not datoer:
        return None
    try:
        import highlightly_source as H
    except Exception as e:
        log(f"  Highlightly utilgjengelig ({type(e).__name__}: {e})")
        return None
    ut, svarte = {}, False
    for d in datoer:
        try:
            rader = H.hent_dag(d, ligaer=("obos",))["obos"]
        except Exception as e:
            log(f"  Highlightly {d}: {type(e).__name__}: {e}")
            continue
        svarte = True
        ut.update({(r["home"], r["away"]): (r["hg"], r["ag"]) for r in rader if r["ferdig"]})
    if svarte:
        log(f"  Highlightly: {len(ut)} ferdigspilte kamper ({len(datoer)} dag(er), ett kall per dag)")
    return ut if svarte else None


# ---------------------------------------------------------------- Wikipedia
def _wiki_logg(utfall, melding="", kamper=None):
    """Wikipedia er en av resultatkildene for OBOS. Ligasiden logges av
    ntf_source selv, saa her logges bare Wikipedia -- ellers ville hvert
    forsok blitt talt to ganger."""
    try:
        import hentelogg
        hentelogg.logg("obos", "wikipedia", utfall, melding=melding,
                       kamper=kamper)
    except Exception:
        pass


def wikipedia_results(names):
    """Resultatrutenettet fra Wikipedia: (hjemme, borte) -> (hg, ag).

    Rutenettet har lagene som rader og motstanderne som kolonner. Bare celler
    med et ferdig resultat ("2–1") leses; tomme celler og strek hoppes over."""
    url = ("https://no.wikipedia.org/w/api.php?action=parse&format=json&prop=text&page="
           + urllib.parse.quote(WIKI_PAGE))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA})
        with urllib.request.urlopen(req, timeout=45) as r:
            page = json.loads(r.read().decode("utf-8"))
        doc = page["parse"]["text"]["*"]
    except Exception as e:
        log(f"  Wikipedia feilet: {type(e).__name__}: {e}")
        _wiki_logg("feil", f"{type(e).__name__}: {e}")
        return None
    tables = re.findall(r"<table[^>]*>.*?</table>", doc, re.S)
    known = {norm(v): v for v in names.values()}
    txt = lambda h: " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h)).split())
    for t in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
        if len(rows) < 16:
            continue
        head = [txt(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.S)]
        # Rutenettet kjennes igjen på hjørnecellen "Hjemme \ Borte" og 16 kolonner.
        if len(head) != 17 or "hjemme" not in head[0].lower():
            continue
        # Kolonnene er forkortelser (BRY, EIK, ...), men står i SAMME rekkefølge
        # som radene, og radene har fulle lagnavn. Derfor leses lagene av radene.
        teams, cells_by_row = [], []
        for row in rows[1:]:
            cells = [c[1] for c in re.findall(r"<(t[hd])[^>]*>(.*?)</\1>", row, re.S)]
            if len(cells) != 17:
                continue
            name = known.get(norm(txt(cells[0])))
            if not name:
                log(f"  Wikipedia: ukjent lagnavn i rutenettet: {txt(cells[0])!r}")
                _wiki_logg("feil", f"ukjent lagnavn: {txt(cells[0])!r}")
                return None
            teams.append(name)
            cells_by_row.append(cells[1:])
        if len(teams) != 16:
            continue
        out = {}
        for ri, home in enumerate(teams):
            for ci, cell in enumerate(cells_by_row[ri]):
                v = txt(cell)
                if ri == ci:
                    # Diagonalen skal være tom. Er den ikke det, stemmer ikke
                    # rekkefølgen, og da leses ingenting.
                    if re.match(r"^\d+\s*[–\-−:]\s*\d+$", v):
                        log("  Wikipedia: diagonalen har resultat, rekkefølgen stemmer ikke")
                        _wiki_logg("feil", "diagonalen har resultat")
                        return None
                    continue
                m = re.match(r"^(\d+)\s*[–\-−:]\s*(\d+)$", v)
                if m:
                    out[(home, teams[ci])] = (int(m.group(1)), int(m.group(2)))
        log(f"  Wikipedia: {len(out)} resultater fra rutenettet")
        _wiki_logg("ok", kamper=len(out))
        return out
    log("  Wikipedia: fant ikke resultatrutenettet")
    _wiki_logg("feil", "fant ikke resultatrutenettet")
    return None


# ---------------------------------------------------------------- validering
def validate(new_rows, sched, prev):
    """Sier fra om noe er galt med datasettet. Tom liste = trygt å publisere."""
    problems = []
    teams = {t for k in sched for t in k}
    if len(teams) != 16:
        problems.append(f"terminlisten har {len(teams)} lag, ventet 16")
    seen = set()
    for m in new_rows:
        key = (m["home"], m["away"])
        if key in seen:
            problems.append(f"kampen finnes to ganger: {key}")
        seen.add(key)
        if key not in sched:
            problems.append(f"kamp som ikke står i terminlisten: {key}")
        if not isinstance(m["hg"], int) or not isinstance(m["ag"], int) or m["hg"] < 0 or m["ag"] < 0:
            problems.append(f"ugyldig resultat for {key}: {m['hg']}-{m['ag']}")
    for key, val in prev.items():
        if key not in seen:
            problems.append(f"tidligere publisert resultat er borte: {key}")
        else:
            now = next(m for m in new_rows if (m["home"], m["away"]) == key)
            if (now["hg"], now["ag"]) != val:
                problems.append(f"tidligere resultat endret: {key} {val} -> {(now['hg'], now['ag'])}")
    if len(new_rows) < len(prev):
        problems.append(f"færre resultater enn før: {len(new_rows)} mot {len(prev)}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-oddspapi", action="store_true", help="bare Wikipedia (for test)")
    ap.add_argument("--max-scores", type=int, default=20, help="høyst så mange /v4/scores-kall")
    ap.add_argument("--forget-round", type=int, help="glem resultatene i denne runden først "
                                                     "(for å vise at kjeden henter dem på nytt)")
    ap.add_argument("--break-wikipedia", action="store_true", help="test: lat som Wikipedia er ødelagt")
    ap.add_argument("--break-all", action="store_true", help="test: lat som ingen kilder svarer")
    args = ap.parse_args()

    # En frossen sesong er uforanderlig. Denne kjeden manglet vakten som
    # update_data og obos_build_data har hatt hele tiden -- og det er den
    # kjeden som skriver RESULTATER. Etter frysing skal den stoppe for
    # hentingen, ikke etter.
    import sesong as _ses
    _a0 = _ses.aktiv_sesong(ROOT, "obos", log=lambda _s: None)
    if _a0 and _ses.er_frosset(ROOT, "obos", _a0):
        log(f"Sesongen {_a0} er frosset -- rører ingenting. "
            f"Venter på sesongskiftet.")
        return 0

    names = load_names()
    sched = schedule()
    prev = published()
    if args.forget_round:
        drop = [k for k, s2 in sched.items() if s2["round"] == args.forget_round and k in prev]
        for k in drop:
            del prev[k]
        log(f"Glemmer runde {args.forget_round}: {len(drop)} resultater tas ut, så kjeden må hente dem på nytt.")
    log(f"Terminliste: {len(sched)} kamper. Publisert fra før: {len(prev)} resultater.")

    # ---- kildene (regelen i resultatregel.py, 3.10.2026)
    # Ligasiden (og fotball.no bare når den ikke svarer) og Wikipedia er
    # gratis. Highlightly hentes per dato, ett kall per kampdag, og bare for
    # kamper som trenger kontroll. OddsPapi er reserve: hvert kall koster, så
    # det spørres bare der regelen ikke kan publisere uten.
    off, nff = (None, None) if args.break_all else ligasiden_og_reserve()
    wiki = None if args.break_all or args.break_wikipedia else wikipedia_results(names)
    now = datetime.now(timezone.utc)
    gml_state = {}
    try:
        gml_state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        pass
    ukontr_for = {tuple(k.split("|")): tuple(v) for k, v in (gml_state.get("ukontrollert") or {}).items()}

    def avspark(k2):
        s2 = sched.get(k2)
        try:
            return datetime.fromisoformat(f"{s2['date']}T{s2['time']}").replace(
                tzinfo=ZoneInfo("Europe/Oslo")).astimezone(timezone.utc)
        except Exception:
            return None
    # Kamper Highlightly skal kontrollere: ligasiden har resultatet (eller er
    # nede og kampen er over), og det er ikke publisert. De ukontrollerte
    # sjekkes på nytt høyst én gang i timen.
    trenger = [k2 for k2 in sched if k2 not in prev and avspark(k2) and avspark(k2) <= now
               and ((off is not None and k2 in off) or off is None)]
    sist = gml_state.get("ukontrollert_sjekket")
    if ukontr_for and (not sist or now - datetime.fromisoformat(sist) >= timedelta(hours=1)):
        trenger += [k2 for k2 in ukontr_for if k2 in sched]
        sjekket_naa = True
    else:
        sjekket_naa = False
    # Kamper som er over (105 minutter etter avspark, som porten), men ikke
    # publisert: Highlightly spørres for datoen også før ligasiden har
    # resultatet, bare for å logge hvilken kilde som har det først. Regelen
    # for publisering endres ikke. Slike kall bare under LOGG_TAK i døgnet.
    ventende = [k2 for k2 in sched if k2 not in prev and avspark(k2)
                and now - timedelta(days=3) <= avspark(k2) <= now - timedelta(minutes=105)]
    datoer = {sched[k2]["date"] for k2 in trenger}
    if ventende and not args.break_all:
        try:
            import highlightly_source as _H
            if _H.dagsbruk() < _H.LOGG_TAK:
                datoer |= {sched[k2]["date"] for k2 in ventende}
            elif {sched[k2]["date"] for k2 in ventende} - datoer:
                log(f"  Highlightly: {_H.dagsbruk()} kall i dag, over {_H.LOGG_TAK}: spør ikke bare for loggen")
        except Exception:
            pass
    hl = None if args.break_all else highlightly_resultater(sorted(datoer))

    # Første runde uten OddsPapi. Det som ikke kan publiseres, får OddsPapi
    # som reserve (ett tellende kall per kamp), og avgjøres på nytt.
    linjer = []
    publish, conflicts, waiting, ukontrollert = decide(off, None, wiki, sched, prev, now, hl=hl, nff=nff, linjer=linjer)
    # Også det regelen ville publisert uten kontroll: OddsPapi er en
    # uavhengig kilde og skal prøves før ligasiden får stå alene.
    uavgjort = [k2 for k2 in trenger if (k2 not in publish or k2 in ukontrollert) and k2 not in ukontr_for]
    key = None if args.no_oddspapi else (oddspapi and __import__("os").environ.get("ODDSPAPI_KEY", "").strip())
    op_scores = None
    if key and uavgjort:
        fixtures = oddspapi_fixtures(key) or []
        teams = {t for k2 in sched for t in k2}
        missing = dict(finished_without_result(fixtures, prev, names, teams))
        rest = [(k2, missing[k2]) for k2 in uavgjort if k2 in missing]
        log(f"  OddsPapi som reserve: {len(rest)} kamp(er) uten avgjørelse")
        op_scores = {}
        for k2, f in rest[: args.max_scores]:
            sc = oddspapi_score(key, f.get("fixtureId"))
            if sc:
                op_scores[k2] = sc
                log(f"    {k2[0]} mot {k2[1]}: {sc[0]}-{sc[1]} (tellende kall)")
            time.sleep(1.2)
        linjer = []
        publish, conflicts, waiting, ukontrollert = decide(off, op_scores, wiki, sched, prev, now, hl=hl, nff=nff, linjer=linjer)
    elif key is None and not args.no_oddspapi and uavgjort:
        log("  ODDSPAPI_KEY mangler: OddsPapi brukes ikke som reserve")

    if args.break_wikipedia or args.break_all:
        log("  (test: later som kilden er ødelagt)")
    if all(x is None for x in (off, nff, wiki, hl, op_scores)):
        log("INGEN KILDER SVARTE. Beholder forrige datasett uendret.")
        return 2

    # Kryssjekk av det som ALT er publisert: endrer ingenting, men sier fra
    # hvis en kilde er uenig i noe vi har stående.
    if wiki:
        old_conf = [f"{h} mot {a}: vi har {v[0]}-{v[1]}, Wikipedia {wiki[(h,a)][0]}-{wiki[(h,a)][1]}"
                    for (h, a), v in prev.items() if (h, a) in wiki and wiki[(h, a)] != v]
        log(f"  kryssjekk mot Wikipedia: {len(prev)} publiserte, "
            f"{sum(1 for k2 in prev if k2 in wiki)} finnes hos Wikipedia, {len(old_conf)} uenige")
        for c in old_conf[:10]:
            log(f"    UENIGHET {c}")

    # Resultater publisert uten kontroll: bekreftet nå, eller fortsatt uten.
    import resultatregel
    if sjekket_naa:
        svar_pk = {k2: {kilde: v[k2] for kilde, v in (("highlightly", hl), ("wikipedia", wiki), ("oddspapi", op_scores))
                        if v and k2 in v} for k2 in ukontr_for}
        ukontr_for, bekreftet, uenige = resultatregel.kontroller_ukontrollerte("obos", ukontr_for, svar_pk)
        for k2 in bekreftet:
            log(f"  {k2[0]} mot {k2[1]}: publisert uten kontroll, nå bekreftet")
        for k2, r, uavh in uenige:
            conflicts.append(f"{k2[0]} mot {k2[1]}: publisert {r[0]}-{r[1]} uten kontroll, men "
                             + ", ".join(f"{kilde} har {v[0]}-{v[1]}" for kilde, v in uavh.items()))
    ukontr_for.update(ukontrollert)
    log(f"\nNye resultater: {len(publish) - len(prev)}. Venter: {len(waiting)}. Konflikter: {len(conflicts)}. "
        f"Uten kontroll: {len(ukontr_for)}.")
    for c in conflicts:
        log(f"  KONFLIKT {c}")
    for w2 in waiting:
        log(f"  venter: {w2}")
    for k2, r in ukontr_for.items():
        log(f"  UTEN KONTROLL {k2[0]} mot {k2[1]} {r[0]}-{r[1]} (bare ligasiden)")
    # Én linje per nytt resultat (4.10.2026), og når hver kilde først hadde det.
    if linjer:
        log("  Resultatene:")
        for l2 in linjer:
            log(f"    {l2}")
    kilder_naa = {"ligasiden": off, "highlightly": hl, "oddspapi": op_scores, "wikipedia": wiki, "fotball.no": nff}
    aktuelle = set(ventende) | {k2 for v in kilder_naa.values() if v for k2 in v if k2 not in prev and k2 in sched}
    forst, forst_linjer = resultatregel.forst_sett(
        gml_state.get("forst_sett"), {k2: {kilde: (v or {}).get(k2) for kilde, v in kilder_naa.items()} for k2 in aktuelle},
        now, set(prev))
    if forst_linjer:
        log("  Først hos kilden (kjøringen som så det):")
        for l2 in forst_linjer:
            log(f"    {l2}")

    rows = []
    for k2, (hg, ag) in publish.items():
        s = sched.get(k2)
        if not s:
            continue
        rows.append({"date": s["date"], "time": s["time"], "round": s["round"],
                     "home": k2[0], "away": k2[1], "hg": hg, "ag": ag})
    rows.sort(key=lambda m: (m["date"], m["time"], m["home"]))

    problems = validate(rows, sched, prev)
    if problems:
        log("\nVALIDERINGEN FEILET. Forrige datasett beholdes uendret:")
        for p in problems:
            log(f"  {p}")
        return 3

    # En tørrkjøring skriver ingenting, heller ikke tilstanden.
    if not args.dry_run:
        STATE.write_text(json.dumps({
            "checked_at": now.isoformat(timespec="seconds"),
            "published": len(rows), "new": len(publish) - len(prev),
            "conflicts": conflicts, "waiting": waiting,
            # Publisert uten kontroll (bare ligasiden, etter 24 timer): kjøringen
            # er rød til en uavhengig kilde bekrefter dem (resultatregel.py sjekk).
            "ukontrollert": {f"{k2[0]}|{k2[1]}": list(r) for k2, r in ukontr_for.items()},
            "ukontrollert_sjekket": now.isoformat(timespec="seconds") if sjekket_naa else sist,
            "oddspapi_usage": oddspapi.usage()[0],
            # Når hver kilde først hadde resultatet, for kampene som venter
            # (bare til loggen, resultatregel.forst_sett).
            "forst_sett": forst,
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    if args.dry_run:
        log(f"\n--dry-run: ville publisert {len(rows)} resultater (ingenting skrevet)")
    else:
        MATCHES.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        log(f"\nPubliserte {len(rows)} resultater til {MATCHES.relative_to(ROOT) if MATCHES.is_relative_to(ROOT) else MATCHES}")
    used, limit = oddspapi.usage()
    log(f"OddsPapi-forbruk denne måneden: {used} av {limit} tellende kall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
