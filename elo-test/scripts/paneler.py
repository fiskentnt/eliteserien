#!/usr/bin/env python3
"""Panelene på testsiden: når de skal regnes, og hva som er en ekte endring.

Panelfilene (keymatch.json, lastmatch.json, prekick.json, accuracy.json) i
elo-test/emodell/ skrives av scripts/snapshot_probs.js mot /elo-test/ og av
scripts/accuracy_log.py --data elo-test/emodell, i elo-test.yml. Samme skript og
samme frysregel (scripts/prekick_frys.js) som produksjonen.

  python3 elo-test/scripts/paneler.py port    # skriver kjor=true/false
  python3 elo-test/scripts/paneler.py etter   # etter kjøringen, se under

PORT: panelene regnes når model.json eller oddsene i odds_upcoming.json er
endret siden forrige gang (sha256 i emodell/paneler_grunnlag.json), og ALLTID
når utløseren er "Odds nær avspark" eller workflow_dispatch -- da skal
prognosen før avspark lagres, selv om ingenting annet er endret.

ETTER: snapshot_probs.js skriver prekick.json på nytt ved hver kjøring, med
nye stempler. Et nytt tidsstempel alene er ikke en endring: er det eneste som
skiller filen fra den committede versjonen "updated" (øverst) og "stamp" (per
rad), legges den committede versjonen tilbake. En ny frosset rad, en ny rad
eller nye tall er en endring og blir committet. Skriver også grunnlaget.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]
EM = ROT / "elo-test" / "emodell"
ODDS = ROT / "eliteserien" / "data" / "odds_upcoming.json"
GRUNNLAG = EM / "paneler_grunnlag.json"
FILER = ("keymatch.json", "lastmatch.json", "prekick.json", "accuracy.json")
ALLTID = ("Odds nær avspark",)


def grunnlag():
    """sha256 av model.json og av oddsene (bare kampene, ikke hentetidspunktet)."""
    odds = json.loads(ODDS.read_text(encoding="utf-8")).get("matches", []) if ODDS.exists() else []
    return {
        "model_json_sha256": hashlib.sha256((EM / "model.json").read_bytes()).hexdigest(),
        "odds_upcoming_sha256": hashlib.sha256(
            json.dumps(odds, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
    }


def uten_stempler(navn, d):
    """Innholdet uten tidsstempler: 'updated' øverst, 'stamp' per prekick-rad."""
    d = dict(d)
    d.pop("updated", None)
    if navn == "prekick.json":
        d["matches"] = {k: {kk: vv for kk, vv in v.items() if kk != "stamp"}
                        for k, v in (d.get("matches") or {}).items()}
    return d


def port():
    utloser = os.environ.get("UTLOSER", "")
    hendelse = os.environ.get("HENDELSE", "")
    gml = json.loads(GRUNNLAG.read_text(encoding="utf-8")) if GRUNNLAG.exists() else {}
    endret = gml != grunnlag()
    kjor = endret or hendelse == "workflow_dispatch" or utloser in ALLTID
    grunn = ("model.json eller oddsene er endret" if endret else
             "workflow_dispatch" if hendelse == "workflow_dispatch" else
             f"utløst av «{utloser}»" if utloser in ALLTID else "ingenting endret")
    print(f"paneler: {'kjøres' if kjor else 'hoppes over'} ({grunn})")
    ut = os.environ.get("GITHUB_OUTPUT")
    if ut:
        with open(ut, "a", encoding="utf-8") as fh:
            fh.write(f"kjor={'true' if kjor else 'false'}\n")
    return 0


def etter():
    for navn in FILER:
        f = EM / navn
        if not f.exists():
            print(f"  {navn}: finnes ikke")
            continue
        r = subprocess.run(["git", "show", f"HEAD:elo-test/emodell/{navn}"], cwd=ROT,
                           capture_output=True)
        if r.returncode != 0:
            print(f"  {navn}: ny fil")
            continue
        gml, ny = json.loads(r.stdout), json.loads(f.read_text(encoding="utf-8"))
        if uten_stempler(navn, gml) == uten_stempler(navn, ny):
            if f.read_bytes() != r.stdout:
                f.write_bytes(r.stdout)
                print(f"  {navn}: bare nye tidsstempler -- committet versjon lagt tilbake")
            else:
                print(f"  {navn}: uendret")
        else:
            print(f"  {navn}: innholdet er endret")
    GRUNNLAG.write_text(json.dumps(grunnlag(), indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit(port() if cmd == "port" else etter() if cmd == "etter" else 2)
