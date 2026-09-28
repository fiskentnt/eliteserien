# /elo-test/ — testversjon med ELO-Odds 90

**Dette er ikke produksjonssiden.** Grunnmodellen er ELO-Odds med
markedsandel w = 90 % i ratingoppdateringen, k = 83,37 og ρ = 0. Produksjonen
ligger på `/eliteserien/` og er uendret.

Mappen kan slettes i sin helhet uten at produksjonen påvirkes. Ingen
produksjonsfil er endret for å få testsiden til å virke.

## Hva som leses hvor

| Fil | Kilde |
|---|---|
| `../eliteserien/data/matches.json` | produksjonens, direkte |
| `../eliteserien/data/fixtures.json` | produksjonens, direkte |
| `../eliteserien/data/odds_upcoming.json` | produksjonens, direkte |
| `../eliteserien/data/odds.json` | produksjonens, direkte (sluttodds 2026) |
| `emodell/model.json` | egen, bygget av `scripts/bygg.py` |
| `emodell/historikk.json` | fryst grunnlag 2012–2025 |

| `emodell/keymatch.json`, `lastmatch.json`, `prekick.json` | egne, skrevet av produksjonens `scripts/snapshot_probs.js` kjørt mot **/elo-test/** (`--side elo-test --ut elo-test/emodell --uten-historikk`) |
| `emodell/accuracy.json` | egen, `scripts/accuracy_log.py eliteserien --data elo-test/emodell` |

**Panelene** (rundens viktigste kamp, forrige kamp i lagboksen, prekick og
treffsikkerhet) regnes av testsiden selv, med ELO90, i `elo-test.yml` --
parallelt med produksjonen og med de samme skriptene. Produksjonens filer
leses ikke. `history.json` skrives ikke og vises ikke.

- **Når:** når `model.json` eller oddsene i `odds_upcoming.json` er endret
  (sha256 i `emodell/paneler_grunnlag.json`), og alltid når utløseren er
  «Odds nær avspark» eller workflow_dispatch, så prognosen før avspark lagres
  (`elo-test/scripts/paneler.py`).
- **Frysregelen** er produksjonens egen modul, `scripts/prekick_frys.js`: en
  rad oppdateres bare før avspark fra terminlisten, og fryses med siste stempel
  fra før avspark når resultatet kommer.
- **Commit bare ved innholdsendring.** Et nytt tidsstempel alene (`updated`,
  `stamp` i prekick-radene) gir ingen commit; den committede versjonen legges
  tilbake. En ny frosset rad, en ny rad eller nye tall er en endring.
- **To frosne registre.** `prognoselogg/` (bygg.py: siste logglinje før
  avspark) og `prekick.json` (snapshot_probs.js: siste skriving før avspark)
  finnes begge. Treffsikkerhetspanelet (`accuracy.json`) regnes av
  `prekick.json`, som i produksjonen, så de to sidene måles med samme regel.
- **Kontroll W** krever at `prekick.json` har ELO90-tallene fra `model.json`
  (outcome av byggingens λ, og OLR-sannsynlighetene som «modell») og skiller
  seg fra produksjonens, at frysregelen er produksjonens modul, at siden henter
  filene fra `emodell/` og ikke `history.json`, og at frosne rader har stempel
  før avspark.
- **Forrige kamp regnes med oppdatert rating også i lastmatch.json.**
  `snapshot_probs.js` venter på at sluttoddsen for spilte kamper
  (`ELO_ODDS_SPILT`) er lastet før lastmatch regnes; ellers ville den regnet
  med fast rating. Kontroll W åpner siden i Chrome og krever at lastmatch.json
  har samme forventning og prosentpoeng som `qaLastMatchData` gir direkte, for
  minst tre lag, og at svaret sier «Ratingen er regnet om ...». I CI
  installeres puppeteer-core i hver kjøring for dette.
- **Kontroll R** sammenligner de to frosne registrene kamp for kamp når det
  finnes frosne kamper: modelltallene i `prekick.json` skal være lik den
  frosne prognosen i loggen innenfor avrundingen (med odds: OLR mot
  `elo90_p`; uten odds: outcome av lambda mot `outcome(fit_rates(elo90_p))`).
  Testet syntetisk (to kamper frosset, avvik 4,6e-05; mutasjon 0,001 feiler).

## Modellen

- **k = 83,37** er låst fra k(w)-regelen på innkjøringen 2012–2013 og regnes
  ikke om når andre parametere endres.
- **Hjemmefordel, startverdier, rating og OLR** regnes på nytt ved hver
  bygging, av historikken pluss alle spilte 2026-kamper.
- **ρ = 0 overalt** — λ-konvertering, simulering og målfordeling. Laben testet
  ρ = 0; produksjonens −0,38 ville gitt en variant laben ikke har validert.
- **Scenarioresultater behandles som spilte kamper** (fra 27.9.2026; før det
  holdt testsiden ratingen fast). Resultater brukeren fyller inn, og
  resultater fra «Simuler runden», «Simuler tomme kamper» og «<lag>
  vinner/taper resten», oppdaterer ratingen etter modellens eksisterende
  regel, labens `hva_mix_lap`, i datorekkefølge (dato, hjemme, borte):
  - kamp med odds i `odds_upcoming.json`: full ELO90-oppdatering, w = 0,90,
    k = 83,37, med kampens odds **normalisert som i `bygg.py`**
    (x / (H + D + A)); rådataene er rundet til fire desimaler og summerer
    ikke alltid til 1
  - kamp uten odds: reserveregelen (§6B), resultatleddet med Elo-Goals sin
    k = 10
- **Forenkling, samme som produksjonens `computeLiveState`:** den resulterende
  ratingen brukes for **alle** åpne kamper, også dem som ligger før en
  utfylt kamp. Fyller brukeren inn en kamp i runde 30, regnes en åpen kamp i
  runde 24 med ratingen etter den. En strengt kronologisk variant ble prøvd og
  lagt bort i påvente av labtesten av dynamisk rating.
- **λ etter en flyttet rating** kommer fra λ-tabellen (under), ikke fra
  JS-`fitRates`. Målt H/U/B-feil mot OLR er av samme størrelse som byggingens
  λ (labens rutenett); kontroll M rapporterer den.
- **Monte Carlo holder ratingen fast** innenfor hver simulerte sesong: faste λ
  per åpen kamp, regnet fra ratingen etter de utfylte kampene. Dynamisk rating
  inne i simuleringen avventer labtesten
  (`resultater/eloodds_2026/BESTILLING_dynamisk_rating.md` i laben).
- **Samme normaliserte markedssannsynlighet overalt:** ratingoppdateringen,
  70 %-blandingen (`blend_lam` og `blend_tabell`) og teksten «Blandet 70 %
  odds (…)» bruker alle x / (H + D + A). Før viste teksten rådataene: for
  Brann–Viking borteseier 42 % mot normalisert 43 %. Produksjonssidens
  `rateFor` bruker fortsatt rådataene; den er ikke endret.
- **70 % direkte markedsblanding** på kommende kamper som finnes i
  produksjonens `odds_upcoming.json`. Ellers ELO90 alene. Vekten er
  produksjonens og er ikke tunet.
- **λ-tabellen.** `bygg.py` legger labens `fit_rates(olr_sannsyn(dr))` i
  `model.json` som bruddpunkter (`lam_tabell`, ~1760 segmenter), og for hver
  kamp med odds en blandingstabell (`blend_tabell`) for
  `fit_rates(0,7 × marked + 0,3 × OLR(dr))`, med normaliserte odds som
  `blend_lam`. Siden bruker byggingens λ når ratingforskjellen er uendret og
  tabellen ellers — aldri JS-`fitRates`, som bruker et annet rutenett og gir
  andre målrater for 74 % av ratingforskjellene. Tabellen bygges ved
  nærmeste-nabo-søk i labens rutenett (k-d-tre; nesten like avstander avgjøres
  av `fit_rates` selv), skann på 0,0005 i [−800, 800], bisektering til 1e-9, og
  hvert segment kontrollert mot `fit_rates` i midtpunktet. ~18 s per bygging.
  Tabellene sammenlignes ikke ved skrivetoleransen: de er avledet av `olr` og
  `kamper` i samme fil og bygges bare når filen skrives, så maskinstøy i dem
  gir ingen commit.

## Den frosne prognosen

`emodell/prognoselogg/<YYYY-MM>.jsonl` er append-only. En ny linje skrives
bare når den publiserte prognosen for en kamp faktisk er **endret** siden
forrige linje for samme kamp: minst ett tall må ha flyttet seg **1e-5 eller
mer**. Modell, dato, avspark og om markedet finnes sammenlignes eksakt. En ny
`odds_hentet` alene er ikke en endring.

**Hvorfor en terskel.** Byggingen er ikke bit-reproduserbar mellom
maskiner, og det gjelder også mellom to CI-kjøringer. Ratingene skiller
2,8e-14 mellom macOS og CI, men `olr_tilpass` bruker scipys Nelder-Mead, som
forsterker det til ~8e-09 i OLR-parameterne og ~2e-09 i 1X2. Ligger en verdi
nær en avrundingsgrense, vipper sjette desimal. 1e-5 er ti avrundingsenheter:
langt over støyen, langt under det siden viser.

**Også CI mot CI.** Kjøringene 2026-09-27 10:56 UTC (36314089108, Azure
westus) og 11:20 UTC (36315415718, centralus) hadde samme input (ingen
produksjonsdata endret etter 10:50), samme image (ubuntu-24.04,
20260920.314.1) og samme numpy 2.5.3 og scipy 1.18.1. Likevel skilte
`model.json` seg med opptil 8,9e-09. Det er tre ulike resultater for samme
input: for Aalesund–Bodø/Glimt ga macOS og centralus 0,722485 og westus
0,722486; for KFUM Oslo–Brann ga macOS og westus 0,43578 og centralus
0,435779. Den sannsynlige årsaken er at runnerne har ulike CPU-er og at numpy
velger regnevei etter CPU; loggene oppgir ikke CPU-modell, så det er ikke
bekreftet.

**Fire linjer i loggen er støy, ikke endrede prognoser.** Linje 1–72 i
`2026-09.jsonl` er skrevet av den lokale byggingen 10:18 UTC (macOS). Linje
73 (Aalesund–Bodø/Glimt, 10:56, westus) og linje 74–76 (KFUM Oslo–Brann,
Aalesund–Bodø/Glimt og Vålerenga–Rosenborg, 11:20, centralus) avviker hver
med nøyaktig 1e-06, én avrundingsenhet, fra forrige linje for samme kamp.
Alle fire ble skrevet av koden før terskelen kom. Med terskelen ville ingen
av dem blitt skrevet. Linjene står, siden loggen er append-only.

**`model.json` og `meta.json` skrives med toleranse.** Et tall regnes som
endret bare når det har flyttet seg mer enn 1e-6 fra filen som ligger der;
tekst, nøkler og listelengder sammenlignes eksakt. Ellers røres filen ikke.
Før dette ble `model.json` sammenlignet eksakt, og f76708a (11:20) var en
commit uten endrede data, bare en annen CPU. Verifisert på de tre versjonene
vi har (10:56 westus, 11:20 centralus og en lokal macOS-bygging): de skiller
seg parvis med opptil 9,5e-09, ingen av dem er eksakt like, og med hver av dem
som filen på disk sier `bygg.py` «model.json uendret» og sha256 er den samme
før og etter. En endring på 1e-3 i én rating skrives. `olr_tilpass` og
Nelder-Mead er ikke endret, ellers ville A1 sluttet å matche laben.

`elo-test/requirements.txt` låser numpy 2.5.3 og scipy 1.18.1, versjonene CI
brukte. Det hindrer bare at en oppgradering flytter tallene. Forskjellen
mellom maskiner fjerner det ikke; den tas av toleransen i `model.json` og
terskelen i loggen.

**Definisjon:** for en kamp hentes avsparket fra **terminlisten**
(`fixtures.json`: `date` + `time`, norsk lokaltid, `Europe/Oslo` → UTC). Den
frosne prognosen er den **siste logglinjen med `logget` < avspark**.

Avsparket tas **ikke** fra logglinjen: feltet `avspark` der kommer fra
`odds_upcoming.json` sin `commence_time` og er `null` for hver kamp som ikke
ligger i den filen. Det er informasjon, ikke utvalgskriterium. Perioden
krysser sommertidsskiftet 25. oktober 2026, så omregningen må gå gjennom
`Europe/Oslo`, ikke et fast timetall.

**Den frosne prognosen er den siste faktisk observerte prognosen før
avspark — ikke garantert en prognose fra 15–60-minuttersvinduet.** Grunnen:
`prekick-odds.yml` kjører `prekick_odds.py … || true`, så en mislykket henting
feiler ikke steget, og workflowen kan ende med `success`. Den utløser da
ELO-byggingen med den **gamle** `odds_upcoming.json`. Er prognosen uendret,
skrives ingen ny logglinje (verifisert: uendret input gir null linjer). Siste
linje før avspark kan dermed være fra en tidligere henting, for eksempel
`update-odds.yml` kl. 08:13 eller 16:13 UTC samme dag.

`odds_upcoming.json` kan også inneholde odds for **pågående** kamper —
`fetch_odds_upcoming.py` sier selv at endepunktet returnerer «kommende/pågående
kamper», og en kamp fjernes først når resultatet står i `matches.json`.
Definisjonen over tåler det, siden bare linjer med `logget` < avspark teller.

- **Panelene stopper aldri modellen.** `elo-test.yml` har to commits.
  Først bygges modellen, `kontroll.py` (A til V og E, uten Chrome) kjøres,
  og `model.json`, `meta.json` og `prognoselogg/` lagres og pushes. Feiler
  `kontroll.py`, stopper alt der, som før. Deretter regnes panelene,
  `kontroll_paneler.py` (W, R og panelfilenes tekst i L) kjøres, og først når
  begge har bestått, lagres de fem panelfilene (`keymatch`, `lastmatch`,
  `prekick`, `accuracy`, `paneler_grunnlag`) i en egen commit. Feiler
  panelsteget eller kontrollen, blir de forrige committede panelfilene stående,
  og jobben blir rød. Kontroll **O** i `kontroll.py` krever denne rekkefølgen,
  at hver commit tar nøyaktig sine filer, og at ingen `continue-on-error` eller
  `always()` slipper noe gjennom. Den feiler på den gamle workflowen med én
  felles `git add elo-test/emodell`.
  Testet med en simulert kjøring av stegene i en klone med egen origin:
  (1) med `ELO_ODDS_SPILT` som aldri lastes, fikk panelsteget tidsavbrudd;
  `model.json` og én ny prognoselinje ble pushet, panelfilene var uendret, og
  jobben var rød. (2) Uten ventingen i snapshot_probs.js besto panelsteget,
  men W feilet; resultatet var det samme. (3) Med en endret festet fil feilet
  `kontroll.py`, og ingenting ble pushet.

Det finnes ingen kunstig historikk: loggen og `prekick.json` starter den
dagen siden går live. Treffsikkerhetspanelet viser testsidens egne frosne
kamper fra første runde etter det (9.–12. oktober 2026).

## Kontroller

`python3 elo-test/scripts/kontroll.py` — hardfeiler og stopper alt. A1 og A2
krever laben og hoppes over uten den; resten kjører også i CI.

`python3 elo-test/scripts/kontroll_paneler.py` — panelene (W, R og
panelfilenes tekst i L). Kjøres etter at modellen er lagret; feiler den, lagres
ikke panelfilene. Chrome-sjekken i W hoppes over lokalt uten puppeteer/Chrome
og feiler i CI.

Kontroll **M** kjører sidens egne `eloMixLap` og `computeLiveState` i Node mot
`hva_mix_lap` på samme input: alle 72 gjenstående kamper med trukne resultater
(fast seed), odds fra `odds_upcoming.json` der de finnes. Ratingen sammenlignes
etter hver kamp, i begge greiner (8 kamper med odds, 64 uten), innenfor 1e-12;
målt avvik er 0. Den krever også at sidens `ELO_HVA` er lik `HVA` i
`eloodds.py`, at sidens sortering er Pythons, og forenklingen: med siste
halvdel utfylt regnes de åpne kampene før dem med ratingen etter alle utfylte,
via λ-tabellen. Markedssannsynligheten kontrolleres fra **rådataene** i
`odds_upcoming.json`: sidens `eloOddsFor` skal gi bit for bit byggingens
`marked` (som blandingen bygger på) og det `rateFor` lagrer og viser, og en
innfylt odds-kamp med rådataene ganget med 1,03 skal gi samme rating som
Python innenfor 1e-12. Med dagens fil summerer tre av åtte kamper ikke til 1,
så også de ekte dataene avslører en manglende normalisering.

## Hva modellen ikke har

Ingen angreps- og forsvarsstyrker, og ingen lagspesifikk hjemmefordel. Én
rating per lag og én ligaomfattende hjemmefordel. «Slik fungerer det»-tabellen
er derfor erstattet av en ratingtabell, ikke fylt med konstruerte tall.

Flaks-spørsmålet er fjernet: det ville vurdert hver spilte kamp med ratingen
slik den er i dag, altså etterpåklokskap.

## Avviksliste mot `eliteserien/index.html`

Basis: `eliteserien/index.html` i commit `54488d8` (sha256 `6bf85c87…`).
Kopien ble tatt i `1fc6e8f`. Produksjonsrettelsene etterpå er tatt inn med
samme patch, ordrett: merkene (`157d9ff`: likt på poeng er en trussel,
ferdigspilt sesong etter faktisk plass), ordlyden i forrige kamp (`bf623aa`:
«markedet ventet» ved sluttodds) og avrundingen i svarene (`5f415cd`:
differansen mellom de viste tallene), merkesøket (`9cc3590`: tidlig stopp og
egen Worker for merkene), tabellsimuleringen i egen Worker (`16934d2`) og
minnet i fitRates med simuleringen sendt med en gang (`e9477ea`) og
låste utfall i svarene regnet med lagstyrkene etter resultatet (`6d6e5b6`; her
går de fortsatt via `eloTaskOver`/`eloKandidatOver`) og den raskere, bit-like
`outcome()` (`fbc447c`), grovsilingen i poolen (`854abcb`), rundens viktigste
kamp med 3 000 sesonger i nettleseren og 20 000 i CI (`c8c0269`, også panelet
`emodell/keymatch.json`), og egne forkastingsgrupper i poolen (`54488d8`).
Kopien har 7293 linjer mot produksjonens 6976, fordelt på 32 endrede
blokker (`git diff`, vanlig kontekst). Merkerettelsen endret ikke antallet
blokker; scenariooppdateringen (27.9.2026) la til tekstendringer og nye
funksjoner i blokk A.
Listen er ment å være nok til å portere Elo-laget inn i produksjonssiden uten
å lese hele diffen. `kontroll.py` (I) advarer hvis produksjonssiden har endret
seg siden.

### A. Modellaget — det som må porteres

Én blokk satt inn til slutt i hovedskriptet. I samme skript vinner den siste
funksjonsdeklarasjonen, og deklarasjoner heises, så alle kall — også under
`boot()` — treffer disse.

| Funksjon | Status | Hva den gjør i ELO90 | Produksjonens versjon gjorde |
|---|---|---|---|
| `eloOLR(par, dr)` | ny | 1X2 av ratingforskjellen; speiler labens `olr_sannsyn` tegn for tegn: `p0 = sig(t1 − z)` borteseier, `p2 = 1 − sig(t2 − z)` hjemmeseier, z klippet til [−60, 60] | — |
| `computeLiveState()` | overstyrt | byggingens rating, deretter `eloMixLap` over alle utfylte kamper i `matches` (egne og grå) i datorekkefølge. Den resulterende ratingen brukes for **alle** åpne kamper, også dem før en utfylt kamp — samme forenkling som produksjonen. `att/con/ha/hc` er nullfylte bærere | bygget att/con/ha/hc fra `MODEL` og drev dem med `FORM_K` for alle utfylte kamper |
| `eloMixLap(R, kamper, hr, w, k)` | ny | labens `hva_mix_lap`, tegn for tegn og i samme uttrykksrekkefølge; begge greiner | — |
| `eloOddsFor(h, a)` | ny | markedets 1X2 fra `odds_upcoming.json`, normalisert med summen som i `bygg.py` | — |
| `eloScenarioKamper()` | ny | utfylte kamper, sortert på (dato, hjemme, borte) med vanlig `<`, som Python | — |
| `eloTabellOppslag(tab, dr)` | ny | oppslag i en bruddpunkttabell; indeksen er antall bruddpunkter ≤ dr, som `bisect_right` | — |
| `stateRate(state, h, a)` | overstyrt | byggingens λ når ratingforskjellen er uendret (bit-lik laben); ellers `lam_tabell`. JS-`fitRates` bare for en `model.json` uten tabell (overgang) | `exp(mu + H + att + ha + con − hc)` |
| `rateFor(h, a)` | overstyrt | 70 %-blanding av **OLR-sannsynlighetene** med markedet; byggingens `blend_lam` når ratingforskjellen er uendret, ellers kampens `blend_tabell` | blandet `outcome(λ)` med markedet |
| `oddsOverrideFor(h, a)` | overstyrt | returnerer λ for **alle** kamper, slik at workeren bruker faste rater, som labens `faste` | returnerte λ bare for kamper med odds, ellers `null` |
| `eloPPK(R, lag)` | ny | balansert forventet poeng per kamp: `eloOLR` mot hvert av de andre lagene **både hjemme og borte**, `3·P(seier) + P(uavgjort)`, snitt over 2·(n−1) kamper. Hjemmefordelen ligger i OLR-tersklene, så begge må med | — |
| `eloStyrke(R, lag)` | ny | **produksjonens formel**: `5 + (ppk − snitt) · FORM_SPAN`, klippet til [0, 10]. Første utkast brukte `(rating − snitt)/100 · FORM_SPAN`, som ga spenn 1,1–12,9 og klippet Glimt og Viking til 10,0 | — |
| `formScores()` | overstyrt | `eloStyrke(LIVE.R)` | forventede poeng av att/con |
| `neutralExpPts()` | overstyrt | returnerer 0, ikke i bruk | forventede poeng på nøytral bane |
| `renderModelTbl()` | overstyrt | ratingtabell: rating, mot snittet, H/U/B mot snittlag | «Slik fungerer det»: fire forventede mål per lag |
| `teamFormHistory(team)` | overstyrt | `eloStyrke` på ratingen per kampdag fra `rating_historikk`, altså samme skala som Styrke-kolonnen | kjørte FORM_K-oppdateringen på nytt |
| `baseRate(h, a)` | overstyrt | `stateRate` med byggingens rating. **I praksis død**: eneste bruker er `qaLuck`, som ikke kan nås | statiske att/con |

Globale variabler: `ELO` (modellfilen), `ELO_LAM` (λ, 1X2 og `blend_lam` per
gjenstående kamp), `ELO_HVA` (c, d, b og reserve-k fra `HVA`, kontrollert av M),
`ELO_EKTE` (**død kode** — satt, men ikke lest; `matches` inneholder bare
gjenstående kamper, så spilte kamper kan ikke oppdateres to ganger).

### B. Inngrep inne i eksisterende kode

| Område | Endring | Hvorfor |
|---|---|---|
| `const DC_RHO` (hovedtråden) | −0,38 → **0** | laben testet ρ = 0; `const` kan ikke overstyres senere |
| `var DC_RHO` i `WORKER_SRC` | −0,38 → **0** | workeren har sin egen kopi; hovedtrådens endring nådde den ikke |
| `runZoneTasks` | `...(t.over\|\|{})` → `...eloTaskOver(payload, t)` | låst utfall (`idx`, `score`) eller alternativt resultat i forrige kamp (`eloAlt`) får egen `oddsOverride`, regnet med ratingen etter utfallet |
| `runMatchImpactAsync` | kandidatene får `overHome`/`overAway`/`overDraw` (`eloKandidatOver`) | samme, for neste kamp, kamper som betyr mest og kortet Neste kamp |
| `runMatchImpact` i `WORKER_SRC` | hvert låste utfall simuleres med sin egen `oddsOverride` | workeren kjørte alle utfallene med samme målrater |
| `qaLastMatchData` | oppgavene for de alternative utfallene merkes `eloAlt` | så `runZoneTasks` kan regne ratingen etter det alternative resultatet |
| `qaLastMatch`, avsluttende setning | «Lagstyrkene holdes som i dag» → «Ratingen er regnet om for hvert alternative resultat, men holdes fast gjennom resten av sesongen» når `odds.json` er lastet | setningen skal si hva som skjer |
| `qaLastMatch` og `qaLastMatchLine` | «enn modellen ventet» → produksjonens `ventetAv(...)` (bf623aa, tatt inn ordrett): «markedet» ved sluttodds, «modellen» ved frosset prognose | testsiden hadde sin egen `eloVentetAv`; den er erstattet av produksjonens |
| `boot()`, `odds.json` | hentes ved siden av, normalisert som i `bygg.py` (`ELO_ODDS_SPILT`) | trengs bare til avspillingen for forrige kamp |
| `boot()`, datastier | `data/…` → `../eliteserien/data/…` for matches, fixtures, odds_upcoming, status, odds_quota | produksjonens filer leses direkte, ingen kopier |
| `boot()`, modellsti | `data/model.json` → `emodell/model.json` | egen modell, i en mappe som ikke heter `data` (sitemap) |
| `boot()`, keymatch/lastmatch/prekick/accuracy | `data/…` → `emodell/…` | testsidens egne panelfiler, regnet med ELO90 (se over). Første versjon erstattet hentingen med `Promise.resolve(null)` og hadde et komma for mye etter hver (`,,`); hullene forskjøv destruktureringen, og sluttoddsen ble aldri lastet. Kontroll **P** krever like mange elementer som variabler og ingen hull |
| `accuracyLog` | `hidden` fjernet, teksten over skrevet om | treffsikkerhetspanelet viser testsidens egne tall |
| `boot()`, etter `MTI` | setter `ELO`, `ELO_LAM`, `ELO_EKTE` | kobler inn modellaget |
| `boot()`, `howP1`/`howP2` | ny forklaringstekst; `MODEL.meta.half_life_days` fjernet | ELO90 har én rating og ingen halveringstid; `meta` finnes ikke |
| `render()`, `baseForm` | `formScores(MODEL.att…)` → `eloStyrke(ELO.rating_alle)` | `MODEL.att` finnes ikke |
| `renderFaq()` | FAQPage-schemaet injiseres ikke | strukturerte data hører ikke på en noindex-side |
| spørsmålslisten | `{id:'luck', …}` fjernet | etterpåklokskap, se over |
| `renderQaHighlight()` | reserven uten valgt lag (og med lag før sonen er klar) **skjuler** knappen i stedet for å vise flaks-spørsmålet; `el.hidden = false` først i funksjonen | `KEYMATCH` er alltid `null` her, så produksjonens reserve ville **alltid** vist «heldig eller uheldig» uten valgt lag. Klikk gjorde ingenting, siden spørsmålet er fjernet |
| klikk på `qaHighlight` | `dataset.qid \|\| 'luck'` → `\|\| ''` | ingen reserve til et fjernet spørsmål |
| `LEAGUE.path` | `/eliteserien/` → `/elo-test/` | |
| `LEAGUE.closingOddsFile` | → `../eliteserien/data/odds_closing.json` | observerte sluttodds, ikke modellberegnet |

### B2. Synlig tekst som beskrev Full

| Sted | Produksjonens tekst | Testsiden |
|---|---|---|
| «Om tabellkalkulatoren» | avsnitt om «Hvem har vært heldig eller uheldig» | fjernet |
| «Slik fungerer det», 1. avsnitt | styrke «fra målene sine … der nye kamper teller mest» | én rating siden 2012, 90 % markedssignal, 10 % resultat |
| «Slik fungerer det», 2. avsnitt | Styrke «over hele sesongen» | Styrke = rating omregnet til forventede poeng per kamp; et utfylt resultat flytter ratingen, og kampene etter regnes med den nye |
| detaljer, simuleringen | «lagstyrken oppdateres etter hver kamp i hver simulerte sesong» | inne i hver simulerte sesong holdes lagstyrken **fast**, som i testene; bare resultatene i kamplisten flytter den |
| detaljer, typisk sesongforløp | «med formoppdatering underveis» | trekkes «med fast lagstyrke» (`oddsOverrideFor` gir faste rater); når kampene er fylt inn, flytter de ratingen som egne resultater |
| detaljer, Sarpsborg-avsnittet | Full-styrken flyttet Sarpsborg 08 fra 4,80 til 4,65 | fjernet — erstatningen gjentok «Slik fungerer det» |
| `howP2` | — | resultater fra brukeren og simuleringsknappene flytter ratingen etter samme regel som spilte kamper; Monte Carlo holder den fast |
| `howP1` | `k = 83.37` | `k = 83,37` |
| «Hvordan vet vi at modellen virker?» | produksjonens validering: 20 mot 18 prosent, sist validert 24. september, `backtest_zones.py`, kalibreringstabeller | kort tekst: testet i laben mot produksjonsmodellen, labresultatene for ELO-Odds 90 er ikke publisert på siden ennå, treffsikkerhet først etter en sesong. `accuracyLog` står som skjult stubb fordi JS skriver til den. `modelExample` (for eksempel Viking mot Brann) **vises**: den regnes med `rateFor` og `outcome`, de samme tallene som kamplisten, og er riktig for ELO90 |
| FAQ «Hvordan regnes sannsynlighetene ut?» | «en modell tilpasset på mål og sluttodds» | ELO-Odds 90: én rating per lag siden 2012, 90 % markedssignal |

Kontroll **L** leter etter **hele Full-fraser**, ikke enkeltord, i HTML-tekst
utenfor script/style/kommentarer og i aktiv JS: produksjonens faktiske
ordlyd der den beskriver Full («tilpasset på mål og sluttodds», «angreps- og
en forsvarsstyrke», «Nyere kamper teller mest», «teller halvparten så mye»,
«tilpasses på nytt», «styrke fra målene» m.fl.), pluss flaks- og
valideringsfrasene. Kjørt på produksjonssiden finner den 11 av 14, så den
vokter noe reelt.

Enkeltord er **ikke** forbudt med vilje. Testsiden sier selv «Det finnes ingen
halveringstid» og «har ikke egne angreps- og forsvarstall» — korrekte
negasjoner. Et forbud mot ordene ville tvunget bort riktig tekst, og korrekt
brukertekst skal ikke endres for at en kontroll skal passere.

Kontroll **U**: svarene som låser et resultat (neste kamp, kamper som betyr
mest, heie på, rundens viktigste kamp, forrige kamp, kortet Neste kamp) holdt
før ratingen fast etter det låste resultatet, mens et innfylt scenario
oppdaterte den. For Brann–Viking ga svaret 13/6/4 % topp 4 mot scenarioets
16,4/6,8/3,8 %. Nå regner hovedtråden ratingen etter hvert låste utfall med
`eloMixLap` og sender egne målrater (tabellene) til workeren. U krever at
målratene er **bit-like** dem scenarioet gir med samme resultat utfylt (Brann–
Viking i tre utfall, seks andre kamper, og med en annen kamp utfylt), at
forrige kamp spilles av riktig (faktisk resultat gir byggingens rating;
alternativet er lik Python-avspillingen), og at svarene er koblet til dette.
Målt med 100 000 simuleringer: svarveien 15,84/6,45/3,22 % mot scenarioet
15,90/6,45/3,17 % (forskjell under 1 SE); før rettelsen ga svarveien 13,81/
6,21/3,62 %. Med samme frø og N gir svarveiens og scenarioets målrater
identiske tall.

Kontroll **T** måler tabellen mot `fit_rates` på ~42 000 punkter (tilfeldige,
kampenes egne dr og alle bruddpunktene) og blandingstabellene på 24 000; avvik
rapporteres, ikke kreves null, fordi segmenter smalere enn skannesteget kan
mangle. Den krever at sidens oppslag er bit-likt Pythons, og at `stateRate` og
`rateFor` faktisk bruker tabellene når ratingen er flyttet. Mutasjoner (`<` for
`<=`, tabellen koblet fra) er kontrollert å feile.

Kontroll **K** regner Styrke uavhengig i Python og krever likhet med sidens
`eloStyrke`, og at ingen lag er klippet til 0 eller 10. Den sjekker også
koblingen statisk: `formScores` returnerer `eloStyrke`, `baseForm` og
formgrafen bruker den. At siden faktisk viser tallene, er kontrollert ved
gjengivelse i Chrome: tabellen og Styrke-kortet viste Glimt 7,8 og Viking 7,0,
tabellen Kristiansund 3,6.

### C. Head og markering

| Område | Endring |
|---|---|
| `<title>` | «TESTVERSJON ELO-Odds 90 — Eliteserien 2026» |
| canonical | fjernet |
| `<meta name="robots">` | `noindex,nofollow` lagt til. `robots.txt` er **ikke** endret — et `Disallow` der ville hindret søkemotorer i å se taggen |
| `og:*`, `twitter:*` | fjernet — pekte på `/eliteserien/` |
| statisk `ld+json` (`WebApplication`) | fjernet — oppga `/eliteserien/` |
| goatcounter | fjernet — var portet på produksjonens vertsnavn og ville talt testsiden |
| banner | nytt, rett etter `<body>` |

### D. Ved portering inn i produksjonen

Blokk A kan flyttes nesten uendret. B må gjøres bevisst: ρ = 0 gjelder på
**begge** steder, og datastiene (også panelfilene i `emodell/`) går tilbake
til `data/`. C er
testsidespesifikk og skal ikke porteres. `ELO_EKTE` kan fjernes.

## Ikke løst

- **Sesongskiftet.** `historikk.json` dekker 2012–2025, og 2026 leses fra
  produksjonens `matches.json`. Når produksjonen går over til 2027, forsvinner
  2026 fra den filen. **2026 må fryses inn i `historikk.json` før det skjer**,
  ellers mister ratingen en sesong. Da endres også sha256-festet i
  `kontroll.py`, og det må gjøres bevisst.
- **OBOS.** Ikke med. ELO-Odds der forutsetter Oddsportal-tilbakefyllet, som
  ikke skal ligge i det offentlige repoet. `scripts/build_league.py` genererer
  `obos/index.html` fra `eliteserien/index.html`, men ikke fra testsiden, og
  skal ikke gjøre det.
- **Historikkpanelet** (`history.json`) er ikke regnet for testsiden og
  vises ikke.
- **Ratingoppdatering i scenarioer er ikke validert i laben.** Regelen er
  labens egen og er kontrollert bit-eksakt mot den (M), men laben har ikke
  målt hva det gjør med prognosene at brukerens resultater flytter ratingen.
- **Monte Carlo med fast rating** avventer labtesten av dynamisk rating.
- **Forenklingen** (resulterende rating også for åpne kamper før en utfylt
  kamp) er ikke kronologisk. Den er valgt fordi produksjonen gjør det samme.
- **Knappene trekker med fast lagstyrke.** «Simuler tomme kamper» og de andre
  trekker hele forløpet med λ fra ratingen på trekketidspunktet, i én
  omgang. Ratingen oppdateres først når resultatene står i kamplisten; den
  oppdateres ikke underveis i trekningen.
- **Forrige kamp trenger `odds.json`.** Avspillingen for et alternativt
  resultat bruker sluttoddsen for de spilte kampene. Er filen ikke lastet,
  holdes ratingen fast for alternativet, som før, og svaret sier det.
- **Produksjonens `rateFor` normaliserer ikke oddsen.** Den bruker rå
  oddstall fra `odds_upcoming.json` (`[o.H, o.D, o.A]`) uten normalisering.
  Rådataene er rundet til fire desimaler og summerer ikke alltid til 1;
  avviket er rundt 1e-4 og gjelder bare produksjonen. Testsiden normaliserer
  som `bygg.py`. Produksjonens `rateFor` er ikke endret.
- **Flaks-spørsmålet** er fjernet, ikke løst. Det lå også som reserve i
  `renderQaHighlight`, som kontroll G ikke så; kontroll L gjør det nå. Det krever å vurdere hver spilt
  kamp med ratingen slik den var **før** kampen, som finnes i
  `rating_historikk`, men mekanismen er ikke bygget.
