# Ting som må gjøres på et bestemt tidspunkt

Kortere oppgaver hører hjemme i en commit, ikke her. Dette er de som må
huskes fram til en dato eller en hendelse.

## Sist oppdatert 22. september 2026

OBOS-ligaen ble lansert på `/obos/` denne dagen: egne soner, lagfarger,
resultatkjede med OddsPapi som hovedkilde og Wikipedia som kontroll,
sluttodds for alle 184 spilte kamper, og odds både i modelltilpasningen og
på kommende kamper. Eliteserien fikk samme språkvask av alle svarene i
«Spør om tabellen», ligafaner i toppmenyen og nye datafiler (`prekick.json`
for sannsynligheter før avspark). To feil ble funnet og rettet: odds hentet
mens en kamp pågikk hadde kommet inn som «sluttodds» og trakk Bodø/Glimts
gullsjanse ned fem prosentpoeng, og tidsvektingen brukte dagens dato, som
krympet lagforskjellene i hver pause. Status: 385 regresjonstester og 31
failsafe-tester grønne mot tabellkalkulator.no.

## Etter runde 23 og 24 i Eliteserien (9.–12. og 17.–19. oktober 2026)

- **Sammenlign oddskildene, og bestem hovedkilde for Eliteserien.**
  OddsPapi (Pinnacle og bet365) og The Odds API kjøres side om side nå.
  Hver kamp lagres i `eliteserien/data/odds_sources.json` med margin
  fjernet og tidspunkt per kilde; raden fryses når kampen er spilt, og
  resultatet føres på. Modellen bruker fortsatt The Odds API.

  Rapporten: `python3 scripts/odds_compare.py --report` gir log loss og
  treffprosent per kilde, og en parvis sammenligning med standardfeil på
  kampene begge kildene har.

  Åtte kamper per runde er for lite til å skille kildene: OBOS-målingen
  trengte 136 kamper for å komme til 1,6 standardfeil. Regn med tre–fire
  runder, altså tidligst i slutten av oktober, før tallet betyr noe. Bytt
  bare hvis forskjellen er utenfor støyen.

## Etter sesongslutt 8. november 2026

- **Kalibrer OBOS-parameterne på OBOS-tall, med tog- og testsett.**
  Halveringstid, regularisering (l1/l2), formoppdatering og Dixon-Coles-rho er
  i dag overført fra Eliteserien. De er IKKE valgt nå, med vilje: OBOS-
  historikken er fjorten sesonger uten odds og én med, og tilbaketesten klarte
  ikke å skille modellen fra tabellmodellen på topp 6. Et søk over parameterne
  på et så tynt grunnlag ville funnet det som tilfeldigvis passet disse
  sesongene, ikke det som holder neste år.
  Når 2026 er ferdigspilt med odds for hele sesongen, gjør samme øvelse som for
  Eliteserien: del i tog- og testsett, søk på togsettet, og rapporter bare
  tallene fra testsettet.

  Oddsvekten er alt målt på OBOS-tall (22. september 2026,
  `scripts/obos_odds_weight.py`, 136 kamper ut av utvalg):

  | vekt | log loss | treff | mot vekt 40 |
  |---|---|---|---|
  | 0 | 1,0143 | 51,5 % | −0,0001 ± 0,0195 (0,0 SE) |
  | 20 | 1,0062 | 49,3 % | −0,0081 ± 0,0078 (1,0 SE) |
  | 40 | 1,0143 | 49,3 % | utgangspunktet |
  | 80 | 1,0033 | 52,9 % | −0,0111 ± 0,0057 (1,9 SE) |
  | 160 | 1,0078 | 51,5 % | −0,0065 ± 0,0083 (0,8 SE) |

  Vekt 80 målte best, men 1,9 standardfeil er innenfor støyen, og rekkefølgen
  er ikke jevn (0 og 40 måler likt, 20 og 160 ligger mellom). Vekten står
  derfor på 40. Kjør målingen på nytt med hele sesongen bak seg.

## Før 2027-sesongen

- **Sjekk lagfargene til Bryne og Strømsgodset på nytt.** Gjøres før første
  serierunde i 2027. Begge ble hentet fra engelsk Wikipedia fordi den norske
  artikkelen var upålitelig da fargene ble lagt inn (22. september 2026):
  - Bryne: no.wikipedia hadde en utdatert infoboks med blå/rødstripet drakt
    (`kropp1=0000BB`). Dagens drakt er rød med hvite ermer, bekreftet mot
    en.wikipedia sin 2026-sesongartikkel og NFF.
  - Strømsgodset: no.wikipedia hadde tomme draktfelter. `#000060` kommer fra
    en.wikipedia (`body1`), bekreftet mot NFF.

  Sjekk om de norske artiklene er oppdatert, og om klubbene har byttet drakt.
  Fargene ligger i `obos/page/league.js` under `teamColors`. Etter en endring:
  `python3 scripts/team_colors.py --check` og `tests/run.sh`.

- **Gå gjennom alle lagfargene når ligaene har nye lag.**
  Opp- og nedrykk betyr at lag flytter mellom `eliteserien/index.html` og
  `obos/page/league.js`. Regresjonstesten feiler hvis et lag mangler farge
  eller en farge er igjen for et lag som ikke spiller i ligaen.

- **Vurder klubbenes egne profilmanualer.**
  Fargene i dag er Wikipedias draktmalfarger. De treffer fargen, men er ikke
  klubbenes eksakte merkevarefarger (Stabæk og Ranheim er begge «malens blå»).

- **Flytt cron-tidene når vintertiden begynner (25. oktober 2026).**
  Klokkeslettene i `.github/workflows/*.yml` er UTC og forutsetter norsk
  sommertid, så alle jobbene går en time for sent fra den datoen. Se
  kommentaren i `update-data.yml`.

## Etter sesongslutt 8. november 2026: overgangen til 2027

Kartlagt 24. september 2026. **Ikke start før sesongen er ferdigspilt.**

Ett funn avgjør rekkefølgen: **prosentene regnes ut i nettleseren fra
`model.json` og `matches.json` hver gang siden åpnes.** En frossen kopi av
datafilene er derfor ikke nok -- en senere endring i JavaScript eller i
modellen gir andre tall fra de samme dataene. Skal 2026 bevares nøyaktig slik
den var, må de **utregnede sannsynlighetene** fryses som data.

Rekkefølgen under er ikke valgfri. Bytteregelen forutsetter at frysingen
virker, og frysingen må være prøvd før den brukes på ekte.

### 1. Frysing, prøvd på 2025 først

Bygg `/eliteserien/2025/` fra `NOR.csv` som en øvelse, og sammenlign med det
siden faktisk viste i 2025. Da er metoden testet før 2026 fryses for godt.

Stabil adresse per sesong, med ferdig utregnet tabell, sannsynligheter og
treffsikkerhet som statisk data:

    eliteserien/2026/index.html
    eliteserien/2026/data/frosset.json

Disse 9 filene utgjør sesongtilstanden og må fryses: `matches.json`,
`fixtures.json`, `model.json`, `odds.json`, `odds_closing.json`,
`accuracy.json`, `history.json`, `lastmatch.json`, `keymatch.json`.

**Risikabelt.** Fryser vi for tidlig blir tallene feil for godt, og fryser vi
uten å verifisere oppdager vi det ikke før noen spør.

### 2. Automatisk oppdagelse av ny sesong

`data/sesonger.json` som autoritativ kilde:

    {"aktiv": "2026",
     "sesonger": {"2026": {"status": "aktiv", "lag": [...]},
                  "2027": {"status": "oppdaget", "lag": [...]}}}

Et ukentlig skript ser etter terminliste for `aktiv + 1` og setter status
`oppdaget`. Det **endrer ikke `aktiv`**. Enkelt: ny fil, ingen eksisterende
logikk berørt.

### 3. Bytteregel -- hendelsesdrevet, ikke kalenderdrevet

Alle tre vilkårene må være oppfylt:

1. Forrige sesong har alle 240 kamper spilt
2. Ny sesong har minst én **spilt** kamp med resultat
3. Forrige sesong er arkivert med status `frosset`

Publisering av terminlisten alene gjør ingenting, siden vilkår 2 krever spilt
kamp. 2026 er hovedsesong gjennom hele vinteren.

**Kan gå galt:** bytter for tidlig hvis en trenings- eller cupkamp havner i
`matches.json`. Må filtrere på ligakamp.

### Hardkodet 2026 som må hentes fra aktiv sesong

Python, ett symbol per fil:

    scripts/odds_compare.py:49         SEASON = 2026
    scripts/elite_closing_odds.py:45   SEASON = 2026
    scripts/prekick_odds.py:39         SEASON = 2026
    scripts/obos_results.py:54         SEASON = "2026"
    scripts/obos_closing_odds.py:97    r["sesong"] != "2026"
    scripts/fetch_odds_history.py:72   r.get("Season") == "2026"
    scripts/discover_sources.py:57     s["year"] == 2026

HTML og JS i `eliteserien/index.html`: `season: 2026` på linje 1351 og
1691/1693, `<title>` og JSON-LD på 7/20/27/36, `<h1>` på 1012, «Om siden» på
1157, FAQ-spørsmålene på 1367/1372. Forsiden: `index.html` 138 og 144.
Testene forventer «Eliteserien 2026» i `tests/regression.js` 1604-1605.

`<title>` og JSON-LD må være statiske for søkemotorer, så de skrives av
`build_league.py` fra `sesonger.json`. De øvrige tekstene kan lese
`LEAGUE.season`.

Laglisten `CANONICAL_TEAMS` i `scripts/oddslib.py:17` må oppdateres ved hvert
opp- og nedrykk.

### Backtestene skal IKKE bruke aktiv sesong

`backtest_zones.py` og `evaluate_model.py` tar eksplisitte historiske år og
skal aldri lese `current_season`. Legg en failsafe-test som håndhever det --
det er nettopp den feilen som ville ødelagt reproduserbarheten av de
publiserte tallene.

### Reserve for terminlisten

**ffksupporter.net er eneste kilde til rundenummer for Eliteserien.** Den
skrapes fra 16 sider, og sesongen står i URL-en:

    scripts/ffk_source.py:18
    BASE_URL = "https://ffksupporter.net/terminliste/2026-eliteserien/{slug}/"

Forsvinner siden, eller bytter den struktur, står vi uten terminliste. Det som
er kartlagt om alternativene:

| Kilde | Kampoppsett | Rundenummer |
|---|---|---|
| ffksupporter | hele sesongen | **ja** |
| ESPN | bare dagens kamper, ett kall per kjøring | **nei** (`espn_source.py:7`) |
| OddsPapi | 256 kamper med `startTime` | **nei**, ikke noe rundefelt |
| OBOS-løsningen | CSV i repoet | ja, `runde`-kolonne |

**Rundenummer kan ikke utledes av datoer.** Runde 12 i 2026 ble flyttet fra
juli til 24.–25. oktober, og runde 15 gikk fra 15. april til 27. juli. En
grådig gruppering på dato ville gitt runde 12 nummeret 24. Siden viser
«Runde 12 (utsatt fra juli)» eksplisitt, med egen CSS for det
(`eliteserien/index.html:872`).

**Men rundenummer er statisk per sesong.** Når kartet (hjemme, borte) → runde
først er hentet, endrer det seg aldri -- heller ikke når kamper flyttes.

**Derfor bør reserven være å hente terminlisten ÉN gang per sesong og
committe den**, slik OBOS alt gjør med sin CSV. Da er avhengigheten til
ffksupporter redusert fra daglig til årlig, og et utfall midt i sesongen gjør
ingenting. Rundeselektoren («Runde N av 30») bruker rundenummer 193 steder i
`index.html`, så det er ikke en avhengighet vi kan droppe.

Faller alt bort, er nødløsningen å gruppere på kampdag i stedet for runde
(«Kamper 9.–12. oktober»). Det er en forringelse, ikke en krise, men
rundeselektoren må da bygges om.

### Varsel når hovedkilden feiler flere dager

I dag er dette usynlig, og verre: det kan ikke skilles fra normal drift.

`data/status.json` har `{"last_checked", "ok"}`, men skrives **kun når
`update_data.py` faktisk kjører** (`scripts/update_data.py:85`).
`should_fetch.py` stopper kjøringen når det ikke er kamper på en stund. Per
25. september sier filen `last_checked: 2026-09-23` -- ikke fordi kilden er
nede, men fordi neste runde er 9. oktober.

**En foreldet `last_checked` kan altså bety «ikke forsøkt» eller «forsøkt og
feilet», og vi kan ikke se forskjell.**

Det som trengs:

- en teller som bare øker ved **reelle forsøk** som feilet, ikke når porten
  sa nei
- varsel i `$GITHUB_STEP_SUMMARY` og `::warning` etter N dager på rad, med
  hvilken kilde og hvor lenge
- `update-data.yml` har i dag verken `$GITHUB_STEP_SUMMARY` eller
  `::warning` noe sted

Samme mønster som arkiveringssteget i `update-odds.yml` bruker: jobben skal
ikke velte, men feilen skal ikke forsvinne stille heller.

