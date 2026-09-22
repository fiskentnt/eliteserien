"""Rullerende ut-av-utvalg-evaluering av modellen (log loss på utfall,
Poisson-NLL på mål) mot en football-data.co.uk-CSV. Generell -- tar
liga/CSV/sesonger/l1-l2 som argumenter, ikke hardkodet til Eliteserien, så
den kan brukes til å rekalibrere når en ny liga legges til siden.

Metoden: for hver sesong, tilpass modellen på kampene før et gitt
rundekutt (samme fit_fast.fit_model_fast som scripts/fit_model.py bruker),
mål så log loss/Poisson-NLL på den PÅFØLGENDE bolken med kamper (ekte
ut-av-utvalg, modellen har ikke sett dem). Gjenta ved flere kutt gjennom
sesongen (styrt av --cutoff-rounds) og summer over alle sesonger.

Brukt til å velge l1/l2=16/48 (8x utgangspunktet) i stedet for de
opprinnelige 2/6 -- se undersøkelsen i git-historien til data/model.json
og scripts/fit_model.py sin egen kommentar om hvorfor. Bekreftet med et
tog/test-sett (--train-seasons 2012-2021, --test-seasons 2022-2026) at
valget ikke bare var overtilpasning til de sesongene det ble funnet på.

Eksempel, Eliteserien -- last ned CSV-en først (den ligger ikke i repoet):
  curl -s https://football-data.co.uk/new/NOR.csv -o /tmp/NOR.csv
  python3 scripts/evaluate_model.py --csv /tmp/NOR.csv --league Eliteserien \
      --train-seasons 2012-2021 --test-seasons 2022-2026 \
      --l1-l2-mults 1,2,4,6,8,10,14,20

For en NY liga: samme kommando med --csv/--league pekt på den ligaens
football-data.co.uk-fil (samme kolonneformat: Country,League,Season,Date,
Home,Away,HG,AG,Res, og BFECH/BFECD/BFECA eller AvgCH/AvgCD/AvgCA for
odds) -- ingenting annet i scriptet er Eliteserien-spesifikt.
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fit_fast
from oddslib import devig

GMAX = 15  # samme grense som fit_fast.py og index.html


def load_seasons(csv_path, league, name_map=None):
    """name_map (valgfri, {alt-stavemåte: kanonisk navn}): football-data.co.uk
    er ikke alltid konsekvent innad i én sesong -- Eliteserien-CSV-en har
    f.eks. både "Ham-Kam" og "HamKam" i 2023 for samme lag. Ubrukt navn i
    kartet endres ikke. Uten kart (standard) brukes CSV-navnene rått, som er
    riktig for ligaer uten kjente stavevarianter."""
    name_map = name_map or {}
    norm = lambda n: name_map.get(n, n)
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig")) if r["League"] == league]
    by_season = {}
    for r in rows:
        dd, mm, yy = r["Date"].split("/")
        date = f"{yy}-{mm}-{dd}"
        odds = None
        if r.get("BFECH", "").strip():
            odds = list(devig(float(r["BFECH"]), float(r["BFECD"]), float(r["BFECA"])))
        elif r.get("AvgCH", "").strip():
            odds = list(devig(float(r["AvgCH"]), float(r["AvgCD"]), float(r["AvgCA"])))
        elif r.get("PSCH", "").strip():
            odds = list(devig(float(r["PSCH"]), float(r["PSCD"]), float(r["PSCA"])))
        m = {"date": date, "home": norm(r["Home"]), "away": norm(r["Away"]),
             "hg": int(r["HG"]), "ag": int(r["AG"]), "odds": odds}
        by_season.setdefault(r["Season"], []).append(m)
    for season in by_season:
        by_season[season].sort(key=lambda m: m["date"])
    return by_season


def dc_tau(x, y, lh, la, rho):
    if x == 0 and y == 0: return max(0.0, 1 - lh * la * rho)
    if x == 1 and y == 0: return max(0.0, 1 + la * rho)
    if x == 0 and y == 1: return max(0.0, 1 + lh * rho)
    if x == 1 and y == 1: return max(0.0, 1 - rho)
    return 1.0


def outcome_probs_dc(lh, la, rho):
    """H/D/B-sannsynligheter fra et Poisson-par med Dixon-Coles tau-korreksjon
    på de fire lave resultatene -- samme formel som dcTau()/outcomeProbs() i
    index.html sin WORKER_SRC. rho=0 gir ren uavhengig Poisson."""
    ph = [math.exp(-lh)]
    pa = [math.exp(-la)]
    for i in range(1, GMAX + 1):
        ph.append(ph[-1] * lh / i)
        pa.append(pa[-1] * la / i)
    H = D = B = 0.0
    for h in range(GMAX + 1):
        for a in range(GMAX + 1):
            p = ph[h] * pa[a] * dc_tau(h, a, lh, la, rho)
            if h > a: H += p
            elif h == a: D += p
            else: B += p
    t = H + D + B
    return H / t, D / t, B / t


def poisson_nll(k, lam):
    lam = max(lam, 1e-9)
    return lam - k * math.log(lam) + math.lgamma(k + 1)


def rate_pair(mu, Hp, att, con, ha, hc, TI, home, away):
    h, a = TI[home], TI[away]
    eh = mu + Hp + att[h] + ha[h] + con[a] - hc[a]
    ea = mu + att[a] - ha[a] + con[h] + hc[h]
    eh = min(9.0, max(-9.0, eh))
    ea = min(9.0, max(-9.0, ea))
    return math.exp(eh), math.exp(ea)


def rolling_evaluate(by_season, seasons, l1, l2, odds_weight, half_life, cutoff_rounds, dc_rho):
    """Rullerende log loss/Poisson-NLL over de gitte sesongene, ved de gitte
    rundekuttene. Hopper over sesonger som mangler i by_season (f.eks. en
    delvis nåværende sesong som ikke er lastet)."""
    total_logloss = 0.0
    total_nll = 0.0
    # Sammenligning: alle lag like sterke, bare hjemmefordel (mu og H fra samme
    # tilpasning, alle lagvise ledd satt til 0). Viser hvor mye det er verdt å
    # vite HVEM som spiller, på samme kamper som modellen vurderes på.
    flat_logloss = 0.0
    flat_nll = 0.0
    n_eval = 0
    hits = flat_hits = 0
    for season in seasons:
        if season not in by_season:
            continue
        matches = by_season[season]
        teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
        TI = {t: i for i, t in enumerate(teams)}
        T = len(teams)
        per_round = T / 2.0
        total = len(matches)
        cuts = sorted(set(min(total, round(r * per_round)) for r in cutoff_rounds) | {total})
        for ci in range(len(cuts) - 1):
            fit_n = cuts[ci]
            eval_start, eval_end = cuts[ci], cuts[ci + 1]
            if fit_n < 10 or eval_start >= eval_end:
                continue
            known = matches[:fit_n]
            res = fit_fast.fit_model_fast(known, teams, TI, odds_weight=odds_weight,
                                           half_life_goals=half_life, half_life_odds=half_life,
                                           l1=l1, l2=l2, ref_date=known[-1]["date"], isolate_global=True)
            mu, Hp, att, con, ha, hc = res["mu"], res["H"], res["att"], res["con"], res["ha"], res["hc"]
            zeros = [0.0] * len(teams)
            for m in matches[eval_start:eval_end]:
                lh, la = rate_pair(mu, Hp, att, con, ha, hc, TI, m["home"], m["away"])
                hg, ag = m["hg"], m["ag"]
                actual = "H" if hg > ag else ("D" if hg == ag else "B")
                pH, pD, pB = outcome_probs_dc(lh, la, dc_rho)
                p_actual = {"H": pH, "D": pD, "B": pB}[actual]
                total_logloss += -math.log(max(p_actual, 1e-9))
                total_nll += poisson_nll(hg, lh) + poisson_nll(ag, la)
                if max((pH, "H"), (pD, "D"), (pB, "B"))[1] == actual:
                    hits += 1
                flh, fla = rate_pair(mu, Hp, zeros, zeros, zeros, zeros, TI, m["home"], m["away"])
                fH, fD, fB = outcome_probs_dc(flh, fla, dc_rho)
                f_actual = {"H": fH, "D": fD, "B": fB}[actual]
                flat_logloss += -math.log(max(f_actual, 1e-9))
                flat_nll += poisson_nll(hg, flh) + poisson_nll(ag, fla)
                if max((fH, "H"), (fD, "D"), (fB, "B"))[1] == actual:
                    flat_hits += 1
                n_eval += 1
    if n_eval == 0:
        return None
    return (total_logloss / n_eval, total_nll / n_eval, n_eval,
            flat_logloss / n_eval, flat_nll / n_eval, hits / n_eval, flat_hits / n_eval)


def season_range(spec):
    a, b = spec.split("-")
    return [str(y) for y in range(int(a), int(b) + 1)]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", required=True, help="football-data.co.uk-CSV (lastes ikke ned av scriptet)")
    p.add_argument("--league", required=True, help='verdien i CSV-ens "League"-kolonne, f.eks. Eliteserien')
    p.add_argument("--train-seasons", help="f.eks. 2012-2021 -- sveiper l1/l2 her")
    p.add_argument("--test-seasons", help="f.eks. 2022-2026 -- validerer valget her (holdt utenfor)")
    p.add_argument("--l1-l2-mults", default="1,2,4,6,8,10,14,20",
                    help="multiplikatorer av l1-base/l2-base å sveipe, komma-separert")
    p.add_argument("--l1-base", type=float, default=2.0)
    p.add_argument("--l2-base", type=float, default=6.0)
    p.add_argument("--odds-weight", type=float, default=40.0)
    p.add_argument("--half-life", type=float, default=35.0)
    p.add_argument("--dc-rho", type=float, default=-0.38, help="Dixon-Coles tau-parameter, 0 = av")
    p.add_argument("--cutoff-rounds", default="5,10,15,20,25",
                    help="rundekutt å tilpasse+evaluere ved gjennom hver sesong")
    p.add_argument("--name-map", help="valgfri JSON-fil {alt-stavemåte: kanonisk navn}, "
                                       "for kjente stavevarianter innad i CSV-en (se load_seasons())")
    args = p.parse_args()

    name_map = json.load(open(args.name_map, encoding="utf-8")) if args.name_map else None
    by_season = load_seasons(args.csv, args.league, name_map)
    mults = [float(x) for x in args.l1_l2_mults.split(",")]
    cutoff_rounds = [int(x) for x in args.cutoff_rounds.split(",")]

    def run_sweep(label, seasons):
        if not seasons:
            return {}
        print(f"\n{label} = {seasons[0]}-{seasons[-1]} ({len(seasons)} sesonger)")
        print(f"{'l1xl2':>10s} {'log loss':>10s} {'Poisson-NLL':>12s} {'n kamper':>10s}"
              f"   | sammenligning med alle lag like sterke")
        results = {}
        for mult in mults:
            out = rolling_evaluate(by_season, seasons, args.l1_base * mult, args.l2_base * mult,
                                    args.odds_weight, args.half_life, cutoff_rounds, args.dc_rho)
            if out is None:
                print(f"{mult:>9.1f}x  (ingen kamper funnet for disse sesongene)")
                continue
            ll, nll, n, fll, fnll, hit, fhit = out
            results[mult] = ll
            print(f"{mult:>9.1f}x {ll:10.4f} {nll:12.4f} {n:10d}"
                  f"   | like sterke lag: {fll:.4f} / {fnll:.4f}"
                  f"   | traff utfallet: {hit*100:.1f} % mot {fhit*100:.1f} %")
        return results

    train_results = run_sweep("TRAIN", season_range(args.train_seasons) if args.train_seasons else [])
    test_results = run_sweep("TEST", season_range(args.test_seasons) if args.test_seasons else [])

    if train_results:
        best = min(train_results, key=train_results.get)
        print(f"\nBeste l1/l2-multiplikator (log loss) TRAIN: {best}x  (l1={args.l1_base*best:g}, l2={args.l2_base*best:g})")
    if test_results:
        best = min(test_results, key=test_results.get)
        print(f"Beste l1/l2-multiplikator (log loss) TEST:  {best}x  (l1={args.l1_base*best:g}, l2={args.l2_base*best:g})")
    if train_results and test_results:
        best_train = min(train_results, key=train_results.get)
        best_test = min(test_results, key=test_results.get)
        if abs(best_train - best_test) <= 2:
            print("TRAIN og TEST er enige (eller nær nok) -- valget ser ekte ut, ikke overtilpasset TRAIN.")
        else:
            print("TRAIN og TEST spriker -- vurder et multiplikator midt i det flate området"
                  " i stedet for TRAIN sitt eget optimum (mindre følsomt for hvilket utvalg det ble funnet på).")


if __name__ == "__main__":
    main()
