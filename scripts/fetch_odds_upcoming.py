"""Henter odds for kommende Eliteserien-kamper fra The Odds API.

Skriver data/odds_upcoming.json (levende snapshot, brukt direkte i index.html
for kommende kamper) og bygger data/odds_captured.json — vår egen historikk av
siste odds før avspark, fanget opp automatisk når en kamp går fra "kommende"
til "spilt" mellom to kjøringer. odds_captured.json er reserve-kilden for
kalibrering når football-data.co.uk ikke har lagt ut sluttodds for kampen
ennå (se merge_odds.py).

Nøkkel: ODDS_API_KEY (miljøvariabel, satt fra secrets i workflowen / .env lokalt).
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oddslib import devig, UnmappedTeamError

USER_AGENT = "eliteserien-tabell (+https://github.com/fiskentnt/eliteserien)"
SPORT = "soccer_norway_eliteserien"
BASE = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/"
ROOT = Path(__file__).parent.parent
LEAGUE = ROOT / "eliteserien"  # ligamappen (data/ ligger under den, så flere ligaer kan komme ved siden av)
UPCOMING_PATH = LEAGUE / "data" / "odds_upcoming.json"
CAPTURED_PATH = LEAGUE / "data" / "odds_captured.json"
MATCHES_PATH = LEAGUE / "data" / "matches.json"
QUOTA_PATH = LEAGUE / "data" / "odds_quota.json"
QUOTA_FLOOR = 100  # under denne mengden kreditter igjen: stopp til neste måned


class RateLimited(Exception):
    """429/403 -- ikke prøv igjen med en gang, vent til neste planlagte kjøring."""
    def __init__(self, code):
        self.code = code
        super().__init__(f"The Odds API svarte {code}")

# The Odds API sine lagnavn -> navnene i index.html (fra /v4/sports/.../participants)
NAME_MAP = {
    "Aalesund": "Aalesund", "Bodø/Glimt": "Bodø/Glimt", "Fredrikstad FK": "Fredrikstad",
    "HamKam": "HamKam", "IK Start": "Start", "KFUM": "KFUM Oslo",
    "Kristiansund BK": "Kristiansund", "Lillestrom": "Lillestrøm", "Molde": "Molde",
    "Rosenborg": "Rosenborg", "SK Brann": "Brann", "Sandefjord": "Sandefjord",
    "Sarpsborg FK": "Sarpsborg 08", "Tromso": "Tromsø", "Vålerenga": "Vålerenga",
    "Viking FK": "Viking",
}

def fetch_odds(api_key, log):
    url = f"{BASE}?apiKey={api_key}&regions=eu&markets=h2h&oddsFormat=decimal"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            remaining = resp.headers.get("x-requests-remaining")
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            raise RateLimited(e.code) from e
        raise
    log(f"The Odds API: {len(data)} kamper, {remaining} kreditter igjen denne måneden.")
    record_quota(remaining, log)
    return data


def record_quota(remaining, log):
    """Logger x-requests-remaining hver kjøring. Under QUOTA_FLOOR: stopp
    videre henting til kalendermåneden skifter (kvoten fornyes månedlig), og
    la index.html vise "Odds ikke oppdatert" i tooltip mens vi venter."""
    now = datetime.now(timezone.utc)
    data = {"remaining": int(remaining) if remaining is not None else None,
            "checked_at": now.isoformat(timespec="seconds")}
    if remaining is not None and int(remaining) < QUOTA_FLOOR:
        data["stopped_until_month"] = now.strftime("%Y-%m")
        log(f"ADVARSEL: bare {remaining} kreditter igjen (under {QUOTA_FLOOR}) -- stopper oddshenting til neste måned.")
    QUOTA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def parse(raw):
    # Ethvert ukjent lagnavn her gjelder per definisjon en IKKE spilt kamp --
    # endepunktet returnerer bare kommende/pågående kamper, aldri ferdigspilte
    # -- så det finnes ingen "har allerede odds fra en annen kilde"-unntak å
    # nedgradere til (i motsetning til fetch_odds_history.py, der CSV-en bare
    # inneholder ferdigspilte kamper). Feiler alltid kjøringen, samme mønster
    # som EspnDataError i espn_source.py.
    out = []
    problems = []
    for m in raw:
        home = NAME_MAP.get(m["home_team"])
        away = NAME_MAP.get(m["away_team"])
        if not home or not away:
            bad = m["home_team"] if not home else m["away_team"]
            problems.append(f"ukjent lagnavn {bad!r} ({m['home_team']}-{m['away_team']}, {m.get('commence_time','?')})")
            continue
        H, D, A, n = [], [], [], 0
        for bm in m["bookmakers"]:
            mk = next((x for x in bm["markets"] if x["key"] == "h2h"), None)
            if not mk:
                continue
            outc = {o["name"]: o["price"] for o in mk["outcomes"]}
            if m["home_team"] in outc and m["away_team"] in outc and "Draw" in outc:
                H.append(outc[m["home_team"]]); D.append(outc["Draw"]); A.append(outc[m["away_team"]])
                n += 1
        if n == 0:
            continue
        avgH, avgD, avgA = sum(H)/n, sum(D)/n, sum(A)/n
        h, d, a = devig(avgH, avgD, avgA)
        out.append({
            "home": home, "away": away, "commence_time": m["commence_time"],
            "H": round(h, 4), "D": round(d, 4), "A": round(a, 4), "n_bookmakers": n,
        })
    if problems:
        raise UnmappedTeamError(
            f"{len(problems)} kamp(er) fra The Odds API har lagnavn som ikke finnes i NAME_MAP:\n" +
            "\n".join(f"  - {p}" for p in problems)
        )
    return out

def main():
    log = lambda s: print(s, file=sys.stderr)
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        log("ADVARSEL: ODDS_API_KEY er ikke satt, hopper over henting.")
        return

    existing_upcoming = json.loads(UPCOMING_PATH.read_text(encoding="utf-8")) if UPCOMING_PATH.exists() else {"matches": []}
    captured = json.loads(CAPTURED_PATH.read_text(encoding="utf-8")) if CAPTURED_PATH.exists() else {"matches": []}
    played_keys = set()
    if MATCHES_PATH.exists():
        played = json.loads(MATCHES_PATH.read_text(encoding="utf-8"))
        played_keys = {(m["home"], m["away"]) for m in played}

    # Fang opp siste kjente odds for kamper som har gått fra "kommende" til "spilt"
    # siden forrige kjøring, inn i vår egen historikk.
    captured_keys = {(m["home"], m["away"]) for m in captured["matches"]}
    newly_captured = 0
    for m in existing_upcoming.get("matches", []):
        key = (m["home"], m["away"])
        if key in played_keys and key not in captured_keys:
            captured["matches"].append({k: v for k, v in m.items() if k != "commence_time"} | {"date": m["commence_time"][:10]})
            newly_captured += 1
    if newly_captured:
        log(f"Fanget opp siste odds før avspark for {newly_captured} nylig spilte kamper.")
        CAPTURED_PATH.parent.mkdir(exist_ok=True)
        CAPTURED_PATH.write_text(json.dumps(captured, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Spilte kamper skal ut av "kommende", uansett hva hentingen gjør. Klarte
    # den ikke å hente, ble filen før liggende urørt, og en spilt kamp ble
    # stående som kommende i dagevis (Brann mot Bodø/Glimt 20. september).
    # Oddsen for den er alt tatt vare på i odds_captured.json over.
    def uten_spilte(d):
        beholdt = [m for m in d.get("matches", []) if (m["home"], m["away"]) not in played_keys]
        fjernet = len(d.get("matches", [])) - len(beholdt)
        if fjernet:
            log(f"Ryddet ut {fjernet} spilte kamper fra data/odds_upcoming.json.")
        return beholdt, fjernet

    try:
        raw = fetch_odds(api_key, log)
    except Exception as e:
        log(f"ADVARSEL: klarte ikke hente fra The Odds API ({e}), beholder eksisterende data/odds_upcoming.json")
        beholdt, fjernet = uten_spilte(existing_upcoming)
        if fjernet:
            UPCOMING_PATH.write_text(json.dumps({
                "fetched_at": existing_upcoming.get("fetched_at"),
                "matches": beholdt,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return

    matches = parse(raw)
    # Et svar kan inneholde en kamp som alt er spilt; den hører ikke hjemme her.
    matches = [m for m in matches if (m["home"], m["away"]) not in played_keys]
    # Ikke overskriv gode data med tomme, med mindre alle de gamle kampene nå er spilt
    # (da er en tom liste riktig, ikke en feil).
    old_still_unplayed, fjernet = uten_spilte(existing_upcoming)
    if not matches and old_still_unplayed:
        log("ADVARSEL: The Odds API ga 0 kamper, men det finnes fortsatt uspilte kamper vi hadde odds for — beholder eksisterende data.")
        if fjernet:
            UPCOMING_PATH.write_text(json.dumps({
                "fetched_at": existing_upcoming.get("fetched_at"),
                "matches": old_still_unplayed,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return

    UPCOMING_PATH.parent.mkdir(exist_ok=True)
    UPCOMING_PATH.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "matches": matches,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"Skrev {len(matches)} kommende kamper med odds til data/odds_upcoming.json.")

if __name__ == "__main__":
    main()
