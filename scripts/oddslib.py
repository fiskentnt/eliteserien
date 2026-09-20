"""Delt mellom fetch_odds_history.py og fetch_odds_upcoming.py."""


def devig(h, d, a):
    """Proporsjonal de-vigging: fjerner bookmakerens overround ved å skalere
    de inverse oddsene (implisitte sannsynlighetene) slik at de summerer til 1."""
    ih, idn, ia = 1 / h, 1 / d, 1 / a
    s = ih + idn + ia
    return ih / s, idn / s, ia / s
