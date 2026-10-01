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
    (poeng, maalforskjell, scorede maal, navn)."""
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
    rekke = sorted(t, key=lambda n: (-t[n]["poeng"], -(t[n]["mf"] - t[n]["mm"]), -t[n]["mf"], n))
    for i, n in enumerate(rekke):
        t[n]["plass"] = i + 1
    return t


def sammenlign(vaar, offisiell, kilde="ligasiden"):
    """(feil, advarsler, nye, alle_like).

    nye er [(lag, poeng)]: poeng som maa legges til lagets justeringer for at
    vaar poengsum skal bli den offisielle. alle_like er sant bare naar alle
    lag har likt antall kamper og alt stemmer, ogsaa poengene."""
    feil, advarsler, nye = [], [], []
    off = {r["lag"]: r for r in offisiell}
    alle_like = True
    for lag in sorted(set(vaar) | set(off)):
        v, o = vaar.get(lag), off.get(lag)
        if not v or not o:
            feil.append(f"Tabell, {lag}: står {'bare hos ' + kilde if o else 'bare hos oss'}")
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
               kjoring=None, log=print, lag=None):
    """Kjorer kontrollen, legger nye justeringer inn i justeringer.json og
    skriver audit_tabell.json. offisiell er tabellen fra ligasiden, eller
    {"feil": tekst} / None naar den ikke kunne hentes eller leses. lag er
    sesongens lag (standard: lagene i kampene og i ligaoppsettet; en frossen
    sesong som repareres, sender sine egne, siden oppsettet da kan gjelde
    neste sesong). Returnerer innholdet i audit_tabell.json."""
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
        ut.update({"sammenlignet": False, "errors": 0, "warnings": 1, "alle_like": False, "nye": [],
                   "avvik": [], "advarsler": [f"Tabell: ikke sammenlignet ({grunn or 'fikk ingen tabell fra ligasiden'})"]})
    else:
        feil, advarsler, nye, alle_like = sammenlign(vaar, offisiell, kilde)
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
        ut.update({"sammenlignet": True, "errors": len(feil), "warnings": len(advarsler),
                   "alle_like": bool(alle_like) and not feil, "nye": lagt_inn,
                   "avvik": feil[:20], "advarsler": advarsler[:20]})
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
