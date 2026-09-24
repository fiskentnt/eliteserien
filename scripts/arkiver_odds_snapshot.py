#!/usr/bin/env python3
"""Arkiverer dagens odds_upcoming.json som et tidsstemplet snapshot.

Hvorfor: tilbaketesten har bare SLUTTODDS -- ett tall per kamp, satt 15 til 60
minutter før avspark. Vi vet derfor ikke hva markedet mente ved et kuttpunkt
midt i sesongen, og kan ikke måle modellarkitekturer som bruker markedsodds på
kommende kamper uten å lekke framtidsinformasjon.

Dette bygger det datagrunnlaget. Om ett til to år finnes en ekte
point-in-time-serie, og da kan slike arkitekturer måles skikkelig.

Snapshotene skrives til et PRIVAT repo, ikke hit. Dette skriptet lager bare
filen; workflowen sørger for at den havner riktig sted.

Bruk:
    python3 scripts/arkiver_odds_snapshot.py <utmappe> [liga ...]
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent


def snapshot(liga, ut):
    kilde = ROT / liga / "data" / "odds_upcoming.json"
    if not kilde.exists():
        print(f"  {liga}: ingen odds_upcoming.json, hopper over")
        return None
    d = json.loads(kilde.read_text(encoding="utf-8"))
    kamper = d.get("matches") or []
    if not kamper:
        print(f"  {liga}: tom odds_upcoming.json, hopper over")
        return None
    hentet = d.get("fetched_at") or datetime.now(timezone.utc).isoformat()
    # Bare feltene som trengs for en point-in-time-serie. Ingen bookmakernavn
    # eller råpriser -- det er sannsynlighetene modellen faktisk bruker.
    rader = []
    for m in kamper:
        rader.append({
            "kamp": f"{m['home']}|{m['away']}",
            "home": m["home"],
            "away": m["away"],
            "kickoff": m.get("commence_time"),
            "H": m.get("H"), "D": m.get("D"), "A": m.get("A"),
            "n_bookmakers": m.get("n_bookmakers"),
        })
    ses = str(datetime.now(timezone.utc).year)
    mappe = Path(ut) / liga / ses
    mappe.mkdir(parents=True, exist_ok=True)
    # Filnavnet er hentetidspunktet, så samme henting aldri skrives to ganger.
    navn = hentet.replace(":", "-").replace("+00-00", "Z").replace(".", "-")
    fil = mappe / f"{navn}.json"
    if fil.exists():
        print(f"  {liga}: {fil.name} finnes alt, hopper over")
        return None
    fil.write_text(json.dumps(
        {"hentet": hentet, "liga": liga, "kilde": "odds_upcoming.json",
         "matches": rader}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"  {liga}: skrev {fil.relative_to(ut)} ({len(rader)} kamper)")
    return fil


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    ut = Path(sys.argv[1])
    ligaer = sys.argv[2:] or ["eliteserien", "obos"]
    print(f"Arkiverer oddssnapshot til {ut}")
    n = sum(1 for l in ligaer if snapshot(l, ut))
    print(f"{n} av {len(ligaer)} ligaer arkivert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
