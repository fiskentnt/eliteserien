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
| Merker ved poenglikhet | for hver merkegrense og nedrykksgrensen i begge ligaer: ferdigspilt og likt på poeng gir merket bare til laget som står over etter målforskjell; helt likt på poeng, målforskjell og scorede mål gir ingen av dem merket; kan et lag fortsatt nå samme poengsum, venter merket |
| Prekick: frysing ved avspark | avspark fra terminlisten regnes om fra norsk tid til UTC (også over sommertidsskiftet); for begge ligaer: en rad oppdateres før avspark, røres ikke ved og etter avspark, lages ikke etter avspark, og fryses med stempelet fra før avspark når resultatet kommer; `snapshot_probs.js` bruker regelen, og OBOS-jobben kjører samme skript |
| Forrige kamp: ordlyden følger kilden | «bedre/verre enn markedet ventet» når forventningen er regnet fra sluttoddsen, «enn modellen ventet» ved frosset prognose (injisert), både i svaret og i linja i lagboksen, begge ligaer |
| Svarene: vist nivå minus vist nå = vist differanse | deterministisk (simuleringen og nå-nivået byttes ut): «Hva betyr neste kamp?», «Hvilke kamper betyr mest?» og «heie på» for én fremre og én bakre sone i begge ligaer, nå fra 0,3 % til 99,7 %; differansen i parentes og «reduserer … med N» er forskjellen mellom de viste tallene, også over «<1 %» og «>99 %»; pluss ekte simulering for to lag |
| Svarene: låste utfall som scenarioet | begge ligaer: de delte funksjonene i `WORKER_SRC` er tegn for tegn hovedtrådens (`Function.toString`), én gang hver, og konstantene er like; hver låste oppgave fra «Rundens viktigste kamp», «Hva betyr neste kamp?», «Heie på» og finsilingen i «Hvilke kamper betyr mest?» spilles av i en Worker (`laastStilling`), og lagstyrkene og målratene er bit-like scenarioets med samme resultat utfylt, uten og med et annet resultat fylt inn; grovsilingen i «Hvilke kamper betyr mest?» går i poolen (400 sesonger) med egen stilling per låst utfall; «Hva betyr neste kamp?» og finsilingen blir ferdige når «Heie på» starter samtidig; «Heie på», «Rundens viktigste kamp» og «Hva betydde forrige kamp?» startet to og to rett etter hverandre blir alle ferdige, med samme tall som hver for seg |
| Rundens viktigste kamp: N i nettleseren og i CI | nettleseren regner med 3 000 sesonger og grense 0,901 (N som faktisk sendes til poolen); CI-nivået (`QA_KEY_N_CI`, `QA_KEY_CLOSE_CI`) er minst 6 000 og 0,93 og brukes når det sendes; `snapshot_probs.js` (banneret) og `lag_innlegg.js` sender CI-nivået |
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
