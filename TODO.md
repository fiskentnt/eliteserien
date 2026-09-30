# Ting som må gjøres på et bestemt tidspunkt

Kortere oppgaver hører hjemme i en commit, ikke her. Dette er de som må
huskes fram til en dato eller en hendelse.

## Planleggerens hemmeligheter: hvor de trekkes tilbake

Tokenet har INGEN utløpsdato, så det finnes ingen fornyingsfrist. Til
gjengjeld gjelder det til noen aktivt trekker det tilbake — og et token uten
utløp som kommer på avveie, blir liggende.

Den eksterne planleggeren (`planlegger/`) har to hemmeligheter i Cloudflare:

  GITHUB_TOKEN     fine-grained PAT, `Actions: Read and write` på
                   `fiskentnt/eliteserien` alene. Uten utløpsdato.
  UTLOSER_NOKKEL   nøkkel for manuell utløsning via headeren
                   `X-Planlegger-Nokkel`. Uten den er manuell utløsning av;
                   den planlagte kjøringen virker uansett.

### Trekke tilbake tokenet

github.com → **Settings → Developer settings → Personal access tokens →
Fine-grained tokens**. Velg tokenet og **Delete**. Der ligger også
«Last used», som er stedet å se om det fortsatt er i bruk.

Fra det øyeblikket svarer dispatch 401, og planleggeren slutter å virke uten
å si fra. Cloudflare-loggen viser det, men ingen leser den til daglig. Det
synlige tegnet er at kjøringene faller tilbake til GitHub sin egen kadens,
altså rundt fem i døgnet — og da er arkivet på kampdager nesten tomt.

### Legge inn et nytt

Lag et nytt token med samme rettigheter, og så:

    cd planlegger
    npx wrangler secret put GITHUB_TOKEN

Kommandoen spør om verdien og leser den uten å vise den. Ingen ny deploy
trengs; workeren leser hemmeligheten ved hvert kall. Slett det gamle tokenet
på GitHub etterpå, ikke før — ellers står planleggeren stille i mellomtiden.

Samme kommando med `UTLOSER_NOKKEL` bytter triggernøkkelen.


## 2. oktober 2026: første kampdag med de offisielle kildene

OBOS runde 24 åpner 2. oktober 19:00 med Ranheim mot Egersund. Det er den
første kampdagen etter kildebyttet — en uke FØR Eliteserien runde 23, så
kontrollen skal gjøres den kvelden, ikke 9. oktober.

Sandkassen kunne ikke teste dette: alle sidene ble hentet mellom runder, så
vi har aldri sett hvordan en pågående kamp ser ut i markupen. Det som er
bygget, er derfor et vern mot det ukjente, ikke mot noe vi har observert.

Ingen skal sitte og følge kampen. Arkiveringsjobben
(`.github/workflows/arkiver-kildehtml.yml`) henter NTF og NFF hvert 20.
minutt i kampvinduet 18.30–23.00 og legger gzippet HTML i
`kilde-arkiv/obos/2026-10-02/` i lab-repoet. Det er det arkivet vi leser
etterpå.

Fristen på tre timer (`RESULTAT_FRIST_TIMER` i `update_data.py`) gjør
kjøringen rød hvis et resultat mangler. Slår den ut denne kvelden, er det et
ønsket signal: produksjonen har valgt den sikre retningen, og live-statusen
mangler sannsynligvis i `KJENTE_KLASSER`.

## Sesongskiftet: hvordan det virker, og hvordan det feiler

SELVKJORENDE siden 25. september 2026. Ingen manuell redigering av
data/sesonger.json skal vaere nodvendig.

data/sesonger.json er eneste autoritet. Den skrives bare av sesong.py, leses
av frys_sesong.py og av datovakten i reconcile_ny.py.

Fire steg, alle i den daglige kjeden for begge ligaer, hver med sitt eget
skript:

  oppdag_sesong.py   Ser etter neste sesongs terminliste. Ligasiden viser
                     bare uspilte kamper, saa naar NTF publiserer neste
                     sesong og ingen er spilt, er det hele sesongen -- 240
                     kamper. Ser bare fra 1. oktober, hoyst ett forsok i
                     dognet. Sender radene til sesong.oppdag(), som
                     validerer: 16 lag, 240 kamper, 30 runder, 15 hjemme og
                     15 borte per lag, alle oppgjor, ingen duplikater,
                     riktig aarstall. Status blir "klar" bare naar alt
                     stemmer.

  frys_sesong.py     Fryser den avsluttede sesongen naar den er FERDIG, som
                     betyr tre ting: alle kamper har resultat, det har gaatt
                     14 DAGER siden siste kamp, og en revisjon mot fotball.no
                     hentet i SAMME kjoring, utfort ETTER siste kamp, har
                     ingen apne kritiske avvik.
                     Fjorten dager fordi en protest kan ta uker. MARGINEN ER
                     TRANG for Eliteserien: siste kamp 13. desember gir
                     tidligste frysing 27. desember, fem dager for byttet.
                     OBOS har 40 dager.
                     Revisjonen maa vaere utfort i SAMME KJORING, og
                     hentingen fra fotball.no maa ha lyktes i den kjoringen
                     -- ikke bare vaere ny i cachen. Feiler hentingen,
                     brukes gamle rader til kontroll, men frysingen sperres.
                     Siden fotball.no hentes hoyst en gang i dognet, er det
                     ETT kjoring per dag som kan fryse.

                     NODUTGANG etter en rettelse:
                       1. frys_sesong.py . <liga> <ses> --tin --grunn "..."
                       2. rett dataene i <liga>/<ses>/data/
                       3. frys_sesong.py . <liga> <ses> --frys-paa-nytt
                     Begrunnelsen i steg 1 er paakrevd og logges i tint.json.
                     Steg 3 reviderer og fryser i samme prosess, leser og
                     skriver BARE i <liga>/<ses>/data, og henter sesongen fra
                     sin egen turneringsadresse hos fotball.no
                     (fiksId; Eliteserien 2026 = 206092, OBOS = 206093).
                     Den gaar utenom 20-timersgrensen, fordi en manuell
                     reparasjon ikke skal stoppes av at kjeden hentet
                     tidligere samme dag.

  daglig_revisjon.py Revisjonen som frysingen venter paa.

  sesong.py bytt     Bytter aktiv sesong fra 1. januar, men bare naar neste
                     er "klar" OG gammel sesong er FROSSET. Uten frysingen
                     ville sesongen forsvunnet fra hovedsiden uten aa finnes
                     som historisk versjon. Er den ikke klar, blir gammel sesong
                     staaende, resten av kjeden fullforer, og kjoringen
                     ender rodt. Den prover igjen hver dag, saa et bytte
                     10. januar skjer ogsaa automatisk.

ETTER FRYSING er sesongen uforanderlig. update_data.py, obos_build_data.py
og daglig_revisjon.py hopper over naar sesong.er_frosset() er sann: rundt
aarsskiftet viser kildene NESTE sesong, og en revisjon ville sett avvik
overalt. Sesongen er fortsatt AKTIV til 1. januar -- frossen og aktiv er to
ulike ting.

HVORDAN DET FEILER, med vilje:

  kilden nede eller omlagt    varsel, exit 0, aktiv sesong urort
  halv terminliste            status "oppdaget", aldri "klar"
  manglende sesongautoritet   datovakten staar over, data skrives, rodt
  neste sesong ikke klar      gammel staar, data skrives, rodt
  kritisk revisjonsavvik      ingen frysing for det er lost

Testet ende-til-ende paa simulert kalender i
tests/kilder/test_sesongskifte.py: tre forlop, 52 kontroller.


## Hentelogg: hvor du ser om en kilde svikter

data/hentelogg/<maaned>/<dato>-<workflow>-<run_id>-<attempt>.jsonl, en
linje per henting:

    {"tid": "...", "liga": "obos", "kilde": "ntf-resultater",
     "utfall": "ok", "kamper": 184, "kjoring": "36094132921-1"}

utfall er ok, cache, feil eller hoppet. Skrives av kildene selv --
ligasidene, fotball.no, Wikipedia, ESPN og OddsPapi -- saa den ikke kan
glemmes.

    python3 scripts/hentelogg.py sammendrag   # utfall per kilde, 14 dogn
    python3 scripts/hentelogg.py feil         # bare det som gikk galt
    python3 scripts/hentelogg.py sjekk        # exit 1 hvis en kilde er ute

HVORFOR: tilstandsfilene husker bare SISTE utfall. Uten en historikk var det
ingenting som viste at OBOS eller fotball.no hadde feilet fem dager paa rad
-- de "feiler gront".

Har en kilde feilet tre ganger paa rad, gjor et EGET STEG TIL SLUTT i
update-data og obos-results kjoringen rod, med kildenavnet i meldingen.
Steget staar ETTER committeren: en kilde som er ute skal gjore kjoringen
rod, men aldri hindre at dagens data blir skrevet.

Et cache-treff nullstiller ikke rekken, og bare en vellykket henting fra
SAMME fysiske kilde gjor det. At en reservekilde svarer, nullstiller ikke
hovedkildens rekke -- ellers ville en hovedkilde kunnet vaere nede i en uke
uten at noe sa fra.

0 kamper er ogsaa feil: en side som svarer 200 men har lagt om markupen er
den verste feilmaaten. Ett unntak, og bare ett: en TOM TERMINLISTE er
gyldig naar resultatsiden samtidig viser en komplett ferdigspilt sesong
etter sesong.valider(). Da logges den som ok med kamper=0.

429 fra OddsPapi er ikke en kilde som er nede -- svaret sier selv hvor lenge
vi skal vente -- og logges som "hoppet". Er retryene oppbrukt, er det en
ekte feil.

EN FIL PER KJORING, ikke per dato eller workflow: to kjoringer fra ulike
checkouts som legger til i samme fil gir konflikt i git, og en rebase taper
da linjer. Det var samme feil OddsPapi-telleren hadde.

TESTENE SKRIVER ALDRI I data/. tests/conftest.py har vern(), som flytter
hentelogg, oddspapi-bruk og nff-cache til en midlertidig rot via
miljovariabler -- ogsaa for subprosesser -- og sjekk_urort(), som
sammenligner sha256 av produksjonsstiene til slutt. Dette gikk galt en gang:
testene la igjen loggfiler i produksjonsdataene, og kvotetelleren fikk tre
fakturerbare kall som aldri skjedde.

## Sesonggrensen: hvor den staar, og hvorfor

Mellom siste runde og frysingen viser ligasiden BADE fjoraaret og neste
sesong, med noyaktig de samme lagparene. Grensen laa fram til 25. september
2026 INDIREKTE i ntf_source.slaa_sammen() sin duplikatregel. Tre ting var
galt:

  1. OPPDAGELSEN VAR BLIND. Tie-breaket "raden med resultat vinner" kastet
     alle 240 neste-sesongs-radene, saa oppdag_sesong.py fant 0 kamper.
     Sesongen ble aldri "klar", og bytt() kunne aldri bytte 1. januar --
     hele det selvkjorende sesongskiftet sto paa en duplikatregel som slo
     det av.
  2. ETTER AT KILDENE FLIPPET ble neste sesongs datoer SKREVET OG PUSHET
     for kjoringen ble rod: rimelige_datoer() oppdaget det og satte
     "sesongskifte_mangler", men kontrollen laa nedenfor write_json.
  3. obos_results.py hadde ingen sesonggrense og ingen frysevakt. Et
     2027-resultat kunne bli publisert som resultatet paa en UTSATT
     2026-kamp -- dato og runde kom fra var egen terminliste, saa
     ingenting saa galt ut, og behold_eksisterende() ville holdt det for
     godt.

SLIK DET ER NAA:

  * ntf_source.slaa_sammen() nokler paa (aar, hjemme, borte). En 2026-kamp
    og en 2027-kamp mellom samme lag er to kamper. Duplikatsjekken for
    "neste kamp" innen samme sesong virker som for, og tie-breaket er
    failsafe -- ikke sesonggrensen.
  * fetch_all() returnerer ALLE sesonger den ser (480 rader i det vinduet).
    Docstringen lister alle kallere og hva hver av dem gjor.
  * reconcile_ny.bare_aktiv_sesong() setter grensen EKSPLISITT, kalt rett
    etter hentingen og for reconcile i update_data, obos_build_data og
    obos_results. Den logger antall og aar EN gang.
  * 0 aktive rader kaster FeilSesong, alltid -- ogsaa for byttedatoen.
    Kallet ligger for forste write_json, og for OBOS utenfor
    except-blokken rundt fetch_all, slik at "kilden viser feil sesong"
    aldri kan tolkes som "kilden er nede, bruk CSV-reserven".
  * "sesongskifte_mangler" behandles FOR skrivingen i begge kjeder.
  * Sesongstegene (oppdagelse, frysing, bytte) har always() i workflowene,
    slik at byttets alarm naas selv om databyggingen stopper. Uten den ble
    Sesongskifte SKIPPED, og 1. januar med ufrosset sesong ble en vranglaas.


## Etter 2. oktober, foerst av alt: kalenderfeeden

NTF har en kalenderfeed som er LAGET for automatisk bruk:

    https://www.eliteserien.no/terminliste/subscribe
    https://www.obos-ligaen.no/terminliste/subscribe

Begge svarer HTTP 200 med `text/calendar`, og hver kamp har det vi trenger:

    SUMMARY:Ranheim TF - Egersund
    DESCRIPTION: OBOS-ligaen (runde 24) ... fredag 02.10.26 19:00
    DTSTART;TZID=Europe/Oslo:20261002T190000

Altsaa lag, RUNDENUMMER, dato og avspark, i riktig tidssone. Hent dato,
avspark og runde derfra i stedet for aa skrape `/terminliste`, for begge
ligaer. Det er baade mer robust enn HTML-parsing og i traad med NTFs vilkaar,
som sier at innhold ikke skal hentes med annen teknologi enn nettstedene
eller funksjoner NTF spesifikt har laget for formaalet. En kalenderfeed er
nettopp en slik funksjon.

Feeden har IKKE resultater. Resultatsiden maa altsaa fortsatt skrapes.

AVKLART 28. september 2026: OBOS-feeden har 58 kamper mot 56 gjenstaaende
fordi to kamper staar to ganger: Raufoss - Moss og Sandnes Ulf - Haugesund
(runde 25, 11. oktober 17.00). Hver dublett er identisk bortsett fra UID og
LAST-MODIFIED (alle fire endret 27. august innenfor sju sekunder). Ellers
stemmer alle 56 med terminlisten paa runde, dato og tid, uten spilte kamper,
kvalifiseringskamper eller ukjente lagnavn. Eliteserien-feeden: 72 av 72,
ingen dubletter.

Kjeden skal derfor:
- slaa sammen identiske dubletter (samme lag, runde, dato og tid);
- feile TYDELIG hvis to oppfoeringer av samme kamp har ulik runde, dato
  eller tid -- da vet vi ikke hvilken som gjelder;
- lese bare mellom BEGIN:VEVENT og END:VEVENT. Tidssonedefinisjonen
  (VTIMEZONE) har egne DTSTART-linjer (20160301T020000 osv.), og en parser
  som leser forbi END:VEVENT, gir feil dato. Det skjedde i undersoekelsen.

## 3.–8. oktober 2026: les arkivet og legg inn de observerte statusene

FRIST: alt skal være testet og pushet FØR 9. oktober.

Les `kilde-arkiv/obos/2026-10-02/` i lab-repoet og finn ut hva kildene
FAKTISK bruker:

1. Hvilken status eller CSS-klasse NTF gir en **pågående** kamp, og hvilken
   den gir en **ferdig** kamp.
2. Hva NFF viser i resultatkolonnen mens kampen pågår.

Legg de observerte statusene inn i `KJENTE_KLASSER` i `ntf_source.py` der
det er nødvendig, og skriv testene med den arkiverte HTML-en som testdata —
ikke med oppdiktet markup slik vi måtte gjøre i september.

Det kritiske skillet: klassen for en **pågående** kamp skal gjenkjennes som
pågående, aldri som ferdig. Å legge den i `KJENTE_KLASSER` fjerner bare
«ukjent radstatus»-advarselen; den skal fortsatt ikke gi resultat. Bare
`FERDIG_KLASSE` gir resultat. Test eksplisitt, mot den arkiverte HTML-en, at
en pågående kamp med stilling på tavla ikke gir resultat i `matches.json`.

IKKE gjett på live-statusene før 2. oktober. Bruk det arkivet viser.

Kjør hele testpakken — kildetester, failsafe, regresjon — og push før
9. oktober.

## 9. oktober 2026: første reelle live-test av Eliteserie-kjeden

OBOS 2. oktober gir oss markupen, men ikke en live-test av produksjonen:
`obos-results.yml` kjører bare 07.17, altså aldri mens en kveldskamp
spilles.

Eliteserien er annerledes, og verre. `update-data.yml` kjører hvert 20.
minutt, og porten (`should_fetch.py`) slipper gjennom 105 minutter etter
avspark. For en kamp som starter 19.00 er det rundt 20.45 — omtrent på
sluttsignalet. Kjeden kan altså møte en kamp som fortsatt pågår, i
overtid eller med forsinket start, og det er nettopp det øyeblikket
vernene er bygget for.

Runde 23 åpner 9. oktober 19.00 med Brann mot Viking.

## Når den nye kjeden har stått stabilt: fjern returveien

`reconcile_gammel()` i `scripts/update_data.py` er den gamle
ffksupporter-baserte sammenslåingen. Den er død kode, beholdt bevisst som
vei tilbake. Fjern den når de offisielle kildene har kjørt gjennom noen
runder uten overraskelser — ellers blir den liggende for godt.

Samtidig: vurder om `ffk_source.py` fortsatt skal hentes. Den er nå tredje
reserve, og den hadde feil avspark på 21 kamper og feil dato på 1 i 2026.

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

- **Vurder oddsvekten (ODDS_W, i dag 70 % marked) på nytt.** Tidligst når
  prognoseloggene (`prekick.json`, `prognoselogg/`) har frosne prognoser fra
  ekte kamper med resultat. `update-odds.yml` går via planleggeren siden 28.
  september 2026, med én henting per døgn; oddsen rett før avspark kommer fra
  «Odds nær avspark».

  Bakgrunn: labens walk-forward-test (`resultater/oddsvekter_2026`, 26.
  september 2026) fant at mer marked traff bedre ved avspark, og at bare
  marked slo 70/30 (−0,0043 ± 0,0014 i log loss, 2 384 kamper). Den brukte
  sluttodds; oddsen siden blander inn er ofte eldre, og effekten av
  blandingen på sluttabellen er ikke testet.

  Test da blandingen både på enkeltkamper og på sluttabellen, med odds av
  den alderen siden faktisk bruker (tidspunktet i prognoseloggen, ikke
  sluttoddsen). Ingen endring av vekten før det er gjort.

- **odds_captured.json kan avvise sluttodds på dager med flere avspark.**
  `fetch_odds_upcoming.py` fanger en kamps siste odds før avspark når kampen
  går fra kommende til spilt, men godtar raden bare hvis filens FELLES
  `fetched_at` er fra før kampens avspark. `prekick_odds.py` setter
  `fetched_at` hver gang den oppdaterer en kamp nær avspark. Oppdateres en
  senere kamp samme dag før den tidligere er registrert som spilt, er
  `fetched_at` etter den tidligere kampens avspark, og dens sluttodds kan bli
  avvist som «hentet etter avspark», selv om raden selv (med `priced_at`) er
  fra før. Filen er bare reserve for kalibreringen (football-data.co.uk og
  OddsPapi-historikken går foran), så ingenting er endret. Rettelse når det
  passer: bruk radens egen `priced_at` når den finnes, ellers filens
  `fetched_at`. Sjekk i odds_captured.json etter første kampdag med flere
  avspark om det faktisk har skjedd.

- **Hullet i oddshentingen rett før 15 minutter før avspark.** «Odds nær
  avspark» (`prekick_odds.py`) henter pris bare mens avsparket er 15 til 60
  minutter unna, med taket ved hentetidspunktet. Kjøringene går hvert tiende
  minutt, så den siste hentingen skjer 15 til 25 minutter før avspark, og en
  pris Pinnacle setter mellom den og 15 minutter før, kommer aldri inn,
  verken i `odds_upcoming.json` eller i den frosne prognosen. Porten står
  åpen til 10 minutter før, men kjøringene 10 til 15 minutter før henter
  ingenting. Ingen endring nå (besluttet 28. september 2026).

  Etter de første kampdagene i begge ligaene (OBOS 2.–4. oktober,
  Eliteserien 9.–12. oktober): se på `minutter_for` for prisene i de frosne
  radene. Er prisene jevnt over eldre enn 20 minutter, eller endrer Pinnacle
  seg ofte i hullet, vurderer vi en henting 10 til 15 minutter før avspark
  med prisene kappet ved 15 minutter.
  - Den frosne raden i `prekick.json` har `odds.minutter_for` og
    `odds.priced_at` når prisen kom fra «Odds nær avspark» (lagt til før
    første OBOS-kampdag 2. oktober 2026; OBOS-radene fra den daglige
    hentingen har bare `priced_at`). Rader frosset før det har dem ikke; da står de i
    `odds_upcoming.json` i commiten «Odds nær avspark» fra samme kjøring
    (radens `stamp` er kjøringens hentetidspunkt):
    `git log -p -- <liga>/data/odds_upcoming.json`.
  - Om Pinnacle endret seg i hullet: sammenlign prisen i den frosne raden
    med sluttoddsen for kampen (`obos/data/odds_closing.json`,
    `eliteserien/data/odds_captured.json`), som er siste pris i hele
    vinduet 60 til 15 minutter før.
  - Innføres hentingen 10 til 15 minutter før, må skriveregelen i
    `scripts/prekick_frys.js` følge med: i dag skrives den frosne raden bare
    når oddsen ble hentet senest 15 minutter før avspark, så en slik henting
    ville ikke nådd raden.

- **Git-veksten fra grunnlagsfilen.** `grunnlag.yml` committer
  `<liga>/data/grunnlag.json` (om lag 155 KB, 64 KB komprimert for
  Eliteserien) hver gang inndataene er endret, 10–20 ganger på en kampdag.
  Anslått om lag 100 MB i historikken per år; `.git` var 5,4 MB 28.
  september 2026. Beholdes som nå (besluttet 28.9). Se på det igjen når
  `.git` passerer 500 MB (`du -sh .git`, eller størrelsen GitHub oppgir for
  repoet), for eksempel ved å flytte filen ut av historikken på main (en
  egen gren som skrives over).

- **Grunnlagsfilen på kampdager tidlig i 2027-sesongen.** Filen med svarene
  og tabellen for dagens stilling regnes med fast N = 100 000 på én maskin
  (målt 28.9.2026: 328 s for Eliteserien med 72 åpne kamper). Tiden vokser
  med antall åpne kamper og oppgaver, så ved sesongstart (om lag 240 åpne
  kamper) tar én regning langt over en time, og filen vil ofte være
  utdatert på kampdager -- da regner siden selv, som i dag. Vurder da å dele
  regningen på flere parallelle jobber (en matrise per bit av oppgavene),
  hvis filen ofte er utdatert på kampdager.

## Etter runden 9.–12. oktober 2026: egne lagsider

- **En egen adresse per lag, for eksempel `/eliteserien/valerenga/` og
  `/obos/kongsvinger/`.** Laget er valgt fra start, og siden har egen
  tittel, beskrivelse og delingsbilde for laget. Besluttet 29.9.2026: bygges
  etter runden 9.–12. oktober, ikke før. Planen:
  - **Fulle kopier**, bygget av `scripts/build_league.py` (som OBOS-siden i
    dag) og committet: GitHub Pages publiserer fra grenen og har ingen
    omskriving av adresser. En lagside er ligasiden med tre forskjeller:
    `<head>` (tittel, beskrivelse, canonical, og:url, og:title,
    og:description, og:image), laget som er valgt fra start, og datastien
    (`data/...` blir `../data/`, også i `grunnlagFil()`). Ikke `<base>`: den
    ville sendt ankrene (`#tabell` osv.) til ligasiden.
  - **Faste adresser** i ligainnstillingene, ikke regnet ut av navnet hver
    gang: `bodo-glimt`, `valerenga`, `sarpsborg-08`, `kfum-oslo` osv. Et lag
    som rykker opp eller ned, får en liten side på den gamle adressen som
    sender videre til laget i den nye ligaen (eller ligasiden), så delte
    lenker ikke gir 404.
  - **Lagvalget:** `#team=` i lenken vinner over lagsiden, som vinner over
    det lagrede valget (`followTeam`). En lagside skriver ikke over det
    lagrede valget. Bytter brukeren lag i nedtrekksmenyen, endres adressen
    til det nye lagets side med `history.replaceState`, uten ny lasting.
    `/eliteserien/#team=Vålerenga` virker som før.
  - **Tittel og beskrivelse uten dagens tall**, så lagsidene ikke må bygges
    på nytt ved hver dataoppdatering. Kort tittel med laget først (besluttet
    29.9.2026): "Vålerenga i Eliteserien 2026: sjanse for gull, Europa og
    nedrykk", og for OBOS "Kongsvinger i OBOS-ligaen 2026: sjanse for
    opprykk og nedrykk". Overskriften er "Vålerenga i Eliteserien 2026", og
    under den står én fast setning: "Her ser du Vålerengas sjanse for gull,
    Europa og nedrykk, og hva de gjenstående kampene betyr for laget." For
    OBOS: "Her ser du Kongsvingers sjanse for opprykk,
    opprykkskvalifisering og nedrykk, og hva de gjenstående kampene betyr
    for laget." Genitiv som i svarene (qaGen: "Vålerengas", men "Moss'").
    Beskrivelse og delingstekst etter samme mønster (foreslått 29.9.2026):
    "Tabellkalkulator for Vålerenga i Eliteserien: fyll inn resultater og se
    Vålerengas sjanse for gull, Europa og nedrykk. Modellen oppdateres etter
    hver kamp." og "Hvor ender Vålerenga i Eliteserien 2026?".
  - **Faste delingsbilder per lag** (lagnavn, liga, klubbfarge), laget én
    gang per sesong: 32 bilder à om lag 70 KB, 2,2 MB i git én gang. Ikke
    bilder med dagens tall: de endres hver runde, og PNG pakkes dårlig i
    git (om lag 65 MB per sesong for begge ligaene).
  - **sitemap.xml** får de 32 adressene.
  - **Kostnad**, målt 29.9.2026 med de 30 siste versjonene av
    Eliteserien-siden og 16 lagkopier: packen vokser om lag 6 KB per
    kodeendring og liga (i dag om lag 10 KB), altså om lag 1,2 MB i måneden
    med dagens tempo; nettstedet blir 13,7 MB større. Lokalt blir det mange
    løse objekter (om lag 0,7 MB per commit og liga) til git pakker dem.
  - **Grunnlagsfilen og testsiden** endres ikke: lagsidene henter
    `../data/grunnlag.json`, avtrykket er det samme, `lag_grunnlag.js`
    regner bare ligasidene, og testsiden får ingen lagsider.
  - **Tester:** failsafe sjekker at hver lagside bare skiller seg fra
    ligasiden i de merkede delene, at adressene er unike og faste, at hvert
    lag har en side, og at sitemap har alle. `regression.js` laster alle 32:
    laget er valgt, tittel, beskrivelse, canonical og delingsbilde er
    riktige, data kommer fra `../data` uten 404, grunnlagsfilen er i bruk,
    `#team=` vinner, lagbytte endrer adressen, og det lagrede valget står.
  - **Ikke nå:** programkoden i en felles fil (mindre sider og felles cache,
    men en stor omlegging: versjon i adressen, porten, testsiden, mange
    tester), og publisering fra en workflow i stedet for fra grenen (lønner
    seg først hvis vi vil ha delingsbilder med dagens tall).

## Samlet modelloppdatering 30. september 2026

- **Gjort 30.9.2026** (flyttet fram fra etter runden 9.–12. oktober, så runde 23
  i Eliteserien og runde 24 i OBOS går på den nye modellen): én samlet
  oppdatering med samme modell i begge ligaene, begrenset til tre endringer som
  alle er kjente metoder. Modellen er fortsatt under faglig gjennomgang (se
  "Modellarbeid høsten 2026"). Markedsstudien (vekt etter oddsens alder,
  prisrekkene i lab under `odds-prisrekker/`) fortsetter.
  1. **Dixon-Coles rho -0,04** overalt (detaljene under).
  2. **Shin (1993) i stedet for normering** når marginen tas ut av oddsen,
     overalt: sluttoddsen i tilpasningen og oddsen for kommende kamper.
     Stedene som gjør om odds i dag: `oddslib.devig` og de egne i
     `evaluate_model.py`, `fetch_odds_upcoming.py` (snitt over bookmakere),
     `obos_upcoming_odds.py`, `elite_closing_odds.py`, `obos_build_data.py`,
     `prekick_odds.py`, `fetch_odds_history.py`, `odds_compare.py`,
     `odds_drift.py`, `dc_rho_studie.py`.
  3. **Konsistent tilpasning:** optimeringen brukte en gradient som ikke
     samsvarte med målfunksjonen: oddsleddet var med i målfunksjonen, men
     ikke i gradienten for mu og H (`isolate_global=True`). L-BFGS-B stoppet
     derfor før et optimum: etter 8 steg i Eliteserien (største absolutte
     komponent i målfunksjonens gradient 31, for H) og 17 i OBOS (14, for mu). Rettes med
     `isolate_global=False`, så gradienten er den eksakte gradienten til
     målfunksjonen. Alle kall med `isolate_global=True`: `fit_model.py`,
     `obos_build_data.py`, `backtest_zones.py`, `evaluate_model.py`,
     `dc_rho_studie.py`, `obos_odds_weight.py` (og standardverdien i
     `fit_fast.py`).
  Prioren med tyngre haler (Student-t) er tatt UT (besluttet 30.9.2026):
  gevinsten var minst (-0,0003 og -0,0005 i log loss), og den er vanskeligst
  å begrunne som kjent metode for fotballmodeller.
- **Tallene** (studien 29.-30.9.2026, rullerende ut av utvalg 2012-2025,
  2800 kamper per liga, pakken mot siden i dag):
  - Log loss per kamp: Eliteserien -0,0136 +/- 0,0027 (5,0 SE), OBOS
    -0,0175 +/- 0,0035 (4,9 SE). Uavgjort spådd 31 -> 24 % (faktisk 24 og
    23). Favoritten spådd 46 -> 50 % og 45 -> 49 % (faktisk 53 og 54).
  - Sone-Brier: litt bedre overalt, innenfor støyen (OBOS nedrykk
    -0,0006 +/- 0,0003, 1,9 SE).
  - Kontroll på 2026 (ikke brukt til å velge noe): Eliteserien -0,0171 +/-
    0,0101 (1,7 SE, 139 kamper), OBOS -0,0217 +/- 0,0090 (2,4 SE, 154
    kamper). Små utvalg, ligaene er ikke uavhengige replikasjoner, og
    pakken er flere endringer samtidig: en uavhengig kontroll som støtter
    endringen, ikke et bevis.
  - Svakheter som står igjen og skal sies rett ut: favorittene er fortsatt
    noe undervurdert, og markedet er fortsatt bedre enn modellen per kamp
    (sluttoddsen 0,016 og 0,017 bedre i log loss, var 0,029 og 0,034).
- **Endringsloggen og forklaringen på siden** oppgir kilden for hver metode
  (forfatter og år) og kaller de praktiske valgene praktiske valg (se
  "Etter sesongslutt: gjennomgang av delene uten publisert metode").
- **Endringsloggen** på siden: utkast i rapporten 30.9.2026. Tallene regnes
  på nytt med den endelige koden, og teksten vises før commit.
- **Tekstene er lagt inn på siden** 30.9.2026 (endringsloggen som egen seksjon,
  "Endringer i modellen", og den tekniske forklaringen under "Slik fungerer
  det"; samme dag ble endringsloggen flyttet ordrett til ENDRINGER.md i
  roten, og siden har bare en kort notis uten lenke nederst i "Hvordan vet
  vi at modellen virker?"), med tallene regnet på nytt med produksjonskoden. Valideringen under
  "Hvordan vet vi at modellen virker?" er regnet på nytt for begge ligaene.
- **Etter OBOS-runden 2.-4. oktober, før runde 23 i Eliteserien:** sjekk at
  grunnlagsfilene er regnet på nytt og i bruk (GRUNNLAG_STATUS "i bruk"), at
  de frosne prognosene i `prekick.json` er laget med den nye modellen (stempel
  etter oppdateringen; treffsikkerhetsloggen teller bare rader etter
  `LOGG_START` i `scripts/accuracy_log.py`), og at uavgjort og sannsynlighetene
  i kampene ser rimelige ut. Rapporter før runde 23.
- **Rho-detaljene** (valgt 29.9.2026, tatt i bruk 30.9.2026): én `DC_RHO` ≈ -0,04 overalt
  (modellens sannsynligheter, oddstilpasningen i `fitRates()`, trekningen og
  tabellsimuleringen), i stedet for -0,38.
- **Hvorfor:** -0,38 ble valgt 20.9.2026 (commit 48e89a3) ved å justere
  uavgjortandelen i 1000 simulerte HELE sesonger (alle mot alle, dagens
  lagstyrker, formoppdatering med rekke-rampe) til 24 %. I de samme sesongene
  var snittet av lagenes målforskjell 24,3 mot 14,4 i virkeligheten:
  spredningen var for stor, og det var den som ga for få uavgjorte. rho
  rettet tallet, ikke årsaken. Tidligere samme dag ble rho tilpasset sammen
  med modellen og forkastet på log loss (0,9335 mot 0,9324). På enkeltkamper
  ut av utvalg gir -0,38 30,5 % uavgjort mot faktisk 24,0 %, og i kamper med
  odds blåser den opp målene (3,60 mot 3,08 per kamp), fordi `fitRates()` må
  bruke høye rater for å treffe oddsens uavgjortandel med så sterk tau.
  Testsiden bruker allerede rho = 0 (se kommentaren ved `DC_RHO` der).
- **Tallene** (regn dem på nytt før endringen, med dagens data):
  - Enkeltkamper, Eliteserien 2012–2025 (2798 kamper ut av utvalg): rho
    tilpasset hele resultatfordelingen er -0,04. Log loss 1,0079 → 0,9985,
    Brier 0,6025 → 0,5961, treff 50,9 → 51,6 %, uavgjort 30,5 → 24,2 %
    (faktisk 24,0), 1-0 4,3 → 8,8 % (faktisk 8,0).
    `python3 scripts/dc_rho_studie.py --liga eliteserien --csv NOR.csv`
  - OBOS 2012–2025 (2800 kamper, historikken med odds): rho -0,02, og -0,04
    er like godt. Log loss 1,0134 → 0,9993, uavgjort 30,2 → 24,0 % (faktisk
    22,6). `--liga obos` (filen ligger i det private lab-repoet, `data/`).
  - Eliteserie-tallene er regnet med NOR.csv lastet ned 25.9.2026 01:39
    (kamper til 20.9.2026, sha256 `151c7368…c67c9`, hele summen står i
    `dc_rho_studie.py`). Filen oppdateres fortløpende hos football-data.co.uk.
  - Sluttplasseringene, parvis mot dagens modell, klustret på sesong:
    Eliteserien 2016–2025 og 2012–2025 uendret (alle forskjeller under 1,1
    SE); OBOS 2012–2025 topp 6 bedre (-0,0006 ± 0,0002, 2,6 SE), opprykk og
    nedrykk uendret. `python3 scripts/backtest_zones.py --csv NOR.csv
    --seasons 2012-2025 --variants tabell,full --dc-rho-alt -0.04`
    (OBOS: `--league-zones obos --csv obos/data/obos_2012-2026.csv`).
  - Dagens sjanser flytter seg lite: Eliteserien høyst 1,7 pp (Start
    nedrykk), gull 0,6; OBOS høyst 1,4 pp (Raufoss nedrykk).
    `node scripts/dc_rho_side.js` og `--liga obos`.
  - Målnivået kalibreres IKKE: tilbaketesten sier modellen ligger 4 % under
    det faktiske, og dagens høye nivå (3,5 mål per kamp) er tidsvektingen
    (august–september 2026: 3,54 mål per kamp).
- **Tatt i bruk 30.9.2026 (gjort):** `DC_RHO` og kommentaren over den i
  `eliteserien/index.html` (OBOS bygges av den; testsiden har sin egen,
  rho = 0), standardverdien `DC_RHO` i `backtest_zones.py` og `--dc-rho` i
  `evaluate_model.py`, Brier-tabellen under "Hvordan vet vi at modellen
  virker?" regnes på nytt (raden "4. + Dixon-Coles" og teksten ved den),
  grunnlagsfilene regnes på nytt av seg selv. Sjekk testene som låser tall
  fra dagens trekning.

### Tekstene til oktoberoppdateringen (endelige, 30.9.2026)

**Endringslogg** (for brukerne):

> **Endringer i modellen, oktober 2026**
>
> Etter runde 23 har modellen fått én samlet oppdatering med tre endringer. Eliteserien og OBOS-ligaen bruker samme modell med samme innstillinger.
>
> Ikke alle deler av modellen kommer fra forskningslitteraturen. Der vi bruker egne praktiske eller empiriske valg, merker vi dem som det.
>
> **Hva er endret**
>
> - **Uavgjort (Dixon og Coles, 1997).** Modellen har en justering for kamper med få mål, fra Dixon og Coles. Styrken på justeringen ble stilt inn med en test som hadde feil oppsett. Modellen ga derfor 31 prosent sjanse for uavgjort, mens 24 prosent av kampene endte uavgjort. Styrken er nå estimert fra resultatene 2012–2025. Søket ga −0,04 i Eliteserien og −0,02 i OBOS-ligaen. Forskjellen var uten praktisk betydning i OBOS-ligaen, og vi bruker derfor −0,04 i begge ligaene.
> - **Marginen i oddsen (Shin, 1993).** Oddsen inneholder en margin for spillselskapet. Nå bruker vi Shins metode, som fordeler marginen ulikt mellom utfallene i stedet for å redusere alle tre forholdsvis like mye.
> - **En feil i beregningen av lagstyrkene er rettet.** Lagstyrkene justeres steg for steg mot det som passer best med målene og oddsen. For det generelle målnivået og hjemmefordelen ble oddsen ikke tatt med i stegene, selv om den var med i det som skulle passe best. Det kunne få beregningen til å stoppe før den hadde funnet et konsistent svar. Rettingen i seg selv endrer lite på treffsikkerheten.
>
> **Hva tilbaketesten viste**
>
> Vi spådde alle kampene i Eliteserien og OBOS-ligaen 2012–2025 på nytt, hver gang bare med kamper som var spilt før kampen: 2 800 kamper i hver liga. Styrken på uavgjort-justeringen ble valgt på de samme sesongene, og flere av modellens andre innstillinger er valgt på overlappende historikk. Dette er derfor ikke en helt uavhengig test.
>
> - Uavgjort: modellen gir nå 24 prosent i snitt, mot 31 før. I virkeligheten endte 24 prosent av kampene i Eliteserien og 23 prosent i OBOS-ligaen uavgjort.
> - Favorittene: lagene som var favoritter i markedet, vant 53 og 54 prosent av kampene. Modellen gir dem nå 50 og 49 prosent i snitt, mot 46 og 45 før.
> - Treffsikkerheten per kamp, målt som log loss (lavere er bedre), ble 0,0136 ± 0,0027 bedre i Eliteserien og 0,0175 ± 0,0035 bedre i OBOS-ligaen.
> - For sjansene for gull, topp 4, opprykk og nedrykk viste testen ingen sikker forskjell.
>
> Kampene fra 15. april i Eliteserien og fra 1. mai i OBOS-ligaen til 20. september 2026 ble ikke brukt til å velge noe av dette. Utsatte kamper fra tidligere runder er med. Hver kamp ble spådd med modellen tilpasset på kampene spilt før kampdagen. Log loss gikk fra 0,9606 til 0,9435 i Eliteserien (139 kamper) og fra 0,9973 til 0,9756 i OBOS-ligaen (154 kamper). Dette er den eneste testen der styrken på uavgjort-justeringen ikke har sett dataene. Utvalget er lite, og de tre endringene ble testet samlet, så det støtter endringen uten å bevise den.
>
> **Det som fortsatt ikke er godt nok**
>
> - Favorittene er fortsatt noe undervurdert: modellen gir dem 50 og 49 prosent, mens de vant 53 og 54.
> - Spillselskapenes sluttodds treffer fortsatt bedre enn modellen, kamp for kamp. Forskjellen er omtrent halvert, men ikke borte.
>
> **Praktiske og empiriske valg som ikke er endret**
>
> - Historiske odds inngår når lagstyrkene estimeres. Formen på dette leddet og vekten 40 er empiriske valg, ikke hentet fra en publisert fotballmodell. I de historiske rullerende testene hjelper leddet: log loss per kamp er 0,035 ± 0,003 lavere enn med mål alene i Eliteserien, og 0,035 ± 0,004 lavere i OBOS-ligaen.
> - Oddsen for neste runde blandes inn med 70 prosent vekt. Å blande prognoser lineært er en etablert metode, men vekten 0,7 er ikke målt.
> - Etter hvert simulert eller innfylt resultat justeres lagstyrkene litt. Det er en praktisk regel. I tilbaketesten for Eliteserien ga den ingen målbar forbedring.
> - Knappene som fyller inn kamper, velger et plausibelt forløp med et filter. Det påvirker ikke prosentene.
>
> (Setningene om at modellen står uendret ut sesongen er fjernet 30.9.2026 i ENDRINGER.md og på siden.)

**Den tekniske forklaringen** (for lesere som vil vite nøyaktig hvordan
modellen er bygget, også fagfolk):

> **Slik regnes sannsynlighetene**
>
> Hvert lag får en angreps- og en forsvarsstyrke, tilpasset på målene og sluttoddsen i sesongens kamper. Styrkene gir forventede mål i hver kamp som gjenstår, og av dem sjansen for hjemmeseier, uavgjort og borteseier. Så spilles resten av sesongen mange tusen ganger.
>
> Ikke alle deler av modellen kommer fra forskningslitteraturen. Delene er derfor delt i det som er hentet fra forskningslitteraturen, våre empiriske valg, tilpasningen og praktiske regler.
>
> **1. Fra forskningslitteraturen**
>
> - **Poisson-modell for mål.** Målene til hvert lag modelleres som to betinget uavhengige Poisson-fordelinger, én for hjemmelaget og én for bortelaget, med en angrepsstyrke for laget og en forsvarsstyrke for motstanderen (Maher 1982).
> - **Justering for kamper med få mål.** Sannsynlighetene for 0-0, 1-0, 0-1 og 1-1 justeres med én parameter, ρ (Dixon og Coles 1997).
> - **Tidsvekting.** Nyere kamper teller mer enn eldre, med vekter som avtar eksponentielt med alderen (Dixon og Coles 1997).
> - **Hjemmefordel per lag.** At hjemmefordelen varierer mellom lag, er vist av Clarke og Norman (1995). Hvert lag har derfor sin egen hjemmefordel, i både angrep og forsvar. Måten den er lagt inn i modellen på, er vår egen.
> - **Marginen i oddsen.** Marginen tas ut med Shins metode (Shin 1993). Štrumbelj (2014) fant i sin sammenligning at Shin-metoden samlet sett ga bedre resultater enn enkel normalisering og regresjonsmetodene som ble undersøkt.
> - **Regularisering mot et felles nivå.** Hierarkiske modeller som Baio og Blangiardo (2010) bruker samme grunnidé, at lagstyrker trekkes mot et felles nivå. Vår ridge-regularisering er ikke deres modell.
> - **Kombinasjon av prognoser.** Å kombinere prognoser som et vektet snitt er en etablert metode (Stone 1961; Bates og Granger 1969).
> - **Simulering av resten av sesongen.** Kampene som gjenstår, spilles 100 000 ganger med tilfeldige resultater fra modellen. Sannsynligheten for en plass er andelen av sesongene der laget endte der. Tallene for dagens tabell er regnet på forhånd; fyller du inn resultater selv, regner nettleseren 10 000 sesonger. Sesongsimulering med en Poisson-modell er brukt av blant andre Lee (1997).
>
> **2. Våre empiriske valg**
>
> Disse er valgt i historiske rullerende tester. Hver kamp er spådd bare med kamper spilt før den, men valgene er gjort på den samme historikken som testene bruker.
>
> - **Halveringstiden på fem uker** (35 dager) for tidsvektingen.
> - **Styrken på regulariseringen** (l1/l2 16/48). Den er valgt både på treffsikkerhet per kamp og på målforskjellen i simulerte sesonger.
> - **Oddsleddet, med vekt 40.** Lagstyrkene tilpasses både på målene og på sluttoddsen i kampene som er spilt. Vi minimerer kvadratavviket mellom modellens og markedets sannsynligheter for hjemmeseier, uavgjort og borteseier, med vekt 40 mot målene. Formen på leddet er vår egen, ikke hentet fra en publisert fotballmodell. Egidi, Pauli og Torelli (2018) kombinerer mål og odds på en beslektet måte, der vekten estimeres i modellen. Den bruker vi ikke. I de historiske rullerende testene ga leddet 0,035 ± 0,003 lavere log loss per kamp enn mål alene i Eliteserien, og 0,035 ± 0,004 lavere i OBOS-ligaen.
> - **ρ = −0,04.** Styrken på justeringen for få mål ble valgt ved å søke etter verdien som gir de faktiske resultatene 2012–2025 høyest sannsynlighet, med modellens forventede mål fra de historiske rullerende testene. Søket ga −0,04 i Eliteserien og −0,02 i OBOS. Forskjellen var uten praktisk betydning i OBOS, og vi bruker derfor −0,04 i begge ligaene. Tilbaketesten 2012–2025 bruker den samme perioden. Kampene i 2026 er den eneste testen der ρ ikke har sett dataene.
> - **70/30-blandingen for neste runde.** Der spillselskapene har lagt ut odds, blandes markedets og modellens sannsynligheter: 70 prosent marked og 30 prosent modell. Vekten 0,7 er ikke målt. Blandingen regnes om til forventede mål med en praktisk numerisk inversjon av Poisson/Dixon–Coles-modellen: et søk etter målratene som gir de blandede sannsynlighetene. Egidi, Pauli og Torelli (2018) løser et beslektet ligningssystem for ren Poisson-modell.
>
> **3. Tilpasningen**
>
> Alle parametrene estimeres samlet ved å minimere én målfunksjon som består av målene, oddsleddet og regulariseringen. Optimeringsmetoden bruker gradienten.
>
> Fram til oktober 2026 samsvarte ikke gradienten fullt med målfunksjonen: oddsleddet var med i målfunksjonen, men ikke i gradienten for det generelle målnivået og hjemmefordelen. Dette kunne få optimeringen til å stoppe før et konsistent optimum var nådd. Produksjonsmodellen for Eliteserien stoppet etter åtte steg. Den største absolutte komponenten i målfunksjonens gradient var da 31, for hjemmefordelen. Dette er rettet.
>
> (OBOS-siden: "Produksjonsmodellen for OBOS-ligaen stoppet etter 17 steg. Den største absolutte komponenten i målfunksjonens gradient var da 14, for det generelle målnivået. Dette er rettet." Målt 30.9.2026 med den gamle tilpasningen på produksjonsdataene fra før oppdateringen; den gjenskaper begge de lagrede modellene eksakt.)
>
> **4. Praktiske regler**
>
> Disse er verken hentet fra en publisert modell eller valgt i testene over. De er ikke en del av Poisson- eller Dixon–Coles-modellen.
>
> - **Bare inneværende sesong.** Styrkene tilpasses bare på kampene i inneværende sesong. Vi testet å ta med tidligere sesonger og begge divisjonene i én tilpasning med én tidsvekt, på lignende måte som Dixon og Coles (1997). Det ga ikke bedre treffsikkerhet, og mer vekt på tidligere sesonger ga dårligere.
> - **Opprykkslag starter på snittet.** Et nyopprykket lag har ingen kamper i ligaen ennå og starter derfor på ligasnittet.
> - **Samme innstillinger i begge ligaene.** OBOS-ligaen bruker innstillingene som ble valgt for Eliteserien.
> - **Ren Poisson i tilpasningen.** Justeringen for få mål brukes når sannsynlighetene regnes ut, ikke når styrkene tilpasses. Dixon og Coles estimerte alt samlet. Med ρ = −0,04 er forskjellen i treffsikkerhet liten.
> - **Formoppdatering med grenser og tilbaketrekking.** Etter hvert simulert eller innfylt resultat justeres de to lagenes styrker litt, ut fra hvor mange mål de scoret og slapp inn mot det modellen ventet. Justeringen holdes innenfor faste grenser og trekkes litt tilbake mot utgangspunktet etter hver kamp. Styrken på justeringen ble satt med én regresjon mot sluttodds, grensene ut fra én ekstremverdi og tilbaketrekkingen etter skjønn. I tilbaketesten for Eliteserien ga regelen ingen målbar forbedring av sjansene for gull, topp 4 og nedrykk. Den gjennomgås etter sesongen.
> - **Scenariofilteret.** Knappene som fyller inn kamper, trekker utfall med under 10 prosent sjanse på nytt, og forkaster sesonger med vesentlig flere eller færre overraskelser enn forventet. Det er et valg for visningen og påvirker ikke prosentene.
> - **Rangering uten innbyrdes oppgjør.** Poeng, målforskjell, scorede mål. Innbyrdes oppgjør er ikke regnet inn.
> - **Tekniske tak.** Forventede mål per lag er begrenset til 6, og det nås ikke i praksis. Resultater regnes med opptil 15 mål per lag. Omregningen fra odds søker mellom 0,15 og 4,5 forventede mål.

## Studie av tilbaketestene: walk-forward mot faste kuttpunkter (30.9.2026)

Ingen produksjonsendring, og valideringstallene på siden er ikke endret. Om
de skal erstattes, og hvordan en ny valideringsmetode i så fall forklares,
avgjøres ved sesongslutt. Skriptene og resultatfilene ligger i lab
(`walkforward/`: `wf_kamper.py`, `wf_analyse.py`, `wf_soner.py`,
`wf_soner_analyse.py`, `wf_2026.py`, og JSON med alle prediksjoner); legg
skriptene i `scripts/` hvis metoden tas i bruk. Regnetid: 20 sekunder for
enkeltkampene, 61 minutter for sonene (100 000 simuleringer, 6 kjerner).

**Metode.** Samme modell og regler gjennom hele studien (oktober-
oppdateringen: odds i tilpasningen med vekt 40 og Shin, halveringstid 35 dager,
l1/l2 16/48, konsistent tilpasning, Dixon-Coles −0,04, formoppdatering i
simuleringen). Ingen parametre er valgt ut fra resultatene.
- *Walk-forward (WF):* før hver kampdato tilpasses modellen på kampene med
  TIDLIGERE dato, og kampene den dagen predikeres (enkeltkamper), eller resten
  av sesongen simuleres (soner). Faktisk dato, så utsatte kamper står der de
  ble spilt, og ingen kamp samme dag er med i tilpasningen (kontrollert med
  `assert` i skriptene).
- *Faste kuttpunkter (FK), dagens validering:* enkeltkamper som
  `evaluate_model.py` (tilpasset etter runde 5, 10, 15, 20, 25, kuttet på
  antall kamper i datoorden, brukt på hele bolken); soner som
  `backtest_zones.py` (40, 55, 70 og 85 % av kampene). FK kan ta med kamper
  fra samme dato som den predikerte kampen i tilpasningen: 61 av 2800
  enkeltkamper i Eliteserien, 77 av 2799 i OBOS.
- *Varianter:* A modellen alene. B som siden nær avspark: neste kamp (soner:
  første runde etter punktet) blandes 0,7 sluttodds + 0,3 modell og regnes
  om med fitRates. Sluttoddsen er odds satt før kampen, tilsvarende oddsen i
  sidens frosne prognose rett før avspark; sannsynlighetene brukeren ser
  tidligere i uken bygger på oddsen som var tilgjengelig da, og kan avvike fra
  sluttoddsen (se D). Referanser: M sluttoddsen alene, F alle lag like sterke,
  tabellmodellen (soner).
- *Parvise sammenligninger* på de samme kampene/punktene og lagene;
  standardfeil klustret på sesong (2026: på kalenderuke). WF og FK har ikke de
  samme sonepunktene, så metodeforskjellen for sonene regnes per sesong og
  sammenlignes over de 14 sesongene.

**Datadekning.**
- Eliteserien: NOR.csv (football-data.co.uk), 2012–2025, 3360 seriekamper
  (kvalikkampene holdt utenfor). Odds i tilpasningen som produksjonen: BFEC,
  ellers AvgC, ellers PSC. Sluttodds i B: Pinnacle (PSC) i 2764 av 2800
  sammenlignede kamper, snittet (AvgC) i 36.
- OBOS: oddsportal-historikken i lab (snitt av sluttodds, avskrevet for hånd,
  kontrollert mot RSSSF), 2012–2025, 3360 kamper, odds for 3359. Ligger ikke i
  det offentlige repoet; OBOS-tallene kan ikke gjenskapes derfra.
- C (tidligere markedsodds): **ikke mulig**. NOR.csv har bare
  sluttoddskolonner (PSC, MaxC, AvgC, BFEC, B365C; C = closing ifølge
  football-data sin notes.txt). Kolonnene uten C (PSH, AvgH, B365H), som i
  hovedligaene er odds innhentet fredag/tirsdag ettermiddag, finnes ikke for
  Norge. Dekning i NOR.csv: PSC alle sesonger (2025: 206 av 240), MaxC/AvgC
  alle, BFEC 2024 (134) og 2025, B365C 2025 (101) og 2026. For OBOS finnes
  bare sluttodds; ingen variant med tidligere odds er laget.
- D (2026): prisrekkene i lab (Pinnacle via OddsPapi, 171 kamper i
  Eliteserien, 186 i OBOS, til 29.9). Med resultat, alle fire avlesninger og
  minst 10 kamper før: 154 i Eliteserien (6.4.–20.9.) og 174 i OBOS
  (12.4.–20.9.). **Lite utvalg, én sesong.**

**1. Enkeltkamper, 2012–2025** (samme kamper: fra runde 5, med sluttodds)

| | Eliteserien (2800) | OBOS (2799) |
|---|---|---|
| FK-A log loss / treff | 1,0004 / 51,6 % | 1,0003 / 51,9 % |
| WF-A | 0,9979 / 51,7 % | 0,9989 / 52,2 % |
| WF-A mot FK-A | −0,0024 ± 0,0007 (3,4 SE), treff +0,1 ± 0,2 pp | −0,0014 ± 0,0008 (1,7 SE), treff +0,3 ± 0,3 pp |
| WF-B (siden nær avspark) | 0,9873 / 52,4 % | 0,9855 / 53,6 % |
| WF-B mot WF-A | −0,0107 ± 0,0015 (7,0 SE), treff +0,6 pp | −0,0133 ± 0,0019 (7,1 SE), treff +1,4 pp |
| WF-B mot FK-B | −0,0003 ± 0,0002 (1,4 SE) | +0,0001 ± 0,0003 (0,2 SE) |
| Sluttodds alene mot WF-B | −0,0023 ± 0,0006 (3,5 SE) | −0,0033 ± 0,0007 (4,7 SE) |
| Kalibreringshelning H / B, WF-A | 1,12 ± 0,05 / 1,24 ± 0,08 | 1,18 ± 0,12 / 1,32 ± 0,09 |
| WF-B | 1,09 ± 0,05 / 1,16 ± 0,06 | 1,13 ± 0,09 / 1,25 ± 0,07 |
| Sluttodds alene | 1,04 ± 0,05 / 1,09 ± 0,06 | 1,06 ± 0,08 / 1,16 ± 0,06 |

Sidens tall (evaluate_model, 2016–2025, kvalikkampene med): 1998 kamper,
1,0046, 50,8 % -- gjenskapt eksakt. På de samme sesongene, uten kvalikkampene
(2000 kamper): FK-A 1,0050 / 50,7 %, WF-A 1,0018 / 50,9 %, forskjell
−0,0032 ± 0,0009 (3,7 SE), treff +0,1 pp.

Retning og størrelse: walk-forward gir litt lavere log loss enn faste
kuttpunkter for modellen alene (0,001–0,003), fordi modellen er ferskere; det
gir ingen forskjell i treffprosent, og nesten ingen for B (oddsen dominerer).
Dagens validering undervurderer altså treffsikkerheten for modellen alene
litt, men tallet på siden (modellen alene) er uansett ikke det brukeren ser
nær avspark: det er B, som er 0,011–0,013 bedre. Helningene over 1 betyr at
sannsynlighetene er for forsiktige (favoritter og bortefavoritter vinner
oftere enn modellen sier); det gjelder også B og, i mindre grad, sluttoddsen
selv.

Per fase (WF, alle kampene den dekker, 3183 / 3168): runde 1–4 er klart
vanskeligst (Eliteserien A 1,037, B 1,008; OBOS A 1,074, B 1,062), og B
hjelper mest der. Faste kuttpunkter måler ikke runde 1–4 i det hele tatt.

**2. Sonene, 2012–2025, 100 000 simuleringer per punkt**

Brier (lavere er bedre), standardfeil klustret på sesong. FK: 4 kuttpunkter
× 14 sesonger × 16 lag = 896 lag-observasjoner. WF: 1003 punkter i
Eliteserien (16 048 lag-observasjoner) og 767 i OBOS (12 272); WF 40–85 % er
de av dem som ligger i samme vindu som kuttpunktene (8 736 og 6 240).

| Eliteserien | Gull | Topp 4 | Nedrykk |
|---|---|---|---|
| FK, A | 0,0172 | 0,0587 | 0,0510 |
| WF hele sesongen, A | 0,0211 | 0,0718 | 0,0591 |
| WF 40–85 %, A | 0,0175 | 0,0605 | 0,0502 |
| WF 40–85 % minus FK, A (per sesong) | +0,0006 ± 0,0006 | +0,0021 ± 0,0011 | −0,0018 ± 0,0010 |
| A mot tabell, FK | −0,0030 ± 0,0032 | −0,0027 ± 0,0036 | −0,0057 ± 0,0021 |
| A mot tabell, WF hele sesongen | −0,0062 ± 0,0034 | −0,0095 ± 0,0044 | −0,0070 ± 0,0025 |
| B mot A, WF hele sesongen | −0,0001 ± 0,0000 | −0,0002 ± 0,0001 | −0,0002 ± 0,0000 |

| OBOS | Opprykk | Topp 6 | Nedrykk |
|---|---|---|---|
| FK, A (med odds, som produksjonen) | 0,0333 | 0,0964 | 0,0476 |
| FK, A0 (uten odds, modellen bak sidens tall) | 0,0408 | 0,1073 | 0,0491 |
| WF hele sesongen, A | 0,0433 | 0,1109 | 0,0555 |
| WF 40–85 %, A | 0,0345 | 0,1001 | 0,0464 |
| WF 40–85 % minus FK, A (per sesong) | +0,0002 ± 0,0011 | −0,0002 ± 0,0020 | −0,0000 ± 0,0011 |
| A mot tabell, FK | −0,0080 ± 0,0021 | −0,0110 ± 0,0027 | −0,0053 ± 0,0023 |
| A mot tabell, WF hele sesongen | −0,0113 ± 0,0026 | −0,0156 ± 0,0032 | −0,0066 ± 0,0026 |
| A0 mot A (odds i tilpasningen), FK | +0,0075 ± 0,0022 | +0,0110 ± 0,0021 | +0,0015 ± 0,0027 |
| B mot A, WF hele sesongen | −0,0001 ± 0,0000 | −0,0002 ± 0,0001 | −0,0003 ± 0,0001 |

Sidens OBOS-tall (FK uten odds, offentlig CSV, 100 000 simuleringer):
0,0402 / 0,1072 / 0,0484; A0 her 0,0408 / 0,1073 / 0,0491 (samme kamper og
resultater, men andre frø, og kamper samme dato i en annen rekkefølge, så
kuttet kan falle på andre kamper).

Per fase (WF, andel spilt), tabellmodell mot A: under 25 % er forskjellen
størst (Eliteserien topp 4 0,1436 mot 0,1131, gull 0,0498 mot 0,0355; OBOS
topp 6 0,1966 mot 0,1607, opprykk 0,0981 mot 0,0743). Over 85 % er A og
tabellmodellen like (gull i Eliteserien 70–85 %: A 0,0132, tabell 0,0126;
OBOS opprykk over 85 %: 0,0102 mot 0,0099).

Retning og størrelse: i samme vindu (40–85 %) gir walk-forward og faste
kuttpunkter samme Brier i begge ligaene (forskjeller høyst 0,002, innenfor
rundt 2 SE). Kuttpunktene er altså et rimelig utvalg av det vinduet. Men de
måler ikke den første delen av sesongen, der usikkerheten er størst og
modellen tilfører mest: over hele sesongen er modellens fordel over
tabellmodellen 1,2 til 3,5 ganger så stor som med kuttpunktene. Dagens
validering undervurderer derfor hva lagstyrken betyr tidlig i sesongen, ikke
treffsikkerheten i vinduet den måler. Oddsen for neste runde (B) betyr nesten
ingenting for sluttplasseringen. For OBOS validerer siden modellen uten odds,
mens produksjonen bruker odds: med odds er modellen klart bedre på opprykk og
topp 6 (3,4 og 5,3 SE), så sidens OBOS-tall beskriver en svakere modell enn
den som er i bruk.

**3. D: 2026 med oddsen slik den var tilgjengelig**

Samme kamper for alle variantene; negativ = bedre enn B med sluttodds;
SE klustret på uke (18 og 22 uker).

| | Eliteserien (154) | OBOS (174) |
|---|---|---|
| B sluttodds (60–15 min før) | 0,9198 / 57,1 % | 0,9672 / 58,0 % |
| B ordinær (siste 08.13/16.13 UTC før avspark) | +0,0018 ± 0,0023 | +0,0036 ± 0,0034 |
| B dagen før (≥ 24 t før) | +0,0106 ± 0,0035 | +0,0043 ± 0,0041 |
| B avspark | +0,0004 ± 0,0009 | −0,0013 ± 0,0009 |
| A modellen alene | +0,0243 ± 0,0068 | +0,0120 ± 0,0083 |
| Sluttodds alene | −0,0074 ± 0,0028 | −0,0009 ± 0,0035 |

Det siden viser i timene før kampen (ordinær henting), er i begge ligaene
innenfor støyen fra det som fryses rett før avspark. Dagen før er
Eliteserien-tallene tydelig dårligere (3 SE); i OBOS innenfor støyen. Modellen
er walk-forward med modellen fra oktoberoppdateringen (ikke det siden viste før 30.9,
som var den gamle modellen), med produksjonens egne odds- og kampfiler.

**Begrensninger.**
- FK og WF for sonene måler ulike deler av sesongen: WF tar med den tidlige
  delen (under 40 %), der usikkerheten er størst, så Brier-nivået er ikke
  sammenlignbart uten å se på samme vindu (derfor også WF 40–85 %).
- Observasjonene innen en sesong er sterkt avhengige (samme lag, nabodatoer),
  så all usikkerhet er klustret på sesong; 14 klynger gir grove standardfeil.
- OBOS-oddsen er snittodds, ikke Pinnacle som i produksjonen; B for OBOS er
  derfor en tilnærming.
- B bruker sluttodds: optimistisk for alt siden viser før prekick-vinduet.
- D er én sesong og lite utvalg; kalibreringshelning er ikke regnet for D.
- Modellens innstillinger er valgt på overlappende historikk (se
  inventaret), så ingen av testene er helt uavhengige.

### Markedsvekten (ODDS_W): beslutningsregel låst 30.9.2026, før vektkurven måles

Grunnlag for beslutningen om markedsvekten (punkt 7 i "Modellarbeid høsten
2026"). Ingen endring i modellen eller på siden før den er tatt; ODDS_W er 0,7.

**Hva vekten er, og hva den ikke er.** ODDS_W = 0,7 blander oddsen for
KOMMENDE kamper inn i sannsynlighetene: 0,7 odds + 0,3 modell på hjemme og
borte, regnet om til målrater med fitRates. 70 % var opprinnelig et praktisk
valg, ikke en optimalisert parameter; vekten er aldri målt (se inventaret).
Det er noe annet enn oddsleddet i TILPASNINGEN av lagstyrkene (vekt 40, med
sluttoddsen for kamper som ALT er spilt), som er valgt i historiske
rullerende tester og ikke berøres her.

**1. Kontrollsettet: 2026.** Med prisrekkene i lab (del D over, sluttodds
60–15 minutter før avspark) var markedet alene bedre enn 70/30-blandingen i
log loss med 0,0074 ± 0,0028 i Eliteserien (154 kamper) og 0,0009 ± 0,0035 i
OBOS (174 kamper, innenfor støyen). 2026 holdes adskilt fra historikken som
brukes til å velge vekt, og brukes bare til å kontrollere den valgte vekten.

**2. Beslutningsregelen (låst nå, før resten av vektkurven måles).**
- Vektene som testes: 0,0, 0,1, ..., 1,0.
- Datasett for valget: 2012–2025, walk-forward som i studien, på de samme
  kampene (fra runde 5, med sluttodds): 2800 i Eliteserien (Pinnacle, PSC,
  ellers snittet, AvgC) og 2799 i OBOS (oddsportal-snittet). Hver vekt regnes
  gjennom sidens egen vei: blanding på hjemme og borte, fitRates,
  Dixon-Coles -0,04. Vekt 1,0 er derfor oddsen gjennom fitRates, ikke
  nøyaktig "markedet alene" (M) i tabellene over; M rapporteres ved siden av.
- Regel: velg den LAVESTE vekten der log loss er høyst 0,0025 dårligere enn
  vekten med lavest log loss på samme datasett, i begge ligaene (altså den
  høyeste av de to ligaenes laveste vekt som oppfyller kravet).
- Terskelen gjelder den estimerte forskjellen, ikke statistisk signifikans.
- Den valgte vekten kontrolleres deretter på 2026 (sluttodds fra
  prisrekkene, som i del D, med alle 2026-kampene som da har prisrekker), uten
  at 2026 brukes til å velge den.

**3. Konsistensmålet, rapporteres for hver vekt.** Gjennomsnittlig største
absolutte endring i H, U eller B mellom modellen alene og blandingen, i
prosentpoeng, og andelen kamper med endring over 5 og over 10 prosentpoeng.
Det viser avveiningen mellom treffsikkerhet for neste kamp og sammenheng
mellom neste runde og resten av sesongen (der modellen alene gjelder), men
flytter ikke grensen etter at resultatene er sett.

**Hvorfor 0,0025.** Hele forbedringen fra modellen alene til markedet i
2012–2025 er 0,0129 i log loss i Eliteserien og 0,0166 i OBOS (walk-forward,
samme kamper). 0,0025 er 19 og 15 % av det, altså under en femtedel. Regelen
krever dermed at blandingen beholder minst omtrent fire femtedeler av
markedets forbedring, men tillater et lite tap i treffsikkerhet for å bevare
mer sammenheng mellom neste runde og resten av sesongen.

**Terskelen er ikke valgt i blinde.** Da den ble bestemt, var resultatene for
vekt 0 (modellen alene), 0,7 (siden i dag) og markedet alene (M) kjent:

| Log loss, 2012–2025 | Eliteserien | OBOS |
|---|---|---|
| Vekt 0 (modellen alene, A, uten fitRates) | 0,9979 | 0,9989 |
| Vekt 0,7 (B, gjennom fitRates som på siden) | 0,9873 | 0,9855 |
| Markedet alene (M) | 0,9850 | 0,9822 |
| 0,7 mot M | +0,0023 | +0,0033 |

Vi visste derfor at en toleranse på 0,0025 sannsynligvis ville gi en vekt i
nærheten av dagens 70 % i Eliteserien. I OBOS var 0,7 allerede 0,0033
dårligere enn M, altså over terskelen; der kan regelen gi en høyere vekt,
avhengig av hvor kurven har sitt minimum og av at vekt 1,0 går gjennom
fitRates. Terskelen skal ikke framstilles som et forhåndsregistrert kriterium
fra før studien startet. Poenget med å låse den nå er at de ukjente
mellomliggende vektene (0,1–0,6 og 0,8–0,9, og 1,0 gjennom fitRates) ikke skal
brukes til å flytte kriteriet etter at hele kurven er sett.

**Begrensning: oddsen i OBOS-historikken.** OBOS-historikken er snittodds fra
oddsportal, skrevet av for hånd og med større margin (median overround
1,071), mens produksjonen bruker Pinnacle. Det kan forklare noe av at 70/30
ligger 0,0033 bak markedet i OBOS mot 0,0023 i Eliteserien. I 2026, med
Pinnacle, var forskjellen i OBOS 0,0009 ± 0,0035. Hvor mye som skyldes
oddskilden og hvor mye modellen, kan ikke skilles med dataene vi har.
Regelen endres ikke av dette.

**Resultat (målt 30.9.2026 kl. 04:40:30 UTC, etter at regelen var pushet i
539f28f kl. 04:40:23 UTC).** Skript og tall i lab (`walkforward/wf_vekt.py`,
`vektkurve.json`). Log loss mot vekten med lavest log loss, SE klustret på
sesong; konsistens = snitt av største endring i H, U eller B fra modellen
alene, og andel kamper over 5 og 10 prosentpoeng.

| Vekt | Eliteserien mot beste | treff | konsistens | OBOS mot beste | treff | konsistens |
|---|---|---|---|---|---|---|
| 0,0 | +0,0130 ± 0,0022 | 51,8 % | 0,0 pp / 0 % / 0 % | +0,0167 ± 0,0026 | 52,2 % | 0,0 pp / 0 % / 0 % |
| 0,5 | +0,0046 ± 0,0011 | 52,4 % | 2,4 pp / 8 % / 0,3 % | +0,0062 ± 0,0012 | 53,1 % | 2,5 pp / 9 % / 0,5 % |
| 0,6 | +0,0033 ± 0,0009 | 52,4 % | 2,9 pp / 14 % / 0,9 % | +0,0047 ± 0,0010 | 53,4 % | 2,9 pp / 15 % / 1,1 % |
| 0,7 | +0,0023 ± 0,0006 | 52,4 % | 3,4 pp / 22 % / 1,5 % | +0,0033 ± 0,0007 | 53,6 % | 3,4 pp / 22 % / 2,3 % |
| 0,8 | +0,0014 ± 0,0004 | 52,5 % | 3,8 pp / 28 % / 3,1 % | +0,0020 ± 0,0005 | 53,6 % | 3,9 pp / 28 % / 4,4 % |
| 0,9 | +0,0006 ± 0,0002 | 52,6 % | 4,3 pp / 33 % / 5,9 % | +0,0009 ± 0,0002 | 53,4 % | 4,4 pp / 33 % / 6,5 % |
| 1,0 | beste | 52,8 % | 4,8 pp / 39 % / 8,2 % | beste | 53,5 % | 4,9 pp / 38 % / 9,0 % |

(Alle vektene 0,0–1,0 er målt; tabellen viser 0,0 og 0,5–1,0. Log loss faller
jevnt med vekten i begge ligaene, så kurven har ikke noe minimum underveis:
den beste er 1,0, oddsen alene gjennom fitRates, som er lik markedet alene
(M) på fire desimaler.)

- Laveste vekt innenfor 0,0025: Eliteserien 0,7, OBOS 0,8. **Regelen gir 0,8.**
- 0,8 mot 0,7 på 2012–2025: Eliteserien −0,0009 ± 0,0002, OBOS −0,0013 ±
  0,0002. Konsistensen: snittet av største endring øker fra 3,4 til 3,8–3,9
  prosentpoeng, andelen kamper over 10 prosentpoeng fra 1,5 til 3,1 %
  (Eliteserien) og fra 2,3 til 4,4 % (OBOS).
- Kontroll på 2026 (ikke brukt til valget; sluttodds fra prisrekkene):
  Eliteserien 0,8 mot 0,7 −0,0026 ± 0,0009 (154 kamper), OBOS −0,0004 ±
  0,0012 (174 kamper, innenfor støyen). Retningen stemmer i begge; utvalget er
  lite.
- Det er OBOS som flytter valget fra 0,7 til 0,8, og OBOS-historikken er
  oddsportal-snitt, ikke Pinnacle (se begrensningen over). Regelen endres ikke
  av det. Beslutningen tas i punkt 7 i "Modellarbeid høsten 2026"; til da er
  ODDS_W 0,7.

## Modellarbeid høsten 2026

Plan fra Trond 30.9.2026. Grensene og valgreglene under er låst før første
variant kjøres (denne teksten er committet før noe er målt).

**Status.** Dette er en ny side, og modellen er fortsatt under faglig
gjennomgang. Dokumenterer testene en klar forbedring etter kriteriene under,
kan den tas i bruk i 2026. Ingen endring gjøres automatisk som følge av
studien: funnet rapporteres først, og Trond bestemmer før eventuell
implementering og push. Tas en endring i bruk: én kort linje i notisen på
siden (for eksempel "Modellen ble justert 3. oktober etter ny
tilbaketesting") og detaljene i ENDRINGER.md; ingen tekst om framtidige
endringer. Aldri push mens oddsen fryses før avspark.

**Hovedspørsmål.** Er modellen for forsiktig fordi lagstyrkene krympes for
mye mot snittet, og kan dette forbedres ut av utvalg uten at kalibrering eller
sluttplassering blir dårligere?

**Oppsett for alle testene.**
- Walk-forward som i studien av tilbaketestene: før hver kampdato
  tilpasses modellen på kampene med tidligere dato (faktisk dato), og
  kampene den dagen predikeres. Eliteserien: NOR.csv, seriekampene
  (kvalikkampene holdt utenfor); OBOS: oddsportal-historikken i lab.
- Kampene som telles: alle kamper walk-forward dekker (minst 10 spilte kamper
  før kampdatoen) og som har sluttodds (trengs for favorittene).
  Fasene (runde 1–4 og 5 og utover) rapporteres også, men beslutningen bygger
  på alle kampene.
- Valg på 2012–2021, kontroll på 2022–2025, siste kontroll på 2026
  (produksjonens kamp- og oddsfiler, alle kamper med minst 10 spilte før).
- Hovedmål: log loss for modellen alene (Dixon–Coles −0,04 fra de tilpassede
  målratene, uten blanding med oddsen for kampen).
- Dagens modell: l1/l2 16/48, halveringstid 35 dager, oddsvekt i
  tilpasningen 40 (Shin), konsistent tilpasning, Dixon–Coles −0,04; i sonene
  også FORM_K 0,015 med dagens tak og tilbaketrekking. Én ting endres om
  gangen; resten står som i dagens modell (eller som besluttet i et tidligere
  trinn, hvis Trond har tatt en endring i bruk).

**Valgregel.** I hvert trinn velges verdien med lavest log loss på
2012–2021, med begge ligaene samlet (hver kamp teller likt). Den er kandidat
til å erstatte dagens verdi bare hvis den også har lavere log loss enn dagens
modell på 2022–2025 i BEGGE ligaene (estimert forskjell under null), og ikke
bryter noen av grensene under. Ligger beste verdi på kanten av de faste
verdiene (trinn 1, 2 og 3), dokumenteres det som et funn; det fortsettes ikke
automatisk utover kanten. Et utvidet intervall er en ny test, og verdiene
bestemmes før den kjøres. Ikke noe stort felles parameterrutenett: hver test
svarer på en konkret hypotese.

**Grensene (sekundære kontroller som kan stoppe en endring), målt på
kontrollsettet 2022–2025, i hver liga, kandidat mot dagens modell:**
- Kalibreringshelning (logistisk regresjon av utfallet på logit av
  sannsynligheten, for H og for B): avstanden til 1 kan ikke øke med mer enn
  0,03 for H eller B.
- Favorittene: favoritten i en kamp er laget (hjemme eller borte) med høyest
  sannsynlighet i sluttoddsen (Shin). Avviket er |modellens snitt for
  favorittens seier − andelen kamper favoritten vant|, i prosentpoeng. Det
  kan ikke øke med mer enn 0,5 prosentpoeng.
- Sonene: Brier (walk-forward over hele sesongen, som i studien) kan ikke bli
  mer enn 0,001 dårligere i noen sone (Eliteserien gull, topp 4, nedrykk;
  OBOS opprykk, topp 6, nedrykk).
- Egne OBOS-innstillinger (trinn 4): minst 0,002 bedre log loss enn felles
  innstillinger.

**2026 som siste kontroll.** Brukes 2026 som del av beslutningsgrunnlaget for
en endring, dokumenteres det her, og den delen av 2026 kan senere ikke
omtales som et urørt kontrollsett for den endringen.

**Gjennomføring.** Enkeltkampene kjøres for alle variantene i hvert trinn.
Sonene kjøres bare for dagens modell og varianten som vinner på
enkeltkampene (hvis den ikke er dagens), med 20 000 simuleringer og de samme
tilfeldige tallene. Resultatet fra hvert trinn dokumenteres her før neste
startes. Lange beregninger med caffeinate, aldri samtidig med regression.js.
Rapport til Trond etter trinn 1 før det går videre. Ingen modellendring,
endring på siden eller push av en modellendring før Trond har sett resultatet
og tatt stilling til det.

**Rekkefølgen, én ting om gangen med resten låst:**
1. Regularisering: dagens 16/48 mot 4/12, 8/24, 24/72 og 32/96. Tester
   hovedhypotesen direkte.
2. Halveringstid: dagens 35 dager mot 21, 28, 42 og 56. Bare en liten 2D-test
   sammen med regulariseringen hvis resultatene gir konkret grunn til å tro at
   de to har et viktig samspill.
3. Oddsvekten 40 i tilpasningen av lagstyrkene: 20, 30, 40, 50 og 60. Holdes
   helt adskilt fra markedsvekten for neste runde.
4. Felles innstillinger mot egne for OBOS, først når det er kjent hvilke
   parametre som faktisk betyr noe.
5. Tidlig sesong som diagnose: runde 1–4 undersøkes separat for etablerte lag
   og opprykkslag før noen løsning testes.
6. Formoppdateringen: FORM_K 0,015 mot 0, nøytralt. Dagens verdi har ingen
   bevismessig fordel: den kom fra én regresjon, den rullerende testen pekte
   mot 0, og ablasjonen av sonene viste ingen målbar forbedring.
7. Markedsvekten for neste runde, separat, etter den låste regelen med
   toleranse 0,0025 (se "Markedsvekten (ODDS_W)" under studien av
   tilbaketestene).

### Trinn 1: regularisering (kjørt 30.9.2026, etter at planen var pushet i 9a60f9f)

Walk-forward, modellen alene, 3183 kamper i Eliteserien og 3168 i OBOS
(2012–2025, alle med sluttodds). Skript og tall i lab (`walkforward/`:
`wf_modell.py`, `wf_modell_analyse.py`, `wf_modell_soner.py`,
`wf_modell_kontroll.py`, `trinn1/`). Negativ forskjell = bedre enn dagens.

**Valg, 2012–2021** (log loss, forskjell mot 16/48, SE klustret på sesong):

| l1/l2 | Eliteserien | OBOS | Samlet |
|---|---|---|---|
| 4/12 | +0,0005 ± 0,0006 | +0,0006 ± 0,0010 | +0,0006 ± 0,0006 |
| 8/24 | −0,0000 ± 0,0003 | +0,0000 ± 0,0006 | −0,0000 ± 0,0003 |
| 16/48 (dagens) | 1,0095 | 1,0090 | 1,0093 |
| 24/72 | +0,0006 ± 0,0002 | +0,0004 ± 0,0004 | +0,0005 ± 0,0002 |
| 32/96 | +0,0013 ± 0,0004 | +0,0009 ± 0,0007 | +0,0011 ± 0,0004 |

Lavest samlet: 8/24, ikke på kanten, men lik 16/48 på fire desimaler.

**Kontroll, 2022–2025** (904 og 911 kamper):

| l1/l2 | ES log loss mot dagens | ES helning H / B | ES favoritter modell/faktisk | OBOS log loss mot dagens | OBOS helning H / B | OBOS favoritter |
|---|---|---|---|---|---|---|
| 4/12 | −0,0001 ± 0,0007 | 1,01 / 1,11 | 51,9 / 53,9 | +0,0002 ± 0,0016 | 1,37 / 1,29 | 49,0 / 53,6 |
| 8/24 | −0,0005 ± 0,0004 | 1,06 / 1,17 | 51,6 / 53,9 | −0,0004 ± 0,0008 | 1,43 / 1,36 | 48,8 / 53,6 |
| 16/48 | (0,9812) | 1,14 / 1,26 | 51,1 / 53,9 | (1,0034) | 1,53 / 1,45 | 48,4 / 53,6 |
| 24/72 | +0,0010 ± 0,0003 | 1,20 / 1,33 | 50,7 / 53,9 | +0,0010 ± 0,0005 | 1,61 / 1,53 | 48,1 / 53,6 |
| 32/96 | +0,0021 ± 0,0005 | 1,26 / 1,39 | 50,3 / 53,9 | +0,0021 ± 0,0009 | 1,68 / 1,60 | 47,8 / 53,6 |

8/24 mot grensene (2022–2025): lavere log loss i begge ligaene (−0,0005 og
−0,0004); |helning − 1| minker med 0,08–0,10 for H og B i begge; favoritt-
avviket minker med 0,5 og 0,4 prosentpoeng.

**Sonene, 8/24 mot 16/48** (walk-forward, 20 000 simuleringer, samme tall):

| | 2012–2021 | 2022–2025 (grensen 0,001) |
|---|---|---|
| Eliteserien gull | −0,0005 ± 0,0002 | +0,0008 ± 0,0008 |
| Eliteserien topp 4 | −0,0001 ± 0,0003 | +0,0007 ± 0,0005 |
| Eliteserien nedrykk | −0,0003 ± 0,0002 | −0,0002 ± 0,0003 |
| OBOS opprykk | −0,0005 ± 0,0002 | −0,0003 ± 0,0003 |
| OBOS topp 6 | −0,0000 ± 0,0002 | +0,0004 ± 0,0006 |
| OBOS nedrykk | −0,0001 ± 0,0002 | −0,0003 ± 0,0003 |

Ingen sone er mer enn 0,001 dårligere. **8/24 oppfyller dermed de låste
kriteriene og er kandidat.**

**Siste kontroll, 2026** (produksjonens filer, 155 og 174 kamper): 8/24 mot
16/48 −0,0011 ± 0,0026 i Eliteserien og +0,0012 ± 0,0016 i OBOS, begge
innenfor støyen. Helningene nærmere 1 også her (Eliteserien H 1,43 → 1,32;
OBOS H 1,15 → 1,09, B 1,12 → 1,03), favorittavviket litt mindre. **2026 er
dermed sett for denne kandidaten**: disse kampene kan ikke senere omtales som
et urørt kontrollsett for en endring til 8/24.

**Vurdering.** Hovedhypotesen får delvis støtte: mindre krymping gjør
modellen mindre forsiktig (helningene nærmere 1, favorittene nærmere
faktisk andel), men log loss endres knapt (høyst 0,0005, innenfor støyen), og
for lite krymping (4/12) er dårligere på 2012–2021. Krympingen forklarer
altså bare en liten del av at modellen er for forsiktig: selv med 4/12 er
helningene i OBOS 1,29–1,37 på 2022–2025. Kandidaten er formelt godkjent,
men forbedringen er ikke klar; beslutningen er Tronds. Neste trinn startes
ikke før han har sett dette.

**Beslutning etter trinn 1 (Trond, 30.9.2026).** 8/24 er kandidat, og
gevinsten er kalibrering, ikke treffsikkerhet. 8/24 brukes som fast verdi i
trinn 2 og 3, men ingen endring i modellen ennå. Når trinn 1–3 er ferdige,
testes den samlede kandidaten mot dagens modell (16/48, 35 dager, oddsvekt
40) på 2022–2025 og sonene, som én pakke, før Trond tar stilling.

### Trinn 2: halveringstid, med 8/24 (kjørt 30.9.2026)

Samme kamper og regler som trinn 1; "dagens" i dette trinnet er 35 dager
med 8/24. 35 dager er kjøringen fra trinn 1 (samme innstilling).

**Valg, 2012–2021** (log loss mot 35 dager):

| Halveringstid | Eliteserien | OBOS | Samlet |
|---|---|---|---|
| 21 | +0,0000 ± 0,0003 | −0,0002 ± 0,0005 | −0,0001 ± 0,0003 |
| 28 | −0,0001 ± 0,0001 | −0,0002 ± 0,0002 | −0,0001 ± 0,0001 |
| 35 | 1,0095 | 1,0090 | 1,0093 |
| 42 | +0,0001 ± 0,0001 | +0,0002 ± 0,0001 | +0,0001 ± 0,0001 |
| 56 | +0,0002 ± 0,0002 | +0,0005 ± 0,0003 | +0,0004 ± 0,0002 |

Lavest samlet: 28 dager, ikke på kanten. Flatt: alle forskjeller er
0,0005 eller mindre.

Helning og favoritter, 2012–2021 (beskrivende): Eliteserien H 1,12 / 1,09 /
1,07 / 1,06 / 1,05 og B 1,18 / 1,16 / 1,14 / 1,13 / 1,12 for 21 / 28 / 35 /
42 / 56 dager; OBOS H 0,98–0,99 og B 1,17–1,20 for alle; favorittene 49,4–
49,6 mot faktisk 51,9 (Eliteserien) og 49,5–49,6 mot 52,1 (OBOS).

**Kontroll, 2022–2025:**

| Halveringstid | ES log loss mot 35 | ES helning H / B | ES fav. modell/faktisk | OBOS log loss mot 35 | OBOS helning H / B | OBOS fav. |
|---|---|---|---|---|---|---|
| 21 | −0,0009 ± 0,0008 | 1,11 / 1,22 | 51,4 / 53,9 | −0,0015 ± 0,0004 | 1,45 / 1,39 | 48,8 / 53,6 |
| 28 | −0,0005 ± 0,0003 | 1,08 / 1,19 | 51,6 / 53,9 | −0,0007 ± 0,0002 | 1,44 / 1,37 | 48,8 / 53,6 |
| 35 | (0,9808) | 1,06 / 1,17 | 51,6 / 53,9 | (1,0030) | 1,43 / 1,36 | 48,8 / 53,6 |
| 42 | +0,0005 ± 0,0003 | 1,05 / 1,15 | 51,6 / 53,9 | +0,0006 ± 0,0001 | 1,43 / 1,35 | 48,7 / 53,6 |
| 56 | +0,0012 ± 0,0007 | 1,04 / 1,14 | 51,6 / 53,9 | +0,0015 ± 0,0004 | 1,43 / 1,34 | 48,6 / 53,6 |

28 mot grensene (2022–2025): lavere log loss i begge ligaene (−0,0005 og
−0,0007); |helning − 1| øker med 0,016 og 0,020 (Eliteserien H og B) og
0,006 og 0,011 (OBOS), under grensen 0,03; favorittavviket +0,06 og −0,05
prosentpoeng.

**Sonene, 28 mot 35 dager** (8/24, 20 000 simuleringer, samme tall):
2022–2025: Eliteserien gull −0,0001, topp 4 −0,0004 ± 0,0001, nedrykk
−0,0002; OBOS opprykk −0,0000, topp 6 −0,0002, nedrykk −0,0001. 2012–2021:
alle innenfor ±0,0002. Ingen sone dårligere. **28 dager er kandidat.**

2026 er ikke brukt i trinn 2; den holdes til testen av den samlede pakken.

**Funn.** På kontrollsettet 2022–2025 er kortere halveringstid bedre hele
veien ned til kanten (21 dager: −0,0009 og −0,0015 ± 0,0004), mens valget på
2012–2021 er flatt og peker på 28. Det kan tyde på at nyere sesonger belønner
kortere hukommelse, men valget følger den låste regelen (28), og det
fortsettes ikke utover kanten. Kortere halveringstid gjør modellen litt mer
forsiktig (helningene øker), altså motsatt vei av 8/24.

**2D-test med regulariseringen?** Ikke kjørt. Planen sier bare ved konkret
grunn. Mulig grunn: halveringstiden og krympingen påvirker begge hvor mye data
hvert lagestimat bygger på, og de to trinnene flytter helningene i hver sin
retning. Men log loss-flaten er flat i begge trinnene, og ingenting i
resultatene viser at valget av det ene endrer seg med det andre (det er ikke
målt). Trond avgjør om en liten 2D-test (8/24 og 16/48 × 28 og 35 dager)
skal kjøres før trinn 3.

**Beslutning etter trinn 2 (Trond, 30.9.2026).** Den lille 2D-testen kjøres,
fordi begge påvirker hvor mye data hvert lagestimat bygger på, og de flytter
helningene hver sin vei. Vinneren brukes som fast verdi i trinn 3. Rapport
etter trinn 3.

### 2D-test: regularisering × halveringstid (regler låst før kjøringen)

- Kombinasjonene: 8/24 og 16/48 × 28 og 35 dager (fire; tre er kjørt i trinn
  1 og 2, den nye er 16/48 med 28 dager).
- Samme regler: valget er kombinasjonen med lavest log loss på 2012–2021,
  begge ligaene samlet. Den er kandidat bare hvis den har lavere log loss
  enn dagens modell (16/48, 35 dager) på 2022–2025 i begge ligaene og ikke
  bryter grensene (helning, favoritter) mot dagens modell.
- Sonene kjøres bare hvis den nye kombinasjonen (16/48, 28 dager) vinner, mot
  dagens modell. De andre er testet trinnvis, og den samlede pakken testes
  mot dagens modell etter trinn 3.

**Resultat (kjørt 30.9.2026, etter 5ca3911).** Log loss mot dagens modell
(16/48, 35 dager):

| l1/l2, dager | Valg 2012–2021, samlet | ES 2022–2025 | OBOS 2022–2025 | ES helning H / B | OBOS helning H / B |
|---|---|---|---|---|---|
| 16/48, 35 (dagens) | 1,0093 | (0,9812) | (1,0034) | 1,14 / 1,26 | 1,53 / 1,45 |
| 16/48, 28 | +0,0001 ± 0,0001 | −0,0001 ± 0,0003 | −0,0004 ± 0,0002 | 1,16 / 1,29 | 1,55 / 1,48 |
| 8/24, 35 | −0,0000 ± 0,0003 | −0,0005 ± 0,0004 | −0,0004 ± 0,0008 | 1,06 / 1,17 | 1,43 / 1,36 |
| 8/24, 28 | −0,0001 ± 0,0003 | −0,0010 ± 0,0003 | −0,0012 ± 0,0007 | 1,08 / 1,19 | 1,44 / 1,37 |

(Helningene er for 2022–2025.) Vinner på 2012–2021: 8/24 med 28 dager,
samme som trinnvis. Mot dagens modell på 2022–2025: lavere log loss i begge
ligaene; |helning − 1| minker med 0,06–0,09; favorittavviket minker med 0,45
og 0,43 prosentpoeng. Sonene er ikke kjørt (den nye kombinasjonen vant ikke);
den samlede pakken testes mot dagens modell etter trinn 3.

Samspillet er lite: 28 dager mot 35 hjelper litt mer med 8/24 enn med 16/48
(2022–2025: Eliteserien −0,0005 mot −0,0001, OBOS −0,0008 mot −0,0004), og med
16/48 gjør 28 dager helningene enda større. Rekkefølgen i trinnene har altså
ikke gitt et annet valg enn 2D-testen. **8/24 med 28 dager er fast verdi i
trinn 3.**

### Trinn 3: oddsvekten i tilpasningen, med 8/24 og 28 dager (kjørt 30.9.2026)

Samme kamper og regler; "dagens" i dette trinnet er vekt 40 med 8/24 og 28
dager (kjøringen fra 2D-testen). Markedsvekten for neste runde er ikke
berørt.

**Valg, 2012–2021** (log loss mot vekt 40):

| Oddsvekt | Eliteserien | OBOS | Samlet |
|---|---|---|---|
| 20 | +0,0008 ± 0,0003 | +0,0010 ± 0,0003 | +0,0009 ± 0,0002 |
| 30 | +0,0002 ± 0,0001 | +0,0003 ± 0,0001 | +0,0002 ± 0,0001 |
| 40 | 1,0094 | 1,0089 | 1,0091 |
| 50 | −0,0001 ± 0,0001 | −0,0001 ± 0,0001 | −0,0001 ± 0,0001 |
| 60 | −0,0001 ± 0,0002 | −0,0002 ± 0,0002 | −0,0001 ± 0,0001 |

Lavest samlet: 60, **på kanten** av de testede verdiene (funn; ikke
fortsatt utover kanten). Flatt fra 40 til 60.

**Kontroll, 2022–2025:**

| Oddsvekt | ES log loss mot 40 | ES helning H / B | ES fav. modell/faktisk | OBOS log loss mot 40 | OBOS helning H / B | OBOS fav. |
|---|---|---|---|---|---|---|
| 20 | +0,0006 ± 0,0003 | 1,15 / 1,27 | 51,1 / 53,9 | +0,0007 ± 0,0004 | 1,48 / 1,44 | 48,6 / 53,6 |
| 30 | +0,0001 ± 0,0002 | 1,10 / 1,22 | 51,4 / 53,9 | +0,0002 ± 0,0002 | 1,45 / 1,39 | 48,7 / 53,6 |
| 40 | (0,9803) | 1,08 / 1,19 | 51,6 / 53,9 | (1,0022) | 1,44 / 1,37 | 48,8 / 53,6 |
| 50 | +0,0000 ± 0,0001 | 1,06 / 1,17 | 51,7 / 53,9 | −0,0001 ± 0,0002 | 1,42 / 1,35 | 48,9 / 53,6 |
| 60 | +0,0001 ± 0,0003 | 1,04 / 1,15 | 51,7 / 53,9 | −0,0001 ± 0,0003 | 1,41 / 1,33 | 48,9 / 53,6 |

**60 er ikke kandidat:** log loss er ikke lavere enn 40 på 2022–2025 i
Eliteserien (+0,0001). Oddsvekten blir stående på 40. Sonene er ikke kjørt.

**Funn.** Høyere oddsvekt gjør modellen litt mindre forsiktig (helningene
nærmere 1), uten gevinst i log loss. Fasene trekker hver sin vei: i runde
1–4 er lav vekt bedre (vekt 20: −0,0017 i begge ligaene, 2012–2025), fra
runde 5 er høy vekt bedre (vekt 60: −0,0001 og −0,0003). Tas med i
diagnosen av tidlig sesong (trinn 5).

**Den samlede kandidaten etter trinn 1–3:** l1/l2 8/24, halveringstid 28
dager, oddsvekt 40 (dagens).

### Pakketesten: 8/24, 28 dager, oddsvekt 40 mot dagens modell (30.9.2026)

**Enkeltkamper, 2022–2025** (fra 2D-testen): Eliteserien −0,0010 ± 0,0003
(3,3 SE), OBOS −0,0012 ± 0,0007. Helningene H / B går fra 1,14 / 1,26 til
1,08 / 1,19 (Eliteserien) og fra 1,53 / 1,45 til 1,44 / 1,37 (OBOS);
favorittavviket minker med 0,45 og 0,43 prosentpoeng. Rundt en tidel av
gevinsten fra oktoberoppdateringen.

**Sonene** (walk-forward, 20 000 simuleringer, samme tall):

| | 2012–2021 | 2022–2025 (grensen 0,001) |
|---|---|---|
| Eliteserien gull | −0,0004 ± 0,0001 | +0,0007 ± 0,0006 |
| Eliteserien topp 4 | −0,0002 ± 0,0002 | +0,0003 ± 0,0004 |
| Eliteserien nedrykk | −0,0002 ± 0,0002 | −0,0004 ± 0,0003 |
| OBOS opprykk | −0,0002 ± 0,0001 | −0,0003 ± 0,0003 |
| OBOS topp 6 | −0,0000 ± 0,0002 | +0,0002 ± 0,0005 |
| OBOS nedrykk | −0,0002 ± 0,0002 | −0,0004 ± 0,0002 |

Ingen sone mer enn 0,001 dårligere. **Pakken oppfyller de låste kriteriene.**

**2026, siste kontroll** (produksjonens filer, 155 og 174 kamper):
Eliteserien −0,0002 ± 0,0023, OBOS +0,0009 ± 0,0015, begge innenfor støyen.
Helningene nærmere 1 (Eliteserien H 1,43 → 1,33, B 1,01 → 0,93; OBOS H 1,15
→ 1,08, B 1,12 → 1,03), favorittavviket 3,9 → 3,3 og 9,0 → 8,6 prosentpoeng.
2026 er nå sett for denne pakken (og for 8/24 alene i trinn 1).

Ingen endring i modellen: Trond tar stilling etter diagnosen av
kalibreringen (under), og en eventuell løsning for nedrykks- og opprykkslag
tas i så fall i samme endring på siden.

**Diagnose før trinn 5 (Trond, 30.9.2026; bare diagnose, ingen løsning).**
OBOS er godt kalibrert på 2012–2021 (helning H 0,98, B 1,18) men for
forsiktig på 2022–2025 (rundt 1,43 og 1,36), uansett innstilling. Undersøk om
det skyldes lag som startet på ligasnittet: nedrykkslag fra Eliteserien til
OBOS, og opprykkslag til begge ligaene. Bryt ned kalibreringshelning,
favorittavvik og log loss på etablerte lag, nedrykkslag og opprykkslag, per
periode (2012–2021 og 2022–2025) og per fase av sesongen. (2012 kan ikke
klassifiseres uten 2011-lagene i dataene.)

**Diagnosen (kjørt 30.9.2026, dagens modell 16/48, 35 dager, 40; kandidaten
ved siden av).** Lagkategori fra lagene i begge ligaene sesongen før:
etablert (samme liga året før), nedrykkslag (Eliteserien året før, nå OBOS),
opprykkslag (ligaen under året før). NOR.csv sitt "Sandnes" er
OBOS-historikkens "Sandnes Ulf"; ellers stemmer alle overgangene. 2013–2025.
Skript og tall i lab (`walkforward/wf_diagnose.py`, `diagnose.json`).

Kamper med minst ett nytt lag mot kamper mellom etablerte lag (helning H / B,
favorittene modell/faktisk):

| | Minst ett nytt lag | Begge etablerte |
|---|---|---|
| OBOS 2013–2021 | 1,04 / 1,21, 49,9 / 52,7 (1246 kamper) | 1,08 / 1,30, 47,6 / 50,5 (786) |
| OBOS 2022–2025 | **1,72 / 1,67**, 49,7 / 55,0 (473) | 1,26 / 1,12, 47,0 / 52,1 (438) |
| Eliteserien 2013–2021 | 1,16 / 1,05, 49,2 / 50,1 (571) | 1,11 / 1,26, 49,1 / 52,3 (1478) |
| Eliteserien 2022–2025 | 1,10 / **1,59**, 50,5 / 53,9 (267) | 1,15 / 1,15, 51,4 / 53,8 (637) |

Fra lagets side (sjansen for at laget vinner; helning, modellens snitt mot
andel vunnet), 2022–2025:
- OBOS: etablerte 1,15 (36,7 / 36,8), nedrykkslag **1,49** (47,7 / 51,8:
  undervurdert med 4 prosentpoeng; som favoritter −7,6), opprykkslag
  **1,36** (34,2 / 30,2: overvurdert med 4 prosentpoeng). I 2013–2021 var
  det 1,12, 1,09 og 0,84.
- Eliteserien: etablerte 1,05, opprykkslag **1,39** (33,5 / 32,6; som
  favoritter −6,7, 108 rader). I 2013–2021: 1,13 og 0,90.
- Per fase: størst i runde 16–30 for de nye lagene (OBOS nedrykkslag 1,58,
  Eliteserien opprykkslag 1,69). Runde 1–4 har for få rader for nye lag (under
  60) til å måles for seg.
- Favorittene undervurderes også blant etablerte lag, særlig sent i
  sesongen (runde 16–30: −3,0 til −6,9 prosentpoeng i alle ligaer og
  perioder).
- Log loss mot markedet: omtrent like stort gap for alle kategoriene i OBOS
  2022–2025 (+0,024 til +0,026).
- Oddsvekten: lav vekt (20) er bedre i runde 1–4 hos de etablerte lagene
  (Eliteserien −0,0030 og −0,0026, OBOS −0,0016 og −0,0047); høy vekt (60)
  er bedre sent i sesongen hos de nye lagene (OBOS nedrykkslag runde 16–30
  −0,0016, Eliteserien opprykkslag −0,0022).
- Kandidaten (8/24, 28 dager) senker helningene med 0,03–0,08 i alle
  kategoriene, uten å endre mønsteret.

**Konklusjon av diagnosen.** Den store forsiktigheten i OBOS 2022–2025 sitter
først og fremst i kampene med nye lag (1,72 / 1,67 mot 1,26 / 1,12):
nedrykkslagene er undervurdert og opprykkslagene overvurdert, som man venter
når de starter på ligasnittet. I 2013–2021 var det ikke slik. At favorittene
undervurderes (rundt 5 prosentpoeng i OBOS), gjelder derimot begge gruppene,
og er størst sent i sesongen; det forklares ikke av de nye lagene alene.
Bare diagnose; ingen løsning er testet.

**Dagens stilling med kandidaten (sammenligning i scratchpad, 30.9.2026).**
100 000 simuleringer, samme tall, som siden (kommende odds 70/30, form,
Dixon–Coles); dagens modell her gjenskaper model.json eksakt og sidens tall
innenfor 0,5 prosentpoeng. Bare én endring over to prosentpoeng: Rosenborg
topp 4 53,5 → 57,3. Gull: Bodø/Glimt 77,1 → 78,0, Viking 22,9 → 22,0.
Styrke: Bodø/Glimt 7,50 → 7,59, Viking 6,61 → 6,66. OBOS: alle endringer
under 0,7 prosentpoeng. (`walkforward/stilling_i_dag.py` og `.txt` i lab.)

### Startnivå for nye lag: data og forslag (utviklingsperioden 2012–2021, 30.9.2026)

**Beslutning etter diagnosen (Trond, 30.9.2026).** Produksjonsmodellen endres
ikke ennå; pakken 8/24, 28 dager, oddsvekt 40 beholdes som kandidat. To
problemer holdes adskilt: (1) OBOS 2022–2025 har et særskilt problem i
kamper med nye lag (nedrykkslag undervurderes, opprykkslag overvurderes);
(2) favoritter undervurderes også mellom etablerte lag. Det andre tas
senere, og de to løses ikke med samme justering. Før egne startpunkter for
nye lag bygges, testes hvor mye forrige sesong sier om styrken i ny
divisjon. Bare 2012–2021 brukes til utvikling; kontrollperioden 2022–2025
brukes ikke til å velge mellom definisjoner eller parameterverdier.
Hovedmålet er log loss ut av utvalg; kalibreringen viser hvor modellen
feiler og skal ikke presses mot 1,00.

**Observerbare mål** (ikke tilpassede lagstyrker, som alt er trukket mot
snittet): for lag *i* i liga *ℓ*, sesong *s*, med *n* seriekamper, mål for
*GF* og mot *GA*, og ligaens snitt ḡ = ΣGF / Σn mål per lag og kamp:

- a(i,s) = ln( GF/n ÷ ḡ ),  d(i,s) = ln( GA/n ÷ ḡ )

samme skala som modellens angrep (att) og forsvar (con).

**Antall lagoverganger** (ny sesong):

| Retning | 2013–2021 (utvikling) | 2022–2025 (bare telt) |
|---|---|---|
| Eliteserien → OBOS (nedrykk) | 21 | 10 |
| OBOS → Eliteserien (opprykk) | 21 | 10 |
| 2. divisjon → OBOS (opprykk) | 32 | 9 |

2012 kan ikke klassifiseres (2011 mangler). Navn: NOR.csv sitt "Sandnes" er
"Sandnes Ulf" i OBOS-historikken; ellers stemmer alle overgangene.

**Sammenheng, siste sesong i gammel divisjon mot første i ny** (2013–2021;
r med 95 % KI):

| Mål | ES → OBOS (21): gammel → ny, r | OBOS → ES (21): gammel → ny, r |
|---|---|---|
| Poeng per kamp | 0,84 → 1,82, −0,05 [−0,47, +0,39] | 2,04 → 1,13, −0,51 [−0,77, −0,09] |
| Målforskjell per kamp | −0,75 → +0,62, 0,16 [−0,29, +0,55] | +0,88 → −0,40, −0,35 [−0,68, +0,10] |
| Mål for per kamp | 1,14 → 1,87, −0,03 | 1,97 → 1,29, −0,17 |
| Mål mot per kamp | 1,89 → 1,24, 0,26 | 1,08 → 1,69, −0,21 |
| a | −0,27 → +0,19, −0,01 | +0,24 → −0,16, −0,24 |
| d | +0,24 → −0,23, 0,25 | −0,36 → +0,10, −0,16 |

Til sammenligning, lag som blir i samme liga (samme periode): Eliteserien
r 0,62 (poeng), 0,69 (målforskjell), 0,56 (a), 0,57 (d), 123 par; OBOS 0,32,
0,39, 0,21, 0,27, 91 par. Sesongen før sier altså nesten ingenting om
styrken i ny divisjon utover hvilken gruppe laget tilhører (en del av det
er at gruppene er smale: nedrykkslagene lå alle nederst). Nivåene per
gruppe er derimot tydelige.

**A (dagens regel).** Senteret for alle lag er ligasnittet:
c_att(i) = c_con(i) = 0.

**B (felles historisk startnivå per overgangstype).** For et nytt lag i
gruppe g ∈ {N: ES → OBOS, P: OBOS → ES, P2: 2. divisjon → OBOS}:
c_att(i) = ā_g, c_con(i) = d̄_g, snittet av a og d i FØRSTE sesong i ny liga
over overgangene i gruppen, 2013–2021. Etablerte lag: 0. Verdiene:

| Gruppe | n | ā_g (sd) | d̄_g (sd) | poeng per kamp mot ligasnittet |
|---|---|---|---|---|
| N: ES → OBOS | 21 | +0,186 (0,166) | −0,230 (0,222) | +0,44 |
| P: OBOS → ES | 21 | −0,155 (0,186) | +0,099 (0,222) | −0,24 |
| P2: 2. div → OBOS | 32 | −0,052 (0,184) | +0,081 (0,173) | −0,21 |

I walk-forward på utviklingsperioden regnes ā_g og d̄_g uten sesongen som
predikeres (utelat én sesong), så en sesong aldri får sine egne sluttall
som startpunkt. For kontrollperioden brukes tallene fra hele 2013–2021.

**C (overført individuell styrke, bare N og P).**
c_att(i) = ā_g + w · ( a(i, s−1) − ā_g^gammel ),
c_con(i) = d̄_g + w · ( d(i, s−1) − d̄_g^gammel ),
der ā_g^gammel og d̄_g^gammel er gruppens snitt i gammel divisjon (siste
sesong). Nivåforskjellen mellom ligaene er ā_g − ā_g^gammel og
d̄_g − d̄_g^gammel (N: +0,453 og −0,468; P: −0,393 og +0,461), fra
gruppesnittene, ikke en egen parameter. Den eneste frie parameteren er w, én
fast overføringsgrad for begge retninger og for både a og d: 0 er B, 1 er
full overføring av lagets avvik fra gruppesnittet. P2 bruker B.

w anslått på 2013–2021 som felles helning av avviket fra gruppesnittet (84
par): **w = −0,06 ± 0,13**, altså ingen påvisbar overføring. Etter regelen
(ingen tilpasning av en fleksibel funksjon, parametre fra
utviklingsperioden) blir w = 0, og C er da identisk med B.

**Tilbaketrekkingen.** To lag: (1) i C trekkes lagets individuelle avvik
mot gruppens nivå B med den faste faktoren w (her 0); (2) i tilpasningen er
senteret forventningen i ridge-straffen ½·l1·Σ[(att − c_att)² + (con −
c_con)²] (fit_fast, `senter_att` og `senter_con`), med samme l1 som for de
andre lagene. Senteret dominerer når laget har spilt få kamper, og betyr
mindre etter hvert som kampene i sesongen veier mer; det er ingen egen
nedtrapping. Hjemmefordelen (ha, hc) trekkes fortsatt mot 0.

**Forslag til walk-forward (ikke kjørt).** A mot B på kandidatpakken
(8/24, 28 dager, oddsvekt 40), enkeltkamper, modellen alene; valg på
2013–2021 (B utelatt-én-sesong); kontroll 2022–2025 med B fra hele
2013–2021; delt på nye og etablerte lag og på fase. C kjøres ikke, siden
w = 0 gjør den lik B.

**Valg og regler for testen A mot B (Trond, 30.9.2026; skrevet før testen
startet).**
- Kandidatpakken er grunnlaget: 8/24, 28 dager, oddsvekt 40. A er pakken
  med senter 0 for alle lag.
- Etablerte lag beholder senter 0 i B. Sentrene sentreres ikke for å tvinge
  snittet til 0: B skal isolert teste hypotesen om at nye lag bør trekkes
  mot et historisk nivå for overgangstypen i stedet for mot ligasnittet.
  Flyttes alle sentrene samtidig, testes også en annen endring.
- Utvikling 2013–2021: B regnes med én sesong utelatt (ā_g og d̄_g uten
  sesongen som predikeres), så ingen sesong bidrar til sitt eget startpunkt.
  Valget mellom A og B gjøres bare her: B velges hvis log loss for modellen
  alene er lavere enn A, begge ligaene samlet (hver kamp teller likt).
- Kontroll 2022–2025: B frosset fra hele 2013–2021 før perioden åpnes. Ingen
  verdier eller metodevalg justeres etter kontrollresultatet. B er kandidat
  bare med lavere log loss enn A i begge ligaene og innenfor de låste
  grensene (helning, favoritter; sonene med samme tilfeldige tall hvis B
  vinner på enkeltkampene). Deretter 2026 som siste kontroll, uten å endre
  noe.
- Rapporteres: log loss samlet og for kamper mellom etablerte lag, kamper
  med minst ett nytt lag, kamper med nedrykkslag til OBOS, opprykkslag til
  Eliteserien og opprykkslag fra 2. divisjon til OBOS, og per fase;
  helning og favorittavvik som diagnose; mu og snittet av att og con for A
  og B på representative tilpasninger (for å se at sentre ulik 0 ikke gir
  en misvisende forskyvning). Sentreringen endres ikke etter
  kontrollperioden.

**Resultat A mot B (kjørt 30.9.2026 kl. 15:27 UTC, etter at reglene var
pushet i e967d66 kl. 15:26:57).** Kandidatpakken, walk-forward, modellen
alene; B mot A (negativ = B bedre), SE klustret på sesong; helning H og B og
favorittavvik (prosentpoeng) A → B.

Utvikling 2013–2021 (B med én sesong utelatt):

| | Eliteserien | OBOS |
|---|---|---|
| Alle | −0,0004 ± 0,0006 (2049) | −0,0007 ± 0,0006 (2032) |
| Mellom etablerte lag | −0,0001 ± 0,0001 | −0,0001 ± 0,0007 |
| Minst ett nytt lag | −0,0011 ± 0,0020 (571) | −0,0012 ± 0,0008 (1246) |
| Med nedrykkslag til OBOS | – | −0,0030 ± 0,0014 (563) |
| Med opprykkslag til Eliteserien | −0,0011 ± 0,0020 (571) | – |
| Med opprykkslag fra 2. divisjon | – | −0,0000 ± 0,0012 (821) |
| Runde 1–4 / 5–15 / 16–30 | −0,0022 / −0,0005 / +0,0000 | −0,0061 / +0,0001 / −0,0005 |
| Helning H, B (alle) | 1,06 → 1,06, 1,13 → 1,12 | 0,99 → 0,97, 1,17 → 1,13 |
| Favorittavvik (alle) | 2,2 → 2,1 | 2,5 → 2,3 |

**Valget: B mot A −0,0006 ± 0,0004, begge ligaene samlet. B velges.**

Kontroll 2022–2025 (B frosset fra hele 2013–2021):

| | Eliteserien | OBOS |
|---|---|---|
| Alle | **+0,0008 ± 0,0005** (904) | −0,0002 ± 0,0013 (911) |
| Mellom etablerte lag | +0,0005 ± 0,0004 | −0,0002 ± 0,0002 |
| Minst ett nytt lag | +0,0016 ± 0,0017 (267) | −0,0001 ± 0,0023 (473) |
| Med nedrykkslag til OBOS | – | −0,0005 ± 0,0034 (270) |
| Med opprykkslag til Eliteserien | +0,0016 ± 0,0017 | – |
| Med opprykkslag fra 2. divisjon | – | +0,0029 ± 0,0031 (246) |
| Runde 1–4 / 5–15 / 16–30 | +0,0087 / +0,0001 / +0,0002 | +0,0086 / −0,0019 / −0,0003 |
| Helning H, B (alle) | 1,07 → 1,06, 1,19 → 1,17 | 1,44 → 1,38, 1,37 → 1,32 |
| Favorittavvik (alle) | 2,3 → 2,2 | 4,8 → 4,5 |

**B er ikke kandidat:** log loss er høyere enn A i Eliteserien på
kontrollperioden (+0,0008). Sonene og 2026 er derfor ikke kjørt.

**Forskyvningen.** B flytter snittet av att og con over alle lag med
−0,02 / +0,01 til +0,02 i Eliteserien og +0,01 til +0,02 / −0,01 til −0,02
i OBOS, og mu med høyst 0,01 (representative tilpasninger 2016, 2019, 2023 og
2025 etter 16, 64, 120 og 200 kamper). Etablerte lag flyttes tilsvarende litt
(rundt 0,01–0,02 på angrep og forsvar). Det er virkningen av sentrene selv,
ikke en misvisende forskyvning; sentreringen er ikke endret.

**Tolkning.** Hypotesen får støtte i utviklingsperioden, mest for
nedrykkslag i OBOS (−0,0030) og tidlig i sesongen, men gevinsten holder ikke
på kontrollperioden: i Eliteserien ga det historiske startnivået dårligere
prediksjoner for kampene med opprykkslag i 2022–2025, og B er dårligere i
runde 1–4 (+0,0087). Testen viser at det historiske nivået traff dårligere,
ikke hvorfor. B påvirker også den felles tilpasningen: selv mellom
etablerte lag i Eliteserien er B 0,0005 dårligere på kontrollperioden. Det
er ventet når mu og lagstyrkene estimeres samtidig, men viser at endringen
ikke er isolert til kampene med nye lag. Helningene og favorittavviket blir
litt bedre med B i begge perioder, men log loss er hovedmålet. Skript og
tall i lab (`walkforward/wf_start.py`, `wf_start_analyse.py`, `start/`).

**Konklusjon.** Problemet med nye lag, særlig i OBOS 2022–2025, står
fortsatt. C fikk ingen støtte i utviklingsdataene. B vant svakt i
utviklingsperioden, men feilet kontrollkravet. Ingen av dem innføres, og det
lages ikke nye varianter av startnivået (en svakere variant for å rette
runde 1–4 ville vært å trene modellen på kontrollperioden). Sonene og 2026
kjøres ikke for B. Kandidatpakken 8/24, 28 dager, oddsvekt 40 står alene.

**Parkert hypotese, ikke testet.** Klubbstørrelse kan skille nedrykkslag som
dominerer OBOS fra dem som ikke gjør det. Den er formulert etter at
kontrollperioden 2022–2025 er sett, og kan derfor bare testes på 2026 og
senere.

### Trinn 6 og 7 med kandidatpakken (regler låst før kjøringen, 30.9.2026)

Grunnlaget i begge trinnene er pakken 8/24, 28 dager, oddsvekt 40.
Beregningene kjøres med 10 arbeidere, aldri mens nettlesertestene går.

**Trinn 6: formoppdateringen, FORM_K 0,015 mot 0, nøytralt.**
- Nøytralt: ingen forhåndsfordel for dagens 0,015, som ikke har noen
  bevismessig fordel (én regresjon, den rullerende testen pekte mot 0,
  ablasjonen viste ingen målbar forbedring).
- FORM_K virker bare i simuleringen (lagstyrkene justeres etter hvert
  simulert resultat), ikke på sannsynligheten for neste kamp. Målet er derfor
  sonene: walk-forward over hele sesongen som i studien, 20 000 simuleringer,
  samme tilpasning og samme tilfeldige tall for begge verdiene på hvert
  punkt. Eliteserien gull, topp 4, nedrykk; OBOS opprykk, topp 6, nedrykk.
- Mål: Brier-snittet av de tre sonene (hver sone teller likt), per liga.
- Valg på 2012–2021: verdien med lavest Brier-snitt, begge ligaene samlet
  (hver lag-observasjon teller likt).
- Kontroll på 2022–2025: velges 0, er det kandidat bare hvis Brier-snittet
  er lavere enn med 0,015 i begge ligaene og ingen sone er mer enn 0,001
  dårligere. Velges 0,015, blir den stående. Kontrollen brukes ikke til å
  velge.

**Trinn 7: markedsvekten for neste runde på nytt, etter den låste regelen**
(539f28f), med pakkens prognoser i stedet for dagens modell: de samme
kampene (2012–2025 fra runde 5, med sluttodds, 2800 og 2799), vektene
0,0–1,0 gjennom fitRates og Dixon–Coles, laveste vekt med log loss høyst
0,0025 dårligere enn den beste i begge ligaene, konsistensmålet per vekt, og
kontroll på 2026 (pakken walk-forward på produksjonens filer, sluttodds fra
prisrekkene) uten at 2026 brukes til å velge.

## Ustabil test: resultat skrevet med tastaturet mens grunnlagsfilen holdes tilbake

Nullstill-testen i `tests/regression.js` (`nullstillGrunnlag`, scenarioet
`tastatur` med `sent = true`) tidsavbrøt i 2 av 6 fulle kjøringer 30.9.2026:
`waitForFunction` på `m.hg === 2 && m.ag === 1` gikk ut etter 20 sekunder, og
testen kom ikke videre (ingen kontroll feilet). Den gikk gjennom ved ny
kjøring begge gangene, og den skjedde også før endringen i "Hva må ... gjøre?".
Mistanke, ikke kontrollert: siden tegnes om eller flytter seg mens testen
klikker i målfeltet (grunnlagsfilen holdes tilbake), så tastetrykkene havner
utenfor feltet. Undersøk om det også kan ramme en bruker som skriver et
resultat mens siden laster, før testen gjøres robust.

## Upresise tekster under tabellen (legendNote)

Funnet i modellgjennomgangen 29. september 2026. Ikke rettet ennå. Sjekk
reglene i kildene før teksten skrives, og vis ny tekst før commit.

- **Eliteserien, Europa League-plassen.** I dag (`LEAGUE.legendNote` i
  `eliteserien/index.html`): "Europa League-plassen går til cupvinneren, ikke
  til en tabellplassering." Det stemmer bare når cupvinneren ikke alt har en
  europaplass fra tabellen. Er cupvinneren blant de fire første, går plassen
  videre nedover tabellen, og nr. 5 får da en europaplass. Hvilken plass som
  flytter hvor, skal sjekkes mot UEFAs regler for 2027/28 og Norsk Toppfotball
  før teksten skrives. Sonene på siden er ikke berørt: de regner ikke cupen.
- **OBOS, opprykkskvalifiseringen.** I dag (`legendNote` i
  `obos/page/league.js`): "Lagene på 3. til 6. plass spiller
  opprykkskvalifisering mot et lag fra Eliteserien." Kvalifiseringen er en
  stige: 5. mot 6., vinneren mot 4., vinneren mot 3., og bare den som vinner
  stigen, møter Eliteseriens nr. 14. Sjekk formatet mot NFFs reglement for
  2026 før teksten skrives. Etter endringen: `python3 scripts/build_league.py obos`.

## Etter sesongslutt: inventar over modellen, og gjennomgang av de praktiske reglene

Kartlagt 30. september 2026, ingen endringer før sesongslutt. Hver del er i
én av tre kategorier:

- **P** publisert metode (kilde oppgitt)
- **U** parameter i en publisert metode, valgt ut av utvalg
- **R** praktisk regel: verken fra en publisert modell eller valgt slik

Etter sesongslutt tas R-delene som ikke viser målbar nytte ut av utvalg.
Nytten av en R-del begrunnes bare med hva den ga i en test ut av utvalg.
Tallene er fra tilbaketesten 2012-2025 (sone-Brier klustret på sesong).
Tilstanden er slik den blir etter oktoberoppdateringen.

**Modellen for én kamp**
- P: Poisson-modell med angreps- og forsvarsstyrke per lag (Maher 1982).
- P (prinsipp): hjemmefordelen varierer mellom lag (Clarke og Norman 1995).
  R (implementasjon): ha og hc i Poisson-ratene, krympet med l2, er vår egen.
- P: tidsvekting som avtar eksponentielt (Dixon og Coles 1997).
  U: halveringstiden 35 dager, valgt på et rutenett i de historiske
  rullerende testene (log loss, Poisson-NLL og RPS; se `fit_model.py`).
  Prognosene er tidsmessig ut av utvalg, men parameteren er valgt på
  overlappende historikk. Prosedyren er dokumentert, men ble ikke skrevet
  ned før søket.
- P (prinsipp): regularisering av lagstyrkene mot et felles snitt
  (hierarkisk regularisering: Baio og Blangiardo 2010 lar lagparametrene
  komme fra en felles normalfordeling, og beskriver selv "overshrinkage",
  som de løser med en blandingsmodell; originalen er sjekket, UCL Discovery).
  Det støtter bare prinsippet, ikke vår konkrete ridge-implementasjon.
  R (implementasjon): vår regularisering (ridge-straff med faste styrker) og
  styrken l1/l2 16/48 er egen implementasjon. Styrken er valgt i de
  historiske rullerende testene på log loss og Poisson-NLL, men valget så i
  tillegg på målforskjellen i simulerte sesonger. Prognosene er tidsmessig
  ut av utvalg, men styrken er valgt på overlappende historikk (NOR.csv
  2012-2026). Fortsatt best i Eliteserien med konsistent tilpasning
  (-0,08 +/- 0,30 x 10^-3 for beste alternativ); ikke i OBOS.
- P: Dixon og Colesʼ justering for kamper med få mål (1997).
  U: rho -0,04. Valgt ved et rutenettsøk (-0,45 til 0,10, steg 0,01) som
  maksimerer sannsynligheten for det eksakte resultatet over ALLE kampene
  2012-2025 fra runde 5, med modellens rater regnet ut av utvalg
  (`dc_rho_studie.py`; Eliteserien -0,04, OBOS -0,02 med -0,04 like godt),
  og evaluert på den SAMME perioden. Valget mellom variantene ble gjort
  etter at resultatene var kjent. 2026 er den eneste testen der rho ikke
  har sett dataene. (Dagens -0,38 er R: stilt inn med en test med feil
  oppsett, se over.)
- P: tilpasning av alle parametre i én målfunksjon, med gradient som
  samsvarer med målfunksjonen (fra oktober; dagens `isolate_global` er R).
- R: ren Poisson i tilpasningen, Dixon-Coles bare i sannsynlighetene. Dixon
  og Coles estimerte rho sammen med resten. Forskjell i log loss 0,0003.
- R: bare inneværende sesong; nyopprykkede lag starter på ligasnittet.
  Dixon og Colesʼ alternativ (tidligere sesonger og begge divisjoner i én
  tilpasning, én tidsvekt) ble verre i begge ligaene ut av utvalg.
- R: OBOS bruker Eliteseriens innstillinger (halveringstid, l1/l2,
  oddsvekt, formoppdatering).

**Oddsen**
- P: marginen tas ut med Shins metode (Shin 1993; Štrumbelj 2014), fra
  oktober. Ingen parameter å velge.
- R: oddsleddet i tilpasningen: kvadratavvik mellom modellens H/U/B og
  markedssannsynlighetene i spilte kamper, vekt 40. Formen er ikke
  publisert. Publisert alternativ: Egidi, Pauli og Torelli (2018), der
  ratene er en konveks kombinasjon av historikk og odds, med vekten
  estimert i en bayesiansk modell. Vekten er valgt i de historiske
  rullerende testene (prognosene tidsmessig ut av utvalg, vekten valgt på
  overlappende historikk), og kurven er flat fra 30. Nytte i de samme
  testene (samme oppsett og rho -0,04 som pakken): log loss per kamp
  0,0348 +/- 0,0027 lavere enn bare mål i Eliteserien og 0,0349 +/- 0,0035
  i OBOS. I sonekjeden (`backtest_zones.py`, Eliteserien 2012-2025, med dagens
  rho -0,38 og l1/l2 2/6 i det steget): nedrykk -0,0055 +/- 0,0028 (2,0 SE),
  topp 4 -0,0086 +/- 0,0049.
- P (metode): lineær blanding av prognoser (Stone 1961; Bates og Granger
  1969).
  R (implementasjon): 0,7 * marked + 0,3 * modell for kamper med odds; 0,7
  er satt i første versjon og aldri validert. Ved sluttodds er beste
  vekt 1,0 (bare marked 0,0043 +/- 0,0014 bedre enn 0,7, 11 av 12 sesonger,
  lab 4051a30). I sonene flytter blandingen for neste runde nesten ingenting
  (nedrykk -0,0004 +/- 0,0002, optimistisk). Markedsstudien, tidligst 2027.
- R: `fitRates`, en praktisk numerisk inversjon av Poisson/Dixon-Coles-
  modellen (rutenettsøk etter målratene som gir de blandede H og B). Relatert
  metode: Egidi, Pauli og Torelli (2018) løser et ikke-lineært
  ligningssystem for ren Poisson (Skellam) fra 1X2-sannsynlighetene. Søket
  treffer i snitt innenfor 0,04 prosentpoeng.
- R: datakildene: sluttodds = siste pris 60-15 minutter før avspark;
  Pinnacle i tilpasningen; snittet fra The Odds API for kommende
  Eliteserie-kamper; én bookmaker for OBOS.

**Simuleringen av resten av sesongen**
- P: Monte Carlo-simulering av de gjenstående kampene (for eksempel Lee
  1997), med Dixon-Coles-trekning.
- R: formoppdateringen (`FORM_K` 0,015). Etter hver simulert eller innfylt
  kamp flyttes angrep, forsvar og hjemmefordel for begge lagene med
  k * (mål - forventede mål). Ikke en del av Dixon-Coles eller Poisson-
  modellen. Valgt ved én regresjon mot sluttodds (korrelasjon 0,067); en
  rullerende test pekte på 0. Ut av utvalg: ingen målbar nytte i sonene
  (+form mot uten: gull -0,0001 +/- 0,0003, topp 4 -0,0005 +/- 0,0004,
  nedrykk 0,0000 +/- 0,0003). Den gjør de simulerte sesongene mindre jevne.
- R: driftgrensene (0,5 og 0,35) og tilbaketrekkingen (2 % per kamp), som
  begrenser formoppdateringen. Grensene satt på én ekstremverdi med den gamle
  regulariseringen 2/6, tilbaketrekkingen etter skjønn. Ut av utvalg: uten
  en av dem er alt nesten likt, nedrykk +0,0002 +/- 0,0001 (1,7-2,1 SE).
- R: rangeringen følger reglementet, men uten innbyrdes oppgjør (under 0,1
  prosentpoeng; står på siden).
- R: tekniske sperrer: tak på målratene (6; binder aldri, høyst 4,64 av
  151 200), GMAX 15.

**Visning, ikke prognose**
- R: filteret i "plausibelt scenario" (knappene som fyller inn kamper):
  enkeltutfall under 10 % sjanse trekkes på nytt, og en sesong godtas bare
  hvis antall overraskelser (utfall under 30 %) er innenfor ett
  standardavvik (Z = 1) fra det forventede. Z ble stilt inn mens det også
  fantes et krav per runde, som senere er fjernet; nå godtas over 99 % på
  første eller andre forsøk. Det forventede antallet regnes med utfall som
  trekningen forbyr. Påvirker ikke prosentene; kan ikke testes ut av utvalg.
- R: Styrke (0-10) og Form (poeng i de fem siste kampene) er visninger.

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

  Funn fra studien av tilpasningen (29.-30. september 2026), IKKE tatt i
  bruk: på OBOS-historikken 2012-2025 (odds fra lab, rullerende ut av utvalg,
  Dixon-Coles rho -0,04, konsistent tilpasning) ga kortere halveringstid og
  svakere krymping sammen lavere log loss per kamp enn dagens 35 dager og
  l1/l2 16/48 (1,0017):

  | halveringstid | l1/l2 | log loss | mot i dag |
  |---|---|---|---|
  | 10 dager | 2/6 | 0,9992 | -2,6 +/- 1,2 (x 10^-3) |
  | 14 dager | 4/12 | 0,9993 | -2,4 +/- 0,8 |
  | 10 dager | 4/12 | 0,9995 | |
  | 21 dager | 8/24 | 1,0001 | |

  Flaten er flat langs en diagonal (kortere minne og svakere krymping
  sammen), og optimum lå i kanten av rutenettet hver gang det ble utvidet:
  først 21 dager og 8/24, så 14 dager og 4/12, så 10 dager, som var den
  korteste halveringstiden som ble prøvd. Utvidelsen ble stoppet med vilje.
  I Eliteserien er 35 dager og 16/48 fortsatt best innenfor støyen
  (-0,08 +/- 0,30 x 10^-3), så dette holder bare i én liga. Prinsippet er én
  felles modell for begge ligaene; egne OBOS-innstillinger vurderes først her,
  etter sesongslutt, med 2026 som testsett som ikke er brukt til å velge noe.
  Tallene over er dermed bare et utgangspunkt for togsettet, ikke et valg.

  Oddsvekten er ikke målt på OBOS-tall ennå. Målingen 22. september 2026
  (`scripts/obos_odds_weight.py`) regnet ratene med feil formel: hjemmelaget
  fikk +hc for motstanderen i stedet for -hc, og bortelaget manglet både -ha
  og +hc. I en kontroll med tilfeldige lagstyrker bommet H/U/B med opptil 42
  prosentpoeng. Resultatene er derfor ugyldige og skal ikke brukes. Formelen
  er rettet 29. september 2026 og gir nå samme H/U/B som tilpasningen
  (`fit_fast`) og `evaluate_model.rate_pair`.

- **Mål OBOS-oddsvekten på nytt, med det rettede skriptet.**
  `python3 scripts/obos_odds_weight.py` på hele 2026-sesongen. Sett `RHO` i
  skriptet til den verdien siden bruker da (-0,04 hvis Dixon-Coles-endringen
  er tatt i bruk, ellers -0,38). Vekten velges ut av utvalg, parvis mot 40 med
  standardfeil, som før. Bytt bare hvis forskjellen er utenfor støyen.

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

Disse 11 filene utgjør sesongtilstanden og må fryses: `matches.json`,
`fixtures.json`, `model.json`, `odds.json`, `odds_closing.json`,
`accuracy.json`, `history.json`, `lastmatch.json`, `keymatch.json`,
`prekick.json` (prognosene før avspark, som treffsikkerheten og «forrige
kamp» regnes av) og `grunnlag.json` (tabellen og svarene regnet på forhånd).

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

#### Reservekilder, kartlagt og delvis verifisert 25. september 2026

To ting er verifisert mot dataene våre, og begge holder:

**Hvert (hjemme, borte)-par møtes nøyaktig én gang per sesong.** Kontrollert
på 2022–2025: null dubletter. Paret er derfor en gyldig nøkkel for en fast
tabell (hjemmelag, bortelag) → runde.

**Runde kan ikke utledes av dato.** I 2026 er ni kamper spilt mer enn fem
dager fra rundens median, og ytterpunktene er ekstreme:

    runde  2   122 dager unna   Bodø/Glimt - HamKam
    runde 18   108 dager unna   Bodø/Glimt - Start      (spilt 30. april)
    runde 15   102 dager unna   Tromsø - Lillestrøm
    runde 17   101 dager unna   Tromsø - Brann          (spilt 29. april)

Rundenummeret følger kampen når den flyttes. Enhver utledning fra dato ville
gitt feil svar på disse ni.

**Arkitekturen som følger:** hent en fast tabell (hjemmelag, bortelag) → runde
fra en offisiell kilde én gang per sesong og committ den. Dato og avspark kan
komme fra hvilken som helst kilde og oppdateres løpende.

Kilder, i anbefalt rekkefølge:

1. **eliteserien.no/terminliste og /resultater.** Offisiell ligaside,
   rundenummer på hver kamp, rendret på serveren så vanlig HTTP holder. OBOS
   har samme format på obos-ligaen.no/terminliste. Ingen årlig ID i URL-en,
   som er den svakheten ffksupporter har. **Førstevalg.**
   Merk: kalenderfeeden (/terminliste/subscribe) har ikke runde.

2. **FotMob.** Hele sesongen som JSON i `__NEXT_DATA__` på ligasiden: runde,
   kamp-ID, UTC-avspark, resultat og status inkludert avlyst og tildelt.
   Eliteserien liga 59, OBOS liga 203. Direkte-API-et er stengt. Uoffisielt,
   så bare som reserve nummer to.

3. **NFF, fotball.no.** Offisiell og har runde, men `fiksId` endres hvert år
   -- samme svakhet som ffksupporter. Hovedterminliste-PDF finnes.

4. **API-Football. VERIFISERT UBRUKELIG på gratisnivået.** Liga-oppslaget
   virker og gir Eliteserien = 103, OBOS = 104, begge med full dekning for
   2026. Men terminlisten svarer:

       {'plan': 'Free plans do not have access to this season,
                 try from 2022 to 2024.'}

   Gratisnivået er 100 kall i døgnet, men inneværende sesong er bak
   betalingsmur. Koden finnes alt i `scripts/discover_sources.py`
   (`api_football_fixtures`, leser `f["league"]["round"]`), så den kan tas i
   bruk umiddelbart hvis vi noen gang betaler.

5. **thestatsapi.com.** Kamp-ID, dato, avspark, ingen runde. Må sjekkes om
   det er åpent og om vilkårene tillater offentlig bruk.

6. **ESPN**, som vi alt bruker. Kampoppsett uten runde, og bare dagens
   kamper.

SofaScore er sjekket og gir 403.

Siden runde bare trengs én gang per sesong, holder det at **én** av kildene
over virker i desember. Faller alle bort, er nødløsningen gruppering på
kampdag i stedet for runde, men rundeselektoren må da bygges om.

