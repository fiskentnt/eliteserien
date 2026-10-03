#!/usr/bin/env python3
"""Felles byggesteiner for datafilene hver liga viser.

update_data.py (Eliteserien) og obos_build_data.py (OBOS) henter kampene fra
helt ulike kilder, men skriver det samme: matches.json med spilte kamper og
fixtures.json med rundene det er kamper igjen i. Den delen er lik, og lå
tidligere i begge skriptene. Da OBOS ble bygget, ble kopien der laget uten
regelen om å hoppe over ferdigspilte runder, og kamplisten viste alle 240
kampene i stedet for de 56 som står igjen. Nå finnes reglene ett sted.

En "rad" er en dict med: round, date, time, home, away, hg, ag.
hg/ag er None for en kamp som ikke er spilt.
"""
import json

MONTH_ABBR = {1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "mai", 6: "jun",
              7: "jul", 8: "aug", 9: "sep", 10: "okt", 11: "nov", 12: "des"}


def month_range_label(dates):
    """Formaterer en liste ISO-datoer til f.eks. '18. til 20. sep' eller '13. des'."""
    days = sorted({d for d in dates})
    parts = [(int(d[8:10]), int(d[5:7])) for d in days]
    first, last = parts[0], parts[-1]
    if first == last:
        return f"{first[0]}. {MONTH_ABBR[first[1]]}"
    joiner = "og" if len(parts) <= 2 or (last[0] - first[0] == 1 and first[1] == last[1]) else "til"
    if first[1] == last[1]:
        return f"{first[0]}. {joiner} {last[0]}. {MONTH_ABBR[first[1]]}"
    return f"{first[0]}. {MONTH_ABBR[first[1]]} {joiner} {last[0]}. {MONTH_ABBR[last[1]]}"


def build_matches(rows):
    """matches.json: de spilte kampene, i kronologisk rekkefølge.

    Sorteres på avspark, ikke på rundenummer: to kamper samme dag skal stå i
    den rekkefølgen de ble spilt. Skriptene sorterte ulikt før (Eliteserien på
    runde, OBOS på klokkeslett) -- her er det én regel.
    """
    played = [r for r in rows if r["hg"] is not None]
    played.sort(key=lambda r: (r["date"], r.get("time") or "", r["round"], r["home"]))
    return [{"date": r["date"], "time": r.get("time"), "round": r["round"],
             "home": r["home"], "away": r["away"], "hg": r["hg"], "ag": r["ag"]}
            for r in played]


def build_fixtures(rows):
    """fixtures.json: rundene det står kamper igjen i.

    To regler som begge ligaene trenger:
      Rundene sorteres kronologisk etter mediandatoen, ikke etter
      rundenummer. En runde som er flyttet skal stå der den faktisk spilles,
      ikke først i listen fordi nummeret er lavt.
      En ferdigspilt runde tas ikke med. Kamplisten er til for å legge inn
      resultater, og de spilte kampene ligger allerede i tabellen.
    """
    by_round = {}
    for r in rows:
        by_round.setdefault(r["round"], []).append(r)
    # Mediandatoen, som rundene på siden (buildRoundSeq): en enkelt flyttet kamp
    # flytter ikke runden, en hel flyttet runde flyttes.
    def _median(rn):
        d = sorted(r["date"] for r in by_round[rn])
        return d[len(d) // 2]
    round_order = sorted(by_round, key=lambda rn: (_median(rn), rn))

    out = []
    for round_no in round_order:
        group = by_round[round_no]
        if not any(r["hg"] is None for r in group):
            continue
        group = sorted(group, key=lambda r: (r["date"], r.get("time") or "", r["home"]))
        moved = flyttede(group)
        # Datospennet i overskriften regnes uten de utsatte kampene. Ellers sto
        # det "2. til 21. okt" på en runde som spilles 2. til 5. oktober, fordi
        # én kamp var utsatt -- og det ser ut som en feil.
        rest = [r for r in group if id(r) not in moved] or group
        out.append({
            "round": round_no,
            "when": month_range_label([r["date"] for r in rest]),
            "matches": [
                {"home": r["home"], "away": r["away"], "date": r["date"], "time": r.get("time"),
                 "played": r["hg"] is not None, "hg": r["hg"], "ag": r["ag"],
                 **({"moved": True} if id(r) in moved else {})}
                for r in group
            ],
        })
    return out


# Samme regel som siden (RUNDE_SAMLET_DAGER og flyttetFraRunde i
# eliteserien/index.html, 4.10.2026): en kamp mer enn så mange dager fra
# mediandatoen i runden er flyttet ut av runden, utsatt eller flyttet fram.
RUNDE_SAMLET_DAGER = 6


def flyttede(group):
    """Kampene i runden som er flyttet ut av rundens vanlige tidsrom, som en
    mengde av id().

    En runde spilles normalt over noen dager rundt mediandatoen. En kamp mer
    enn RUNDE_SAMLET_DAGER dager før eller etter den er flyttet: utsatt
    (Sogndal-Raufoss i runde 24, 21.10.) eller flyttet fram (Tromsø-Lillestrøm
    i runde 15, spilt 15.4.). En hel flyttet runde har medianen med seg og har
    ingen flyttede kamper. Før gjaldt bare kamper minst fire dager etter den
    siste av de andre: to kamper utsatt til samme dag (runde 8 i Eliteserien)
    ble ikke sett, og ingen kamper flyttet fram. Regelen ser bare på datoene
    som alt ligger i terminlisten; ingenting hentes eller gjettes.
    """
    from datetime import date as _date, timedelta as _td

    if len(group) < 2:
        return set()
    datoer = sorted(r["date"] for r in group)
    mid = _date.fromisoformat(datoer[len(datoer) // 2])
    fra = (mid - _td(days=RUNDE_SAMLET_DAGER)).isoformat()
    til = (mid + _td(days=RUNDE_SAMLET_DAGER)).isoformat()
    return {id(r) for r in group if r["date"] < fra or r["date"] > til}


def forrige_terminliste(data_dir, sesong, forventet_par=None, log=lambda s: None):
    """Den siste gyldige terminlisten vi selv har skrevet: de spilte kampene
    fra matches.json og de uspilte fra fixtures.json, paa radformen
    {round, date, time, home, away, hg, ag}.

    Reserven naar ligasiden ikke kan leses (3.10.2026). Foer var reserven
    CSV-en, et oeyeblikksbilde fra sesongstart, og da ble Ranheim-Sogndal satt
    tilbake fra 14:30 til 17:00 i 50 minutter, enda flyttingen var rettet
    hos oss for lenge siden. En feil hos NTF skal aldri sette tilbake et
    klokkeslett vi har rettet.

    None hvis filene mangler, har kamper fra en annen sesong, eller ikke har
    nøyaktig lagparene i forventet_par (hele terminlisten) -- da faller
    kalleren tilbake paa CSV-en, som ved sesongstart."""
    from pathlib import Path as _P
    data_dir = _P(data_dir)
    try:
        spilte = json.loads((data_dir / "matches.json").read_text(encoding="utf-8"))
        runder = json.loads((data_dir / "fixtures.json").read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  forrige terminliste: kunne ikke lese matches.json og fixtures.json ({e})")
        return None
    rader = {}
    for m in spilte:
        rader[(m["home"], m["away"])] = {"round": m["round"], "date": m["date"], "time": m.get("time"),
                                         "home": m["home"], "away": m["away"], "hg": m["hg"], "ag": m["ag"]}
    for r in runder:
        for m in r.get("matches", []):
            k = (m["home"], m["away"])
            if k in rader:
                continue          # spilt: matches.json gjelder
            rader[k] = {"round": r["round"], "date": m["date"], "time": m.get("time"),
                        "home": m["home"], "away": m["away"],
                        "hg": m.get("hg") if m.get("played") else None,
                        "ag": m.get("ag") if m.get("played") else None}
    annen = [k for k, v in rader.items() if not str(v["date"] or "").startswith(str(sesong))]
    if annen:
        log(f"  forrige terminliste: {len(annen)} kamper er ikke fra {sesong} -- brukes ikke")
        return None
    if forventet_par is not None and set(rader) != set(forventet_par):
        log(f"  forrige terminliste: {len(rader)} kamper, ventet {len(forventet_par)} "
            f"({len(set(forventet_par) - set(rader))} mangler) -- brukes ikke")
        return None
    return sorted(rader.values(), key=lambda m: (m["date"], m["time"] or "", m["home"]))


def write_json(path, data, indent=2):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
