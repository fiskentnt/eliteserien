"""Ligaoppsett, delt av de to offisielle kildene.

Eliteserien og OBOS-ligaen håndteres uavhengig overalt. At neste sesong er
klar i den ene ligaen skal aldri blokkere den andre, så all konfigurasjon er
per liga og ingen kode deler tilstand mellom dem.

Navnene: begge offisielle kilder bruker de samme lagnavnene, og de avviker
fra våre på tre lag til sammen. Kartet går fra kildens navn til vårt.
"""

ELITESERIEN = "eliteserien"
OBOS = "obos"

LIGAER = {
    ELITESERIEN: {
        "visningsnavn": "Eliteserien",
        # Norsk Toppfotball sine ligasider (hovedkilde)
        "ntf_base": "https://www.eliteserien.no",
        "ntf_liga_alt": "Eliteserien",
        # NFF sin turneringsdatabase (uavhengig offisiell kontroll)
        "nff_url": "https://www.fotball.no/turneringer/eliteserien/",
        "navn": {
            "KFUM": "KFUM Oslo",
            "Sandefjord Fotball": "Sandefjord",
        },
        "lag": {
            "Aalesund", "Bodø/Glimt", "Brann", "Fredrikstad", "HamKam", "KFUM Oslo",
            "Kristiansund", "Lillestrøm", "Molde", "Rosenborg", "Sandefjord",
            "Sarpsborg 08", "Start", "Tromsø", "Viking", "Vålerenga",
        },
        "data": "eliteserien/data",
    },
    OBOS: {
        "visningsnavn": "OBOS-ligaen",
        "ntf_base": "https://www.obos-ligaen.no",
        "ntf_liga_alt": "OBOS-ligaen",
        "nff_url": "https://www.fotball.no/turneringer/obosligaen/",
        "navn": {
            "Ranheim TF": "Ranheim",
        },
        "lag": {
            "Bryne", "Egersund", "Haugesund", "Hødd", "Kongsvinger", "Lyn", "Moss",
            "Odd", "Ranheim", "Raufoss", "Sandnes Ulf", "Sogndal", "Stabæk",
            "Strømmen", "Strømsgodset", "Åsane",
        },
        "data": "obos/data",
    },
}

# 16 lag, dobbel serie: 16 * 15 = 240 kamper, 30 runder.
ANTALL_LAG = 16
ANTALL_KAMPER = ANTALL_LAG * (ANTALL_LAG - 1)
ANTALL_RUNDER = (ANTALL_LAG - 1) * 2


def oppsett(liga):
    if liga not in LIGAER:
        raise KeyError(f"ukjent liga: {liga!r} (kjenner {sorted(LIGAER)})")
    return LIGAER[liga]
