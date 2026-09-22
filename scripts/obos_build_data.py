#!/usr/bin/env python3
"""Bygger datafilene OBOS-siden leser, fra obos/data/obos_2012-2026.csv.

  obos/data/matches.json   spilte kamper i 2026 (dato, tid, runde, lag, mål)
  obos/data/fixtures.json  rundene det står kamper igjen i, med played-flagg
  obos/data/model.json     lagstyrkene, tilpasset på 2026-kampene (uten odds)
  obos/data/status.json    når filene sist ble bygget

Samme format som eliteserien/data/, så sidekoden er felles. Modellen tilpasses
med de samme parameterne som Eliteserien (l1/l2 = 16/48, halveringstid 35
dager), men uten oddsleddet: OBOS-historikken har ingen odds før 2026, og
tilbaketesten viste at parameterne holder (se scripts/backtest_zones.py).

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

ROOT = Path(__file__).parent.parent
DATA = ROOT / "obos" / "data"
CSV_PATH = DATA / "obos_2012-2026.csv"
SEASON = "2026"
HALF_LIFE, L1, L2 = 35.0, 16.0, 48.0


def rows_for(season=SEASON):
    out = []
    for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")):
        if r["sesong"] != season:
            continue
        out.append({
            "round": int(r["runde"]), "date": r["dato"], "time": r["tid"],
            "home": r["hjemme"], "away": r["borte"],
            "hg": int(float(r["hjemmemaal"])) if r["hjemmemaal"] else None,
            "ag": int(float(r["bortemaal"])) if r["bortemaal"] else None,
        })
    out.sort(key=lambda m: (m["date"], m["time"], m["home"]))
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

    # Modellen: samme tilpasning som Eliteserien, men uten oddsleddet.
    TI = {t: i for i, t in enumerate(teams)}
    fit_matches = [{"date": m["date"], "home": m["home"], "away": m["away"],
                    "hg": m["hg"], "ag": m["ag"], "odds": None} for m in played]
    ref = max(m["date"] for m in played) if played else date.today().isoformat()
    res = fit_fast.fit_model_fast(fit_matches, teams, TI, odds_weight=0.0,
                                  half_life_goals=HALF_LIFE, half_life_odds=HALF_LIFE,
                                  l1=L1, l2=L2, ref_date=ref, isolate_global=True)
    model = {
        "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": teams, "mu": res["mu"], "H": res["H"],
        "att": list(res["att"]), "con": list(res["con"]),
        "ha": list(res["ha"]), "hc": list(res["hc"]),
        "meta": {"league": "OBOS-ligaen", "season": int(SEASON), "matches": len(played),
                 "odds_weight": 0.0, "half_life_days": HALF_LIFE, "l1": L1, "l2": L2,
                 "note": "Tilpasset uten odds: OBOS-historikken har ingen odds før 2026."},
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
