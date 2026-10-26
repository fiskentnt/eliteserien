#!/usr/bin/env python3
"""Løser rebase-konflikter i de genererte datafilene, så resultatene alltid
kommer med (26.10.2026).

Søndag 25.10. skrev «OBOS: hent resultater» og «Odds nær avspark»
obos/data/odds_upcoming.json samtidig. Rebasen i lagre-steget stoppet på
konflikten, push_med_rebase.sh ga opp, og hele commiten forsvant, også de nye
resultatene (fire kjøringer på rad, 17.10 til 17.41).

Kalles av scripts/push_med_rebase.sh når `git pull --rebase` stopper. Under en
rebase er stadium 2 («ours») versjonen på main og stadium 3 («theirs») den
egne commiten som legges oppå; stadium 1 er felles utgangspunkt.

  odds_upcoming.json, oddspapi_fixtures*.json, oddspapi_markets.json
      mains versjon beholdes. Den egne oddsen hentes igjen i neste kjøring.
  prekick.json
      flettes: alle kampene fra begge sider er med. Prisen før avspark kan
      ikke hentes igjen. Har begge endret samme kamp, vinner en fryst rad
      (frosset), ellers den med nyest stamp, ellers mains.
  data/oddspapi_usage.json
      flettes: tellerne blir felles utgangspunkt pluss begge sidenes økning,
      så telleren ikke viser for lite. (Fila skrives ikke lenger etter
      24.09.2026, hver kjøring har sin egen fil i data/oddspapi-bruk/, men
      regelen står for sikkerhets skyld.)

Andre filer med konflikt løses ikke: skriptet avslutter med 1, og
push_med_rebase.sh avbryter som før.

  python3 scripts/flett_konflikt.py      (inne i en rebase som har stoppet)
"""
import json
import subprocess
import sys
from fnmatch import fnmatch

# Bare ligaene; testsiden (elo-test) holdes utenfor.
LIGAER = ("eliteserien", "obos")
BEHOLD_MAIN = [f"{l}/data/{f}" for l in LIGAER for f in ("odds_upcoming.json", "oddspapi_fixtures*.json", "oddspapi_markets.json")]
PREKICK = [f"{l}/data/prekick.json" for l in LIGAER]
TELLER = ["data/oddspapi_usage.json"]


def git(*a, check=True):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=check).stdout


def stadium(n, sti):
    """Innholdet i stadium n (1 = utgangspunkt, 2 = main, 3 = egen), eller None."""
    r = subprocess.run(["git", "show", f":{n}:{sti}"], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def skriv(sti, data):
    # Samme form som skriverne (JSON.stringify(x, null, 1) og json.dumps(indent=1)).
    with open(sti, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def flett_prekick(base, main, egen):
    """Alle kampene fra begge sider. Samme kamp endret på begge sider:
    fryst rad først, så nyest stamp, så mains."""
    base_m = (base or {}).get("matches", {})
    ut = dict(main)
    ut["matches"] = dict(main.get("matches", {}))
    for k, rad in egen.get("matches", {}).items():
        m = ut["matches"].get(k)
        if m is None or m == rad:
            ut["matches"][k] = rad
        elif m == base_m.get(k):  # bare den egne siden har endret kampen
            ut["matches"][k] = rad
        elif rad == base_m.get(k):  # bare main har endret den
            continue
        elif bool(rad.get("frosset")) != bool(m.get("frosset")):
            ut["matches"][k] = rad if rad.get("frosset") else m
        elif (rad.get("stamp") or "") > (m.get("stamp") or ""):
            ut["matches"][k] = rad
    return ut


def flett_teller(base, main, egen):
    """Tall: utgangspunkt + økningen på hver side. «last»: den nyeste."""
    def tre(b, m, e):
        if isinstance(m, dict) or isinstance(e, dict):
            b, m, e = b if isinstance(b, dict) else {}, m if isinstance(m, dict) else {}, e if isinstance(e, dict) else {}
            return {k: tre(b.get(k), m.get(k), e.get(k)) for k in list(m) + [k for k in e if k not in m]}
        if isinstance(m, (int, float)) or isinstance(e, (int, float)):
            b0 = b if isinstance(b, (int, float)) else 0
            return (m if isinstance(m, (int, float)) else b0) + (e if isinstance(e, (int, float)) else b0) - b0
        if isinstance(m, str) and isinstance(e, str) and m[:4].isdigit() and e[:4].isdigit():
            return max(m, e)  # tidspunkter (ISO)
        return m if m is not None else e
    return tre(base or {}, main or {}, egen or {})


def main():
    filer = [f for f in git("diff", "--name-only", "--diff-filter=U").splitlines() if f]
    if not filer:
        return 0
    uloste = []
    for f in filer:
        if any(fnmatch(f, p) for p in BEHOLD_MAIN):
            git("checkout", "--ours", "--", f)
            print(f"Konflikt i {f}: beholdt mains versjon (egen odds hentes igjen i neste kjøring).")
        elif any(fnmatch(f, p) for p in PREKICK):
            base, main_, egen = stadium(1, f), stadium(2, f), stadium(3, f)
            if main_ is None or egen is None:
                uloste.append(f)
                continue
            ut = flett_prekick(base, main_, egen)
            skriv(f, ut)
            nye = len(set(egen.get("matches", {})) - set(main_.get("matches", {})))
            print(f"Konflikt i {f}: flettet, {len(ut['matches'])} kamper ({nye} bare fra egen side).")
        elif f in TELLER:
            base, main_, egen = stadium(1, f), stadium(2, f), stadium(3, f)
            if main_ is None or egen is None:
                uloste.append(f)
                continue
            skriv(f, flett_teller(base, main_, egen))
            print(f"Konflikt i {f}: tellerne flettet (utgangspunkt pluss begge sidenes økning).")
        else:
            uloste.append(f)
            continue
        git("add", "--", f)
    if uloste:
        print(f"Konflikt som ikke løses automatisk: {', '.join(uloste)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
