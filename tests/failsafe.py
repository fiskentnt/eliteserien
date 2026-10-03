#!/usr/bin/env python3
"""Tester at resultatkjeden aldri publiserer noe den ikke skal.

Kjøres av tests/run.sh, uten nett og uten nøkkel: kildene simuleres.
"""
import json
import os
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
        logg_fil(d, "OBOS:_hent_resultater", 200,
                 [("obos", "ntf-resultater", "feil")] * 4 + [("alle", "oddspapi-historical-odds", "feil")] * 3)
        r = sjekk_som(d, "Oppdater kampdata")
        check("kildevakt: eliteseriejobben blir ikke rød av OBOS-jobbens feil",
              r.returncode == 0 and "ntf-resultater" not in r.stderr, (r.stdout + r.stderr)[-200:])
        r = sjekk_som(d, "OBOS: hent resultater")
        check("kildevakt: OBOS-jobben blir rød av sine egne kilder",
              r.returncode == 1 and "obos/ntf-resultater" in r.stderr and "oddspapi-historical-odds" in r.stderr,
              (r.stdout + r.stderr)[-200:])
        r = sjekk_som(d, None)
        check("kildevakt: lokalt, uten jobb, sjekkes alle jobber", r.returncode == 1, (r.stdout + r.stderr)[-200:])
        r = sjekk_som(d, "Oppdater kampdata", "--alle")
        check("kildevakt: --alle sjekker alle jobber også i Actions", r.returncode == 1, (r.stdout + r.stderr)[-200:])
    with tempfile.TemporaryDirectory() as d:
        logg_fil(d, "Oppdater_kampdata", 101, [("eliteserien", "nff", "feil")] * 3)
        logg_fil(d, "OBOS:_hent_resultater", 201, [("obos", "nff", "ok")])
        r = sjekk_som(d, "Oppdater kampdata")
        check("kildevakt: eliteseriejobben blir rød av sine egne kilder",
              r.returncode == 1 and "eliteserien/nff" in r.stderr, (r.stdout + r.stderr)[-200:])
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
    check("elo-test.yml: testsiden er eneste skriver av sin prekick.json og bruker ingen av modusene",
          "--uten-prekick-vindu" not in elo and "--bare-prekick" not in elo and "--ut elo-test/emodell" in elo)

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
        check(f"{s_}/index.html: fast N = 100 000 i grunnlagsfilen (GRUNNLAG_N), versjon 2 med innsiktsblokken", "const GRUNNLAG_VERSJON = 2, GRUNNLAG_N = 100000;" in t)
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
    check("grunnlag.yml: utløses etter datajobbene, oddsjobbene, byggingen av ligasidene og ELO-modellen, med navn som finnes",
          sorted(navn_wf.get(n, "?") for n in utlosere) == ["build-leagues.yml", "elo-test.yml", "obos-results.yml", "prekick-odds.yml", "update-data.yml", "update-odds.yml"],
          str(utlosere))
    check("grunnlag.yml: etter ELO-modellen bare testsiden, etter datajobbene bare ligaene, ellers alle tre",
          '"ELO-test: bygg modellen") sider="elo-test" ;;' in gw and '"") sider="eliteserien obos elo-test" ;;' in gw
          and '*) sider="eliteserien obos" ;;' in gw and "python3 scripts/grunnlag_port.py $sider" in gw)
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
    check("grunnlag.yml: fast N (ingen --n), filen der porten sier, og bare grunnlagsfilen og banneret committes",
          i_rg > 0 and "--n" not in gst[i_rg] and '--ut "$UT"' in gst[i_rg] and "UT: ${{ steps.port.outputs.ut }}" in gst[i_rg]
          and 'git add "$UT/grunnlag.json"\n' in gst[i_lg] and '[ -f "$UT/keymatch.json" ] && git add "$UT/keymatch.json"' in gst[i_lg]
          and gst[i_lg].count("git add") == 2 and "bash scripts/push_med_rebase.sh" in gst[i_lg])
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
