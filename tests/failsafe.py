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
    r = run("--break-wikipedia", "--no-oddspapi")
    check("ødelagt Wikipedia: datasettet er uendret", MATCHES.read_bytes() == before)

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

    # 7. OddsPapi har resultatet, Wikipedia henger etter.
    from datetime import datetime, timedelta, timezone as _tz
    key = next(iter(sched))
    s2 = sched[key]
    kick = datetime.fromisoformat(f"{s2['date']}T{s2['time']}").replace(
        tzinfo=R.ZoneInfo("Europe/Oslo")).astimezone(_tz.utc)
    fersk = kick + timedelta(hours=3)      # tre timer etter avspark
    gammel = kick + timedelta(hours=30)    # over et døgn etter
    # De offisielle kildene (NTF og NFF) har alt blitt enige i reconcile().
    # Da skal resultatet ut med en gang -- Wikipedia er en ekstra kontroll,
    # ikke et krav. Uten dette ville et ferskt resultat blitt staaende i 24
    # timer bare fordi ingen hadde rukket aa redigere Wikipedia-rutenettet.
    pub, conf, vent = R.decide({key: (2, 1)}, {}, {}, sched, {}, fersk)
    check("offisielt alene, fersk kamp: publiseres med en gang",
          pub.get(key) == (2, 1) and not conf and not vent, f"{pub.get(key)} {conf} {vent}")
    pub, conf, vent = R.decide({key: (2, 1)}, {}, {key: (2, 1)}, sched, {}, fersk)
    check("offisielt og Wikipedia enige: publiseres", pub.get(key) == (2, 1) and not conf)
    pub, conf, vent = R.decide({key: (2, 1)}, {}, {key: (1, 1)}, sched, {}, fersk)
    check("offisielt, men Wikipedia uenig: holdes tilbake",
          key not in pub and len(conf) == 1, f"{pub.get(key)} {conf}")

    # OddsPapi er siste utvei og teller fortsatt bare som EN kilde.
    pub, conf, vent = R.decide({}, {key: (2, 1)}, {}, sched, {}, fersk)
    check("OddsPapi alene, fersk kamp: venter, ingen konflikt",
          key not in pub and not conf and len(vent) == 1, f"{pub.get(key)} {conf} {vent}")
    pub, conf, vent = R.decide({}, {key: (2, 1)}, {}, sched, {}, gammel)
    check("OddsPapi alene, over et døgn: publiseres", pub.get(key) == (2, 1) and not conf)
    pub, conf, vent = R.decide({}, {key: (2, 1)}, {key: (2, 1)}, sched, {}, fersk)
    check("OddsPapi og Wikipedia enige: publiseres med en gang",
          pub.get(key) == (2, 1) and not conf)
    pub, conf, vent = R.decide({}, {key: (2, 1)}, {key: (1, 1)}, sched, {}, gammel)
    check("OddsPapi og Wikipedia uenige: holdes tilbake og logges",
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
        check(f"statistikk: {navn} teller stien, ikke scenariet",
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
    # Hele fetch_all, med sidene fra en lokal mappe og matches.json fra repoet.
    import tempfile as _tf
    import hentelogg as HL2
    with _tf.TemporaryDirectory() as d:
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

    # 20. Tidsporten for The Odds API (update-odds.yml via planleggeren hvert
    # tiende minutt). Porten avgjør, uten filer: hver 12. time over 48 timer
    # til neste avspark, hver 4. ved 6-48 timer, hver time under 6 timer (og
    # derfor fram til siste avspark den dagen); én time sperre etter et
    # mislykket forsøk; budsjettvakt (under 100 + 4 per gjenstående dag i
    # måneden: tilbake til 12 timer); ingen henting uten kamp innen 7 dager
    # eller med stanset kvote; FORCE tvinger. Falsk klokke.
    import should_fetch_odds as SFO
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    naa = _dt(2026, 10, 7, 12, 0, tzinfo=_tz.utc)          # onsdag, midt i måneden
    def fx(*kamper):   # (dato, tid, spilt) -> fixtures.json-form
        return [{"round": 23, "matches": [{"home": f"H{i}", "away": f"B{i}", "date": d, "time": t, "played": sp}
                                          for i, (d, t, sp) in enumerate(kamper)]}]
    def kvote(timer_siden, igjen=400, mnd=None):
        t = naa - _td(hours=timer_siden)
        return {"remaining": igjen, "checked_at": (t if mnd is None else mnd).isoformat()}
    def v(fix, q, st=None, force=False, n=naa):
        return SFO.vurder(n, fix, q, st, force=force)[0]
    # neste avspark 9.10 19:00 norsk = 17:00 UTC, 53 timer fram: 12 timer
    langt = fx(("2026-10-09", "19:00", False))
    check("odds-port: over 48 t til avspark: 11 t siden siste henting -> vent", v(langt, kvote(11)) is False)
    check("odds-port: over 48 t til avspark: 13 t siden siste henting -> hent", v(langt, kvote(13)) is True)
    # neste avspark 8.10 19:00 norsk = 17:00 UTC, 29 timer fram: 4 timer
    naer = fx(("2026-10-08", "19:00", False))
    check("odds-port: 6-48 t til avspark: 3 t siden -> vent, 5 t siden -> hent",
          v(naer, kvote(3)) is False and v(naer, kvote(5)) is True)
    # neste avspark i dag 17:00 norsk = 15:00 UTC, 3 timer fram: hver time
    idag = fx(("2026-10-07", "17:00", False), ("2026-10-07", "20:00", False))
    check("odds-port: under 6 t til avspark: 50 min siden -> vent, 70 min siden -> hent",
          v(idag, kvote(50 / 60)) is False and v(idag, kvote(70 / 60)) is True)
    # etter første avspark (16:00 UTC): neste er dagens siste, 20:00 norsk = 18:00 UTC -> fortsatt hver time
    etter = naa.replace(hour=16)
    check("odds-port: mellom to avspark samme dag gjelder fortsatt hver time",
          SFO.intervall_timer(etter, idag)[0] == 1)
    # sperre: forsøk for 30 min siden etter siste vellykkede -> vent, selv om intervallet er passert
    st30 = {"siste_forsok": (naa - _td(minutes=30)).isoformat()}
    st70 = {"siste_forsok": (naa - _td(minutes=70)).isoformat()}
    check("odds-port: mislykket forsøk for 30 min siden -> sperre; for 70 min siden -> hent",
          v(langt, kvote(20), st30) is False and v(langt, kvote(20), st70) is True)
    check("odds-port: et forsøk som GIKK BRA (eldre enn siste henting) gir ingen sperre",
          v(idag, kvote(70 / 60), {"siste_forsok": (naa - _td(minutes=75)).isoformat()}) is True)
    # budsjettvakt: 7.10, 25 dager igjen -> krav 100 + 4*25 = 200
    check("odds-port: budsjettvakten: 190 kreditter igjen -> tilbake til 12 t (2 t siden -> vent)",
          v(idag, kvote(2, igjen=190)) is False and v(idag, kvote(13, igjen=190)) is True)
    check("odds-port: budsjettvakten slår ikke til med nok kreditter (210 igjen, 2 t siden -> hent)",
          v(idag, kvote(2, igjen=210)) is True)
    check("odds-port: lavt tall fra FORRIGE måned teller ikke i budsjettvakten",
          v(idag, kvote(0, igjen=120, mnd=_dt(2026, 9, 30, 20, 0, tzinfo=_tz.utc))) is True)
    check("odds-port: ingen uspilt kamp innen 7 dager -> ingen henting",
          v(fx(("2026-10-20", "19:00", False)), kvote(48)) is False and v(fx(("2026-10-08", "19:00", True)), kvote(48)) is False)
    check("odds-port: stanset kvote denne måneden -> ingen henting",
          v(idag, {"remaining": 90, "checked_at": (naa - _td(hours=5)).isoformat(), "stopped_until_month": "2026-10"}) is False)
    check("odds-port: FORCE tvinger henting", v(idag, kvote(0), st30, force=True) is True)
    check("odds-port: ingen tidligere henting -> hent", v(idag, None) is True)
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
