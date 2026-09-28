# Ekstern planlegger

GitHub sin cron er sterkt strupet for dette repoet. Målt 20.–25. september
2026: `update-data` fyrte **27 av 233** planlagte luker (12 %), med median
**251 minutter** mellom kjøringer der cronen ber om 20. `update-odds` fyrte 9
av 10 luker, men 3 til 7 timer for sent. `workflow_dispatch` går umiddelbart.

Denne workeren sender derfor `workflow_dispatch` hvert tiende minutt.

    Cloudflare Worker (cron)  ->  workflow_dispatch  ->  GitHub Actions
                                                          -> porter og scripts

GitHub er fortsatt eneste produksjonsmiljø. Workeren regner ikke ut noe og
lagrer ingenting. GitHub sin egen `schedule` beholdes parallelt som reserve.

## Workeren er dum med vilje

Den kjenner ikke kampvinduer, porter eller kvoter. Den sender `planlagt=true`
og lar repoet bestemme:

| Workflow | Hva `planlagt=true` gjør |
|---|---|
| `update-data.yml` | `should_fetch.py` avgjør som ved schedule |
| `obos-results.yml` | `should_fetch.py obos` avgjør — sparer OddsPapi-kvoten |
| `arkiver-kildehtml.yml` | kampvinduet i `arkiver_kildehtml.py` avgjør |
| `prekick-odds.yml` | vinduet 15–60 minutter før avspark i `prekick_odds.py` avgjør |
| `update-odds.yml` | tidsporten i `should_fetch_odds.py` avgjør: The Odds API kalles høyst hver 12. time (over 48 t til neste avspark), hver 4. (6–48 t) eller hver time (under 6 t), med én time sperre etter et mislykket forsøk og budsjettvakt (under 100 + 4 kreditter per gjenstående dag: hver 12. time) |

En manuell kjøring **uten** flagget tvinger fortsatt henting, som før.

All kunnskap ligger dermed i repoet, der den har tester. Legger vi
vinduslogikk i workeren, får vi to steder å holde i synk og ett av dem uten
tester.

## Oppsett

Alt under gjør du selv. Ingen av hemmelighetene skal limes inn i en chat, i
koden, i `wrangler.toml` eller i git.

### 1. Fine-grained GitHub-token

På github.com: **Settings → Developer settings → Personal access tokens →
Fine-grained tokens → Generate new token**.

| Felt | Verdi |
|---|---|
| Resource owner | `fiskentnt` |
| Expiration | sett en dato, og skriv den i `TODO.md` |
| Repository access | **Only select repositories** → `fiskentnt/eliteserien` |
| Permissions → Repository → **Actions** | **Read and write** |
| Alt annet | **No access** |

`Actions: Read and write` er det minste som finnes for `workflow_dispatch` —
GitHub har ingen egen «bare dispatch»-rettighet. Ingen `contents`, ingen
`metadata` utover det GitHub legger til selv.

### 2. Cloudflare-konto

Gratis konto på dash.cloudflare.com hvis du ikke har en. Ingen kortopplysninger
trengs for Workers på gratisnivået.

### 3. Nøkkel for manuell utløsning

Lag en tilfeldig streng og legg den i en fil bare du kan lese:

    umask 077
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.tabellkalkulator-utloser
    chmod 600 ~/.tabellkalkulator-utloser

Filen brukes av curl-kommandoen nederst, så nøkkelen aldri skrives i
terminalen.

### 4. Logg inn og legg inn hemmelighetene

    cd planlegger
    npx wrangler login

    npx wrangler secret put GITHUB_TOKEN
    # limer du inn tokenen fra steg 1 når den spør

    npx wrangler secret put UTLOSER_NOKKEL
    # lim inn innholdet i ~/.tabellkalkulator-utloser

`wrangler secret put` spør om verdien og leser den uten å vise den. Gi den
aldri som argument på kommandolinjen — da havner den i terminalhistorikken
og i prosesslisten mens den kjører.

### 5. Publiser

    npx wrangler deploy

Adressen skrives ut til slutt, på formen
`https://tabellkalkulator-planlegger.<ditt-subdomene>.workers.dev`. Den står
også under **Workers & Pages** i Cloudflare-panelet.

### 6. Kontroller at den virker

Åpner du adressen i nettleseren, svarer den bare «Ingenting å se her». Det er
med vilje.

Manuell utløsning krever nøkkelen i headeren `X-Planlegger-Nokkel`:

    ADR=https://tabellkalkulator-planlegger.<ditt-subdomene>.workers.dev
    curl -sS -X POST "$ADR/?kjor=1" \
      -H "X-Planlegger-Nokkel: $(cat ~/.tabellkalkulator-utloser)"

Nøkkelen leses fra filen, så den står ikke i kommandoen. Vil du heller skrive
den inn for hånd, uten at den vises eller lagres:

    read -rs -p "Nøkkel: " N; echo
    curl -sS -X POST "$ADR/?kjor=1" -H "X-Planlegger-Nokkel: $N"; unset N

Svaret er en linje per workflow med `"ok": true` når GitHub godtok
utløsningen. Alt annet enn riktig nøkkel gir `404 Ikke funnet` — det samme
svaret enten headeren manglet, var feil, eller hemmeligheten ikke er satt.
Nøkkelen sendes aldri i URL-en: en query-streng havner i Cloudflare-loggen,
i referrer-headeren og i nettleserhistorikken.

Til slutt: sjekk i Actions at kjøringene dukker opp som `workflow_dispatch`,
og at portene stopper dem når det ikke er noe å gjøre.

## Dødmannsknapp (healthchecks.io)

Varsel når noe har vært galt en stund, uten åpen økt, Mac eller GitHub sin
cron. Tre sjekker hos healthchecks.io, hver med sin hemmelige ping-adresse.
Hver av dem får et livstegn bare når alt gikk bra; feiler en runde eller en
kjøring, sendes ingenting. Kommer det ikke livstegn innenfor tidsplanen pluss
slingringsmonnet, sender healthchecks e-post.

| Sjekk | Livstegn når | Hemmelighet |
|---|---|---|
| `tabellkalkulator-planlegger` | workeren fikk 204 fra GitHub for alle utløsningene i en planlagt runde | `HEALTHCHECK_URL` i Cloudflare |
| `tabellkalkulator-update-data` | en kjøring av `update-data.yml` er grønn (siste steg) | `HEALTHCHECK_UPDATE_DATA` i GitHub |
| `tabellkalkulator-obos-results` | en kjøring av `obos-results.yml` er grønn (siste steg) | `HEALTHCHECK_OBOS` i GitHub |

Adressene er hemmeligheter: den som har dem, kan sende falske livstegn og
skjule et stopp. De skal aldri i koden, `wrangler.toml`, git eller en chat.
Mangler en hemmelighet, sendes det ikke livstegn, og ingenting annet endres.
Et livstegn som ikke kommer fram, kan aldri gjøre en kjøring rød.

### Oppsett hos healthchecks.io

1. Gratis konto på healthchecks.io (20 sjekker og e-post er gratis).
2. For HVER av de tre sjekkene over: **Add Check**, navn som i tabellen,
   **Schedule → Cron**, uttrykket `*/10 9-21 * * *`, tidssone **UTC**,
   **Grace time 60 minutter**. Utenfor 09-21 UTC venter den ingen livstegn,
   så natten gir ikke varsel.
3. **Integrations → Email**: la «Notify when a check goes **down**» stå på,
   og skru **av** «Notify when a check goes **up**». Du får da e-post når en
   sjekk har vært uten livstegn i om lag en time, og ikke når den kommer
   tilbake.
4. Kopier ping-adressen til hver sjekk (`https://hc-ping.com/<uuid>`).

### Hemmelighetene

    # Cloudflare (planleggeren), fra planlegger/:
    npx wrangler secret put HEALTHCHECK_URL
    # lim inn adressen til tabellkalkulator-planlegger når den spør

    # GitHub (jobbene), fra repo-roten:
    gh secret set HEALTHCHECK_UPDATE_DATA
    gh secret set HEALTHCHECK_OBOS
    # hver av dem spør om verdien og leser den uten å vise den

Eller på github.com: **Settings → Secrets and variables → Actions → New
repository secret**. Gi aldri verdien som argument på kommandolinjen.

### Publiser og kontroller

    cd planlegger && npx wrangler deploy

Koden i repoet og den publiserte workeren skal være like. Etter 10-20
minutter (innenfor vinduet) skal alle tre sjekkene stå som «up» med livstegn
hvert tiende minutt. «Send test notification» i healthchecks viser at
e-posten kommer fram.

Dette fanger at planleggeren eller en av jobbene har stått stille eller vært
rød i om lag en time. Det fanger ikke at dataene er utdaterte selv om alt er
grønt (en kilde som leverer gamle tall uten å feile).

## Når tokenen går ut

Uten dødmannsknappen slutter planleggeren å virke uten å si fra -- dispatch
svarer 401 og `scheduled` logger det, men ingen ser Cloudflare-loggen til
daglig. Med den (over) kommer det ikke livstegn, og du får e-post etter om lag
en time. Det
synlige tegnet er at kjøringene faller tilbake til GitHub sin egen kadens,
altså rundt fem i døgnet. Derfor står utløpsdatoen i `TODO.md`.
