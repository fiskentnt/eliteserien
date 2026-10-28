"""Push-konflikt laget med vilje (26.10.2026), for scripts/push_med_rebase.sh og
scripts/flett_konflikt.py. Brukes av tests/failsafe.py; kan også kjøres alene:

  python3 tests/push_konflikt.py

Et ekte git-oppsett i en midlertidig mappe: en sentral kopi (bare) og to
kloner. «avspark» spiller «Odds nær avspark» og pusher først; «resultater»
spiller resultatjobben, har endret de samme filene og kommer etter, med
lagre-stegets `git pull --rebase --autostash origin main || true` og så
push_med_rebase.sh. Begge ligaene er med.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(cwd, *a, check=True):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=check)


def _skriv(rot, sti, data):
    p = Path(rot) / sti
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _les(rot, sti):
    return json.loads((Path(rot) / sti).read_text(encoding="utf-8"))


def _rad(dato, stamp, frosset=False, H=0.5):
    return {"home": "A", "away": "B", "date": dato, "H": H, "U": 0.25, "B": 1 - H - 0.25, "stamp": stamp, "frosset": frosset}


START = {
    "obos/data/odds_upcoming.json": {"fetched_at": "2026-10-25T15:00:00+00:00", "matches": [{"home": "Lyn", "away": "Moss", "H": 0.5, "D": 0.25, "A": 0.25}]},
    "eliteserien/data/odds_upcoming.json": {"fetched_at": "2026-10-25T15:00:00+00:00", "matches": [{"home": "Brann", "away": "Molde", "H": 0.5, "D": 0.25, "A": 0.25}]},
    "obos/data/oddspapi_markets.json": {"hentet": "2026-10-25T15:00:00+00:00", "n": 1},
    "obos/data/oddspapi_fixtures_2026.json": {"hentet": "2026-10-25T15:00:00+00:00", "n": 1},
    "obos/data/prekick.json": {"version": 1, "matches": {"2026|Lyn|Moss": _rad("2026-10-25", "2026-10-25T14:00:00Z")}},
    "eliteserien/data/prekick.json": {"version": 1, "matches": {"2026|Brann|Molde": _rad("2026-10-25", "2026-10-25T14:00:00Z")}},
    "data/oddspapi_usage.json": {"note": "teller", "monthly_limit": 250, "months": {"2026-10": {"billable": 10, "endpoints": {"/v4/fixtures": 3}, "last": "2026-10-25T10:00:00+00:00"}}},
    "obos/data/matches.json": [{"home": "Lyn", "away": "Moss", "hg": None, "ag": None}],
    "data/indexnow.json": {"note": "x", "adresser": {"https://tabellkalkulator.no/": {"meldt": "2026-10-24T10:00:00Z", "hash": "h0"}},
                           "dager": {"2026-10-24": 20}},
}


def _oppsett(d):
    sentral, avs, res = Path(d) / "sentral.git", Path(d) / "avspark", Path(d) / "resultater"
    _git(d, "init", "-q", "--bare", "-b", "main", str(sentral))
    _git(d, "clone", "-q", str(sentral), str(avs))
    for sti, data in START.items():
        _skriv(avs, sti, data)
    for s in ("push_med_rebase.sh", "flett_konflikt.py"):
        (avs / "scripts").mkdir(exist_ok=True)
        shutil.copy(ROOT / "scripts" / s, avs / "scripts" / s)
    for c in (avs,):
        _git(c, "config", "user.name", "test"); _git(c, "config", "user.email", "test@test")
    _git(avs, "add", "-A"); _git(avs, "commit", "-q", "-m", "start"); _git(avs, "push", "-q", "origin", "main")
    _git(d, "clone", "-q", str(sentral), str(res))
    _git(res, "config", "user.name", "test"); _git(res, "config", "user.email", "test@test")
    return sentral, avs, res


def _avspark_pusher(avs):
    """«Odds nær avspark»: nye priser, fryser Lyn-Moss, ny kamp i prekick, to tellende kall."""
    _skriv(avs, "obos/data/odds_upcoming.json", {"fetched_at": "2026-10-25T15:11:00+00:00", "matches": [{"home": "Lyn", "away": "Moss", "H": 0.6, "D": 0.2, "A": 0.2}]})
    _skriv(avs, "eliteserien/data/odds_upcoming.json", {"fetched_at": "2026-10-25T15:11:00+00:00", "matches": [{"home": "Brann", "away": "Molde", "H": 0.6, "D": 0.2, "A": 0.2}]})
    _skriv(avs, "obos/data/oddspapi_markets.json", {"hentet": "2026-10-25T15:11:00+00:00", "n": 2})
    p = _les(avs, "obos/data/prekick.json")
    p["matches"]["2026|Lyn|Moss"] = _rad("2026-10-25", "2026-10-25T15:11:00Z", frosset=True, H=0.61)
    p["matches"]["2026|Odd|Hodd"] = _rad("2026-10-25", "2026-10-25T15:11:00Z", frosset=True, H=0.55)
    _skriv(avs, "obos/data/prekick.json", p)
    e = _les(avs, "eliteserien/data/prekick.json")
    e["matches"]["2026|Viking|Start"] = _rad("2026-10-25", "2026-10-25T15:11:00Z", frosset=True)
    _skriv(avs, "eliteserien/data/prekick.json", e)
    u = _les(avs, "data/oddspapi_usage.json")
    u["months"]["2026-10"]["billable"] += 2; u["months"]["2026-10"]["endpoints"]["/v4/fixtures"] += 2
    u["months"]["2026-10"]["last"] = "2026-10-25T15:11:00+00:00"
    _skriv(avs, "data/oddspapi_usage.json", u)
    # Den andre grunnlag-jobben har meldt sine sider (IndexNow, 28.10.2026).
    ix = _les(avs, "data/indexnow.json")
    ix["adresser"]["https://tabellkalkulator.no/obos/"] = {"meldt": "2026-10-25T15:11:00Z", "hash": "o1"}
    ix["adresser"]["https://tabellkalkulator.no/"] = {"meldt": "2026-10-25T15:11:00Z", "hash": "f1"}
    ix["dager"]["2026-10-25"] = 2
    _skriv(avs, "data/indexnow.json", ix)
    _git(avs, "commit", "-q", "-am", "Odds nær avspark"); _git(avs, "push", "-q", "origin", "main")


def _resultater_committer(res, bare_odds=False, ekstra_konflikt=False):
    """Resultatjobben, startet før avspark-jobben pushet: egen odds, egen
    prekick-rad, ett tellende kall og, om ikke bare_odds, et nytt resultat."""
    _skriv(res, "obos/data/odds_upcoming.json", {"fetched_at": "2026-10-25T15:12:00+00:00", "matches": [{"home": "Lyn", "away": "Moss", "H": 0.55, "D": 0.25, "A": 0.2}]})
    if not bare_odds:
        _skriv(res, "eliteserien/data/odds_upcoming.json", {"fetched_at": "2026-10-25T15:12:00+00:00", "matches": []})
        _skriv(res, "obos/data/oddspapi_markets.json", {"hentet": "2026-10-25T15:12:00+00:00", "n": 3})
        p = _les(res, "obos/data/prekick.json")
        p["matches"]["2026|Lyn|Moss"] = _rad("2026-10-25", "2026-10-25T15:12:00Z", H=0.52)
        p["matches"]["2026|Sogndal|Bryne"] = _rad("2026-10-26", "2026-10-25T15:12:00Z")
        _skriv(res, "obos/data/prekick.json", p)
        u = _les(res, "data/oddspapi_usage.json")
        u["months"]["2026-10"]["billable"] += 1; u["months"]["2026-10"]["endpoints"]["/v4/fixtures"] += 1
        u["months"]["2026-10"]["endpoints"]["/v4/scores"] = 1
        u["months"]["2026-10"]["last"] = "2026-10-25T15:12:00+00:00"
        _skriv(res, "data/oddspapi_usage.json", u)
        _skriv(res, "obos/data/matches.json", [{"home": "Lyn", "away": "Moss", "hg": 2, "ag": 1}])
        ix = _les(res, "data/indexnow.json")
        ix["adresser"]["https://tabellkalkulator.no/eliteserien/"] = {"meldt": "2026-10-25T15:12:00Z", "hash": "e1"}
        ix["adresser"]["https://tabellkalkulator.no/"] = {"meldt": "2026-10-25T15:12:00Z", "hash": "f2"}
        ix["dager"]["2026-10-25"] = 2
        _skriv(res, "data/indexnow.json", ix)
    if ekstra_konflikt:
        _skriv(res, "obos/data/oddspapi_markets.json", {"hentet": "x", "n": 9})
        (Path(res) / "annen.txt").write_text("egen\n")
    _git(res, "add", "-A"); _git(res, "commit", "-q", "-m", "OBOS: resultater oppdatert")


def _lagre(res):
    """Lagre-steget i obos-results.yml: pull --rebase || true, så push_med_rebase.sh."""
    _git(res, "pull", "--rebase", "--autostash", "origin", "main", check=False)
    return subprocess.run(["bash", str(ROOT / "scripts" / "push_med_rebase.sh")], cwd=res, capture_output=True, text=True,
                          env={**__import__("os").environ, "GITHUB_REF_NAME": "main"})


def tester():
    """Liste av (navn, ok, detalj)."""
    ut = []
    with tempfile.TemporaryDirectory() as d:
        sentral, avs, res = _oppsett(d)
        _resultater_committer(res)
        _avspark_pusher(avs)
        r = _lagre(res)
        sjekk = Path(d) / "sjekk"
        _git(d, "clone", "-q", str(sentral), str(sjekk))
        logg = [l for l in (r.stdout + r.stderr).splitlines() if "Konflikt" in l or "Pushet" in l or "FEIL" in l]
        ut.append(("push-konflikt: resultatjobben pusher selv om avspark-jobben skrev de samme filene, og resultatet kommer med",
                   r.returncode == 0 and _les(sjekk, "obos/data/matches.json")[0]["hg"] == 2, logg))
        ut.append(("push-konflikt: odds_upcoming.json (begge ligaene) og oddspapi_markets.json: mains versjon beholdes",
                   _les(sjekk, "obos/data/odds_upcoming.json")["matches"][0]["H"] == 0.6
                   and _les(sjekk, "eliteserien/data/odds_upcoming.json")["matches"][0]["H"] == 0.6
                   and _les(sjekk, "obos/data/oddspapi_markets.json")["n"] == 2, ""))
        pk = _les(sjekk, "obos/data/prekick.json")["matches"]
        ut.append(("push-konflikt: prekick.json flettes, kampene fra begge sidene er med, og den fryste raden vinner over en senere ufryst",
                   set(pk) == {"2026|Lyn|Moss", "2026|Odd|Hodd", "2026|Sogndal|Bryne"} and pk["2026|Lyn|Moss"]["frosset"] is True
                   and pk["2026|Lyn|Moss"]["H"] == 0.61 and "2026|Viking|Start" in _les(sjekk, "eliteserien/data/prekick.json")["matches"],
                   sorted(pk)))
        u = _les(sjekk, "data/oddspapi_usage.json")["months"]["2026-10"]
        ut.append(("push-konflikt: oddspapi_usage.json flettes: 10 + 2 + 1 tellende kall, endepunktene summeres, siste tidspunkt beholdes",
                   u["billable"] == 13 and u["endpoints"] == {"/v4/fixtures": 6, "/v4/scores": 1} and u["last"] == "2026-10-25T15:12:00+00:00", u))
        ix = _les(sjekk, "data/indexnow.json")
        ut.append(("push-konflikt: data/indexnow.json flettes: alle adressene med den nyeste innmeldingen, og antallet per dag summeres (2 + 2)",
                   set(ix["adresser"]) == {"https://tabellkalkulator.no/", "https://tabellkalkulator.no/obos/", "https://tabellkalkulator.no/eliteserien/"}
                   and ix["adresser"]["https://tabellkalkulator.no/"]["hash"] == "f2" and ix["dager"] == {"2026-10-24": 20, "2026-10-25": 4}, ix))
    with tempfile.TemporaryDirectory() as d:
        sentral, avs, res = _oppsett(d)
        _resultater_committer(res, bare_odds=True)
        _avspark_pusher(avs)
        r = _lagre(res)
        sjekk = Path(d) / "sjekk"
        _git(d, "clone", "-q", str(sentral), str(sjekk))
        ut.append(("push-konflikt: endret resultatjobben bare odds-fila, blir commiten tom og hoppes over, og pushen lykkes",
                   r.returncode == 0 and _les(sjekk, "obos/data/odds_upcoming.json")["matches"][0]["H"] == 0.6,
                   (r.stdout + r.stderr)[-300:]))
    with tempfile.TemporaryDirectory() as d:
        sentral, avs, res = _oppsett(d)
        (Path(avs) / "annen.txt").write_text("main\n"); _git(avs, "add", "annen.txt")
        _git(avs, "commit", "-q", "-m", "annen fil"); _git(avs, "push", "-q", "origin", "main")
        _git(res, "pull", "-q", "origin", "main")
        (Path(avs) / "annen.txt").write_text("main 2\n"); _git(avs, "commit", "-q", "-am", "annen fil 2"); _git(avs, "push", "-q", "origin", "main")
        _resultater_committer(res, ekstra_konflikt=True)
        r = _lagre(res)
        sjekk = Path(d) / "sjekk"
        _git(d, "clone", "-q", str(sentral), str(sjekk))
        ut.append(("push-konflikt: konflikt i en annen fil løses ikke automatisk: skriptet feiler som før og main er urørt",
                   r.returncode != 0 and (sjekk / "annen.txt").read_text() == "main 2\n" and _les(sjekk, "obos/data/matches.json")[0]["hg"] is None,
                   (r.stdout + r.stderr)[-300:]))
    return ut


if __name__ == "__main__":
    for navn, ok, detalj in tester():
        print(("  ✓ " if ok else "  ✗ ") + navn + ("" if ok else f"\n      {detalj}"))
