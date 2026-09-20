"""Delt mellom fetch_odds_history.py og fetch_odds_upcoming.py."""


def devig(h, d, a):
    """Proporsjonal de-vigging: fjerner bookmakerens overround ved å skalere
    de inverse oddsene (implisitte sannsynlighetene) slik at de summerer til 1."""
    ih, idn, ia = 1 / h, 1 / d, 1 / a
    s = ih + idn + ia
    return ih / s, idn / s, ia / s


# De 16 lagnavnene index.html og resten av datapipelinen faktisk bruker (fra
# ESPN_source.py sin TEAM_ID_TO_NAME / ffk_source.py sin SLUG_TO_NAME, som
# begge er immune mot stavevarianter siden de kobler via id/slug, ikke navn).
# Brukt her til å avgjøre om et lagnavn fra en oddskilde (som KOBLER via
# streng-navn, og derfor ER sårbar) er gjenkjent -- se UnmappedTeamError.
CANONICAL_TEAMS = {
    "Aalesund", "Bodø/Glimt", "Brann", "Fredrikstad", "HamKam", "KFUM Oslo",
    "Kristiansund", "Lillestrøm", "Molde", "Rosenborg", "Sandefjord",
    "Sarpsborg 08", "Start", "Tromsø", "Viking", "Vålerenga",
}


class UnmappedTeamError(Exception):
    """Et lagnavn fra en oddskilde (The Odds API eller football-data.co.uk)
    som verken står i kildens egen NAME_MAP eller er et kjent kanonisk
    lagnavn -- samme rolle for oddskildene som EspnDataError har for ESPN i
    espn_source.py: feiler kjøringen tydelig i stedet for å la kampen falle
    stille ut av kalibreringen."""
