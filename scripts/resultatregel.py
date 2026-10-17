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

BEKREFTET (12.10.2026): når et resultat publiseres, lagres hvilke kilder
utenfor NTF som hadde nøyaktig samme resultat (results_state.json,
"bekreftet"). Tabellkontrollen bruker det rett etter kampslutt: et avvik mot
tabellen på ligasiden som bare gjelder en fersk kamp med bekreftet resultat,
er en advarsel og en ny sjekk i neste kjøring, ikke en rød kjøring (se
tabellkontroll.py og ferske_bekreftede under).

KONTROLLKILDENE (17.10.2026): alle publiserte resultater kontrolleres mot en
kilde med hele sesongen (ffksupporter.net i Eliteserien, Wikipedia i OBOS),
se revider_kilde og kilde_stoppet. Rødt bare når kilden har et ANNET resultat
enn oss, eller når den mangler et resultat og ingen uavhengig kilde bekrefter
det etter fristen. Mangler kilden det, men en annen bekrefter: advarsel. Har
kilden ikke registrert noe på flere døgn: advarsel om at den har stoppet.
Advarslene står i status.json ("advarsler") og går med livstegnet.

Ingen nettkall her: kalleren henter kildene og gir svarene inn.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent

VENT_TIMER = 24
# Tabellkontrollen: en kamp er FERSK til så mange timer etter avspark. 9.10.2026
# førte tabellen på ligasiden Brann-Viking (0-2) som 0-0 til 3 t 10 min etter
# avspark. Seks timer er også portens egen grense (should_fetch.py).
FERSK_TIMER = 6
# Så lenge står en bekreftelse i results_state.json.
BEKREFTET_TIMER = 48
# Kontrollen av alle publiserte resultater mot en kontrollkilde (revider_kilde):
# mangler kilden et resultat og ingen annen uavhengig kilde bekrefter det, er
# det rødt så mange timer etter avspark. Med en bekreftelse er det en advarsel.
KONTROLL_FRIST_TIMER = 72
# En kontrollkilde som ikke har registrert noe nytt på så mange døgn og mangler
# resultater vi har hatt like lenge, har stoppet (kilde_stoppet): advarsel.
STOPPET_DOGN = 3

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


def uavhengige_enige(svar, resultat):
    """Kildene UTENFOR NTF som har nøyaktig dette resultatet.
    svar: {kilde: (hg, ag) eller None}. Ligasiden og fotball.no er NTF, og
    tabellen kontrollen sammenligner med, er også NTF sin."""
    r = tuple(resultat)
    return sorted(k for k, v in (svar or {}).items()
                  if v is not None and LEVERANDOR.get(k) != "NTF" and tuple(v) == r)


def bekreftet_tilstand(gml, nye, naa, behold_timer=BEKREFTET_TIMER):
    """Feltet "bekreftet" i results_state.json:
    {"Hjemme|Borte": {"resultat": [hg, ag], "kilder": [...], "publisert": iso}}.

    gml: feltet fra forrige kjøring. nye: {(hjemme, borte): (resultat, kilder)}
    for resultatene som ble publisert (eller bekreftet i etterkant) i denne
    kjøringen; uten en kilde utenfor NTF lagres ingenting. Oppføringer eldre
    enn behold_timer tas ut."""
    ut = {}
    for n, v in (gml or {}).items():
        try:
            if naa - datetime.fromisoformat(v["publisert"]) < timedelta(hours=behold_timer):
                ut[n] = v
        except Exception:
            continue
    for k, (resultat, kilder) in (nye or {}).items():
        if kilder:
            ut[f"{k[0]}|{k[1]}"] = {"resultat": [int(resultat[0]), int(resultat[1])], "kilder": sorted(kilder),
                                    "publisert": naa.isoformat(timespec="seconds")}
    return ut


def ferske_bekreftede(liga, kamper, naa, state_sti=None, timer=FERSK_TIMER):
    """De spilte kampene i `kamper` som er FERSKE (avspark for mindre enn
    `timer` timer siden) og har resultatet BEKREFTET utenfor NTF: det står i
    results_state.json med nøyaktig samme resultat og minst én kilde.

    Returnerer [{home, away, hg, ag, avspark, frist, kilder}] med avspark og
    frist som ISO-tid i UTC. En kamp uten avspark, uten oppføring eller med et
    annet lagret resultat er ikke med: da gjelder tabellkontrollen som før."""
    from zoneinfo import ZoneInfo
    sti = Path(state_sti) if state_sti else ROT / liga / "data" / "results_state.json"
    try:
        bekreftet = json.loads(sti.read_text(encoding="utf-8")).get("bekreftet") or {}
    except Exception:
        return []
    ut = []
    for m in kamper:
        if m.get("hg") is None or m.get("ag") is None or not m.get("date") or not m.get("time"):
            continue
        b = bekreftet.get(f"{m['home']}|{m['away']}")
        if not b or not b.get("kilder") or list(b.get("resultat") or []) != [m["hg"], m["ag"]]:
            continue
        try:
            avspark = datetime.fromisoformat(f"{m['date']}T{m['time']}").replace(
                tzinfo=ZoneInfo("Europe/Oslo")).astimezone(naa.tzinfo)
        except Exception:
            continue
        if timedelta(0) <= naa - avspark < timedelta(hours=timer):
            ut.append({"home": m["home"], "away": m["away"], "hg": m["hg"], "ag": m["ag"],
                       "avspark": avspark.isoformat(timespec="seconds"),
                       "frist": (avspark + timedelta(hours=timer)).isoformat(timespec="seconds"),
                       "kilder": list(b["kilder"])})
    return ut


def revider_kilde(kilde, vaare, kilde_res, bekreftere, naa, frist_timer=KONTROLL_FRIST_TIMER, navn=None):
    """Kontrollen av ALLE publiserte resultater mot én kontrollkilde (17.10.2026),
    felles for begge ligaene. Regelen:

      * Kilden har et ANNET resultat enn oss: feil (rødt) med en gang.
      * Kilden mangler resultatet (eller hele kampen), men minst én annen
        uavhengig kilde har nøyaktig samme resultat som oss: advarsel.
      * Kilden mangler det og ingen uavhengig kilde bekrefter det: advarsel
        til frist_timer etter avspark, så feil.

    Før 17.10. var «mangler» alene rødt etter 72 timer: ffksupporter.net
    manglet KFUM Oslo-Vålerenga 2-1 (12.10.), og statusen sto rød fra 16.10.
    07.45, så ingen ekte feil i runde 24 ville gitt nytt varsel.

    vaare: [{home, away, date, hg, ag, avspark}] -- de spilte kampene våre,
           avspark som datetime med tidssone eller None.
    kilde_res: {(hjemme, borte): (hg, ag) eller None}; None er en kamp kilden
           har uten resultat, en kamp som ikke står, har kilden ikke.
    bekreftere: {annen kilde: {(hjemme, borte): (hg, ag)}}, eller en funksjon
           som gir det; den kalles bare når en kamp mangler hos kilden (kan
           koste et nettkall). NTF teller aldri som uavhengig.
    kilde er nøkkelen i LEVERANDOR, navn det som står i tekstene.
    Returnerer (feil, advarsler), begge lister med tekst."""
    feil, advarsler = [], []
    navn = navn or kilde
    cache = {}

    def bekreftet_av(nokkel, r):
        if "b" not in cache:
            try:
                cache["b"] = (bekreftere() if callable(bekreftere) else bekreftere) or {}
            except Exception as e:
                advarsler.append(f"bekreftelsene til kontrollen mot {navn} kunne ikke hentes ({type(e).__name__}: {e})")
                cache["b"] = {}
        return sorted(k for k, res in cache["b"].items()
                      if LEVERANDOR.get(k) not in ("NTF", LEVERANDOR.get(kilde)) and k != kilde
                      and res and res.get(nokkel) is not None and tuple(res[nokkel]) == r)

    for m in vaare:
        nokkel = (m["home"], m["away"])
        r = (m["hg"], m["ag"])
        hvem = f"{m['home']}-{m['away']} ({m['date']})"
        if nokkel in kilde_res and kilde_res[nokkel] is not None:
            if tuple(kilde_res[nokkel]) != r:
                v = kilde_res[nokkel]
                feil.append(f"{hvem}: vi har {r[0]}-{r[1]}, {navn} har {v[0]}-{v[1]}")
            continue
        timer = (naa - m["avspark"]).total_seconds() / 3600 if m.get("avspark") else None
        hva = "mangler resultatet" if nokkel in kilde_res else "mangler kampen"
        naar = f" {timer:.0f} timer etter avspark" if timer is not None else ""
        bekr = bekreftet_av(nokkel, r)
        if bekr:
            advarsler.append(f"{hvem}: vi har {r[0]}-{r[1]}, {navn} {hva}{naar}; bekreftet av {', '.join(bekr)}")
        elif timer is not None and timer <= frist_timer:
            advarsler.append(f"{hvem}: vi har {r[0]}-{r[1]}, {navn} {hva} ennå ({timer:.0f}t siden avspark), "
                             f"ingen annen uavhengig kilde har bekreftet det")
        else:
            feil.append(f"{hvem}: vi har {r[0]}-{r[1]}, {navn} {hva}{naar}, og ingen uavhengig kilde bekrefter det")
    return feil, advarsler


def kilde_stoppet(navn, vaare, kilde_res, gml, naa, dogn=STOPPET_DOGN):
    """Har kontrollkilden sluttet å oppdatere? (17.10.2026) Advarsel, aldri rødt.

    Tilstanden {"resultater": antall, "endret": iso} husker når antallet
    resultater hos kilden sist endret seg. Første gang settes "endret" til
    avsparket for den siste kampen kilden har resultat for: kilden har i alle
    fall ikke registrert noe før det.

    Advarsel når kilden mangler en kamp spilt ETTER at den sist registrerte
    noe, og kampen er minst `dogn` døgn gammel. En kilde som har alt, er à jour
    selv om ingenting er endret (landskamppause), og et gammelt hull (Wikipedia
    mangler fem OBOS-kamper fra 10.5.) er ikke et tegn på at kilden har stoppet.
    Returnerer (ny tilstand, advarsel eller None)."""
    n = sum(1 for v in kilde_res.values() if v is not None)
    gml = gml or {}
    try:
        endret = datetime.fromisoformat(gml["endret"]) if gml.get("endret") else None
    except ValueError:
        endret = None
    if endret is None:
        har = [m["avspark"] for m in vaare if m.get("avspark") and kilde_res.get((m["home"], m["away"])) is not None]
        endret = max(har) if har else naa
    elif gml.get("resultater") != n:
        endret = naa
    tilstand = {"resultater": n, "endret": endret.isoformat(timespec="seconds")}
    grense = naa - timedelta(days=dogn)
    mangler = [m for m in vaare if kilde_res.get((m["home"], m["away"])) is None
               and m.get("avspark") and endret < m["avspark"] <= grense]
    if not mangler:
        return tilstand, None
    from zoneinfo import ZoneInfo
    e = endret.astimezone(ZoneInfo("Europe/Oslo"))
    dager = (naa - endret).total_seconds() / 86400
    return tilstand, (f"{navn} har ikke registrert noe nytt på {dager:.0f} døgn (siden {e.day}.{e.month}.) og mangler "
                      f"{len(mangler)} resultat(er) fra kamper spilt etter det: kilden ser ut til å ha stoppet")


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
