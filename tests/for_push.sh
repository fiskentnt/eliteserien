#!/usr/bin/env bash
# Alt som skal være grønt FØR HVER PUSH (3.10.2026):
#
#   tests/for_push.sh
#
# Rekkefølge, raskest først, og stopp ved første feil:
#   1. failsafe                      tests/failsafe.py
#   2. kildetestene                  tests/kilder/test_kilder.py
#   3. sesongskiftetestene           tests/kilder/test_sesongskifte.py
#   4. testsiden (ELO)               elo-test/scripts/kontroll.py
#   5. byggene er oppdatert          build_league.py obos --check, build_modellsjekk.py --check
#   6. hele regresjonen              tests/regression.js (Chrome, puppeteer-core)
#   7. panelene på testsiden         elo-test/scripts/kontroll_paneler.py
#      (etter regresjonen, ikke samtidig: begge bruker nettleseren)
# Til slutt: commitene som pushes (git log origin/main..HEAD).
#
# KORT KONTROLL (4.10.2026): failsafe, kontroll.py, kontroll_paneler.py og
# regression.js --bare del, bare når full for_push var grønn på samme kode
# før rebasen og origin bare endret filer på listen over genererte filer
# (tests/for_push_valg.py, som skriver ut hvorfor). Ellers full. En grønn full
# kjøring lagrer commiten i .git/for-push-gronn. FOR_PUSH_FULL=1 gir alltid full.
#
# Python: .venv/bin/python3 hvis den finnes (numpy og scipy), ellers python3.
# puppeteer-core: NODE_PATH hvis satt, ellers hentes den til en midlertidig
# mappe, som i tests/run.sh.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=python3
[ -x .venv/bin/python3 ] && PY=.venv/bin/python3

if ! node -e "require('puppeteer-core')" >/dev/null 2>&1; then
  PP_DIR="${TMPDIR:-/tmp}/tabellkalkulator-pp"
  if [ ! -d "$PP_DIR/node_modules/puppeteer-core" ]; then
    echo "Henter puppeteer-core til $PP_DIR ..."
    mkdir -p "$PP_DIR"
    npm install --no-save --no-audit --no-fund --silent --prefix "$PP_DIR" puppeteer-core@25.11.0
  fi
  export NODE_PATH="$PP_DIR/node_modules"
fi

LOGG="${TMPDIR:-/tmp}/tabellkalkulator-for-push"
mkdir -p "$LOGG"
start=$(date +%s)
git fetch -q 2>/dev/null || true
steg() {
  local navn="$1"; shift
  local fil="$LOGG/$(echo "$navn" | tr ' /' '__').log"
  printf '%-34s ' "$navn"
  local t0=$(date +%s)
  if "$@" >"$fil" 2>&1; then
    printf 'OK   %4ss  %s\n' "$(( $(date +%s) - t0 ))" "$(grep -E 'gikk gjennom|bestod|bygget fra dagens kilde' "$fil" | tail -1)"
  else
    printf 'FEIL %4ss\n\n' "$(( $(date +%s) - t0 ))"
    grep -E '✗|FEIL|Error|Traceback' "$fil" | head -20
    echo
    echo "Hele loggen: $fil"
    echo "IKKE PUSH."
    exit 1
  fi
}

# Kort eller full (se over).
VALG_UT=$("$PY" tests/for_push_valg.py)
echo "$VALG_UT" | grep -v '^VALG='
echo
VALG=$(echo "$VALG_UT" | grep '^VALG=' | cut -d= -f2)
if [ "$VALG" = "kort" ] && [ -z "${FOR_PUSH_FULL:-}" ]; then
  steg "failsafe"                 "$PY" tests/failsafe.py
  steg "kontroll.py (ELO)"        "$PY" elo-test/scripts/kontroll.py
  steg "kontroll_paneler.py"      "$PY" elo-test/scripts/kontroll_paneler.py
  steg "regression.js --bare del" node tests/regression.js --bare del
  echo
  echo "Kort kontroll grønn på $(( ($(date +%s) - start) / 60 )) min. Dette pushes:"
  git log --oneline origin/main..HEAD
  # Koden er den samme som i den grønne fulle kjøringen, pluss genererte filer
  # fra origin: den rebaserte commiten lagres som grønn. Ellers sto den gamle
  # (fra før rebasen) igjen, og neste valg viste den pushede commiten som om
  # den kom fra origin.
  if [ -z "$(git status --porcelain --untracked-files=no)" ]; then
    printf '{"commit": "%s", "origin": "%s", "tid": "%s", "kort": true}\n' "$(git rev-parse HEAD)" "$(git rev-parse origin/main)" "$(date '+%Y-%m-%d %H:%M')" \
      > "$(git rev-parse --git-dir)/for-push-gronn"
    echo "(lagret: $(git rev-parse --short HEAD) har samme kode som den grønne kjøringen)"
  fi
  exit 0
fi

steg "failsafe"                 "$PY" tests/failsafe.py
steg "kildetestene"             "$PY" tests/kilder/test_kilder.py
steg "sesongskiftetestene"      "$PY" tests/kilder/test_sesongskifte.py
steg "kontroll.py (ELO)"        "$PY" elo-test/scripts/kontroll.py
steg "obos/index.html bygget"   python3 scripts/build_league.py obos --check
steg "modellsjekk-sidene"       python3 scripts/build_modellsjekk.py --check
steg "hele regresjonen"         node tests/regression.js
steg "kontroll_paneler.py"      "$PY" elo-test/scripts/kontroll_paneler.py

echo
echo "Alt grønt på $(( ($(date +%s) - start) / 60 )) min. Dette pushes:"
git fetch -q 2>/dev/null || true
git log --oneline origin/main..HEAD
# Den grønne kjøringen gjelder commiten bare når alt var committet.
if [ -z "$(git status --porcelain --untracked-files=no)" ]; then
  printf '{"commit": "%s", "origin": "%s", "tid": "%s"}\n' "$(git rev-parse HEAD)" "$(git rev-parse origin/main)" "$(date '+%Y-%m-%d %H:%M')" \
    > "$(git rev-parse --git-dir)/for-push-gronn"
  echo "(lagret: full for_push grønn på $(git rev-parse --short HEAD))"
else
  echo "(ikke lagret som grønn: endringer som ikke er committet)"
fi
