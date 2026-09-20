"""Henter sluttodds for spilte 2026-kamper fra football-data.co.uk.

BFE (Betfair Exchange sluttodds) er hovedkilde, AvgC (snitt sluttodds) er
reserve der BFE mangler. Henter CSV-en betinget (If-None-Match mot lagret
ETag) — én forespørsel per kjøring, og bare bearbeidet på nytt hvis filen
faktisk er endret. Skriver aldri over gode data med tomme: hvis noe feiler
eller gir færre kamper enn det som allerede ligger i data/odds_fd.json, beholdes
den eksisterende filen uendret.
"""
import csv
import io
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from oddslib import devig, CANONICAL_TEAMS, UnmappedTeamError

USER_AGENT = "eliteserien-tabell (+https://github.com/fiskentnt/eliteserien)"
CSV_URL = "https://football-data.co.uk/new/NOR.csv"
ROOT = Path(__file__).parent.parent
OUT_PATH = ROOT / "data" / "odds_fd.json"
CAPTURED_PATH = ROOT / "data" / "odds_captured.json"
OSLO = ZoneInfo("Europe/Oslo")


class RateLimited(Exception):
    """429/403 -- ikke prøv igjen med en gang, vent til neste planlagte sjekk (i morgen)."""
    def __init__(self, code):
        self.code = code
        super().__init__(f"football-data.co.uk svarte {code}")

NAME_MAP = {"Bodo/Glimt": "Bodø/Glimt", "Lillestrom": "Lillestrøm",
            "Tromso": "Tromsø", "Valerenga": "Vålerenga"}
def norm(name): return NAME_MAP.get(name, name)
def is_known(name): return name in NAME_MAP or name in CANONICAL_TEAMS

def fetch(etag=None, log=lambda s: None):
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": USER_AGENT})
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8-sig"), resp.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            log("Ikke endret siden sist (304).")
            return None, etag
        if e.code in (429, 403):
            raise RateLimited(e.code) from e
        raise

def parse(csv_text, captured_matches=(), log=lambda s: None):
    # Hver rad her ER en ferdigspilt kamp (CSV-en har bare resultater), så det
    # "allerede spilt"-vilkåret er alltid oppfylt for et ukjent lagnavn. Det
    # eneste spørsmålet er om kampen ALLEREDE har odds fra reserve-kilden
    # (data/odds_captured.json, The Odds API) -- da nedgraderes det ukjente
    # navnet til en advarsel (vi mister ikke reell kalibreringsdata), ellers
    # feiler kjøringen (samme mønster som EspnDataError i espn_source.py).
    # Krysssjekken bruker den GJENKJENTE siden av kampen (dato + det andre
    # lagnavnet) -- er BEGGE navn ukjente samtidig kan vi ikke bekrefte
    # reserven finnes, og det er da alltid en feil.
    captured_by_date = {}
    for cm in captured_matches:
        captured_by_date.setdefault(cm["date"], []).append(cm)

    rows = [r for r in csv.DictReader(io.StringIO(csv_text)) if r.get("Season") == "2026"
            and r.get("League") == "Eliteserien"]
    out = []
    problems = []
    for r in rows:
        dd, mm, yy = r["Date"].split("/")
        date = f"{yy}-{mm}-{dd}"
        raw_home, raw_away = r["Home"], r["Away"]
        home_known, away_known = is_known(raw_home), is_known(raw_away)
        if not (home_known and away_known):
            bad = raw_home if not home_known else raw_away
            known_side = norm(raw_away) if not home_known and away_known else (norm(raw_home) if not away_known and home_known else None)
            has_reserve = known_side is not None and any(
                known_side in (cm["home"], cm["away"]) for cm in captured_by_date.get(date, [])
            )
            msg = f"ukjent lagnavn {bad!r} ({raw_home}-{raw_away}, {date})"
            if has_reserve:
                log(f"ADVARSEL: {msg} -- men The Odds API har allerede odds for denne kampen, hopper over raden")
            else:
                problems.append(msg)
            continue
        home, away = norm(raw_home), norm(raw_away)
        if r.get("BFECH", "").strip():
            h, d, a = devig(float(r["BFECH"]), float(r["BFECD"]), float(r["BFECA"]))
            src = "BFE"
        elif r.get("AvgCH", "").strip():
            h, d, a = devig(float(r["AvgCH"]), float(r["AvgCD"]), float(r["AvgCA"]))
            src = "AvgC"
        else:
            continue
        out.append({"date": date, "home": home, "away": away, "H": round(h, 4),
                     "D": round(d, 4), "A": round(a, 4), "src": src})
    if problems:
        raise UnmappedTeamError(
            f"{len(problems)} kamp(er) fra football-data.co.uk har lagnavn som ikke finnes i NAME_MAP, "
            "og har ingen odds fra The Odds API som reserve:\n" +
            "\n".join(f"  - {p}" for p in problems)
        )
    return out

def main(force=False):
    log = lambda s: print(s, file=sys.stderr)
    existing = {"etag": None, "matches": [], "checked_date": None}
    if OUT_PATH.exists():
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    today_oslo = datetime.now(timezone.utc).astimezone(OSLO).strftime("%Y-%m-%d")
    if not force and existing.get("checked_date") == today_oslo:
        log(f"Allerede sjekket football-data.co.uk i dag ({today_oslo}), maks én gang i døgnet -- hopper over.")
        return

    try:
        csv_text, new_etag = fetch(etag=existing.get("etag"), log=log)
    except RateLimited as e:
        log(f"ADVARSEL: {e} -- venter til neste planlagte sjekk (i morgen kl 06), beholder eksisterende data/odds_fd.json")
        existing["checked_date"] = today_oslo  # ikke prøv igjen før i morgen selv om andre kjøringer skjer i dag
        OUT_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    except Exception as e:
        log(f"ADVARSEL: klarte ikke hente odds-CSV ({e}), beholder eksisterende data/odds_fd.json")
        return

    if csv_text is None:
        existing["checked_date"] = today_oslo
        OUT_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"data/odds_fd.json uendret ({len(existing['matches'])} kamper).")
        return

    captured_matches = []
    if CAPTURED_PATH.exists():
        captured_matches = json.loads(CAPTURED_PATH.read_text(encoding="utf-8")).get("matches", [])
    matches = parse(csv_text, captured_matches, log)
    if len(matches) < len(existing["matches"]):
        log(f"ADVARSEL: ny CSV ga færre kamper ({len(matches)}) enn eksisterende data ({len(existing['matches'])}) "
            "— beholder eksisterende data/odds_fd.json uendret.")
        return

    bfe = sum(1 for m in matches if m["src"] == "BFE")
    log(f"Hentet {len(matches)} kamper med sluttodds ({bfe} BFE, {len(matches)-bfe} AvgC).")
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps({"etag": new_etag, "checked_date": today_oslo, "matches": matches},
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
