#!/usr/bin/env python3
"""Flyttinger som venter på bekreftelse, og avgjørelser for hånd (13.10.2026).

Ingen enkeltkilde flytter en uspilt kamp (reconcile_ny.bekreft_datoer): viser
ligasiden en ny dato eller tid, flyttes kampen bare når en uavhengig kilde
viser det samme. Eliteserien: ESPN (kalenderfeeden når ESPN ikke svarer).
OBOS: Highlightly-listen fra den daglige hentingen, lagret i
obos/data/kontroll_highlightly.json av daglig_revisjon.py, så byggingen ikke
gjør egne kall. Uten en liste yngre enn HL_MAKS_TIMER venter flyttingen.

Tre filer i <liga>/data:

  flytting_venter.json       skrives av datakjøringen: flyttingene den holdt
                             tilbake, med når hver først ble sett. Den daglige
                             revisjonen leser den: avviket mot kalenderfeeden
                             for en slik kamp er en ADVARSEL, ikke kritisk.
  flytting_overstyring.json  skrives FOR HÅND. Én linje per kamp:
                               {"hjemme": "Rosenborg", "borte": "Start",
                                "valg": "godta", "dato": "2026-11-18", "tid": "18:00"}
                             "godta": flyttingen gjennomføres. "avvis": vi
                             beholder datoen vi har, og det varsles ikke mer.
                             Linjen gjelder bare så lenge ligasiden viser
                             nøyaktig den datoen og tiden.
  kontroll_highlightly.json  (bare OBOS) Highlightly-listen fra den daglige
                             hentingen.

RØDT (revider_flyttinger, kjøres i den daglige revisjonen): en flytting som
har stått ubekreftet i VENT_DOGN døgn, eller der det er under FOR_AVSPARK_TIMER
timer til den tidligste av de to datoene. Da må den avgjøres for hånd i
overstyringsfilen; datafilene redigeres aldri.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")
VENTER = "flytting_venter.json"
OVERSTYRING = "flytting_overstyring.json"
KONTROLLISTE = "kontroll_highlightly.json"

VENT_DOGN = 3
FOR_AVSPARK_TIMER = 48
HL_MAKS_TIMER = 48

DATO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TID_RE = re.compile(r"^\d{2}:\d{2}$")


def _vis(dato, tid=None):
    return (f"{int(dato[8:10])}.{int(dato[5:7])}." if dato and len(dato) == 10 else str(dato)) + (f" {tid}" if tid else "")


def _avspark(dato, tid):
    return datetime.fromisoformat(f"{dato}T{tid or '00:00'}:00").replace(tzinfo=OSLO)


def linje(hjemme, borte, valg, dato, tid):
    """Linjen som limes inn i overstyringsfilen."""
    return json.dumps({"hjemme": hjemme, "borte": borte, "valg": valg, "dato": dato, "tid": tid}, ensure_ascii=False)


# ---------------------------------------------------------------- for hånd

def les_overstyringer(data_dir, lagpar=None, log=lambda s: None):
    """{(hjemme, borte): {"valg", "dato", "tid"}} fra flytting_overstyring.json.

    En linje som ikke kan brukes -- ukjent lagpar, annet valg enn godta/avvis,
    dato eller tid i feil form, to linjer for samme kamp -- hoppes over med
    ADVARSEL (og gul merknad i Actions). Kan filen ikke leses, brukes ingen
    linjer, med ADVARSEL. Mangler filen, er det ingen overstyringer. lagpar:
    de gyldige lagparene (terminlisten), til kontroll av navnene."""
    sti = Path(data_dir) / OVERSTYRING
    if not sti.exists():
        return {}

    def advar(tekst):
        log(f"ADVARSEL: {sti.name}: {tekst}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=Overstyringsfilen::{sti.name}: {tekst}")
    try:
        rader = json.loads(sti.read_text(encoding="utf-8")).get("overstyringer") or []
        if not isinstance(rader, list):
            raise ValueError("«overstyringer» er ikke en liste")
    except Exception as e:
        advar(f"kan ikke leses ({type(e).__name__}: {e}) -- ingen overstyringer brukes")
        return {}
    ut, forkastet = {}, set()
    for r in rader:
        if not isinstance(r, dict):
            advar(f"linjen {r!r} er ikke på formen {{hjemme, borte, valg, dato, tid}} -- hoppes over")
            continue
        k = (r.get("hjemme"), r.get("borte"))
        hvem = f"{k[0]}-{k[1]}"
        if lagpar is not None and k not in lagpar:
            advar(f"{hvem} er ikke en kamp i terminlisten (sjekk lagnavnene) -- hoppes over")
        elif r.get("valg") not in ("godta", "avvis"):
            advar(f"{hvem}: valg må være \"godta\" eller \"avvis\", ikke {r.get('valg')!r} -- hoppes over")
        elif not (isinstance(r.get("dato"), str) and DATO_RE.match(r["dato"])
                  and isinstance(r.get("tid"), str) and TID_RE.match(r["tid"])):
            advar(f"{hvem}: dato må være ÅÅÅÅ-MM-DD og tid TT:MM, ikke {r.get('dato')!r} og {r.get('tid')!r} -- hoppes over")
        elif k in ut or k in forkastet:
            advar(f"{hvem} står flere ganger -- ingen av linjene brukes")
            ut.pop(k, None)
            forkastet.add(k)
        else:
            ut[k] = {"valg": r["valg"], "dato": r["dato"], "tid": r["tid"]}
    return ut


# --------------------------------------------------- flyttingene som venter

def les_venter(data_dir):
    """Listen i flytting_venter.json, tom uten fil."""
    try:
        return json.loads((Path(data_dir) / VENTER).read_text(encoding="utf-8")).get("venter") or []
    except Exception:
        return []


def skriv_venter(data_dir, utfall, naa):
    """Skriver flyttingene datakjøringen holdt tilbake (utfall fra
    reconcile_ny.bekreft_datoer): "beholdt" venter på bekreftelse, "avvist" er
    avgjort for hånd. forst_sett beholdes så lenge ligasiden viser SAMME dato
    og tid for kampen; viser den noe nytt, er det en ny påstand og en ny
    klokke. Filen skrives bare når innholdet er endret. Returnerer listen."""
    sti = Path(data_dir) / VENTER
    gamle = {(v.get("kamp"), tuple(v.get("ligasiden") or [])): v for v in les_venter(data_dir)}
    ut = []
    for u in utfall or []:
        if u.get("utfall") not in ("beholdt", "avvist") or not u.get("har"):
            continue
        kamp = f"{u['nokkel'][0]}|{u['nokkel'][1]}"
        g = gamle.get((kamp, tuple(u["ny"])))
        ut.append({"kamp": kamp, "vaar": list(u["har"]), "ligasiden": list(u["ny"]),
                   "forst_sett": (g or {}).get("forst_sett") or naa.isoformat(timespec="seconds"),
                   "avvist": u["utfall"] == "avvist", "hva": u.get("hva") or ""})
    ut.sort(key=lambda v: v["kamp"])
    if ut != les_venter(data_dir) or not sti.exists():
        sti.write_text(json.dumps({"venter": ut}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return ut


def revider_flyttinger(venter, naa, data_navn="<liga>/data"):
    """(feil, advarsler) for flyttingene som venter på bekreftelse.

    ADVARSEL så lenge en flytting venter. KRITISK (rød kjøring, e-post) når
    den har stått ubekreftet i VENT_DOGN døgn, eller når det er under
    FOR_AVSPARK_TIMER timer til den tidligste av de to datoene: da viser siden
    kanskje feil avspark for en kamp som snart spilles, og den må avgjøres
    for hånd. En flytting som er avvist for hånd, gir verken advarsel eller
    feil."""
    feil, advarsler = [], []
    for v in venter or []:
        if v.get("avvist"):
            continue
        h, b = v["kamp"].split("|")
        vaar, lig = v["vaar"], v["ligasiden"]
        grunn = f"{h}-{b}: ligasiden viser {_vis(*lig)}, vi har {_vis(*vaar)}"
        ventet = naa - datetime.fromisoformat(v["forst_sett"])
        til_avspark = min(_avspark(*vaar), _avspark(*lig)) - naa
        # Har kampen startet etter avsparket VI har, gjelder ikke 48-timersregelen:
        # da er den i gang (ligasiden endrer oppføringen underveis) eller utsatt,
        # og en kamp uten resultat tre timer etter avspark gjør uansett
        # kjøringen rød (update_data.sjekk_manglende_resultat).
        startet = _avspark(*vaar) <= naa
        hvorfor = None
        if ventet >= timedelta(days=VENT_DOGN):
            hvorfor = f"ubekreftet i {ventet.days} døgn"
        elif not startet and til_avspark < timedelta(hours=FOR_AVSPARK_TIMER):
            hvorfor = f"ubekreftet, og under {FOR_AVSPARK_TIMER} timer til avspark"
        if hvorfor:
            feil.append(f"{grunn}, {hvorfor}. Godta eller avvis i {data_navn}/{OVERSTYRING}: "
                        f"{linje(h, b, 'godta', lig[0], lig[1])}")
        else:
            advarsler.append(f"{grunn} -- flyttingen venter på bekreftelse (siden "
                             f"{datetime.fromisoformat(v['forst_sett']).astimezone(OSLO):%d.%m. %H:%M})")
    return feil, advarsler


# ------------------------------------- Highlightly fra den daglige hentingen

def lagre_kontrolliste(data_dir, rader, naa):
    """Lagrer Highlightly-listen fra den daglige hentingen (daglig_revisjon).
    rader: {(hjemme, borte): {date, time, ...}}."""
    kamper = sorted(({"home": k[0], "away": k[1], "date": r.get("date"), "time": r.get("time")}
                     for k, r in rader.items()), key=lambda m: (m["date"] or "", m["time"] or "", m["home"]))
    (Path(data_dir) / KONTROLLISTE).write_text(json.dumps(
        {"kilde": "Highlightly", "hentet": naa.isoformat(timespec="seconds"), "kamper": kamper},
        ensure_ascii=False, indent=0) + "\n", encoding="utf-8")


def highlightly_lagret(data_dir, naa, maks_timer=HL_MAKS_TIMER):
    """{(hjemme, borte): (dato, tid)} fra den lagrede Highlightly-listen.
    Kaster ValueError når listen mangler, ikke kan leses eller er eldre enn
    maks_timer: da kan ingen flytting bekreftes, og den venter."""
    sti = Path(data_dir) / KONTROLLISTE
    try:
        d = json.loads(sti.read_text(encoding="utf-8"))
        hentet = datetime.fromisoformat(d["hentet"])
        kamper = d["kamper"]
    except Exception as e:
        raise ValueError(f"den lagrede Highlightly-listen mangler eller kan ikke leses ({type(e).__name__})")
    if hentet.tzinfo is None:
        hentet = hentet.replace(tzinfo=timezone.utc)
    alder = naa - hentet
    if alder > timedelta(hours=maks_timer):
        raise ValueError(f"den lagrede Highlightly-listen er {alder.total_seconds() / 3600:.0f} timer gammel "
                         f"(grensen er {maks_timer})")
    return {(m["home"], m["away"]): (m["date"], m.get("time")) for m in kamper}
