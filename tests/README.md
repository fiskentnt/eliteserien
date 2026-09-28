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
| Prekick: frysing ved avspark | avspark fra terminlisten regnes om fra norsk tid til UTC (også over sommertidsskiftet); for begge ligaer: en rad oppdateres før avspark, røres ikke ved og etter avspark, lages ikke etter avspark, og fryses med stempelet fra før avspark når resultatet kommer; `snapshot_probs.js` bruker regelen, og OBOS-jobben kjører samme skript. Hvem som skriver raden: datajobbene lar rader med avspark innen 80 minutter være og fryser fortsatt; «Odds nær avspark» skriver bare når oddsen i kjøringen ble hentet 70 til 15 minutter før avspark og skrivingen lander senest 10 minutter før (odds hentet 16 og skrevet 14 minutter før: skrevet, med stempelet fra hentingen), rører ikke andre rader og fryser ingenting; de to skriver aldri samme rad innen ti minutter av hverandre; grensene er de samme som i porten (`prekick_vindu.py`) og sluttoddsvinduet (`oddswindow.py`); `prekick_odds.py` henter fortsatt 60 til 15 minutter før avspark |
| Prekick: «Odds nær avspark» bruker de nyeste lagstyrkene | i en kopi av repoet med falsk klokke (`tests/falsk_klokke.js`), OBOS: to kamper samme dag kl. 15 og 19. Kjøringen 40 minutter før avspark skriver raden for kampen kl. 19 med Pinnacle-prisen, prisens tidspunkt og minutter før avspark (`priced_at`, `minutter_for`; uten dem i oddsraden står de heller ikke i den frosne raden), modellen fra `model.json` og prognosen siden viser. Så kommer resultatet kl. 15 inn (5-0, `matches.json`, `fixtures.json` og ny modell med samme tilpasning som OBOS-jobben, som først sjekkes mot dagens `model.json`), og kjøringen 30 minutter før bruker de nye lagstyrkene: modelldelen flytter seg og er lik den nye modellen, med samme pris i `odds_upcoming.json` og i raden. Odds hentet 16 og skrevet 14 minutter før: skrevet; skrevet 9 minutter før eller odds hentet 14 minutter før: ingenting. Bare raden i vinduet endres, og `keymatch`, `lastmatch` og historikken er urørt |
| Grunnlagsfilen: fingeravtrykket, oppgavene og regningen | begge produksjonssidene: `grunnlagAvtrykk()` er lik ved to lastinger og avhenger av N; den endres med et resultat, en lagstyrke, mu og en oddspris, og har Worker-koden, `FORM_K` og `ODDS_W`; oppgavene «Heie på», «Hva betyr neste kamp?», «Hvilke kamper betyr mest?» (grov- og finsiling) og «Rundens viktigste kamp» sender til poolen for alle 16 lag, finnes i `grunnlagOppgaver()` med samme kamp, resultat og frø; `grunnlagRegn()` gir poolens antall bit for bit, fordelingene summerer til N per lag og plass, og den nekter å regne med et resultat fylt inn |
| Grunnlagsfilen: skriptet skriver bare når alt stemmer | `scripts/lag_grunnlag.js` i en kopi av repoet (OBOS, N = 300): filen har sidens avtrykk for N = 300 (ikke for 100 000), inndata-hashen og én linje per oppgave; med et avtrykk som endres fra lasting til lasting, eller en side som ikke finnes, avslutter skriptet med 1 og den forrige filen står |
| Grunnlagsfilen på siden: tabellen og svarene fra filen | begge produksjonssidene (testserveren gir 404 for `grunnlag.json` i alle andre grupper, så de prøver sidens egen regning): med gyldig fil og uten scenario er tabellen og grunnlaget for delingsteksten filens (100 000 sesonger); «Heie på», «Hva betyr neste kamp?», «Hvilke kamper betyr mest?», «Rundens viktigste kamp» og kortet «Neste kamp» kommer fra filen uten oppgaver til poolen og uten ny tabellsimulering; teksten er den samme med filen og med en pool som gir samme tall; filen er bit for bit det siden regner selv med samme frø og N, og innenfor 3 standardfeil mot en regning med annet frø (N = 20 000) for H, U, B og utgangspunktet i en kamp i neste runde (Brann mot Viking), tre lag; med ett resultat fylt inn regner siden selv, og tømmes scenarioet, gjelder filen igjen uten ny simulering; et svar for en annen sone (qaWhyZoneOverride) regnes av siden; feil avtrykk, feil N, ødelagt og manglende fil gir sidens egen regning uten JS-feil; en fil som kommer 2,5 s sent bytter tabellen og svaret som står; tid til første prosenter i tabellen er ikke lengre med filen eller en fil som kommer 3 s sent enn uten (median av fem, grense +15 % + 30 ms) |
| Treffsikkerhet og sluttoddsen: teksten i modellsjekken | alle tre sidene: avsnittet «Hvorfor oddsen hentes rett før avspark» (tre avsnitt, og log loss-tallet under «Vis detaljer»), "Traff utfallet" med vanlige anførselstegn i forklaringen til tabellen, og med `renderAccuracy` gitt data: uten kamper står "Treffsikkerheten vises her etter hvert som kampene spilles. De første tallene kommer etter neste runde."; med 1 kamp "Tallene bygger på 1 kamp, og sier lite før det er flere. Kampen ble spilt 2. oktober."; med 3 kamper samme dag, over to dager ("mellom 2. og 3. oktober") og over månedsskiftet ("mellom 30. september og 2. oktober"); med 50 kamper uten forbeholdet; antallet i kolonnen Kamper; ingen JS-feil. Kan kjøres alene: `node tests/regression.js --bare treffsikkerhet` |
| Forrige kamp: ordlyden følger kilden | «bedre/verre enn markedet ventet» når forventningen er regnet fra sluttoddsen, «enn modellen ventet» ved frosset prognose (injisert), både i svaret og i linja i lagboksen, begge ligaer |
| Svarene: vist nivå minus vist nå = vist differanse | deterministisk (simuleringen og nå-nivået byttes ut): «Hva betyr neste kamp?», «Hvilke kamper betyr mest?» og «heie på» for én fremre og én bakre sone i begge ligaer, nå fra 0,3 % til 99,7 %; differansen i parentes og «reduserer … med N» er forskjellen mellom de viste tallene, også over «<1 %» og «>99 %»; pluss ekte simulering for to lag |
| Svarene: låste utfall som scenarioet | begge ligaer: de delte funksjonene i `WORKER_SRC` er tegn for tegn hovedtrådens (`Function.toString`), én gang hver, og konstantene er like; hver låste oppgave fra «Rundens viktigste kamp», «Hva betyr neste kamp?», «Heie på» og finsilingen i «Hvilke kamper betyr mest?» spilles av i en Worker (`laastStilling`), og lagstyrkene og målratene er bit-like scenarioets med samme resultat utfylt, uten og med et annet resultat fylt inn; grovsilingen i «Hvilke kamper betyr mest?» går i poolen (400 sesonger) med egen stilling per låst utfall; «Hva betyr neste kamp?» og finsilingen blir ferdige når «Heie på» starter samtidig; «Heie på», «Rundens viktigste kamp» og «Hva betydde forrige kamp?» startet to og to rett etter hverandre blir alle ferdige, med samme tall som hver for seg |
| Rundens viktigste kamp: N i nettleseren og i CI | nettleseren regner med 3 000 sesonger og grense 0,901 (N som faktisk sendes til poolen); CI-nivået (`QA_KEY_N_CI`, `QA_KEY_CLOSE_CI`) er minst 6 000 og 0,93 og brukes når det sendes; `snapshot_probs.js` (banneret) og `lag_innlegg.js` sender CI-nivået |
| Dødmannsknappen | `planlegger/worker.js` kjørt i Node med fetch og klokka byttet ut: livstegn til healthchecks bare etter en planlagt runde innenfor 09-21 UTC der alle utløsningene (hver workflow i `WORKFLOWS`) fikk 204; ingen livstegn når én feiler, utenfor vinduet, ved manuell utløsning eller uten hemmeligheter; aldri `/fail`. `update-data.yml` og `obos-results.yml`: livstegnet er siste steg etter kildevakten, kjøres bare når jobben er grønn, bruker sin hemmelighet og kan ikke gjøre jobben rød |
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
