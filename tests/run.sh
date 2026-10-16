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

# puppeteer-core: fast mappe utenfor den midlertidige, sjekket med require og
# installert på nytt når den ikke kan lastes (tests/puppeteer_sti.sh).
. tests/puppeteer_sti.sh || exit 1

# Failsafe-testene for resultatkjeden kjører først: de trenger verken nett,
# nøkkel eller nettleser.
python3 tests/failsafe.py || exit 1
echo

exec node tests/regression.js "$@"
