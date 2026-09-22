#!/usr/bin/env python3
"""Treffsikkerhetslogg: hvor godt sidens egne tall traff, kamp for kamp.

Bruker BARE sannsynligheter som ble lagret FØR avspark (data/prekick.json,
skrevet av scripts/snapshot_probs.js mens kampen var uspilt og frosset da den
ble spilt) og resultatene i data/matches.json. Ingenting regnes på nytt i
etterkant, så tallene kan ikke bli bedre av etterpåklokskap.

Tre kilder holdes fra hverandre:
  side    tallet siden faktisk viste (odds og modell blandet)
  modell  modellen alene
  odds    sluttoddsen alene, med margin fjernet

Skriver <liga>/data/accuracy.json, som siden viser under "Hvordan vet vi at
modellen virker?".

  python3 scripts/accuracy_log.py eliteserien
  python3 scripts/accuracy_log.py obos
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
KILDER = ("side", "modell", "odds")
# Kalibrering: bredere bøtter enn i tilbaketesten, fordi loggen starter med
# få kamper. 20 prosentpoeng gir nok i hver bøtte til at tallet betyr noe.
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]


def probs_for(entry, kilde):
    """{H,U,B} for én kilde, eller None når kilden mangler for kampen."""
    if kilde == "side":
        p = {k: entry.get(k) for k in "HUB"}
    else:
        d = entry.get("modell" if kilde == "modell" else "odds") or {}
        p = {k: d.get(k) for k in "HUB"}
    if any(p[k] is None for k in "HUB"):
        return None
    s = sum(p.values())
    if s <= 0:
        return None
    return {k: p[k] / s for k in "HUB"}


def main():
    liga = sys.argv[1] if len(sys.argv) > 1 else "eliteserien"
    data = ROOT / liga / "data"
    pre_path, res_path = data / "prekick.json", data / "matches.json"
    if not pre_path.exists() or not res_path.exists():
        print(f"{liga}: mangler prekick.json eller matches.json", file=sys.stderr)
        return 1
    pre = json.loads(pre_path.read_text(encoding="utf-8")).get("matches", {})
    spilte = {}
    for m in json.loads(res_path.read_text(encoding="utf-8")):
        u = "H" if m["hg"] > m["ag"] else ("U" if m["hg"] == m["ag"] else "B")
        spilte[(m["home"], m["away"])] = {"utfall": u, "hg": m["hg"], "ag": m["ag"],
                                          "date": m["date"], "round": m.get("round")}

    # Bare kamper som BÅDE har en frosset sannsynlighet fra før avspark og et
    # publisert resultat. Frosset betyr at raden ikke er rørt etter avspark.
    rader = []
    for key, e in pre.items():
        if not e.get("frosset"):
            continue
        r = spilte.get((e.get("home"), e.get("away")))
        if r:
            rader.append((e, r))
    rader.sort(key=lambda x: (x[1]["date"], x[0].get("home") or ""))

    ut = {
        "version": 1,
        "note": ("Hvor godt tallene som ble lagret FØR avspark traff. Ingenting er regnet "
                 "på nytt i etterkant. Skrevet av scripts/accuracy_log.py."),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n": len(rader),
        "fra": rader[0][1]["date"] if rader else None,
        "til": rader[-1][1]["date"] if rader else None,
        "kilder": {},
        "kalibrering": [],
    }

    for kilde in KILDER:
        tap, treff, n = 0.0, 0, 0
        for e, r in rader:
            p = probs_for(e, kilde)
            if not p:
                continue
            n += 1
            tap += -math.log(max(p[r["utfall"]], 1e-9))
            if max("HUB", key=lambda k: p[k]) == r["utfall"]:
                treff += 1
        ut["kilder"][kilde] = {
            "n": n,
            "treff": round(treff / n, 4) if n else None,
            "logloss": round(tap / n, 4) if n else None,
        }

    # Kalibrering for modellen: hver kamp gir tre (sannsynlighet, skjedde det?).
    for lo, hi in BINS:
        n, hendte, sum_p = 0, 0, 0.0
        for e, r in rader:
            p = probs_for(e, "modell")
            if not p:
                continue
            for k in "HUB":
                if lo <= p[k] < hi or (hi == 1.0 and p[k] == 1.0):
                    n += 1
                    sum_p += p[k]
                    if r["utfall"] == k:
                        hendte += 1
        ut["kalibrering"].append({
            "lo": lo, "hi": hi, "n": n,
            "ventet": round(sum_p / n, 4) if n else None,
            "faktisk": round(hendte / n, 4) if n else None,
        })

    (data / "accuracy.json").write_text(json.dumps(ut, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")
    k = ut["kilder"]
    print(f"{liga}: {ut['n']} kamper med lagret sannsynlighet og resultat")
    for kilde in KILDER:
        v = k[kilde]
        if v["n"]:
            print(f"  {kilde:<7} {v['n']:>3} kamper, treff {v['treff']*100:.1f} %, log loss {v['logloss']:.4f}")
        else:
            print(f"  {kilde:<7} ingen kamper ennå")
    return 0


if __name__ == "__main__":
    sys.exit(main())
