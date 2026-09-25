#!/usr/bin/env python3
"""Merker at det daglige vedlikeholdet for en liga er UTFORT og FULLFORT.

Kalles som eget steg til SLUTT i kjeden, etter at arbeidet faktisk er gjort.
Det er hele poenget: siste_ok skal aldri settes fordi en kjoring startet
eller fordi et av de forste stegene gikk bra.

Arbeidsdelingen:
  siste_forsok   settes av should_fetch.py NAAR den daglige porten aapner
  siste_ok       settes her, naar arbeidet er ferdig

Uansett hva som aapnet porten -- en ventende kamp eller 20-timersregelen --
er det de samme stegene som utgjor det daglige vedlikeholdet, saa en
kampdrevet kjoring som fullforer dem teller ogsaa.

Bruk:  python3 scripts/merk_daglig.py <liga>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import should_fetch


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    liga = argv[0]
    if liga not in should_fetch.LIGAER:
        print(f"ukjent liga: {liga}", file=sys.stderr)
        return 2
    should_fetch.merk_ok(liga)
    print(f"[{liga}] daglig vedlikehold utfort -- 20-timersklokka nullstilt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
