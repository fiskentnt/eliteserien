#!/usr/bin/env python3
"""Måler oddsvekten i OBOS-modellen på OBOS-tallene, ut av utvalg.

Vekten 40 er arvet fra Eliteserien, der den ble funnet med snittodds fra mange
bookmakere. OBOS bruker Pinnacle alene, som har lavere margin, så vekten kan
være en annen her.

Metoden: for hver runde tilpasses modellen BARE på kampene som var spilt før
runden, med den gitte oddsvekten, og bedømmes på rundens kamper -- som
modellen ikke har sett. Oddsen for kampene som bedømmes, brukes ikke; bare
oddsen for kampene før dem, som i tilpasningen. Tallet som måles er modellens
egen sannsynlighet for kampresultatet (Poisson med Dixon-Coles), ikke en
blanding med oddsen: det er vekten i TILPASNINGEN som testes.

Forskjellen mot vekt 40 regnes parvis, kamp for kamp, med standardfeil. Er den
innenfor støyen, er det ikke grunnlag for å bytte.

  python3 scripts/obos_odds_weight.py
  python3 scripts/obos_odds_weight.py --weights 0 20 40 80 160 --min 48
"""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fit_fast
from obos_build_data import rows_for, load_closing_odds, HALF_LIFE, L1, L2

RHO, GMAX = -0.38, 15


def outcome_probs(res, i, j):
    """Sannsynlighet for hjemmeseier, uavgjort og borteseier, som på siden."""
    lh = min(math.exp(res["mu"] + res["H"] + res["att"][i] + res["con"][j]
                      + res["ha"][i] + res["hc"][j]), 6.0)
    la = min(math.exp(res["mu"] + res["att"][j] + res["con"][i]), 6.0)
    ph = [math.exp(-lh) * lh**k / math.factorial(k) for k in range(GMAX)]
    pa = [math.exp(-la) * la**k / math.factorial(k) for k in range(GMAX)]
    H = D = A = 0.0
    for a in range(GMAX):
        for b in range(GMAX):
            p = ph[a] * pa[b]
            if a <= 1 and b <= 1:      # Dixon-Coles
                p *= {(0, 0): 1 - lh * la * RHO, (0, 1): 1 + lh * RHO,
                      (1, 0): 1 + la * RHO, (1, 1): 1 - RHO}[(a, b)]
            if p <= 0:
                continue
            if a > b:
                H += p
            elif a == b:
                D += p
            else:
                A += p
    s = H + D + A
    return H / s, D / s, A / s


def evaluate(weight, rounds, order, teams, TI, odds, min_matches):
    """Log loss og treff per kamp, ut av utvalg, for én oddsvekt."""
    tap, treff, seen = [], [], []
    for rn in order:
        grp = rounds[rn]
        if len(seen) >= min_matches:
            fm = [{"date": m["date"], "home": m["home"], "away": m["away"],
                   "hg": m["hg"], "ag": m["ag"],
                   "odds": odds.get((m["home"], m["away"])) if weight else None} for m in seen]
            res = fit_fast.fit_model_fast(
                fm, teams, TI, odds_weight=weight, half_life_goals=HALF_LIFE,
                half_life_odds=HALF_LIFE, l1=L1, l2=L2,
                ref_date=seen[-1]["date"], isolate_global=True)
            for m in grp:
                p = outcome_probs(res, TI[m["home"]], TI[m["away"]])
                k = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
                tap.append(-math.log(max(p[k], 1e-9)))
                treff.append(1 if max(range(3), key=lambda x: p[x]) == k else 0)
        seen.extend(grp)
    return tap, treff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=float, nargs="+", default=[0, 20, 40, 80, 160])
    ap.add_argument("--min", type=int, default=48, help="kamper til oppvarming før første måling")
    ap.add_argument("--baseline", type=float, default=40.0, help="vekten de andre måles mot")
    args = ap.parse_args()

    rows = [m for m in rows_for() if m["hg"] is not None]
    odds = load_closing_odds()
    teams = sorted({m["home"] for m in rows} | {m["away"] for m in rows})
    TI = {t: i for i, t in enumerate(teams)}
    rounds = {}
    for m in rows:
        rounds.setdefault(m["round"], []).append(m)
    order = sorted(rounds, key=lambda rn: min(x["date"] for x in rounds[rn]))

    print(f"{len(rows)} spilte kamper, {len(odds)} med sluttodds. "
          f"Oppvarming: {args.min} kamper.\n")
    res = {}
    for w in args.weights:
        res[w] = evaluate(w, rounds, order, teams, TI, odds, args.min)
    n = len(res[args.weights[0]][0])
    print(f"{n} kamper bedømt ut av utvalg\n")
    print(f"{'oddsvekt':>9} {'log loss':>10} {'treff':>8}   mot vekt {args.baseline:g}")
    base_tap = res[args.baseline][0]
    for w in args.weights:
        tap, treff = res[w]
        ll = sum(tap) / n
        hit = 100 * sum(treff) / n
        if w == args.baseline:
            print(f"{w:>9g} {ll:>10.4f} {hit:>7.1f} %   (utgangspunktet)")
            continue
        d = [tap[i] - base_tap[i] for i in range(n)]
        md = sum(d) / n
        sd = math.sqrt(sum((x - md) ** 2 for x in d) / (n - 1))
        se = sd / math.sqrt(n)
        se_txt = f"{md:+.4f} ± {se:.4f} ({abs(md/se) if se > 1e-12 else 0:.1f} SE, "
        se_txt += "bedre" if md < 0 else "dårligere"
        se_txt += ")"
        print(f"{w:>9g} {ll:>10.4f} {hit:>7.1f} %   {se_txt}")

    best = min(args.weights, key=lambda w: sum(res[w][0]) / n)
    if best == args.baseline:
        print(f"\nVekt {args.baseline:g} er best målt. Ingen grunn til å bytte.")
        return 0
    tap = res[best][0]
    d = [tap[i] - base_tap[i] for i in range(n)]
    md = sum(d) / n
    sd = math.sqrt(sum((x - md) ** 2 for x in d) / (n - 1))
    se = sd / math.sqrt(n)
    utenfor = se > 1e-12 and abs(md / se) > 2
    print(f"\nBest målt: vekt {best:g}, {md:+.4f} ± {se:.4f} mot {args.baseline:g} "
          f"({abs(md/se) if se > 1e-12 else 0:.1f} SE).")
    print("Utenfor støyen: bytt." if utenfor
          else f"Innenfor støyen: behold {args.baseline:g}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
