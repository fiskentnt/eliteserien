#!/usr/bin/env python3
"""ELO-Odds w = 90 %: de seks funksjonene testversjonen trenger, KOPIERT
VERBATIM fra laben.

HVORFOR EN KOPI OG IKKE EN IMPORT. Testsiden skal kunne kjore uten at
tabellkalkulator-lab finnes paa maskinen, og den skal kunne slettes uten aa
etterlate noe. Derfor ligger koden her, ikke bak en import.

HVORFOR VERBATIM. Funksjonene er hentet ut med ast fra
tabellkalkulator-lab/eksperimenter/backtest_zones_med_eksperimenter.py, tegn
for tegn, uten omskriving, forenkling eller "forbedring". Enhver endring
ville gjort testsiden til en modell laben ikke har validert.
Kontroll: scripts/kontroll.py sammenligner mot labens egne funksjoner og
krever bit-eksakt likhet.

HVA MODELLEN ER:
  rating  r' = r + k(w) * u(w),  u(w) = (1-w)*(1+|gd|)^b*(s-e) + w*(m*-e)
  w = 0,90 og k = 83,37. k er LAAST fra k(w)-regelen paa innkjoringen
  2012-2013 og regnes ikke om naar andre parametere endres.
  Kamper UTEN odds: resultatleddet med HVA["k"] = 10, Elo-Goals sin egen k.
  1X2 kommer av en ordnet logistisk regresjon (OLR) paa ratingforskjellen.

RHO = 0 OVERALT. Laben testet fit_rates(..., 0.0) og simulerte med
dc_rho = 0. Produksjonens Full bruker -0,38, men aa arve den her ville laget
en ELO90-variant laben ikke har validert. Diagnostisk kontroll paa
2026-data: rho = 0 gir 2,772 maal per kamp mot faktisk 3,161, rho = -0,38 gir
4,154. Det er en kontroll, ikke et bevis for at 0 er optimalt.
"""
import math
import math as _math   # labens eget alias; _grid() bruker det

import numpy as np
from scipy import optimize

GMAX = 15
HVA = {"k": 10.0, "b": 1.0, "c": 10.0, "d": 400.0}
_GRID = {}
def hva_lap(R, kamper, p=HVA, logg=None):
    """Én gjennomkjøring av oppdateringsformelen, i kamprekkefølge.
    logg (valgfri liste) fylles med (ratingforskjell FØR kampen, utfall) --
    ratingforskjellen slik den var da kampen skulle spås, ikke i ettertid.
    HJEMMEFORDEL INNGÅR IKKE: forfatterne holder den utenfor ratingen med den
    begrunnelsen at lagene spiller like mange hjemme- og bortekamper. Den tas
    i stedet av prediksjonsmodellen."""
    for m in kamper:
        h, a = m["home"], m["away"]
        rh, ra = R.get(h, 0.0), R.get(a, 0.0)
        e = 1.0 / (1.0 + p["c"] ** ((ra - rh) / p["d"]))
        s = 1.0 if m["hg"] > m["ag"] else (0.5 if m["hg"] == m["ag"] else 0.0)
        if logg is not None:
            logg.append((rh - ra, 2 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 0)))
        # b = 0 gir (1+|maalforskjell|)^0 = 1, altsaa ELO-Result: bare utfallet.
        # b = 1 gir ELO-Goals, den publiserte ELOg.
        d = p["k"] * (1.0 + abs(m["hg"] - m["ag"])) ** p["b"] * (s - e)
        R[h] = rh + d
        R[a] = ra - d
    return R
def hva_startverdier(innkjor, p=HVA, tol=1e-10, maks=500):
    """Startverdiene: alle lag på 0, kjør formelen gjennom de to første
    sesongene, bruk sluttverdiene som nye startverdier, og gjenta til de
    står stille. Formelen er nullsum, så snittet blir 0 -- et lag som kommer
    opp senere og starter på 0, starter dermed på snittet."""
    lag = sorted({m["home"] for m in innkjor} | {m["away"] for m in innkjor})
    R = {t: 0.0 for t in lag}
    for i in range(maks):
        R2 = hva_lap(dict(R), innkjor, p)
        d = max(abs(R2[t] - R[t]) for t in R2)
        R = R2
        if d < tol:
            return R, i + 1, d
    return R, maks, d
def hva_mix_lap(R, kamper, p, hjemme_r, w, logg=None):
    """GENERALISERING mellom hva_lap (Elo-Goals) og hva_odds_lap (ELO-Odds).

    w er markedets andel av oppdateringssignalet:
        w = 0    NOYAKTIG hva_lap      -- Elo-Goals, maalforskjellen ganger inn
        w = 1    NOYAKTIG hva_odds_lap -- ELO-Odds, ingen maalforskjell

    SIGNALET blandes, ikke maalet:

        u(w) = (1-w) * (1+|g_h - g_a|)^b * (s - e)  +  w * (m* - e)
        R_h += k(w) * u(w)   ,   R_a -= k(w) * u(w)

    hvor s er 1/0.5/0, m* er markedets forventede score paa NOYTRAL bane (se
    hva_odds_lap), og e er Elo-forventningen. De to leddene beholder hver sin
    naturlige form: maalforskjellen ganger bare inn paa resultatleddet, fordi
    Wunderlich og Memmert IKKE har en maalforskjellsmultiplikator i ELO-Odds.
    Ville vi i stedet blandet maalene, a = (1-w)*s + w*m*, og beholdt
    multiplikatoren, ville w = 1 ikke vaert ELO-Odds.

    HVA SOM ER ARTIKKELENS METODE: w = 1, m* = pH + 0,5*pU regnet om til
    noytral bane, ingen maalforskjell, egen k. HVA SOM ER VAR INTERPOLASJON:
    alt for 0 < w < 1, og selve formen paa blandingen.

    k(w) OPPGIS AV KALLEREN og er lik for alle sesonger og kuttpunkt. Den
    retunes ikke per steg. Signalene har ulik skala -- malt paa innkjoringen
    er snitt|u(0)| = 0,93 mot snitt|u(1)| = 0,050, altsaa 18,6 ganger -- og
    det er nettopp derfor artikkelen bruker k rundt 175 for ELO-Odds mot 10
    for ELO-Goals.

    KAMPER UTEN ODDS (og bare ved w > 0) faller tilbake paa resultatleddet
    med ELO-GOALS SIN k (HVA["k"] = 10), ikke k(w). Ved w = 0 er det ingen
    fallback: modellen ER Elo-Goals, og kallerens k brukes. Se kommentaren i koden: med k(w) ville en
    kamp uten odds flyttet ratingen opp til 18,6 ganger mer enn Elo-Goals
    gjor, og varianten vaert mest ustabil der dekningen er tynnest.
    Konsekvensen er at ved 0 % oddsdekning er ALLE steg bit-eksakt lik
    w = 0, altsaa vanlig Elo-Goals.

    Eliteserien har 100 % dekning i alle sesongene 2012-2026, saa fallbacken
    slaar ikke inn der. OBOS har 3359 av 3360 for 2012-2025 (en
    oddshistorikk som ikke er offentlig, snitt av sluttodds, tilbakefyll)
    og 184 av 184 i 2026 (OddsPapi), saa
    fallbacken slaar inn i noyaktig EN kamp: 2021-11-10
    Sogndal-Stjordals-Blink.
    """
    c, d, k, b = p["c"], p["d"], p["k"], p["b"]
    for m in kamper:
        h, a = m["home"], m["away"]
        rh, ra = R.get(h, 0.0), R.get(a, 0.0)
        e = 1.0 / (1.0 + c ** ((ra - rh) / d))
        if logg is not None:
            logg.append((rh - ra, 2 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 0)))
        s = 1.0 if m["hg"] > m["ag"] else (0.5 if m["hg"] == m["ag"] else 0.0)
        o = m.get("odds")
        if o and w > 0.0:
            mk = min(max(o[0] + 0.5 * o[1], 1e-6), 1 - 1e-6)
            dr_mkt = -d * math.log(1.0 / mk - 1.0) / math.log(c)
            mstar = 1.0 / (1.0 + c ** (-(dr_mkt - hjemme_r) / d))
            res_ledd = (1.0 + abs(m["hg"] - m["ag"])) ** b * (s - e)
            delta = k * ((1.0 - w) * res_ledd + w * (mstar - e))
        else:
            # FALLBACK NAAR ODDSEN MANGLER: resultatleddet med ELO-GOALS SIN
            # EGEN k, ikke k(w).
            #
            # Her sto det k, og det var galt. k(w) er skalert opp fordi
            # markedssignalet er lite -- 186 ved w = 1 mot 10 for Elo-Goals.
            # Brukt paa resultatleddet ville en kamp UTEN odds flyttet
            # ratingen 18,6 ganger mer enn Elo-Goals gjor. En oddsdrevet
            # rating ville dermed vaert mest ustabil nettopp der
            # markedsdekningen er tynn, altsaa i OBOS. Funnet av kontrollen
            # som krever at alle steg blir bit-eksakt lik w = 0 naar all odds
            # fjernes.
            #
            # HVA["k"] = 10 er Elo-Goals sin k. Med den blir en kamp uten
            # odds behandlet NOYAKTIG som Elo-Goals behandler den, uansett w.
            #
            # TO TILFELLER, og de maa skilles. Betingelsen over er
            # "o and w > 0", saa w = 0 lander ogsaa her -- og da er modellen
            # IKKE i fallback, den ER Elo-Goals. Da skal kallerens k brukes,
            # ellers ville hva_mix_lap(w=0) ignorert p["k"] og docstringens
            # "w = 0 NOYAKTIG hva_lap" bare holdt for k = 10. Ingen kjort
            # variant har w = 0 med k != 10 (sveip-0 og sveipk-0 bruker
            # begge 10.00), saa ingen publiserte tall er rammet -- men en
            # k-folsomhetskontroll ved w = 0 ville blitt stille feil.
            # SAMME UTTRYKKSREKKEFOLGE SOM hva_lap, med vilje. Skrevet som
            # kk * (mult * (s-e)) i stedet for (kk * mult) * (s-e) ble avviket
            # mot hva_lap 5,7e-14 -- ren flyttallsassosiativitet ved
            # maskinepsilon, akkumulert gjennom vandringen. Kontroll 1 saa den
            # ikke, for den sammenligner stegene med HVERANDRE, og alle brukte
            # samme rekkefolge. Kontroll 3 fanget den.
            delta = (k if w == 0.0 else HVA["k"]) \
                * (1.0 + abs(m["hg"] - m["ag"])) ** b * (s - e)
        R[h] = rh + delta
        R[a] = ra - delta
    return R
def hjemmefordel_i_rating(kamper, p=HVA):
    """Hjemmefordelen i ratingpoeng, lest rett ut av markedet: snittet av den
    ratingforskjellen oddsen impliserer. Over mange kamper er den ekte
    styrkeforskjellen i snitt null, saa det som staar igjen er hjemmefordelen."""
    c, d = p["c"], p["d"]
    v = []
    for m in kamper:
        o = m.get("odds")
        if not o:
            continue
        mk = min(max(o[0] + 0.5 * o[1], 1e-6), 1 - 1e-6)
        v.append(-d * math.log(1.0 / mk - 1.0) / math.log(c))
    return float(np.mean(v)) if v else 0.0
def olr_tilpass(dr, y):
    """Ordinal logistisk regresjon med ratingforskjellen som eneste
    forklaringsvariabel -- prediksjonsmodellen i artikkelen. Elo gir ingen
    sannsynlighet for uavgjort, og det er nettopp derfor de bruker OLR.
    Hjemmefordelen ligger i skjæringspunktene: utfallet er kodet sett fra
    hjemmelaget, så det de fanger opp er hjemmefordelen i snitt."""
    dr = np.asarray(dr, dtype=float); y = np.asarray(y, dtype=int)
    sig = lambda z: 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))

    def nll(par):
        t1, lg, beta = par
        t2 = t1 + np.exp(lg)          # sikrer t1 < t2
        z = beta * dr
        p0 = sig(t1 - z)
        p1 = sig(t2 - z) - p0
        p2 = 1.0 - sig(t2 - z)
        pr = np.where(y == 0, p0, np.where(y == 1, p1, p2))
        return -np.sum(np.log(np.clip(pr, 1e-12, None)))

    best = None
    for start in ([-1.0, 0.0, 0.01], [-0.5, -0.5, 0.005], [-1.5, 0.5, 0.02]):
        r = optimize.minimize(nll, start, method="Nelder-Mead",
                              options={"maxiter": 4000, "xatol": 1e-9, "fatol": 1e-9})
        if best is None or r.fun < best.fun:
            best = r
    t1, lg, beta = best.x
    return float(t1), float(t1 + np.exp(lg)), float(beta)
def olr_sannsyn(par, dr):
    """(hjemmeseier, uavgjort, borteseier) for en ratingforskjell."""
    t1, t2, beta = par
    sig = lambda z: 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))
    z = beta * dr
    p0 = sig(t1 - z)                  # borteseier
    p2 = 1.0 - sig(t2 - z)            # hjemmeseier
    return p2, 1.0 - p0 - p2, p0
def _grid(rho):
    """Forhåndsregnet utfallstabell over et rutenett av målrater. Rutenettet er
    fast, så H og B regnes ut ÉN gang per rho og gjenbrukes for alle kamper --
    ellers ville rutenettsøket per kamp tatt dager."""
    if rho in _GRID:
        return _GRID[rho]
    g = np.round(np.arange(0.15, 4.5001, 0.01), 3)
    k = np.arange(15)
    lf = np.array([_math.factorial(int(i)) for i in k], dtype=float)
    P = np.exp(-g)[:, None] * g[:, None] ** k[None, :] / lf[None, :]   # (G,15)
    L = np.tril(np.ones((15, 15)), -1)          # i > j
    H = P @ L @ P.T                              # hjemmeseier
    D = P @ P.T                                  # uavgjort
    if rho:
        lh = g[:, None]; la = g[None, :]
        t00 = np.maximum(0.0, 1 - lh * la * rho) - 1
        t10 = np.maximum(0.0, 1 + la * rho) - 1
        t01 = np.maximum(0.0, 1 + lh * rho) - 1
        t11 = (1 - rho) - 1
        p0h, p1h = P[:, 0][:, None], P[:, 1][:, None]
        p0a, p1a = P[:, 0][None, :], P[:, 1][None, :]
        D = D + p0h * p0a * t00 + p1h * p1a * t11
        H = H + p1h * p0a * t10
    B = 1 - H - D
    _GRID[rho] = (g, H, B)
    return _GRID[rho]
def fit_rates(pH, pB, rho):
    """Finner (lh, la) som gir utfallssjansene pH/pB -- samme jobb som
    fitRates() i Workeren, men som oppslag i rutenettet over."""
    g, H, B = _grid(rho)
    e = (H - pH) ** 2 + (B - pB) ** 2
    i, j = np.unravel_index(int(np.argmin(e)), e.shape)
    return float(g[i]), float(g[j])
