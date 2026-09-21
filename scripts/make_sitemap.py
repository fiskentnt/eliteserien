#!/usr/bin/env python3
"""Lager sitemap.xml: forsiden og en side per liga.

En liga er en mappe i repoet med både index.html og data/matches.json (i dag
bare eliteserien/). Nye ligaer plukkes derfor opp uten at dette scriptet må
endres. lastmod for en liga er datoen for siste spilte kamp i kampdataene, så
den bare endrer seg når noe faktisk har skjedd. Forsiden har ingen lastmod
(den er valgfri) siden den ikke endrer seg med dataene.
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
BASE = "https://tabellkalkulator.no"


def leagues():
    out = []
    for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        matches = d / "data" / "matches.json"
        if (d / "index.html").exists() and matches.exists():
            data = json.loads(matches.read_text(encoding="utf-8"))
            last = max((m["date"] for m in data), default=None)
            out.append((d.name, last))
    return out


def main():
    urls = [f"  <url><loc>{BASE}/</loc></url>"]
    for name, last in leagues():
        lm = f"<lastmod>{last}</lastmod>" if last else ""
        urls.append(f"  <url><loc>{BASE}/{name}/</loc>{lm}</url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(urls) + "\n</urlset>\n")
    (ROOT / "sitemap.xml").write_text(xml, encoding="utf-8")
    print("Skrev sitemap.xml med", len(urls), "adresser.")


if __name__ == "__main__":
    main()
