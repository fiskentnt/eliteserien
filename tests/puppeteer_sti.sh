# puppeteer-core for de lokale testene (16.10.2026). Leses inn av
# tests/run.sh og tests/for_push.sh:
#
#   . tests/puppeteer_sti.sh || exit 1
#
# Pakken ligger fast i ~/.local/share/tabellkalkulator/pp (samme sted som
# xG-filene). Før lå den i den midlertidige mappa, og macOS ryddet den 10.10.
# og 14.10.2026 kl. 03:35 (filer som ikke er brukt på tre dager): mappa sto
# igjen, men pakken kunne ikke lastes, og for_push stoppet eller hentet den
# ikke på nytt.
#
# Rekkefølgen:
#   1. Kan puppeteer-core lastes med miljøet slik det er (NODE_PATH eller en
#      node_modules i nærheten), brukes det.
#   2. Ellers den faste mappa (TABELLKALKULATOR_PP overstyrer). Sjekken er
#      require('puppeteer-core'), ikke at en katalog finnes.
#   3. Kan den ikke lastes derfra, installeres PP_VERSJON på nytt (en halvt
#      ryddet pakke tas bort først), og sjekken kjøres igjen. Feiler den
#      fortsatt, stopper skriptet med en tydelig beskjed.
# CI bruker sin egen mappe ($RUNNER_TEMP/pp) og leser ikke denne filen.
PP_VERSJON="25.11.0"
PP_DIR="${TABELLKALKULATOR_PP:-$HOME/.local/share/tabellkalkulator/pp}"
pp_kan_lastes() { NODE_PATH="$1" node -e "require('puppeteer-core')" >/dev/null 2>&1; }
if node -e "require('puppeteer-core')" >/dev/null 2>&1; then
  :
elif pp_kan_lastes "$PP_DIR/node_modules"; then
  export NODE_PATH="$PP_DIR/node_modules"
else
  echo "puppeteer-core kan ikke lastes fra $PP_DIR -- henter $PP_VERSJON ..."
  mkdir -p "$PP_DIR"
  rm -rf "$PP_DIR/node_modules/puppeteer-core"
  ${PP_NPM:-npm} install --no-save --no-audit --no-fund --silent --prefix "$PP_DIR" "puppeteer-core@$PP_VERSJON"
  if pp_kan_lastes "$PP_DIR/node_modules"; then
    export NODE_PATH="$PP_DIR/node_modules"
  else
    echo "FEIL: puppeteer-core kan fortsatt ikke lastes fra $PP_DIR etter ny installasjon."
    return 1 2>/dev/null || exit 1
  fi
fi
