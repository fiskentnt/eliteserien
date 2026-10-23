"""Skriftene på sidene (24.10.2026): Barlow og Barlow Condensed fra eget domene.

Før kom de fra Google Fonts med display=swap. Ved første besøk kom de etter at
siden var tegnet første gang, teksten ble tegnet om med ny skrift, tittelen
brøt annerledes, og alt under hoppet (CLS 0,17 til 0,28 på mobil). Nå ligger
de i assets/fonts/ (SIL OFL, assets/fonts/OFL.txt; latin-utsnittet fra Google
Fonts, det samme som Google sendte for norsk tekst). preload henter skriftene
siden bruker straks, og font-display: optional gjør at de bare brukes hvis de
er der til første tegning: ellers står reserveskriften hele besøket, i stedet
for å bytte og flytte teksten.

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


def blokk(vekter):
    """<head>-blokken: preload for vektene siden bruker, @font-face for alle."""
    linjer = ["<!-- SKRIFTER --><!-- Fra eget domene med font-display: optional, så teksten ikke tegnes om (scripts/skrifter.py). -->"]
    linjer += [f'<link rel="preload" href="/assets/fonts/{FILER[v]}" as="font" type="font/woff2" crossorigin>' for v in vekter]
    linjer.append("<style>" + "".join(
        f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{w};font-display:optional;src:url(/assets/fonts/{fil}) format('woff2')}}"
        for (fam, w), fil in FILER.items()) + "</style><!-- /SKRIFTER -->")
    return "\n".join(linjer)
