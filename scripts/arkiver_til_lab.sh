#!/usr/bin/env bash
# Arkiverer odds_upcoming.json som tidsstemplet snapshot i det PRIVATE
# lab-repoet. Kalles to ganger per oddsjobb:
#
#   for-henting   tar snapshotet som alt ligger i repoet, FOR noe kan
#                 overskrive det. Fanger et snapshot som ble tapt sist fordi
#                 arkiveringen feilet.
#   etter-henting tar det nye snapshotet.
#
# Idempotent: filnavnet er hentetidspunktet (fetched_at), så et snapshot som
# alt finnes i laben hoppes over. To kall på rad gir dermed én fil.
#
# Skriver ALDRI til det offentlige repoet. Nøkkelen er en deploy key med
# skrivetilgang bare til laben.
#
# Bruk:  LAB_DEPLOY_KEY=... scripts/arkiver_til_lab.sh <fase> [liga ...]
set -uo pipefail

FASE="${1:-ukjent}"; shift || true
LIGAER=("$@")
[ ${#LIGAER[@]} -eq 0 ] && LIGAER=(eliteserien obos)

if [ -z "${LAB_DEPLOY_KEY:-}" ]; then
  echo "LAB_DEPLOY_KEY er ikke satt -- hopper over arkivering ($FASE)."
  exit 0
fi

ARB="${RUNNER_TEMP:-/tmp}/lab-$FASE-$$"
NOKKEL="${RUNNER_TEMP:-/tmp}/lab-key-$$"
opprydding() { rm -rf "$ARB" "$NOKKEL"; }
trap opprydding EXIT

printf '%s\n' "$LAB_DEPLOY_KEY" > "$NOKKEL"
chmod 600 "$NOKKEL"
mkdir -p ~/.ssh
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null
export GIT_SSH_COMMAND="ssh -i $NOKKEL -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

git clone --quiet --depth 1 \
  git@github.com:fiskentnt/tabellkalkulator-lab.git "$ARB" || {
  echo "FEIL: klarte ikke klone lab-repoet ($FASE)"; exit 1; }

python3 scripts/arkiver_odds_snapshot.py "$ARB/odds-arkiv" "${LIGAER[@]}" || {
  echo "FEIL: arkiveringsskriptet feilet ($FASE)"; exit 1; }

cd "$ARB"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add odds-arkiv
if git diff --cached --quiet; then
  echo "Ingen nye snapshot ($FASE) -- alt var arkivert fra for."
  exit 0
fi
git commit --quiet -m "Oddssnapshot ($FASE) $(date -u +%Y-%m-%dT%H:%MZ)"
git push --quiet || { echo "FEIL: klarte ikke pushe til laben ($FASE)"; exit 1; }
echo "Arkivert ($FASE): $(git show --stat --oneline HEAD | tail -n +2 | wc -l | tr -d ' ') fil(er)."
