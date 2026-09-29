#!/usr/bin/env python3
"""Dixon-Coles-rho og målfordelingen, målt på enkeltkamper ut av utvalg.

Spørsmålet (29.9.2026): trekningen på siden ("Simuler runden", "Simuler tomme
kamper", H/U/B) ga for mange store sifre, og DC_RHO = -0,38 viste seg å gi
30,5 % uavgjort mot faktisk 24,0 %. Dette skriptet sammenligner rho-verdier og
målnivå på det siden faktisk regner med:

  1. Rullerende tilpasning som i produksjonen (fit_fast, oddsvekt 40,
     halveringstid 35 dager, l1/l2 16/48, bare sesongens egne kamper), ved
     rundekuttene 5, 10, 15, 20 og 25. Hver kamp i bolken etter et kutt får
     modellens rater. Kampene i FØRSTE runde etter kuttet har odds på siden:
     70 % odds + 30 % modell (H og B), og ratene tilpasses som fitRates()
     (samme gridsøk), med variantens rho.
  2. rho tilpasset hele resultatfordelingen (maks sannsynlighet for det
     eksakte resultatet med modellens rater), og målnivået (faktiske mål delt
     på modellens forventning, hjemme og borte).
  3. Variantene regnes EKSAKT av rutenettet (Poisson + tau på 0-0, 1-0, 0-1,
     1-1, GMAX 15, som siden): målfordelingen mot de faktiske kampene, log
     loss, Brier og treff på hjemme/uavgjort/borte, og log loss på det eksakte
     resultatet.

Hvorfor -0,38 ble valgt (20.9.2026, se commit 48e89a3): den ble justert til
uavgjortandelen i 1000 simulerte HELE sesonger (alle mot alle, dagens
lagstyrker, formoppdatering med rekke-rampe) traff 24 %. I de samme
sesongene var snittet av lagenes målforskjell 24,3 mot 14,4 i virkeligheten:
spredningen mellom lagene var for stor, og det var den som ga for få
uavgjorte (18,7 % med ren Poisson). rho rettet uavgjortandelen, ikke
årsaken. På enkeltkamper ut av utvalg gir -0,38 for mange uavgjorte.

Sluttplasseringene (gull, topp 4, nedrykk) måles i backtest_zones.py
(--dc-rho-alt). Dagens tall på siden med hver variant: scripts/dc_rho_side.js.

Data:
  Eliteserien: NOR.csv fra football-data.co.uk (ligger ikke i repoet):
    curl -s https://football-data.co.uk/new/NOR.csv -o NOR.csv
  Filen oppdateres fortløpende. Tallene 29.9.2026 er regnet med den som ble
  lastet ned 25.9.2026 01:39, med kamper til og med 20.9.2026 (3550 rader),
  sha256 151c7368b4c5386912f6be952f4ee2fd4e5896d4ff1992228632e58fdc9c67c9.
  Sesongene 2012–2025 i en nyere fil bør gi de samme tallene.
  OBOS: obos/data/historikk/obos_historikk_2012-2025.csv (i repoet; satt
  sammen, kan ikke lastes ned på nytt, se README.md der).

Bruk:
  python3 scripts/dc_rho_studie.py --liga eliteserien --csv NOR.csv
  python3 scripts/dc_rho_studie.py --liga obos
"""
import argparse
import csv
import json
import math
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import fit_fast
from evaluate_model import load_seasons, rate_pair, season_range
from oddslib import devig

G = 15                                   # GMAX, som siden
K = np.arange(G + 1)
LF = np.array([math.lgamma(k + 1) for k in K])
ODDS_W = 0.7                             # sidens ODDS_W
RHO_I_DAG = -0.38
KUTT = (5, 10, 15, 20, 25)


def les_obos_historikk(path):
    """obos_historikk_2012-2025.csv: sesong,dato,hjemmelag,bortelag,
    mal_hjemme,mal_borte,utfall,odds_1,odds_x,odds_2."""
    by = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not r["mal_hjemme"] or not r["mal_borte"]:
                continue
            odds = None
            try:
                odds = list(devig(float(r["odds_1"]), float(r["odds_x"]), float(r["odds_2"])))
            except (ValueError, KeyError):
                pass
            by.setdefault(r["sesong"], []).append({"date": r["dato"], "home": r["hjemmelag"], "away": r["bortelag"],
                                                   "hg": int(r["mal_hjemme"]), "ag": int(r["mal_borte"]), "odds": odds})
    for s in by:
        by[s].sort(key=lambda m: m["date"])
    return by


def prediksjoner_sesong(arg):
    """Rullerende rater for én sesong (kjøres i parallell)."""
    season, matches = arg
    teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
    TI = {t: i for i, t in enumerate(teams)}
    per_round = len(teams) / 2.0
    cuts = sorted(set(min(len(matches), round(r * per_round)) for r in KUTT) | {len(matches)})
    ut = []
    for ci in range(len(cuts) - 1):
        a, b = cuts[ci], cuts[ci + 1]
        if a < 10 or a >= b:
            continue
        known = matches[:a]
        r = fit_fast.fit_model_fast(known, teams, TI, odds_weight=40.0, half_life_goals=35.0, half_life_odds=35.0,
                                    l1=16.0, l2=48.0, ref_date=known[-1]["date"], isolate_global=True)
        for j, m in enumerate(matches[a:b]):
            lh, la = rate_pair(r["mu"], r["H"], r["att"], r["con"], r["ha"], r["hc"], TI, m["home"], m["away"])
            ut.append((season, j < per_round, lh, la, m["odds"], m["hg"], m["ag"]))
    return ut


def pois_mat(lam):
    """(n,) -> (n, G+1) Poisson-sannsynligheter."""
    lam = np.asarray(lam, dtype=float)[:, None]
    return np.exp(-lam + K[None, :] * np.log(lam) - LF[None, :])


def rutenett(lh, la, rho):
    """(n,) -> (n, G+1, G+1), normert, med tau på de fire lave cellene."""
    M = pois_mat(lh)[:, :, None] * pois_mat(la)[:, None, :]
    if rho:
        M[:, 0, 0] *= np.maximum(0.0, 1 - lh * la * rho)
        M[:, 1, 0] *= np.maximum(0.0, 1 + la * rho)
        M[:, 0, 1] *= np.maximum(0.0, 1 + lh * rho)
        M[:, 1, 1] *= max(0.0, 1 - rho)
    return M / M.sum(axis=(1, 2), keepdims=True)


HM = K[:, None] > K[None, :]
DM = K[:, None] == K[None, :]
BM = K[:, None] < K[None, :]


def utfall(M):
    return M[:, HM].sum(1), M[:, DM].sum(1), M[:, BM].sum(1)


GROV = np.arange(0.15, 4.5 + 1e-9, 0.05)
_TAB = {}


def fit_rates(pH, pB, rho):
    """fitRates() for mange kamper: grovt gitter 0,15-4,5 (steg 0,05), så
    fint +/-0,05 (steg 0,005) rundt det beste, som siden."""
    if rho not in _TAB:
        LH, LA = np.meshgrid(GROV, GROV, indexing="ij")
        h, _d, b = utfall(rutenett(LH.ravel(), LA.ravel(), rho))
        _TAB[rho] = (h.reshape(LH.shape), b.reshape(LH.shape))
    H, B = _TAB[rho]
    ut = []
    fin = np.arange(-0.05, 0.05 + 1e-9, 0.005)
    for ph, pb in zip(pH, pB):
        i, j = np.unravel_index(np.argmin((H - ph) ** 2 + (B - pb) ** 2), H.shape)
        lh = (GROV[i] + fin)[:, None].repeat(len(fin), 1).ravel()
        la = (GROV[j] + fin)[None, :].repeat(len(fin), 0).ravel()
        ok = (lh > 0) & (la > 0)
        h, _d, b = utfall(rutenett(lh[ok], la[ok], rho))
        k = int(np.argmin((h - ph) ** 2 + (b - pb) ** 2))
        ut.append((lh[ok][k], la[ok][k]))
    return np.array(ut)


def stats(S, n):
    """Fordelingen S (G+1, G+1) summert over n kamper -> andeler."""
    S = S / n
    tot = K[:, None] + K[None, :]
    return {"mål": float((S * tot).sum()), "hjemme": float((S * K[:, None]).sum()), "borte": float((S * K[None, :]).sum()),
            "uavgjort": float(S[DM].sum()), "0-0": float(S[0, 0]), "1-0": float(S[1, 0]), "0-1": float(S[0, 1]),
            "1-1": float(S[1, 1]), "≥5 ett lag": float(S[(K[:, None] >= 5) | (K[None, :] >= 5)].sum()),
            "margin ≥4": float(S[np.abs(K[:, None] - K[None, :]) >= 4].sum()), "≥6 totalt": float(S[tot >= 6].sum())}


def faktisk(hg, ag):
    S = np.zeros((G + 1, G + 1))
    for h, a in zip(hg, ag):
        S[min(h, G), min(a, G)] += 1
    return stats(S, len(hg))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--liga", choices=["eliteserien", "obos"], required=True)
    ap.add_argument("--csv", help="NOR.csv (Eliteserien); OBOS: obos/data/historikk/obos_historikk_2012-2025.csv som standard")
    ap.add_argument("--sesonger", default="2012-2025")
    ap.add_argument("--ut", help="JSON med alle tallene")
    args = ap.parse_args()

    if args.csv is None:
        if args.liga != "obos":
            ap.error("--csv er påkrevd for Eliteserien (NOR.csv)")
        args.csv = str(Path(__file__).parent.parent / "obos" / "data" / "historikk" / "obos_historikk_2012-2025.csv")
    if args.liga == "eliteserien":
        kart = json.loads((Path(__file__).parent / "eliteserien_name_map.json").read_text(encoding="utf-8"))
        by = load_seasons(args.csv, "Eliteserien", kart)
    else:
        by = les_obos_historikk(args.csv)
    sesonger = [s for s in season_range(args.sesonger) if s in by]
    with Pool() as pool:
        rader = [x for del_ in pool.map(prediksjoner_sesong, [(s, by[s]) for s in sesonger]) for x in del_]
    forste = np.array([r[1] for r in rader])
    LH = np.array([r[2] for r in rader]); LA = np.array([r[3] for r in rader])
    odds = [r[4] for r in rader]
    HG = np.array([r[5] for r in rader]); AG = np.array([r[6] for r in rader])
    har_odds = forste & np.array([o is not None for o in odds])
    n = len(rader)
    print(f"{args.liga}: {n} kamper ut av utvalg, sesongene {sesonger[0]}-{sesonger[-1]}, "
          f"{int(har_odds.sum())} i første runde etter et kutt med odds")

    # rho tilpasset hele resultatfordelingen, og målnivået.
    hgk, agk = np.minimum(HG, G), np.minimum(AG, G)
    def score_ll(rho, c=(1.0, 1.0)):
        M = rutenett(LH * c[0], LA * c[1], rho)
        return float(np.log(np.maximum(M[np.arange(n), hgk, agk], 1e-12)).mean())
    rhos = np.round(np.arange(-0.45, 0.101, 0.01), 2)
    kurve = [score_ll(r) for r in rhos]
    rho_ml = float(rhos[int(np.argmax(kurve))])
    c = (float(HG.sum() / LH.sum()), float(AG.sum() / LA.sum()))
    rho_ml_c = float(rhos[int(np.argmax([score_ll(r, c) for r in rhos]))])
    print(f"rho tilpasset hele resultatfordelingen: {rho_ml} (med kalibrert nivå {rho_ml_c}); "
          f"målnivå faktisk/modell: hjemme {c[0]:.3f}, borte {c[1]:.3f}")
    print("snitt log-sannsynlighet for eksakt resultat: " + "  ".join(f"{r:+.2f}: {v:.4f}" for r, v in zip(rhos, kurve) if round(r * 100) % 5 == 0))

    VAR = [("I dag", RHO_I_DAG, RHO_I_DAG, (1.0, 1.0)),
           ("1a: odds tilpasset uten DC", RHO_I_DAG, 0.0, (1.0, 1.0)),
           ("1b: odds tilpasset med rho -0,10", RHO_I_DAG, -0.10, (1.0, 1.0)),
           (f"2: rho {rho_ml:g} overalt", rho_ml, rho_ml, (1.0, 1.0)),
           ("2': rho -0,04 overalt", -0.04, -0.04, (1.0, 1.0)),
           ("3: målnivået kalibrert", RHO_I_DAG, RHO_I_DAG, c),
           (f"Samlet: rho {rho_ml_c:g} + nivå", rho_ml_c, rho_ml_c, c)]
    res = {"liga": args.liga, "n": n, "rho_ml": rho_ml, "rho_ml_c": rho_ml_c, "c": c,
           "kurve": dict(zip(map(float, rhos), kurve)),
           "faktisk": {"alle": faktisk(HG, AG), "odds": faktisk(HG[har_odds], AG[har_odds])}, "varianter": {}}
    for navn, rho, rho_fit, cc in VAR:
        lh, la = LH * cc[0], LA * cc[1]
        if har_odds.any():
            idx = np.flatnonzero(har_odds)
            mH, _mD, mB = utfall(rutenett(lh[idx], la[idx], rho))
            o = np.array([odds[i] for i in idx])
            fit = fit_rates(ODDS_W * o[:, 0] + (1 - ODDS_W) * mH, ODDS_W * o[:, 2] + (1 - ODDS_W) * mB, rho_fit)
            lh, la = lh.copy(), la.copy()
            lh[idx], la[idx] = fit[:, 0], fit[:, 1]
        M = rutenett(lh, la, rho)
        pH, pD, pB = utfall(M)
        P = np.stack([pH, pD, pB], 1)
        y = np.where(HG > AG, 0, np.where(HG == AG, 1, 2))
        Y = np.eye(3)[y]
        res["varianter"][navn] = {
            "rho": rho, "rho_odds": rho_fit, "nivå": cc,
            "alle": stats(M.sum(0), n), "odds": stats(M[har_odds].sum(0), max(1, int(har_odds.sum()))),
            "log loss": float(-np.log(np.maximum(P[np.arange(n), y], 1e-12)).mean()),
            "Brier": float(((P - Y) ** 2).sum(1).mean()), "treff": float((P.argmax(1) == y).mean()),
            "resultat-NLL": float(-np.log(np.maximum(M[np.arange(n), hgk, agk], 1e-12)).mean())}

    kol = ["mål", "uavgjort", "0-0", "1-0", "0-1", "1-1", "≥5 ett lag", "margin ≥4", "≥6 totalt"]
    pst = lambda k, v: f"{v:.2f}" if k == "mål" else f"{v * 100:.1f}"
    for del_, tittel in [("alle", f"alle {n} kampene"), ("odds", f"de {int(har_odds.sum())} kampene med odds på siden")]:
        print(f"\nMålfordelingen, {tittel}:")
        print(f"  {'':36}" + "".join(f"{k:>11}" for k in kol))
        print(f"  {'Faktisk':36}" + "".join(f"{pst(k, res['faktisk'][del_][k]):>11}" for k in kol))
        for navn, v in res["varianter"].items():
            print(f"  {navn:36}" + "".join(f"{pst(k, v[del_][k]):>11}" for k in kol))
    print("\nHjemme/uavgjort/borte og eksakt resultat, alle kampene:")
    print(f"  {'':36}{'log loss':>10}{'Brier':>9}{'treff':>8}{'resultat-NLL':>14}")
    for navn, v in res["varianter"].items():
        print(f"  {navn:36}{v['log loss']:>10.4f}{v['Brier']:>9.4f}{v['treff'] * 100:>7.1f}%{v['resultat-NLL']:>14.4f}")
    if args.ut:
        Path(args.ut).write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
