#!/usr/bin/env python3
"""Oppdaterer odds for kommende kamper (The Odds API), fanger opp historikk,
slår sammen med football-data.co.uk og tilpasser modellen på nytt.

Kjøres av .github/workflows/update-odds.yml kl. 08 og 16 hver dag.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_odds_upcoming
import merge_odds
import fit_model


def main():
    log = lambda s: print(s, file=sys.stderr)
    log("--- Henter kommende odds (The Odds API) ---")
    fetch_odds_upcoming.main()
    log("--- Slår sammen oddskilder ---")
    merge_odds.main()
    log("--- Tilpasser modellen ---")
    fit_model.main()


if __name__ == "__main__":
    main()
