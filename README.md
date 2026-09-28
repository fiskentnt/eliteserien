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

**OBOS 2025: ingen sluttodds hos OddsPapi.** Tilbakefyllingen
(«OBOS: hent historiske sluttodds», `--sesong 2025`) fikk HTTP 404 «No
historical odds found» for alle 45 kampene den prøvde, 26. september 2026
(`obos/data/odds-historikk/2025.json`). OddsPapi har altså ikke 2025-oddsen.
Tilbakefyllingen er ikke endret.

## Kjente svakheter

Notert, ikke rettet.

- **NTF-unntaket for ugyldig dato slår opp kampen uten sesong.** En rad på
  resultatsiden med ugyldig dato hoppes over når (hjemme, borte) har resultat
  i `matches.json` (`scripts/ntf_source.py`). Oppslaget har ikke med
  sesongen. Det er trygt så lenge `matches.json` bare har én sesong.
- **`obos_results.py --dry-run` skriver til `obos/data/results_state.json`**
  (`checked_at` og `oddspapi_usage`). En tørrkjøring skal ikke skrive.
- **`prekick_odds.py` kan ha samme 404-mønster** for kommende kamper som
  `obos_upcoming_odds.py` hadde: 404 «No historical odds found» logges som
  feil selv om markedet bare ikke er åpnet. Sjekkes når Eliteserie-kampene
  nærmer seg (9. oktober 2026).
- **«Heie på» følger ikke sonen brukeren kom fra.** `qaCheerFor` bruker
  alltid lagets egen målsone (`qaTargetZone`) og ignorerer
  `qaWhyZoneOverride`, mens de andre svarene følger sonen brukeren kom fra.
  Eksempel: etter «Hvorfor har Ranheim 0 % nedrykksfare?» svarer «heie på»
  for topp 6, ikke for nedrykk.
- **Fingeravtrykket for grunnlagsfilen dekker ikke all koden i produksjonen.**
  Avtrykket (`grunnlagAvtrykk`) har med dataene, oppgavene og Worker-koden
  (`WORKER_SRC`), men ikke koden på hovedtråden som setter sammen det
  Workerne får (for eksempel `laastTaskOver` og `stillingsGrunnlag`). Endres
  den koden, kan siden bruke en `grunnlag.json` regnet av den gamle koden
  fram til `grunnlag.yml` har regnet filen på nytt. Porten
  (`scripts/grunnlag_port.py`) regner alltid på nytt når siden er endret, så
  det gjelder noen minutter etter en push. Står slik etter beslutning 28.
  september 2026. Testsiden har ikke svakheten for ELO-koden sin: den er med
  i avtrykket (`grunnlagEkstra`).

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

- **`tests/failsafe.py`** — 184 tester, ingen nett og ingen nettleser. Sjekker
  resultatkjeden, sluttoddsvinduet, at `obos/index.html` er bygget av dagens
  kilde, at xG-data aldri havner i repoet, og portene og oppsettet i
  workflowene.
- **`tests/regression.js`** — 866 tester i hodeløs Chrome via `puppeteer-core`.
  Sjekker tallene i tabellen og kortene mot simuleringen, alle svarene i «Spør
  om tabellen», deling, scenariolenker, og oppsettet på PC og mobil i lys og
  mørk modus. `--live` kjører dem mot den publiserte siden i stedet.

Krever Node og Chrome. `puppeteer-core` hentes til en midlertidig mappe ved
behov, så repoet slipper `node_modules`.

## Personvern

Besøksstatistikken er GoatCounter: ingen informasjonskapsler, ingen
kryssidesporing og ingen samtykkebanner. Skriptet lastes bare på det publiserte
domenet, så lokale kjøringer og testene teller ikke med.
