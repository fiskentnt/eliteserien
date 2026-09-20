"""Utvidelse av fit_fast.py med valgfri Dixon-Coles-korreksjon (rho) for de
fire lave resultatene 0-0, 1-0, 0-1, 1-1. Brukes til å teste om korreksjonen
forbedrer treffsikkerheten (fase A) — separat fra produksjonsmodulen
fit_fast.py inntil den eventuelt tas i bruk.
"""
import math
import numpy as np
from scipy.optimize import minimize
import fit_fast  # gjenbruker GMAX, pois_pmf, grid-masker

GMAX = fit_fast.GMAX
_K = fit_fast._K
_HGRID, _AGRID = fit_fast._HGRID, fit_fast._AGRID
_H_MASK, _D_MASK, _B_MASK = fit_fast._H_MASK, fit_fast._D_MASK, fit_fast._B_MASK


def dc_tau(h, a, lh, la, rho):
    """Dixon-Coles korreksjonsfaktor for cellen (h hjemmemål, a bortemål)."""
    if h == 0 and a == 0: return 1 - lh*la*rho
    if h == 0 and a == 1: return 1 + lh*rho
    if h == 1 and a == 0: return 1 + la*rho
    if h == 1 and a == 1: return 1 - rho
    return 1.0

def dc_grid(lh, la, rho):
    """Full (GMAX+1)x(GMAX+1)-sannsynlighetsgrid med DC-korreksjon, renormalisert."""
    P = np.outer(fit_fast.pois_pmf(lh), fit_fast.pois_pmf(la))
    P[0,0] *= (1 - lh*la*rho)
    P[0,1] *= (1 + lh*rho)
    P[1,0] *= (1 + la*rho)
    P[1,1] *= (1 - rho)
    P = np.clip(P, 0, None)
    return P / P.sum()

def outcome_dc(lh, la, rho):
    P = dc_grid(lh, la, rho)
    return P[_H_MASK].sum(), P[_D_MASK].sum(), P[_B_MASK].sum()

def diff_dist_dc(lh, la, rho):
    """Sannsynlighet for målforskjell i 7 klasser (som goal_realism_eval), med DC."""
    P = dc_grid(lh, la, rho)
    diffs = _HGRID - _AGRID
    bins = np.clip(diffs, -3, 3) + 3
    probs = np.array([P[bins==b].sum() for b in range(7)])
    return probs / probs.sum()


def fit_model_dc(matches, teams, TI, odds_weight=0.0, half_life_goals=70, half_life_odds=None,
                  l1=2.0, l2=6.0, ref_date='2026-09-20', x0=None, isolate_global=True,
                  use_dc=True, rho_l2=1.0):
    """Som fit_fast.fit_model_fast, men med valgfri Dixon-Coles rho (use_dc=True/False).
    rho_l2: svak regularisering av rho mot 0 (unngår ekstreme verdier ved lite data)."""
    if half_life_odds is None:
        half_life_odds = half_life_goals
    n = len(teams)
    d = fit_fast.prep_matches(matches, TI, ref_date, half_life_goals, half_life_odds)
    nm = len(d['h'])
    has_odds = [o is not None for o in d['odds']]
    odds_arr = np.array([o if o is not None else (0,0,0) for o in d['odds']])
    hg_i = d['hg'].astype(int); ag_i = d['ag'].astype(int)

    N_EXTRA = 1 if use_dc else 0  # rho

    def unpack(x):
        mu, Hp = x[0], x[1]
        att = x[2:2+n]; con = x[2+n:2+2*n]; ha = x[2+2*n:2+3*n]; hc = x[2+3*n:2+4*n]
        rho = x[2+4*n] if use_dc else 0.0
        return mu, Hp, att, con, ha, hc, rho

    def loss_and_grad(x):
        mu, Hp, att, con, ha, hc, rho = unpack(x)
        h, a = d['h'], d['a']
        eh = mu + Hp + att[h] + ha[h] + con[a] - hc[a]
        ea = mu + att[a] - ha[a] + con[h] + hc[h]
        eh = np.clip(eh, -9.0, 9.0); ea = np.clip(ea, -9.0, 9.0)
        lh = np.exp(eh); la = np.exp(ea)

        # --- Målbasert ledd: Poisson, med analytisk DC-korreksjon for de 4 spesialcellene ---
        loss = np.sum(d['wg']*(lh - d['hg']*np.log(lh))) + np.sum(d['wg']*(la - d['ag']*np.log(la)))
        deh_goal = d['wg']*(lh - d['hg'])
        dea_goal = d['wg']*(la - d['ag'])
        g_rho_goal = 0.0

        if use_dc:
            for i in range(nm):
                hi, ai = hg_i[i], ag_i[i]
                if hi>1 or ai>1: continue  # tau=1 utenfor de 4 cellene, ingen endring
                tau = dc_tau(hi, ai, lh[i], la[i], rho)
                if tau <= 1e-9: tau = 1e-9
                if hi==0 and ai==0:
                    dtau_dlh, dtau_dla, dtau_drho = -la[i]*rho, -lh[i]*rho, -lh[i]*la[i]
                elif hi==0 and ai==1:
                    dtau_dlh, dtau_dla, dtau_drho = rho, 0.0, lh[i]
                elif hi==1 and ai==0:
                    dtau_dlh, dtau_dla, dtau_drho = 0.0, rho, la[i]
                else:  # 1,1
                    dtau_dlh, dtau_dla, dtau_drho = 0.0, 0.0, -1.0
                loss += -d['wg'][i]*math.log(tau)
                deh_goal[i] += -d['wg'][i]/tau * dtau_dlh * lh[i]
                dea_goal[i] += -d['wg'][i]/tau * dtau_dla * la[i]
                g_rho_goal += -d['wg'][i]/tau * dtau_drho

        deh_team = deh_goal.copy(); dea_team = dea_goal.copy()

        # --- Oddsledd: H/D/B (med DC hvis på), finite-diff gradient (grid er billig: 13x13) ---
        g_rho_odds = 0.0
        if odds_weight>0:
            eps = 1e-3
            for i in range(nm):
                if not has_odds[i]: continue
                if use_dc:
                    Hh,Dd,Bb = outcome_dc(lh[i], la[i], rho)
                else:
                    Hh,Dd,Bb,*_ = fit_fast.outcome_and_grad(lh[i], la[i])
                mH,mD,mA = odds_arr[i]
                loss += odds_weight*d['wo'][i]*((Hh-mH)**2+(Dd-mD)**2+(Bb-mA)**2)
                if use_dc:
                    Hp2,Dp2,Bp2 = outcome_dc(lh[i]+eps, la[i], rho)
                    Ha2,Da2,Ba2 = outcome_dc(lh[i], la[i]+eps, rho)
                    dHdlh=(Hp2-Hh)/eps; dDdlh=(Dp2-Dd)/eps; dBdlh=(Bp2-Bb)/eps
                    dHdla=(Ha2-Hh)/eps; dDdla=(Da2-Dd)/eps; dBdla=(Ba2-Bb)/eps
                else:
                    _,_,_,dHdlh,dDdlh,dBdlh,dHdla,dDdla,dBdla = fit_fast.outcome_and_grad(lh[i], la[i])
                dLdlh = 2*(Hh-mH)*dHdlh + 2*(Dd-mD)*dDdlh + 2*(Bb-mA)*dBdlh
                dLdla = 2*(Hh-mH)*dHdla + 2*(Dd-mD)*dDdla + 2*(Bb-mA)*dBdla
                deh_team[i] += odds_weight*d['wo'][i]*dLdlh*lh[i]
                dea_team[i] += odds_weight*d['wo'][i]*dLdla*la[i]
                if use_dc:
                    Hr,Dr,Br = outcome_dc(lh[i], la[i], rho+eps)
                    dLdrho = 2*(Hh-mH)*(Hr-Hh)/eps + 2*(Dd-mD)*(Dr-Dd)/eps + 2*(Bb-mA)*(Br-Bb)/eps
                    g_rho_odds += odds_weight*d['wo'][i]*dLdrho

        loss += 0.5*l1*np.sum(att**2) + 0.5*l1*np.sum(con**2) + 0.5*l2*np.sum(ha**2) + 0.5*l2*np.sum(hc**2)
        if use_dc:
            loss += 0.5*rho_l2*rho**2

        deh_mu, dea_mu = (deh_goal, dea_goal) if isolate_global else (deh_team, dea_team)
        g_mu = np.sum(deh_mu)+np.sum(dea_mu)
        g_Hp = np.sum(deh_mu)
        g_att = np.zeros(n); g_con = np.zeros(n); g_ha = np.zeros(n); g_hc = np.zeros(n)
        np.add.at(g_att, h, deh_team); np.add.at(g_att, a, dea_team)
        np.add.at(g_con, a, deh_team); np.add.at(g_con, h, dea_team)
        np.add.at(g_ha, h, deh_team); np.add.at(g_ha, a, -dea_team)
        np.add.at(g_hc, a, -deh_team); np.add.at(g_hc, h, dea_team)
        g_att += l1*att; g_con += l1*con; g_ha += l2*ha; g_hc += l2*hc

        grad = np.concatenate(([g_mu],[g_Hp], g_att, g_con, g_ha, g_hc))
        if use_dc:
            g_rho = g_rho_goal + g_rho_odds + rho_l2*rho
            grad = np.concatenate((grad, [g_rho]))
        return loss, grad

    if x0 is None:
        x0 = np.zeros(2+4*n+N_EXTRA); x0[1] = 0.2
    opts = {'maxiter':1000, 'maxls':100, 'maxcor':20, 'ftol':1e-12, 'gtol':1e-9}
    res = minimize(loss_and_grad, x0, jac=True, method='L-BFGS-B', options=opts)
    if not res.success:
        res = minimize(loss_and_grad, res.x + np.random.RandomState(0).randn(len(res.x))*1e-3,
                        jac=True, method='L-BFGS-B', options=opts)
    mu,Hp,att,con,ha,hc,rho = unpack(res.x)

    def rate(home,away):
        h,a = TI[home], TI[away]
        eh = min(9.0, max(-9.0, mu+Hp+att[h]+ha[h]+con[a]-hc[a]))
        ea = min(9.0, max(-9.0, mu+att[a]-ha[a]+con[h]+hc[h]))
        return math.exp(eh), math.exp(ea)
    return {'mu':mu,'H':Hp,'att':att,'con':con,'ha':ha,'hc':hc,'rho':rho,
            'rate':rate,'nit':res.nit,'success':res.success}
