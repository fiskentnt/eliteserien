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

Arkiveres bare i KAMPVINDUET, per liga: fra 30 minutter før dagens første
avspark til fire timer etter dagens siste. Utenfor vinduet hoppes ligaen
over, også på en kampdag -- ellers ville en kveldskamp gitt oss femti kopier
av en side som ikke endrer seg før klokka seks.

Vinduet regnes fra dagens kamper i BÅDE fixtures.json og matches.json. En
kamp som er ferdigspilt flyttes fra den ene filen til den andre, og skal
fortsatt holde vinduet åpent: det er nettopp markupen ETTER kampslutt vi
trenger for å se hvordan et endelig resultat ser ut.

Filene lagres gzippet. Sidene er svært repetitiv HTML og komprimerer 13
ganger (målt på arkivet fra 25. september 2026), så et arkiv som ellers
hadde vokst med megabyte per kjøring vokser med titalls kilobyte.

Bare ligasidene arkiveres. fotball.no holdes utenfor: robots.txt der sier
Disallow: / for alle andre enn sokemotorene, og det er uansett ligasidens
statusmerking vi skal studere.

Filnavn: <liga>/<dato>/<kilde>-<tidspunkt>.html.gz, med tidspunkt i UTC.

Bruk:  python3 scripts/arkiver_kildehtml.py <arkivkatalog> [liga ...]
"""
import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ntf_source
from ligaer import LIGAER, oppsett

ROT = Path(__file__).resolve().parent.parent
OSLO = ZoneInfo("Europe/Oslo")

# Vinduet rundt dagens kamper. Fire timer etter siste avspark dekker en kamp
# som starter presis (105 min), pluss tid til at kilden rekker å oppdatere
# seg, pluss margin for en forsinket start.
FOER_MIN = 30
ETTER_TIMER = 4


def kampdag(liga, naa):
    """Er vi i kampvinduet for denne ligaen akkurat nå?

    ARKIV_TVING_KAMPDAG=1 svarer ja uansett. Den finnes for å kunne bevise
    hele kjeden i Actions utenom en kampdag, og settes bare fra
    workflow_dispatch.

    Leses av ligaens egne fixtures.json og matches.json, som er de samme
    filene siden viser. Finner vi dem ikke, arkiverer vi heller for mye enn
    for lite -- et arkiv som mangler nettopp kampdagen er verdiløst.
    """
    if os.environ.get("ARKIV_TVING_KAMPDAG") == "1":
        return True, "kampvindu tvunget (ARKIV_TVING_KAMPDAG=1)"

    data = ROT / oppsett(liga)["data"]
    i_dag = naa.date().isoformat()
    avspark = []

    # Dagens kamper fra BEGGE filene. En ferdigspilt kamp ligger i
    # matches.json, ikke i fixtures.json, og skal fortsatt holde vinduet åpent.
    try:
        for runde in json.loads((data / "fixtures.json").read_text(encoding="utf-8")):
            avspark += _avspark_i_dag(runde.get("matches", []), i_dag)
    except Exception:
        return True, "fant ikke fixtures.json -- arkiverer for sikkerhets skyld"
    try:
        avspark += _avspark_i_dag(
            json.loads((data / "matches.json").read_text(encoding="utf-8")), i_dag)
    except Exception:
        pass

    if not avspark:
        return False, "ingen kamp i dag"

    start = min(avspark) - timedelta(minutes=FOER_MIN)
    slutt = max(avspark) + timedelta(hours=ETTER_TIMER)
    vindu = f"{start.strftime('%H:%M')}-{slutt.strftime('%H:%M')}"
    if start <= naa <= slutt:
        return True, f"i kampvinduet {vindu} ({len(avspark)} kamp(er) i dag)"
    return False, f"kamp i dag, men utenfor vinduet {vindu}"


def _avspark_i_dag(kamper, i_dag):
    """Avsparkstidspunktene for dagens kamper, som tidssonebevisste datoer.

    Avspark står i norsk lokaltid. Sommer- og vintertid skiller en time, så
    tidssonen må komme fra kalenderen, ikke fra en fast forskyvning."""
    ut = []
    for m in kamper:
        if m.get("date") != i_dag or not m.get("time"):
            continue
        try:
            ut.append(datetime.fromisoformat(
                f"{m['date']}T{m['time']}:00").replace(tzinfo=OSLO))
        except ValueError:
            continue
    return ut


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
    # fotball.no arkiveres IKKE. robots.txt der sier Disallow: / for alle
    # andre enn de navngitte sokemotorene, og arkivet henter hvert tiende
    # minutt i kampvinduet. Vi trenger det heller ikke: det vi skal studere
    # er hvordan LIGASIDEN merker en paagaaende kamp. fotball.no har ingen
    # statusmarkering i det hele tatt -- der er vernet en klokkeregel, og en
    # klokke trenger vi ikke lese markup for aa forstaa.
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
            fil = mappe / f"{navn}-{stempel}.html.gz"
            if fil.exists():
                continue
            raa = html.encode("utf-8")
            fil.write_bytes(gzip.compress(raa, 9))
            print(f"  skrev {fil.relative_to(arkiv)} "
                  f"({len(raa) / 1024:.0f} kB -> {fil.stat().st_size / 1024:.0f} kB)")
            skrevet += 1

    print(f"{skrevet} fil(er) arkivert.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
