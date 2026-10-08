"""Hovedkilde: Norsk Toppfotball sine ligasider (eliteserien.no, obos-ligaen.no).

PROTOTYP. Ligger i laben, ikke i produksjon. Tiltenkt å erstatte
ffksupporter.net (Eliteserien) som hovedkilde for terminliste, runde, dato og
avspark. De to ligasidene har identisk markup, så samme parser dekker begge --
det eneste som skiller dem er domenet, liga-logoen og navnekartet, og alt tre
ligger i ligaer.py.

To sider dekker sesongen til sammen:
    /terminliste   kampene som ikke er spilt (runde, dato, avspark)
    /resultater    kampene som er spilt (runde, dato, avspark, resultat)

Begge må hentes gjennom hele sesongen. Rundenummeret følger kampen, men dato
og avspark endres når enkeltkamper eller hele runder flyttes -- typisk av
hensyn til europacup og landslagspauser. En kamp som flyttes forsvinner ikke
fra terminlisten, den får ny dato, og nøkkelen (hjemmelag, bortelag) holder
identiteten på plass.

Tre feller i markupen, alle tre dekket av testene i test_es_source.py:

  1. "Neste kamp" har eget radoppsett. Den øverste kommende kampen mangler
     --round-cellen; rundenummeret ligger i datocellen i stedet, og
     klokkeslettet i en egen <span class="schedule__time">.
  2. Motstanderen står i ulik CSS-klasse på de to sidene:
     schedule__team--opponent på terminlisten, results__team--opponent på
     resultatsiden. Parseren matcher derfor bare på suffikset --opponent.
  3. To lagnavn avviker fra navnene vi bruker: KFUM og Sandefjord Fotball.
     Se ligaer.py. Et ukjent lagnavn er en feil, ikke noe som hoppes over
     stille -- da har siden endret seg og kjøringen skal stoppe synlig.

Sidene viser også NM-cupen. Radene filtreres på liga-logoen (ntf_liga_alt),
med ett unntak: "neste kamp"-raden har ingen liga-celle, og hentes fra
terminlisten der bare ligaens egne kamper står.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import hentelogg
from ligaer import oppsett

OSLO = ZoneInfo("Europe/Oslo")

# Reporoten, der data/sesonger.json ligger. Samme monster som
# daglig_revisjon.ROT: testene peker den til en sandkasse.
ROT = Path(__file__).resolve().parent.parent

USER_AGENT = "eliteserien-tabell (+https://github.com/fiskentnt/eliteserien)"

RAD_RE = re.compile(r'<tr[^>]*class="([^"]*schedule__match[^"]*)"[^>]*>(.*?)</tr>', re.S)

# Bare en rad som er EKSPLISITT merket ferdigspilt gir resultat. Alt annet --
# en pågående kamp, en pause, en avbrutt kamp, en klasse vi ikke har sett --
# behandles som uspilt, og sies fra om. Vi har aldri sett en pågående kamp i
# denne markupen (sidene ble hentet mellom runder), så den ukjente tilstanden
# er nettopp den vi ikke får lov til å gjette på.
FERDIG_KLASSE = "schedule__match--played"

# KLOKKEREGEL, i tillegg til radklassen.
#
# Fram til naa hvilte vernet mot en paagaaende kamp paa to uavhengige ben:
# ligasidens radklasse, og en tidsgrense hos fotball.no. Naar fotball.no bare
# hentes en gang i dognet, staar radklassen alene -- og den er nettopp det vi
# ikke kjenner ennaa, siden vi aldri har sett en kamp underveis i markupen.
#
# Klokken koster ingen ekstra henting. En kamp som starter presis er ferdig
# 105-115 minutter etter avspark; 110 er derfor en grense som i verste fall
# utsetter et ferdig resultat noen faa minutter, og som til gjengjeld gjor at
# en ukjent klasse ikke alene kan gjore en paagaaende kamp ferdig.
#
# Regelen gjelder OGSAA naar radklassen mangler eller er ukjent: da er den
# det eneste vernet vi har igjen.
FERDIG_ETTER_MIN = 110
KJENTE_KLASSER = ("schedule__match--played", "schedule__match--upcoming",
                  "future__match__terminlist")
CELLE_RE = re.compile(r'<td[^>]*class="([^"]*)"[^>]*>(.*?)</td>', re.S)
LAG_RE = re.compile(r'([^<>]+?)\s*-\s*<span[^>]*--opponent"[^>]*>([^<]+)</span>', re.S)
DATO_RE = re.compile(r'(\d{2})\.(\d{2})\.\s*<span[^>]*--date__year"[^>]*>(\d{4})</span>')
TID_RE = re.compile(r'(?:schedule__time"[^>]*>\s*)?\b([012]\d:[0-5]\d)\b')
RUNDE_RE = re.compile(r'#(\d+)')
RESULTAT_RE = re.compile(r'^\s*(\d+)\s*-\s*(\d+)\s*$')


class EsDataError(Exception):
    """Siden kunne ikke tolkes -- ukjent lagnavn, manglende runde eller dato.

    Skal ikke fanges stille. Hvis eliteserien.no legger om markupen, skal
    kjøringen feile synlig i stedet for å levere en halv terminliste."""


class TomSide(EsDataError):
    """Siden ble tolket, men inneholdt ingen kamprader.

    Egen type fordi de to feilmaatene er ulike: en tolkningsfeil er ALLTID
    galt, mens en tom TERMINLISTE er riktig naar sesongen er ferdigspilt.
    Uten dette skillet maatte fetch_all gjette paa feilmeldingens ordlyd."""


class SvarerIkke(Exception):
    """Ligasiden svarte ikke: nettverksfeil, tidsavbrudd, HTTP-feil eller
    blokkering (403/429). Det er BARE da fotball.no kan hentes automatisk,
    som reserve (se nff_source.py). En side som svarer, men som vi ikke
    forstaar, er en feil hos oss og gir ingen reserve."""


class RateLimited(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f"eliteserien.no svarte {code}")


def _celler(rad):
    """class-streng -> innhold, for cellene i én rad."""
    return {k: v for k, v in CELLE_RE.findall(rad)}


def _finn(celler, suffiks):
    for k, v in celler.items():
        if suffiks in k:
            return v
    return None


def _navn(rått, cfg):
    n = html.unescape(rått).strip()
    n = cfg["navn"].get(n, n)
    if n not in cfg["lag"]:
        raise EsDataError(f"ukjent lagnavn fra {cfg['ntf_base']}: {rått.strip()!r} (tolket som {n!r})")
    return n


# NTFS RESULTATSIDE OG UTC (2.10.2026). Ranheim - Egersund hadde avspark
# 19:00 norsk tid (terminlisten, kalenderfeeden og OddsPapi 17:00Z), men
# etter kampen viste resultatsiden og kampsiden "17:00": avsparket i UTC.
# Lest som norsk tid ble det lagret to timer for tidlig, og klokkeregelen
# under (FERDIG_ETTER_MIN) regnet fra et avspark som var 120 minutter for
# tidlig: den aapnet 10 minutter FOER avspark i stedet for 110 etter (om
# vinteren 50 minutter etter avspark). De 184 eldre OBOS-kampene og alle
# 168 i Eliteserien staar paa resultatsiden i norsk tid (kontrollert mot
# OddsPapi 3.10.2026), saa tiden derfra kan ikke regnes om fra UTC uten
# videre: det ville flyttet dem en eller to timer. Regelen: viser
# resultatsiden det avsparket vi alt kjenner for kampen (fra terminlisten,
# lagret i fixtures.json), men i UTC, regnes den om til norsk tid. Ellers
# staar den som den er. Omregningen skjer foer klokkeregelen. Viser den en
# tid som verken er vaart avspark eller det i UTC, brukes sidens tid, men
# det logges som AVVIK (4.10.2026).
def _utc_til_oslo(dato, tid):
    """(dato, tid) lest som UTC -> (dato, tid) i norsk tid."""
    d = datetime.fromisoformat(f"{dato}T{tid}:00").replace(tzinfo=timezone.utc).astimezone(OSLO)
    return d.strftime("%Y-%m-%d"), d.strftime("%H:%M")


def kjente_avspark(liga, rot=None):
    """{(hjemme, borte): (dato, tid)} i norsk tid fra fixtures.json (fra
    terminlisten), med matches.json som reserve. Tomt hvis filene mangler."""
    data = Path(rot or ROT) / oppsett(liga)["data"]
    ut = {}
    for fil in ("matches.json", "fixtures.json"):     # fixtures.json sist: den vinner
        try:
            d = json.loads((data / fil).read_text(encoding="utf-8"))
        except Exception:
            continue
        kamper = [m for r in d for m in r.get("matches", [])] if fil == "fixtures.json" else d
        for m in kamper:
            if m.get("date") and m.get("time"):
                ut[(m["home"], m["away"])] = (m["date"], m["time"])
    return ut


def kjente_uspilte(liga, rot=None):
    """{(hjemme, borte): (dato, tid)} for kampene som er USPILTE hos oss:
    i fixtures.json uten played, og uten resultat i matches.json. Brukes naar
    terminlisten viser en uspilt kamp uten dato (se parse_rad). Bare uspilte:
    paa terminlisten kan samme lagpar vaere neste sesongs kamp, og den skal
    ikke faa datoen til aarets spilte kamp. Tomt hvis filene mangler."""
    data = Path(rot or ROT) / oppsett(liga)["data"]
    try:
        runder = json.loads((data / "fixtures.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    try:
        spilte = {(m["home"], m["away"]) for m in json.loads((data / "matches.json").read_text(encoding="utf-8"))
                  if m.get("hg") is not None}
    except Exception:
        spilte = set()
    return {(m["home"], m["away"]): (m["date"], m.get("time"))
            for r in runder for m in r.get("matches", [])
            if not m.get("played") and m.get("date") and (m["home"], m["away"]) not in spilte}


def parse_rad(rad, kilde, cfg, klasser="", naa=None, log=lambda s: None,
              har_resultat=None, hoppet=None, kjent_avspark=None, uspilt_avspark=None):
    """Én kamprad -> dict, eller None hvis raden ikke hører til ligaen.

    har_resultat(hjemme, borte): True hvis kampen alt har resultat i
    matches.json. Da stopper ikke en ugyldig dato hentingen: raden hoppes over
    med en advarsel (og legges i listen hoppet). Brukes bare paa
    resultatsiden. Uten resultat stopper en ugyldig dato fortsatt alt.

    kjent_avspark: {(hjemme, borte): (dato, tid)} i norsk tid (kjente_avspark).
    Viser raden det kjente avsparket i UTC, regnes den om (se over). Brukes
    bare paa resultatsiden.

    uspilt_avspark: {(hjemme, borte): (dato, tid)} for kampene som er uspilte
    hos oss (kjente_uspilte). En USPILT rad uten dato beholder da dato og
    avspark herfra i stedet for aa stoppe hele siden. En spilt rad uten dato
    (merket ferdigspilt eller med resultat) avvises fortsatt."""
    naa = naa or datetime.now(OSLO)
    celler = _celler(rad)
    lag_celle = _finn(celler, "--teams")
    if lag_celle is None:
        return None

    # Cup-kamper luftes ut på resultatsiden, der liga-cellen finnes.
    liga = _finn(celler, "--league")
    if liga is not None and f'alt="{cfg["ntf_liga_alt"]}"' not in liga:
        return None

    ren = re.sub(r'<span class="team-form[^>]*>\s*</span>', "", lag_celle)
    m = LAG_RE.search(ren)
    if not m:
        raise EsDataError(f"klarte ikke lese lagene fra rad ({kilde}): {ren.strip()[:200]!r}")
    hjemme, borte = _navn(m.group(1), cfg), _navn(m.group(2), cfg)

    dato_celle = _finn(celler, "--date") or ""
    d = DATO_RE.search(dato_celle)
    if not d:
        # NTF viste "Invalid date." for Kongsvinger - Hødd (spilt 20.9.2026,
        # 5-1) paa OBOS-resultatsiden, og hele hentingen stoppet hver dag.
        # Har kampen alt resultat hos oss, er raden ikke noe vi trenger.
        if har_resultat is not None and har_resultat(hjemme, borte):
            melding = (f"ADVARSEL: ugyldig dato for {hjemme} - {borte} ({kilde}) -- "
                       f"kampen har alt resultat i matches.json, raden hoppes over")
            log(melding)
            print(melding, file=sys.stderr)
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::warning title=NTF: ugyldig dato::{melding}")
            if hoppet is not None:
                hoppet.append(f"{hjemme} - {borte}")
            return None
        # En USPILT kamp uten dato stopper ikke resten av siden (3.10.2026:
        # NTF viste Sandnes Ulf - Haugesund og saa Bryne - Raufoss uten dato
        # mens kampene ble endret, og hele terminlisten ble avvist i 50
        # minutter -- ingen resultater ble publisert, og reserven satte
        # tilbake et avspark vi hadde rettet). Dato og avspark beholdes fra
        # det vi har. Bare for kamper som er uspilte hos oss, og bare naar
        # raden heller ikke hos NTF er spilt.
        res0 = _finn(celler, "--result")
        spilt_hos_ntf = (FERDIG_KLASSE in klasser.split()
                         or bool(res0 and RESULTAT_RE.match(re.sub(r"<[^>]+>", "", res0))))
        kjent = (uspilt_avspark or {}).get((hjemme, borte))
        if not kjent or spilt_hos_ntf:
            raise EsDataError(f"manglende dato for {hjemme} - {borte} ({kilde})")
        melding = (f"ADVARSEL: manglende dato for {hjemme} - {borte} ({kilde}) -- kampen er "
                   f"uspilt, beholder datoen og avsparket vi har ({kjent[0]} {kjent[1] or 'uten klokkeslett'})")
        log(melding)
        print(melding, file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=NTF: manglende dato::{melding}")
        dato, tid = kjent
    else:
        dato = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"
        t = TID_RE.search(dato_celle)
        tid = t.group(1) if t else None
    if d and tid and kjent_avspark:
        kjent = kjent_avspark.get((hjemme, borte))
        if kjent and (dato, tid) != kjent and _utc_til_oslo(dato, tid) == kjent:
            log(f"MERK: {hjemme} - {borte} ({kilde}) viser avspark {dato} {tid}, som er det "
                f"kjente avsparket {kjent[0]} {kjent[1]} norsk tid i UTC -- regnet om til norsk tid")
            dato, tid = kjent
        elif (kjent and (dato, tid) != kjent and dato[:4] == kjent[0][:4]
              and har_resultat is not None and har_resultat(hjemme, borte)):
            # SPILT hos oss (8.10.2026): datoen og avsparket beholdes.
            # eliteserien.no viste 7.10. Start-Tromsø (spilt 3.5.) som 5.1.,
            # Tromsø-Vålerenga (11.7.) som 18.11. og Brann-Rosenborg (2.8.)
            # som 19.2.; før sto det "bruker" her. Se reconcile_ny.frys_spilte.
            # Bare i samme sesong: de samme lagene møtes igjen neste år, og en
            # 2027-rad er en annen kamp. Den skal sesonggrensen se
            # (bare_aktiv_sesong), ikke få 2026-datoen vår.
            vis = lambda d, t: t if d == kjent[0] == dato else f"{int(d[8:10])}.{int(d[5:7])}. {t}"
            melding = (f"Kamp {hjemme}-{borte} er spilt: ligasiden viser {vis(dato, tid)}, vi har "
                       f"{vis(*kjent)}, beholder {vis(*kjent)}")
            log(f"AVVIK: {melding}")
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::warning title=Ligasiden: annen dato for spilt kamp::{melding}")
            dato, tid = kjent
        elif kjent and (dato, tid) != kjent:
            # Verken vårt avspark eller det samme i UTC (4.10.2026): ligasiden
            # er hovedkilden, så tiden derfra brukes, men det sies fra om.
            vis = lambda d, t: t if d == kjent[0] == dato else f"{int(d[8:10])}.{int(d[5:7])}. {t}"
            melding = (f"Kamp {hjemme}-{borte}: ligasiden viser {vis(dato, tid)}, vi hadde "
                       f"{vis(*kjent)}, bruker {vis(dato, tid)}")
            log(f"AVVIK: {melding}")
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::warning title=Ligasiden: annet avspark::{melding}")

    # Runde står normalt i egen celle. "Neste kamp" har den i datocellen.
    runde_celle = _finn(celler, "--round")
    r = RUNDE_RE.search(runde_celle) if runde_celle else RUNDE_RE.search(dato_celle)
    if not r:
        raise EsDataError(f"manglende rundenummer for {hjemme} - {borte} ({kilde})")

    merket_ferdig = FERDIG_KLASSE in klasser.split()
    ukjent = not any(k in klasser.split() for k in KJENTE_KLASSER)

    # Klokken, uavhengig av klassen. Mangler avspark, kan vi ikke regne --
    # da faar klassen bestemme alene, som for.
    lenge_nok, siden = True, None
    if tid:
        avspark = datetime.fromisoformat(f"{dato}T{tid}:00").replace(tzinfo=OSLO)
        siden = (naa - avspark).total_seconds() / 60
        lenge_nok = siden >= FERDIG_ETTER_MIN

    ferdig = merket_ferdig and lenge_nok

    hg = ag = None
    res_celle = _finn(celler, "--result")
    rm = RESULTAT_RE.match(re.sub(r"<[^>]+>", "", res_celle)) if res_celle else None
    if rm and ferdig:
        hg, ag = int(rm.group(1)), int(rm.group(2))
    elif rm and merket_ferdig and not lenge_nok:
        log(f"ADVARSEL: {hjemme} - {borte} ({kilde}) står {rm.group(1)}-{rm.group(2)} "
            f"og er merket ferdigspilt, men det er bare {siden:.0f} min siden "
            f"avspark (grensen er {FERDIG_ETTER_MIN}) -- regnes som IKKE spilt")
    elif rm:
        # Det STÅR et resultat, men raden er ikke merket ferdigspilt. Det er
        # slik en kamp underveis ser ut. Stillingen er ikke et sluttresultat.
        log(f"ADVARSEL: {hjemme} - {borte} ({kilde}) har stillingen "
            f"{rm.group(1)}-{rm.group(2)}, men raden er ikke merket ferdigspilt "
            f"(klasser: {klasser.strip()!r}) -- regnes som IKKE spilt")
    elif ukjent:
        log(f"ADVARSEL: {hjemme} - {borte} ({kilde}) har ukjent radstatus "
            f"(klasser: {klasser.strip()!r}) -- regnes som IKKE spilt")

    return {"date": dato, "time": tid, "round": int(r.group(1)),
            "home": hjemme, "away": borte, "hg": hg, "ag": ag,
            "ferdig": ferdig, "ukjent_status": ukjent}


def parse_side(html_tekst, kilde, liga, naa=None, log=lambda s: None,
               har_resultat=None, hoppet=None, kjent_avspark=None, uspilt_avspark=None):
    cfg = oppsett(liga)
    naa = naa or datetime.now(OSLO)
    ut = []
    for klasser, rad in RAD_RE.findall(html_tekst):
        rad_data = parse_rad(rad, kilde, cfg, klasser, naa, log,
                             har_resultat=har_resultat, hoppet=hoppet,
                             kjent_avspark=kjent_avspark, uspilt_avspark=uspilt_avspark)
        if rad_data:
            ut.append(rad_data)
    if not ut:
        raise TomSide(f"fant ingen kamper på {kilde}")
    return ut


def slå_sammen(rader, log=lambda s: None):
    """Dedupliserer på (år, hjemmelag, bortelag).

    "Neste kamp" står BÅDE som egen framhevet rad og i den vanlige listen --
    på OBOS-terminlisten 25. sep 2026 gjaldt det to kamper med samme
    avsparkstid. Radene skal være identiske. Er de ikke det, har siden to
    ulike svar om samme kamp, og det skal sies fra om.

    Terminlisten og resultatsiden er disjunkte i praksis (spilt / ikke
    spilt), men hvis en kamp skulle stå begge steder vinner raden som har
    resultat. Det er en failsafe, ikke sesonggrensen: sesonggrensen settes
    eksplisitt i produksjonskjeden, av reconcile_ny.bare_aktiv_sesong().

    ÅRET ER MED I NØKKELEN, og det er ikke kosmetisk. Mellom siste runde og
    frysingen publiserer NTF neste sesongs terminliste med NØYAKTIG de samme
    lagparene. Med nøkkelen (hjemme, borte) alene var en 2026-kamp og en
    2027-kamp mellom samme lag "samme kamp", og to ting gikk galt:

      * OPPDAGELSEN BLE BLIND. Tie-breaket beholdt 2026-raden med resultat,
        så alle 240 2027-radene ble kastet. oppdag_sesong.py fant 0 kamper i
        2027, sesongen ble aldri "klar", og bytt() kunne aldri bytte 1.
        januar -- den alarmerte bare, hver dag, til noen kjørte oppdag for
        hånd. Hele det selvkjørende sesongskiftet sto altså på en
        duplikatregel som slo det av.
      * 240 ADVARSLER per kjøring i det vinduet, som druknet den ekte
        duplikatadvarselen -- to rader som er uenige om dato eller avspark
        for samme kamp, som er nettopp det advarselen finnes for.

    Innen samme sesong er nøkkelen uendret, så "neste kamp"-dupliseringen
    fanges som før.
    """
    ut = {}
    for r in rader:
        # Datoen finnes alltid: parse_rad kaster paa en rad uten dato.
        k = (r["date"][:4], r["home"], r["away"])
        f = ut.get(k)
        if f is None:
            ut[k] = r
            continue
        if f["hg"] is None and r["hg"] is not None:
            ut[k] = r
        elif (f["date"], f["time"], f["round"]) != (r["date"], r["time"], r["round"]):
            log(f"ADVARSEL: {k[1]}-{k[2]} står to ganger med ulikt innhold: "
                f"{f['date']} {f['time']} #{f['round']} vs "
                f"{r['date']} {r['time']} #{r['round']} -- bruker den første")
    return list(ut.values())


# TABELLEN staar paa resultatsiden vi alt henter (div league-table--full),
# saa tabellkontrollen (scripts/tabellkontroll.py) koster ingen ekstra
# forespoersel. Kolonnene: plass, lag, Spilt, Vunnet, Uavgjort, Tap, +, -,
# +/-, Poeng og Form. Tabellen viser poengene ETTER trekk fra NFF (Aasane 19
# i 2026), uten noen markering av trekket.
TABELL_RE = re.compile(r'<div class="league-table league-table--full">.*?</table>', re.S)
TABELL_KOLONNER = ["", "Spilt", "Vunnet", "Uavgjort", "Tap", "+", "-", "+/-", "Poeng", "Form"]
TH_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
TABELLRAD_RE = re.compile(r'<tr class="table__row[^"]*"[^>]*>(.*?)</tr>', re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
FULL_RE = re.compile(r'<span class="table__typo--full">(.*?)</span>', re.S)
TALL_RE = re.compile(r"^[-+\u2212]?\d+$")


def _ren(celle):
    full = FULL_RE.search(celle)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", full.group(1) if full else celle))).strip()


def parse_tabell(html_tekst, liga):
    """Tabellen paa resultatsiden: [{plass, lag, k, v, u, t, mf, mm, diff, poeng}].

    EsDataError hvis tabellen mangler, har andre kolonner eller feil antall
    lag -- da har siden lagt om, og kontrollen ville vaert verdiloes."""
    cfg = oppsett(liga)
    m = TABELL_RE.search(html_tekst)
    if not m:
        raise EsDataError(f"fant ingen tabell paa resultatsiden for {liga}")
    tab = m.group(0)
    kol = [_ren(x) for x in TH_RE.findall(tab)]
    if kol != TABELL_KOLONNER:
        raise EsDataError(f"uventede kolonner i tabellen for {liga}: {kol}")
    tall = lambda x: int(x.replace("\u2212", "-"))
    ut = []
    for rad in TABELLRAD_RE.findall(tab):
        c = [_ren(x) for x in TD_RE.findall(rad)]
        if len(c) != 11 or not all(TALL_RE.match(x) for x in [c[0]] + c[2:10]):
            raise EsDataError(f"uventet tabellrad for {liga}: {c}")
        ut.append({"plass": int(c[0]), "lag": _navn(c[1], cfg), "k": tall(c[2]), "v": tall(c[3]),
                   "u": tall(c[4]), "t": tall(c[5]), "mf": tall(c[6]), "mm": tall(c[7]),
                   "diff": tall(c[8]), "poeng": tall(c[9])})
    if len(ut) != len(cfg["lag"]) or len({r["lag"] for r in ut}) != len(ut):
        raise EsDataError(f"tabellen for {liga} har {len(ut)} rader, ventet {len(cfg['lag'])} lag")
    return ut


# Tabellen fra siste vellykkede henting i DENNE prosessen, per liga:
# {"tabell": [...], "hentet": ISO-tid, "kilde": URL} eller {"feil": tekst}.
# Fylles av fetch_all, leses av tabellkontrollen i samme kjoring.
SISTE_TABELL = {}


def siste_tabell(liga):
    return SISTE_TABELL.get(liga)


# KALENDERFEEDEN (/terminliste/subscribe) er laget av NTF for automatisk
# bruk, og er den loepende kontrollen av runde, dato og avspark
# (daglig_revisjon.py). Hver kamp er en VEVENT med "Hjemme - Borte" i
# SUMMARY, "(runde N)" i DESCRIPTION og avspark i norsk tid i DTSTART.
# Feeden har bare kommende kamper og ingen resultater. Les BARE mellom
# BEGIN:VEVENT og END:VEVENT: tidssonedefinisjonen (VTIMEZONE) har egne
# DTSTART-linjer. OBOS-feeden hadde to identiske dubletter i 2026; de slaas
# sammen, mens to oppfoeringer av samme kamp med ulik runde, dato eller tid
# er en feil -- da vet vi ikke hvilken som gjelder.
KAL_RUNDE_RE = re.compile(r"\(runde (\d+)\)")
# DTSTART med parametre (TZID=..., VALUE=DATE) og eventuelt Z (UTC). Tiden
# regnes om til norsk tid etter tidssonen den er oppgitt i (_kal_start):
# Z eller TZID=UTC er UTC, en annen TZID er den sonen, TZID=Europe/Oslo og
# ingen sone ("flytende" tid) er norsk tid. Foer godtok vi bare
# TZID=Europe/Oslo, og en tid i UTC ville stoppet hele revisjonen.
KAL_START_RE = re.compile(r"^DTSTART((?:;[A-Za-z-]+=[^;:]*)*):(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})\d{2}(Z?))?$")


def _kal_start(linje):
    """(dato, tid) i norsk tid fra en DTSTART-linje, eller None. tid er None
    for en heldagsoppfoering. EsDataError for en tidssone vi ikke kjenner."""
    m = KAL_START_RE.match(linje or "")
    if not m:
        return None
    param = dict(p.split("=", 1) for p in m.group(1).split(";") if "=" in p)
    dato = f"{m.group(2)}-{m.group(3)}-{m.group(4)}"
    if not m.group(5):
        return dato, None
    tid = f"{m.group(5)}:{m.group(6)}"
    sone = "UTC" if m.group(7) else param.get("TZID", "Europe/Oslo").strip('"')
    if sone in ("Europe/Oslo", ""):
        return dato, tid
    try:
        tz = timezone.utc if sone.upper() in ("UTC", "Z", "ETC/UTC", "GMT") else ZoneInfo(sone)
    except Exception:
        raise EsDataError(f"ukjent tidssone i kalenderfeeden: {linje}")
    d = datetime.fromisoformat(f"{dato}T{tid}:00").replace(tzinfo=tz).astimezone(OSLO)
    return d.strftime("%Y-%m-%d"), d.strftime("%H:%M")


def hent_kalender(liga, log=lambda s: None):
    """Kalenderfeeden for ligaen som tekst. SvarerIkke hvis siden ikke svarer."""
    url = f"{oppsett(liga)['ntf_base']}/terminliste/subscribe"
    log(f"[ntf {liga}] henter kalenderfeeden ...")
    try:
        return hent(url)
    except Exception as e:
        hentelogg.logg(liga, "ntf-kalender", "feil", melding=f"{type(e).__name__}: {e}")
        if isinstance(e, (RateLimited, OSError)):
            raise SvarerIkke(f"{url}: {type(e).__name__}: {e}") from e
        raise


def parse_kalender(tekst, liga):
    """[{round, date, time, home, away}] fra kalenderfeeden. EsDataError hvis
    den ikke kan leses, eller samme kamp staar med ulik runde, dato eller tid."""
    cfg = oppsett(liga)
    # Lange linjer er brettet: linjeskift fulgt av mellomrom eller tab.
    linjer = re.sub(r"\r?\n[ \t]", "", tekst).splitlines()
    hendelser, cur = [], None
    for l in linjer:
        if l == "BEGIN:VEVENT":
            cur = {}
        elif l == "END:VEVENT":
            if cur is not None:
                hendelser.append(cur)
            cur = None
        elif cur is not None and ":" in l:
            navn = l.split(":", 1)[0].split(";", 1)[0]
            if navn in ("SUMMARY", "DESCRIPTION", "DTSTART"):
                cur[navn] = l if navn == "DTSTART" else l.split(":", 1)[1]
    ut = {}
    for h in hendelser:
        lag = (h.get("SUMMARY") or "").split(" - ")
        r = KAL_RUNDE_RE.search(h.get("DESCRIPTION") or "")
        d = _kal_start(h.get("DTSTART"))
        if len(lag) != 2 or not r or not d:
            raise EsDataError(f"uventet oppføring i kalenderfeeden for {liga}: {h}")
        rad = {"round": int(r.group(1)), "date": d[0], "time": d[1],
               "home": _navn(lag[0].replace("\\,", ","), cfg), "away": _navn(lag[1].replace("\\,", ","), cfg)}
        k = (rad["home"], rad["away"])
        if k in ut and ut[k] != rad:
            raise EsDataError(f"{k[0]}-{k[1]} står to ganger i kalenderfeeden for {liga} med ulik "
                              f"runde, dato eller tid: {ut[k]} og {rad}")
        ut[k] = rad
    if not ut:
        raise EsDataError(f"kalenderfeeden for {liga} hadde ingen kamper")
    return sorted(ut.values(), key=lambda m: (m["date"], m["time"] or "", m["home"]))


def hent(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            raise RateLimited(e.code) from e
        raise


def sesongen_ferdigspilt(navn, hittil, liga, rot=None):
    """Er en TOM side gyldig? (ja/nei, begrunnelse)

    ANTALLET avgjor, ikke datoen. En datoregel -- "etter byttedatoen", "etter
    siste oppsatte runde" -- godtar en tom terminliste ogsaa naar en utsatt
    kamp fortsatt gjenstaar, og da mister vi nettopp den kampen.

    Terminlisten kan bare vaere tom naar resultatsiden samtidig viser en
    KOMPLETT FERDIGSPILT sesong. Hva "komplett" betyr, avgjores ikke her:
    sesong.valider() er den autoritative regelen, den samme frysingen og
    sesongskiftet bruker. Den krever unike lagpar, ingen duplikater, alle
    oppgjor til stede, 15 hjemme- og 15 bortekamper per lag, runde 1-30 og
    riktig aarstall. Antall RADER er ikke nok: 239 unike par pluss en
    duplikat gir ogsaa 240 rader.

    Resultatsiden kan aldri vaere tom -- da har kilden lagt om markupen,
    eller svart med noe annet enn det vi ba om.

    MERK: regelen hviler paa at fetch_all henter "resultater" FOR
    "terminliste", slik at de ferdigspilte kampene er kjent naar
    terminlisten tolkes."""
    if navn != "terminliste":
        return False, f"{navn} ga 0 kamper -- resultatsiden kan aldri være tom"

    import sesong as _ses
    rot = rot or ROT
    aar = _ses.aktiv_sesong(rot, liga, log=lambda _s: None)
    if not aar:
        # Uten sesongautoritet kan vi ikke avgjore dette. Da er en tom
        # terminliste en feil, ikke noe vi godtar paa antagelse.
        return False, ("terminlisten er tom, men det finnes ingen "
                       "sesongautoritet å bekrefte ferdigspilt sesong mot")

    ferdige = [r for r in hittil if r.get("hg") is not None]
    ok, funn = _ses.valider(ferdige, aar)
    if not ok:
        grunner = [t for alvor, t in funn if alvor == "feil"]
        return False, (f"terminlisten er tom, men {aar} er ikke ferdigspilt: "
                       + "; ".join(grunner[:2]))
    return True, f"sesongen {aar} er ferdigspilt ({len(ferdige)} kamper)"


def fetch_all(liga, cache_dir=None, log=lambda s: None, naa=None):
    """Begge sidene for én liga, slått sammen til én liste kamper.

    Terminlisten må hentes gjennom hele sesongen, ikke bare ved oppstart:
    rundenummeret følger kampen, men dato og avspark endres når enkeltkamper
    eller hele runder flyttes.

    Resultatsiden og terminlisten er disjunkte i praksis (spilt / ikke spilt),
    men hvis en kamp skulle stå begge steder vinner raden som har resultat.

    RETURNERER ALLE SESONGER DEN SER. I vinduet mellom siste runde og
    frysingen viser sidene bade fjoraaret og neste sesong, og da er dette
    480 rader, ikke 240. Kildelaget skal returnere det det ser; hvilken
    sesong som gjelder, avgjores av kalleren. ALLE KALLERE, og hva de gjor:

      scripts/update_data.py         FILTRERER -- bare_aktiv_sesong() rett
                                     etter dette kallet, for reconcile
      scripts/obos_build_data.py     FILTRERER -- samme, i rows_for(), og
                                     utenfor reservene (forrige terminliste, CSV)
      scripts/obos_results.py        FILTRERER -- samme, i ligaside_results()
      scripts/oppdag_sesong.py       SER ALLE SESONGER, med vilje: den skal
                                     finne NESTE sesongs terminliste, og
                                     gjor sin egen utvelging paa aarstall

    Legger du til en kaller: den skal filtrere, med mindre den har en grunn
    til aa se flere sesonger. Ingen skal fa 480 rader uten aa vite det."""
    cfg = oppsett(liga)
    naa = naa or datetime.now(OSLO)
    rader = []
    # Kamper som alt har resultat hos oss. Bare resultatsiden bruker dette:
    # der kan en rad med ugyldig dato hoppes over naar vi alt har kampen.
    # Paa terminlisten kan samme lagpar vaere NESTE sesongs kamp, og der
    # stopper en ugyldig dato fortsatt hentingen.
    try:
        _ms = json.loads((ROT / cfg["data"] / "matches.json").read_text(encoding="utf-8"))
        med_resultat = {(m["home"], m["away"]) for m in _ms if m.get("hg") is not None}
    except Exception:
        med_resultat = set()
    for navn in ("resultater", "terminliste"):
        hoppet = []
        sti = cache_dir and (Path(cache_dir) / f"{liga}_{navn}.html")
        if sti and sti.exists():
            log(f"[ntf {liga}] {navn}: fra lokal cache")
            tekst = sti.read_text(encoding="utf-8")
        else:
            log(f"[ntf {liga}] henter {navn} ...")
            try:
                tekst = hent(f"{cfg['ntf_base']}/{navn}")
            except Exception as e:
                # Logges FOR den kastes videre. Kalleren bestemmer om det er
                # kritisk; loggen skal ha linjen uansett. Svarte ikke siden
                # (nett, tidsavbrudd, HTTP-feil, blokkering), kastes
                # SvarerIkke: bare da kan kalleren bruke fotball.no som reserve.
                hentelogg.logg(liga, f"ntf-{navn}", "feil", melding=f"{type(e).__name__}: {e}")
                if isinstance(e, (urllib.error.URLError, RateLimited, TimeoutError, ConnectionError, OSError)):
                    raise SvarerIkke(f"{cfg['ntf_base']}/{navn}: {type(e).__name__}: {e}") from e
                raise
            if sti:
                sti.parent.mkdir(parents=True, exist_ok=True)
                sti.write_text(tekst, encoding="utf-8")
        # Tolkningen ligger INNE i loggingen, ikke bare hentingen. En side
        # som svarer 200 men har lagt om markupen gir 0 kamper, og
        # parse_side kaster da. Sto kastet utenfor, ble den verste
        # feilmaaten -- kilden svarer, men vi forstaar den ikke -- aldri
        # loggfort, og alarmen kunne ikke se den.
        try:
            nye = parse_side(tekst, navn, liga, naa=naa, log=log,
                             har_resultat=(lambda h, b: (h, b) in med_resultat)
                             if navn == "resultater" else None,
                             hoppet=hoppet,
                             # Resultatsiden kan vise avsparket i UTC (se
                             # _utc_til_oslo); terminlisten viser norsk tid.
                             kjent_avspark=kjente_avspark(liga) if navn == "resultater" else None,
                             # En uspilt kamp uten dato beholder det vi har (parse_rad).
                             uspilt_avspark=kjente_uspilte(liga))
        except TomSide as e:
            ferdig, hvorfor = sesongen_ferdigspilt(navn, rader, liga, rot=ROT)
            if not ferdig:
                hentelogg.logg(liga, f"ntf-{navn}", "feil", kamper=0,
                               melding=hvorfor)
                raise
            # Gyldig tom terminliste: sesongen ER ferdigspilt. Loggfores som
            # "ok" med 0 kamper, ellers bygger sesongslutten en falsk
            # feilrekke og gjor kjoringen rod nettopp i frysevinduet.
            log(f"[ntf {liga}] terminliste: tom -- {hvorfor}")
            hentelogg.logg(liga, f"ntf-{navn}", "ok", kamper=0,
                           melding=hvorfor)
            continue
        except Exception as e:
            hentelogg.logg(liga, f"ntf-{navn}", "feil",
                           melding=f"{type(e).__name__}: {e}")
            raise
        hentelogg.logg(liga, f"ntf-{navn}", "ok", kamper=len(nye),
                       melding=(f"hoppet over rad med ugyldig dato (har resultat): "
                                f"{', '.join(hoppet)}") if hoppet else "")
        rader.extend(nye)
        if navn == "resultater":
            # Tabellen paa samme side, til tabellkontrollen. Kan den ikke
            # leses, er det en feil i kontrollen, ikke i resultatene.
            try:
                SISTE_TABELL[liga] = {"tabell": parse_tabell(tekst, liga), "kilde": f"{cfg['ntf_base']}/resultater",
                                      "hentet": naa.astimezone(timezone.utc).isoformat(timespec="seconds")}
                hentelogg.logg(liga, "ntf-tabell", "ok", kamper=len(SISTE_TABELL[liga]["tabell"]))
            except EsDataError as e:
                SISTE_TABELL[liga] = {"feil": str(e)[:300]}
                hentelogg.logg(liga, "ntf-tabell", "feil", melding=str(e)[:200])
                log(f"[ntf {liga}] ADVARSEL: tabellen kunne ikke leses: {e}")

    return slå_sammen(rader, log=log)


if __name__ == "__main__":
    from ligaer import LIGAER
    cache = sys.argv[1] if len(sys.argv) > 1 else None
    for liga in LIGAER:
        rader = fetch_all(liga, cache_dir=cache, log=lambda s: print(s, file=sys.stderr))
        spilt = sum(1 for r in rader if r["hg"] is not None)
        runder = sorted({r["round"] for r in rader})
        print(f"{liga:12} kamper: {len(rader)} ({spilt} spilt)  "
              f"runder: {runder[0]}-{runder[-1]} ({len(runder)} stk)")
