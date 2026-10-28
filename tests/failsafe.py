#!/usr/bin/env python3
"""Tester at resultatkjeden aldri publiserer noe den ikke skal.

Kjøres av tests/run.sh, uten nett og uten nøkkel: kildene simuleres.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# ETT sted hindrer at testene skriver i produksjonsdataene. Se tests/conftest.py.
sys.path.insert(0, str(ROOT / "tests"))
import conftest as _vern
_VERN = _vern.vern()
MATCHES = ROOT / "obos" / "data" / "matches.json"

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}\n      {detail}")


def run(*args):
    # Subprosessen er en EGEN python, og arver os.environ. Det er derfor
    # conftest.vern() setter MILJOVARIABLER og ikke bare modulattributter:
    # et modulattributt satt her inne naar aldri inn dit.
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "obos_results.py"), *args],
                          capture_output=True, text=True, cwd=ROOT)


def main():
    print("Resultatkjeden: failsafe")
    before = MATCHES.read_bytes()
    n_before = len(json.loads(before))

    # 1. Ingen kilder svarer: ingenting skal endres.
    r = run("--break-all", "--no-oddspapi")
    check("ingen kilder: avslutter med feilkode", r.returncode == 2, f"kode {r.returncode}")
    check("ingen kilder: sier fra i loggen", "INGEN KILDER SVARTE" in r.stdout, r.stdout[-200:])
    check("ingen kilder: datasettet er uendret", MATCHES.read_bytes() == before)

    # 2. Wikipedia ødelagt, men OddsPapi mangler nøkkel: heller ingen endring.
    #    Tørrkjøring: ligasiden svarer, så kjeden går helt gjennom, og da skal
    #    verken datasettet eller tilstanden (results_state.json) skrives.
    tilstand = (ROOT / "obos" / "data" / "results_state.json").read_bytes()
    r = run("--break-wikipedia", "--no-oddspapi", "--dry-run")
    check("ødelagt Wikipedia: datasettet er uendret", MATCHES.read_bytes() == before)
    check("tørrkjøring: results_state.json er uendret",
          (ROOT / "obos" / "data" / "results_state.json").read_bytes() == tilstand, r.stdout[-300:])

    # 3. Valideringen: et tidligere publisert resultat som forsvinner eller
    #    endrer seg skal stoppe publiseringen.
    import obos_results as R
    sched = R.schedule()
    prev = R.published()
    rows = json.loads(before)
    check("validering: uendret datasett går gjennom", R.validate(rows, sched, prev) == [])
    missing = [m for m in rows[1:]]
    p = R.validate(missing, sched, prev)
    check("validering: stopper hvis et resultat forsvinner",
          any("borte" in x for x in p), str(p[:2]))
    changed = json.loads(before)
    changed[0]["hg"] = changed[0]["hg"] + 5
    p = R.validate(changed, sched, prev)
    check("validering: stopper hvis et resultat endres",
          any("endret" in x for x in p), str(p[:2]))
    dup = json.loads(before) + [json.loads(before)[0]]
    p = R.validate(dup, sched, prev)
    check("validering: stopper hvis en kamp finnes to ganger",
          any("to ganger" in x for x in p), str(p[:2]))
    bad = json.loads(before)
    bad[0]["hg"] = None
    p = R.validate(bad, sched, prev)
    check("validering: stopper på ugyldig resultat", any("ugyldig" in x for x in p), str(p[:2]))
    ghost = json.loads(before)
    ghost[0]["home"] = "Et Lag Som Ikke Finnes"
    p = R.validate(ghost, sched, prev)
    check("validering: stopper på kamp utenfor terminlisten",
          any("terminlisten" in x for x in p), str(p[:2]))

    # 4. Wikipedia-parseren skal si nei til sider uten resultatrutenett.
    import urllib.request, io, json as _json
    names = R.load_names()

    def with_page(body_html):
        """Later som Wikipedia svarer med denne siden."""
        payload = _json.dumps({"parse": {"text": {"*": body_html}}}).encode()
        real = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: io.BytesIO(payload)
        try:
            return R.wikipedia_results(names)
        finally:
            urllib.request.urlopen = real

    check("Wikipedia: helt tom side gir ingen resultater", with_page("") is None)
    check("Wikipedia: side uten rutenett gir ingen resultater",
          with_page("<p>Ingen tabell her</p><table class='wikitable'><tr><th>Lag</th>"
                    "<th>Poeng</th></tr><tr><td>Bryne</td><td>35</td></tr></table>") is None)
    check("Wikipedia: rutenett med ukjent lagnavn avvises",
          with_page("<table class='wikitable'><tr>" + "<th>Hjemme \\ Borte</th>" +
                    "".join(f"<th>K{i}</th>" for i in range(16)) + "</tr>" +
                    "".join("<tr><th>Ukjent Klubb</th>" + "<td></td>" * 16 + "</tr>"
                            for _ in range(16)) + "</table>") is None)

    # 5. Kamper som ikke er ferdigspilt skal aldri gi resultat.
    teams = {t for k in sched for t in k}
    fx = lambda status: [{"participant1Name": "Bryne FK", "participant2Name": "Moss FK",
                          "statusId": status, "fixtureId": "x"}]
    tomt = {}
    for status, navn in [(0, "ikke startet"), (1, "pågår"), (3, "utsatt eller avbrutt")]:
        got = R.finished_without_result(fx(status), tomt, R.load_names(), teams)
        check(f"kamp som {navn}: hentes ikke", got == [], str(got))
    got = R.finished_without_result(fx(2), tomt, R.load_names(), teams)
    check("ferdigspilt kamp: hentes", len(got) == 1 and got[0][0] == ("Bryne", "Moss"), str(got))
    got = R.finished_without_result(fx(2), {("Bryne", "Moss"): (1, 0)}, R.load_names(), teams)
    check("kamp vi alt har resultat for: hentes ikke igjen", got == [], str(got))

    # 6. Delresultat fra OddsPapi skal ikke godtas: bare feltet "result".
    import types
    saved = R.oddspapi.call
    def fake(payload):
        R.oddspapi.call = lambda *a, **k: (payload, None)
        try:
            return R.oddspapi_score("nøkkel", "x")
        finally:
            R.oddspapi.call = saved
    check("bare omgangsresultat: ingen score",
          fake({"scores": {"periods": {"period1": {"participant1Score": 1, "participant2Score": 0}}}}) is None)
    check("sluttresultat: leses",
          fake({"scores": {"periods": {"result": {"participant1Score": 2, "participant2Score": 1}}}}) == (2, 1))

    # 7. Regelen for å publisere, med kildene hver for seg.
    from datetime import datetime, timedelta, timezone as _tz
    key = next(iter(sched))
    s2 = sched[key]
    kick = datetime.fromisoformat(f"{s2['date']}T{s2['time']}").replace(
        tzinfo=R.ZoneInfo("Europe/Oslo")).astimezone(_tz.utc)
    fersk = kick + timedelta(hours=3)      # tre timer etter avspark
    gammel = kick + timedelta(hours=30)    # over et døgn etter
    # Regelen fra 3.10.2026 (resultatregel.py): et resultat publiseres når
    # hovedkilden og minst én kilde fra en annen leverandør er enige. Uten
    # uavhengig kilde publiseres ligasiden alene etter 24 timer, ukontrollert;
    # en annen enkeltkilde aldri. off=None betyr at ligasiden ikke svarte.
    pub, conf, vent, ukon = R.decide({key: (2, 1)}, None, None, sched, {}, fersk)
    check("ligasiden alene, fersk kamp: venter på en uavhengig kilde",
          key not in pub and not conf and len(vent) == 1, f"{pub.get(key)} {conf} {vent}")
    pub, conf, vent, ukon = R.decide({key: (2, 1)}, None, None, sched, {}, gammel)
    check("ligasiden alene, over et døgn: publiseres uten kontroll (rødt til den er bekreftet)",
          pub.get(key) == (2, 1) and ukon == {key: (2, 1)}, f"{pub.get(key)} {ukon}")
    pub, conf, vent, ukon = R.decide({key: (2, 1)}, None, None, sched, {}, fersk, hl={key: (2, 1)})
    check("ligasiden og Highlightly enige: publiseres med en gang", pub.get(key) == (2, 1) and not conf and not ukon)
    pub, conf, vent, ukon = R.decide({key: (2, 1)}, None, {key: (2, 1)}, sched, {}, fersk)
    check("ligasiden og Wikipedia enige: publiseres", pub.get(key) == (2, 1) and not conf)
    pub, conf, vent, ukon = R.decide({key: (2, 1)}, None, {key: (1, 1)}, sched, {}, fersk)
    check("ligasiden, men Wikipedia uenig og ingen andre: holdes tilbake",
          key not in pub and len(conf) == 1, f"{pub.get(key)} {conf}")
    pub, conf, vent, ukon = R.decide({key: (2, 1)}, None, {key: (1, 1)}, sched, {}, fersk, hl={key: (2, 1)})
    check("ligasiden og Highlightly enige, Wikipedia uenig: publiseres", pub.get(key) == (2, 1) and not conf)
    pub, conf, vent, ukon = R.decide({key: (2, 1)}, None, None, sched, {}, fersk, nff={key: (2, 1)})
    check("ligasiden og fotball.no (samme leverandør): venter", key not in pub and len(vent) == 1)

    # Ligasiden nede: neste kilde er hovedkilde, og to leverandører må være enige.
    pub, conf, vent, ukon = R.decide(None, {key: (2, 1)}, None, sched, {}, gammel)
    check("ligasiden nede, OddsPapi alene, over et døgn: publiseres aldri",
          key not in pub and not conf and len(vent) == 1, f"{pub.get(key)} {conf} {vent}")
    pub, conf, vent, ukon = R.decide(None, {key: (2, 1)}, {key: (2, 1)}, sched, {}, fersk)
    check("ligasiden nede, OddsPapi og Wikipedia enige: publiseres med en gang",
          pub.get(key) == (2, 1) and not conf)
    pub, conf, vent, ukon = R.decide(None, {key: (2, 1)}, {key: (1, 1)}, sched, {}, gammel)
    check("ligasiden nede, OddsPapi og Wikipedia uenige: holdes tilbake og logges",
          key not in pub and len(conf) == 1, f"{pub.get(key)} {conf}")
    check("datasettet er fortsatt uendret etter alle testene",
          MATCHES.read_bytes() == before and len(json.loads(MATCHES.read_bytes())) == n_before)

    # 8. Genererte ligasider. obos/index.html bygges fra eliteserien/index.html,
    # og en rettelse i kilden når ikke ut før filen er bygget på nytt. Det har
    # gått galt før: hjelpefunksjoner havnet inne i regionen som byttes ut, og
    # OBOS-siden ble publisert uten dem.
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_league
    for liga in ("obos",):
        dest = ROOT / liga / "index.html"
        try:
            ventet = build_league.render(liga)
        except FileNotFoundError as e:
            check(f"{liga}/index.html: kildefilene finnes", False, f"mangler {e}")
            continue
        har = dest.read_text(encoding="utf-8") if dest.exists() else ""
        check(f"{liga}/index.html er bygget fra dagens eliteserien/index.html",
              har == ventet,
              f"kjør: python3 scripts/build_league.py {liga}"
              + (f" (filen er {len(har)} tegn, kilden gir {len(ventet)})" if har else " (filen mangler)"))
        check(f"{liga}/index.html er merket som generert",
              "GENERERT FIL -- IKKE REDIGER" in har[:1200], har[:80])

    # 9. Modellen og oddsen står stille når ingen kamper spilles.
    #   Tidsvektingen skal regnes fra siste spilte kamp, ikke fra dagens dato:
    #   ellers krymper lagforskjellene i hver pause uten at noe har skjedd.
    #   Og en lagret "sluttodds" må være hentet FØR avspark -- Brann mot
    #   Bodø/Glimt ble fanget opp 91 minutter etter avspark og trakk Glimts
    #   gullsjanse ned fem prosentpoeng.
    for liga in ("eliteserien", "obos"):
        mdl = json.loads((ROOT / liga / "data" / "model.json").read_text(encoding="utf-8"))
        kamper = json.loads((ROOT / liga / "data" / "matches.json").read_text(encoding="utf-8"))
        siste = max(k["date"] for k in kamper)
        ref = (mdl.get("meta") or {}).get("ref_date")
        check(f"{liga}: modellen er tilpasset med siste spilte kamp som referanse",
              ref == siste, f"ref_date={ref}, siste kamp {siste}")
    cap = json.loads((ROOT / "eliteserien" / "data" / "odds_captured.json").read_text(encoding="utf-8"))["matches"]
    etter = [f"{c['home']}-{c['away']}" for c in cap
             if c.get("fetched_at") and c.get("kickoff") and c["fetched_at"][:19] >= c["kickoff"][:19]]
    check("ingen lagret sluttodds er hentet etter avspark", not etter, ", ".join(etter))
    check("Brann mot Bodø/Glimt (hentet under kampen) er ikke lagret som sluttodds",
          not any(c["home"] == "Brann" and c["away"] == "Bodø/Glimt" for c in cap))

    # 10. Treffsikkerhetsloggen: bare kamper som BÅDE har en frosset
    #   sannsynlighet fra før avspark og et publisert resultat skal telles, og
    #   tallene skal mangle så lenge det ikke finnes kamper.
    import accuracy_log
    for liga in ("eliteserien", "obos"):
        acc_path = ROOT / liga / "data" / "accuracy.json"
        if not acc_path.exists():
            check(f"{liga}: accuracy.json finnes", False, "filen mangler")
            continue
        acc = json.loads(acc_path.read_text(encoding="utf-8"))
        pre = json.loads((ROOT / liga / "data" / "prekick.json").read_text(encoding="utf-8"))["matches"]
        spilte = {(m["home"], m["away"])
                  for m in json.loads((ROOT / liga / "data" / "matches.json").read_text(encoding="utf-8"))}
        ventet = sum(1 for e in pre.values()
                     if e.get("frosset") and (e.get("home"), e.get("away")) in spilte)
        check(f"{liga}: loggen teller bare frosne kamper med resultat",
              acc["n"] == ventet, f"filen sier {acc['n']}, fant {ventet}")
        tomme = [k for k, v in acc["kilder"].items()
                 if (v["n"] == 0) != (v["treff"] is None)]
        check(f"{liga}: ingen tall uten kamper bak seg", not tomme, ", ".join(tomme))
        # Hver kamp gir nøyaktig tre kalibreringspunkter for modellen.
        n_modell = acc["kilder"]["modell"]["n"]
        check(f"{liga}: kalibreringen dekker alle utfall",
              sum(b["n"] for b in acc["kalibrering"]) == 3 * n_modell,
              f"{sum(b['n'] for b in acc['kalibrering'])} mot {3 * n_modell}")
    # Sannsynlighetene normaliseres, også når kilden summerer til litt over 1.
    p3 = accuracy_log.probs_for({"H": 0.5, "U": 0.3, "B": 0.4}, "side")
    check("treffsikkerhet: sannsynlighetene normaliseres",
          abs(sum(p3.values()) - 1) < 1e-9 and abs(p3["H"] - 0.5 / 1.2) < 1e-9, str(p3))
    check("treffsikkerhet: kilde som mangler gir ingen rad",
          accuracy_log.probs_for({"H": 0.5, "U": 0.3, "B": 0.2}, "odds") is None)

    # 11. xG-data skal ALDRI ligge i repoet. Den er fra en privat kilde og skal
    #   bare brukes til å tilpasse modellen, utenfor repoet. Testen ser på
    #   INNHOLDET, ikke bare filnavnet: et nytt navn skal ikke slippe unna.
    xg_kol = ("home_xg", "away_xg", "xg_home", "xg_away", "expected_goals", "expectedgoals")
    funn = []
    for f in ROOT.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith(".git/") or "__pycache__" in rel or f.suffix not in (".csv", ".json", ".tsv", ".txt"):
            continue
        if rel.startswith("tests/") and "failsafe" in rel:
            continue      # denne filen nevner navnene for å lete etter dem
        try:
            hode = f.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
        except Exception:
            continue
        if any(k in hode for k in xg_kol):
            funn.append(rel)
    check("ingen xG-data i repoet", not funn, ", ".join(funn[:5]))
    # Og mønstrene i .gitignore skal fange de vanlige navnene.
    ignorert = subprocess.run(["git", "check-ignore", "eliteserien_xg.csv", "data/xg_2026.csv",
                               "obos/data/team-xg.csv", "eliteserien/data/xg/kamper.json"],
                              capture_output=True, text=True, cwd=ROOT)
    check("gitignore fanger xG-filnavn",
          len(ignorert.stdout.split()) == 4, ignorert.stdout.strip() or "ingen treff")

    # 12. Sluttoddsvinduet: siste observasjon 60 til 15 minutter før avspark.
    #   Reglene her er de som holder in-play-priser ute. 22. september kom en
    #   pris hentet 91 minutter ETTER avspark inn som "sluttodds" for Brann mot
    #   Bodø/Glimt og kostet Glimt 5,3 prosentpoeng på gullsjansen.
    import oddswindow
    KO = "2026-09-20T17:00:00Z"

    def payload(tider, bm="pinnacle"):
        """Ett OddsPapi-svar der alle tre utfall har pris på de gitte tidene."""
        utfall = {str(i): {"players": {"0": [{"price": 2.0 + i, "createdAt": t}
                                             for t in tider]}} for i in (1, 2, 3)}
        return {"data": {"bookmakers": {bm: {"markets": {"101": {"outcomes": utfall}}}}}}

    def kjor(tider, bm="pinnacle", bms=("pinnacle", "bet365")):
        return oddswindow.closing_from(payload(tider, bm), 101, KO, list(bms))

    bm, odds, stamp = kjor(["2026-09-20T16:30:00.000Z"])
    check("sluttodds: pris 30 min før avspark godtas", bm == "pinnacle" and odds is not None)
    check("sluttodds: for sen pris (10 min før) forkastes",
          kjor(["2026-09-20T16:50:00.000Z"])[0] is None)
    check("sluttodds: for tidlig pris (90 min før) forkastes",
          kjor(["2026-09-20T15:30:00.000Z"])[0] is None)
    check("sluttodds: pris ETTER avspark forkastes",
          kjor(["2026-09-20T18:31:00.000Z"])[0] is None)
    check("sluttodds: pris fra dagen før forkastes",
          kjor(["2026-09-19T16:30:00.000Z"])[0] is None)
    # Innenfor vinduet skal den SISTE prisen vinne, ikke den første.
    bm2, odds2, stamp2 = kjor(["2026-09-20T16:05:00.000Z", "2026-09-20T16:40:00.000Z"])
    check("sluttodds: siste pris i vinduet vinner", stamp2 == "2026-09-20T16:40:00.000Z", str(stamp2))
    # Grensene er med: nøyaktig 60 og nøyaktig 15 minutter før skal godtas.
    check("sluttodds: nøyaktig 60 min før er innenfor",
          kjor(["2026-09-20T16:00:00.000Z"])[0] == "pinnacle")
    check("sluttodds: nøyaktig 15 min før er innenfor",
          kjor(["2026-09-20T16:45:00.000Z"])[0] == "pinnacle")
    # Ett utfall uten pris i vinduet ødelegger hele kampen: to priser fra
    # vinduet og én fra i går er ikke en sluttodds.
    delvis = payload(["2026-09-20T16:30:00.000Z"])
    delvis["data"]["bookmakers"]["pinnacle"]["markets"]["101"]["outcomes"]["2"] = {
        "players": {"0": [{"price": 3.4, "createdAt": "2026-09-19T12:00:00.000Z"}]}}
    check("sluttodds: ett utfall utenfor vinduet forkaster hele kampen",
          oddswindow.closing_from(delvis, 101, KO, ["pinnacle"])[0] is None)
    # Rekkefølgen på bookmakerne: Pinnacle først, så bet365.
    bare_b365 = payload(["2026-09-20T16:30:00.000Z"], bm="bet365")
    check("sluttodds: faller ned på bet365 når Pinnacle mangler",
          oddswindow.closing_from(bare_b365, 101, KO, ["pinnacle", "bet365"])[0] == "bet365")
    check("sluttodds: ukjent avspark gir ingen sluttodds",
          oddswindow.closing_from(payload(["2026-09-20T16:30:00.000Z"]), 101, "", ["pinnacle"])[0] is None)

    # 13. En kamp uten sluttodds skal ALDRI bæres videre med en eldre pris.
    import merge_odds
    rader = merge_odds.load_window.__doc__ or ""
    check("merge: vindusfilen dokumenterer at tomme rader hoppes over",
          "eldre pris" in rader.lower() or "aldri" in rader.lower(), rader[:60])
    check("merge: OddsPapi-vinduet ligger over football-data",
          "odds_closing.json" in (merge_odds.__doc__ or "") and
          (merge_odds.__doc__ or "").index("odds_closing.json")
          < (merge_odds.__doc__ or "").index("odds_fd.json"))

    # 14. Besøksstatistikken: samme oppsett på alle tre sidene, og den skal
    #   aldri telle fra localhost -- ellers ville hver testkjøring sendt treff.
    sider = {navn: (ROOT / f).read_text(encoding="utf-8")
             for navn, f in (("forsiden", "index.html"),
                             ("eliteserien", "eliteserien/index.html"),
                             ("obos", "obos/index.html"))}
    for navn, tekst in sider.items():
        check(f"statistikk: {navn} sender til GoatCounter",
              "tabellkalkulator.goatcounter.com/count" in tekst)
        check(f"statistikk: {navn} teller bare på det publiserte domenet",
              "location.hostname !== 'tabellkalkulator.no'" in tekst)
    # Ligasidene bruker count.js; forsiden sender treffet selv, fordi den som
    # regel videresender før et async skript rekker å telle.
    for navn in ("eliteserien", "obos"):
        check(f"statistikk: {navn} laster count.js async",
              "gc.zgo.at/count.js" in sider[navn] and "s.async = true" in sider[navn])
    f0 = sider["forsiden"]
    check("statistikk: forsiden laster ikke count.js",
          "gc.zgo.at" not in f0)
    check("statistikk: forsiden bruker keepalive, så treffet overlever videresendingen",
          "keepalive:true" in f0.replace(" ", ""))
    check("statistikk: forsiden teller seg selv som /",
          "encodeURIComponent('/')" in f0)
    check("statistikk: forsiden sender henvisningen med",
          "document.referrer" in f0.split("location.replace")[0])
    # 15. Google Search Console-verifiseringen skal stå permanent. Fjernes den,
    #   mister nettstedet verifiseringen, og det skjer uten noe varsel.
    hode = sider["forsiden"]
    hode = hode[hode.index("<head>"):hode.index("</head>")]
    check("søk: forsiden har Search Console-verifiseringen i head",
          'name="google-site-verification"' in hode)
    check("søk: verifiseringskoden er uendret",
          'content="hKUGnlXBnP0c37c5KbXAR2N_sb2zTmH1zIjcYckB8h8"' in hode)

    check("statistikk: forsiden teller FØR den videresender",
          f0.index("goatcounter.com/count") < f0.index("location.replace('/eliteserien/'"))
    for navn in ("eliteserien", "obos"):
        # Uten path-funksjonen ville hver delte lenke (#s=...) blitt sin egen side.
        check(f"statistikk: {navn} teller stien, ikke scenarioet",
              "path: function()" in sider[navn] and "location.pathname" in sider[navn])
        # Forsiden videresender med location.replace, og da blir referrer
        # forsiden selv. Den ytre henvisningen må hentes fra det forsiden la unna.
        check(f"statistikk: {navn} beholder den ytre henvisningen",
              "referrer: function()" in sider[navn] and "tk:henvisning" in sider[navn])
    check("statistikk: forsiden legger unna henvisningen før den videresender",
          "sessionStorage.setItem('tk:henvisning'" in sider["forsiden"])
    # Rekkefølgen er det som avgjør: legges den unna ETTER location.replace,
    # rekker den aldri å bli lagret.
    f = sider["forsiden"]
    check("statistikk: henvisningen lagres før videresendingen",
          f.index("tk:henvisning") < f.index("location.replace('/eliteserien/'"))
    # Ingen informasjonskapsler, ingen samtykkebanner.
    for navn, tekst in sider.items():
        check(f"statistikk: {navn} setter ingen informasjonskapsel",
              "document.cookie" not in tekst)

    # 16. Innleggsforslagene er et LOKALT verktøy. Repoet er offentlig, så
    #   hverken tekstene, bildene eller hvilke lag som er brukt skal kunne
    #   havne der. Et .gitignore-mønster er hele vernet -- det testes.
    ignorert = subprocess.run(["git", "check-ignore",
                               "innlegg/index.html", "innlegg/tilstand.json",
                               "innlegg/eliteserien-for.png"],
                              capture_output=True, text=True, cwd=ROOT)
    check("innlegg: mappa er utenfor repoet",
          len(ignorert.stdout.split()) == 3, ignorert.stdout.strip() or "ingen treff")
    sporet = subprocess.run(["git", "ls-files", "innlegg"],
                            capture_output=True, text=True, cwd=ROOT)
    check("innlegg: ingenting er sporet", not sporet.stdout.strip(), sporet.stdout.strip())

    # 17. Kildevakten (hentelogg.py sjekk) gjor bare en jobb rod for kilder den
    #   jobben SELV har forsokt. "Oppdater kampdata" ble rod av OBOS-jobbens
    #   feil, som den aldri forsoker -- en alarm som alltid er rod, blir
    #   ignorert. Syntetiske loggfiler i en egen mappe; jobben leses av
    #   filnavnet, som i produksjonen.
    import tempfile
    from datetime import datetime, timedelta, timezone
    def logg_fil(mappe, jobb, rid, rader):
        naa = datetime.now(timezone.utc)
        f = Path(mappe) / f"{naa:%Y-%m}" / f"{naa:%Y-%m-%d}-{jobb}-{rid}-1.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            for i, (liga, kilde, utfall) in enumerate(rader):
                t = (naa - timedelta(minutes=60 - i)).isoformat(timespec="seconds")
                fh.write(json.dumps({"tid": t, "liga": liga, "kilde": kilde, "utfall": utfall}) + "\n")
    def sjekk_som(mappe, workflow, *ekstra):
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_WORKFLOW", "GITHUB_ACTIONS")}
        env["HENTELOGG_KATALOG"] = str(mappe)
        if workflow:
            env["GITHUB_WORKFLOW"] = workflow
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "hentelogg.py"), "sjekk", *ekstra],
                              capture_output=True, text=True, cwd=ROOT, env=env)
    with tempfile.TemporaryDirectory() as d:
        logg_fil(d, "Oppdater_kampdata", 100, [("eliteserien", "nff", "ok"), ("eliteserien", "espn", "ok")])
        # 17.10.2026: bare terminlisten (ntf-terminliste) gjør rødt; de andre
        # kildene gir en advarsel (hentelogg.RODE_KILDER).
        logg_fil(d, "OBOS:_hent_resultater", 200,
                 [("obos", "ntf-terminliste", "feil")] * 4 + [("obos", "ntf-resultater", "feil")] * 3
                 + [("alle", "oddspapi-historical-odds", "feil")] * 3)
        r = sjekk_som(d, "Oppdater kampdata")
        check("kildevakt: eliteseriejobben blir ikke rød av OBOS-jobbens feil",
              r.returncode == 0 and "ntf-terminliste" not in r.stderr, (r.stdout + r.stderr)[-200:])
        r = sjekk_som(d, "OBOS: hent resultater")
        check("kildevakt: OBOS-jobben blir rød av terminlisten, og resultatsiden og OddsPapi står som advarsel",
              r.returncode == 1 and "FEIL: obos/ntf-terminliste" in r.stderr and "ADVARSEL: obos/ntf-resultater" in r.stderr
              and "ADVARSEL: alle/oddspapi-historical-odds" in r.stderr, (r.stdout + r.stderr)[-400:])
        r = sjekk_som(d, None)
        check("kildevakt: lokalt, uten jobb, sjekkes alle jobber", r.returncode == 1, (r.stdout + r.stderr)[-200:])
        r = sjekk_som(d, "Oppdater kampdata", "--alle")
        check("kildevakt: --alle sjekker alle jobber også i Actions", r.returncode == 1, (r.stdout + r.stderr)[-200:])
    with tempfile.TemporaryDirectory() as d:
        logg_fil(d, "Oppdater_kampdata", 101, [("eliteserien", "ntf-terminliste", "feil")] * 3 + [("eliteserien", "nff", "feil")] * 3)
        logg_fil(d, "OBOS:_hent_resultater", 201, [("obos", "nff", "ok")])
        r = sjekk_som(d, "Oppdater kampdata")
        check("kildevakt: eliteseriejobben blir rød av sin egen terminliste, og fotball.no (reserve) står som advarsel",
              r.returncode == 1 and "FEIL: eliteserien/ntf-terminliste" in r.stderr and "ADVARSEL: eliteserien/nff" in r.stderr,
              (r.stdout + r.stderr)[-300:])
    with tempfile.TemporaryDirectory() as d:
        logg_fil(d, "Oppdater_kampdata", 102, [("eliteserien", "espn", "feil")] * 3 + [("eliteserien", "ntf-resultater", "feil")] * 3)
        r = sjekk_som(d, "Oppdater kampdata")
        check("kildevakt: bare kontroll- og resultatkilder ute (ESPN, ligasidens resultater): advarsel og exit 0",
              r.returncode == 0 and "ADVARSEL: eliteserien/espn" in r.stderr and "ADVARSEL: eliteserien/ntf-resultater" in r.stderr,
              (r.stdout + r.stderr)[-300:])
        r = sjekk_som(d, "OBOS: hent resultater")
        check("kildevakt: OBOS-jobben blir ikke rød av eliteseriejobbens feil",
              r.returncode == 0, (r.stdout + r.stderr)[-200:])

    # 18. OBOS-odds for kommende kamper: 404 "No historical odds found" for en
    #   kamp som ikke er spilt, betyr at markedet ikke er aapnet. Det skal
    #   logges som "hoppet", ikke "feil" -- ellers melder kildevakten
    #   oddspapi-historical-odds som ute hver gang neste runde er for langt
    #   unna. Andre feil logges som foer. Ingen nett: urlopen er byttet ut.
    import io
    import urllib.error
    import urllib.request
    import oddspapi as OP
    import hentelogg as HL
    def siste_utfall(kode, kropp, **kw):
        def falsk(*_a, **_k):
            raise urllib.error.HTTPError("https://x", kode, "feil", {}, io.BytesIO(kropp.encode()))
        gml = urllib.request.urlopen
        urllib.request.urlopen = falsk
        try:
            OP.call_retry("/v4/historical-odds", {"fixtureId": "t"}, "testnokkel", **kw)
        except TypeError as e:
            return f"TypeError: {e}"
        finally:
            urllib.request.urlopen = gml
        rader = [r for r in HL.les(1) if r.get("kilde") == "oddspapi-historical-odds"]
        return rader[-1]["utfall"] if rader else None
    ikke_funnet = '{"error":{"message":"No historical odds found.","code":"NOT_FOUND"}}'
    u = siste_utfall(404, ikke_funnet, ikke_funnet_er_hoppet=True)
    check("OBOS-odds: 404 'No historical odds found' for uspilt kamp logges som hoppet", u == "hoppet", str(u))
    u = siste_utfall(404, ikke_funnet)
    check("OBOS-odds: samme 404 uten flagget (andre kallere) logges fortsatt som feil", u == "feil", str(u))
    u = siste_utfall(404, '{"error":{"message":"Fixture not found."}}', ikke_funnet_er_hoppet=True)
    check("OBOS-odds: en annen 404 logges fortsatt som feil", u == "feil", str(u))
    u = siste_utfall(500, "Internal Server Error", ikke_funnet_er_hoppet=True)
    check("OBOS-odds: HTTP 500 logges fortsatt som feil", u == "feil", str(u))
    kilde = (ROOT / "scripts" / "obos_upcoming_odds.py").read_text(encoding="utf-8")
    check("OBOS-odds: obos_upcoming_odds.py bruker flagget, og bare for uspilte kamper",
          "ikke_funnet_er_hoppet=True" in kilde
          and 'kommende = [(r, f) for r, f in links if (r["home"], r["away"]) not in played' in kilde)

    # 19. NTF: en rad med ugyldig dato skal ikke stoppe hele hentingen naar
    #   kampen alt har resultat i matches.json. NTF viste "Invalid date." for
    #   Kongsvinger - Hødd (spilt 20.9.2026, 5-1), og OBOS-resultatene stoppet
    #   hver dag. Uten resultat -- og alltid paa terminlisten -- skal en
    #   ugyldig dato fortsatt stoppe. Syntetiske rader i NTF-markupen; ingen nett.
    import ntf_source as NTF
    def ntf_rad(h, b, dato_html, res="5 - 1", klasse="schedule__match schedule__match--played", runde="#23"):
        return (f'<tr class="{klasse}"><td class="schedule__match__item--round">{runde}</td>'
                f'<td class="schedule__match__item--teams">{h} - <span class="schedule__match__item--opponent">{b}</span></td>'
                f'<td class="schedule__match__item--result">{res}</td>'
                f'<td class="schedule__match__item--date">{dato_html} <span class="schedule__time">17:00</span></td></tr>')
    ugyldig = 'Invalid date.<span class="schedule__match__item--date__year">Invalid date</span>'
    gyldig = '20.09.<span class="schedule__match__item--date__year">2026</span>'
    side = ntf_rad("Kongsvinger", "Hødd", ugyldig) + ntf_rad("Lyn", "Moss", gyldig, res="2 - 0")
    hoppet = []
    try:
        rader = NTF.parse_side(side, "resultater", "obos", har_resultat=lambda h, b: (h, b) == ("Kongsvinger", "Hødd"),
                               hoppet=hoppet)
        check("NTF: ugyldig dato for kamp MED resultat hoppes over, resten tolkes",
              [(r["home"], r["away"]) for r in rader] == [("Lyn", "Moss")] and hoppet == ["Kongsvinger - Hødd"],
              f"{rader}, hoppet {hoppet}")
    except Exception as e:
        check("NTF: ugyldig dato for kamp MED resultat hoppes over, resten tolkes", False, f"{type(e).__name__}: {e}")
    for navn, kw in (("uten resultat", {"har_resultat": lambda h, b: False}),
                     ("uten oppslag (terminlisten)", {})):
        try:
            NTF.parse_side(side, "resultater", "obos", **kw)
            check(f"NTF: ugyldig dato {navn} stopper fortsatt hentingen", False, "ingen feil ble kastet")
        except NTF.EsDataError as e:
            check(f"NTF: ugyldig dato {navn} stopper fortsatt hentingen", "manglende dato" in str(e), str(e))
        except TypeError as e:
            check(f"NTF: ugyldig dato {navn} stopper fortsatt hentingen", False, f"TypeError: {e}")
    # Hele fetch_all, med sidene fra en lokal mappe og en egen matches.json der
    # Kongsvinger - Hødd har resultat (ikke repoets, som endres hele sesongen
    # og er tom ved neste sesongstart).
    # Hentelogget får en egen, tom katalog her. Test 2 (obos_results.py
    # --break-wikipedia) logger også obos/ntf-resultater, i sin egen fil og
    # ofte i samme sekund som hentingen under. Tidsstempelet har hele sekunder,
    # og ved likt sekund sorterer les() på filnavnet, så "siste linje" kunne
    # være subprosessens (184 kamper, ingen melding), og testen feilet av og til.
    import tempfile as _tf
    import hentelogg as HL2
    gml_katalog = HL2.KATALOG
    gml_rot19 = NTF.ROT
    with _tf.TemporaryDirectory() as d:
        HL2.KATALOG = Path(d) / "hentelogg"
        NTF.ROT = Path(d)
        Path(d, "obos", "data").mkdir(parents=True)
        Path(d, "obos", "data", "matches.json").write_text(json.dumps(
            [{"date": "2026-09-20", "time": "15:00", "round": 21, "home": "Kongsvinger", "away": "Hødd", "hg": 5, "ag": 1}]),
            encoding="utf-8")
        Path(d, "obos_resultater.html").write_text(side, encoding="utf-8")
        Path(d, "obos_terminliste.html").write_text(
            ntf_rad("Ranheim", "Egersund", '02.10.<span class="schedule__match__item--date__year">2026</span>',
                    res="", klasse="schedule__match schedule__match--upcoming", runde="#24"), encoding="utf-8")
        try:
            alle = NTF.fetch_all("obos", cache_dir=d)
            par = {(r["home"], r["away"]) for r in alle}
            siste = [r for r in HL2.les(1) if r.get("liga") == "obos" and r.get("kilde") == "ntf-resultater"][-1]
            check("NTF: fetch_all fortsetter forbi raden, og hentelogget sier ok og nevner kampen",
                  ("Lyn", "Moss") in par and ("Ranheim", "Egersund") in par and ("Kongsvinger", "Hødd") not in par
                  and siste["utfall"] == "ok" and "Kongsvinger - Hødd" in siste.get("melding", ""),
                  f"{sorted(par)}, logg {siste}")
        except Exception as e:
            check("NTF: fetch_all fortsetter forbi raden, og hentelogget sier ok og nevner kampen", False,
                  f"{type(e).__name__}: {e}")
        Path(d, "obos_terminliste.html").write_text(
            ntf_rad("Ranheim", "Egersund", ugyldig, res="", klasse="schedule__match schedule__match--upcoming",
                    runde="#24"), encoding="utf-8")
        try:
            NTF.fetch_all("obos", cache_dir=d)
            check("NTF: ugyldig dato på terminlisten stopper fortsatt fetch_all", False, "ingen feil ble kastet")
        except NTF.EsDataError as e:
            check("NTF: ugyldig dato på terminlisten stopper fortsatt fetch_all", "manglende dato" in str(e), str(e))
    HL2.KATALOG = gml_katalog
    NTF.ROT = gml_rot19

    # 20. Tidsporten for The Odds API (update-odds.yml via planleggeren hvert
    # tiende minutt). Porten avgjør, uten filer: én vellykket henting per
    # døgn (norsk tid); oddsen rett før avspark kommer fra prekick-odds.yml. Én
    # time sperre etter et mislykket forsøk; budsjettvakt (under 100 + 4 per
    # gjenstående dag i måneden: bare annenhver dag); ingen henting uten kamp
    # innen 7 dager eller med stanset kvote; FORCE tvinger. Falsk klokke.
    import should_fetch_odds as SFO
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    naa = _dt(2026, 10, 7, 12, 0, tzinfo=_tz.utc)          # 7.10 kl. 14 norsk tid, midt i måneden
    def fx(*kamper):   # (dato, spilt[, klokkeslett]) -> fixtures.json-form
        return [{"round": 23, "matches": [{"home": f"H{i}", "away": f"B{i}", "date": k[0],
                                           "time": k[2] if len(k) > 2 else "19:00", "played": k[1]}
                                          for i, k in enumerate(kamper)]}]
    def kvote(tid, igjen=400):
        return {"remaining": igjen, "checked_at": tid.isoformat()}
    def v(fix, q, st=None, force=False, n=naa):
        return SFO.vurder(n, fix, q, st, force=force)[0]
    uke = fx(("2026-10-09", False))
    i_dag_morgen = _dt(2026, 10, 7, 7, 5, tzinfo=_tz.utc)     # 09:05 norsk tid i dag
    i_gar_kveld = _dt(2026, 10, 6, 21, 50, tzinfo=_tz.utc)    # 23:50 norsk tid i går
    sent_i_gar_utc = _dt(2026, 10, 6, 22, 30, tzinfo=_tz.utc) # 00:30 norsk tid I DAG (22:30 UTC i går)
    check("odds-port: hentet i dag (norsk tid) -> ingen ny henting samme døgn", v(uke, kvote(i_dag_morgen)) is False)
    check("odds-port: siste henting i går -> hent i dag", v(uke, kvote(i_gar_kveld)) is True)
    check("odds-port: døgnet er norsk tid: 22:30 UTC i går er i dag i Norge -> ingen ny henting",
          v(uke, kvote(sent_i_gar_utc)) is False)
    check("odds-port: ny dag (00:10 norsk tid) etter henting 23:50 i går -> hent",
          v(uke, kvote(i_gar_kveld), n=_dt(2026, 10, 6, 22, 10, tzinfo=_tz.utc)) is True)
    # sperre: forsøk for 30 min siden, nyere enn siste vellykkede -> vent; 70 min -> hent
    st30 = {"siste_forsok": (naa - _td(minutes=30)).isoformat()}
    st70 = {"siste_forsok": (naa - _td(minutes=70)).isoformat()}
    check("odds-port: mislykket forsøk for 30 min siden -> sperre; for 70 min siden -> hent",
          v(uke, kvote(i_gar_kveld), st30) is False and v(uke, kvote(i_gar_kveld), st70) is True)
    check("odds-port: et forsøk som GIKK BRA (eldre enn siste henting) gir ingen sperre",
          v(uke, kvote(i_gar_kveld), {"siste_forsok": (i_gar_kveld - _td(minutes=1)).isoformat()}) is True)
    # budsjettvakt: 7.10, 25 dager igjen -> krav 100 + 4*25 = 200
    check("odds-port: budsjettvakten: 190 kreditter igjen, hentet i går -> vent (annenhver dag)",
          v(uke, kvote(i_gar_kveld, igjen=190)) is False)
    check("odds-port: budsjettvakten: 190 kreditter igjen, hentet i forgårs -> hent",
          v(uke, kvote(i_gar_kveld - _td(days=1), igjen=190)) is True)
    check("odds-port: budsjettvakten slår ikke til med nok kreditter (210 igjen, hentet i går -> hent)",
          v(uke, kvote(i_gar_kveld, igjen=210)) is True)
    check("odds-port: lavt tall fra FORRIGE måned teller ikke i budsjettvakten",
          v(fx(("2026-10-03", False)), kvote(_dt(2026, 9, 30, 20, 0, tzinfo=_tz.utc), igjen=120),
            n=_dt(2026, 10, 1, 10, 0, tzinfo=_tz.utc)) is True)
    check("odds-port: ingen uspilt kamp innen 7 dager -> ingen henting",
          v(fx(("2026-10-20", False)), kvote(i_gar_kveld)) is False and v(fx(("2026-10-08", True)), kvote(i_gar_kveld)) is False)
    check("odds-port: stanset kvote denne måneden -> ingen henting",
          v(uke, {"remaining": 90, "checked_at": i_gar_kveld.isoformat(), "stopped_until_month": "2026-10"}) is False)
    check("odds-port: FORCE tvinger henting, også samme døgn og under sperren",
          v(uke, kvote(i_dag_morgen), st30, force=True) is True)
    check("odds-port: ingen tidligere henting -> hent", v(uke, None) is True)
    # Ingen ekstra henting på kampdagen: oddsen rett før avspark kommer fra
    # prekick-odds.yml. En kamp 40 minutter unna gir ingen ny henting når det
    # er hentet i dag.
    kampdag = fx(("2026-10-07", False, "17:00"), ("2026-10-07", False, "19:00"))
    check("odds-port: kamp om 40 minutter, hentet i morges -> ingen ny henting (prekick-odds.yml dekker det)",
          v(kampdag, kvote(i_dag_morgen), n=_dt(2026, 10, 7, 14, 20, tzinfo=_tz.utc)) is False)
    wf = (ROOT / ".github" / "workflows" / "update-odds.yml").read_text(encoding="utf-8")
    steg = wf.split("\n      - ")
    i_port = next((i for i, x in enumerate(steg) if "should_fetch_odds.py" in x), -1)
    i_ark = next((i for i, x in enumerate(steg) if "arkiver_til_lab.sh for-henting" in x), -1)
    check("update-odds.yml: porten står foran arkiveringen, som bare kjøres når porten er åpen",
          0 <= i_port < i_ark and "if: steps.gate.outputs.should_fetch == 'true'" in steg[i_ark], f"port {i_port}, arkiv {i_ark}")
    check("update-odds.yml: siste forsøk (odds_hentestatus.json) committes, også når hentingen feiler",
          "git add eliteserien/data/odds_hentestatus.json" in wf)
    check("update-odds.yml deler køgruppe med update-data.yml (begge skriver model.json)",
          "group: update-data" in wf and "group: update-data" in (ROOT / ".github" / "workflows" / "update-data.yml").read_text(encoding="utf-8"))

    # 21. Prognosen før avspark (prekick.json) med sluttoddsen. «Odds nær
    # avspark» regner raden i vinduet på nytt HVER gang porten er åpen, ikke
    # bare når det kom nye priser (prognosen er 30 prosent modell, og nye
    # lagstyrker etter en tidligere kamp samme dag skal med). Datajobbene lar
    # vinduet være, så to jobber aldri skriver samme rad. Hentingen av oddsen
    # er uendret og kommer først; en feil i prognosesteget stopper den aldri.
    # Selve regelen og en kjøring med nye lagstyrker testes i regression.js.
    wfd = ROOT / ".github" / "workflows"
    pk = (wfd / "prekick-odds.yml").read_text(encoding="utf-8")
    inputs = pk.split("workflow_dispatch:", 1)[1].split("\npermissions:", 1)[0]
    # Valget sitt eget innrykk (8 mellomrom) til neste valg.
    sim = inputs.split("      simuler_tid:\n", 1)[1] if "      simuler_tid:\n" in inputs else ""
    sim = "\n".join(l for l in sim.splitlines()[:4] if l.startswith("        "))
    check("prekick-odds.yml: simuler_tid er et valg under workflow_dispatch.inputs (tekst), ved siden av dry_run",
          "        type: string" in sim.splitlines() and "      dry_run:\n" in inputs, sim)
    # Stegene uten kommentarlinjer (en kommentar foran et steg havner ellers
    # i steget over).
    pst = ["\n".join(l for l in x.splitlines() if not l.lstrip().startswith("#")) for x in pk.split("\n      - ")]
    finn = lambda tekst: next((i for i, x in enumerate(pst) if tekst in x), -1)
    i_port, i_hent, i_lagre = finn("prekick_vindu.py"), finn("prekick_odds.py"), finn("Lagre hvis noe endret seg")
    i_node, i_pp, i_prog = finn("actions/setup-node"), finn("Installer puppeteer-core"), finn("--bare-prekick")
    check("prekick-odds.yml: porten, hentingen og lagringen av oddsen kommer først, prognosesteget etter",
          0 <= i_port < i_hent < i_lagre < i_node < i_pp < i_prog, f"{i_port} {i_hent} {i_lagre} {i_node} {i_pp} {i_prog}")
    check("prekick-odds.yml: hentingen av oddsen har samme betingelse som før (bare porten)",
          i_hent > 0 and "if: steps.gate.outputs.should_fetch == 'true'\n" in pst[i_hent], pst[i_hent][:120] if i_hent > 0 else "")
    check("prekick-odds.yml: porten skriver tidspunktet for hentingen (naa) før den vurderer vinduet",
          i_port >= 0 and 'echo "naa=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$GITHUB_OUTPUT"\n          python3 scripts/prekick_vindu.py' in pst[i_port])
    prog = pst[i_prog] if i_prog >= 0 else ""
    betingelse = "if: ${{ always() && steps.gate.outputs.should_fetch == 'true' }}\n"
    check("prekick-odds.yml: prognosen regnes hver gang porten er åpen, ikke bare når det kom nye priser",
          min(i_node, i_pp, i_prog) >= 0 and all(betingelse in pst[i] for i in (i_node, i_pp, i_prog))
          and "git diff" not in prog.split("for forsok", 1)[0]
          and "steps.hent" not in prog and "outputs.endret" not in prog)
    check("prekick-odds.yml: prognosesteget kan aldri stoppe oddsen (continue-on-error, etter lagringen)",
          "continue-on-error: true" in prog and i_lagre < i_prog)
    check("prekick-odds.yml: begge ligaer, bare vinduet, med tidspunktet fra porten",
          'for liga in eliteserien obos; do' in prog and 'node scripts/snapshot_probs.js "$liga" --bare-prekick --oddstid "$ODDSTID" ||' in prog
          and "ODDSTID: ${{ steps.gate.outputs.naa }}" in prog)
    check("prekick-odds.yml: bare de to prekick.json committes, og en avvist push regnes på nytt oppå main, høyst tre ganger",
          "git add eliteserien/data/prekick.json obos/data/prekick.json\n" in prog and "for forsok in 1 2 3; do" in prog
          and "git reset -q --hard HEAD~1" in prog and 'git push -q origin "HEAD:$GREN"' in prog)
    torr = prog.split('if [ "${{ inputs.dry_run }}" = "true" ]; then', 1)[1].split("exit 0", 1)[0] if "inputs.dry_run" in prog else ""
    check("prekick-odds.yml: tørrkjøringen skriver ingenting, og den falske klokka virker bare der",
          "--dry-run" in torr and "git " not in torr and "FALSK_KLOKKE: ${{ inputs.dry_run && inputs.simuler_tid || '' }}" in prog
          and 'export NODE_OPTIONS="--require ./tests/falsk_klokke.js"' in torr and prog.count("NODE_OPTIONS") == 1)
    check("prekick-odds.yml: lagringen av oddsen tar ikke med prekick.json",
          i_lagre > 0 and "prekick.json" not in pst[i_lagre])
    check("prekick-odds.yml: en tørrkjøring sjekker ut grenen den startes fra, ellers main",
          "ref: ${{ inputs.dry_run && github.ref_name || 'main' }}" in pk)
    for navn, kall in (("update-data.yml", "node scripts/snapshot_probs.js --uten-prekick-vindu\n"),
                       ("obos-results.yml", "node scripts/snapshot_probs.js obos --uten-prekick-vindu\n")):
        t = (wfd / navn).read_text(encoding="utf-8")
        check(f"{navn}: snapshot-steget lar raden i vinduet være (--uten-prekick-vindu)",
              kall in t and t.count("snapshot_probs.js") == t.count("--uten-prekick-vindu") + t.count("se scripts/snapshot_probs.js")
              and "--bare-prekick" not in t)
    elo = (wfd / "elo-test.yml").read_text(encoding="utf-8")
    # 17.10.2026: ELO-testsiden er løs, og panelene (også prekick.json) regnes
    # ikke lenger. Ingen workflow skriver testsidens prekick.json.
    check("elo-test.yml: panelene regnes ikke lenger (ingen snapshot_probs), og ingen workflow skriver til elo-test/emodell med snapshot_probs",
          "snapshot_probs" not in "\n".join(l for l in elo.splitlines() if not l.strip().startswith("#"))
          and not any("--ut elo-test/emodell" in f.read_text(encoding="utf-8") for f in wfd.glob("*.yml")))

    # 22. Grunnlagsfilen (del 2, steg 2): porten slipper gjennom bare når det
    # siden regner med er endret, og workflowen kan ikke stoppe datajobbene.
    import shutil as _sh
    import tempfile as _tf
    sys.path.insert(0, str(ROOT / "scripts"))
    import grunnlag_port as _gp
    # Datafilene fra det frosne bildet (tests/data/README.md), ikke dagens:
    # testene endrer første odds og første gjenstående kamp, og dagens filer
    # er tomme når det ikke er odds ute, ved sesongslutt og ved sesongstart.
    BILDE22 = ROOT / "tests" / "data" / "2026-10-01"
    with _tf.TemporaryDirectory() as _t:
        rot = Path(_t)
        (rot / "scripts").mkdir()
        _sh.copy(ROOT / "scripts" / "lag_grunnlag.js", rot / "scripts")
        (rot / "eliteserien" / "data").mkdir(parents=True)
        _sh.copy(ROOT / "eliteserien" / "index.html", rot / "eliteserien")
        for f in ("model.json", "matches.json", "fixtures.json", "odds_upcoming.json"):
            _sh.copy(BILDE22 / "eliteserien" / "data" / f, rot / "eliteserien" / "data")
        d = rot / "eliteserien" / "data"
        les = lambda f: json.loads((d / f).read_text(encoding="utf-8"))
        skriv = lambda f, x: (d / f).write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
        v = lambda **k: _gp.vurder("eliteserien", root=rot, **k)
        check("grunnlag-port: ingen fil -> regn", v()[0] is True and "finnes ikke" in v()[2])
        (d / "grunnlag.json").write_text(json.dumps({"inndata": v()[1]}), encoding="utf-8")
        check("grunnlag-port: filen er regnet av dagens inndata -> hopp over", v()[0] is False)
        check("grunnlag-port: tving -> regn", v(tving=True)[0] is True)

        def prov(navn, f, endre, regn):
            gml = (d / f).read_text(encoding="utf-8")
            x = les(f)
            endre(x)
            skriv(f, x)
            check(f"grunnlag-port: {navn} -> {'regn' if regn else 'hopp over'}", v()[0] is regn)
            (d / f).write_text(gml, encoding="utf-8")

        prov("fitted_at og meta i model.json endret", "model.json",
             lambda m: m.update(fitted_at="2099-01-01T00:00:00+00:00", meta={"note": "annen"}), False)
        prov("en lagstyrke i model.json endret", "model.json", lambda m: m["att"].__setitem__(0, m["att"][0] + 1e-9), True)
        prov("fetched_at og bookmaker/priced_at i odds_upcoming.json endret", "odds_upcoming.json",
             lambda o: (o.update(fetched_at="2099-01-01T00:00:00+00:00"),
                        [r.update(bookmaker="annen", priced_at="2099") for r in o["matches"]]), False)
        prov("en oddspris endret", "odds_upcoming.json", lambda o: o["matches"][0].update(H=o["matches"][0]["H"] + 0.0001), True)
        prov("et resultat i matches.json endret", "matches.json", lambda m: m[0].update(hg=m[0]["hg"] + 1), True)
        prov("terminlisten endret", "fixtures.json", lambda f: f[0]["matches"][0].update(time="23:59"), True)
        _sh.copy(BILDE22 / "eliteserien" / "data" / "justeringer.json", d)
        (d / "grunnlag.json").write_text(json.dumps({"inndata": v()[1]}), encoding="utf-8")
        prov("en poengjustering lagt til i justeringer.json", "justeringer.json",
             lambda j: j["justeringer"].append({"sesong": 2026, "lag": "Brann", "poeng": -1, "dato": "2026-03-04"}), True)
        prov("bare noten i justeringer.json endret", "justeringer.json", lambda j: j.update(note="annen"), False)
        for navn, fil in (("siden (index.html)", rot / "eliteserien" / "index.html"), ("skriptet (lag_grunnlag.js)", rot / "scripts" / "lag_grunnlag.js")):
            gml = fil.read_text(encoding="utf-8")
            fil.write_text(gml + "\n<!-- endret -->\n", encoding="utf-8")
            check(f"grunnlag-port: {navn} endret -> regn", v()[0] is True)
            fil.write_text(gml, encoding="utf-8")
        check("grunnlag-port: alt tilbake -> hopp over", v()[0] is False)
        (d / "grunnlag.json").write_text("{ødelagt", encoding="utf-8")
        check("grunnlag-port: filen kan ikke leses -> regn", v()[0] is True)
    # Testsiden: egen side og ELO-modell, kampdata og odds fra Eliteserien,
    # filen i elo-test/emodell.
    with _tf.TemporaryDirectory() as _t:
        rot = Path(_t)
        (rot / "scripts").mkdir()
        _sh.copy(ROOT / "scripts" / "lag_grunnlag.js", rot / "scripts")
        (rot / "elo-test" / "emodell").mkdir(parents=True)
        (rot / "eliteserien" / "data").mkdir(parents=True)
        _sh.copy(ROOT / "elo-test" / "index.html", rot / "elo-test")
        _sh.copy(BILDE22 / "elo-test" / "emodell" / "model.json", rot / "elo-test" / "emodell")
        for f in ("matches.json", "fixtures.json", "odds_upcoming.json"):
            _sh.copy(BILDE22 / "eliteserien" / "data" / f, rot / "eliteserien" / "data")
        v = lambda: _gp.vurder("elo-test", root=rot)
        (rot / "elo-test" / "emodell" / "grunnlag.json").write_text(json.dumps({"inndata": v()[1]}), encoding="utf-8")
        check("grunnlag-port, testsiden: filen i elo-test/emodell er regnet av dagens inndata -> hopp over", v()[0] is False)
        em = rot / "elo-test" / "emodell" / "model.json"
        gml = em.read_text(encoding="utf-8")
        m = json.loads(gml); m.update(built="2099-01-01T00:00:00+00:00", note="annen")
        em.write_text(json.dumps(m), encoding="utf-8")
        check("grunnlag-port, testsiden: built og note i ELO-modellen endret -> hopp over", v()[0] is False)
        m["hjemmefordel_rating"] = m["hjemmefordel_rating"] + 1e-9
        em.write_text(json.dumps(m), encoding="utf-8")
        check("grunnlag-port, testsiden: ELO-modellen endret -> regn", v()[0] is True)
        em.write_text(gml, encoding="utf-8")
        ek = rot / "eliteserien" / "data" / "matches.json"
        gml = ek.read_text(encoding="utf-8"); mm = json.loads(gml); mm[0]["hg"] += 1
        ek.write_text(json.dumps(mm), encoding="utf-8")
        check("grunnlag-port, testsiden: et resultat i eliteserien/data endret -> regn", v()[0] is True)
        ek.write_text(gml, encoding="utf-8")
        check("grunnlag-port, testsiden: alt tilbake -> hopp over", v()[0] is False)
    ut_ = subprocess.run([sys.executable, str(ROOT / "scripts" / "grunnlag_port.py"), "elo-test"], capture_output=True, text=True).stdout
    check("grunnlag-port: med én side skrives mappen filen ligger i (ut=elo-test/emodell)", "\nut=elo-test/emodell" in "\n" + ut_, ut_)

    # Porten tar med de datafilene siden faktisk regner med (boot()).
    side = (ROOT / "eliteserien" / "index.html").read_text(encoding="utf-8")
    check("grunnlag-port: filene er de siden laster i boot() (matches, fixtures, model, odds_upcoming)",
          # hentSporet/hentFersk (3.10.2026): samme filer, hentet uten gammel kopi.
          all(any(f"{h}('data/{f}')" in side for h in ("hentSporet", "hentFersk"))
              for f in ("matches.json", "fixtures.json", "model.json", "odds_upcoming.json")))
    for s_ in ("eliteserien", "obos"):
        t = (ROOT / s_ / "index.html").read_text(encoding="utf-8")
        check(f"{s_}/index.html: fast N = 100 000 i grunnlagsfilen (GRUNNLAG_N), versjon 3 (låst utfall i oppgavene, 16.10.2026)", "const GRUNNLAG_VERSJON = 3, GRUNNLAG_N = 100000;" in t)
    # Innsiktssvarene ("Hvorfor har ...?", "Hva må ... gjøre?", "Når kan det
    # være avgjort?", "Hvem kjemper ... mot?") kommer fra én kjøring for alle
    # lag og soner: filens blokk når den gjelder, ellers siden selv med like
    # mange sesonger som tabellen. Den gamle kjøringen per spørsmål (1 500
    # sesonger, eget frø per lag og sone) finnes ikke lenger på noen av sidene.
    for s_ in ("eliteserien", "obos", "elo-test"):
        t = (ROOT / s_ / "index.html").read_text(encoding="utf-8")
        check(f"{s_}/index.html: innsiktssvarene fra runInsightsAlle, uten den gamle kjøringen per spørsmål",
              "function runInsightsAlle(d){" in t and "d.mode==='insightsAlle'){ runInsightsAlle(d); }" in t
              and not any(x in t for x in ("function runInsights(", "runInsightsAsync", "QA_N_INSIGHTS", "mode:'insights'", "qaPointCurve")))
        check(f"{s_}/index.html: uten filen regnes innsikten med MC_N (samme antall som tabellen) og tabellens frø for scenarioet",
              "const payload = innsiktPayload(MC_N), nokkel = JSON.stringify(payload);" in t
              and "seed:hashStr(scenarioKey+'|impact'), zones:innsiktSoner(), checkpoints:buildCheckpoints(open)};" in t)
        check(f"{s_}/index.html: filen svarer også for en annen sone enn lagets egen (ingen qaWhyZoneOverride i grunnlagSvar)",
              "if(!GRUNNLAG || gruppe.startsWith('grunnlag') || payload.seed!==GRUNNLAG.seed || !grunnlagTomtScenario()) return null;" in t
              and "if(GRUNNLAG && grunnlagTomtScenario()){" in t and "return Promise.resolve(GRUNNLAG.innsikt);" in t)
        # Med egne resultater regnes innsikten i bakgrunnen når tabellen er
        # ferdig (og poolen ledig), i sin egen Worker, og en regning for et
        # scenario som ikke gjelder lenger, stoppes når et nytt starter.
        check(f"{s_}/index.html: innsikten i egen Worker, startet når tabellen er ferdig, og stoppet ved nytt scenario",
              "getInnsiktWorker().postMessage({...payload, mode:'insightsAlle', runId});" in t
              and "const kart = data.mode==='typical' ? typicalResolvers : null;" in t
              and "fillOdds();\n      if(lastMCFinal) innsiktForhand();" in t
              and "if(scenarioKey===lastMCScenarioKey && lastMC) return;\n  innsiktAvbryt(scenarioKey);" in t
              and "poolLedig(()=>{ if(qaScenarioKey()===scen && lastMCFinal && lastMCScenarioKey===scen) innsiktData(); });" in t)
        # Kvalikavsnittet i "Hva må ... gjøre?": fra 15 % direkte nedrykk, med
        # grensen for 14. plass fra en egen sone i blokken (14. plass eller bedre).
        check(f"{s_}/index.html: kvalikavsnittet fra 15 % direkte nedrykk, med egen sone for 14. plass i innsiktsblokken",
              "const QA_KVALIK_DIREKTE = 0.15;" in t and "if(direkte<QA_KVALIK_DIREKTE || minstKvalik<0.01) return '';" in t
              and "if(ned) soner.push({key:'direkte', lo:ned.lo, hi:ned.hi, boundary:ned.lo-1, dir:'back'});" in t
              and "if(T13!=null && T14!=null && T14>myPts && T13-T14>=2)" in t)
        check(f"{s_}/index.html: med minst fire kjerner starter innsikten samtidig med tabellen, ellers etter",
              "const INNSIKT_SAMTIDIG_KJERNER = 4;" in t
              and "N\n  });\n  // Med minst INNSIKT_SAMTIDIG_KJERNER kjerner starter innsikten samtidig med\n  // tabellen, ellers når tabellen er ferdig (innsiktForhand).\n  if(scenarioKey!=='' && (navigator.hardwareConcurrency||0) >= INNSIKT_SAMTIDIG_KJERNER) innsiktData();\n}" in t)
        check(f"{s_}/index.html: sonene og rundekontrollpunktene i innsiktsblokken er med i fingeravtrykket",
              "innsikt:{soner:innsiktSoner(), kontrollpunkter:buildCheckpoints(q.open)}," in t)
    lg_ = (ROOT / "scripts" / "lag_grunnlag.js").read_text(encoding="utf-8")
    check("lag_grunnlag.js: innsiktsblokken sjekkes mot tabellen før filen skrives",
          lg_.index("const fi = sjekkInnsikt(r);") < lg_.index("fs.writeFileSync(tmp, tekst);")
          and "tabellen gir ${tabell}" in lg_)
    gw = (wfd / "grunnlag.yml").read_text(encoding="utf-8")
    navn_wf = {}
    for f in wfd.glob("*.yml"):
        for l in f.read_text(encoding="utf-8").splitlines():
            if l.startswith("name:"):
                navn_wf[l.split(":", 1)[1].strip().strip('"')] = f.name
                break
    utlosere = gw.split("workflows:", 1)[1].split("types:", 1)[0]
    utlosere = [l.strip()[2:].strip().strip('"') for l in utlosere.splitlines() if l.strip().startswith("- ")]
    # 17.10.2026: ELO-testsiden er løs, og testsidens grunnlagsfil regnes ikke
    # lenger. ELO-byggingen utløser ikke grunnlag.yml.
    check("grunnlag.yml: utløses etter datajobbene, oddsjobbene og byggingen av ligasidene (ikke ELO-modellen), med navn som finnes",
          sorted(navn_wf.get(n, "?") for n in utlosere) == ["build-leagues.yml", "obos-results.yml", "prekick-odds.yml", "update-data.yml", "update-odds.yml"],
          str(utlosere))
    check("grunnlag.yml: bare de to ligaene, aldri testsiden",
          'sider="eliteserien obos"' in gw and "python3 scripts/grunnlag_port.py $sider" in gw
          and 'sider="elo-test"' not in gw and "eliteserien obos elo-test" not in gw)
    check("grunnlag.yml: bare kjøringer på main utløser den, og push av sidene og skriptene",
          "types: [completed]\n    branches: [main]\n" in gw and all(f"      - {p_}\n" in gw for p_ in
          ("eliteserien/index.html", "obos/index.html", "scripts/lag_grunnlag.js", "scripts/grunnlag_port.py",
           "eliteserien/data/justeringer.json", "obos/data/justeringer.json")))
    gst = ["\n".join(l for l in x.splitlines() if not l.lstrip().startswith("#")) for x in gw.split("\n      - ")]
    gi = lambda tekst: next((i for i, x in enumerate(gst) if tekst in x), -1)
    i_p2, i_nd, i_rg, i_lg = gi("Fortsatt endret?"), gi("actions/setup-node"), gi("lag_grunnlag.js \"${{ matrix.liga }}\""), gi("name: Lagre")
    check("grunnlag.yml: porten sjekkes på nytt i regnejobben før Chrome, så regnes og lagres det",
          0 < i_p2 < i_nd < i_rg < i_lg and "concurrency:\n      group: grunnlag-${{ matrix.liga }}\n      cancel-in-progress: false" in gw
          and "if: needs.port.outputs.ligaer != '[]'" in gw, f"{i_p2} {i_nd} {i_rg} {i_lg}")
    i_ls = gi("lag_sider.py")
    check("grunnlag.yml: fast N (ingen --n), filen der porten sier, sidene lages fra tekster.json (lag_sider.py, kan ikke stoppe lagringen), og bare grunnlagsfilen, banneret, tekster.json, ligasiden, forsiden og undersidene committes, så sitemap.xml",
          i_rg > 0 and "--n" not in gst[i_rg] and '--ut "$UT"' in gst[i_rg] and "UT: ${{ steps.port.outputs.ut }}" in gst[i_rg]
          and i_rg < i_ls < i_lg and "continue-on-error: true" in gst[i_ls]
          and 'git add "$UT/grunnlag.json"\n' in gst[i_lg] and '[ -f "$UT/keymatch.json" ] && git add "$UT/keymatch.json"' in gst[i_lg]
          and '[ -f "$UT/tekster.json" ] && git add "$UT/tekster.json"' in gst[i_lg] and 'git add "${{ matrix.liga }}/index.html"' in gst[i_lg]
          and "git add index.html" in gst[i_lg] and 'python3 scripts/lag_sider.py --filer "${{ matrix.liga }}" | xargs -r git add --' in gst[i_lg]
          and gst[i_lg].count("git add") == 8 and '[ -f "$UT/sjansehistorikk.json" ] && git add "$UT/sjansehistorikk.json"' in gst[i_lg] and "bash scripts/push_med_rebase.sh" in gst[i_lg]
          and gst[i_lg].index("bash scripts/push_med_rebase.sh") < gst[i_lg].index("bash scripts/push_sitemap.sh"))
    # Google (20.10.2026): den statiske tabellen. lag_grunnlag.js skriver
    # regionene STATISK-* fra siden selv; porten ser bort fra dem, bygget
    # beholder ligaens egne, og sitemap.xml har én skriver (push_sitemap.sh i
    # grunnlag.yml), med lastmod fra når tabellen ble regnet.
    import shutil, tempfile
    sys.path.insert(0, str(ROOT / "scripts"))
    import grunnlag_port, statisk_region, lag_sider
    for liga in ("eliteserien", "obos"):
        tk = lag_sider.les(liga)
        rd = tk["tabell"]["rader"]
        check(f"tekster.json: {liga} har tabellen fra siden (16 lag med poeng og tre sjanser, overskriftene), når og hvor mange sesonger",
              tk.get("versjon") == 1 and tk.get("side") == liga and tk.get("laget") and tk.get("sesonger") == 100000
              and len(rd) == 16 and [r["plass"] for r in rd] == list(range(1, 17))
              and all(set(r["sjanser"]) == {"gull", "europa", "ned"} and all("vist" in v and "andel" in v for v in r["sjanser"].values()) for r in rd)
              and [k["key"] for k in tk["tabell"]["kolonner"]] == ["gull", "europa", "ned"] and tk["tabell"]["rader_html"].count("<tr ") == 16)
        check(f"lag_sider.py: {liga}/index.html er laget fra tekster.json (lag_sider.py --check)", lag_sider.ligaside(liga) == (ROOT / liga / "index.html").read_text(encoding="utf-8"))
        side_ = (ROOT / liga / "index.html").read_text(encoding="utf-8")
        r_ = statisk_region.statiske(side_)
        # Ligasiden (20.10.2026): ingen oppsummering, verken øverst eller
        # nederst; «Oppdatert» er en liten linje nederst ved «Om modellen».
        check(f"ligaside: {liga}/index.html har ingen oppsummeringssetning, og «Oppdatert <dato>, N simulerte sesonger» står nederst etter «Om modellen»",
              "OPPSUMMERING" not in r_ and 'class="oppsummering"' not in side_ and "grid-area:opps" not in side_ and 'id="bunntekst"' not in side_
              and re.fullmatch(r"Oppdatert \d+\. \S+ \d{4} kl\. \d\d\.\d\d, [\d\u00a0 ]+ simulerte sesonger\.", r_.get("OPPDATERT", ""))
              and side_.index('id="omModellen"') < side_.index("<!-- STATISK-OPPDATERT -->"), r_.get("OPPDATERT", "")[:80])
        # Det JS fyller over og under tabellen står i HTML-en (tekster.json
        # «statisk», statiskeDeler() på siden): menyen, stempelet,
        # fargeforklaringen og boksene med tall og «Se alle →» til
        # spørsmålssidene for toppsonen og nedrykk.
        st_ = tk.get("statisk") or {}
        sider_ = dict((s, sti) for sti, s in lag_sider.SPORSMAL.get(liga, []))
        check(f"ligaside: {liga}/index.html har menyen, stempelet, fargeforklaringen og de fire boksene med tall fra tekster.json, og «Se alle →» til spørsmålssidene",
              all(r_.get(k) for k in ("LIGAMENY", "STEMPEL", "FORKLARING", "KORTGULL", "KORTEUROPA", "KORTNED", "KORTFORM"))
              and r_["LIGAMENY"] == st_.get("ligameny") and r_["STEMPEL"] == st_.get("stempel") and r_["FORKLARING"] == st_.get("forklaring")
              and all(r_[f"KORT{k.upper()}"] == st_["kort"][k] and r_[f"KORT{k.upper()}"].count("<li") >= 1 for k in ("gull", "europa", "ned", "form"))
              and f'href="/{liga}/{sider_.get("gull")}/"' in r_["KORTGULL"] and f'href="/{liga}/{sider_.get("nedrykk")}/"' in r_["KORTNED"]
              and 'aria-current="page"' in r_["LIGAMENY"] and r_["STEMPEL"].strip(), {k: len(v) for k, v in r_.items()})
        check(f"hopp: {liga}/index.html: qaHighlight har fast høyde (én linje, to på mobil) og skjules ikke når den er tom, og menylinja er fast 56 px",
              ".qa-highlight{min-height:1.25em}" in side_ and "@media (max-width:760px){.qa-highlight{min-height:2.5em}}" in side_
              and ".qa-highlight:empty" not in side_ and "height:56px;display:flex;align-items:center;gap:20px}" in side_
              and 'id="statiskNote"' not in side_)
    # Spørsmålssidene (fase 2): laget fra tekster.json, med tittel, canonical og
    # beskrivelse, i sitemap og lenket fra ligasiden og forsiden.
    sm_ = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    for liga, sider in lag_sider.SPORSMAL.items():
        tk = lag_sider.les(liga)
        for sti, sone in sider:
            f_ = ROOT / liga / sti / "index.html"
            t_ = f_.read_text(encoding="utf-8") if f_.exists() else ""
            tit = lag_sider.sporsmal_tittel(tk, sti)
            check(f"spørsmålsside: /{liga}/{sti}/ er laget fra tekster.json, med tittelen «{tit}», canonical og beskrivelse (svaret)",
                  t_ == lag_sider.sporsmal_side(liga, sti, sone, tk) and f"<title>{tit}</title>" in t_
                  and f'<link rel="canonical" href="https://tabellkalkulator.no/{liga}/{sti}/">' in t_ and '<meta name="description" content="' in t_)
            check(f"spørsmålsside: /{liga}/{sti}/ er i sitemap.xml og lenket fra ligasiden og forsiden",
                  f"<loc>https://tabellkalkulator.no/{liga}/{sti}/</loc>" in sm_
                  and f'href="/{liga}/{sti}/"' in "".join(v for k, v in statisk_region.statiske((ROOT / liga / "index.html").read_text(encoding="utf-8")).items() if k.startswith("KORT"))
                  and f'href="/{liga}/{sti}/"' in statisk_region.statiske((ROOT / "index.html").read_text(encoding="utf-8"))[liga.upper()])
    # Lagsidene (fase 3): laget fra tekster.json for hvert lag, med tittel,
    # canonical og knappen til kalkulatoren, lenket fra lista nederst på
    # ligasiden, med i sitemap-adressene, og funnet av lag_sider.py --filer
    # (git add i grunnlag-workflowen).
    import html as _html
    from urllib.parse import quote as _quote
    import make_sitemap
    sm_lag = "\n".join(make_sitemap.adresser())
    for liga in ("eliteserien", "obos"):
        tk = lag_sider.les(liga)
        lagt = tk.get("lag", {})
        check(f"tekster.json: {liga} har «lag» for alle 16 lagene (de øverste spørsmålene med svar, plassen, kampene som er igjen, sonene)",
              len(lagt) == 16 and set(lagt) == {r["lag"] for r in tk["tabell"]["rader"]} and all(
                  1 <= len(d["topp"]) <= 3 and all(q["id"] and q["sporsmal"] and q["svar"] for q in d["topp"])
                  and d["plass"]["sporsmal"] and d["plass"]["svar"]
                  and all({"naar", "motstander", "hjemme", "seier", "uavgjort", "tap"} <= set(k) for k in d["rest"])
                  and {"gull", "europa", "kvalik", "nedrykk"} <= {s["key"] for s in d["soner"]} for d in lagt.values()))
        side_ = (ROOT / liga / "index.html").read_text(encoding="utf-8")
        lagsider_ = statisk_region.statiske(side_).get("LAGSIDER", "")
        slugs, feil = [lag_sider.lag_slug(lag) for lag in lagt], []
        for lag in lagt:
            sl = lag_sider.lag_slug(lag)
            f_ = ROOT / liga / sl / "index.html"
            t_ = f_.read_text(encoding="utf-8") if f_.exists() else ""
            if not (t_ == lag_sider.lag_side(liga, lag, tk) and f"<title>{_html.escape(lag_sider.lag_tittel(tk, lag))}</title>" in t_
                    and f'<link rel="canonical" href="https://tabellkalkulator.no/{liga}/{sl}/">' in t_
                    and f'href="/{liga}/#team={_quote(lag, safe="")}"' in t_ and f'href="/{liga}/{sl}/"' in lagsider_
                    and f"<loc>https://tabellkalkulator.no/{liga}/{sl}/</loc>" in sm_lag):
                feil.append(lag)
        forst = next(iter(lagt), "")
        check(f"lagside: alle {len(lagt)} lagsidene i {liga} er laget fra tekster.json, med tittel («{lag_sider.lag_tittel(tk, forst) if forst else ''}» ...), "
              "canonical og knappen #team=, lenket fra lista nederst på ligasiden og med i sitemap", lagt and not feil, feil)
        check(f"lagside: adressene i {liga} er unike og kolliderer ikke med andre mapper (data, modellsjekk, spørsmålssidene)",
              len(set(slugs)) == len(slugs) and not set(slugs) & {"data", "modellsjekk", *(s for s, _ in lag_sider.SPORSMAL.get(liga, []))})
        check(f"lagside: «Lagsidene: ...» står nederst på {liga}/index.html ved «Om modellen», ikke i tabellen, og lagboksen har «Mer om <lag> →»; klikk på laget i tabellen følger fortsatt laget",
              side_.index('id="omModellen"') < side_.index("<!-- STATISK-LAGSIDER -->") < side_.index("<!-- STATISK-OPPDATERT -->")
              and lagsider_.startswith("Lagsidene: ") and lagsider_.count("<a ") == 16 and "<a " not in statisk_region.statiske(side_)["TABELL"]
              and 'class="lag-mer" href="${LEAGUE.path}${lagSlug(SELECTED_TEAM)}/">Mer om ${SELECTED_TEAM} →</a>' in side_
              and "if(el) followTeamToggle(el.dataset.team);" in side_)
        filer = lag_sider.undersider(liga)
        understi = list(slugs) + [s for s, _ in lag_sider.SPORSMAL.get(liga, [])]
        check(f"lagside: lag_sider.py --filer finner spørsmåls- og lagsidene i {liga} med delingsbildet ({len(filer)}), ikke modellsjekk",
              set(filer) == {f"{liga}/{s}/{f_}" for s in understi for f_ in ("index.html", "og.png")})
        # Delingsbildene (23.10.2026): ett per side, 1200 x 630, under 25 KB, med
        # innholdet lagret i bildet lik det lag_sider.py lager av tekster.json
        # (de samme tallene som teksten på siden), og og:image og twitter:image
        # på siden peker dit.
        bfeil = []
        for fil, innhold in lag_sider.bilder([liga]):
            sti_ = fil.parent.relative_to(ROOT).as_posix()
            side_t = (fil.parent / "index.html").read_text(encoding="utf-8")
            data = fil.read_bytes() if fil.exists() else b""
            mal = data[16:24] == (1200).to_bytes(4, "big") + (630).to_bytes(4, "big")
            url_ = f"https://tabellkalkulator.no/{sti_}/og.png"
            if innhold["art"] == "lag":
                r_ = next(r for r in tk["tabell"]["rader"] if r["lag"] == innhold["navn"])
                prosa = lambda v: {">99 %": "over 99 %", "<1 %": "under 1 %"}.get(v, v)
                tall_ok = innhold["tall_venstre"] == [[f"{r_['plass']}.", "plass"], [str(r_["poeng"]), "poeng"]] and all(
                    z["sone"] == "plass" or lag_sider._nb(prosa(z["tall"])) in side_t for z in innhold["tall"])
            else:
                tall_ok = f'<p class="svar">{lag_sider._nb(_html.escape(innhold["svar"]))}</p>' in side_t
            if not (data.startswith(b"\x89PNG") and mal and len(data) < 25 * 1024 and lag_sider.les_bilde(fil) == lag_sider.bilde_tekst(innhold)
                    and tall_ok and f'<meta property="og:image" content="{url_}">' in side_t and f'<meta name="twitter:image" content="{url_}">' in side_t):
                bfeil.append(f"{sti_} ({len(data)} B, mål {mal}, tall {tall_ok})")
        check(f"delingsbilde: hver lag- og spørsmålsside i {liga} har sitt eget bilde (1200 x 630, under 25 KB) med de samme tallene som siden, og og:image/twitter:image peker dit",
              not bfeil, bfeil[:4])
        # Lagsidene utvidet (23.10.2026). A: sjansehistorikk.json har ett punkt
        # per runde i rundevelgerens rekkefølge, med alle lag og soner, og siste
        # punkt er tallene i tekster.json når de er regnet etter runden. B:
        # «Vanskeligst» er kampen med lavest sjanse for seier i lista, som i
        # kalkulatoren. C: plassfordelingen summerer til 1.
        import sjansehistorikk as _sh
        hist = lag_sider.les_historikk(liga)
        nr_ = [x["nr"] for x in hist]
        soner_ = set(tk["regler"]["soner"])
        struktur = bool(hist) and nr_ == sorted(set(nr_)) and all(set(x["lag"]) == set(lagt) and all(set(v) == soner_ for v in x["lag"].values()) for x in hist)
        siste = hist[-1] if hist else {}
        like = siste.get("laget") != tk["laget"] or all(abs(siste["lag"][lg][s_["key"]] - s_["andel"]) < 6e-5
                                                         for lg, dd in lagt.items() for s_ in dd["soner"])
        d_ = ROOT / liga / "data"
        naa = _sh.punkt(_sh.terminliste(json.loads((d_ / "matches.json").read_text(encoding="utf-8")), json.loads((d_ / "fixtures.json").read_text(encoding="utf-8"))),
                        json.loads((d_ / "grunnlag.json").read_text(encoding="utf-8")), tk["regler"]["soner"], tk["regler"].get("utsatte_runder", {}))
        check(f"lagside: sjansehistorikk.json for {liga} har {len(hist)} runder ({', '.join(x['merke'] for x in hist)}) i rekkefølge med alle lag og soner, siste lik tekster.json og dagens runde",
              struktur and like and (naa is None or (naa["nr"] == siste.get("nr") and naa["runde"] == siste.get("runde"))), {"struktur": struktur, "like": like, "naa": naa and naa["merke"]})
        lfeil = []
        for lag, dd in lagt.items():
            t_ = (ROOT / liga / lag_sider.lag_slug(lag) / "index.html").read_text(encoding="utf-8")
            soner_lag = lag_sider._lagets_soner(dd)
            punkter = [x for x in hist if lag in x["lag"]]
            if punkter and soner_lag:
                figur = len(punkter) >= lag_sider.HIST_MIN_FIGUR
                vist = punkter[-lag_sider.HIST_FIGUR_MAKS:]
                # En sone der alle søylene er under 1 %, har ingen figur, og uten
                # noen igjen er det ingen seksjon (28.10.2026).
                med_figur = [s_ for s_ in soner_lag if any(p["lag"][lag][s_["key"]] >= 0.005 for p in vist)] if figur else []
                # Figur: egen seksjon med overskrift. Ellers én linje rett under
                # tabellen, uten overskrift.
                if (("de siste rundene</h2>" in t_) != bool(med_figur) or "gjennom sesongen" in t_ or ('<p class="historikk">' in t_) == figur
                        or (not figur and t_.index('<p class="historikk">') < t_.index('<p class="om">'))):
                    lfeil.append(f"{lag}: A")
                # Under søylen «Runde» over nummeret; en hel utsatt runde «Utsatt»
                # over datoen (28.10.2026).
                utsatte = sum(1 for p in vist if p["merke"] != str(p["runde"]))
                if t_.count('<figure class="fig hist">') != len(med_figur) or (figur and (
                        t_.count(">Runde</text>") != (len(vist) - utsatte) * len(med_figur)
                        or t_.count(">Utsatt</text>") != utsatte * len(med_figur) or "<polyline" in t_)):
                    lfeil.append(f"{lag}: A figurer")
            rp_ = dd.get("restprogram")
            if rp_ and dd["rest"]:
                tall_ = lambda v: 0 if v.startswith("<") else int(v.split()[0].lstrip(">"))
                minst = min(tall_(k["seier"]) for k in dd["rest"])
                merket = [k for k in dd["rest"] if k["naar"] == rp_["vanskeligst"]["naar"] and k["motstander"] == rp_["vanskeligst"]["motstander"]]
                if (f"motstanderne har i snitt {lag_sider._nb(rp_['snitt'])} vinnersjanse" not in t_ or t_.count('class="vanskeligst"') != 1
                        or len(merket) != 1 or tall_(merket[0]["seier"]) != minst or "vinner i snitt" in t_):
                    lfeil.append(f"{lag}: B")
            f_ = dd.get("fordeling") or []
            if (len(f_) != 16 or abs(sum(f_) - 1) > 1e-3 or t_.count('<figure class="fig fordeling">') != 1 or t_.count('role="img"') < 1
                    or not all(f'<li><i class="b-{b["cls"]}"></i>{b["tekst"].replace(" League-kvalifisering", " League")}</li>' in t_ for b in tk["regler"]["baand"])
                    or "soyle b-" not in t_):
                lfeil.append(f"{lag}: C")
            # «Hvilke kamper betyr mest» bare når en kamp flytter sjansen mer enn
            # 3 prosentpoeng (23.10.2026).
            km = next((q for q in dd["topp"] if q["id"] == "keymatches"), None)
            if km and "\n\n" in km["svar"]:
                vises = f"<h3>{km['sporsmal']}</h3>" in t_
                if vises != (lag_sider.kamper_flytter(km["svar"]) > lag_sider.KAMPER_MIN_PP):
                    lfeil.append(f"{lag}: kamper ({lag_sider.kamper_flytter(km['svar'])} pp, vises {vises})")
            # «Har X tatt flere eller færre poeng enn ventet?» (het «Har X vært
            # heldig eller uheldig?» til 24.10.2026): svaret fra kalkulatoren via
            # tekster.json, som de andre spørsmålene (23.10.2026).
            h_ = dd.get("heldig") or {}
            if (h_.get("sporsmal") != f"Har {lag} tatt flere eller færre poeng enn ventet?" or f"<h3>{h_['sporsmal']}</h3>" not in t_
                    or lag_sider._avsnitt(h_.get("svar", "")) not in t_):
                lfeil.append(f"{lag}: heldig")
        check(f"lagside: alle lagsidene i {liga} har historikken (tekst under {lag_sider.HIST_MIN_FIGUR} punkter, ellers søyler), restprogrammet med «Vanskeligst» som kalkulatoren, plassfordelingen i sonefargene med navnene og setningen om heldig/uheldig",
              not lfeil, lfeil[:4])
        if liga == "eliteserien":
            # Grafen på lagsiden (28.10.2026), med laget data: en sone der alle
            # søylene er under 1 %, har ingen figur, og uten noen igjen ingen
            # seksjon; 0,5 % vises som «1 %» og gir figur. Den utsatte runden
            # står der den ble spilt, som «Utsatt» over datoen.
            def _ht(kv, ned):
                pk = [{"nr": i + 21, "runde": r, "merke": m, "dato": dt, "lag": {"X": {"kvalik": a, "ned": b}}}
                      for i, (r, m, dt, a, b) in enumerate(zip((22, 23, 24, 12), ("22", "23", "24", "12 (utsatt)"),
                                                                 ("2026-09-20", "2026-10-12", "2026-10-18", "2026-10-25"), kv, ned))]
                t = {"liga": {"ferdig": False}, "laget": "x", "lag": {"X": {"aapnest": "kvalik", "soner": [
                    {"key": "kvalik", "navn": "kvalik", "avgjort": 0, "vist": "3 %"}, {"key": "ned", "navn": "nedrykk", "avgjort": 0, "vist": "2 %"}]}}}
                return lag_sider._historikk_html("eliteserien", t, "X", pk)
            _tom = _ht([0.004, 0.001, 0, 0.0049], [0.003, 0, 0.001, 0.002])
            _en = _ht([0.004, 0.001, 0, 0.0049], [0.28, 0.37, 0.14, 0.18])[1]
            _grense = _ht([0, 0, 0.005, 0], [0, 0, 0, 0])[1]
            check("lagside: grafen skjules når alle søylene er under 1 %, og den utsatte runden står som «Utsatt» over datoen den ble spilt",
                  _tom == ("", "") and "<h2>Sjansen for nedrykk de siste rundene</h2>" in _en and _en.count('<figure class="fig hist">') == 1
                  and _en.count(">Runde</text>") == 3 and _en.count(">Utsatt</text>") == 1 and ">25.10.</text>" in _en and "(utsatt)" not in _en
                  and "Etter den utsatte runde 12 (25.10.): 18 %." in _en
                  and "<h2>Sjansen for kvalik de siste rundene</h2>" in _grense and _grense.count('<figure class="fig hist">') == 1,
                  {"tom": _tom, "en": _en[:240], "grense": _grense[:120]})
        # Heldig/uheldig fra sluttoddsen (23.10.2026): det lagsidene sier, regnet
        # på nytt her fra odds_closing.json (marginen fjernet proporsjonalt, som
        # CLOSING på siden) og football-data der den mangler.
        kamper_ = json.loads((d_ / "matches.json").read_text(encoding="utf-8"))
        slutt_ = json.loads((d_ / "odds_closing.json").read_text(encoding="utf-8"))["matches"]
        fd_f = d_ / "odds_fd.json"
        fd_ = {(m["home"], m["away"]): m for m in json.loads(fd_f.read_text(encoding="utf-8"))["matches"]} if fd_f.exists() else {}
        regn = {lag: [0, 0.0, 0, 0, []] for lag in lagt}
        for m in kamper_:
            o = (slutt_.get(f"{tk['liga']['sesong']}|{m['home']}|{m['away']}") or {}).get("odds") or {}
            if o.get("H") and o.get("U") and o.get("B"):
                inv = 1 / o["H"] + 1 / o["U"] + 1 / o["B"]
                pH, pU, pB = (1 / o["H"]) / inv, (1 / o["U"]) / inv, (1 / o["B"]) / inv
            elif (m["home"], m["away"]) in fd_:
                x_ = fd_[(m["home"], m["away"])]
                pH, pU, pB = x_["H"], x_["D"], x_["A"]
            else:
                regn[m["home"]][3] += 1
                regn[m["away"]][3] += 1
                continue
            hj, bo = (3, 0) if m["hg"] > m["ag"] else (0, 3) if m["hg"] < m["ag"] else (1, 1)
            for lag_, po, ve, egen, mot, hjemme, opp in ((m["home"], hj, 3 * pH + pU, pH, pB, True, m["away"]),
                                                         (m["away"], bo, 3 * pB + pU, pB, pH, False, m["home"])):
                regn[lag_][0] += po
                regn[lag_][1] += ve
                regn[lag_][2] += 1
                regn[lag_][4].append({"egen": egen, "mot": mot, "vant": po == 3, "tapte": po == 0, "hjemme": hjemme, "opp": opp, "dato": m["date"]})
        # Svaret på «Har X tatt flere eller færre poeng enn ventet?» regnet på nytt her: det
        # markedet ventet, favoritt/underdog, største overraskelse og skuffelse.
        dato_ = lambda iso: f"{int(iso[8:10])}. {lag_sider.MAANEDER[int(iso[5:7]) - 1]}"
        hvor_ = lambda x: f"{'hjemme' if x['hjemme'] else 'borte'} mot {x['opp']} {dato_(x['dato'])}"
        avvik = []
        for lag, dd in lagt.items():
            svar_ = (dd.get("heldig") or {}).get("svar", "")
            faktisk, forventet, n_, uten_, ks = regn[lag]
            if not n_:
                continue
            ventet = int(forventet + 0.5)
            fav = [x for x in ks if x["egen"] > x["mot"]]
            und = [x for x in ks if x["egen"] < x["mot"]]
            seier = min((x for x in ks if x["vant"]), key=lambda x: x["egen"], default=None)
            tap = max((x for x in ks if x["tapte"]), key=lambda x: x["egen"], default=None)
            krav = [f"ga {ventet} poeng", f"{lag} {'tok' if uten_ else 'har'} {faktisk}"]
            if fav:
                krav.append(f"favoritt i {len(fav)} {'kamp' if len(fav) == 1 else 'kamper'} og vant {sum(x['vant'] for x in fav)}")
            if und:
                krav.append(f"underdog i {len(und)}")
            if seier:
                krav.append(f"Største overraskelse var seieren {hvor_(seier)}")
            if tap:
                krav.append(f"Største skuffelse var tapet {hvor_(tap)}")
            mangler_ = [k for k in krav if k not in svar_]
            setninger = len(re.findall(r"[.?!](?= [A-ZÆØÅ]|$)", svar_))
            if mangler_ or setninger > 4 or (uten_ and f"i de {n_} kampene som har sluttodds" not in svar_):
                avvik.append(f"{lag}: mangler {mangler_}, {setninger} setninger")
        check(f"heldig: «Har X tatt flere eller færre poeng enn ventet?» for alle lagene i {liga} stemmer med sluttoddsen (3 x seier + uavgjort uten margin, football-data der den mangler): ventet, favoritt/underdog, overraskelse og skuffelse, høyst fire setninger",
              not avvik, avvik[:3])
    gy_ = (ROOT / ".github" / "workflows" / "grunnlag.yml").read_text(encoding="utf-8")
    # Heldig/uheldig fra sluttoddsen (23.10.2026): «Om modellen» sier det, og
    # Eliteserien har football-data som reserve.
    for f_ in ("eliteserien/index.html", "obos/page/om.html"):
        t_ = (ROOT / f_).read_text(encoding="utf-8")
        check(f"heldig: «Om modellen» i {f_} forklarer heldig/uheldig fra oddsene før kampene, ikke modellens forventede poeng",
              "minus det oddsene før kampene tilsa" in t_ and "modellens forventede poeng" not in t_)
    es_ = (ROOT / "eliteserien" / "index.html").read_text(encoding="utf-8")
    check("heldig: kalkulatoren regner fra sluttoddsen (CLOSING) med football-data som reserve, og lagsidene bruker samme heldigData()",
          "reserveSluttodds: 'data/odds_fd.json'" in es_ and "function heldigData()" in es_ and "baseRate(" not in es_
          and "{id:'teamluck', needsTeam:true, run:team=>qaTeamLuck(team)" in es_
          and "QA_QUESTIONS.find(q => q.id === 'teamluck')" in (ROOT / "scripts" / "lag_grunnlag.js").read_text(encoding="utf-8"))
    # Temaet (23.10.2026): lag- og spørsmålssidene leser det lagrede valget i
    # <head> før stilarket, har månknappen (skjult uten JS) og data-theme i CSS-en.
    tfeil = []
    for liga_ in ("eliteserien", "obos"):
        for f_ in sorted((ROOT / liga_).glob("*/index.html")):
            t_ = f_.read_text(encoding="utf-8")
            if lag_sider.MERKE not in t_[:2000]:
                continue
            if not (t_.index("localStorage.getItem('theme')") < t_.index("<style>") and 'id="themeToggle"' in t_ and " hidden>" in t_
                    and ':root[data-theme="dark"]' in t_ and ':root:not([data-theme="light"])' in t_ and "localStorage.setItem('theme', n)" in t_):
                tfeil.append(f_.relative_to(ROOT).as_posix())
    check("tema: alle lag- og spørsmålssidene har det lagrede temaet satt i <head>, månknappen og data-theme i CSS-en, som kalkulatoren", not tfeil, tfeil[:4])
    check("delingsbilde: grunnlag.yml installerer Pillow før «Lag sidene», og lag_sider.py lager sidene også uten Pillow",
          gy_.index("run: pip install Pillow") < gy_.index("- name: Lag sidene fra tekster.json")
          and "except ImportError" in (ROOT / "scripts" / "lag_sider.py").read_text(encoding="utf-8"))
    check("lagside: grunnlag.yml legger undersidene lag_sider.py har laget (--filer) i grunnlag-commiten",
          'python3 scripts/lag_sider.py --filer "${{ matrix.liga }}" | xargs -r git add --' in (ROOT / ".github" / "workflows" / "grunnlag.yml").read_text(encoding="utf-8"))
    # Regelsvarene (20.10.2026): synlige i HTML-en på spørsmålssidene i
    # lag_sider.REGLER, med plassene fra LEAGUE og siste runde, dato og antall
    # kamper fra terminlisten (matches.json og fixtures.json, ikke hardkodet).
    for liga, sider in lag_sider.REGLER.items():
        tk = lag_sider.les(liga)
        rg = tk.get("regler") or {}
        kamper = {(m["home"], m["away"]): m for m in json.loads((ROOT / liga / "data" / "matches.json").read_text(encoding="utf-8"))}
        for rd_ in json.loads((ROOT / liga / "data" / "fixtures.json").read_text(encoding="utf-8")):
            for m in rd_["matches"]:
                kamper.setdefault((m["home"], m["away"]), {**m, "round": rd_["round"]})
        siste = max(m["date"] for m in kamper.values())
        check(f"regelsvar: tekster.json for {liga} har siste runde {rg.get('siste_runde')}, {rg.get('siste_dato')} og {rg.get('kamper')} kamper, som terminlisten (matches.json og fixtures.json)",
              rg.get("siste_dato") == siste and rg.get("siste_runde") == max(m["round"] for m in kamper.values()) and rg.get("kamper") == len(kamper)
              and rg.get("runder_siste_dato") == sorted({m["round"] for m in kamper.values() if m["date"] == siste}), {k: rg.get(k) for k in ("siste_runde", "siste_dato", "kamper")})
        kilde = (ROOT / ("eliteserien/index.html" if liga == "eliteserien" else f"{liga}/page/league.js")).read_text(encoding="utf-8")
        soner_ok = all(re.search(rf"\b{k}: \{{lo: {v['lo']}, hi: {v['hi']}\b", kilde) for k, v in rg.get("soner", {}).items())
        check(f"regelsvar: plassene i tekster.json for {liga} er de samme som i LEAGUE (sonene)", bool(rg.get("soner")) and soner_ok, rg.get("soner"))
        for sti, nokler in sider.items():
            t_ = (ROOT / liga / sti / "index.html").read_text(encoding="utf-8")
            svar = [lag_sider.regelsvar(tk, n) for n in nokler]
            check(f"regelsvar: /{liga}/{sti}/ har {', '.join(f'«{sp}»' for sp, _ in svar)} synlig i HTML-en, høyst to setninger hver, og ikke «2. divisjon» (ikke bekreftet)",
                  "<h2>Om reglene</h2>" in t_ and all(f"<h3>{sp}</h3><p>{lag_sider._nb(sv)}</p>" in t_ and 1 <= len(re.findall(r"[.?!](?= [A-ZÆØÅ]|$)", sv)) <= 2 for sp, sv in svar)
                  and "2. divisjon" not in t_,
                  [sv for _, sv in svar])
    # Rekkefølgen (20.10.2026): lag nevnes i tabellens rekkefølge, nedrykk
    # nedenfra, så tekst og tabell aldri sier noe ulikt om plassene.
    for liga, sider in lag_sider.SPORSMAL.items():
        tk = lag_sider.les(liga)
        plass = {r["lag"]: r["plass"] for r in tk["tabell"]["rader"]}
        for sti, sone in sider:
            t_ = (ROOT / liga / sti / "index.html").read_text(encoding="utf-8")
            orden = [plass[n] for n in re.findall(r"Kampene som betyr mest for ([^<]+)</h3>", t_)]
            ned = tk["sporsmal"][sone]["kolonne"] == "ned"
            # Svarsetningen: etter sjanse, høyest først; nedrykk nedenfra.
            rad = {r["lag"]: r for r in tk["tabell"]["rader"]}
            svar = re.search(r'<p class="svar">(.*?)</p>', t_).group(1)
            i_svar = sorted((svar.index(x["lag"]), x["lag"]) for x in tk["sporsmal"][sone]["lag"] if x["lag"] in svar)
            sv_lag = [n for _, n in i_svar]
            ventet = sorted(sv_lag, key=lambda n: -rad[n]["plass"]) if ned else sorted(sv_lag, key=lambda n: -rad[n]["sjanser"]["gull"]["andel"])
            check(f"rekkefølge: /{liga}/{sti}/: «Hvorfor» og kampene i tabellens rekkefølge{' nedenfra' if ned else ''} ({orden}), svaret {'nedenfra' if ned else 'etter sjanse'} ({', '.join(sv_lag)})",
                  orden == sorted(orden, reverse=ned) and len(orden) == len(tk["sporsmal"][sone]["lag"]) and sv_lag == ventet)
    for liga in ("eliteserien", "obos"):
        tk = lag_sider.les(liga)
        topp = lag_sider.topp_setning(tk)
        i_ = sorted((topp.index(r["lag"]), r) for r in tk["tabell"]["rader"] if r["lag"] in topp)
        andeler = [r["sjanser"]["gull"]["andel"] for _, r in i_ if r["sjanser"]["gull"]["avgjort"] == 0]
        check(f"rekkefølge: oppsummeringen for {liga} nevner lederne etter sjanse, høyest først", andeler == sorted(andeler, reverse=True), topp[:80])
    fs_ = statisk_region.statiske((ROOT / "index.html").read_text(encoding="utf-8"))
    check("oppsummering: forsiden har den korte oppsummeringen for begge ligaene, laget fra tekster.json",
          all(fs_.get(k, "").count("Oppdatert ") == 1 and "ligger nærmest" in fs_.get(k, "") for k in ("ELITESERIEN", "OBOS"))
          and lag_sider.forside() == (ROOT / "index.html").read_text(encoding="utf-8"), {k: len(fs_.get(k, "")) for k in ("ELITESERIEN", "OBOS")})
    for liga in ("eliteserien", "obos"):
        t = (ROOT / liga / "index.html").read_text(encoding="utf-8")
        r = statisk_region.statiske(t)
        # Fra 24.10.2026 også høyre kolonne uten lag (ingen hopp ved lasting):
        # «Neste kamp» (hele seksjonen, JS fyller den), spørsmålslista,
        # «Forrige runde» og de to første rundene i kamplista; banneret,
        # «etter ...», rundetallet og tellerne.
        check(f"statisk tabell: {liga}/index.html har regionene KOLONNER, TABELL, OPPDATERT, menyen, stempelet, fargeforklaringen, boksene, lagsidene, «Neste kamp», spørsmålslista, «Forrige runde», kamplista, banneret, «etter ...», rundetallet og tellerne, med overskriftscellene og rader",
              set(r) == {"KOLONNER", "OPPDATERT", "TABELL", "LIGAMENY", "STEMPEL", "FORKLARING", "KORTGULL", "KORTEUROPA", "KORTNED", "KORTFORM", "LAGSIDER",
                         "NESTEKAMP", "SPORSMALSLISTE", "FORRIGERUNDE", "RUNDER", "BANNER", "TABELLINFO", "RUNDE", "FORRIGEINFO", "KAMPINFO"} and all(f'id="{x}"' in r["KOLONNER"] for x in ("gullHeader", "europaHeader", "nedHeader"))
              and r["TABELL"].count("<tr ") == 16 and r["OPPDATERT"].startswith("Oppdatert ")
              and r["NESTEKAMP"].lstrip().startswith('<section class="panel nextmatch" id="nextMatch"') and all(f'id="{x}"' in r["NESTEKAMP"] for x in ("nmWhen", "nmHome", "nmAway", "nmHub", "nmImpact", "nmRes"))
              and 'class="qa-item' in r["SPORSMALSLISTE"] and 1 <= r["RUNDER"].count('<div class="round') <= 2 and "hiddenRounds" not in r["RUNDER"]
              and 'id="qaHighlight"' in r["BANNER"] and re.fullmatch(r"Runde \d+.* av \d+", r["RUNDE"]) and r["TABELLINFO"].strip() and r["KAMPINFO"].strip(),
              {k: len(v) for k, v in r.items()})
        with tempfile.TemporaryDirectory() as tmp:
            c = grunnlag_port.SIDER[liga]
            for rel in {c["side"], c["modell"], "scripts/lag_grunnlag.js"}:
                (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / rel, Path(tmp) / rel)
            shutil.copytree(ROOT / c["data"], Path(tmp) / c["data"], dirs_exist_ok=True)
            h1 = grunnlag_port.inndata(liga, Path(tmp))
            (Path(tmp) / c["side"]).write_text(statisk_region.med_statiske(t, {**r, "TABELL": "<tr><td>annet</td></tr>", "OPPDATERT": "Oppdatert i går"}), encoding="utf-8")
            h2 = grunnlag_port.inndata(liga, Path(tmp))
            (Path(tmp) / c["side"]).write_text(t + "\n<!-- endret kode -->\n", encoding="utf-8")
            h3 = grunnlag_port.inndata(liga, Path(tmp))
        check(f"statisk tabell: grunnlag-porten for {liga} ser bort fra den statiske tabellen, men ikke fra koden", h1 == h2 and h1 != h3)
    eli_lag = set(re.findall(r'data-team="([^"]+)"', statisk_region.statiske((ROOT / "eliteserien" / "index.html").read_text(encoding="utf-8"))["TABELL"]))
    obos_lag = set(re.findall(r'data-team="([^"]+)"', statisk_region.statiske((ROOT / "obos" / "index.html").read_text(encoding="utf-8"))["TABELL"]))
    check("statisk tabell: OBOS-siden har sin egen tabell, ikke Eliteserien-sidens", obos_lag and not (obos_lag & eli_lag))
    # Skriftene fra eget domene (24.10.2026, scripts/skrifter.py): blokken er
    # lik blokk() med sidens vekter, filene finnes, og ingen publisert side
    # henter dem fra Google Fonts lenger (skriftbyttet der flyttet teksten).
    sys.path.insert(0, str(ROOT / "scripts"))
    import skrifter
    sk_ = {"index.html": skrifter.FORSIDE, "eliteserien/index.html": skrifter.LIGA, "obos/index.html": skrifter.LIGA,
           "eliteserien/brann/index.html": skrifter.LAGSIDE, "obos/odd/index.html": skrifter.LAGSIDE,
           "eliteserien/hvem-vinner/index.html": skrifter.SPORSMAL, "eliteserien/modellsjekk/index.html": skrifter.MODELLSJEKK}
    sk_feil = [f for f, v in sk_.items() if skrifter.blokk(v) not in (ROOT / f).read_text(encoding="utf-8")]
    sk_feil += [fil for fil in skrifter.FILER.values() if not (ROOT / "assets" / "fonts" / fil).is_file()]
    sk_feil += [str(f.relative_to(ROOT)) for f in [ROOT / "index.html", *ROOT.glob("eliteserien/**/index.html"), *ROOT.glob("obos/**/index.html")]
                if "fonts.googleapis.com" in f.read_text(encoding="utf-8")]
    check("skriftene: fra assets/fonts/ med preload og font-display: optional (scripts/skrifter.py) på forsiden, ligasidene, lagsidene, spørsmålssidene og modellsjekk, ingen fra Google Fonts",
          not sk_feil, sk_feil[:5])
    uw = (ROOT / ".github" / "workflows" / "update-data.yml").read_text(encoding="utf-8")
    ms = (ROOT / "scripts" / "make_sitemap.py").read_text(encoding="utf-8")
    check("sitemap.xml: én skriver (push_sitemap.sh i grunnlag.yml), ikke update-data.yml, og lastmod fra grunnlagsfilen",
          "make_sitemap.py" not in "\n".join(l for l in uw.splitlines() if not l.lstrip().startswith("#")) and "sitemap.xml" not in uw.split("git add eliteserien/og.png")[1].split("\n")[0]
          and 'grunnlag.json' in ms and '"laget"' in ms and "make_sitemap.py" in (ROOT / "scripts" / "push_sitemap.sh").read_text(encoding="utf-8"))
    # IndexNow (fase 1c): nøkkelfilen i roten, sidene som adresser, og kallet
    # i grunnlag.yml etter pushen, som aldri kan gjøre kjøringen rød.
    import indexnow
    k_ = indexnow.nokkel()
    check("IndexNow: nøkkelfilen <nøkkel>.txt i roten har nøkkelen som innhold, og sidene i en commit blir adresser (ikke data, sitemap eller elo-test)",
          (ROOT / f"{k_}.txt").read_text(encoding="utf-8").strip() == k_
          and indexnow.adresser(["eliteserien/index.html", "index.html", "obos/index.html", "eliteserien/data/grunnlag.json", "sitemap.xml", "elo-test/index.html"])
          == ["https://tabellkalkulator.no/eliteserien/", "https://tabellkalkulator.no/", "https://tabellkalkulator.no/obos/"])
    lg_steg = gst[i_lg]
    # Bare med endret innhold, uten tidsgrense (28.10.2026):
    # sidene velges før commiten (--planlegg, data/indexnow.json følger med) og
    # sendes etter pushen (--send).
    check("IndexNow: grunnlag.yml velger sidene før commiten (data/indexnow.json følger med) og melder fra etter pushen, og indexnow.py avslutter alltid med 0",
          lg_steg.index('python3 scripts/indexnow.py --planlegg "$RUNNER_TEMP/indexnow.txt"') < lg_steg.index("[ -f data/indexnow.json ] && git add data/indexnow.json")
          < lg_steg.index("git commit") < lg_steg.index("bash scripts/push_med_rebase.sh")
          < lg_steg.index('python3 scripts/indexnow.py --send "$RUNNER_TEMP/indexnow.txt"') and "$FILER" not in lg_steg
          and "except Exception" in (ROOT / "scripts" / "indexnow.py").read_text(encoding="utf-8"))
    from datetime import datetime as _dt_ix, timedelta as _td_ix, timezone as _tz_ix
    _s1 = '<p class="dato">Oppdatert 27. oktober 2026 kl. 12.43.</p><td title="hentet tirsdag 27.10 kl. 10.00: 24/24/52">54 %</td>'
    _s2 = '<p class="dato">Oppdatert 28. oktober 2026 kl. 09.15.</p><td title="hentet onsdag 28.10 kl. 08.00: 24/24/52">54 %</td>'
    _s3 = _s2.replace("54 %", "55 %")
    _ls = '<!-- STATISK-OPPDATERT -->Oppdatert 27. oktober kl. 10.07<!-- /STATISK-OPPDATERT --><span class="opps-dato">Oppdatert kl. 12.43.</span>X'
    _ls2 = _ls.replace("10.07", "11.00").replace("12.43", "13.00")
    check("IndexNow: innholdssummen ser bort fra tidsfeltene («Oppdatert ... kl.», STATISK-OPPDATERT, forsidens dato, «hentet ... kl.»), ikke fra tallene",
          indexnow.innholdssum(_s1) == indexnow.innholdssum(_s2) != indexnow.innholdssum(_s3) and indexnow.innholdssum(_ls) == indexnow.innholdssum(_ls2))
    _t = {"adresser": {}, "dager": {}}
    _n0 = _dt_ix(2026, 10, 25, 10, 0, tzinfo=_tz_ix.utc)
    _A, _B = "https://tabellkalkulator.no/obos/", "https://tabellkalkulator.no/obos/odd/"
    _v = [indexnow.velg(_t, {_A: "a1", _B: "b1"}, _n0),                      # første gang: begge
          indexnow.velg(_t, {_A: "a2", _B: "b1"}, _n0 + _td_ix(minutes=10)), # A endret 10 minutter etter: A med en gang
          indexnow.velg(_t, {_A: "a2", _B: "b1"}, _n0 + _td_ix(hours=3)),    # ingenting endret siden sist meldt
          indexnow.velg(_t, {_A: "a3", _B: "b2"}, _n0 + _td_ix(hours=13, minutes=30))]  # 23.30 UTC = 00.30 norsk tid 26.10.
    check("IndexNow: en side meldes når innholdet er endret siden sist den ble meldt, uten tidsgrense; antallet per dag (norsk dato) lagres",
          _v == [[_A, _B], [_A], [], [_A, _B]] and _t["dager"] == {"2026-10-25": 3, "2026-10-26": 2}
          and _t["adresser"][_A]["meldt"] == "2026-10-25T23:30:00Z" and _t["adresser"][_A]["hash"] == "a3"
          and not hasattr(indexnow, "GRENSE"), f"{_v} {_t}")
    for liga in ("eliteserien", "obos"):
        uten = re.findall(r'<span class="sm">(?! )[^<]{0,20}', (ROOT / liga / "index.html").read_text(encoding="utf-8"))
        check(f"søk: {liga}/index.html: fullt og kort navn har mellomrom først i det korte («Legg inn resultater Resultater», «Rosenborg RBK»), i markupen og i JS",
              not uten, uten[:4])
    for liga, navn in (("eliteserien", "Eliteserien"), ("obos", "OBOS-ligaen")):
        tit = re.search(r"<title>(.*?)</title>", (ROOT / liga / "index.html").read_text(encoding="utf-8")).group(1)
        check(f"søk: tittelen på {liga}/index.html begynner med «Tabellkalkulator {navn} 2026: sjanse for»", tit.startswith(f"Tabellkalkulator {navn} 2026: sjanse for"), tit)
    # meta description høyst 155 tegn på alle sidene (Bing: høyst 160; /obos/
    # hadde 170 og modellsjekk-sidene 185, 28.10.2026). Lag- og
    # spørsmålssidene bruker svaret, kortet av lag_sider.kort_beskrivelse.
    import html as _html_d
    _lange = []
    for _f in [ROOT / "index.html", *ROOT.glob("eliteserien/**/index.html"), *ROOT.glob("obos/**/index.html")]:
        _m = re.search(r'<meta name="description" content="([^"]*)"', _f.read_text(encoding="utf-8"))
        if not _m or len(_html_d.unescape(_m.group(1))) > lag_sider.BESKRIVELSE_MAKS:
            _lange.append(f"{_f.relative_to(ROOT)}: {len(_html_d.unescape(_m.group(1))) if _m else 'mangler'}")
    _fyll = "Laget har mange kamper igjen mot lag fra den øvre halvdelen av tabellen. " * 3
    _lang = "Brann har 54 % sjanse for topp 4 og 1 % for gull. " + _fyll
    # Ordenstall deler ikke setningen (28.10.2026): «3. plass» er ikke et setningsslutt.
    _plass = "Brann ender på 3. plass i 41 % av sesongene og på 4. plass i 22 %."
    _korte = [lag_sider.kort_beskrivelse(x) for x in (_lang, _plass + " " + _fyll)]
    check("søk: meta description er høyst 155 tegn på forsiden, ligasidene, lag-, spørsmåls- og modellsjekk-sidene, og et for langt svar kortes til første setning (ikke ved «3. plass»)",
          not _lange and all(len(x) <= 155 for x in _korte) and _korte[1] == _plass
          and lag_sider.kort_beskrivelse("Kort svar.") == "Kort svar.", _lange[:5] + _korte)
    # Banneret (keymatch.json) har én skriver: lag_grunnlag.js, fra
    # grunnlagsfilen, i grunnlag.yml. To jobber som committer samme fil, kan
    # gi rebasekonflikt, og da kan en datajobb miste commiten sin.
    lg = (ROOT / "scripts" / "lag_grunnlag.js").read_text(encoding="utf-8")
    sp = (ROOT / "scripts" / "snapshot_probs.js").read_text(encoding="utf-8")
    check("banneret regnes fra grunnlagsfilen: lag_grunnlag.js skriver keymatch.json med keymatchFra(await qaKeyRoundData())",
          "keymatchFra(await qaKeyRoundData())" in lg and "path.join(UT, 'keymatch.json')" in lg
          and "if (v.status !== 'i bruk') throw" in lg)
    check("snapshot_probs.js regner og skriver ikke banneret lenger",
          "qaKeyRoundData" not in sp and "KEYMATCH" not in sp and "writeFileSync(path.join(UT, 'keymatch.json')" not in sp)
    check("ingen andre jobber committer keymatch.json (datajobbene og elo-test.yml)",
          not any("keymatch.json" in "\n".join(l for l in (wfd / f).read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
                  for f in ("update-data.yml", "obos-results.yml", "elo-test.yml", "prekick-odds.yml", "update-odds.yml")))
    check("datajobbene nevner ikke grunnlagsfilen: regningen kan ikke stoppe eller forsinke dem",
          not any(n_ in (wfd / f).read_text(encoding="utf-8") for f in ("update-data.yml", "obos-results.yml", "update-odds.yml", "prekick-odds.yml")
                  for n_ in ("grunnlag.json", "lag_grunnlag", "grunnlag_port", "grunnlag.yml")))

    # 23. Anførselstegn: tekst brukeren ser, bruker vanlige anførselstegn (").
    # Ingen « » i statisk tekst, FAQ-en, tekstene svarene bygger eller CSS
    # (banneret satte « » rundt spørsmålet med content:"\00AB"). Kommentarer
    # i koden teller ikke: de fjernes før søket (HTML-, CSS/JS-blokk- og
    # linjekommentarer; // teller som kommentar bare først på linjen eller
    # etter mellomrom, så https:// i en streng står).
    import re as _re
    def _uten_kommentarer(t):
        nl = lambda m: "\n" * m.group(0).count("\n")
        t = _re.sub(r"<!--.*?-->", nl, t, flags=_re.S)
        t = _re.sub(r"/\*.*?\*/", nl, t, flags=_re.S)
        return _re.sub(r"(^|[ \t])//[^\n]*", r"\1", t, flags=_re.M)
    _gaase = _re.compile(r"[«»]|\\00a[bB]|\\00b[bB]|\\00A[bB]|\\00B[bB]|\\u00a[bB]|\\u00b[bB]|&laquo;|&raquo;|&#171;|&#187;")
    _funn = []
    for f in ["eliteserien/index.html", "obos/index.html", "elo-test/index.html",
              *sorted(str(x.relative_to(ROOT)) for x in (ROOT / "obos" / "page").iterdir())]:
        for nr, linje in enumerate(_uten_kommentarer((ROOT / f).read_text(encoding="utf-8")).split("\n"), 1):
            if _gaase.search(linje):
                _funn.append(f"{f}:{nr}: {linje.strip()[:120]}")
    check("ingen « » i tekst brukeren ser eller i strengene svarene bygger (alle tre sidene og obos/page)",
          not _funn, "\n      ".join(_funn))

    # 24. Sommer- og vintertid uten å flytte noe: jobbene med et norsk
    # klokkeslett har én cron-linje for hver, og scripts/norsk_klokke.py
    # slipper gjennom den som gjelder etter den PLANLAGTE tiden; jobbene med
    # vinduer har vinduer som dekker begge. Falsk klokke: før og etter
    # vintertiden 25. oktober 2026 (01.00 UTC), og på selve dagen.
    import norsk_klokke as _nk
    from datetime import timezone as _tzu
    U = lambda *a: _dt(*a, tzinfo=_tzu.utc)
    tilfeller = [
        # (hendelse, cron-linje, norsk time, klokka, skal kjøre, hva)
        ("schedule", "17 5 * * *", 7, U(2026, 10, 20, 5, 17), True, "20. oktober, sommertid: 05.17 UTC er 07.17"),
        ("schedule", "17 6 * * *", 7, U(2026, 10, 20, 6, 17), False, "20. oktober, sommertid: vinterlinja (06.17 UTC er 08.17) avslutter"),
        ("schedule", "17 5 * * *", 7, U(2026, 10, 25, 5, 17), False, "25. oktober, vintertid fra 01.00 UTC: sommerlinja (06.17 norsk) avslutter"),
        ("schedule", "17 6 * * *", 7, U(2026, 10, 25, 6, 17), True, "25. oktober, vintertid: 06.17 UTC er 07.17"),
        ("schedule", "17 5 * * *", 7, U(2026, 11, 2, 5, 17), False, "2. november: sommerlinja avslutter"),
        ("schedule", "17 6 * * *", 7, U(2026, 11, 2, 6, 17), True, "2. november: vinterlinja kjører"),
        ("schedule", "17 5 * * *", 7, U(2026, 10, 20, 7, 40), True, "sommerlinja forsinket over to timer (07.40 UTC) kjører likevel"),
        ("schedule", "17 5 * * *", 7, U(2027, 3, 29, 5, 17), True, "29. mars 2027, sommertid igjen: sommerlinja kjører"),
        ("schedule", "17 6 * * *", 7, U(2027, 3, 29, 6, 17), False, "29. mars 2027: vinterlinja avslutter"),
        ("schedule", "40 6 * * 1", 8, U(2026, 10, 19, 6, 40), True, "mandag 19. oktober: 06.40 UTC er 08.40"),
        ("schedule", "40 7 * * 1", 8, U(2026, 10, 19, 7, 40), False, "mandag 19. oktober: vinterlinja avslutter"),
        ("schedule", "40 6 * * 1", 8, U(2026, 10, 26, 6, 40), False, "mandag 26. oktober: sommerlinja avslutter"),
        ("schedule", "40 7 * * 1", 8, U(2026, 10, 26, 7, 40), True, "mandag 26. oktober: 07.40 UTC er 08.40"),
        ("workflow_dispatch", "", 7, U(2026, 10, 20, 13, 3), True, "planleggeren og manuelt kjører alltid"),
    ]
    for hend, plan, t, naa, ventet, hva in tilfeller:
        kjor, grunn = _nk.skal_kjore(hend, plan, t, naa)
        check(f"norsk klokke: {hva} -> {'kjører' if ventet else 'avslutter'}", kjor is ventet, grunn)
    # Kommandolinja, slik workflowen kaller den (falsk klokke i KLOKKE_NAA).
    def _nk_cli(time, plan, naa):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "norsk_klokke.py"), str(time)], capture_output=True, text=True,
                           env={**os.environ, "HENDELSE": "schedule", "PLAN": plan, "KLOKKE_NAA": naa, "GITHUB_OUTPUT": ""})
        return r.stdout.strip()
    check("norsk klokke fra kommandolinja: sommerlinja før 25. oktober, vinterlinja etter",
          _nk_cli(7, "17 5 * * *", "2026-10-24T05:17:00+00:00") == "kjor=true" and _nk_cli(7, "17 6 * * *", "2026-10-24T06:17:00+00:00") == "kjor=false"
          and _nk_cli(7, "17 5 * * *", "2026-10-26T05:17:00+00:00") == "kjor=false" and _nk_cli(7, "17 6 * * *", "2026-10-26T06:17:00+00:00") == "kjor=true")

    def _timer(felt):
        ut = set()
        for d in felt.split(","):
            if "-" in d:
                a_, b_ = d.split("-"); ut.update(range(int(a_), int(b_) + 1))
            else:
                ut.add(int(d))
        return ut
    def _crons(navn):
        t = (wfd / navn).read_text(encoding="utf-8")
        return [l.split('"')[1] for l in t.splitlines() if l.strip().startswith('- cron:')]
    # Jobbene med et norsk klokkeslett: begge linjene, og klokkejobben først.
    for navn, linjer, time in (("obos-results.yml", ["17 5 * * *", "17 6 * * *"], 7),
                               ("obos-odds-history.yml", ["40 6 * * 1", "40 7 * * 1"], 8)):
        t = (wfd / navn).read_text(encoding="utf-8")
        check(f"{navn}: én cron-linje for sommertid og én for vintertid, og klokkejobben slipper gjennom den som gjelder",
              _crons(navn) == linjer and f"run: python3 scripts/norsk_klokke.py {time}\n" in t
              and "PLAN: ${{ github.event.schedule }}" in t and "    if: github.event_name == 'schedule'\n" in t
              and "    needs: klokke\n    if: ${{ !cancelled() && (github.event_name != 'schedule' || needs.klokke.outputs.kjor == 'true') }}\n" in t,
              str(_crons(navn)))
    # Jobbene med vinduer: hver norsk time i vinduet er dekket både om
    # sommeren (UTC+2) og om vinteren (UTC+1), med samme kadens.
    def _dekker(navn, cron_nr, norske_timer):
        c = _crons(navn)[cron_nr].split()
        timer = _timer(c[1])
        mangler = [(h, s) for h in norske_timer for s, fs in (("sommer", 2), ("vinter", 1)) if (h - fs) % 24 not in timer]
        return mangler
    check("update-data.yml: hvert 20. minutt kl 12-22 norsk tid, både sommer og vinter",
          not _dekker("update-data.yml", 0, range(12, 23)) and _crons("update-data.yml")[0].split()[0] == "5,25,45",
          str(_dekker("update-data.yml", 0, range(12, 23))))
    alle = set(range(24))
    t0, t1 = _timer(_crons("update-data.yml")[0].split()[1]), _timer(_crons("update-data.yml")[1].split()[1])
    check("update-data.yml: resten av døgnet hver time, uten hull (alle 24 timene i UTC)", t0 | t1 == alle and not (t0 & t1), f"{sorted(t0)} {sorted(t1)}")
    check("arkiver-kildehtml.yml: hvert 20. minutt kl 12-23 norsk tid, både sommer og vinter",
          not _dekker("arkiver-kildehtml.yml", 0, range(12, 24)), str(_dekker("arkiver-kildehtml.yml", 0, range(12, 24))))

    # 25. Modellinnstillingene: l1/l2 8/24 og halveringstid 28 dager, tatt i
    # bruk 30. september 2026 etter tilbaketesten (ENDRINGER.md). Skriptene som
    # tilpasser modellen, tilbaketestene som validerer den og model.json i
    # begge ligaene skal ha de samme verdiene, og den tekniske teksten på
    # sidene skal si det samme. Et skript som står igjen med 16/48 og 35
    # dager, gir en annen modell enn den som er validert.
    import fit_model as _FM, obos_build_data as _OB, backtest_zones as _BZ
    _ventet = (28.0, 8.0, 24.0)
    for _navn, _v in (("scripts/fit_model.py", (_FM.HALF_LIFE_DAYS, _FM.L1, _FM.L2)),
                      ("scripts/obos_build_data.py", (_OB.HALF_LIFE, _OB.L1, _OB.L2)),
                      ("scripts/backtest_zones.py (og backtest_walkforward.py, som bruker den)",
                       (_BZ.HALF_LIFE, _BZ.L1_FULL, _BZ.L2_FULL))):
        check(f"{_navn}: halveringstid 28 dager og l1/l2 8/24", tuple(float(x) for x in _v) == _ventet, str(_v))
    check("scripts/evaluate_model.py: standard halveringstid 28 dager",
          'add_argument("--half-life", type=float, default=28.0)' in (ROOT / "scripts" / "evaluate_model.py").read_text(encoding="utf-8"))
    for liga in ("eliteserien", "obos"):
        _m = json.loads((ROOT / liga / "data" / "model.json").read_text(encoding="utf-8")).get("meta") or {}
        _v = (_m.get("half_life_days"), _m.get("l1"), _m.get("l2"))
        check(f"{liga}/data/model.json er tilpasset med halveringstid 28 dager og l1/l2 8/24", _v == _ventet, str(_v))
    # Den forrige modellen (16/48, 35 dager) kan nevnes som sammenligning,
    # men ikke der teksten beskriver modellen som er i bruk.
    # Ablasjonen står på modellsjekk-siden (<liga>/modellsjekk/) fra 3.10.2026.
    for liga, rad in (("eliteserien", "Full modell (l1/l2=8/24)"), ("obos", "Modell uten odds (l1/l2=8/24)")):
        _t = (ROOT / liga / "index.html").read_text(encoding="utf-8")
        _m = (ROOT / liga / "modellsjekk" / "index.html").read_text(encoding="utf-8")
        check(f"{liga}: den tekniske teksten sier 28 dager og l1/l2 8/24, og ablasjonen på modellsjekk-siden det samme",
              "<strong>Halveringstiden på fire uker</strong> (28 dager)" in _t and "<strong>Styrken på regulariseringen</strong> (l1/l2 8/24)" in _t
              and rad in _m and all(x not in t for t in (_t, _m) for x in ("(35 dager) for tidsvektingen", "(l1/l2 16/48)", "(l1/l2=16/48)")))

    # 26. Poengjusteringene fra NFF (<liga>/data/justeringer.json): formatet
    # siden og scripts/daglig_revisjon.py regner med. Åsane ble trukket ett
    # poeng i 2026 (vedtak 3.3., registrert 4.3. på fotball.no); siden viste
    # 20 poeng, fotball.no 19.
    import re as _re26
    sys.path.insert(0, str(ROOT / "scripts"))
    from ligaer import oppsett as _opp26
    _dato26 = _re26.compile(r"^20\d\d-[01]\d-[0-3]\d$")
    for liga in ("eliteserien", "obos"):
        _f26 = ROOT / liga / "data" / "justeringer.json"
        check(f"{liga}/data/justeringer.json finnes", _f26.exists())
        if not _f26.exists():
            continue
        _j26 = json.loads(_f26.read_text(encoding="utf-8")).get("justeringer")
        check(f"{liga}/data/justeringer.json: en liste i 'justeringer'", isinstance(_j26, list), str(_j26)[:80])
        for j in _j26 or []:
            hvem = f"{liga} {j.get('lag')} {j.get('dato')}"
            check(f"justering {hvem}: sesong (heltall), lag i ligaen, poeng (heltall ulik 0)",
                  isinstance(j.get("sesong"), int) and j.get("lag") in _opp26(liga)["lag"]
                  and isinstance(j.get("poeng"), int) and not isinstance(j.get("poeng"), bool) and j.get("poeng") != 0, str(j))
            # vedtak og lenke legges inn for hånd; et trekk tabellkontrollen
            # har lagt inn automatisk, har dem ikke ennå.
            check(f"justering {hvem}: dato som ÅÅÅÅ-MM-DD, og vedtak (om det er lagt inn) ikke etter dato",
                  bool(_dato26.match(str(j.get("dato"))))
                  and (j.get("vedtak") is None or (bool(_dato26.match(str(j["vedtak"]))) and j["vedtak"] <= j["dato"])), str(j))
            check(f"justering {hvem}: kilde og årsak, lenke (om den er lagt inn) til en https-side, automatisk som sann/usann",
                  bool(str(j.get("kilde", "")).strip()) and bool(j.get("årsak"))
                  and (j.get("lenke") is None or str(j["lenke"]).startswith("https://"))
                  and isinstance(j.get("automatisk", False), bool)
                  and (not j.get("automatisk") or bool(_dato26.match(str(j.get("oppdaget", ""))[:10]))), str(j))
    _o26 = json.loads((ROOT / "obos" / "data" / "justeringer.json").read_text(encoding="utf-8"))["justeringer"]
    check("obos: Åsane -1 poeng i 2026, registrert 4. mars (vedtak 3. mars), med lenke til vedtaket",
          [(j["sesong"], j["lag"], j["poeng"], j["dato"], j["vedtak"], j.get("lenke")) for j in _o26 if j["lag"] == "Åsane"]
          == [(2026, "Åsane", -1, "2026-03-04", "2026-03-03",
               "https://www.fotball.no/lov-og-reglement/beslutninger-fra-utvalg/2026/poengtrekk-for-asane/")], str(_o26))
    _e26 = json.loads((ROOT / "eliteserien" / "data" / "justeringer.json").read_text(encoding="utf-8"))["justeringer"]
    check("eliteserien: ingen justeringer i 2026 (fotball.no har ingen liste)", [j for j in _e26 if j["sesong"] == 2026] == [], str(_e26))
    # Siden henter filen, og poengJust brukes overalt der poeng regnes.
    for f in ("eliteserien/index.html", "obos/index.html"):
        _t26 = (ROOT / f).read_text(encoding="utf-8")
        check(f"{f}: henter data/justeringer.json og legger poengJust til i tabellen, rundetabellen, P0 (to steder) og basePos",
              "hentFersk('data/justeringer.json')" in _t26
              and _t26.count("P0[i]=b[2]*3+b[3]+poengJust(b[0])") == 2
              and "pts:r.w*3+r.d+just" in _t26 and "pts:b[2]*3+b[3]+poengJust(b[0])" in _t26
              and "const just=poengJust(r.name, end)" in _t26
              and _re26.search(r"pts: ?r\.w\*3\+r\.d[,}]", _t26) is None)
    # Frysingen tar filen med, og grunnlagsporten ser den.
    check("frys_sesong.py fryser justeringer.json", '"justeringer.json"' in (ROOT / "scripts" / "frys_sesong.py").read_text(encoding="utf-8"))

    # 27. Regelen for fotball.no (1.10.2026): den hentes BARE automatisk som
    # reserve når ligasiden ikke svarer, aldri ellers. Ingen daglig revisjon,
    # ingen tabellkontroll og ikke noe krav ved frysing. Hvert kall til
    # nff_source.fetch_all i skriptene skal stå i en reserveblokk for
    # SvarerIkke, og ingen workflow skal kjøre noe som henter derfra.
    import re as _re27
    _kall27 = []
    for _f27 in sorted((ROOT / "scripts").glob("*.py")):
        if _f27.name == "nff_source.py":
            continue
        _l27 = _f27.read_text(encoding="utf-8").splitlines()
        for _i27, _x27 in enumerate(_l27):
            if "nff_source.fetch_all(" in _x27 and not _x27.strip().startswith("#"):
                _kall27.append((_f27.name, _i27 + 1, any("SvarerIkke" in y for y in _l27[max(0, _i27 - 14):_i27])))
    check("fotball.no hentes bare som reserve: hvert nff_source.fetch_all-kall står etter en SvarerIkke fra ligasiden",
          len(_kall27) >= 3 and all(r for _, _, r in _kall27), str(_kall27))
    check("fotball.no: reserven finnes for begge ligaer (update_data, obos_build_data, obos_results)",
          {f for f, _, _ in _kall27} >= {"update_data.py", "obos_build_data.py", "obos_results.py"}, str(_kall27))
    _dr27 = (ROOT / "scripts" / "daglig_revisjon.py").read_text(encoding="utf-8")
    _main27 = _dr27[_dr27.index("def main("):]
    check("den daglige revisjonen bruker kalenderfeeden, ikke fotball.no",
          "hent_kalender" in _main27 and "nff_source.fetch_all" not in _main27 and "nff_source.hent(" not in _main27)
    _fr27 = (ROOT / "scripts" / "frys_sesong.py").read_text(encoding="utf-8")
    _if27 = _fr27[_fr27.index("def ikke_ferdig("):_fr27.index("def tin(")]
    check("frysingen krever tabellkontrollen (samme kjøring, eller den siste vellykkede med uendrede resultater og justeringer), ikke fotball.no",
          "audit_tabell.json" in _if27 and "audit_fixtures.json" not in _if27 and "len(_lag) * (len(_lag) - 1)" in _if27
          and "siste_like" in _if27 and "data_avtrykk" in _if27)
    for _wf27 in ("update-data.yml", "obos-results.yml"):
        _t27 = (ROOT / ".github" / "workflows" / _wf27).read_text(encoding="utf-8")
        _liga27 = "eliteserien" if _wf27 == "update-data.yml" else "obos"
        check(f"{_wf27}: ingen henting fra fotball.no, revisjonen mot kalenderfeeden, varsel om nytt poengtrekk med issues: write, og tabellkontrollens filer i commit-listen",
              "www.fotball.no" not in _t27
              and not any("nff_source" in l for l in _t27.splitlines() if not l.strip().startswith("#"))
              and f"python3 scripts/daglig_revisjon.py {_liga27}" in _t27 and "mot kalenderfeeden" in _t27
              and f"python3 scripts/tabellkontroll.py varsle {_liga27}" in _t27 and "GH_TOKEN: ${{ github.token }}" in _t27
              and _re27.search(r"permissions:\n  contents: write\n  issues: write", _t27) is not None
              and f"{_liga27}/data/audit_tabell.json" in _t27 and f"{_liga27}/data/justeringer.json" in _t27)

    # 28. Betingede tall (2.10.2026): kortet "Neste kamp", svarene og linja om
    # forrige kamp i lagboksen kommer fra grunnlagsfilen når den er i bruk, og
    # ellers fra tabellens simulering (QA_N_BETINGET = MC_N, tabellens frø).
    # Ingen av dem har et eget antall sesonger (før: 2 500, 3 000 og 6 000,
    # og kortet og svaret viste ulike tall for samme kamp). Forrige kamp er i
    # filen på Eliteserien og OBOS, ikke på testsiden (grunnlagMedForrige).
    import re as _re28
    for s_ in ("eliteserien", "obos", "elo-test"):
        _t28 = (ROOT / s_ / "index.html").read_text(encoding="utf-8")
        _konst28 = ("const QA_N_BETINGET = MC_N;", "const QA_CHEER_N = QA_N_BETINGET;", "const QA_LAST_N = QA_N_BETINGET;",
                    "const QA_KEY_N = QA_N_BETINGET;")
        _faste28 = _re28.findall(r"N:\s*\d{3,}", _t28)
        check(f"{s_}/index.html: alle betingede tall med tabellens sesonger (QA_N_BETINGET), ingen fast N i kallene",
              all(k in _t28 for k in _konst28) and _t28.count("N:QA_N_BETINGET") >= 3 and not _faste28
              and "(res.sesonger >= QA_KEY_N_STRAM ? QA_KEY_CLOSE_CI : QA_KEY_CLOSE)" in _t28,
              f"faste N: {_faste28}" if _faste28 else "")
        _med28 = s_ != "elo-test"
        check(f"{s_}/index.html: " + ("forrige kamp i grunnlagsfilen, og linja i lagboksen fra filen når den er i bruk" if _med28
              else "forrige kamp ikke i grunnlagsfilen (ratingen etter det alternative resultatet er ikke i avtrykket), linja fra lastmatch.json"),
              "forrigeOppgaver(m, P0, G0, F0).forEach(x=>tasks.push(x));" in _t28
              and "if(!grunnlagMedForrige()) return tasks;" in _t28
              and "(GRUNNLAG && GRUNNLAG_STATUS==='i bruk' && grunnlagMedForrige())) return null;" in _t28
              and "|| (t.over && !t.id.startsWith('f:'))) return null;" in _t28
              and (_t28.rfind("function grunnlagMedForrige(){ return true; }") > _t28.rfind("function grunnlagMedForrige(){ return false; }")) == _med28)

    # 29. Modellsjekk-sidene (3.10.2026). "Vis detaljer" i "Hvordan vet vi at
    # modellen virker?" er kortet ned, og resten (Brier-tabellene, kontrollen
    # med faste kuttpunkter, hva hvert ledd tilfører, tabellen per fase, log
    # loss for sluttoddsen og metoden, og tabellene for sesongen) står på
    # <liga>/modellsjekk/, bygget av scripts/build_modellsjekk.py. Navnet på
    # den ikke-offentlige oddskilden for OBOS-historikken skal ikke stå i noen
    # fil i repoet (git-historikken skrives ikke om).
    _kilde29 = "odds" + "portal"
    _filer29 = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True).stdout.split("\0")
    _filer29 = [f for f in _filer29 if f] + ["eliteserien/modellsjekk/index.html", "obos/modellsjekk/index.html"]
    _treff29 = []
    for _f in _filer29:
        try:
            if _kilde29 in (ROOT / _f).read_text(encoding="utf-8", errors="ignore").lower():
                _treff29.append(_f)
        except (IsADirectoryError, FileNotFoundError):
            pass
    check("navnet på den ikke-offentlige oddskilden står ikke i noen fil i repoet", not _treff29, ", ".join(_treff29))
    _b29 = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_modellsjekk.py"), "--check"], capture_output=True, text=True)
    check("modellsjekk-sidene er bygget fra kildene (build_modellsjekk.py --check)", _b29.returncode == 0, _b29.stdout.strip())
    # "Med og uten odds" under "Vis detaljer": korte tall, ingen standardfeil og
    # ingen omtale av repoet (3.10.2026). Tallene er fra valideringen 30.9.2026
    # (walkforward/validering/wf_es.log og obos_medodds.log i lab).
    _med29 = {
        "eliteserien": "Lagstyrken og oddsen gjør prosentene mer treffsikre enn uten dem, særlig tidlig i sesongen. I den første fjerdedelen av sesongen er Brier-feilen 0,0180 lavere for gull og 0,0252 lavere for topp 4. Over hele sesongen er forbedringen tydeligst for nedrykk, med 0,0076 lavere Brier-feil.",
        "obos": "Lagstyrken og oddsen gjør prosentene mer treffsikre enn uten dem, særlig tidlig i sesongen. Brier-feilen er 0,0116 lavere for opprykk, 0,0156 lavere for topp 6 og 0,0069 lavere for nedrykk."}
    for _liga29, _sone29 in _med29.items():
        _t29 = (ROOT / _liga29 / "index.html").read_text(encoding="utf-8")
        _a29 = _t29.index("<!-- LIGA-MODELLSJEKK -->")
        _s29 = _t29[_a29:_t29.index("\n</details>", _a29)]     # den ytre </details> står uten innrykk
        _m29 = (ROOT / _liga29 / "modellsjekk" / "index.html").read_text(encoding="utf-8")
        check(f"{_liga29}: Vis detaljer er kortet ned med lenken til modellsjekk-siden, og tabellene står der",
              '<a href="modellsjekk/">Full dokumentasjon av testene</a>' in _s29 and _sone29 in _s29
              and not any(x in _s29 for x in ("Kontroll: faste kuttpunkter", "<table", "Siden ble lansert", 'id="accuracyTall"',
                                              "standardfeil", "repoet", "GitHub", "tabellen alene", "sier tabellen", "Tabellen sier"))
              and "Modellen ble justert igjen 30. september etter ny tilbaketesting." in _s29
              and all(x in _m29 for x in ("Kontroll: faste kuttpunkter", "per fase av sesongen", 'id="accuracyTall"', "Sist validert",
                                          "høyere log loss enn sluttoddsen", "window.tegnTreffsikkerhet")))
    _wf29 = (ROOT / ".github" / "workflows" / "build-leagues.yml").read_text(encoding="utf-8")
    check("build-leagues.yml bygger og committer modellsjekk-sidene",
          "python3 scripts/build_modellsjekk.py" in _wf29 and '"modellsjekk/**"' in _wf29 and "obos/modellsjekk/index.html" in _wf29)

    # Ferske data (3.10.2026): ingen datafil hentes med vanlig fetch(), som
    # kunne gi en opptil ti minutter gammel kopi (GitHub Pages: max-age=600).
    # Alle går gjennom hentFersk (cache: 'no-cache') eller hentSporet, og
    # siden sjekker selv om nye resultater er publisert (sjekkNyeData).
    import re as _re30
    for _side30 in ("eliteserien/index.html", "obos/index.html", "elo-test/index.html"):
        _t30 = (ROOT / _side30).read_text(encoding="utf-8")
        _rene30 = _re30.findall(r"(?<![\w.])fetch\((?:'[^']*\.json'|grunnlagFil\(\)|LEAGUE\.closingOddsFile)", _t30)
        check(f"{_side30}: datafilene hentes uten gammel kopi (hentFersk/hentSporet), og siden ser etter nye data",
              not _rene30 and "const hentFersk = (url, opt) => fetch(url, {cache:'no-cache'" in _t30
              and "hentSporet(" in _t30 and "startDataSjekk();" in _t30, str(_rene30[:3]))

    # Push-konflikt i de genererte filene (26.10.2026): resultatene kommer
    # alltid med. Konflikt laget med vilje i et midlertidig git-oppsett
    # (tests/push_konflikt.py): odds-filene beholder mains versjon,
    # prekick.json og OddsPapi-telleren flettes, andre konflikter feiler som før.
    sys.path.insert(0, str(ROOT / "tests"))
    import push_konflikt
    for _navn, _ok, _detalj in push_konflikt.tester():
        check(_navn, _ok, _detalj)

    # En testkjoring skal ikke etterlate seg noe i produksjonsdataene. Dette
    # gikk galt: hentelogget og OddsPapi-telleren fikk linjer og fakturerbare
    # kall som aldri skjedde, av selve testene.
    #
    # sha256 av hver fil, ikke "git status": status sier ingenting om filer
    # som er .gitignore-et, og heller ingenting om en fil som er endret og
    # lagt til igjen. Summen over innholdet er uavhengig av git.
    _vern.sjekk_urort(check)

    print(f"\n{ok} av {ok + fail} failsafe-tester gikk gjennom.")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
