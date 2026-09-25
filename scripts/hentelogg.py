#!/usr/bin/env python3
"""Logg over hver henting fra kildene. En linje per forsok.

HVORFOR: tilstandsfilene husker bare SISTE utfall. Du kan se at forrige
henting gikk bra, men ikke hvor ofte en kilde har feilet, eller om den har
vaert nede i en uke. Det er samme hull som gjor at OBOS og fotball.no
"feiler gront": de logger en advarsel og lar kjoringen bli gronn, og uten en
historikk er det ingenting som viser at det har skjedd fem dager paa rad.

FORMAT: en JSONL-fil per KJORING,

    data/hentelogg/<YYYY-MM>/<dato>-<workflow>-<run_id>-<attempt>.jsonl

Ikke EN felles fil, og ikke en per workflow: to kjoringer fra ulike
checkouts som legger til linjer i samme fil gir konflikt i git, og en rebase
taper da linjer -- samme problem som OddsPapi-telleren hadde. Med en fil per
kjoring kan det ikke skje.

VIKTIG OM UTFALLENE: feiler en henting og koden faller tilbake paa cache
eller en reservekilde, logges "feil" for selve forsoket. "cache" kan komme i
tillegg, men skjuler aldri at hentingen feilet -- feil_paa_rad() teller bare
ok og feil.

Linjene er smaa og skrives bare naar en henting faktisk skjer -- ikke i de
kjoringene porten stopper. Det blir noen faa linjer i dognet.

Bruk:
    python3 scripts/hentelogg.py sammendrag [dager]   # utfall per kilde
    python3 scripts/hentelogg.py feil [dager]         # bare det som gikk galt
    python3 scripts/hentelogg.py sjekk [dager]        # exit 1 hvis en kilde er ute
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent
# HENTELOGG_KATALOG finnes for testene: failsafe-suiten kjorer de ekte
# skriptene i EGNE PROSESSER, og en subprosess kan ikke fanges opp ved aa
# sette KATALOG i testen. Uten denne la testkjoringene igjen loggfiler i
# produksjonsdataene. Produksjonen setter den ikke.
KATALOG = Path(os.environ.get("HENTELOGG_KATALOG") or ROT / "data" / "hentelogg")

# Hvor mange forsok paa rad som maa feile for det regnes som at kilden er ute.
# To kan vaere et blaff; tre paa rad er et monster.
FEIL_PAA_RAD_GRENSE = 3


def _fil(naa):
    """EN FIL PER KJORING. To kjoringer fra ulike checkouts kan da aldri
    legge til linjer i samme fil, og en rebase kan ikke tape linjer.

    Aa stole paa at concurrency-gruppen koer kjoringer av samme workflow er
    for svakt: gruppen kan endres, og en gjenopptatt kjoring har samme
    workflow-navn. Lokalt finnes ingen run_id, og da holder dato pluss
    prosess-id."""
    wf = os.environ.get("GITHUB_WORKFLOW", "lokal").replace("/", "-").replace(" ", "_")
    rid = os.environ.get("GITHUB_RUN_ID")
    hale = (f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" if rid
            else f"pid{os.getpid()}")
    return KATALOG / f"{naa:%Y-%m}" / f"{naa:%Y-%m-%d}-{wf}-{hale}.jsonl"


def logg(liga, kilde, utfall, melding="", kamper=None, naa=None):
    """Skriver en linje. utfall: ok | cache | feil | hoppet.

    Skal ALDRI kunne velte en kjoring -- en logg som feiler er en mistet
    linje, ikke en grunn til aa stoppe."""
    try:
        naa = naa or datetime.now(timezone.utc)
        rad = {"tid": naa.isoformat(timespec="seconds"), "liga": liga,
               "kilde": kilde, "utfall": utfall}
        if kamper is not None:
            rad["kamper"] = kamper
        if melding:
            rad["melding"] = str(melding)[:200]
        rid = os.environ.get("GITHUB_RUN_ID")
        if rid:
            rad["kjoring"] = f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
        f = _fil(naa)
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rad, ensure_ascii=False) + "\n")
    except Exception:
        pass


def les(dager=14, naa=None):
    """Alle linjer fra de siste dogn, eldste forst."""
    naa = naa or datetime.now(timezone.utc)
    grense = naa - timedelta(days=dager)
    ut = []
    if not KATALOG.exists():
        return ut
    for f in sorted(KATALOG.rglob("*.jsonl")):
        for linje in f.read_text(encoding="utf-8").splitlines():
            if not linje.strip():
                continue
            try:
                r = json.loads(linje)
                t = datetime.fromisoformat(r["tid"])
            except Exception:
                continue
            if t >= grense:
                r["_t"] = t
                ut.append(r)
    ut.sort(key=lambda r: r["_t"])
    return ut


def feil_paa_rad(liga, kilde, dager=14, naa=None):
    """Hvor mange forsok paa rad som har feilet, nyeste forst.

    Dette er svaret tilstandsfilene ikke kan gi: de husker bare siste
    utfall. En kilde som har feilet tre ganger paa rad er ute, ikke uheldig.
    """
    rader = [r for r in les(dager, naa)
             if r.get("liga") == liga and r.get("kilde") == kilde
             and r.get("utfall") in ("ok", "feil")]
    n = 0
    for r in reversed(rader):
        if r["utfall"] == "feil":
            n += 1
        else:
            break
    return n


def ute(dager=14, naa=None):
    """Kilder som har feilet FEIL_PAA_RAD_GRENSE ganger eller mer paa rad."""
    par = {(r.get("liga"), r.get("kilde")) for r in les(dager, naa)}
    ut = []
    # Bare kilden maa vaere navngitt. Krevde vi ogsaa liga, ville kilder som
    # ikke horer til EN liga -- OddsPapi deler nokkel og kvote mellom dem --
    # aldri kunne utlose alarmen, uansett hvor lenge de var nede.
    for liga, kilde in sorted((x for x in par if x[1]), key=lambda x: (x[0] or "", x[1])):
        n = feil_paa_rad(liga, kilde, dager, naa)
        if n >= FEIL_PAA_RAD_GRENSE:
            ut.append((liga, kilde, n))
    return ut


def sammendrag(dager=14, bare_feil=False, naa=None):
    rader = les(dager, naa)
    if not rader:
        print(f"Ingen hentinger logget de siste {dager} døgnene.")
        return 0

    etter = defaultdict(lambda: defaultdict(int))
    for r in rader:
        etter[(r.get("liga"), r.get("kilde"))][r.get("utfall")] += 1

    print(f"Hentinger siste {dager} døgn ({len(rader)} forsøk):\n")
    print(f"  {'liga':12} {'kilde':16} {'ok':>5} {'cache':>6} {'feil':>5}  {'på rad':>6}")
    for (liga, kilde), tall in sorted(etter.items(), key=lambda x: (x[0][0] or "", x[0][1] or "")):
        if bare_feil and not tall.get("feil"):
            continue
        rad = feil_paa_rad(liga, kilde, dager, naa)
        merke = "  <-- UTE" if rad >= FEIL_PAA_RAD_GRENSE else ""
        print(f"  {liga or '?':12} {kilde or '?':16} {tall.get('ok', 0):>5} "
              f"{tall.get('cache', 0):>6} {tall.get('feil', 0):>5}  {rad:>6}{merke}")

    feilene = [r for r in rader if r.get("utfall") == "feil"]
    if feilene:
        print(f"\n  De siste feilene:")
        for r in feilene[-8:]:
            print(f"    {r['tid'][:16]}  {r.get('liga', '?')}/{r.get('kilde', '?')}: "
                  f"{r.get('melding', '')[:80]}")

    nede = ute(dager, naa)
    if nede:
        print()
        for liga, kilde, n in nede:
            print(f"  ADVARSEL: {liga}/{kilde} har feilet {n} ganger på rad. "
                  f"Kilden er sannsynligvis ute.")
    return 1 if nede else 0


def sjekk(dager=14, naa=None):
    """Exit 1 hvis en kilde har feilet FEIL_PAA_RAD_GRENSE ganger paa rad.

    Kalles som eget steg TIL SLUTT i kjeden, etter at data er lagret: en
    kilde som er ute skal gjore kjoringen rod, men ikke hindre at dagens
    data blir skrevet."""
    nede = ute(dager, naa)
    if not nede:
        print(f"Hentelogg: ingen kilde har feilet {FEIL_PAA_RAD_GRENSE} "
              f"ganger på rad.")
        return 0
    i_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    for liga, kilde, n in nede:
        melding = (f"{liga}/{kilde} har feilet {n} ganger på rad -- kilden er "
                   f"sannsynligvis ute.")
        if i_actions:
            # Kildenavnet skal staa i selve feilmeldingen paa kjoringen, ikke
            # bare i loggen: det er hele poenget med at steget er rodt.
            print(f"::error title=Kilde ute: {liga}/{kilde}::{melding}")
        print(f"FEIL: {melding}", file=sys.stderr)
    print(f"Se 'python3 scripts/hentelogg.py feil' for detaljene.",
          file=sys.stderr)
    return 1


def main(argv):
    cmd = argv[0] if argv else "sammendrag"
    dager = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 14
    if cmd in ("sammendrag", "feil"):
        return sammendrag(dager, bare_feil=(cmd == "feil"))
    if cmd == "sjekk":
        return sjekk(dager)
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
