"""Delt mellom fetch_odds_history.py og fetch_odds_upcoming.py."""
import math


def devig(h, d, a):
    """Fjerner bookmakerens margin med Shins metode (Shin 1993), i stedet for
    å skalere alle tre inverse oddsene forholdsvis like mye (normering).
    Štrumbelj (2014) fant i sin sammenligning at Shin samlet sett ga bedre
    resultater enn enkel normalisering og regresjonsmetodene som ble
    undersøkt. Tatt i bruk 1. oktober 2026.

    Med q_i = 1/odds_i og Q = sum(q_i) er Shin-sannsynligheten
        p_i(z) = (sqrt(z^2 + 4 (1 - z) q_i^2 / Q) - z) / (2 (1 - z)),
    og z (andelen innsidere) er verdien som gjør at p_i summerer til 1. Summen
    synker når z øker, så z finnes ved halvering. Bare standardbiblioteket:
    skriptet kjører også der numpy og scipy ikke er installert. Er det ingen
    margin (Q <= 1), finnes ingen slik z, og da normeres det som før."""
    q = (1 / h, 1 / d, 1 / a)
    Q = sum(q)
    if Q <= 1.0:
        return tuple(x / Q for x in q)

    def shin(z):
        return [(math.sqrt(z * z + 4 * (1 - z) * x * x / Q) - z) / (2 * (1 - z)) for x in q]

    lo, hi = 0.0, 0.5
    while sum(shin(hi)) > 1.0 and hi < 0.999:
        hi = min(0.999, hi * 1.5)
    for _ in range(100):
        mid = (lo + hi) / 2
        if sum(shin(mid)) > 1.0:
            lo = mid
        else:
            hi = mid
    p = shin((lo + hi) / 2)
    s = sum(p)
    return tuple(x / s for x in p)


def devig_normering(h, d, a):
    """Den gamle marginfjerningen (i bruk til 1. oktober 2026): skalerer de
    inverse oddsene forholdsvis like mye, så de summerer til 1. Beholdt for
    sammenligninger, ikke brukt i produksjonen."""
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
