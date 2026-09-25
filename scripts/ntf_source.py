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
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ligaer import oppsett

OSLO = ZoneInfo("Europe/Oslo")

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


def parse_rad(rad, kilde, cfg, klasser="", naa=None, log=lambda s: None):
    """Én kamprad -> dict, eller None hvis raden ikke hører til ligaen."""
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
        raise EsDataError(f"manglende dato for {hjemme} - {borte} ({kilde})")
    dato = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"

    t = TID_RE.search(dato_celle)
    tid = t.group(1) if t else None

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


def parse_side(html_tekst, kilde, liga, naa=None, log=lambda s: None):
    cfg = oppsett(liga)
    naa = naa or datetime.now(OSLO)
    ut = []
    for klasser, rad in RAD_RE.findall(html_tekst):
        rad_data = parse_rad(rad, kilde, cfg, klasser, naa, log)
        if rad_data:
            ut.append(rad_data)
    if not ut:
        raise EsDataError(f"fant ingen kamper på {kilde} -- har siden lagt om markupen?")
    return ut


def slå_sammen(rader, log=lambda s: None):
    """Dedupliserer på (hjemmelag, bortelag).

    "Neste kamp" står BÅDE som egen framhevet rad og i den vanlige listen --
    på OBOS-terminlisten 25. sep 2026 gjaldt det to kamper med samme
    avsparkstid. Radene skal være identiske. Er de ikke det, har siden to
    ulike svar om samme kamp, og det skal sies fra om.

    Terminlisten og resultatsiden er disjunkte i praksis (spilt / ikke
    spilt), men hvis en kamp skulle stå begge steder vinner raden som har
    resultat.
    """
    ut = {}
    for r in rader:
        k = (r["home"], r["away"])
        f = ut.get(k)
        if f is None:
            ut[k] = r
            continue
        if f["hg"] is None and r["hg"] is not None:
            ut[k] = r
        elif (f["date"], f["time"], f["round"]) != (r["date"], r["time"], r["round"]):
            log(f"ADVARSEL: {k[0]}-{k[1]} står to ganger med ulikt innhold: "
                f"{f['date']} {f['time']} #{f['round']} vs "
                f"{r['date']} {r['time']} #{r['round']} -- bruker den første")
    return list(ut.values())


def hent(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            raise RateLimited(e.code) from e
        raise


def fetch_all(liga, cache_dir=None, log=lambda s: None, naa=None):
    """Begge sidene for én liga, slått sammen til én liste kamper.

    Terminlisten må hentes gjennom hele sesongen, ikke bare ved oppstart:
    rundenummeret følger kampen, men dato og avspark endres når enkeltkamper
    eller hele runder flyttes.

    Resultatsiden og terminlisten er disjunkte i praksis (spilt / ikke spilt),
    men hvis en kamp skulle stå begge steder vinner raden som har resultat."""
    cfg = oppsett(liga)
    naa = naa or datetime.now(OSLO)
    rader = []
    for navn in ("resultater", "terminliste"):
        sti = cache_dir and (Path(cache_dir) / f"{liga}_{navn}.html")
        if sti and sti.exists():
            log(f"[ntf {liga}] {navn}: fra lokal cache")
            tekst = sti.read_text(encoding="utf-8")
        else:
            log(f"[ntf {liga}] henter {navn} ...")
            tekst = hent(f"{cfg['ntf_base']}/{navn}")
            if sti:
                sti.parent.mkdir(parents=True, exist_ok=True)
                sti.write_text(tekst, encoding="utf-8")
        rader.extend(parse_side(tekst, navn, liga, naa=naa, log=log))

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
