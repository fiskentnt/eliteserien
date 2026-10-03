# Endringer i modellen

## 30. september 2026 (kveld)

Modellen er justert etter en ny tilbaketest. Eliteserien og OBOS-ligaen bruker fortsatt samme modell med samme innstillinger.

### Hva er endret

- **Mindre regularisering.** Lagstyrkene trekkes mindre mot et felles nivå: l1/l2 er endret fra 16/48 til 8/24.
- **Kortere halveringstid.** Tidsvektingen har nå halveringstid 28 dager, mot 35 før. Nyere kamper teller dermed litt mer.

Resten er som før: oddsleddet i tilpasningen med vekt 40, ρ = −0,04, formoppdateringen (FORM_K 0,015), startnivået for nye lag (ligasnittet) og markedsvekten 0,7 for neste runde.

### Slik ble det testet

Hver kamp i 2012–2025 ble spådd med modellen tilpasset bare på kampene med tidligere dato (walk-forward), uten markedsoddsen for selve kampen. For Eliteserien bygger testen på resultater og sluttodds fra football-data.co.uk, for OBOS-ligaen på en oddshistorikk som ikke er offentlig (snittodds), og som derfor ikke ligger i repoet.

Innstillingene ble valgt på 2012–2021, én om gangen, og kontrollert på 2022–2025. Hovedmålet var log loss per kamp (lavere er bedre). Reglene og grensene ble bestemt før testene: kalibreringen og favorittene kunne ikke bli merkbart dårligere, og sjansene for gull, topp 4, opprykk, topp 6 og nedrykk (Brier) kunne ikke bli mer enn 0,001 dårligere i noen sone.

Tallene i "Hvordan vet vi at modellen virker?" på siden bruker 2016–2025 for Eliteserien og 2012–2025 for OBOS-ligaen, mens studien som valgte innstillingene brukte 2012–2025 i begge.

### Hva tilbaketesten viste

- Treffsikkerheten per kamp på 2022–2025: log loss 0,0010 ± 0,0003 lavere i Eliteserien og 0,0012 ± 0,0007 lavere i OBOS-ligaen. Forbedringen er liten.
- Modellen er litt mindre forsiktig. Kalibreringshelningen, der 1 er perfekt og mer enn 1 betyr for forsiktig, gikk fra 1,14 til 1,08 for hjemmeseier og fra 1,26 til 1,19 for borteseier i Eliteserien, og fra 1,53 til 1,44 og fra 1,45 til 1,37 i OBOS-ligaen. Avviket mellom favorittenes sannsynlighet og hvor ofte de vant, ble rundt 0,4 prosentpoeng mindre i begge ligaene.
- Sjansene for sluttplasseringene: ingen sone ble mer enn 0,001 dårligere, og forskjellene var innenfor støyen.
- OBOS-ligaen uten odds: siden viser også en tilbaketest for OBOS-ligaen uten odds, fordi den kan gjenskapes fra det offentlige repoet. Der er de nye verdiene dårligere enn de gamle: Brier 0,0015 ± 0,0005 høyere for opprykk, 0,0028 ± 0,0004 for topp 6 og 0,0008 ± 0,0003 for nedrykk, mest tidlig i sesongen. Uten odds bygger lagstyrkene bare på målene, og da hjelper sterkere regularisering. Siden bruker odds i OBOS-ligaen (alle kampene i 2026 har sluttodds), og med odds ble ingen sone dårligere.
- 2026 fram til 20. september: innenfor støyen i begge ligaene (Eliteserien −0,0002 ± 0,0023, OBOS-ligaen +0,0009 ± 0,0015). Disse kampene er brukt som siste kontroll og kan ikke senere regnes som en urørt test av denne endringen.

### Testet, men ikke endret

- **Oddsvekten i tilpasningen** (20 til 60): 60 var best på 2012–2021, men ikke bedre enn 40 i Eliteserien på 2022–2025. Vekten er fortsatt 40.
- **Formoppdateringen** (FORM_K 0,015 mot 0, med odds som på siden): ingen målbar forskjell på sjansene for sluttplasseringene. 0,015 beholdes. Uten odds hjelper den (OBOS-testen uten odds på siden), fordi lagstyrken da bare bygger på målene.
- **Startnivået for nye lag:** et startnivå for opprykks- og nedrykkslag bygget på tidligere sesonger var litt bedre på 2012–2021, men dårligere i Eliteserien på 2022–2025. Nye lag starter fortsatt på ligasnittet.

### Markedsvekten for neste runde: regelen ga 0,8, vi beholder 0,7

Regelen ble bestemt før testen: den laveste vekten med log loss høyst 0,0025 dårligere enn den beste vekten, i begge ligaene. Med den nye modellen holdt 0,7 seg innenfor i Eliteserien (0,0022 bak), men ikke i OBOS-ligaen (0,0032 bak). Regelen ga derfor 0,8. Kampene i 2026 pekte samme vei: 0,8 var 0,0029 ± 0,0009 bedre i Eliteserien og 0,0007 ± 0,0011 i OBOS-ligaen (innenfor støyen).

Vi beholder likevel 0,7 fordi forskjellen i treffsikkerhet er liten, mens 0,8 gir større hopp i sannsynlighetene når markedsoddsen kommer inn. Historisk er log loss med 0,7 henholdsvis 0,0008 og 0,0012 dårligere enn med 0,8 i Eliteserien og OBOS-ligaen. Samtidig øker andelen kamper med endringer på over 10 prosentpoeng fra 1,5 til 2,9 prosent i Eliteserien og fra 2,1 til 4,0 prosent i OBOS-ligaen. Med 0,7 får vi fortsatt med rundt 83 prosent av forbedringen markedet gir i Eliteserien og 80 prosent i OBOS-ligaen. Vi beholder derfor 0,7 for å unngå unødvendig store hopp og få sannsynlighetene for neste runde til å henge bedre sammen med resten av sesongen.

### Tallene på siden

Tallene i "Hvordan vet vi at modellen virker?" er regnet på nytt for den nye modellen, med walk-forward i stedet for faste kuttpunkter: modellen tilpasses før hver kampdato, og resten av sesongen simuleres, gjennom hele sesongen. Det måler modellen slik siden faktisk brukes. Kuttpunktene (40, 55, 70 og 85 prosent av kampene) hoppet over den første delen av sesongen, der lagstyrken betyr mest. Tallene med kuttpunktene står ved siden av som kontroll.

## 30. september 2026

Etter runde 22 i Eliteserien og runde 23 i OBOS-ligaen har modellen fått én samlet oppdatering med tre endringer. I Eliteserien er runde 12 utsatt til 24. og 25. oktober. Eliteserien og OBOS-ligaen bruker samme modell med samme innstillinger.

Ikke alle deler av modellen kommer fra forskningslitteraturen. Der vi bruker egne praktiske eller empiriske valg, merker vi dem som det.

### Hva er endret

- **Uavgjort (Dixon og Coles, 1997).** Modellen har en justering for kamper med få mål, fra Dixon og Coles. Styrken på justeringen ble stilt inn med en test som hadde feil oppsett. Modellen ga derfor 31 prosent sjanse for uavgjort, mens 24 prosent av kampene endte uavgjort. Styrken er nå estimert fra resultatene 2012–2025. Søket ga −0,04 i Eliteserien og −0,02 i OBOS-ligaen. Forskjellen var uten praktisk betydning i OBOS-ligaen, og vi bruker derfor −0,04 i begge ligaene.
- **Marginen i oddsen (Shin, 1993).** Oddsen inneholder en margin for spillselskapet. Nå bruker vi Shins metode, som fordeler marginen ulikt mellom utfallene i stedet for å redusere alle tre forholdsvis like mye.
- **En feil i beregningen av lagstyrkene er rettet.** Lagstyrkene justeres steg for steg mot det som passer best med målene og oddsen. For det generelle målnivået og hjemmefordelen ble oddsen ikke tatt med i stegene, selv om den var med i det som skulle passe best. Det kunne få beregningen til å stoppe før den hadde funnet et konsistent svar. Rettingen i seg selv endrer lite på treffsikkerheten.

### Hva tilbaketesten viste

Vi spådde alle kampene i Eliteserien og OBOS-ligaen 2012–2025 på nytt, hver gang bare med kamper som var spilt før kampen: 2 800 kamper i hver liga. Styrken på uavgjort-justeringen ble valgt på de samme sesongene, og flere av modellens andre innstillinger er valgt på overlappende historikk. Dette er derfor ikke en helt uavhengig test.

For Eliteserien bygger testen på resultater og sluttodds fra football-data.co.uk. For OBOS-ligaen bygger den på en oddshistorikk som ikke er offentlig (snittodds), så OBOS-tallene kan ikke gjenskapes fra repoet alene.

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
