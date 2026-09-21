"""Tilpasser Poisson-modellen (mål + oddskalibrering) og skriver data/model.json.

Kjøres av workflowen etter hver oppdatering av kamper eller odds. index.html
leser kun parameterne herfra — ingen tilpasning skjer lenger i nettleseren.

Vekt og halveringstid er valgt via rullerende out-of-sample-evaluering
(log loss på utfall, Poisson-NLL på mål, RPS på målforskjell): vekt 40,
halveringstid 35 dager for både mål og odds. Se undersøkelsen i samtalen
som førte fram til disse tallene.

l1/l2 (ridge-straff på henholdsvis att/con og ha/hc) ble satt til 16/48
(8x de opprinnelige 2/6) etter en egen undersøkelse av at simulerte
sesonger fikk urealistisk stor målforskjell (opptil ±1400, mot ekte
sesongers ±60-70) sammenlignet med NOR.csv 2012-2026. Testet 1x-20x på
rullerende log loss/Poisson-NLL for enkeltkamper OG på målforskjell-
fordelingen i simulerte sesonger: begge pekte uavhengig av hverandre på
rundt 8x som optimum -- svakere gir dårligere enkeltkamp-treffsikkerhet
(mindre regularisert, mer overtilpasset), sterkere begynner å viske ut
reelle styrkeforskjeller. Ved 8x falt simulert målforskjell til 15,9,
nesten nøyaktig likt de faktiske 15,9 for de samme sesongene, og log
loss/Poisson-NLL var samtidig de BESTE observerte (1,0008/3,0897, mot
1,0040/3,1086 ved 1x) -- ikke en avveining, samme retning på begge mål.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fit_fast

ROOT = Path(__file__).parent.parent
LEAGUE = ROOT / "eliteserien"  # ligamappen (data/ ligger under den, så flere ligaer kan komme ved siden av)
ODDS_WEIGHT = 40.0
HALF_LIFE_DAYS = 35.0
L1, L2 = 16.0, 48.0

WATCH_TEAMS = ["Brann", "Bodø/Glimt"]  # logges før/etter hver tilpasning, til overvåking av kjøringene


def log_watch_teams(label, log):
    model_path = LEAGUE / "data" / "model.json"
    if not model_path.exists():
        return
    m = json.loads(model_path.read_text(encoding="utf-8"))
    ti = {t: i for i, t in enumerate(m["teams"])}
    for t in WATCH_TEAMS:
        if t not in ti:
            continue
        i = ti[t]
        log(f"  {label} {t}: att={m['att'][i]:+.4f} con={m['con'][i]:+.4f} ha={m['ha'][i]:+.4f} hc={m['hc'][i]:+.4f}")


def main():
    log = lambda s: print(s, file=sys.stderr)
    log_watch_teams("FØR", log)

    matches = json.loads((LEAGUE / "data" / "matches.json").read_text(encoding="utf-8"))
    odds_path = LEAGUE / "data" / "odds.json"
    odds_by_key = {}
    if odds_path.exists():
        odds_data = json.loads(odds_path.read_text(encoding="utf-8"))["matches"]
        odds_by_key = {(o["home"], o["away"]): (o["H"], o["D"], o["A"]) for o in odds_data}

    teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
    TI = {t: i for i, t in enumerate(teams)}

    for m in matches:
        m["odds"] = odds_by_key.get((m["home"], m["away"]))
    n_odds = sum(1 for m in matches if m["odds"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    res = fit_fast.fit_model_fast(
        matches, teams, TI, odds_weight=ODDS_WEIGHT,
        half_life_goals=HALF_LIFE_DAYS, half_life_odds=HALF_LIFE_DAYS,
        l1=L1, l2=L2, ref_date=today, isolate_global=True,
    )
    log(f"Tilpasset mot {len(matches)} kamper ({n_odds} med odds). Konvergerte: {res['success']} "
        f"({res['nit']} iterasjoner).")

    out = {
        "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": teams,
        "mu": round(float(res["mu"]), 6),
        "H": round(float(res["H"]), 6),
        "att": [round(float(x), 6) for x in res["att"]],
        "con": [round(float(x), 6) for x in res["con"]],
        "ha": [round(float(x), 6) for x in res["ha"]],
        "hc": [round(float(x), 6) for x in res["hc"]],
        "meta": {
            "odds_weight": ODDS_WEIGHT, "half_life_days": HALF_LIFE_DAYS,
            "l1": L1, "l2": L2, "n_matches": len(matches), "n_odds_matches": n_odds,
        },
    }
    (LEAGUE / "data" / "model.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("Skrev data/model.json.")
    log_watch_teams("ETTER", log)

if __name__ == "__main__":
    main()
