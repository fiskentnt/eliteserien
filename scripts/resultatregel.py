#!/usr/bin/env python3
"""Regelen for å publisere et resultat (3.10.2026), felles for begge ligaene.

Kildene står i prioritert rekkefølge (KILDER), og hver har en leverandør
(LEVERANDOR). fotball.no og NTF (ligasidene) er samme leverandør.

  Eliteserien: ligasiden, ESPN, Highlightly, Wikipedia, ffksupporter,
               fotball.no (bare i krise)
  OBOS:        ligasiden, Highlightly, OddsPapi (reserve: spørres bare når
               Highlightly mangler eller er uenig, hvert kall koster),
               Wikipedia, fotball.no (bare i krise)

REGELEN:
  * Hovedkilden er den første kilden i rekkefølgen som svarte (er oppe).
    Er ligasiden nede, blir neste kilde hovedkilde.
  * Et resultat publiseres når hovedkilden og minst én kilde fra en ANNEN
    leverandør er enige.
  * Har hovedkilden ikke resultatet ennå: vent.
  * En uenig kilde stopper ikke, så lenge en annen uavhengig kilde er enig
    (et 0-0 fra ESPN som er uenig med ligasiden, publiseres derfor aldri
    alene, og det stopper heller ikke et resultat Highlightly bekrefter).
    Ingen enige og minst én uenig: konflikt, holdes tilbake.
  * Ingen uavhengig kilde har resultatet: vent. Etter VENT_TIMER timer fra
    avspark publiseres resultatet fra den OFFISIELLE ligasiden alene -- aldri
    fra en annen enkeltkilde -- og kjøringen er rød så lenge det står uten
    kontroll (ukontrollert=True, se kontroller_ukontrollerte).

Ingen nettkall her: kalleren henter kildene og gir svarene inn.
"""
from datetime import timedelta

VENT_TIMER = 24

LEVERANDOR = {"ligasiden": "NTF", "fotball.no": "NTF", "espn": "ESPN", "highlightly": "Highlightly",
              "oddspapi": "OddsPapi", "wikipedia": "Wikipedia", "ffksupporter": "ffksupporter",
              "football-data": "football-data"}

KILDER = {
    "eliteserien": ("ligasiden", "espn", "highlightly", "wikipedia", "ffksupporter", "fotball.no"),
    "obos": ("ligasiden", "highlightly", "oddspapi", "wikipedia", "fotball.no"),
}


def avgjor(liga, svar, oppe, avspark=None, naa=None):
    """Avgjørelsen for én kamp.

    svar:    {kilde: (hg, ag)} for kildene som har et sluttresultat; en kilde
             som svarte uten resultat for kampen, står ikke (eller med None).
    oppe:    kildene som svarte denne kjøringen (kunne hentes og leses).
    avspark, naa: datetime med tidssone; trengs bare for ventetiden.

    Returnerer {utfall, resultat, hoved, enig, uenige, ukontrollert, grunn}
    der utfall er "publiser", "vent" eller "konflikt"."""
    rekke = KILDER[liga]
    ut = {"utfall": "vent", "resultat": None, "hoved": None, "enig": None, "uenige": [],
          "ukontrollert": False, "grunn": ""}
    hoved = next((k for k in rekke if k in oppe), None)
    ut["hoved"] = hoved
    if hoved is None:
        ut["grunn"] = "ingen kilde svarte"
        return ut
    r = svar.get(hoved)
    if r is None:
        ut["grunn"] = f"hovedkilden ({hoved}) har ikke resultatet ennå"
        return ut
    r = tuple(r)
    for k in rekke:
        if k == hoved or LEVERANDOR[k] == LEVERANDOR[hoved]:
            continue
        v = svar.get(k)
        if v is None:
            continue
        if tuple(v) == r:
            ut.update(utfall="publiser", resultat=r, enig=k,
                      grunn=f"{hoved} og {k} er enige" + (f" ({', '.join(ut['uenige'])} uenig)" if ut["uenige"] else ""))
            return ut
        ut["uenige"].append(k)
    if ut["uenige"]:
        ut.update(utfall="konflikt", grunn=f"{hoved} har {r[0]}-{r[1]}, " + ", ".join(
            f"{k} har {svar[k][0]}-{svar[k][1]}" for k in ut["uenige"]) + " -- holdes tilbake")
        return ut
    if hoved == "ligasiden" and avspark is not None and naa is not None and naa - avspark >= timedelta(hours=VENT_TIMER):
        ut.update(utfall="publiser", resultat=r, ukontrollert=True,
                  grunn=f"bare ligasiden har resultatet etter {VENT_TIMER} timer -- publisert uten kontroll")
        return ut
    ut["grunn"] = f"bare {hoved} har resultatet -- venter på en uavhengig kilde"
    return ut


def kontroller_ukontrollerte(liga, ukontrollerte, svar_per_kamp):
    """Resultater publisert uten kontroll: (fortsatt_ukontrollerte, bekreftet, uenige).

    ukontrollerte: {(hjemme, borte): (hg, ag)} fra forrige kjøring.
    svar_per_kamp: {(hjemme, borte): {kilde: (hg, ag)}} denne kjøringen.
    Et resultat er bekreftet når en kilde fra en annen leverandør enn
    ligasiden har det samme; uenig når en slik kilde har et annet."""
    fortsatt, bekreftet, uenige = {}, [], []
    for k, r in ukontrollerte.items():
        sv = svar_per_kamp.get(k, {})
        uavh = {kilde: tuple(v) for kilde, v in sv.items() if v is not None and LEVERANDOR.get(kilde) != "NTF"}
        if any(v == tuple(r) for v in uavh.values()):
            bekreftet.append(k)
        else:
            if uavh:
                uenige.append((k, tuple(r), uavh))
            fortsatt[k] = tuple(r)
    return fortsatt, bekreftet, uenige
