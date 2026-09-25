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

1. **Token.** Lag en fine-grained PAT på github.com:
   - Resource owner: `fiskentnt`
   - Repository access: **Only select repositories** → `fiskentnt/eliteserien`
   - Permissions → Repository → **Actions: Read and write**. Ingenting annet.
   - Noter utløpsdatoen. Den skal inn i `TODO.md`, ellers stopper
     planleggeren stille den dagen den går ut.

2. **Legg den inn som hemmelighet:**

       cd planlegger
       npx wrangler secret put GITHUB_TOKEN

   Tokenen skal aldri i `wrangler.toml` og aldri i repoet.

3. **Publiser:**

       npx wrangler deploy

4. **Sjekk at den svarer:** åpne workerens URL. Den viser hva den gjør uten å
   sende noe. `?kjor=1` utløser én runde med én gang.

## Når tokenen går ut

Planleggeren slutter å virke uten å si fra — dispatch svarer 401 og
`scheduled` logger det, men ingen ser Cloudflare-loggen til daglig. Det
synlige tegnet er at kjøringene faller tilbake til GitHub sin egen kadens,
altså rundt fem i døgnet. Derfor står utløpsdatoen i `TODO.md`.
