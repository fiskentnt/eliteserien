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
                     _hent("fitRates"), _hent("eloOLR"),
                     _hent("stateRate", True), _hent("rateFor", True)])
          + """
const fs=require('fs');
const M=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const OJ=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const LAM={},OU={};
M.kamper.forEach(r=>{LAM[r.home+"|"+r.away]={dr:r.dr,lam:r.lam,p:[r.pH,r.pU,r.pB],
  blend_lam:r.blend_lam||null};});
OJ.matches.forEach(o=>{const t=o.H+o.D+o.A;OU[o.home+"|"+o.away]={H:o.H/t,D:o.D/t,A:o.A/t};});
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
# Workeren har SIN EGEN hardkodede DC_RHO. Endringen paa hovedtraaden naadde den
# ikke, og det ble funnet ved aa lese workerkilden -- ikke av en kontroll. Da
# ville simuleringen trukket maal med rho = -0,38 mens lambda er tilpasset
# rho = 0. Det skal ikke kunne komme tilbake.
print("\nF   rho = 0 overalt i index.html")
_h = (HER.parent / "index.html").read_text(encoding="utf-8")
_i = _h.index("const WORKER_SRC = `")
_j = _h.index("`;", _i)
_hoved = _h[:_i] + _h[_j:]
_worker = _h[_i:_j]
import re as _r2
_mh = _r2.findall(r"const DC_RHO\s*=\s*([-\d.]+)\s*;", _hoved)
_mw = _r2.findall(r"var DC_RHO\s*=\s*([-\d.]+)\s*;", _worker)
krev("hovedtraadens DC_RHO er 0", _mh == ["0"], f"fant {_mh}")
krev("workerens DC_RHO er 0", _mw == ["0"], f"fant {_mw}")
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
# 1fc6e8f, med merkerettelsen fra 157d9ff tatt inn (samme patch, ordrett).
# Basisen er derfor 157d9ff. Endres produksjonssiden etterpaa, drifter de fra hverandre: en
# rettelse eller ny funksjon der kommer ikke med her. Det er ikke en feil i
# testsiden, men noen maa ta stilling til det -- derfor en advarsel med antall
# endrede linjer, og ingen FEIL.
#
# ELOTEST_PROD_INDEX kan peke paa en annen fil, bare for aa teste advarselen
# uten aa roere produksjonssiden.
print("\nI   drift mot produksjonssiden (advarsel, ikke feil)")
import os as _os
BASE_COMMIT = "157d9ff995461a5030266da26585f057676f1ad1"
BASE_SHA = "8c35dda095ed2e328d1bbac7b268633ddfb24813ca0eb95bb9d4f7237e05107f"
_prod = Path(_os.environ.get("ELOTEST_PROD_INDEX") or (ROT / "eliteserien/index.html"))
_naa = hashlib.sha256(_prod.read_bytes()).hexdigest()
if _naa == BASE_SHA:
    print(f"  OK    produksjonssiden er uendret siden kopien ble tatt "
          f"({BASE_COMMIT[:7]}, sha256 {BASE_SHA[:16]}...)")
else:
    def _basis():
        """Basisversjonen fra git. I CI er klonen grunn, saa commiten hentes
        ved behov; mangler den likevel, returneres None."""
        for forsok in (0, 1):
            r = subprocess.run(["git", "-C", str(ROT), "show",
                                f"{BASE_COMMIT}:eliteserien/index.html"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return r.stdout
            if forsok == 0:
                subprocess.run(["git", "-C", str(ROT), "fetch", "--quiet",
                                "--depth=1", "origin", BASE_COMMIT],
                               capture_output=True, text=True)
        return None
    import difflib as _dl
    _b = _basis()
    if _b is None:
        _txt = (f"produksjonssiden er ENDRET siden {BASE_COMMIT[:7]} "
                f"(sha256 {_naa[:16]}...), men basisversjonen kunne ikke hentes, "
                f"saa antall endrede linjer er ukjent")
    else:
        _a = _b.splitlines(); _c = _prod.read_text(encoding="utf-8").splitlines()
        _sm = _dl.SequenceMatcher(None, _a, _c, autojunk=False)
        _fj = sum(i2 - i1 for t, i1, i2, j1, j2 in _sm.get_opcodes() if t != "equal")
        _lt = sum(j2 - j1 for t, i1, i2, j1, j2 in _sm.get_opcodes() if t != "equal")
        _txt = (f"produksjonssiden er ENDRET siden kopien ble tatt i "
                f"{BASE_COMMIT[:7]}: {_fj} linjer fjernet/endret og {_lt} "
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

# ---------- E: festede sha256
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
