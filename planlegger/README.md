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

## Når tokenen går ut

Planleggeren slutter å virke uten å si fra -- dispatch svarer 401 og
`scheduled` logger det, men ingen ser Cloudflare-loggen til daglig. Det
synlige tegnet er at kjøringene faller tilbake til GitHub sin egen kadens,
altså rundt fem i døgnet. Derfor står utløpsdatoen i `TODO.md`.
