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

    Dato, avspark og runde oppdateres likevel. De er entydige
    terminlistedata, og en kamp som flyttes skal flytte seg hos oss også.
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

    return ut


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
        log(f"Datovakt: fant ikke runder i {aar}-dataene -- står over.")
        return merged, [], None
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
            log(f"ADVARSEL: {r['home']}-{r['away']} oppgis med {r['date']}, "
                f"utenfor {fra}–{til} i sesongen {aar}. "
                + (f"Beholder {forrige}." if forrige
                   else "Ingen tidligere dato i denne sesongen, slipper gjennom."))
            if forrige:
                r = {**r, "date": forrige, "time": (g.get("time") or r.get("time"))}
        ut.append(r)

    if merged and len(utenfor) > len(merged) * ANDEL_KILDEFEIL:
        log(f"AVVIK: {len(utenfor)} av {len(merged)} kamper hadde dato utenfor "
            f"{fra}–{til}. Det er ikke enkeltfeil -- noe er galt med kilden.")
    return ut, utenfor, None
