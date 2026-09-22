# Ting som må gjøres på et bestemt tidspunkt

Kortere oppgaver hører hjemme i en commit, ikke her. Dette er de som må
huskes fram til en dato eller en hendelse.

## Etter at 2026-sesongen er ferdigspilt

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

- **Sjekk lagfargene til Bryne og Strømsgodset på nytt.**
  Begge ble hentet fra engelsk Wikipedia fordi den norske artikkelen var
  upålitelig da fargene ble lagt inn (22. september 2026):
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

- **Flytt cron-tidene når vintertiden begynner.**
  Klokkeslettene i `.github/workflows/*.yml` er UTC og forutsetter norsk
  sommertid. Se kommentaren i `update-data.yml`.
