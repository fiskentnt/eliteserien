#!/usr/bin/env bash
# sitemap.xml etter en ny grunnlagsfil (20.10.2026): lastmod for hver liga er
# når tabellen sist ble regnet (scripts/make_sitemap.py). De to ligaene regnes
# i hver sin jobb og kan pushe samtidig, og begge endrer sitemap.xml. For å
# unngå rebasekonflikter i den filen lages den alltid på nytt fra det som
# ligger på main: hent, lag, commit og push; avvises pushen, forkastes den
# egne sitemap-commiten, og det prøves på nytt (høyst tre ganger). Kjøres
# etter at grunnlagsfilen og siden er pushet, så den har ingen andre endringer.
set -uo pipefail
GREN="${GITHUB_REF_NAME:-main}"
for forsok in 1 2 3; do
  git pull --rebase --autostash origin "$GREN" || { git rebase --abort 2>/dev/null; continue; }
  python3 scripts/make_sitemap.py
  if git diff --quiet -- sitemap.xml; then echo "sitemap.xml er uendret."; exit 0; fi
  git add sitemap.xml
  git commit -q -m "Sitemap $(date -u +%Y-%m-%dT%H:%MZ)"
  if git push origin "HEAD:$GREN"; then echo "Pushet sitemap.xml."; exit 0; fi
  echo "Push avvist, prøver igjen ($forsok)."
  git reset -q --hard HEAD~1
done
echo "FEIL: klarte ikke pushe sitemap.xml etter tre forsøk." >&2
exit 1
