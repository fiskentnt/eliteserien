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
from pathlib import Path

USER_AGENT = "eliteserien-tabell (+https://github.com/fiskentnt/eliteserien)"
CSV_URL = "https://football-data.co.uk/new/NOR.csv"
ROOT = Path(__file__).parent.parent
OUT_PATH = ROOT / "data" / "odds_fd.json"

NAME_MAP = {"Bodo/Glimt": "Bodø/Glimt", "Lillestrom": "Lillestrøm",
            "Tromso": "Tromsø", "Valerenga": "Vålerenga"}
def norm(name): return NAME_MAP.get(name, name)

def devig(h, d, a):
    ih, idn, ia = 1/h, 1/d, 1/a
    s = ih + idn + ia
    return ih/s, idn/s, ia/s

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
        raise

def parse(csv_text):
    rows = [r for r in csv.DictReader(io.StringIO(csv_text)) if r.get("Season") == "2026"
            and r.get("League") == "Eliteserien"]
    out = []
    for r in rows:
        dd, mm, yy = r["Date"].split("/")
        date = f"{yy}-{mm}-{dd}"
        home, away = norm(r["Home"]), norm(r["Away"])
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
    return out

def main():
    log = lambda s: print(s, file=sys.stderr)
    existing = {"etag": None, "matches": []}
    if OUT_PATH.exists():
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    try:
        csv_text, new_etag = fetch(etag=existing.get("etag"), log=log)
    except Exception as e:
        log(f"ADVARSEL: klarte ikke hente odds-CSV ({e}), beholder eksisterende data/odds_fd.json")
        return

    if csv_text is None:
        log(f"data/odds_fd.json uendret ({len(existing['matches'])} kamper).")
        return

    matches = parse(csv_text)
    if len(matches) < len(existing["matches"]):
        log(f"ADVARSEL: ny CSV ga færre kamper ({len(matches)}) enn eksisterende data ({len(existing['matches'])}) "
            "— beholder eksisterende data/odds_fd.json uendret.")
        return

    bfe = sum(1 for m in matches if m["src"] == "BFE")
    log(f"Hentet {len(matches)} kamper med sluttodds ({bfe} BFE, {len(matches)-bfe} AvgC).")
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps({"etag": new_etag, "matches": matches}, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

if __name__ == "__main__":
    main()
