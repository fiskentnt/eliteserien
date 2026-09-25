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
# Bruk:  bash scripts/push_med_rebase.sh
set -uo pipefail

GREN="$(git rev-parse --abbrev-ref HEAD)"
if [ "$GREN" = "HEAD" ]; then
  # Detached head (vanlig i Actions): bruk grenen workflowen kjorer paa.
  GREN="${GITHUB_REF_NAME:-main}"
fi
echo "Pusher til $GREN"

forsok() {
  git pull --rebase --autostash origin "$GREN" || return 1
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
