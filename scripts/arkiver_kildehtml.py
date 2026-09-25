#!/usr/bin/env python3
"""Arkiverer rå HTML fra de offisielle kildene på kampdager, til laben.

HVORFOR: vernet mot pågående kamper er bygget mot noe vi aldri har sett.
Alle sidene vi har hentet så langt er hentet mellom runder, så vi vet ikke
hvilken CSS-klasse ligasiden gir en kamp som spilles akkurat nå, eller hva
fotball.no viser mens stillingen er 1-0 etter en halvtime.

Uten arkivet må noen sitte og følge en kamp live for å finne det ut. Med
arkivet kan vi lese det i ettertid -- og vi får samtidig eksempler på utsatte
og avbrutte kamper, som er enda sjeldnere og enda vanskeligere å treffe.

Dette er DIAGNOSTIKK. Det ligger i det private lab-repoet, ikke i
produksjonen, og det skal aldri kunne velte produksjonskjeden. Kalleren
(arkiver_til_lab.sh) svelger feil herfra.

Arkiveres bare på kampdager, for å holde arkivet lesbart: en dag der en kamp
starter, eller der en kamp startet i løpet av de siste seks timene. Da får vi
markup fra før, under og etter kamp uten å lagre 365 kopier av en side som
ikke endrer seg.

Filnavn: <liga>/<dato>/<kilde>-<tidspunkt>.html, med tidspunkt i UTC.

Bruk:  python3 scripts/arkiver_kildehtml.py <arkivkatalog> [liga ...]
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nff_source
import ntf_source
from ligaer import LIGAER, oppsett

ROT = Path(__file__).resolve().parent.parent
OSLO = ZoneInfo("Europe/Oslo")
TIMER_ETTER = 6


def kampdag(liga, naa):
    """Spilles det kamp i dag, eller startet en kamp for under seks timer siden?

    ARKIV_TVING_KAMPDAG=1 svarer ja uansett. Den finnes for å kunne bevise
    hele kjeden i Actions utenom en kampdag, og settes bare fra
    workflow_dispatch.

    Leses av ligaens egne fixtures.json og matches.json, som er de samme
    filene siden viser. Finner vi dem ikke, arkiverer vi heller for mye enn
    for lite -- et arkiv som mangler nettopp kampdagen er verdiløst.
    """
    if os.environ.get("ARKIV_TVING_KAMPDAG") == "1":
        return True, "kampdag tvunget (ARKIV_TVING_KAMPDAG=1)"

    data = ROT / oppsett(liga)["data"]
    i_dag = naa.date().isoformat()
    try:
        fx = json.loads((data / "fixtures.json").read_text(encoding="utf-8"))
    except Exception:
        return True, "fant ikke fixtures.json -- arkiverer for sikkerhets skyld"

    for runde in fx:
        for m in runde.get("matches", []):
            if m.get("date") == i_dag:
                return True, f"kamp i dag: {m['home']} - {m['away']}"

    grense = naa - timedelta(hours=TIMER_ETTER)
    try:
        ms = json.loads((data / "matches.json").read_text(encoding="utf-8"))
    except Exception:
        ms = []
    for m in ms:
        if not m.get("date") or not m.get("time"):
            continue
        try:
            # Avspark står i norsk lokaltid. Sommer- og vintertid skiller en
            # time, så tidssonen må komme fra kalenderen, ikke fra en fast verdi.
            avspark = datetime.fromisoformat(
                f"{m['date']}T{m['time']}:00").replace(tzinfo=OSLO)
        except ValueError:
            continue
        if grense <= avspark <= naa:
            return True, f"kamp nettopp spilt: {m['home']} - {m['away']}"

    return False, "ingen kamp i dag"


def hent_alle(liga):
    """(navn, html) for hver kilde. En kilde som feiler hopper vi over --
    poenget er å fange det vi får tak i, ikke å være komplett."""
    cfg = oppsett(liga)
    ut = []
    for side in ("terminliste", "resultater"):
        try:
            ut.append((f"ntf-{side}", ntf_source.hent(f"{cfg['ntf_base']}/{side}")))
        except Exception as e:
            print(f"  {liga}/ntf-{side}: {type(e).__name__}: {e}", file=sys.stderr)
    try:
        ut.append(("nff", nff_source.hent(cfg["nff_url"])))
    except Exception as e:
        print(f"  {liga}/nff: {type(e).__name__}: {e}", file=sys.stderr)
    return ut


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    arkiv = Path(argv[0])
    ligaer = argv[1:] or list(LIGAER)
    naa = datetime.now(timezone.utc)
    stempel = naa.strftime("%Y-%m-%dT%H%MZ")

    skrevet = 0
    for liga in ligaer:
        spilles, hvorfor = kampdag(liga, naa)
        if not spilles:
            print(f"{liga}: {hvorfor} -- arkiverer ikke.")
            continue
        print(f"{liga}: {hvorfor}")
        mappe = arkiv / liga / naa.date().isoformat()
        mappe.mkdir(parents=True, exist_ok=True)
        for navn, html in hent_alle(liga):
            fil = mappe / f"{navn}-{stempel}.html"
            if fil.exists():
                continue
            fil.write_text(html, encoding="utf-8")
            print(f"  skrev {fil.relative_to(arkiv)} ({len(html)} tegn)")
            skrevet += 1

    print(f"{skrevet} fil(er) arkivert.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
