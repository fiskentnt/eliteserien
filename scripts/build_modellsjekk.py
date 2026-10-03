#!/usr/bin/env python3
"""Bygger modellsjekk-sidene: <liga>/modellsjekk/index.html.

Full dokumentasjon av testene bak sannsynlighetene (Brier-tabellene,
kontrollen med faste kuttpunkter, hva hvert ledd tilfører, tabellen per fase,
log loss for sluttoddsen og metoden), og treffsikkerheten denne sesongen med
tabellene. Kortversjonen står under "Vis detaljer" i "Hvordan vet vi at
modellen virker?" på ligasiden, med lenken "Full dokumentasjon av testene"
hit. Flyttet dit fra ligasiden 3.10.2026.

Kildene:
  modellsjekk/<liga>.html        innholdet
  modellsjekk/treffsikkerhet.js  tabellene for denne sesongen (accuracy.json)
  <liga>/index.html              stilarket, temaskriptet, besøkstellingen og
                                 fontene, så siden ser ut som ligasiden og
                                 følger det lagrede temaet

obos/index.html bygges av build_league.py først (stilarket hentes derfra).

Bruk (fra repo-roten):
  python3 scripts/build_modellsjekk.py           bygg begge
  python3 scripts/build_modellsjekk.py --check   exit 1 hvis en side er utdatert
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIGAER = {"eliteserien": "Eliteserien", "obos": "OBOS-ligaen"}

EKSTRA_CSS = """
  /* Modellsjekk-siden (scripts/build_modellsjekk.py). */
  .doc{max-width:900px;margin:0 auto;padding:20px 24px 40px}
  .doc-top{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:0 0 12px;font:600 14px/1.3 var(--body);color:var(--muted)}
  .doc a{color:var(--ink);text-decoration:underline;text-underline-offset:2px}
  .doc .in{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 22px 20px}
  .doc h1{font:800 28px/1.1 var(--cond);margin:14px 0 10px}
  .doc h2{font:700 20px/1.15 var(--cond);margin:26px 0 8px}
  .doc h3{font:700 16px/1.25 var(--cond);margin:18px 0 8px}
  .doc p,.doc li{font-size:14px;line-height:1.55;color:var(--ink);max-width:72ch}
  .doc p{margin:0 0 12px}
  .doc .note{padding:0 0 12px;font-size:13px;color:var(--muted)}
  .doc .plain-lead{font-size:16.5px}
  .doc ul{margin:0 0 12px;padding-left:20px}
  .doc .tblscroll{margin:0 0 10px}
  .doc .tilbake{margin-top:26px}
  .doc code{font-size:12.5px;overflow-wrap:anywhere}
  /* Effekt-kolonnen i ablasjonstabellen brytes i stedet for å gå ut til høyre
     (på telefon er tabellen kort per rad, se table.mt.ablation i ligasiden). */
  @media (min-width:641px){.doc table.mt.ablation td:last-child{white-space:normal;min-width:16em}}
  @media (max-width:640px){.doc{padding:12px 12px 32px}.doc .in{padding:4px 14px 16px}.doc h1{font-size:24px}}
"""


def _ett(mønster, tekst, hva):
    m = re.search(mønster, tekst, re.S)
    if not m:
        raise SystemExit(f"build_modellsjekk: fant ikke {hva} i ligasiden")
    return m.group(0)


def render(liga):
    navn = LIGAER[liga]
    side = (ROOT / liga / "index.html").read_text(encoding="utf-8")
    tema = _ett(r"<script>\n// Kjøres synkront i <head>.*?</script>", side, "temaskriptet")
    telling = _ett(r"<!-- Besøksstatistikk.*?</script>", side, "besøkstellingen")
    fonter = _ett(r'<link rel="preconnect" href="https://fonts.googleapis.com">.*?rel="stylesheet">', side, "fontene")
    stil = _ett(r"<style>.*?</style>", side, "stilarket")
    stil = stil[:-len("</style>")] + EKSTRA_CSS + "</style>"
    innhold = (ROOT / "modellsjekk" / f"{liga}.html").read_text(encoding="utf-8").strip()
    js = (ROOT / "modellsjekk" / "treffsikkerhet.js").read_text(encoding="utf-8").strip()
    url = f"https://tabellkalkulator.no/{liga}/modellsjekk/"
    beskrivelse = (f"Full dokumentasjon av testene bak sannsynlighetene for {navn}: Brier-score, "
                   f"kontroll med faste kuttpunkter, hva hvert ledd tilfører, sluttoddsen og "
                   f"treffsikkerheten denne sesongen.")
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
<meta charset="utf-8">
<!-- BYGGET av scripts/build_modellsjekk.py fra modellsjekk/{liga}.html og
     {liga}/index.html. Ikke rediger her: endre kildene og bygg på nytt. -->
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Modellsjekk: {navn} | Tabellkalkulator</title>
<meta name="description" content="{beskrivelse}">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#13305f">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" type="image/png" sizes="32x32">
<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
{tema}
{telling}
{fonter}
{stil}
</head>
<body>
<main class="doc">
<nav class="doc-top"><a href="/">Tabellkalkulator</a><span>/</span><a href="../">{navn}</a><span>/</span><span>Modellsjekk</span></nav>
<article class="in">
{innhold}
</article>
</main>
<script>
{js}
</script>
</body>
</html>
"""


def main(argv):
    sjekk = "--check" in argv
    utdatert = []
    for liga in LIGAER:
        ut = ROOT / liga / "modellsjekk" / "index.html"
        ny = render(liga)
        if sjekk:
            if not ut.exists() or ut.read_text(encoding="utf-8") != ny:
                utdatert.append(str(ut.relative_to(ROOT)))
            continue
        ut.parent.mkdir(parents=True, exist_ok=True)
        ut.write_text(ny, encoding="utf-8")
        print(f"Skrev {ut.relative_to(ROOT)} ({len(ny)} tegn)")
    if utdatert:
        print("Utdatert, kjør python3 scripts/build_modellsjekk.py: " + ", ".join(utdatert))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
