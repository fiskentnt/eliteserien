#!/usr/bin/env python3
"""Kontroller for ELO90-testsiden. Skal feile hoylytt.

  A1  den isolerte modulen mot LABENS EGNE funksjoner, samme input.
      Krav: bit-eksakt. Dette er kontrollen paa at kopien er en kopi.
  A2  hele kjeden mot labens diagnose_2026_eloodds.py, med NOR.csv sine
      2026-odds. Krav: 1e-12 paa rating og 1X2.
  B   de 72 lambda-parene mot labens fit_rates. Samme kode og input, saa
      de skal vaere identiske.
  C   sannsynligheter summerer til 1, og markedsblandingen er bare brukt
      paa kampene i produksjonens odds_upcoming.json.

LABEN TRENGS BARE TIL KONTROLLENE, aldri ved kjoring av testsiden. Mangler
den, sies det fra og A1/A2 hoppes over -- de oevrige kjores.
"""
import hashlib
import os
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HER = Path(__file__).resolve().parent
sys.path.insert(0, str(HER))
import eloodds as E

ROT = HER.parent.parent
PROD = ROT / "eliteserien" / "data"
UT = HER.parent / "emodell"
LAB = Path.home() / "Documents/tabellkalkulator-lab"
W, K, RHO = 0.90, 83.37, 0.0
FEIL = []

# FESTEDE SHA256. historikk.json er det fryste grunnlaget og eloodds.py er
# kopien av labens funksjoner. Endrer en av dem seg uten at det er meningen,
# er modellen en annen enn den som er validert -- og da skal dette feile, ogsaa
# i CI der laben ikke finnes.
FESTET = {
    "emodell/historikk.json": "b48baa5de8de8093f36b0bea8d1030921a403bebd823c822559c77d9fce7e108",
    "scripts/eloodds.py": "6afdad7421c64d84f01f1f09b390f6a310ab930bd3452c70d0269d073d3f36b2",
}


def krev(navn, ok, d=""):
    print(f"  {'OK  ' if ok else 'FEIL'}  {navn}" + (f"   {d}" if d else ""))
    if not ok:
        FEIL.append(navn)


M = json.loads((UT / "model.json").read_text(encoding="utf-8"))
hist = json.loads((UT / "historikk.json").read_text(encoding="utf-8"))["sesonger"]
hist = {s: hist[s] for s in sorted(hist)}

# ---- gjenskap byggets input
spilt = [m for m in json.loads((PROD / "matches.json").read_text(encoding="utf-8"))
         if m.get("hg") is not None]
od = {}
for m in json.loads((PROD / "odds.json").read_text(encoding="utf-8"))["matches"]:
    s = m["H"] + m["D"] + m["A"]
    od[(m["home"], m["away"])] = [m["H"]/s, m["D"]/s, m["A"]/s]
S26 = sorted([{"date": m["date"], "home": m["home"], "away": m["away"],
               "hg": m["hg"], "ag": m["ag"],
               "odds": od.get((m["home"], m["away"]))} for m in spilt],
             key=lambda m: (m["date"], m["home"], m["away"]))


def kjeden(mod, hist_, s26_):
    """Labens rekkefolge, ledd for ledd. Tar modulen som argument."""
    alle = [m for v in hist_.values() for m in v if m.get("odds")] + \
           [m for m in s26_ if m.get("odds")]
    hr = mod.hjemmefordel_i_rating(alle, dict(mod.HVA))
    innkjor = [m for y in ("2012", "2013") for m in hist_[y]]
    p = dict(mod.HVA, k=K)
    R, _i, _r = mod.hva_startverdier(innkjor, dict(mod.HVA))
    lg = []
    mod.hva_mix_lap(dict(R), innkjor, p, hr, W, logg=lg)
    for y in [str(x) for x in range(2014, 2026)]:
        mod.hva_mix_lap(R, hist_[y], p, hr, W, logg=lg)
    mod.hva_mix_lap(R, s26_, p, hr, W, logg=lg)
    par = mod.olr_tilpass([x[0] for x in lg], [x[1] for x in lg])
    return hr, R, par


# ---------- A1: mot labens egne funksjoner
lab_mod = None
_p = LAB / "eksperimenter/backtest_zones_med_eksperimenter.py"
if _p.exists():
    sys.path.insert(0, str(ROT / "scripts"))
    _s = importlib.util.spec_from_file_location("labbz", _p)
    lab_mod = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(lab_mod)

# A1 OG A2 ER MASKINUAVHENGIGE MOT model.json. De kjorer kjeden to ganger
# PAA SAMME MASKIN -- en gang med den isolerte modulen, en gang med labens -- og
# sammenligner de to. model.json brukes bare som liste over kamppar;
# ratingforskjellen kommer fra den lokale kjoringen. Det er viktig fordi
# model.json bygges i CI, og en annen maskin -- macOS, eller en CI-runner i en
# annen region -- gir ~8e-09 forskjell i OLR. Hadde A1 sammenlignet mot filen
# med 1e-12, ville den feilet paa maskinen og ikke paa koden. Verifisert: lokalt mot CI-bygget model.json gir 0,000e+00.
print("A1  den isolerte modulen mot labens egne funksjoner, samme input")
if lab_mod is None:
    print("     laben finnes ikke -- hoppes over (den trengs aldri ved kjoring)")
else:
    hr_a, R_a, par_a = kjeden(E, hist, S26)
    hr_b, R_b, par_b = kjeden(lab_mod, hist, S26)
    krev("hjemmefordel identisk", hr_a == hr_b, f"{hr_a!r} mot {hr_b!r}")
    d = max(abs(R_a[t] - R_b[t]) for t in R_a) if set(R_a) == set(R_b) else float("inf")
    krev("rating identisk for alle lag", d == 0.0, f"storste avvik {d:.3e}")
    dp = max(abs(float(x) - float(y)) for x, y in zip(par_a, par_b))
    krev("OLR-parametere identiske", dp == 0.0, f"storste avvik {dp:.3e}")
    # lambda
    dl = 0.0
    for r in M["kamper"]:
        dr = R_a[r["home"]] - R_a[r["away"]]
        ph, pu, pb = E.olr_sannsyn(par_a, dr)
        qh, qu, qb = lab_mod.olr_sannsyn(par_b, dr)
        dl = max(dl, abs(ph-qh), abs(pu-qu), abs(pb-qb))
    krev("1X2 identisk", dl == 0.0, f"storste avvik {dl:.3e}")

# ---------- A2: mot labens diagnose, med NOR.csv sine 2026-odds
print("\nA2  hele kjeden mot labens diagnose_2026_eloodds.py (NOR.csv-odds for 2026)")
NOR = LAB / "resultater/full_elo_2026/inputs/NOR.csv"
if lab_mod is None or not NOR.exists():
    print("     NOR.csv finnes ikke -- hoppes over")
else:
    nm = json.loads((ROT / "scripts/eliteserien_name_map.json").read_text())
    ses = lab_mod.load_seasons(NOR, "Eliteserien", nm)
    for y in list(ses):
        if int(y) >= 2026:
            ses[y] = sorted(ses[y], key=lambda m: m["date"]); continue
        c = Counter(t for m in ses[y] for t in (m["home"], m["away"]))
        ses[y] = sorted([m for m in ses[y]
                         if c[m["home"]] >= 25 and c[m["away"]] >= 25],
                        key=lambda m: m["date"])
    h2 = {s: ses[s] for s in [str(x) for x in range(2012, 2026)]}
    hr_n, R_n, par_n = kjeden(E, h2, ses["2026"])
    # labens diagnose bygger paa NOYAKTIG samme maate
    HRl = lab_mod.hjemmefordel_i_rating(
        [m for y in sorted(ses) for m in ses[y] if m.get("odds")], dict(lab_mod.HVA))
    INN = [m for y in ("2012", "2013") for m in ses[y]]
    pl = dict(lab_mod.HVA, k=K)
    Rl, _i, _r = lab_mod.hva_startverdier(INN, dict(lab_mod.HVA))
    lgl = []
    lab_mod.hva_mix_lap(dict(Rl), INN, pl, HRl, W, logg=lgl)
    for y in range(2014, 2027):
        lab_mod.hva_mix_lap(Rl, ses[str(y)], pl, HRl, W, logg=lgl)
    parl = lab_mod.olr_tilpass([x[0] for x in lgl], [x[1] for x in lgl])
    krev("hjemmefordel", abs(hr_n - HRl) <= 1e-12, f"{hr_n:.10f} mot {HRl:.10f}")
    dd = max(abs(R_n[t] - Rl[t]) for t in R_n)
    krev("rating per lag innenfor 1e-12", dd <= 1e-12, f"storste avvik {dd:.3e}")
    dpp = max(abs(float(a) - float(b)) for a, b in zip(par_n, parl))
    krev("OLR innenfor 1e-12", dpp <= 1e-12, f"storste avvik {dpp:.3e}")
    d12 = 0.0
    for t1 in sorted(R_n):
        for t2 in sorted(R_n):
            if t1 == t2: continue
            a = E.olr_sannsyn(par_n, R_n[t1]-R_n[t2])
            b = lab_mod.olr_sannsyn(parl, Rl[t1]-Rl[t2])
            d12 = max(d12, max(abs(x-y) for x, y in zip(a, b)))
    krev("1X2 for ALLE lagpar innenfor 1e-12", d12 <= 1e-12,
         f"storste avvik {d12:.3e}")

# ---------- B: lambda-parene
print("\nB   de 72 lambda-parene mot labens fit_rates")
if lab_mod is None:
    # Her sto bare "if lab_mod is not None:", uten else. I CI skrev B da
    # overskriften og ingenting mer -- en STILLE hopping, i motsetning til A1
    # og A2 som sier fra. Funnet i den forste CI-kjoringen.
    print("     laben finnes ikke -- hoppes over (den trengs aldri ved kjoring)")
else:
    dl = 0.0
    for r in M["kamper"]:
        a = lab_mod.fit_rates(r["pH"], r["pB"], RHO)
        dl = max(dl, abs(a[0]-r["lam"][0]), abs(a[1]-r["lam"][1]))
    krev(f"{len(M['kamper'])} lambda-par identiske", dl == 0.0,
         f"storste avvik {dl:.3e}")

# ---------- C: summer og blandingsomfang
print("\nC   summer og blandingsomfang")
s1 = max(abs(r["pH"]+r["pU"]+r["pB"]-1.0) for r in M["kamper"])
krev("ELO90s 1X2 summerer til 1", s1 < 1e-12, f"storste avvik {s1:.2e}")
bl = [r for r in M["kamper"] if "blend_p" in r]
if bl:
    s2 = max(abs(sum(r["blend_p"])-1.0) for r in bl)
    krev("blandet 1X2 summerer til 1", s2 < 1e-12, f"storste avvik {s2:.2e}")
opp = {(m["home"], m["away"]) for m in
       json.loads((PROD / "odds_upcoming.json").read_text(encoding="utf-8"))["matches"]}
brukt = {(r["home"], r["away"]) for r in bl}
krev("blanding brukt bare paa kamper i odds_upcoming.json",
     brukt <= opp, f"{len(brukt)} brukt, {len(opp)} i filen")
krev("ingen kamp utenfor odds_upcoming.json har blanding",
     not (brukt - opp), f"{len(brukt - opp)} utenfor")

# ---------- D: sidens EGNE funksjoner, kjort i Node
# Fortegnsfeilen i eloOLR ble fanget med oynene, ikke av en kontroll. 1e-12-
# kontrollene kjorte bare paa Python-siden. Denne kjorer index.html sin egen
# eloOLR, fitRates, stateRate og rateFor mot model.json, saa JS-siden er dekket
# ogsaa i CI.
print("\nD   sidens egne JS-funksjoner mot model.json (Node)")
import shutil
import subprocess
import tempfile
if shutil.which("node") is None:
    krev("node finnes", False, "node mangler -- JS-siden kan ikke kontrolleres")
else:
    import re as _re
    html = (HER.parent / "index.html").read_text(encoding="utf-8")

    def _hent(navn, siste=False):
        ms = list(_re.finditer(r"\nfunction " + navn + r"\(.*?\n\}\n", html, _re.S))
        if not ms:
            raise SystemExit(f"fant ikke function {navn} i index.html")
        return (ms[-1] if siste else ms[0]).group(0)

    js = ("const GMAX=15;\nconst ODDS_W=0.7;\n"
          "let ELO=null,ELO_LAM={},RATES={},LIVE=null,ODDS_UP={};\n"
          + "".join([_hent("pois"), _hent("dcTau"), _hent("outcome"),
                     _hent("fitRates"), _hent("eloOLR"), _hent("eloTabellOppslag"),
                     _hent("eloOddsFor"), _hent("stateRate", True), _hent("rateFor", True)])
          + """
const fs=require('fs');
const M=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const OJ=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const LAM={},OU={};
M.kamper.forEach(r=>{LAM[r.home+"|"+r.away]={dr:r.dr,lam:r.lam,p:[r.pH,r.pU,r.pB],
  blend_lam:r.blend_lam||null};});
OJ.matches.forEach(o=>{OU[o.home+"|"+o.away]=o;});   // RAA, som i boot(); eloOddsFor normaliserer
ELO=M; ELO_LAM=LAM; LIVE={R:(M.rating_alle||M.rating)}; ODDS_UP=OU; RATES={};
let m1=0,mU=0,mB=0,nB=0,mR=0;
for(const r of M.kamper){
  const p=eloOLR(M.olr,r.dr);
  m1=Math.max(m1,Math.abs(p[0]-r.pH),Math.abs(p[1]-r.pU),Math.abs(p[2]-r.pB));
  const got=rateFor(r.home,r.away);
  if(r.blend_lam){nB++;mB=Math.max(mB,Math.abs(got[0]-r.blend_lam[0]),Math.abs(got[1]-r.blend_lam[1]));}
  else {mU=Math.max(mU,Math.abs(got[0]-r.lam[0]),Math.abs(got[1]-r.lam[1]));}
  const o=outcome(r.lam[0],r.lam[1]);
  mR=Math.max(mR,Math.abs(o.H-r.pH),Math.abs(o.U-r.pU),Math.abs(o.B-r.pB));
}
console.log(JSON.stringify({olr:m1,ub:mU,bl:mB,nB:nB,rek:mR}));
""")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(js); jp = fh.name
    r = subprocess.run(["node", jp, str(UT / "model.json"),
                        str(PROD / "odds_upcoming.json")],
                       capture_output=True, text=True)
    if r.returncode:
        krev("Node-sjekken kjorer", False, r.stderr.strip().splitlines()[-1][:120])
    else:
        d = json.loads(r.stdout)
        krev("sidens eloOLR mot byggingens 1X2", d["olr"] <= 1e-15,
             f"maks {d['olr']:.2e}")
        krev("sidens rateFor UTEN odds reproduserer lambda", d["ub"] == 0.0,
             f"maks {d['ub']:.2e}")
        krev(f"sidens rateFor MED 70 % ({d['nB']} kamper) reproduserer lambda",
             d["bl"] == 0.0, f"maks {d['bl']:.2e}")
        # Dette er en MAALING, ikke et krav: lambda-paret rekonstruerer ikke
        # 1X2 eksakt, og storrelsen skal staa i rapporten.
        print(f"  MAALT  lambda-rekonstruksjon av 1X2: maks {d['rek']:.2e} "
              f"(rho = 0)")

# ---------- F: rho MAA vaere 0 baade paa hovedtraaden og i workeren
# Workeren hadde SIN EGEN hardkodede DC_RHO. Endringen paa hovedtraaden naadde
# den ikke, og det ble funnet ved aa lese workerkilden -- ikke av en kontroll.
# Da ville simuleringen trukket maal med rho = -0,38 mens lambda er tilpasset
# rho = 0. Det skal ikke kunne komme tilbake. Fra rettelsen av laaste utfall
# (produksjonen) henter Workeren verdien fra hovedtraaden (${DC_RHO} i
# WORKER_SRC); da er det hovedtraadens verdi som gjelder, og den maa vaere 0.
print("\nF   rho = 0 overalt i index.html")
_h = (HER.parent / "index.html").read_text(encoding="utf-8")
_i = _h.index("const WORKER_SRC = `")
_j = _h.index("`;", _i)
_hoved = _h[:_i] + _h[_j:]
_worker = _h[_i:_j]
import re as _r2
_mh = _r2.findall(r"const DC_RHO\s*=\s*([-\d.]+)\s*;", _hoved)
_mw = _r2.findall(r"var DC_RHO\s*=\s*([-\d.]+|\$\{DC_RHO\})\s*;", _worker)
krev("hovedtraadens DC_RHO er 0", _mh == ["0"], f"fant {_mh}")
krev("workerens DC_RHO er 0 (tallet 0, eller hentet fra hovedtraaden, som er 0)",
     len(_mw) == 1 and (_mw[0] == "0" or (_mw[0] == "${DC_RHO}" and _mh == ["0"])), f"fant {_mw}")
krev('teksten "-0.38" finnes ikke i index.html', "-0.38" not in _h,
     f"{_h.count('-0.38')} forekomster")
krev("model.json oppgir rho = 0", M.get("rho") == 0.0, f"{M.get('rho')}")

# ---------- G: flaksporsmaalet skal ikke kunne naas
# qaLuck() vurderer hver SPILTE kamp med ratingen slik den er I DAG, etter alle
# kampene. En kamp i mars vurderes med septemberratingen -- etterpaaklokskap.
# Oppforingen er fjernet fra sporsmaalslisten, men en kommentar som inneholder
# "id:'luck'" staar igjen som forklaring. En kontroll som bare teller teksten
# ville derfor bestaatt uten aa maale noe. Her fjernes linjekommentarer FORST.
print("\nG   flaksporsmaalet er ikke naabart")
_kode = []
for _l in _h.splitlines():
    _i2 = _l.find("//")
    _kode.append(_l if _i2 < 0 else _l[:_i2])
_kode = "\n".join(_kode)
krev("ingen aktiv oppforing med id:'luck'", "id:'luck'" not in _kode,
     f"{_kode.count(chr(39).join(['id:', 'luck', '']))} treff utenfor kommentar")
_kall = [l.strip() for l in _kode.splitlines()
         if "qaLuck" in l and not l.strip().startswith("function qaLuck")]
krev("qaLuck() kalles ikke fra aktiv kode", not _kall,
     f"{len(_kall)} kall: {_kall[:2]}")

# ---------- H: metadata og isolasjon mot produksjonen
print("\nH   metadata og isolasjon")
krev("meta robots noindex,nofollow finnes",
     'name="robots" content="noindex,nofollow"' in _h)
krev("ingen canonical", "canonical" not in _h, f"{_h.count('canonical')} treff")
krev("ingen og:*-tagger", 'property="og:' not in _h,
     f"{_h.count(chr(39).join([chr(34)+'property=', 'og:']))}")
krev("ingen twitter:*-tagger", 'name="twitter:' not in _h)
krev("ingen strukturerte data (ld+json)", "application/ld+json" not in _h,
     f"{_h.count('application/ld+json')} treff")
krev("ingen besoksstatistikk (goatcounter/analytics)",
     "gc.zgo.at" not in _h and "goatcounter.com" not in _h
     and "window.goatcounter" not in _h)
# INGEN LENKE FRA PRODUKSJONEN. Testsiden skal ikke kunne naas derfra, og ikke
# ligge i sitemap. Rotens index.html, ligasiden og sitemap sjekkes hver for seg.
for rel in ("index.html", "eliteserien/index.html", "sitemap.xml"):
    p = ROT / rel
    krev(f'"elo-test" finnes ikke i {rel}',
         "elo-test" not in p.read_text(encoding="utf-8"))

# INGEN LENKE TIL PRODUKSJONEN FRA TESTSIDEN, bortsett fra banneret
# "Produksjonssiden ligger her". Ligaknappen "Eliteserien" pekte til
# /eliteserien/ og sendte brukeren til produksjonen uten at det merkes.
# Alle forekomster av /eliteserien/ telles, ogsaa fulle URL-er. Unntatt er
# kommentarer (HTML-kommentar, eller en linje som starter med //, /* eller *)
# og ../eliteserien/data/, som er data som hentes, ikke lenker.
# Kontrollen er ikke tom: paa produksjonens index.html MAA den finne
# ligaknappen, ellers maaler den ingenting.
import re as _re
_BANNER = '<a href="/eliteserien/" style="color:#fecaca">Produksjonssiden ligger her.</a>'
def _prodlenker(tekst):
    kom = [(m.start(), m.end()) for m in _re.finditer(r"<!--.*?-->", tekst, _re.S)]
    ut = []
    for m in _re.finditer(r"(?:https?://[^\s\"'`<>]*?)?/eliteserien/", tekst):
        i = m.start()
        if any(a <= i < b for a, b in kom):
            continue
        ls = tekst.rfind("\n", 0, i) + 1
        le = tekst.find("\n", i)
        linje = tekst[ls:le if le >= 0 else None]
        if linje.lstrip().startswith(("//", "/*", "*")):
            continue
        if tekst[max(0, i - 2):i] == ".." and tekst.startswith("data/", m.end()):
            continue
        ut.append(linje.strip())
    return ut
_pl = _prodlenker(_h)
krev("eneste lenke til /eliteserien/ er banneret",
     len(_pl) == 1 and _BANNER in _pl[0],
     f"{len(_pl)} forekomst(er): {[x[:60] for x in _pl]}")
_pp = _prodlenker((ROT / "eliteserien/index.html").read_text(encoding="utf-8"))
krev("kontrollen finner ligaknappen i produksjonens index.html (ikke tom)",
     any("path: '/eliteserien/'" in x for x in _pp),
     f"{len(_pp)} forekomst(er) der")

# ---------- I: DRIFT mot produksjonssiden -- ADVARSEL, ikke feil
# elo-test/index.html er en kopi av eliteserien/index.html slik den var i commit
# 1fc6e8f, med produksjonsrettelsene tatt inn ordrett: merkene (157d9ff),
# ordlyden i forrige kamp (bf623aa), avrundingen i svarene (5f415cd) og
# tidlig stopp og egen Worker for merkene (9cc3590), tabellsimuleringen i
# egen Worker (16934d2) og minnet i fitRates med simuleringen sendt med en
# gang (e9477ea) og låste utfall i svarene regnet med lagstyrkene etter
# resultatet (6d6e5b6), den raskere, bit-like outcome() (fbc447c), grovsilingen
# i poolen (854abcb), rundens viktigste kamp med 3 000 / 20 000 sesonger
# (c8c0269), egne forkastingsgrupper i poolen (54488d8), grunnlagsfilen
# (e83cf10: fingeravtrykket og regningen; bfeb464: siden bruker filen) og
# tekstene om 100 000 simuleringer, treffsikkerheten og sluttoddsen
# (172b0c6, 1f304c6, aaf12ed, d5dc74f), vanlige anførselstegn (e8e9f81) og
# banneret fra grunnlagsfilen (938d959), banneret med én kamp uten den døde
# grenen i qaKeyBanner, siden uten spilte kamper (sesongstart),
# innsiktssvarene fra én kjøring for alle lag og soner (innsiktsblokken i
# grunnlagsfilen, ellers 10 000 sesonger), én delingsknapp ("Del scenario",
# delingsmenyen bare på berøringsskjerm), tabellen på telefon (Gull vises,
# kortnavn under 760 px), "Forrige kamp" (linja og svaret med samme endring,
# uten odds i linja) og "Simulert forrige kamp" / "Neste kamp" bare uten
# resultat, flettet inn med git merge-file. Der
# testsiden har sin egen tekst (ELO-Odds 90), er den beholdt, med samme ordlyd om 100 000 og
# 10 000 simuleringer.
#
# BASISEN ER INNHOLDET, ikke en commit: BASE_SHA er sha256 av
# eliteserien/index.html slik kopien ble tatt. Commiten slås opp i historikken
# ved behov (den nyeste med samme innhold). Før sto commit-hashen her, og den
# ble ugyldig hver gang commiten ble rebaset før push (to ganger 28.9.2026),
# og en commit som endret begge sidene, kunne ikke peke på seg selv.
# Endres produksjonssiden etterpaa, drifter de fra hverandre: en
# rettelse eller ny funksjon der kommer ikke med her. Det er ikke en feil i
# testsiden, men noen maa ta stilling til det -- derfor en advarsel med antall
# endrede linjer, og ingen FEIL.
#
# ELOTEST_PROD_INDEX kan peke paa en annen fil, bare for aa teste advarselen
# uten aa roere produksjonssiden.
print("\nI   drift mot produksjonssiden (advarsel, ikke feil)")
import os as _os
BASE_SHA = "c125e40911de56cafe7e7a63239be71ed8ddeca45b6a9f1db5f0f97349e67571"
_prod = Path(_os.environ.get("ELOTEST_PROD_INDEX") or (ROT / "eliteserien/index.html"))
_naa = hashlib.sha256(_prod.read_bytes()).hexdigest()
if _naa == BASE_SHA:
    print(f"  OK    produksjonssiden er uendret siden kopien ble tatt "
          f"(sha256 {BASE_SHA[:16]}...)")
else:
    def _basis():
        """(commit, tekst) for den nyeste versjonen av eliteserien/index.html
        med sha256 BASE_SHA, eller None. I CI er klonen grunn, saa hele
        historikken hentes ved behov."""
        for forsok in (0, 1):
            r = subprocess.run(["git", "-C", str(ROT), "log", "--format=%H", "--",
                                "eliteserien/index.html"], capture_output=True, text=True)
            for _c in r.stdout.split():
                v = subprocess.run(["git", "-C", str(ROT), "show", f"{_c}:eliteserien/index.html"],
                                   capture_output=True)
                if v.returncode == 0 and hashlib.sha256(v.stdout).hexdigest() == BASE_SHA:
                    return _c, v.stdout.decode("utf-8")
            if forsok == 0:
                subprocess.run(["git", "-C", str(ROT), "fetch", "--quiet", "--unshallow", "origin"],
                               capture_output=True, text=True)
        return None
    import difflib as _dl
    _b = _basis()
    if _b is None:
        _txt = (f"produksjonssiden er ENDRET siden kopien ble tatt "
                f"(sha256 {_naa[:16]}..., basis {BASE_SHA[:16]}...), men basisversjonen "
                f"finnes ikke i historikken, saa antall endrede linjer er ukjent")
    else:
        _a = _b[1].splitlines(); _c = _prod.read_text(encoding="utf-8").splitlines()
        _sm = _dl.SequenceMatcher(None, _a, _c, autojunk=False)
        _fj = sum(i2 - i1 for t_, i1, i2, j1, j2 in _sm.get_opcodes() if t_ != "equal")
        _lt = sum(j2 - j1 for t_, i1, i2, j1, j2 in _sm.get_opcodes() if t_ != "equal")
        _txt = (f"produksjonssiden er ENDRET siden kopien ble tatt i "
                f"{_b[0][:7]}: {_fj} linjer fjernet/endret og {_lt} "
                f"lagt til/endret. Endringene er IKKE med i elo-test/index.html.")
    print(f"  ADVARSEL  {_txt}")
    if _os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning title=ELO-test drifter fra produksjonen::{_txt}")

# ---------- J: SESONGSKIFTET -- ADVARSEL, ikke feil
# Testsiden leser 2026 fra produksjonens filer, og historikk.json dekker bare
# 2012-2025. Naar produksjonen gaar over til 2027, forsvinner 2026 fra
# matches.json, og ratingen mister en hel sesong UTEN at noe feiler: byggingen
# kjorer videre paa 2012-2025 + 2027. Det er den farligste stille feilen
# testsiden har. Derfor advares det med en gang fixtures.json inneholder en
# kamp fra en annen sesong enn 2026.
#
# Hvorfor fixtures.json og ikke matches.json: terminlisten for neste sesong
# kommer FOR de forste resultatene, saa den gir tidligst varsel.
# ELOTEST_FIXTURES kan peke paa en annen fil, bare for aa teste advarselen.
print("\nJ   sesongskiftet (advarsel, ikke feil)")
AKTIV_SESONG = "2026"
_fx_sti = Path(_os.environ.get("ELOTEST_FIXTURES") or (PROD / "fixtures.json"))
_fx = json.loads(_fx_sti.read_text(encoding="utf-8"))
from collections import Counter as _C
_ses = _C(m["date"][:4] for r in _fx for m in r["matches"])
_andre = {aar: n for aar, n in sorted(_ses.items()) if aar != AKTIV_SESONG}
if not _andre:
    print(f"  OK    fixtures.json har bare {AKTIV_SESONG} "
          f"({_ses.get(AKTIV_SESONG, 0)} kamper)")
else:
    _txt = (f"fixtures.json har kamper fra en ANNEN sesong enn {AKTIV_SESONG}: "
            + ", ".join(f"{a} ({n} kamper)" for a, n in _andre.items())
            + f". Sesongskiftet er i gang. {AKTIV_SESONG} maa fryses inn i "
            f"elo-test/emodell/historikk.json FOR produksjonens matches.json "
            f"slutter aa inneholde {AKTIV_SESONG}, ellers mister ratingen en "
            f"sesong uten at noe feiler. Se 'Ikke loest' i elo-test/README.md.")
    print(f"  ADVARSEL  {_txt}")
    if _os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning title=ELO-test: sesongskiftet er i gang::{_txt}")

# ---------- K: STYRKE, regnet uavhengig og mot sidens egen JS
# Styrke var feil skalert: 5 + (rating - snitt)/100 * FORM_SPAN, med spenn 1,1
# til 12,9 og baade Glimt og Viking klippet til 10,0. Funnet ved gjennomgang av
# den publiserte siden, ikke av en kontroll. Riktig er produksjonens formel,
# 5 + (ppk - snitt) * FORM_SPAN, med balansert ppk mot alle de andre lagene,
# hjemme og borte. Her regnes den UAVHENGIG i Python med labens olr_sannsyn, og
# sammenlignes med sidens eloStyrke kjort i Node.
print("\nK   Styrke: uavhengig Python mot sidens eloStyrke, og ingen lag paa 0 eller 10")
_lag = M["teams"]
_R = M.get("rating_alle") or M["rating"]
_FS = float(_r2.search(r"const FORM_SPAN\s*=\s*([\d.]+)\s*;", _hoved).group(1))
_ppk = {}
for _t in _lag:
    _v = []
    for _u in _lag:
        if _u == _t:
            continue
        # _kh/_kb, IKKE _h: _h er HTML-teksten som L trenger. Forste utkast
        # brukte _h her og overskrev den med en tuppel.
        _kh = E.olr_sannsyn(M["olr"], _R.get(_t, 0.0) - _R.get(_u, 0.0))
        _v.append(3 * _kh[0] + _kh[1])
        _kb = E.olr_sannsyn(M["olr"], _R.get(_u, 0.0) - _R.get(_t, 0.0))
        _v.append(3 * _kb[2] + _kb[1])
    _ppk[_t] = sum(_v) / len(_v)
_sn = sum(_ppk.values()) / len(_lag)
_py = [min(10.0, max(0.0, 5 + (_ppk[_t] - _sn) * _FS)) for _t in _lag]
if shutil.which("node") is None:
    krev("node finnes", False)
else:
    _jsK = ("const FORM_SPAN = " + repr(_FS) + ";\nlet ELO=null;\n"
            + _hent("eloOLR", True) + _hent("eloPPK", True) + _hent("eloStyrke", True)
            + "\nconst fs=require('fs');\nELO=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));\n"
              "console.log(JSON.stringify(eloStyrke(ELO.rating_alle||ELO.rating, ELO.teams)));\n")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(_jsK); _jk = fh.name
    _rk = subprocess.run(["node", _jk, str(UT / "model.json")],
                         capture_output=True, text=True)
    if _rk.returncode:
        krev("Styrke-sjekken kjorer", False, _rk.stderr.strip()[:150])
    else:
        _js = json.loads(_rk.stdout)
        _d = max(abs(a - b) for a, b in zip(_py, _js))
        krev("sidens eloStyrke = uavhengig Python-utregning", _d <= 1e-12,
             f"storste avvik {_d:.2e}")
        _klipt = [t for t, v in zip(_lag, _js) if v <= 0.0 or v >= 10.0]
        krev("ingen lag klippet til 0 eller 10 med dagens data", not _klipt,
             f"spenn {min(_js):.1f} til {max(_js):.1f}"
             + (f"; klippet: {_klipt}" if _klipt else ""))

# K tester FUNKSJONEN eloStyrke. At SIDEN bruker den, er vist ved aa gjengi
# siden i Chrome (tabellen og Styrke-kortet viste Glimt 7,8 og Viking 7,0),
# men det kjorer ikke i CI. Her sjekkes koblingen statisk: den SISTE
# definisjonen av formScores (den som vinner) maa returnere eloStyrke, og
# baseForm i tabellraden maa regnes med eloStyrke. Ellers kunne en ny
# formScores gaa rundt eloStyrke uten at noe feilet.
_fs_siste = _hent("formScores", True)
krev("sidens formScores returnerer eloStyrke (Styrke-kolonnen og -kortet)",
     "return eloStyrke(" in _fs_siste, _fs_siste.strip().splitlines()[0][:70])
krev("baseForm i tabellen regnes med eloStyrke",
     "const baseForm=eloStyrke(" in _hoved)
_tfh = _hent("teamFormHistory", True)
krev("formgrafen (teamFormHistory) bruker eloStyrke paa rating_historikk",
     "eloStyrke(" in _tfh and "rating_historikk" in _tfh)

# ---------- L: SYNLIG TEKST skal ikke beskrive Full
# Testsiden er en kopi av produksjonen, og flere avsnitt beskrev Full-modellen:
# at styrken kommer fra maalene, at nye kamper teller mest, produksjonens
# validering, og flaksporsmaalet. Denne ser paa det brukeren kan se:
#   - HTML-tekst utenfor <script>, <style> og <!-- kommentarer -->
#   - aktiv JS, med blokk- og linjekommentarer fjernet (strenger der kan vises)
print("\nL   synlig tekst beskriver ikke Full")
_stat = _r2.sub(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", " ",
                _h, flags=_r2.S)
_aktiv_js = []
for _blk in _r2.findall(r"<script\b[^>]*>(.*?)</script>", _h, _r2.S):
    _blk = _r2.sub(r"/\*.*?\*/", " ", _blk, flags=_r2.S)
    _aktiv_js.append("\n".join(l for l in _blk.splitlines()
                               if not l.strip().startswith("//")))
_aktiv_js = "\n".join(_aktiv_js)
# HELE FULL-FRASER, ikke enkeltord. Testsidens egen tekst sier med vilje
# «Det finnes ingen halveringstid» og «har ikke egne angreps- og forsvarstall»
# -- korrekte negasjoner. Et forbud mot enkeltordene ville tvunget dem bort, og
# korrekt brukertekst skal ikke endres for at en kontroll skal passere.
#
# Frasene er produksjonens FAKTISKE ordlyd der den beskriver Full (sjekket mot
# eliteserien/index.html), pluss eksempelfrasene fra gjennomgangen. To av dem
# finnes ikke ordrett i produksjonen: der heter det «en angreps- og en
# forsvarsstyrke» og «teller halvparten saa mye». Begge variantene er med.
FULL_FRASER = (
    "heldig eller uheldig", "backtest_zones", "Sist validert",
    "gjelder ikke denne siden",
    # produksjonens beskrivelse av Full, ordrett
    "tilpasset på mål og sluttodds", "angreps- og en forsvarsstyrke",
    "Styrkene er beregnet fra alle kampene", "Nyere kamper teller mest",
    "nye kamper teller mest", "teller halvparten så mye",
    "tilpasses på nytt", "styrke fra målene",
    # eksempelfrasene fra gjennomgangen
    "angreps- og forsvarsstyrke", "halveringstid på",
)
for _fr in FULL_FRASER:
    _i1, _i2 = _stat.count(_fr), _aktiv_js.count(_fr)
    krev(f"«{_fr}» finnes ikke i synlig tekst", _i1 == 0 and _i2 == 0,
         f"{_i1} i HTML, {_i2} i aktiv JS")
krev("qaHighlight faller ikke tilbake til 'luck'",
     "dataset.qid = 'luck'" not in _aktiv_js and "qid || 'luck'" not in _aktiv_js)

# ---------- O: rekkefølgen i elo-test.yml -- panelene stopper aldri modellen
print("O   elo-test.yml: modellen og prognoseloggen lagres før panelene")
import re as _re
_wft = (ROT / ".github" / "workflows" / "elo-test.yml").read_text(encoding="utf-8")
# Stegene i rekkefølge: navn og kjørt tekst (alt til neste "      - ").
_steg = []
for _b in _re.split(r"\n      - ", _wft.split("\n    steps:\n", 1)[1])[1:] if "\n    steps:\n" in _wft else []:
    _n = _re.search(r"name:\s*(.+)", _b)
    _b = "\n".join(l for l in _b.splitlines() if not l.strip().startswith("#"))   # kommentarer teller ikke
    _steg.append((_n.group(1).strip() if _n else _b.split("\n")[0], _b))
_navn = [n for n, _ in _steg]
_MODELLFILER = ("elo-test/emodell/model.json", "elo-test/emodell/meta.json", "elo-test/emodell/prognoselogg")
# Banneret (keymatch.json) er ikke med: det regnes av grunnlag.yml fra
# grunnlagsfilen (scripts/lag_grunnlag.js), som i produksjonen.
_PANELFILER = tuple(f"elo-test/emodell/{f}" for f in
                    ("lastmatch.json", "prekick.json", "accuracy.json", "paneler_grunnlag.json"))
def _adds(tekst):
    """Stiene i git add-linjene i et steg (med linjeskift-fortsettelser)."""
    t = tekst.replace("\\\n", " ")
    return [x for l in t.splitlines() if l.strip().startswith("git add")
            for x in l.split()[2:]]
def _i(navn):
    return _navn.index(navn) if navn in _navn else -1
_iB, _iK, _iLM = _i("Bygg ELO90-modellen"), _i("Kontroller modellen"), _i("Lagre modellen og prognoseloggen")
_iP, _iKP, _iLP = _i("Paneler -- regn dem med /elo-test/"), _i("Kontroller panelene"), _i("Lagre panelene")
krev("rekkefølgen: bygg, kontroll.py, lagre modellen, paneler, kontroll_paneler.py, lagre panelene",
     -1 not in (_iB, _iK, _iLM, _iP, _iKP, _iLP) and _iB < _iK < _iLM < _iP < _iKP < _iLP,
     str(_navn))
if -1 not in (_iK, _iKP, _iLM, _iLP):
    krev("kontroll.py kjøres i modellsteget, kontroll_paneler.py i panelsteget",
         "elo-test/scripts/kontroll.py" in _steg[_iK][1] and "kontroll_paneler" not in _steg[_iK][1]
         and "elo-test/scripts/kontroll_paneler.py" in _steg[_iKP][1])
    _am, _ap = _adds(_steg[_iLM][1]), _adds(_steg[_iLP][1])
    krev("modellcommiten tar model.json, meta.json og prognoseloggen -- og ingen panelfil",
         sorted(_am) == sorted(_MODELLFILER), str(_am))
    krev("panelcommiten tar de fire panelfilene -- ikke banneret (grunnlag.yml), modellen eller loggen",
         sorted(_ap) == sorted(_PANELFILER), str(_ap))
    krev("ingen git add av hele elo-test/emodell (da ville panelene følge med modellen)",
         "git add elo-test/emodell\n" not in _wft and not _re.search(r"git add elo-test/emodell/?\s*$", _wft, _re.M))
    krev("ingen continue-on-error eller if: always() som slipper panelfiler gjennom etter feil",
         "continue-on-error" not in _wft and "always()" not in _wft and "failure()" not in _wft)
print()

# ---------- E: festede sha256
# ---------- T: lambda-TABELLEN -- labens fit_rates som bruddpunkter
# Naar ratingen er flyttet, bruker siden tabellen i stedet for JS-fitRates.
# Tabellen er bygget av bygg.py fra labens fit_rates(olr_sannsyn(dr)) og, per
# kamp med odds, fra fit_rates paa den blandede sannsynligheten. Den er ikke
# bevist eksakt: segmenter smalere enn skannesteget kan mangle. Derfor
# MAALES den mot fit_rates paa tilfeldige punkter. Sidens oppslag, derimot,
# skal vaere BIT-LIKT Pythons, og stateRate/rateFor skal faktisk bruke den.
print("\nT   lambda-tabellen: labens fit_rates som bruddpunkter")
import bisect as _bs
import random as _rt
_tab = M.get("lam_tabell")
krev("model.json har lam_tabell", _tab is not None)
_btab = [r for r in M["kamper"] if "marked" in r]
krev(f"alle {len(_btab)} kamper med odds har blend_tabell",
     all("blend_tabell" in r for r in _btab))
if _tab is not None and all("blend_tabell" in r for r in _btab):
    def _stig(tb):
        return all(a < b for a, b in zip(tb["bp"], tb["bp"][1:])) and \
            len(tb["lh"]) == len(tb["la"]) == len(tb["bp"]) + 1
    krev("bruddpunktene er strengt stigende, verdiene en flere",
         _stig(_tab) and all(_stig(r["blend_tabell"]) for r in _btab),
         f"{len(_tab['bp']) + 1} segmenter")
    def _slaa(tb, dr):
        i = _bs.bisect_right(tb["bp"], dr)
        return (tb["lh"][i], tb["la"][i])
    _rg2 = _rt.Random(4711)
    _pk = ([_rg2.uniform(-800, 800) for _ in range(20000)]
           + [_rg2.gauss(0, 150) for _ in range(20000)]
           + [r["dr"] for r in M["kamper"]]
           + list(_tab["bp"]))   # bruddpunktene selv: der skiller <= og <
    _par = M["olr"]
    _avv, _maks = 0, 0.0
    for _x in _pk:
        _ph, _pu, _pb = E.olr_sannsyn(_par, _x)
        _f = E.fit_rates(_ph, _pb, 0.0); _t = _slaa(_tab, _x)
        if _f != _t:
            _avv += 1; _maks = max(_maks, abs(_f[0] - _t[0]), abs(_f[1] - _t[1]))
    print(f"  MAALT  tabell mot fit_rates(olr_sannsyn(dr)): {_avv} avvik av {len(_pk)} "
          f"punkter, stoerste lambda-avvik {_maks:.3f}")
    _bpk = {}
    _bavv, _bn = 0, 0
    for r in _btab:
        mk = r["marked"]
        pts = [_rg2.uniform(-800, 800) for _ in range(2000)] + [_rg2.gauss(r["dr"], 60) for _ in range(1000)] + [r["dr"]]
        _bpk[r["home"] + "|" + r["away"]] = pts
        for _x in pts:
            _ph, _pu, _pb = E.olr_sannsyn(_par, _x)
            _f = E.fit_rates(0.70 * mk[0] + (1 - 0.70) * _ph, 0.70 * mk[2] + (1 - 0.70) * _pb, 0.0)
            _bn += 1
            if _f != _slaa(r["blend_tabell"], _x):
                _bavv += 1
    print(f"  MAALT  blandingstabellene mot fit_rates paa blandet 1X2: {_bavv} avvik av {_bn} punkter")
    krev("blandingstabellen gir byggingens blend_lam ved kampens egen dr",
         all(list(_slaa(r["blend_tabell"], r["dr"])) == r["blend_lam"] for r in _btab))

    # Sidens oppslag og kobling i Node.
    _jst = ("const GMAX=15;\nconst ODDS_W=0.7;\n"
            "let ELO=null,ELO_LAM={},RATES={},LIVE=null,ODDS_UP={};\n"
            + "".join([_hent("pois"), _hent("dcTau"), _hent("outcome"), _hent("fitRates"),
                       _hent("eloOLR"), _hent("eloTabellOppslag"), _hent("eloOddsFor"),
                       _hent("stateRate", True), _hent("rateFor", True)])
            + r"""
const fs=require('fs');
const M=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const OJ=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const INN=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
ELO=M;
M.kamper.forEach(r=>{ELO_LAM[r.home+"|"+r.away]={dr:r.dr,lam:r.lam,p:[r.pH,r.pU,r.pB],blend_lam:r.blend_lam||null,blend_tabell:r.blend_tabell||null};});
OJ.matches.forEach(o=>{ ODDS_UP[o.home+"|"+o.away]=o; });
const opp=INN.pk.map(x=>eloTabellOppslag(M.lam_tabell,x));
const bopp={}; for(const k in INN.bpk){ bopp[k]=INN.bpk[k].map(x=>eloTabellOppslag(ELO_LAM[k].blend_tabell,x)); }
// Kobling: flytt hjemmelagets rating med +d og se hva stateRate og rateFor gir.
const kobling=[];
for(const r of M.kamper){
  for(const d of [-37.5, 12.25, 80]){
    const R=Object.assign({}, M.rating_alle||M.rating); R[r.home]=(R[r.home]||0)+d;
    LIVE={R}; RATES={};
    kobling.push({k:r.home+"|"+r.away, dr:(R[r.home]||0)-(R[r.away]||0), s:stateRate(LIVE,r.home,r.away), f:rateFor(r.home,r.away)});
  }
}
console.log(JSON.stringify({opp,bopp,kobling}));
""")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump({"pk": _pk, "bpk": _bpk}, fh); _inn_t = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(_jst); _jp_t = fh.name
    _r_t = subprocess.run(["node", _jp_t, str(UT / "model.json"), str(PROD / "odds_upcoming.json"), _inn_t],
                          capture_output=True, text=True)
    if _r_t.returncode:
        _fl = [l for l in _r_t.stderr.splitlines() if "Error" in l] or ["?"]
        krev("Node-sjekken for tabellen kjorer", False, _fl[0][:200])
    else:
        _dt = json.loads(_r_t.stdout)
        _ulik = sum(1 for x, j in zip(_pk, _dt["opp"]) if tuple(j) != _slaa(_tab, x))
        krev(f"sidens eloTabellOppslag = Pythons oppslag ({len(_pk)} punkter)", _ulik == 0,
             f"{_ulik} ulike")
        _bulik = sum(1 for k, xs in _bpk.items() for x, j in zip(xs, _dt["bopp"][k])
                     if tuple(j) != _slaa(next(r for r in _btab if r["home"] + "|" + r["away"] == k)["blend_tabell"], x))
        krev(f"sidens oppslag i blandingstabellene = Pythons ({_bn} punkter)", _bulik == 0,
             f"{_bulik} ulike")
        _kr = {r["home"] + "|" + r["away"]: r for r in M["kamper"]}
        _ks = sum(1 for o in _dt["kobling"] if tuple(o["s"]) != _slaa(_tab, o["dr"]))
        krev(f"stateRate bruker lam_tabell naar ratingen er flyttet ({len(_dt['kobling'])} tilfeller)",
             _ks == 0, f"{_ks} ulike")
        _kf = 0
        for o in _dt["kobling"]:
            r = _kr[o["k"]]
            forv = _slaa(r["blend_tabell"], o["dr"]) if "blend_tabell" in r else _slaa(_tab, o["dr"])
            if tuple(o["f"]) != forv:
                _kf += 1
        krev("rateFor bruker blandingstabellen (odds) eller lam_tabell (uten) naar ratingen er flyttet",
             _kf == 0, f"{_kf} ulike")

# ---------- M: SCENARIOOPPDATERINGEN -- sidens JS mot labens hva_mix_lap
# Resultater brukeren fyller inn, og resultater fra simuleringsknappene,
# flytter ratingen etter labens hva_mix_lap (w = 0,90, k = 83,37 med odds,
# reserveregelen k = 10 uten). Regelen er portert til JS i index.html. Denne
# kontrollen kjorer SIDENS EGNE eloMixLap og computeLiveState i Node mot
# Python paa noyaktig samme input -- alle 72 gjenstaaende kamper med trukne
# resultater (fast seed), odds fra odds_upcoming.json der de finnes -- og
# sammenligner ratingen etter HVER kamp, i begge greiner, innenfor 1e-12.
# Kampene gis til siden i terminlisterekkefolge, ikke sortert, saa ogsaa
# sidens sortering (dato, hjemme, borte) blir kontrollert mot Pythons.
print("\nM   scenariooppdateringen: sidens JS mot labens hva_mix_lap")
if shutil.which("node") is None:
    krev("node finnes", False, "node mangler -- JS-siden kan ikke kontrolleres")
else:
    import random as _rnd
    _fx = json.loads((PROD / "fixtures.json").read_text(encoding="utf-8"))
    _oj = json.loads((PROD / "odds_upcoming.json").read_text(encoding="utf-8"))
    _od = {}   # normalisert NOYAKTIG som bygg.py: x / (H + D + A)
    for _o in _oj["matches"]:
        _s = _o["H"] + _o["D"] + _o["A"]
        _od[(_o["home"], _o["away"])] = [_o["H"] / _s, _o["D"] / _s, _o["A"] / _s]
    _rg = _rnd.Random(20260927)
    _terminliste = []
    for _r in _fx:
        for _m in _r["matches"]:
            if _m.get("played"):
                continue
            _hg, _ag = _rg.randint(0, 4), _rg.randint(0, 3)
            _terminliste.append({"date": _m["date"], "home": _m["home"], "away": _m["away"],
                                 "hg": _hg, "ag": _ag})
    _sortert = sorted(_terminliste, key=lambda m: (m["date"], m["home"], m["away"]))
    for _m in _sortert:
        _m["odds"] = _od.get((_m["home"], _m["away"]))
    _R0 = dict(M.get("rating_alle") or M["rating"])
    _p = dict(E.HVA, k=M["k"])
    _hr, _w = M["hjemmefordel_rating"], M["w"]
    _py_steg = []
    _R = dict(_R0)
    for _m in _sortert:
        E.hva_mix_lap(_R, [_m], _p, _hr, _w)
        _py_steg.append(dict(_R))
    # Hele vandringen i ett kall skal gi det samme som steg for steg.
    _py_hel = E.hva_mix_lap(dict(_R0), _sortert, _p, _hr, _w)
    krev("Python: hele vandringen = steg for steg",
         max(abs(_py_hel[t] - _py_steg[-1][t]) for t in _py_hel) == 0.0)
    if lab_mod is not None and hasattr(lab_mod, "hva_mix_lap"):
        _lab_hel = lab_mod.hva_mix_lap(dict(_R0), _sortert, _p, _hr, _w)
        krev("eloodds.py = labens egen hva_mix_lap (samme input)",
             max(abs(_lab_hel[t] - _py_hel[t]) for t in _py_hel) == 0.0)
    else:
        print("     laben finnes ikke -- eloodds.py (verbatim kopi, se A1) brukes alene")

    # DC_RHO kommer fra sidens egen tekst (et av stykkene over tar den med),
    # og kontroll F krever at den er 0.
    _js = ("const GMAX=15;\nconst ODDS_W=0.7;\n"
           "let ELO=null,ELO_LAM={},RATES={},LIVE=null,ODDS_UP={},matches=[],TEAMS=[];\n"
           + _re.search(r"\nconst ELO_HVA = \{[^\n]*\n", html).group(0)
           + "".join([_hent("pois"), _hent("dcTau"), _hent("outcome"), _hent("fitRates"),
                      _hent("eloOLR"), _hent("eloTabellOppslag"), _hent("eloOddsFor"),
                      _hent("eloMixLap"), _hent("eloScenarioKamper"),
                      _hent("computeLiveState", True), _hent("stateRate", True),
                      _hent("rateFor", True)])
           + r"""
const fs=require('fs');
const M=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const OJ=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const INN=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
ELO=M; TEAMS=M.teams; ODDS_UP={};
OJ.matches.forEach(o=>{ ODDS_UP[o.home+"|"+o.away]=o; });   // RAA, som i boot()
M.kamper.forEach(r=>{ELO_LAM[r.home+"|"+r.away]={dr:r.dr,lam:r.lam,p:[r.pH,r.pU,r.pB],blend_lam:r.blend_lam||null,blend_tabell:r.blend_tabell||null};});
// Kampene i terminlisterekkefolge; steg i fylles de i-forste i SORTERT rekkefolge.
const nokkel=m=>m.date+"|"+m.home+"|"+m.away;
const rang={}; INN.sortert.forEach((m,i)=>{ rang[nokkel(m)]=i; });
const steg=[];
for(let i=0;i<INN.sortert.length;i++){
  matches=INN.terminliste.map(m=>rang[nokkel(m)]<=i ? {...m} : {...m, hg:null, ag:null});
  steg.push(computeLiveState().R);
}
matches=INN.terminliste.map(m=>({...m}));
const rekkefolge=eloScenarioKamper().map(nokkel);
const direkte=eloMixLap(Object.assign({},M.rating_alle||M.rating), INN.sortert, M.hjemmefordel_rating, M.w, M.k);
// FORENKLINGEN: siste halvdel utfylt, forste aapen. De aapne kampene ligger
// FOER de utfylte, men skal regnes med ratingen etter ALLE utfylte, via
// lambda-tabellen (blandingstabellen for kamper med odds).
const halv=Math.floor(INN.sortert.length/2);
matches=INN.terminliste.map(m=>rang[nokkel(m)]>=halv ? {...m} : {...m, hg:null, ag:null});
LIVE=computeLiveState(); RATES={};
const aapne=matches.filter(m=>m.hg==null).map(m=>({k:m.home+"|"+m.away,
  dr:(LIVE.R[m.home]||0)-(LIVE.R[m.away]||0), s:stateRate(LIVE,m.home,m.away), f:rateFor(m.home,m.away)}));
// SAMME NORMALISERTE MARKEDSSANNSYNLIGHET: eloOddsFor paa RAADATA fra filen,
// og det rateFor lagrer (og viser i "Blandet 70 % odds").
const norm={}; OJ.matches.forEach(o=>{ norm[o.home+"|"+o.away]=eloOddsFor(o.home,o.away); });
const visMk={}; for(const k in RATES){ if(RATES[k].odds) visMk[k]=RATES[k].mk; }
// RAADATA MED PAASLAG (x 1,03): en innfylt odds-kamp, 3-0, alene. Uten
// normalisering ville markedsleddet brukt tall som summerer til 1,03.
const EKTE=ODDS_UP, skal={};
ODDS_UP={}; OJ.matches.forEach(o=>{ ODDS_UP[o.home+"|"+o.away]={...o, H:o.H*1.03, D:o.D*1.03, A:o.A*1.03}; });
for(const o of OJ.matches){
  matches=INN.terminliste.map(m=>(m.home===o.home&&m.away===o.away) ? {...m, hg:3, ag:0} : {...m, hg:null, ag:null});
  skal[o.home+"|"+o.away]=computeLiveState().R;
}
ODDS_UP=EKTE;
console.log(JSON.stringify({steg, rekkefolge, direkte, hva:ELO_HVA, halv, R_etter:LIVE.R, aapne, norm, visMk, skal}));
""")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump({"terminliste": _terminliste,
                   "sortert": [{k: v for k, v in m.items()} for m in _sortert]}, fh, ensure_ascii=False)
        _inn = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(_js); _jp = fh.name
    _r = subprocess.run(["node", _jp, str(UT / "model.json"), str(PROD / "odds_upcoming.json"), _inn],
                        capture_output=True, text=True)
    if _r.returncode:
        _fl = [l for l in _r.stderr.splitlines() if "Error" in l] or _r.stderr.strip().splitlines() or ["?"]
        krev("Node-sjekken for scenariooppdateringen kjorer", False, _fl[0][:200])
    else:
        _d = json.loads(_r.stdout)
        krev("sidens ELO_HVA = HVA i eloodds.py", _d["hva"] == E.HVA, f"{_d['hva']}")
        krev("sidens sortering = Pythons (dato, hjemme, borte)",
             _d["rekkefolge"] == [f"{m['date']}|{m['home']}|{m['away']}" for m in _sortert],
             f"{len(_d['rekkefolge'])} kamper")
        _med = [i for i, m in enumerate(_sortert) if m["odds"]]
        _uten = [i for i, m in enumerate(_sortert) if not m["odds"]]
        def _avvik(idx):
            mx = 0.0
            for i in idx:
                forr_js = _d["steg"][i - 1] if i else _R0
                forr_py = _py_steg[i - 1] if i else _R0
                m = _sortert[i]
                for t in (m["home"], m["away"]):
                    d_js = _d["steg"][i][t] - forr_js.get(t, 0.0)
                    d_py = _py_steg[i][t] - forr_py.get(t, 0.0)
                    mx = max(mx, abs(d_js - d_py))
                mx = max(mx, max(abs(_d["steg"][i][t] - _py_steg[i][t]) for t in _py_steg[i]))
            return mx
        _a_med, _a_uten = _avvik(_med), _avvik(_uten)
        krev(f"greinen MED odds (w = {_w}, k = {M['k']}): {len(_med)} kamper, JS = Python",
             len(_med) > 0 and _a_med <= 1e-12, f"storste avvik {_a_med:.2e}")
        krev(f"greinen UTEN odds (k = {E.HVA['k']}): {len(_uten)} kamper, JS = Python",
             len(_uten) > 0 and _a_uten <= 1e-12, f"storste avvik {_a_uten:.2e}")
        _a_dir = max(abs(_d["direkte"][t] - _py_hel[t]) for t in _py_hel)
        krev("eloMixLap direkte paa Pythons liste = hva_mix_lap", _a_dir <= 1e-12,
             f"storste avvik {_a_dir:.2e}")
        # Forenklingen: Python-vandringen over den siste halvdelen, i datorekkefolge.
        _R_h = E.hva_mix_lap(dict(_R0), _sortert[_d["halv"]:], _p, _hr, _w)
        _a_h = max(abs(_d["R_etter"][t] - _R_h[t]) for t in _R_h)
        krev("ratingen etter de utfylte kampene = hva_mix_lap over dem (Python)", _a_h <= 1e-12,
             f"storste avvik {_a_h:.2e}")
        import bisect as _bs2
        def _sl(tb, dr):
            i = _bs2.bisect_right(tb["bp"], dr)
            return [tb["lh"][i], tb["la"][i]]
        _kr = {r["home"] + "|" + r["away"]: r for r in M["kamper"]}
        _feil_s = _feil_f = _flyttet = 0
        for o in _d["aapne"]:
            r = _kr[o["k"]]
            dr_py = _R_h[r["home"]] - _R_h[r["away"]]
            if abs(dr_py - r["dr"]) < 1e-12:
                forv_s = r["lam"]; forv_f = r.get("blend_lam") or r["lam"]
            else:
                _flyttet += 1
                forv_s = _sl(M["lam_tabell"], dr_py)
                forv_f = _sl(r["blend_tabell"], dr_py) if "blend_tabell" in r else forv_s
            _feil_s += o["s"] != forv_s
            _feil_f += o["f"] != forv_f
        krev(f"forenklingen: {len(_d['aapne'])} aapne kamper FOER de utfylte regnes med ratingen "
             f"etter alle utfylte, via tabellen ({_flyttet} med flyttet rating)",
             _flyttet > 0 and _feil_s == 0 and _feil_f == 0,
             f"stateRate {_feil_s} ulike, rateFor {_feil_f} ulike")
        # Markedssannsynligheten: raadata -> normalisert, samme tall overalt.
        _ikke1 = [o for o in _oj["matches"] if o["H"] + o["D"] + o["A"] != 1.0]
        print(f"     raadata: {len(_ikke1)} av {len(_oj['matches'])} kamper i odds_upcoming.json "
              f"summerer ikke til 1 ({', '.join(o['home'] + ' - ' + o['away'] for o in _ikke1)})")
        _uln = 0
        for r in M["kamper"]:
            if "marked" not in r:
                continue
            k = r["home"] + "|" + r["away"]
            if _d["norm"].get(k) != r["marked"] or _d["norm"].get(k) != _od[(r["home"], r["away"])]:
                _uln += 1
        krev("sidens eloOddsFor(raadata) = byggingens marked = Pythons normalisering, bit for bit "
             "(samme tall i hva_mix_lap og i 70 %-blandingen)", _uln == 0, f"{_uln} ulike")
        _ulv = sum(1 for k, v in _d["visMk"].items() if v != _d["norm"][k])
        krev(f"rateFor lagrer og viser den normaliserte (\"Blandet 70 % odds\"), {len(_d['visMk'])} kamper",
             len(_d["visMk"]) > 0 and _ulv == 0, f"{_ulv} ulike")
        _ask = 0.0
        for o in _oj["matches"]:
            h_, d_, a_ = o["H"] * 1.03, o["D"] * 1.03, o["A"] * 1.03
            s_ = h_ + d_ + a_
            m_ = next(m for m in _terminliste if m["home"] == o["home"] and m["away"] == o["away"])
            R_ = E.hva_mix_lap(dict(_R0), [{"date": m_["date"], "home": o["home"], "away": o["away"],
                                            "hg": 3, "ag": 0, "odds": [h_ / s_, d_ / s_, a_ / s_]}], _p, _hr, _w)
            J_ = _d["skal"][o["home"] + "|" + o["away"]]
            _ask = max(_ask, max(abs(J_[t] - R_[t]) for t in R_))
        krev(f"innfylt odds-kamp fra raadata med paaslag 1,03 ({len(_oj['matches'])} kamper): "
             "JS-rating = Python innenfor 1e-12", _ask <= 1e-12, f"storste avvik {_ask:.2e}")
        _flytt = max(abs(_py_hel[t] - _R0.get(t, 0.0)) for t in _py_hel)
        krev("kontrollen maaler noe: ratingen flytter seg", _flytt > 1.0,
             f"storste flytting {_flytt:.1f} ratingpoeng")
        # MAALING, ikke krav: tabellens lambda gjenskaper ikke OLR-1X2 eksakt
        # (labens fit_rates-rutenett). Samme stoerrelse som byggingens lambda.
        _rek = 0.0
        g_, Hg_, Bg_ = E._grid(0.0)
        _gi = {round(float(v), 3): i for i, v in enumerate(g_)}
        for o in _d["aapne"]:
            dr_py = _R_h[_kr[o["k"]]["home"]] - _R_h[_kr[o["k"]]["away"]]
            ph, pu, pb = E.olr_sannsyn(M["olr"], dr_py)
            i, j = _gi[round(o["s"][0], 3)], _gi[round(o["s"][1], 3)]
            _rek = max(_rek, abs(Hg_[i, j] - ph), abs(Bg_[i, j] - pb), abs(1 - Hg_[i, j] - Bg_[i, j] - pu))
        print(f"  MAALT  tabell-lambda mot OLR-1X2 etter flyttet rating: maks {_rek:.2e} i H/U/B "
              f"({len(_d['aapne'])} kamper, labens rutenett)")

# ---------- P: Promise.all i boot() -- like mange elementer som variabler, ingen hull
# Da Full-filene ble koblet fra, ble fetch-kallene erstattet av
# Promise.resolve(null) med et komma for mye etter hver. [a,,b] har et HULL, og
# destruktureringen forskyves: CLOSING_IN ble undefined, saa sluttoddsen aldri
# ble lastet paa testsiden. Denne kontrollen deler listen paa toppnivaa (utenom
# kommentarer og strenger) og krever like mange elementer som variabler.
print("\nP   Promise.all i boot(): like mange elementer som variabler, ingen hull")
def _promise_all(src):
    import re as _rp
    m = _rp.search(r"\[([A-Za-z_$][\w$]*(?:\s*,\s*[A-Za-z_$][\w$]*)*)\]\s*=\s*await\s+Promise\.all\(\[", src)
    if not m:
        return None
    navn = [x.strip() for x in m.group(1).split(",")]
    i, dybde, el, deler = m.end(), 0, [], []
    while i < len(src):
        c = src[i]
        if src.startswith("//", i):
            i = src.index("\n", i); continue
        if src.startswith("/*", i):
            i = src.index("*/", i) + 2; continue
        if c in "'\"`":
            j = i + 1
            while src[j] != c:
                j += 2 if src[j] == "\\" else 1
            el.append(src[i:j + 1]); i = j + 1; continue
        if c in "([{":
            dybde += 1
        elif c in ")]}":
            if dybde == 0:
                deler.append("".join(el).strip()); break
            dybde -= 1
        elif c == "," and dybde == 0:
            deler.append("".join(el).strip()); el = []; i += 1; continue
        el.append(c); i += 1
    if deler and deler[-1] == "":
        deler = deler[:-1]          # ett avsluttende komma er lov i JS
    return navn, deler
_pa = _promise_all(_h)
krev("fant [..] = await Promise.all([..]) i boot()", _pa is not None)
if _pa:
    _navn, _deler = _pa
    _hull = [i for i, d in enumerate(_deler) if d == ""]
    krev(f"ingen hull i listen", not _hull,
         f"hull paa plass {_hull}" if _hull else f"{len(_deler)} elementer")
    krev(f"like mange elementer som variabler ({len(_navn)})", len(_deler) == len(_navn),
         f"{len(_deler)} elementer mot {len(_navn)} variabler")
    if len(_deler) == len(_navn):
        _cl = _deler[_navn.index("CLOSING_IN")] if "CLOSING_IN" in _navn else ""
        krev("CLOSING_IN faar fetch av LEAGUE.closingOddsFile", "closingOddsFile" in _cl, _cl[:60])

# ---------- U: LÅSTE UTFALL I SVARENE = SCENARIOET MED SAMME RESULTAT
# Svarene som låser et resultat (neste kamp, kamper som betyr mest, heie på,
# rundens viktigste kamp, forrige kamp, kortet Neste kamp) holdt ratingen fast
# etter det låste resultatet, mens et innfylt scenario oppdaterte den. Nå
# regner hovedtråden ratingen etter utfallet og sender egne målrater for
# oppgaven. Kravet: målratene for de andre åpne kampene er BIT-LIKE dem
# scenarioet gir når samme resultat fylles inn.
print("\nU   låste utfall i svarene: samme målrater som scenarioet med samme resultat")
if shutil.which("node") is None:
    krev("node finnes", False, "node mangler")
else:
    _fxu = json.loads((PROD / "fixtures.json").read_text(encoding="utf-8"))
    _terminu = [{"date": m["date"], "home": m["home"], "away": m["away"], "round": r["round"], "hg": None, "ag": None}
                for r in _fxu for m in r["matches"] if not m.get("played")]
    _spilteu = json.loads((PROD / "matches.json").read_text(encoding="utf-8"))
    _oddsu = json.loads((PROD / "odds.json").read_text(encoding="utf-8"))
    _jsu = ("const GMAX=15;\nconst ODDS_W=0.7;\n"
            "let ELO=null,ELO_LAM={},RATES={},LIVE=null,ODDS_UP={},matches=[],TEAMS=[],MATCHES=[],ELO_ODDS_SPILT=null;\n"
            + _re.search(r"\nconst ELO_HVA = \{[^\n]*\n", html).group(0)
            + "".join([_hent("pois"), _hent("dcTau"), _hent("outcome"), _hent("fitRates"), _hent("eloOLR"),
                       _hent("eloTabellOppslag"), _hent("eloOddsFor"), _hent("eloMixLap"), _hent("eloScenarioKamper"),
                       _hent("computeLiveState", True), _hent("stateRate", True), _hent("rateFor", True),
                       _hent("oddsOverrideFor", True), _hent("eloLamFor"), _hent("eloRatingMedLaast"),
                       _hent("eloRatingMedAlternativ"), _hent("eloOverrideFor"), _hent("eloTaskOver")])
            + r"""
const fs=require('fs');
const M=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const OJ=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const INN=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
ELO=M; TEAMS=M.teams; MATCHES=INN.spilte;
OJ.matches.forEach(o=>{ ODDS_UP[o.home+"|"+o.away]=o; });
M.kamper.forEach(r=>{ELO_LAM[r.home+"|"+r.away]={dr:r.dr,lam:r.lam,p:[r.pH,r.pU,r.pB],blend_lam:r.blend_lam||null,blend_tabell:r.blend_tabell||null};});
ELO_ODDS_SPILT={}; INN.odds.forEach(o=>{ const s=o.H+o.D+o.A; ELO_ODDS_SPILT[o.home+"|"+o.away]=[o.H/s,o.D/s,o.A/s]; });
const TI={}; TEAMS.forEach((t,i)=>TI[t]=i);
// Scenario: fyll inn kampen med resultatet, bygg LIVE, og les oddsOverrideFor for de åpne.
function scenario(forfylt, home, away, hg, ag){
  matches=INN.termin.map(m=>({...m}));
  forfylt.forEach(f=>{ const x=matches.find(m=>m.home===f[0]&&m.away===f[1]); x.hg=f[2]; x.ag=f[3]; });
  const x=matches.find(m=>m.home===home&&m.away===away); x.hg=hg; x.ag=ag;
  LIVE=computeLiveState(); RATES={};
  const ut={}; matches.filter(m=>m.hg==null).forEach(m=>{ ut[m.home+"|"+m.away]=oddsOverrideFor(m.home,m.away); });
  return ut;
}
// Svarveien: kampen står åpen, låses i oppgaven.
function laast(forfylt, home, away, hg, ag){
  matches=INN.termin.map(m=>({...m}));
  forfylt.forEach(f=>{ const x=matches.find(m=>m.home===f[0]&&m.away===f[1]); x.hg=f[2]; x.ag=f[3]; });
  LIVE=computeLiveState(); RATES={};
  const aapne=matches.filter(m=>m.hg==null), open=aapne.map(m=>[TI[m.home],TI[m.away]]);
  const idx=aapne.findIndex(m=>m.home===home&&m.away===away);
  const ov=eloTaskOver({open}, {idx, score:[hg,ag]}).oddsOverride;
  const fast=aapne.map(m=>oddsOverrideFor(m.home,m.away));
  const ut={}, utF={};
  aapne.forEach((m,j)=>{ if(j===idx) return; ut[m.home+"|"+m.away]=ov[j]; utF[m.home+"|"+m.away]=fast[j]; });
  return {ut, utF};
}
const saker=[];
for(const [f, h, a, hg, ag] of INN.saker){
  const s=scenario(f,h,a,hg,ag), l=laast(f,h,a,hg,ag);
  let ulik=0, endret=0, n=0;
  for(const k in s){ n++; if(JSON.stringify(s[k])!==JSON.stringify(l.ut[k])) ulik++;
    if(JSON.stringify(s[k])!==JSON.stringify(l.utF[k])) endret++; }
  saker.push({sak:`${h}-${a} ${hg}-${ag}${f.length?' (med '+f.map(x=>x[0]+'-'+x[1]+' '+x[2]+'-'+x[3]).join(', ')+' utfylt)':''}`, n, ulik, endret});
}
// Forrige kamp: sidens avspilling for alternativt resultat.
matches=INN.termin.map(m=>({...m})); LIVE=computeLiveState();
const alt={};
for(const a of INN.alt){ alt[a.key]=eloRatingMedAlternativ(a); }
console.log(JSON.stringify({saker, alt}));
""")
    # Brann - Viking, alle tre utfall, pluss andre kamper og med noe utfylt fra før.
    _saker = [[[], "Brann", "Viking", 2, 1], [[], "Brann", "Viking", 1, 1], [[], "Brann", "Viking", 0, 1]]
    _ekstra = [m for m in _terminu if not (m["home"] == "Brann" and m["away"] == "Viking")]
    for m in _ekstra[::9][:6]:
        _saker.append([[], m["home"], m["away"], 3, 0])
    _saker.append([[[_ekstra[0]["home"], _ekstra[0]["away"], 0, 2]], "Brann", "Viking", 2, 1])
    # Forrige kamp: et lags siste spilte kamp, med faktisk og alternativt resultat.
    _sisteu = sorted(_spilteu, key=lambda m: (m["date"], m["home"], m["away"]))[-1]
    _alt = [{"key": "faktisk", "home": _sisteu["home"], "away": _sisteu["away"], "hg": _sisteu["hg"], "ag": _sisteu["ag"]},
            {"key": "alternativ", "home": _sisteu["home"], "away": _sisteu["away"], "hg": 0, "ag": 3}]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump({"termin": _terminu, "spilte": _spilteu, "odds": _oddsu["matches"], "saker": _saker, "alt": _alt}, fh,
                  ensure_ascii=False); _innu = fh.name
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(_jsu); _jpu = fh.name
    _ru = subprocess.run(["node", _jpu, str(UT / "model.json"), str(PROD / "odds_upcoming.json"), _innu],
                         capture_output=True, text=True)
    if _ru.returncode:
        _fl = [l for l in _ru.stderr.splitlines() if "Error" in l] or ["?"]
        krev("Node-sjekken for låste utfall kjorer", False, _fl[0][:200])
    else:
        _du = json.loads(_ru.stdout)
        for s in _du["saker"]:
            krev(f"{s['sak']}: svarveien = scenarioet for {s['n']} åpne kamper "
                 f"({s['endret']} endret mot fast rating)",
                 s["ulik"] == 0 and s["endret"] > 0,
                 f"eloTaskOver {s['ulik']} ulike (alle svarene med låste utfall går via den)")
        # Avspillingen i Python: fra dagen før kampen, over de ekte kampene med
        # normalisert sluttodds, med hva_mix_lap. Faktisk resultat skal gi
        # byggingens rating; alternativet skal gi det siden gir.
        _od2 = {}
        for o in _oddsu["matches"]:
            s_ = o["H"] + o["D"] + o["A"]
            _od2[(o["home"], o["away"])] = [o["H"] / s_, o["D"] / s_, o["A"] / s_]
        _H = M["rating_historikk"]
        _foer = sorted(d for d in _H if d < _sisteu["date"])[-1]
        _rest = sorted([m for m in _spilteu if m["date"] >= _sisteu["date"]], key=lambda m: (m["date"], m["home"], m["away"]))
        def _spill(alt):
            R = dict(_H[_foer])
            E.hva_mix_lap(R, [{**m, "odds": _od2.get((m["home"], m["away"])),
                               **({"hg": alt[0], "ag": alt[1]} if alt and m["home"] == _sisteu["home"] and m["away"] == _sisteu["away"] else {})}
                              for m in _rest], dict(E.HVA, k=M["k"]), M["hjemmefordel_rating"], M["w"])
            return R
        _fak, _alt3 = _spill(None), _spill((0, 3))
        _a1 = max(abs(_fak[t] - M["rating_alle"][t]) for t in M["rating_alle"])
        krev(f"forrige kamp: avspilling fra {_foer} med faktisk resultat gir byggingens rating", _a1 <= 1e-9,
             f"største avvik {_a1:.2e}")
        _forv = {t: M["rating_alle"][t] + (_alt3[t] - _fak[t]) for t in M["rating_alle"]}
        _a2 = max(abs(_du["alt"]["alternativ"][t] - _forv[t]) for t in _forv)
        _a3 = max(abs(_du["alt"]["faktisk"][t] - M["rating_alle"][t]) for t in M["rating_alle"])
        _fl2 = max(abs(_forv[t] - M["rating_alle"][t]) for t in _forv)
        krev(f"forrige kamp ({_sisteu['home']} - {_sisteu['away']} 0-3 i stedet for "
             f"{_sisteu['hg']}-{_sisteu['ag']}): sidens rating = Python-avspillingen",
             _a2 <= 1e-9 and _a3 <= 1e-9 and _fl2 > 1.0,
             f"alternativ {_a2:.2e}, faktisk {_a3:.2e}, flytting {_fl2:.1f}")

    # Koblingen: svarene bruker faktisk de egne målratene.
    _hv = _h
    # Kallstedet er produksjonens (laastTaskOver, fra rettelsen av låste
    # utfall i svarene). På testsiden er den SISTE deklarasjonen -- den som
    # gjelder -- en som går til eloTaskOver, så produksjonens lagstyrke-
    # variant aldri kjøres her og ingenting regnes dobbelt. Alle svarene med
    # låste utfall (også kortet, "Hva betyr neste kamp?" og begge silingene i
    # "Hvilke kamper betyr mest?") går i poolen via runZoneTasks.
    def _siste_decl(navn):
        i = _hv.rfind(f"function {navn}(")
        if i < 0:
            return ""
        j = _hv.find("\n}", i)
        k = _hv.find("\n", i)
        return _hv[i:k] if "}" in _hv[i:k] else _hv[i:j + 2]
    _lt = _siste_decl("laastTaskOver")
    krev("runZoneTasks gir hver oppgave eloTaskOver (låst utfall og forrige kamp)",
         "...laastTaskOver(payload, t), mode:'zoneTask'" in _hv and "...(t.over||{}), mode:'zoneTask'" not in _hv
         and "return eloTaskOver(payload, t);" in _lt, _lt[:90])
    krev("runMatchImpactAsync går i poolen (runZoneTasks -> laastTaskOver = eloTaskOver), ingen annen vei",
         "}, tasks, null, gruppe" in _hv and "mode:'matchImpact'" not in _hv and "grovKandidatOver" not in _hv
         and "eloKandidatOver" not in _hv)
    krev("qaLastMatchData merker det alternative resultatet (eloAlt)",
         "eloAlt:{home:m.home, away:m.away, hg, ag}" in _hv)

# ---------- V: forrige kamp -- kildeordet står i svaret, ikke i lagboksen
# Sjansen for resultatet før kampen kan være en frosset prognose eller, som
# reserve, sluttoddsen. Før sto "enn markedet/modellen ventet" både i svaret og
# i linja i lagboksen (ventetAv, bf623aa). Fra 29.9.2026 sier linja bare
# resultatet og endringen i lagets sjanse, og kilden står i svaret: "Sluttoddsen
# ga ..." eller "Modellen ga ...". Produksjonens regel, tatt inn med patchen.
print("\nV   forrige kamp: kildeordet i svaret, ingen kilde i lagboksen")
krev("svaret sier \"Sluttoddsen ga\" ved sluttodds, ellers \"Modellen ga\" (produksjonens)",
     "const kilde = pk && pk.kilde==='sluttoddsen' ? 'Sluttoddsen' : 'Modellen';" in _h
     and "`${kilde} ga ${team} ${pctTxt(pRes)} sjanse ${hva}.`" in _h)
_ml = _r2.search(r"\nfunction qaLastMatchLine\(.*?\n\}\n", _h, _r2.S)
krev("lagbokslinja nevner ingen kilde og ingen forventning",
     bool(_ml) and not any(o in _ml.group(0) for o in ("ventet", "markedet", "modellen", "odds", "preKickProbs")),
     _ml.group(0)[:90] if _ml else "fant ikke qaLastMatchLine")
krev("ingen rester av ventetAv", "ventetAv" not in _h, f"{_h.count('ventetAv')} treff")

print("\nE   festede sha256")
for rel, ventet in FESTET.items():
    p = HER.parent / rel
    fikk = hashlib.sha256(p.read_bytes()).hexdigest()
    krev(f"{rel}", fikk == ventet, f"{fikk[:16]}... mot {ventet[:16]}...")

print()
if FEIL:
    print(f"{len(FEIL)} KONTROLL(ER) FEILET:")
    for f in FEIL:
        print(f"    {f}")
    raise SystemExit(1)
print("Alle kontroller bestod.")
