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

# ETT sted hindrer at testene skriver i produksjonsdataene. Se tests/conftest.py.
sys.path.insert(0, str(ROT / "tests"))
import conftest as _vern
_VERN = _vern.vern()
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
    # 20-timersgrensen: nullstill forsoksmerket saa hver testkjoring henter
    for f in (sb / "data" / "nff-cache").glob("*.json"):
        d = _json.loads(f.read_text("utf-8"))
        d.pop("forsokt", None)
        f.write_text(_json.dumps(d), encoding="utf-8")
    try:
        # miljo() gjenoppretter GITHUB_* noyaktig -- ogsaa naar revisjonen
        # kaster. En pop etterpaa ville slettet verdier vi ikke satte.
        with _vern.miljo(GITHUB_RUN_ID=str(run_id), GITHUB_RUN_ATTEMPT="1"):
            return _dr2.main([liga])
    finally:
        _dr2.ROT, _nff2.CACHE_KATALOG = ekte_rot_dr, ekte_kat
        _nff2.hent, _nff2.parse_side = ekte_hent, ekte_parse


def hindre_naa(sb, liga, run_id):
    with _vern.miljo(GITHUB_RUN_ID=str(run_id), GITHUB_RUN_ATTEMPT="1"):
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

# ============ Sesongslutt: tom terminliste, hele kjeden fram til frysing
print("\n=== Sesongslutt: tom terminliste, hele kjeden fram til frysing ===")
import ntf_source as _ntf3

# Datoen ligger INNE i frysevinduet: Eliteseriens siste kamp er 13. desember,
# karenstiden er 14 dager, og byttet skjer 1. januar. En test utenfor vinduet
# ville ikke provd det som faktisk skal skje.
_SISTE_DES = "2026-12-13"
_NAA_DES = datetime(2026, 12, 28, 12, 0, tzinfo=timezone.utc)

_RAD_MAL = '''<tr class="schedule__match schedule__match--{kl}">
 <td class="schedule__match__item schedule__match__item--round"><span>#{r}</span></td>
 <td class="schedule__match__item schedule__match__item--teams">
   {h} - <span class="results__team--opponent">{b}</span></td>
 {res}
 <td class="schedule__match__item schedule__match__item--date">{dag}.<span
   class="schedule__match__item--date__year">2026</span> 18:00</td>
 <td class="schedule__match__item schedule__match__item--league"><img alt="Eliteserien"/></td>
</tr>'''


def _des_sesong(lag, utsatt=0):
    """Hele sesongen, siste runde 13. desember. utsatt=N lar N kamper staa
    uspilt -- altsaa etter siste oppsatte runde, slik en utsatt kamp gjor."""
    par = sorted((h, b) for h in lag for b in lag if h != b)
    ut = []
    for i, (h, b) in enumerate(par):
        runde = i // 8 + 1
        # Siste runde havner paa 13. desember, de andre fordelt bakover.
        dag = 13 - (30 - runde)
        mnd, dato = (12, f"{dag:02d}.12") if dag >= 1 else (11, f"{30 + dag:02d}.11")
        ut.append({"round": runde, "date": f"2026-{mnd:02d}-{dato[:2]}",
                   "time": "18:00", "home": h, "away": b,
                   "spilt": i < len(par) - utsatt})
    return ut


def _res_rad(r):
    return _RAD_MAL.format(
        kl="played", r=r["round"], h=r["home"], b=r["away"],
        dag=r["date"][8:10] + "." + r["date"][5:7],
        res='<td class="schedule__match__item schedule__match__item--result">2 - 1</td>')


# En terminliste med rader som FINNES, men ikke kan tolkes: lagnavnet er
# ukjent. Da skal parse_rad kaste, og det er en ekte feil -- ikke en tom
# side vi kan godta.
_UTOLKELIG = _RAD_MAL.format(
    kl="upcoming", r=30, h="Et Lag Som Ikke Finnes", b="Brann", dag="20.12",
    res="")


def _des_sider(rader, term="tom", dupliser=0, uspilt_rad=0):
    """(resultater-HTML, terminliste-HTML).

    term: "tom" (ingen gjenkjennelige rader) eller "utolkelig".
    dupliser: N rader gjentas, saa radtallet stemmer men parene ikke er unike.
    uspilt_rad: N rader staar med resultatcellen fjernet -- kampen finnes paa
    resultatsiden, men er ikke ferdig."""
    spilte = [r for r in rader if r["spilt"]]
    html_rader = [_res_rad(r) for r in spilte]
    for i in range(uspilt_rad):
        html_rader[i] = _RAD_MAL.format(
            kl="upcoming", r=spilte[i]["round"], h=spilte[i]["home"],
            b=spilte[i]["away"],
            dag=spilte[i]["date"][8:10] + "." + spilte[i]["date"][5:7], res="")
    for i in range(dupliser):
        html_rader.append(html_rader[i])
    term_html = ("<html><body><table></table></body></html>" if term == "tom"
                 else "<table>" + _UTOLKELIG + "</table>")
    return "<table>" + "".join(html_rader) + "</table>", term_html


def _kjed_til_frysing(lag, utsatt, run_id, **sider):
    """Kjorer den FAKTISKE kjeden: ligasiden -> matches/fixtures -> ekte
    daglig_revisjon mot ren fotball.no-data i samme kjoring -> ikke_ferdig.

    Returnerer (feilmelding fra fetch_all eller None, loggrader, gjenstaar)."""
    rader = _des_sesong(lag, utsatt=utsatt)
    res_html, term_html = _des_sider(rader, **sider)
    sb = ny_sandkasse(lag)
    import hentelogg as _hl3
    _hl3.KATALOG = Path(tempfile.mkdtemp()) / "hentelogg"

    # Sesongautoriteten skal leses fra SANDKASSEN, ikke fra repoet: regelen
    # for "komplett sesong" er sesong.valider(), og den trenger aarstallet
    # fra data/sesonger.json.
    ekte_hent3, ekte_rot3 = _ntf3.hent, _ntf3.ROT
    _ntf3.ROT = sb
    _ntf3.hent = lambda url, **kw: (res_html if url.endswith("resultater")
                                    else term_html)
    hentet, kastet = None, None
    try:
        with _vern.miljo(GITHUB_RUN_ID=str(run_id), GITHUB_RUN_ATTEMPT="1"):
            try:
                hentet = _ntf3.fetch_all("eliteserien", log=lambda _s: None,
                                         naa=_NAA_DES)
            except Exception as e:
                kastet = f"{type(e).__name__}: {e}"
    finally:
        _ntf3.hent, _ntf3.ROT = ekte_hent3, ekte_rot3
    # hentelogg.logg stempler med den EKTE klokken, ikke _NAA_DES. Leses
    # loggen med desemberdatoen, faller alle linjene utenfor vinduet.
    logg = list(_hl3.les())
    if kastet:
        return kastet, logg, None, sb

    # Kjeden skriver dataene, slik produksjonen gjor.
    d = sb / LIGAER["eliteserien"]["data"]
    _spilte = [{"home": r["home"], "away": r["away"], "date": r["date"],
                "time": r["time"], "round": r["round"],
                "hg": 2 if r["spilt"] else None, "ag": 1 if r["spilt"] else None}
               for r in rader]
    d.joinpath("matches.json").write_text(_json.dumps(_spilte), encoding="utf-8")
    # MERK: vaare_kamper() leser matches.json FORST og lar fixtures.json
    # overstyre. Radene her maa derfor ha dato og avspark, ellers ser
    # revisjonen "dato None hos oss" for hver kamp.
    _runder = {}
    for r in _spilte:
        _runder.setdefault(r["round"], []).append(
            {"home": r["home"], "away": r["away"], "date": r["date"],
             "time": r["time"], "hg": r["hg"], "ag": r["ag"],
             "played": r["hg"] is not None})
    d.joinpath("fixtures.json").write_text(_json.dumps(
        [{"round": k, "matches": v} for k, v in sorted(_runder.items())]),
        encoding="utf-8")

    # Ekte daglig_revisjon.main(), med klokken satt til frysevinduet.
    class _Klokke(datetime):
        @classmethod
        def now(cls, tz=None):
            return _NAA_DES if tz else _NAA_DES.replace(tzinfo=None)

    ekte_dt = _dr2.datetime
    _dr2.datetime = _Klokke
    try:
        # Frysingen krever en revisjon fra SAMME kjoring, saa ikke_ferdig maa
        # ligge inne i den samme miljo()-blokken. Laa den utenfor, ville
        # GITHUB_RUN_ID vaert borte og sperren slaatt inn av feil grunn.
        with _vern.miljo(GITHUB_RUN_ID=str(run_id), GITHUB_RUN_ATTEMPT="1"):
            kode = kjor_ekte_revisjon(sb, "eliteserien", _spilte, run_id)
            gjenstaar = frys_sesong.ikke_ferdig(sb, "eliteserien", "2026",
                                                naa=_NAA_DES)
    finally:
        _dr2.datetime = ekte_dt
    return None, logg, (kode, gjenstaar), sb


# --- 1) 240 unike ferdige resultater + tom terminliste
_kastet1, _logg1, _res1, _sb1 = _kjed_til_frysing(LAG26, utsatt=0, run_id=300)
sjekk("240 unike ferdige + tom terminliste: kjeden går videre",
      _kastet1 is None, str(_kastet1))
_r1 = [r for r in _logg1 if r["kilde"] == "ntf-resultater"]
sjekk("resultatsiden ga 240 kamper",
      _r1 and _r1[-1]["kamper"] == 240, str(_r1))
_t1 = [r for r in _logg1 if r["kilde"] == "ntf-terminliste"]
sjekk("den tomme terminlisten logges som «ok» med kamper=0",
      _t1 and _t1[-1]["utfall"] == "ok" and _t1[-1]["kamper"] == 0, str(_t1))
sjekk("og meldingen sier at sesongen er ferdigspilt",
      _t1 and "ferdigspilt" in _t1[-1].get("melding", ""), str(_t1))
sjekk("ingen falsk feilrekke bygges",
      _logg1 and all(r["utfall"] == "ok" for r in _logg1),
      str([(r["kilde"], r["utfall"]) for r in _logg1]))
sjekk("revisjonen er ren", _res1 and _res1[0] == 0, str(_res1))
sjekk("og frysing er tillatt", _res1 and not _res1[1], str(_res1 and _res1[1]))

# --- 2) 239 unike ferdige resultater + tom terminliste
_kastet2, _logg2, _res2, _sb2 = _kjed_til_frysing(LAG26, utsatt=1, run_id=301)
sjekk("239 unike ferdige + tom terminliste: kjeden stopper",
      _kastet2 is not None, str(_kastet2))
_t2 = [r for r in _logg2 if r["kilde"] == "ntf-terminliste"]
sjekk("og det logges som feil", _t2 and _t2[-1]["utfall"] == "feil", str(_t2))
sjekk("med den manglende kampen i meldingen, ikke en dato",
      _t2 and "ikke ferdigspilt" in _t2[-1].get("melding", "")
      and "239" in _t2[-1].get("melding", ""), str(_t2))

# --- 3) 240 resultatrader, men EN kamp er ikke ferdig
_kastet3, _logg3, _res3, _sb3 = _kjed_til_frysing(
    LAG26, utsatt=0, run_id=302, uspilt_rad=1)
sjekk("240 rader der én ikke er ferdig + tom terminliste: feil",
      _kastet3 is not None, str(_kastet3))
_t3 = [r for r in _logg3 if r["kilde"] == "ntf-terminliste"]
sjekk("antall RADER er ikke nok -- det må være ferdigspilte par",
      _t3 and _t3[-1]["utfall"] == "feil", str(_t3))

# --- 4) Komplett sesong, men terminlisten har rader som ikke kan tolkes
_kastet4, _logg4, _res4, _sb4 = _kjed_til_frysing(
    LAG26, utsatt=0, run_id=303, term="utolkelig")
sjekk("terminliste med utolkelige rader: feil, ikke «tom»",
      _kastet4 is not None and "EsDataError" in _kastet4, str(_kastet4))
_t4 = [r for r in _logg4 if r["kilde"] == "ntf-terminliste"]
sjekk("og det logges som feil med tolkningsfeilen",
      _t4 and _t4[-1]["utfall"] == "feil"
      and "ukjent lagnavn" in _t4[-1].get("melding", ""), str(_t4))

# --- 5) Tom resultatside
_kastet5, _logg5, _res5, _sb5 = _kjed_til_frysing(LAG26, utsatt=240, run_id=304)
sjekk("tom resultatside: feil", _kastet5 is not None, str(_kastet5))
_r5 = [r for r in _logg5 if r["kilde"] == "ntf-resultater"]
sjekk("resultatsiden kan aldri være tom",
      _r5 and _r5[-1]["utfall"] == "feil"
      and "aldri være tom" in _r5[-1].get("melding", ""), str(_r5))
sjekk("og terminlisten ble aldri hentet",
      not [r for r in _logg5 if r["kilde"] == "ntf-terminliste"], str(_logg5))

# --- 6) 239 unike par + EN duplikat = 240 rader
_kastet6, _logg6, _res6, _sb6 = _kjed_til_frysing(
    LAG26, utsatt=1, run_id=305, dupliser=1)
_r6 = [r for r in _logg6 if r["kilde"] == "ntf-resultater"]
sjekk("239 unike par + én duplikat gir også 240 rader",
      _r6 and _r6[-1]["kamper"] == 240, str(_r6))
sjekk("men det godtas ikke som komplett sesong", _kastet6 is not None,
      str(_kastet6))
_t6 = [r for r in _logg6 if r["kilde"] == "ntf-terminliste"]
sjekk("sesong.valider() fanger duplikatet eller det manglende oppgjøret",
      _t6 and _t6[-1]["utfall"] == "feil"
      and ("forekommer flere ganger" in _t6[-1].get("melding", "")
           or "mangler" in _t6[-1].get("melding", "")), str(_t6))

# ============ Sesonggrensen: 2027 publisert mens 2026 er aktiv
print("\n=== Sesonggrensen i produksjonskjeden ===")
# Grensen laa fram til naa INDIREKTE i slaa_sammen() sin duplikatregel. Den
# gjorde to ting galt: oppdagelsen ble blind (alle 2027-rader kastet), og
# etter at kildene flippet ble 2027-datoer skrevet OG pushet for kjoringen
# ble rod. Naa staar grensen eksplisitt i kjeden.
import update_data as _ud
from reconcile_ny import (bare_aktiv_sesong as _bas, FeilSesong as _FS,
                          behold_eksisterende as _bh, rimelige_datoer as _rd2)

_par27 = sorted((h, b) for h in LAG26 for b in LAG26 if h != b)


def _sider27(res_aar="2026", mangler=0, res_har_resultat=True):
    """(resultater-HTML, terminliste-HTML): terminlisten er alltid 2027."""
    res = [_RAD_MAL.format(
        kl="played" if res_har_resultat else "upcoming",
        r=i // 8 + 1, h=h, b=b, dag=f"{1 + (i // 8) % 28:02d}.11",
        res=('<td class="schedule__match__item schedule__match__item--result">2 - 1</td>'
             if res_har_resultat else "")).replace(">2026<", f">{res_aar}<")
        for i, (h, b) in enumerate(_par27[:len(_par27) - mangler])]
    term = [_RAD_MAL.format(kl="upcoming", r=i // 8 + 1, h=h, b=b,
                            dag="05.04", res="").replace(">2026<", ">2027<")
            for i, (h, b) in enumerate(_par27)]
    return "<table>" + "".join(res) + "</table>", "<table>" + "".join(term) + "</table>"


_EKS26 = [{"home": h, "away": b, "date": f"2026-11-{1 + (i // 8) % 28:02d}",
           "time": "18:00", "round": i // 8 + 1, "hg": 2, "ag": 1, "src": "ntf"}
          for i, (h, b) in enumerate(_par27)]


def _hent(res_html, term_html, sb, naa=None):
    ekte_hent, ekte_rot = _ntf3.hent, _ntf3.ROT
    _ntf3.ROT = sb
    _ntf3.hent = lambda url, **kw: (res_html if url.endswith("resultater")
                                    else term_html)
    try:
        return _ntf3.fetch_all("eliteserien", log=lambda _s: None,
                               naa=naa or _NAA_DES)
    finally:
        _ntf3.hent, _ntf3.ROT = ekte_hent, ekte_rot


def _bit_for_bit(m):
    lagret = {(r["home"], r["away"]): (r["date"], r["time"], r["round"],
                                       r["hg"], r["ag"]) for r in _EKS26}
    return all(lagret.get((r["home"], r["away"]))
               == (r["date"], r["time"], r["round"], r["hg"], r["ag"])
               for r in m) and len(m) == len(_EKS26)


# --- 1) 240 ferdige 2026 + komplett publisert 2027
_sb27 = ny_sandkasse(LAG26)
_res, _term = _sider27()
_alle = _hent(_res, _term, _sb27)
sjekk("fetch_all ser BEGGE sesongene (480 rader)", len(_alle) == 480,
      str(len(_alle)))
_logg27 = []
_aktive, _ford = _bas(_alle, "2026", log=_logg27.append)
sjekk("sesonggrensen slipper bare 2026 gjennom", len(_aktive) == 240
      and all(r["date"].startswith("2026") for r in _aktive), str(len(_aktive)))
sjekk("og logger antall og år ÉN gang",
      len(_logg27) == 1 and "240" in _logg27[0] and "2027" in _logg27[0],
      str(_logg27))
_m1 = _rd2(_bh(_ud.reconcile(_aktive, [], [], [], log=lambda _s: None), _EKS26,
               log=lambda _s: None), _EKS26, "2026", log=lambda _s: None)[0]
sjekk("2026-dataene er bit for bit uendret", _bit_for_bit(_m1))
sjekk("ingen 2027-dato kommer inn",
      all(r["date"].startswith("2026") for r in _m1))
sjekk("ingen duplikatadvarsler lenger -- året er med i nøkkelen",
      not [1 for _r in _alle
           if sum(1 for _x in _alle if (_x["date"][:4], _x["home"], _x["away"])
                  == (_r["date"][:4], _r["home"], _r["away"])) > 1])

# --- 2) 239 aktive 2026-rader: 2027 skal ALDRI erstatte den manglende
_res2, _term2 = _sider27(mangler=1)
_aktive2, _ = _bas(_hent(_res2, _term2, _sb27), "2026", log=lambda _s: None)
sjekk("239 aktive rader går gjennom", len(_aktive2) == 239, str(len(_aktive2)))
_mangler_par = _par27[-1]
sjekk("og den manglende kampen er IKKE erstattet av 2027-raden",
      not [r for r in _aktive2
           if (r["home"], r["away"]) == _mangler_par], str(_mangler_par))
_m2 = _rd2(_bh(_ud.reconcile(_aktive2, [], [], [], log=lambda _s: None), _EKS26,
               log=lambda _s: None), _EKS26, "2026", log=lambda _s: None)[0]
sjekk("behold_eksisterende tar den tilbake med LAGRET 2026-dato",
      _bit_for_bit(_m2))

# --- 3) Bare 2027-rader mens aktiv er 2026
_res3, _term3 = _sider27(res_aar="2027")
_alle3 = _hent(_res3, _term3, _sb27)
sjekk("kildene viser bare 2027",
      {r["date"][:4] for r in _alle3} == {"2027"},
      str({r["date"][:4] for r in _alle3}))
try:
    _bas(_alle3, "2026", log=lambda _s: None)
    _kastet3 = None
except _FS as e:
    _kastet3 = str(e)
sjekk("sesonggrensen kaster FeilSesong", _kastet3 is not None)
sjekk("og sier hvilke år den fant",
      _kastet3 and "2027" in _kastet3 and "2026" in _kastet3, str(_kastet3))
sjekk("og at ingenting skrives", _kastet3 and "ingenting" in _kastet3.lower())

# --- 4) Samme etter 1. januar: fortsatt rødt, og byttets alarm har sin grunn
_sb28 = ny_sandkasse(LAG26)
_kode_jan = sesong.bytt(_sb28, date(2027, 1, 5), utfor=True,
                        log=lambda _s: None, ligaer=["eliteserien"])
sjekk("5. januar med ufrosset 2026: bytt() gir exit 1", _kode_jan == 1)
sjekk("og aktiv sesong er fortsatt 2026",
      sesong.aktiv_sesong(_sb28, "eliteserien") == "2026")
try:
    _bas(_hent(_res3, _term3, _sb28, naa=datetime(2027, 1, 5, tzinfo=timezone.utc)),
         "2026", log=lambda _s: None)
    _kastet4 = None
except _FS as e:
    _kastet4 = str(e)
sjekk("og sesonggrensen stopper databyggingen også i januar",
      _kastet4 is not None)

# --- Ordningen som gjor at ingenting KAN skrives: kontrollen ligger for
# write_json i kilden. Testen leser kildekoden, for det er en
# rekkefolge-invariant, ikke en verdi.
_kilde_ud = (ROT / "scripts" / "update_data.py").read_text(encoding="utf-8").splitlines()
_l_filter = next(i for i, l in enumerate(_kilde_ud) if "bare_aktiv_sesong(" in l and "import" not in l)
_l_skifte = next(i for i, l in enumerate(_kilde_ud) if 'DATOVAKT_BESKJED["sesongskifte_mangler"]' in l)
_l_write = next(i for i, l in enumerate(_kilde_ud) if "write_json(data_dir" in l)
sjekk("update_data: sesonggrensen ligger FØR write_json",
      _l_filter < _l_write, f"filter={_l_filter+1} write={_l_write+1}")
sjekk("update_data: sesongskifte_mangler ligger FØR write_json",
      _l_skifte < _l_write, f"skifte={_l_skifte+1} write={_l_write+1}")

_kilde_ob = (ROT / "scripts" / "obos_build_data.py").read_text(encoding="utf-8").splitlines()
_o_filter = next(i for i, l in enumerate(_kilde_ob) if "bare_aktiv_sesong(" in l and "import" not in l)
_o_skifte = next(i for i, l in enumerate(_kilde_ob) if 'DATOVAKT_BESKJED["sesongskifte_mangler"]' in l)
_o_write = next(i for i, l in enumerate(_kilde_ob) if "write_json(DATA" in l)
sjekk("obos_build_data: sesonggrensen ligger FØR write_json",
      _o_filter < _o_write, f"filter={_o_filter+1} write={_o_write+1}")
sjekk("obos_build_data: sesongskifte_mangler ligger FØR write_json",
      _o_skifte < _o_write, f"skifte={_o_skifte+1} write={_o_write+1}")

# ============ OBOS: ingen CSV-fallback som skjuler kildefeilen
print("\n=== OBOS: 0 aktive rader gir ikke CSV-fallback ===")
# Dagens except-blokk rundt fetch_all faller tilbake til CSV-en. Den er
# riktig naar KILDEN ER NEDE, men ikke naar den svarer med en annen sesong:
# da ville kjeden bygget et datasett som ser helt riktig ut, fra fasiten,
# og kildefeilen ville vaert usynlig.
import obos_build_data as _obd

_sb_obos = ny_sandkasse(LAG26)
_lag_obos = sorted(LIGAER["obos"]["lag"])
_par_obos = sorted((h, b) for h in _lag_obos for b in _lag_obos if h != b)

# En GYLDIG 2026-CSV -- reserven er altsaa i orden, og ville blitt brukt.
_csv_rader = ["sesong,runde,dato,tid,hjemme,borte,hjemmemaal,bortemaal"]
for _i, (_h, _b) in enumerate(_par_obos):
    _csv_rader.append(f"2026,{_i // 8 + 1},2026-11-{1 + (_i // 8) % 28:02d},"
                      f"18:00,{_h},{_b},2,1")
_csv_sti = _sb_obos / "obos" / "data" / "obos_2012-2026.csv"
_csv_sti.parent.mkdir(parents=True, exist_ok=True)
_csv_sti.write_text("\n".join(_csv_rader) + "\n", encoding="utf-8")

# Ligasiden viser BARE 2027.
_res_o = [_RAD_MAL.format(kl="played", r=i // 8 + 1, h=h, b=b, dag="05.04",
          res='<td class="schedule__match__item schedule__match__item--result">1 - 0</td>')
          .replace(">2026<", ">2027<").replace('alt="Eliteserien"', 'alt="OBOS-ligaen"')
          for i, (h, b) in enumerate(_par_obos)]
_term_o = [_RAD_MAL.format(kl="upcoming", r=i // 8 + 1, h=h, b=b, dag="20.04", res="")
           .replace(">2026<", ">2027<").replace('alt="Eliteserien"', 'alt="OBOS-ligaen"')
           for i, (h, b) in enumerate(_par_obos)]

_filer_for = {n: (_sb_obos / "obos" / "data" / n).read_bytes()
              for n in ("matches.json", "fixtures.json")}
_ekte = (_obd.ROOT, _obd.DATA, _obd.CSV_PATH, _ntf3.hent, _ntf3.ROT)
_obd.ROOT, _obd.DATA = _sb_obos, _sb_obos / "obos" / "data"
_obd.CSV_PATH = _csv_sti
_ntf3.ROT = _sb_obos
_ntf3.hent = lambda url, **kw: ("<table>" + "".join(_res_o) + "</table>"
                                if url.endswith("resultater")
                                else "<table>" + "".join(_term_o) + "</table>")
try:
    _obd.rows_for(log=lambda _s: None)
    _obos_kastet = None
except _FS as e:
    _obos_kastet = f"FeilSesong: {e}"
except SystemExit as e:
    _obos_kastet = f"SystemExit: {e}"
finally:
    _obd.ROOT, _obd.DATA, _obd.CSV_PATH, _ntf3.hent, _ntf3.ROT = _ekte
sjekk("rows_for() stopper i stedet for å bygge fra CSV-en",
      _obos_kastet is not None and "FeilSesong" in _obos_kastet,
      str(_obos_kastet))
sjekk("og eksisterende filer er bit for bit urørt",
      all((_sb_obos / "obos" / "data" / n).read_bytes() == b
          for n, b in _filer_for.items()))

# ============ obos_results: et 2027-resultat paa en utsatt 2026-kamp
print("\n=== obos_results: utsatt 2026-kamp, 2027-resultat på ligasiden ===")
# Den verste veien inn, og den var uvoktet: ligaside_results() nokler paa
# (hjemme, borte) uansett sesong, decide() lar ligasiden ALENE publisere, og
# rows tar dato og runde fra VAR egen terminliste. Et 2027-resultat ville
# altsaa blitt publisert som resultatet paa 2026-kampen, uten at noe saa
# galt ut -- og behold_eksisterende() holder et publisert resultat for godt.
# Rekkevidden er en UTSATT kamp: decide() hopper over alt som alt er
# publisert, men en kamp uten resultat ville fatt neste sesongs.
import obos_results as _obr

_sb_res = ny_sandkasse(LAG26)
_d_res = _sb_res / "obos" / "data"
_d_res.mkdir(parents=True, exist_ok=True)
_utsatt = _par_obos[-1]

# Terminlisten: hele 2026. Publisert: alt UNNTATT den utsatte kampen.
_csv_res = ["sesong,runde,dato,tid,hjemme,borte,hjemmemaal,bortemaal"]
for _i, (_h, _b) in enumerate(_par_obos):
    _csv_res.append(f"2026,{_i // 8 + 1},2026-11-{1 + (_i // 8) % 28:02d},"
                    f"18:00,{_h},{_b},2,1")
(_d_res / "obos_2012-2026.csv").write_text("\n".join(_csv_res) + "\n",
                                           encoding="utf-8")
_publisert = [{"date": f"2026-11-{1 + (_i // 8) % 28:02d}", "time": "18:00",
               "round": _i // 8 + 1, "home": _h, "away": _b, "hg": 2, "ag": 1}
              for _i, (_h, _b) in enumerate(_par_obos) if (_h, _b) != _utsatt]
(_d_res / "matches.json").write_text(_json.dumps(_publisert, indent=1) + "\n",
                                     encoding="utf-8")
_matches_for = (_d_res / "matches.json").read_bytes()
sjekk("den utsatte kampen er IKKE publisert fra før",
      len(_publisert) == len(_par_obos) - 1)

# Ligasiden viser BARE 2027 -- inkludert et resultat for det utsatte lagparet.
_ekte_res = (_obr.ROOT, _obr.DATA, _obr.CSV_PATH, _obr.MATCHES, _obr.STATE,
             _ntf3.hent, _ntf3.ROT)
_obr.ROOT, _obr.DATA = _sb_res, _d_res
_obr.CSV_PATH = _d_res / "obos_2012-2026.csv"
_obr.MATCHES, _obr.STATE = _d_res / "matches.json", _d_res / "results_state.json"
_ntf3.ROT = _sb_res
_ntf3.hent = lambda url, **kw: ("<table>" + "".join(_res_o) + "</table>"
                                if url.endswith("resultater")
                                else "<table>" + "".join(_term_o) + "</table>")
try:
    _obr.offisielle_resultater()
    _res_kastet = None
except _FS as e:
    _res_kastet = str(e)
finally:
    (_obr.ROOT, _obr.DATA, _obr.CSV_PATH, _obr.MATCHES, _obr.STATE,
     _ntf3.hent, _ntf3.ROT) = _ekte_res
sjekk("offisielle_resultater() kaster FeilSesong i stedet for å levere 2027-resultater",
      _res_kastet is not None, str(_res_kastet))
sjekk("den returnerer altså IKKE {} -- da ville Wikipedia skjult kildefeilen",
      _res_kastet is not None)
sjekk("ingenting er publisert på den utsatte kampen",
      (_d_res / "matches.json").read_bytes() == _matches_for)
sjekk("og results_state.json ble aldri skrevet",
      not (_d_res / "results_state.json").exists())

# Rekkefolgen i kilden: stoppet maa ligge for begge skrivingene.
_kilde_or = (ROT / "scripts" / "obos_results.py").read_text(encoding="utf-8").splitlines()
_r_filter = next(i for i, l in enumerate(_kilde_or) if "bare_aktiv_sesong(" in l and "import" not in l)
_r_state = next(i for i, l in enumerate(_kilde_or) if "STATE.write_text" in l)
_r_match = next(i for i, l in enumerate(_kilde_or) if "MATCHES.write_text" in l)
sjekk("obos_results: sesonggrensen ligger FØR results_state.json",
      _r_filter < _r_state, f"filter={_r_filter+1} state={_r_state+1}")
sjekk("obos_results: og FØR matches.json",
      _r_filter < _r_match, f"filter={_r_filter+1} matches={_r_match+1}")
sjekk("obos_results har nå frysevakten de to andre kjedene har hatt",
      any("er_frosset" in l for l in _kilde_or))

# ============ Oppdagelsen: den som var blind
print("\n=== Oppdagelsen ser 2027 gjennom fetch_all ===")
# Med noekkelen (hjemme, borte) kastet slaa_sammen ALLE 240 2027-radene, og
# oppdag_sesong fant 0. Sesongen ble aldri "klar", og bytt() kunne aldri
# bytte 1. januar -- hele det selvkjorende sesongskiftet sto paa en
# duplikatregel som slo det av.
_sb_opp = ny_sandkasse(LAG26)
_res_opp, _term_opp = _sider27()
_alle_opp = _hent(_res_opp, _term_opp, _sb_opp)
_n2027 = [r for r in _alle_opp if (r.get("date") or "").startswith("2027")]
sjekk("fetch_all gir oppdagelsen alle 240 2027-kampene",
      len(_n2027) == 240, str(len(_n2027)))
_ok_opp, _funn_opp = sesong.valider(_n2027, "2027")
sjekk("og de validerer som en hel sesong", _ok_opp,
      str([t for a, t in _funn_opp if a == "feil"]))
sesong.oppdag(_sb_opp, "eliteserien", "2027", _n2027, log=lambda _s: None)
_blokk_opp = sesong.les(_sb_opp)["ligaer"]["eliteserien"]["sesonger"].get("2027", {})
sjekk("oppdag() registrerer 2027 som «klar»",
      _blokk_opp.get("status") == "klar", str(_blokk_opp.get("status")))
sjekk("og aktiv sesong er fortsatt 2026 til 1. januar",
      sesong.aktiv_sesong(_sb_opp, "eliteserien") == "2026")

# ============ Workflow: sesongmaskineriet kjores selv om databyggingen feiler
print("\n=== Workflow: byttets alarm nås selv om databyggingen feiler ===")
# Uten always() ble Sesongskifte SKIPPED naar databygging-steget feilet, og
# da utloses ikke sluttsteget som gjor kjoringen rod paa byttets alarm -- et
# hoppet steg har outcome "skipped", ikke "failure". Verre: byttet ville
# aldri kjort, altsaa vranglaas 1. januar.
import yaml as _yaml
for _wf, _byggsteg in (("update-data", "Kjør oppdateringsscript"),
                       ("obos-results", "Bygg tabell og modell på nytt")):
    _d = _yaml.safe_load((ROT / ".github" / "workflows" / f"{_wf}.yml")
                         .read_text(encoding="utf-8"))
    _steg = {(s.get("name") or ""): s for s in list(_d["jobs"].values())[0]["steps"]}
    _bygg = [n for n in _steg if n.startswith(_byggsteg)]
    sjekk(f"{_wf}: databygging-steget finnes", bool(_bygg), str(_byggsteg))
    for _navn in ("Se etter neste sesongs terminliste", "Frys sesongen hvis den er ferdig",
                  "Sesongskifte"):
        _treff = [n for n in _steg if n.startswith(_navn)]
        sjekk(f"{_wf}: «{_navn[:28]}» kjører også når databyggingen feiler",
              _treff and "always()" in str(_steg[_treff[0]].get("if", "")),
              str(_treff and _steg[_treff[0]].get("if")))
    _rod = [n for n in _steg if "rød hvis sesongskiftet" in n]
    sjekk(f"{_wf}: sluttsteget gjør kjøringen rød på byttets alarm",
          _rod and "steps.sesongskifte.outcome == 'failure'" in str(_steg[_rod[0]]["if"])
          and "always()" in str(_steg[_rod[0]]["if"]),
          str(_rod and _steg[_rod[0]].get("if")))

# Hver suite vokter seg selv: en lekkasje herfra skal ikke vaere usynlig til
# noen tilfeldigvis kjorer failsafe etterpaa.
_vern.sjekk_urort(sjekk)

print(f"\n{antall[0] - len(feil)} av {antall[0]} tester gikk gjennom.")
if feil:
    print("FEILET: " + ", ".join(feil))
sys.exit(1 if feil else 0)
