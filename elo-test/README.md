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

`keymatch.json`, `lastmatch.json`, `prekick.json`, `accuracy.json` og
`history.json` er **ikke** lest: de er regnet med produksjonsmodellen av
`scripts/snapshot_probs.js`, som kjører produksjonssiden i headless Chrome.
Panelene er skjult.

## Modellen

- **k = 83,37** er låst fra k(w)-regelen på innkjøringen 2012–2013 og regnes
  ikke om når andre parametere endres.
- **Hjemmefordel, startverdier, rating og OLR** regnes på nytt ved hver
  bygging, av historikken pluss alle spilte 2026-kamper.
- **ρ = 0 overalt** — λ-konvertering, simulering og målfordeling. Laben testet
  ρ = 0; produksjonens −0,38 ville gitt en variant laben ikke har validert.
- **Scenarioer flytter ikke ratingen.** Laben holder den fast, og testsiden
  gjør det samme. Produksjonssiden justerer styrkene underveis.
- **70 % direkte markedsblanding** på kommende kamper som finnes i
  produksjonens `odds_upcoming.json`. Ellers ELO90 alene. Vekten er
  produksjonens og er ikke tunet.

## Den frosne prognosen

`emodell/prognoselogg/<YYYY-MM>.jsonl` er append-only. En ny linje skrives
bare når den publiserte prognosen for en kamp faktisk er **endret** siden
forrige linje for samme kamp, målt på de samme avrundede tallene som lagres.
En ny `odds_hentet` alene er ikke en endring.

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

Treffsikkerhetspanelene er skjult til testperioden er over. Det finnes ingen
kunstig historikk: loggen starter den dagen siden går live.

## Kontroller

`python3 elo-test/scripts/kontroll.py` — hardfeiler. A1 og A2 krever laben og
hoppes over uten den; resten kjører også i CI.

## Hva modellen ikke har

Ingen angreps- og forsvarsstyrker, og ingen lagspesifikk hjemmefordel. Én
rating per lag og én ligaomfattende hjemmefordel. «Slik fungerer det»-tabellen
er derfor erstattet av en ratingtabell, ikke fylt med konstruerte tall.

Flaks-spørsmålet er fjernet: det ville vurdert hver spilte kamp med ratingen
slik den er i dag, altså etterpåklokskap.

## Avviksliste mot `eliteserien/index.html`

Basis: `eliteserien/index.html` i commit `1fc6e8f` (sha256 `4a6a3244…`).
Kopien har 6885 linjer mot produksjonens 6721, fordelt på 22 endrede blokker.
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
| `computeLiveState()` | overstyrt | returnerer byggingens rating **uendret**; scenarioer flytter den ikke. `att/con/ha/hc` er nullfylte bærere | bygget att/con/ha/hc fra `MODEL` og drev dem med `FORM_K` for alle spilte kamper |
| `stateRate(state, h, a)` | overstyrt | byggingens λ når ratingforskjellen er uendret (bit-lik laben); ellers `eloOLR` → `fitRates` | `exp(mu + H + att + ha + con − hc)` |
| `rateFor(h, a)` | overstyrt | 70 %-blanding av **OLR-sannsynlighetene** med markedet; byggingens `blend_lam` når den finnes | blandet `outcome(λ)` med markedet |
| `oddsOverrideFor(h, a)` | overstyrt | returnerer λ for **alle** kamper, slik at workeren bruker faste rater, som labens `faste` | returnerte λ bare for kamper med odds, ellers `null` |
| `eloStyrke(R, lag)` | ny | Styrke 0–10 av ratingen om ligasnittet, `/100 · FORM_SPAN` | — |
| `formScores()` | overstyrt | `eloStyrke(LIVE.R)` | forventede poeng av att/con |
| `neutralExpPts()` | overstyrt | returnerer 0, ikke i bruk | forventede poeng på nøytral bane |
| `renderModelTbl()` | overstyrt | ratingtabell: rating, mot snittet, H/U/B mot snittlag | «Slik fungerer det»: fire forventede mål per lag |
| `teamFormHistory(team)` | overstyrt | ratingen per kampdag fra `rating_historikk` | kjørte FORM_K-oppdateringen på nytt |
| `baseRate(h, a)` | overstyrt | byggingens rating → `eloOLR` → `fitRates`. **I praksis død**: eneste bruker er `qaLuck`, som ikke kan nås | statiske att/con |

Globale variabler: `ELO` (modellfilen), `ELO_LAM` (λ, 1X2 og `blend_lam` per
gjenstående kamp), `ELO_EKTE` (**død kode** — brukt da scenarioer flyttet
ratingen, nå satt men ikke lest).

### B. Inngrep inne i eksisterende kode

| Område | Endring | Hvorfor |
|---|---|---|
| `const DC_RHO` (hovedtråden) | −0,38 → **0** | laben testet ρ = 0; `const` kan ikke overstyres senere |
| `var DC_RHO` i `WORKER_SRC` | −0,38 → **0** | workeren har sin egen kopi; hovedtrådens endring nådde den ikke |
| `boot()`, datastier | `data/…` → `../eliteserien/data/…` for matches, fixtures, odds_upcoming, status, odds_quota | produksjonens filer leses direkte, ingen kopier |
| `boot()`, modellsti | `data/model.json` → `emodell/model.json` | egen modell, i en mappe som ikke heter `data` (sitemap) |
| `boot()`, keymatch/lastmatch/prekick/accuracy | `fetch(…)` → `Promise.resolve(null)` | Full-beregnet av `snapshot_probs.js`; skal ikke vises som ELO90 |
| `boot()`, etter `MTI` | setter `ELO`, `ELO_LAM`, `ELO_EKTE` | kobler inn modellaget |
| `boot()`, `howP1`/`howP2` | ny forklaringstekst; `MODEL.meta.half_life_days` fjernet | ELO90 har én rating og ingen halveringstid; `meta` finnes ikke |
| `render()`, `baseForm` | `formScores(MODEL.att…)` → `eloStyrke(ELO.rating_alle)` | `MODEL.att` finnes ikke |
| `renderFaq()` | FAQPage-schemaet injiseres ikke | strukturerte data hører ikke på en noindex-side |
| spørsmålslisten | `{id:'luck', …}` fjernet | etterpåklokskap, se over |
| `LEAGUE.path` | `/eliteserien/` → `/elo-test/` | |
| `LEAGUE.closingOddsFile` | → `../eliteserien/data/odds_closing.json` | observerte sluttodds, ikke modellberegnet |

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
**begge** steder, datastiene går tilbake til `data/`, og de fem
`snapshot_probs.js`-panelene må regnes med ELO90 før de vises igjen. C er
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
- **`snapshot_probs.js`-panelene** — rundens viktigste kamp, forrige kamp,
  historikk, prekick og treffsikkerhet — er skjult. De er ikke regnet om med
  ELO90. Treffsikkerhet kan uansett ikke vises før prognoseloggen har en
  sesong bak seg.
- **Scenarioer holder ratingen fast**, som i laben. Fyller brukeren inn et
  resultat, endres tabellen, men ikke lagstyrken. Produksjonssiden justerer
  styrkene. At ratingen burde flyttes er mulig, men utestet.
- **Flaks-spørsmålet** er fjernet, ikke løst. Det krever å vurdere hver spilt
  kamp med ratingen slik den var **før** kampen, som finnes i
  `rating_historikk`, men mekanismen er ikke bygget.
