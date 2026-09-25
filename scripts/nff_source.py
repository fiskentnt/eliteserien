"""Uavhengig offisiell kontroll: NFF sin turneringsdatabase på fotball.no.

Dette er FIKS, forbundets eget kamparkiv, og den er uavhengig av Norsk
Toppfotball sine ligasider. Den dekker begge ligaer i nøyaktig samme
tabellformat, og gir runde, dato, avspark, lag og resultat i én forespørsel
per liga -- både spilte og kommende kamper i samme tabell.

Rollen her er kontroll og reserve, ikke hovedkilde. Poenget er at
terminlisten endelig får en annenmening: fram til nå har runde og dato hatt
nøyaktig én kilde, uten noe som kunne si fra når den tok feil.

Tabellen heter customSorterAtomicMatches og har kolonnene
    Runde | Dato | Dag | Tid | Hjemmelag | Resultat | Bortelag | Bane | Kampnr.
Kampnummeret er stabilt hos NFF, men nøkkelen vår er fortsatt
(hjemmelag, bortelag), slik at den er lik på tvers av alle kildene.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import hentelogg
from ligaer import oppsett

OSLO = ZoneInfo("Europe/Oslo")

# fotball.no har ingen statusmarkering i raden: en kamp underveis ser ut som
# en ferdigspilt kamp med en lavere stilling. Det eneste signalet vi har er
# klokka. En kamp regnes derfor ikke som ferdig før det er gått så lang tid
# at den MÅ være det -- 90 minutter pluss pause, tillegg og margin.
# Ligasiden (ntf_source) har en eksplisitt ferdig-klasse og er hovedkilden;
# denne grensen gjelder bare kontrollkilden.
FERDIG_ETTER_MIN = 150

# HVOR OFTE VI HENTER FRA fotball.no -- og hvorfor det er sjelden.
#
# robots.txt paa fotball.no navngir Googlebot, Bing og noen til, og avslutter
# med "User-agent: *" og "Disallow: /". Vaar User-Agent sier aerlig at vi er
# en robot, saa vi er omfattet. robots.txt er ikke lov, men det er forbundets
# uttrykte oenske, og aa hente derfra i hver kjoring er aa gaa imot det.
#
# Derfor: hoeyst ETT forsok per liga per doegn, uansett hvor mange workflows
# som spoer. Alle andre leser det som ligger i cachen. Et forsok som FEILER
# teller ogsaa -- ellers ville en nede-periode gitt nytt forsok hver time.
#
# Grensen ligger her, i kilden, ikke i hver kaller. Da kan den ikke omgaas
# ved at noen glemmer den.
HENT_INTERVALL_TIMER = 20
# NFF_CACHE_KATALOG finnes for testene, av samme grunn som
# HENTELOGG_KATALOG og ODDSPAPI_BRUK_KATALOG: failsafe-suiten kjorer de
# ekte skriptene i EGNE PROSESSER, og en subprosess ser ikke at testen
# har satt CACHE_KATALOG i sin egen. Produksjonen setter den ikke.
CACHE_KATALOG = Path(os.environ.get("NFF_CACHE_KATALOG")
                     or Path(__file__).resolve().parent.parent / "data" / "nff-cache")


def _cache_sti(liga):
    return CACHE_KATALOG / f"{liga}.json"


def les_cache(liga):
    p = _cache_sti(liga)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _skriv_cache(liga, d):
    p = _cache_sti(liga)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def sist_hentet(liga):
    """Naar fotball.no-svaret i cachen faktisk ble hentet, eller None."""
    d = les_cache(liga)
    try:
        return datetime.fromisoformat(d["hentet"]) if d.get("hentet") else None
    except (KeyError, ValueError):
        return None


def hentet_i_denne_kjoringen(liga):
    """Lyktes hentingen fra fotball.no i DENNE kjoringen?

    Det er dette frysingen krever. Feiler hentingen, faller fetch_all tilbake
    paa cachen og returnerer gamle rader -- de er brukbare til kontroll, men
    de sier ingenting om at dagens henting gikk bra."""
    import sesong as _s
    return les_cache(liga).get("hentet_av") == _s.kjoring_id()


def _forfalt(d, naa):
    """Er det over HENT_INTERVALL_TIMER siden SISTE FORSOK?"""
    forsokt = d.get("forsokt")
    if not forsokt:
        return True, "aldri hentet"
    try:
        alder = (naa - datetime.fromisoformat(forsokt)).total_seconds() / 3600
    except ValueError:
        return True, "ulesbart tidspunkt i cachen"
    if alder >= HENT_INTERVALL_TIMER:
        return True, f"siste forsøk var {alder:.0f} timer siden"
    return False, f"siste forsøk var {alder:.1f} timer siden, venter til {HENT_INTERVALL_TIMER}"

USER_AGENT = "eliteserien-tabell (+https://github.com/fiskentnt/eliteserien)"

TABELL_RE = re.compile(r"<table[^>]*customSorterAtomicMatches.*?</table>", re.S)
TURNERING_RE = re.compile(r"tournamentId=(\d+)")

# fotball.no/turneringer/<liga>/ viser ALLTID den aktive sesongen. En avsluttet
# sesong hentes med sin egen turnerings-id:
#   https://www.fotball.no/fotballdata/turnering/hjem/?fiksId=206092&underside=kamper
# Eliteserien 2026 = 206092, OBOS 2026 = 206093 (lest av kalenderlenken paa
# ligaens egen side 25. september 2026). Id-en lagres i cachen og folger med
# inn i den frosne sesongen, saa en senere reparasjon finner den selv.
SESONG_URL = ("https://www.fotball.no/fotballdata/turnering/hjem/"
              "?fiksId={turnering}&underside=kamper")


def turnering_url(turnering):
    return SESONG_URL.format(turnering=turnering)


def finn_turnering(html_tekst):
    """Turnerings-id-en siden gjelder, eller None."""
    m = TURNERING_RE.search(html_tekst)
    return m.group(1) if m else None
RAD_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELLE_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
DATO_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
TID_RE = re.compile(r"^([012]\d):([0-5]\d)$")
RESULTAT_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


class NffDataError(Exception):
    """Siden kunne ikke tolkes. Skal ikke fanges stille -- da har fotball.no
    lagt om, og kontrollen er verdiløs uten at noen merker det."""


class RateLimited(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f"fotball.no svarte {code}")


def _tekst(celle):
    return html.unescape(re.sub(r"<[^>]+>", " ", celle)).strip()


def _navn(rått, cfg):
    n = cfg["navn"].get(rått, rått)
    if n not in cfg["lag"]:
        raise NffDataError(f"ukjent lagnavn fra fotball.no: {rått!r} (tolket som {n!r})")
    return n


def parse_side(html_tekst, liga, naa=None, log=lambda s: None):
    cfg = oppsett(liga)
    naa = naa or datetime.now(OSLO)
    tabell = TABELL_RE.search(html_tekst)
    if not tabell:
        raise NffDataError(f"fant ingen kamptabell for {liga} på fotball.no")

    ut = []
    for rad in RAD_RE.findall(tabell.group(0)):
        celler = [_tekst(c) for c in CELLE_RE.findall(rad)]
        if len(celler) < 7:
            continue  # overskriftsraden har <th>, ikke <td>
        runde, dato, _dag, tid, hjemme, resultat, borte = celler[:7]

        d = DATO_RE.match(dato)
        if not d:
            raise NffDataError(f"uventet datoformat for {hjemme} - {borte} ({liga}): {dato!r}")
        if not runde.isdigit():
            raise NffDataError(f"uventet rundenummer for {hjemme} - {borte} ({liga}): {runde!r}")

        res = RESULTAT_RE.match(resultat)
        dato = f"{d.group(3)}-{d.group(2)}-{d.group(1)}"
        klokke = tid if TID_RE.match(tid) else None

        ferdig = True
        if res and klokke:
            avspark = datetime.fromisoformat(f"{dato}T{klokke}").replace(tzinfo=OSLO)
            if naa < avspark + timedelta(minutes=FERDIG_ETTER_MIN):
                ferdig = False
                log(f"ADVARSEL: {hjemme} - {borte} (fotball.no) står {resultat}, "
                    f"men det er under {FERDIG_ETTER_MIN} min siden avspark "
                    f"{dato} {klokke} -- regnes som IKKE ferdig")

        ut.append({
            "round": int(runde),
            "date": dato,
            "time": klokke,
            "home": _navn(hjemme, cfg),
            "away": _navn(borte, cfg),
            "hg": int(res.group(1)) if (res and ferdig) else None,
            "ag": int(res.group(2)) if (res and ferdig) else None,
            "ferdig": bool(res and ferdig),
        })

    if not ut:
        raise NffDataError(f"kamptabellen for {liga} var tom -- har fotball.no lagt om?")
    return ut


def hent(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            raise RateLimited(e.code) from e
        raise


def fetch_all(liga, cache_dir=None, log=lambda s: None, naa=None):
    """Hele sesongen for én liga -- fra cachen, eller ett forsøk i døgnet.

    Returnerer alltid en liste. Har vi ingenting i cachen og forsøket er
    sperret, er listen tom: da går kaller videre uten kontrollkilde, ikke i
    stykker.

    cache_dir er testinngangen: ligger filen der, brukes den og ingenting
    hentes over nett."""
    cfg = oppsett(liga)
    naa = naa or datetime.now(timezone.utc)

    sti = cache_dir and (Path(cache_dir) / f"nff_{liga}.html")
    if sti and sti.exists():
        log(f"[nff {liga}] fra lokal fil ({sti.name})")
        return parse_side(sti.read_text(encoding="utf-8"), liga, log=log)

    d = les_cache(liga)
    forfalt, hvorfor = _forfalt(d, naa)
    if not forfalt:
        rader = d.get("rader") or []
        log(f"[nff {liga}] {hvorfor} -- bruker lagret svar ({len(rader)} kamper)")
        hentelogg.logg(liga, "nff", "cache", kamper=len(rader), melding=hvorfor)
        return rader

    # Forsøket merkes FØR det gjøres. Feiler det, teller det likevel, og
    # neste forsøk kommer først om 20 timer.
    d["forsokt"] = naa.isoformat(timespec="seconds")
    _skriv_cache(liga, d)

    log(f"[nff {liga}] {hvorfor} -- henter {cfg['nff_url']}")
    try:
        tekst = hent(cfg["nff_url"])
        rader = parse_side(tekst, liga, naa=naa, log=log)
        # Turnerings-id-en for sesongen siden viste. Den folger med inn i den
        # frosne sesongen, slik at en reparasjon senere kan hente NETTOPP den
        # sesongen framfor den aktive.
        t = finn_turnering(tekst)
        if t:
            d["turnering"] = t
    except Exception as e:
        d["siste_feil"] = f"{type(e).__name__}: {e}"[:200]
        _skriv_cache(liga, d)
        log(f"[nff {liga}] FEILET ({type(e).__name__}) -- nytt forsøk om "
            f"{HENT_INTERVALL_TIMER} timer. Bruker det som lå i cachen.")
        hentelogg.logg(liga, "nff", "feil", melding=f"{type(e).__name__}: {e}")
        return d.get("rader") or []

    # HVILKEN KJORING som faktisk hentet. Et tidsstempel duger ikke: naar
    # hentingen feiler faller vi tilbake paa cachen, og "hentet for 30
    # sekunder siden" ville da sett ferskt ut selv om DENNE kjoringen ikke
    # fikk tak i noe. Frysingen krever at hentingen lyktes i samme kjoring.
    import sesong as _s
    d.update({"hentet": naa.isoformat(timespec="seconds"),
              "hentet_av": _s.kjoring_id(), "rader": rader})
    d.pop("siste_feil", None)
    _skriv_cache(liga, d)
    log(f"[nff {liga}] hentet {len(rader)} kamper")
    # 0 kamper er ikke "ok": fotball.no svarte, men vi fikk ingenting ut av
    # det. Det er samme feilmaate som en omlagt markup.
    hentelogg.logg(liga, "nff", "ok" if rader else "feil", kamper=len(rader),
                   melding="" if rader else "siden ga 0 kamper")
    return rader


if __name__ == "__main__":
    from ligaer import LIGAER
    cache = sys.argv[1] if len(sys.argv) > 1 else None
    for liga in LIGAER:
        rader = fetch_all(liga, cache_dir=cache, log=lambda s: print(s, file=sys.stderr))
        spilt = sum(1 for r in rader if r["hg"] is not None)
        runder = sorted({r["round"] for r in rader})
        print(f"{liga:12} kamper: {len(rader)} ({spilt} spilt)  "
              f"runder: {runder[0]}-{runder[-1]} ({len(runder)} stk)")
