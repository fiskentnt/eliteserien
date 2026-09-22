# Regresjonstest

Én kommando kjører alt:

```sh
tests/run.sh
```

Den tar rundt to minutter, skriver én linje per test og avslutter med kode 1
hvis noe feiler. Trenger Node og Chrome (eller Chromium). `puppeteer-core`
hentes automatisk til en midlertidig mappe, så repoet slipper `node_modules`.
Ligger Chrome et uvanlig sted: `CHROME_PATH=/sti/til/chrome tests/run.sh`.

Testene kjører mot den ekte siden i en headless Chrome, servert fra repoet slik
GitHub Pages gjør det. Ingenting er gjenskapt i testen: den klikker og leser det
en bruker ville sett.

## Hva som dekkes

| Gruppe | Sjekker |
| --- | --- |
| Lasting | 16 lag i tabellen og velgeren, fordelingen summerer til 1 per lag |
| Sidelengs scroll | ingen vannrett scroll ved 1400, 1180, 900 og 390 px |
| Spør om tabellen | hvert spørsmål svarer med den størrelsen det ber om (prosent, poeng, prosentpoeng, plasseringsspenn, kamp eller runde), i tre situasjoner × tre lag |
| Utdaterte svar | svaret står aldri igjen fra et annet lag eller scenario, og regnes om |
| Grå resultater | «Simuler tomme kamper» fyller alle, egne resultater sletter dem ikke, «Nullstill» tømmer |
| Sortering | riktig retning per kolonne, merknaden vises, sonestrekene skjules, tredje klikk gir vanlig tabell, simulering nullstiller |
| Delingslenker | scenario ut og inn igjen gir samme resultater og samme tabell, også for en simulert sesong |
| Datafiler | `keymatch.json`, `lastmatch.json` og `history.json` har riktig form, og banneret og lagboksen viser dem |
| Tabellen på mobil | alle tallkolonnene synlige ved 390 px, merket som ikon med forklaring ved trykk, lengste lagnavn ikke klippet |
| Lagbytte | bytte av lag flytter ikke siden, men et trykk på et spørsmål scroller til svaret (mobil og PC) |
| OBOS-ligaen | riktig liga og kolonner (Opprykk, Topp 6, Nedrykk), sonefarger og stiplede linjer på plass 1–2, 3–6, 14 og 15–16, fargeforklaring og kort, og hvert spørsmål svarer med riktig størrelse uten å arve Eliteserien-sonene |
| OBOS: grensene | kunstige scenarioer der et lag krysser 3.→2., 7.→6., 15.→14. og 14.→13. plass, og sonefargen følger den nye plasseringen |
| JS-feil | ingen feil i konsollen gjennom hele kjøringen |

Nye spørsmål i «Spør om tabellen» må legges inn i `QA_EXPECT` i
`tests/regression.js` med størrelsen svaret skal inneholde. Testen feiler hvis
et spørsmål mangler en forventning, så den kan ikke bli utdatert i det stille.

## Når en test feiler

Utskriften viser svaret eller verdien som ikke stemte, rett under navnet. Feiler
noe i «Spør om tabellen», er det ofte fordi en tekst er endret: sjekk om selve
tallet mangler i svaret, eller om bare ordlyden er ny. Mønstrene godtar de
gyldige «ingenting i spill»-svarene (avgjort sone, ferdig sesong), se `SETTLED`.

## Ikke dekket

Firefox og Safari (testen kjører bare Chrome), utseende og farger, og
workflowen som skriver datafilene. Den siste kan kjøres manuelt:

```sh
NODE_PATH=<mappe med puppeteer-core> node scripts/snapshot_probs.js
```

Tilbaketesten av modellen er et eget skript, og krever nedlastet CSV:

```sh
curl -s https://football-data.co.uk/new/NOR.csv -o /tmp/NOR.csv
python3 scripts/backtest_zones.py --csv /tmp/NOR.csv --seasons 2016-2025
```
