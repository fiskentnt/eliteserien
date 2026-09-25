#!/usr/bin/env python3
"""Fryser en avsluttet sesong til en stabil, selvstendig adresse.

HVORFOR DET MÅ GJØRES SLIK: siden regner ut prosentene i nettleseren fra
model.json og matches.json hver gang den åpnes. En frossen kopi av bare
datafilene er derfor ikke nok -- en senere endring i JavaScript gir andre
tall fra de samme dataene.

Derfor fryses KODEN OG DATAENE SAMMEN. Alle fetch-kall i index.html er
relative ("data/..."), så en kopi av index.html ved siden av en kopi av
data/ laster de frosne filene av seg selv. Ingen stier skrives om.

I tillegg lagres de FERDIG UTREGNEDE tallene i frosset.json, lest ut av
siden i Chrome. Det er kontrakten: en test kan siden lese den frosne siden
på nytt og bekrefte at den fortsatt viser de samme tallene.

Bruk:
    python3 frys_sesong.py <rot> <liga> <sesong>
      rot      repo-rot (eller en sandkasse-kopi)
      liga     eliteserien | obos
      sesong   f.eks. 2026
"""
import json, shutil, subprocess, sys, os
from datetime import datetime, timezone
from pathlib import Path

HER = Path(__file__).resolve().parent
# Filene som utgjør sesongtilstanden. Alt annet er avledet eller irrelevant.
DATAFILER = ["matches.json", "fixtures.json", "model.json", "odds.json",
             "odds_closing.json", "odds_fd.json", "accuracy.json", "history.json",
             "lastmatch.json", "keymatch.json", "prekick.json", "status.json"]


def les_side(rot, sti, ut):
    pp = os.environ.get("NODE_PATH") or str(
        Path(os.environ.get("TMPDIR", "/tmp")) / "tabellkalkulator-pp/node_modules")
    r = subprocess.run(["node", str(HER / "les_side.js"), str(rot), sti, str(ut)],
                       env={**os.environ, "NODE_PATH": pp},
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"kunne ikke lese siden: {r.stderr.strip()[:300]}")
    return json.loads(Path(ut).read_text(encoding="utf-8"))


def main():
    if len(sys.argv) < 4:
        print(__doc__.strip(), file=sys.stderr); return 2
    rot, liga, sesong = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
    kilde = rot / liga
    mal = kilde / sesong
    if not (kilde / "index.html").exists():
        print(f"finner ikke {kilde}/index.html", file=sys.stderr); return 1

    # SPERRE: ikke frys før neste sesongs terminliste er på plass.
    #
    # Frysing er irreversibel i praksis. Kommer det en utsatt kamp, et rettet
    # resultat eller en protest ETTER at vi har frosset, er det frosne bildet
    # feil -- og det er nettopp bildet som ikke skal kunne endres.
    #
    # At neste sesongs terminliste finnes er den beste indikasjonen vi har på
    # at sesongen faktisk er ferdig, og ikke bare ser ferdig ut. Den kommer
    # normalt flere uker etter siste runde.
    #
    # --uten-sperre finnes bare for testing i sandkasse.
    neste = str(int(sesong) + 1)
    reg = rot / "data" / "sesonger.json"
    klar = False
    if reg.exists():
        d = json.loads(reg.read_text(encoding="utf-8"))
        # Registeret er per liga (version 2): at 2027 er klar i Eliteserien
        # sier ingenting om OBOS, og skal ikke kunne låse opp frysing der.
        blokk = d.get("ligaer", {}).get(liga, {})
        st = blokk.get("sesonger", {}).get(neste, {}).get("status")
        klar = st in ("oppdaget", "klar", "aktiv")
    if not klar and "--uten-sperre" not in sys.argv:
        print(f"NEKTER Å FRYSE {sesong}: terminlisten for {neste} er ikke oppdaget.",
              file=sys.stderr)
        print(f"  Kjør oppdag_sesong.py først. Frysing før etterfølgeren finnes "
              f"gir et bilde vi ikke kan rette.", file=sys.stderr)
        print(f"  (--uten-sperre kan brukes i sandkasse.)", file=sys.stderr)
        return 3
    if not klar:
        print(f"   ADVARSEL: sperren er overstyrt, {neste} er ikke oppdaget.")

    # 1) Les hva siden viser NÅ, før noe fryses. Dette er fasiten.
    print(f"1. Leser hva {liga}/ viser nå ...")
    foer = les_side(rot, f"{liga}/", HER / "_foer.json")
    print(f"   {len(foer['rader'])} rader, tittel {foer['tittel']!r}")

    # 2) Frys koden og dataene sammen
    print(f"2. Fryser til {liga}/{sesong}/ ...")
    mal.mkdir(parents=True, exist_ok=True)
    (mal / "data").mkdir(exist_ok=True)
    shutil.copy2(kilde / "index.html", mal / "index.html")
    tatt = []
    for f in DATAFILER:
        s = kilde / "data" / f
        if s.exists():
            shutil.copy2(s, mal / "data" / f)
            tatt.append(f)
    # Filer siden henter men som ikke skal fryses: odds for KOMMENDE kamper.
    # Sesongen er over, så det finnes ingen. Tom fil hindrer 404 i konsollen.
    (mal / "data" / "odds_upcoming.json").write_text(
        json.dumps({"fetched_at": None, "matches": []}) + "\n", encoding="utf-8")
    print(f"   index.html + {len(tatt)} datafiler")

    # 3) Les den frosne siden og bekreft at den viser det samme
    print(f"3. Leser den frosne siden ...")
    etter = les_side(rot, f"{liga}/{sesong}/", HER / "_etter.json")

    # 4) Kontrakten
    avvik = []
    if len(foer["rader"]) != len(etter["rader"]):
        avvik.append(f"ulikt antall rader: {len(foer['rader'])} mot {len(etter['rader'])}")
    for i, (a, b) in enumerate(zip(foer["rader"], etter["rader"])):
        if a != b:
            avvik.append(f"rad {i+1}: {a} != {b}")
    (mal / "data" / "frosset.json").write_text(json.dumps({
        "sesong": sesong, "liga": liga,
        "frosset_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": ("Ferdig utregnede tall, lest ut av siden i Chrome ved frysing. "
                 "Kontrakt: den frosne siden skal alltid vise disse tallene. "
                 "Avviker den, er noe i den frosne kopien endret."),
        "hoder": etter["hoder"], "rader": etter["rader"],
        "datafiler": tatt,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"4. Kontrakt lagret i {liga}/{sesong}/data/frosset.json")
    if avvik:
        print(f"\n   AVVIK ({len(avvik)}):")
        for a in avvik[:6]:
            print(f"     {a}")
        return 1
    print(f"\n   BESTATT: den frosne siden viser NOYAKTIG samme tall "
          f"({len(foer['rader'])} rader, {len(foer['hoder'])} kolonner).")
    if etter["feil"]:
        print(f"   men JS-feil pa den frosne siden: {etter['feil']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
