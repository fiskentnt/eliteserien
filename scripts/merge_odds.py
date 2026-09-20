"""Slår sammen de to oddskildene til data/odds.json, som brukes av fit_model.py
til kalibrering av modellen. football-data.co.uk (data/odds_fd.json) vinner
alltid ved uenighet; data/odds_captured.json (vår egen historikk fra The Odds
API) er reserve for kamper football-data.co.uk ikke har lagt ut ennå."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT_PATH = ROOT / "data" / "odds.json"

def load(name):
    p = ROOT / "data" / name
    return json.loads(p.read_text(encoding="utf-8"))["matches"] if p.exists() else []

def main():
    log = lambda s: print(s, file=sys.stderr)
    fd = load("odds_fd.json")
    captured = load("odds_captured.json")

    by_key = {}
    for m in captured:
        by_key[(m["home"], m["away"])] = {**m, "src": "odds-api"}
    n_fd_override = 0
    for m in fd:
        key = (m["home"], m["away"])
        if key in by_key:
            n_fd_override += 1
        by_key[key] = {**m, "src": "fd"}

    matches = sorted(by_key.values(), key=lambda m: (m["date"], m["home"]))
    n_fd = sum(1 for m in matches if m["src"] == "fd")
    n_api = sum(1 for m in matches if m["src"] == "odds-api")
    log(f"Slo sammen {len(matches)} kamper med odds ({n_fd} fra football-data.co.uk, "
        f"{n_api} fra The Odds API-historikk, {n_fd_override} der fd overstyrte api).")

    OUT_PATH.write_text(json.dumps({"matches": matches}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
