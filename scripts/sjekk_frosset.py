#!/usr/bin/env python3
"""Viser den frosne sesongsiden fortsatt NØYAKTIG de tallene som ble frosset?

Dette er kontrakten. Avviker den, er noe i den frosne kopien endret -- og da
er historikken omskrevet, som er nettopp det frysingen skal hindre.
"""
import json, os, subprocess, sys
from pathlib import Path
HER = Path(__file__).resolve().parent

rot, liga, sesong = sys.argv[1], sys.argv[2], sys.argv[3]
kontrakt = Path(rot) / liga / sesong / "data" / "frosset.json"
if not kontrakt.exists():
    print(f"  ingen frosset.json i {liga}/{sesong}/data/", file=sys.stderr); sys.exit(1)
K = json.loads(kontrakt.read_text(encoding="utf-8"))
pp = os.environ.get("NODE_PATH") or str(
    Path(os.environ.get("TMPDIR", "/tmp")) / "tabellkalkulator-pp/node_modules")
r = subprocess.run(["node", str(HER / "les_side.js"), rot, f"{liga}/{sesong}/",
                    str(HER / "_sjekk.json")],
                   env={**os.environ, "NODE_PATH": pp}, capture_output=True, text=True)
if r.returncode != 0:
    print(f"  kunne ikke lese den frosne siden: {r.stderr.strip()[:200]}", file=sys.stderr)
    sys.exit(1)
N = json.loads((HER / "_sjekk.json").read_text(encoding="utf-8"))
avvik = [f"rad {i+1}: {a} != {b}" for i, (a, b) in enumerate(zip(K["rader"], N["rader"])) if a != b]
if len(K["rader"]) != len(N["rader"]):
    avvik.insert(0, f"ulikt antall rader: {len(K['rader'])} mot {len(N['rader'])}")
print(f"  frosset {K['frosset_at']}, {len(K['rader'])} rader")
if avvik:
    print(f"  AVVIK ({len(avvik)}):")
    for a in avvik[:5]: print(f"    {a}")
    sys.exit(1)
print(f"  BESTATT: alle {len(K['rader'])} rader identiske med kontrakten")
for rad in N["rader"][:3]:
    print(f"    {rad[0]}. {rad[1][:18]:<20}{rad[8]:>4} p   gull {rad[11]:>6}")
sys.exit(0)
