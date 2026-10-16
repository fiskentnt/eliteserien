# Frosne data for regresjonstestene

`tests/regression.js` kjører lokalt mot et frossent øyeblikksbilde av
datafilene sidene henter, ikke mot dagens filer i `<liga>/data/`. Mange av
testene er skrevet mot en bestemt tabellstilling: lag som er i
nedrykksstriden, odds for neste runde, merker i tabellen, kamper som gjenstår.
Med dagens filer feiler de eller blir tomme når nye resultater kommer, en kamp
flyttes eller sesongen tar slutt. Med et frosset bilde tester de koden, og
gir det samme svaret i morgen som i dag.

`2026-10-01/` er filene fra commit f500e01 (1.10.2026, etter runde 23 i
OBOS-ligaen og runde 22 i Eliteserien, med runde 12 utsatt), samme sti som i
repoet:

- `eliteserien/data/` og `obos/data/`: matches, fixtures, model,
  odds_upcoming, odds (Eliteserien), odds_quota (Eliteserien), keymatch,
  lastmatch, prekick, odds_closing, accuracy, justeringer, status, history og
  grunnlag.
- `elo-test/emodell/`: model, accuracy, keymatch, lastmatch, prekick og
  grunnlag. Testsiden leser kampene fra `eliteserien/data/`.

`2026-10-16/` er Eliteserien-filene fra 16.10.2026 (før runde 24): matches,
fixtures, model, justeringer, odds_upcoming og status. Viking og Bodø/Glimt
står da helt likt (53 poeng, +36, 56 scorede mål), og gruppen «Innbyrdes
oppgjør i tabellen» bruker det til å sjekke at Viking står først (innbyrdes
5-0, kampreglementet § 5-3).

Slik brukes det (se `DATA_DAG` i `tests/regression.js`):

- Testserveren svarer `/<liga>/data/<fil>.json` og `/elo-test/emodell/<fil>.json`
  fra bildet, og 404 for filer som ikke er med.
- Repokopiene testene lager (grunnlagsfilen, prekick) får bildet lagt over
  dataene.
- Gruppen "Dagens data" laster sidene med de ekte filene, så en endring i
  dataformatet fra CI fortsatt oppdages.
- Med `--live` brukes den publiserte siden med dagens data.

`justeringer.json` er gjort om til formatet fra 1.10.2026 (kilde og lenke
hver for seg), ellers er filene uendret.

Grunnlagsfilene i bildet er regnet av CI for disse dataene. Endres koden i
Workeren eller konstantene som inngår i avtrykket, regner testene filen på
nytt fra bildet, som før.

Bildet må byttes ved sesongskiftet: koden filtrerer på `LEAGUE.season`, og
2026-dataene passer ikke til en 2027-side. Lag da et nytt bilde fra en commit
der testene er grønne, og pek `DATA_DAG` dit.

Tester som sammenligner med fotball.no-sidene lagret 25.9.2026
(`tests/kilder/testdata/`), bruker fasiten fra samme dag
(`fasit_<liga>_2026-09-25.json`), ikke dette bildet.
