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
