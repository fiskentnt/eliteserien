#!/usr/bin/env python3
"""Daglig revisjon av TERMINLISTEN mot NTFs kalenderfeed. Begge ligaer.

HVORFOR DENNE FINNES: de 22 feilene vi rettet 25. september var feil avspark
og en feil dato -- altsaa terminlistedata, ikke resultater. De ble funnet ved
aa sammenligne kilder. Terminlisten bygges av den skrapte /terminliste-siden;
kalenderfeeden (/terminliste/subscribe) er en annen kanal fra NTF, laget for
automatisk bruk, og har runde, dato og avspark for alle kommende kamper.

fotball.no er IKKE med (regelen fra 1.10.2026, se nff_source.py): den hentes
bare automatisk som reserve naar ligasiden ikke svarer. Unntaket er
revider_sesong(), reparasjon av en frossen sesong for haand.

En avvikende RUNDE eller DATO er kritisk: da viser siden kampen paa feil
plass, eller vekter den feil i modellen. Et avvikende AVSPARK er en advarsel
-- tv-tider justeres. En kamp i feeden som vi ikke har, er kritisk; en
uspilt kamp hos oss som feeden ikke har, er en advarsel (feeden kan ha tatt
ut en kamp som spilles naa).

Stempelet: staar dagens revisjon med kritiske avvik, forblir det roedt til
en NY revisjon bekrefter at avviket er borte. Uten det ville neste kjoring
skrevet ok=True og gjort stempelet groent mens feilen sto.

Tabellen kontrolleres av scripts/tabellkontroll.py, i datakjoringen.

Bruk:  python3 scripts/daglig_revisjon.py <liga>
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hentelogg
import nff_source
import ntf_source
import tabellkontroll
from ligaer import LIGAER, oppsett

ROT = Path(__file__).resolve().parent.parent
OSLO = ZoneInfo("Europe/Oslo")


def data_katalog(liga, sesong=None):
    """Hvor dataene for en sesong ligger.

    Den AKTIVE sesongen ligger i <liga>/data. En avsluttet, frossen sesong
    ligger i <liga>/<sesong>/data. En reparasjon av 2026 etter at 2027 er
    aktiv maa lese og skrive i 2026-mappen -- ellers overskriver den den
    aktive sesongens revisjon, bekreftede avvik og stempel.
    """
    if sesong:
        return ROT / liga / str(sesong) / "data"
    return ROT / oppsett(liga)["data"]


def vaare_kamper(liga, sesong=None):
    """(hjemme, borte) -> {round, date, time, hg, ag} fra det siden viser."""
    d = data_katalog(liga, sesong)
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


def revider(vaare, nff_rader, ferskt=True, bekreftet=None, sesong=None):
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

    # BARE SAMME SESONG. I desember viser fotball.no 2027 mens vi fortsatt
    # har 2026. Sammenlignet vi paa tvers, ville hver kamp sett ut som et
    # avvik, revisjonen aldri blitt ren, frysingen aldri skjedd -- og med
    # frysingen som vilkaar for byttet ville sesongskiftet staatt fast for
    # godt. En kamp fra en annen sesong er en advarsel, ikke et avvik.
    if sesong:
        annen = [r for r in nff_rader if not (r.get("date") or "").startswith(str(sesong))]
        if annen:
            advarsler.append(f"{len(annen)} kamper hos fotball.no er fra en "
                             f"annen sesong enn {sesong} -- ikke sammenlignet")
        nff_rader = [r for r in nff_rader
                     if (r.get("date") or "").startswith(str(sesong))]

    nff = {(r["home"], r["away"]): r for r in nff_rader}
    if not nff:
        return [], advarsler + ["fotball.no ga ingen kamper i sesongen -- "
                                "ingen kontroll denne gangen"]

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


def revider_kalender(vaare, kalender, sesong=None, naa=None, log=lambda s: None):
    """(feil, advarsler) for terminlisten mot kalenderfeeden.

    vaare er ALLE kampene vaare ({(hjemme, borte): rad}), spilte og uspilte:
    en kamp som nettopp er spilt, kan fortsatt staa i feeden, og skal da
    sammenlignes, ikke se ut som en kamp vi mangler.

    AVSPARK I UTC (3.10.2026): naar NTF endrer en oppfoering ved kampslutt,
    lagres klokkeslettet i UTC, men feeden oppgir fortsatt TZID=Europe/Oslo
    (Haugesund-Stabæk 16:00 sto som 14:00, LAST-MODIFIED 15:52Z; det samme
    paa resultatsiden, se ntf_source._utc_til_oslo). For en kamp som har
    STARTET (vaart avspark <= naa) leses feedens tid da som UTC naar den
    nettopp er vaart avspark i UTC, og det er ikke et avvik. For en kamp som
    ikke har startet, gjoeres det aldri: der kan det vaere en ekte flytting to
    timer fram, og den skal sees. Advarselen sier da at det kan vaere feilen."""
    naa = naa or datetime.now(timezone.utc)
    feil, advarsler = [], []
    if sesong:
        annen = [r for r in kalender if not (r.get("date") or "").startswith(str(sesong))]
        if annen:
            advarsler.append(f"{len(annen)} kamper i kalenderfeeden er fra en annen sesong "
                             f"enn {sesong} -- ikke sammenlignet")
        kalender = [r for r in kalender if (r.get("date") or "").startswith(str(sesong))]
    kal = {(r["home"], r["away"]): r for r in kalender}
    if not kal:
        return [], advarsler + ["kalenderfeeden ga ingen kamper i sesongen -- ingen kontroll denne gangen"]
    for key, k in sorted(kal.items()):
        hvem = f"{key[0]}-{key[1]}"
        v = vaare.get(key)
        if not v:
            feil.append(f"{hvem}: står i kalenderfeeden, men ikke hos oss")
            continue
        if k["round"] != v.get("round"):
            feil.append(f"{hvem}: runde {v.get('round')} hos oss, {k['round']} i kalenderfeeden")
        i_utc = _er_vaart_avspark_i_utc(k, v)
        if i_utc and _har_startet(v, naa):
            log(f"MERK: {hvem} står med avspark {k['date']} {k['time']} i kalenderfeeden, som er "
                f"avsparket vårt {v['date']} {v['time']} i UTC (kampen har startet) -- regnet om til norsk tid")
            continue
        if i_utc:
            advarsler.append(f"{hvem}: avspark {v['date']} {v['time']} hos oss, {k['date']} {k['time']} i "
                             f"kalenderfeeden (det er vårt avspark i UTC -- en flytting, eller tiden lagret i UTC)")
            continue
        if k["date"] != v.get("date"):
            feil.append(f"{hvem}: dato {v.get('date')} hos oss, {k['date']} i kalenderfeeden")
        elif k.get("time") and v.get("time") and k["time"] != v["time"]:
            advarsler.append(f"{hvem}: avspark {v['time']} hos oss, {k['time']} i kalenderfeeden")
    for key, v in sorted(vaare.items()):
        if v.get("hg") is None and key not in kal and (not sesong or (v.get("date") or "").startswith(str(sesong))):
            advarsler.append(f"{key[0]}-{key[1]}: uspilt hos oss, men står ikke i kalenderfeeden")
    return feil, advarsler


def revider_kontroller(vaare, kontroller, naa):
    """(feil, advarsler) for de kommende kampene våre mot kontrollkildene
    (3.10.2026): Eliteserien ESPN og Highlightly, OBOS Highlightly og
    OddsPapi. kontroller: {navn: {(hjemme, borte): {date, time, round?}}}.

    Bare kamper som ikke har startet (et avspark i UTC eller en kamp som er i
    gang er ikke en flytting). Én kontroll med annen dato eller tid er en
    advarsel. To kontroller som er enige med hverandre om en annen DATO enn
    vår, er et avvik: to uavhengige leverandører sier det samme."""
    feil, advarsler = [], []
    for key, v in sorted(vaare.items()):
        if v.get("hg") is not None or _har_startet(v, naa):
            continue
        hvem = f"{key[0]}-{key[1]}"
        datoer = {}
        for navn, rader in kontroller.items():
            k = rader.get(key)
            if not k:
                continue
            if k.get("date") != v.get("date"):
                datoer.setdefault(k.get("date"), []).append(navn)
                advarsler.append(f"{hvem}: dato {v.get('date')} hos oss, {k.get('date')} hos {navn}")
            elif k.get("time") and v.get("time") and k["time"] != v["time"]:
                advarsler.append(f"{hvem}: avspark {v['time']} hos oss, {k['time']} hos {navn}")
            if k.get("round") and v.get("round") and k["round"] != v["round"]:
                advarsler.append(f"{hvem}: runde {v['round']} hos oss, {k['round']} hos {navn}")
        for dato, hvem_kilder in datoer.items():
            if len(hvem_kilder) >= 2:
                feil.append(f"{hvem}: dato {v.get('date')} hos oss, {dato} hos både {' og '.join(hvem_kilder)}")
    return feil, advarsler


def hent_kontroller(liga, vaare, naa, log=print):
    """Kontrollkildene for terminlisten som {navn: {(hjemme, borte): rad}}.
    En kilde som ikke kan hentes, gir en advarsel, aldri et avvik."""
    aar = naa.astimezone(OSLO).year
    ut, advarsler = {}, []
    kjente = {k: v.get("date") for k, v in vaare.items()}
    hentere = []
    if liga == "eliteserien":
        def _espn():
            import espn_source
            return espn_source.fetch_season(aar, log=lambda _s: None)
        hentere.append(("ESPN", _espn))

    def _hl():
        import highlightly_source
        return highlightly_source.hent_sesong(liga, aar, kjente)
    hentere.append(("Highlightly", _hl))
    if liga == "obos":
        def _op():
            import obos_results
            fx = json.loads(obos_results.FIXTURES_CACHE.read_text(encoding="utf-8")).get("fixtures", [])
            navn, lag = obos_results.load_names(), {obos_results.norm(t): t for k in vaare for t in k}
            rader = []
            for f in fx:
                h = lag.get(obos_results.norm(navn.get(f.get("participant1Name"), f.get("participant1Name"))))
                b = lag.get(obos_results.norm(navn.get(f.get("participant2Name"), f.get("participant2Name"))))
                t = f.get("startTime")
                if h and b and t:
                    d = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(OSLO)
                    rader.append({"home": h, "away": b, "date": d.strftime("%Y-%m-%d"), "time": d.strftime("%H:%M")})
            return rader
        hentere.append(("OddsPapi", _op))
    for navn, hent in hentere:
        try:
            ut[navn] = {(r["home"], r["away"]): r for r in hent()}
        except Exception as e:
            advarsler.append(f"kontrollen mot {navn} kunne ikke kjøres ({type(e).__name__}: {e})")
    return ut, advarsler


def _er_vaart_avspark_i_utc(k, v):
    """True naar feedens (dato, tid) er vaart avspark (norsk tid) skrevet i UTC."""
    if not (k.get("time") and v.get("time") and v.get("date")):
        return False
    if (k["date"], k["time"]) == (v["date"], v["time"]):
        return False
    oslo = datetime.fromisoformat(f"{k['date']}T{k['time']}:00").replace(tzinfo=timezone.utc).astimezone(OSLO)
    return (oslo.strftime("%Y-%m-%d"), oslo.strftime("%H:%M")) == (v["date"], v["time"])


def _har_startet(v, naa):
    """True naar vaart avspark (norsk tid) er passert."""
    try:
        avspark = datetime.fromisoformat(f"{v['date']}T{v.get('time') or '00:00'}:00").replace(tzinfo=OSLO)
    except Exception:
        return False
    return avspark <= naa


def _vaar_verdi(vaare, lagpar):
    """Vaar runde, dato, avspark og resultat for et lagpar -- det som skal
    sammenlignes for aa avgjore om vi har rettet noe siden forrige revisjon."""
    for (h, b), v in vaare.items():
        if f"{h}-{b}" == lagpar:
            return [v.get("round"), v.get("date"), v.get("time"),
                    v.get("hg"), v.get("ag")]
    return None


def les_bekreftet(liga, naa=None, sesong=None):
    """Avvik en FERSK revisjon har bekreftet, med vaar verdi den gangen.

    IKKE begrenset til i dag. Et bekreftet avvik gjelder til en fersk
    revisjon viser at det er borte, eller til vaar verdi har endret seg.
    Knyttet vi det til dagens dato, ville forste kjoring etter midnatt
    nedgradert avviket, satt siste_ok og gjort stempelet gronnt -- mens
    feilen fortsatt sto."""
    sti = data_katalog(liga, sesong) / "audit_fixtures.json"
    if not sti.exists():
        return {}
    try:
        return json.loads(sti.read_text(encoding="utf-8")).get("bekreftet") or {}
    except Exception:
        return {}


def dagens_avvik(liga, naa, sesong=None):
    """Antall kritiske avvik i DAGENS terminlisterevisjon, ellers 0.

    Leses av dem som ogsaa skriver status.json -- write_status() for
    Eliteserien og obos_build_data.py for OBOS -- slik at de ikke kan
    overskrive et rodt stempel med ok=True. Uten dette ville neste kjoring
    gjort stempelet gronnt mens avviket sto."""
    sti = data_katalog(liga, sesong) / "audit_fixtures.json"
    if not sti.exists():
        return 0
    try:
        d = json.loads(sti.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if d.get("checked_date") != naa.astimezone(OSLO).strftime("%Y-%m-%d"):
        return 0
    return int(d.get("errors") or 0)


def skriv_stempel(liga, feil, naa, sesong=None, kilde="kalenderfeeden"):
    """Setter ok=False saa lenge dagens revisjon staar med kritiske avvik.

    Samme regel som Eliteserien: gronnt kommer tilbake bare naar en NY
    revisjon bekrefter at avviket er borte."""
    sti = data_katalog(liga, sesong) / "status.json"
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
        hva = "tabellen" if all(f.startswith("Tabell, ") for f in feil) else "terminlisten"
        d["error"] = (f"{len(feil)} kritisk(e) avvik mellom {hva} og "
                      f"{kilde}: {feil[0]}")[:300]
    else:
        d["ok"] = True
        d.pop("revisjon_avvik", None)
        d.pop("error", None)
    sti.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def revider_sesong(liga, sesong, naa=None, log=print):
    """Reviderer EN BESTEMT sesong i sin egen mappe, mot sin egen
    turneringsadresse hos fotball.no.

    Brukes til reparasjon etter at sesongen er byttet: fotball.no viser da
    den AKTIVE sesongen, saa vi maa hente den avsluttede med turnerings-id-en
    som ligger i sesongens egen audit_fixtures.json.

    Reservens 20-timersgrense (i nff_source) gjelder ikke her: sesongadressen
    hentes DIREKTE, fordi dette er en manuell reparasjon som ikke skal
    blokkeres av at reserven hentet tidligere samme dag. Det er en ekstra
    forespørsel, utlost av et menneske, og derfor unntaket i regelen for
    fotball.no (se nff_source.py).

    Tabellen paa samme side sammenlignes med tabellkontrollens regler
    (tabellkontroll.py): et nytt trekk legges inn i sesongens
    justeringer.json, og audit_tabell.json skrives, som frysingen krever.
    """
    naa = naa or datetime.now(timezone.utc)
    kat = data_katalog(liga, sesong)
    tidligere = {}
    sti = kat / "audit_fixtures.json"
    if sti.exists():
        try:
            tidligere = json.loads(sti.read_text(encoding="utf-8"))
        except Exception:
            tidligere = {}
    turnering = tidligere.get("turnering") or oppsett(liga).get("nff_turnering", {}).get(str(sesong))
    if not turnering:
        log(f"Fant ingen turnerings-id for {liga} {sesong}. Uten den kan vi "
            f"ikke hente NETTOPP den sesongen fra fotball.no.")
        return 1

    url = nff_source.turnering_url(turnering)
    log(f"Henter {liga} {sesong} fra {url}")
    try:
        tekst = nff_source.hent(url)
        rader = nff_source.parse_side(tekst, liga, naa=naa,
                                      log=lambda m: log(f"  {m}"))
    except Exception as e:
        log(f"ADVARSEL: klarte ikke hente {sesong} ({type(e).__name__}: {e}).")
        return 1
    try:
        nff_tab = nff_source.parse_tabell(tekst, liga)
    except nff_source.NffDataError as e:
        nff_tab = {"feil": str(e)}

    vaare = vaare_kamper(liga, sesong)
    feil, advarsler = revider(vaare, rader, ferskt=True,
                              bekreftet=les_bekreftet(liga, naa, sesong),
                              sesong=str(sesong))
    # Tabellen fra samme fotball.no-side, med tabellkontrollens regler, i
    # sesongens egen mappe: en frossen sesong som aapnes fordi NFF har vedtatt
    # noe etterpaa, faar trekket lagt inn i sin egen justeringer.json, og
    # frysingen paa nytt krever at alle lag stemmer (audit_tabell.json).
    import sesong as _s
    spilte = json.loads((kat / "matches.json").read_text(encoding="utf-8"))
    tk = tabellkontroll.kontroller(liga, sesong, spilte, nff_tab, naa=naa, data_dir=kat,
                                   kilde_url=url, kjoring=_s.kjoring_id(), log=lambda m: log(f"  {m}"),
                                   lag={m["home"] for m in spilte} | {m["away"] for m in spilte})
    feil = feil + tk["avvik"]
    log(f"Revisjon av {liga} {sesong}: {len(vaare)} kamper mot {len(rader)} "
        f"hos fotball.no")
    for a in advarsler:
        log(f"  ADVARSEL: {a}")
    for f in feil:
        log(f"  AVVIK: {f}")

    sti.write_text(json.dumps({
        "checked_date": naa.astimezone(OSLO).strftime("%Y-%m-%d"),
        "checked_at": naa.isoformat(timespec="seconds"),
        "ferskt": True, "kjoring": _s.kjoring_id(), "turnering": turnering, "kilde": "fotball.no",
        "errors": len(feil), "warnings": len(advarsler),
        "avvik": feil[:20], "advarsler": advarsler[:20],
        "bekreftet": {_nokkel(f): _vaar_verdi(vaare, _nokkel(f)) for f in feil if not f.startswith("Tabell, ")},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    skriv_stempel(liga, feil, naa, sesong, kilde="fotball.no")
    return 1 if feil else 0


def main(argv, naa=None):
    if not argv or argv[0] not in LIGAER:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    liga = argv[0]
    naa = naa or datetime.now(timezone.utc)

    # Ikke revider en frossen sesong. Kildene viser neste sesong rundt
    # aarsskiftet, og da ville hver kamp sett ut som et avvik.
    import sesong as _ses
    _a = _ses.aktiv_sesong(ROT, liga, log=lambda _s: None)
    if _a and _ses.er_frosset(ROT, liga, _a):
        print(f"Sesongen {_a} er frosset -- reviderer ikke. "
              f"En frossen sesong er uforanderlig.")
        return 0

    vaare = vaare_kamper(liga)
    sti = ROT / oppsett(liga)["data"] / "audit_fixtures.json"
    try:
        kalender = ntf_source.parse_kalender(ntf_source.hent_kalender(liga), liga)
        hentelogg.logg(liga, "ntf-kalender", "ok", kamper=len(kalender))
    except Exception as e:
        # En kontroll som ikke kunne kjores, er ikke et avvik i dataene: en
        # advarsel her, og henteloggen gjor kjoringen rod hvis det skjer
        # tre ganger paa rad. Stempelet roeres ikke.
        if not isinstance(e, ntf_source.SvarerIkke):
            hentelogg.logg(liga, "ntf-kalender", "feil", melding=f"{type(e).__name__}: {e}"[:200])
        print(f"Daglig terminlisterevisjon, {oppsett(liga)['visningsnavn']}: kalenderfeeden kunne ikke "
              f"brukes ({type(e).__name__}: {e}) -- ingen kontroll denne gangen.")
        return 0
    feil, advarsler = revider_kalender(vaare, kalender, sesong=_a, naa=naa,
                                       log=lambda l: print(f"  {l}"))
    # Kontrollen mot de uavhengige kildene (3.10.2026): Eliteserien ESPN og
    # Highlightly, OBOS Highlightly og OddsPapi.
    _kontroller, _ka = hent_kontroller(liga, vaare, naa)
    _kf, _ka2 = revider_kontroller(vaare, _kontroller, naa)
    feil, advarsler = feil + _kf, advarsler + _ka + _ka2
    print(f"  kontrollert mot {', '.join(_kontroller) or 'ingen'} ({len(_kf)} avvik, {len(_ka) + len(_ka2)} advarsel(er))")
    print(f"Daglig terminlisterevisjon, {oppsett(liga)['visningsnavn']}: "
          f"{len(vaare)} kamper hos oss mot {len(kalender)} i kalenderfeeden")
    for a in advarsler:
        print(f"  ADVARSEL: {a}")
    for f in feil:
        print(f"  AVVIK: {f}")

    sti.write_text(json.dumps({
        "checked_date": naa.astimezone(OSLO).strftime("%Y-%m-%d"),
        "checked_at": naa.isoformat(timespec="seconds"),
        "kilde": "kalenderfeeden",
        # Alltid hentet i denne kjoringen: feeden caches ikke.
        "ferskt": True,
        # Turnerings-id-en sesongen har hos fotball.no, til reparasjon av en
        # frossen sesong for haand. Leses fra cachen, hentes ikke.
        "turnering": (nff_source.les_cache(liga).get("turnering")
                      or oppsett(liga).get("nff_turnering", {}).get(str(_a))),
        "kjoring": _ses.kjoring_id(),
        "errors": len(feil), "warnings": len(advarsler),
        "avvik": feil[:20], "advarsler": advarsler[:20], "bekreftet": {},
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
