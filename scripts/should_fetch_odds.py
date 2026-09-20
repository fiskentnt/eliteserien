#!/usr/bin/env python3
"""Avgjør om update-odds.yml skal kjøre The Odds API-hentingen. Kjøres FØR
pip install (ingen avhengigheter utover standardbiblioteket).

Kjører videre hvis:
  - det finnes minst én uspilt kamp i data/fixtures.json innen 7 dager (ellers
    er det ingen vits i å bruke kreditter i en landskampspause), OG
  - vi ikke har stanset kvoten for denne måneden (se data/odds_quota.json,
    skrevet av fetch_odds_upcoming.py når x-requests-remaining < 100),
med mindre FORCE_FETCH=true (manuell workflow_dispatch).
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent


def should_fetch_odds(now=None):
    if os.environ.get("FORCE_FETCH") == "true":
        return True, "manuelt trigget (workflow_dispatch)"
    now = now or datetime.now(timezone.utc)

    quota_path = ROOT / "data" / "odds_quota.json"
    if quota_path.exists():
        quota = json.loads(quota_path.read_text(encoding="utf-8"))
        stopped_month = quota.get("stopped_until_month")
        if stopped_month == now.strftime("%Y-%m"):
            return False, f"kvoten ble lav denne måneden ({quota.get('remaining')} igjen {quota.get('checked_at')}), venter til neste måned"

    fixtures_path = ROOT / "data" / "fixtures.json"
    if not fixtures_path.exists():
        return True, "data/fixtures.json finnes ikke ennå"
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    horizon = now + timedelta(days=7)
    upcoming = [m for r in fixtures for m in r["matches"] if not m["played"] and m["date"] <= horizon.strftime("%Y-%m-%d")]
    if not upcoming:
        return False, "ingen uspilte kamper de neste 7 dagene -- sparer kreditter"
    return True, f"{len(upcoming)} uspilt(e) kamp(er) innen 7 dager"


if __name__ == "__main__":
    ok, reason = should_fetch_odds()
    print(reason, file=sys.stderr)
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"should_fetch={'true' if ok else 'false'}\n")
    print(f"should_fetch={ok}")
