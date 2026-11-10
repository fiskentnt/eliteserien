"""Skriftene på sidene (24.10.2026): Barlow og Barlow Condensed fra eget domene.

Før kom de fra Google Fonts med display=swap. Ved første besøk kom de etter at
siden var tegnet første gang, teksten ble tegnet om med ny skrift, tittelen
brøt annerledes, og alt under hoppet (CLS 0,17 til 0,28 på mobil). Nå ligger
de i assets/fonts/ (SIL OFL, assets/fonts/OFL.txt; latin-utsnittet fra Google
Fonts, det samme som Google sendte for norsk tekst). preload henter skriftene
siden bruker straks, og font-display: optional gjør at de bare brukes hvis de
er der til første tegning: ellers står reserveskriften hele besøket, i stedet
for å bytte og flytte teksten.

LIGASIDENE (10.11.2026): font-display: swap med en tilpasset reserveskrift.
Med optional fikk nesten alle reserveskriften: filene brukte 155 til 673 ms
(målt i Chrome, x-cache HIT), mens optional bare venter rundt 100 ms, og
GitHub Pages gir max-age=600 og ny ETag ved hver utrulling (datajobbene ruller
ut hvert tiende minutt). Første besøk og alle besøk etter ti minutter fikk
derfor Arial Narrow og systemskriften, med tall i ulik størrelse og tykkelse.
Med swap byttes skriften når den kommer, og reserveskriften (RESERVE) er Arial
skalert med size-adjust til Barlows bredde, én for sifrene og én for resten
(unicode-range), og med Barlows høyde (ascent 1,00, descent 0,20 em), så
linjene og tabellen ikke flytter seg. Målt med skriftfilene 3 sekunder
forsinket (CLS ved byttet): uten tilpasset reserve 0,026 til 0,250, med
0,000 til 0,0002, og tabellen endrer verken bredde, høyde eller rader.

blokk(vekter) gir det som står i <head>, mellom <!-- SKRIFTER --> og
<!-- /SKRIFTER -->. Ligasidene og forsiden har blokken skrevet inn (failsafe
sjekker at den er lik blokk() med vektene under); lag_sider.py og
build_modellsjekk.py setter den inn selv.
"""

# (familie, vekt) -> fil i assets/fonts/
FILER = {
    ("Barlow", 400): "Barlow-Regular.woff2",
    ("Barlow", 500): "Barlow-Medium.woff2",
    ("Barlow", 600): "Barlow-SemiBold.woff2",
    ("Barlow", 700): "Barlow-Bold.woff2",
    ("Barlow Condensed", 500): "BarlowCondensed-Medium.woff2",
    ("Barlow Condensed", 600): "BarlowCondensed-SemiBold.woff2",
    ("Barlow Condensed", 700): "BarlowCondensed-Bold.woff2",
    ("Barlow Condensed", 800): "BarlowCondensed-ExtraBold.woff2",
}

# Vektene hver side bruker (målt i Chrome 24.10.2026, PC og mobil): bare de
# hentes med preload.
LIGA = tuple(FILER)
FORSIDE = (("Barlow", 400), ("Barlow", 600), ("Barlow Condensed", 700), ("Barlow Condensed", 800))
LAGSIDE = (("Barlow", 400), ("Barlow", 500), ("Barlow", 600), ("Barlow", 700), ("Barlow Condensed", 700), ("Barlow Condensed", 800))
SPORSMAL = (("Barlow", 400), ("Barlow", 600), ("Barlow", 700), ("Barlow Condensed", 700), ("Barlow Condensed", 800))
MODELLSJEKK = SPORSMAL

# Reserveskriften på ligasidene: (familie, vekt) -> (lokal skrift, size-adjust
# for bokstavene, size-adjust for sifrene). Målt i Chrome 10.11.2026: bredden
# mot Barlow på all tekst på begge ligasidene (uten sifre) og på sifrene, og
# linjehøyden (lik, 120 px ved 100 px).
RESERVE = {
    ("Barlow", 400): ("Arial", 96.3, 90.3),
    ("Barlow", 500): ("Arial", 96.6, 91.8),
    ("Barlow", 600): ("Arial Bold", 91.3, 92.9),
    ("Barlow", 700): ("Arial Bold", 92.6, 94.4),
    ("Barlow Condensed", 500): ("Arial", 78.1, 72.8),
    ("Barlow Condensed", 600): ("Arial Bold", 75.1, 74.5),
    ("Barlow Condensed", 700): ("Arial Bold", 75.5, 76.6),
    ("Barlow Condensed", 800): ("Arial Bold", 77.5, 78.7),
}
POSTSCRIPT = {"Arial": "ArialMT", "Arial Bold": "Arial-BoldMT"}
# Ligasidene: swap og reserveskriften (se over). De andre sidene: som før.
LIGA_VALG = {"display": "swap", "reserve": True}


def _reserve_face(fam, w, lokal, size, sifre=False):
    """Én @font-face for reserveskriften. ascent/descent er Barlows høyde delt
    på size-adjust, siden size-adjust også skalerer dem."""
    return (f"@font-face{{font-family:'{fam} reserve';font-style:normal;font-weight:{w};"
            f"src:local('{lokal}'),local('{POSTSCRIPT[lokal]}');size-adjust:{size}%;"
            f"ascent-override:{10000 / size:.1f}%;descent-override:{2000 / size:.1f}%;line-gap-override:0%"
            + (";unicode-range:U+30-39" if sifre else "") + "}")


def blokk(vekter, display="optional", reserve=False):
    """<head>-blokken: preload for vektene siden bruker, @font-face for alle, og
    med reserve=True reserveskriften («Barlow reserve», «Barlow Condensed reserve»)."""
    if reserve:
        kommentar = "Fra eget domene med font-display: swap og en reserveskrift med Barlows mål, så teksten ikke flytter seg når skriften kommer (scripts/skrifter.py)."
    else:
        kommentar = "Fra eget domene med font-display: optional, så teksten ikke tegnes om (scripts/skrifter.py)."
    linjer = [f"<!-- SKRIFTER --><!-- {kommentar} -->"]
    linjer += [f'<link rel="preload" href="/assets/fonts/{FILER[v]}" as="font" type="font/woff2" crossorigin>' for v in vekter]
    css = "".join(
        f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{w};font-display:{display};src:url(/assets/fonts/{fil}) format('woff2')}}"
        for (fam, w), fil in FILER.items())
    if reserve:
        css += "".join(_reserve_face(fam, w, lok, sb) + _reserve_face(fam, w, lok, ss, sifre=True)
                       for (fam, w), (lok, sb, ss) in RESERVE.items())
    linjer.append("<style>" + css + "</style><!-- /SKRIFTER -->")
    return "\n".join(linjer)
