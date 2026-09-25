"""Avgjør uenighet mellom eliteserien.no og produksjonen med ESPN som dommer.

Kjør: python3 verifiser_avvik.py   -> skriver testdata/verifisert_avvik.json

ESPN er uavhengig av begge de to andre kildene og oppgir eksakt UTC-tidspunkt
per kamp, som regnes om til norsk lokaltid. Filen er fasiten testene bruker
der produksjonen og eliteserien.no er uenige, slik at testen ikke låser seg
til en verdi produksjonen har arvet feil fra ffksupporter.net.
"""
import importlib.util
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import es_source

OSLO = ZoneInfo("Europe/Oslo")
PROD = Path("/Users/trond/Documents/eliteserien/eliteserien/data")
UT = Path(__file__).parent / "testdata" / "verifisert_avvik.json"

spec = importlib.util.spec_from_file_location(
    "espn_source", "/Users/trond/Documents/eliteserien/scripts/espn_source.py")
espn_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(espn_source)
TIL_ID = {v: k for k, v in espn_source.TEAM_ID_TO_NAME.items()}


def prod_kamper():
    ut = {(r["home"], r["away"]): r for r in json.loads((PROD / "matches.json").read_text("utf-8"))}
    for runde in json.loads((PROD / "fixtures.json").read_text("utf-8")):
        for k in runde["matches"]:
            ut[(k["home"], k["away"])] = {**k, "round": runde["round"]}
    return ut


def espn_for_dato(dato):
    url = ("https://site.api.espn.com/apis/site/v2/sports/soccer/nor.1/scoreboard"
           f"?dates={dato.replace('-', '')}")
    req = urllib.request.Request(url, headers={"User-Agent": es_source.USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    ut = {}
    for ev in data.get("events", []):
        lag = ev["competitions"][0]["competitors"]
        # Retningen må med: hjemme- og bortekampen mellom to lag er to ulike
        # kamper, og en mengde av lag-id-er slår dem sammen til én.
        hjemme = next(x["team"]["id"] for x in lag if x.get("homeAway") == "home")
        borte = next(x["team"]["id"] for x in lag if x.get("homeAway") == "away")
        lokal = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(OSLO)
        ut[(hjemme, borte)] = {"date": lokal.strftime("%Y-%m-%d"), "time": lokal.strftime("%H:%M")}
    return ut


def main():
    td = Path(__file__).parent / "testdata"
    rader = (es_source.parse_side((td / "resultater_2026-09-25.html").read_text("utf-8"), "resultater")
             + es_source.parse_side((td / "terminliste_2026-09-25.html").read_text("utf-8"), "terminliste"))
    prod = prod_kamper()

    uenige = [r for r in rader
              if (p := prod.get((r["home"], r["away"])))
              and (r["date"] != p.get("date") or r["time"] != p.get("time"))]
    print(f"{len(uenige)} kamper der eliteserien.no og produksjonen er uenige om dato/avspark")

    cache, ut = {}, []
    for r in uenige:
        for d in {r["date"], prod[(r["home"], r["away"])].get("date")}:
            if d and d not in cache:
                cache[d] = espn_for_dato(d)
                time.sleep(0.4)
        ids = (TIL_ID[r["home"]], TIL_ID[r["away"]])
        treff = next((d[ids] for d in cache.values() if ids in d), None)
        p = prod[(r["home"], r["away"])]
        if treff is None:
            print(f"  ADVARSEL: ESPN har ingen kamp for {r['home']} - {r['away']}")
            continue
        dommer = ("eliteserien.no" if (treff["date"], treff["time"]) == (r["date"], r["time"])
                  else "produksjon" if (treff["date"], treff["time"]) == (p.get("date"), p.get("time"))
                  else "ingen")
        ut.append({"home": r["home"], "away": r["away"], "round": r["round"],
                   "es": {"date": r["date"], "time": r["time"]},
                   "prod": {"date": p.get("date"), "time": p.get("time")},
                   "espn": treff, "dommer": dommer})

    UT.write_text(json.dumps(ut, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fordeling = {}
    for x in ut:
        fordeling[x["dommer"]] = fordeling.get(x["dommer"], 0) + 1
    print(f"ESPN som dommer: {fordeling}")
    print(f"skrevet: {UT}")


if __name__ == "__main__":
    main()
