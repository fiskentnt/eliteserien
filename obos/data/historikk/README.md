# OBOS-ligaen 2012–2025: kamper med odds

To filer, satt sammen 26. september 2026 i en Claude-chat (claude.ai), ikke
lastet ned fra en fast adresse. De kan derfor ikke hentes på nytt og ligger
her. macOS-merket på filene sier "Claude", og regnearket er laget med
openpyxl/LibreOffice på Linux. Hvor resultatene og oddsen opprinnelig kommer
fra, står ikke i filene. Fasenavnene er på engelsk ("Promotion - Play Offs",
"Relegation"), som i oddsarkivene på nettet.

- `1divisjon_2012-2025_kamper_og_odds.xlsx` (sha256 `cca97c0469ad44f2e31afd5c27203bcf67215850d54a5b57f8aa825a2fe24703`):
  originalen. Arket "Alle sesonger" og ett ark per sesong, 3461 kamper:
  seriekamper (3360), opprykks- og nedrykkskvalik og sluttspill, med odds
  H/U/B og merknader ("Etter straffer", "Etter ekstraomganger", én kamp
  "Tildelt").
- `obos_historikk_2012-2025.csv` (sha256 `2145496d164d0acafee9d5ed0ea09699cfd30836f1d6c93c0f952de4c39d78e6`):
  seriekampene fra regnearket, 3360 kamper, odds for 3359 (ikke Sandnes
  Ulf–Strømmen 2019, som ble tildelt). Kolonner: sesong, dato, hjemmelag,
  bortelag, mal_hjemme, mal_borte, utfall (1/X/2), odds_1, odds_x, odds_2.

Mot `../obos_2012-2026.csv` (kampene uten odds): samme antall seriekamper
per sesong. 2700 kamper har samme dato og lag i begge filene, og alle har
samme resultat. De 660 andre skiller seg på dato eller lagnavn.

Brukes av `scripts/dc_rho_studie.py --liga obos` (Dixon-Coles-rho og
målfordelingen, 29.9.2026).
