#!/usr/bin/env bash
# Pusher det som er commitet, med rebase foerst og ett nytt forsoek.
#
# HVORFOR: naar den eksterne planleggeren kaller hvert 10. minutt, kan to
# jobber vaere i luften samtidig -- for eksempel update-data og
# obos-results, som begge skriver til data-filer. Den siste faar da
# "non-fast-forward" og mister arbeidet sitt. Med rebase henter den inn den
# andres commit og legger sin egen paa toppen.
#
# Grenen kommer fra HEAD, ALDRI hardkodet til main. En testkjoering paa en
# annen gren skal pushe dit den kjorer, ikke til main.
#
# KONFLIKT I DE GENERERTE FILENE (26.10.2026): stopper rebasen, loeses
# odds_upcoming.json, oddspapi_fixtures*.json og oddspapi_markets.json med
# mains versjon, og prekick.json og oddspapi_usage.json flettes
# (scripts/flett_konflikt.py), saa resultatene alltid kommer med. Foer forsvant
# hele commiten, ogsaa nye resultater (OBOS 25.10., fire kjoeringer paa rad).
# Andre konflikter: som foer, rebasen avbrytes.
#
# Bruk:  bash scripts/push_med_rebase.sh
set -uo pipefail

FLETT="$(dirname "$0")/flett_konflikt.py"
rebase_pagar() { [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; }
uloste() { git diff --name-only --diff-filter=U; }
los_konflikter() {
  local n=0
  while rebase_pagar; do
    n=$((n + 1)); [ "$n" -le 50 ] || return 1
    if [ -n "$(uloste)" ]; then python3 "$FLETT" || return 1; fi
    if ! GIT_EDITOR=true git rebase --continue; then
      # Ble commiten tom etter loesningen (bare odds-fila var endret), hoppes
      # den over. Stopper rebasen paa neste commit, loeses den i neste runde.
      if rebase_pagar && [ -z "$(uloste)" ] && git diff --cached --quiet; then
        git rebase --skip || true
      fi
    fi
  done
  return 0
}

# Lagre-stegene kjoerer "git pull --rebase ... || true" foer dette skriptet;
# har den stoppet paa en konflikt, loeses den her foerst.
if rebase_pagar; then
  echo "En rebase har stoppet paa konflikt -- loeser de genererte filene."
  los_konflikter || git rebase --abort 2>/dev/null || true
fi

GREN="$(git rev-parse --abbrev-ref HEAD)"
if [ "$GREN" = "HEAD" ]; then
  # Detached head (vanlig i Actions): bruk grenen workflowen kjorer paa.
  GREN="${GITHUB_REF_NAME:-main}"
fi
echo "Pusher til $GREN"

hent() {
  git pull --rebase --autostash origin "$GREN" && return 0
  rebase_pagar || return 1
  los_konflikter
}

forsok() {
  hent || return 1
  git push origin "HEAD:$GREN" || return 1
  return 0
}

if forsok; then
  echo "Pushet."
  exit 0
fi

echo "Push avvist eller rebase feilet -- proever en gang til."
git rebase --abort 2>/dev/null || true
if forsok; then
  echo "Pushet ved andre forsok."
  exit 0
fi

echo "FEIL: klarte ikke pushe til $GREN etter to forsok." >&2
exit 1
