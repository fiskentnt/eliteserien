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


def skriv_revisjon(sb, liga, naa, errors=0, bekreftet=None):
    d = sb / LIGAER[liga]["data"] / "audit_fixtures.json"
    d.write_text(json.dumps({
        "checked_date": naa.date().isoformat(),
        "checked_at": naa.isoformat(timespec="seconds"),
        "errors": errors, "warnings": 0,
        "bekreftet": bekreftet or {},
    }), encoding="utf-8")


def frys(sb, liga, sesong_, naa):
    """Kaller frysingens EGEN sperre, og utforer bare hvis den slipper."""
    hindre = frys_sesong.ikke_ferdig(sb, liga, sesong_, naa=naa)
    blokk = sesong.les(sb).get("ligaer", {}).get(liga, {})
    if blokk.get("sesonger", {}).get(str(int(sesong_) + 1), {}).get("status") \
            not in ("oppdaget", "klar", "aktiv"):
        hindre = hindre + ["neste sesong ikke oppdaget"]
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
skriv_revisjon(sb, "eliteserien", SISTE_KAMP + timedelta(hours=2))
hindre = frys_sesong.ikke_ferdig(sb, "eliteserien", "2026",
                                 naa=SISTE_KAMP + timedelta(hours=2))
sjekk("rett etter siste kamp: fryser ikke (karenstid)",
      any("karenstiden" in h for h in hindre), str(hindre))

# 72 timer senere, fersk revisjon uten avvik
naa = SISTE_KAMP + timedelta(hours=73)
skriv_revisjon(sb, "eliteserien", naa)
ok, hindre = frys(sb, "eliteserien", "2026", naa)
sjekk("etter 72 timer med ren revisjon: fryses", ok, str(hindre))
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
naa = SISTE_KAMP + timedelta(hours=80)
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
skriv_revisjon(sb3, "obos", naa - timedelta(hours=30))
hindre = frys_sesong.ikke_ferdig(sb3, "obos", "2026", naa=naa)
sjekk("en 30 timer gammel revisjon er ikke fersk nok",
      any("ikke fersk" in h for h in hindre), str(hindre))

# ===================================================== C. sen terminliste
print("\n=== C. 2027-listen blir først klar 10. januar ===")
sb4 = ny_sandkasse(LAG26)
naa = SISTE_KAMP + timedelta(hours=80)
skriv_revisjon(sb4, "eliteserien", naa)
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

naa = SISTE_KAMP + timedelta(hours=80)
skriv_revisjon(sb6, "obos", naa)
frys(sb6, "obos", "2026", naa)
frosset1 = (sb6 / "obos" / "2026" / "data" / "matches.json").read_bytes()
for _ in range(3):
    sesong.bytt(sb6, date(2027, 1, 1), utfor=True, log=lambda _s: None, ligaer=["obos"])
sjekk("tre bytter etter hverandre: aktiv er 2027, ikke 2029",
      sesong.aktiv_sesong(sb6, "obos") == "2027")
sjekk("og frosne data er uendret",
      (sb6 / "obos" / "2026" / "data" / "matches.json").read_bytes() == frosset1)

print(f"\n{antall[0] - len(feil)} av {antall[0]} tester gikk gjennom.")
if feil:
    print("FEILET: " + ", ".join(feil))
sys.exit(1 if feil else 0)
