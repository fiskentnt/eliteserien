#!/usr/bin/env bash
# Én kommando som kjører hele regresjonstesten:
#
#   tests/run.sh
#
# Trenger Chrome (eller Chromium) og Node. puppeteer-core hentes til en
# midlertidig mappe hvis den ikke alt er tilgjengelig, så repoet slipper
# node_modules. Sett CHROME_PATH hvis Chrome ligger et uvanlig sted.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! node -e "require('puppeteer-core')" >/dev/null 2>&1; then
  if [ -n "${NODE_PATH:-}" ] && node -e "require('puppeteer-core')" >/dev/null 2>&1; then
    :
  else
    PP_DIR="${TMPDIR:-/tmp}/tabellkalkulator-pp"
    if [ ! -d "$PP_DIR/node_modules/puppeteer-core" ]; then
      echo "Henter puppeteer-core til $PP_DIR ..."
      mkdir -p "$PP_DIR"
      npm install --no-save --no-audit --no-fund --silent --prefix "$PP_DIR" puppeteer-core@25.11.0
    fi
    export NODE_PATH="$PP_DIR/node_modules"
  fi
fi

# Failsafe-testene for resultatkjeden kjører først: de trenger verken nett,
# nøkkel eller nettleser.
python3 tests/failsafe.py || exit 1
echo

exec node tests/regression.js "$@"
