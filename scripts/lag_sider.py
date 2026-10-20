#!/usr/bin/env python3
"""Lager de statiske delene av sidene fra <liga>/data/tekster.json (20.10.2026).

Chrome henter, Python lager sidene: scripts/lag_grunnlag.js skriver
tekster.json fra siden selv med den ferdige grunnlagsfilen (tabellen slik siden
viser den, overskriftene for sjansene, når det ble regnet). Dette skriptet
skriver ut fra den, uten Chrome og uten å regne noe:

  <liga>/index.html  regionene STATISK-KOLONNER, STATISK-TABELL og
                     STATISK-OPPDATERT (scripts/statisk_region.py): tabellen
                     med tall og sjanser i HTML-en, for søkemotorer og uten
                     JavaScript; render() på siden tar over
                     STATISK-OPPSUMMERING øverst (fase 1a): hvem som leder i
                     hver sone, hvem som ligger nærmest nedrykk, og rundens
                     viktigste kamp, som setninger, med når det ble regnet
  index.html         (forsiden) STATISK-ELITESERIEN og STATISK-OBOS: den
                     samme oppsummeringen, kort, for hver liga

Setningene bygges av tallene slik siden viste dem (vist tekst og status for
hver sone); ingenting regnes.

Kjøres av grunnlag-workflowen etter lag_grunnlag.js, og alt committes sammen.

  python3 scripts/lag_sider.py [liga ...]          skriv (standard: begge)
  python3 scripts/lag_sider.py --check [liga ...]  er sidene laget fra filen?
"""
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from statisk_region import med_statiske, statiske  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIGAER = ("eliteserien", "obos")
MAANEDER = ("januar", "februar", "mars", "april", "mai", "juni", "juli", "august",
            "september", "oktober", "november", "desember")


def norsk_tid(iso):
    """'2026-10-20T02:42:09Z' -> '20. oktober 2026 kl. 04.42' (norsk tid)."""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Oslo"))
    return f"{t.day}. {MAANEDER[t.month - 1]} {t.year} kl. {t.hour:02d}.{t.minute:02d}"


def tall(n):
    """100000 -> '100 000' med hardt mellomrom, som på siden."""
    return f"{n:,}".replace(",", " ")


def liste(ord_):
    return ord_[0] if len(ord_) == 1 else ", ".join(ord_[:-1]) + " og " + ord_[-1]


def les(liga, root=ROOT):
    return json.loads((root / liga / "data" / "tekster.json").read_text(encoding="utf-8"))


def oppdatert(t):
    navn = [k["navn"][0].lower() + k["navn"][1:] for k in t["tabell"]["kolonner"]]
    return (f"Oppdatert {norsk_tid(t['laget'])}. Sjansene for {liste(navn)} er regnet fra "
            f"{tall(t['sesonger'])} simulerte sesonger.")


def sone_navn(t, key):
    k = next(x for x in t["tabell"]["kolonner"] if x["key"] == key)
    return k["navn"][0].lower() + k["navn"][1:]


def _vist(r, key):
    """Sjansen slik siden viste den, med hardt mellomrom foran %, som på siden
    (ellers kan «42» og «%» havne på hver sin linje)."""
    return r["sjanser"][key]["vist"].replace(" %", "\u00a0%")


def _lag_pst(r, key, parentes=False):
    return f"{r['lag']} ({_vist(r, key)})" if parentes else f"{r['lag']} {_vist(r, key)}"


def _aapne(t, key, minst):
    """Lagene der sonen fortsatt er åpen og sjansen er minst «minst», størst først."""
    rader = [r for r in t["tabell"]["rader"] if r["sjanser"][key]["avgjort"] == 0 and r["sjanser"][key]["andel"] >= minst]
    return sorted(rader, key=lambda r: -r["sjanser"][key]["andel"])


def _sikre(t, key):
    return [r["lag"] for r in t["tabell"]["rader"] if r["sjanser"][key]["avgjort"] == 1]


def topp_setning(t):
    """«Bodø/Glimt har 69 % sjanse for gull og Viking 31 %.» Sikret: «X har sikret gull.»"""
    navn, deler = sone_navn(t, "gull"), []
    sikre = _sikre(t, "gull")
    if sikre:
        deler.append(f"{liste(sikre)} har sikret {navn}.")
    aapne = _aapne(t, "gull", 0.005)[:3]
    if aapne:
        resten = [_lag_pst(r, "gull") for r in aapne[1:]]
        deler.append(f"{aapne[0]['lag']} har {_vist(aapne[0], 'gull')} sjanse for {navn}"
                     + (f" og {resten[0]}" if len(resten) == 1 else f", {liste(resten)}" if resten else "") + ".")
    return " ".join(deler)


def midt_setning(t):
    """«I kampen om topp 4 har Rosenborg 65 %, Molde 64 % ... og Brann 1 %.» Åpne lag med 1 til 99 %."""
    aapne = [r for r in _aapne(t, "europa", 0.01) if r["sjanser"]["europa"]["andel"] <= 0.99][:5]
    if not aapne:
        return ""
    return f"I kampen om {sone_navn(t, 'europa')} har {liste([_lag_pst(r, 'europa') for r in aapne])}."


def bunn_setning(t):
    """«Start (90 %) og Kristiansund (76 %) ligger nærmest nedrykk.» Avgjort: «X er rykket ned.»"""
    deler = []
    sikre = _sikre(t, "ned")
    if sikre:
        deler.append(f"{liste(sikre)} er rykket ned.")
    aapne = _aapne(t, "ned", 0.01)[:2]
    if aapne:
        deler.append(f"{liste([_lag_pst(r, 'ned', True) for r in aapne])} ligger nærmest {sone_navn(t, 'ned')}.")
    return " ".join(deler)


def oppsummering(t, kort=False):
    """Setningene øverst på ligasiden (kort: på forsiden, uten midten og kampen)."""
    deler = [topp_setning(t)] + ([] if kort else [midt_setning(t)]) + [bunn_setning(t)]
    tekst = " ".join(html.escape(d, quote=False) for d in deler if d)
    # Rundens viktigste kamp: i en egen span, som siden skjuler når banneret
    # rett under viser den samme setningen (renderQaHighlight).
    if not kort and t.get("viktigste") and t["viktigste"].get("banner"):
        tekst += f' <span class="opps-kamp">{html.escape(t["viktigste"]["banner"], quote=False)}</span>'
    return f'{tekst} <span class="opps-dato">Oppdatert {norsk_tid(t["laget"])}.</span>'


def forside(root=ROOT, ligaer=LIGAER):
    """Forsiden med den korte oppsummeringen for hver liga som har tekster.json."""
    side = (root / "index.html").read_text(encoding="utf-8")
    regioner = statiske(side)
    for liga in ligaer:
        if (root / liga / "data" / "tekster.json").exists():
            regioner[liga.upper()] = oppsummering(les(liga, root), kort=True)
    return med_statiske(side, regioner)


def ligaside(liga, root=ROOT):
    """Ligasiden med de statiske regionene fra tekster.json."""
    side = (root / liga / "index.html").read_text(encoding="utf-8")
    t = les(liga, root)
    return med_statiske(side, {**statiske(side),
                               "KOLONNER": t["tabell"]["kolonner_html"],
                               "TABELL": t["tabell"]["rader_html"],
                               "OPPDATERT": oppdatert(t),
                               "OPPSUMMERING": oppsummering(t)})


def main(argv):
    sjekk = "--check" in argv
    ligaer = [a for a in argv if not a.startswith("-")] or list(LIGAER)
    feil = 0
    # Forsiden har én region per liga; hver liga skriver bare sin egen, så de
    # to grunnlag-jobbene ikke endrer de samme linjene.
    for navn, fil, ny in [(f"{liga}/index.html", ROOT / liga / "index.html", ligaside(liga)) for liga in ligaer] + \
            [("index.html (forsiden)", ROOT / "index.html", forside(ligaer=ligaer))]:
        gml = fil.read_text(encoding="utf-8")
        if sjekk:
            if ny == gml:
                print(f"{navn} er laget fra tekster.json.")
            else:
                print(f"{navn} er IKKE laget fra tekster.json.\n"
                      f"  Kjør: python3 scripts/lag_sider.py", file=sys.stderr)
                feil = 1
        elif ny != gml:
            fil.write_text(ny, encoding="utf-8")
            print(f"Skrev {navn} fra tekster.json.")
        else:
            print(f"{navn} var uendret.")
    return feil


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
