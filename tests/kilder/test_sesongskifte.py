"""Ende-til-ende: sesongskiftet paa simulert kalender. Kjør: python3 tests/kilder/test_sesongskifte.py

Hele veien fra "bare 2026 finnes" til "2027 er aktiv", uten at noe gjores
manuelt. Kildene er simulert, klokken er simulert, og hvert steg bruker de
samme funksjonene som workflowene kaller.

Tre forlop testes:

  A. Normalt: siste kamp -> 72 timers karens -> fersk revisjon -> frysing ->
     daglige kjoringer fram til nyttaar uten at frosne data endres -> bytte
     1. januar.
  B. Et kritisk revisjonsavvik etter 72 timer gir INGEN frysing. Naar avviket
     er lost og en fersk revisjon er gronn, skjer frysingen.
  C. Neste terminliste blir forst klar 10. januar: 1.-9. januar varsler rodt
     uten aa endre data, og 10. januar skjer byttet automatisk.
"""
import json
import json as _json
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROT / "scripts"))
import frys_sesong
import oppdag_sesong
import sesong
from ligaer import ANTALL_KAMPER, ANTALL_RUNDER, LIGAER

_json_dumps = _json.dumps
feil, antall = [], [0]


def sjekk(navn, betingelse, detalj=""):
    antall[0] += 1
    if betingelse:
        print(f"  ✓ {navn}")
    else:
        print(f"  ✗ {navn}  {detalj}")
        feil.append(navn)


# ------------------------------------------------------------- simulert verden
def terminliste(aar, lag, spilt=False):
    """Full dobbel serie: 240 kamper, 30 runder, 15 hjemme og 15 borte."""
    par = sorted((h, b) for h in lag for b in lag if h != b)
    ut = []
    for i, (h, b) in enumerate(par):
        ut.append({"round": i // 8 + 1,
                   "date": f"{aar}-{3 + (i // 8) // 4:02d}-{(i % 28) + 1:02d}",
                   "time": "18:00", "home": h, "away": b,
                   "hg": 1 if spilt else None, "ag": 0 if spilt else None})
    return ut


def sett_opp(sb, liga, aar, lag):
    """Ligamappe med ferdigspilt sesong, som etter siste runde."""
    d = sb / LIGAER[liga]["data"]
    d.mkdir(parents=True, exist_ok=True)
    rader = terminliste(aar, lag, spilt=True)
    d.joinpath("matches.json").write_text(json.dumps(rader), encoding="utf-8")
    d.joinpath("fixtures.json").write_text("[]", encoding="utf-8")
    (sb / liga).joinpath("index.html").write_text("<html></html>", encoding="utf-8")
    return rader


def skriv_revisjon(sb, liga, naa, errors=0, bekreftet=None, ferskt=True,
                   kjoring=None):
    d = sb / LIGAER[liga]["data"] / "audit_fixtures.json"
    d.write_text(json.dumps({
        "checked_date": naa.date().isoformat(),
        "checked_at": naa.isoformat(timespec="seconds"),
        "errors": errors, "warnings": 0,
        "ferskt": ferskt,
        "kjoring": kjoring if kjoring is not None else sesong.kjoring_id(),
        "bekreftet": bekreftet or {},
    }), encoding="utf-8")


def frys(sb, liga, sesong_, naa):
    """Kaller frysingens EGEN sperre, og utforer bare hvis den slipper."""
    # Neste sesong er IKKE lenger et vilkaar -- ikke_ferdig() svarer direkte
    # paa om sesongen er over.
    hindre = frys_sesong.ikke_ferdig(sb, liga, sesong_, naa=naa)
    if hindre:
        return False, hindre
    # Selve frysingen leser siden i Chrome. Her simuleres resultatet: koden
    # og dataene kopieres, og frosset.json legges ved som kontrakt.
    mal = sb / liga / sesong_
    (mal / "data").mkdir(parents=True, exist_ok=True)
    for f in (sb / LIGAER[liga]["data"]).glob("*.json"):
        shutil.copy2(f, mal / "data" / f.name)
    shutil.copy2(sb / liga / "index.html", mal / "index.html")
    (mal / "data" / "frosset.json").write_text(json.dumps(
        {"sesong": sesong_, "liga": liga,
         "frosset_at": naa.isoformat(timespec="seconds"),
         "rader": [["1", "Lag", "73"]]}), encoding="utf-8")
    return True, []


def ny_sandkasse(lag_2026):
    sb = Path(tempfile.mkdtemp())
    (sb / "data").mkdir()
    for liga in LIGAER:
        sett_opp(sb, liga, "2026", lag_2026)
        sesong.init(sb, liga, "2026", log=lambda _s: None)
    return sb


def siste_kamp(lag):
    """Avspark for den siste kampen i den genererte 2026-sesongen.

    Utledes av dataene, ikke hardkodet: karenstiden regnes fra den faktiske
    siste kampen, og en hardkodet dato ville gjort testen til en test av
    datoen framfor av regelen."""
    from zoneinfo import ZoneInfo
    r = terminliste("2026", lag, spilt=True)
    sist = max(f"{x['date']}T{x['time']}" for x in r)
    return datetime.fromisoformat(sist + ":00").replace(
        tzinfo=ZoneInfo("Europe/Oslo")).astimezone(timezone.utc)


LAG26 = sorted(LIGAER["eliteserien"]["lag"])
LAG27 = sorted(set(LAG26) - {"Start"} | {"Bryne"})
SISTE_KAMP = siste_kamp(LAG26)


# =============================================================== 1. september
print("=== 1. September 2026: bare 2026 finnes ===")
sb = ny_sandkasse(LAG26)
naa = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
se, neste, hvorfor = oppdag_sesong.bor_se_etter(sb, "eliteserien", naa, log=lambda _s: None)
sjekk("ser ikke etter neste sesong i september", not se, hvorfor)
sjekk("og begrunnelsen nevner november", "november" in hvorfor, hvorfor)
sjekk("2027 er ikke registrert",
      "2027" not in sesong.les(sb)["ligaer"]["eliteserien"]["sesonger"])
sjekk("aktiv er fortsatt 2026", sesong.aktiv_sesong(sb, "eliteserien") == "2026")

# =========================================================== 2. halv liste
print("\n=== 2. Ufullstendig 2027-terminliste dukker opp ===")
naa = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
halv = terminliste("2027", LAG27)[:120]
sesong.oppdag(sb, "eliteserien", "2027", halv, log=lambda _s: None)
blokk = sesong.les(sb)["ligaer"]["eliteserien"]
sjekk("halv liste gir status «oppdaget», ikke «klar»",
      blokk["sesonger"]["2027"]["status"] == "oppdaget",
      str(blokk["sesonger"]["2027"]["status"]))
sjekk("og valideringen sier hvorfor",
      any("kamper" in f for f in blokk["sesonger"]["2027"]["validering"]["funn"]),
      str(blokk["sesonger"]["2027"]["validering"]["funn"]))
sjekk("aktiv sesong er urørt", sesong.aktiv_sesong(sb, "eliteserien") == "2026")
sjekk("og 1. januar ville ikke byttet",
      not sesong.skal_bytte(blokk, date(2027, 1, 1))[0])

# =========================================================== 3. hel liste
print("\n=== 3. Komplett og gyldig 2027-liste ===")
hel = terminliste("2027", LAG27)
sjekk("den simulerte listen er en hel sesong",
      len(hel) == ANTALL_KAMPER
      and len({r["round"] for r in hel}) == ANTALL_RUNDER,
      f"{len(hel)} kamper, {len({r['round'] for r in hel})} runder")
sesong.oppdag(sb, "eliteserien", "2027", hel, log=lambda _s: None)
blokk = sesong.les(sb)["ligaer"]["eliteserien"]
sjekk("hel liste gir status «klar»", blokk["sesonger"]["2027"]["status"] == "klar",
      str(blokk["sesonger"]["2027"]))
sjekk("lagendringene rapporteres",
      any("Bryne" in f for f in blokk["sesonger"]["2027"]["validering"]["funn"]),
      str(blokk["sesonger"]["2027"]["validering"]["funn"]))
sjekk("men aktiv er fortsatt 2026", sesong.aktiv_sesong(sb, "eliteserien") == "2026")

# ===================================================== A. normalt forlop
print("\n=== A. Karens, frysing, ro fram til nyttår, bytte ===")
# Rett etter siste kamp: karenstiden ikke ute
skriv_revisjon(sb, "eliteserien", SISTE_KAMP + timedelta(days=1))
hindre = frys_sesong.ikke_ferdig(sb, "eliteserien", "2026",
                                 naa=SISTE_KAMP + timedelta(days=1))
sjekk("én dag etter siste kamp: fryser ikke (karenstid)",
      any("karenstiden er 14" in h for h in hindre), str(hindre))

# 72 timer senere, fersk revisjon uten avvik
naa = SISTE_KAMP + timedelta(days=15)
skriv_revisjon(sb, "eliteserien", naa)
ok, hindre = frys(sb, "eliteserien", "2026", naa)
sjekk("etter 14 dager med ren revisjon: fryses", ok, str(hindre))
sjekk("frosset.json finnes", sesong.er_frosset(sb, "eliteserien", "2026"))
sjekk("men sesongen er FORTSATT aktiv",
      sesong.aktiv_sesong(sb, "eliteserien") == "2026")

# Daglige kjoringer fram til nyttaar skal ikke roere frosne data
frosset_for = (sb / "eliteserien" / "2026" / "data" / "matches.json").read_bytes()
for dag in (25, 30):
    d = datetime(2026, 12, dag, 6, 0, tzinfo=timezone.utc)
    sjekk(f"{dag}. desember: kjeden ser at sesongen er frosset",
          sesong.er_frosset(sb, "eliteserien", sesong.aktiv_sesong(sb, "eliteserien")))
    sjekk(f"{dag}. desember: bytter ikke",
          not sesong.skal_bytte(sesong.les(sb)["ligaer"]["eliteserien"], d.date())[0])
sjekk("frosne data er uendret gjennom desember",
      (sb / "eliteserien" / "2026" / "data" / "matches.json").read_bytes() == frosset_for)

# 1. januar: byttet skjer
kode = sesong.bytt(sb, date(2027, 1, 1), utfor=True, log=lambda _s: None,
                   ligaer=["eliteserien"])
sjekk("1. januar: aktiv blir 2027", sesong.aktiv_sesong(sb, "eliteserien") == "2027")
sjekk("og exitkoden er 0", kode == 0)
sjekk("2026 er merket frosset i registeret",
      sesong.les(sb)["ligaer"]["eliteserien"]["sesonger"]["2026"]["status"] == "frosset")
sjekk("frosne data er fortsatt uendret",
      (sb / "eliteserien" / "2026" / "data" / "matches.json").read_bytes() == frosset_for)

# ===================================================== 6. ligaene uavhengige
print("\n=== 6. Eliteserien klar, OBOS ikke ===")
sjekk("OBOS står fortsatt på 2026", sesong.aktiv_sesong(sb, "obos") == "2026")
sjekk("OBOS er ikke frosset", not sesong.er_frosset(sb, "obos", "2026"))
kode_obos = sesong.bytt(sb, date(2027, 1, 1), utfor=True, log=lambda _s: None,
                        ligaer=["obos"])
sjekk("OBOS bytter ikke uten klar 2027", sesong.aktiv_sesong(sb, "obos") == "2026")
sjekk("og gir exit 1, så kjøringen ender rødt", kode_obos == 1)
sjekk("Eliteserien er upåvirket", sesong.aktiv_sesong(sb, "eliteserien") == "2027")

# ===================================================== B. avvik utsetter frysing
print("\n=== B. Kritisk revisjonsavvik utsetter frysingen ===")
sb2 = ny_sandkasse(LAG26)
sesong.oppdag(sb2, "obos", "2027", terminliste("2027", LAG27), log=lambda _s: None)
naa = SISTE_KAMP + timedelta(days=15)
skriv_revisjon(sb2, "obos", naa, errors=1)
ok, hindre = frys(sb2, "obos", "2026", naa)
sjekk("åpent kritisk avvik: fryser ikke",
      not ok and any("kritiske avvik" in h for h in hindre), str(hindre))
sjekk("og sesongen er ikke frosset", not sesong.er_frosset(sb2, "obos", "2026"))

# Bekreftet avvik som staar ulost blokkerer ogsaa
skriv_revisjon(sb2, "obos", naa, errors=0, bekreftet={"A-B": [1, "2026-01-01"]})
ok, hindre = frys(sb2, "obos", "2026", naa)
sjekk("bekreftet avvik som står uløst: fryser heller ikke",
      not ok and any("bekreftede avvik" in h for h in hindre), str(hindre))

# Avviket loses, fersk gronn revisjon
skriv_revisjon(sb2, "obos", naa, errors=0)
ok, hindre = frys(sb2, "obos", "2026", naa)
sjekk("når avviket er løst og revisjonen er grønn: fryses", ok, str(hindre))
sjekk("frosset.json finnes nå", sesong.er_frosset(sb2, "obos", "2026"))

# En gammel revisjon duger ikke
sb3 = ny_sandkasse(LAG26)
sesong.oppdag(sb3, "obos", "2027", terminliste("2027", LAG27), log=lambda _s: None)
skriv_revisjon(sb3, "obos", naa - timedelta(days=2))
hindre = frys_sesong.ikke_ferdig(sb3, "obos", "2026", naa=naa)
sjekk("en to døgn gammel revisjon er ikke fersk nok",
      any("ikke fersk" in h for h in hindre), str(hindre))

# En revisjon mot CACHET fotball.no-data duger ikke: den nedgraderer nye
# avvik til advarsler og kan ha errors=0 uten aa ha kontrollert noe.
skriv_revisjon(sb3, "obos", naa, ferskt=False)
hindre = frys_sesong.ikke_ferdig(sb3, "obos", "2026", naa=naa)
sjekk("revisjon mot cachet data duger ikke",
      any("cachet fotball.no-data" in h for h in hindre), str(hindre))

# Og en REN revisjon fra FOR siste kamp sier ingenting om sluttresultatene.
skriv_revisjon(sb3, "obos", SISTE_KAMP - timedelta(days=30))
hindre = frys_sesong.ikke_ferdig(sb3, "obos", "2026", naa=naa)
sjekk("ren revisjon fra før siste kamp åpner ikke for frysing",
      any("før siste kamp" in h for h in hindre), str(hindre))

# ===================================================== C. sen terminliste
print("\n=== C. 2027-listen blir først klar 10. januar ===")
sb4 = ny_sandkasse(LAG26)
naa = SISTE_KAMP + timedelta(days=15)
skriv_revisjon(sb4, "eliteserien", naa)
# Sesongen er ferdig og fryses i desember. Det er BARE 2027-listen som er
# sen -- frysingen venter ikke lenger paa den.
ok, hindre = frys(sb4, "eliteserien", "2026", naa)
sjekk("2026 fryses selv om 2027 ikke er oppdaget", ok, str(hindre))
data_for = (sb4 / "eliteserien" / "data" / "matches.json").read_bytes()

for dag in range(1, 10):
    d = date(2027, 1, dag)
    kode = sesong.bytt(sb4, d, utfor=True, log=lambda _s: None,
                       ligaer=["eliteserien"])
    if dag in (1, 5, 9):
        sjekk(f"{dag}. januar: varsler rødt (exit 1)", kode == 1)
        sjekk(f"{dag}. januar: aktiv er fortsatt 2026",
              sesong.aktiv_sesong(sb4, "eliteserien") == "2026")
sjekk("og ingen data er endret gjennom de ni dagene",
      (sb4 / "eliteserien" / "data" / "matches.json").read_bytes() == data_for)

# 10. januar: listen kommer, valideres, og byttet skjer i SAMME kjede
sesong.oppdag(sb4, "eliteserien", "2027", terminliste("2027", LAG27),
              log=lambda _s: None)
sjekk("10. januar: 2027 blir klar",
      sesong.les(sb4)["ligaer"]["eliteserien"]["sesonger"]["2027"]["status"] == "klar")
kode = sesong.bytt(sb4, date(2027, 1, 10), utfor=True, log=lambda _s: None,
                   ligaer=["eliteserien"])
sjekk("og byttet skjer automatisk, uten manuell inngripen",
      sesong.aktiv_sesong(sb4, "eliteserien") == "2027")
sjekk("med exit 0", kode == 0)

# ===================================================== 7. kilden forsvinner
print("\n=== 7. Kilden forsvinner eller parseren feiler ===")
sb5 = ny_sandkasse(LAG26)
naa = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
for_reg = json.dumps(sesong.les(sb5), sort_keys=True)
_ekte = oppdag_sesong.ntf_source.fetch_all
oppdag_sesong.ntf_source.fetch_all = lambda *a, **k: (_ for _ in ()).throw(
    RuntimeError("403 Forbidden"))
_ekte_rot = oppdag_sesong.ROT
oppdag_sesong.ROT = sb5
kode = oppdag_sesong.main(["eliteserien"])
oppdag_sesong.ntf_source.fetch_all = _ekte
oppdag_sesong.ROT = _ekte_rot
sjekk("en kilde som feiler gir exit 0", kode == 0)
sjekk("registeret er ikke korrumpert",
      json.dumps(sesong.les(sb5), sort_keys=True) == for_reg)
sjekk("aktiv sesong er urørt", sesong.aktiv_sesong(sb5, "eliteserien") == "2026")

# ===================================================== 8. idempotent
print("\n=== 8. Flere kjøringer: idempotent ===")
sb6 = ny_sandkasse(LAG26)
hel27 = terminliste("2027", LAG27)
sesong.oppdag(sb6, "obos", "2027", hel27, log=lambda _s: None)
etter_en = json.loads(json.dumps(sesong.les(sb6)))
for _ in range(3):
    sesong.oppdag(sb6, "obos", "2027", hel27, log=lambda _s: None)
naa_reg = sesong.les(sb6)
del etter_en["ligaer"]["obos"]["sesonger"]["2027"]["validering"]["sett"]
d2 = json.loads(json.dumps(naa_reg))
del d2["ligaer"]["obos"]["sesonger"]["2027"]["validering"]["sett"]
sjekk("fire oppdagelser gir samme register (bortsett fra tidsstempel)",
      json.dumps(etter_en, sort_keys=True) == json.dumps(d2, sort_keys=True))

naa = SISTE_KAMP + timedelta(days=15)
skriv_revisjon(sb6, "obos", naa)
frys(sb6, "obos", "2026", naa)
frosset1 = (sb6 / "obos" / "2026" / "data" / "matches.json").read_bytes()
for _ in range(3):
    sesong.bytt(sb6, date(2027, 1, 1), utfor=True, log=lambda _s: None, ligaer=["obos"])
sjekk("tre bytter etter hverandre: aktiv er 2027, ikke 2029",
      sesong.aktiv_sesong(sb6, "obos") == "2027")
sjekk("og frosne data er uendret",
      (sb6 / "obos" / "2026" / "data" / "matches.json").read_bytes() == frosset1)

# ============================================ 2/3. frysing som vilkaar for bytte
print("\n=== Frysing er vilkår for bytte ===")
for frosset in (False, True):
    sb7 = ny_sandkasse(LAG26)
    sesong.oppdag(sb7, "obos", "2027", terminliste("2027", LAG27), log=lambda _s: None)
    naa7 = SISTE_KAMP + timedelta(days=15)
    skriv_revisjon(sb7, "obos", naa7)
    if frosset:
        frys(sb7, "obos", "2026", naa7)
    reg_for = json.dumps(sesong.les(sb7), sort_keys=True)
    lg7 = []
    kode7 = sesong.bytt(sb7, date(2027, 1, 1), utfor=True, log=lg7.append, ligaer=["obos"])
    if frosset:
        sjekk("1. januar, 2027 klar OG 2026 frosset: bytter",
              sesong.aktiv_sesong(sb7, "obos") == "2027" and kode7 == 0,
              f"aktiv={sesong.aktiv_sesong(sb7, 'obos')} kode={kode7}")
    else:
        sjekk("1. januar, 2027 klar men 2026 IKKE frosset: bytter ikke",
              sesong.aktiv_sesong(sb7, "obos") == "2026")
        sjekk("og exitkoden er 1", kode7 == 1)
        sjekk("og registeret er uendret",
              json.dumps(sesong.les(sb7), sort_keys=True) == reg_for)
        sjekk("og alarmen sier at sesongen ikke er frosset",
              any("IKKE FROSSET" in m for m in lg7), str(lg7))

# ================================ 4. avvik stopper frysing OG dermed bytte
print("\n=== Uløst avvik stopper frysingen, og dermed byttet ===")
sb8 = ny_sandkasse(LAG26)
sesong.oppdag(sb8, "eliteserien", "2027", terminliste("2027", LAG27), log=lambda _s: None)
naa8 = SISTE_KAMP + timedelta(days=15)
skriv_revisjon(sb8, "eliteserien", naa8, errors=1)
ok, hindre = frys(sb8, "eliteserien", "2026", naa8)
sjekk("uløst avvik: fryser ikke", not ok, str(hindre))
kode8 = sesong.bytt(sb8, date(2027, 1, 1), utfor=True, log=lambda _s: None,
                    ligaer=["eliteserien"])
sjekk("og 1. januar bytter derfor ikke",
      sesong.aktiv_sesong(sb8, "eliteserien") == "2026" and kode8 == 1)

# 10. januar: avviket loses, fersk gronn revisjon -- frysing OG bytte i SAMME kjede
naa8b = datetime(2027, 1, 10, 6, 0, tzinfo=timezone.utc)
skriv_revisjon(sb8, "eliteserien", naa8b)
ok, hindre = frys(sb8, "eliteserien", "2026", naa8b)
sjekk("10. januar: avviket løst, 2026 fryses", ok, str(hindre))
kode8b = sesong.bytt(sb8, date(2027, 1, 10), utfor=True, log=lambda _s: None,
                     ligaer=["eliteserien"])
sjekk("og 2027 aktiveres i samme kjøring",
      sesong.aktiv_sesong(sb8, "eliteserien") == "2027" and kode8b == 0,
      f"aktiv={sesong.aktiv_sesong(sb8, 'eliteserien')} kode={kode8b}")

# ============================== 5. fotball.no viser 2027 for frysingen
print("\n=== fotball.no viser 2027 før frysingen har skjedd ===")
import daglig_revisjon as _dr
vaare_2026 = {(r["home"], r["away"]): r for r in terminliste("2026", LAG26, spilt=True)}
nff_2027 = terminliste("2027", LAG27)
_f, _a = _dr.revider(vaare_2026, nff_2027, ferskt=True, sesong="2026")
sjekk("kamper fra 2027 gir ingen kritiske avvik", not _f, str(_f[:2]))
sjekk("men de rapporteres som advarsel",
      any("annen sesong enn 2026" in x for x in _a), str(_a[:2]))

sb9 = ny_sandkasse(LAG26)
naa9 = SISTE_KAMP + timedelta(days=15)
skriv_revisjon(sb9, "obos", naa9)          # ren, fordi 2027 ikke sammenlignes
ok, hindre = frys(sb9, "obos", "2026", naa9)
sjekk("frysingen går likevel gjennom etter karenstiden", ok, str(hindre))

# ============================================ nodutgangen for aa tine
print("\n=== Nødutgang: tine en frossen sesong ===")
sjekk("tining uten begrunnelse nektes",
      frys_sesong.tin(sb9, "obos", "2026", "", log=lambda _s: None) == 2)
sjekk("sesongen er fortsatt frosset", sesong.er_frosset(sb9, "obos", "2026"))
sjekk("med begrunnelse går den gjennom",
      frys_sesong.tin(sb9, "obos", "2026", "Kamp dømt 3-0 etter protest",
                      log=lambda _s: None) == 0)
sjekk("og sesongen er ikke lenger frosset", not sesong.er_frosset(sb9, "obos", "2026"))
_tint = json.loads((sb9 / "obos" / "2026" / "data" / "tint.json").read_text("utf-8"))
sjekk("begrunnelsen er logget",
      _tint["tininger"][0]["grunn"] == "Kamp dømt 3-0 etter protest", str(_tint))
sjekk("og byttet blokkeres igjen etter tining",
      sesong.bytt(sb9, date(2027, 1, 1), utfor=True, log=lambda _s: None,
                  ligaer=["obos"]) == 1)

# ================== Bindingen til kjoringen, mot EKTE daglig_revisjon.py
print("\n=== Frysingen krever revisjon fra SAMME kjøring ===")
import daglig_revisjon as _dr2
import nff_source as _nff2
import os as _os2

# Denne testen kjorer den EKTE daglig_revisjon.main(), som bruker klokken nå.
# Sesongen maa derfor ligge i fortiden, ellers er karenstiden ikke ute.
sb10 = ny_sandkasse(LAG26)
_i_fjor = [{**r, "date": r["date"].replace("2026-", "2026-0").replace("2026-01", "2026-01")[:10]}
           for r in terminliste("2026", LAG26, spilt=True)]
_i_fjor = [{**r, "date": f"2026-0{1 + (r['round'] - 1) // 8}-{(r['round'] % 28) + 1:02d}"}
           for r in terminliste("2026", LAG26, spilt=True)]
(sb10 / LIGAER["obos"]["data"] / "matches.json").write_text(
    _json.dumps(_i_fjor), encoding="utf-8")
vaart = _i_fjor


def kjor_ekte_revisjon(sb, liga, svar, run_id):
    """Kjorer den EKTE daglig_revisjon.main() med fotball.no simulert.

    Mokker hent(), ikke fetch_all(): da gaar den virkelige cachelogikken --
    forsoksmerking, feilhaandtering og hentet-tidsstempel -- som i
    produksjon. svar=None betyr at hentingen feiler."""
    ekte_rot_dr, ekte_kat = _dr2.ROT, _nff2.CACHE_KATALOG
    ekte_hent, ekte_parse = _nff2.hent, _nff2.parse_side
    _dr2.ROT = sb
    _nff2.CACHE_KATALOG = sb / "data" / "nff-cache"
    if svar is None:
        _nff2.hent = lambda url: (_ for _ in ()).throw(RuntimeError("403 Forbidden"))
    else:
        _nff2.hent = lambda url: "<html>simulert</html>"
        _nff2.parse_side = lambda *a, **k: svar
    _os2.environ["GITHUB_RUN_ID"] = str(run_id)
    _os2.environ["GITHUB_RUN_ATTEMPT"] = "1"
    # 20-timersgrensen: nullstill forsoksmerket saa hver testkjoring henter
    for f in (sb / "data" / "nff-cache").glob("*.json"):
        d = _json.loads(f.read_text("utf-8"))
        d.pop("forsokt", None)
        f.write_text(_json.dumps(d), encoding="utf-8")
    try:
        return _dr2.main([liga])
    finally:
        _dr2.ROT, _nff2.CACHE_KATALOG = ekte_rot_dr, ekte_kat
        _nff2.hent, _nff2.parse_side = ekte_hent, ekte_parse


def hindre_naa(sb, liga, run_id):
    _os2.environ["GITHUB_RUN_ID"] = str(run_id)
    _os2.environ["GITHUB_RUN_ATTEMPT"] = "1"
    return frys_sesong.ikke_ferdig(sb, liga, "2026")


# 1) Gronn og fersk revisjon i kjoring 100
kode = kjor_ekte_revisjon(sb10, "obos", vaart, 100)
sjekk("ekte revisjon mot samme data: ingen kritiske avvik", kode == 0)
sjekk("frysing tillatt i SAMME kjøring", not hindre_naa(sb10, "obos", 100),
      str(hindre_naa(sb10, "obos", 100)))

# 2) Ny kjoring der HENTINGEN FEILER. Den gamle gronne revisjonen skal ikke
#    kunne apne for frysing.
kode = kjor_ekte_revisjon(sb10, "obos", None, 101)
h = hindre_naa(sb10, "obos", 101)
sjekk("hentingen feiler i ny kjøring: ingen frysing", bool(h), str(h))
sjekk("og grunnen er at hentingen ikke skjedde i denne kjøringen",
      any("samme kjøring" in x or "annen kjøring" in x for x in h), str(h))

# 3) Hentingen lykkes, men revisjonen finner kritisk avvik
feil_nff = [dict(r) for r in vaart]
feil_nff[0] = {**feil_nff[0], "date": "2026-12-24"}
kode = kjor_ekte_revisjon(sb10, "obos", feil_nff, 102)
sjekk("kritisk avvik: revisjonen feiler kjøringen", kode == 1)
h = hindre_naa(sb10, "obos", 102)
sjekk("og ingen frysing", any("kritiske avvik" in x for x in h), str(h))

# 4) Gront igjen
kode = kjor_ekte_revisjon(sb10, "obos", vaart, 103)
sjekk("grønn revisjon i ny kjøring: frysing tillatt igjen",
      kode == 0 and not hindre_naa(sb10, "obos", 103),
      f"kode={kode} {hindre_naa(sb10, 'obos', 103)}")
_os2.environ.pop("GITHUB_RUN_ID", None)
_os2.environ.pop("GITHUB_RUN_ATTEMPT", None)

# ====================== Reparasjon ETTER byttet
print("\n=== Tining og ny frysing etter at 2027 er aktiv ===")
sb11 = ny_sandkasse(LAG26)
naa11 = SISTE_KAMP + timedelta(days=15)
sesong.oppdag(sb11, "obos", "2027", terminliste("2027", LAG27), log=lambda _s: None)
skriv_revisjon(sb11, "obos", naa11)
frys(sb11, "obos", "2026", naa11)
sesong.bytt(sb11, date(2027, 1, 1), utfor=True, log=lambda _s: None, ligaer=["obos"])
sjekk("2027 er aktiv", sesong.aktiv_sesong(sb11, "obos") == "2027")
sjekk("og 2026 er frosset", sesong.er_frosset(sb11, "obos", "2026"))

# 2027 far sin egen tilstand, som IKKE skal roeres av reparasjonen
_akt = sb11 / LIGAER["obos"]["data"]
_akt.joinpath("audit_fixtures.json").write_text(_json_dumps({
    "checked_date": "2027-01-02", "errors": 0, "ferskt": True,
    "kjoring": "2027-kjoring", "bekreftet": {}}), encoding="utf-8")
_akt.joinpath("status.json").write_text(_json_dumps({"ok": True, "sesong": "2027"}),
                                        encoding="utf-8")
_2027_rev = _akt.joinpath("audit_fixtures.json").read_bytes()
_2027_st = _akt.joinpath("status.json").read_bytes()
_2027_data = _akt.joinpath("matches.json").read_bytes()

# En rettelse kommer inn. Ingen daglig kjede rorer 2026 lenger.
sjekk("tining av 2026 krever begrunnelse",
      frys_sesong.tin(sb11, "obos", "2026", "", log=lambda _s: None) == 2)
sjekk("med begrunnelse tines den",
      frys_sesong.tin(sb11, "obos", "2026", "Moss-Lyn dømt 3-0 etter protest",
                      log=lambda _s: None) == 0)
sjekk("2026 er ikke lenger frosset", not sesong.er_frosset(sb11, "obos", "2026"))
sjekk("men 2027 er fortsatt aktiv", sesong.aktiv_sesong(sb11, "obos") == "2027")

# Rett en kamp i 2026-dataene
_m2026 = sb11 / "obos" / "2026" / "data" / "matches.json"
_r26 = _json.loads(_m2026.read_text("utf-8"))
_r26[0] = {**_r26[0], "hg": 3, "ag": 0}
_m2026.write_text(_json.dumps(_r26), encoding="utf-8")
# turnerings-id maa ligge i sesongens egen revisjon
_rev26 = sb11 / "obos" / "2026" / "data" / "audit_fixtures.json"
_d26 = _json.loads(_rev26.read_text("utf-8"))
_d26["turnering"] = "206093"
_rev26.write_text(_json.dumps(_d26), encoding="utf-8")

# --frys-paa-nytt: henter 2026 fra sin EGEN turneringsadresse
_ekte_hent = _nff2.hent
_ekte_rot_dr = _dr2.ROT
_dr2.ROT = sb11
_hentet_url = []


def _fake_hent(url):
    _hentet_url.append(url)
    return "x"


_nff2.hent = _fake_hent
_ekte_parse = _nff2.parse_side
_nff2.parse_side = lambda *a, **k: _r26
_kode11 = frys_sesong.frys_paa_nytt(sb11, "obos", "2026", log=lambda _s: None,
                                    naa=naa11)
_nff2.hent, _nff2.parse_side, _dr2.ROT = _ekte_hent, _ekte_parse, _ekte_rot_dr

sjekk("--frys-paa-nytt henter sesongens EGEN turneringsadresse",
      any("fiksId=206093" in u for u in _hentet_url), str(_hentet_url))
sjekk("2026 er frosset på nytt", sesong.er_frosset(sb11, "obos", "2026"), f"kode={_kode11}")
sjekk("det rettede resultatet står i den frosne sesongen",
      _json.loads(_m2026.read_text("utf-8"))[0]["hg"] == 3)
sjekk("og tint.json beholder sporet",
      len(_json.loads((sb11 / "obos" / "2026" / "data" / "tint.json")
                      .read_text("utf-8"))["tininger"]) == 1)

# 2027 skal vaere HELT urort
sjekk("2027 sin revisjon er uendret",
      _akt.joinpath("audit_fixtures.json").read_bytes() == _2027_rev)
sjekk("2027 sitt stempel er uendret",
      _akt.joinpath("status.json").read_bytes() == _2027_st)
sjekk("2027 sine data er uendret",
      _akt.joinpath("matches.json").read_bytes() == _2027_data)
sjekk("og 2027 er fortsatt aktiv", sesong.aktiv_sesong(sb11, "obos") == "2027")

sjekk("uten eksplisitt sesong nektes kommandoen",
      frys_sesong.frys_paa_nytt(sb11, "obos", None, log=lambda _s: None) == 2)

print(f"\n{antall[0] - len(feil)} av {antall[0]} tester gikk gjennom.")
if feil:
    print("FEILET: " + ", ".join(feil))
sys.exit(1 if feil else 0)
