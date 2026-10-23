#!/usr/bin/env python3
"""Sjansen per lag etter hver runde, slik siden viste den (23.10.2026).

<liga>/data/sjansehistorikk.json har ett punkt per runde: sjansen i hver sone
(gull, Champions League, topp 4/topp 6, kvalik, nedrykk) for alle lagene, fra
grunnlagsfilen (100 000 sesonger, tallene siden viser). Lagsidene viser det
under «Sjansen for ... de siste rundene» (scripts/lag_sider.py).

Rundene står i samme rekkefølge som rundevelgeren på siden (buildRoundSeq):
etter mediandatoen, og en kamp mer enn seks dager fra den er flyttet ut av
runden (en hel utsatt runde, som runde 12 i 2026, havner der den spilles). En
runde er ferdig når alle dens egne kamper er spilt. Punktet for runden er det
siste siden viste før neste runde begynte: oppdateres til første kamp i en ny
runde er spilt, og står fast etter det.

  python3 scripts/sjansehistorikk.py [liga ...]           oppdater fra dagens filer
  python3 scripts/sjansehistorikk.py --fyll-bakover liga   bygg fra git-historikken
                                                           til grunnlag.json (én gang)

Kjøres av grunnlag-workflowen etter lag_grunnlag.js og før lag_sider.py.
"""
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIGAER = ("eliteserien", "obos")
SAMLET_DAGER = 6        # som RUNDE_SAMLET_DAGER på siden


def terminliste(matches, fixtures):
    """Alle kampene (spilte og kommende), uten doble, som (runde, dato, spilt)."""
    kamper = {}
    for m in matches:
        kamper[(m["home"], m["away"])] = (m["round"], m["date"], m.get("hg") is not None)
    for r in fixtures:
        for m in r["matches"]:
            kamper.setdefault((m["home"], m["away"]), (r["round"], m["date"], m.get("hg") is not None))
    return list(kamper.values())


def rundefolge(kamper):
    """Rundene i rekkefølge som på siden: [(runde, egne kamper (dato, spilt), siste dato)]."""
    per = {}
    for runde, dato, spilt in kamper:
        per.setdefault(runde, []).append((dato, spilt))
    ut = []
    for runde, liste in per.items():
        d = sorted(x[0] for x in liste)
        midt = d[len(d) // 2]
        m = date.fromisoformat(midt)
        fra, til = (m - timedelta(days=SAMLET_DAGER)).isoformat(), (m + timedelta(days=SAMLET_DAGER)).isoformat()
        egne = [x for x in liste if fra <= x[0] <= til]
        ut.append((midt, runde, egne, max(x[0] for x in egne)))
    return [(r, egne, slutt) for _, r, egne, slutt in sorted(ut)]


def tilstand(kamper):
    """(nr, runde, dato) for siste ferdige runde når neste ikke har begynt, ellers None."""
    folge = rundefolge(kamper)
    k = 0
    while k < len(folge) and all(spilt for _, spilt in folge[k][1]):
        k += 1
    if k == 0 or any(spilt for _, egne, _ in folge[k:] for _, spilt in egne):
        return None
    runde, _, slutt = folge[k - 1]
    return k, runde, slutt


def sjanser(grunnlag, soner):
    """{lag: {sone: andel}} fra grunnlagsfilen (plassfordelingen, som på siden)."""
    n, base, lag = grunnlag["sesonger"], grunnlag["utfall"]["base"], grunnlag["lag"]
    p = len(lag)
    return {t: {k: round(sum(base[i * p + pl - 1] for pl in range(z["lo"], z["hi"] + 1)) / n, 4) for k, z in soner.items()}
            for i, t in enumerate(lag)}


def punkt(kamper, grunnlag, soner, utsatte):
    t = tilstand(kamper)
    if not t:
        return None
    nr, runde, slutt = t
    merke = f"{runde} {utsatte[str(runde)]}" if str(runde) in utsatte else str(runde)
    return {"nr": nr, "runde": runde, "merke": merke, "dato": slutt, "laget": grunnlag.get("laget"), "lag": sjanser(grunnlag, soner)}


def legg_til(hist, p):
    """Punktet erstatter det for samme runde, ellers legges det til."""
    rundene = [x for x in hist["runder"] if x["nr"] != p["nr"]] + [p]
    hist["runder"] = sorted(rundene, key=lambda x: x["nr"])


def tom():
    return {"versjon": 1, "note": "Sjansen per lag etter hver runde, slik siden viste den (grunnlagsfilen, 100 000 sesonger). "
            "Se scripts/sjansehistorikk.py.", "runder": []}


def les(liga, root=ROOT):
    f = root / liga / "data" / "sjansehistorikk.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else tom()


def skriv(liga, hist, root=ROOT):
    f = root / liga / "data" / "sjansehistorikk.json"
    ny = json.dumps(hist, ensure_ascii=False, indent=1) + "\n"
    if f.exists() and f.read_text(encoding="utf-8") == ny:
        return False
    f.write_text(ny, encoding="utf-8")
    return True


def _regler(liga, root):
    r = json.loads((root / liga / "data" / "tekster.json").read_text(encoding="utf-8"))["regler"]
    return r["soner"], r.get("utsatte_runder", {})


def oppdater(liga, root=ROOT):
    d = root / liga / "data"
    les_ = lambda n: json.loads((d / n).read_text(encoding="utf-8"))
    soner, utsatte = _regler(liga, root)
    p = punkt(terminliste(les_("matches.json"), les_("fixtures.json")), les_("grunnlag.json"), soner, utsatte)
    hist = les(liga, root)
    if p:
        legg_til(hist, p)
    return skriv(liga, hist, root), p


def fyll_bakover(liga, root=ROOT):
    """Går gjennom commitene som endret grunnlag.json, eldst først, med
    kampene slik de var i samme commit."""
    git = lambda *a: subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout
    vis = lambda c, f: json.loads(git("show", f"{c}:{liga}/data/{f}"))
    soner, utsatte = _regler(liga, root)
    hist = tom()
    for c in git("log", "--reverse", "--format=%H", "--", f"{liga}/data/grunnlag.json").split():
        try:
            g = vis(c, "grunnlag.json")
            p = punkt(terminliste(vis(c, "matches.json"), vis(c, "fixtures.json")), g, soner, utsatte)
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            continue
        if p and g.get("sesonger"):
            legg_til(hist, p)
    return skriv(liga, hist, root), hist


def main(argv):
    ligaer = [a for a in argv if not a.startswith("-")] or list(LIGAER)
    for liga in ligaer:
        if "--fyll-bakover" in argv:
            endret, hist = fyll_bakover(liga)
            print(f"{liga}: {len(hist['runder'])} runder fra git-historikken "
                  f"({', '.join(x['merke'] for x in hist['runder'])}){'' if endret else ', uendret'}.")
        else:
            endret, p = oppdater(liga)
            print(f"{liga}: {'runde ' + p['merke'] + (' oppdatert' if endret else ' uendret') if p else 'mellom to runder, ingen endring'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
