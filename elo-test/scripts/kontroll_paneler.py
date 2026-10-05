#!/usr/bin/env python3
"""Kontroller for PANELENE på testsiden (W, R og panelfilenes tekst i L).

Egen fil, egen kjøring i elo-test.yml, ETTER at modellen og prognoseloggen er
lagret: panelene skal aldri stoppe modellen. Feiler noe her, lagres ikke
panelfilene, og jobben blir rød. De andre kontrollene (A til V) ligger i
kontroll.py og stopper fortsatt alt, også modellen.

    python3 elo-test/scripts/kontroll_paneler.py
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

HER = Path(__file__).resolve().parent
sys.path.insert(0, str(HER))
import eloodds as E

ROT = HER.parent.parent
PROD = ROT / "eliteserien" / "data"
UT = HER.parent / "emodell"
FEIL = []


def krev(navn, ok, d=""):
    print(f"  {'OK  ' if ok else 'FEIL'}  {navn}" + (f"   {d}" if d else ""))
    if not ok:
        FEIL.append(navn)


M = json.loads((UT / "model.json").read_text(encoding="utf-8"))
_h = (HER.parent / "index.html").read_text(encoding="utf-8")
_akt = "\n".join(l for l in _h.splitlines() if not l.strip().startswith("//"))
# Full-frasene står ett sted, i kontroll.py (kontroll L).
for _n in ast.parse((HER / "kontroll.py").read_text(encoding="utf-8")).body:
    if isinstance(_n, ast.Assign) and getattr(_n.targets[0], "id", None) == "FULL_FRASER":
        FULL_FRASER = ast.literal_eval(_n.value)

# ---------- L (panelfilene): banneret og lastmatch skal ikke beskrive Full
print("L   panelfilenes tekst beskriver ikke Full")
# Panelfilene (keymatch-banneret og lastmatch) er tekst siden viser. De er
# skrevet av /elo-test/, og skal heller ikke beskrive Full.
for _pn in ("keymatch.json", "lastmatch.json"):
    _pf = UT / _pn
    if _pf.exists():
        _pt = _pf.read_text(encoding="utf-8")
        _pfunn = [f for f in FULL_FRASER if f in _pt]
        krev(f"{_pn}: ingen Full-fraser", not _pfunn, ", ".join(_pfunn))

# ---------- W: PANELENE -- regnet av /elo-test/, samme frysregel som produksjonen
# keymatch.json, lastmatch.json, prekick.json og accuracy.json i emodell/ skal
# være skrevet av scripts/snapshot_probs.js mot /elo-test/ (ELO90), ikke kopiert
# fra produksjonen. Beviset: prekick-radene har ELO90-tallene fra model.json
# (outcome av byggingens lambda; "modell" = OLR-sannsynlighetene), og de skiller
# seg fra produksjonens. Frysregelen er produksjonens egen modul.
print("\nW   panelene: regnet av /elo-test/, samme frysregel som produksjonen")
_wf = (ROT / ".github" / "workflows" / "elo-test.yml").read_text(encoding="utf-8")
krev("elo-test.yml kjører produksjonens snapshot_probs.js mot /elo-test/ til emodell/",
     "node scripts/snapshot_probs.js eliteserien --side elo-test --ut elo-test/emodell --uten-historikk" in _wf
     and "python3 scripts/accuracy_log.py eliteserien --data elo-test/emodell" in _wf)
krev("frysregelen er produksjonens modul (ingen kopi i elo-test/)",
     "require('./prekick_frys')" in (ROT / "scripts" / "snapshot_probs.js").read_text(encoding="utf-8")
     and not list((ROT / "elo-test").rglob("prekick_frys*")))
krev("siden henter de fire panelfilene fra emodell/, og ikke history.json",
     # hentFersk (3.10.2026): samme filer, hentet uten gammel kopi.
     all(f"hentFersk('emodell/{n}.json')" in _h for n in ("keymatch", "lastmatch", "prekick", "accuracy"))
     and "history.json" not in _akt and "Promise.resolve(null)" not in _h)
krev("history.json skrives ikke for testsiden", not (UT / "history.json").exists())
_pk = UT / "prekick.json"
if not _pk.exists():
    print("     prekick.json finnes ikke ennå -- innholdssjekkene hoppes over (skrives i CI)")
else:
    import math as _mw
    def _utfall(lh, la):
        def pv(l):
            v = [_mw.exp(-l)]
            for k in range(1, 16):
                v.append(v[-1] * l / k)
            return v
        a, b = pv(lh), pv(la)
        H = U = B = 0.0
        for i in range(16):
            for j in range(16):
                q = a[i] * b[j]
                if i > j: H += q
                elif i == j: U += q
                else: B += q
        s = H + U + B
        return H / s, U / s, B / s
    _pkd = json.loads(_pk.read_text(encoding="utf-8"))["matches"]
    _prodpk = json.loads((PROD / "prekick.json").read_text(encoding="utf-8"))["matches"]
    _kr = {(r["home"], r["away"]): r for r in M["kamper"]}
    _avv, _n, _ulik_prod, _mangler = 0.0, 0, 0, []
    for k, v in _pkd.items():
        if v.get("frosset"):
            continue
        r = _kr.get((v["home"], v["away"]))
        if r is None:
            _mangler.append(k); continue
        med_odds = v.get("kilde") == "odds+modell"
        lam = r["blend_lam"] if med_odds else r["lam"]
        side = _utfall(*lam)
        modell = (r["pH"], r["pU"], r["pB"]) if med_odds else side
        _avv = max(_avv, max(abs(v[x] - side[i]) for i, x in enumerate("HUB")),
                   max(abs(v["modell"][x] - modell[i]) for i, x in enumerate("HUB")))
        _n += 1
        pr = _prodpk.get(k)
        if pr and max(abs(pr[x] - v[x]) for x in "HUB") > 1e-3:
            _ulik_prod += 1
    krev(f"prekick.json har ELO90-tallene fra model.json for {_n} uspilte kamper (runde 23 og utover)",
         _n > 0 and not _mangler and _avv <= 5e-5 + 1e-12, f"største avvik {_avv:.1e}, uten modell: {_mangler[:3]}")
    krev(f"prekick.json er ikke produksjonens: {_ulik_prod} av {_n} kamper skiller seg med over 0,1 prosentpoeng",
         _ulik_prod > _n // 2, f"{_ulik_prod} ulike")
    from datetime import datetime as _dtw
    from zoneinfo import ZoneInfo as _ZIw
    _fxw = {(m["home"], m["away"]): m for r in json.loads((PROD / "fixtures.json").read_text(encoding="utf-8")) for m in r["matches"]}
    _etter = []
    for k, v in _pkd.items():
        if not v.get("frosset"):
            continue
        m = _fxw.get((v["home"], v["away"]))
        if m and m.get("time"):
            a = _dtw.fromisoformat(f"{m['date']}T{m['time']}").replace(tzinfo=_ZIw("Europe/Oslo"))
            if _dtw.fromisoformat(v["stamp"].replace("Z", "+00:00")) >= a:
                _etter.append(k)
    krev(f"frosne rader har stempel før avspark ({sum(1 for v in _pkd.values() if v.get('frosset'))} frosne)",
         not _etter, f"etter avspark: {_etter[:3]}")
    for n in ("keymatch.json", "lastmatch.json"):
        if (UT / n).exists() and (PROD / n).exists():
            krev(f"{n} er ikke en kopi av produksjonens", (UT / n).read_bytes() != (PROD / n).read_bytes())
    _acc = UT / "accuracy.json"
    krev("accuracy.json finnes og teller de frosne radene med resultat",
         _acc.exists() and json.loads(_acc.read_text(encoding="utf-8"))["n"]
         == sum(1 for v in _pkd.values() if v.get("frosset")
                and any(m["home"] == v["home"] and m["away"] == v["away"]
                        for m in json.loads((PROD / "matches.json").read_text(encoding="utf-8")))))

    # lastmatch.json mot det siden selv regner (qaLastMatchData), i Chrome.
    # Snapshot skal ha ventet på ELO_ODDS_SPILT, så forrige kamp er regnet med
    # ratingen etter det alternative resultatet, ikke fast rating.
    krev("snapshot_probs.js venter på ELO_ODDS_SPILT før lastmatch regnes",
         'ELO_ODDS_SPILT === "undefined" || ELO_ODDS_SPILT !== null' in
         (ROT / "scripts" / "snapshot_probs.js").read_text(encoding="utf-8"))
    _lm = UT / "lastmatch.json"
    _chrome = os.environ.get("CHROME_PATH") or next((c for c in ("/usr/bin/google-chrome", "/usr/bin/chromium",
               "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") if Path(c).exists()), None)
    _pp = subprocess.run(["node", "-e", "require('puppeteer-core')"], capture_output=True, text=True).returncode == 0
    if not (_lm.exists() and _chrome and _pp):
        _hvorfor = "lastmatch.json mangler" if not _lm.exists() else "puppeteer-core eller Chrome mangler"
        if os.environ.get("GITHUB_ACTIONS") and _lm.exists():
            krev("lastmatch.json mot siden (Chrome)", False, _hvorfor)
        else:
            print(f"     lastmatch.json mot siden hoppes over lokalt: {_hvorfor}")
    else:
        import socket as _so
        import time as _tm
        _jsw = r"""
const puppeteer = require('puppeteer-core');
(async () => {
  const b = await puppeteer.launch({executablePath: process.argv[2], headless: 'new', args: ['--no-sandbox']});
  const p = await b.newPage();
  await p.goto(process.argv[1], {waitUntil: 'networkidle0'});
  await p.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC && ELO_ODDS_SPILT', {timeout: 180000});
  const ut = await p.evaluate(async () => {
    const r = [];
    for (const t of Object.keys(LASTMATCH.teams).slice(0, 4)) {
      const d = await qaLastMatchData(t), tx = await qaLastMatch(t);
      r.push({lag: t, expected: d.expected == null ? null : +d.expected.toFixed(4), pp: d.pp,
              regnetOm: tx.includes('Ratingen er regnet om'), fast: tx.includes('Lagstyrkene holdes som i dag')});
    }
    return {status: GRUNNLAG_STATUS, lag: r};
  });
  console.log(JSON.stringify(ut)); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""

        def _side(rot):
            _s = _so.socket(); _s.bind(("127.0.0.1", 0)); _port = _s.getsockname()[1]; _s.close()
            _srv = subprocess.Popen([sys.executable, "-m", "http.server", str(_port), "--bind", "127.0.0.1"],
                                    cwd=rot, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                _tm.sleep(1.0)
                return subprocess.run(["node", "-e", _jsw, f"http://127.0.0.1:{_port}/elo-test/", _chrome],
                                      capture_output=True, text=True, timeout=600)
            finally:
                _srv.terminate()

        _rw = _side(ROT)
        # Lokalt etter en endring i sidens kode (5.10.2026): grunnlagsfilen i
        # repoet er regnet av CI med den forrige koden, og avtrykket tar med
        # Worker-koden, så siden avviser filen ("feil avtrykk") og regner forrige
        # kamp live. Da får den litt andre tall enn lastmatch.json, som CI regnet
        # med filen i bruk. Som i regresjonen (grunnlagFilFor i
        # tests/regression.js): filen regnes på nytt med lag_grunnlag.js i en
        # kopi av arbeidstreet, og siden sammenlignes der. Etter push regner CI
        # filen og panelene på nytt. I CI sammenlignes alltid direkte.
        if not _rw.returncode and not os.environ.get("GITHUB_ACTIONS") and (UT / "grunnlag.json").exists():
            _st = json.loads(_rw.stdout.strip().splitlines()[-1])["status"]
            if _st != "i bruk":
                import shutil as _sh
                import tempfile as _tf
                _kopi = _tf.mkdtemp(prefix="grunnlag-paneler-")
                try:
                    _filer = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROT,
                                            capture_output=True, check=True).stdout.decode().split("\0")
                    for _f in filter(None, _filer):
                        _fra = ROT / _f
                        if _fra.is_file():
                            (Path(_kopi) / _f).parent.mkdir(parents=True, exist_ok=True)
                            _sh.copyfile(_fra, Path(_kopi) / _f)
                    _lg = subprocess.run(["node", "scripts/lag_grunnlag.js", "elo-test", "--ut", "elo-test/emodell"],
                                         cwd=_kopi, capture_output=True, text=True, timeout=900)
                    krev(f"grunnlagsfilen regnet på nytt i en kopi (siden avviste filen i repoet: {_st})",
                         _lg.returncode == 0, (_lg.stderr.strip().splitlines() or ["?"])[-1][:160] if _lg.returncode else
                         (_lg.stdout.strip().splitlines() or [""])[0][:160])
                    if _lg.returncode == 0:
                        _rw = _side(_kopi)
                        if not _rw.returncode:
                            _st2 = json.loads(_rw.stdout.strip().splitlines()[-1])["status"]
                            krev("siden i kopien godtar den nye grunnlagsfilen", _st2 == "i bruk", _st2)
                finally:
                    _sh.rmtree(_kopi, ignore_errors=True)
        if _rw.returncode:
            krev("lastmatch.json mot siden (Chrome) kjører", False, (_rw.stderr.strip().splitlines() or ["?"])[-1][:160])
        else:
            _sd = json.loads(_rw.stdout.strip().splitlines()[-1])["lag"]
            _lmd = json.loads(_lm.read_text(encoding="utf-8"))["teams"]
            _ulik = [f"{x['lag']}: fil {_lmd[x['lag']].get('expected')}/{_lmd[x['lag']].get('pp')}, side {x['expected']}/{x['pp']}"
                     for x in _sd if _lmd[x["lag"]].get("expected") != x["expected"] or _lmd[x["lag"]].get("pp") != x["pp"]]
            krev(f"lastmatch.json = qaLastMatch på siden, forventning og prosentpoeng ({len(_sd)} lag: "
                 f"{', '.join(x['lag'] for x in _sd)})", len(_sd) >= 3 and not _ulik, "; ".join(_ulik[:3]))
            krev("forrige kamp sier «Ratingen er regnet om ...», ikke «Lagstyrkene holdes som i dag»",
                 all(x["regnetOm"] and not x["fast"] for x in _sd),
                 ", ".join(x["lag"] for x in _sd if not x["regnetOm"] or x["fast"]))

# ---------- R: DE TO FROSNE REGISTRENE -- prognoseloggen og prekick.json
# Testsiden fryser prognosen før avspark to steder: prognoseloggen (bygg.py:
# siste logglinje med logget < avspark) og prekick.json (snapshot_probs.js:
# siste skriving før avspark, prekick_frys.js). For hver frosne kamp skal
# modelltallene være like innenfor avrundingen. Med odds er prekick "modell"
# OLR-sannsynligheten, som i loggen (elo90_p). Uten odds er den outcome av
# lambda, altså outcome(fit_rates(elo90_p)). Hopper over til det finnes frosne kamper.
print("\nR   de to frosne registrene: prognoseloggen og prekick.json")
_pkR = json.loads((UT / "prekick.json").read_text(encoding="utf-8"))["matches"] if (UT / "prekick.json").exists() else {}
_frR = {k: v for k, v in _pkR.items() if v.get("frosset")}
if not _frR:
    print("     ingen frosne kamper ennå -- hoppes over (første runde: 9.-12. oktober 2026)")
else:
    from datetime import datetime as _dtR
    from zoneinfo import ZoneInfo as _ZIR
    _loggR = [json.loads(l) for f in sorted((UT / "prognoselogg").glob("*.jsonl"))
              for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    _fxR = {}
    for f in [PROD / "fixtures.json"]:
        for r in json.loads(f.read_text(encoding="utf-8")):
            for m in r["matches"]:
                _fxR[(m["home"], m["away"])] = m
    _ms = {(m["home"], m["away"]): m for m in json.loads((PROD / "matches.json").read_text(encoding="utf-8"))}
    def _avsR(h, a):
        m = _fxR.get((h, a)) or _ms.get((h, a))
        if not m or not m.get("time"):
            return None
        return _dtR.fromisoformat(f"{m['date']}T{m['time']}").replace(tzinfo=_ZIR("Europe/Oslo"))
    _avvR, _nR, _utenR = 0.0, 0, []
    for k, v in _frR.items():
        a = _avsR(v["home"], v["away"])
        linjer = [l for l in _loggR if l["hjemme"] == v["home"] and l["borte"] == v["away"]
                  and a is not None and _dtR.fromisoformat(l["logget"]) < a]
        if not linjer:
            _utenR.append(k); continue
        l = linjer[-1]
        if v.get("kilde") == "odds+modell":
            forv = l["elo90_p"]
        else:
            forv = _utfall(*E.fit_rates(l["elo90_p"][0], l["elo90_p"][2], 0.0))
        _avvR = max(_avvR, max(abs(v["modell"][x] - forv[i]) for i, x in enumerate("HUB")))
        _nR += 1
    krev(f"{_nR} frosne kamper: modelltallene i prekick.json = frosset prognose i loggen (innenfor avrundingen)",
         _nR > 0 and not _utenR and _avvR <= 5e-5 + 1e-6, f"største avvik {_avvR:.1e}, uten logglinje: {_utenR[:3]}")


print()
if FEIL:
    print(f"{len(FEIL)} PANELKONTROLL(ER) FEILET:")
    for f in FEIL:
        print(f"    {f}")
    raise SystemExit(1)
print("Alle panelkontroller bestod.")
