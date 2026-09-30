#!/usr/bin/env python3
"""Tilbaketest av SLUTTPLASS-sannsynlighetene (Brier-score), ikke av
enkeltkamper -- det er scripts/evaluate_model.py sin jobb.

Faste kuttpunkter. Siden viser disse tallene som kontroll ved siden av
walk-forward-testen (scripts/backtest_walkforward.py), som tilpasser modellen
før hver kampdato gjennom hele sesongen. Her: for hver
sesong og hvert kuttpunkt tilpasses modellen KUN på kampene som var spilt til
da, resten av sesongen simuleres, og sannsynligheten for seriemester, topp 4 og
nedrykk sammenlignes med det som faktisk skjedde. Brier-score er snittet av
(sannsynlighet − utfall)² over alle lag, kuttpunkt og sesonger. Lavere er bedre.

To ting om usikkerheten, som begge er nødvendige for at tallene skal bety det
de ser ut som:

  Standardfeilene er KLUSTRET PÅ SESONG. Lagene i en sesong er ikke
  uavhengige forsøk -- bare ett lag kan vinne serien, så bommer modellen på
  gulloppgjøret bommer den på flere lag samtidig, og de samme sesongene måles
  ved flere kuttpunkt. Regnet som om hver lagobservasjon var et eget forsøk,
  blir standardfeilene rundt halvparten så store. Begge varianter skrives ut,
  så forskjellen er synlig.

  Alle variantene bruker SAMME TILFELDIGE TALL innenfor samme sesong og
  kuttpunkt. Frøet avhenger bare av (frø, sesong, kuttpunkt). To varianter med
  identiske parametre gir da bit-identiske tall, og i parvise sammenligninger
  faller simuleringsstøyen ut av differansen. Resultatet er også uavhengig av
  kjørerekkefølge: ett kuttpunkt kan kjøres for seg og gir nøyaktig samme
  bidrag som i en full kjøring.

Modellene som sammenlignes:
  basisrate   samme faste sannsynlighet for alle lag (1/n, 4/n, 2/n). Kjenner
              verken tabellen eller lagene.
  tabell      alle lag er like sterke: målnivået hjemme og borte er snittet i
              sesongen så langt, likt for alle. Bare dagens poeng, målforskjell
              og hvilke kamper som står igjen skiller lagene. Dette er den
              sterke baselinjen -- den som viser hva lagstyrke tilfører.
  poisson     modellen tilpasset på mål alene, uten odds, uten formoppdatering
              og uten Dixon-Coles.
  full        modellen fra model.json slik siden simulerer med den: mål +
              sluttodds i tilpasningen, formoppdatering underveis i hver
              simulerte sesong, Dixon-Coles og l1/l2 = 8/24. Siden blander i
              tillegg inn oddsen for neste runde (ODDS_W); det gjør ikke full.
  kjede       som full, men første runde etter kuttet får målrater fra
              sluttoddsen blandet 70/30 med modellen og regnet om med fitRates,
              slik siden gjør med oddsen den har for neste runde. Formen
              oppdateres mot de ratene, som i Workeren. OPTIMISTISK: siden har
              odds hentet før avspark, mens sluttoddsen er satt rett før kampen
              og vet mer. Bare der CSV-en har odds (ikke OBOS).

Bruk (CSV-en ligger ikke i repoet):
  curl -s https://football-data.co.uk/new/NOR.csv -o /tmp/NOR.csv
  python3 scripts/backtest_zones.py --csv /tmp/NOR.csv --league Eliteserien \
      --seasons 2016-2025

Tallene i tabellen "Brier-score" i eliteserien/index.html kommer herfra.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import fit_fast
from evaluate_model import load_seasons, season_range

# Sonene per liga. lo/hi er plasseringer, 1-indeksert; "bunn 2" uttrykkes med
# negative tall fra slutten (n-1, n).
LEAGUES = {
    "eliteserien": {
        "targets": [("gull", 1, 1), ("topp4", 1, 4), ("nedrykk", -2, -1)],
        "csv": "football-data",
    },
    "obos": {
        # 1. og 2. plass rykker direkte opp, 3.-6. spiller opprykkskvalifisering,
        # 15. og 16. rykker ned (14. plass er kvalik, ikke egen Brier-sone her).
        "targets": [("opprykk", 1, 2), ("topp6", 1, 6), ("nedrykk", -2, -1)],
        "csv": "obos",
    },
}


def load_obos_csv(path):
    """obos/data/obos_2012-2026.csv -> samme form som load_seasons(): sesong ->
    liste av kamper med dato, lag, mål og odds=None (ingen odds før 2026)."""
    import csv as _csv
    by_season = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            if not r["hjemmemaal"] or not r["bortemaal"]:
                continue  # kamp uten resultat
            by_season.setdefault(r["sesong"], []).append({
                "date": r["dato"], "home": r["hjemme"], "away": r["borte"],
                "hg": int(float(r["hjemmemaal"])), "ag": int(float(r["bortemaal"])),
                "odds": None,
            })
    for s in by_season:
        by_season[s].sort(key=lambda m: m["date"])
    return by_season

GMAX = 15
# Samme verdier som eliteserien/index.html og scripts/fit_model.py.
ODDS_WEIGHT, HALF_LIFE, L1_FULL, L2_FULL = 40.0, 28.0, 8.0, 24.0
L1_PLAIN, L2_PLAIN = 2.0, 6.0
FORM_K = 0.015
DRIFT_CAP_ATTCON, DRIFT_CAP_HAHC, DRIFT_REVERSION = 0.5, 0.35, 0.02
# Taket på målratene, som på siden. Kontrollert 29. september 2026: av 151 200
# tilpassede rater ut av utvalg (Eliteserien og OBOS 2012-2025, alle varianter
# og innstillinger i studien av tilpasningen) gikk ingen over 6; den største
# var 4,64. Taket binder altså ikke for tilpassede rater. Avklart.
MAX_LAMBDA_LOG = np.log(6.0)
DC_RHO = -0.04   # fra 1. oktober 2026 (var -0,38), se DC_RHO i eliteserien/index.html
# Rekke-rampen (bare i Form-visningen på siden, se STREAK_BONUS i index.html):
# k vokser med lengden på en strak rekke seire eller tap.
STREAK_BONUS, STREAK_CAP = 0.6, 5


def standings(matches, TI, n):
    """Poeng, målforskjell og scorede mål etter de gitte kampene."""
    pts, gd, gf = np.zeros(n), np.zeros(n), np.zeros(n)
    for m in matches:
        h, a = TI[m["home"]], TI[m["away"]]
        gd[h] += m["hg"] - m["ag"]; gd[a] += m["ag"] - m["hg"]
        gf[h] += m["hg"]; gf[a] += m["ag"]
        if m["hg"] > m["ag"]: pts[h] += 3
        elif m["hg"] < m["ag"]: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
    return pts, gd, gf


def final_positions(pts, gd, gf, teams):
    """Faktisk sluttplassering. Helt like lag skilles på navn (som compute() på
    siden), ikke tilfeldig -- fasiten skal være entydig."""
    order = sorted(range(len(teams)), key=lambda i: (-pts[i], -gd[i], -gf[i], teams[i]))
    pos = np.zeros(len(teams), dtype=int)
    for rank, i in enumerate(order):
        pos[i] = rank + 1
    return pos


def draw_goals(lh, la, rng, dc_rho):
    """Trekker (hjemmemål, bortemål) for hver simulering. lh/la: (N,).

    Uten Dixon-Coles er målene uavhengige Poisson. MED Dixon-Coles brukes
    forkastningsmetoden: tau endrer bare de fire cellene under 2-2, så et
    uavhengig Poisson-trekk godtas med sannsynlighet tau/tau_max, der tau_max
    er den største tau-verdien for DE lambdaene (1-rho for 1-1, eller
    1-lh*la*rho for 0-0, som kan være større). Bare trekk som ikke er godtatt
    ennå trekkes på nytt -- tester man de godtatte om igjen, favoriseres
    cellene med høy tau (1-1) kraftig, og fordelingen blir feil."""
    if not dc_rho:
        return rng.poisson(lh), rng.poisson(la)
    tau_max = np.maximum(1.0 - dc_rho, 1.0 - lh * la * dc_rho)
    hg = np.zeros(lh.shape, dtype=np.int64); ag = np.zeros(la.shape, dtype=np.int64)
    pending = np.ones(lh.shape, dtype=bool)
    for _ in range(60):
        idx = np.flatnonzero(pending)
        if idx.size == 0:
            break
        lhi, lai = lh[idx], la[idx]
        h = rng.poisson(lhi); a = rng.poisson(lai)
        tau = np.ones(idx.size)
        m = (h == 0) & (a == 0); tau[m] = np.maximum(0.0, 1 - lhi[m] * lai[m] * dc_rho)
        m = (h == 1) & (a == 0); tau[m] = np.maximum(0.0, 1 + lai[m] * dc_rho)
        m = (h == 0) & (a == 1); tau[m] = np.maximum(0.0, 1 + lhi[m] * dc_rho)
        m = (h == 1) & (a == 1); tau[m] = 1 - dc_rho
        acc = rng.random(idx.size) <= tau / tau_max[idx]
        hg[idx[acc]] = h[acc]; ag[idx[acc]] = a[acc]
        pending[idx[acc]] = False
    if pending.any():  # skal ikke skje; fall tilbake på uavhengig trekk
        hg[pending] = rng.poisson(lh[pending]); ag[pending] = rng.poisson(la[pending])
    return hg, ag


def simulate(remaining, TI, n, pts0, gd0, gf0, N, rng, *, mu, Hp,
             att=None, con=None, ha=None, hc=None, form_k=0.0, dc_rho=0.0,
             flat=None, ramp=False, faste=None):
    """Simulerer de gjenstående kampene N ganger og returnerer sluttplassering
    per lag og simulering, (N, n).

    flat: (lambda_hjemme, lambda_borte) -- tabellmodellen, der alle lag er like
    sterke. Ellers brukes lagstyrkene, og med form_k > 0 oppdateres de underveis
    i hver simulerte sesong (samme drift og tak som Workeren).

    faste: {indeks i remaining: (lambda_hjemme, lambda_borte)} -- faste rater
    for kamper med odds (varianten kjede), som oddsOverride i Workeren. Formen
    oppdateres mot de faste ratene."""
    pts = np.tile(pts0, (N, 1)); gd = np.tile(gd0, (N, 1)); gf = np.tile(gf0, (N, 1))
    if flat is None:
        A = np.tile(att, (N, 1)); C = np.tile(con, (N, 1))
        HA = np.tile(ha, (N, 1)); HC = np.tile(hc, (N, 1))
        A0, C0, HA0, HC0 = A.copy(), C.copy(), HA.copy(), HC.copy()
        # Rekke-rampe: lengden på inneværende strake rekke per lag og
        # simulering (+ for seire, - for tap, 0 rett etter uavgjort).
        streak = np.zeros((N, n), dtype=np.int16) if ramp else None
    for j, m in enumerate(remaining):
        h, a = TI[m["home"]], TI[m["away"]]
        if flat is not None:
            lh = np.full(N, flat[0]); la = np.full(N, flat[1])
        elif faste and j in faste:
            lh = np.full(N, faste[j][0]); la = np.full(N, faste[j][1])
        else:
            eh = np.clip(mu + Hp + A[:, h] + HA[:, h] + C[:, a] - HC[:, a], -9, MAX_LAMBDA_LOG)
            ea = np.clip(mu + A[:, a] - HA[:, a] + C[:, h] + HC[:, h], -9, MAX_LAMBDA_LOG)
            lh = np.exp(eh); la = np.exp(ea)
        hg, ag = draw_goals(lh, la, rng, dc_rho)
        gd[:, h] += hg - ag; gd[:, a] += ag - hg
        gf[:, h] += hg; gf[:, a] += ag
        pts[:, h] += np.where(hg > ag, 3, np.where(hg == ag, 1, 0))
        pts[:, a] += np.where(ag > hg, 3, np.where(hg == ag, 1, 0))
        if flat is None and form_k:
            rh = hg - lh; ra = ag - la
            if ramp:
                sh, sa = streak[:, h], streak[:, a]
                lenh = np.minimum(np.abs(sh), STREAK_CAP); lena = np.minimum(np.abs(sa), STREAK_CAP)
                kh = form_k * (1 + STREAK_BONUS * np.maximum(lenh - 1, 0))
                ka = form_k * (1 + STREAK_BONUS * np.maximum(lena - 1, 0))
                hw = hg > ag; aw = ag > hg; dr = hg == ag
                streak[:, h] = np.where(dr, 0, np.where(hw, np.where(sh > 0, sh + 1, 1), np.where(sh < 0, sh - 1, -1)))
                streak[:, a] = np.where(dr, 0, np.where(aw, np.where(sa > 0, sa + 1, 1), np.where(sa < 0, sa - 1, -1)))
            else:
                kh = ka = form_k
            def drift(arr, base, idx, delta, cap):
                v = arr[:, idx] + delta - DRIFT_REVERSION * (arr[:, idx] - base[:, idx])
                arr[:, idx] = np.clip(v, base[:, idx] - cap, base[:, idx] + cap)
            drift(A, A0, h, kh * rh, DRIFT_CAP_ATTCON); drift(HA, HA0, h, kh * rh, DRIFT_CAP_HAHC)
            drift(C, C0, a, kh * rh, DRIFT_CAP_ATTCON); drift(HC, HC0, a, -kh * rh, DRIFT_CAP_HAHC)
            drift(A, A0, a, ka * ra, DRIFT_CAP_ATTCON); drift(HA, HA0, a, -ka * ra, DRIFT_CAP_HAHC)
            drift(C, C0, h, ka * ra, DRIFT_CAP_ATTCON); drift(HC, HC0, h, ka * ra, DRIFT_CAP_HAHC)
    # Rangering: poeng, målforskjell, scorede mål, deretter tilfeldig (som siden).
    key = (pts * 1e9 + gd * 1e5 + gf * 1e1 + rng.random((N, n)))
    order = np.argsort(-key, axis=1, kind="stable")
    pos = np.empty((N, n), dtype=np.int16)
    np.put_along_axis(pos, order, np.arange(1, n + 1, dtype=np.int16)[None, :].repeat(N, 0), axis=1)
    return pos


def zone_probs(pos, n, targets):
    """Sannsynlighet for hver sone. lo/hi < 0 betyr plasser fra slutten."""
    out = []
    for _, lo, hi in targets:
        a = lo if lo > 0 else n + lo + 1
        b = hi if hi > 0 else n + hi + 1
        out.append(np.mean((pos >= a) & (pos <= b), axis=0))
    return out


ODDS_W = 0.7   # oddsens vekt i kommende kamper på siden (ODDS_W i index.html)


def neste_runde_med_odds(remaining, TI, n, r, dc_rho):
    """Faste rater for første runde etter kuttet, som siden regner dem:
    ODDS_W * oddsen + (1 - ODDS_W) * modellen, regnet om til målrater med
    fitRates (samme rutenett som siden, Dixon-Coles med dc_rho). Runden er de
    første kampene der ingen lag går igjen, høyst n/2."""
    import dc_rho_studie as S   # fitRates og utfallsrutenettet, som på siden
    att, con, ha, hc = (np.array(r[x]) for x in ("att", "con", "ha", "hc"))
    brukt, faste = set(), {}
    for j, m in enumerate(remaining):
        if m["home"] in brukt or m["away"] in brukt or len(brukt) >= n:
            break
        brukt |= {m["home"], m["away"]}
        if not m.get("odds"):
            continue
        h, a = TI[m["home"]], TI[m["away"]]
        lh = float(np.exp(np.clip(r["mu"] + r["H"] + att[h] + ha[h] + con[a] - hc[a], -9, MAX_LAMBDA_LOG)))
        la = float(np.exp(np.clip(r["mu"] + att[a] - ha[a] + con[h] + hc[h], -9, MAX_LAMBDA_LOG)))
        mH, _, mB = S.utfall(S.rutenett(np.array([lh]), np.array([la]), dc_rho))
        pH = ODDS_W * m["odds"][0] + (1 - ODDS_W) * float(mH[0])
        pB = ODDS_W * m["odds"][2] + (1 - ODDS_W) * float(mB[0])
        faste[j] = tuple(float(v) for v in S.fit_rates([pH], [pB], dc_rho)[0])
    return faste


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--league-zones", default="eliteserien", choices=sorted(LEAGUES),
                    help="hvilke soner og hvilket CSV-format")
    ap.add_argument("--league", default="Eliteserien")
    ap.add_argument("--seasons", default="2016-2025")
    ap.add_argument("--cuts", default="0.4,0.55,0.7,0.85",
                    help="andel av sesongens kamper som er spilt ved hvert kuttpunkt")
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--variants", default="", help="komma-separert delmengde av variantene")
    ap.add_argument("--name-map", default=str(Path(__file__).parent / "eliteserien_name_map.json"))
    ap.add_argument("--dc-rho-alt", type=float, default=None,
                    help="legger til varianten 'full rho=X': som full, bare med en annen "
                         "Dixon-Coles-rho, sammenlignet parvis med full (samme tilpasning og frø)")
    args = ap.parse_args()

    name_map = {}
    if Path(args.name_map).exists():
        name_map = json.loads(Path(args.name_map).read_text(encoding="utf-8"))
    lcfg = LEAGUES[args.league_zones]
    targets = [t[0] for t in lcfg["targets"]]
    if lcfg["csv"] == "obos":
        by_season = load_obos_csv(args.csv)
    else:
        by_season = load_seasons(args.csv, args.league, name_map)
    seasons = season_range(args.seasons)
    cuts = [float(c) for c in args.cuts.split(",")]
    # Frøet settes per (frø, sesong, kuttpunkt) inne i variantløkka, ikke her.
    # Se kommentaren der.

    # Varianter: (oddsvekt, l1, l2, form_k, dc_rho). Tilpasningen deles av
    # varianter med samme (oddsvekt, l1, l2), så en ekstra variant som bare
    # endrer simuleringen er nesten gratis.
    has_odds = lcfg["csv"] != "obos"   # OBOS-historikken har ingen odds
    ow = ODDS_WEIGHT if has_odds else 0.0
    VARIANTS = {
        "tabell":    None,  # egen sak: alle lag like sterke
        "poisson":   (0.0,  L1_PLAIN, L2_PLAIN, 0.0,    0.0),
        "+form":     (ow, L1_PLAIN, L2_PLAIN, FORM_K, 0.0),
        "+dc":       (ow, L1_PLAIN, L2_PLAIN, FORM_K, DC_RHO),
        "full":      (ow, L1_FULL,  L2_FULL,  FORM_K, DC_RHO),
        # Som full, men neste runde med sluttoddsen blandet inn (se toppen).
        "kjede":     (ow, L1_FULL,  L2_FULL,  FORM_K, DC_RHO, False, True),
        # Sidegren, ikke del av kjeden: rampen er IKKE med i modellen som brukes.
        "+rampe":    (ow, L1_PLAIN, L2_PLAIN, FORM_K, 0.0, True),
    }
    if has_odds:
        # Oddssteget settes inn mellom ren Poisson og formoppdateringen.
        VARIANTS = {"tabell": VARIANTS["tabell"], "poisson": VARIANTS["poisson"],
                    "+odds": (ODDS_WEIGHT, L1_PLAIN, L2_PLAIN, 0.0, 0.0),
                    "+form": VARIANTS["+form"], "+dc": VARIANTS["+dc"],
                    "full": VARIANTS["full"], "kjede": VARIANTS["kjede"],
                    "+rampe": VARIANTS["+rampe"]}
    else:
        del VARIANTS["kjede"]   # OBOS-historikken har ingen odds å blande inn
    ALT = None
    if args.dc_rho_alt is not None:
        ALT = f"rho {args.dc_rho_alt:g}"
        VARIANTS[ALT] = VARIANTS["full"][:4] + (args.dc_rho_alt,)
    if args.variants:
        keep = set(args.variants.split(",")) | {"basisrate"} | ({ALT} if ALT else set())
        VARIANTS = {k: v for k, v in VARIANTS.items() if k in keep}
    models = ["basisrate"] + list(VARIANTS)
    # Per observasjon, ikke bare summen: da kan forskjellen mellom to modeller
    # måles PARVIS (samme lag, samme kuttpunkt), og usikkerheten i forskjellen
    # regnes ut. Uten det kan man ikke si om en rad faktisk er bedre enn raden
    # over, eller om forskjellen er innenfor testens egen støy.
    err = {m: {t: [] for t in targets} for m in models}
    # Kuttpunktet hver observasjon hører til, i samme rekkefølge som err-listene,
    # så resultatet kan brytes ned per kuttpunkt etterpå.
    tags = {t: [] for t in targets}
    klynge = {t: [] for t in targets}   # sesong per observasjon
    # Rå sannsynlighet og utfall, til kalibreringen (samme observasjoner).
    raw = {m: {t: {"p": [], "y": []} for t in targets} for m in models}
    cnt = 0

    for season in seasons:
        if season not in by_season:
            print(f"  (hopper over {season}: ikke i CSV-en)", file=sys.stderr)
            continue
        # football-data.co.uk legger NEDRYKKSKVALIKEN i samme ligafil, så en
        # sesong ser ut til å ha 17 lag og 242 kamper. Kvaliklaget har bare et
        # par kamper og ville alltid endt sist. Behold bare lag med en full
        # serie (>=25 kamper) og kampene mellom dem.
        allm = by_season[season]
        played_cnt = {}
        for m in allm:
            played_cnt[m["home"]] = played_cnt.get(m["home"], 0) + 1
            played_cnt[m["away"]] = played_cnt.get(m["away"], 0) + 1
        full_season = {t for t, c in played_cnt.items() if c >= 25}
        matches = [m for m in allm if m["home"] in full_season and m["away"] in full_season]
        teams = sorted(full_season)
        TI = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        pts_f, gd_f, gf_f = standings(matches, TI, n)
        pos_f = final_positions(pts_f, gd_f, gf_f, teams)
        actual = {}
        for name, lo, hi in lcfg["targets"]:
            a = lo if lo > 0 else n + lo + 1
            b = hi if hi > 0 else n + hi + 1
            actual[name] = ((pos_f >= a) & (pos_f <= b)).astype(float)

        for kutt_nr, frac in enumerate(cuts):
            k = int(round(frac * len(matches)))
            if k < 10 or k >= len(matches):
                continue
            played, remaining = matches[:k], matches[k:]
            pts0, gd0, gf0 = standings(played, TI, n)
            ref = played[-1]["date"]

            # Basisraten kjenner bare hvor mange plasser sonen har.
            probs = {"basisrate": {name: np.full(n, ((hi if hi > 0 else n + hi + 1) -
                                                    (lo if lo > 0 else n + lo + 1) + 1) / n)
                                   for name, lo, hi in lcfg["targets"]}}
            fits = {}
            for name, cfg in VARIANTS.items():
                # FELLES TILFELDIGE TALL: hver variant får sin egen generator,
                # men med samme frø innenfor samme sesong og kuttpunkt. To
                # varianter med identiske parametre gir da bit-identiske tall,
                # og i alle parvise sammenligninger faller simuleringsstøyen ut
                # av differansen i stedet for å legge seg oppå den ekte
                # usikkerheten. Deler man én strøm, får hver variant sine egne
                # terninger, og kontrollrader blir ikke eksakt null.
                #
                # Frøet avhenger bare av (frø, sesong, kuttpunkt). Ett enkelt
                # kuttpunkt kan derfor kjøres for seg og gir nøyaktig samme
                # tall som det bidrar med i en full kjøring.
                rng = np.random.default_rng([args.seed, int(season), kutt_nr])
                if cfg is None:  # tabellmodellen: målnivå fra sesongen så langt
                    lh_flat = max(0.2, float(np.mean([m["hg"] for m in played])))
                    la_flat = max(0.2, float(np.mean([m["ag"] for m in played])))
                    pos = simulate(remaining, TI, n, pts0, gd0, gf0, args.sims, rng,
                                   mu=0.0, Hp=0.0, flat=(lh_flat, la_flat))
                else:
                    ow, l1, l2, fk, dcr = cfg[:5]
                    rmp = len(cfg) > 5 and cfg[5]
                    kjede = len(cfg) > 6 and cfg[6]
                    key = (ow, l1, l2)
                    if key not in fits:
                        fits[key] = fit_fast.fit_model_fast(
                            played, teams, TI, odds_weight=ow, half_life_goals=HALF_LIFE,
                            half_life_odds=HALF_LIFE, l1=l1, l2=l2, ref_date=ref, isolate_global=False)
                    r = fits[key]
                    faste = neste_runde_med_odds(remaining, TI, n, r, dcr) if kjede else None
                    pos = simulate(remaining, TI, n, pts0, gd0, gf0, args.sims, rng,
                                   mu=r["mu"], Hp=r["H"], att=np.array(r["att"]), con=np.array(r["con"]),
                                   ha=np.array(r["ha"]), hc=np.array(r["hc"]), form_k=fk,
                                   dc_rho=dcr, ramp=rmp, faste=faste)
                probs[name] = dict(zip(targets, zone_probs(pos, n, lcfg["targets"])))

            for name in models:
                for t in targets:
                    err[name][t].extend(((probs[name][t] - actual[t]) ** 2).tolist())
                    raw[name][t]["p"].extend(probs[name][t].tolist())
                    raw[name][t]["y"].extend(actual[t].tolist())
            for t in targets:
                tags[t].extend([frac] * n)
                klynge[t].extend([season] * n)
            cnt += n
            print(f"  {season} kutt {frac:.2f}: {k} spilt, {len(remaining)} igjen", file=sys.stderr)

    if not cnt:
        print("Ingen data å regne på.", file=sys.stderr)
        return 1
    print(f"\nBrier-score, {cnt} lag-observasjoner, {args.sims} simuleringer, "
          f"sesongene {seasons[0]}-{seasons[-1]}, kuttpunkt {args.cuts}")
    E = {m: {t: np.array(err[m][t]) for t in targets} for m in models}
    # Sesongklustret standardfeil. Lagene i samme sesong er IKKE uavhengige
    # forsøk: bare ett lag kan vinne serien, så bommer modellen på
    # gulloppgjøret bommer den på flere lag samtidig -- og den samme sesongen
    # går igjen på hvert kuttpunkt. Den vanlige standardfeilen teller hver
    # lagobservasjon som et eget forsøk og blir for liten. Denne teller
    # SESONGEN som forsøket, og er den som gjelder.
    KL = {t: np.array(klynge[t]) for t in targets}

    def se_klynge(d, g):
        """Klusterrobust standardfeil for gjennomsnittet av d, gruppert på g."""
        if len(d) == 0:
            return float("nan")
        m = d.mean()
        u = np.array([(d[g == c] - m).sum() for c in np.unique(g)])
        return float(np.sqrt((u ** 2).sum()) / len(d))

    def par(b, a, t, sel=None):
        """Parvis forskjell b-a for sone t, med begge standardfeilene."""
        d = E[b][t] - E[a][t]; g = KL[t]
        if sel is not None:
            d, g = d[sel], g[sel]
        sn = d.std(ddof=1) / np.sqrt(len(d))
        return d.mean(), se_klynge(d, g), sn
    print(f"{'Modell':<12}" + "".join(f"{t:>12}" for t in targets))
    for m in models:
        print(f"{m:<12}" + "".join(f"{E[m][t].mean():>12.4f}" for t in targets))
    # Hver sammenligning skal skille seg fra referansen på PRESIS én ting.
    # Rampen er en sidegren: den sammenlignes med +form, ikke med raden over.
    BASE_OF = {"tabell": "basisrate", "poisson": "tabell", "+odds": "poisson",
               "+form": "+odds" if "+odds" in E else "poisson",
               "+dc": "+form", "full": "+dc", "+rampe": "+form", "kjede": "full"}
    if ALT:
        BASE_OF[ALT] = "full"   # samme modell, bare en annen rho
    # Per kuttpunkt: hvor mye modellen slår tabellmodellen når det er mye igjen
    # å spille, mot når det nesten er over.
    if "tabell" in E and "full" in E:
        TAG = {t: np.array(tags[t]) for t in targets}
        print("\nPer kuttpunkt: full modell mot tabellmodell. Negativ forskjell = modellen er bedre.")
        for t in targets:
            print(f"\n  {t}")
            print(f"    {'spilt':>7}{'lag':>6}{'tabell':>9}{'full':>9}{'forskjell':>12}"
                  f"{'klustret':>11}{'uklustret':>11}")
            for frac in cuts:
                sel = TAG[t] == frac
                if not sel.any():
                    continue
                a, b = E["tabell"][t][sel], E["full"][t][sel]
                d, sk, sn = par("full", "tabell", t, sel)
                print(f"    {frac*100:>5.0f} %{int(sel.sum()):>6}{a.mean():>9.4f}{b.mean():>9.4f}"
                      f"{d:>+12.4f}{sk:>11.4f}{sn:>11.4f}")

    # Full modell mot tabellmodellen, samlet: den sammenligningen teksten under
    # Brier-tabellen bygger på.
    if "tabell" in E and "full" in E:
        print("\nFull modell mot tabellmodell, alle kuttpunkt samlet:")
        for t in targets:
            d, sk, sn = par("full", "tabell", t)
            print(f"    {t:<10}{d:>+9.4f} +/- {sk:.4f} klustret ({abs(d)/sk:.1f} SE)"
                  f"   [uklustret {sn:.4f}, {abs(d)/sn:.1f} SE]")

    # Kalibrering for modellen som er i bruk: prediksjonene delt i
    # tiprosentspenn, med snitt predikert og faktisk andel i hvert.
    if "full" in raw:
        print("\nKalibrering, full modell (samme observasjoner):")
        for t in targets:
            P = np.array(raw["full"][t]["p"]); Y = np.array(raw["full"][t]["y"])
            print(f"\n  {t}  ({len(P)} prediksjoner)")
            print(f"    {'intervall':<12}{'antall':>7}{'snitt pred.':>13}{'faktisk':>10}")
            for lo in range(0, 100, 10):
                hi = lo + 10
                sel = (P >= lo / 100) & (P < hi / 100) if hi < 100 else (P >= 0.9) & (P <= 1.0)
                if not sel.any():
                    print(f"    {lo}-{hi} %{'':<6}{0:>7}{'-':>13}{'-':>10}")
                    continue
                print(f"    {lo}-{hi} %{'':<6}{int(sel.sum()):>7}{P[sel].mean()*100:>12.1f}%{Y[sel].mean()*100:>9.1f}%")

    print("\nForskjell mot referansen, parvis (samme lag og kuttpunkt).")
    print("Standardfeilen er KLUSTRET PAA SESONG. Et avvik under to standardfeil")
    print("kan ikke skilles fra testens egen stoy.")
    print(f"{'Steg':<14}{'mot':<12}" + "".join(f"{t:>26}" for t in targets))
    for b in models[1:]:
        a = BASE_OF.get(b)
        if a is None or a not in E:
            continue
        cells = []
        for t in targets:
            d, sk, _sn = par(b, a, t)
            cells.append(f"{d:+.4f} +/- {sk:.4f} ({abs(d)/sk:.1f})".rjust(26))
        print(f"{b:<14}{a:<12}" + "".join(cells))

    print("\nSamme tabell UTEN klustring, til sammenligning.")
    print(f"{'Steg':<14}{'mot':<12}" + "".join(f"{t:>26}" for t in targets))
    for b in models[1:]:
        a = BASE_OF.get(b)
        if a is None or a not in E:
            continue
        cells = []
        for t in targets:
            d, _sk, sn = par(b, a, t)
            cells.append(f"{d:+.4f} +/- {sn:.4f} ({abs(d)/sn:.1f})".rjust(26))
        print(f"{b:<14}{a:<12}" + "".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
