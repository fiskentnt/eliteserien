"""Slår sammen oddskildene til data/odds.json, som fit_model.py kalibrerer på.

Rekkefølgen, best først:

  1. data/odds_closing.json -- OddsPapi, siste observasjon 60 til 15 minutter
     før avspark (se scripts/oddswindow.py). Den eneste kilden der vi vet
     NÅR prisen ble satt, og derfor kan stå inne for at laguttaket er med.
     Målt på 351 kamper traff odds fra dagen før 2,0 standardfeil dårligere.
  2. data/odds_fd.json -- football-data.co.uk. Snitt over mange bookmakere,
     uten tidsstempel. Reserve der vinduet er tomt, og eneste kilde for
     sesongene før OddsPapi.
  3. data/odds_captured.json -- vår egen historikk fra The Odds API, hentet
     på faste klokkeslett. Siste utvei.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
LEAGUE = ROOT / "eliteserien"  # ligamappen (data/ ligger under den, så flere ligaer kan komme ved siden av)
OUT_PATH = LEAGUE / "data" / "odds.json"

def load(name):
    p = LEAGUE / "data" / name
    return json.loads(p.read_text(encoding="utf-8"))["matches"] if p.exists() else []

def load_window():
    """Sluttodds fra OddsPapi-vinduet, i samme form som de andre kildene.

    Kamper uten pris i vinduet står i filen med bookmaker null. De hoppes
    over her, så de faller ned på football-data -- de skal ALDRI bæres videre
    med en eldre pris under navnet sluttodds.
    """
    p = LEAGUE / "data" / "odds_closing.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    ut = []
    for key, v in d.get("matches", {}).items():
        if not v.get("bookmaker") or v.get("H") is None:
            continue
        parts = key.split("|")
        if len(parts) != 3:
            continue
        ut.append({"date": (v.get("start") or "")[:10], "home": parts[1], "away": parts[2],
                   "H": v["H"], "D": v["U"], "A": v["B"],
                   "bookmaker": v["bookmaker"], "minutter_for": v.get("minutter_for")})
    return ut


def main():
    log = lambda s: print(s, file=sys.stderr)
    fd = load("odds_fd.json")
    captured = load("odds_captured.json")
    vindu = load_window()

    by_key = {}
    for m in captured:
        by_key[(m["home"], m["away"])] = {**m, "src": "odds-api"}
    n_fd_override = 0
    for m in fd:
        key = (m["home"], m["away"])
        if key in by_key:
            n_fd_override += 1
        by_key[key] = {**m, "src": "fd"}
    n_vindu_override = 0
    for m in vindu:
        key = (m["home"], m["away"])
        if key in by_key:
            n_vindu_override += 1
        by_key[key] = {**m, "src": "oddspapi-vindu"}

    matches = sorted(by_key.values(), key=lambda m: (m["date"], m["home"]))
    n_fd = sum(1 for m in matches if m["src"] == "fd")
    n_api = sum(1 for m in matches if m["src"] == "odds-api")
    n_win = sum(1 for m in matches if m["src"] == "oddspapi-vindu")
    log(f"Slo sammen {len(matches)} kamper med odds ({n_win} fra OddsPapi-vinduet, "
        f"{n_fd} fra football-data.co.uk, {n_api} fra The Odds API-historikk; "
        f"vinduet overstyrte {n_vindu_override}, fd overstyrte {n_fd_override} api).")

    OUT_PATH.write_text(json.dumps({"matches": matches}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
