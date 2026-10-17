#!/usr/bin/env python3
"""Regelen for å publisere et resultat (3.10.2026), felles for begge ligaene.

Kildene står i prioritert rekkefølge (KILDER), og hver har en leverandør
(LEVERANDOR). fotball.no og NTF (ligasidene) er samme leverandør.

  Eliteserien: ligasiden, ESPN, Highlightly, Wikipedia, ffksupporter,
               fotball.no (bare i krise)
  OBOS:        ligasiden, Highlightly, OddsPapi (reserve: spørres bare når
               Highlightly mangler eller er uenig, hvert kall koster),
               Wikipedia, fotball.no (bare i krise)

REGELEN (stemmer, 17.10.2026):
  * Én stemme per leverandør: den første kilden i rekkefølgen som har et
    resultat for kampen. Ligasiden og fotball.no er én stemme (NTF).
  * Bare ferdigspilte kamper gir stemme: ESPN når kampen er markert
    completed (og ikke 0-0 med en vinner, "suspect"), Highlightly når status
    er "Finished". Det sørger kalleren for (update_data.kontroller_nye_resultater,
    obos_results.highlightly_resultater); svar her er bare sluttresultater.
  * Et resultat publiseres når minst to stemmer har nøyaktig samme resultat,
    og ingen annen stilling har like mange. Ligasiden trenger ikke være blant
    dem. Er ligasiden uenig, er den overstemt: publiser, med advarsel
    ("overstemt", se overstemt_tilstand). 17.10.2026 hadde ligasiden
    Viking-Fredrikstad 1-2 (pausestillingen), ESPN og Highlightly 3-2.
  * Like mange stemmer for to stillinger (1 mot 1, 2 mot 2): konflikt,
    holdes tilbake (rødt, se sjekk).
  * Én stemme: vent. Etter VENT_TIMER timer fra avspark publiseres resultatet
    fra den OFFISIELLE ligasiden alene -- aldri fra en annen enkeltkilde -- og
    kjøringen er rød så lenge det står uten kontroll (ukontrollert=True, se
    kontroller_ukontrollerte).
  * Før 17.10.2026 var den første kilden som svarte, hovedkilde, og et
    resultat krevde hovedkilden pluss én annen leverandør.

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
    """Avgjørelsen for én kamp, med stemmer (17.10.2026, se REGELEN øverst).

    svar:    {kilde: (hg, ag)} for kildene som har et SLUTTRESULTAT; en kilde
             som svarte uten resultat for kampen, står ikke (eller med None).
    oppe:    kildene som svarte denne kjøringen (kunne hentes og leses).
    avspark, naa: datetime med tidssone; trengs bare for ventetiden.

    Returnerer {utfall, resultat, hoved, enig, uenige, ukontrollert,
    overstemt, grunn} der utfall er "publiser", "vent" eller "konflikt".
    Ved publisering er hoved og enig de to første kildene (i rekkefølgen)
    med vinnerresultatet; ellers er hoved den første kilden som svarte.
    uenige er kildene med en annen stilling, overstemt er sann når ligasiden
    (NTF) er blant dem."""
    rekke = KILDER[liga]
    ut = {"utfall": "vent", "resultat": None, "hoved": None, "enig": None, "uenige": [],
          "ukontrollert": False, "overstemt": False, "grunn": ""}
    forste = next((k for k in rekke if k in oppe), None)
    stemmer = {}                      # leverandør -> (kilde, resultat)
    for k in rekke:
        v = svar.get(k)
        if v is not None and LEVERANDOR[k] not in stemmer:
            stemmer[LEVERANDOR[k]] = (k, tuple(v))
    grupper = {}                      # resultat -> kildene som har det, i rekkefølgen
    for k, r in sorted(stemmer.values(), key=lambda x: rekke.index(x[0])):
        grupper.setdefault(r, []).append(k)
    ut["hoved"] = forste
    if not grupper:
        ut["grunn"] = f"hovedkilden ({forste}) har ikke resultatet ennå" if forste else "ingen kilde svarte"
        return ut
    mest = max(len(v) for v in grupper.values())
    vinnere = [r for r, v in grupper.items() if len(v) == mest]
    if mest >= 2 and len(vinnere) == 1:
        r = vinnere[0]
        enige = grupper[r]
        uenige = [k for rr, v in grupper.items() if rr != r for k in v]
        uenige.sort(key=rekke.index)
        ut.update(utfall="publiser", resultat=r, hoved=enige[0], enig=enige[1], uenige=uenige,
                  overstemt=any(LEVERANDOR[k] == "NTF" for k in uenige),
                  grunn=f"{enige[0]} og {enige[1]} er enige"
                        + (f" ({', '.join(uenige)} uenig)" if uenige else ""))
        return ut
    if len(grupper) > 1:
        alle = sorted((k for v in grupper.values() for k in v), key=rekke.index)
        ut.update(utfall="konflikt", uenige=[k for k in alle if k != forste],
                  grunn=", ".join(f"{k} har {svar[k][0]}-{svar[k][1]}" for k in alle) + " -- holdes tilbake")
        return ut
    # Én stemme.
    (r, (k,)), = [(r, tuple(v)) for r, v in grupper.items()]
    if (k == "ligasiden" and avspark is not None and naa is not None
            and naa - avspark >= timedelta(hours=VENT_TIMER)):
        ut.update(utfall="publiser", resultat=r, hoved=k, ukontrollert=True,
                  grunn=f"bare ligasiden har resultatet etter {VENT_TIMER} timer -- publisert uten kontroll")
        return ut
    ut["grunn"] = (f"bare {k} har resultatet -- venter på en uavhengig kilde" if k == forste
                   else f"hovedkilden ({forste}) har ikke resultatet ennå; bare {k} har det")
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


def overstemt_tilstand(gml, nye, ligasiden, naa):
    """Feltet "overstemt" i results_state.json (17.10.2026): resultatene som ble
    publisert mot ligasidens stemme, så lenge ligasiden er uenig.
    {"Hjemme|Borte": {"resultat": [hg, ag], "ligasiden": [hg, ag], "kilder": [...],
                      "publisert": iso}}.

    gml: feltet fra forrige kjøring. nye: {(hjemme, borte): (resultat,
    ligasidens resultat, kildene som var enige)} fra denne kjøringen.
    ligasiden: {(hjemme, borte): (hg, ag)} fra ligasiden nå, eller None når
    den ikke svarte. En oppføring tas ut når ligasiden har samme resultat som
    vi; ingen tidsgrense ellers. Tabellkontrollen bruker dem (ferske_bekreftede),
    og status.json viser dem som advarsel (overstemt_tekster)."""
    ut = {}
    for n, v in (gml or {}).items():
        k = tuple(n.split("|"))
        if ligasiden is not None and k in ligasiden and list(ligasiden[k]) == list(v.get("resultat") or []):
            continue
        if ligasiden is not None and k in ligasiden:
            v = {**v, "ligasiden": [int(ligasiden[k][0]), int(ligasiden[k][1])]}
        ut[n] = v
    for k, (resultat, lig, kilder) in (nye or {}).items():
        n = f"{k[0]}|{k[1]}"
        if n in ut and ut[n].get("resultat") == [int(resultat[0]), int(resultat[1])] \
                and ut[n].get("ligasiden") == [int(lig[0]), int(lig[1])]:
            continue    # står alt: tidspunktet beholdes, og fila endres ikke i hver kjøring
        ut[n] = {"resultat": [int(resultat[0]), int(resultat[1])],
                 "ligasiden": [int(lig[0]), int(lig[1])], "kilder": sorted(kilder),
                 "publisert": naa.isoformat(timespec="seconds")}
    return ut


def overstemt_etterpaa(publiserte, ligasiden, bekreftet):
    """De publiserte resultatene der ligasiden NÅ viser noe annet, og
    resultatet vårt er bekreftet av kilder utenfor NTF (17.10.2026).

    Hullet det tetter: en kamp publisert av ESPN og Highlightly før ligasiden
    hadde resultatet, ble aldri "overstemt" når ligasiden senere viste noe
    annet (publiserte resultater vurderes ikke på nytt), og tabellkontrollen
    ga rødt etter seks timer. Slike kamper er overstemt i senere kjøringer.

    publiserte: {(hjemme, borte): (hg, ag)} som står på siden. ligasiden:
    {(hjemme, borte): (hg, ag)} fra ligasiden nå, eller None. bekreftet:
    feltet "bekreftet" i results_state.json ({"H|B": {resultat, kilder, ...}}),
    med denne kjøringens nye. Uten en bekreftelse med samme resultat er det
    ikke med: da er det et ubekreftet avvik, og tabellkontrollen gjelder.
    Returnerer {(hjemme, borte): (resultat, ligasidens resultat, kilder)}."""
    ut = {}
    for k, r in (publiserte or {}).items():
        lig = (ligasiden or {}).get(k)
        if lig is None or tuple(lig) == tuple(r):
            continue
        b = (bekreftet or {}).get(f"{k[0]}|{k[1]}") or {}
        if b.get("kilder") and list(b.get("resultat") or []) == [r[0], r[1]]:
            ut[k] = (tuple(r), tuple(lig), list(b["kilder"]))
    return ut


def overstemt_tekster(liga, state_sti=None, overstemt=None):
    """Advarslene til status.json for resultatene publisert mot ligasidens
    stemme: "Viking-Fredrikstad: publisert 3-2 (espn og highlightly), ligasiden
    har 1-2"."""
    if overstemt is not None:
        ov = overstemt
    else:
        sti = Path(state_sti) if state_sti else ROT / liga / "data" / "results_state.json"
        try:
            ov = json.loads(sti.read_text(encoding="utf-8")).get("overstemt") or {}
        except Exception:
            return []
    return [f"{n.replace('|', '-')}: publisert {v['resultat'][0]}-{v['resultat'][1]} ({' og '.join(v.get('kilder') or [])}), "
            f"ligasiden har {v['ligasiden'][0]}-{v['ligasiden'][1]}"
            for n, v in sorted(ov.items()) if v.get("resultat") and v.get("ligasiden")]


def ferske_bekreftede(liga, kamper, naa, state_sti=None, timer=FERSK_TIMER):
    """De spilte kampene i `kamper` som er FERSKE (avspark for mindre enn
    `timer` timer siden) og har resultatet BEKREFTET utenfor NTF: det står i
    results_state.json med nøyaktig samme resultat og minst én kilde.

    Returnerer [{home, away, hg, ag, avspark, frist, kilder}] med avspark og
    frist som ISO-tid i UTC. En kamp uten avspark, uten oppføring eller med et
    annet lagret resultat er ikke med: da gjelder tabellkontrollen som før.

    OVERSTEMT (17.10.2026): en kamp i "overstemt" (publisert mot ligasidens
    stemme) er med uansett alder, så lenge ligasiden er uenig, med frist None:
    ligasidens tabell fører den med ligasidens resultat, og det er en
    advarsel, ikke rødt. Uten frist holder den heller ikke porten åpen
    (should_fetch.tabell_venter)."""
    from zoneinfo import ZoneInfo
    sti = Path(state_sti) if state_sti else ROT / liga / "data" / "results_state.json"
    try:
        _st = json.loads(sti.read_text(encoding="utf-8"))
    except Exception:
        return []
    bekreftet = _st.get("bekreftet") or {}
    overstemt = _st.get("overstemt") or {}
    ut = []
    for m in kamper:
        o = overstemt.get(f"{m.get('home')}|{m.get('away')}")
        if o and m.get("hg") is not None and list(o.get("resultat") or []) == [m["hg"], m["ag"]]:
            try:
                avspark = datetime.fromisoformat(f"{m['date']}T{m['time']}").replace(
                    tzinfo=ZoneInfo("Europe/Oslo")).astimezone(naa.tzinfo).isoformat(timespec="seconds")
            except Exception:
                avspark = None
            ut.append({"home": m["home"], "away": m["away"], "hg": m["hg"], "ag": m["ag"],
                       "avspark": avspark, "frist": None, "kilder": list(o.get("kilder") or []), "overstemt": True})
            continue
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
