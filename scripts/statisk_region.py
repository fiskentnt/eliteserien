"""Regionene STATISK-* i ligasidene (20.10.2026).

scripts/lag_grunnlag.js skriver dem i grunnlag-workflowen, fra siden selv i
Chrome med den nye grunnlagsfilen: overskriftene for sjansene
(STATISK-KOLONNER), når det ble regnet (STATISK-OPPDATERT) og radene i tabellen
med tall og sjanser (STATISK-TABELL). Da står tabellen i HTML-en for
søkemotorer og uten JavaScript.

  build_league.py  beholder regionene fra den eksisterende ligasiden, så
                   OBOS-siden ikke får Eliteserien-sidens tabell
  grunnlag_port.py ser bort fra innholdet, så en skrevet tabell ikke regnes som
                   endret kode og starter grunnlag på nytt
"""
import re

STATISK_RE = re.compile(r"(<!-- STATISK-([A-Z]+) -->)(.*?)(<!-- /STATISK-\2 -->)", re.S)


def statiske(tekst):
    """Innholdet i hver region, etter navn."""
    return {m.group(2): m.group(3) for m in STATISK_RE.finditer(tekst)}


def med_statiske(tekst, regioner):
    """Teksten med regionenes innhold byttet ut (tomt for regioner som mangler)."""
    return STATISK_RE.sub(lambda m: m.group(1) + regioner.get(m.group(2), "") + m.group(4), tekst)


def uten_statisk(tekst):
    """Teksten med alle regionene tomme."""
    return med_statiske(tekst, {})
