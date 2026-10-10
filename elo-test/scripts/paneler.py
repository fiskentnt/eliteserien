#!/usr/bin/env python3
"""Panelene på testsiden: hva som er en ekte endring.

Panelfilene (lastmatch.json, prekick.json, accuracy.json) i elo-test/emodell/
skrives av scripts/snapshot_probs.js mot /elo-test/ og av
scripts/accuracy_log.py --data elo-test/emodell, i elo-test.yml. Samme skript og
samme frysregel (scripts/prekick_frys.js) som produksjonen. Banneret
(keymatch.json) regnes av scripts/lag_grunnlag.js fra grunnlagsfilen, i
grunnlag.yml, som i produksjonen.

  python3 elo-test/scripts/paneler.py etter   # etter kjøringen, se under

INGEN PORT (10.10.2026): panelene regnes i hver byggende ELO-test-kjøring.
Porten regnet dem bare når model.json eller oddsene var endret, men sidens tall
for forrige kamp avhenger også av om grunnlagsfilen (emodell/grunnlag.json)
passer. Den regnes av grunnlag.yml etter ELO-test, så panelene ble regnet mens
den var foreldet, og når den nye kom, flyttet sidens tall seg uten at porten
så det (kontroll W rød ca. 40 ganger 9.10.2026).

ETTER: snapshot_probs.js skriver prekick.json på nytt ved hver kjøring, med
nye stempler. Et nytt tidsstempel alene er ikke en endring: er det eneste som
skiller filen fra den committede versjonen "updated" (øverst) og "stamp" (per
rad), legges den committede versjonen tilbake. En ny frosset rad, en ny rad
eller nye tall er en endring og blir committet.
"""
import json
import subprocess
import sys
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]
EM = ROT / "elo-test" / "emodell"
FILER = ("lastmatch.json", "prekick.json", "accuracy.json")


def uten_stempler(navn, d):
    """Innholdet uten tidsstempler: 'updated' øverst, 'stamp' per prekick-rad."""
    d = dict(d)
    d.pop("updated", None)
    if navn == "prekick.json":
        d["matches"] = {k: {kk: vv for kk, vv in v.items() if kk != "stamp"}
                        for k, v in (d.get("matches") or {}).items()}
    return d


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
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit(etter() if cmd == "etter" else 2)
