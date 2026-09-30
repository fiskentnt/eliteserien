# Endringer i modellen

## 30. september 2026

Etter runde 22 i Eliteserien og runde 23 i OBOS-ligaen har modellen fått én samlet oppdatering med tre endringer. I Eliteserien er runde 12 utsatt til 24. og 25. oktober. Eliteserien og OBOS-ligaen bruker samme modell med samme innstillinger. Modellen står deretter uendret ut 2026-sesongen, også vekten oddsen får for neste runde.

Ikke alle deler av modellen kommer fra forskningslitteraturen. Der vi bruker egne praktiske eller empiriske valg, merker vi dem som det.

### Hva er endret

- **Uavgjort (Dixon og Coles, 1997).** Modellen har en justering for kamper med få mål, fra Dixon og Coles. Styrken på justeringen ble stilt inn med en test som hadde feil oppsett. Modellen ga derfor 31 prosent sjanse for uavgjort, mens 24 prosent av kampene endte uavgjort. Styrken er nå estimert fra resultatene 2012–2025. Søket ga −0,04 i Eliteserien og −0,02 i OBOS-ligaen. Forskjellen var uten praktisk betydning i OBOS-ligaen, og vi bruker derfor −0,04 i begge ligaene.
- **Marginen i oddsen (Shin, 1993).** Oddsen inneholder en margin for spillselskapet. Nå bruker vi Shins metode, som fordeler marginen ulikt mellom utfallene i stedet for å redusere alle tre forholdsvis like mye.
- **En feil i beregningen av lagstyrkene er rettet.** Lagstyrkene justeres steg for steg mot det som passer best med målene og oddsen. For det generelle målnivået og hjemmefordelen ble oddsen ikke tatt med i stegene, selv om den var med i det som skulle passe best. Det kunne få beregningen til å stoppe før den hadde funnet et konsistent svar. Rettingen i seg selv endrer lite på treffsikkerheten.

### Hva tilbaketesten viste

Vi spådde alle kampene i Eliteserien og OBOS-ligaen 2012–2025 på nytt, hver gang bare med kamper som var spilt før kampen: 2 800 kamper i hver liga. Styrken på uavgjort-justeringen ble valgt på de samme sesongene, og flere av modellens andre innstillinger er valgt på overlappende historikk. Dette er derfor ikke en helt uavhengig test.

For Eliteserien bygger testen på resultater og sluttodds fra football-data.co.uk. For OBOS-ligaen bygger den på snittodds fra oddsportal.com. Den oddshistorikken ligger i et privat arkiv og ikke i det offentlige repoet, så OBOS-tallene kan ikke gjenskapes fra repoet alene.

- Uavgjort: modellen gir nå 24 prosent i snitt, mot 31 før. I virkeligheten endte 24 prosent av kampene i Eliteserien og 23 prosent i OBOS-ligaen uavgjort.
- Favorittene: lagene som var favoritter i markedet, vant 53 og 54 prosent av kampene. Modellen gir dem nå 50 og 49 prosent i snitt, mot 46 og 45 før.
- Treffsikkerheten per kamp, målt som log loss (lavere er bedre), ble 0,0135 ± 0,0027 bedre i Eliteserien og 0,0175 ± 0,0035 bedre i OBOS-ligaen.
- For sjansene for gull, topp 4, opprykk og nedrykk viste testen ingen sikker forskjell.

Kampene fra 15. april i Eliteserien og fra 1. mai i OBOS-ligaen til 20. september 2026 ble ikke brukt til å velge noe av dette. Utsatte kamper fra tidligere runder er med. Hver kamp ble spådd med modellen tilpasset på kampene spilt før kampdagen, med sluttoddsen som ligger i repoet. Log loss gikk fra 0,9606 til 0,9435 i Eliteserien (139 kamper) og fra 0,9973 til 0,9756 i OBOS-ligaen (154 kamper). Dette er den eneste testen der styrken på uavgjort-justeringen ikke har sett dataene. Utvalget er lite, og de tre endringene ble testet samlet, så det støtter endringen uten å bevise den.

### Det som fortsatt ikke er godt nok

- Favorittene er fortsatt noe undervurdert: modellen gir dem 50 og 49 prosent, mens de vant 53 og 54.
- Spillselskapenes sluttodds treffer fortsatt bedre enn modellen, kamp for kamp. Forskjellen er omtrent halvert, men ikke borte.

### Praktiske og empiriske valg som ikke er endret

- Historiske odds inngår når lagstyrkene estimeres. Formen på dette leddet og vekten 40 er empiriske valg, ikke hentet fra en publisert fotballmodell. I de historiske rullerende testene hjelper leddet: log loss per kamp er 0,035 ± 0,003 lavere enn med mål alene i Eliteserien, og 0,035 ± 0,004 lavere i OBOS-ligaen.
- Oddsen for neste runde blandes inn med 70 prosent vekt. Å blande prognoser lineært er en etablert metode, men vekten 0,7 er ikke målt.
- Etter hvert simulert eller innfylt resultat justeres lagstyrkene litt. Det er en praktisk regel. I tilbaketesten for Eliteserien ga den ingen målbar forbedring.
- Knappene som fyller inn kamper, velger et plausibelt forløp med et filter. Det påvirker ikke prosentene.

Disse står uendret ut sesongen og blir gjennomgått etter sesongslutt. Hvor mye oddsen bør veie, undersøker vi videre. Endringer derfra tas i bruk tidligst fra 2027.
