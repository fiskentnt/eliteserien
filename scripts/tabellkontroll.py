#!/usr/bin/env python3
"""Tabellkontrollen: tabellen vi regner mot tabellen paa ligasiden.

Tabellen staar paa resultatsiden til eliteserien.no og obos-ligaen.no, som
datakjoringen alt henter (ntf_source.siste_tabell). Kontrollen koster derfor
ingen ekstra forespoersel, og den bruker aldri fotball.no (se nff_source.py).
Den kjores i datakjoringen, rett etter at matches.json er skrevet, mot
tabellen fra SAMME kjoring.

Lag for lag:

  ulikt antall kamper          advarsel: kildene er hentet paa ulike tidspunkt
  likt antall kamper, men V/U/T eller maal avviker
                               kritisk avvik: rodt stempel, kjoringen feiler
  likt antall og lik V/U/T og maal, men ulike poeng
                               et nytt poengtrekk (eller tillegg) fra NFF.
                               Differansen legges AUTOMATISK inn i
                               justeringer.json med datoen den ble oppdaget og
                               kilden, saa siden viser stjernen og merknaden
                               med en gang. Lenken til vedtaket legges inn for
                               haand senere. Det varsles i Actions og med en
                               GitHub-issue (varsle() under), ikke med rodt
                               stempel.

RETT ETTER KAMPSLUTT (12.10.2026): gjelder avviket bare en FERSK kamp (avspark
for mindre enn seks timer siden) med resultat bekreftet utenfor NTF, er det en
advarsel og en ny sjekk i neste kjoring, ikke et kritisk avvik. Det gjelder
baade naar kampen er foert med et annet resultat i tabellen paa ligasiden og
naar den mangler der. Kampen staar i feltet "venter" i audit_tabell.json, og
porten (should_fetch.py) aapner i hver kjoring saa lenge noe venter. Er
resultatet ikke bekreftet, eller er fristen ute, gjelder reglene over. Se
ferske_unntak().

Resultatet skrives til <liga>/data/audit_tabell.json. Den siste vellykkede
kontrollen (alle lag stemte) lagres i feltet siste_like med tidspunkt og et
avtrykk av resultatene og justeringene den gjaldt. Frysingen ved sesongslutt
godtar den saa lenge ingenting av det er endret siden (se
frys_sesong.ikke_ferdig): rundt nyttaar kan ligasiden ha byttet til neste
sesong foer karenstiden er ute, og da kan ingen ny kontroll vaere vellykket.

Bruk i workflowen, etter commit-steget:

  python3 scripts/tabellkontroll.py varsle <liga>
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import justeringer as _just
from ligaer import LIGAER, oppsett

ROT = Path(__file__).resolve().parent.parent
OSLO = ZoneInfo("Europe/Oslo")
FELT = (("k", "kamper"), ("v", "vunnet"), ("u", "uavgjort"), ("t", "tap"),
        ("mf", "mål for"), ("mm", "mål mot"))


def vaar_tabell(kamper, lag, just=None):
    """{lag: {k, v, u, t, mf, mm, poeng, plass}} fra de spilte kampene, med
    justeringene ({lag: poeng}) lagt til poengene, rangert som paa siden
    (poeng, maalforskjell, scorede maal, innbyrdes oppgjoer, navn; se
    scripts/rangering.py)."""
    just = just or {}
    t = {n: {"k": 0, "v": 0, "u": 0, "t": 0, "mf": 0, "mm": 0} for n in lag}
    for m in kamper:
        if m.get("hg") is None or m.get("ag") is None:
            continue
        for l, f, mot in ((m["home"], m["hg"], m["ag"]), (m["away"], m["ag"], m["hg"])):
            r = t.setdefault(l, {"k": 0, "v": 0, "u": 0, "t": 0, "mf": 0, "mm": 0})
            r["k"] += 1; r["mf"] += f; r["mm"] += mot
            r["v" if f > mot else "t" if f < mot else "u"] += 1
    for l, r in t.items():
        r["poeng"] = 3 * r["v"] + r["u"] + just.get(l, 0)
    # Rangeringen etter kampreglementet § 5-3, med innbyrdes oppgjør (16.10.2026,
    # scripts/rangering.py), som på siden.
    import rangering
    rekke = rangering.rekkefolge(list(t), kamper, {n: t[n]["poeng"] for n in t},
                                 {n: t[n]["mf"] - t[n]["mm"] for n in t}, {n: t[n]["mf"] for n in t})
    for i, n in enumerate(rekke):
        t[n]["plass"] = i + 1
    return t


def sammenlign(vaar, offisiell, kilde="ligasiden", venter=()):
    """(feil, advarsler, nye, alle_like).

    nye er [(lag, poeng)]: poeng som maa legges til lagets justeringer for at
    vaar poengsum skal bli den offisielle. alle_like er sant bare naar alle
    lag har likt antall kamper og alt stemmer, ogsaa poengene.

    venter: lagene som venter paa en ny sjekk etter en fersk kamp (se
    ferske_unntak). De sammenlignes ikke her -- verken avvik, advarsel eller
    nytt poengtrekk -- og alle_like er da usann."""
    feil, advarsler, nye = [], [], []
    off = {r["lag"]: r for r in offisiell}
    alle_like = True
    for lag in sorted(set(vaar) | set(off)):
        v, o = vaar.get(lag), off.get(lag)
        if not v or not o:
            feil.append(f"Tabell, {lag}: står {'bare hos ' + kilde if o else 'bare hos oss'}")
            alle_like = False
            continue
        if lag in venter:
            alle_like = False
            continue
        if v["k"] != o["k"]:
            advarsler.append(f"Tabell, {lag}: {v['k']} kamper hos oss, {o['k']} hos {kilde} "
                             f"-- hentet på ulike tidspunkt, ikke sammenlignet")
            alle_like = False
            continue
        ulikt = [f"{v[f]} {navn} hos oss, {o[f]} hos {kilde}" for f, navn in FELT if v[f] != o[f]]
        if ulikt:
            feil.append(f"Tabell, {lag}: " + "; ".join(ulikt))
            alle_like = False
        elif v["poeng"] != o["poeng"]:
            nye.append((lag, o["poeng"] - v["poeng"]))
    if alle_like and not nye:
        for lag in sorted(off, key=lambda l: off[l]["plass"]):
            if vaar[lag]["plass"] != off[lag]["plass"]:
                advarsler.append(f"Tabell, {lag}: plass {vaar[lag]['plass']} hos oss, "
                                 f"{off[lag]['plass']} hos {kilde} (lik poengsum, ulik rangering)")
    return feil, advarsler, nye, alle_like and not nye


RADFELT = ("k", "v", "u", "t", "mf", "mm")


def _en_kamp(o, b):
    """Er tabellraden o lik raden b pluss NOEYAKTIG en kamp? Returnerer
    (maal for, maal mot) for den kampen, ellers None."""
    d = {f: o[f] - b[f] for f in RADFELT}
    if d["k"] != 1 or min(d.values()) < 0 or d["v"] + d["u"] + d["t"] != 1:
        return None
    utfall = "v" if d["mf"] > d["mm"] else "t" if d["mf"] < d["mm"] else "u"
    return (d["mf"], d["mm"]) if d[utfall] == 1 else None


def _klokke(iso):
    return datetime.fromisoformat(iso).astimezone(OSLO).strftime("%H:%M")


def ferske_unntak(kamper, lag, just, offisiell, ferske, kilde="ligasiden"):
    """Rett etter kampslutt (12.10.2026): (lag som venter, venter, advarsler).

    9.10.2026 foerte tabellen paa ligasiden Brann-Viking (0-2) som 0-0 i 80
    minutter etter kampslutt. Det ga kritisk avvik og roedt stempel til dagen
    etter, enda resultatet vaart var bekreftet av en uavhengig kilde. De
    andre kveldene manglet den ferske kampen i tabellen en stund.

    ferske er kampene fra resultatregel.ferske_bekreftede: avspark for mindre
    enn seks timer siden, og resultatet bekreftet utenfor NTF. For hver av
    dem regnes tabellen vaar UTEN de ferske kampene (grunnlinjen), og hvert
    av de to lagene er da i en av disse tilstandene:

      lik      raden paa ligasiden er vaar rad (kampen er foert riktig)
      mangler  raden er grunnlinjen (kampen er ikke kommet inn)
      foert    raden er grunnlinjen pluss noeyaktig en kamp, med et annet
               resultat enn vaart (9.10.: pluss en 0-0)
      ulikt    antall kamper er ulikt, og resten gaar ikke opp
      feil     samme antall kamper, men raden er ikke grunnlinjen pluss en
               kamp: noe ELDRE er ulikt

    REGELEN: har et av lagene "feil", eller har begge "foert" med resultater
    som ikke er speilvendte, gjelder kontrollen som foer (kritisk). Ellers
    gjelder avviket bare den ferske kampen: lagene sammenlignes ikke, det
    blir ADVARSEL, og kampen staar i "venter" til tabellen stemmer eller
    fristen (seks timer etter avspark) er ute. Da er kampen ikke lenger
    fersk, og kontrollen gjelder som foer.

    Uten ferske kamper skjer ingenting her."""
    if not ferske:
        return set(), [], []
    off = {r["lag"]: r for r in offisiell}
    nokler = {(f["home"], f["away"]) for f in ferske}
    vaar = vaar_tabell(kamper, lag, just)
    grunn = vaar_tabell([m for m in kamper if (m["home"], m["away"]) not in nokler], lag, just)
    lag_venter, venter, advarsler = set(), [], []
    for f in ferske:
        h, a = f["home"], f["away"]
        if any(l not in off or l not in vaar for l in (h, a)):
            continue
        tilstand = {}
        for l in (h, a):
            v, o, b = vaar[l], off[l], grunn[l]
            if all(v[x] == o[x] for x in RADFELT):
                tilstand[l] = ("lik", None)
            elif all(b[x] == o[x] for x in RADFELT):
                tilstand[l] = ("mangler", None)
            elif o["k"] != v["k"]:
                tilstand[l] = ("ulikt", None)
            else:
                en = _en_kamp(o, b)
                tilstand[l] = ("foert", en) if en else ("feil", None)
        typer = {tilstand[h][0], tilstand[a][0]}
        if typer == {"lik"} or "feil" in typer:
            continue
        foert = tilstand[h][1] or (tilstand[a][1][::-1] if tilstand[a][1] else None)   # sett fra hjemmelaget
        if tilstand[h][0] == "foert" and tilstand[a][0] == "foert" and tilstand[h][1] != tilstand[a][1][::-1]:
            continue        # de to radene forteller ikke om samme kamp
        hvem = f"{h}-{a}"
        bekr = " og ".join(f["kilder"])
        hale = (f"Hos oss {f['hg']}-{f['ag']}, bekreftet av {bekr}. Avspark {_klokke(f['avspark'])}, "
                f"sjekkes på nytt i neste kjøring (frist {_klokke(f['frist'])}).")
        if foert:
            grunn_tekst = f"ført som {foert[0]}-{foert[1]} i tabellen"
            advarsler.append(f"Tabell: {h} og {a} avviker bare i {hvem}, som er {grunn_tekst} på {kilde}. {hale}")
        else:
            grunn_tekst = "mangler i tabellen"
            advarsler.append(f"Tabell: {hvem} {grunn_tekst} på {kilde}. {hale}")
        lag_venter |= {l for l in (h, a) if tilstand[l][0] != "lik"}
        venter.append({"kamp": f"{h}|{a}", "resultat": [f["hg"], f["ag"]], "avspark": f["avspark"],
                       "frist": f["frist"], "kilder": list(f["kilder"]), "grunn": grunn_tekst})
    return lag_venter, venter, advarsler


def avtrykk(kamper, justeringer):
    """sha256 av det tabellen bygger paa: resultatene (lag og maal for hver
    spilte kamp) og justeringene (lag og poeng). Dato og avspark er ikke med;
    de endrer ikke tabellen."""
    k = sorted([m["home"], m["away"], m["hg"], m["ag"]] for m in kamper
               if m.get("hg") is not None and m.get("ag") is not None)
    j = sorted([x["lag"], x["poeng"]] for x in justeringer)
    tekst = json.dumps({"kamper": k, "justeringer": j}, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(tekst.encode("utf-8")).hexdigest()


def data_avtrykk(data_dir, sesong):
    """avtrykk() av matches.json og justeringer.json (sesongen) i data_dir."""
    data_dir = Path(data_dir)
    kamper = json.loads((data_dir / "matches.json").read_text(encoding="utf-8"))
    jsti = data_dir / "justeringer.json"
    just = json.loads(jsti.read_text(encoding="utf-8")).get("justeringer", []) if jsti.exists() else []
    return avtrykk(kamper, [j for j in just if int(j.get("sesong", 0)) == int(sesong)])


def annen_sesong(vaar, offisiell):
    """En grunn hvis tabellen paa ligasiden ser ut til aa gjelde en ANNEN
    sesong enn vaar, ellers None. Rundt aarsskiftet bytter ligasiden til neste
    sesong: tabellen staar da uten kamper, eller med andre lag. Det er ikke
    avvik i vaare data, og skal verken gi rodt stempel eller aapne for
    frysing -- bare sies tydelig."""
    off = {r["lag"] for r in offisiell}
    if off != set(vaar):
        return (f"tabellen på ligasiden har andre lag enn vår (bare der: {sorted(off - set(vaar))}, "
                f"bare hos oss: {sorted(set(vaar) - off)}) -- en annen sesong?")
    if all(r["k"] == 0 for r in offisiell) and any(v["k"] > 0 for v in vaar.values()):
        return "tabellen på ligasiden har ingen spilte kamper -- en ny sesong?"
    return None


def _poeng_tekst(n):
    return "et poeng" if abs(n) == 1 else f"{abs(n)} poeng"


def kontroller(liga, sesong, kamper, offisiell, naa=None, data_dir=None, kilde_url=None,
               kjoring=None, log=print, lag=None, ferske=None):
    """Kjorer kontrollen, legger nye justeringer inn i justeringer.json og
    skriver audit_tabell.json. offisiell er tabellen fra ligasiden, eller
    {"feil": tekst} / None naar den ikke kunne hentes eller leses. lag er
    sesongens lag (standard: lagene i kampene og i ligaoppsettet; en frossen
    sesong som repareres, sender sine egne, siden oppsettet da kan gjelde
    neste sesong). ferske er de ferske kampene med bekreftet resultat
    (resultatregel.ferske_bekreftede), se ferske_unntak; uten dem gjelder
    kontrollen som foer. Returnerer innholdet i audit_tabell.json."""
    naa = naa or datetime.now(timezone.utc)
    data_dir = Path(data_dir or ROT / oppsett(liga)["data"])
    lag = sorted(lag or ({m["home"] for m in kamper} | {m["away"] for m in kamper} | set(oppsett(liga)["lag"])))
    kilde = (kilde_url or oppsett(liga)["ntf_base"]).replace("https://www.", "").split("/")[0]
    jsti = data_dir / "justeringer.json"
    jdok = json.loads(jsti.read_text(encoding="utf-8")) if jsti.exists() else {"justeringer": []}
    asti = data_dir / "audit_tabell.json"
    try:
        forrige = json.loads(asti.read_text(encoding="utf-8"))
    except Exception:
        forrige = {}
    just = [j for j in jdok.get("justeringer", []) if int(j.get("sesong", 0)) == int(sesong)]
    vaar = vaar_tabell(kamper, lag, _just.per_lag(just))
    ut = {"checked_at": naa.isoformat(timespec="seconds"),
          "checked_date": naa.astimezone(OSLO).strftime("%Y-%m-%d"),
          "kjoring": kjoring, "kilde": kilde_url, "sesong": str(sesong)}
    grunn = None
    if offisiell and isinstance(offisiell, list):
        grunn = annen_sesong(vaar, offisiell)
        if grunn:
            offisiell = None
    elif isinstance(offisiell, dict):
        grunn = offisiell.get("feil")
    if not offisiell or not isinstance(offisiell, list):
        # Kunne ikke sammenligne: det som ventet paa en ny sjekk, venter
        # videre til fristen er ute.
        venter = [v for v in (forrige.get("venter") or [])
                  if forrige.get("sesong") == str(sesong) and v.get("frist") and datetime.fromisoformat(v["frist"]) > naa]
        ut.update({"sammenlignet": False, "errors": 0, "warnings": 1, "alle_like": False, "nye": [],
                   "avvik": [], "advarsler": [f"Tabell: ikke sammenlignet ({grunn or 'fikk ingen tabell fra ligasiden'})"],
                   "venter": venter})
    else:
        lag_venter, venter, ferske_adv = ferske_unntak(kamper, lag, _just.per_lag(just), offisiell, ferske, kilde)
        feil, advarsler, nye, alle_like = sammenlign(vaar, offisiell, kilde, venter=lag_venter)
        advarsler = ferske_adv + advarsler
        for a in ferske_adv:
            log(f"::warning title=Tabellen på {kilde} henger etter::{a}")
        lagt_inn = []
        for l, p in nye:
            r = vaar[l]
            j = {"sesong": int(sesong), "lag": l, "poeng": p,
                 "dato": naa.astimezone(OSLO).strftime("%Y-%m-%d"),
                 "oppdaget": naa.isoformat(timespec="seconds"),
                 "kilde": kilde_url or kilde,
                 "årsak": (f"Oppdaget automatisk i tabellen på {kilde}: {r['poeng'] + p} poeng, mot "
                           f"{r['poeng']} fra kampene{' og justeringene' if r['poeng'] != 3 * r['v'] + r['u'] else ''}. "
                           f"Vedtaket er ikke lagt inn ennå."),
                 "automatisk": True}
            jdok.setdefault("justeringer", []).append(j)
            lagt_inn.append(j)
            log(f"NYTT POENGTREKK: {l} {'trukket' if p < 0 else 'gitt'} {_poeng_tekst(p)} "
                f"(tabellen på {kilde}) -- lagt inn i justeringer.json")
        if lagt_inn:
            jsti.write_text(json.dumps(jdok, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            alle_like = alle_like or (not feil and all(o["k"] == vaar[o["lag"]]["k"] for o in offisiell))
        # Saa lenge noe venter paa en ny sjekk, er ikke alle like: frysingen
        # kan ikke bygge paa denne kontrollen.
        ut.update({"sammenlignet": True, "errors": len(feil), "warnings": len(advarsler),
                   "alle_like": bool(alle_like) and not feil and not venter, "nye": lagt_inn,
                   "avvik": feil[:20], "advarsler": advarsler[:20], "venter": venter})
    # Den siste vellykkede kontrollen, til frysingen (se docstringen oeverst):
    # en ny vellykket kontroll erstatter den; en kontroll som sammenlignet,
    # men ikke fant alle like, sletter den (et nyere avvik skal ikke kunne
    # overstyres av en eldre gronn kontroll); en kontroll som ikke kunne
    # sammenligne, beholder den.
    if ut["sammenlignet"] and ut["alle_like"]:
        ut["siste_like"] = {"checked_at": ut["checked_at"], "kjoring": kjoring, "kilde": kilde_url,
                            "avtrykk": avtrykk(kamper, [j for j in jdok.get("justeringer", [])
                                                        if int(j.get("sesong", 0)) == int(sesong)])}
    elif not ut["sammenlignet"] and forrige.get("sesong") == str(sesong) and forrige.get("siste_like"):
        ut["siste_like"] = forrige["siste_like"]
    else:
        ut["siste_like"] = None
    asti.write_text(json.dumps(ut, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for a in ut["advarsler"]:
        log(f"  ADVARSEL: {a}")
    for f in ut["avvik"]:
        log(f"  AVVIK: {f}")
    return ut


def avvik(liga, data_dir=None):
    """Antall kritiske avvik i siste tabellkontroll (0 uten fil). Leses av dem
    som skriver status.json, saa et rodt stempel ikke blir overskrevet."""
    sti = Path(data_dir or ROT / oppsett(liga)["data"]) / "audit_tabell.json"
    try:
        return int(json.loads(sti.read_text(encoding="utf-8")).get("errors") or 0)
    except Exception:
        return 0


def varsle(liga, data_dir=None, kjoring=None, gh="gh", log=print):
    """Varsler om justeringer som ble lagt inn i DENNE kjoringen: en advarsel
    i Actions, en linje i jobboppsummeringen og en GitHub-issue. Returnerer
    antallet som ble varslet."""
    import sesong as _s
    sti = Path(data_dir or ROT / oppsett(liga)["data"]) / "audit_tabell.json"
    try:
        d = json.loads(sti.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if d.get("kjoring") != (kjoring or _s.kjoring_id()) or not d.get("nye"):
        return 0
    navn = oppsett(liga)["visningsnavn"]
    for j in d["nye"]:
        tittel = (f"Nytt poengtrekk i {navn}: {j['lag']} {'trukket' if j['poeng'] < 0 else 'gitt'} "
                  f"{_poeng_tekst(j['poeng'])}")
        tekst = (f"{j['årsak']}\n\nLagt inn automatisk i `{oppsett(liga)['data']}/justeringer.json` "
                 f"{j['oppdaget']} (dato {j['dato']}, kilde {j['kilde']}). Siden viser stjernen og "
                 f"merknaden allerede.\n\nGjenstår for hånd: legg inn vedtaket (dato i `vedtak`, lenke i "
                 f"`lenke`, årsak), og sett `dato` til datoen trekket gjelder fra hvis den er en annen.")
        log(f"::warning title={tittel}::{j['årsak']}")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(f"### {tittel}\n\n{tekst}\n\n")
        if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
            r = subprocess.run([gh, "issue", "create", "--title", tittel, "--body", tekst],
                               capture_output=True, text=True)
            log(f"  issue: {(r.stdout or r.stderr).strip()[:200]}")
    return len(d["nye"])


def main(argv):
    if len(argv) != 2 or argv[0] != "varsle" or argv[1] not in LIGAER:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    varsle(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
