#!/usr/bin/env python3
"""Bygger datafilene OBOS-siden leser, fra obos/data/obos_2012-2026.csv.

  obos/data/matches.json   spilte kamper i 2026 (dato, tid, runde, lag, mål)
  obos/data/fixtures.json  rundene det står kamper igjen i, med played-flagg
  obos/data/model.json     lagstyrkene, tilpasset på 2026-kampene
  obos/data/status.json    når filene sist ble bygget

Samme format som eliteserien/data/, så sidekoden er felles. Modellen tilpasses
med de samme parameterne som Eliteserien (l1/l2 = 16/48, halveringstid 35
dager). Oddsleddet er med når obos/data/odds_closing.json har sluttodds, og
ellers faller den tilbake til bare mål. --no-odds slår oddsleddet av.

Tilbaketesten i scripts/backtest_zones.py er kjørt UTEN odds: OBOS-historikken
har ingen odds før 2026, så oddsleddet er ikke validert på denne ligaen.

  python3 scripts/obos_build_data.py
"""
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fit_fast
import leaguedata
import oddslib

ROOT = Path(__file__).parent.parent
DATA = ROOT / "obos" / "data"
CSV_PATH = DATA / "obos_2012-2026.csv"
SEASON = "2026"
HALF_LIFE, L1, L2 = 35.0, 16.0, 48.0
# Samme vekt som Eliteserien. Målt på OBOS-tall 22. september 2026 med
# scripts/obos_odds_weight.py (136 kamper ut av utvalg): vekt 80 målte best,
# men 1,9 standardfeil fra 40 er innenfor støyen, og rekkefølgen mellom
# vektene er ikke jevn. Vekten er derfor ikke endret. Måles på nytt når
# sesongen er ferdigspilt, se TODO.md.
ODDS_WEIGHT = 40.0
ODDS_PATH = DATA / "odds_closing.json"


def rows_for(season=SEASON, log=lambda s: None):
    """Kampene i sesongen.

    Runde, dato og avspark kommer fra den offisielle ligakilden, ikke fra
    CSV-en. CSV-en er et statisk øyeblikksbilde som ingen kode skriver til,
    så en flyttet kamp ville aldri blitt fanget opp der. Resultatene
    beholdes fra den eksisterende kjeden (obos_results.py), som har regelen
    om at ingenting publiseres før to kilder er enige.

    CSV-en er fortsatt fasit for sesongene 2012-2025, som er ferdige og
    ikke har noen kilde å hente fra lenger.
    """
    fra_csv = []
    for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")):
        if r["sesong"] != season:
            continue
        fra_csv.append({
            "round": int(r["runde"]), "date": r["dato"], "time": r["tid"],
            "home": r["hjemme"], "away": r["borte"],
            "hg": int(float(r["hjemmemaal"])) if r["hjemmemaal"] else None,
            "ag": int(float(r["bortemaal"])) if r["bortemaal"] else None,
        })

    if season != SEASON:
        fra_csv.sort(key=lambda m: (m["date"], m["time"], m["home"]))
        return fra_csv

    import ntf_source, nff_source
    from reconcile_ny import reconcile
    try:
        ntf = ntf_source.fetch_all("obos", log=log)
    except Exception as e:
        log(f"ADVARSEL: ligasiden feilet ({e}) -- bruker CSV-terminlisten "
            f"denne kjøringen. En kamp som er flyttet i dag blir da ikke fanget opp.")
        fra_csv.sort(key=lambda m: (m["date"], m["time"], m["home"]))
        return fra_csv
    try:
        nff = nff_source.fetch_all("obos", log=log)
    except Exception as e:
        log(f"ADVARSEL: fotball.no feilet ({e}) -- ingen uavhengig kontroll av "
            f"terminlisten denne kjøringen.")
        nff = []

    offisiell = reconcile(ntf, nff, reserver=[("csv", fra_csv)], log=log)
    resultat = {(r["home"], r["away"]): r for r in fra_csv}
    out = []
    for r in offisiell:
        egen = resultat.get((r["home"], r["away"]), {})
        out.append({"round": r["round"], "date": r["date"], "time": r["time"],
                    "home": r["home"], "away": r["away"],
                    "hg": egen.get("hg"), "ag": egen.get("ag")})
    out.sort(key=lambda m: (m["date"], m["time"], m["home"]))
    return out


def load_closing_odds():
    """Sluttoddsen per kamp, som de-viggede sannsynligheter (H, U, B).

    Nøkkelen er hjemmelag og bortelag, aldri datoen: en flyttet kamp er den
    samme kampen. Filen fylles av scripts/obos_closing_odds.py.
    """
    if not ODDS_PATH.exists():
        return {}
    d = json.loads(ODDS_PATH.read_text(encoding="utf-8"))
    out = {}
    for key, v in d.get("matches", {}).items():
        o = v.get("odds")
        if not o or not v.get("bookmaker"):
            continue
        parts = key.split("|")
        if len(parts) != 3:
            continue
        out[(parts[1], parts[2])] = oddslib.devig(o["H"], o["U"], o["B"])
    return out


def main():
    from_matches = "--from-matches" in sys.argv
    rows = rows_for()
    if from_matches and (DATA / "matches.json").exists():
        # Resultatene kommer fra resultatkjeden, ikke fra CSV-en: CSV-en er bare
        # terminlisten etter at sesongen er i gang.
        pub = {(m["home"], m["away"]): (m["hg"], m["ag"])
               for m in json.loads((DATA / "matches.json").read_text(encoding="utf-8"))}
        for m in rows:
            v = pub.get((m["home"], m["away"]))
            m["hg"], m["ag"] = (v if v else (None, None))
        print(f"  bruker {len(pub)} resultater fra matches.json")
    played = [m for m in rows if m["hg"] is not None]
    teams = sorted({m["home"] for m in rows} | {m["away"] for m in rows})
    if len(teams) != 16:
        print(f"FEIL: fant {len(teams)} lag, ventet 16", file=sys.stderr)
        return 1
    print(f"{len(rows)} kamper i {SEASON}, {len(played)} spilte, {len(teams)} lag")

    DATA.mkdir(parents=True, exist_ok=True)
    # Formen på begge filene, og reglene for hvilke runder som blir med, er
    # felles med Eliteserien -- se scripts/leaguedata.py.
    leaguedata.write_json(DATA / "matches.json", leaguedata.build_matches(rows), indent=1)
    fixtures = leaguedata.build_fixtures(rows)
    leaguedata.write_json(DATA / "fixtures.json", fixtures, indent=1)
    print(f"  {len(fixtures)} runder med kamper igjen")

    # Modellen: samme tilpasning som Eliteserien. Oddsleddet er med når vi har
    # sluttodds (obos/data/odds_closing.json, Pinnacle via OddsPapi), ellers
    # faller den tilbake til bare mål. --no-odds slår det av, til sammenligning.
    TI = {t: i for i, t in enumerate(teams)}
    closing = load_closing_odds() if "--no-odds" not in sys.argv else {}
    fit_matches = [{"date": m["date"], "home": m["home"], "away": m["away"],
                    "hg": m["hg"], "ag": m["ag"],
                    "odds": closing.get((m["home"], m["away"]))} for m in played]
    n_odds = sum(1 for m in fit_matches if m["odds"])
    odds_weight = ODDS_WEIGHT if n_odds else 0.0
    print(f"  odds: {n_odds} av {len(played)} spilte kamper, vekt {odds_weight}")
    ref = max(m["date"] for m in played) if played else date.today().isoformat()
    res = fit_fast.fit_model_fast(fit_matches, teams, TI, odds_weight=odds_weight,
                                  half_life_goals=HALF_LIFE, half_life_odds=HALF_LIFE,
                                  l1=L1, l2=L2, ref_date=ref, isolate_global=True)
    model = {
        "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": teams, "mu": res["mu"], "H": res["H"],
        "att": list(res["att"]), "con": list(res["con"]),
        "ha": list(res["ha"]), "hc": list(res["hc"]),
        "meta": {"league": "OBOS-ligaen", "season": int(SEASON), "matches": len(played),
                 "odds_weight": odds_weight, "n_odds_matches": n_odds, "ref_date": ref,
                 "half_life_days": HALF_LIFE, "l1": L1, "l2": L2,
                 "note": ("Sluttodds fra Pinnacle via OddsPapi, samme vekt som Eliteserien."
                          if n_odds else
                          "Tilpasset uten odds: ingen sluttodds tilgjengelig.")},
    }
    (DATA / "model.json").write_text(json.dumps(model, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")
    print(f"  mu={res['mu']:.3f} H={res['H']:.3f}, sterkeste lag: "
          f"{teams[max(range(len(teams)), key=lambda i: res['att'][i])]}")

    (DATA / "status.json").write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "obos/data/obos_2012-2026.csv", "played": len(played),
        "last_match": max((m["date"] for m in played), default=None),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    if not (DATA / "odds_upcoming.json").exists():
        (DATA / "odds_upcoming.json").write_text(
            json.dumps({"matches": [], "fetched_at": None}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    print("  skrev matches.json, fixtures.json, model.json, status.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
