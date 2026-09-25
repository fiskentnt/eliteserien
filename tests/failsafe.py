#!/usr/bin/env python3
"""Tester at resultatkjeden aldri publiserer noe den ikke skal.

Kjøres av tests/run.sh, uten nett og uten nøkkel: kildene simuleres.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
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

    print(f"\n{ok} av {ok + fail} failsafe-tester gikk gjennom.")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
