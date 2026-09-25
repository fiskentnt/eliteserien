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
    python3 frys_sesong.py <rot> <liga> [<sesong>]
    python3 frys_sesong.py <rot> <liga> <sesong> --tin --grunn "..."  (nodutgang)
    python3 frys_sesong.py <rot> <liga> <sesong> --frys-paa-nytt      (etter tining)
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


# Karenstid etter siste kamp. Fjorten dager, ikke tre: en protest eller en
# kamp som dommes i etterkant kan ta uker, og en frysing som skjer for tidlig
# laser inn feilen for godt.
#
# Marginen er trang for Eliteserien. Siste kamp i 2026 er 13. desember, saa
# sesongen kan tidligst fryses 27. desember -- fem dager for byttet. OBOS har
# 40 dager. Rekker ikke frysingen, bytter ikke sesongen heller (det er et
# vilkaar), og kjoringen blir rod hver dag til den er gjort.
KARENS_DAGER = 14


def ikke_ferdig(rot, liga, sesong, naa=None, sesongmappe=False):
    """Hva som gjenstaar for sesongen kan kalles FERDIG. Tom liste = ferdig.

    "Ferdig" er tre ting, ikke bare at kampene er spilt:

      1. alle kamper har resultat
      2. det har gaatt minst 14 dager siden siste kamp
      3. en revisjon mot fotball.no som er FERSK, utfort i SAMME KJORING,
         etter siste kamp, og uten apne kritiske avvik

    naa kan settes for aa prove et forlop paa en simulert kalender.

    Karenstiden og revisjonen er der fordi resultater kan endres i etterkant
    -- en kamp som domme 3-0 etter protest, en rettet feilregistrering. En
    frysing som skjer for tidlig laser inn feilen for godt, og det er nettopp
    det frysingen skal hindre.
    """
    import json as _json
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    oslo = ZoneInfo("Europe/Oslo")
    # sesongmappe=True leser <liga>/<sesong>/data i stedet for <liga>/data.
    # Brukes ved reparasjon av en avsluttet sesong, der den aktive sesongens
    # data ikke har noe med saken aa gjore.
    data = (Path(rot) / liga / str(sesong) / "data" if sesongmappe
            else Path(rot) / liga / "data")
    naa = naa or datetime.now(timezone.utc)
    ut = []

    # 1) alle kamper spilt
    try:
        fx = _json.loads((data / "fixtures.json").read_text(encoding="utf-8"))
        uspilt = [m for r in fx for m in r["matches"] if not m.get("played")]
        if uspilt:
            ut.append(f"{len(uspilt)} kamp(er) mangler fortsatt resultat")
    except Exception as e:
        ut.append(f"kunne ikke lese fixtures.json ({type(e).__name__})")

    # 2) karenstid etter siste kamp
    siste = None
    try:
        m = _json.loads((data / "matches.json").read_text(encoding="utf-8"))
        tider = []
        for x in m:
            if x.get("date") and x.get("time"):
                try:
                    tider.append(datetime.fromisoformat(
                        f"{x['date']}T{x['time']}:00").replace(tzinfo=oslo))
                except ValueError:
                    continue
        if tider:
            siste = max(tider)
            dager = (naa - siste).total_seconds() / 86400
            if dager < KARENS_DAGER:
                ut.append(f"bare {dager:.1f} dager siden siste kamp "
                          f"(karenstiden er {KARENS_DAGER})")
    except Exception as e:
        ut.append(f"kunne ikke lese matches.json ({type(e).__name__})")

    # 3) fersk revisjon uten apne kritiske avvik
    rev = data / "audit_fixtures.json"
    if not rev.exists():
        ut.append("ingen terminlisterevisjon er kjørt")
    else:
        try:
            d = _json.loads(rev.read_text(encoding="utf-8"))
            if int(d.get("errors") or 0):
                ut.append(f"{d['errors']} åpne kritiske avvik i revisjonen")
            elif d.get("bekreftet"):
                ut.append(f"{len(d['bekreftet'])} bekreftede avvik står uløst")
            # FERSK betyr at fotball.no-dataene ble hentet i den kjoringen
            # revisjonen gikk -- ikke bare at filen er ny. En revisjon mot
            # cachet data nedgraderer nye avvik til advarsler, og kan derfor
            # ha errors=0 uten aa ha kontrollert noe.
            if not d.get("ferskt"):
                ut.append("siste revisjon gikk mot cachet fotball.no-data, "
                          "ikke mot data hentet i samme kjøring")
            # SAMME KJORING. En gronn revisjon fra i gaar sier ingenting om
            # at dagens henting gikk bra -- den kan ha feilet, eller
            # revisjonssteget kan ha krasjet, uten at filen ble roert.
            import sesong as _s2
            naa_id = _s2.kjoring_id()
            if d.get("kjoring") != naa_id:
                ut.append(f"revisjonen er fra en annen kjøring "
                          f"({d.get('kjoring')}, nå {naa_id})")
            sett = datetime.fromisoformat(d["checked_at"])
            alder = (naa - sett).total_seconds() / 3600
            if alder > 24:
                ut.append(f"revisjonen er {alder:.0f} timer gammel, ikke fersk")
            # Revisjonen maa vaere utfort ETTER siste kamp. En ren revisjon
            # fra midtsesongen sier ingenting om sluttresultatene.
            if siste and sett < siste:
                ut.append(f"revisjonen er fra {sett:%Y-%m-%d}, før siste kamp "
                          f"{siste:%Y-%m-%d}")
        except Exception as e:
            ut.append(f"kunne ikke lese revisjonen ({type(e).__name__})")
    return ut


def tin(rot, liga, sesong, grunn, log=print):
    """NODUTGANG: tiner en frossen sesong. Ikke del av den automatiske flyten.

    Frysing er ment aa vaere endelig. Men et resultat KAN endres etter at vi
    har frosset -- en protest som fores, en kamp som dommes 3-0 uker etterpaa.
    Da er det frosne bildet feil, og et feil historisk bilde er verre enn
    ingen frysing.

    Begrunnelsen er PAAKREVD og lagres i tint.json ved siden av sesongen.
    Det er hele poenget: en tining skal etterlate et spor som forklarer
    hvorfor historikken ble endret. Uten den logges ingenting, og om et aar
    vet ingen hvorfor tallene ikke stemmer med det folk husker.

    Etter tining kjorer den daglige kjeden igjen som normalt, og frysingen
    skjer paa nytt naar kriteriene er oppfylt.

    Bruk:  python3 scripts/frys_sesong.py <rot> <liga> <sesong> --tin \
               --grunn "Sarpsborg-Brann dommet 3-0 etter protest 12. januar"
    """
    from datetime import datetime, timezone
    mal = Path(rot) / liga / str(sesong)
    markor = mal / "data" / "frosset.json"
    if not markor.exists():
        log(f"{liga}/{sesong} er ikke frosset -- ingenting aa tine.")
        return 1
    if not (grunn or "").strip():
        log("NEKTER: --grunn er paakrevd. En tining som ikke forklarer seg "
            "etterlater en historikk ingen kan stole paa.")
        return 2

    tint = mal / "data" / "tint.json"
    tidligere = []
    if tint.exists():
        try:
            tidligere = json.loads(tint.read_text(encoding="utf-8")).get("tininger", [])
        except Exception:
            tidligere = []
    frosset_at = None
    try:
        frosset_at = json.loads(markor.read_text(encoding="utf-8")).get("frosset_at")
    except Exception:
        pass
    tidligere.append({"tint_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "grunn": grunn.strip(), "var_frosset_at": frosset_at})
    tint.write_text(json.dumps({"liga": liga, "sesong": str(sesong),
                                "note": ("Sporet etter hver tining av denne sesongen. "
                                         "Frysing er ment aa vaere endelig; staar det "
                                         "noe her, er historikken endret etter at den "
                                         "var laast, og grunnen skal staa nedenfor."),
                                "tininger": tidligere},
                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    markor.unlink()
    log(f"TINT {liga}/{sesong}. Grunn: {grunn.strip()}")
    log(f"  logget i {tint.relative_to(Path(rot))} ({len(tidligere)} tining(er) totalt)")
    log(f"  den daglige kjeden kjorer naa igjen, og fryser paa nytt naar "
        f"kriteriene er oppfylt.")
    return 0


def frys_paa_nytt(rot, liga, sesong, log=print, naa=None):
    """Revisjon OG frysing av EN BESTEMT sesong, alt i samme prosess.

    HVORFOR DEN TRENGS: kommer en rettelse etter at neste sesong er aktiv,
    kjorer ingen daglig kjede for den gamle sesongen lenger. Den blir
    staaende tint. Og frysingen krever at revisjonen skjedde i SAMME
    kjoring, saa to separate kommandoer ville aldri matchet.

    SESONGEN OPPGIS EKSPLISITT. Kommandoen bruker aldri aktiv sesong: etter
    byttet er 2027 aktiv, mens det er 2026 som skal repareres.

    Alt leses og skrives i <liga>/<sesong>/data, aldri i <liga>/data. Ellers
    ville reparasjonen overskrevet den aktive sesongens revisjon, bekreftede
    avvik og stempel.

    fotball.no viser den aktive sesongen, saa 2026 hentes med sin egen
    turnerings-id (se nff_source.turnering_url). Hentingen gaar direkte,
    ikke gjennom den daglige 20-timersgrensen -- en manuell reparasjon skal
    ikke stoppes av at kjeden hentet tidligere samme dag.

    FRAMGANGSMAATE ved en rettelse etter byttet:

      1. Tin:  frys_sesong.py . <liga> <sesong> --tin --grunn "..."
      2. Rett dataene i <liga>/<sesong>/data/ (matches.json, og bygg
         model.json paa nytt om resultatet endret seg)
      3. Frys: frys_sesong.py . <liga> <sesong> --frys-paa-nytt
    """
    import daglig_revisjon
    if not sesong:
        log("NEKTER: sesongen maa oppgis eksplisitt. Etter byttet er det den "
            "AVSLUTTEDE sesongen som skal repareres, ikke den aktive.")
        return 2
    kat = Path(rot) / liga / str(sesong) / "data"
    if not kat.exists():
        log(f"Finner ikke {kat} -- er sesongen frosset en gang?")
        return 1

    log(f"1. Reviderer {liga}/{sesong} i sin egen mappe ...")
    kode = daglig_revisjon.revider_sesong(liga, sesong, naa=naa, log=log)
    if kode != 0:
        log(f"   revisjonen fant kritiske avvik -- fryser ikke. "
            f"Rett dem forst, se {liga}/{sesong}/data/audit_fixtures.json.")
        return 1

    log(f"2. Fryser {liga}/{sesong} paa nytt ...")
    hindre = ikke_ferdig(Path(rot), liga, sesong, naa=naa, sesongmappe=True)
    if hindre:
        log("   NEKTER:")
        for h in hindre:
            log(f"     - {h}")
        return 1
    markor = kat / "frosset.json"
    markor.write_text(json.dumps({
        "sesong": str(sesong), "liga": liga,
        "frosset_at": (naa or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "note": ("Frosset paa nytt etter en rettelse. Se tint.json for "
                 "hvorfor sesongen ble tint."),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"   {liga}/{sesong} er frosset paa nytt.")
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip(), file=sys.stderr); return 2
    rot, liga = Path(sys.argv[1]).resolve(), sys.argv[2]
    if "--frys-paa-nytt" in sys.argv:
        # Ingen reserve til aktiv sesong: den ville pekt paa 2027 mens det er
        # 2026 som skal repareres.
        ses = next((a for a in sys.argv[3:] if a[:1].isdigit()), None)
        return frys_paa_nytt(rot, liga, ses)
    if "--tin" in sys.argv:
        ses = next((a for a in sys.argv[3:] if a[:1].isdigit()), None)
        grunn = (sys.argv[sys.argv.index("--grunn") + 1]
                 if "--grunn" in sys.argv else "")
        if not ses:
            import sesong as _s
            ses = _s.aktiv_sesong(rot, liga, log=lambda m: None)
        return tin(rot, liga, ses, grunn)
    if len(sys.argv) > 3 and sys.argv[3][:1].isdigit():
        sesong = sys.argv[3]
    else:
        # Sesongen leses fra registeret naar den ikke er oppgitt. Da slipper
        # workflowen aa regne den ut i en shell-substitusjon.
        import sesong as _ses
        sesong = _ses.aktiv_sesong(rot, liga, log=lambda s: print(f"  {s}"))
        if not sesong:
            print("Ingen aktiv sesong i registeret -- fryser ingenting.",
                  file=sys.stderr)
            return 0
    kilde = rot / liga
    mal = kilde / sesong
    if not (kilde / "index.html").exists():
        print(f"finner ikke {kilde}/index.html", file=sys.stderr); return 1

    # NAAR ER SESONGEN FERDIG?
    #
    # Frysing er irreversibel i praksis. Kommer det en utsatt kamp, et rettet
    # resultat eller en protest ETTER at vi har frosset, er det frosne bildet
    # feil -- og det er nettopp bildet som ikke skal kunne endres.
    #
    # Tidligere ventet vi paa at neste sesongs terminliste skulle dukke opp,
    # som en ERSTATNING for aa vite om sesongen var over. Den er fjernet:
    # ikke_ferdig() svarer paa sporsmaalet direkte -- alle kamper spilt, 72
    # timer siden siste kamp, og en fersk revisjon uten apne avvik.
    #
    # Erstatningen var dessuten skadelig. Den utsatte frysingen til ETTER at
    # NTF publiserte neste sesong, altsaa til kildene hadde begynt aa vise
    # 2027. Naa fryses sesongen mens kildene fortsatt er enige om den.
    #
    # --uten-sperre finnes bare for testing i sandkasse.
    hindre = ikke_ferdig(rot, liga, sesong)
    if hindre and "--uten-sperre" not in sys.argv:
        print(f"NEKTER Å FRYSE {sesong}:", file=sys.stderr)
        for h in hindre:
            print(f"  - {h}", file=sys.stderr)
        print(f"  Frysing skal ikke låse inn en feil. Prøver igjen ved neste "
              f"daglige kjøring.", file=sys.stderr)
        print(f"  (--uten-sperre kan brukes i sandkasse.)", file=sys.stderr)
        return 3

    return main_frys(rot, liga, sesong)


def main_frys(rot, liga, sesong, log=print):
    kilde = rot / liga
    mal = kilde / sesong
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
        "frosset_at": (naa or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
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
