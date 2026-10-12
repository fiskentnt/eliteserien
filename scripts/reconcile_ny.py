"""PROTOTYP: sammenslåing av kilder, med den offisielle ligakilden som fasit.

Fire roller, og de er bevisst adskilt:

  HOVEDKILDE       Norsk Toppfotball sin ligaside (eliteserien.no,
                   obos-ligaen.no). Fasit for terminliste, runde, dato og
                   avspark. Gir også resultater.

  OFFISIELL        NFF sin turneringsdatabase (fotball.no). Uavhengig av
  KONTROLL         ligasidene og like offisiell. Rollen er å si fra når
                   hovedkilden tar feil -- og å være reserve hvis den er
                   nede. Dette er det som manglet: fram til nå hadde runde
                   og dato nøyaktig én kilde, uten noen annenmening.

  RESERVE          ffksupporter.net (Eliteserien). Degradert fra fasit til
                   siste utvei. Den hadde feil avspark på 21 kamper og feil
                   dato på 1 i 2026, verifisert mot ESPN og fotball.no.

  RESULTATKONTROLL ESPN for Eliteserien, OddsPapi og Wikipedia for OBOS.
                   Brukes bare på resultater, aldri på terminlisten.

Nøkkelen er (hjemmelag, bortelag) i alle kilder. Den er unik i en dobbel
serie og uavhengig av dato og runde. Når en kamp eller en hel runde flyttes,
endres dato og avspark, men kampen er den samme og skal oppdateres -- ikke
dukke opp som en ny kamp ved siden av den gamle.
"""
import os


def _nøkkel(r):
    return (r["home"], r["away"])


def _indeks(rader):
    return {_nøkkel(r): r for r in (rader or [])}


def reconcile(hovedkilde, offisiell_kontroll=None, reserver=(), resultatkontroll=(),
              log=lambda s: None):
    """Slår sammen kildene. Returnerer rader på formen
    {date, time, round, home, away, hg, ag, src}.

    src sier hvor RESULTATET kom fra (None for uspilte kamper). Runde, dato og
    avspark kommer alltid fra hovedkilden når kampen finnes der.

    reserver og resultatkontroll er lister av (navn, rader), slik at
    advarslene kan si hvilken kilde som er uenig.
    """
    hoved = _indeks(hovedkilde)
    if not hoved:
        raise ValueError("hovedkilden ga ingen kamper -- kalleren skal falle "
                         "tilbake til den offisielle kontrollkilden")
    kontroll = _indeks(offisiell_kontroll)
    reserve_ix = [(navn, _indeks(rader)) for navn, rader in reserver]
    res_ix = [(navn, _indeks(rader)) for navn, rader in resultatkontroll]

    merged = []
    for key in hoved:
        r = hoved[key]
        dato, tid, runde = r["date"], r["time"], r["round"]
        hvem = f"{key[0]}-{key[1]}"

        # --- terminlisten: hovedkilden vinner, uenighet skal alltid sees ---
        for navn, ix in ([("fotball.no", kontroll)] if kontroll else []) + reserve_ix:
            a = ix.get(key)
            if not a:
                if ix is kontroll:
                    log(f"ADVARSEL: {hvem} finnes ikke hos fotball.no -- "
                        f"kontrollen er ufullstendig for denne kampen")
                continue
            if a.get("round") != runde:
                log(f"ADVARSEL runde {hvem}: hovedkilde=#{runde} {navn}=#{a['round']}")
            if a.get("date") != dato:
                log(f"ADVARSEL dato {hvem}: hovedkilde={dato} {navn}={a['date']}")
            elif a.get("time") and tid and a["time"] != tid:
                log(f"ADVARSEL avspark {hvem}: hovedkilde={tid} {navn}={a['time']}")

        # --- resultat: hovedkilde, så offisiell kontroll, så reservene ---
        hg, ag, src = r["hg"], r["ag"], "ntf"
        if hg is None and kontroll.get(key, {}).get("hg") is not None:
            hg, ag, src = kontroll[key]["hg"], kontroll[key]["ag"], "nff"
        if hg is None:
            for navn, ix in res_ix + reserve_ix:
                a = ix.get(key)
                if a and a.get("hg") is not None:
                    if a.get("suspect"):
                        log(f"ADVARSEL: {navn} har mistenkelig resultat for {hvem} "
                            f"-- hopper over og venter på den offisielle kilden")
                        continue
                    hg, ag, src = a["hg"], a["ag"], navn
                    break

        # --- uavhengig resultatkontroll ---
        if hg is not None:
            for navn, ix in ([("fotball.no", kontroll)] if kontroll else []) + res_ix + reserve_ix:
                a = ix.get(key)
                if (a and a.get("hg") is not None and not a.get("suspect")
                        and (a["hg"], a["ag"]) != (hg, ag)):
                    log(f"ADVARSEL resultat {hvem} runde {runde}: {src}={hg}-{ag} "
                        f"{navn}={a['hg']}-{a['ag']} -- bruker {src}")

        merged.append({"date": dato, "time": tid, "round": runde,
                       "home": key[0], "away": key[1], "hg": hg, "ag": ag,
                       "src": src if hg is not None else None})

    # En kamp som bare finnes hos en annen kilde skal ikke forsvinne stille.
    for navn, ix in ([("fotball.no", kontroll)] if kontroll else []) + reserve_ix:
        for key in set(ix) - set(hoved):
            a = ix[key]
            log(f"ADVARSEL: {key[0]}-{key[1]} (runde {a.get('round')}) finnes hos "
                f"{navn}, men ikke hos hovedkilden -- tatt med fra {navn}")
            merged.append({**a, "home": key[0], "away": key[1],
                           "src": navn if a.get("hg") is not None else None})
            hoved[key] = a  # så den ikke tas med to ganger fra neste kilde

    merged.sort(key=lambda r: (r["date"], r["time"] or "", r["home"]))
    return merged


def behold_eksisterende(merged, eksisterende, log=lambda s: None):
    """Et resultat vi allerede har publisert skal aldri forsvinne.

    En kamp som er ferdigspilt hos oss, men som kildene i dag ikke melder
    som ferdig -- fordi siden er midt i en omlegging, fordi raden har fått
    en status vi ikke kjenner, eller fordi kampen står som pågående -- skal
    beholde resultatet sitt. Alternativet er at en ferdigspilt kamp blir
    uspilt igjen, og at tabellen går bakover.

    Dato, avspark og runde for en SPILT kamp beholdes også (8.10.2026, se
    frys_spilte()): eliteserien.no viste 7.10. Start-Tromsø (spilt 3.5.) som
    5.1., Tromsø-Vålerenga (spilt 11.7.) som 18.11. og Brann-Rosenborg (spilt
    2.8.) som 19.2. Bare datovinduet stoppet dem, og 18.11. ville sluppet
    gjennom når vinduet vokste etter runde 23.
    """
    gamle = {_nøkkel(r): r for r in (eksisterende or [])}
    ut = []
    for r in merged:
        g = gamle.get(_nøkkel(r))
        if r["hg"] is None and g and g.get("hg") is not None:
            log(f"ADVARSEL: {r['home']}-{r['away']} står som ikke ferdig hos "
                f"kildene, men vi har {g['hg']}-{g['ag']} fra før -- beholder "
                f"resultatet, oppdaterer bare dato og avspark")
            r = {**r, "hg": g["hg"], "ag": g["ag"], "src": g.get("src") or "beholdt"}
        elif (r["hg"] is not None and g and g.get("hg") is not None
              and (r["hg"], r["ag"]) != (g["hg"], g["ag"])):
            log(f"ADVARSEL: {r['home']}-{r['away']} endret resultat fra "
                f"{g['hg']}-{g['ag']} til {r['hg']}-{r['ag']} -- bruker det nye, "
                f"men dette skal ikke skje for en ferdigspilt kamp")
        ut.append(r)

    # En ferdigspilt kamp som er borte fra ALLE kildene skal ikke forsvinne
    # stille. Det er en verre nedgradering enn å bli uspilt: kampen faller ut
    # av tabellen helt. Vi tar den med videre uendret og sier tydelig fra.
    sett = {_nøkkel(r) for r in merged}
    for key, g in gamle.items():
        if key in sett or g.get("hg") is None:
            continue
        log(f"ADVARSEL: {key[0]}-{key[1]} ({g.get('date')}) er ferdigspilt hos oss "
            f"med {g['hg']}-{g['ag']}, men finnes ikke hos noen kilde nå -- "
            f"beholder kampen uendret")
        ut.append(dict(g))

    return frys_spilte(ut, eksisterende, log=log)


def frys_spilte(rader, eksisterende, kilde="ligasiden", log=lambda s: None):
    """En spilt kamp beholder dato, avspark og runde (8.10.2026).

    Datoen hører til resultatet: den var bekreftet av to kilder da resultatet
    ble publisert, og modellen (tidsvektingen), formen, "forrige kamp" og
    treffsikkerhetsloggen bygger på den. Ligasiden kan bare flytte uspilte
    kamper. Viser kilden noe annet for en spilt kamp, beholdes våre verdier,
    og det sies fra (AVVIK, og ::warning i GitHub Actions). Trengs en
    rettelse av en spilt kamp, gjøres den for hånd.

    Bare i samme sesong: en rad fra et annet år for de samme lagene er neste
    (eller forrige) sesongs kamp, og den røres ikke her.

    eksisterende: våre rader; de med resultat (hg) er de spilte. Gjelder
    begge ligaene (update_data.py via behold_eksisterende, obos_build_data.py
    direkte)."""
    spilte = {_nøkkel(g): g for g in (eksisterende or []) if g.get("hg") is not None and g.get("date")}

    def vis(x):
        d = x.get("date") or ""
        return f"{int(d[8:10])}.{int(d[5:7])}." + (f" {x['time']}" if x.get("time") else "") if len(d) == 10 else str(d)
    ut = []
    for r in rader:
        g = spilte.get(_nøkkel(r))
        # Bare i samme sesong (år): de samme lagene møtes igjen neste år, og
        # en rad fra et annet år er en annen kamp (sesonggrensen tar den).
        if (g and (r.get("date") or "")[:4] == g["date"][:4]
                and (r.get("date"), r.get("time"), r.get("round")) != (g.get("date"), g.get("time"), g.get("round"))):
            runde = (f" (runde {r.get('round')} der, {g.get('round')} hos oss)"
                     if r.get("round") != g.get("round") else "")
            melding = (f"{r['home']}-{r['away']} er spilt {vis(g)}; {kilde} viser nå {vis(r)}{runde} "
                       f"-- beholder {vis(g)}")
            log(f"AVVIK: {melding}")
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::warning title=Spilt kamp: annen dato hos kilden::{melding}")
            r = {**r, "date": g["date"], "time": g.get("time"), "round": g.get("round")}
        ut.append(r)
    return ut


def _vis_dato(d, t=None):
    return (f"{int(d[8:10])}.{int(d[5:7])}." if d and len(d) == 10 else str(d)) + (f" {t}" if t else "")


def bekreft_datoer(rader, forrige, kilder, log=lambda s: None, nye=(), overstyringer=()):
    """Ingen enkeltkilde setter eller flytter datoen for en uspilt kamp.

    eliteserien.no viste Rosenborg-Start (runde 26, 7.11. 18:00) som 7.1. den
    9.10.2026 og som 18.11. den 10.10. Datovakten (rimelige_datoer) stopper bare
    datoer utenfor sesongen, så 18.11. kom på siden. Feilene flytter seg
    mellom kampene fra dag til dag. Derfor:

      * FLYTTING: ligasiden viser en annen dato eller tid enn vi har lagret
        for en uspilt kamp. Kampen flyttes bare når den uavhengige kilden
        viser samme nye dato og tid. Ellers beholder vi datoen og tiden vi
        har, med ADVARSEL ("beholdt"): flyttingen venter.
      * NY KAMP (13.10.2026): en uspilt kamp uten brukbar lagret dato (nye, se
        uten_lagret_dato). Datoen og tiden godtas bare når den uavhengige
        kilden viser det samme. Ellers er den "ubekreftet", og kalleren skal
        IKKE skrive noe: det finnes ingen gammel dato å beholde, vi utelater
        aldri en kamp, og en ubekreftet dato skal ikke ut.

    kilder: [(navn, hent)] i rekkefølge. Den første som svarer, avgjør; de
    neste spørres bare når den foran kaster unntak. Eliteserien: ESPN
    (sesongkallet, gratis), så kalenderfeeden. OBOS: Highlightly-listen fra
    den daglige hentingen (flytting.highlightly_lagret), ingen reserve. hent
    gir {(hjemme, borte): (dato, tid)} og kalles bare når minst én kamp er
    flyttet eller ny og ikke avgjort for hånd.

    overstyringer: avgjørelser for hånd fra <liga>/data/flytting_overstyring.json
    (flytting.les_overstyringer): {(hjemme, borte): {"valg", "dato", "tid"}}.
    En overstyring gjelder bare når ligasiden viser nøyaktig den datoen og
    tiden. "godta": flyttingen gjennomføres (eller den nye kampen godtas)
    uten kilde. "avvis": vi beholder det vi har, og flyttingen varsles ikke
    lenger ("avvist").

    forrige: terminlisten vi sist skrev (leaguedata.forrige_terminliste).
    Returnerer (rader, utfall). utfall er en liste av dict:
      {kamp, nokkel, type ("flytting"|"ny"), utfall ("flyttet"|"beholdt"|
       "avvist"|"bekreftet"|"ubekreftet"), kilde, ny, har, hva}."""
    gamle = {_nøkkel(g): g for g in (forrige or []) if g.get("hg") is None and g.get("date")}
    nye = set(nye or ())
    overstyringer = overstyringer or {}

    def ny_kamp(r):
        return r.get("hg") is None and bool(r.get("date")) and _nøkkel(r) in nye

    def flyttet(r):
        g = gamle.get(_nøkkel(r))
        return (not ny_kamp(r) and g is not None and r.get("hg") is None and r.get("date")
                and r["date"][:4] == g["date"][:4]     # samme sesong
                and (r.get("date"), r.get("time")) != (g.get("date"), g.get("time")))

    def overstyrt(r):
        """Overstyringen for kampen når den gjelder det ligasiden viser nå, ellers None."""
        o = overstyringer.get(_nøkkel(r))
        if o and (o.get("dato"), o.get("tid")) == (r.get("date"), r.get("time")):
            return o
        return None

    aktuelle = [r for r in rader if flyttet(r) or ny_kamp(r)]
    if not aktuelle:
        return rader, []
    for r in aktuelle:
        o = overstyringer.get(_nøkkel(r))
        if o and not overstyrt(r):
            log(f"ADVARSEL: overstyringen for {r['home']}-{r['away']} gjelder {_vis_dato(o.get('dato'), o.get('tid'))}, "
                f"men ligasiden viser nå {_vis_dato(r.get('date'), r.get('time'))} -- brukes ikke")

    fasit, kilde, svarte_ikke = None, None, []
    if any(not overstyrt(r) for r in aktuelle):
        for i, (navn, hent) in enumerate(kilder):
            try:
                fasit, kilde = hent(), navn
                break
            except Exception as e:
                svarte_ikke.append(navn)
                neste = kilder[i + 1][0] if i + 1 < len(kilder) else None
                if i == 0 and neste:
                    log(f"Flytting: {navn} svarte ikke ({type(e).__name__}: {e}) -- {neste} avgjør.")
                elif i == 0:
                    log(f"Flytting: {navn} kan ikke brukes ({type(e).__name__}: {e}).")
                else:
                    log(f"Flytting: {navn} svarte heller ikke ({type(e).__name__}: {e}).")
    if len(svarte_ikke) >= 2:
        ingen_svarte = "verken " + " eller ".join([", ".join(svarte_ikke[:-1]), svarte_ikke[-1]]) + " svarte"
    else:
        ingen_svarte = f"{svarte_ikke[0] if svarte_ikke else 'ingen kilde'} kunne ikke brukes"

    ut, utfall = [], []
    for r in rader:
        er_ny = ny_kamp(r)
        if not er_ny and not flyttet(r):
            ut.append(r)
            continue
        k = _nøkkel(r)
        g = gamle.get(k) if not er_ny else None
        ny = (r["date"], r.get("time"))
        har = (g["date"], g.get("time")) if g else None
        kamp = f"{r['home']}-{r['away']}"
        f0 = {"kamp": kamp, "nokkel": (r["home"], r["away"]), "type": "ny" if er_ny else "flytting", "ny": ny, "har": har}
        o = overstyrt(r)
        if o and o["valg"] == "godta":
            log(f"Flytting: {kamp} flyttet fra {_vis_dato(*har)} til {_vis_dato(*ny)}, godtatt for hånd (overstyringsfilen)." if har
                else f"Ny kamp: {kamp} {_vis_dato(*ny)}, godtatt for hånd (overstyringsfilen).")
            utfall.append({**f0, "utfall": "bekreftet" if er_ny else "flyttet", "kilde": "overstyring", "hva": "godtatt for hånd"})
            ut.append(r)
            continue
        if o and o["valg"] == "avvis" and not er_ny:
            log(f"Flytting avvist for hånd (overstyringsfilen): {kamp}: ligasiden viser {_vis_dato(*ny)}, "
                f"vi beholder {_vis_dato(*har)}.")
            utfall.append({**f0, "utfall": "avvist", "kilde": "overstyring", "hva": "avvist for hånd"})
            ut.append({**r, "date": g["date"], "time": g.get("time")})
            continue
        if fasit is not None and fasit.get(k) == ny:
            log(f"Flytting: {kamp} flyttet fra {_vis_dato(*har)} til {_vis_dato(*ny)}, bekreftet av {kilde}." if har
                else f"Ny kamp: {kamp} {_vis_dato(*ny)}, bekreftet av {kilde}.")
            utfall.append({**f0, "utfall": "bekreftet" if er_ny else "flyttet", "kilde": kilde, "hva": f"bekreftet av {kilde}"})
            ut.append(r)
            continue
        if fasit is None:
            hva = ingen_svarte
        elif k in fasit:
            hva = f"{kilde} viser {_vis_dato(*fasit[k])}"
        else:
            hva = f"{kilde} har ikke kampen"
        if er_ny:
            melding = f"{kamp}: ligasiden viser {_vis_dato(*ny)}, og vi har ingen lagret dato; {hva} -- ikke bekreftet"
            log(f"AVVIK: {melding}")
            utfall.append({**f0, "utfall": "ubekreftet", "kilde": kilde, "hva": hva})
            ut.append(r)
            continue
        melding = f"{kamp}: ligasiden viser {_vis_dato(*ny)}, vi har {_vis_dato(*har)}; {hva} -- beholder {_vis_dato(*har)}"
        log(f"ADVARSEL: {melding}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=Flytting ikke bekreftet::{melding}")
        utfall.append({**f0, "utfall": "beholdt", "kilde": kilde, "hva": hva})
        ut.append({**r, "date": g["date"], "time": g.get("time")})
    return ut, utfall


def bekreft_flytting(rader, forrige, hent_espn, hent_kalender, log=lambda s: None):
    """Regelen for Eliteserien slik den ble innført 10.10.2026: en uspilt kamp
    flyttes bare når ESPN viser samme nye dato og tid; svarer ikke ESPN,
    avgjør kalenderfeeden. Se bekreft_datoer, som denne kaller.
    Returnerer (rader, utfall), utfall = [(kamp, "flyttet"|"beholdt", kilde)]."""
    ut, utfall = bekreft_datoer(rader, forrige, [("ESPN", hent_espn), ("kalenderfeeden", hent_kalender)], log=log)
    return ut, [(u["kamp"], u["utfall"], u["kilde"]) for u in utfall]


# Hvor langt utenfor sesongens egne kamper en dato faar ligge for vi
# forkaster den. En utsatt kamp kan flyttes bakover i kalenderen, sjelden
# framover forbi sesongstart.
VINDU_FOR_DAGER = 7
VINDU_ETTER_DAGER = 45

# Over denne andelen utenfor vinduet er det ikke enkeltfeil, men noe galt med
# kilden -- typisk en markupendring som gir feil dato paa mange kamper.
ANDEL_KILDEFEIL = 0.25


def _dato(s):
    from datetime import date
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _median(datoer):
    d = sorted(datoer)
    return d[len(d) // 2]


def _sesongens_ytterkanter(kjente):
    """(medianen i forste runde, medianen i siste runde), eller None.

    IKKE min og maks av alle datoer: en enkelt lagret feildato -- akkurat den
    typen vi er ute etter -- ville da apnet vinduet og slatt vakten av. En
    runde har aatte kamper, sa medianen i den er ufolsom for en enkelt.
    """
    etter_runde = {}
    for r in kjente:
        runde = r.get("round")
        if runde is None:
            continue
        etter_runde.setdefault(runde, []).append(_dato(r["date"]))
    if not etter_runde:
        return None
    return (_median(etter_runde[min(etter_runde)]),
            _median(etter_runde[max(etter_runde)]))


class FeilSesong(Exception):
    """Ligasiden ga ingen kamper i den aktive sesongen.

    Egen type, og den skal IKKE fanges av en generell except rundt
    hentingen: "kilden er nede" og "kilden viser en annen sesong" er to ulike
    ting. Den forste kan forsvares med en reserve; den andre betyr at vi ikke
    vet hvilken sesong dataene hoerer til, og da skal ingenting skrives."""


def bare_aktiv_sesong(rader, sesong, log=lambda s: None):
    """(aktive rader, fordeling per aar) -- setter sesonggrensen EKSPLISITT.

    HVORFOR DEN FINNES: mellom siste runde og frysingen viser ligasiden BADE
    fjoraaret og neste sesong, med noyaktig de samme lagparene. Grensen laa
    fram til naa indirekte i ntf_source.slaa_sammen() sin duplikatregel --
    altsaa i en regel skrevet for noe annet, i kildelaget, som ikke kjenner
    aktiv sesong. En sesonggrense skal staa i klartekst der sesongen er
    kjent: i produksjonskjeden.

    Kaster FeilSesong naar ingen rad hoerer til aktiv sesong. Det er ALLTID
    et avvik, ogsaa for byttedatoen: fram til frysingen forventer vi aa finne
    aktiv sesong hos ligakilden. Da skal kjeden stoppe FOR den skriver noe,
    saa de eksisterende filene staar urort.

    sesong=None: ingen grense aa sette. Da filtreres ingenting -- den saken
    har sin egen feilkode i rimelige_datoer() ("ingen_autoritet")."""
    fordeling = {}
    for r in rader:
        aar = (r.get("date") or "")[:4]
        fordeling[aar] = fordeling.get(aar, 0) + 1
    if sesong is None:
        log(f"Sesonggrense: ingen autoritativ sesong -- filtrerer ikke "
            f"({fordeling}).")
        return list(rader), fordeling

    aar = str(sesong)
    aktive = [r for r in rader if (r.get("date") or "").startswith(aar)]
    andre = {k: v for k, v in fordeling.items() if k != aar}
    if andre and aktive:
        # EN linje, ikke en per rad: i vinduet for frysingen er dette 240
        # rader, og en linje per rad ville gjort loggen ubrukelig.
        log(f"Sesonggrense: {sum(andre.values())} rad(er) fra en annen sesong "
            f"enn {aar} holdes utenfor ({andre}). Går videre med "
            f"{len(aktive)} rad(er) fra {aar}.")
    if not aktive:
        raise FeilSesong(
            f"ligasiden ga 0 kamper i sesongen {aar} (fant {fordeling or 'ingenting'}). "
            f"Da vet vi ikke hvilken sesong dataene hører til, og ingenting "
            f"skrives. Er sesongen ferdig, skal den fryses; er byttedatoen "
            f"passert, kjør: python3 scripts/sesong.py . bytt --utfor")
    return aktive, fordeling


def rimelige_datoer(merged, eksisterende, sesong, log=lambda s: None):
    """(rader, utenfor, feilkode) -- retter datoer som umulig kan stemme.

    obos-ligaen.no oppga 25. september 2026 datoen 01.01.2026 for
    Haugesund-Sogndal, en kamp som ble spilt 5. september. Uten denne vakten
    ville kampen flyttet seg ni maaneder i tidsvektingen, og ingenting ville
    sagt fra for noen saa tabellen.

    SESONGEN kommer fra kjeden som kjorer (sesong.py), ikke fra dataene. Det
    er forskjellen som gjor at et sesongskifte og en massefeil kan skilles:

      * Eksisterende data fra en ANNEN sesong brukes aldri som forrige verdi.
        Ved skiftet er fjoraarets kamper irrelevante, og hele den nye
        terminlisten slipper gjennom uendret.
      * Vinduet settes av MEDIANDATOEN i forste og siste runde i sesongen,
        med margin. Et kalenderaar alene duger ikke -- 01.01.2026 ligger inne
        i 2026 -- og min/maks duger ikke, fordi en enkelt lagret feildato da
        ville apnet vinduet og slatt vakten av.
      * En dato utenfor vinduet rettes til forrige verdi fra samme sesong,
        uansett hvor mange det gjelder. Mangler forrige verdi, slipper
        kampen gjennom med advarsel -- vi utelater aldri en kamp.

    utenfor er lagparene som laa utenfor. Er de mange, er det kilden det er
    noe galt med, og kalleren skal la kjoringen feile synlig. utenfor er None
    naar sesong er None -- da har vakten staatt over, og kalleren skal ogsaa
    feile, men av en annen grunn."""
    from datetime import timedelta
    if sesong is None:
        # Ingen autoritativ sesong. Vi gjetter ikke -- kalleren skal la
        # kjoringen feile synlig, men dataene skrives som normalt.
        log("Datovakt: ingen autoritativ sesong -- står over uten å gjette.")
        return merged, None, "ingen_autoritet"
    aar = str(sesong)

    # SESONGSKIFTET IKKE KJORT. Registeret sier 2026, men terminlisten er
    # 2027. Lagparene gaar igjen, saa uten denne sperren ville vakten funnet
    # en "tidligere verdi" for hver kamp og skrevet HELE den nye sesongen
    # tilbake til fjoraarets datoer, kamp for kamp, uten at noe saa galt ut.
    aarene = {}
    for r in merged:
        if r.get("date"):
            aarene[r["date"][:4]] = aarene.get(r["date"][:4], 0) + 1
    if aarene:
        flest = max(aarene, key=aarene.get)
        if flest != aar and aarene[flest] > len(merged) * 0.5:
            log(f"AVVIK: terminlisten er for {flest}, men registeret sier "
                f"{aar}. Sesongskiftet er ikke kjørt. Datovakten retter "
                f"ingenting -- den ville skrevet hele {flest}-sesongen "
                f"tilbake til {aar}-datoer.")
            return merged, None, "sesongskifte_mangler"
    # Bare samme sesong teller som "forrige verdi".
    gamle = {_nøkkel(r): r for r in (eksisterende or [])
             if (r.get("date") or "").startswith(aar)}
    kjente = [r for r in gamle.values() if _dato(r.get("date"))]
    if len(kjente) < 20:
        # Ny sesong, eller for tynt grunnlag til aa si hva som er umulig.
        log(f"Datovakt: bare {len(kjente)} kjente kamper i {aar} -- står over.")
        return merged, [], None

    ytre = _sesongens_ytterkanter(kjente)
    if ytre is None:
        # De lagrede kampene mangler rundenummer: vinduet kan ikke regnes.
        # Vakten står ALDRI over i stillhet (13.10.2026): kalleren skal ikke
        # skrive noe, som ved "sesongskifte_mangler".
        log(f"AVVIK: de {len(kjente)} lagrede kampene i {aar} har ingen rundenummer, så sesongvinduet "
            f"kan ikke regnes. Datovakten kan ikke kontrollere datoene.")
        return merged, None, "ingen_runder"
    forste, siste = ytre
    fra = forste - timedelta(days=VINDU_FOR_DAGER)
    til = siste + timedelta(days=VINDU_ETTER_DAGER)

    ut, utenfor = [], []
    for r in merged:
        d = _dato(r.get("date"))
        if d and not (fra <= d <= til):
            utenfor.append(f"{r['home']}-{r['away']} ({r['date']})")
            g = gamle.get(_nøkkel(r))
            forrige = g.get("date") if g else None
            # Den forrige datoen maa selv ligge i vinduet. Ellers ville en feil
            # vi alt har lagret bli holdt fast for alltid.
            df = _dato(forrige)
            ogsaa_utenfor = bool(forrige) and not (df and fra <= df <= til)
            if ogsaa_utenfor:
                forrige = None
            log(f"ADVARSEL: {r['home']}-{r['away']} oppgis med {r['date']}, "
                f"utenfor {fra}–{til} i sesongen {aar}. "
                + (f"Beholder {forrige}." if forrige
                   else f"Tidligere dato {g.get('date')} er også utenfor, slipper gjennom her "
                        f"(må bekreftes av en uavhengig kilde, se bekreft_datoer)." if ogsaa_utenfor
                   else "Ingen tidligere dato i denne sesongen, slipper gjennom her "
                        "(må bekreftes av en uavhengig kilde, se bekreft_datoer)."))
            if forrige:
                r = {**r, "date": forrige, "time": (g.get("time") or r.get("time"))}
        ut.append(r)

    if merged and len(utenfor) > len(merged) * ANDEL_KILDEFEIL:
        log(f"AVVIK: {len(utenfor)} av {len(merged)} kamper hadde dato utenfor "
            f"{fra}–{til}. Det er ikke enkeltfeil -- noe er galt med kilden.")
    return ut, utenfor, None


def uten_lagret_dato(rader, eksisterende, sesong):
    """Lagparene for de USPILTE kampene i rader som ikke har en brukbar
    lagret dato (13.10.2026): kampen står ikke i eksisterende (terminlisten vi
    sist skrev), eller den lagrede datoen ligger utenfor sesongvinduet. Slike
    kamper kan ikke «beholde den gamle datoen», så datoen må bekreftes av en
    uavhengig kilde (bekreft_datoer, nye).

    Tom mengde når vinduet ikke kan regnes: uten sesong, og ved SESONGSTART
    (under 20 kjente kamper i sesongen), der hele den nye terminlisten godtas
    som før. Samme vindu som rimelige_datoer."""
    from datetime import timedelta
    if sesong is None:
        return set()
    aar = str(sesong)
    gamle = {_nøkkel(r): r for r in (eksisterende or []) if (r.get("date") or "").startswith(aar)}
    kjente = [r for r in gamle.values() if _dato(r.get("date"))]
    if len(kjente) < 20:
        return set()
    ytre = _sesongens_ytterkanter(kjente)
    if ytre is None:
        return set()
    fra, til = ytre[0] - timedelta(days=VINDU_FOR_DAGER), ytre[1] + timedelta(days=VINDU_ETTER_DAGER)
    ut = set()
    for r in rader:
        if r.get("hg") is not None or not r.get("date"):
            continue
        d = _dato((gamle.get(_nøkkel(r)) or {}).get("date"))
        if not (d and fra <= d <= til):
            ut.add(_nøkkel(r))
    return ut
