#!/usr/bin/env python3
"""Port for grunnlag.yml: må grunnlagsfilen regnes på nytt for en side?

Grunnlagsfilen (<side>/data/grunnlag.json, scripts/lag_grunnlag.js) tar
flere minutter å regne. Workflowen startes etter hver kjøring av data- og
oddsjobbene, også når de ikke endret noe (planleggeren starter dem hvert
tiende minutt). Porten ser på innholdet i det siden regner med, og slipper
gjennom bare når noe av det er endret siden filen ble regnet:

  <side>/index.html          koden, med Worker-koden og konstantene
  data/model.json            lagstyrkene (teams, mu, H, att, con, ha, hc),
                             uten fitted_at og meta
  data/matches.json          resultatene
  data/fixtures.json         kampene som gjenstår
  data/odds_upcoming.json    prisene (hjemme, borte, H, D, A per kamp), uten
                             tidsstempler og kilde
  scripts/lag_grunnlag.js    skriptet som regner filen

Hashen av dette (inndata) lagres i filen av lag_grunnlag.js. Porten er bare
en billig forhåndssjekk uten nettleser. Siden bruker filen bare når SITT
fingeravtrykk stemmer (grunnlagAvtrykk på siden), så en fil porten lot stå
for lenge, gir aldri feil tall: siden regner da selv.

Ingen avhengigheter utover standardbiblioteket, ingen nettverk.

Bruk:  python3 scripts/grunnlag_port.py <side> [<side> ...]
  Skriver én linje per side: "<side>: regn|hopp over (<grunn>)", og i
  Actions til GITHUB_OUTPUT:
    ligaer=<JSON-liste over sidene som må regnes>
    inndata_<side>=<hash>
    inndata=<hash>          (bare med én side)
  TVING=true: alle sidene regnes (workflow_dispatch med tving).
"""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SIDER = ("eliteserien", "obos")


def _json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def inndata(side, root=ROOT):
    """sha256 av det siden regner med, se over. Mangler en fil, tas det med
    som null, så hashen blir en annen enn med filen."""
    d = root / side / "data"

    def les(navn, hvordan):
        p = d / navn
        if not p.exists():
            return None
        return hvordan(_json(p))

    deler = {
        "side": hashlib.sha256((root / side / "index.html").read_bytes()).hexdigest(),
        "skript": hashlib.sha256((root / "scripts" / "lag_grunnlag.js").read_bytes()).hexdigest(),
        "modell": les("model.json", lambda m: {k: m.get(k) for k in ("teams", "mu", "H", "att", "con", "ha", "hc")}),
        "resultater": les("matches.json", lambda m: m),
        "terminliste": les("fixtures.json", lambda f: f),
        "odds": les("odds_upcoming.json", lambda o: sorted(
            [r.get("home"), r.get("away"), r.get("H"), r.get("D"), r.get("A")] for r in (o.get("matches") or []))),
    }
    tekst = json.dumps(deler, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(tekst.encode("utf-8")).hexdigest()


def vurder(side, root=ROOT, tving=False):
    """(regn, inndata, grunn)."""
    h = inndata(side, root)
    if tving:
        return True, h, "tvunget (workflow_dispatch)"
    fil = root / side / "data" / "grunnlag.json"
    if not fil.exists():
        return True, h, "filen finnes ikke"
    try:
        gml = _json(fil).get("inndata")
    except (OSError, ValueError):
        return True, h, "filen kan ikke leses"
    if gml != h:
        return True, h, "inndataene er endret siden filen ble regnet"
    return False, h, "inndataene er uendret"


def main(argv):
    sider = argv or list(SIDER)
    tving = os.environ.get("TVING") == "true"
    regnes, ut = [], []
    for side in sider:
        regn, h, grunn = vurder(side, tving=tving)
        print(f"{side}: {'regn' if regn else 'hopp over'} ({grunn})", file=sys.stderr)
        if regn:
            regnes.append(side)
        ut.append(f"inndata_{side}={h}")
    ut.append(f"ligaer={json.dumps(regnes)}")
    if len(sider) == 1:
        ut.append(f"inndata={ut[0].split('=', 1)[1]}")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write("\n".join(ut) + "\n")
    print("\n".join(ut))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
