#!/usr/bin/env python3
"""Bygger ELO-Odds 90-modellen for testsiden /elo-test/.

LESER PRODUKSJONENS EGNE FILER, ingen kopier:
    eliteserien/data/matches.json    spilte 2026-kamper
    eliteserien/data/odds.json       sluttodds 2026, avviggede sannsynligheter
    eliteserien/data/fixtures.json   terminlisten
    eliteserien/data/odds_upcoming.json  markedet paa kommende kamper
og ETT fryst grunnlag, som produksjonen ikke har:
    elo-test/emodell/historikk.json  2012-2025, kamper og avviggede sluttodds

HVORFOR HISTORIKKEN MAA FRYSES: produksjonen har bare 2026 (168 kamper).
ELO90-ratingen bygges kronologisk fra 2012, og hjemmefordelen regnes av ALLE
kamper med odds, saa hele vandringen maa gjores om ved hver oppdatering. Da maa
det historiske grunnlaget ligge her. Det er avviggede sannsynligheter, samme
datatype produksjonen alt publiserer i odds.json.

REKKEFOLGEN ER LABENS, ledd for ledd (diagnose_2026_eloodds.py):
  1  hjemmefordel av ALLE kamper med odds, historikk + spilte 2026
  2  startverdier: hva_startverdier paa innkjoringen 2012+2013, med HVA
     (k = 10), iterert til konvergens
  3  en KOPI av startratingene vandres over innkjoringen for aa fylle
     OLR-loggen -- ratingene flyttes IKKE en gang til
  4  2014 til 2026 vandres kronologisk med w = 0,90 og k = 83,37
  5  OLR tilpasses hele loggen
  6  1X2 per gjenstaaende kamp av OLR paa ratingforskjellen
  7  lambda av fit_rates(pH, pB, rho = 0)

LAAST: k = 83,37, fra k(w)-regelen paa innkjoringen 2012-2013. Regnes IKKE om
naar hjemmefordelen eller andre lopende parametere endres.
BEREGNES PAA NYTT hver gang: hjemmefordel, startverdier, rating, OLR.
RHO = 0 OVERALT.

Bruk:
    python3 elo-test/scripts/bygg.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HER = Path(__file__).resolve().parent
sys.path.insert(0, str(HER))
import eloodds as E

ROT = HER.parent.parent
PROD = ROT / "eliteserien" / "data"
UT = HER.parent / "emodell"
W, K = 0.90, 83.37
RHO = 0.0
BLEND_W = 0.70


def last_historikk():
    d = json.loads((UT / "historikk.json").read_text(encoding="utf-8"))
    return d, {s: d["sesonger"][s] for s in sorted(d["sesonger"])}


def last_2026():
    """Spilte 2026-kamper med sluttodds fra PRODUKSJONENS egne filer."""
    spilt = [m for m in json.loads((PROD / "matches.json").read_text(encoding="utf-8"))
             if m.get("hg") is not None]
    od = {}
    for m in json.loads((PROD / "odds.json").read_text(encoding="utf-8"))["matches"]:
        s = m["H"] + m["D"] + m["A"]
        od[(m["home"], m["away"])] = [m["H"] / s, m["D"] / s, m["A"] / s]
    ut = [{"date": m["date"], "home": m["home"], "away": m["away"],
           "hg": m["hg"], "ag": m["ag"],
           "odds": od.get((m["home"], m["away"]))}
          for m in spilt]
    ut.sort(key=lambda m: (m["date"], m["home"], m["away"]))
    return ut


def main():
    meta_h, hist = last_historikk()
    s26 = last_2026()
    alle_med_odds = [m for v in hist.values() for m in v if m.get("odds")] + \
                    [m for m in s26 if m.get("odds")]
    hr = E.hjemmefordel_i_rating(alle_med_odds, dict(E.HVA))
    print(f"  historikk 2012-2025: {sum(len(v) for v in hist.values())} kamper")
    print(f"  2026 spilte:         {len(s26)} kamper, "
          f"{sum(1 for m in s26 if m.get('odds'))} med sluttodds")
    print(f"  hjemmefordel av {len(alle_med_odds)} kamper med odds: {hr:.6f}")

    innkjor = [m for y in ("2012", "2013") for m in hist[y]]
    p = dict(E.HVA, k=K)
    R, it, rest = E.hva_startverdier(innkjor, dict(E.HVA))
    print(f"  startverdier: {it} runder, siste endring {rest:.2e}, "
          f"{len(R)} lag")
    logg = []
    E.hva_mix_lap(dict(R), innkjor, p, hr, W, logg=logg)   # KOPI: bare loggen
    for y in [str(x) for x in range(2014, 2026)]:
        E.hva_mix_lap(R, hist[y], p, hr, W, logg=logg)
    # Avtrykk FOER 2026, saa ratinghistorikken kan bygges av samme tilstand.
    R_etter_2025 = dict(R)
    logg_etter_2025 = list(logg)
    E.hva_mix_lap(R, s26, p, hr, W, logg=logg)
    par = E.olr_tilpass([x[0] for x in logg], [x[1] for x in logg])
    print(f"  OLR paa {len(logg)} kamper: {[round(float(x), 6) for x in par]}")

    # RATINGHISTORIKK FOR 2026, til formgrafen. Ratingen etter hver kampdag,
    # bygget med SAMME regel: vi gjentar vandringen og tar et avtrykk. Ikke en
    # egen mekanisme -- hva_mix_lap kalles akkurat som over.
    R2 = dict(R_etter_2025)
    lg2 = list(logg_etter_2025)
    hist_r = {}
    for dato in sorted({m["date"] for m in s26}):
        blokk = [m for m in s26 if m["date"] == dato]
        E.hva_mix_lap(R2, blokk, p, hr, W, logg=lg2)
        hist_r[dato] = {t: R2.get(t, 0.0) for t in sorted(R2)}
    kontroll = max(abs(R2.get(t, 0.0) - R.get(t, 0.0)) for t in R)
    assert kontroll == 0.0, f"ratinghistorikken avviker: {kontroll:.3e}"
    print(f"  ratinghistorikk: {len(hist_r)} kampdager, "
          f"sluttrating identisk med hovedvandringen ({kontroll:.1e})")

    fx = json.loads((PROD / "fixtures.json").read_text(encoding="utf-8"))
    rest_k = [{"date": m["date"], "home": m["home"], "away": m["away"]}
              for r in fx for m in r["matches"] if not m.get("played")]
    opp = {}
    oj = json.loads((PROD / "odds_upcoming.json").read_text(encoding="utf-8"))
    for m in oj.get("matches", []):
        s = m["H"] + m["D"] + m["A"]
        opp[(m["home"], m["away"])] = [m["H"] / s, m["D"] / s, m["A"] / s]

    kamper = []
    n_blend = 0
    for m in rest_k:
        dr = R.get(m["home"], 0.0) - R.get(m["away"], 0.0)
        ph, pu, pb = E.olr_sannsyn(par, dr)
        rad = {"home": m["home"], "away": m["away"], "date": m["date"],
               "dr": dr, "pH": ph, "pU": pu, "pB": pb}
        lh, la = E.fit_rates(ph, pb, RHO)
        rad["lam"] = [lh, la]
        mk = opp.get((m["home"], m["away"]))
        if mk:
            # PRODUKSJONENS REGEL: 70 % marked hvis kampen finnes i
            # odds_upcoming.json. Blandingen skjer paa H og B i
            # SANNSYNLIGHETSROMMET, som i labens Elo-sti og i rateFor().
            bh = BLEND_W * mk[0] + (1 - BLEND_W) * ph
            bb = BLEND_W * mk[2] + (1 - BLEND_W) * pb
            rad["marked"] = mk
            rad["blend_lam"] = list(E.fit_rates(bh, bb, RHO))
            rad["blend_p"] = [bh, 1.0 - bh - bb, bb]
            n_blend += 1
        kamper.append(rad)
    print(f"  gjenstaaende: {len(kamper)} kamper, {n_blend} med direkte odds")
    for r in kamper:
        if "marked" in r:
            print(f"      {r['date']}  {r['home']} - {r['away']}")

    lag = sorted({m["home"] for m in s26} | {m["away"] for m in s26})
    UT.mkdir(parents=True, exist_ok=True)

    def skriv_hvis_endret(navn, d, ignorer):
        """Skriver bare naar INNHOLDET er endret, tidsstempler holdt utenfor.

        HVORFOR: "Oppdater kampdata" kan kjore hvert tiende minutt. Et
        tidsstempel som endres hver gang ville gitt en commit hver gang, ogsaa
        naar modellen og prognosene staar stille. Sammenligningen ser bort fra
        feltene i `ignorer` -- built og odds_upcoming_fetched_at -- for en ny
        hentetid alene er ikke en endret prognose.

        Er ingenting endret, roeres filen IKKE, og den beholder sitt gamle
        tidsstempel. Filen sier naar MODELLEN ble bygget, og modellen er den
        samme."""
        p = UT / navn
        ny = {k: v for k, v in d.items() if k not in ignorer}
        if p.exists():
            gml = json.loads(p.read_text(encoding="utf-8"))
            if {k: v for k, v in gml.items() if k not in ignorer} == ny:
                return False
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
        return True

    MODELL = {
        "version": 1,
        "model": "ELO-Odds w=90 %", "w": W, "k": K, "rho": RHO,
        "note": "Rating fra hva_mix_lap, 1X2 fra OLR paa ratingforskjellen, "
                "lambda fra fit_rates med rho = 0. k er laast fra "
                "k(w)-regelen paa innkjoringen 2012-2013. Hjemmefordel, "
                "startverdier, rating og OLR regnes paa nytt ved hver bygging.",
        # mu og H finnes ikke i ELO90, men nyttelasten til workeren sender
        # MODEL.mu og MODEL.H. De brukes ALDRI, fordi oddsOverride er satt for
        # alle kamper og workeren da tar den tvungne grenen. Settes likevel til
        # 0 saa ingenting er undefined.
        "mu": 0.0, "H": 0.0,
        "teams": lag,
        "rating": {t: R.get(t, 0.0) for t in lag},
        "rating_alle": {t: v for t, v in sorted(R.items())},
        "hjemmefordel_rating": hr,
        "olr": [float(x) for x in par],
        "blend_w": BLEND_W,
        "kamper": kamper,
        "rating_historikk": hist_r,
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    endret_modell = skriv_hvis_endret("model.json", MODELL, {"built"})
    META = {
        "version": 1, "w": W, "k": K, "rho": RHO, "blend_w": BLEND_W,
        "hjemmefordel_rating": hr,
        "olr_kamper": len(logg),
        "historikk_kamper": sum(len(v) for v in hist.values()),
        "historikk_sha256_kilde": meta_h["kilde_sha256"],
        "spilte_2026": len(s26),
        "spilte_2026_med_odds": sum(1 for m in s26 if m.get("odds")),
        "gjenstaaende": len(kamper),
        "med_direkte_odds": n_blend,
        "direkte_odds_kamper": [f"{r['date']} {r['home']} - {r['away']}"
                                for r in kamper if "marked" in r],
        "odds_upcoming_fetched_at": oj.get("fetched_at"),
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    endret_meta = skriv_hvis_endret("meta.json", META,
                                    {"built", "odds_upcoming_fetched_at"})
    print(f"  model.json {'SKREVET' if endret_modell else 'uendret'}, "
          f"meta.json {'SKREVET' if endret_meta else 'uendret'}")
    # ---- PROGNOSELOGG. Ingen kunstig historikk: loggen starter den dagen
    # siden gaar live. Den SISTE linjen for en kamp foer avspark er den frosne.
    # Grunnlaget for aa sammenligne treffsikkerhet mot produksjonen naar
    # testperioden er over -- panelene forblir skjult til da.
    #
    # EN LINJE BARE NAAR PROGNOSEN ER ENDRET. "Oppdater kampdata" kan kjore
    # hvert tiende minutt. Skrev vi 72 linjer hver gang, ville loggen vokst med
    # ~14 KB per kjoring og hver kjoring gitt en commit, ogsaa naar ingenting
    # var endret. Sammenligningen bruker de SAMME AVRUNDEDE tallene som lagres
    # (6 desimaler), saa flyttallsstoy under den oppdelingen ikke lager commits.
    # En ny odds_hentet ALENE regnes ikke som endret prognose: feltet er ikke
    # med i sammenligningen.
    #
    # HVA DEN FROSNE PROGNOSEN ER, presist:
    #
    #   For en kamp: AVSPARK hentes fra TERMINLISTEN
    #   (eliteserien/data/fixtures.json: date + time, norsk lokaltid,
    #   Europe/Oslo -> UTC). Den frosne prognosen er den SISTE logglinjen for
    #   kampen med logget < avspark.
    #
    # AVSPARKET TAS IKKE FRA LOGGLINJEN. Feltet "avspark" der kommer fra
    # odds_upcoming.json sin commence_time og er NULL for hver kamp som ikke
    # ligger i den filen -- i dag 64 av 72. Det er informasjon, ikke
    # utvalgskriterium. Terminlisten har klokkeslett for alle kamper.
    #
    # Perioden 9. oktober til 13. desember krysser sommertidsskiftet
    # (25. oktober 2026), saa omregningen maa gaa gjennom Europe/Oslo og ikke
    # et fast timetall.
    #
    # EN FIL PER MAANED, som data/hentelogg. Append-only, aldri omskrevet.
    kt = {}
    for m in oj.get("matches", []):
        kt[(m["home"], m["away"])] = m.get("commence_time")
    naa = datetime.now(timezone.utc)
    logg_dir = UT / "prognoselogg"
    logg_dir.mkdir(parents=True, exist_ok=True)

    # SISTE loggede linje per kamp, over ALLE maanedsfiler -- ellers ville hver
    # kamp blitt logget paa nytt ved hvert maanedsskifte.
    siste = {}
    for p in sorted(logg_dir.glob("*.jsonl")):
        for linje in p.read_text(encoding="utf-8").splitlines():
            if not linje.strip():
                continue
            r = json.loads(linje)
            siste[(r["hjemme"], r["borte"])] = r

    def rad_for(r):
        blandet = "blend_p" in r
        p_pub = r["blend_p"] if blandet else [r["pH"], r["pU"], r["pB"]]
        return {
            "logget": naa.isoformat(timespec="seconds"),
            "dato": r["date"], "hjemme": r["home"], "borte": r["away"],
            "avspark": kt.get((r["home"], r["away"])),
            "modell": "ELO90+70" if blandet else "ELO90",
            "p": [round(x, 6) for x in p_pub],
            "elo90_p": [round(r["pH"], 6), round(r["pU"], 6), round(r["pB"], 6)],
            "marked": [round(x, 6) for x in r["marked"]] if "marked" in r else None,
            "odds_hentet": oj.get("fetched_at"),
        }

    # NAAR ER PROGNOSEN ENDRET? En tallverdi maa ha flyttet seg MINST TERSKEL
    # mot siste loggede linje for samme kamp.
    #
    # HVORFOR EN TERSKEL og ikke likhet paa de avrundede tallene: byggingen er
    # ikke bit-reproduserbar mellom maskiner, heller ikke mellom to
    # CI-kjoringer (samme image og versjoner, ulik Azure-region). Ratingene
    # skiller 2,8e-14 mellom macOS og CI, men olr_tilpass bruker scipys
    # Nelder-Mead, som forsterker det til ~8e-09 i parameterne og ~2e-09 i 1X2.
    # Ligger en verdi naer en avrundingsgrense, vipper sjette desimal. Det
    # skjedde i den forste CI-kjoringen: Aalesund - Bodo/Glimt, borteseier
    # 0,722485499307 lokalt, bare 6,9e-10 under grensen 0,7224855, og
    # 0,722485500848 i CI. Fire falske linjer i alt; se README.
    #
    # 1e-5 er ti avrundingsenheter: langt over stoyen, og langt under
    # det siden viser (hele prosent). En reell endring fanges; stoy gjor ikke.
    #
    # Ikke-tall (modell, dato, avspark, og om markedet finnes) sammenlignes
    # eksakt. logget og odds_hentet er utenfor med vilje: en ny hentetid alene er
    # ikke en endret prognose.
    TERSKEL = 1e-5
    TALL = ("p", "elo90_p", "marked")
    EKSAKT = ("modell", "avspark", "dato")

    def endret(gml, rad):
        if any(gml.get(k) != rad[k] for k in EKSAKT):
            return True
        for k in TALL:
            a, b = gml.get(k), rad[k]
            if (a is None) != (b is None):
                return True
            if a is not None and any(abs(x - y) >= TERSKEL for x, y in zip(a, b)):
                return True
        return False

    nye = []
    for r in kamper:
        rad = rad_for(r)
        gml = siste.get((r["home"], r["away"]))
        if gml is not None and not endret(gml, rad):
            continue
        nye.append(rad)
    if nye:
        sti = logg_dir / f"{naa:%Y-%m}.jsonl"
        with sti.open("a", encoding="utf-8") as fh:
            for rad in nye:
                fh.write(json.dumps(rad, ensure_ascii=False) + "\n")
        print(f"  prognoselogg: {len(nye)} av {len(kamper)} kamper endret, "
              f"skrevet til {sti.relative_to(UT.parent)}")
    else:
        print(f"  prognoselogg: ingen av {len(kamper)} prognoser endret, "
              f"ingen linjer skrevet")

    if not (endret_modell or endret_meta or nye):
        print(f"\n  INGENTING ENDRET -- ingen fil roert, ingen commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
