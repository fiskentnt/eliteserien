#!/usr/bin/env python3
"""Walk-forward-tilbaketest av sluttplassen (Brier) og enkeltkampene.

Slik siden faktisk brukes: før HVER kampdato tilpasses modellen bare på
kampene med tidligere dato (faktisk dato, så utsatte kamper står der de ble
spilt), og resten av sesongen simuleres. Det gjøres gjennom hele sesongen,
fra første dato med minst 10 spilte kamper. Faste kuttpunkter
(scripts/backtest_zones.py) måler bare 40-85 prosent av sesongen og hopper
over den første delen, der lagstyrken betyr mest.

Modellene er de samme som i backtest_zones.py (samme simulering, samme
parametre), og alle variantene får de samme tilfeldige tallene på hvert punkt
(frøet avhenger av frø, sesong og dato), så parvise forskjeller er uten
simuleringsstøy. Standardfeilene er klustret på sesong.

Sluttplass (Brier), med tabell, ablasjon, fordel mot tabellmodellen per fase
og kalibrering:
  python3 scripts/backtest_walkforward.py --csv NOR.csv --league-zones eliteserien \\
      --seasons 2016-2025 --sims 100000 --jobber 10
  python3 scripts/backtest_walkforward.py --csv obos/data/obos_2012-2026.csv \\
      --league-zones obos --seasons 2012-2025 --sims 100000 --jobber 10

Enkeltkamper (log loss og treff, full modell mot alle lag like sterke):
  python3 scripts/backtest_walkforward.py --csv NOR.csv --enkeltkamper --seasons 2016-2025
"""
import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import fit_fast                                   # noqa: E402
import backtest_zones as BZ                       # noqa: E402
from evaluate_model import load_seasons, season_range, rate_pair, outcome_probs_dc  # noqa: E402

MIN_FIT = 10
FASER = [("under 25 %", 0.0, 0.25), ("25–40 %", 0.25, 0.40), ("40–55 %", 0.40, 0.55),
         ("55–70 %", 0.55, 0.70), ("70–85 %", 0.70, 0.85), ("over 85 %", 0.85, 1.01)]


def varianter(har_odds):
    """Som i backtest_zones.py: (oddsvekt, l1, l2, form_k, dc_rho[, rampe])."""
    ow = BZ.ODDS_WEIGHT if har_odds else 0.0
    V = {"tabell": None,
         "poisson": (0.0, BZ.L1_PLAIN, BZ.L2_PLAIN, 0.0, 0.0)}
    if har_odds:
        V["+odds"] = (BZ.ODDS_WEIGHT, BZ.L1_PLAIN, BZ.L2_PLAIN, 0.0, 0.0)
    V["+form"] = (ow, BZ.L1_PLAIN, BZ.L2_PLAIN, BZ.FORM_K, 0.0)
    V["+dc"] = (ow, BZ.L1_PLAIN, BZ.L2_PLAIN, BZ.FORM_K, BZ.DC_RHO)
    V["full"] = (ow, BZ.L1_FULL, BZ.L2_FULL, BZ.FORM_K, BZ.DC_RHO)
    if har_odds:
        V["+rampe"] = (ow, BZ.L1_PLAIN, BZ.L2_PLAIN, BZ.FORM_K, 0.0, True)
    return V


def seriekamper(allm):
    """Bare lag med full serie (kvalikkampene i NOR.csv holdes utenfor)."""
    c = {}
    for m in allm:
        c[m["home"]] = c.get(m["home"], 0) + 1
        c[m["away"]] = c.get(m["away"], 0) + 1
    full = {t for t, k in c.items() if k >= 25}
    return [m for m in allm if m["home"] in full and m["away"] in full], sorted(full)


def fasit_for(ms, teams, targets):
    TI = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    pos_f = BZ.final_positions(*BZ.standings(ms, TI, n), teams)
    fasit = {}
    for name, lo, hi in targets:
        a = lo if lo > 0 else n + lo + 1
        b = hi if hi > 0 else n + hi + 1
        fasit[name] = ((pos_f >= a) & (pos_f <= b)).astype(float).tolist()
    return fasit


def punkt_soner(arg):
    """Ett punkt: tilpass på kampene før datoen d, simuler resten."""
    season, d, ms, teams, targets, V, N, seed = arg
    TI = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    played = [m for m in ms if m["date"] < d]
    remaining = [m for m in ms if m["date"] >= d]
    pts0, gd0, gf0 = BZ.standings(played, TI, n)
    ref = played[-1]["date"]
    probs = {"basisrate": {name: np.full(n, ((hi if hi > 0 else n + hi + 1) - (lo if lo > 0 else n + lo + 1) + 1) / n)
                           for name, lo, hi in targets}}
    fits = {}
    for navn, cfg in V.items():
        rng = np.random.default_rng([seed, int(season), int(d.replace("-", ""))])   # samme tall for alle
        if cfg is None:
            lh = max(0.2, float(np.mean([m["hg"] for m in played])))
            la = max(0.2, float(np.mean([m["ag"] for m in played])))
            pos = BZ.simulate(remaining, TI, n, pts0, gd0, gf0, N, rng, mu=0.0, Hp=0.0, flat=(lh, la))
        else:
            ow, l1, l2, fk, dcr = cfg[:5]
            key = (ow, l1, l2)
            if key not in fits:
                fits[key] = fit_fast.fit_model_fast(played, teams, TI, odds_weight=ow, half_life_goals=BZ.HALF_LIFE,
                                                    half_life_odds=BZ.HALF_LIFE, l1=l1, l2=l2, ref_date=ref,
                                                    isolate_global=False)
            r = fits[key]
            pos = BZ.simulate(remaining, TI, n, pts0, gd0, gf0, N, rng, mu=r["mu"], Hp=r["H"],
                              att=np.array(r["att"]), con=np.array(r["con"]), ha=np.array(r["ha"]),
                              hc=np.array(r["hc"]), form_k=fk, dc_rho=dcr, ramp=len(cfg) > 5 and cfg[5])
        probs[navn] = dict(zip([t[0] for t in targets], BZ.zone_probs(pos, n, targets)))
    return season, d, len(played) / len(ms), {v: {z: np.asarray(probs[v][z]).tolist() for z in probs[v]} for v in probs}


def se_klynge(d, g):
    d = np.asarray(d, float); m = d.mean()
    u = np.array([(d[g == c] - m).sum() for c in np.unique(g)])
    return float(np.sqrt((u ** 2).sum()) / len(d))


def soner(args):
    lcfg = BZ.LEAGUES[args.league_zones]
    targets = lcfg["targets"]; zn = [t[0] for t in targets]
    if lcfg["csv"] == "obos":
        by = BZ.load_obos_csv(args.csv); har_odds = False
    else:
        nm = json.loads(Path(args.name_map).read_text(encoding="utf-8")) if Path(args.name_map).exists() else {}
        by = load_seasons(args.csv, args.league, nm); har_odds = True
    V = varianter(har_odds)
    sesonger = [s for s in season_range(args.seasons) if s in by]
    oppg, fasit = [], {}
    for s in sesonger:
        ms, teams = seriekamper(by[s])
        fasit[s] = fasit_for(ms, teams, targets)
        for d in sorted({m["date"] for m in ms}):
            if sum(1 for m in ms if m["date"] < d) >= MIN_FIT and any(m["date"] >= d for m in ms):
                oppg.append((s, d, ms, teams, targets, V, args.sims, args.seed))
    print(f"{len(oppg)} punkter, {len(V)} varianter, {args.sims} simuleringer, {args.jobber} jobber", file=sys.stderr, flush=True)
    per_sesong = {s: [] for s in sesonger}
    with ProcessPoolExecutor(args.jobber) as ex:
        for i, (s, d, andel, p) in enumerate(ex.map(punkt_soner, oppg, chunksize=1)):
            per_sesong[s].append({"dato": d, "andel": andel, "p": p, "y": fasit[s]})
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(oppg)} punkter", file=sys.stderr, flush=True)
    res = [(s, per_sesong[s]) for s in sesonger]
    modeller = ["basisrate"] + list(V)
    E = {m: {z: [] for z in zn} for m in modeller}; P = {z: [] for z in zn}; Y = {z: [] for z in zn}
    g, andel = [], []
    for s, pk in res:
        for x in pk:
            n = len(x["y"][zn[0]])
            for z in zn:
                y = np.array(x["y"][z])
                for m in modeller:
                    E[m][z].extend(((np.array(x["p"][m][z]) - y) ** 2).tolist())
                P[z].extend(x["p"]["full"][z]); Y[z].extend(x["y"][z])
            g.extend([s] * n); andel.extend([x["andel"]] * n)
    g, andel = np.array(g), np.array(andel)
    E = {m: {z: np.array(E[m][z]) for z in zn} for m in modeller}
    npunkt = sum(len(pk) for _, pk in res)
    ut = {"liga": args.league_zones, "sesonger": sesonger, "sims": args.sims, "punkter": npunkt, "lagobs": int(len(g)),
          "brier": {m: {z: float(E[m][z].mean()) for z in zn} for m in modeller}}
    print(f"Walk-forward, {args.league_zones}, sesongene {sesonger[0]}-{sesonger[-1]}: {npunkt} punkter, "
          f"{len(g)} lag-observasjoner, {args.sims} simuleringer")
    print(f"{'Modell':<12}" + "".join(f"{z:>12}" for z in zn))
    for m in modeller:
        print(f"{m:<12}" + "".join(f"{E[m][z].mean():>12.4f}" for z in zn))
    base_of = {"tabell": "basisrate", "poisson": "tabell", "+odds": "poisson", "+form": "+odds" if "+odds" in V else "poisson",
               "+dc": "+form", "full": "+dc", "+rampe": "+form"}
    print("\nParvis mot referansen (klustret SE på sesong):")
    ut["parvis"] = {}
    for b in modeller[1:]:
        a = base_of.get(b)
        if a not in E:   # et utvalg av variantene: referansen er ikke kjørt
            continue
        cel = []
        for z in zn:
            d = E[b][z] - E[a][z]
            cel.append((float(d.mean()), se_klynge(d, g)))
        ut["parvis"][f"{b} mot {a}"] = cel
        print(f"  {b:<8} mot {a:<9}" + "".join(f"{m:+.4f} ± {se:.4f} ({abs(m)/se if se else 0:.1f})   " for m, se in cel))
    cel = []
    for z in zn:
        d = E["full"][z] - E["tabell"][z]
        cel.append((float(d.mean()), se_klynge(d, g)))
    ut["full_mot_tabell"] = cel
    print("  full mot tabell    " + "".join(f"{m:+.4f} ± {se:.4f} ({abs(m)/se if se else 0:.1f})   " for m, se in cel))
    print("\nFull modell mot tabellmodellen per fase (andel spilt), klustret SE:")
    ut["faser"] = {}
    for navn, lo, hi in FASER:
        sel = (andel >= lo) & (andel < hi)
        if not sel.any():
            continue
        cel = []
        for z in zn:
            d = E["full"][z][sel] - E["tabell"][z][sel]
            cel.append((float(d.mean()), se_klynge(d, g[sel])))
        ut["faser"][navn] = {"n": int(sel.sum()), "d": cel}
        print(f"  {navn:<11}{int(sel.sum()):>7}" + "".join(f"   {z} {m:+.4f} ± {se:.4f}" for z, (m, se) in zip(zn, cel)))
    print("\nKalibrering, full modell:")
    ut["kalibrering"] = {}
    for z in zn:
        p_, y_ = np.array(P[z]), np.array(Y[z])
        rader = []
        for lo in range(0, 100, 10):
            sel = (p_ >= lo / 100) & ((p_ < (lo + 10) / 100) if lo < 90 else (p_ <= 1.0))
            rader.append((lo, int(sel.sum()), float(p_[sel].mean() * 100) if sel.any() else None,
                          float(y_[sel].mean() * 100) if sel.any() else None))
        ut["kalibrering"][z] = rader
        print(f"  {z}: " + "; ".join(f"{lo}-{lo+10} % n {n_} pred {pp:.1f} fakt {ff:.1f}" for lo, n_, pp, ff in rader if n_))
    # Innledningen på siden: alle sonene samlet, ett intervall.
    pa = np.concatenate([np.array(P[z]) for z in zn]); ya = np.concatenate([np.array(Y[z]) for z in zn])
    ut["samlet"] = {}
    for lo in range(0, 100, 10):
        sel = (pa >= lo / 100) & ((pa < (lo + 10) / 100) if lo < 90 else (pa <= 1.0))
        if sel.any():
            ut["samlet"][f"{lo}-{lo + 10}"] = [int(sel.sum()), float(pa[sel].mean() * 100), float(ya[sel].mean() * 100)]
    print("  alle soner samlet: " + "; ".join(f"{k} % n {v[0]} pred {v[1]:.1f} fakt {v[2]:.1f}" for k, v in ut["samlet"].items()))
    if args.ut:
        Path(args.ut).write_text(json.dumps(ut, indent=1), encoding="utf-8")


def sesong_kamper(arg):
    season, allm = arg
    ms, teams = seriekamper(allm)
    TI = {t: i for i, t in enumerate(teams)}
    zero = [0.0] * len(teams)
    ut = []
    for d in sorted({m["date"] for m in ms}):
        known = [m for m in ms if m["date"] < d]
        if len(known) < MIN_FIT:
            continue
        r = fit_fast.fit_model_fast(known, teams, TI, odds_weight=BZ.ODDS_WEIGHT, half_life_goals=BZ.HALF_LIFE,
                                    half_life_odds=BZ.HALF_LIFE, l1=BZ.L1_FULL, l2=BZ.L2_FULL,
                                    ref_date=known[-1]["date"], isolate_global=False)
        for m in ms:
            if m["date"] != d:
                continue
            k = 0 if m["hg"] > m["ag"] else 1 if m["hg"] == m["ag"] else 2
            lh, la = rate_pair(r["mu"], r["H"], r["att"], r["con"], r["ha"], r["hc"], TI, m["home"], m["away"])
            flh, fla = rate_pair(r["mu"], r["H"], zero, zero, zero, zero, TI, m["home"], m["away"])
            pm, pf = outcome_probs_dc(lh, la, BZ.DC_RHO), outcome_probs_dc(flh, fla, BZ.DC_RHO)
            ut.append((season, -math.log(max(pm[k], 1e-12)), -math.log(max(pf[k], 1e-12)),
                       int(max(range(3), key=lambda i: pm[i]) == k), int(max(range(3), key=lambda i: pf[i]) == k)))
    return ut


def enkeltkamper(args):
    nm = json.loads(Path(args.name_map).read_text(encoding="utf-8")) if Path(args.name_map).exists() else {}
    by = load_seasons(args.csv, args.league, nm)
    sesonger = [s for s in season_range(args.seasons) if s in by]
    with ProcessPoolExecutor(args.jobber) as ex:
        R = [r for res in ex.map(sesong_kamper, [(s, by[s]) for s in sesonger]) for r in res]
    g = np.array([r[0] for r in R]); llm = np.array([r[1] for r in R]); llf = np.array([r[2] for r in R])
    tm = np.array([r[3] for r in R], float); tf = np.array([r[4] for r in R], float)
    d = llm - llf
    ut = {"sesonger": sesonger, "kamper": len(R), "full": [float(llm.mean()), float(tm.mean())],
          "like_sterke": [float(llf.mean()), float(tf.mean())], "d": float(d.mean()), "se": se_klynge(d, g)}
    print(f"Walk-forward, enkeltkamper {sesonger[0]}-{sesonger[-1]}: {len(R)} kamper")
    print(f"  Alle lag like sterke: log loss {llf.mean():.4f}, traff {tf.mean()*100:.1f} %")
    print(f"  Full modell:          log loss {llm.mean():.4f}, traff {tm.mean()*100:.1f} %  "
          f"(forskjell {d.mean():+.4f} ± {se_klynge(d, g):.4f})")
    if args.ut:
        Path(args.ut).write_text(json.dumps(ut, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--league-zones", default="eliteserien", choices=sorted(BZ.LEAGUES))
    ap.add_argument("--league", default="Eliteserien")
    ap.add_argument("--seasons", default="2016-2025")
    ap.add_argument("--sims", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--jobber", type=int, default=10)
    ap.add_argument("--name-map", default=str(Path(__file__).parent / "eliteserien_name_map.json"))
    ap.add_argument("--enkeltkamper", action="store_true")
    ap.add_argument("--ut", default=None, help="JSON med resultatene")
    args = ap.parse_args()
    if args.enkeltkamper:
        enkeltkamper(args)
    else:
        soner(args)


if __name__ == "__main__":
    main()
