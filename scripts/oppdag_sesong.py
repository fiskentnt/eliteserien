#!/usr/bin/env python3
"""Ser etter neste sesongs terminliste, og registrerer den naar den er hel.

Uten dette maa noen huske aa kjore sesong.py for haand en gang i november.
Da er sesongskiftet ikke selvkjorende, og maskineriet blir kode ingen kjorer.

HVORDAN DEN VIRKER

Ligasiden viser bare kamper som ikke er spilt. Gjennom hosten er det de
siste rundene i inneverende sesong; naar NTF publiserer neste sesong, og
ingen av dem er spilt, er det HELE neste sesong -- 240 kamper. Det er
signalet vi venter paa, og det trengs ingen egen kilde for aa se det.

Selve vurderingen gjores IKKE her. Radene sendes til sesong.oppdag(), som
validerer dem med valider(): 16 lag, 240 kamper, 30 runder, 15 hjemme- og
15 bortekamper per lag, alle oppgjor til stede, ingen duplikater, riktig
aarstall. Status blir "klar" bare naar alt stemmer, ellers "oppdaget".
En halv terminliste blir altsaa registrert som sett, men aldri som klar.

HVORDAN DEN FEILER

Alt som kan gaa galt her -- kilden nede, markupen endret, halv liste,
manglende sesongregister -- gir varsel og avslutning 0. Den skal ALDRI
kunne odelegge aktiv sesong: den rorer bare blokken for NESTE sesong, og
bare gjennom oppdag().

BILLIG MED VILJE

Ser bare fra 1. oktober (terminlisten kommer normalt i november), hopper
over naar neste sesong alt er klar, og forsoker hoyst en gang i dognet.

Bruk:  python3 scripts/oppdag_sesong.py <liga>
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ntf_source
import sesong
from ligaer import ANTALL_KAMPER, LIGAER, oppsett

ROT = Path(__file__).resolve().parent.parent

# Terminlisten for neste sesong kommer normalt i november. For oktober er
# det ingenting aa se etter, og da skal vi ikke hente heller.
FRA_MAANED = 10
FORSOK_INTERVALL_TIMER = 20


def _tilstandssti(liga):
    return ROT / "data" / "nff-cache" / f"oppdag_{liga}.json"


def _sist_forsokt(liga):
    p = _tilstandssti(liga)
    if not p.exists():
        return None
    try:
        return datetime.fromisoformat(
            json.loads(p.read_text(encoding="utf-8"))["forsokt"])
    except Exception:
        return None


def _merk_forsok(liga, naa):
    p = _tilstandssti(liga)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"forsokt": naa.isoformat(timespec="seconds")},
                            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def bor_se_etter(rot, liga, naa, log=print):
    """(se etter?, neste sesong, begrunnelse)."""
    aktiv = sesong.aktiv_sesong(rot, liga, log=log)
    if not aktiv:
        return False, None, "ingen aktiv sesong i registeret -- gjør ingenting"
    neste = str(int(aktiv) + 1)

    blokk = sesong.les(rot).get("ligaer", {}).get(liga, {})
    status = blokk.get("sesonger", {}).get(neste, {}).get("status")
    if status in ("klar", "aktiv"):
        return False, neste, f"{neste} er allerede {status}"

    if naa.month < FRA_MAANED and naa.year <= int(aktiv):
        # %B gir engelsk maanedsnavn paa en runner uten norsk locale.
        return False, neste, (f"det er måned {naa.month}, terminlisten for "
                              f"{neste} kommer normalt i november")

    forsokt = _sist_forsokt(liga)
    if forsokt and (naa - forsokt) < timedelta(hours=FORSOK_INTERVALL_TIMER):
        timer = (naa - forsokt).total_seconds() / 3600
        return False, neste, (f"forsøkt for {timer:.0f} timer siden, "
                              f"venter til {FORSOK_INTERVALL_TIMER}")
    return True, neste, f"ser etter terminlisten for {neste}"


def main(argv):
    if not argv or argv[0] not in LIGAER:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    liga = argv[0]
    naa = datetime.now(timezone.utc)

    se, neste, hvorfor = bor_se_etter(ROT, liga, naa)
    print(f"{oppsett(liga)['visningsnavn']}: {hvorfor}")
    if not se:
        return 0

    _merk_forsok(liga, naa)
    try:
        rader = ntf_source.fetch_all(liga, log=lambda s: print(f"  {s}"))
    except Exception as e:
        # En kilde som er nede eller har lagt om skal bare varsle. Aktiv
        # sesong er urort, og vi prover igjen i morgen.
        print(f"  ADVARSEL: klarte ikke hente terminlisten "
              f"({type(e).__name__}: {e}). Prøver igjen i morgen.")
        return 0

    neste_sesong = [r for r in rader if (r.get("date") or "").startswith(neste)]
    if not neste_sesong:
        print(f"  ingen {neste}-kamper på ligasiden ennå.")
        return 0

    print(f"  fant {len(neste_sesong)} kamper i {neste} "
          f"(av {ANTALL_KAMPER} i en hel sesong)")
    try:
        sesong.oppdag(ROT, liga, neste, neste_sesong,
                      log=lambda s: print(f"  {s}"))
    except Exception as e:
        print(f"  ADVARSEL: kunne ikke registrere {neste} "
              f"({type(e).__name__}: {e}). Aktiv sesong er urørt.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
