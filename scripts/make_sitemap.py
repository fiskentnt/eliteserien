#!/usr/bin/env python3
"""Lager sitemap.xml: forsiden og en side per liga.

En liga er en mappe i repoet med både index.html og data/matches.json
(eliteserien/ og obos/). Nye ligaer plukkes derfor opp uten at dette scriptet
må endres. lastmod for en liga er når tabellen og sjansene sist ble regnet
(laget i data/grunnlag.json, med klokkeslett), for da skriver
scripts/lag_grunnlag.js også den statiske tabellen i siden: lastmod følger
hver dataendring (20.10.2026). Før var det datoen for siste spilte kamp, og
den endret seg ikke med odds og flyttede kamper. Uten grunnlagsfil: datoen for
siste spilte kamp. Forsiden har ingen lastmod (den er valgfri) siden den ikke
endrer seg med dataene.

Spørsmålssidene (fase 2, scripts/lag_sider.py SPORSMAL, for eksempel
/eliteserien/hvem-vinner/) er med, med samme lastmod som ligaen: de lages fra
de samme tallene.

Kjøres av grunnlag-workflowen via scripts/push_sitemap.sh, etter at
grunnlagsfilen og siden er pushet.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lag_sider import SPORSMAL  # noqa: E402

ROOT = Path(__file__).parent.parent
BASE = "https://tabellkalkulator.no"


def leagues():
    out = []
    for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        matches = d / "data" / "matches.json"
        if (d / "index.html").exists() and matches.exists():
            grunnlag = d / "data" / "grunnlag.json"
            laget = json.loads(grunnlag.read_text(encoding="utf-8")).get("laget") if grunnlag.exists() else None
            if laget:
                out.append((d.name, laget.replace("Z", "+00:00")))
                continue
            data = json.loads(matches.read_text(encoding="utf-8"))
            last = max((m["date"] for m in data), default=None)
            out.append((d.name, last))
    return out


def main():
    urls = [f"  <url><loc>{BASE}/</loc></url>"]
    for name, last in leagues():
        lm = f"<lastmod>{last}</lastmod>" if last else ""
        urls.append(f"  <url><loc>{BASE}/{name}/</loc>{lm}</url>")
        for sti, _ in SPORSMAL.get(name, []):
            if (ROOT / name / sti / "index.html").exists():
                urls.append(f"  <url><loc>{BASE}/{name}/{sti}/</loc>{lm}</url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(urls) + "\n</urlset>\n")
    (ROOT / "sitemap.xml").write_text(xml, encoding="utf-8")
    print("Skrev sitemap.xml med", len(urls), "adresser.")


if __name__ == "__main__":
    main()
