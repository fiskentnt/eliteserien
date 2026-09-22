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
      Rundene sorteres kronologisk etter tidligste kampdato, ikke etter
      rundenummer. En runde som er flyttet skal stå der den faktisk spilles,
      ikke først i listen fordi nummeret er lavt.
      En ferdigspilt runde tas ikke med. Kamplisten er til for å legge inn
      resultater, og de spilte kampene ligger allerede i tabellen.
    """
    by_round = {}
    for r in rows:
        by_round.setdefault(r["round"], []).append(r)
    round_order = sorted(by_round, key=lambda rn: min(r["date"] for r in by_round[rn]))

    out = []
    for round_no in round_order:
        group = by_round[round_no]
        if not any(r["hg"] is None for r in group):
            continue
        group = sorted(group, key=lambda r: (r["date"], r.get("time") or "", r["home"]))
        out.append({
            "round": round_no,
            "when": month_range_label([r["date"] for r in group]),
            "matches": [
                {"home": r["home"], "away": r["away"], "date": r["date"], "time": r.get("time"),
                 "played": r["hg"] is not None, "hg": r["hg"], "ag": r["ag"]}
                for r in group
            ],
        })
    return out


def write_json(path, data, indent=2):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
