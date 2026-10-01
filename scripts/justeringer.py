#!/usr/bin/env python3
"""Poengjusteringer fra NFF: <liga>/data/justeringer.json (se notatet i filen).

Delt av scripts/make_og.py og scripts/daglig_revisjon.py. Siden har samme
regel i poengJust (eliteserien/index.html): summen av justeringene for laget
denne sesongen, registrert til og med datoen.
"""
import json
from pathlib import Path


def les(mappe, sesong):
    """Justeringene for sesongen i <mappe>/data/justeringer.json; [] uten fil."""
    p = Path(mappe) / "data" / "justeringer.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return [j for j in d.get("justeringer", []) if int(j.get("sesong", 0)) == int(sesong)]


def per_lag(justeringer, til=None):
    """{lag: sum av poeng} for justeringene registrert til og med til (ISO-dato), eller alle."""
    s = {}
    for j in justeringer:
        if til is None or j["dato"] <= til:
            s[j["lag"]] = s.get(j["lag"], 0) + j["poeng"]
    return s
