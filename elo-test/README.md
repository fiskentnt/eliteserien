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
