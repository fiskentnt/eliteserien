#!/usr/bin/env python3
"""Daglig revisjon av TERMINLISTEN mot fotball.no. Begge ligaer.

HVORFOR DENNE FINNES: de 22 feilene vi rettet 25. september var feil avspark
og en feil dato -- altsaa terminlistedata, ikke resultater. De ble funnet ved
aa sammenligne kilder. Naar fotball.no ikke lenger er med i hver kjoring, er
dette det ENESTE stedet den sammenligningen skjer, og for OBOS er det den
eneste uavhengige kontrollen paa runde, dato og avspark i det hele tatt.

Eliteserien har i tillegg en resultatrevisjon inne i update_data.py. Den
roerer vi ikke; denne kontrollerer terminlisten.

En avvikende RUNDE eller DATO er kritisk: da viser siden kampen paa feil
plass, eller vekter den feil i modellen. Et avvikende AVSPARK er en advarsel
-- tv-tider justeres, og fotball.no henger av og til noen timer etter.

Stempelet foelger samme regel som Eliteserien: staar dagens revisjon med
kritiske avvik, forblir det roedt til en NY revisjon bekrefter at avviket er
borte. Uten det ville neste kjoring skrevet ok=True og gjort stempelet groent
mens feilen sto.

Bruk:  python3 scripts/daglig_revisjon.py <liga>
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nff_source
from ligaer import LIGAER, oppsett

ROT = Path(__file__).resolve().parent.parent
OSLO = ZoneInfo("Europe/Oslo")


def vaare_kamper(liga):
    """(hjemme, borte) -> {round, date, time, hg, ag} fra det siden viser."""
    d = ROT / oppsett(liga)["data"]
    ut = {}
    for r in json.loads((d / "matches.json").read_text(encoding="utf-8")):
        ut[(r["home"], r["away"])] = r
    for runde in json.loads((d / "fixtures.json").read_text(encoding="utf-8")):
        for m in runde["matches"]:
            ut[(m["home"], m["away"])] = {**m, "round": runde["round"]}
    return ut


# Hvor ferske fotball.no-dataene maa vaere for et avvik kan kalles kritisk.
FERSK_MIN = 10


def _nokkel(tekst):
    """Lagpar-delen av en avviksmelding, til gjenkjenning paa tvers av dager."""
    return tekst.split(":", 1)[0]


def revider(vaare, nff_rader, ferskt=True, bekreftet=None):
    """(feil, advarsler). feil er kritisk og gjoer stempelet roedt.

    ferskt=False naar fotball.no-svaret kommer fra cachen og altsaa kan vaere
    inntil 20 timer gammelt. Da nedgraderes ALT til advarsler: en kamp som
    ble flyttet i gaar kveld staar med ny dato hos ligasiden og gammel dato i
    cachen, og det er ikke en feil -- det er bare to ulike tidspunkter. Et
    rodt stempel paa det grunnlaget ville vaert falskt alarm hver gang noe
    flyttes.

    bekreftet er avvik en FERSK revisjon alt har funnet, med vaar verdi paa
    det tidspunktet: {lagpar: vaar_verdi}. Et slikt avvik forblir kritisk
    ogsaa mot gammel cache SAA LENGE VAAR VERDI ER UENDRET. Uten det ville et
    bekreftet avvik blitt gronnt en time senere, bare fordi cachen rakk aa bli
    ti minutter gammel -- mens feilen fortsatt sto."""
    feil, advarsler = [], []
    bekreftet = bekreftet or {}
    nff = {(r["home"], r["away"]): r for r in nff_rader}
    if not nff:
        return [], ["fotball.no ga ingen kamper -- ingen kontroll denne gangen"]

    for key, v in sorted(vaare.items()):
        k = nff.get(key)
        hvem = f"{key[0]}-{key[1]}"
        if not k:
            advarsler.append(f"{hvem}: finnes ikke hos fotball.no")
            continue
        if k.get("round") != v.get("round"):
            feil.append(f"{hvem}: runde {v.get('round')} hos oss, "
                        f"{k.get('round')} hos fotball.no")
        if k.get("date") != v.get("date"):
            feil.append(f"{hvem}: dato {v.get('date')} hos oss, "
                        f"{k.get('date')} hos fotball.no")
        elif k.get("time") and v.get("time") and k["time"] != v["time"]:
            advarsler.append(f"{hvem}: avspark {v['time']} hos oss, "
                             f"{k['time']} hos fotball.no")
        if (v.get("hg") is not None and k.get("hg") is not None
                and (v["hg"], v["ag"]) != (k["hg"], k["ag"])):
            feil.append(f"{hvem}: resultat {v['hg']}-{v['ag']} hos oss, "
                        f"{k['hg']}-{k['ag']} hos fotball.no")

    for key in set(nff) - set(vaare):
        feil.append(f"{key[0]}-{key[1]}: finnes hos fotball.no, men ikke hos oss")

    if not ferskt and feil:
        beholdt, nedgradert = [], []
        for f in feil:
            k = _nokkel(f)
            if k in bekreftet and bekreftet[k] == _vaar_verdi(vaare, k):
                # Bekreftet av en fersk revisjon, og vi har ikke rettet noe
                # siden. Da staar det.
                beholdt.append(f + " [bekreftet av fersk revisjon, uendret hos oss]")
            else:
                nedgradert.append(f"(fotball.no-dataene er fra cachen) {f}")
        feil, advarsler = beholdt, nedgradert + advarsler
    return feil, advarsler


def _vaar_verdi(vaare, lagpar):
    """Vaar runde, dato, avspark og resultat for et lagpar -- det som skal
    sammenlignes for aa avgjore om vi har rettet noe siden forrige revisjon."""
    for (h, b), v in vaare.items():
        if f"{h}-{b}" == lagpar:
            return [v.get("round"), v.get("date"), v.get("time"),
                    v.get("hg"), v.get("ag")]
    return None


def les_bekreftet(liga, naa=None):
    """Avvik en FERSK revisjon har bekreftet, med vaar verdi den gangen.

    IKKE begrenset til i dag. Et bekreftet avvik gjelder til en fersk
    revisjon viser at det er borte, eller til vaar verdi har endret seg.
    Knyttet vi det til dagens dato, ville forste kjoring etter midnatt
    nedgradert avviket, satt siste_ok og gjort stempelet gronnt -- mens
    feilen fortsatt sto."""
    sti = ROT / oppsett(liga)["data"] / "audit_fixtures.json"
    if not sti.exists():
        return {}
    try:
        return json.loads(sti.read_text(encoding="utf-8")).get("bekreftet") or {}
    except Exception:
        return {}


def dagens_avvik(liga, naa):
    """Antall kritiske avvik i DAGENS terminlisterevisjon, ellers 0.

    Leses av dem som ogsaa skriver status.json -- write_status() for
    Eliteserien og obos_build_data.py for OBOS -- slik at de ikke kan
    overskrive et rodt stempel med ok=True. Uten dette ville neste kjoring
    gjort stempelet gronnt mens avviket sto."""
    sti = ROT / oppsett(liga)["data"] / "audit_fixtures.json"
    if not sti.exists():
        return 0
    try:
        d = json.loads(sti.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if d.get("checked_date") != naa.astimezone(OSLO).strftime("%Y-%m-%d"):
        return 0
    return int(d.get("errors") or 0)


def skriv_stempel(liga, feil, naa):
    """Setter ok=False saa lenge dagens revisjon staar med kritiske avvik.

    Samme regel som Eliteserien: gronnt kommer tilbake bare naar en NY
    revisjon bekrefter at avviket er borte."""
    sti = ROT / oppsett(liga)["data"] / "status.json"
    d = {}
    if sti.exists():
        try:
            d = json.loads(sti.read_text(encoding="utf-8"))
        except Exception:
            d = {}
    d["revidert_at"] = naa.isoformat(timespec="seconds")
    if feil:
        d["ok"] = False
        d["revisjon_avvik"] = len(feil)
        d["error"] = (f"{len(feil)} kritisk(e) avvik mellom terminlisten og "
                      f"fotball.no: {feil[0]}")[:300]
    else:
        d["ok"] = True
        d.pop("revisjon_avvik", None)
        d.pop("error", None)
    sti.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv):
    if not argv or argv[0] not in LIGAER:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    liga = argv[0]
    naa = datetime.now(timezone.utc)

    # fetch_all haandterer selv at fotball.no hentes hoeyst en gang i dognet.
    # Er forsoket sperret, kommer det lagrede svaret -- og det er riktig: da
    # reviderer vi mot det nyeste vi lovlig har.
    nff_rader = nff_source.fetch_all(liga, log=lambda s: print(f"  {s}"))
    hentet = nff_source.sist_hentet(liga)
    ferskt = bool(hentet and (naa - hentet).total_seconds() / 60 < FERSK_MIN)
    vaare = vaare_kamper(liga)
    bekreftet_for = les_bekreftet(liga, naa)
    feil, advarsler = revider(vaare, nff_rader, ferskt=ferskt,
                              bekreftet=bekreftet_for)

    alder = f"{(naa - hentet).total_seconds() / 3600:.0f} t gammel" if hentet else "ukjent alder"
    print(f"Daglig terminlisterevisjon, {oppsett(liga)['visningsnavn']}: "
          f"{len(vaare)} kamper mot {len(nff_rader)} hos fotball.no "
          f"({'hentet nå' if ferskt else alder + ' -- avvik blir advarsler'})")
    for a in advarsler:
        print(f"  ADVARSEL: {a}")
    for f in feil:
        print(f"  AVVIK: {f}")

    sti = ROT / oppsett(liga)["data"] / "audit_fixtures.json"
    sti.write_text(json.dumps({
        "checked_date": naa.astimezone(OSLO).strftime("%Y-%m-%d"),
        "checked_at": naa.isoformat(timespec="seconds"),
        "errors": len(feil), "warnings": len(advarsler),
        "avvik": feil[:20], "advarsler": advarsler[:20],
        # Vaar verdi da avviket ble bekreftet. En senere revisjon mot gammel
        # cache holder avviket kritisk saa lenge denne er uendret.
        "bekreftet": ({_nokkel(f): _vaar_verdi(vaare, _nokkel(f)) for f in feil}
                      if ferskt else bekreftet_for),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    skriv_stempel(liga, feil, naa)

    if feil:
        print(f"\nFEILER KJØRINGEN: {len(feil)} kritisk(e) avvik. Stempelet er rødt "
              f"til en ny revisjon bekrefter at de er borte.", file=sys.stderr)
        return 1
    print(f"  ingen kritiske avvik ({len(advarsler)} advarsel(er)).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
