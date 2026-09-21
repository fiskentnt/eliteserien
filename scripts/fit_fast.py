"""Rask, vektorisert modelltilpasning med analytisk gradient og L-BFGS-B.
Erstatter den håndskrevne gradientnedstigningen (1500-3000 steg) og den
finite-difference-baserte oddsgradienten (3 grid-evalueringer per kamp per steg).
"""
import math
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

# Samme grense overalt (index.html sin hovedtråd og Worker brukte 10 -- en
# reell inkonsistens siden tilpasningen her summerte til 12; med lambda opp
# til 6 er halen forbi 10 ikke helt ubetydelig). 15 gir god margin alle steder.
GMAX = 15
_K = np.arange(GMAX+1)
_LOGFACT = gammaln(_K+1)
_HGRID, _AGRID = np.meshgrid(_K, _K, indexing='ij')  # h varierer over rader, a over kolonner
_H_MASK = (_HGRID > _AGRID)
_D_MASK = (_HGRID == _AGRID)
_B_MASK = (_HGRID < _AGRID)

def pois_pmf(lam):
    """Poisson-pmf for k=0..GMAX, vektorisert. lam: skalar."""
    return np.exp(-lam + _K*np.log(lam) - _LOGFACT)

def outcome_and_grad(lh, la):
    """Returnerer (H,D,B, dH_dlh,dD_dlh,dB_dlh, dH_dla,dD_dla,dB_dla) analytisk."""
    ph, pa = pois_pmf(lh), pois_pmf(la)
    P = np.outer(ph, pa)  # P[h,a]
    H = P[_H_MASK].sum(); D = P[_D_MASK].sum(); B = P[_B_MASK].sum()
    # d/dlam Pois(k;lam) = Pois(k;lam)*(k/lam - 1)
    fac_h = (_K/lh - 1.0)[:,None]  # (GMAX+1,1), brukes langs h-aksen
    fac_a = (_K/la - 1.0)[None,:]  # (1,GMAX+1), brukes langs a-aksen
    dP_dlh = P*fac_h
    dP_dla = P*fac_a
    dH_dlh = dP_dlh[_H_MASK].sum(); dD_dlh = dP_dlh[_D_MASK].sum(); dB_dlh = dP_dlh[_B_MASK].sum()
    dH_dla = dP_dla[_H_MASK].sum(); dD_dla = dP_dla[_D_MASK].sum(); dB_dla = dP_dla[_B_MASK].sum()
    return H,D,B, dH_dlh,dD_dlh,dB_dlh, dH_dla,dD_dla,dB_dla

def prep_matches(matches, TI, ref_date, half_life_goals, half_life_odds):
    from datetime import date as Dt
    ry,rm,rd = map(int, ref_date.split('-'))
    ref = Dt(ry,rm,rd)
    H_IDX=[]; A_IDX=[]; HG=[]; AG=[]; W_G=[]; W_O=[]; ODDS=[]
    for m in matches:
        y,mo,d = map(int, m['date'].split('-'))
        days = (ref-Dt(y,mo,d)).days
        H_IDX.append(TI[m['home']]); A_IDX.append(TI[m['away']])
        HG.append(m['hg']); AG.append(m['ag'])
        W_G.append(0.5**(days/half_life_goals))
        W_O.append(0.5**(days/half_life_odds))
        ODDS.append(m.get('odds'))
    return dict(h=np.array(H_IDX), a=np.array(A_IDX), hg=np.array(HG,dtype=float),
                ag=np.array(AG,dtype=float), wg=np.array(W_G), wo=np.array(W_O), odds=ODDS)

def fit_model_fast(matches, teams, TI, odds_weight=0.0, half_life_goals=70, half_life_odds=None,
                    l1=2.0, l2=6.0, ref_date='2026-09-20', x0=None, isolate_global=True):
    """isolate_global: hvis True (anbefalt), påvirker oddsgradienten kun de
    lagvise parametrene (att/con/ha/hc), ikke det generelle målnivået (mu)
    eller hjemmefordelen (H) — de bestemmes utelukkende av faktiske mål."""
    if half_life_odds is None:
        half_life_odds = half_life_goals
    n = len(teams)
    d = prep_matches(matches, TI, ref_date, half_life_goals, half_life_odds)
    nm = len(d['h'])
    has_odds = [o is not None for o in d['odds']]
    odds_arr = np.array([o if o is not None else (0,0,0) for o in d['odds']])

    def unpack(x):
        mu, Hp = x[0], x[1]
        att = x[2:2+n]; con = x[2+n:2+2*n]; ha = x[2+2*n:2+3*n]; hc = x[2+3*n:2+4*n]
        return mu, Hp, att, con, ha, hc

    def loss_and_grad(x):
        mu, Hp, att, con, ha, hc = unpack(x)
        h, a = d['h'], d['a']
        eh = mu + Hp + att[h] + ha[h] + con[a] - hc[a]
        ea = mu + att[a] - ha[a] + con[h] + hc[h]
        # Tak mot overflow: eh/ea klippes til [-9,9] (lh/la maks ~8100), uansett oddsvekt.
        eh = np.clip(eh, -9.0, 9.0); ea = np.clip(ea, -9.0, 9.0)
        lh = np.exp(eh); la = np.exp(ea)

        loss = np.sum(d['wg']*(lh - d['hg']*np.log(lh))) + np.sum(d['wg']*(la - d['ag']*np.log(la)))
        deh_goal = d['wg']*(lh - d['hg'])
        dea_goal = d['wg']*(la - d['ag'])
        deh_team = deh_goal.copy()
        dea_team = dea_goal.copy()

        if odds_weight>0:
            for i in range(nm):
                if not has_odds[i]: continue
                Hh,Dd,Bb, dHdlh,dDdlh,dBdlh, dHdla,dDdla,dBdla = outcome_and_grad(lh[i], la[i])
                mH,mD,mA = odds_arr[i]
                loss += odds_weight*d['wo'][i]*((Hh-mH)**2+(Dd-mD)**2+(Bb-mA)**2)
                dL_dlh = 2*(Hh-mH)*dHdlh + 2*(Dd-mD)*dDdlh + 2*(Bb-mA)*dBdlh
                dL_dla = 2*(Hh-mH)*dHdla + 2*(Dd-mD)*dDdla + 2*(Bb-mA)*dBdla
                deh_team[i] += odds_weight*d['wo'][i]*dL_dlh*lh[i]
                dea_team[i] += odds_weight*d['wo'][i]*dL_dla*la[i]

        loss += 0.5*l1*np.sum(att**2) + 0.5*l1*np.sum(con**2) + 0.5*l2*np.sum(ha**2) + 0.5*l2*np.sum(hc**2)

        # mu/Hp (globalt målnivå + hjemmefordel): kun målbasert hvis isolate_global
        deh_mu, dea_mu = (deh_goal, dea_goal) if isolate_global else (deh_team, dea_team)
        g_mu = np.sum(deh_mu)+np.sum(dea_mu)
        g_Hp = np.sum(deh_mu)
        # att/con/ha/hc (lagvise forskjeller): mål + odds
        g_att = np.zeros(n); g_con = np.zeros(n); g_ha = np.zeros(n); g_hc = np.zeros(n)
        np.add.at(g_att, h, deh_team); np.add.at(g_att, a, dea_team)
        np.add.at(g_con, a, deh_team); np.add.at(g_con, h, dea_team)
        np.add.at(g_ha, h, deh_team); np.add.at(g_ha, a, -dea_team)
        np.add.at(g_hc, a, -deh_team); np.add.at(g_hc, h, dea_team)
        g_att += l1*att; g_con += l1*con; g_ha += l2*ha; g_hc += l2*hc

        grad = np.concatenate(([g_mu],[g_Hp], g_att, g_con, g_ha, g_hc))
        return loss, grad

    if x0 is None:
        x0 = np.zeros(2+4*n); x0[1] = 0.2
    res = minimize(loss_and_grad, x0, jac=True, method='L-BFGS-B',
                    options={'maxiter':1000, 'maxls':100, 'maxcor':20, 'ftol':1e-12, 'gtol':1e-9})
    if not res.success:
        # Prøv på nytt fra et lett forstyrret punkt — løser sjeldne linjesøk-feil
        res = minimize(loss_and_grad, res.x + np.random.RandomState(0).randn(len(res.x))*1e-3,
                        jac=True, method='L-BFGS-B',
                        options={'maxiter':1000, 'maxls':100, 'maxcor':20, 'ftol':1e-12, 'gtol':1e-9})
    mu,Hp,att,con,ha,hc = unpack(res.x)

    def rate(home,away):
        h,a = TI[home], TI[away]
        eh = min(9.0, max(-9.0, mu+Hp+att[h]+ha[h]+con[a]-hc[a]))
        ea = min(9.0, max(-9.0, mu+att[a]-ha[a]+con[h]+hc[h]))
        return math.exp(eh), math.exp(ea)
    return {'mu':mu,'H':Hp,'att':att,'con':con,'ha':ha,'hc':hc,'rate':rate,'nit':res.nit,'success':res.success}
