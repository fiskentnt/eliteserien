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
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent

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


def resultatlinje(liga, k, u, svar):
    """Én linje per nytt resultat i loggen (4.10.2026), også når det holdes
    tilbake eller venter: "Bryne-Lyn 1-0: ligasiden og highlightly enige,
    publisert", "Bryne-Lyn: ligasiden 2-1, highlightly 1-1, holdt tilbake".
    u er svaret fra avgjor, svar kildenes resultater for kampen."""
    hvem = f"{k[0]}-{k[1]}"
    rekke = [kilde for kilde in KILDER[liga] if svar.get(kilde) is not None]
    alle = ", ".join(f"{kilde} {svar[kilde][0]}-{svar[kilde][1]}" for kilde in rekke)
    if u["utfall"] == "publiser":
        r = u["resultat"]
        if u["ukontrollert"]:
            return f"{hvem} {r[0]}-{r[1]}: bare {u['hoved']} etter {VENT_TIMER} timer, publisert uten kontroll"
        tekst = f"{hvem} {r[0]}-{r[1]}: {u['hoved']} og {u['enig']} enige, publisert"
        if u["uenige"]:
            tekst += " (" + ", ".join(f"{kilde} {svar[kilde][0]}-{svar[kilde][1]} uenig" for kilde in u["uenige"]) + ")"
        return tekst
    if u["utfall"] == "konflikt":
        return f"{hvem}: {alle}, holdt tilbake"
    hoved = u["hoved"]
    if hoved and svar.get(hoved) is not None:
        r = svar[hoved]
        return f"{hvem} {r[0]}-{r[1]}: bare {hoved}, venter på en uavhengig kilde"
    return f"{hvem}: {hoved or 'ingen kilde'} har ikke resultatet ennå" + (f" ({alle})" if alle else "") + ", venter"


def forst_sett(gml, svar_per_kamp, naa, publisert_foer):
    """Når hver kilde FØRST hadde resultatet (4.10.2026), bare til loggen:
    "Bryne-Lyn: highlightly 16.21, ligasiden 16.31". Tidspunktet er kjøringen
    som så det, så det er nøyaktig til nærmeste kjøring (hvert tiende minutt).

    gml: {"Bryne|Lyn": {kilde: iso-tid}} fra forrige kjøring.
    svar_per_kamp: {(hjemme, borte): {kilde: (hg, ag) eller None}} denne
    kjøringen, for kampene som er nye eller venter.
    publisert_foer: kampene som var publisert før denne kjøringen; de er
    ferdig logget og tas ut av tilstanden.
    Returnerer (ny tilstand, linjer)."""
    from zoneinfo import ZoneInfo
    oslo = ZoneInfo("Europe/Oslo")
    ut = {n: dict(v) for n, v in (gml or {}).items() if tuple(n.split("|")) not in publisert_foer}
    for k, svar in svar_per_kamp.items():
        d = ut.setdefault(f"{k[0]}|{k[1]}", {})
        for kilde, v in svar.items():
            if v is not None and kilde not in d:
                d[kilde] = naa.isoformat(timespec="seconds")
    idag = naa.astimezone(oslo).date()

    def klokke(iso):
        t = datetime.fromisoformat(iso).astimezone(oslo)
        return t.strftime("%H.%M") if t.date() == idag else f"{t.day}.{t.month}. {t.strftime('%H.%M')}"
    linjer = [f"{n.replace('|', '-')}: " + ", ".join(f"{kilde} {klokke(t)}" for kilde, t in sorted(d.items(), key=lambda x: x[1]))
              for n, d in ut.items() if d]
    return {n: d for n, d in ut.items() if d}, linjer


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


def sjekk(liga, rot=None):
    """Gjør kjøringen rød (1) så lenge et resultat står uten kontroll eller i
    konflikt i <liga>/data/results_state.json. Eget steg til slutt i
    workflowen (if: always()), så resultatene og tabellen er lagret først."""
    sti = Path(rot or ROT) / liga / "data" / "results_state.json"
    try:
        st = json.loads(sti.read_text(encoding="utf-8"))
    except Exception:
        print(f"{liga}: ingen results_state.json -- ingenting å sjekke")
        return 0
    feil = 0
    for k, r in (st.get("ukontrollert") or {}).items():
        print(f"FEIL: {liga}: {k.replace('|', ' mot ')} {r[0]}-{r[1]} er publisert uten kontroll "
              f"(bare ligasiden) -- venter på en uavhengig kilde")
        feil += 1
    for c in st.get("conflicts") or []:
        print(f"FEIL: {liga}: konflikt: {c}")
        feil += 1
    if not feil:
        print(f"{liga}: ingen resultater uten kontroll, ingen konflikter")
    return 1 if feil else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "sjekk":
        sys.exit(sjekk(sys.argv[2]))
    print("Bruk: python3 scripts/resultatregel.py sjekk <liga>", file=sys.stderr)
    sys.exit(2)
