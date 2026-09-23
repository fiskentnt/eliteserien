# Tabellkalkulator

**In English:** Tabellkalkulator is a table calculator for the two top Norwegian
football divisions, Eliteserien and OBOS-ligaen, at
[tabellkalkulator.no](https://tabellkalkulator.no). It simulates the rest of the
season 10 000 times from a Poisson model with a Dixon–Coles correction, fitted on
goals and closing betting odds, and shows each team's chance of winning the
league, reaching Europe, being promoted or relegated.

---

## Hva siden er

[tabellkalkulator.no](https://tabellkalkulator.no) viser dagens tabell i
Eliteserien og OBOS-ligaen, og sannsynligheten for hvor hvert lag ender.

Du kan fylle inn egne resultater, la modellen simulere de tomme kampene, følge
ett lag, se tabellen etter en valgt runde og dele scenarioet som en lenke.
«Spør om tabellen» svarer på tretten spørsmål med tall fra samme simulering
som tabellen viser.

Alt regnes ut i nettleseren. Python-skriptene i `scripts/` henter data og
tilpasser modellen; de skriver ferdige JSON-filer som siden leser.

## Modellen

**Poisson med Dixon–Coles.** Forventede mål for hvert lag kommer fra et
angreps- og forsvarstall per lag, pluss hjemmefordel. Dixon–Coles-korreksjonen
(rho = −0,38) retter opp at uavhengig Poisson undervurderer uavgjorte resultater
ved lave målsummer. Målrutenettet går til 15 mål per lag.

**Lagstyrkene tilpasses på mål OG sluttodds.** Oddsen er med i selve
tilpasningen med vekt 40, sammen med halveringstid 35 dager på eldre kamper og
regularisering (l1 = 16, l2 = 48). Vektene er målt ut av utvalg, ikke valgt
etter smak: ablasjonstabellen på siden viser hvert ledd for seg, og
`scripts/obos_odds_weight.py` måler oddsvekten på OBOS-tall.

**Markedsoddsen blandes inn per kommende kamp**, med vekt 0,7 mot modellens
egen sannsynlighet. Sluttodds er definert som **siste observasjon mellom 60 og
15 minutter før avspark** (`scripts/oddswindow.py`). En kamp uten pris i det
vinduet står uten sluttodds; en eldre pris brukes aldri i stedet.

**10 000 simulerte sesonger** kjøres i en Web Worker. Frøet er avledet av
scenarioet, så samme scenario gir alltid samme tall — ingen støy når siden
tegnes på nytt.

## Hvordan den er validert

- **Tilbaketest 2016–2025.** Modellen tilpasses ved fire kuttpunkter i hver
  sesong (etter 40, 55, 70 og 85 prosent av kampene), resten simuleres, og
  tallene snittes over 640 lag-observasjoner. Kalibreringen holder omtrent
  vann: der modellen ga rundt 20 prosent, skjedde det i 18 prosent av
  tilfellene. Kjøringen ligger i `scripts/backtest_zones.py`.
- **Ablasjonstest.** Hvert ledd i modellen er slått av og på for seg, og bare
  de som målbart forbedret sluttplassprediksjonen er i bruk. Rekke-rampen ble
  testet og forkastet; xG ble testet på fem sesonger og ga ingen målbar gevinst.
- **Offentlig treffsikkerhetslogg.** `scripts/accuracy_log.py` måler
  sannsynlighetene som ble **lagret før avspark** mot resultatet, og skiller
  side, modell og odds. Ingenting regnes på nytt i etterkant.
- **Oddsvinduet er målt.** På 351 spilte kamper traff odds fra dagen før
  0,0082 ± 0,0041 dårligere i log loss enn odds fra vinduet 60–15 minutter før
  avspark, altså 2,0 standardfeil (`scripts/odds_drift.py`).

## Datakilder

| Hva | Kilde |
|---|---|
| Eliteserien-resultater | ffksupporter.net er fasit; ESPN fyller inn ferske resultater som ikke er lagt inn der ennå |
| OBOS-resultater | OddsPapi, med Wikipedia som kontroll |
| Sluttodds | OddsPapi (Pinnacle, ellers bet365, ellers Unibet), med football-data.co.uk som reserve |
| Odds for kommende kamper | OddsPapi og The Odds API |
| Historiske sesonger | football-data.co.uk (`NOR.csv`), OBOS-CSV 2012–2026 |

Alt hentes automatisk av workflowene i `.github/workflows/`. Ingenting
publiseres uten at valideringen går gjennom.

## Kjøre lokalt

Siden er statiske filer og trenger ingen byggesteg:

```sh
python3 -m http.server 8000
```

Åpne så `http://localhost:8000/eliteserien/` eller `.../obos/`.
Forsiden (`/`) videresender til den ligaen du sist brukte.

`obos/index.html` er **generert**. Rediger `eliteserien/index.html` og
ligadelene i `obos/page/`, og bygg:

```sh
python3 scripts/build_league.py
```

Skriptene som henter data trenger `pip install -r requirements.txt` og, for
oddskildene, `ODDSPAPI_KEY` eller `ODDS_API_KEY` i miljøet.

## Kjøre testene

```sh
tests/run.sh
```

To sett, og begge må være grønne før noe publiseres:

- **`tests/failsafe.py`** — 76 tester, ingen nett og ingen nettleser. Sjekker
  resultatkjeden, sluttoddsvinduet, at `obos/index.html` er bygget av dagens
  kilde, og at xG-data aldri havner i repoet.
- **`tests/regression.js`** — 575 tester i hodeløs Chrome via `puppeteer-core`.
  Sjekker tallene i tabellen og kortene mot simuleringen, alle svarene i «Spør
  om tabellen», deling, scenariolenker, og oppsettet på PC og mobil i lys og
  mørk modus. `--live` kjører dem mot den publiserte siden i stedet.

Krever Node og Chrome. `puppeteer-core` hentes til en midlertidig mappe ved
behov, så repoet slipper `node_modules`.

## Personvern

Besøksstatistikken er GoatCounter: ingen informasjonskapsler, ingen
kryssidesporing og ingen samtykkebanner. Skriptet lastes bare på det publiserte
domenet, så lokale kjøringer og testene teller ikke med.
