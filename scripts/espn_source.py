"""Kilde 2 (ferskhet): ESPN sitt åpne API for Eliteserien (nor.1), ingen nøkkel.

ESPN oppdaterer resultater raskere enn ffksupporter.net, men har vist seg å
kunne gi feil resultat for enkeltkamper (verifisert manuelt: to kamper i mai
2026 sto låst på 0-0 i ESPN sin data). Brukes derfor i update_data.py kun til
å fylle inn resultater ffksupporter.net ikke har lagt inn ennå — ffksupporter
er alltid fasit når den har et resultat. ESPN gir ingen rundenummer, så runde
kommer alltid fra ffksupporter.net.
"""
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

USER_AGENT = "eliteserien-tabell (+https://github.com/fiskentnt/eliteserien)"
LEAGUE = "nor.1"
REQUEST_DELAY = 0.4
OSLO = ZoneInfo("Europe/Oslo")

# ESPN lag-id -> visningsnavn slik det brukes i index.html
TEAM_ID_TO_NAME = {
    "3278": "Aalesund",
    "2980": "Bodø/Glimt",
    "3039": "Fredrikstad",
    "21380": "HamKam",
    "6750": "Start",
    "22165": "KFUM Oslo",
    "6672": "Kristiansund",
    "987": "Lillestrøm",
    "2715": "Molde",
    "438": "Rosenborg",
    "620": "Brann",
    "3279": "Sandefjord",
    "5002": "Sarpsborg 08",
    "5270": "Tromsø",
    "510": "Viking",
    "2791": "Vålerenga",
}


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all(cache_dir=None, log=lambda s: None):
    """Henter alle 16 lags sesongoppsett (spilte + kommende, via ?fixture=true)
    og returnerer deduplisert liste av {home, away, date, hg, ag} (hg/ag er
    None for uspilte/ikke fullførte kamper). Datoer konverteres fra UTC til
    norsk lokaltid."""
    events = {}
    for i, (tid, name) in enumerate(TEAM_ID_TO_NAME.items()):
        for suffix in ("", "?fixture=true"):
            cache_file = cache_dir and (cache_dir / f"{tid}{'_fx' if suffix else ''}.json")
            if cache_file and cache_file.exists():
                d = json.loads(cache_file.read_text(encoding="utf-8"))
                log(f"[espn {i+1}/16] {name}{' (fixture)' if suffix else ''}: fra lokal cache")
            else:
                url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{LEAGUE}/teams/{tid}/schedule{suffix}"
                log(f"[espn {i+1}/16] Henter {name}{' (fixture)' if suffix else ''} ...")
                d = get_json(url)
                if cache_file:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(d), encoding="utf-8")
                time.sleep(REQUEST_DELAY)
            for e in d.get("events", []):
                events[e["id"]] = e

    out = []
    for e in events.values():
        comp = e["competitions"][0]
        utc_dt = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        date = utc_dt.astimezone(OSLO).strftime("%Y-%m-%d")
        completed = comp["status"]["type"]["completed"]
        home = away = hg = ag = None
        winner_home = winner_away = False
        for c in comp["competitors"]:
            name = TEAM_ID_TO_NAME.get(c["team"]["id"])
            if name is None:
                continue  # kamp mot lag utenfor Eliteserien (bør ikke skje for nor.1)
            score = c.get("score")
            v = score.get("value") if isinstance(score, dict) else None
            if c["homeAway"] == "home":
                home, hg, winner_home = name, v, bool(c.get("winner"))
            else:
                away, ag, winner_away = name, v, bool(c.get("winner"))
        if not (home and away):
            continue
        if completed and hg is not None and ag is not None:
            # Selvmotsigende data sett i praksis: 0-0 men en "winner" merket.
            # Slikt forkastes her (ikke None -> spilt, men markert usikkert)
            # og overlates til ffksupporter.net i update_data.py.
            suspect = (hg == 0 and ag == 0) and (winner_home or winner_away)
            out.append({"home": home, "away": away, "date": date,
                        "hg": int(hg), "ag": int(ag), "suspect": suspect})
        else:
            out.append({"home": home, "away": away, "date": date, "hg": None, "ag": None, "suspect": False})
    return out


if __name__ == "__main__":
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = fetch_all(cache_dir=cache, log=lambda s: print(s, file=sys.stderr))
    played = sum(1 for r in rows if r["hg"] is not None)
    suspect = [r for r in rows if r.get("suspect")]
    print(f"Kamper: {len(rows)} ({played} spilt)", file=sys.stderr)
    if suspect:
        print(f"MISTENKELIGE ({len(suspect)}): 0-0 men med vinner merket:", file=sys.stderr)
        for r in suspect:
            print(" ", r, file=sys.stderr)
