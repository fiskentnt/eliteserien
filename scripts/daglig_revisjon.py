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

TABELLEN sammenlignes ogsaa, lag for lag: kamper, vunnet, uavgjort, tap,
maal og poeng i tabellen vi regner (matches.json pluss poengjusteringene i
justeringer.json) mot den offisielle tabellen paa samme fotball.no-side,
og listen over justeringer mot fotball.no sin. Et avvik med likt antall
kamper er kritisk (Aasane sto med 20 poeng hos oss og 19 hos NFF fordi
trekket manglet). Ulikt antall kamper er en advarsel: da er kildene hentet
paa ulike tidspunkt.

Bruk:  python3 scripts/daglig_revisjon.py <liga>
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import justeringer as _just
import nff_source
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


def vaar_tabell(liga, sesong=None):
    """(tabell, justeringer) slik siden regner dem: {lag: {k, v, u, t, mf, mm,
    poeng, plass}} fra matches.json med justeringene for sesongen lagt til
    poengene, og justeringene som [{dato, lag, poeng, maal}]."""
    kat = data_katalog(liga, sesong)
    kamper = json.loads((kat / "matches.json").read_text(encoding="utf-8"))
    aar = str(sesong) if sesong else (max(m["date"] for m in kamper)[:4] if kamper else None)
    just = _just.les(kat.parent, aar) if aar else []
    t = {n: {"k": 0, "v": 0, "u": 0, "t": 0, "mf": 0, "mm": 0} for n in oppsett(liga)["lag"]}
    for m in kamper:
        if m.get("hg") is None or m.get("ag") is None:
            continue
        for lag, f, mot in ((m["home"], m["hg"], m["ag"]), (m["away"], m["ag"], m["hg"])):
            r = t.setdefault(lag, {"k": 0, "v": 0, "u": 0, "t": 0, "mf": 0, "mm": 0})
            r["k"] += 1; r["mf"] += f; r["mm"] += mot
            r["v" if f > mot else "t" if f < mot else "u"] += 1
    per_lag = _just.per_lag(just)
    for lag, r in t.items():
        r["poeng"] = 3 * r["v"] + r["u"] + per_lag.get(lag, 0)
    rekke = sorted(t, key=lambda n: (-t[n]["poeng"], -(t[n]["mf"] - t[n]["mm"]), -t[n]["mf"], n))
    for i, n in enumerate(rekke):
        t[n]["plass"] = i + 1
    return t, [{"dato": j["dato"], "lag": j["lag"], "poeng": j["poeng"], "maal": j.get("maal", 0)}
               for j in just]


TABELL_FELT = (("k", "kamper"), ("v", "vunnet"), ("u", "uavgjort"), ("t", "tap"),
               ("mf", "mål for"), ("mm", "mål mot"), ("poeng", "poeng"))


def _just_tekst(j):
    return f"{j['dato']} {j['lag']} {j['poeng']:+d} poeng" + (f", {j['maal']:+d} mål" if j.get("maal") else "")


def revider_tabell(vaar, nff_tabell, vaare_just, nff_just, ferskt=True, bekreftet=None,
                   nff_feil=None):
    """(feil, advarsler) for tabellen og justeringene. Samme regel for
    ferskhet som revider(): mot cachet fotball.no-data blir avvik advarsler,
    med mindre en fersk revisjon har bekreftet dem og vi ikke har rettet noe."""
    feil, advarsler = [], []
    bekreftet = bekreftet or {}
    if nff_tabell is None:
        return [], [f"Tabell: ikke sammenlignet ({nff_feil or 'fikk ingen tabell fra fotball.no'})"]
    nff = {r["lag"]: r for r in nff_tabell}
    for lag in sorted(set(vaar) | set(nff)):
        v, k = vaar.get(lag), nff.get(lag)
        if not v or not k:
            feil.append(f"Tabell, {lag}: står {'bare hos fotball.no' if k else 'bare hos oss'}")
            continue
        if v["k"] != k["k"]:
            advarsler.append(f"Tabell, {lag}: {v['k']} kamper hos oss, {k['k']} hos "
                             f"fotball.no -- hentet på ulike tidspunkt, ikke sammenlignet")
            continue
        ulikt = [f"{v[f]} {navn} hos oss, {k[f]} hos fotball.no" for f, navn in TABELL_FELT if v[f] != k[f]]
        if ulikt:
            feil.append(f"Tabell, {lag}: " + "; ".join(ulikt))
    if not feil and all(vaar[l]["k"] == nff[l]["k"] for l in nff if l in vaar):
        for lag in sorted(nff, key=lambda l: nff[l]["plass"]):
            if lag in vaar and vaar[lag]["plass"] != nff[lag]["plass"]:
                advarsler.append(f"Tabell, {lag}: plass {vaar[lag]['plass']} hos oss, "
                                 f"{nff[lag]['plass']} hos fotball.no (lik poengsum, ulik rangering)")
    if nff_just is not None:
        nokkel = lambda j: (j["dato"], j["lag"], j["poeng"], j.get("maal", 0))
        hos_oss = [nokkel(j) for j in vaare_just]
        hos_nff = [nokkel(j) for j in nff_just]
        for j in nff_just:
            if nokkel(j) not in hos_oss:
                feil.append(f"Justering, {j['lag']}: {_just_tekst(j)} hos fotball.no mangler i "
                            f"justeringer.json" + (" (måljusteringer støttes ikke på siden)" if j.get("maal") else ""))
        for j in vaare_just:
            if nokkel(j) not in hos_nff:
                feil.append(f"Justering, {j['lag']}: {_just_tekst(j)} i justeringer.json finnes ikke hos fotball.no")
    if not ferskt and feil:
        beholdt, nedgradert = [], []
        for f in feil:
            k = _nokkel(f)
            if k in bekreftet and bekreftet[k] == _tabell_verdi(vaar, vaare_just, k):
                beholdt.append(f + " [bekreftet av fersk revisjon, uendret hos oss]")
            else:
                nedgradert.append(f"(fotball.no-dataene er fra cachen) {f}")
        feil, advarsler = beholdt, nedgradert + advarsler
    return feil, advarsler


def _tabell_verdi(vaar, vaare_just, nokkel):
    """Vaar rad (eller vaare justeringer) for et tabellavvik, til
    gjenkjenning paa tvers av kjoringer, som _vaar_verdi for kampene."""
    hva, _, lag = nokkel.partition(", ")
    if hva == "Tabell":
        r = vaar.get(lag)
        return [r[f] for f, _ in TABELL_FELT] if r else None
    if hva == "Justering":
        return sorted([j["dato"], j["poeng"], j.get("maal", 0)] for j in vaare_just if j["lag"] == lag)
    return None


def _verdi(nokkel, vaare, vaar=None, vaare_just=()):
    """Vaar verdi for et avvik, kamp eller tabell."""
    if nokkel.startswith(("Tabell, ", "Justering, ")):
        return _tabell_verdi(vaar or {}, list(vaare_just), nokkel)
    return _vaar_verdi(vaare, nokkel)


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


def skriv_stempel(liga, feil, naa, sesong=None):
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
        hva = ("tabellen" if all(f.startswith(("Tabell, ", "Justering, ")) for f in feil)
               else "terminlisten")
        d["error"] = (f"{len(feil)} kritisk(e) avvik mellom {hva} og "
                      f"fotball.no: {feil[0]}")[:300]
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

    Den daglige 20-timersgrensen gaar gjennom nff_source.fetch_all(). Her
    hentes sesongadressen DIREKTE, fordi dette er en manuell reparasjon som
    ikke skal blokkeres av at den daglige kjeden hentet tidligere samme dag.
    Det er en ekstra forespørsel, utlost av et menneske.
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
        nff_tab, nff_just, nff_feil = (nff_source.parse_tabell(tekst, liga),
                                       nff_source.parse_justeringer(tekst, liga), None)
    except nff_source.NffDataError as e:
        nff_tab, nff_just, nff_feil = None, None, str(e)

    vaare = vaare_kamper(liga, sesong)
    feil, advarsler = revider(vaare, rader, ferskt=True,
                              bekreftet=les_bekreftet(liga, naa, sesong),
                              sesong=str(sesong))
    vaar, vaare_just = vaar_tabell(liga, sesong)
    tf, ta = revider_tabell(vaar, nff_tab, vaare_just, nff_just, nff_feil=nff_feil)
    feil, advarsler = feil + tf, advarsler + ta
    log(f"Revisjon av {liga} {sesong}: {len(vaare)} kamper mot {len(rader)} "
        f"hos fotball.no")
    for a in advarsler:
        log(f"  ADVARSEL: {a}")
    for f in feil:
        log(f"  AVVIK: {f}")

    import sesong as _s
    sti.write_text(json.dumps({
        "checked_date": naa.astimezone(OSLO).strftime("%Y-%m-%d"),
        "checked_at": naa.isoformat(timespec="seconds"),
        "ferskt": True, "kjoring": _s.kjoring_id(), "turnering": turnering,
        "errors": len(feil), "warnings": len(advarsler),
        "avvik": feil[:20], "advarsler": advarsler[:20],
        "bekreftet": {_nokkel(f): _verdi(_nokkel(f), vaare, vaar, vaare_just) for f in feil},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    skriv_stempel(liga, feil, naa, sesong)
    return 1 if feil else 0


def main(argv):
    if not argv or argv[0] not in LIGAER:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    liga = argv[0]
    naa = datetime.now(timezone.utc)

    # Ikke revider en frossen sesong. Kildene viser neste sesong rundt
    # aarsskiftet, og da ville hver kamp sett ut som et avvik.
    import sesong as _ses
    _a = _ses.aktiv_sesong(ROT, liga, log=lambda _s: None)
    if _a and _ses.er_frosset(ROT, liga, _a):
        print(f"Sesongen {_a} er frosset -- reviderer ikke. "
              f"En frossen sesong er uforanderlig.")
        return 0

    # fetch_all haandterer selv at fotball.no hentes hoeyst en gang i dognet.
    # Er forsoket sperret, kommer det lagrede svaret -- og det er riktig: da
    # reviderer vi mot det nyeste vi lovlig har.
    nff_rader = nff_source.fetch_all(liga, log=lambda s: print(f"  {s}"))
    hentet = nff_source.sist_hentet(liga)
    # FERSKT betyr at hentingen lyktes i DENNE kjoringen -- ikke at cachen er
    # ny. Feiler dagens henting, brukes de gamle radene til kontroll, men
    # avvik nedgraderes til advarsler og frysingen slipper ikke gjennom.
    ferskt = nff_source.hentet_i_denne_kjoringen(liga)
    vaare = vaare_kamper(liga)
    bekreftet_for = les_bekreftet(liga, naa)
    feil, advarsler = revider(vaare, nff_rader, ferskt=ferskt,
                              bekreftet=bekreftet_for, sesong=_a)
    # Tabellen og justeringene, fra samme henting som kampene.
    nff_tab, nff_just, nff_feil = nff_source.offisiell_tabell(liga)
    vaar, vaare_just = vaar_tabell(liga)
    tf, ta = revider_tabell(vaar, nff_tab, vaare_just, nff_just, ferskt=ferskt,
                            bekreftet=bekreftet_for, nff_feil=nff_feil)
    feil, advarsler = feil + tf, advarsler + ta

    if ferskt:
        kilde_ord = "hentet i denne kjøringen"
    elif hentet:
        kilde_ord = (f"fra cachen, hentet {(naa - hentet).total_seconds() / 3600:.0f} "
                     f"timer siden -- avvik blir advarsler, og frysing sperres")
    else:
        kilde_ord = "ingen henting registrert -- avvik blir advarsler"
    print(f"Daglig terminliste- og tabellrevisjon, {oppsett(liga)['visningsnavn']}: "
          f"{len(vaare)} kamper mot {len(nff_rader)} hos fotball.no ({kilde_ord}); "
          f"tabell: {'sammenlignet' if nff_tab is not None else 'ikke sammenlignet'}")
    for a in advarsler:
        print(f"  ADVARSEL: {a}")
    for f in feil:
        print(f"  AVVIK: {f}")

    sti = ROT / oppsett(liga)["data"] / "audit_fixtures.json"
    sti.write_text(json.dumps({
        "checked_date": naa.astimezone(OSLO).strftime("%Y-%m-%d"),
        "checked_at": naa.isoformat(timespec="seconds"),
        # Om fotball.no-dataene ble hentet i DENNE kjoringen. En revisjon
        # mot cachet data nedgraderer nye avvik til advarsler, og kan derfor
        # ha null feil uten aa ha kontrollert noe. Frysingen krever ferskt.
        "ferskt": ferskt,
        # Turnerings-id-en sesongen har hos fotball.no. Folger med inn i den
        # frosne sesongen, saa en reparasjon senere kan hente nettopp den.
        "turnering": nff_source.les_cache(liga).get("turnering"),
        # Hvilken kjoring som utforte revisjonen. Frysingen krever samme id,
        # saa en gronn revisjon fra i gaar ikke kan apne for frysing naar
        # dagens henting feilet.
        "kjoring": _ses.kjoring_id(),
        "errors": len(feil), "warnings": len(advarsler),
        "avvik": feil[:20], "advarsler": advarsler[:20],
        # Vaar verdi da avviket ble bekreftet. En senere revisjon mot gammel
        # cache holder avviket kritisk saa lenge denne er uendret.
        "bekreftet": ({_nokkel(f): _verdi(_nokkel(f), vaare, vaar, vaare_just) for f in feil}
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
