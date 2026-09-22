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
    pub, conf, vent = R.decide({key: (2, 1)}, {}, sched, {}, fersk)
    check("OddsPapi alene, fersk kamp: venter, ingen konflikt",
          key not in pub and not conf and len(vent) == 1, f"{pub.get(key)} {conf} {vent}")
    pub, conf, vent = R.decide({key: (2, 1)}, {}, sched, {}, gammel)
    check("OddsPapi alene, over et døgn: publiseres", pub.get(key) == (2, 1) and not conf)
    pub, conf, vent = R.decide({key: (2, 1)}, {key: (2, 1)}, sched, {}, fersk)
    check("begge kilder enige: publiseres med en gang", pub.get(key) == (2, 1) and not conf)
    pub, conf, vent = R.decide({key: (2, 1)}, {key: (1, 1)}, sched, {}, gammel)
    check("kildene uenige: holdes tilbake og logges",
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

    print(f"\n{ok} av {ok + fail} failsafe-tester gikk gjennom.")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
