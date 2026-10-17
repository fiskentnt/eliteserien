"""Tester for de offisielle kildene, reconcile() og sesongskiftet.
Kjør: python3 test_kilder.py

Testdataene er sidene slik de sto 25. september 2026, lagret i testdata/.
Fasiten er produksjonens filer fra samme dag, lagret ved siden av dem
(testdata/fasit_<liga>_2026-09-25.json), ikke dagens terminliste: testen
skal sjekke at parserne leser kopiene riktig, og ikke feile hver gang en
kamp flyttes senere. Unntaket er de 22 Eliteserie-kampene
der produksjonen og de offisielle kildene er uenige om dato eller avspark.
Der er ESPN brukt som uavhengig dommer, og ESPN ga de offisielle kildene rett
i alle 22. Se verifiser_avvik.py og testdata/verifisert_avvik.json.
"""
import json
import sys
from datetime import date, datetime as _dt, timezone as _tz
from zoneinfo import ZoneInfo
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROT / "scripts"))

# ETT sted hindrer at testene skriver i produksjonsdataene. Se tests/conftest.py.
sys.path.insert(0, str(ROT / "tests"))
import conftest as _vern
_VERN = _vern.vern()
import ntf_source
import nff_source
import sesong
from ligaer import ANTALL_KAMPER, ANTALL_LAG, ANTALL_RUNDER, LIGAER
from reconcile_ny import reconcile, behold_eksisterende

TESTDATA = Path(__file__).parent / "testdata"

AVVIK = {(x["home"], x["away"]): x
         for x in json.loads((TESTDATA / "verifisert_avvik.json").read_text("utf-8"))}

feil, antall = [], [0]


def _frys_kunstig(rot, liga, ses):
    """Setter frosset.json. Byttet krever at gammel sesong er frosset, og
    denne filen prover BYTTEREGLENE -- frysekriteriene har sin egen test i
    test_sesongskifte.py."""
    m = Path(rot) / liga / str(ses) / "data"
    m.mkdir(parents=True, exist_ok=True)
    (m / "frosset.json").write_text("{}", encoding="utf-8")



def sjekk(navn, betingelse, detalj=""):
    antall[0] += 1
    if betingelse:
        print(f"  ✓ {navn}")
    else:
        print(f"  ✗ {navn}  {detalj}")
        feil.append(navn)


def les_ntf(liga, side):
    return (TESTDATA / f"ntf_{liga}_{side}_2026-09-25.html").read_text(encoding="utf-8")


def les_nff(liga):
    return (TESTDATA / f"nff_{liga}_2026-09-25.html").read_text(encoding="utf-8")


def fasit_kamper(liga):
    """Kampene slik produksjonen hadde dem 25.9.2026, da testdataene ble
    lagret (se notatet i filen)."""
    d = json.loads((TESTDATA / f"fasit_{liga}_2026-09-25.json").read_text("utf-8"))
    return {(r["home"], r["away"]): r for r in d["kamper"]}


KILDER = {}
for liga in LIGAER:
    print(f"\n=== {LIGAER[liga]['visningsnavn']}: de to offisielle kildene ===")
    dobbelt = []
    ntf = ntf_source.slå_sammen(
        ntf_source.parse_side(les_ntf(liga, "resultater"), "resultater", liga)
        + ntf_source.parse_side(les_ntf(liga, "terminliste"), "terminliste", liga),
        log=dobbelt.append)
    nff = nff_source.parse_side(les_nff(liga), liga)
    KILDER[liga] = (ntf, nff)

    for navn, rader in (("ligasiden", ntf), ("fotball.no", nff)):
        sjekk(f"{navn}: {ANTALL_KAMPER} kamper", len(rader) == ANTALL_KAMPER, f"fikk {len(rader)}")
        sjekk(f"{navn}: runde 1-{ANTALL_RUNDER} komplett",
              sorted({r['round'] for r in rader}) == list(range(1, ANTALL_RUNDER + 1)))
        sjekk(f"{navn}: {ANTALL_LAG} lag", len({r['home'] for r in rader}) == ANTALL_LAG)
        sjekk(f"{navn}: hvert lagpar én gang",
              len({(r['home'], r['away']) for r in rader}) == ANTALL_KAMPER)
        sjekk(f"{navn}: alle har dato og runde",
              all(r["date"] and r["round"] for r in rader))
    sjekk("«neste kamp» som står dobbelt er identisk begge steder",
          not dobbelt, str(dobbelt[:2]))

    ntf_ix = {(r["home"], r["away"]): r for r in ntf}
    nff_ix = {(r["home"], r["away"]): r for r in nff}
    sjekk("de to kildene har samme kampsett", set(ntf_ix) == set(nff_ix))
    for felt in ("round", "date", "time"):
        u = [k for k in ntf_ix if ntf_ix[k][felt] != nff_ix[k][felt]]
        sjekk(f"de to kildene er enige om {felt}", not u, str(u[:2]))
    u = [k for k in ntf_ix if ntf_ix[k]["hg"] is not None and nff_ix[k]["hg"] is not None
         and (ntf_ix[k]["hg"], ntf_ix[k]["ag"]) != (nff_ix[k]["hg"], nff_ix[k]["ag"])]
    sjekk("de to kildene er enige om resultatene", not u, str(u[:2]))

    print(f"--- {LIGAER[liga]['visningsnavn']}: mot fasiten fra samme dag ---")
    prod = fasit_kamper(liga)
    sjekk("samme kampsett som fasiten", set(ntf_ix) == set(prod),
          str(set(ntf_ix) ^ set(prod)))
    ulik = {f: [] for f in ("round", "date", "time")}
    ulikt_res = []
    for k, p in prod.items():
        e = ntf_ix.get(k)
        if not e:
            continue
        fasit = AVVIK.get(k)
        vent_d = fasit["espn"]["date"] if fasit else p.get("date")
        vent_t = fasit["espn"]["time"] if fasit else p.get("time")
        if e["round"] != p.get("round"):
            ulik["round"].append((k, e["round"], p.get("round")))
        if e["date"] != vent_d:
            ulik["date"].append((k, e["date"], vent_d))
        if e["time"] != vent_t:
            ulik["time"].append((k, e["time"], vent_t))
        if p.get("hg") is not None and (e["hg"], e["ag"]) != (p["hg"], p["ag"]):
            ulikt_res.append((k, (e["hg"], e["ag"]), (p["hg"], p["ag"])))
    for f in ("round", "date", "time"):
        sjekk(f"alle {ANTALL_KAMPER} {f} stemmer mot fasit", not ulik[f], str(ulik[f][:2]))
    sjekk("alle resultater stemmer mot fasiten", not ulikt_res, str(ulikt_res[:2]))

    print(f"--- {LIGAER[liga]['visningsnavn']}: navneavvik ---")
    cfg = LIGAER[liga]
    sjekk(f"kildenavnene {sorted(cfg['navn'])} er oversatt",
          all(k not in {r["home"] for r in ntf} for k in cfg["navn"]))
    sjekk("alle oversatte navn er i bruk",
          all(v in {r["home"] for r in ntf} for v in cfg["navn"].values()))
    sjekk("hvert lag har 15 hjemmekamper",
          all(sum(1 for r in ntf if r["home"] == t) == ANTALL_LAG - 1 for t in cfg["lag"]))

print("\n=== Fellene i markupen (Eliteserien) ===")
ntf_es = KILDER["eliteserien"][0]
neste = [r for r in ntf_es if (r["home"], r["away"]) == ("Brann", "Viking")]
sjekk("«neste kamp»-raden er med", len(neste) == 1)
if neste:
    sjekk("den har runde, dato og avspark",
          (neste[0]["round"], neste[0]["date"], neste[0]["time"]) == (23, "2026-10-09", "19:00"),
          str(neste[0]))
sjekk("terminlisten bruker schedule__team--opponent",
      "schedule__team--opponent" in les_ntf("eliteserien", "terminliste"))
sjekk("resultatsiden bruker results__team--opponent",
      "results__team--opponent" in les_ntf("eliteserien", "resultater"))
try:
    ntf_source._navn("Ukjent BK", LIGAER["eliteserien"])
    sjekk("ukjent lagnavn stopper kjøringen", False, "ingen feil kastet")
except ntf_source.EsDataError:
    sjekk("ukjent lagnavn stopper kjøringen", True)
try:
    nff_source.parse_side("<html>ingen tabell</html>", "eliteserien")
    sjekk("tom fotball.no-side stopper kjøringen", False, "ingen feil kastet")
except nff_source.NffDataError:
    sjekk("tom fotball.no-side stopper kjøringen", True)

print("\n=== Utsatt runde (Eliteserien runde 12) ===")
r12 = [r for r in ntf_es if r["round"] == 12]
sjekk("runde 12 har 8 kamper og er uspilt",
      len(r12) == 8 and all(r["hg"] is None for r in r12), f"{len(r12)} kamper")
sjekk("runde 12 spilles etter runde 22",
      min(r["date"] for r in r12) > max(r["date"] for r in ntf_es if r["round"] == 22))

print("\n=== reconcile(): roller og advarsler ===")
for liga in LIGAER:
    ntf, nff = KILDER[liga]
    logg = []
    ut = reconcile(ntf, nff, log=logg.append)
    sjekk(f"{liga}: {ANTALL_KAMPER} kamper ut", len(ut) == ANTALL_KAMPER, f"fikk {len(ut)}")
    sjekk(f"{liga}: ingen advarsler når de offisielle kildene er enige",
          not logg, str(logg[:2]))

ntf_es, nff_es = KILDER["eliteserien"]
KFUM = ("KFUM Oslo", "Lillestrøm")
ffk = [dict(r) for r in ntf_es]
for r in ffk:
    if (r["home"], r["away"]) == KFUM:
        r["date"], r["time"] = "2026-08-16", "17:00"
logg = []
ut = reconcile(ntf_es, nff_es, reserver=[("ffksupporter", ffk)], log=logg.append)
truffet = next(x for x in ut if (x["home"], x["away"]) == KFUM)
sjekk("hovedkilden vinner over reserven",
      (truffet["date"], truffet["time"]) == ("2026-08-15", "16:00"), str(truffet))
sjekk("uenigheten med reserven er logget",
      any("dato" in m and "KFUM" in m and "ffksupporter" in m for m in logg), str(logg[:2]))

kontroll_uenig = [dict(r) for r in nff_es]
for r in kontroll_uenig:
    if (r["home"], r["away"]) == KFUM:
        r["round"] = 99
logg = []
reconcile(ntf_es, kontroll_uenig, log=logg.append)
sjekk("uenighet med fotball.no om runde er logget",
      any("runde" in m and "fotball.no" in m for m in logg), str(logg[:2]))

espn_uenig = [{**r, "hg": 9, "ag": 9} for r in ntf_es if r["hg"] is not None][:1]
logg = []
reconcile(ntf_es, nff_es, resultatkontroll=[("ESPN", espn_uenig)], log=logg.append)
sjekk("uenig resultat mot ESPN er logget",
      any("resultat" in m and "ESPN" in m for m in logg), str(logg[:2]))

uten_resultat = [{**r, "hg": None, "ag": None} if r["hg"] is not None else r for r in ntf_es]
ut = reconcile(uten_resultat, nff_es, log=lambda s: None)
sjekk("fotball.no fyller inn resultat hovedkilden mangler",
      sum(1 for r in ut if r["src"] == "nff") == 168,
      str(sum(1 for r in ut if r["src"] == "nff")))

mangler_en = [r for r in ntf_es if (r["home"], r["away"]) != KFUM]
logg = []
ut = reconcile(mangler_en, nff_es, log=logg.append)
sjekk("kamp hovedkilden mangler hentes fra fotball.no", len(ut) == ANTALL_KAMPER, f"fikk {len(ut)}")
sjekk("og det er logget", any("ikke hos hovedkilden" in m for m in logg))

print("\n=== Flytting: samme kamp, aldri duplikat ===")
for liga in LIGAER:
    ntf, nff = KILDER[liga]
    FLYTT = (ntf[0]["home"], ntf[0]["away"])
    før = reconcile(ntf, nff, log=lambda s: None)
    før_rad = next(r for r in før if (r["home"], r["away"]) == FLYTT)

    flyttet = [dict(r) for r in ntf]
    nff_flyttet = [dict(r) for r in nff]
    for kilde in (flyttet, nff_flyttet):
        for r in kilde:
            if (r["home"], r["away"]) == FLYTT:
                r["date"], r["time"] = "2026-12-20", "18:30"
    etter = reconcile(flyttet, nff_flyttet, log=lambda s: None)
    rad = next(r for r in etter if (r["home"], r["away"]) == FLYTT)
    sjekk(f"{liga}: fortsatt {ANTALL_KAMPER} kamper", len(etter) == ANTALL_KAMPER)
    sjekk(f"{liga}: kampen finnes bare én gang",
          sum(1 for r in etter if (r["home"], r["away"]) == FLYTT) == 1)
    sjekk(f"{liga}: dato og avspark er oppdatert",
          (rad["date"], rad["time"]) == ("2026-12-20", "18:30"), str(rad))
    sjekk(f"{liga}: rundenummeret følger kampen", rad["round"] == før_rad["round"])
    sjekk(f"{liga}: ingen annen kamp er rørt",
          {(r["home"], r["away"], r["date"]) for r in etter if (r["home"], r["away"]) != FLYTT}
          == {(r["home"], r["away"], r["date"]) for r in før if (r["home"], r["away"]) != FLYTT})

    RUNDE = 26
    flyttet_r = [dict(r) for r in ntf]
    nff_r = [dict(r) for r in nff]
    for kilde in (flyttet_r, nff_r):
        for r in kilde:
            if r["round"] == RUNDE:
                r["date"] = "2026-12-28"
    etter_r = reconcile(flyttet_r, nff_r, log=lambda s: None)
    i_runden = [r for r in etter_r if r["round"] == RUNDE]
    sjekk(f"{liga}: hele runde {RUNDE} flyttet, fortsatt {ANTALL_KAMPER} kamper",
          len(etter_r) == ANTALL_KAMPER)
    sjekk(f"{liga}: runde {RUNDE} har 8 kamper med ny dato",
          len(i_runden) == 8 and all(r["date"] == "2026-12-28" for r in i_runden))
    sjekk(f"{liga}: ingen duplikater etter rundeflytting",
          len({(r["home"], r["away"]) for r in etter_r}) == ANTALL_KAMPER)

print("\n=== Sesongskifte: validering av ny terminliste ===")


def dikt_terminliste(år, lag, endre=None):
    """Full dobbel serie for 16 lag, fordelt på 30 runder."""
    kamper = [(h, b) for h in lag for b in lag if h != b]
    rader = []
    for i, (h, b) in enumerate(kamper):
        rader.append({"round": i % ANTALL_RUNDER + 1,
                      "date": f"{år}-04-{i % 28 + 1:02d}", "time": "18:00",
                      "home": h, "away": b, "hg": None, "ag": None})
    # Fordel rundene slik at hver runde har 8 kamper
    for i, r in enumerate(sorted(rader, key=lambda x: (x["home"], x["away"]))):
        r["round"] = i // 8 + 1
    if endre:
        endre(rader)
    return rader


# Lagene i Eliteserien 2026, faste her: testen er et oppdiktet skifte
# 2026 -> 2027 (Start ut, Bryne inn) og skal ikke avhenge av hvilke lag
# ligaer.py har når den kjøres.
LAG_ES_2026 = ["Bodø/Glimt", "Brann", "Fredrikstad", "HamKam", "KFUM Oslo", "Kristiansund", "Lillestrøm",
               "Molde", "Rosenborg", "Sandefjord", "Sarpsborg 08", "Start", "Tromsø", "Viking",
               "Vålerenga", "Aalesund"]
LAG_2027 = sorted(set(LAG_ES_2026) - {"Start"} | {"Bryne"})
god = dikt_terminliste(2027, LAG_2027)
ok, funn = sesong.valider(god, "2027", sorted(LAG_ES_2026))
sjekk("gyldig terminliste validerer", ok, str(funn))
sjekk("lagendringen rapporteres uten å blokkere",
      any(a == "merk" and "inn ['Bryne']" in t and "ut ['Start']" in t for a, t in funn),
      str(funn))

ok, funn = sesong.valider(god[:-1], "2027", None)
sjekk("for få kamper blokkerer", not ok and any("239 kamper" in t for _, t in funn), str(funn))

ok, _ = sesong.valider(god, "2028", None)
sjekk("feil årstall blokkerer", not ok)

uten_tid = dikt_terminliste(2027, LAG_2027, lambda rs: [r.update(time=None) for r in rs])
ok, funn = sesong.valider(uten_tid, "2027", None)
sjekk("manglende avspark blokkerer IKKE (tv-tider settes senere)", ok, str(funn))
sjekk("men det rapporteres", any(a == "merk" and "avspark" in t for a, t in funn))

dobbel = dikt_terminliste(2027, LAG_2027)
dobbel[1] = dict(dobbel[0])
ok, funn = sesong.valider(dobbel, "2027", None)
sjekk("duplisert lagpar blokkerer", not ok and any("flere ganger" in t for _, t in funn), str(funn))

femten = sorted(set(LAG_2027) - {"Bryne"})
ok, _ = sesong.valider(dikt_terminliste(2027, femten), "2027", None)
sjekk("feil antall lag blokkerer", not ok)

print("\n=== Sesongskifte: når byttes aktiv sesong ===")
import tempfile
rot = Path(tempfile.mkdtemp())
(rot / "data").mkdir()
d = sesong.les(rot)
for liga in LIGAER:
    d["ligaer"][liga] = {"aktiv": "2026", "sesonger": {"2026": {"status": "aktiv",
                         "lag": sorted(LIGAER[liga]["lag"])}}}
sesong.skriv(rot, d)

stille = lambda s: None
sesong.oppdag(rot, "eliteserien", "2027", god, log=stille)
d = sesong.les(rot)
sjekk("validert terminliste gir status «klar»",
      d["ligaer"]["eliteserien"]["sesonger"]["2027"]["status"] == "klar")
sjekk("oppdagelse endrer IKKE aktiv sesong",
      d["ligaer"]["eliteserien"]["aktiv"] == "2026")

for dag, vent in (("2026-11-10", False), ("2026-12-31", False), ("2027-01-01", True)):
    gjør, neste, hvorfor = sesong.skal_bytte(d["ligaer"]["eliteserien"], date.fromisoformat(dag))
    sjekk(f"{dag}: {'bytter' if vent else 'står på 2026'}", gjør == vent, hvorfor)

sjekk("OBOS er upåvirket av at Eliteserien er klar",
      sesong.skal_bytte(d["ligaer"]["obos"], date(2027, 1, 1))[0] is False)
sjekk("og begrunnelsen sier at terminlisten mangler",
      "ukjent" in sesong.skal_bytte(d["ligaer"]["obos"], date(2027, 1, 1))[2])

sesong.oppdag(rot, "eliteserien", "2027", god[:-1], log=stille)
d = sesong.les(rot)
sjekk("ugyldig terminliste gir status «oppdaget», ikke «klar»",
      d["ligaer"]["eliteserien"]["sesonger"]["2027"]["status"] == "oppdaget")
gjør, _, hvorfor = sesong.skal_bytte(d["ligaer"]["eliteserien"], date(2027, 1, 1))
sjekk("1. januar uten validert liste: bytter ikke", not gjør)
sjekk("og det sies tydelig fra", "VENTER" in hvorfor, hvorfor)

sesong.oppdag(rot, "eliteserien", "2027", god, log=stille)
_frys_kunstig(rot, "eliteserien", "2026")
sesong.bytt(rot, date(2027, 1, 1), utfor=True, log=stille)
d = sesong.les(rot)
sjekk("etter byttet er 2027 aktiv for Eliteserien",
      d["ligaer"]["eliteserien"]["aktiv"] == "2027")
sjekk("2026 er merket frosset",
      d["ligaer"]["eliteserien"]["sesonger"]["2026"]["status"] == "frosset")
sjekk("OBOS står fortsatt på 2026", d["ligaer"]["obos"]["aktiv"] == "2026")

obos_2027 = dikt_terminliste(2027, sorted(LIGAER["obos"]["lag"]))
sesong.oppdag(rot, "obos", "2027", obos_2027, log=stille)
_frys_kunstig(rot, "obos", "2026")
sesong.bytt(rot, date(2027, 1, 2), utfor=True, log=stille)
d = sesong.les(rot)
sjekk("OBOS bytter uavhengig, senere", d["ligaer"]["obos"]["aktiv"] == "2027")
sjekk("Eliteserien er uendret av OBOS-byttet",
      d["ligaer"]["eliteserien"]["aktiv"] == "2027")

print("\n=== En kamp underveis skal aldri regnes som ferdig ===")
UNDERVEIS = '''<tr class="schedule__match schedule__match--live">
  <td class="schedule__match__item schedule__match__item--round"><span>#23</span></td>
  <td class="schedule__match__item schedule__match__item--teams">
    Brann - <span class="results__team--opponent">Viking</span></td>
  <td class="schedule__match__item schedule__match__item--result">1 - 0</td>
  <td class="schedule__match__item schedule__match__item--date">09.10.<span
    class="schedule__match__item--date__year">2026</span> 19:00</td>
  <td class="schedule__match__item schedule__match__item--league"><img alt="Eliteserien"/></td>
</tr>'''
logg = []
rader = ntf_source.parse_side(UNDERVEIS, "resultater", "eliteserien", log=logg.append)
sjekk("pågående kamp: stillingen blir IKKE et resultat",
      len(rader) == 1 and rader[0]["hg"] is None, str(rader))
sjekk("pågående kamp: dato og avspark leses likevel",
      (rader[0]["date"], rader[0]["time"]) == ("2026-10-09", "19:00"), str(rader[0]))
sjekk("pågående kamp: rundenummeret leses likevel", rader[0]["round"] == 23)
sjekk("pågående kamp: det logges tydelig",
      any("ikke merket ferdigspilt" in m for m in logg), str(logg))

UKJENT = UNDERVEIS.replace("schedule__match--live", "schedule__match--noe-nytt") \
                  .replace('<td class="schedule__match__item schedule__match__item--result">1 - 0</td>', "")
logg = []
rader = ntf_source.parse_side(UKJENT, "resultater", "eliteserien", log=logg.append)
sjekk("ukjent radstatus: regnes som ikke spilt", rader[0]["hg"] is None)
sjekk("ukjent radstatus: det logges", any("ukjent radstatus" in m for m in logg), str(logg))

FERDIG = UNDERVEIS.replace("schedule__match--live", "schedule__match--played")
# Kampen i testdataene er 9. oktober 19:00. Klokkeregelen krever at det har
# gaatt 110 minutter, saa "naa" maa settes -- ellers ligger avsparket i
# framtiden og raden avvises med rette.
_etterpaa = _dt(2026, 10, 9, 21, 30, tzinfo=ZoneInfo("Europe/Oslo"))
rader = ntf_source.parse_side(FERDIG, "resultater", "eliteserien",
                              naa=_etterpaa, log=lambda s: None)
sjekk("eksplisitt ferdigspilt OG lenge nok etter avspark: resultatet tas inn",
      (rader[0]["hg"], rader[0]["ag"]) == (1, 0), str(rader[0]))
rader = ntf_source.parse_side(FERDIG, "resultater", "eliteserien",
                              naa=_dt(2026, 10, 9, 20, 0, tzinfo=ZoneInfo("Europe/Oslo")),
                              log=lambda s: None)
sjekk("men merket ferdig bare 60 min etter avspark: ikke resultat",
      rader[0]["hg"] is None, str(rader[0]))

print("\n=== Resultatsiden viser avsparket i UTC: regnes om til norsk tid ===")
# 2.10.2026: Ranheim - Egersund hadde avspark 19:00 norsk tid (terminlisten,
# kalenderfeeden, OddsPapi 17:00Z), men resultatsiden viste "17:00" etter
# kampen, og vi lagret 17:00. Raden under er den ekte raden fra
# obos-ligaen.no/resultater 3.10.2026. Lest som norsk tid aapnet
# klokkeregelen (110 min) 10 minutter FOER avspark.
RANHEIM_RAD = """<tr class="schedule__match schedule__match--played match__link" onclick="window.location = &#39;https://www.ranheimfotball.no/resultater/kamp?id=8986797&#39;"> <td class="schedule__match__item schedule__match__item--round"> <span>#24</span> </td> <td class="schedule__match__item schedule__match__item--teams"> <span class="team-form team-form--small team-form--float"></span> Ranheim TF - <span class="results__team--opponent">Egersund</span> <span class="schedule__match__score">(5-0)</span> </td> <td class="schedule__match__item schedule__match__item--result">5-0</td> <td class="schedule__match__item schedule__match__item--date">02.10.<span class="schedule__match__item--date__year">2026</span> 17:00 <span class="schedule__match__item--match-round-number">#24</span> </td> <td class="schedule__match__item schedule__match__item--venue">EXTRA Arena</td> <td class="schedule__match__item schedule__match__item--league schedule__match__item--league--results"> <img src="/_/asset/no.seeds.app.football:0000019ff1790cb0/img/obos.png" alt="OBOS-ligaen"/> </td> </tr>"""
_OSLO = ZoneInfo("Europe/Oslo")
_kjent = {("Ranheim", "Egersund"): ("2026-10-02", "19:00")}
_logg = []
_r = ntf_source.parse_side(RANHEIM_RAD, "resultater", "obos", naa=_dt(2026, 10, 2, 21, 30, tzinfo=_OSLO),
                           log=_logg.append, kjent_avspark=_kjent)
sjekk("kamp kl. 19:00 norsk tid vist som 17:00 på resultatsiden: lagres som 19:00",
      (_r[0]["date"], _r[0]["time"]) == ("2026-10-02", "19:00"), str(_r[0]))
sjekk("og resultatet tas inn 2,5 time etter det riktige avsparket", (_r[0]["hg"], _r[0]["ag"]) == (5, 0), str(_r[0]))
sjekk("omregningen logges", any(l.startswith("MERK: Ranheim - Egersund") and "i UTC" in l for l in _logg), str(_logg))
# Klokkeregelen regner fra det riktige avsparket: merket ferdig 60 minutter
# etter avspark (20:00) er IKKE et resultat. Uten omregningen var det 180
# minutter etter "17:00", og resultatet ble godtatt.
_r = ntf_source.parse_side(RANHEIM_RAD, "resultater", "obos", naa=_dt(2026, 10, 2, 20, 0, tzinfo=_OSLO),
                           log=lambda _s: None, kjent_avspark=_kjent)
sjekk("merket ferdig 60 min etter det riktige avsparket: ikke resultat (klokkeregelen bruker 19:00)",
      _r[0]["hg"] is None and _r[0]["time"] == "19:00", str(_r[0]))
_r = ntf_source.parse_side(RANHEIM_RAD, "resultater", "obos", naa=_dt(2026, 10, 2, 20, 0, tzinfo=_OSLO),
                           log=lambda _s: None)
sjekk("(uten kjent avspark leses 17:00 som norsk tid, og regelen ville godtatt resultatet: derfor omregningen)",
      _r[0]["hg"] == 5 and _r[0]["time"] == "17:00", str(_r[0]))
# Raden viser norsk tid (som de eldre kampene): står som den er.
_logg = []
_r = ntf_source.parse_side(RANHEIM_RAD.replace("2026</span> 17:00", "2026</span> 19:00"), "resultater", "obos",
                           naa=_dt(2026, 10, 2, 21, 30, tzinfo=_OSLO), log=_logg.append, kjent_avspark=_kjent)
sjekk("resultatsiden viser norsk tid (19:00): uendret, ingen omregning",
      _r[0]["time"] == "19:00" and not any(l.startswith("MERK") for l in _logg), f"{_r[0]} {_logg}")
sjekk("og ikke noe avvik", not any("AVVIK" in l for l in _logg), str(_logg))
_logg = []
ntf_source.parse_side(RANHEIM_RAD, "resultater", "obos", naa=_dt(2026, 10, 2, 21, 30, tzinfo=_OSLO),
                      log=_logg.append, kjent_avspark=_kjent)
sjekk("vist i UTC (17:00) er heller ikke et avvik", not any("AVVIK" in l for l in _logg), str(_logg))
# En tid som verken er det kjente avsparket eller det i UTC: ingen gjetning.
# Ligasiden er hovedkilden, så tiden derfra brukes, men det logges som avvik
# (4.10.2026), og i GitHub Actions også som advarsel.
import io as _iou, contextlib as _ctxu, os as _osu
_logg, _ut = [], _iou.StringIO()
_gha_u = _osu.environ.get("GITHUB_ACTIONS")
_osu.environ["GITHUB_ACTIONS"] = "true"
try:
    with _ctxu.redirect_stdout(_ut):
        _r = ntf_source.parse_side(RANHEIM_RAD.replace("2026</span> 17:00", "2026</span> 16:00"), "resultater", "obos",
                                   naa=_dt(2026, 10, 2, 21, 30, tzinfo=_OSLO), log=_logg.append, kjent_avspark=_kjent)
finally:
    if _gha_u is None:
        _osu.environ.pop("GITHUB_ACTIONS", None)
    else:
        _osu.environ["GITHUB_ACTIONS"] = _gha_u
sjekk("en annen tid (16:00): sidens tid brukes", _r[0]["time"] == "16:00", str(_r[0]))
sjekk("og det logges som avvik: «Kamp Ranheim-Egersund: ligasiden viser 16:00, vi hadde 19:00, bruker 16:00»",
      "AVVIK: Kamp Ranheim-Egersund: ligasiden viser 16:00, vi hadde 19:00, bruker 16:00" in _logg, str(_logg))
sjekk("med advarsel i GitHub Actions",
      "::warning title=Ligasiden: annet avspark::Kamp Ranheim-Egersund: ligasiden viser 16:00" in _ut.getvalue(), _ut.getvalue())
sjekk("og ingen MERK om omregning", not any(l.startswith("MERK") for l in _logg), str(_logg))
# Annen dato: datoen er med i linjen.
_logg = []
_r = ntf_source.parse_side(RANHEIM_RAD.replace("02.10.<span", "03.10.<span"), "resultater", "obos",
                           naa=_dt(2026, 10, 3, 21, 30, tzinfo=_OSLO), log=_logg.append, kjent_avspark=_kjent)
sjekk("annen dato: «ligasiden viser 3.10. 17:00, vi hadde 2.10. 19:00, bruker 3.10. 17:00»",
      _r[0]["date"] == "2026-10-03" and
      "AVVIK: Kamp Ranheim-Egersund: ligasiden viser 3.10. 17:00, vi hadde 2.10. 19:00, bruker 3.10. 17:00" in _logg, str(_logg))
# Uten kjent avspark for kampen: ingenting å sammenligne med.
_logg = []
ntf_source.parse_side(RANHEIM_RAD.replace("2026</span> 17:00", "2026</span> 16:00"), "resultater", "obos",
                      naa=_dt(2026, 10, 2, 21, 30, tzinfo=_OSLO), log=_logg.append,
                      kjent_avspark={("Bryne", "Lyn"): ("2026-10-04", "14:30")})
sjekk("ukjent kamp: ikke noe avvik", not any("AVVIK" in l for l in _logg), str(_logg))
# Vintertid: én time. 7.11.2026 kl. 18:00 norsk tid er 17:00 UTC.
_r = ntf_source.parse_side(RANHEIM_RAD.replace("02.10.<span", "07.11.<span"), "resultater", "obos",
                           naa=_dt(2026, 11, 7, 21, 30, tzinfo=_OSLO), log=lambda _s: None,
                           kjent_avspark={("Ranheim", "Egersund"): ("2026-11-07", "18:00")})
sjekk("vintertid: 17:00 på resultatsiden er 18:00 norsk tid",
      (_r[0]["date"], _r[0]["time"]) == ("2026-11-07", "18:00"), str(_r[0]))
# Bryne - Lyn 4.10.2026: resultatsiden viste 12:30, avsparket var 14:30.
_r = ntf_source.parse_side(RANHEIM_RAD.replace("02.10.<span", "04.10.<span").replace("2026</span> 17:00", "2026</span> 12:30"),
                           "resultater", "obos", naa=_dt(2026, 10, 4, 16, 35, tzinfo=_OSLO), log=lambda _s: None,
                           kjent_avspark={("Ranheim", "Egersund"): ("2026-10-04", "14:30")})
sjekk("Bryne - Lyn-tilfellet 4.10.: 12:30 på resultatsiden er 14:30 norsk tid (to timer, sommertid)",
      (_r[0]["date"], _r[0]["time"]) == ("2026-10-04", "14:30"), str(_r[0]))
# Overgangen til vintertid natt til 25.10.2026: dagen før er UTC to timer bak,
# fra 25.10. én time.
for _dag, _vist, _kjent_t in (("24.10.", "12:00", "14:00"), ("25.10.", "16:00", "17:00")):
    _iso = f"2026-10-{_dag[:2]}"
    _r = ntf_source.parse_side(RANHEIM_RAD.replace("02.10.<span", f"{_dag}<span").replace("2026</span> 17:00", f"2026</span> {_vist}"),
                               "resultater", "obos", naa=_dt(2026, 10, int(_dag[:2]), 22, 0, tzinfo=_OSLO), log=lambda _s: None,
                               kjent_avspark={("Ranheim", "Egersund"): (_iso, _kjent_t)})
    sjekk(f"{_dag} ({'sommertid, to timer' if _dag == '24.10.' else 'vintertid, én time'}): {_vist} på resultatsiden er {_kjent_t} norsk tid",
          (_r[0]["date"], _r[0]["time"]) == (_iso, _kjent_t), str(_r[0]))

# Hele veien: fetch_all leser det kjente avsparket fra fixtures.json og
# bruker det bare paa resultatsiden. Sandkasse for repoet og hentingsloggen.
import tempfile as _tfu
import hentelogg as _hlu
_sbu = Path(_tfu.mkdtemp())
(_sbu / "obos" / "data").mkdir(parents=True)
(_sbu / "obos" / "data" / "fixtures.json").write_text(json.dumps([{"round": 24, "matches": [
    {"home": "Ranheim", "away": "Egersund", "date": "2026-10-02", "time": "19:00", "played": False}]}]), encoding="utf-8")
(_sbu / "obos" / "data" / "matches.json").write_text("[]", encoding="utf-8")
_cacheu = _sbu / "cache"
_cacheu.mkdir()
_res = les_ntf("obos", "resultater")
_i = _res.index('<tr class="schedule__match schedule__match--played')
(_cacheu / "obos_resultater.html").write_text(_res[:_i] + RANHEIM_RAD + _res[_i:], encoding="utf-8")
(_cacheu / "obos_terminliste.html").write_text(les_ntf("obos", "terminliste"), encoding="utf-8")
_ekte_rot_u, _ekte_kat_u = ntf_source.ROT, _hlu.KATALOG
ntf_source.ROT, _hlu.KATALOG = _sbu, _sbu / "hentelogg"
try:
    _alle = ntf_source.fetch_all("obos", cache_dir=_cacheu, log=lambda _s: None,
                                 naa=_dt(2026, 10, 2, 21, 30, tzinfo=_OSLO))
finally:
    ntf_source.ROT, _hlu.KATALOG = _ekte_rot_u, _ekte_kat_u
_re = [r for r in _alle if (r["home"], r["away"], r["date"]) == ("Ranheim", "Egersund", "2026-10-02")]
sjekk("fetch_all: Ranheim - Egersund får 19:00 fra fixtures.json, med resultatet",
      len(_re) == 1 and _re[0]["time"] == "19:00" and _re[0]["hg"] == 5, str(_re))
# De andre radene paa resultatsiden: samme dato og tid som uten omregning.
_som_foer = {(r["home"], r["away"], r["date"]): r["time"] for r in ntf_source.parse_side(
    _res, "resultater", "obos", naa=_dt(2026, 10, 2, 21, 30, tzinfo=_OSLO), log=lambda _s: None)}
_eldre = [r for r in _alle if (r["home"], r["away"], r["date"]) in _som_foer]
_flyttet = [r for r in _eldre if r["time"] != _som_foer[(r["home"], r["away"], r["date"])]]
sjekk(f"fetch_all: de {len(_eldre)} andre kampene på resultatsiden står med samme klokkeslett som før",
      len(_eldre) > 100 and not _flyttet, str(_flyttet[:3]))

print("\n=== En uspilt kamp uten dato stopper ikke terminlisten ===")
# 3.10.2026: NTF viste Sandnes Ulf - Haugesund (15:53Z) og Bryne - Raufoss
# (16:01-16:33Z) uten dato mens kampene ble endret. Hele terminlisten ble
# avvist ("manglende dato"), ingen resultater ble publisert i 50 minutter, og
# reserven satte tilbake et avspark. Nå beholder en USPILT kamp uten dato
# datoen og avsparket vi har, og resten av siden brukes. En spilt kamp uten
# dato avvises fortsatt, og det samme gjør et lagpar som er spilt hos oss
# (på terminlisten kan det være neste sesongs kamp).
import re as _re_u
_term = les_ntf("obos", "terminliste")
_cfg_o = ntf_source.oppsett("obos")
_naa_u = _dt(2026, 10, 3, 18, 10, tzinfo=_OSLO)
def _par_u(k, r):
    try:
        x = ntf_source.parse_rad(r, "terminliste", _cfg_o, k, naa=_naa_u, log=lambda _s: None)
    except Exception:
        return None
    return x and (x["home"], x["away"])
_br = next((k, r) for k, r in ntf_source.RAD_RE.findall(_term) if _par_u(k, r) == ("Bryne", "Raufoss"))
_br_uten = _re_u.sub(r'(schedule__match__item--date">).*?(</td>)', r"\1 \2", _br[1], count=1, flags=_re_u.S)
_term_uten = _term.replace(_br[1], _br_uten)
_uspilte = {("Bryne", "Raufoss"): ("2026-10-14", "19:00")}
_foer = ntf_source.parse_side(_term, "terminliste", "obos", naa=_naa_u, log=lambda _s: None)
_logg = []
_etter = ntf_source.parse_side(_term_uten, "terminliste", "obos", naa=_naa_u, log=_logg.append, uspilt_avspark=_uspilte)
_brr = [r for r in _etter if (r["home"], r["away"]) == ("Bryne", "Raufoss")]
sjekk("raden for Bryne - Raufoss har ingen dato i testen (ellers er testen tom)",
      _br_uten != _br[1] and not ntf_source.DATO_RE.search(_br_uten), _br_uten[:300])
sjekk("uspilt kamp uten dato: hele terminlisten leses, og kampen beholder datoen og avsparket vi har (14.10. 19:00)",
      len(_etter) == len(_foer) and len(_brr) == 1 and (_brr[0]["date"], _brr[0]["time"]) == ("2026-10-14", "19:00")
      and _brr[0]["hg"] is None, f"{len(_etter)} {len(_foer)} {_brr}")
sjekk("de andre kampene står som før", [r for r in _etter if (r["home"], r["away"]) != ("Bryne", "Raufoss")]
      == [r for r in _foer if (r["home"], r["away"]) != ("Bryne", "Raufoss")])
sjekk("det logges", any("manglende dato for Bryne - Raufoss" in l and "beholder" in l for l in _logg), str(_logg))
try:
    ntf_source.parse_side(_term_uten, "terminliste", "obos", naa=_naa_u, log=lambda _s: None, uspilt_avspark={})
    _kast = None
except ntf_source.EsDataError as e:
    _kast = str(e)
sjekk("uten et avspark vi har for kampen (ukjent, eller spilt hos oss): avvist som før",
      _kast is not None and "manglende dato for Bryne - Raufoss" in _kast, str(_kast))
_spilt_klasser = _br[0].replace("schedule__match--upcoming", "schedule__match--played") + " schedule__match--played"
_spilt_rad = _re_u.sub(r'(schedule__match__item--result">).*?(</td>)', r"\g<1>2-1\2", _br_uten, count=1, flags=_re_u.S)
try:
    ntf_source.parse_rad(_spilt_rad, "terminliste", _cfg_o, _spilt_klasser, naa=_naa_u, log=lambda _s: None, uspilt_avspark=_uspilte)
    _kast = None
except ntf_source.EsDataError as e:
    _kast = str(e)
sjekk("en SPILT kamp uten dato (merket ferdigspilt hos NTF) avvises, også når vi har den som uspilt",
      _kast is not None and "manglende dato" in _kast, str(_kast))
# kjente_uspilte: bare kamper som er uspilte hos oss.
_sbk = Path(_tfu.mkdtemp())
(_sbk / "obos" / "data").mkdir(parents=True)
(_sbk / "obos" / "data" / "fixtures.json").write_text(json.dumps([{"round": 26, "matches": [
    {"home": "Bryne", "away": "Raufoss", "date": "2026-10-14", "time": "19:00", "played": False},
    {"home": "Moss", "away": "Odd", "date": "2026-10-14", "time": "19:00", "played": True, "hg": 1, "ag": 0},
    {"home": "Lyn", "away": "Hødd", "date": "2026-10-14", "time": "19:00", "played": False}]}]), encoding="utf-8")
(_sbk / "obos" / "data" / "matches.json").write_text(json.dumps([{"home": "Lyn", "away": "Hødd", "hg": 2, "ag": 2,
    "date": "2026-04-01", "time": "18:00", "round": 3}]), encoding="utf-8")
_ku = ntf_source.kjente_uspilte("obos", rot=_sbk)
sjekk("kjente_uspilte: bare kampene som er uspilte hos oss (ikke played, ikke resultat i matches.json)",
      _ku == {("Bryne", "Raufoss"): ("2026-10-14", "19:00")}, str(_ku))
# Hele veien: fetch_all med terminlisten der Bryne - Raufoss mangler dato.
(_sbk / "obos" / "data" / "matches.json").write_text("[]", encoding="utf-8")
_cachek = _sbk / "cache"
_cachek.mkdir()
(_cachek / "obos_resultater.html").write_text(les_ntf("obos", "resultater"), encoding="utf-8")
(_cachek / "obos_terminliste.html").write_text(_term_uten, encoding="utf-8")
ntf_source.ROT, _hlu.KATALOG = _sbk, _sbk / "hentelogg"
try:
    _alle_k = ntf_source.fetch_all("obos", cache_dir=_cachek, log=lambda _s: None, naa=_naa_u)
    _kast = None
except Exception as e:
    _alle_k, _kast = [], repr(e)
finally:
    ntf_source.ROT, _hlu.KATALOG = _ekte_rot_u, _ekte_kat_u
_brk = [r for r in _alle_k if (r["home"], r["away"]) == ("Bryne", "Raufoss")]
sjekk("fetch_all: terminlisten med Bryne - Raufoss uten dato leses, med datoen fra fixtures.json",
      _kast is None and len(_alle_k) > 200 and len(_brk) == 1 and (_brk[0]["date"], _brk[0]["time"]) == ("2026-10-14", "19:00"),
      f"{_kast} {len(_alle_k)} {_brk}")

from datetime import datetime
from zoneinfo import ZoneInfo
OSLO = ZoneInfo("Europe/Oslo")
h_nff = les_nff("eliteserien")
logg = []
midt = nff_source.parse_side(h_nff, "eliteserien",
                             naa=datetime(2026, 9, 20, 20, 0, tzinfo=OSLO), log=logg.append)
ix = {(r["home"], r["away"]): r for r in midt}
sjekk("fotball.no: kamp som startet for 45 min siden er ikke ferdig",
      ix[("Brann", "Bodø/Glimt")]["hg"] is None, str(ix[("Brann", "Bodø/Glimt")]))
sjekk("fotball.no: det logges", any("under 150 min siden avspark" in m for m in logg), str(logg[:1]))
sent = nff_source.parse_side(h_nff, "eliteserien",
                             naa=datetime(2026, 9, 20, 23, 0, tzinfo=OSLO), log=lambda s: None)
ix2 = {(r["home"], r["away"]): r for r in sent}
sjekk("fotball.no: samme kamp er ferdig etter tre timer",
      (ix2[("Brann", "Bodø/Glimt")]["hg"], ix2[("Brann", "Bodø/Glimt")]["ag"]) == (2, 1))

print("\n=== En spilt kamp beholder dato, avspark og runde (frys_spilte, 8.10.2026) ===")
# eliteserien.no viste 7.10. Start-Tromsø (spilt 3.5.) som 05.01.2026,
# Tromsø-Vålerenga (11.7.) som 18.11.2026 og Brann-Rosenborg (2.8.) som
# 19.02.2026. Bare datovinduet stoppet dem, og 18.11. ville sluppet gjennom
# når vinduet vokste etter runde 23.
from reconcile_ny import frys_spilte as _frys, rimelige_datoer as _rd_f
_spilt = lambda h, a, d, t, rn, hg, ag: {"date": d, "time": t, "round": rn, "home": h, "away": a, "hg": hg, "ag": ag, "src": "ntf"}
_vaare = [_spilt("Start", "Tromsø", "2026-05-03", "17:00", 7, 1, 1), _spilt("Tromsø", "Vålerenga", "2026-07-11", "18:00", 13, 4, 0),
          _spilt("Brann", "Rosenborg", "2026-08-02", "19:15", 16, 3, 2)]
_fra_siden = [{**_vaare[0], "date": "2026-01-05"}, {**_vaare[1], "date": "2026-11-18"}, {**_vaare[2], "date": "2026-02-19"},
              {"date": "2026-11-01", "time": "17:00", "round": 25, "home": "Start", "away": "Lillestrøm", "hg": None, "ag": None, "src": None}]
_lf = []
_ut_f = _frys(_fra_siden, _vaare + [{"date": "2026-10-31", "time": "17:00", "round": 25, "home": "Start", "away": "Lillestrøm", "hg": None, "ag": None}], log=_lf.append)
sjekk("de tre spilte kampene beholder 3.5., 11.7. og 2.8.",
      [r["date"] for r in _ut_f[:3]] == ["2026-05-03", "2026-07-11", "2026-08-02"], str(_ut_f[:3]))
sjekk("og loggen sier det: «Tromsø-Vålerenga er spilt 11.7. 18:00; ligasiden viser nå 18.11. 18:00 -- beholder 11.7. 18:00»",
      "AVVIK: Tromsø-Vålerenga er spilt 11.7. 18:00; ligasiden viser nå 18.11. 18:00 -- beholder 11.7. 18:00" in _lf and len(_lf) == 3, str(_lf))
sjekk("en uspilt kamp flyttes som før (frys_spilte rører den ikke)", _ut_f[3]["date"] == "2026-11-01", str(_ut_f[3]))
_lr = []
_rn = _frys([{**_vaare[0], "round": 8}], _vaare, log=_lr.append)
sjekk("annen runde for en spilt kamp: beholdes, og loggen sier begge rundene",
      _rn[0]["round"] == 7 and "(runde 8 der, 7 hos oss)" in _lr[0], str(_lr))
_gha_f = _osu.environ.get("GITHUB_ACTIONS"); _osu.environ["GITHUB_ACTIONS"] = "true"
_bf = _iou.StringIO()
try:
    with _ctxu.redirect_stdout(_bf):
        _frys(_fra_siden[:1], _vaare, log=lambda s: None)
finally:
    if _gha_f is None: _osu.environ.pop("GITHUB_ACTIONS", None)
    else: _osu.environ["GITHUB_ACTIONS"] = _gha_f
sjekk("med advarsel i GitHub Actions", "::warning title=Spilt kamp: annen dato hos kilden::Start-Tromsø er spilt 3.5. 17:00" in _bf.getvalue(), _bf.getvalue())
# Neste sesong: de samme lagene møtes igjen. En 2027-rad er en annen kamp og
# skal IKKE få 2026-datoen (da ville sesonggrensen ikke sett at kilden viser
# 2027).
_n27 = _frys([{**_vaare[0], "date": "2027-04-11", "hg": None, "ag": None}], _vaare, log=lambda s: None)
sjekk("neste sesong (2027-rad for Start-Tromsø): røres ikke", _n27[0]["date"] == "2027-04-11", str(_n27))
# Vinduet etter runde 23 (Brann-Viking spilt 9.10.): 18.11. ligger da inne i
# det. Datovakten alene slipper den gjennom; med frys_spilte (via
# behold_eksisterende, som update_data.py bruker) står 11.7.
_tidl = [_spilt(f"H{i}", f"B{i}", f"2026-03-{15 + (i % 2):02d}", "18:00", 1, 1, 0) for i in range(8)] \
      + [_spilt(f"H{i}", f"B{i}", "2026-10-09", "19:00", 23, 1, 0) for i in range(8, 16)] \
      + [_spilt(f"H{i}", f"B{i}", "2026-06-01", "18:00", 10, 1, 0) for i in range(16, 30)] + _vaare
_bare_vakt, _, _ = _rd_f([{**_vaare[1], "date": "2026-11-18"}], _tidl, 2026, log=lambda s: None)
_med_frys = behold_eksisterende([{**_vaare[1], "date": "2026-11-18"}], _tidl, log=lambda s: None)
_med_frys, _, _ = _rd_f(_med_frys, _tidl, 2026, log=lambda s: None)
_tv = next(r for r in _med_frys if r["home"] == "Tromsø")
sjekk("vinduet etter runde 23: datovakten alene slipper 18.11. gjennom, med frys_spilte står 11.7.",
      _bare_vakt[0]["date"] == "2026-11-18" and _tv["date"] == "2026-07-11", f"{_bare_vakt[0]['date']} {_tv['date']}")
# Resultatsiden (parse_rad): en rad for en kamp vi har resultatet for, med en
# annen dato, beholder vår; en kamp som er spilt hos NTF, men ikke publisert
# hos oss, får sidens dato som før.
_lp = []
_rp = ntf_source.parse_side(RANHEIM_RAD.replace("02.10.<span", "05.01.<span"), "resultater", "obos",
                            naa=_dt(2026, 10, 3, 21, 30, tzinfo=_OSLO), log=_lp.append, kjent_avspark=_kjent,
                            har_resultat=lambda h, b: True)
sjekk("resultatsiden, spilt hos oss: vår dato og vårt avspark beholdes, «er spilt ... beholder»",
      (_rp[0]["date"], _rp[0]["time"]) == ("2026-10-02", "19:00")
      and "AVVIK: Kamp Ranheim-Egersund er spilt: ligasiden viser 5.1. 17:00, vi har 2.10. 19:00, beholder 2.10. 19:00" in _lp, f"{_rp[0]} {_lp}")
_lp = []
_rp = ntf_source.parse_side(RANHEIM_RAD.replace("02.10.<span", "03.10.<span"), "resultater", "obos",
                            naa=_dt(2026, 10, 3, 21, 30, tzinfo=_OSLO), log=_lp.append, kjent_avspark=_kjent,
                            har_resultat=lambda h, b: False)
_lp27 = []
_rp27 = ntf_source.parse_side(RANHEIM_RAD.replace("02.10.<span class=\"schedule__match__item--date__year\">2026", "02.10.<span class=\"schedule__match__item--date__year\">2027"),
                              "resultater", "obos", naa=_dt(2027, 10, 3, 21, 30, tzinfo=_OSLO), log=_lp27.append,
                              kjent_avspark=_kjent, har_resultat=lambda h, b: True)
sjekk("resultatsiden, rad fra 2027 for et lagpar vi har 2026-resultat for: sidens 2027-dato (sesonggrensen tar den)",
      _rp27[0]["date"] == "2027-10-02" and not any("er spilt" in l for l in _lp27), f"{_rp27[0]} {_lp27}")
sjekk("spilt hos NTF, men ikke publisert hos oss: sidens dato brukes som før («bruker»)",
      _rp[0]["date"] == "2026-10-03" and any(", bruker 3.10. 17:00" in l for l in _lp), f"{_rp[0]} {_lp}")
_ob = (ROT / "scripts" / "obos_build_data.py").read_text("utf-8")
sjekk("OBOS (obos_build_data.py): frys_spilte etter sammenslåingen og før datovakten",
      "offisiell = frys_spilte(offisiell, forrige or fra_csv, log=log)" in _ob
      and _ob.index("frys_spilte(offisiell") < _ob.index("rimelige_datoer(offisiell"))

print("\n=== Et publisert resultat skal aldri forsvinne ===")
ntf_es2, nff_es2 = KILDER["eliteserien"]
alle2 = reconcile(ntf_es2, nff_es2, log=lambda s: None)
ferdige = [r for r in alle2 if r["hg"] is not None]
GLEMT = (ferdige[0]["home"], ferdige[0]["away"])
glemt = [{**r, "hg": None, "ag": None, "src": None}
         if (r["home"], r["away"]) == GLEMT else r for r in alle2]
logg = []
beholdt = behold_eksisterende(glemt, ferdige, log=logg.append)
mål = next(r for r in beholdt if (r["home"], r["away"]) == GLEMT)
sjekk("resultatet beholdes når kildene slutter å melde kampen ferdig",
      (mål["hg"], mål["ag"]) == (ferdige[0]["hg"], ferdige[0]["ag"]), str(mål))
sjekk("og det logges tydelig", any("beholder resultatet" in m for m in logg), str(logg[:1]))

# En spilt kamp beholder også dato og avspark (8.10.2026, frys_spilte):
# før ble de oppdatert fra kilden.
_logg_fb = []
flyttet_beholdt = behold_eksisterende(
    [{**r, "date": "2026-12-01", "time": "20:00"} for r in glemt], ferdige, log=_logg_fb.append)
mål2 = next(r for r in flyttet_beholdt if (r["home"], r["away"]) == GLEMT)
sjekk("og dato og avspark beholdes for en spilt kamp, med AVVIK",
      (mål2["date"], mål2["time"]) == (ferdige[0]["date"], ferdige[0]["time"])
      and any(l.startswith(f"AVVIK: {GLEMT[0]}-{GLEMT[1]} er spilt") for l in _logg_fb), f"{mål2} {_logg_fb[:2]}")

print("\n=== Ukjent status skal ALDRI gjøre en ferdig kamp uspilt ===")
# Dette er den farlige retningen. At en uspilt kamp forblir uspilt når vi ikke
# kjenner statusen er trygt. At en FERDIG kamp blir uspilt igjen er det ikke:
# da går tabellen bakover, og en kamp som er spilt forsvinner fra poengsummen.
FERDIG_HOS_OSS = [{"date": "2026-09-20", "time": "19:15", "round": 22,
                   "home": "Brann", "away": "Bodø/Glimt", "hg": 2, "ag": 1, "src": "ntf"}]
UKJENT_KLASSE = '''<tr class="schedule__match schedule__match--helt-ny-klasse">
  <td class="schedule__match__item schedule__match__item--round"><span>#22</span></td>
  <td class="schedule__match__item schedule__match__item--teams">
    Brann - <span class="results__team--opponent">Bodø/Glimt</span></td>
  <td class="schedule__match__item schedule__match__item--result">2 - 1</td>
  <td class="schedule__match__item schedule__match__item--date">20.09.<span
    class="schedule__match__item--date__year">2026</span> 19:15</td>
</tr>'''
logg = []
fra_kilde = ntf_source.parse_side(UKJENT_KLASSE, "resultater", "eliteserien", log=logg.append)
sjekk("kilden alene gir ingen resultat ved ukjent klasse", fra_kilde[0]["hg"] is None)
sjekk("og markerer statusen som ukjent", fra_kilde[0]["ukjent_status"] is True)

etter = behold_eksisterende(reconcile(fra_kilde, [], log=lambda s: None),
                            FERDIG_HOS_OSS, log=logg.append)
rad = etter[0]
sjekk("FERDIG KAMP + UKJENT KLASSE: resultatet beholdes",
      (rad["hg"], rad["ag"]) == (2, 1), str(rad))
sjekk("FERDIG KAMP + UKJENT KLASSE: ferdigstatus beholdes",
      rad["src"] is not None, str(rad))
sjekk("FERDIG KAMP + UKJENT KLASSE: kampen er fortsatt med", len(etter) == 1)
sjekk("og begge stegene er logget",
      any("ikke merket ferdigspilt" in m for m in logg)
      and any("beholder resultatet" in m for m in logg), str(logg))

# build_matches skal fortsatt regne den som spilt
sys.path.insert(0, str(ROT / "scripts"))
import leaguedata
sjekk("kampen havner fortsatt blant de spilte i matches.json",
      len(leaguedata.build_matches(etter)) == 1, str(leaguedata.build_matches(etter)))

# En kamp som forsvinner HELT fra kildene er en verre nedgradering
BORTE = behold_eksisterende([], FERDIG_HOS_OSS, log=lambda s: None)
sjekk("ferdig kamp som forsvinner fra alle kilder beholdes",
      len(BORTE) == 1 and (BORTE[0]["hg"], BORTE[0]["ag"]) == (2, 1), str(BORTE))
logg = []
behold_eksisterende([], FERDIG_HOS_OSS, log=logg.append)
sjekk("og det logges tydelig",
      any("finnes ikke hos noen kilde" in m for m in logg), str(logg))

USPILT_HOS_OSS = [{"date": "2026-10-09", "time": "19:00", "round": 23,
                   "home": "Start", "away": "Odd", "hg": None, "ag": None, "src": None}]
sjekk("men en USPILT kamp som forsvinner gjenoppstår ikke",
      behold_eksisterende([], USPILT_HOS_OSS, log=lambda s: None) == [])

print("\n=== Manglende resultat tre timer etter avspark skal feile ===")
sys.path.insert(0, str(ROT / "scripts"))
import update_data
from datetime import timezone, timedelta
naa = datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc)
fx_sent = [{"round": 23, "matches": [
    {"home": "Brann", "away": "Viking", "date": "2026-10-09", "time": "19:00", "played": False}]}]
try:
    update_data.sjekk_manglende_resultat(fx_sent, naa, lambda s: None)
    sjekk("kamp uten resultat 3 t etter avspark feiler kjøringen", False, "ingen feil")
except update_data.DataAuditError as e:
    sjekk("kamp uten resultat 3 t etter avspark feiler kjøringen", True)
    sjekk("og feilmeldingen navngir kampen", "Brann-Viking" in str(e), str(e)[:100])
fx_tidlig = [{"round": 23, "matches": [
    {"home": "Brann", "away": "Viking", "date": "2026-10-09", "time": "19:00", "played": False}]}]
update_data.sjekk_manglende_resultat(
    fx_tidlig, datetime(2026, 10, 9, 19, 30, tzinfo=timezone.utc), lambda s: None)
sjekk("men ikke mens kampen fortsatt spilles", True)
update_data.sjekk_manglende_resultat(
    [{"round": 23, "matches": [{"home": "A", "away": "B", "date": "2026-10-09",
                                "time": None, "played": False}]}], naa, lambda s: None)
sjekk("kamp uten avspark utløser ikke fristen", True)

print("\n=== Kampvinduet styrer arkiveringen ===")
import json as _json
import tempfile as _tempfile
import arkiver_kildehtml as ark
from datetime import datetime as _dt

_OSLO = ZoneInfo("Europe/Oslo")
_sb = Path(_tempfile.mkdtemp())
(_sb / "obos/data").mkdir(parents=True)
_ekte_rot = ark.ROT
ark.ROT = _sb


def _sett(fixtures, matches):
    (_sb / "obos/data/fixtures.json").write_text(_json.dumps(fixtures), encoding="utf-8")
    (_sb / "obos/data/matches.json").write_text(_json.dumps(matches), encoding="utf-8")


def _paa(kl, dato="2026-10-02"):
    return ark.kampdag("obos", _dt.fromisoformat(f"{dato}T{kl}:00").replace(tzinfo=_OSLO))


# Den viktigste: kampen er FERDIGSPILT og ligger bare i matches.json.
# Vinduet skal fortsatt være åpent -- det er markupen etter kampslutt vi
# trenger for å se hvordan et endelig resultat ser ut.
FERDIG = [{"date": "2026-10-02", "time": "19:00", "round": 24,
           "home": "Ranheim", "away": "Egersund", "hg": 2, "ag": 1}]
_sett([], FERDIG)
sjekk("avspark 19:00, ferdigspilt, kl 21:30: ARKIVERER", _paa("21:30")[0], str(_paa("21:30")))
sjekk("kl 12:00 samme dag: utenfor vinduet", not _paa("12:00")[0], str(_paa("12:00")))
sjekk("kl 18:29 (31 min før): utenfor", not _paa("18:29")[0])
sjekk("kl 18:31 (29 min før): innenfor", _paa("18:31")[0])
sjekk("kl 22:59 (3t59 etter): innenfor", _paa("22:59")[0])
sjekk("kl 23:01 (4t01 etter): utenfor", not _paa("23:01")[0])
sjekk("begrunnelsen navngir vinduet", "18:30-23:00" in _paa("21:30")[1], _paa("21:30")[1])

# Samme kamp, men uspilt i fixtures.json -- vinduet skal være identisk
_sett([{"round": 24, "matches": [dict(FERDIG[0], hg=None, ag=None, played=False)]}], [])
sjekk("uspilt kamp i fixtures.json gir samme vindu",
      _paa("21:30")[0] and "18:30-23:00" in _paa("21:30")[1], str(_paa("21:30")))

# Stort spenn: vinduet spenner fra første til siste
_sett([{"round": 24, "matches": [
    {"date": "2026-10-03", "time": "14:30", "home": "Strømmen", "away": "Sandnes Ulf"},
    {"date": "2026-10-03", "time": "19:00", "home": "Moss", "away": "Kongsvinger"}]}], [])
sjekk("stort spenn: vinduet er 14:00-23:00",
      "14:00-23:00" in _paa("17:00", "2026-10-03")[1], _paa("17:00", "2026-10-03")[1])
sjekk("stort spenn: midt imellom arkiveres", _paa("17:00", "2026-10-03")[0])
sjekk("stort spenn: 13:59 er utenfor", not _paa("13:59", "2026-10-03")[0])

_sett([], [])
sjekk("ingen kamp i dag: hopper over", not _paa("19:00")[0])
sjekk("og sier hvorfor", "ingen kamp i dag" in _paa("19:00")[1], _paa("19:00")[1])

with _vern.miljo(ARKIV_TVING_KAMPDAG="1"):
    sjekk("testbryteren overstyrer vinduet", _paa("03:00")[0])
ark.ROT = _ekte_rot

print("\n=== Arkivet lagres komprimert ===")
import gzip as _gzip
_pr = Path(TESTDATA / "ntf_eliteserien_resultater_2026-09-25.html").read_bytes()
_kom = _gzip.compress(_pr, 9)
sjekk(f"HTML-en komprimerer minst 5x (målt {len(_pr)/len(_kom):.1f}x)",
      len(_pr) / len(_kom) >= 5)
sjekk("og lar seg pakke ut igjen uendret", _gzip.decompress(_kom) == _pr)

print("\n=== Porten: siste_forsok skrives BARE for daglig vedlikehold ===")
import should_fetch as sf
from datetime import timezone as _tz, timedelta as _td

_sb2 = Path(_tempfile.mkdtemp())
(_sb2 / "data").mkdir(parents=True)
sf.LIGAER["test"] = _sb2
_naa = _dt(2026, 10, 2, 18, 0, tzinfo=_tz.utc)


def _fixtures(kamper):
    (_sb2 / "data").mkdir(exist_ok=True)
    (_sb2 / "data" / "fixtures.json").write_text(_json.dumps(kamper), encoding="utf-8")


def _tilstand():
    f = _sb2 / "data" / "daglig_state.json"
    return _json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _nullstill():
    f = _sb2 / "data" / "daglig_state.json"
    if f.exists():
        f.unlink()


# 1) En VENTENDE KAMP aapner porten -- det er ikke daglig vedlikehold,
#    og da skal forsokssperren ikke belastes.
_nullstill()
_fixtures([{"round": 24, "matches": [
    {"home": "Ranheim", "away": "Egersund", "date": "2026-10-02",
     "time": "16:00", "played": False}]}])   # avspark 16:00 norsk = 14:00 UTC
ok1, hvorfor1 = sf.should_fetch(now=_naa, liga="test")
sjekk("ventende kamp åpner porten", ok1, hvorfor1)
sjekk("og siste_forsok er IKKE skrevet", "siste_forsok" not in _tilstand(), str(_tilstand()))

# 2) Ingen ventende kamp: da er daglig_forfalt grunnen, og forsoket skal telles.
_nullstill()
_fixtures([])
ok2, hvorfor2 = sf.should_fetch(now=_naa, liga="test")
sjekk("uten ventende kamp åpner det daglige vedlikeholdet porten", ok2, hvorfor2)
sjekk("og siste_forsok ER skrevet", "siste_forsok" in _tilstand(), str(_tilstand()))

# 3) Ny planlagt kjoring 30 minutter senere, fortsatt ingen kamp: sperret.
ok3, hvorfor3 = sf.should_fetch(now=_naa + _td(minutes=30), liga="test")
sjekk("ny kjøring innen timen stoppes av forsøkssperren", not ok3, hvorfor3)
sjekk("og begrunnelsen sier hvorfor", "venter minst 1 time" in hvorfor3, hvorfor3)

# 4) MEN en ventende kamp skal fortsatt slippe gjennom i samme time.
#    Sperren gjelder bare det daglige vedlikeholdet.
_fixtures([{"round": 24, "matches": [
    {"home": "Ranheim", "away": "Egersund", "date": "2026-10-02",
     "time": "16:00", "played": False}]}])
ok4, hvorfor4 = sf.should_fetch(now=_naa + _td(minutes=30), liga="test")
sjekk("men en ventende kamp åpner porten likevel", ok4, hvorfor4)
sjekk("og det er kampen som er grunnen, ikke vedlikeholdet",
      "venter på resultat" in hvorfor4, hvorfor4)

# 5) Etter en time er det daglige forsoket tillatt igjen.
_fixtures([])
ok5, hvorfor5 = sf.should_fetch(now=_naa + _td(minutes=70), liga="test")
sjekk("etter en time slipper det daglige vedlikeholdet gjennom igjen", ok5, hvorfor5)

# 6) Og naar arbeidet er FULLFORT, hviler klokka i 20 timer.
sf.merk_ok("test", _naa + _td(minutes=70))
ok6, hvorfor6 = sf.should_fetch(now=_naa + _td(hours=5), liga="test")
sjekk("etter fullført vedlikehold er porten lukket i 20 timer", not ok6, hvorfor6)
ok7, hvorfor7 = sf.should_fetch(now=_naa + _td(hours=22), liga="test")  # 20 t etter merk_ok på +70 min
sjekk("og åpen igjen etter 20 timer", ok7, hvorfor7)

print("\n=== Porten: nytt forsøk hver time når status.json er rød, uten tellende kall (12.10.2026) ===")
# 9.10.2026 sto en feil i fire timer; i en landskampspause kunne den stått i
# 20. Med rød status åpner porten når det er minst 55 minutter siden siste
# sjekk -- regnet fra tidspunktet, ikke fra minuttet i timen.
_T = _naa + _td(hours=6, minutes=37)             # vedlikeholdet er gjort, ingen kamp venter; minutt 37


def _status(ok, minutter_siden=None, felt="last_checked", feil=None):
    d = {"ok": ok}
    if minutter_siden is not None:
        d[felt] = (_T - _td(minutes=minutter_siden)).isoformat(timespec="seconds")
    if feil:
        d["error"] = feil
    (_sb2 / "data" / "status.json").write_text(_json.dumps(d), encoding="utf-8")


def _uten_rodt_merke():
    d = _tilstand()
    d.pop("siste_rodt_forsok", None)
    (_sb2 / "data" / "daglig_state.json").write_text(_json.dumps(d), encoding="utf-8")


_fixtures([{"round": 24, "matches": [{"home": "Ranheim", "away": "Egersund", "date": "2026-10-20",
                                      "time": "18:00", "played": False}]}])
_status(True, 300)
sjekk("grønn status: porten er lukket som før, og ingen sperre",
      sf.vurder(now=_T, liga="test") == (False, sf.vurder(now=_T, liga="test")[1], False)
      and "rød" not in sf.vurder(now=_T, liga="test")[1], str(sf.vurder(now=_T, liga="test")))
_status(False, 30, feil="1 kritisk(e) avvik")
_r = sf.vurder(now=_T, liga="test")
sjekk("rød status, 30 minutter siden siste sjekk: lukket, og begrunnelsen sier det",
      _r[0] is False and _r[2] is False and "status.json er rød" in _r[1] and "30 min" in _r[1], str(_r))
sjekk("og ingenting er skrevet i daglig_state.json", "siste_rodt_forsok" not in _tilstand(), str(_tilstand()))
_status(False, 54, feil="1 kritisk(e) avvik")
sjekk("54 minutter: fortsatt lukket", sf.vurder(now=_T, liga="test")[0] is False)
_status(False, 55, feil="1 kritisk(e) avvik")
_r = sf.vurder(now=_T, liga="test")
sjekk("55 minutter (minutt 37 i timen): porten åpner, med uten_tellende",
      _r[0] is True and _r[2] is True and "nytt forsøk uten tellende kall" in _r[1], str(_r))
sjekk("og forsøket er merket i daglig_state.json", _tilstand().get("siste_rodt_forsok") == _T.isoformat(timespec="seconds"),
      str(_tilstand()))
sjekk("should_fetch() gir fortsatt (kjør, begrunnelse)", len(sf.should_fetch(now=_T + _td(hours=2), liga="test")) == 2)
_uten_rodt_merke()
sf.merk_rodt_forsok("test", _T)
# Forsøket feilet før status.json ble skrevet på nytt: last_checked er like gammel.
_r = sf.vurder(now=_T + _td(minutes=10), liga="test")
sjekk("ti minutter etter et forsøk som ikke skrev status på nytt: lukket (forsøket teller)",
      _r[0] is False and "10 min" in _r[1], str(_r))
_r = sf.vurder(now=_T + _td(minutes=56), liga="test")
sjekk("56 minutter etter forsøket: åpner igjen, fortsatt uten tellende kall", _r[0] is True and _r[2] is True, str(_r))
_uten_rodt_merke()
_status(False, 30, felt="built_at")
sjekk("OBOS (built_at i status.json): 30 minutter er lukket", sf.vurder(now=_T, liga="test")[0] is False)
_status(False, 70, felt="built_at")
_r = sf.vurder(now=_T, liga="test")
sjekk("OBOS (built_at): 70 minutter åpner uten tellende kall", _r[0] is True and _r[2] is True, str(_r))
_uten_rodt_merke()
# En vanlig grunn går foran: da er det en vanlig kjøring, med tellende kall som før.
_fixtures([{"round": 24, "matches": [{"home": "Ranheim", "away": "Egersund", "date": _T.astimezone(sf.OSLO).strftime("%Y-%m-%d"),
                                      "time": (_T.astimezone(sf.OSLO) - _td(minutes=110)).strftime("%H:%M"), "played": False}]}])
_status(False, 300, feil="1 kritisk(e) avvik")
_r = sf.vurder(now=_T, liga="test")
sjekk("rød status OG en kamp som venter på resultat: vanlig kjøring, ikke uten_tellende",
      _r[0] is True and _r[2] is False and "venter på resultat" in _r[1], str(_r))
sjekk("og da merkes ikke noe rødt forsøk", "siste_rodt_forsok" not in _tilstand(), str(_tilstand()))
_fixtures([{"round": 24, "matches": [{"home": "Ranheim", "away": "Egersund", "date": "2026-10-20",
                                      "time": "18:00", "played": False}]}])
with _vern.miljo(FORCE_FETCH="true"):
    _r = sf.vurder(now=_T, liga="test")
sjekk("manuell kjøring (FORCE_FETCH): vanlig kjøring, ikke uten_tellende", _r[0] is True and _r[2] is False, str(_r))
# Tabellkontrollen venter på en ny sjekk etter en fersk kamp (12.10.2026):
# porten åpner i HVER kjøring så lenge audit_tabell.json har noe i "venter",
# uten tellende kall, og til en time etter fristen.
def _tabell_venter(liste):
    (_sb2 / "data" / "audit_tabell.json").write_text(_json.dumps({"errors": 0, "venter": liste}), encoding="utf-8")


def _bv(frist_om_min):
    return [{"kamp": "Brann|Viking", "resultat": [0, 2], "grunn": "ført som 0-0 i tabellen",
             "frist": (_T + _td(minutes=frist_om_min)).isoformat(timespec="seconds")}]


_status(True, 5)
sjekk("motprøve: grønn status fem minutter gammel og ingen audit_tabell.json: porten er lukket", sf.vurder(now=_T, liga="test")[0] is False)
_tabell_venter(_bv(120))
_r = sf.vurder(now=_T, liga="test")
sjekk("tabellkontrollen venter: porten åpner fem minutter etter forrige sjekk, uten tellende kall, og begrunnelsen nevner kampen",
      _r == (True, "tabellkontrollen venter på ny sjekk etter Brann-Viking: uten tellende kall", True), str(_r))
sjekk("og det merkes ikke som et rødt forsøk", "siste_rodt_forsok" not in _tilstand(), str(_tilstand()))
_tabell_venter([])
sjekk("ingenting venter lenger (tabellen stemte, eller fristen gikk ut): lukket", sf.vurder(now=_T, liga="test")[0] is False)
_tabell_venter(_bv(-59))
sjekk("59 minutter etter fristen: åpner fortsatt, for sjekken som avgjør saken", sf.vurder(now=_T, liga="test")[::2] == (True, True))
_tabell_venter(_bv(-61))
sjekk("61 minutter etter fristen (kjøringene har feilet): lukket, timesforsøket ved rød status tar over",
      sf.vurder(now=_T, liga="test")[0] is False)
_tabell_venter(_bv(120))
_status(False, 30, feil="1 kritisk(e) avvik")
_r = sf.vurder(now=_T, liga="test")
sjekk("rød status 30 minutter gammel (timesforsøket er ikke klart) og en kamp som venter: åpner for tabellsjekken, uten tellende kall",
      _r[0] is True and _r[2] is True and "tabellkontrollen venter" in _r[1] and "siste_rodt_forsok" not in _tilstand(), str(_r))
_status(True, 5)
_fixtures([{"round": 24, "matches": [{"home": "Ranheim", "away": "Egersund", "date": _T.astimezone(sf.OSLO).strftime("%Y-%m-%d"),
                                      "time": (_T.astimezone(sf.OSLO) - _td(minutes=110)).strftime("%H:%M"), "played": False}]}])
_r = sf.vurder(now=_T, liga="test")
sjekk("en kamp venter på resultat OG tabellkontrollen venter: vanlig kjøring med tellende kall som før",
      _r[0] is True and _r[2] is False and "venter på resultat" in _r[1], str(_r))
_fixtures([{"round": 24, "matches": [{"home": "Ranheim", "away": "Egersund", "date": "2026-10-20",
                                      "time": "18:00", "played": False}]}])
(_sb2 / "data" / "audit_tabell.json").unlink()

# Utskriften: begge utfallene til GITHUB_OUTPUT, og UTEN_TELLENDE til resten av jobben.
import io as _io_p, contextlib as _cl_p
_gho, _ghe = _sb2 / "gh_output", _sb2 / "gh_env"
for _f in (_gho, _ghe):
    _f.write_text("", encoding="utf-8")
with _cl_p.redirect_stdout(_io_p.StringIO()), _cl_p.redirect_stderr(_io_p.StringIO()):
    sf.meld("test", True, "x", True, miljo={"GITHUB_OUTPUT": str(_gho), "GITHUB_ENV": str(_ghe)})
sjekk("rødt forsøk: should_fetch=true og uten_tellende=true til GITHUB_OUTPUT, UTEN_TELLENDE=true til GITHUB_ENV",
      _gho.read_text() == "should_fetch=true\nuten_tellende=true\n" and _ghe.read_text() == "UTEN_TELLENDE=true\n",
      f"{_gho.read_text()!r} {_ghe.read_text()!r}")
for _f in (_gho, _ghe):
    _f.write_text("", encoding="utf-8")
with _cl_p.redirect_stdout(_io_p.StringIO()), _cl_p.redirect_stderr(_io_p.StringIO()):
    sf.meld("test", True, "x", False, miljo={"GITHUB_OUTPUT": str(_gho), "GITHUB_ENV": str(_ghe)})
sjekk("vanlig kjøring: uten_tellende=false, og ingenting i GITHUB_ENV",
      _gho.read_text() == "should_fetch=true\nuten_tellende=false\n" and _ghe.read_text() == "", f"{_gho.read_text()!r} {_ghe.read_text()!r}")
(_sb2 / "data" / "status.json").unlink()
del sf.LIGAER["test"]

print("\n=== OBOS: publiseringsregelen ===")
import obos_results as _R
from reconcile_ny import reconcile as _rec

_sched = {("Ranheim", "Egersund"): {"date": "2026-10-02", "time": "19:00"}}
_naa2 = _dt.now(_tz.utc)
_NTF = '''<tr class="schedule__match schedule__match--played">
 <td class="schedule__match__item schedule__match__item--round"><span>#24</span></td>
 <td class="schedule__match__item schedule__match__item--teams">
   Ranheim TF - <span class="results__team--opponent">Egersund</span></td>
 <td class="schedule__match__item schedule__match__item--result">2 - 1</td>
 <td class="schedule__match__item schedule__match__item--date">02.10.<span
   class="schedule__match__item--date__year">2026</span> 19:00</td>
 <td class="schedule__match__item schedule__match__item--league"><img alt="OBOS-ligaen"/></td></tr>'''
_NFF = '''<table class="tablesorter customSorterAtomicMatches"><tr><th>R</th></tr>
<tr><td>24</td><td>02.10.2026</td><td>fredag</td><td>19:00</td><td>Ranheim TF</td>
<td>2 - 1</td><td>Egersund</td><td>Bane</td><td>1</td></tr></table>'''


def _off(ntf_html, nff_naa):
    n1 = ntf_source.parse_side(ntf_html, "resultater", "obos", log=lambda _s: None)
    n2 = nff_source.parse_side(_NFF, "obos", naa=nff_naa, log=lambda _s: None)
    return {(r["home"], r["away"]): (r["hg"], r["ag"])
            for r in _rec(n1, n2, log=lambda _s: None) if r["hg"] is not None}


_sent = _dt(2026, 10, 2, 23, 0, tzinfo=ZoneInfo("Europe/Oslo"))
_off_ferdig = _off(_NTF, _sent)
sjekk("ferdig kamp: begge offisielle kilder gir resultatet",
      _off_ferdig == {("Ranheim", "Egersund"): (2, 1)}, str(_off_ferdig))
_p, _c, _v, _u = _R.decide(_off_ferdig, None, None, _sched, {}, _naa2, hl={("Ranheim", "Egersund"): (2, 1)})
sjekk("og den publiseres i SAMME kjøring når Highlightly er enig, uten å vente på Wikipedia",
      _p.get(("Ranheim", "Egersund")) == (2, 1) and not _v, f"{_p} {_v}")
_p, _c, _v, _u = _R.decide(_off_ferdig, None, None, _sched, {}, _dt(2026, 10, 2, 22, 0, tzinfo=ZoneInfo("Europe/Oslo")))
sjekk("uten uavhengig kilde venter den, tre timer etter avspark (regelen fra 3.10.2026)",
      not _p and len(_v) == 1, f"{_p} {_v}")
_p, _c, _v, _u = _R.decide(_off_ferdig, None, {("Ranheim", "Egersund"): (3, 1)}, _sched, {}, _naa2)
sjekk("uenighet med Wikipedia holder resultatet tilbake",
      not _p and len(_c) == 1, f"{_p} {_c}")

# Pågående kamp: 40 minutter etter avspark, stilling på tavla hos begge.
_underveis = _NTF.replace("schedule__match--played", "schedule__match--live")
_off_live = _off(_underveis, _dt(2026, 10, 2, 19, 40, tzinfo=ZoneInfo("Europe/Oslo")))
sjekk("pågående kamp: INGEN av de offisielle kildene gir resultat", not _off_live, str(_off_live))
_p, _c, _v, _u = _R.decide(_off_live, None, None, _sched, {}, _naa2)
sjekk("og den kan derfor ikke publiseres som sluttresultat", not _p, str(_p))

print("\n=== Revisjonens dato-sperre maa ikke laase 20-timersklokka ===")
# Funnet i en ekte Actions-kjoring 25. sep 2026: revisjonen hadde alt kjort
# den dagen, saa den ble hoppet over og gjorde_daglig ble False. Da ble
# siste_ok aldri satt, og porten ville proevd hver time resten av dagen.
import update_data as _ud
import tempfile as _tf2

_sti = Path(_tf2.mkdtemp()) / "audit_state.json"
_ekte = _ud.AUDIT_STATE_PATH
_ud.AUDIT_STATE_PATH = _sti
_naa3 = _dt.now(_tz.utc)
_i_dag = _naa3.astimezone(_ud.OSLO).strftime("%Y-%m-%d")

_sti.write_text(_json.dumps({"checked_date": _i_dag, "errors": 0}), encoding="utf-8")
sjekk("revisjon gjort i dag UTEN avvik: regnes som utført, hoppes over",
      _ud.run_daily_audit([], [], _naa3, lambda _s: None) is True)

# Men en revisjon som fant avvik skal kjores PAA NYTT, ikke regnes som gjort:
# avviket kan vaere rettet hos kontrollkilden i mellomtiden.
_sti.write_text(_json.dumps({"checked_date": _i_dag, "errors": 3}), encoding="utf-8")
_ud.run_daily_audit([], [], _naa3, lambda _s: None)
sjekk("revisjon gjort i dag MED avvik: kjøres på nytt og skriver ny tilstand",
      _json.loads(_sti.read_text(encoding="utf-8")).get("errors") == 0,
      str(_json.loads(_sti.read_text(encoding="utf-8"))))

_sti.write_text(_json.dumps({"checked_date": "2020-01-01"}), encoding="utf-8")
sjekk("revisjon ikke gjort i dag: kjører og regnes som utført",
      _ud.run_daily_audit([], [], _naa3, lambda _s: None) is True)
sjekk("og datoen er oppdatert",
      _json.loads(_sti.read_text(encoding="utf-8"))["checked_date"] == _i_dag)
_ud.AUDIT_STATE_PATH = _ekte

print("\n=== Et kritisk revisjonsavvik skal stå til det er løst ===")
# Revisjonen kjorer en gang per kalenderdag. Uten dette ville NESTE kjoring
# samme dag hoppet over revisjonen, skrevet ok=True og gjort stempelet
# gronnt mens avviket fortsatt sto. Med utloser hvert tiende minutt ville
# det skjedd innen en time.
_st_dir = Path(_tf2.mkdtemp())
_ud.AUDIT_STATE_PATH = _st_dir / "audit_state.json"
_ud.STATUS_PATH = _st_dir / "status.json"
# Tabellkontrollens tilstand ogsaa i den tomme katalogen (0 avvik). Ellers
# leser write_status() den ekte eliteserien/data/audit_tabell.json, og et ekte
# avvik der (2 fra 9.10.2026 19:00Z) ga 4 i stedet for 2 og roede tester.
import tabellkontroll as _tko_iso
_ekte_tk_avvik = _tko_iso.avvik
_tko_iso.avvik = lambda liga, data_dir=None: _ekte_tk_avvik(liga, data_dir=data_dir or _st_dir)
sjekk("isolert: tabellkontrollen gir 0 avvik i den tomme katalogen", _tko_iso.avvik("eliteserien") == 0)
# Terminlisterevisjonen likedan (10.10.2026: 1 ekte avvik i
# eliteserien/data/audit_fixtures.json ga 3 i stedet for 2).
import daglig_revisjon as _dr_iso
_ekte_dr_katalog = _dr_iso.data_katalog
_dr_iso.data_katalog = lambda liga, sesong=None: _st_dir
sjekk("isolert: terminlisterevisjonen gir 0 avvik i den tomme katalogen",
      _dr_iso.dagens_avvik("eliteserien", _dt.now(_tz.utc)) == 0)
_naa4 = _dt.now(_tz.utc)
_dag = _naa4.astimezone(_ud.OSLO).strftime("%Y-%m-%d")


def _status():
    return _json.loads(_ud.STATUS_PATH.read_text(encoding="utf-8"))


# 1) Revisjonen finner et kritisk avvik -> roedt
_ud.AUDIT_STATE_PATH.write_text(
    _json.dumps({"checked_date": _dag, "errors": 2, "warnings": 0}), encoding="utf-8")
_ud.write_status(ok=False, now=_naa4, error="2 avvik mellom matches.json og kontrollkilden")
sjekk("kritisk revisjonsavvik: stempelet er rødt", _status()["ok"] is False)

# 2) Ny, ellers vellykket kjoring samme dag -> FORTSATT roedt
_ud.write_status(ok=True, now=_naa4)
sjekk("ny vanlig kjøring samme dag: fortsatt rødt", _status()["ok"] is False, str(_status()))
sjekk("og begrunnelsen sier at avviket står uløst",
      "står" in _status().get("error", "") and _status().get("revisjon_avvik") == 2,
      str(_status()))

# 3) DEN EKTE FLYTEN: avviket rettes hos kontrollkilden, neste tillatte
#    kjoring kjorer revisjonen PAA NYTT, den er ren, og stempelet blir gronnt.
_kamp = {"date": "2026-09-20", "time": "19:15", "round": 22,
         "home": "Brann", "away": "Bodø/Glimt", "hg": 2, "ag": 1}
_vaart = [_kamp]
_kontroll_feil = [{**_kamp, "hg": 3}]     # kontrollkilden er uenig
_kontroll_rett = [dict(_kamp)]            # og blir rettet

_ud.AUDIT_STATE_PATH.write_text(
    _json.dumps({"checked_date": "2020-01-01"}), encoding="utf-8")
_gammel_naa = _dt(2026, 9, 21, 12, 0, tzinfo=_tz.utc)   # godt etter avspark
try:
    _ud.run_daily_audit(_vaart, _kontroll_feil, _gammel_naa, lambda _s: None)
    _reiste = False
except _ud.DataAuditError:
    _reiste = True
sjekk("revisjonen finner avviket og feiler kjøringen", _reiste)
_tilstand = _json.loads(_ud.AUDIT_STATE_PATH.read_text(encoding="utf-8"))
sjekk("og avviket er lagret i audit_state", _tilstand.get("errors") == 1, str(_tilstand))
_ud.write_status(ok=True, now=_gammel_naa)
sjekk("stempelet er rødt selv om kjøringen ellers gikk bra", _status()["ok"] is False)

# Kontrollkilden rettes. Neste tillatte kjoring kjorer revisjonen paa nytt.
_ren = _ud.run_daily_audit(_vaart, _kontroll_rett, _gammel_naa, lambda _s: None)
sjekk("neste kjøring kjører revisjonen på nytt og den er ren", _ren is True)
sjekk("audit_state er oppdatert til null avvik",
      _json.loads(_ud.AUDIT_STATE_PATH.read_text(encoding="utf-8")).get("errors") == 0)
_ud.write_status(ok=True, now=_gammel_naa)
sjekk("og DA blir stempelet grønt igjen", _status()["ok"] is True, str(_status()))
sjekk("avviksfeltet er borte", "revisjon_avvik" not in _status(), str(_status()))

# REGELEN FRA 17.10.2026 (resultatregel.revider_kilde): ffksupporter.net
# manglet KFUM Oslo-Vålerenga 2-1 (12.10.). Før ble det rødt etter 72 timer, og
# statusen sto rød fra 16.10. 07.45, så ingen ekte feil i runde 24 ville gitt
# nytt varsel. Nå: rødt bare når en kilde har et annet resultat, eller ingen
# uavhengig kilde bekrefter etter fristen; mangler, men bekreftet: advarsel.
import resultatregel as _rr17
_k17 = {"date": "2026-10-12", "time": "18:00", "round": 23, "home": "KFUM Oslo", "away": "Vålerenga", "hg": 2, "ag": 1}
_n17 = ("KFUM Oslo", "Vålerenga")
_naa17 = _dt(2026, 10, 17, 12, 0, tzinfo=_tz.utc)    # 116 timer etter avspark (18.00 norsk tid)
_ffk17 = [{**_k17, "hg": None, "ag": None}]
_e17, _w17 = _ud.audit_against_ffk([_k17], _ffk17, _naa17, bekreftere={"football-data": {_n17: (2, 1)}})
sjekk("17.10.: ffksupporter mangler resultatet, football-data bekrefter det: advarsel, ikke feil",
      _e17 == [] and len(_w17) == 1 and "ffksupporter.net mangler resultatet 116 timer etter avspark; bekreftet av football-data" in _w17[0],
      f"{_e17} {_w17}")
_e17, _w17 = _ud.audit_against_ffk([_k17], _ffk17, _naa17, bekreftere={})
sjekk("ingen uavhengig kilde bekrefter, over 72 timer etter avspark: feil",
      len(_e17) == 1 and "ingen uavhengig kilde bekrefter det" in _e17[0], f"{_e17} {_w17}")
_e17, _w17 = _ud.audit_against_ffk([_k17], _ffk17, _dt(2026, 10, 13, 12, 0, tzinfo=_tz.utc), bekreftere={})
sjekk("uten bekreftelse, innenfor 72 timer: advarsel", _e17 == [] and len(_w17) == 1 and "ennå (20t siden avspark)" in _w17[0],
      f"{_e17} {_w17}")
_e17, _w17 = _ud.audit_against_ffk([_k17], _ffk17, _naa17,
                                   bekreftere={"ligasiden": {_n17: (2, 1)}, "fotball.no": {_n17: (2, 1)}})
sjekk("NTF (ligasiden, fotball.no) teller ikke som uavhengig bekreftelse: feil", len(_e17) == 1, f"{_e17} {_w17}")
_e17, _w17 = _ud.audit_against_ffk([_k17], _ffk17, _naa17, bekreftere={"espn": {_n17: (0, 0)}})
sjekk("en kilde med et ANNET resultat bekrefter ikke (ESPNs feil 0-0): feil", len(_e17) == 1, f"{_e17} {_w17}")
_e17, _w17 = _ud.audit_against_ffk([_k17], [], _naa17, bekreftere={"espn": {_n17: (2, 1)}})
sjekk("ffksupporter mangler hele kampen, ESPN bekrefter: advarsel",
      _e17 == [] and len(_w17) == 1 and "mangler kampen" in _w17[0] and "bekreftet av espn" in _w17[0], f"{_e17} {_w17}")
_e17, _w17 = _ud.audit_against_ffk([_k17], [{**_k17, "hg": 1}], _naa17, bekreftere={"espn": {_n17: (2, 1)}})
sjekk("et ANNET resultat hos ffksupporter er feil, også når andre har vårt",
      _e17 == ["KFUM Oslo-Vålerenga (2026-10-12): vi har 2-1, ffksupporter.net har 1-1"], f"{_e17} {_w17}")
_kalt17 = []
_ud.audit_against_ffk([_k17], [dict(_k17)], _naa17, bekreftere=lambda: _kalt17.append(1) or {})
sjekk("bekreftelsene (ESPN-kallet) hentes bare når ffksupporter mangler noe", _kalt17 == [], str(_kalt17))
# Hele flyten: kontrollen er grønn, advarslene lagres og står i status.json.
_ud.AUDIT_STATE_PATH.write_text(_json.dumps({"checked_date": "2020-01-01"}), encoding="utf-8")
_ok17 = _ud.run_daily_audit([_k17], _ffk17, _naa17, lambda _s: None, bekreftere={"football-data": {_n17: (2, 1)}})
_t17 = _json.loads(_ud.AUDIT_STATE_PATH.read_text(encoding="utf-8"))
sjekk("run_daily_audit med et bekreftet resultat ffksupporter mangler: utført uten feil, advarselen lagret",
      _ok17 is True and _t17["errors"] == 0 and any("bekreftet av football-data" in a for a in _t17.get("advarsler", [])), str(_t17))
_ud.write_status(ok=True, now=_naa17)
sjekk("og status.json er grønn, med advarselen", _status()["ok"] is True and "error" not in _status()
      and any("KFUM Oslo-Vålerenga" in a for a in _status().get("advarsler", [])), str(_status()))
sjekk("en vanlig kjøring en annen dag: advarslene fra i går er borte",
      (_ud.write_status(ok=True, now=_naa17 + _td(days=1)), "advarsler" not in _status())[1], str(_status()))

# Kilden har stoppet (resultatregel.kilde_stoppet): advarsel, aldri rødt.
_a17 = {"date": "2026-10-11", "home": "Lillestrøm", "away": "Molde", "hg": 2, "ag": 2,
        "avspark": _dt(2026, 10, 11, 17, 15, tzinfo=_tz.utc)}
_b17 = {**_k17, "avspark": _dt(2026, 10, 12, 16, 0, tzinfo=_tz.utc)}
_r17 = {("Lillestrøm", "Molde"): (2, 2), _n17: None}
_s17, _adv17 = _rr17.kilde_stoppet("ffksupporter.net", [_a17, _b17], _r17, None, _naa17)
sjekk("første gang: «endret» er avsparket for siste kamp kilden har, og den mangler en kamp spilt etter det for over 3 døgn siden: stoppet",
      _s17 == {"resultater": 1, "endret": "2026-10-11T17:15:00+00:00"} and _adv17
      and "ffksupporter.net har ikke registrert noe nytt på 6 døgn (siden 11.10.)" in _adv17 and "stoppet" in _adv17, f"{_s17} {_adv17}")
_, _adv17 = _rr17.kilde_stoppet("ffksupporter.net", [_a17, _b17], _r17, _s17, _dt(2026, 10, 14, 12, 0, tzinfo=_tz.utc))
sjekk("under 3 døgn etter den manglende kampen: ingen advarsel", _adv17 is None, str(_adv17))
_s17b, _adv17 = _rr17.kilde_stoppet("ffksupporter.net", [_a17, _b17], {**_r17, _n17: (2, 1)}, _s17, _naa17)
sjekk("kilden registrerer resultatet: «endret» blir nå, ingen advarsel",
      _s17b == {"resultater": 2, "endret": "2026-10-17T12:00:00+00:00"} and _adv17 is None, f"{_s17b} {_adv17}")
_, _adv17 = _rr17.kilde_stoppet("ffksupporter.net", [_a17, _b17], {**_r17, _n17: (2, 1)}, _s17b, _naa17 + _td(days=10))
sjekk("ingenting nytt på ti døgn, men kilden har alt (landskamppause): ingen advarsel", _adv17 is None, str(_adv17))
_gml17 = {**_a17, "date": "2026-05-10", "avspark": _dt(2026, 5, 10, 15, 0, tzinfo=_tz.utc)}
_, _adv17 = _rr17.kilde_stoppet("Wikipedia", [_gml17, _a17], {("Lillestrøm", "Molde"): (2, 2)}, None, _naa17)
sjekk("et gammelt hull (Wikipedia mangler OBOS-kamper fra 10.5.) er ikke et tegn på at kilden har stoppet", _adv17 is None, str(_adv17))

# 4) Gaarsdagens avvik skal ikke faerge dagens stempel
_ud.AUDIT_STATE_PATH.write_text(
    _json.dumps({"checked_date": "2020-01-01", "errors": 5}), encoding="utf-8")
_ud.write_status(ok=True, now=_naa4)
sjekk("gårsdagens avvik holder ikke stempelet rødt", _status()["ok"] is True)

# 5) En ekte feil i kjoringen gjor det fortsatt roedt, uavhengig av revisjonen
_ud.write_status(ok=False, now=_naa4, error="noe annet gikk galt")
sjekk("en vanlig feil gjør det fortsatt rødt", _status()["ok"] is False)
_ud.AUDIT_STATE_PATH = _ekte
_tko_iso.avvik = _ekte_tk_avvik
_dr_iso.data_katalog = _ekte_dr_katalog

print("\n=== Klokkeregelen paa ligasiden (110 min), ogsaa uten radklasse ===")
# Da fotball.no falt ut av hver kjoring, mistet vernet mot paagaaende kamper
# ett av to ben. Klokken er det som erstatter det -- og den koster ingen
# ekstra henting.
_MAL = '''<tr class="{klasse}">
 <td class="schedule__match__item schedule__match__item--round"><span>#24</span></td>
 <td class="schedule__match__item schedule__match__item--teams">
   Ranheim TF - <span class="results__team--opponent">Egersund</span></td>
 <td class="schedule__match__item schedule__match__item--result">2 - 1</td>
 <td class="schedule__match__item schedule__match__item--date">02.10.<span
   class="schedule__match__item--date__year">2026</span> 19:00</td></tr>'''
_OSLO2 = ZoneInfo("Europe/Oslo")
_AV = _dt(2026, 10, 2, 19, 0, tzinfo=_OSLO2)
from datetime import timedelta as _td2


def _les(klasse, minutter, logg=None):
    return ntf_source.parse_side(_MAL.format(klasse=klasse), "resultater", "obos",
                                 naa=_AV + _td2(minutes=minutter),
                                 log=(logg.append if logg is not None else (lambda _s: None)))[0]


sjekk("rad MERKET FERDIG 60 min etter avspark gir IKKE resultat",
      _les("schedule__match schedule__match--played", 60)["hg"] is None)
sjekk("109 min: fortsatt ikke", _les("schedule__match schedule__match--played", 109)["hg"] is None)
sjekk("110 min: resultatet tas inn",
      _les("schedule__match schedule__match--played", 110)["hg"] == 2)
_l = []
_les("schedule__match schedule__match--played", 60, _l)
sjekk("og for tidlig logges tydelig",
      any("bare 60 min siden avspark" in m for m in _l), str(_l))

sjekk("UKJENT klasse 180 min etter: fortsatt ikke resultat",
      _les("schedule__match schedule__match--noe-helt-nytt", 180)["hg"] is None)
sjekk("uten klasse i det hele tatt: ikke resultat",
      _les("schedule__match", 180)["hg"] is None)

print("\n=== fotball.no: ett forsok per liga per dogn ===")
import nff_source as _nff
_nff_dir = Path(_tf2.mkdtemp())
_ekte_kat = _nff.CACHE_KATALOG
_nff.CACHE_KATALOG = _nff_dir
_hentet = []
_ekte_hent = _nff.hent
_nff.hent = lambda url: (_hentet.append(url), les_nff("eliteserien"))[1]
_n0 = _dt(2026, 10, 2, 8, 0, tzinfo=_tz.utc)

_r1 = _nff.fetch_all("eliteserien", naa=_n0, log=lambda _s: None)
sjekk("workflow 1 henter og fyller cachen", len(_hentet) == 1 and len(_r1) == 240)
_c1 = _json.loads((_nff_dir / "eliteserien.json").read_text("utf-8"))
sjekk("hentingen (som reserve) lagrer bare kampene, ikke tabellen fra fotball.no",
      len(_c1.get("rader") or []) == 240 and "tabell" not in _c1 and "justeringer" not in _c1, str(list(_c1)))
_r2 = _nff.fetch_all("eliteserien", naa=_n0 + _td2(minutes=10), log=lambda _s: None)
sjekk("workflow 2 samme dag henter IKKE, men får samme data",
      len(_hentet) == 1 and _r2 == _r1, f"{len(_hentet)} hentinger")
_r3 = _nff.fetch_all("eliteserien", naa=_n0 + _td2(hours=19), log=lambda _s: None)
sjekk("etter 19 timer: fortsatt ikke", len(_hentet) == 1)
_r4 = _nff.fetch_all("eliteserien", naa=_n0 + _td2(hours=21), log=lambda _s: None)
sjekk("etter 21 timer: nytt forsøk", len(_hentet) == 2)

# Et forsok som FEILER maa ogsaa telle, ellers proever den hver time
_nff.hent = lambda url: (_hentet.append(url), (_ for _ in ()).throw(RuntimeError("403")))[1]
_r5 = _nff.fetch_all("eliteserien", naa=_n0 + _td2(hours=42), log=lambda _s: None)
sjekk("feilet forsøk teller: gammelt svar beholdes", _r5 == _r1 and len(_hentet) == 3)
_r6 = _nff.fetch_all("eliteserien", naa=_n0 + _td2(hours=43), log=lambda _s: None)
sjekk("og nytt forsøk kommer ikke før om 20 timer", len(_hentet) == 3)
sjekk("feilen er lagret i cachen",
      "403" in _json.loads((_nff_dir / "eliteserien.json").read_text("utf-8")).get("siste_feil", ""))
_nff.hent = _ekte_hent
_nff.CACHE_KATALOG = _ekte_kat

print("\n=== Gammel fotball.no-cache skal ikke paavirke en kjoring ===")
# Cachen kan vaere 20 timer gammel. Ligasiden kan i mellomtiden ha faatt nytt
# avspark OG ferskt resultat. Da skal ligasiden vinne, uten konflikt og uten
# stoy -- derfor er fotball.no ute av avstemmingen og bare med i den daglige
# revisjonen, der begge sider er like gamle.
_NY = [{"date": "2026-10-02", "time": "19:15", "round": 24,
        "home": "Ranheim", "away": "Egersund", "hg": 2, "ag": 1}]
_GAMMEL = [{"date": "2026-10-02", "time": "19:00", "round": 24,
            "home": "Ranheim", "away": "Egersund", "hg": None, "ag": None}]
_l2 = []
_ut2 = reconcile(_NY, [], log=_l2.append)
sjekk("ligasiden alene: nytt avspark og ferskt resultat beholdes",
      (_ut2[0]["time"], _ut2[0]["hg"], _ut2[0]["ag"]) == ("19:15", 2, 1), str(_ut2[0]))
sjekk("ingen konflikt", not any("ADVARSEL" in m for m in _l2), str(_l2))
sjekk("ingen advarsler i det hele tatt", not _l2, str(_l2))

# Til sammenligning: hadde cachen vaert med som kontroll, ville den klaget
_l3 = []
reconcile(_NY, _GAMMEL, log=_l3.append)
sjekk("(og med cachen som kontroll ville den klaget -- derfor er den ute)",
      any("avspark" in m for m in _l3), str(_l3))

print("\n=== Daglig terminlisterevisjon, begge ligaer ===")
import daglig_revisjon as _dr

_v = {("Ranheim", "Egersund"): {"round": 24, "date": "2026-10-02",
                                "time": "19:00", "hg": 2, "ag": 1}}
_lik = [{"home": "Ranheim", "away": "Egersund", "round": 24,
         "date": "2026-10-02", "time": "19:00", "hg": 2, "ag": 1}]
sjekk("enighet: ingen avvik", _dr.revider(_v, _lik) == ([], []))

_feil_runde = [{**_lik[0], "round": 25}]
_f, _a = _dr.revider(_v, _feil_runde)
sjekk("ulik RUNDE er kritisk", len(_f) == 1 and "runde" in _f[0], str(_f))

_feil_dato = [{**_lik[0], "date": "2026-10-03"}]
_f, _a = _dr.revider(_v, _feil_dato)
sjekk("ulik DATO er kritisk", len(_f) == 1 and "dato" in _f[0], str(_f))

_feil_tid = [{**_lik[0], "time": "19:15"}]
_f, _a = _dr.revider(_v, _feil_tid)
sjekk("ulikt AVSPARK er bare advarsel (tv-tider justeres)",
      not _f and len(_a) == 1 and "avspark" in _a[0], f"{_f} {_a}")

_feil_res = [{**_lik[0], "hg": 3}]
_f, _a = _dr.revider(_v, _feil_res)
sjekk("ulikt RESULTAT er kritisk", len(_f) == 1 and "resultat" in _f[0], str(_f))

_f, _a = _dr.revider(_v, [])
sjekk("tom kontrollkilde blokkerer ikke, men sier fra",
      not _f and len(_a) == 1, f"{_f} {_a}")

_f, _a = _dr.revider({}, _lik)
sjekk("kamp hos fotball.no som vi mangler er kritisk", len(_f) == 1, str(_f))

print("\n=== Gammel cache gir ADVARSEL, ikke rodt stempel ===")
# En kamp flyttes i gaar kveld. Ligasiden har ny dato; cachen er 10 timer
# gammel og har den gamle. Det er ikke en feil -- det er to tidspunkter.
_flyttet = {("Ranheim", "Egersund"): {"round": 24, "date": "2026-10-05",
                                      "time": "19:00", "hg": None, "ag": None}}
_gammel_cache = [{"home": "Ranheim", "away": "Egersund", "round": 24,
                  "date": "2026-10-02", "time": "19:00", "hg": None, "ag": None}]

_f, _a = _dr.revider(_flyttet, _gammel_cache, ferskt=True)
sjekk("fersk henting: flyttet kamp er kritisk", len(_f) == 1 and "dato" in _f[0], str(_f))
_f, _a = _dr.revider(_flyttet, _gammel_cache, ferskt=False)
sjekk("10 timer gammel cache: bare advarsel, ingen kritiske avvik",
      not _f and len(_a) == 1, f"feil={_f} advarsler={_a}")
sjekk("og advarselen sier at dataene er fra cachen",
      "fra cachen" in _a[0], str(_a))

print("\n=== Stempelet overskrives ikke av neste kjoring ===")
import daglig_revisjon as _dr2
_sd = Path(_tf2.mkdtemp())
(_sd / "data").mkdir()
_ekte_rot2 = _dr2.ROT
_dr2.ROT = _sd
_dr2.LIGAER["test"] = {"data": "data", "visningsnavn": "Test"}
_ligaer_ekte = dict(_dr2.oppsett.__globals__["LIGAER"])
_dr2.oppsett.__globals__["LIGAER"]["test"] = {"data": "data", "visningsnavn": "Test"}
_naa5 = _dt.now(_tz.utc)
_dag5 = _naa5.astimezone(_dr2.OSLO).strftime("%Y-%m-%d")

(_sd / "data" / "audit_fixtures.json").write_text(
    _json.dumps({"checked_date": _dag5, "errors": 3}), encoding="utf-8")
sjekk("dagens revisjon med 3 avvik leses av andre skrivere",
      _dr2.dagens_avvik("test", _naa5) == 3)
(_sd / "data" / "audit_fixtures.json").write_text(
    _json.dumps({"checked_date": "2020-01-01", "errors": 3}), encoding="utf-8")
sjekk("gårsdagens avvik teller ikke", _dr2.dagens_avvik("test", _naa5) == 0)
(_sd / "data" / "audit_fixtures.json").write_text(
    _json.dumps({"checked_date": _dag5, "errors": 0}), encoding="utf-8")
sjekk("ren revisjon i dag gir 0", _dr2.dagens_avvik("test", _naa5) == 0)

# skriv_stempel: rodt naar det er avvik, gronnt naar det ikke er det
_dr2.skriv_stempel("test", ["noe galt"], _naa5)
_st5 = _json.loads((_sd / "data" / "status.json").read_text(encoding="utf-8"))
sjekk("skriv_stempel setter ok=False ved avvik", _st5["ok"] is False and _st5["revisjon_avvik"] == 1)
_dr2.skriv_stempel("test", [], _naa5)
_st5 = _json.loads((_sd / "data" / "status.json").read_text(encoding="utf-8"))
sjekk("og ok=True naar avviket er borte",
      _st5["ok"] is True and "revisjon_avvik" not in _st5, str(_st5))
_dr2.skriv_stempel("test", ["Ranheim-Egersund: dato 2026-10-03 hos oss, 2026-10-02 i kalenderfeeden"], _naa5)
_st5 = _json.loads((_sd / "data" / "status.json").read_text(encoding="utf-8"))
sjekk("et avvik i terminlisten gjør stempelet rødt og sier at det er mot kalenderfeeden",
      _st5["ok"] is False and "avvik mellom terminlisten og kalenderfeeden: Ranheim-Egersund" in _st5["error"], str(_st5))
_dr2.skriv_stempel("test", ["Tabell, Åsane: 20 poeng hos oss, 19 hos fotball.no"], _naa5, kilde="fotball.no")
_st5 = _json.loads((_sd / "data" / "status.json").read_text(encoding="utf-8"))
sjekk("ved reparasjon for hånd (fotball.no): et tabellavvik sier at det er tabellen",
      _st5["ok"] is False and "avvik mellom tabellen og fotball.no: Tabell, Åsane" in _st5["error"], str(_st5))
_dr2.skriv_stempel("test", [], _naa5)
_dr2.ROT = _ekte_rot2
_dr2.oppsett.__globals__["LIGAER"].pop("test", None)

print("\n=== Et bekreftet avvik blir ikke gronnt av at cachen eldes ===")
# Forlopet: fersk revisjon finner avviket. En time senere er cachen over 10
# minutter gammel. Uten dette ville avviket blitt nedgradert til advarsel,
# stempelet gronnt og siste_ok satt -- mens feilen sto.
_v_feil = {("Haugesund", "Sogndal"): {"round": 21, "date": "2026-01-01",
                                      "time": "16:00", "hg": 2, "ag": 0}}
_nff_rett = [{"home": "Haugesund", "away": "Sogndal", "round": 21,
              "date": "2026-09-05", "time": "16:00", "hg": 2, "ag": 0}]

_f1, _a1 = _dr.revider(_v_feil, _nff_rett, ferskt=True)
sjekk("fersk revisjon: avviket er kritisk", len(_f1) == 1, str(_f1))
_bekreftet = {_dr._nokkel(_f1[0]): _dr._vaar_verdi(_v_feil, _dr._nokkel(_f1[0]))}

_f2, _a2 = _dr.revider(_v_feil, _nff_rett, ferskt=False, bekreftet=_bekreftet)
sjekk("en time senere, gammel cache, VÅR VERDI UENDRET: fortsatt kritisk",
      len(_f2) == 1, f"feil={_f2} advarsler={_a2}")
sjekk("og det sies at den er bekreftet",
      "bekreftet av fersk revisjon" in _f2[0], str(_f2))

# Retter vi datoen, skal den ikke lenger holdes kritisk mot gammel cache
_v_rettet = {("Haugesund", "Sogndal"): {"round": 21, "date": "2026-09-05",
                                        "time": "16:00", "hg": 2, "ag": 0}}
_f3, _a3 = _dr.revider(_v_rettet, _nff_rett, ferskt=False, bekreftet=_bekreftet)
sjekk("etter at VI har rettet: ingen avvik igjen", not _f3 and not _a3, f"{_f3} {_a3}")

# Endrer vi til noe ANNET galt, er det et nytt avvik mot gammel cache --
# og da skal det nedgraderes, ikke arve bekreftelsen
_v_annet = {("Haugesund", "Sogndal"): {"round": 21, "date": "2026-02-02",
                                       "time": "16:00", "hg": 2, "ag": 0}}
_f4, _a4 = _dr.revider(_v_annet, _nff_rett, ferskt=False, bekreftet=_bekreftet)
sjekk("men en NY, annen verdi arver ikke bekreftelsen",
      not _f4 and len(_a4) == 1, f"{_f4} {_a4}")

print("\n=== fotball.no-tabellen: bare reparasjon for hånd ===")
# Regelen fra 1.10.2026: fotball.no hentes bare automatisk som reserve når
# ligasiden ikke svarer. Tabellen og justeringene der leses bare ved
# reparasjon av en frossen sesong for hånd (daglig_revisjon.revider_sesong).
_html_o = les_nff("obos")
_tab = nff_source.parse_tabell(_html_o, "obos")
_jn = nff_source.parse_justeringer(_html_o, "obos")
_aa = next(r for r in _tab if r["lag"] == "Åsane")
sjekk("fotball.no-tabellen leses: 16 lag, Åsane 19 poeng med stjerne (\"15 *\"), 5-5-13",
      [r["plass"] for r in _tab] == list(range(1, 17)) and (_aa["plass"], _aa["merket"], _aa["poeng"], _aa["v"], _aa["u"]) == (15, True, 19, 5, 5), str(_aa))
sjekk("negativ målforskjell med minustegn (U+2212) leses som tall", _aa["diff"] == _aa["mf"] - _aa["mm"] == -18, str(_aa))
sjekk("justeringene leses: Åsane −1 poeng, 0 mål, 4. mars, med årsaken",
      [(j["dato"], j["lag"], j["poeng"], j["maal"]) for j in _jn] == [("2026-03-04", "Åsane", -1, 0)]
      and _jn[0]["aarsak"].startswith("Oversittelse av rapporteringsfrist"), str(_jn))
for _navn, _omlagt in (("en kolonne har nytt navn", _html_o.replace(">Poeng</th>", ">Pts</th>")),
                       ("tabellen mangler", _html_o.replace("customTableSorter", "nyKlasse"))):
    try:
        nff_source.parse_tabell(_omlagt, "obos")
        _kast = False
    except nff_source.NffDataError:
        _kast = True
    sjekk(f"fotball.no: omlagt markup ({_navn}) gir NffDataError, ikke en stille feil", _kast)

print("\n=== Tabellkontrollen mot tabellen på ligasiden ===")
# Tabellen står på resultatsiden vi alt henter (ingen ekstra forespørsel), og
# viser poengene etter trekk, uten markering. Testdataene og fasiten er fra
# samme dag, 25.9.2026.
import tabellkontroll as _tk
_ntf_o = les_ntf("obos", "resultater")
_nt = ntf_source.parse_tabell(_ntf_o, "obos")
_na = next(r for r in _nt if r["lag"] == "Åsane")
sjekk("NTF-tabellen leses fra resultatsiden: 16 lag, plass 1 til 16, Åsane 19 poeng (23 kamper, 5-5-13, 34-52)",
      [r["plass"] for r in _nt] == list(range(1, 17))
      and (_na["k"], _na["v"], _na["u"], _na["t"], _na["mf"], _na["mm"], _na["poeng"]) == (23, 5, 5, 13, 34, 52, 19), str(_na))
_nte = ntf_source.parse_tabell(les_ntf("eliteserien", "resultater"), "eliteserien")
sjekk("Eliteserien: 16 lag, navnene oversatt (KFUM Oslo, Sandefjord)",
      len(_nte) == 16 and {"KFUM Oslo", "Sandefjord"} <= {r["lag"] for r in _nte}, str([r["lag"] for r in _nte]))
for _navn, _omlagt in (("en kolonne har nytt navn", _ntf_o.replace(">Poeng<", ">Pts<", 1)),
                       ("tabellen mangler", _ntf_o.replace("league-table--full", "nyKlasse"))):
    try:
        ntf_source.parse_tabell(_omlagt, "obos")
        _kast = False
    except ntf_source.EsDataError:
        _kast = True
    sjekk(f"NTF: omlagt tabell ({_navn}) gir EsDataError, ikke en stille feil", _kast)
_fk = {l: [m for m in json.loads((TESTDATA / f"fasit_{l}_2026-09-25.json").read_text("utf-8"))["kamper"] if m["hg"] is not None]
       for l in ("eliteserien", "obos")}
_lag_o = sorted(LIGAER["obos"]["lag"])
_vt = _tk.vaar_tabell(_fk["obos"], _lag_o, {"Åsane": -1})
_f, _a, _n, _like = _tk.sammenlign(_vt, _nt, "obos-ligaen.no")
sjekk("kampene fra 25.9 med Åsanes trekk mot NTF-tabellen samme dag: alle 16 lag like, også plassene",
      (_f, _a, _n, _like) == ([], [], [], True), f"{_f} {_a} {_n}")
_f, _a, _n, _like = _tk.sammenlign(_tk.vaar_tabell(_fk["eliteserien"], sorted(LIGAER["eliteserien"]["lag"])), _nte, "eliteserien.no")
sjekk("Eliteserien 25.9: alle like uten justeringer", (_f, _a, _n, _like) == ([], [], [], True), f"{_f} {_a} {_n}")
_vt0 = _tk.vaar_tabell(_fk["obos"], _lag_o)
_f, _a, _n, _like = _tk.sammenlign(_vt0, _nt, "obos-ligaen.no")
sjekk("uten trekket: ingen feil, men et nytt poengtrekk for Åsane (−1), og ikke alle like ennå",
      not _f and not _a and _n == [("Åsane", -1)] and not _like, f"{_f} {_a} {_n}")
_feil_vut = {**_vt, "Moss": {**_vt["Moss"], "v": _vt["Moss"]["v"] + 1, "t": _vt["Moss"]["t"] - 1, "poeng": _vt["Moss"]["poeng"] + 3}}
_f, _a, _n, _like = _tk.sammenlign(_feil_vut, _nt, "obos-ligaen.no")
sjekk("likt antall kamper, men V/U/T avviker: kritisk avvik, ikke et poengtrekk",
      len(_f) == 1 and _f[0].startswith("Tabell, Moss:") and "vunnet" in _f[0] and "tap" in _f[0] and not _n, f"{_f} {_n}")
_feil_maal = {**_vt, "Lyn": {**_vt["Lyn"], "mf": _vt["Lyn"]["mf"] + 1}}
_f, _a, _n, _like = _tk.sammenlign(_feil_maal, _nt, "obos-ligaen.no")
sjekk("likt antall kamper, men målene avviker: kritisk avvik",
      len(_f) == 1 and "mål for hos oss" in _f[0] and not _like, str(_f))
_en_kamp_til = {**_vt0, "Åsane": {**_vt0["Åsane"], "k": 24, "v": 6, "poeng": 23}}
_f, _a, _n, _like = _tk.sammenlign(_en_kamp_til, _nt, "obos-ligaen.no")
sjekk("ulikt antall kamper: advarsel (hentet på ulike tidspunkt), ikke avvik og ikke et poengtrekk",
      not _f and not _n and len(_a) == 1 and "24 kamper hos oss, 23 hos obos-ligaen.no" in _a[0] and not _like, f"{_f} {_a} {_n}")
_byttet = {**_vt, "Åsane": {**_vt["Åsane"], "plass": 16}, "Raufoss": {**_vt["Raufoss"], "plass": 15}}
_f, _a, _n, _like = _tk.sammenlign(_byttet, _nt, "obos-ligaen.no")
sjekk("lik poengsum, ulik rangering: advarsel", not _f and len(_a) == 2 and "ulik rangering" in _a[0], f"{_f} {_a}")

# kontroller(): skriver audit_tabell.json, og legger et nytt trekk inn i
# justeringer.json AUTOMATISK, med datoen det ble oppdaget og kilden.
_kd = Path(_tf2.mkdtemp())
(_kd / "justeringer.json").write_text(json.dumps({"note": "x", "justeringer": []}), encoding="utf-8")
_naa_k = _dt(2026, 10, 1, 9, 0, tzinfo=_tz.utc)
_r1 = _tk.kontroller("obos", 2026, _fk["obos"], _nt, naa=_naa_k, data_dir=_kd,
                     kilde_url="https://www.obos-ligaen.no/resultater", kjoring="k1", log=lambda _s: None)
_j1 = json.loads((_kd / "justeringer.json").read_text("utf-8"))["justeringer"]
sjekk("kontroller: Åsanes trekk oppdages og legges inn i justeringer.json, med dato, oppdaget, kilde, årsak og automatisk",
      [(j["sesong"], j["lag"], j["poeng"], j["dato"], j["oppdaget"], j["kilde"], j["automatisk"]) for j in _j1]
      == [(2026, "Åsane", -1, "2026-10-01", "2026-10-01T09:00:00+00:00", "https://www.obos-ligaen.no/resultater", True)]
      and "19 poeng, mot 20 fra kampene" in _j1[0]["årsak"] and "lenke" not in _j1[0], str(_j1))
_a1 = json.loads((_kd / "audit_tabell.json").read_text("utf-8"))
sjekk("og audit_tabell.json: sammenlignet, ingen avvik, alle like etter trekket, det nye trekket og kjøringen",
      (_a1["sammenlignet"], _a1["errors"], _a1["alle_like"], len(_a1["nye"]), _a1["kjoring"]) == (True, 0, True, 1, "k1"), str(_a1))
_r2 = _tk.kontroller("obos", 2026, _fk["obos"], _nt, naa=_naa_k, data_dir=_kd, kjoring="k2", log=lambda _s: None)
sjekk("neste kjøring legger ikke inn trekket på nytt",
      len(json.loads((_kd / "justeringer.json").read_text("utf-8"))["justeringer"]) == 1 and _r2["nye"] == [] and _r2["alle_like"], str(_r2))
sjekk("varsle: bare trekk som ble lagt inn i DENNE kjøringen (k2 la ikke inn noe)",
      _tk.varsle("obos", data_dir=_kd, kjoring="k2", log=lambda _s: None) == 0)
_kd2 = Path(_tf2.mkdtemp())
(_kd2 / "justeringer.json").write_text(json.dumps({"justeringer": []}), encoding="utf-8")
_tk.kontroller("obos", 2026, _fk["obos"], _nt, naa=_naa_k, data_dir=_kd2, kjoring="k3", log=lambda _s: None)
_varsel = []
with _vern.miljo(GH_TOKEN="", GITHUB_TOKEN="", GITHUB_STEP_SUMMARY=str(_kd2 / "oppsummering.md")):
    _antall = _tk.varsle("obos", data_dir=_kd2, kjoring="k3", log=_varsel.append)
sjekk("varsle i kjøringen som la inn trekket: advarsel i Actions og en linje i oppsummeringen (ingen issue uten token)",
      _antall == 1 and any(v.startswith("::warning title=Nytt poengtrekk i OBOS-ligaen: Åsane trukket et poeng::") for v in _varsel)
      and "Nytt poengtrekk i OBOS-ligaen: Åsane trukket et poeng" in (_kd2 / "oppsummering.md").read_text("utf-8")
      and not any(v.startswith("  issue:") for v in _varsel), str(_varsel))
_kd3 = Path(_tf2.mkdtemp())
(_kd3 / "justeringer.json").write_text(json.dumps({"justeringer": [
    {"sesong": 2026, "lag": "Åsane", "poeng": -1, "dato": "2026-03-04", "kilde": "test", "årsak": "test"}]}), encoding="utf-8")
_feil_kamper = [dict(m) for m in _fk["obos"]]
_mi = next(i for i, m in enumerate(_feil_kamper) if m["home"] == "Moss" and m["hg"] < m["ag"])
_feil_kamper[_mi]["hg"], _feil_kamper[_mi]["ag"] = _feil_kamper[_mi]["ag"], _feil_kamper[_mi]["hg"]
_r4 = _tk.kontroller("obos", 2026, _feil_kamper, _nt, naa=_naa_k, data_dir=_kd3, kjoring="k5", log=lambda _s: None)
sjekk("et feil resultat hos oss gir kritiske avvik for begge lagene i audit_tabell.json (rødt stempel), og ikke et poengtrekk",
      _r4["errors"] == 2 and {f.split(":")[0] for f in _r4["avvik"]} == {"Tabell, Moss", "Tabell, " + (_feil_kamper[_mi]["away"])}
      and not _r4["alle_like"] and _r4["nye"] == [] and _tk.avvik("obos", data_dir=_kd3) == 2
      and len(json.loads((_kd3 / "justeringer.json").read_text("utf-8"))["justeringer"]) == 1, str(_r4))
_r5 = _tk.kontroller("obos", 2026, _fk["obos"], {"feil": "fant ingen tabell"}, naa=_naa_k, data_dir=_kd3, kjoring="k6", log=lambda _s: None)
sjekk("uten tabell fra ligasiden: advarsel om at den ikke er sammenlignet, ingen avvik og ikke alle like",
      (_r5["sammenlignet"], _r5["errors"], _r5["alle_like"]) == (False, 0, False) and "fant ingen tabell" in _r5["advarsler"][0], str(_r5))

print("\n=== Kalenderfeeden: den løpende kontrollen av runde, dato og avspark ===")
_kal_o = (TESTDATA / "ntf_obos_kalender_2026-10-01.ics").read_text("utf-8")
_ko = ntf_source.parse_kalender(_kal_o, "obos")
_ke = ntf_source.parse_kalender((TESTDATA / "ntf_eliteserien_kalender_2026-10-01.ics").read_text("utf-8"), "eliteserien")
sjekk("OBOS-feeden: 58 oppføringer, de to identiske dublettene slått sammen til 56 kamper",
      _kal_o.count("BEGIN:VEVENT") == 58 and len(_ko) == 56, f"{_kal_o.count('BEGIN:VEVENT')} {len(_ko)}")
sjekk("Eliteserien-feeden: 72 kamper", len(_ke) == 72, str(len(_ke)))
_rd = next(m for m in _ko if (m["home"], m["away"]) == ("Ranheim", "Egersund"))
sjekk("Ranheim TF - Egersund: runde 24, 2.10. kl. 19.00, Ranheim TF oversatt",
      (_rd["round"], _rd["date"], _rd["time"]) == (24, "2026-10-02", "19:00"), str(_rd))
_brettet = _kal_o.replace("DESCRIPTION: OBOS-ligaen (runde 24)", "DESCRIPTION: OBOS-ligaen (ru\r\n nde 24)", 1)
sjekk("brettede linjer (linjeskift + mellomrom) leses som én", ntf_source.parse_kalender(_brettet, "obos") == _ko)
_tz_tekst = _kal_o.replace("BEGIN:VEVENT", "BEGIN:VTIMEZONE\nDTSTART:20160301T020000\nEND:VTIMEZONE\nBEGIN:VEVENT", 1)
sjekk("DTSTART i tidssonedefinisjonen (VTIMEZONE) leses ikke som en kamp", ntf_source.parse_kalender(_tz_tekst, "obos") == _ko)
_konflikt = _kal_o.replace("END:VCALENDAR", "BEGIN:VEVENT\nSUMMARY:Ranheim TF - Egersund\nDESCRIPTION: OBOS-ligaen (runde 24)\n"
                           "DTSTART;TZID=Europe/Oslo:20261002T181500\nEND:VEVENT\nEND:VCALENDAR")
try:
    ntf_source.parse_kalender(_konflikt, "obos")
    _kast = None
except ntf_source.EsDataError as e:
    _kast = str(e)
sjekk("samme kamp to ganger med ulik tid: tydelig feil", _kast is not None and "to ganger" in _kast, str(_kast))
import daglig_revisjon as _drk
_fasit_alle = {l: {(m["home"], m["away"]): m for m in json.loads((ROT / "tests" / "data" / "2026-10-01" / l / "data" / "matches.json").read_text("utf-8"))}
               for l in ("eliteserien", "obos")}
for _l in ("eliteserien", "obos"):
    for _r in json.loads((ROT / "tests" / "data" / "2026-10-01" / _l / "data" / "fixtures.json").read_text("utf-8")):
        for _m in _r["matches"]:
            _fasit_alle[_l][(_m["home"], _m["away"])] = {**_m, "round": _r["round"]}
_f, _a = _drk.revider_kalender(_fasit_alle["obos"], _ko, sesong="2026")
sjekk("terminlisten fra samme dag (1.10) mot feeden: ingen avvik, ingen advarsler (OBOS)", (_f, _a) == ([], []), f"{_f} {_a}")
_f, _a = _drk.revider_kalender(_fasit_alle["eliteserien"], _ke, sesong="2026")
sjekk("og Eliteserien", (_f, _a) == ([], []), f"{_f} {_a}")
_v = {**_fasit_alle["obos"], ("Ranheim", "Egersund"): {**_fasit_alle["obos"][("Ranheim", "Egersund")], "round": 25}}
_f, _a = _drk.revider_kalender(_v, _ko, sesong="2026")
sjekk("ulik RUNDE er kritisk", _f == ["Ranheim-Egersund: runde 25 hos oss, 24 i kalenderfeeden"], str(_f))
_v = {**_fasit_alle["obos"], ("Ranheim", "Egersund"): {**_fasit_alle["obos"][("Ranheim", "Egersund")], "date": "2026-10-03"}}
_f, _a = _drk.revider_kalender(_v, _ko, sesong="2026")
sjekk("ulik DATO er kritisk", _f == ["Ranheim-Egersund: dato 2026-10-03 hos oss, 2026-10-02 i kalenderfeeden"], str(_f))
_v = {**_fasit_alle["obos"], ("Ranheim", "Egersund"): {**_fasit_alle["obos"][("Ranheim", "Egersund")], "time": "18:00"}}
_f, _a = _drk.revider_kalender(_v, _ko, sesong="2026")
sjekk("ulikt AVSPARK er en advarsel", not _f and _a == ["Ranheim-Egersund: avspark 18:00 hos oss, 19:00 i kalenderfeeden"], f"{_f} {_a}")
_v = {k: m for k, m in _fasit_alle["obos"].items() if k != ("Ranheim", "Egersund")}
_f, _a = _drk.revider_kalender(_v, _ko, sesong="2026")
sjekk("en kamp i feeden som vi ikke har, er kritisk", _f == ["Ranheim-Egersund: står i kalenderfeeden, men ikke hos oss"], str(_f))
_f, _a = _drk.revider_kalender(_fasit_alle["obos"], [m for m in _ko if (m["home"], m["away"]) != ("Ranheim", "Egersund")], sesong="2026")
sjekk("en uspilt kamp hos oss som feeden ikke har, er en advarsel", not _f and _a == ["Ranheim-Egersund: uspilt hos oss, men står ikke i kalenderfeeden"], f"{_f} {_a}")
_v = {**_fasit_alle["obos"], ("Ranheim", "Egersund"): {**_fasit_alle["obos"][("Ranheim", "Egersund")], "hg": 2, "ag": 1}}
_f, _a = _drk.revider_kalender(_v, _ko, sesong="2026")
sjekk("en kamp som nettopp er spilt, men fortsatt står i feeden, sammenlignes og er ikke et avvik", (_f, _a) == ([], []), f"{_f} {_a}")

# Tidssonen i DTSTART (3.10.2026). Feeden oppgir TZID=Europe/Oslo, men en
# tid i UTC (Z eller TZID=UTC) eller en annen sone skal regnes om, ikke stoppe
# revisjonen ("uventet oppføring") eller leses som norsk tid.
def _ett_kal(dtstart):
    return ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Haugesund - Stabæk\r\nDESCRIPTION: OBOS-ligaen (runde 24)\r\n"
            f"{dtstart}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
_tz_tilfeller = [("DTSTART;TZID=Europe/Oslo:20261003T160000", ("2026-10-03", "16:00")),
                 ("DTSTART:20261003T160000", ("2026-10-03", "16:00")),
                 ("DTSTART:20261003T140000Z", ("2026-10-03", "16:00")),
                 ("DTSTART;TZID=UTC:20261003T140000", ("2026-10-03", "16:00")),
                 ("DTSTART;TZID=Europe/London:20261003T150000", ("2026-10-03", "16:00")),
                 ("DTSTART:20261107T170000Z", ("2026-11-07", "18:00")),
                 ("DTSTART;VALUE=DATE:20261003", ("2026-10-03", None))]
_tz_ut = [(d, (lambda r: (r[0]["date"], r[0]["time"]))(ntf_source.parse_kalender(_ett_kal(d), "obos"))) for d, _v in _tz_tilfeller]
sjekk("DTSTART i norsk tid, flytende, UTC (Z og TZID=UTC), en annen sone, vintertid og heldag: alle til norsk tid",
      [u for _d, u in _tz_ut] == [v for _d, v in _tz_tilfeller], str(_tz_ut))
try:
    ntf_source.parse_kalender(_ett_kal("DTSTART;TZID=Mars/Olympus:20261003T160000"), "obos")
    _kast = None
except ntf_source.EsDataError as e:
    _kast = str(e)
sjekk("ukjent tidssone: tydelig feil, ikke en gjetning", _kast is not None and "tidssone" in _kast, str(_kast))
# Feeden fra 3.10.2026 kl. 18.49: de fire kampene som var spilt den dagen,
# sto med avsparket i UTC under TZID=Europe/Oslo (NTF lagret tiden slik da
# oppføringen ble endret ved kampslutt). Revisjonen ga fem advarsler
# ("avspark 16:00 hos oss, 14:00 i kalenderfeeden").
_k3 = ntf_source.parse_kalender((TESTDATA / "ntf_obos_kalender_2026-10-03.ics").read_text("utf-8"), "obos")
_hs = next(m for m in _k3 if (m["home"], m["away"]) == ("Haugesund", "Stabæk"))
sjekk("feeden 3.10.: Haugesund - Stabæk står med 14:00 (avsparket 16:00 i UTC)", _hs["time"] == "14:00", str(_hs))
_v3 = {k: dict(m) for k, m in _fasit_alle["obos"].items()}
for _k, _res in {("Ranheim", "Egersund"): (5, 0), ("Strømmen", "Sandnes Ulf"): (3, 3), ("Strømsgodset", "Åsane"): (1, 0),
                 ("Haugesund", "Stabæk"): (2, 0), ("Hødd", "Odd"): (2, 3)}.items():
    _v3[_k]["hg"], _v3[_k]["ag"] = _res
_logg = []
_f, _a = _drk.revider_kalender(_v3, _k3, sesong="2026", naa=_dt(2026, 10, 3, 16, 33, tzinfo=_tz.utc), log=_logg.append)
sjekk("revisjonen 3.10. kl. 18.33: ingen avvik og ingen advarsler; de fire er regnet om fra UTC og logget",
      (_f, _a) == ([], []) and sum(l.startswith("MERK:") and "i UTC" in l for l in _logg) == 4, f"{_f} {_a} {_logg}")
_f, _a = _drk.revider_kalender(_v3, _k3, sesong="2026", naa=_dt(2026, 10, 3, 11, 0, tzinfo=_tz.utc), log=lambda _s: None)
sjekk("samme feed FØR avspark: advarsel for alle fire (en ekte flytting to timer fram skal sees), med forklaringen",
      not _f and len(_a) == 4 and all("vårt avspark i UTC" in x for x in _a), f"{_f} {_a}")
_v4 = {k: dict(m) for k, m in _v3.items()}
_v4[("Haugesund", "Stabæk")]["time"] = "18:00"
_f, _a = _drk.revider_kalender(_v4, _k3, sesong="2026", naa=_dt(2026, 10, 3, 16, 33, tzinfo=_tz.utc), log=lambda _s: None)
sjekk("en tid som ikke er vårt avspark i UTC, er fortsatt en advarsel etter avspark",
      not _f and _a == ["Haugesund-Stabæk: avspark 18:00 hos oss, 14:00 i kalenderfeeden"], f"{_f} {_a}")

print("\n=== fotball.no bare som reserve når ligasiden ikke svarer ===")
import urllib.error as _ue
import hentelogg as _hlr
import nff_source as _nffr
_ekte_hl_kat = _hlr.KATALOG
_hlr.KATALOG = Path(_tf2.mkdtemp()) / "hentelogg"
import obos_build_data as _obd
import obos_results as _obr
_ekte_ntf_hent, _ekte_ntf_fa, _ekte_nff_fa = ntf_source.hent, ntf_source.fetch_all, _nffr.fetch_all
_nff_kall = []
_nffr.fetch_all = lambda liga, **k: (_nff_kall.append(liga), [{"date": "2026-10-02", "time": "19:00", "round": 24, "home": "Ranheim",
                                                             "away": "Egersund", "hg": None, "ag": None, "ferdig": False}])[1]
try:
    ntf_source.hent = lambda url: (_ for _ in ()).throw(_ue.URLError("Name or service not known"))
    try:
        ntf_source.fetch_all("obos", log=lambda _s: None)
        _kast = None
    except ntf_source.SvarerIkke as e:
        _kast = e
    sjekk("ligasiden svarer ikke (nettverksfeil): fetch_all kaster SvarerIkke", _kast is not None, repr(_kast))
    ntf_source.hent = lambda url: (_ for _ in ()).throw(ntf_source.RateLimited(403))
    try:
        ntf_source.fetch_all("obos", log=lambda _s: None)
        _kast = None
    except ntf_source.SvarerIkke as e:
        _kast = e
    sjekk("og blokkering (403) er også SvarerIkke", _kast is not None, repr(_kast))
    # Reservekjeden for terminlisten (3.10.2026) går foran fotball.no: med
    # den siste gyldige terminlisten brukes fotball.no bare i resultatkjeden.
    # Kalenderfeeden går gjennom ntf_source.hent (stoppet over); ESPN og
    # Highlightly stoppes her, så ingenting går ut på nettet.
    import espn_source as _esr
    import leaguedata as _ldr
    import highlightly_source as _hlsr
    _ekte_espn_get, _ekte_hl_http2, _ekte_forrige = _esr.get_json, _hlsr._http, _ldr.forrige_terminliste
    _esr.get_json = lambda url: (_ for _ in ()).throw(_ue.URLError("ingen ESPN i testen"))
    _hlsr._http = lambda sti, param: (_ for _ in ()).throw(_ue.URLError("ingen Highlightly i testen"))
    ntf_source.fetch_all = lambda *a, **k: (_ for _ in ()).throw(ntf_source.SvarerIkke("ingen svar"))
    _rader = _obd.rows_for(log=lambda _s: None)
    _res = _obr.offisielle_resultater()
    sjekk("OBOS: ligasiden svarer ikke -> byggingen bruker reservekjeden (her: den siste gyldige terminlisten), resultatkjeden fotball.no",
          _nff_kall == ["obos"] and len(_rader) == 240 and _res == {}, f"{_nff_kall} {len(_rader)} {_res}")
    import update_data as _ud
    _nff_kall.clear()
    _r = _ud.ligasiden_eller_reserve(None, lambda _s: None)
    sjekk("Eliteserien: ligasiden svarer ikke -> reservekjeden (her: den siste gyldige terminlisten), ikke fotball.no",
          _nff_kall == [] and len(_r) == 240 and _ud.LIGAKILDE == "forrige terminliste", f"{_nff_kall} {len(_r)} {_ud.LIGAKILDE}")
    # Krise: ligasiden svarer ikke, og den siste gyldige terminlisten finnes ikke.
    _ldr.forrige_terminliste = lambda *a, **k: None
    _nff_kall.clear()
    _rader = _obd.rows_for(log=lambda _s: None)
    _r = _ud.ligasiden_eller_reserve(None, lambda _s: None)
    sjekk("i krise (ingen siste gyldige terminliste): fotball.no i begge ligaene",
          _nff_kall == ["obos", "eliteserien"] and len(_r) == 1 and _ud.LIGAKILDE == "fotball.no", f"{_nff_kall} {_ud.LIGAKILDE}")
    _ldr.forrige_terminliste = _ekte_forrige
    _nff_kall.clear()
    ntf_source.fetch_all = lambda *a, **k: (_ for _ in ()).throw(ntf_source.EsDataError("lagt om"))
    _r = _ud.ligasiden_eller_reserve(None, lambda _s: None)
    _obd.rows_for(log=lambda _s: None)
    _obr.offisielle_resultater()
    sjekk("ligasiden svarer, men kan ikke leses: reservekjeden, aldri fotball.no",
          _nff_kall == [] and len(_r) == 240, f"{_nff_kall} {len(_r)}")
    _ldr.forrige_terminliste = lambda *a, **k: None
    try:
        _ud.ligasiden_eller_reserve(None, lambda _s: None)
        _kast = None
    except ntf_source.EsDataError as e:
        _kast = e
    _ldr.forrige_terminliste = _ekte_forrige
    sjekk("og uten siste gyldige terminliste: feilen stopper Eliteserie-kjøringen (skjules ikke bak fotball.no)",
          _nff_kall == [] and _kast is not None, f"{_nff_kall} {_kast!r}")
    _esr.get_json, _hlsr._http = _ekte_espn_get, _ekte_hl_http2
    ntf_source.fetch_all = lambda liga, **k: [{"date": "2026-10-02", "time": "19:00", "round": 24, "home": "Ranheim",
                                               "away": "Egersund", "hg": None, "ag": None, "ferdig": False}]
    _obr.offisielle_resultater()
    _ud.ligasiden_eller_reserve(None, lambda _s: None)
    sjekk("ligasiden svarer: fotball.no hentes aldri", _nff_kall == [], str(_nff_kall))
finally:
    ntf_source.hent, ntf_source.fetch_all, _nffr.fetch_all = _ekte_ntf_hent, _ekte_ntf_fa, _ekte_nff_fa
    _hlr.KATALOG = _ekte_hl_kat

print("\n=== Reserven er den forrige terminlisten, ikke CSV-en ===")
# 3.10.2026: mens NTF-terminlisten feilet (15:53-16:33Z), bygget OBOS-kjeden
# fra CSV-en, og Ranheim-Sogndal (1.11.) sto med 17:00 hos oss i 50 minutter,
# enda den ble flyttet til 14:30 29.9. Reserven er nå den siste gyldige
# terminlisten vi selv har skrevet (fixtures.json og matches.json), også når
# en kamp mangler hos ligasiden, i datovakten og i resultatkjeden
# (obos_results.schedule skriver dato og avspark i matches.json). CSV-en
# bare når filene mangler eller er ufullstendige, som ved sesongstart.
import shutil as _shr
_sbr = Path(_tf2.mkdtemp())
for _f in ("fixtures.json", "matches.json"):
    _shr.copy(ROT / "tests" / "data" / "2026-10-01" / "obos" / "data" / _f, _sbr / _f)
_csv_par = {}
import csv as _csvr
for _r in _csvr.DictReader((ROT / "obos" / "data" / "obos_2012-2026.csv").open(encoding="utf-8-sig")):
    if _r["sesong"] == "2026":
        _csv_par[(_r["hjemme"], _r["borte"])] = (_r["dato"], _r["tid"])
sjekk("forutsetningen: CSV-en har Ranheim-Sogndal 1.11. 17:00, terminlisten vår 14:30",
      _csv_par.get(("Ranheim", "Sogndal")) == ("2026-11-01", "17:00"), str(_csv_par.get(("Ranheim", "Sogndal"))))
_fr = leaguedata.forrige_terminliste(_sbr, "2026", forventet_par=set(_csv_par))
_rs = [m for m in (_fr or []) if (m["home"], m["away"]) == ("Ranheim", "Sogndal")]
sjekk("forrige_terminliste: alle 240 kampene fra fixtures.json og matches.json, Ranheim-Sogndal 14:30",
      _fr is not None and len(_fr) == 240 and (_rs[0]["date"], _rs[0]["time"]) == ("2026-11-01", "14:30")
      and sum(m["hg"] is not None for m in _fr) == len(json.loads((_sbr / "matches.json").read_text("utf-8"))), str(_rs))
sjekk("forrige_terminliste: None når en kamp mangler, eller sesongen er en annen",
      leaguedata.forrige_terminliste(_sbr, "2026", forventet_par=set(_csv_par) | {("Moss", "Moss")}) is None
      and leaguedata.forrige_terminliste(_sbr, "2027") is None)
_ekte_data_obd, _ekte_data_obr, _ekte_fa_r = _obd.DATA, _obr.DATA, ntf_source.fetch_all
_ekte_kal_r = ntf_source.hent_kalender
import highlightly_source as _hlsr2
_ekte_hl_http3 = _hlsr2._http
_hlr.KATALOG = Path(_tf2.mkdtemp()) / "hentelogg"
try:
    # Reservekjeden: kalenderfeeden og Highlightly svarer ikke her, så den
    # siste gyldige terminlisten står (kjeden selv testes for seg under).
    ntf_source.hent_kalender = lambda liga, log=None: (_ for _ in ()).throw(ntf_source.SvarerIkke("ingen feed i testen"))
    _hlsr2._http = lambda sti, param: (_ for _ in ()).throw(ntf_source.SvarerIkke("ingen Highlightly i testen"))
    _obd.DATA, _obr.DATA = _sbr, _sbr
    ntf_source.fetch_all = lambda *a, **k: (_ for _ in ()).throw(ntf_source.EsDataError("manglende dato for Bryne - Raufoss (terminliste)"))
    _logg = []
    _rr = _obd.rows_for(log=_logg.append)
    _rs = [m for m in _rr if (m["home"], m["away"]) == ("Ranheim", "Sogndal")]
    sjekk("ligasiden kan ikke leses: byggingen bruker forrige terminliste, Ranheim-Sogndal står med 14:30 (ikke CSV-ens 17:00)",
          len(_rr) == 240 and (_rs[0]["date"], _rs[0]["time"]) == ("2026-11-01", "14:30")
          and any("den siste gyldige terminlisten" in l for l in _logg) and not any("CSV-terminlisten" in l for l in _logg), f"{_rs} {_logg}")
    # Ligasiden svarer, men mangler en kamp: den tas med fra forrige terminliste.
    _ntf_rader = [{**m, "ferdig": m["hg"] is not None} for m in _fr if (m["home"], m["away"]) != ("Ranheim", "Sogndal")]
    ntf_source.fetch_all = lambda *a, **k: [dict(r) for r in _ntf_rader]
    _logg = []
    _rr = _obd.rows_for(log=_logg.append)
    _rs = [m for m in _rr if (m["home"], m["away"]) == ("Ranheim", "Sogndal")]
    sjekk("en kamp som mangler hos ligasiden, tas med fra forrige terminliste (14:30), ikke fra CSV-en",
          len(_rr) == 240 and len(_rs) == 1 and _rs[0]["time"] == "14:30"
          and any("forrige terminliste" in l and "Ranheim-Sogndal" in l for l in _logg), f"{_rs} {[l for l in _logg if 'Ranheim' in l]}")
    # Resultatkjeden: dato og avspark i matches.json kommer fra schedule().
    _sch = _obr.schedule()
    sjekk("resultatkjeden (obos_results.schedule): forrige terminliste, Ranheim-Sogndal 14:30",
          len(_sch) == 240 and _sch[("Ranheim", "Sogndal")]["time"] == "14:30", str(_sch.get(("Ranheim", "Sogndal"))))
    # Uten forrige terminliste (sesongstart): CSV-en, som før.
    (_sbr / "fixtures.json").unlink()
    ntf_source.fetch_all = lambda *a, **k: (_ for _ in ()).throw(ntf_source.EsDataError("lagt om"))
    _logg = []
    _rr = _obd.rows_for(log=_logg.append)
    _rs = [m for m in _rr if (m["home"], m["away"]) == ("Ranheim", "Sogndal")]
    sjekk("uten forrige terminliste (sesongstart): CSV-en, med advarsel",
          (_rs[0]["date"], _rs[0]["time"]) == ("2026-11-01", "17:00") and any("CSV-terminlisten" in l for l in _logg)
          and _obr.schedule()[("Ranheim", "Sogndal")]["time"] == "17:00", f"{_rs} {_logg}")
finally:
    _obd.DATA, _obr.DATA, ntf_source.fetch_all = _ekte_data_obd, _ekte_data_obr, _ekte_fa_r
    ntf_source.hent_kalender, _hlsr2._http = _ekte_kal_r, _ekte_hl_http3
    _hlr.KATALOG = _ekte_hl_kat

print("\n=== Datovakten bruker den AKTIVE sesongen, ikke dataene ===")
from reconcile_ny import rimelige_datoer as _rd
# Runde MAA vaere med: vinduet regnes av medianen i forste og siste runde.
_eks = [{"home": f"L{i}", "away": f"B{i}", "date": f"2026-{3 + i // 8:02d}-{10 + i % 8:02d}",
         "time": "18:00", "hg": 1, "ag": 0, "round": i // 8 + 1}
        for i in range(80)]
_eks.append({"home": "Haugesund", "away": "Sogndal", "date": "2026-09-05",
             "time": "16:00", "hg": 2, "ag": 0, "round": 7})

# 1) Enkeltfeil midt i sesongen: rettes, og det er FAA nok til aa vaere ok
_ny = [dict(r) for r in _eks]
for r in _ny:
    if r["home"] == "Haugesund":
        r["date"] = "2026-01-01"
_l4 = []
_ut4, _utenfor4, _kode4 = _rd(_ny, _eks, "2026", log=_l4.append)
sjekk("01.01.2026 rettes til 05.09",
      next(r for r in _ut4 if r["home"] == "Haugesund")["date"] == "2026-09-05")
sjekk("ingen kamp forsvinner", len(_ut4) == len(_ny))
sjekk("én utenfor, altså ikke kildefeil", len(_utenfor4) == 1, str(_utenfor4))
sjekk("og det logges med sesongen navngitt",
      any("i sesongen 2026" in m and "Beholder 2026-09-05" in m for m in _l4), str(_l4))

# 2) SESONGSKIFTE: fjoraarets data som eksisterende -> full terminliste
# Autoritativ sesong er 2027; eksisterende matches.json er 2026.
_neste = [{**r, "date": r["date"].replace("2026", "2027")} for r in _eks]
_l5 = []
_ut5, _utenfor5, _kode5 = _rd(_neste, _eks, "2027", log=_l5.append)
sjekk("sesongskifte: ingen 2026-dato brukes som tidligere verdi",
      not any(r["date"].startswith("2026") for r in _ut5),
      str([r["date"] for r in _ut5 if r["date"].startswith("2026")][:3]))
sjekk("sesongskifte: full terminliste kommer gjennom", len(_ut5) == len(_neste))
sjekk("og datoene er den NYE sesongens",
      all(r["date"].startswith("2027") for r in _ut5), str([r["date"] for r in _ut5[:2]]))
sjekk("ingen regnes som utenfor, fordi fjoråret ikke er sammenlignbart",
      not _utenfor5, str(_utenfor5))
sjekk("og vakten sier at den står over", any("står over" in m for m in _l5), str(_l5[:1]))

# 3) MASSEFEIL: halve sesongen faar 01.01 midt i sesongen
_masse = [dict(r) for r in _eks]
for r in _masse[: len(_masse) // 2]:
    r["date"] = "2026-01-01"
_ut6, _utenfor6, _kode6 = _rd(_masse, _eks, "2026", log=lambda _s: None)
sjekk("massefeil: alle datoer rettes til de gamle",
      all(not r["date"].endswith("01-01") for r in _ut6),
      str([r["date"] for r in _ut6[:3]]))
sjekk("ingen kamp forsvinner", len(_ut6) == len(_masse))
sjekk("og over en fjerdedel meldes utenfor -> kjøringen skal bli rød",
      len(_utenfor6) > len(_masse) * 0.25, f"{len(_utenfor6)} av {len(_masse)}")

# 3b) VINDUET skal taale EN gal dato i eksisterende data. Med min/maks ville
#     den ene lagrede 01.01 apnet vinduet og slatt vakten av.
_med_feil = [{"home": f"L{i}", "away": f"B{i}", "round": i // 8 + 1,
              "date": f"2026-{3 + i // 8:02d}-{10 + i % 8:02d}", "time": "18:00"}
             for i in range(80)]
_med_feil[0]["date"] = "2026-01-01"          # allerede lagret feil
_ny_feil = [dict(r) for r in _med_feil]
_ny_feil[40]["date"] = "2026-01-01"          # NY feil samme sted i kalenderen
_ut_f, _utenfor_f, _kode_f = _rd(_ny_feil, _med_feil, "2026", log=lambda _s: None)
sjekk("én gal dato i eksisterende data slår ikke av vakten",
      _ut_f[40]["date"] == _med_feil[40]["date"],
      f'{_ut_f[40]["date"]} skulle vært {_med_feil[40]["date"]}')
sjekk("og den nye feilen meldes utenfor", len(_utenfor_f) >= 1, str(_utenfor_f))

print("\n=== Aktiv sesong: hvor kommer den fra ===")
import sesong as _ses
_sd3 = Path(_tf2.mkdtemp())
(_sd3 / "data").mkdir()
(_sd3 / "eliteserien" / "data").mkdir(parents=True)
(_sd3 / "eliteserien" / "data" / "matches.json").write_text(
    _json.dumps([{"date": "2026-04-01", "home": "A", "away": "B"}]), encoding="utf-8")

_lg = []
sjekk("uten register: INGEN gjetting, returnerer None",
      _ses.aktiv_sesong(_sd3, "eliteserien", log=_lg.append) is None)
sjekk("og det sies tydelig at autoriteten mangler",
      any("INGEN SESONGAUTORITET" in m for m in _lg), str(_lg))

(_sd3 / "data" / "sesonger.json").write_text(_json.dumps({
    "version": 2, "ligaer": {"eliteserien": {"aktiv": "2027", "sesonger": {}}}}),
    encoding="utf-8")
_lg = []
sjekk("med register: registeret vinner",
      _ses.aktiv_sesong(_sd3, "eliteserien", log=_lg.append) == "2027")
sjekk("og kilden navngis", any("sesonger.json" in m for m in _lg), str(_lg))

# 4) Kamp uten tidligere verdi utelates aldri
_ukjent = _ny + [{"home": "Helt", "away": "Ny", "date": "2026-01-02",
                  "time": "18:00", "round": 5}]
_l7 = []
_ut7, _, _ = _rd(_ukjent, _eks, "2026", log=_l7.append)
sjekk("kamp uten tidligere dato utelates ikke", len(_ut7) == len(_ukjent))
sjekk("den slipper gjennom med sin egen dato",
      next(r for r in _ut7 if r["home"] == "Helt")["date"] == "2026-01-02")
sjekk("og det logges", any("slipper gjennom" in m for m in _l7), str(_l7))

# 5) USPILT kamp (9.10.2026): ligasiden viste Rosenborg-Start (runde 26,
#    7.11.) som 7.1. Med hele terminlisten som forrige verdi rettes den, og
#    vinduet går til siste runde i terminlisten, ikke siste spilte.
_terminliste = [{"home": f"T{i}", "away": f"U{i}", "round": i // 8 + 1,
                 "date": (_dt(2026, 3, 14) + _td(days=7 * (i // 8))).strftime("%Y-%m-%d"),
                 "time": "18:00", "hg": (1 if i < 21 * 8 else None), "ag": (0 if i < 21 * 8 else None)}
                for i in range(240)]
_r26 = next(r for r in _terminliste if r["round"] == 26)
_kilde = [dict(r) for r in _terminliste]
_feil = next(r for r in _kilde if r["home"] == _r26["home"])
_feil["date"] = "2026-01-07"
_l10 = []
_ut10, _utenfor10, _ = _rd(_kilde, _terminliste, "2026", log=_l10.append)
sjekk("uspilt kamp i runde 26 med 7.1. rettes til terminlistens dato",
      next(r for r in _ut10 if r["home"] == _r26["home"])["date"] == _r26["date"],
      f'{next(r for r in _ut10 if r["home"] == _r26["home"])} {_l10}')
sjekk("og bare den ene meldes utenfor -- rundene etter siste spilte er innenfor vinduet",
      _utenfor10 == [f'{_r26["home"]}-{_r26["away"]} (2026-01-07)'], str(_utenfor10))
_bare_spilte = [r for r in _terminliste if r["hg"] is not None]
_l10b = []
_, _utenfor10b, _ = _rd(_kilde, _bare_spilte, "2026", log=_l10b.append)
sjekk("motprøve: med bare spilte kamper som forrige verdi slipper 7.1. gjennom (feilen 9.10.)",
      any("Ingen tidligere dato" in m and "2026-01-07" in m for m in _l10b)
      and len(_utenfor10b) > 1, f"{len(_utenfor10b)} {_l10b[:2]}")

# 6) Forrige verdi er selv utenfor vinduet: den holdes ikke fast
_lagret_feil = [dict(r) for r in _terminliste]
next(r for r in _lagret_feil if r["home"] == _r26["home"])["date"] = "2026-01-07"
_l11 = []
_ut11, _, _ = _rd(_kilde, _lagret_feil, "2026", log=_l11.append)
sjekk("en lagret feildato brukes ikke som forrige verdi",
      any("er også utenfor" in m for m in _l11), str(_l11))
sjekk("og kampen utelates ikke", len(_ut11) == len(_kilde))

_ud = (ROT / "scripts" / "update_data.py").read_text("utf-8")
sjekk("Eliteserien (update_data.py): datovakten får hele terminlisten som forrige verdi",
      "rimelige_datoer(merged, _forrige_liste or tidligere," in _ud
      and "_forrige_liste = leaguedata.forrige_terminliste(" in _ud)

print("\n=== Ingen enkeltkilde flytter en uspilt kamp (bekreft_flytting, 10.10.2026) ===")
# eliteserien.no viste Rosenborg-Start (runde 26, 7.11. 18:00) som 18.11. den
# 10.10., innenfor sesongvinduet. Kampen flyttes bare naar ESPN viser samme
# nye dato og tid; svarer ikke ESPN, avgjoer kalenderfeeden.
from reconcile_ny import bekreft_flytting as _bf
_forr = [{"home": "Rosenborg", "away": "Start", "round": 26, "date": "2026-11-07", "time": "18:00", "hg": None, "ag": None},
         {"home": "Molde", "away": "Brann", "round": 26, "date": "2026-11-08", "time": "17:00", "hg": None, "ag": None},
         {"home": "Brann", "away": "Viking", "round": 23, "date": "2026-10-09", "time": "19:00", "hg": 0, "ag": 2}]
_flyttet_kilde = [dict(r) for r in _forr]
_flyttet_kilde[0]["date"] = "2026-11-18"          # det ligasiden viste 10.10.
_RS = ("Rosenborg", "Start")


def _kilde(svar, kall, navn):
    def hent():
        kall.append(navn)
        if isinstance(svar, Exception):
            raise svar
        return svar
    return hent


def _kjor_bf(kilde, espn, kalender):
    kall, logg = [], []
    ut, utfall = _bf(kilde, _forr, _kilde(espn, kall, "espn"), _kilde(kalender, kall, "kalender"), log=logg.append)
    rs = next(r for r in ut if (r["home"], r["away"]) == _RS)
    return rs, utfall, kall, logg


_espn_gml = {_RS: ("2026-11-07", "18:00")}
_espn_ny = {_RS: ("2026-11-18", "18:00")}

# 0) Ingen flytting: ingen kilde spørres
_rs, _utf, _kall, _ = _kjor_bf([dict(r) for r in _forr], _espn_ny, _espn_ny)
sjekk("ingen flytting: verken ESPN eller kalenderfeeden spørres, ingenting endres",
      _kall == [] and _utf == [] and _rs["date"] == "2026-11-07", f"{_kall} {_utf}")

# 1) Ligasiden flytter alene: ESPN viser den gamle datoen -> beholdes
_rs, _utf, _kall, _logg = _kjor_bf(_flyttet_kilde, _espn_gml, _espn_ny)
sjekk("ligasiden flytter alene (ESPN viser 7.11.): kampen beholder 7.11. 18:00",
      (_rs["date"], _rs["time"]) == ("2026-11-07", "18:00") and _utf == [("Rosenborg-Start", "beholdt", "ESPN")], f"{_rs} {_utf}")
sjekk("og det står ADVARSEL med hva ligasiden og ESPN viser, og kalenderfeeden spørres ikke",
      any("ADVARSEL" in m and "ligasiden viser 18.11. 18:00" in m and "ESPN viser 7.11. 18:00" in m
          and "beholder 7.11. 18:00" in m for m in _logg) and _kall == ["espn"], f"{_logg} {_kall}")

# 2) ESPN er enig -> flyttes
_rs, _utf, _kall, _logg = _kjor_bf(_flyttet_kilde, _espn_ny, _espn_gml)
sjekk("ESPN er enig (18.11. 18:00): kampen flyttes, og kalenderfeeden spørres ikke",
      _rs["date"] == "2026-11-18" and _utf == [("Rosenborg-Start", "flyttet", "ESPN")] and _kall == ["espn"], f"{_rs} {_utf} {_kall}")
sjekk("og det står at flyttingen er bekreftet av ESPN",
      any("flyttet fra 7.11. 18:00 til 18.11. 18:00, bekreftet av ESPN" in m for m in _logg), str(_logg))

# 3) ESPN svarer ikke -> kalenderfeeden avgjør, begge veier
_rs, _utf, _kall, _logg = _kjor_bf(_flyttet_kilde, ConnectionError("timeout"), _espn_ny)
sjekk("ESPN svarer ikke, kalenderfeeden viser 18.11.: kampen flyttes, avgjort av kalenderfeeden",
      _rs["date"] == "2026-11-18" and _utf == [("Rosenborg-Start", "flyttet", "kalenderfeeden")]
      and _kall == ["espn", "kalender"] and any("ESPN svarte ikke" in m for m in _logg), f"{_rs} {_utf} {_kall}")
_rs, _utf, _kall, _logg = _kjor_bf(_flyttet_kilde, ConnectionError("timeout"), _espn_gml)
sjekk("ESPN svarer ikke, kalenderfeeden viser 7.11.: kampen beholder 7.11., med ADVARSEL",
      _rs["date"] == "2026-11-07" and _utf == [("Rosenborg-Start", "beholdt", "kalenderfeeden")]
      and any("ADVARSEL" in m and "kalenderfeeden viser 7.11. 18:00" in m for m in _logg), f"{_rs} {_logg}")

# 4) Kildene er uenige -> beholdes med ADVARSEL
_rs, _utf, _kall, _logg = _kjor_bf(_flyttet_kilde, {_RS: ("2026-11-08", "18:00")}, _espn_ny)
sjekk("kildene er uenige (ligasiden 18.11., ESPN 8.11.): kampen beholder 7.11., med ADVARSEL",
      _rs["date"] == "2026-11-07" and _utf == [("Rosenborg-Start", "beholdt", "ESPN")]
      and any("ADVARSEL" in m and "ESPN viser 8.11. 18:00" in m for m in _logg), f"{_rs} {_logg}")
_rs, _utf, _kall, _logg = _kjor_bf(_flyttet_kilde, {_RS: ("2026-11-18", "16:00")}, _espn_ny)
sjekk("samme nye dato, men annen tid hos ESPN: uenige, kampen beholder 7.11. 18:00",
      (_rs["date"], _rs["time"]) == ("2026-11-07", "18:00"), str(_rs))
_rs, _utf, _kall, _logg = _kjor_bf(_flyttet_kilde, {}, _espn_ny)
sjekk("ESPN mangler kampen: beholdes, og det står at ESPN ikke har kampen",
      _rs["date"] == "2026-11-07" and any("ESPN har ikke kampen" in m for m in _logg), str(_logg))
_rs, _utf, _kall, _logg = _kjor_bf(_flyttet_kilde, ConnectionError("x"), OSError("y"))
sjekk("verken ESPN eller kalenderfeeden svarer: beholdes, med ADVARSEL",
      _rs["date"] == "2026-11-07" and _utf == [("Rosenborg-Start", "beholdt", None)]
      and any("verken ESPN eller kalenderfeeden svarte" in m for m in _logg), str(_logg))

# 5) Det regelen ikke skal røre
_spilt_kilde = [dict(r) for r in _forr]
_spilt_kilde[2]["date"] = "2026-01-09"           # spilt kamp: frys_spilte sin sak
_ut5, _utf5 = _bf(_spilt_kilde, _forr, _kilde({}, [], "espn"), _kilde({}, [], "kalender"))
sjekk("en spilt kamp er ikke en flytting her (frys_spilte tar den)", _utf5 == [] and _ut5 == _spilt_kilde)
_ny_kamp = [dict(r) for r in _forr] + [{"home": "Helt", "away": "Ny", "round": 27, "date": "2026-11-21",
                                         "time": "17:00", "hg": None, "ag": None}]
_ut6, _utf6 = _bf(_ny_kamp, _forr, _kilde({}, [], "espn"), _kilde({}, [], "kalender"))
sjekk("en kamp uten forrige verdi slipper gjennom uten oppslag", _utf6 == [] and _ut6 == _ny_kamp)
_neste_aar = [dict(r) for r in _forr]
_neste_aar[0]["date"] = "2027-04-10"
_ut7, _utf7 = _bf(_neste_aar, _forr, _kilde({}, [], "espn"), _kilde({}, [], "kalender"))
sjekk("en rad fra neste sesong for samme lagpar er ikke en flytting", _utf7 == [] and _ut7 == _neste_aar)

_ud = (ROT / "scripts" / "update_data.py").read_text("utf-8")
sjekk("Eliteserien (update_data.py): bekreft_datoer kjøres etter datovakten, med ESPN-sesongkallet først og kalenderfeeden som reserve",
      'merged, _forrige_liste, [("ESPN", _espn_fasit), ("kalenderfeeden", _kalender_fasit)], log=log,' in _ud
      and "espn_source.fetch_season(_aktiv" in _ud and "ntf_source.parse_kalender(ntf_source.hent_kalender(LIGA" in _ud
      and _ud.index("rimelige_datoer(merged, _forrige_liste") < _ud.index("merged, _flytting = bekreft_datoer("))

print("\n=== Testsidens prekick-kontroll bruker frysingens avsparkregel (10.10.2026) ===")
# Rosenborg-Sandefjord pagikk da Glimt-Kristiansund kom inn: modellen ble ny,
# raden for kampen som pagikk ble staaende fra avspark (frysregelen), og
# kontroll W i kontroll_paneler.py var roed hvert tiende minutt.
import json as _json_pk, subprocess as _sp_pk, tempfile as _tf_pk
from datetime import datetime as _dt_pk, timezone as _tz_pk
sys.path.insert(0, str(ROT / "elo-test" / "scripts"))
import paneler as _pn_t
_fx_pk = [{"round": 23, "matches": [
    {"home": "Rosenborg", "away": "Sandefjord", "date": "2026-10-10", "time": "18:00", "played": False},
    {"home": "Lillestrøm", "away": "Molde", "date": "2026-10-11", "time": "19:15", "played": False},
    {"home": "Bodø/Glimt", "away": "Kristiansund", "date": "2026-10-10", "time": "16:00", "played": True}]},
    {"round": 26, "matches": [{"home": "Rosenborg", "away": "Start", "date": "2026-11-07", "time": "18:00", "played": False}]}]
with _tf_pk.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as _fh:
    _json_pk.dump(_fx_pk, _fh, ensure_ascii=False); _fx_sti = _fh.name
_avsp_pk, _naa_pk = _pn_t.avspark_fra_terminliste(_fx_sti)
_ms = lambda *a: int(_dt_pk(*a, tzinfo=_tz_pk.utc).timestamp() * 1000)
sjekk("avsparket regnes av prekick_frys.js: 10.10. 18:00 norsk tid = 16:00 UTC, 7.11. 18:00 = 17:00 UTC (vintertid)",
      _avsp_pk["Rosenborg|Sandefjord"] == _ms(2026, 10, 10, 16, 0) and _avsp_pk["Rosenborg|Start"] == _ms(2026, 11, 7, 17, 0),
      str(_avsp_pk))
sjekk("og klokka kommer fra samme node-kall", abs(_naa_pk - _dt_pk.now(_tz_pk.utc).timestamp() * 1000) < 60000)
_rader_pk = {
    "2026|Rosenborg|Sandefjord": {"home": "Rosenborg", "away": "Sandefjord", "H": 0.5},   # pågår, uten resultat
    "2026|Lillestrøm|Molde": {"home": "Lillestrøm", "away": "Molde", "H": 0.4},          # før avspark
    "2026|Bodø/Glimt|Kristiansund": {"home": "Bodø/Glimt", "away": "Kristiansund", "H": 0.7, "frosset": True}}
_naa_kamp = _ms(2026, 10, 10, 16, 42)          # 18:42 norsk tid, mens Rosenborg-Sandefjord pågår
_sml, _etter, _fros = _pn_t.prekick_til_kontroll(_rader_pk, _avsp_pk, _naa_kamp)
sjekk("en rad etter avspark uten resultat hoppes over", _etter == ["2026|Rosenborg|Sandefjord"], str(_etter))
sjekk("en rad før avspark sammenlignes som før", _sml == ["2026|Lillestrøm|Molde"], str(_sml))
sjekk("en frosset rad sammenlignes ikke her, som før (den har sin egen kontroll)", _fros == ["2026|Bodø/Glimt|Kristiansund"], str(_fros))
_sml2, _etter2, _ = _pn_t.prekick_til_kontroll(_rader_pk, _avsp_pk, _ms(2026, 10, 10, 15, 59))
sjekk("ett minutt før avspark sammenlignes raden", "2026|Rosenborg|Sandefjord" in _sml2 and not _etter2, f"{_sml2} {_etter2}")
_sml3, _etter3, _ = _pn_t.prekick_til_kontroll(_rader_pk, _avsp_pk, _ms(2026, 10, 10, 16, 0))
sjekk("i avsparksminuttet hoppes den over (>=, som i prekick_frys.js)", _etter3 == ["2026|Rosenborg|Sandefjord"], str(_etter3))
# Samme deling som oppdaterPrekick() i JS: radene den skriver = de som sammenlignes.
_js_pk = ("const f=require(process.argv[1]);const d=JSON.parse(process.argv[2]);"
          "const g={matches:JSON.parse(JSON.stringify(d.rader))};"
          "const pre=Object.fromEntries(Object.entries(d.rader).map(([k,v])=>[k,{...v}]));"
          "f.oppdaterPrekick(g,pre,[],d.avspark,d.naa,'NY','alle');"
          "process.stdout.write(JSON.stringify(Object.keys(g.matches).filter(k=>g.matches[k].stamp==='NY')))")
_skrevet = _json_pk.loads(_sp_pk.run(["node", "-e", _js_pk, str(ROT / "scripts" / "prekick_frys.js"),
                                      _json_pk.dumps({"rader": _rader_pk, "avspark": _avsp_pk, "naa": _naa_kamp})],
                                     capture_output=True, text=True, check=True).stdout)
sjekk("samme deling som oppdaterPrekick(): radene frysingen skriver, er nøyaktig de som sammenlignes",
      sorted(_skrevet) == sorted(_sml), f"JS {_skrevet}, kontrollen {_sml}")
_kp_src = (ROT / "elo-test" / "scripts" / "kontroll_paneler.py").read_text("utf-8")
sjekk("kontroll_paneler.py deler prekick-radene med paneler.prekick_til_kontroll og avspark_fra_terminliste",
      "_pn_w.prekick_til_kontroll(" in _kp_src and "_pn_w.avspark_fra_terminliste(" in _kp_src)

print("\n=== Uten sesongautoritet står vakten over ===")
_l8 = []
_ut8, _utenfor8, _kode8 = _rd(_ny, _eks, None, log=_l8.append)
sjekk("ingen sesong: dataene går uendret gjennom", _ut8 == _ny)
sjekk("og feilkoden sier at autoriteten mangler", _kode8 == "ingen_autoritet")
sjekk("og det logges at den ikke gjetter",
      any("uten å gjette" in m for m in _l8), str(_l8))

print("\n=== Sesongskiftet ikke kjort: vakten retter INGENTING ===")
# Registeret sier 2026, terminlisten er 2027. Lagparene gaar igjen, saa uten
# denne sperren ville vakten funnet en "tidligere verdi" for hver kamp og
# skrevet hele 2027-sesongen tilbake til 2026-datoer.
_ikke_byttet = [{**r, "date": r["date"].replace("2026", "2027")} for r in _eks]
_l9 = []
_ut9, _utenfor9, _kode9 = _rd(_ikke_byttet, _eks, "2026", log=_l9.append)
sjekk("datoene beholdes som 2027",
      all(r["date"].startswith("2027") for r in _ut9),
      str([r["date"] for r in _ut9[:2]]))
sjekk("ingenting rettes", _ut9 == _ikke_byttet)
sjekk("feilkoden er sesongskifte_mangler", _kode9 == "sesongskifte_mangler")
sjekk("og loggen sier at sesongskiftet ikke er kjørt",
      any("Sesongskiftet er ikke kjørt" in m for m in _l9), str(_l9[:1]))

print("\n=== sesong.py init: bootstrap ===")
_sd4 = Path(_tf2.mkdtemp())
(_sd4 / "data").mkdir()
for _l in ("eliteserien", "obos"):
    (_sd4 / _l / "data").mkdir(parents=True)
    (_sd4 / _l / "data" / "matches.json").write_text(
        _json.dumps([{"date": "2026-04-01", "home": "A", "away": "B"}]), encoding="utf-8")

sjekk("tom tilstand: ingen autoritet", _ses.aktiv_sesong(_sd4, "obos") is None)
_li = []
sjekk("init setter 2026 for eliteserien",
      _ses.init(_sd4, "eliteserien", "2026", log=_li.append) == 0)
sjekk("init setter 2026 for obos",
      _ses.init(_sd4, "obos", "2026", log=_li.append) == 0)
sjekk("og kampdataene ble brukt som KONTROLL",
      any("kontroll: matches.json" in m for m in _li), str(_li))
sjekk("etterpå leses registeret, uten reserve",
      (_ses.aktiv_sesong(_sd4, "eliteserien"), _ses.aktiv_sesong(_sd4, "obos"))
      == ("2026", "2026"))

_li = []
sjekk("ny init NEKTES når aktiv finnes",
      _ses.init(_sd4, "obos", "2027", log=_li.append) == 1)
sjekk("og den sier at bytt er veien",
      any("går\ngjennom 'bytt'" in m or "gjennom 'bytt'" in m for m in _li), str(_li))
sjekk("aktiv er uendret", _ses.aktiv_sesong(_sd4, "obos") == "2026")

_li = []
sjekk("feil årstall mot kampdata avvises",
      _ses.init(_sd4, "eliteserien", "2030", log=_li.append) != 0)
sjekk("tullball som årstall avvises", _ses.init(_sd4, "obos", "i fjor", log=lambda _s: None) == 2)

# bytt() er fortsatt eneste normale vei videre
_d4 = _ses.les(_sd4)
_d4["ligaer"]["obos"]["sesonger"]["2027"] = {"status": "klar", "lag": []}
_ses.skriv(_sd4, _d4)
_gjor, _neste, _hvorfor = _ses.skal_bytte(_ses.les(_sd4)["ligaer"]["obos"], date(2026, 12, 31))
sjekk("bytt nekter 31. desember", not _gjor, _hvorfor)
_gjor, _neste, _hvorfor = _ses.skal_bytte(_ses.les(_sd4)["ligaer"]["obos"], date(2027, 1, 1))
sjekk("bytt godtar 1. januar når sesongen er klar", _gjor, _hvorfor)

print("\n=== bytt --utfor i det daglige vedlikeholdet ===")
# data/sesonger.json er autoriteten datovakten leser, saa sesongskiftet kan
# ikke ligge som kode ingen kjorer. Steget er en no-op 364 dager i aaret.
_sd5 = Path(_tf2.mkdtemp())
(_sd5 / "data").mkdir()
for _l in ("eliteserien", "obos"):
    (_sd5 / _l / "data").mkdir(parents=True)
    (_sd5 / _l / "data" / "matches.json").write_text(
        _json.dumps([{"date": "2026-04-01", "home": "A", "away": "B"}]), encoding="utf-8")
    (_sd5 / _l / "data" / "fixtures.json").write_text("[]", encoding="utf-8")
    _ses.init(_sd5, _l, "2026", log=lambda _s: None)


def _reg():
    return _ses.les(_sd5)["ligaer"]


def _lag_2027(liga, status="klar"):
    d = _ses.les(_sd5)
    d["ligaer"][liga]["sesonger"]["2027"] = {"status": status, "lag": []}
    _ses.skriv(_sd5, d)


# 1) Vanlig dag i 2026: ingenting skjer
_for = _json.dumps(_reg(), sort_keys=True)
_lg5 = []
sjekk("vanlig dag: exitkode 0",
      _ses.bytt(_sd5, date(2026, 9, 25), utfor=True, log=_lg5.append, ligaer=["eliteserien"]) == 0)
sjekk("og registeret er uendret", _json.dumps(_reg(), sort_keys=True) == _for)
sjekk("og begrunnelsen står i loggen",
      any("aktiv ut kalenderåret" in m for m in _lg5), str(_lg5))

# 2) 1. januar med 2027 oppdaget OG validert -> bytter
_lag_2027("eliteserien", "klar")
_frys_kunstig(_sd5, "eliteserien", "2026")
_lg5 = []
_ses.bytt(_sd5, date(2027, 1, 1), utfor=True, log=_lg5.append, ligaer=["eliteserien"])
sjekk("1. januar med validert 2027: aktiv blir 2027",
      _reg()["eliteserien"]["aktiv"] == "2027")
sjekk("og 2026 merkes frosset",
      _reg()["eliteserien"]["sesonger"]["2026"]["status"] == "frosset")

# 3) LIGAENE ER UAVHENGIGE: OBOS er urort
sjekk("OBOS står fortsatt på 2026", _reg()["obos"]["aktiv"] == "2026")
sjekk("og har ingen 2027 registrert", "2027" not in _reg()["obos"]["sesonger"])

# 4) 1. januar UTEN validert 2027 -> staar, ALARM, og exit 1
_lag_2027("obos", "oppdaget")        # oppdaget, men ikke validert
_lg5 = []
_kode5 = _ses.bytt(_sd5, date(2027, 1, 1), utfor=True, log=_lg5.append, ligaer=["obos"])
sjekk("1. januar uten validert 2027: OBOS blir stående på 2026",
      _reg()["obos"]["aktiv"] == "2026")
sjekk("og det varsles tydelig",
      any("VENTER" in m for m in _lg5), str(_lg5))
# En passert byttedato med en sesong som ikke er klar er IKKE en vanlig
# no-op. Da skal kjoringen ende rodt, ikke stole paa at datovakten kanskje
# oppdager det senere.
sjekk("og exitkoden er 1, så kjøringen ender rødt", _kode5 == 1)
sjekk("med ALARM i loggen", any("ALARM" in m for m in _lg5), str(_lg5))

# Til sammenligning: samme tilstand FØR byttedatoen er en ren no-op
sjekk("men samme tilstand i desember gir exit 0",
      _ses.bytt(_sd5, date(2026, 12, 31), utfor=True, log=lambda _s: None,
                ligaer=["obos"]) == 0)

# 4b) Eliteserien mangler 2027 mens OBOS er klar
_d5 = _ses.les(_sd5)
_d5["ligaer"]["eliteserien"]["aktiv"] = "2026"
_d5["ligaer"]["eliteserien"]["sesonger"].pop("2027", None)
_ses.skriv(_sd5, _d5)
_lag_2027("obos", "klar")
_lgE = []
_kodeE = _ses.bytt(_sd5, date(2027, 1, 1), utfor=True, log=_lgE.append,
                   ligaer=["eliteserien"])
sjekk("Eliteserien mangler 2027: står, og varsler med exit 1",
      _kodeE == 1 and _reg()["eliteserien"]["aktiv"] == "2026",
      f"kode={_kodeE} aktiv={_reg()['eliteserien']['aktiv']}")
_frys_kunstig(_sd5, "obos", "2026")
_kodeO = _ses.bytt(_sd5, date(2027, 1, 1), utfor=True, log=lambda _s: None,
                   ligaer=["obos"])
sjekk("mens OBOS bytter uavhengig, med exit 0",
      _kodeO == 0 and _reg()["obos"]["aktiv"] == "2027",
      f"kode={_kodeO} aktiv={_reg()['obos']['aktiv']}")
sjekk("og Eliteserien er fortsatt urørt", _reg()["eliteserien"]["aktiv"] == "2026")



print("\n=== Bekreftet avvik overlever midnatt ===")
# Forlopet: avviket bekreftes klokka 23. Forste kjoring etter midnatt maa
# ikke nedgradere det bare fordi datoen har skiftet.
_sd2 = Path(_tf2.mkdtemp())
(_sd2 / "data").mkdir()
_dr.ROT = _sd2
_dr.oppsett.__globals__["LIGAER"]["test"] = {"data": "data", "visningsnavn": "Test"}
(_sd2 / "data" / "audit_fixtures.json").write_text(_json.dumps({
    "checked_date": "2026-10-02", "errors": 1,
    "bekreftet": {"Haugesund-Sogndal": [21, "2026-01-01", "16:00", 2, 0]},
}), encoding="utf-8")
_i_morgen = _dt(2026, 10, 3, 6, 0, tzinfo=_tz.utc)
_b = _dr.les_bekreftet("test", _i_morgen)
sjekk("bekreftelsen leses også dagen etter", "Haugesund-Sogndal" in _b, str(_b))
_f8, _a8 = _dr.revider(_v_feil, _nff_rett, ferskt=False, bekreftet=_b)
sjekk("og avviket er fortsatt kritisk etter midnatt", len(_f8) == 1, f"{_f8} {_a8}")
_dr.ROT = _ekte_rot2
_dr.oppsett.__globals__["LIGAER"].pop("test", None)

print("\n=== Hentelogg: historikk, ikke bare siste utfall ===")
import hentelogg as _hl
from datetime import timedelta as _td3

_hl_dir = Path(_tf2.mkdtemp())
_ekte_kat = _hl.KATALOG
_hl.KATALOG = _hl_dir
_n = _dt(2026, 10, 2, 12, 0, tzinfo=_tz.utc)

_hl.logg("obos", "ntf-resultater", "ok", kamper=184, naa=_n)
sjekk("en linje skrives", len(_hl.les(naa=_n + _td3(minutes=1))) == 1)
_r = _hl.les(naa=_n + _td3(minutes=1))[0]
sjekk("med liga, kilde, utfall og antall",
      (_r["liga"], _r["kilde"], _r["utfall"], _r["kamper"])
      == ("obos", "ntf-resultater", "ok", 184), str(_r))

# Tre feil paa rad -> kilden regnes som ute
for _i in range(1, 4):
    _hl.logg("obos", "nff", "feil", melding="403", naa=_n + _td3(hours=_i))
_etter = _n + _td3(hours=4)
sjekk("tre feil på rad telles", _hl.feil_paa_rad("obos", "nff", naa=_etter) == 3)
sjekk("og kilden regnes som ute",
      ("obos", "nff", 3) in _hl.ute(naa=_etter), str(_hl.ute(naa=_etter)))

# To feil er ikke nok -- et blaff skal ikke gi alarm
_hl2 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl2
for _i in range(2):
    _hl.logg("obos", "nff", "feil", naa=_n + _td3(hours=_i))
sjekk("to feil gir ingen alarm", not _hl.ute(naa=_n + _td3(hours=3)))

# En vellykket henting nullstiller
_hl.logg("obos", "nff", "ok", kamper=240, naa=_n + _td3(hours=3))
sjekk("en vellykket henting nullstiller telleren",
      _hl.feil_paa_rad("obos", "nff", naa=_n + _td3(hours=4)) == 0)
sjekk("og alarmen forsvinner", not _hl.ute(naa=_n + _td3(hours=4)))

# cache-treff skal ikke telle som verken ok eller feil
_hl3 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl3
for _i in range(1, 4):
    _hl.logg("obos", "nff", "feil", naa=_n + _td3(hours=_i))
_hl.logg("obos", "nff", "cache", kamper=240, naa=_n + _td3(hours=4))
sjekk("et cache-treff nullstiller IKKE feilrekken",
      _hl.feil_paa_rad("obos", "nff", naa=_n + _td3(hours=5)) == 3)

# Filnavnet skilles per workflow, saa to workflows ikke skriver samme fil
import os as _os3
_hl4 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl4
with _vern.miljo(GITHUB_WORKFLOW="Oppdater kampdata"):
    _hl.logg("obos", "nff", "ok", naa=_n)
with _vern.miljo(GITHUB_WORKFLOW="OBOS: hent resultater"):
    _hl.logg("obos", "nff", "ok", naa=_n)
_filer = sorted(x.name for x in _hl4.rglob("*.jsonl"))
sjekk("to workflows skriver til ULIKE filer", len(_filer) == 2, str(_filer))
sjekk("og begge linjene finnes", len(_hl.les(naa=_n + _td3(minutes=1))) == 2)

# EN FIL PER KJORING, ikke per workflow: to kjoringer av SAMME workflow fra
# ulike checkouts ville ellers lagt til linjer i samme fil, og en rebase
# taper da linjer -- samme feil som OddsPapi-telleren hadde.
_hl5 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl5
with _vern.miljo(GITHUB_WORKFLOW="Oppdater kampdata"):
    for _rid in ("111", "222"):
        with _vern.miljo(GITHUB_RUN_ID=_rid):
            _hl.logg("obos", "nff", "ok", naa=_n)
    with _vern.miljo(GITHUB_RUN_ID="222", GITHUB_RUN_ATTEMPT="2"):
        _hl.logg("obos", "nff", "ok", naa=_n)
_filer5 = sorted(x.name for x in _hl5.rglob("*.jsonl"))
sjekk("to kjøringer av samme workflow skriver til ulike filer",
      len(_filer5) == 3, str(_filer5))
sjekk("og forsøk 2 skrives for seg",
      any(x.endswith("222-2.jsonl") for x in _filer5), str(_filer5))

# En logg som feiler skal aldri velte en kjoring
_hl.KATALOG = Path("/dev/null/finnes-ikke")
_hl.logg("obos", "nff", "ok")
sjekk("en logg som ikke kan skrives kaster ikke", True)
_hl.KATALOG = _ekte_kat

print("\n=== Cache skjuler ikke en kilde som er nede ===")
# Fem mislykkede daglige fotball.no-hentinger MED fungerende cache. Kjeden
# skal gaa videre paa cachen hver dag -- men historikken skal vise fem feil
# paa rad, ellers er loggen verdilos.
import nff_source as _nffs
_hl6 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl6
_nff_ekte_kat, _nff_ekte_hent = _nffs.CACHE_KATALOG, _nffs.hent
_nffs.CACHE_KATALOG = Path(_tf2.mkdtemp())
_nffs.CACHE_KATALOG.mkdir(parents=True, exist_ok=True)
_cache_rader = [{"home": f"L{_i}", "away": f"B{_i}", "date": "2026-09-01",
                 "round": 1, "hg": 1, "ag": 0} for _i in range(240)]
(_nffs.CACHE_KATALOG / "obos.json").write_text(_json.dumps({
    "rader": _cache_rader, "hentet": "2026-09-19T10:00:00+00:00",
    "hentet_av": "gammel", "forsokt": "2026-09-19T10:00:00+00:00"}),
    encoding="utf-8")


def _nede(url, **kw):
    raise OSError("timed out")


_nffs.hent = _nede
_start6 = _dt(2026, 9, 20, 10, 0, tzinfo=_tz.utc)
_fra_cache = []
for _dag in range(5):
    with _vern.miljo(GITHUB_RUN_ID=f"nede{_dag}"):
        _fra_cache.append(len(_nffs.fetch_all("obos", log=lambda _s: None,
                                              naa=_start6 + _td3(days=_dag))))
_etter6 = _start6 + _td3(days=5)
sjekk("cachen virker -- kjeden fikk 240 kamper hver dag",
      _fra_cache == [240] * 5, str(_fra_cache))
sjekk("men historikken viser fem feil på rad",
      _hl.feil_paa_rad("obos", "nff", naa=_etter6) == 5,
      str([r["utfall"] for r in _hl.les(naa=_etter6)]))
sjekk("og kilden regnes som ute", ("obos", "nff", 5) in _hl.ute(naa=_etter6),
      str(_hl.ute(naa=_etter6)))
sjekk("fem kjøringer ga fem filer",
      len(list(_hl6.rglob("*.jsonl"))) == 5)
_nffs.CACHE_KATALOG, _nffs.hent = _nff_ekte_kat, _nff_ekte_hent

print("\n=== Tre feil mot ligasiden gjør kjøringen rød, én henting gjør den grønn ===")
# Mot den EKTE ntf_source og den ekte lagrede obos-ligaen.no-siden.
import ntf_source as _ntfs
_hl7 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl7
_ntf_ekte_hent = _ntfs.hent
_ntfs.hent = _nede
_start7 = _dt(2026, 9, 22, 10, 0, tzinfo=_tz.utc)
for _dag in range(3):
    with _vern.miljo(GITHUB_RUN_ID=f"ligaside{_dag}"):
        try:
            _ntfs.fetch_all("obos", log=lambda _s: None,
                            naa=_start7 + _td3(days=_dag))
        except Exception:
            pass
_etter7 = _start7 + _td3(days=3)
sjekk("tre feil mot obos-ligaen.no gir exit 1",
      _hl.sjekk(naa=_etter7) == 1)
_nede7 = _hl.ute(naa=_etter7)
sjekk("og kildenavnet står i meldingen",
      _nede7 and _nede7[0][1] == "ntf-resultater", str(_nede7))

_sider7 = {n: (Path("tests/kilder/testdata") /
               f"ntf_obos_{n}_2026-09-25.html").read_text(encoding="utf-8")
           for n in ("resultater", "terminliste")}
_ntfs.hent = lambda url, **kw: _sider7[
    "resultater" if url.endswith("resultater") else "terminliste"]
with _vern.miljo(GITHUB_RUN_ID="oppe-igjen"):
    _ok7 = _ntfs.fetch_all("obos", log=lambda _s: None, naa=_etter7)
sjekk("en vellykket henting gir hele terminlisten", len(_ok7) == 240,
      str(len(_ok7)))
sjekk("og kjøringen blir grønn igjen",
      _hl.sjekk(naa=_etter7 + _td3(hours=1)) == 0)
_ntfs.hent = _ntf_ekte_hent

print("\n=== OddsPapi: 429 er ventebeskjed, ikke en kilde som er nede ===")
import urllib.error as _ue
import oddspapi as _op
_hl8 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl8
_op_ekte_aapne = _op.urllib.request.urlopen
_op_ekte_budsjett = _op.budsjett_stopp
_op.budsjett_stopp = lambda *a, **k: (False, "")


def _svar_429(*a, **k):
    raise _ue.HTTPError("u", 429, "rate", None, None)


_op.urllib.request.urlopen = _svar_429
# call_retry folger serverens ventetid. Her er poenget hva som LOGGES, ikke
# at testen faktisk venter.
import time as _time8
_sov_ekte = _time8.sleep
_time8.sleep = lambda _s: None
_op.call_retry("/v4/historical-odds", {}, "n", forsok=3)
_time8.sleep = _sov_ekte
_r8 = [r for r in _hl.les() if r["kilde"] == "oddspapi-historical-odds"]
sjekk("tre 429 logges som «hoppet», ikke feil",
      [r["utfall"] for r in _r8[:3]] == ["hoppet"] * 3,
      str([r["utfall"] for r in _r8]))
sjekk("men oppbrukte forsøk gir én ekte feil",
      _r8[-1]["utfall"] == "feil", str(_r8[-1]))
sjekk("tre 429 alene gjør IKKE kjøringen rød",
      _hl.feil_paa_rad("alle", "oddspapi-historical-odds") == 1,
      str(_hl.feil_paa_rad("alle", "oddspapi-historical-odds")))

# En annen HTTP-feil er en ekte feil fra forste forsok
_hl9 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl9


def _svar_500(*a, **k):
    raise _ue.HTTPError("u", 500, "nede", None, None)


_op.urllib.request.urlopen = _svar_500
for _i in range(3):
    _op.call("/v4/fixtures", {}, "n")
sjekk("tre HTTP 500 teller som tre feil",
      _hl.feil_paa_rad("alle", "oddspapi-fixtures") == 3)
sjekk("og kilden navngis per endepunkt, med liga «alle»",
      ("alle", "oddspapi-fixtures", 3) in _hl.ute(), str(_hl.ute()))
sjekk("en kilde uten egen liga kan altså gjøre kjøringen rød",
      _hl.sjekk() == 1)
_op.urllib.request.urlopen = _op_ekte_aapne
_op.budsjett_stopp = _op_ekte_budsjett

print("\n=== Bare samme fysiske kilde nullstiller feilrekken ===")
# Faren: ligasiden er nede, reservekilden svarer, kjeden gaar videre -- og
# alarmen forsvinner fordi "en kilde" lyktes. Da er loggen verre enn ingen
# logg: den sier at alt er bra mens hovedkilden har vaert nede i en uke.
# Hver fysisk kilde har derfor sin egen rekke, paa (liga, kilde).
_hl10 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl10
_n10 = _dt(2026, 9, 20, 10, 0, tzinfo=_tz.utc)
for _i in range(3):
    _hl.logg("obos", "ntf-resultater", "feil", melding="timeout",
             naa=_n10 + _td3(days=_i))
_etter10 = _n10 + _td3(days=3)
sjekk("hovedkilden har tre feil på rad",
      _hl.feil_paa_rad("obos", "ntf-resultater", naa=_etter10) == 3)

# 1. En RESERVEKILDE lykkes -- fotball.no er reserve for ligasiden.
_hl.logg("obos", "nff", "ok", kamper=240, naa=_etter10)
sjekk("at reservekilden fotball.no lykkes nullstiller IKKE hovedkilden",
      _hl.feil_paa_rad("obos", "ntf-resultater",
                       naa=_etter10 + _td3(hours=1)) == 3)
sjekk("og kjøringen er fortsatt rød",
      _hl.sjekk(naa=_etter10 + _td3(hours=1)) == 1)

# 2. Den ANDRE SIDEN hos samme leverandor lykkes. Terminlisten og
#    resultatsiden er to forespørsler til to adresser: den ene kan svare
#    mens den andre er nede, og da er de ikke samme fysiske kilde.
_hl.logg("obos", "ntf-terminliste", "ok", kamper=56,
         naa=_etter10 + _td3(hours=2))
sjekk("at terminlisten lykkes nullstiller ikke resultatsiden",
      _hl.feil_paa_rad("obos", "ntf-resultater",
                       naa=_etter10 + _td3(hours=3)) == 3)

# 3. SAMME KILDE i den andre ligaen lykkes.
_hl.logg("eliteserien", "ntf-resultater", "ok", kamper=184,
         naa=_etter10 + _td3(hours=4))
sjekk("at Eliteserien-siden lykkes nullstiller ikke OBOS-siden",
      _hl.feil_paa_rad("obos", "ntf-resultater",
                       naa=_etter10 + _td3(hours=5)) == 3)

# 4. Alle de tre andre kildene lyktes, og alarmen staar likevel -- med
#    NOYAKTIG hovedkilden navngitt, ikke de som virker.
_nede10 = _hl.ute(naa=_etter10 + _td3(hours=5))
sjekk("alarmen navngir bare kilden som er nede",
      _nede10 == [("obos", "ntf-resultater", 3)], str(_nede10))

# 5. Bare en vellykket henting fra SAMME kilde nullstiller.
_hl.logg("obos", "ntf-resultater", "ok", kamper=184,
         naa=_etter10 + _td3(hours=6))
sjekk("en vellykket henting fra samme kilde nullstiller",
      _hl.feil_paa_rad("obos", "ntf-resultater",
                       naa=_etter10 + _td3(hours=7)) == 0)
sjekk("og da blir kjøringen grønn",
      _hl.sjekk(naa=_etter10 + _td3(hours=7)) == 0)
_hl.KATALOG = _ekte_kat

print("\n=== En kilde som svarer, men ikke gir kamper, er en FEIL ===")
# Den verste feilmaaten: 200 OK, men 0 kamper ut. Loggen maa ikke vise
# dette gront -- da er en omlagt markup usynlig.
_hl11 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl11
_n11 = _dt(2026, 9, 20, 10, 0, tzinfo=_tz.utc)

# 1. Ligasiden svarer med en side vi ikke kjenner igjen. parse_side kaster,
#    og kastet skjer ETTER hentingen -- for laa det utenfor loggingen, saa
#    denne feilmaaten ble aldri loggfort i det hele tatt.
_ntfs.hent = lambda url, **kw: "<html><body>ny forside</body></html>"
with _vern.miljo(GITHUB_RUN_ID="omlagt"):
    try:
        _ntfs.fetch_all("obos", log=lambda _s: None, naa=_n11)
    except Exception:
        pass
_r11 = [r for r in _hl.les(naa=_n11 + _td3(hours=1)) if r["liga"] == "obos"]
sjekk("omlagt markup på ligasiden logges som feil",
      _r11 and _r11[-1]["utfall"] == "feil", str(_r11))
sjekk("og ikke som «ok» med 0 kamper",
      not any(r["utfall"] == "ok" for r in _r11), str(_r11))
_ntfs.hent = _ntf_ekte_hent

# 2. fotball.no svarer med en gyldig, men tom tabell. Da kaster ikke
#    parse_side -- og uten regelen ville dette blitt logget «ok, 0 kamper».
_hl12 = Path(_tf2.mkdtemp())
_hl.KATALOG = _hl12
_nffs.CACHE_KATALOG = Path(_tf2.mkdtemp())
_nffs.CACHE_KATALOG.mkdir(parents=True, exist_ok=True)
_nffs.hent = lambda url, **kw: "<html>tom</html>"
_nff_ekte_parse = _nffs.parse_side
_nffs.parse_side = lambda *a, **k: []
with _vern.miljo(GITHUB_RUN_ID="tom-tabell"):
    _tomt = _nffs.fetch_all("obos", log=lambda _s: None, naa=_n11)
_r12 = [r for r in _hl.les(naa=_n11 + _td3(hours=1)) if r["kilde"] == "nff"]
sjekk("fotball.no med 0 kamper logges som feil",
      _r12 and _r12[-1]["utfall"] == "feil" and _r12[-1].get("kamper") == 0,
      str(_r12))
# Tre slike dogn paa rad: kilden svarer hver gang, og alarmen gaar likevel.
for _dag in (1, 2):
    with _vern.miljo(GITHUB_RUN_ID=f"tom{_dag}"):
        _nffs.fetch_all("obos", log=lambda _s: None,
                        naa=_n11 + _td3(days=_dag))
_etter12 = _n11 + _td3(days=3)
sjekk("tre døgn med 0 kamper teller som tre feil",
      _hl.feil_paa_rad("obos", "nff", naa=_etter12) == 3,
      str([r["utfall"] for r in _hl.les(naa=_etter12) if r["kilde"] == "nff"]))
sjekk("og gjør kjøringen rød", _hl.sjekk(naa=_etter12) == 1)
_nffs.parse_side = _nff_ekte_parse
_nffs.hent = _nff_ekte_hent
_nffs.CACHE_KATALOG = _nff_ekte_kat
_hl.KATALOG = _ekte_kat

print("\n=== Regelen for å publisere et resultat (resultatregel.py) ===")
# 3.10.2026: et resultat publiseres når hovedkilden og minst én kilde fra en
# annen leverandør er enige. Er ligasiden nede, blir neste kilde hovedkilde.
# fotball.no og NTF er samme leverandør. Uten uavhengig kilde: 24 timer, og
# da bare for den offisielle ligasiden alene, aldri en annen enkeltkilde, og
# kjøringen er rød til resultatet er kontrollert.
import resultatregel as _regel
_A = _dt(2026, 5, 29, 19, 0, tzinfo=ZoneInfo("Europe/Oslo"))
_kort, _lenge = _A + __import__("datetime").timedelta(hours=3), _A + __import__("datetime").timedelta(hours=25)
_alle_es = set(_regel.KILDER["eliteserien"])
def _avg(liga, svar, oppe=None, naa=None):
    return _regel.avgjor(liga, svar, set(oppe if oppe is not None else _regel.KILDER[liga]), avspark=_A, naa=naa or _kort)
_t = [
    ("OBOS: ligasiden og Highlightly enige: publiseres", "obos", {"ligasiden": (2, 0), "highlightly": (2, 0)}, None, None,
     ("publiser", (2, 0), "ligasiden", "highlightly", False)),
    ("Eliteserien: ligasiden 3-1, ESPN 0-0 (feil hos ESPN), Highlightly 3-1: publiseres, ESPN står som uenig",
     "eliteserien", {"ligasiden": (3, 1), "espn": (0, 0), "highlightly": (3, 1)}, None, None, ("publiser", (3, 1), "ligasiden", "highlightly", False)),
    ("Eliteserien: ligasiden 3-1 og bare ESPN 0-0: konflikt, holdes tilbake",
     "eliteserien", {"ligasiden": (3, 1), "espn": (0, 0)}, None, None, ("konflikt", None, "ligasiden", None, False)),
    ("ligasiden nede, bare ESPN 0-0: vent (en enkeltkilde publiserer aldri alene), også etter 24 timer",
     "eliteserien", {"espn": (0, 0)}, _alle_es - {"ligasiden"}, _lenge, ("vent", None, "espn", None, False)),
    ("ligasiden nede, ESPN 0-0 og Highlightly 3-1: konflikt",
     "eliteserien", {"espn": (0, 0), "highlightly": (3, 1)}, _alle_es - {"ligasiden"}, None, ("konflikt", None, "espn", None, False)),
    ("ligasiden nede: ESPN blir hovedkilde, og ESPN og fotball.no enige (ulike leverandører): publiseres",
     "eliteserien", {"espn": (2, 1), "fotball.no": (2, 1)}, {"espn", "fotball.no"}, None, ("publiser", (2, 1), "espn", "fotball.no", False)),
    ("ligasiden og fotball.no enige: samme leverandør (NTF), så ikke enighet: vent",
     "eliteserien", {"ligasiden": (2, 1), "fotball.no": (2, 1)}, None, None, ("vent", None, "ligasiden", None, False)),
    ("bare ligasiden har resultatet etter 25 timer: publiseres uten kontroll (rødt)",
     "obos", {"ligasiden": (1, 1)}, None, _lenge, ("publiser", (1, 1), "ligasiden", None, True)),
    ("bare ligasiden etter 3 timer: vent",
     "obos", {"ligasiden": (1, 1)}, None, None, ("vent", None, "ligasiden", None, False)),
    ("ligasiden er oppe, men har ikke resultatet: vent, selv om ESPN og Highlightly er enige",
     "eliteserien", {"espn": (1, 0), "highlightly": (1, 0)}, None, None, ("vent", None, "ligasiden", None, False)),
    ("OBOS: Highlightly mangler, OddsPapi (reserve) enig: publiseres",
     "obos", {"ligasiden": (0, 4), "oddspapi": (0, 4)}, None, None, ("publiser", (0, 4), "ligasiden", "oddspapi", False)),
]
for _navn, _l, _sv, _opp, _naa, _f in _t:
    _u = _avg(_l, _sv, _opp, _naa)
    sjekk(_navn, (_u["utfall"], _u["resultat"], _u["hoved"], _u["enig"], _u["ukontrollert"]) == _f, str(_u))
_fort, _bekr, _ueni = _regel.kontroller_ukontrollerte("obos", {("Moss", "Odd"): (1, 1), ("Lyn", "Bryne"): (2, 0), ("Hødd", "Moss"): (0, 0)},
    {("Moss", "Odd"): {"highlightly": (1, 1)}, ("Lyn", "Bryne"): {"fotball.no": (2, 0)}, ("Hødd", "Moss"): {"wikipedia": (1, 0)}})
sjekk("uten kontroll: bekreftet av Highlightly; fotball.no (samme leverandør) bekrefter ikke; Wikipedia uenig",
      _bekr == [("Moss", "Odd")] and set(_fort) == {("Lyn", "Bryne"), ("Hødd", "Moss")} and [u[0] for u in _ueni] == [("Hødd", "Moss")],
      f"{_fort} {_bekr} {_ueni}")

print("\n=== Highlightly: lagrede svar fra kartleggingen 3.10.2026 ===")
# Svarene er fra highlightly-probe.yml (bare feltene vi bruker). Tidene er
# UTC; sidedelingen er ustabil (16.8. og 30.8.: kamper med samme avspark kom
# to ganger, og Egersund-Stabæk, Sandefjord-Brann og Vålerenga-Molde manglet).
# Resultatene hentes derfor per dato, og en hel sesong får dublettene fjernet
# og det som mangler hentet per dato -- ellers kastes den.
import highlightly_source as _hls
_HLD = TESTDATA / "highlightly"
_hl_les = lambda navn: json.loads((_HLD / f"{navn}.json").read_text("utf-8"))
_hl_kall = []
def _hl_http(sti, param, fjern=None):
    """Lagrede svar: datoene som egne filer, sesongen side for side (100 per side,
    i rekkefølgen den kom, med dublettene)."""
    _hl_kall.append(dict(param))
    if "date" in param:
        d = _hl_les(f"dag_{param['date']}")
        if fjern:
            d = [m for m in d if (m["homeTeam"]["name"], m["awayTeam"]["name"]) not in fjern]
        return {"data": d, "pagination": {"totalCount": len(d), "offset": 0, "limit": 100}}
    liga = {v: k for k, v in _hls.LIGA_ID.items()}[param["leagueId"]]
    alle = _hl_les(f"sesong_{liga}_2026")
    o = param.get("offset", 0)
    return {"data": alle[o:o + 100], "pagination": {"totalCount": len(alle), "offset": o, "limit": 100}}
_hl_ekte_http = _hls._http
_hls._http = _hl_http
try:
    # Tidene: UTC til norsk tid, før og etter vintertid (25.10.2026 kl. 03).
    _s_o = {(r["home"], r["away"]): r for r in (_hls.parse_kamp(m, "obos") for m in
            {m["id"]: m for m in _hl_les("sesong_obos_2026")}.values())}
    _s_e = {(r["home"], r["away"]): r for r in (_hls.parse_kamp(m, "eliteserien") for m in
            {m["id"]: m for m in _hl_les("sesong_eliteserien_2026")}.values())}
    sjekk("Sogndal-Raufoss (flyttet): 21.10. 17:00Z er 19:00 norsk tid, runde 24",
          (_s_o[("Sogndal", "Raufoss")]["date"], _s_o[("Sogndal", "Raufoss")]["time"], _s_o[("Sogndal", "Raufoss")]["round"]) == ("2026-10-21", "19:00", 24),
          str(_s_o[("Sogndal", "Raufoss")]))
    sjekk("Eliteserien runde 12: 24.10. 14:00Z er 16:00 (sommertid), 25.10. 13:30Z er 14:30 (vintertid)",
          (_s_e[("Bodø/Glimt", "Vålerenga")]["time"], _s_e[("Viking", "Tromsø")]["time"], _s_e[("Viking", "Tromsø")]["round"]) == ("16:00", "14:30", 12),
          f"{_s_e[('Bodø/Glimt', 'Vålerenga')]} {_s_e[('Viking', 'Tromsø')]}")
    # Navnene: alle 16 i hver liga kjennes igjen; et ukjent navn stopper.
    _navn = {l: sorted({m[s]["name"] for m in _hl_les(f"sesong_{l}_2026") for s in ("homeTeam", "awayTeam")}) for l in ("obos", "eliteserien")}
    sjekk("navnekartet: alle 16 lagnavn i hver liga blir våre (Haugesund FK, ODD Ballklubb, Strommen, Sandnes ULF, Kongsvinger IL, Tromsø IL ...)",
          all(len({_hls._lag(n, l) for n in _navn[l]}) == 16 == len(_navn[l]) for l in _navn), str(_navn))
    try:
        _hls._lag("Haugesund", "eliteserien"); _kast = None
    except _hls.HighlightlyDataError as e:
        _kast = str(e)
    sjekk("et lag fra en annen liga (eller et ukjent navn): tydelig feil", _kast is not None and "ukjent lag" in _kast, str(_kast))
    # Resultatene per dato: ett kall for begge ligaene, bare ligaenes kamper.
    _hl_kall.clear()
    _d = _hls.hent_dag("2026-10-03")
    _hs = [r for r in _d["obos"] if (r["home"], r["away"]) == ("Haugesund", "Stabæk")]
    sjekk("hent_dag 3.10.: ett kall, de fire OBOS-kampene med resultat (Haugesund-Stabæk 2-0, 16:00), ingen fra kvinneligaen",
          len(_hl_kall) == 1 and len(_d["obos"]) == 4 and _d["eliteserien"] == [] and _hs and (_hs[0]["hg"], _hs[0]["ag"], _hs[0]["time"], _hs[0]["ferdig"]) == (2, 0, "16:00", True),
          f"{_hl_kall} {_d}")
    _d = _hls.hent_dag("2026-05-29")
    _r = {(r["home"], r["away"]): (r["hg"], r["ag"]) for r in _d["eliteserien"]}
    sjekk("hent_dag 29.5.: Vålerenga-Kristiansund 3-1 og Aalesund-HamKam 2-2 (der ESPN viser 0-0)",
          _r.get(("Vålerenga", "Kristiansund")) == (3, 1) and _r.get(("Aalesund", "HamKam")) == (2, 2), str(_r))
    # Hele sesongen: dubletter fjernet, det som mangler hentet per dato.
    for _l, _dag, _mangler in (("obos", "2026-08-16", [("Egersund", "Stabæk")]),
                              ("eliteserien", "2026-08-30", [("Sandefjord", "Brann"), ("Vålerenga", "Molde")])):
        _rå = _hl_les(f"sesong_{_l}_2026")
        _dubl = len(_rå) - len({m["id"] for m in _rå})
        _kj = {}
        for _f in ("matches.json",):
            for _m in json.loads((ROT / "tests" / "data" / "2026-10-01" / _l / "data" / _f).read_text("utf-8")):
                _kj[(_m["home"], _m["away"])] = _m["date"]
        for _rr in json.loads((ROT / "tests" / "data" / "2026-10-01" / _l / "data" / "fixtures.json").read_text("utf-8")):
            for _m in _rr["matches"]:
                _kj.setdefault((_m["home"], _m["away"]), _m["date"])
        _hl_kall.clear()
        _ses = _hls.hent_sesong(_l, 2026, _kj)
        _nok = {(r["home"], r["away"]) for r in _ses}
        sjekk(f"{_l}: sesongen med {_dubl} dublett(er) på kamp-id gir 240 unike kamper, og {', '.join(f'{a}-{b}' for a, b in _mangler)} hentes fra {_dag} (4 kall)",
              _dubl > 0 and len(_ses) == 240 and len(_nok) == 240 and all(k in _nok for k in _mangler)
              and len(_hl_kall) == 4 and _hl_kall[-1].get("date") == _dag, f"{len(_ses)} {len(_nok)} {_hl_kall}")
        # Mot testdataene fra 1.10.: samme dato, tid og runde for alle, samme
        # resultat for alle som var spilt da.
        _v = {}
        for _m in json.loads((ROT / "tests" / "data" / "2026-10-01" / _l / "data" / "matches.json").read_text("utf-8")):
            _v[(_m["home"], _m["away"])] = (_m["date"], _m["time"], _m["round"], _m["hg"], _m["ag"])
        _avvik = [(r["home"], r["away"]) for r in _ses if (r["home"], r["away"]) in _v
                  and (r["date"], r["time"], r["round"], r["hg"], r["ag"]) != _v[(r["home"], r["away"])]]
        sjekk(f"{_l}: dato, tid (norsk), runde og resultat er de samme som våre for alle {len(_v)} spilte kampene",
              not _avvik, str(_avvik[:5]))
        # Mangler kampen også i dagssvaret, er svaret ufullstendig og brukes ikke.
        _hls._http = lambda sti, param, _f=set(_mangler): _hl_http(sti, param, fjern={(n, m) for n, m in
            [("Egersund", "Stabæk"), ("Sandefjord", "Brann"), ("Vålerenga", "Molde")]})
        try:
            _hls.hent_sesong(_l, 2026, _kj); _kast = None
        except _hls.Ufullstendig as e:
            _kast = str(e)
        _hls._http = _hl_http
        sjekk(f"{_l}: mangler kampen også i dagssvaret, er sesongen ufullstendig (ikke 240) og kastes",
              _kast is not None and "ventet 240" in _kast, str(_kast))
    # Dagstaket: ingen kall over taket, og hvert kall er talt.
    _brukt = _hls.dagsbruk()
    _ekte_tak = _hls.DAGSTAK
    _hls.DAGSTAK = _brukt
    try:
        _hl_kall.clear(); _hls.hent_dag("2026-10-03"); _kast = None
    except _hls.Budsjett as e:
        _kast = str(e)
    _hls.DAGSTAK = _ekte_tak
    sjekk(f"dagstaket: kallene telles ({_brukt} i testen), og over taket går ingen kall ut",
          _brukt >= 10 and _kast is not None and _hl_kall == [], f"{_brukt} {_kast} {_hl_kall}")
    # Kvoten fra Highlightly (x-ratelimit-requests-remaining) logges ved hvert
    # kall, og under 20 er det en advarsel (4.10.2026). Svaret uten headeren
    # sies også.
    import io as _io, contextlib as _cl, os as _os4
    def _med_kvote(igjen):
        def h(sti, param):
            d = _hl_http(sti, param)
            if igjen is not None:
                _hls._siste_kvote.update({"x-ratelimit-requests-remaining": str(igjen), "x-ratelimit-requests-limit": "100"})
            return d
        return h
    _kv = {}
    _ekte_gh = _os4.environ.pop("GITHUB_ACTIONS", None)
    for _igjen in (57, 20, 19, None):
        _hls._http = _med_kvote(_igjen)
        _buf = _io.StringIO()
        with _cl.redirect_stdout(_buf):
            _hls.hent_dag("2026-10-03")
        _kv[_igjen] = _buf.getvalue()
    if _ekte_gh is not None:
        _os4.environ["GITHUB_ACTIONS"] = _ekte_gh
    _hls._http = _hl_http
    sjekk("kvoten logges ved hvert kall: «57 av 100 kall igjen i dag (x-ratelimit-requests-remaining)», ingen advarsel ved 57 og 20",
          "/matches 2026-10-03 (alle): 57 av 100 kall igjen i dag (x-ratelimit-requests-remaining)" in _kv[57]
          and "ADVARSEL" not in _kv[57] and "20 av 100 kall igjen" in _kv[20] and "ADVARSEL" not in _kv[20], _kv[57] + _kv[20])
    sjekk("under 20: advarsel (19 kall igjen)",
          "ADVARSEL: Highlightly har bare 19 kall igjen i dag (under 20)" in _kv[19], _kv[19])
    sjekk("svar uten headeren: det sies, ingen advarsel", "hadde ikke x-ratelimit-requests-remaining" in _kv[None]
          and "ADVARSEL" not in _kv[None], _kv[None])
    _os4.environ["GITHUB_ACTIONS"] = "true"
    _buf = _io.StringIO()
    _hls._http = _med_kvote(3)
    with _cl.redirect_stdout(_buf):
        _hls.hent_dag("2026-10-03")
    if _ekte_gh is None:
        _os4.environ.pop("GITHUB_ACTIONS", None)
    else:
        _os4.environ["GITHUB_ACTIONS"] = _ekte_gh
    sjekk("i GitHub Actions blir advarselen også en ::warning", "::warning title=Highlightly-kvoten::Highlightly har bare 3 kall igjen i dag" in _buf.getvalue(),
          _buf.getvalue())
finally:
    _hls._http = _hl_ekte_http

print("\n=== Én linje per resultat, og hvilken kilde som hadde det først (resultatregel, 4.10.2026) ===")
_kB = ("Bryne", "Lyn")
_L = lambda liga, svar, oppe, **kw: _regel.resultatlinje(liga, _kB, _regel.avgjor(liga, svar, oppe, **kw), svar)
_O2 = {"ligasiden", "highlightly"}
sjekk('enige: "Bryne-Lyn 1-0: ligasiden og highlightly enige, publisert"',
      _L("obos", {"ligasiden": (1, 0), "highlightly": (1, 0)}, _O2) == "Bryne-Lyn 1-0: ligasiden og highlightly enige, publisert")
sjekk('uenige: "Bryne-Lyn: ligasiden 2-1, highlightly 1-1, holdt tilbake"',
      _L("obos", {"ligasiden": (2, 1), "highlightly": (1, 1)}, _O2) == "Bryne-Lyn: ligasiden 2-1, highlightly 1-1, holdt tilbake")
_l = _L("eliteserien", {"ligasiden": (3, 1), "espn": (0, 0), "highlightly": (3, 1)}, {"ligasiden", "espn", "highlightly"})
sjekk("publisert selv om én kilde er uenig: den uenige står i parentes", _l == "Bryne-Lyn 3-1: ligasiden og highlightly enige, publisert (espn 0-0 uenig)", _l)
sjekk('bare ligasiden: "venter på en uavhengig kilde"',
      _L("obos", {"ligasiden": (1, 0)}, _O2) == "Bryne-Lyn 1-0: bare ligasiden, venter på en uavhengig kilde")
_l = _L("obos", {"highlightly": (1, 0)}, _O2)
sjekk('Highlightly før ligasiden: "ligasiden har ikke resultatet ennå (highlightly 1-0), venter"',
      _l == "Bryne-Lyn: ligasiden har ikke resultatet ennå (highlightly 1-0), venter", _l)
_avs = _dt(2026, 10, 4, 12, 30, tzinfo=_tz.utc)
_l = _L("obos", {"ligasiden": (1, 0)}, _O2, avspark=_avs, naa=_avs + _td(hours=25))
sjekk("etter 24 timer uten uavhengig kilde: publisert uten kontroll", _l == "Bryne-Lyn 1-0: bare ligasiden etter 24 timer, publisert uten kontroll", _l)
_t1, _t2 = _dt(2026, 10, 4, 14, 21, tzinfo=_tz.utc), _dt(2026, 10, 4, 14, 31, tzinfo=_tz.utc)
_f1, _fl1 = _regel.forst_sett({}, {_kB: {"highlightly": (1, 0), "ligasiden": None}}, _t1, set())
_f2, _fl2 = _regel.forst_sett(_f1, {_kB: {"highlightly": (1, 0), "ligasiden": (1, 0)}}, _t2, set())
sjekk('først hos kilden: "Bryne-Lyn: highlightly 16.21, ligasiden 16.31" (norsk tid), Highlightly beholder sin første tid',
      _fl1 == ["Bryne-Lyn: highlightly 16.21"] and _fl2 == ["Bryne-Lyn: highlightly 16.21, ligasiden 16.31"]
      and _f2["Bryne|Lyn"]["highlightly"] == _t1.isoformat(timespec="seconds"), f"{_fl1} {_fl2} {_f2}")
_f3, _fl3 = _regel.forst_sett(_f2, {}, _t2 + _td(minutes=10), {_kB})
sjekk("publisert før kjøringen: tatt ut av tilstanden, ingen linje", _f3 == {} and _fl3 == [], f"{_f3} {_fl3}")
_f4, _fl4 = _regel.forst_sett(_f1, {}, _t1 + _td(days=1), set())
sjekk("fra en annen dag: med dato (4.10. 16.21)", _fl4 == ["Bryne-Lyn: highlightly 4.10. 16.21"], str(_fl4))

print("\n=== OBOS-resultatkjeden med regelen, hele veien (main) ===")
# obos_results.main() i en sandkasse med terminlisten fra 1.10. og fast
# klokke. Ligasiden har fem resultater fra 2.-3.10.; Highlightly svarer med
# de lagrede dagssvarene (3.10. har fire av dem, 2.10. er ikke lagret og gir
# ingenting). OddsPapi er reserve og skal bare spørres for kampen
# Highlightly ikke har.
import types as _types
_sbo = Path(_tf2.mkdtemp())
for _f in ("matches.json", "fixtures.json"):
    _shr.copy(ROT / "tests" / "data" / "2026-10-01" / "obos" / "data" / _f, _sbo / _f)
_lig = {("Ranheim", "Egersund"): (5, 0), ("Strømmen", "Sandnes Ulf"): (3, 3), ("Haugesund", "Stabæk"): (2, 0),
        ("Hødd", "Odd"): (2, 3), ("Strømsgodset", "Åsane"): (1, 0)}
_op_kall = []
_ekte = {n: getattr(_obr, n) for n in ("DATA", "MATCHES", "STATE", "ligasiden_og_reserve", "wikipedia_results",
                                       "oddspapi_fixtures", "finished_without_result", "oddspapi_score", "datetime")}
_ekte_sleep, _ekte_argv, _ekte_hlhttp = _obr.time.sleep, sys.argv, _hls._http
def _klokke(t):
    class _D(_dt):
        @classmethod
        def now(cls, tz=None):
            return t if tz is None else t.astimezone(tz)
    return _D
def _hl_stub(sti, param, endre=None):
    _hl_kall.append(dict(param))
    d = [dict(m) for m in (_hl_les(f"dag_{param['date']}") if (_HLD / f"dag_{param['date']}.json").exists() else [])]
    for m in d:
        if endre and (m["homeTeam"]["name"], m["awayTeam"]["name"]) in endre:
            m["state"] = {**m["state"], "score": {"current": endre[(m["homeTeam"]["name"], m["awayTeam"]["name"])]}}
    return {"data": d, "pagination": {"totalCount": len(d), "offset": 0, "limit": 100}}
def _kjor(naa, lig=_lig, hl_endre=None, wiki=None):
    _obr.datetime = _klokke(naa)
    _obr.ligasiden_og_reserve = lambda: (dict(lig), None)
    _obr.wikipedia_results = lambda names: wiki
    _hls._http = lambda sti, param: _hl_stub(sti, param, hl_endre)
    _hl_kall.clear()
    sys.argv = ["obos_results.py"]
    with _vern.miljo(ODDSPAPI_KEY="test"):
        kode = _obr.main()
    st = json.loads((_sbo / "results_state.json").read_text("utf-8"))
    pub = {(m["home"], m["away"]): (m["hg"], m["ag"]) for m in json.loads((_sbo / "matches.json").read_text("utf-8"))}
    return kode, st, pub
try:
    _obr.DATA, _obr.MATCHES, _obr.STATE = _sbo, _sbo / "matches.json", _sbo / "results_state.json"
    _obr.time.sleep = lambda _x: None
    _obr.oddspapi_fixtures = lambda key: [{"fixtureId": "x"}]
    _obr.finished_without_result = lambda fx, prev, names, teams: [(k, {"fixtureId": f"{k[0]}|{k[1]}"}) for k in _lig if k not in prev]
    _obr.oddspapi_score = lambda key, fid: (_op_kall.append(fid), {"Ranheim|Egersund": (5, 0)}.get(fid))[1]
    _hls._http = _hl_stub
    _n0 = len(json.loads((_sbo / "matches.json").read_text("utf-8")))
    _kode, _st, _pub = _kjor(_dt(2026, 10, 3, 18, 43, tzinfo=_tz.utc))
    sjekk("ligasiden + Highlightly 3.10.: de fire kampene publiseres; Ranheim-Egersund (2.10., ikke hos Highlightly) avgjøres av OddsPapi",
          all(_pub.get(k) == v for k, v in _lig.items()) and len(_pub) == _n0 + 5 and not _st["conflicts"] and not _st["ukontrollert"],
          f"{_kode} {len(_pub)} {_n0} {_st}")
    sjekk("OddsPapi (koster ett kall per kamp) spørres bare for Ranheim-Egersund", _op_kall == ["Ranheim|Egersund"], str(_op_kall))
    # Bekreftelsen (12.10.2026): hvilke kilder utenfor NTF som hadde resultatet da det ble publisert.
    sjekk("tilstanden: de fire kampene er bekreftet av highlightly, Ranheim-Egersund av oddspapi, med tidspunktet for publiseringen",
          {k: (v["resultat"], v["kilder"], v["publisert"]) for k, v in _st.get("bekreftet", {}).items()}
          == {**{f"{k[0]}|{k[1]}": (list(v), ["highlightly"], "2026-10-03T18:43:00+00:00") for k, v in _lig.items() if k != ("Ranheim", "Egersund")},
              "Ranheim|Egersund": ([5, 0], ["oddspapi"], "2026-10-03T18:43:00+00:00")}, str(_st.get("bekreftet")))
    sjekk("Highlightly: ett kall per kampdag (2.10. og 3.10.)",
          sorted(k["date"] for k in _hl_kall) == ["2026-10-02", "2026-10-03"], str(_hl_kall))
    # Uenighet: Highlightly har 1-0 for Haugesund-Stabæk (ligasiden 2-0), og ingen andre.
    for _f in ("matches.json",):
        _shr.copy(ROT / "tests" / "data" / "2026-10-01" / "obos" / "data" / _f, _sbo / _f)
    (_sbo / "results_state.json").unlink()
    _op_kall.clear()
    _kode, _st, _pub = _kjor(_dt(2026, 10, 3, 18, 43, tzinfo=_tz.utc), hl_endre={("Haugesund FK", "Stabæk"): "1 - 0"})
    sjekk("Highlightly uenig (1-0 mot ligasidens 2-0): Haugesund-Stabæk holdes tilbake som konflikt, de andre publiseres",
          ("Haugesund", "Stabæk") not in _pub and any("Haugesund mot Stabæk" in c for c in _st["conflicts"])
          and _pub.get(("Hødd", "Odd")) == (2, 3), f"{_st['conflicts']} {_pub.get(('Haugesund', 'Stabæk'))}")
    sjekk("og OddsPapi spørres for den omstridte kampen (og Ranheim-Egersund)",
          sorted(_op_kall) == ["Haugesund|Stabæk", "Ranheim|Egersund"], str(_op_kall))
    # Uten kontroll: bare ligasiden har Ranheim-Egersund, 25 timer etter avspark.
    _shr.copy(ROT / "tests" / "data" / "2026-10-01" / "obos" / "data" / "matches.json", _sbo / "matches.json")
    (_sbo / "results_state.json").unlink()
    _obr.oddspapi_score = lambda key, fid: (_op_kall.append(fid), None)[1]
    _kode, _st, _pub = _kjor(_dt(2026, 10, 3, 18, 1, tzinfo=_tz.utc), lig={("Ranheim", "Egersund"): (5, 0)})
    sjekk("bare ligasiden, 25 timer etter avspark: Ranheim-Egersund publiseres uten kontroll og står i tilstanden",
          _pub.get(("Ranheim", "Egersund")) == (5, 0) and _st["ukontrollert"] == {"Ranheim|Egersund": [5, 0]}, str(_st))
    sjekk("og et resultat publisert uten kontroll står IKKE som bekreftet", _st.get("bekreftet") == {}, str(_st.get("bekreftet")))
    _ok_rr = Path(_tf2.mkdtemp()); (_ok_rr / "obos" / "data").mkdir(parents=True)
    _shr.copy(_sbo / "results_state.json", _ok_rr / "obos" / "data" / "results_state.json")
    sjekk("og kjøringen er rød så lenge den står uten kontroll (resultatregel.py sjekk obos)", _regel.sjekk("obos", rot=_ok_rr) == 1)
    # Neste time: Highlightly har kampen (2.10. lagt til som dagssvar fra 3.10.-filen sin form).
    _dag2 = [m for m in _hl_les("sesong_obos_2026") if m["homeTeam"]["name"] == "Ranheim" and m["awayTeam"]["name"] == "Egersund"]
    (_HLD / "dag_2026-10-02.json").write_text(json.dumps(_dag2[:1]), encoding="utf-8")
    try:
        _kode, _st, _pub = _kjor(_dt(2026, 10, 3, 19, 5, tzinfo=_tz.utc), lig={("Ranheim", "Egersund"): (5, 0)})
    finally:
        (_HLD / "dag_2026-10-02.json").unlink()
    _shr.copy(_sbo / "results_state.json", _ok_rr / "obos" / "data" / "results_state.json")
    sjekk("en time senere bekrefter Highlightly 5-0: ikke lenger uten kontroll, og kjøringen er grønn",
          _st["ukontrollert"] == {} and _regel.sjekk("obos", rot=_ok_rr) == 0, str(_st))
    sjekk("og da står det som bekreftet av highlightly",
          _st.get("bekreftet") == {"Ranheim|Egersund": {"resultat": [5, 0], "kilder": ["highlightly"], "publisert": "2026-10-03T19:05:00+00:00"}},
          str(_st.get("bekreftet")))
    # Én linje per resultat og hvem som hadde det først (4.10.2026). Ligasiden
    # har ingen av rundens resultater ennå 3.10. kl. 20.43; Highlightly har fire.
    import io as _io7, contextlib as _cl7
    def _kjor_ut(naa, lig):
        b = _io7.StringIO()
        with _cl7.redirect_stdout(b):
            r = _kjor(naa, lig=lig)
        return (*r, b.getvalue())
    _shr.copy(ROT / "tests" / "data" / "2026-10-01" / "obos" / "data" / "matches.json", _sbo / "matches.json")
    (_sbo / "results_state.json").unlink()
    _obr.oddspapi_score = lambda key, fid: (_op_kall.append(fid), {"Ranheim|Egersund": (5, 0)}.get(fid))[1]
    _kode, _st, _pub, _ut = _kjor_ut(_dt(2026, 10, 3, 18, 43, tzinfo=_tz.utc), {})
    sjekk("kampene er over, ligasiden har dem ikke ennå: Highlightly spørres likevel (ett kall per dato), bare til loggen",
          sorted(k["date"] for k in _hl_kall) == ["2026-10-02", "2026-10-03"] and len(_pub) == _n0, f"{_hl_kall} {len(_pub)}")
    sjekk('linjen: "Haugesund-Stabæk: ligasiden har ikke resultatet ennå (highlightly 2-0), venter", og ingenting publiseres',
          "Haugesund-Stabæk: ligasiden har ikke resultatet ennå (highlightly 2-0), venter" in _ut, _ut[-900:])
    sjekk("tilstanden husker når Highlightly først hadde Haugesund-Stabæk",
          _st.get("forst_sett", {}).get("Haugesund|Stabæk") == {"highlightly": "2026-10-03T18:43:00+00:00"}, str(_st.get("forst_sett")))
    _kode, _st, _pub, _ut = _kjor_ut(_dt(2026, 10, 3, 18, 53, tzinfo=_tz.utc), _lig)
    sjekk('ti minutter senere har ligasiden det: "Haugesund-Stabæk 2-0: ligasiden og highlightly enige, publisert"',
          "Haugesund-Stabæk 2-0: ligasiden og highlightly enige, publisert" in _ut and _pub.get(("Haugesund", "Stabæk")) == (2, 0), _ut[-900:])
    sjekk('og "Haugesund-Stabæk: highlightly 20.43, ligasiden 20.53"', "Haugesund-Stabæk: highlightly 20.43, ligasiden 20.53" in _ut, _ut[-900:])
    _kode, _st, _pub, _ut = _kjor_ut(_dt(2026, 10, 3, 19, 3, tzinfo=_tz.utc), _lig)
    sjekk("kjøringen etter publiseringen: kampen er tatt ut av tilstanden", "Haugesund|Stabæk" not in _st.get("forst_sett", {}), str(_st.get("forst_sett")))
    # Kontrollen mot Wikipedia (17.10.2026, resultatregel.revider_kilde): et
    # ANNET resultat er en konflikt (rødt; før bare en linje i loggen), et
    # manglende er en advarsel når publiseringen hadde en uavhengig kilde.
    _wk = dict(_pub)
    del _wk[("Haugesund", "Stabæk")]
    _wk[("Hødd", "Odd")] = (3, 3)
    _kode, _st, _ = _kjor(_dt(2026, 10, 7, 12, 0, tzinfo=_tz.utc), wiki=_wk)
    sjekk("OBOS: Wikipedia har Hødd-Odd 3-3 mot vårt 2-3: konflikt",
          any("kontrollen mot Wikipedia" in c and "Hødd-Odd (2026-10-03): vi har 2-3, Wikipedia har 3-3" in c for c in _st["conflicts"]),
          str(_st["conflicts"]))
    _ok_rr17 = Path(_tf2.mkdtemp()); (_ok_rr17 / "obos" / "data").mkdir(parents=True)
    _shr.copy(_sbo / "results_state.json", _ok_rr17 / "obos" / "data" / "results_state.json")
    sjekk("og kjøringen er rød (resultatregel.py sjekk obos)", _regel.sjekk("obos", rot=_ok_rr17) == 1)
    sjekk("Wikipedia mangler Haugesund-Stabæk, publisert med en uavhengig kilde: advarsel, ikke konflikt",
          any(a.startswith("Haugesund-Stabæk (2026-10-03): vi har 2-0, Wikipedia mangler resultatet")
              and "bekreftet av en uavhengig kilde ved publiseringen" in a for a in _st.get("advarsler", []))
          and not any("Haugesund-Stabæk" in c for c in _st["conflicts"]), f"{_st.get('advarsler')} {_st['conflicts']}")
    sjekk("og tilstanden husker hvor mange resultater Wikipedia har (kilde_stoppet)",
          _st.get("kilder", {}).get("wikipedia", {}).get("resultater") == len(_wk), str(_st.get("kilder")))
    _wk[("Hødd", "Odd")] = (2, 3)
    _kode, _st, _ = _kjor(_dt(2026, 10, 7, 12, 10, tzinfo=_tz.utc), wiki=_wk)
    _shr.copy(_sbo / "results_state.json", _ok_rr17 / "obos" / "data" / "results_state.json")
    sjekk("Wikipedia retter Hødd-Odd: ingen konflikt, kjøringen grønn, advarselen om Haugesund-Stabæk står",
          not _st["conflicts"] and _regel.sjekk("obos", rot=_ok_rr17) == 0
          and any("Haugesund-Stabæk" in a for a in _st.get("advarsler", [])), f"{_st['conflicts']} {_st.get('advarsler')}")
    # Over LOGG_TAK (40) i døgnet: ingen kall bare for loggen.
    _shr.copy(ROT / "tests" / "data" / "2026-10-01" / "obos" / "data" / "matches.json", _sbo / "matches.json")
    (_sbo / "results_state.json").unlink()
    _ekte_bruk = _hls.dagsbruk
    _hls.dagsbruk = lambda dag=None: 45
    try:
        _kode, _st, _pub, _ut = _kjor_ut(_dt(2026, 10, 3, 18, 43, tzinfo=_tz.utc), {})
    finally:
        _hls.dagsbruk = _ekte_bruk
    sjekk("45 kall i dag (over 40): Highlightly spørres ikke bare for loggen, og det står i loggen",
          _hl_kall == [] and "over 40" in _ut, f"{_hl_kall} {_ut[-400:]}")
finally:
    for _n, _v in _ekte.items():
        setattr(_obr, _n, _v)
    _obr.time.sleep, sys.argv, _hls._http = _ekte_sleep, _ekte_argv, _ekte_hlhttp

print("\n=== Eliteserien: nye resultater med regelen (update_data.kontroller_nye_resultater) ===")
# Lagrede svar: ESPN-sesongen 3.10. (to feil 0-0 fra 29.5.) og Highlightly per
# dato. Ligasiden har de riktige resultatene. Testdataene fra 1.10. med
# kampene 29.5. og 20.9. tatt ut av det publiserte, så de er nye.
import update_data as _udr
_espn_ses = lambda aar: __import__("espn_source").tolk(json.loads((TESTDATA / "espn_sesong_2026-10-03.json").read_text("utf-8"))["events"])[0]
def _hl_es(d):
    sti = _HLD / f"dag_{d}.json"
    if not sti.exists():
        return []
    return [_hls.parse_kamp(m, "eliteserien") for m in json.loads(sti.read_text("utf-8")) if m["league"]["id"] == _hls.LIGA_ID["eliteserien"]]
_es_m = json.loads((ROT / "tests" / "data" / "2026-10-01" / "eliteserien" / "data" / "matches.json").read_text("utf-8"))
_nye_d = ("2026-05-29", "2026-09-20")
_tidl = [m for m in _es_m if m["date"] not in _nye_d]
_merged = [{**m, "src": "ntf"} for m in _es_m]
_liga = [dict(m) for m in _es_m]
_sbs = Path(_tf2.mkdtemp())
def _kjor_es(naa, hl=_hl_es, espn=_espn_ses, state=None):
    _st = _sbs / "results_state.json"
    if state is None and _st.exists():
        _st.unlink()
    _udr.LIGAKILDE = "ligasiden"
    _ut, _s = _udr.kontroller_nye_resultater([dict(r) for r in _merged], _tidl, _liga, [], [], naa, log=lambda _x: None,
                                             hl_dag=hl, espn_sesong=espn, state_sti=_st)
    return {(r["home"], r["away"]): (r["hg"], r["ag"]) for r in _ut}, _s
_naa_es = _dt(2026, 9, 20, 23, 0, tzinfo=ZoneInfo("Europe/Oslo"))
_r, _s = _kjor_es(_naa_es)
_nye = [(m["home"], m["away"]) for m in _es_m if m["date"] in _nye_d]
sjekk(f"ligasiden, ESPN og Highlightly: alle {len(_nye)} nye resultatene (29.5. og 20.9.) publiseres",
      all(_r[k] == next((m["hg"], m["ag"]) for m in _es_m if (m["home"], m["away"]) == k) for k in _nye) and not _s["conflicts"],
      f"{[(k, _r[k]) for k in _nye if _r[k][0] is None]} {_s}")
sjekk("Vålerenga-Kristiansund 3-1 og Aalesund-HamKam 2-2 publiseres selv om ESPN har 0-0 (Highlightly er enig med ligasiden)",
      _r[("Vålerenga", "Kristiansund")] == (3, 1) and _r[("Aalesund", "HamKam")] == (2, 2), str((_r[("Vålerenga", "Kristiansund")], _r[("Aalesund", "HamKam")])))
# Uten Highlightly, 2,5 time etter avspark 29.5.: ESPN sitt 0-0 er uenig med
# ligasiden. Aalesund-HamKam blir konflikt (ESPN 0-0 uten vinnermerke);
# Vålerenga-Kristiansund har ESPN merket mistenkelig (0-0 med vinner), så der
# finnes ingen uavhengig kilde: vent. Ingen av dem publiseres.
def _hl_nede(d):
    raise RuntimeError("Highlightly svarer ikke")
_r, _s = _kjor_es(_dt(2026, 5, 29, 21, 30, tzinfo=ZoneInfo("Europe/Oslo")), hl=_hl_nede)
sjekk("uten Highlightly: et 0-0 fra ESPN som er uenig med ligasiden, publiseres aldri; Aalesund-HamKam er konflikt",
      _r[("Aalesund", "HamKam")] == (None, None) and _r[("Vålerenga", "Kristiansund")] == (None, None)
      and any("Aalesund-HamKam" in c for c in _s["conflicts"]) and any("Vålerenga-Kristiansund" in w for w in _s["waiting"]),
      f"{_s['conflicts']} {_s['waiting'][:3]}")
sjekk("og de andre kampene 29.5., der ESPN er enig med ligasiden, publiseres",
      _r[("Brann", "Sarpsborg 08")] == (1, 2) and _r[("Fredrikstad", "Start")] == (2, 1), str((_r[("Brann", "Sarpsborg 08")], _r[("Fredrikstad", "Start")])))
# Bekreftelsen (12.10.2026): hvilke kilder utenfor NTF som hadde resultatet da det ble publisert.
import resultatregel as _rrb
_r, _s = _kjor_es(_naa_es)
_b_bekr = _s.get("bekreftet", {})
sjekk(f"Eliteserien: alle {len(_nye)} nye resultatene (29.5. og 20.9.) står som bekreftet, hvert med riktig resultat og minst én kilde utenfor NTF",
      set(_b_bekr) == {f"{k[0]}|{k[1]}" for k in _nye}
      and all(tuple(_b_bekr[f"{k[0]}|{k[1]}"]["resultat"]) == _r[k] and _b_bekr[f"{k[0]}|{k[1]}"]["kilder"]
              and not {"ligasiden", "fotball.no"} & set(_b_bekr[f"{k[0]}|{k[1]}"]["kilder"]) for k in _nye), str(_b_bekr)[:400])
sjekk("Vålerenga-Kristiansund 3-1 er bekreftet av highlightly alene (ESPN hadde 0-0 og teller ikke)",
      _b_bekr.get("Vålerenga|Kristiansund") == {"resultat": [3, 1], "kilder": ["highlightly"], "publisert": _naa_es.isoformat(timespec="seconds")},
      str(_b_bekr.get("Vålerenga|Kristiansund")))
_udr.skriv_state(_s, _naa_es, state_sti=_sbs / "results_state.json")
sjekk("skriv_state skriver feltet til results_state.json",
      json.loads((_sbs / "results_state.json").read_text("utf-8")).get("bekreftet") == _b_bekr)
# Neste kjøring, ti minutter senere, uten noe nytt (alt er publisert): feltet
# må overleve, ellers vet ikke den nye tabellsjekken at resultatet er bekreftet.
_ut_b, _s_b = _udr.kontroller_nye_resultater([dict(r) for r in _merged], [dict(m) for m in _es_m], _liga, [], [],
                                             _naa_es + _td(minutes=10), log=lambda _x: None, hl_dag=_hl_nede,
                                             espn_sesong=lambda aar: (_ for _ in ()).throw(RuntimeError("skal ikke kalles")),
                                             state_sti=_sbs / "results_state.json")
sjekk("neste kjøring uten nye resultater (ingen kilder spørres): bekreftelsene står", _s_b.get("bekreftet") == _b_bekr, str(_s_b.get("bekreftet"))[:300])
# Etter 24 timer uten uavhengig kilde: ligasiden alene, ukontrollert (rødt),
# men Aalesund-HamKam er fortsatt konflikt (ESPN er uenig).
_r, _s = _kjor_es(_dt(2026, 5, 31, 12, 0, tzinfo=ZoneInfo("Europe/Oslo")), hl=_hl_nede)
sjekk("etter 24 timer: Vålerenga-Kristiansund publiseres uten kontroll; Aalesund-HamKam holdes fortsatt tilbake",
      _r[("Vålerenga", "Kristiansund")] == (3, 1) and _s["ukontrollert"] == {("Vålerenga", "Kristiansund"): (3, 1)}
      and _r[("Aalesund", "HamKam")] == (None, None), str(_s))
sjekk("publisert uten kontroll etter 24 timer (bare ligasiden): Vålerenga-Kristiansund står IKKE som bekreftet",
      _s["ukontrollert"] == {("Vålerenga", "Kristiansund"): (3, 1)} and "Vålerenga|Kristiansund" not in _s.get("bekreftet", {}),
      str(_s.get("bekreftet"))[:300])
_udr.skriv_state(_s, _dt(2026, 5, 31, 12, 0, tzinfo=_tz.utc), state_sti=_sbs / "results_state.json")
_ok_es = Path(_tf2.mkdtemp()); (_ok_es / "eliteserien" / "data").mkdir(parents=True)
_shr.copy(_sbs / "results_state.json", _ok_es / "eliteserien" / "data" / "results_state.json")
sjekk("og kjøringen er rød (resultatregel.py sjekk eliteserien)", _regel.sjekk("eliteserien", rot=_ok_es) == 1)
# En time senere svarer Highlightly: bekreftet, og grønt.
_tidl2 = _tidl + [m for m in _es_m if (m["home"], m["away"]) == ("Vålerenga", "Kristiansund")]
_tidl_lagret = _tidl
_tidl = _tidl2
try:
    _r, _s = _kjor_es(_dt(2026, 5, 31, 13, 30, tzinfo=ZoneInfo("Europe/Oslo")), state=True)
finally:
    _tidl = _tidl_lagret
sjekk("en time senere bekrefter Highlightly 3-1: ikke lenger uten kontroll",
      _s["ukontrollert"] == {}, str(_s))
# Én linje per resultat og hvem som hadde det først (4.10.2026): Brann-Sarpsborg
# 08 (29.5.) er over, men ligasiden har det ikke ennå; ESPN og Highlightly har.
_kBS = ("Brann", "Sarpsborg 08")
_bs = next(m for m in _es_m if (m["home"], m["away"]) == _kBS)
_tidl_bs = [m for m in _es_m if (m["home"], m["away"]) != _kBS]
_hl_tell = []
def _hl_telle(d):
    _hl_tell.append(d)
    return _hl_es(d)
def _kjor_es_bs(naa, har_liga, bruk=0, behold=False):
    _st = _sbs / "results_state_bs.json"
    if not behold and _st.exists():
        _st.unlink()
    merged = [dict(r, src="ntf") if (r["home"], r["away"]) != _kBS or har_liga else {**r, "hg": None, "ag": None, "src": None} for r in _es_m]
    liga = [r for r in _es_m if (r["home"], r["away"]) != _kBS or har_liga]
    logg = []
    _hl_tell.clear()
    _ut, _s = _udr.kontroller_nye_resultater(merged, _tidl_bs, liga, [], [], naa, log=logg.append, hl_dag=_hl_telle,
                                             espn_sesong=_espn_ses, state_sti=_st, hl_bruk=lambda: bruk)
    _udr.skriv_state(_s, naa, state_sti=_st)
    return {(r["home"], r["away"]): (r["hg"], r["ag"]) for r in _ut}, _s, "\n".join(logg)
_t_bs = _kickoff_utc_bs = __import__("datetime").datetime.fromisoformat(f"{_bs['date']}T{_bs['time']}:00").replace(tzinfo=ZoneInfo("Europe/Oslo"))
_r, _s, _lg = _kjor_es_bs(_t_bs + _td(minutes=120), har_liga=False)
sjekk(f"Brann-Sarpsborg 08 over, ligasiden har det ikke: Highlightly spørres for {_bs['date']}, og linjen sier hvem som har det",
      _hl_tell == [_bs["date"]] and _r[_kBS] == (None, None)
      and "Brann-Sarpsborg 08: ligasiden har ikke resultatet ennå (espn 1-2, highlightly 1-2), venter" in _lg, f"{_hl_tell} {_lg}")
_r, _s, _lg = _kjor_es_bs(_t_bs + _td(minutes=130), har_liga=True, behold=True)
_tid = lambda m: (_t_bs + _td(minutes=m)).strftime("%H.%M")
sjekk("ti minutter senere har ligasiden det: publisert, og hvem som hadde det først",
      _r[_kBS] == (1, 2) and "Brann-Sarpsborg 08 1-2: ligasiden og espn enige, publisert" in _lg
      and f"Brann-Sarpsborg 08: espn {_tid(120)}, highlightly {_tid(120)}, ligasiden {_tid(130)}" in _lg, _lg)
_r, _s, _lg = _kjor_es_bs(_t_bs + _td(minutes=120), har_liga=False, bruk=45)
sjekk("45 kall i dag (over 40): Highlightly spørres ikke bare for loggen", _hl_tell == [] and "over LOGG_TAK" in _lg, f"{_hl_tell} {_lg}")

print("\n=== Reservekjeden for terminlisten (terminliste_reserve.py) ===")
# Ligasiden kan ikke brukes: kalenderfeeden, (ESPN i Eliteserien),
# Highlightly og til slutt den siste gyldige terminlisten. Spilte kamper står
# alltid som hos oss, og en kamp som har startet beholder avsparket vårt.
# Lagrede svar: feeden 3.10. kl. 18.49, Highlightly- og ESPN-sesongen 3.10.,
# og terminlisten fra 1.10. som den siste gyldige.
import terminliste_reserve as _tlr
_naa_r = _dt(2026, 10, 3, 18, 33, tzinfo=_tz.utc)
def _forrige(l):
    return leaguedata.forrige_terminliste(ROT / "tests" / "data" / "2026-10-01" / l / "data", "2026")
_fo, _fe = _forrige("obos"), _forrige("eliteserien")
_kal3 = lambda: ntf_source.parse_kalender((TESTDATA / "ntf_obos_kalender_2026-10-03.ics").read_text("utf-8"), "obos")
_hl_obos = lambda: [_hls.parse_kamp(m, "obos") for m in {m["id"]: m for m in _hl_les("sesong_obos_2026")}.values()]
_feil = lambda: (_ for _ in ()).throw(RuntimeError("svarer ikke"))
_ix = lambda rader: {(m["home"], m["away"]): m for m in rader}
_r, _k = _tlr.kjede("obos", _fo, _naa_r, hent={"kalenderfeeden": _kal3, "highlightly": _hl_obos})
_ri, _fi = _ix(_r), _ix(_fo)
sjekk("OBOS: kalenderfeeden er første reserve, og alle 240 kampene står", _k == "kalenderfeeden" and len(_r) == 240, f"{_k} {len(_r)}")
sjekk("spilte kamper står som hos oss (resultat, dato og avspark)",
      all(_ri[k] == _fi[k] for k in _fi if _fi[k]["hg"] is not None))
sjekk("kamper som har startet, beholder avsparket vårt (feeden viser dem i UTC): Haugesund-Stabæk 16:00, Strømmen-Sandnes Ulf 14:30",
      (_ri[("Haugesund", "Stabæk")]["time"], _ri[("Strømmen", "Sandnes Ulf")]["time"]) == ("16:00", "14:30"),
      str((_ri[("Haugesund", "Stabæk")], _ri[("Strømmen", "Sandnes Ulf")])))
sjekk("kommende kamper får dato, avspark og runde fra feeden: Sogndal-Raufoss 21.10. 19:00 runde 24, Ranheim-Sogndal 1.11. 14:30",
      (_ri[("Sogndal", "Raufoss")]["date"], _ri[("Sogndal", "Raufoss")]["time"], _ri[("Sogndal", "Raufoss")]["round"]) == ("2026-10-21", "19:00", 24)
      and _ri[("Ranheim", "Sogndal")]["time"] == "14:30", str((_ri[("Sogndal", "Raufoss")], _ri[("Ranheim", "Sogndal")])))
# Feeden mangler en kommende kamp: neste reserve (Highlightly).
_kal_uten = lambda: [m for m in _kal3() if (m["home"], m["away"]) != ("Bryne", "Raufoss")]
_r, _k = _tlr.kjede("obos", _fo, _naa_r, hent={"kalenderfeeden": _kal_uten, "highlightly": _hl_obos})
_ri = _ix(_r)
sjekk("feeden mangler Bryne-Raufoss: den brukes ikke, Highlightly tar over (med runden fra Highlightly)",
      _k == "highlightly" and (_ri[("Bryne", "Raufoss")]["date"], _ri[("Bryne", "Raufoss")]["round"]) == ("2026-10-14", 26), f"{_k} {_ri[('Bryne', 'Raufoss')]}")
sjekk("og Highlightly sine resultater for kamper som har startet, er med (de går gjennom regelen før de publiseres)",
      (_ri[("Haugesund", "Stabæk")]["hg"], _ri[("Haugesund", "Stabæk")]["ag"]) == (2, 0) and _ri[("Haugesund", "Stabæk")]["time"] == "16:00",
      str(_ri[("Haugesund", "Stabæk")]))
_r, _k = _tlr.kjede("obos", _fo, _naa_r, hent={"kalenderfeeden": _feil, "highlightly": _feil})
sjekk("ingen reserve svarer: den siste gyldige terminlisten, uendret", _k == "forrige terminliste" and _r == _fo, _k)
# Eliteserien: feeden svarer ikke, ESPN tar over (runden fra den lagrede).
_espn3 = lambda: __import__("espn_source").tolk(json.loads((TESTDATA / "espn_sesong_2026-10-03.json").read_text("utf-8"))["events"])[0]
_r, _k = _tlr.kjede("eliteserien", _fe, _naa_r, hent={"kalenderfeeden": _feil, "espn": _espn3, "highlightly": _feil})
_ri, _fi = _ix(_r), _ix(_fe)
sjekk("Eliteserien: feeden svarer ikke, ESPN er reserve; runden fra den lagrede terminlisten (runde 12 står som runde 12)",
      _k == "espn" and len(_r) == 240 and _ri[("Viking", "Tromsø")]["round"] == 12 and _ri[("Viking", "Tromsø")]["time"] == "14:30",
      f"{_k} {_ri[('Viking', 'Tromsø')]}")
sjekk("ESPN sine feil 0-0 endrer aldri et publisert resultat (Vålerenga-Kristiansund 3-1, Aalesund-HamKam 2-2)",
      (_ri[("Vålerenga", "Kristiansund")]["hg"], _ri[("Vålerenga", "Kristiansund")]["ag"]) == (3, 1)
      and (_ri[("Aalesund", "HamKam")]["hg"], _ri[("Aalesund", "HamKam")]["ag"]) == (2, 2), str(_ri[("Vålerenga", "Kristiansund")]))

print("\n=== Den daglige kontrollen mot ESPN, Highlightly og OddsPapi (daglig_revisjon.revider_kontroller) ===")
# Bare kommende kamper. Én kontroll som er uenig: advarsel. To kontroller
# som er enige med hverandre om en annen dato enn vår: avvik (rødt).
_ve = {k: dict(m) for k, m in _fasit_alle["eliteserien"].items()}
_vo = {k: dict(m) for k, m in _fasit_alle["obos"].items()}
_kes = {"ESPN": {(r["home"], r["away"]): r for r in _espn3()},
        "Highlightly": {(r["home"], r["away"]): r for r in (_hls.parse_kamp(m, "eliteserien") for m in
                        {m["id"]: m for m in _hl_les("sesong_eliteserien_2026")}.values())}}
_f, _a = _drk.revider_kontroller(_ve, _kes, _naa_r)
sjekk("Eliteserien 3.10.: terminlisten fra 1.10. mot ESPN og Highlightly: ingen avvik og ingen advarsler", (_f, _a) == ([], []), f"{_f} {_a[:3]}")
_kos = {"Highlightly": {(r["home"], r["away"]): r for r in _hl_obos()}}
_f, _a = _drk.revider_kontroller(_vo, _kos, _naa_r)
sjekk("OBOS 3.10.: mot Highlightly: ingen avvik og ingen advarsler (dagens kamper som har startet, er ikke med)", (_f, _a) == ([], []), f"{_f} {_a[:3]}")
_ve2 = {k: dict(m) for k, m in _ve.items()}
_ve2[("Brann", "Viking")]["date"] = "2026-10-10"
_f, _a = _drk.revider_kontroller(_ve2, _kes, _naa_r)
sjekk("vi har en annen dato enn både ESPN og Highlightly: avvik (to leverandører enige)",
      _f == ["Brann-Viking: dato 2026-10-10 hos oss, 2026-10-09 hos både ESPN og Highlightly"], f"{_f} {_a}")
_kes2 = {"ESPN": dict(_kes["ESPN"]), "Highlightly": _kes["Highlightly"]}
_kes2["ESPN"][("Brann", "Viking")] = {**_kes["ESPN"][("Brann", "Viking")], "date": "2026-10-10"}
_f, _a = _drk.revider_kontroller(_ve, _kes2, _naa_r)
sjekk("bare én kontroll (ESPN) har en annen dato: advarsel, ikke avvik",
      _f == [] and _a == ["Brann-Viking: dato 2026-10-09 hos oss, 2026-10-10 hos ESPN"], f"{_f} {_a}")
_kos2 = {"Highlightly": dict(_kos["Highlightly"]), "OddsPapi": {("Bryne", "Raufoss"): {"date": "2026-10-14", "time": "17:00"}}}
_f, _a = _drk.revider_kontroller(_vo, _kos2, _naa_r)
sjekk("OBOS: OddsPapi med annet avspark (17:00 mot 19:00): advarsel",
      _f == [] and _a == ["Bryne-Raufoss: avspark 19:00 hos oss, 17:00 hos OddsPapi"], f"{_f} {_a}")

print("\n=== Kontrollkildene hentes én gang i døgnet (daglig_revisjon.kontroller_i_dag) ===")
# Porten slipper revisjonen gjennom hvert tiende minutt mens en kamp venter på
# resultat. Hele sesongen fra Highlightly er 4 kall, og dagstaket (60) skal
# holde til resultatkontrollen. Blokken går gjennom JSON som i audit_fixtures.json.
_hentet = []
def _hent_kontroll(liga, vaare, naa):
    _hentet.append(naa)
    return {k: dict(v) for k, v in _kes2.items()}, ["kontrollen mot OddsPapi kunne ikke kjøres (Test: nede)"]
_tur = lambda b: json.loads(json.dumps(b, ensure_ascii=False))
_k1 = _drk.kontroller_i_dag("eliteserien", _ve2, _naa_r, None, hent=_hent_kontroll)
sjekk("første revisjon i døgnet henter kontrollene: ett kall til henteren, funnene som revider_kontroller gir",
      len(_hentet) == 1 and _k1[4] is False and _k1[0] == ["ESPN", "Highlightly"]
      and _k1[1] == _drk.revider_kontroller(_ve2, _kes2, _naa_r)[0]
      and _k1[2] == _drk.revider_kontroller(_ve2, _kes2, _naa_r)[1] + ["kontrollen mot OddsPapi kunne ikke kjøres (Test: nede)"],
      f"{len(_hentet)} {_k1[:3]}")
sjekk("og funnene er ikke tomme (Brann-Viking: en annen dato hos Highlightly, ESPN enig med oss)",
      any("Brann-Viking" in t for t in _k1[2]), str(_k1[2]))
_k2 = _drk.kontroller_i_dag("eliteserien", _ve2, _naa_r + _td(hours=3), {"kontroller": _tur(_k1[3])}, hent=_hent_kontroll)
sjekk("tre timer senere samme dag: ingen ny henting, de samme funnene og de samme kildene",
      len(_hentet) == 1 and _k2[4] is True and _k2[:3] == _k1[:3], f"{len(_hentet)} {_k2[:3]}")
_ve3 = {k: dict(m) for k, m in _ve2.items()}
_ve3[("Brann", "Viking")]["date"] = "2026-10-09"
_k3 = _drk.kontroller_i_dag("eliteserien", _ve3, _naa_r + _td(hours=3), {"kontroller": _tur(_k1[3])}, hent=_hent_kontroll)
sjekk("vår dato er endret siden: funnet for kampen gjelder ikke lenger (sjekkes på nytt i morgen)",
      len(_hentet) == 1 and not any("Brann-Viking" in t for t in _k3[1] + _k3[2]) and _k3[2][-1].startswith("kontrollen mot OddsPapi"),
      str(_k3[1:3]))
_bv = _ve2[("Brann", "Viking")]
_etter_avspark = _dt.fromisoformat(f"{_bv['date']}T{_bv['time']}:00").replace(tzinfo=_drk.OSLO) + _td(minutes=5)
_blokk_fram = {**_tur(_k1[3]), "dato": _etter_avspark.strftime("%Y-%m-%d")}
_k4 = _drk.kontroller_i_dag("eliteserien", _ve2, _etter_avspark, {"kontroller": _blokk_fram}, hent=_hent_kontroll)
sjekk("kampen har startet: funnet for den er borte, uten ny henting",
      len(_hentet) == 1 and _k4[4] is True and not any("Brann-Viking" in t for t in _k4[1] + _k4[2]), str(_k4[1:3]))
_k5 = _drk.kontroller_i_dag("eliteserien", _ve2, _naa_r + _td(days=1), {"kontroller": _tur(_k1[3])}, hent=_hent_kontroll)
sjekk("neste dag: kontrollene hentes på nytt", len(_hentet) == 2 and _k5[4] is False and _k5[3]["dato"] != _k1[3]["dato"],
      f"{len(_hentet)} {_k5[3].get('dato')} {_k1[3].get('dato')}")
_src_dr = Path(_drk.__file__).read_text(encoding="utf-8")
_hoved = _src_dr[_src_dr.index("def main("):]
sjekk("revisjonen henter kontrollene bare gjennom kontroller_i_dag, og lagrer blokken i audit_fixtures.json",
      "kontroller_i_dag(" in _hoved and "hent_kontroller(" not in _hoved and '"kontroller": _kblokk' in _hoved)

print("\n=== Etterkontrollen mot football-data.co.uk (Eliteserien) ===")
# NOR.csv 3.10.2026 (bare 2026-radene): fetch_odds_history tar nå med
# sluttresultatet (HG/AG), og den daglige revisjonen sammenligner de
# publiserte resultatene med dem. Uenig: avvik. Mangler: ikke et avvik.
import fetch_odds_history as _foh
_fd = _foh.parse((TESTDATA / "nor_2026-10-03.csv").read_text("utf-8"))
sjekk("NOR.csv 3.10.: 168 kamper med sluttodds og sluttresultat", len(_fd) == 168 and all("hg" in r for r in _fd), str(len(_fd)))
_f, _a = _drk.etterkontroll_football_data(_es_m, _fd)
sjekk("de publiserte resultatene fra 1.10. er de samme som hos football-data.co.uk", (_f, _a) == ([], []), str(_f[:3]))
_es_feil = [dict(m) for m in _es_m]
_es_feil[0]["hg"] += 1
_f, _a = _drk.etterkontroll_football_data(_es_feil, _fd)
sjekk(f"et annet resultat hos oss ({_es_feil[0]['home']}-{_es_feil[0]['away']}): avvik", len(_f) == 1 and "football-data.co.uk" in _f[0], str(_f))
_f, _a = _drk.etterkontroll_football_data(_es_m, [r for r in _fd if r["date"] < "2026-09-01"])
sjekk("kamper football-data ikke har ennå: ikke et avvik", _f == [], str(_f))

print("\n=== Flyttede kamper: samme regel som siden (leaguedata.flyttede, 4.10.2026) ===")
# En kamp mer enn RUNDE_SAMLET_DAGER (6) dager fra mediandatoen i runden er
# flyttet ut av runden, utsatt eller flyttet fram -- som flyttetFraRunde på
# siden. Bildet fra 1.10. (tests/data): alle 240 kampene i hver liga.
def _alle_kamper(liga):
    d = ROT / "tests" / "data" / "2026-10-01" / liga / "data"
    spilt = json.loads((d / "matches.json").read_text("utf-8"))
    fx = json.loads((d / "fixtures.json").read_text("utf-8"))
    sett = {(m["home"], m["away"]) for m in spilt}
    return [dict(m) for m in spilt] + [{"date": m["date"], "time": m.get("time"), "round": r["round"], "home": m["home"],
            "away": m["away"], "hg": None, "ag": None} for r in fx for m in r["matches"] if (m["home"], m["away"]) not in sett]
_ventet_flyttet = {
    "eliteserien": {"Sarpsborg 08-Bodø/Glimt", "Tromsø-Lillestrøm", "Tromsø-Brann", "Bodø/Glimt-Start", "Start-Bodø/Glimt",
                    "Lillestrøm-Kristiansund", "Aalesund-Brann", "Bodø/Glimt-HamKam", "Lillestrøm-Viking"},
    "obos": {"Egersund-Raufoss", "Ranheim-Strømmen", "Sogndal-Raufoss"}}
for _liga in ("eliteserien", "obos"):
    _alle = _alle_kamper(_liga)
    _per = {}
    for _m in _alle:
        _per.setdefault(_m["round"], []).append(_m)
    _funnet = set()
    for _g in _per.values():
        _ids = leaguedata.flyttede(_g)
        _funnet |= {f"{m['home']}-{m['away']}" for m in _g if id(m) in _ids}
    _om = {"eliteserien": ", med to utsatt til samme dag (runde 8) og tre flyttet fram (runde 15, 17, 18)",
           "obos": ", med Sogndal-Raufoss (runde 24, 21.10.)"}[_liga]
    sjekk(f"{_liga}: flyttede kamper etter medianregelen: {len(_funnet)} (som siden){_om}",
          len(_alle) == 240 and _funnet == _ventet_flyttet[_liga], f"{len(_alle)} kamper; ekstra {_funnet - _ventet_flyttet[_liga]}, mangler {_ventet_flyttet[_liga] - _funnet}")
_fx_es = leaguedata.build_fixtures(_alle_kamper("eliteserien"))
_fx_ob = leaguedata.build_fixtures(_alle_kamper("obos"))
_rek = [r["round"] for r in _fx_es]
sjekk("Eliteserien: runde 12 (hele runden flyttet) står mellom 24 og 25 i fixtures.json, uten flyttede kamper",
      _rek.index(12) == _rek.index(24) + 1 and _rek.index(25) == _rek.index(12) + 1
      and not any(m.get("moved") for r in _fx_es if r["round"] == 12 for m in r["matches"]), str(_rek))
_r24 = next(r for r in _fx_ob if r["round"] == 24)
sjekk("OBOS: i runde 24 er bare Sogndal-Raufoss merket flyttet, og datospennet regnes uten den (2. til 5. okt)",
      [f"{m['home']}-{m['away']}" for m in _r24["matches"] if m.get("moved")] == ["Sogndal-Raufoss"] and _r24["when"] == "2. til 5. okt",
      str((_r24["when"], [m for m in _r24["matches"] if m.get("moved")])))

print("\n=== OBOS-odds: varsel når en kamp mangler odds et døgn før avspark (obos_upcoming_odds, 7.10.2026) ===")
# Erstatter målingen av når OddsPapi fikk oddsen (odds_aapning.json, 4.10.):
# mangler en uspilt kamp odds i odds_upcoming.json når det er under et døgn
# til avspark, er det en ADVARSEL. Ingen linje når alt er i orden.
import obos_upcoming_odds as _ouo
_OSLO_O = ZoneInfo("Europe/Oslo")
sjekk("målingen er borte: ingen odds_aapning/oddsaapning i skriptet, ingen odds_forventet i leaguedata",
      not any(hasattr(_ouo, n) for n in ("oddsaapning", "AAPNING_PATH", "LISTE_TID")) and not hasattr(leaguedata, "odds_forventet")
      and "odds_aapning" not in (ROT / "scripts" / "obos_upcoming_odds.py").read_text("utf-8").split("Varselet (7.10.2026)")[0], "")
_mo = lambda h, b, d, t, hg=None: {"home": h, "away": b, "date": d, "time": t, "hg": hg}
_naa_o = _dt(2026, 10, 10, 16, 0, tzinfo=_tz.utc)   # lørdag 18.00 norsk tid
_kampene = [_mo("A", "B", "2026-10-11", "17:00"),      # om 23 t
            _mo("C", "D", "2026-10-11", "19:00"),      # om 25 t
            _mo("E", "F", "2026-10-10", "17:30"),      # startet for 30 min siden
            _mo("G", "H", "2026-10-11", None),         # uten klokkeslett: fra midnatt
            _mo("I", "J", "2026-10-11", "12:00", hg=2)]  # spilt (flyttet fram)
_mangl = _ouo.manglende_odds(_naa_o, _kampene, set())
sjekk("innen et døgn og ikke startet: A-B (om 23 t) og G-H (uten klokkeslett, regnet fra midnatt); ikke C-D (25 t), E-F (startet) eller spilt",
      [(m["home"], a.astimezone(_OSLO_O).strftime("%d.%m %H:%M")) for m, a in _mangl] == [("G", "11.10 00:00"), ("A", "11.10 17:00")], str(_mangl))
sjekk("med odds: ingen varsel", _ouo.manglende_odds(_naa_o, _kampene, {("A", "B"), ("G", "H")}) == [], "")
sjekk("grensen: nøyaktig 24 t før avspark varsles, 24 t og 1 min før ikke",
      len(_ouo.manglende_odds(_dt(2026, 10, 10, 15, 0, tzinfo=_tz.utc), _kampene[:1], set())) == 1
      and not _ouo.manglende_odds(_dt(2026, 10, 10, 14, 59, tzinfo=_tz.utc), _kampene[:1], set()), "")

print("\n=== OBOS-odds: hele skriptet med OddsPapi i en sandkasse (obos_upcoming_odds.main) ===")
# hasOdds false: ikke slått opp, og ingen linje. 404 for en kamp med hasOdds
# true: egen ADVARSEL. Andre feil: FEIL som før. Og varselet et døgn før
# avspark, med grunnen.
_sbo2 = Path(_tf2.mkdtemp())
for _f in ("matches.json", "fixtures.json"):
    _shr.copy(ROT / "tests" / "data" / "2026-10-01" / "obos" / "data" / _f, _sbo2 / _f)
_alle_o = _alle_kamper("obos")
_ekte_ou = {n: getattr(_ouo, n) for n in ("ROOT", "DATA", "OUT_PATH", "SEASON_CACHE", "COOLDOWN",
                                           "csv_2026", "fetch_markets", "find_1x2", "closing_from", "datetime")}
_ekte_op = {n: getattr(_ouo.oddspapi, n) for n in ("call", "call_retry", "usage")}
_ekte_argv_o, _gha_o = sys.argv, _osu.environ.get("GITHUB_ACTIONS")
_op_oppslag = []
def _kjor_o(naa, har_odds, spilt=(), svar_ok=(), svar_feil="HTTP 404: No historical odds found", nokkel=True):
    """har_odds: kampene OddsPapi sier har odds (hasOdds); svar_ok: de av dem
    oppslaget gir odds for (resten får svar_feil)."""
    class _D(_dt):
        @classmethod
        def now(cls, tz=None):
            return naa if tz is None else naa.astimezone(tz)
    _sett, _ok = set(spilt), set(svar_ok)
    _ouo.csv_2026 = lambda: [dict(m, hg=m.get("hg") if m.get("hg") is not None else (1 if (m["home"], m["away"]) in _sett else None))
                             for m in _alle_o]
    (_sbo2 / "oddspapi_fixtures_2026.json").write_text(json.dumps({"fetched_at": (naa - _td(hours=2)).isoformat(timespec="seconds"), "fixtures": [
        {"fixtureId": f"id-{m['home']}-{m['away']}", "participant1Name": m["home"], "participant2Name": m["away"],
         "hasOdds": (m["home"], m["away"]) in har_odds,
         "startTime": _dt.fromisoformat(f"{m['date']}T{m['time']}:00").replace(tzinfo=_OSLO_O).astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")}
        for m in _alle_o]}), encoding="utf-8")
    (_sbo2 / "odds_upcoming.json").unlink(missing_ok=True)
    _op_oppslag.clear()
    def _ikke_tellende(*a, **k):
        raise AssertionError("tellende kall til OddsPapi i testen")
    def _oppslag(sti, param, key, **k):
        _op_oppslag.append(param["fixtureId"])
        return ({"ok": param["fixtureId"]}, None) if param["fixtureId"] in {f"id-{h}-{b}" for h, b in _ok} else (None, svar_feil)
    _ouo.oddspapi.call = _ikke_tellende
    _ouo.oddspapi.call_retry = _oppslag
    _ouo.oddspapi.usage = lambda: (7, 250)
    _ouo.fetch_markets = lambda key: [{"marketId": 101}]
    _ouo.find_1x2 = lambda mk: {"marketId": 101}
    _ouo.closing_from = lambda svar, market_id, kickoff: ("pinnacle", {"H": 2.5, "U": 3.4, "B": 2.8}, "2026-10-10T14:00:00Z")
    _ouo.datetime = _D
    _ouo.ROOT, _ouo.DATA, _ouo.OUT_PATH = _sbo2.parent, _sbo2, _sbo2 / "odds_upcoming.json"
    _ouo.SEASON_CACHE, _ouo.COOLDOWN = _sbo2 / "oddspapi_fixtures_2026.json", 0
    sys.argv = ["obos_upcoming_odds.py"]
    _osu.environ["GITHUB_ACTIONS"] = "true"
    _osu.environ["ODDSPAPI_KEY"] = "test" if nokkel else ""
    _buf = _iou.StringIO()
    try:
        with _ctxu.redirect_stdout(_buf):
            _kode = _ouo.main()
    finally:
        for _n, _v in _ekte_ou.items():
            setattr(_ouo, _n, _v)
        for _n, _v in _ekte_op.items():
            setattr(_ouo.oddspapi, _n, _v)
        sys.argv = _ekte_argv_o
        if _gha_o is None:
            _osu.environ.pop("GITHUB_ACTIONS", None)
        else:
            _osu.environ["GITHUB_ACTIONS"] = _gha_o
    return _kode, _buf.getvalue()
_mk = ("Moss", "Kongsvinger")
_ekte_nokkel = _osu.environ.get("ODDSPAPI_KEY")
_r24_spilt = [(m["home"], m["away"]) for m in _alle_o if m["round"] == 24 and m["date"] <= "2026-10-04"]
_r25p = [(m["home"], m["away"]) for m in _alle_o if m["round"] == 25]
try:
    # Søndag 4.10. kl. 16.00 UTC: bare Moss-Kongsvinger (5.10. kl. 19.00, om
    # 25 t) har odds, og oppslaget gir 404. Runde 25 har ikke odds ennå.
    _k, _u = _kjor_o(_dt(2026, 10, 4, 16, 0, tzinfo=_tz.utc), {_mk}, spilt=_r24_spilt)
    sjekk("hasOdds false: ingen linje om kampene uten odds (det er normalt så langt fram)",
          "har ikke odds" not in _u and "OddsPapi har ikke odds ennå" not in _u and "Runde 25" not in _u, _u)
    sjekk("og de slås ikke opp: ett oppslag, for kampen med hasOdds", _op_oppslag == ["id-Moss-Kongsvinger"], str(_op_oppslag))
    sjekk("404 for en kamp med hasOdds true: egen advarsel, ikke FEIL",
          "ADVARSEL: Moss mot Kongsvinger: OddsPapi sier at kampen har odds (hasOdds), men oppslaget gir 404" in _u
          and "::warning title=OddsPapi: 404 med hasOdds::Moss mot Kongsvinger" in _u and "FEIL" not in _u, _u)
    sjekk("Moss-Kongsvinger er 25 t unna: ikke varslet ennå", "odds mangler før avspark" not in _u and _k == 0, _u)
    # Mandag 5.10. kl. 16.30 UTC, en halv time før Moss-Kongsvinger, med odds: ingen linje.
    _k, _u = _kjor_o(_dt(2026, 10, 5, 16, 30, tzinfo=_tz.utc), {_mk}, spilt=_r24_spilt, svar_ok={_mk})
    _skrevet = {(m["home"], m["away"]) for m in json.loads((_sbo2 / "odds_upcoming.json").read_text("utf-8"))["matches"]}
    sjekk("alt i orden en halv time før avspark: ingen ADVARSEL og ingen linje om manglende odds",
          "ADVARSEL" not in _u and "har ikke odds" not in _u and _mk in _skrevet and _k == 0, _u)
    # Samme tid, men oppslaget gir 404: varsel med grunnen, og «30 min til avspark».
    _k, _u = _kjor_o(_dt(2026, 10, 5, 16, 30, tzinfo=_tz.utc), {_mk}, spilt=_r24_spilt)
    sjekk("uten odds en halv time før: «Moss mot Kongsvinger har ikke odds, og det er 30 min til avspark (5.10. kl. 19.00): OddsPapi sier at kampen har odds, men oppslaget gir 404»",
          "  ADVARSEL: Moss mot Kongsvinger har ikke odds, og det er 30 min til avspark (5.10. kl. 19.00): "
          "OddsPapi sier at kampen har odds, men oppslaget gir 404\n" in _u
          and "::warning title=OddsPapi: odds mangler før avspark::Moss mot Kongsvinger" in _u, _u)
    # Lørdag 10.10. kl. 16.00 UTC, 23 t før runde 25 (11.10. kl. 17.00): sju av
    # åtte har odds, den første har ikke (hasOdds false).
    _k, _u = _kjor_o(_naa_o, set(_r25p[1:]), spilt=_r24_spilt + [_mk], svar_ok=set(_r25p[1:]))
    _h0, _b0 = _r25p[0]
    sjekk(f"23 t før runde 25: én ADVARSEL, for {_h0} mot {_b0}, med grunnen «OddsPapi har ikke odds for kampen ennå»",
          f"  ADVARSEL: {_h0} mot {_b0} har ikke odds, og det er 23 t til avspark (11.10. kl. 17.00): OddsPapi har ikke odds for kampen ennå\n" in _u
          and _u.count("ADVARSEL") == 1 and _u.count("::warning") == 1, _u)
    sjekk("de sju andre slås opp og står i odds_upcoming.json; runde 26 (14.10.) varsles ikke",
          sorted(_op_oppslag) == sorted(f"id-{h}-{b}" for h, b in _r25p[1:])
          and {(m["home"], m["away"]) for m in json.loads((_sbo2 / "odds_upcoming.json").read_text("utf-8"))["matches"]} >= set(_r25p[1:]), _u)
    # En annen feil enn 404: FEIL som før, og grunnen i varselet.
    _k, _u = _kjor_o(_naa_o, set(_r25p), spilt=_r24_spilt + [_mk], svar_ok=set(_r25p[1:]), svar_feil="HTTP 500: Internal Server Error")
    sjekk(f"annen feilkode: «{_h0} mot {_b0}: FEIL HTTP 500 ...», og varselet sier «oppslaget feilet (HTTP 500 ...)»",
          f"  {_h0} mot {_b0}: FEIL HTTP 500: Internal Server Error" in _u and "404" not in _u
          and f"{_h0} mot {_b0} har ikke odds, og det er 23 t til avspark (11.10. kl. 17.00): oppslaget feilet (HTTP 500: Internal Server Error)" in _u, _u)
    # Ingen nøkkel: oddsen hentes ikke, men varselet kommer likevel, for alle åtte.
    _k, _u = _kjor_o(_naa_o, set(_r25p), spilt=_r24_spilt + [_mk], nokkel=False)
    sjekk("uten ODDSPAPI_KEY: varsel for alle åtte i runde 25, med grunnen",
          sum(1 for l in _u.splitlines() if l.startswith("  ADVARSEL: ") and "har ikke odds, og det er 23 t til avspark" in l) == 8
          and _u.count("::warning title=OddsPapi: odds mangler før avspark::") == 8
          and "oddsen ble ikke hentet (ODDSPAPI_KEY er ikke satt)" in _u and _k == 1, _u)
    # Runde 25 har startet (11.10. kl. 15.30 UTC), uten odds: ingen varsel.
    _k, _u = _kjor_o(_dt(2026, 10, 11, 15, 30, tzinfo=_tz.utc), set(), spilt=_r24_spilt + [_mk])
    sjekk("kamper som har startet, varsles ikke", "har ikke odds" not in _u, _u)
finally:
    if _ekte_nokkel is None:
        _osu.environ.pop("ODDSPAPI_KEY", None)
    else:
        _osu.environ["ODDSPAPI_KEY"] = _ekte_nokkel
    _shr.rmtree(_sbo2, ignore_errors=True)

print("\n=== Pages-vakt: varsel når publiseringen henger (scripts/pages_vakt.py, 7.10.2026) ===")
# 6.10.: publiseringen av f3fe1df hang i deploy fra 15:17Z. Vakten gir
# livstegn til healthchecks når alt er publisert eller den eldste
# upubliserte commiten er under 30 min gammel, /fail når den er eldre, og
# ingenting når GitHub ikke svarer.
import pages_vakt as _pv
_u = lambda t: _dt.fromisoformat(t.replace("Z", "+00:00"))
_c = [("f3fe1df0", _u("2026-10-06T15:17:03Z"), "Grunnlag (obos) 2026-10-06T15:17Z")]
sjekk("ingen upubliserte commiter: ok", _pv.vurder([], "e36d60c0", _u("2026-10-06T16:00:00Z"))[0] == "ok")
sjekk("upublisert i 29 min: ok (publiseringen kan være i gang)", _pv.vurder(_c, "5f9a7440", _u("2026-10-06T15:46:03Z"))[0] == "ok")
sjekk("nøyaktig 30 min: fortsatt ok", _pv.vurder(_c, "5f9a7440", _u("2026-10-06T15:47:03Z"))[0] == "ok")
_t, _tx = _pv.vurder(_c, "5f9a7440", _u("2026-10-06T15:50:00Z"))
sjekk("32 min: henger, med commit, tid, alder og det siden viser",
      _t == "henger" and _tx == "Publiseringen henger: f3fe1df (Grunnlag (obos) 2026-10-06T15:17Z) kom til main 6.10. kl. 17.17 og er ikke "
      "publisert etter 32 min, og 1 commit(er) venter. Siden viser 5f9a744.", _tx)
# Alderen regnes fra pushen, ikke fra da commiten ble laget (7.10.2026): en
# commit laget lokalt 40 min før pushen gir ikke varsel rett etter pushen.
_lokal = [("abc12340", _u("2026-10-07T09:10:00Z"), "Laget lokalt")]
sjekk("commit laget 40 min før, pushet for 5 min siden: ok (regnet fra pushen)",
      _pv.vurder(_lokal, "def56780", _u("2026-10-07T09:50:00Z"), kom=_u("2026-10-07T09:45:00Z"))[0] == "ok")
sjekk("uten pushtid (ikke i aktivitetsloggen): fra da commiten ble laget",
      _pv.vurder(_lokal, "def56780", _u("2026-10-07T09:50:00Z"))[0] == "henger")
# Hele skriptet med GitHub-API-et byttet ut: 6.10., publiseringen av f3fe1df
# står på waiting, den forrige (5f9a744) er success.
_dep = [{"id": 2, "sha": "f3fe1df0"}, {"id": 1, "sha": "5f9a7440"}]
_stat = {2: [{"state": "waiting", "created_at": "2026-10-06T15:17:39Z"}],
         1: [{"state": "success", "created_at": "2026-10-06T15:13:16Z"}, {"state": "in_progress", "created_at": "2026-10-06T15:12:55Z"}]}
_cmp = {"status": "ahead", "commits": [{"sha": "f3fe1df0", "commit": {"committer": {"date": "2026-10-06T15:17:03Z"},
                                                                        "message": "Grunnlag (obos) 2026-10-06T15:17Z\n\nmer"}}]}
_ekte_pv = {n: getattr(_pv, n) for n in ("api", "ping", "datetime")}
_pv_ping = []
def _kjor_pv(naa, hc="https://hc-ping.com/test-uuid", feil=None, aktivitet=()):
    class _D(_dt):
        @classmethod
        def now(cls, tz=None):
            return naa if tz is None else naa.astimezone(tz)
    def _api(sti):
        if feil:
            raise OSError(feil)
        if sti.startswith("deployments?environment=github-pages"):
            return _dep
        if sti.startswith("deployments/"):
            return _stat[int(sti.split("/")[1])]
        if sti == "compare/5f9a7440...main":
            return _cmp
        if sti.startswith("activity?ref=refs/heads/main&activity_type=push"):
            if aktivitet is None:
                raise OSError("HTTP 403")
            return aktivitet
        raise AssertionError(sti)
    _pv.api, _pv.datetime = _api, _D
    _pv.ping = lambda url: _pv_ping.append(url) or True
    _pv_ping.clear()
    _gml = {k: _osu.environ.get(k) for k in ("HC_URL", "GITHUB_ACTIONS")}
    _osu.environ["HC_URL"], _osu.environ["GITHUB_ACTIONS"] = hc, "true"
    _buf = _iou.StringIO()
    try:
        with _ctxu.redirect_stdout(_buf):
            _kode = _pv.main()
    finally:
        for _n, _v in _ekte_pv.items():
            setattr(_pv, _n, _v)
        for _k, _v in _gml.items():
            if _v is None:
                _osu.environ.pop(_k, None)
            else:
                _osu.environ[_k] = _v
    return _kode, _buf.getvalue(), list(_pv_ping)
_k, _ut, _p = _kjor_pv(_u("2026-10-06T15:40:00Z"))
sjekk("6.10. kl. 15:40Z (23 min): livstegn, ikke /fail", _p == ["https://hc-ping.com/test-uuid"] and _k == 0
      and "1 commit(er) venter på publisering, den eldste (f3fe1df) kom til main for 22 min siden" in _ut, _ut)
# Pushen 20 min etter at commiten ble laget: kl. 15:50Z er den 13 min gammel på main.
_akt = [{"timestamp": "2026-10-06T15:37:00Z", "after": "f3fe1df0"}, {"timestamp": "2026-10-06T15:12:20Z", "after": "5f9a7440"}]
_k, _ut, _p = _kjor_pv(_u("2026-10-06T15:50:00Z"), aktivitet=_akt)
sjekk("pushet 20 min etter at commiten ble laget: kl. 15:50Z regnes 13 min fra pushen, livstegn",
      _p == ["https://hc-ping.com/test-uuid"] and "kom til main for 13 min siden" in _ut, _ut)
_k, _ut, _p = _kjor_pv(_u("2026-10-06T16:10:00Z"), aktivitet=_akt)
sjekk("... og kl. 16:10Z (33 min etter pushen): /fail, med pushtiden i teksten",
      _p == ["https://hc-ping.com/test-uuid/fail"] and "kom til main 6.10. kl. 17.37" in _ut, _ut)
_k, _ut, _p = _kjor_pv(_u("2026-10-06T15:50:00Z"), aktivitet=None)
sjekk("aktivitetsloggen svarer ikke: regnet fra da commiten ble laget (32 min, /fail), sagt i loggen",
      _p == ["https://hc-ping.com/test-uuid/fail"] and "aktivitetsloggen svarte ikke" in _ut, _ut)
_k, _ut, _p = _kjor_pv(_u("2026-10-06T15:50:00Z"))
sjekk("6.10. kl. 15:50Z (32 min): /fail til healthchecks og ::warning, men kjøringen er grønn",
      _p == ["https://hc-ping.com/test-uuid/fail"] and _k == 0 and "::warning title=Publiseringen henger::Publiseringen henger: f3fe1df" in _ut
      and "Siden viser 5f9a744." in _ut, _ut)
_k, _ut, _p = _kjor_pv(_u("2026-10-06T15:50:00Z"), hc="")
sjekk("uten HEALTHCHECK_PAGES: ingen ping, en ::warning om at vakten ikke kan varsle, grønn",
      _p == [] and _k == 0 and "HEALTHCHECK_PAGES er ikke satt" in _ut and "Publiseringen henger" in _ut, _ut)
_k, _ut, _p = _kjor_pv(_u("2026-10-06T15:50:00Z"), feil="HTTP 502")
sjekk("GitHub svarer ikke: ingenting sendes (dødmannsknappen tar det), grønn",
      _p == [] and _k == 0 and "sender ingenting" in _ut, _ut)
_wf = (ROT / ".github" / "workflows" / "pages-vakt.yml").read_text("utf-8")
_wf_kode = "\n".join(l for l in _wf.splitlines() if not l.strip().startswith("#"))
sjekk("pages-vakt.yml: etter «Oppdater kampdata» (alle utfall), etter publisering (page_build), hver time og manuelt, bare lesing, ingen concurrency, hemmeligheten fra secrets",
      'workflows: ["Oppdater kampdata"]' in _wf_kode and "types: [completed]" in _wf_kode
      and "  page_build:" in _wf_kode and 'cron: "7 * * * *"' in _wf_kode and "workflow_dispatch:" in _wf_kode and "planlagt:" in _wf_kode
      and "contents: read" in _wf_kode and "deployments: read" in _wf_kode and "write" not in _wf_kode
      and "concurrency" not in _wf_kode and "if:" not in _wf_kode
      and "HC_URL: ${{ secrets.HEALTHCHECK_PAGES }}" in _wf_kode and "python3 scripts/pages_vakt.py" in _wf_kode)
sjekk("planlegger/README.md har sjekken tabellkalkulator-pages og hemmeligheten",
      "`tabellkalkulator-pages`" in (ROT / "planlegger" / "README.md").read_text("utf-8")
      and "gh secret set HEALTHCHECK_PAGES" in (ROT / "planlegger" / "README.md").read_text("utf-8"))

print("\n=== Porten for runder av utløsninger: ELO-test og grunnlag (scripts/puljeport.py, 8.10.2026) ===")
# GitHub holder bare én ventende kjøring per concurrency-gruppe, så den
# midterste av tre ELO-test-starter i en runde ble avbrutt (78 av 238 siste
# døgn 7.10.). Porten lar bare den siste i runden bygge, og sier hvorfor.
import puljeport as _pj
def _pj_api(svar):
    def api(sti):
        for k, v in svar.items():
            if sti.startswith(k):
                if isinstance(v, Exception):
                    raise v
                return v() if callable(v) else v
        raise AssertionError(sti)
    return api
_ekte_pj = _pj.api
def _kjor(wf, *rader):
    return {f"actions/workflows/{wf}/runs": {"workflow_runs": [dict(id=i, status=st, conclusion=c, created_at=t) for i, st, c, t in rader]}}
_sov = []
try:
    _ingen = {**_kjor("update-data.yml", (1, "completed", "success", "2026-10-07T10:00:30Z")),
              **_kjor("update-odds.yml", (2, "completed", "success", "2026-10-07T10:00:31Z")),
              **_kjor("prekick-odds.yml", (3, "completed", "success", "2026-10-07T10:00:32Z"))}
    _pj.api = _pj_api({**_ingen, **_kjor("elo-test.yml", (101, "in_progress", None, "2026-10-07T10:00:48Z"),
                                          (102, "in_progress", None, "2026-10-07T10:00:55Z"))})
    _b, _h = _pj.elo(101, "workflow_run", sov=_sov.append)
    sjekk("ELO-test: en nyere kjøring finnes: bygg=false, og loggen sier «nyere kjøring» med nummer og tid",
          _b is False and _h == "bygg=false: nyere kjøring -- ELO-test #102 (startet 10:00:55Z) er nyere og bygger i stedet" and _sov == [20], _h)
    _b, _h = _pj.elo(102, "workflow_run", sov=lambda s: None)
    sjekk("den nyeste, ingen utløser kjører: bygg=true", _b is True and "ingen nyere" in _h, _h)
    _pj.api = _pj_api({**_ingen, **_kjor("update-odds.yml", (2, "in_progress", None, "2026-10-07T10:00:31Z")),
                       **_kjor("elo-test.yml", (102, "in_progress", None, "2026-10-07T10:00:55Z"))})
    _b, _h = _pj.elo(102, "workflow_run", sov=lambda s: None)
    sjekk("en utløser kjører fortsatt: bygg=false, og loggen sier «aktiv utløser» med navnet",
          _b is False and _h.startswith("bygg=false: aktiv utløser -- «Oppdater odds for kommende kamper» (#2) kjører fortsatt"), _h)
    _sov.clear()
    _b, _h = _pj.elo(100, "workflow_dispatch", sov=_sov.append)
    sjekk("manuelt: bygger alltid, uten å vente", _b is True and _sov == [], _h)

    # Grunnlag: en nyere kjøring har "regn (obos)" i kø: obos tas bort.
    _jobb = lambda *j: {"jobs": [dict(name=n, status=st, conclusion=c) for n, st, c in j]}
    _pj.api = _pj_api({**_kjor("grunnlag.yml", (201, "in_progress", None, "t"), (202, "queued", None, "t"), (203, "completed", "cancelled", "t")),
                       "actions/runs/202/jobs": _jobb(("port", "completed", "success"), ("regn (obos)", "queued", None)),
                       "actions/runs/203/jobs": _jobb(("port", "completed", "success"), ("regn (eliteserien)", "completed", "cancelled"))})
    _l, _borte = _pj.grunnlag(201, "workflow_run", ["eliteserien", "obos"], sov=lambda s: None)
    sjekk("grunnlag: en nyere kjøring regner obos: obos tas bort, eliteserien beholdes (den avbrutte teller ikke)",
          _l == ["eliteserien"] and _borte == [("obos", 202)], f"{_l} {_borte}")
    # Den nyere kjøringens port er ikke ferdig ennå: porten venter på den.
    _tilstand = {"n": 0}
    def _jobber_202():
        _tilstand["n"] += 1
        return _jobb(("port", "in_progress", None)) if _tilstand["n"] < 3 else _jobb(("port", "completed", "success"), ("regn (eliteserien)", "queued", None), ("regn (obos)", "queued", None))
    _pj.api = _pj_api({**_kjor("grunnlag.yml", (201, "in_progress", None, "t"), (202, "in_progress", None, "t")), "actions/runs/202/jobs": _jobber_202})
    _sov2 = []
    _l, _borte = _pj.grunnlag(201, "workflow_run", ["eliteserien", "obos"], sov=_sov2.append)
    sjekk("grunnlag: venter til den nyere kjøringens port er ferdig, og tar så bort begge",
          _l == [] and [x for x, _ in _borte] == ["eliteserien", "obos"] and _sov2 == [20, 5, 5], f"{_l} {_borte} {_sov2}")
    # Den nyere regner ingenting (porten sa []): alt beholdes.
    _pj.api = _pj_api({**_kjor("grunnlag.yml", (201, "in_progress", None, "t"), (202, "completed", "success", "t")),
                       "actions/runs/202/jobs": _jobb(("port", "completed", "success"), ("regn", "completed", "skipped"))})
    _l, _borte = _pj.grunnlag(201, "workflow_run", ["eliteserien"], sov=lambda s: None)
    sjekk("grunnlag: den nyere regner ingenting: alt beholdes", _l == ["eliteserien"] and _borte == [], f"{_l} {_borte}")
    _l, _borte = _pj.grunnlag(201, "workflow_dispatch", ["eliteserien", "obos"], sov=lambda s: (_ for _ in ()).throw(AssertionError("sov")))
    sjekk("grunnlag manuelt: alle, uten å vente", _l == ["eliteserien", "obos"])

    # Hele skriptet: GITHUB_OUTPUT og loggen, og GitHub som ikke svarer.
    _ut = Path(_tf2.mkdtemp()) / "output"
    _gml_env = {k: _osu.environ.get(k) for k in ("GITHUB_OUTPUT", "GITHUB_RUN_ID", "GITHUB_EVENT_NAME", "LIGAER")}
    _osu.environ.update(GITHUB_OUTPUT=str(_ut), GITHUB_RUN_ID="201", GITHUB_EVENT_NAME="workflow_run", LIGAER='["eliteserien", "obos"]')
    _pj.api = _pj_api({"actions/workflows": OSError("HTTP 502")})
    _ekte_sov = _pj.time.sleep
    _pj.time.sleep = lambda s: None
    try:
        _buf = _iou.StringIO()
        with _ctxu.redirect_stdout(_buf):
            sys.argv = ["puljeport.py", "elo"]; _k1 = _pj.main()
            sys.argv = ["puljeport.py", "grunnlag"]; _k2 = _pj.main()
    finally:
        _pj.time.sleep = _ekte_sov
        sys.argv = _ekte_argv_o
        for _k, _v in _gml_env.items():
            if _v is None:
                _osu.environ.pop(_k, None)
            else:
                _osu.environ[_k] = _v
    _o = _ut.read_text("utf-8")
    sjekk("GitHub svarer ikke: ELO-test bygger og grunnlag regner alle, og loggen sier hvorfor",
          _k1 == 0 and _k2 == 0 and _o == 'bygg=true\nligaer=["eliteserien", "obos"]\n' and "GitHub svarte ikke" in _buf.getvalue(), _o + _buf.getvalue())
finally:
    _pj.api = _ekte_pj

_ew = (ROT / ".github" / "workflows" / "elo-test.yml").read_text("utf-8")
_ewk = "\n".join(l for l in _ew.splitlines() if not l.strip().startswith("#"))
_gw = (ROT / ".github" / "workflows" / "grunnlag.yml").read_text("utf-8")
_gwk = "\n".join(l for l in _gw.splitlines() if not l.strip().startswith("#"))
sjekk("elo-test.yml: ingen kø på hele workflowen, byggejobben trenger porten og står i kø elo-test-bygg uten å avbryte",
      "\nconcurrency:" not in _ewk and "    needs: port\n    if: needs.port.outputs.bygg == 'true'\n" in _ewk
      and "    concurrency:\n      group: elo-test-bygg" in _ewk and "cancel-in-progress: false" in _ewk and "cancel-in-progress: true" not in _ewk)
sjekk("elo-test.yml: porten kjører puljeport.py elo med GITHUB_TOKEN og har actions: read; ingen gammel betingelse på utløserens utfall",
      "  port:\n" in _ewk and "python3 scripts/puljeport.py elo" in _ewk and "GITHUB_TOKEN: ${{ github.token }}" in _ewk
      and "actions: read" in _ewk and "workflow_run.conclusion" not in _ewk and _ewk.index("  bygg:") < _ewk.index("  port:"))
sjekk("grunnlag.yml: steget puljen etter porten, ligaene fra det, med actions: read",
      "python3 scripts/grunnlag_port.py $sider" in _gwk and "LIGAER: ${{ steps.port.outputs.ligaer }}" in _gwk
      and "python3 scripts/puljeport.py grunnlag" in _gwk and "ligaer: ${{ steps.puljen.outputs.ligaer }}" in _gwk
      and _gwk.index("grunnlag_port.py $sider") < _gwk.index("puljeport.py grunnlag") and "actions: read" in _gwk)

print("\n=== Chrome-start: 90 sekunder og ett nytt forsøk (scripts/chrome_start.js, 8.10.2026) ===")
_cs = r"""
const {startChrome} = require(process.argv[1]);
(async () => {
  const kall = [], logg = [];
  const lag = utfall => ({launch: async o => { kall.push(o.timeout); const u = utfall.shift(); if (u instanceof Error) throw u; return u; }});
  const tidsavbrudd = () => Object.assign(new Error('Timed out after 30000 ms while waiting for the WS endpoint URL to appear in stdout!'), {name: 'TimeoutError'});
  const a = await startChrome(lag([tidsavbrudd(), 'nettleser']), {headless: 'new'}, {logg: m => logg.push(m)});
  let feil = null;
  try { await startChrome(lag([tidsavbrudd(), tidsavbrudd()]), {headless: 'new'}, {logg: m => logg.push(m)}); } catch (e) { feil = e.name; }
  const b = await startChrome(lag(['rett']), {}, {logg: m => logg.push(m)});
  console.log(JSON.stringify({a, b, feil, kall, logg}));
})();
"""
import subprocess as _sub_cs
_r = _sub_cs.run(["node", "-e", _cs, str(ROT / "scripts" / "chrome_start.js")], capture_output=True, text=True)
_cr = json.loads(_r.stdout.strip() or "{}") if _r.returncode == 0 else {}
sjekk("Chrome startet ikke første gang: nytt forsøk, og loggen sier det",
      _cr.get("a") == "nettleser" and len(_cr.get("logg", [])) == 2 and "prøver igjen (forsøk 2 av 2)" in (_cr.get("logg") or [""])[0], _r.stdout + _r.stderr)
sjekk("feiler begge forsøkene: feilen kastes (kjøringen blir rød som før); går det første, bare ett forsøk",
      _cr.get("feil") == "TimeoutError" and _cr.get("b") == "rett", str(_cr))
sjekk("90 sekunder i hvert forsøk", _cr.get("kall") == [90000] * 5, str(_cr.get("kall")))
_sp = (ROT / "scripts" / "snapshot_probs.js").read_text("utf-8")
_kp = (ROT / "elo-test" / "scripts" / "kontroll_paneler.py").read_text("utf-8")
sjekk("snapshot_probs.js og kontroll_paneler.py starter Chrome med startChrome, ikke puppeteer.launch",
      "await startChrome(puppeteer, {executablePath: chromePath()" in _sp and "puppeteer.launch(" not in _sp
      and "const {startChrome} = require(process.argv[3]);" in _kp and "await startChrome(puppeteer, {executablePath: process.argv[2]" in _kp
      and 'str(ROT / "scripts" / "chrome_start.js")' in _kp and "puppeteer.launch(" not in _kp)

print("\n=== Runnerne er låst, og actions kjører på Node 24 (8.10.2026) ===")
# GitHub bytter ubuntu-latest til Ubuntu 26 fra 19.10.2026. Alle jobbene står
# på ubuntu-24.04, så ingenting endrer seg midt i en runde; checkout,
# setup-python og setup-node er versjonene laget for Node 24 (v7).
import re as _re_r
_wfs = sorted((ROT / ".github" / "workflows").glob("*.yml"))
_runs = [(f.name, l.strip()) for f in _wfs for l in f.read_text("utf-8").splitlines() if l.strip().startswith("runs-on:")]
sjekk(f"alle {len(_runs)} jobbene i {len(_wfs)} workflows kjører på ubuntu-24.04, ingen på ubuntu-latest",
      len(_runs) >= 19 and all(_re_r.match(r"runs-on: ubuntu-24\.04(\s|$)", l) for _, l in _runs),
      str([x for x in _runs if not x[1].startswith("runs-on: ubuntu-24.04")][:4]))
_bruk = [(f.name, m) for f in _wfs for m in _re_r.findall(r"uses: (actions/(?:checkout|setup-python|setup-node)@\S+)", f.read_text("utf-8"))]
sjekk(f"checkout, setup-python og setup-node er v7 (Node 24) alle {len(_bruk)} steder",
      len(_bruk) >= 29 and all(m.endswith("@v7") for _, m in _bruk), str([x for x in _bruk if not x[1].endswith("@v7")][:4]))

print("\n=== Kort eller full kontroll før push (tests/for_push_valg.py, 4.10.2026) ===")
# Kort kontroll bare når full for_push var grønn på samme kode før rebasen og
# origin bare endret filer på den eksplisitte listen over genererte filer.
sys.path.insert(0, str(ROT / "tests"))
import for_push_valg as _fpv
_gen = ["obos/data/grunnlag.json", "elo-test/emodell/lastmatch.json", "data/hentelogg/2026-10/x.jsonl", "data/highlightly-bruk/2026-10-04/1.json"]
sjekk("listen: grunnlag, lastmatch, panelfilene og logg-/tellermappene er genererte",
      all(_fpv.generert(f) for f in _gen + ["elo-test/emodell/prekick.json", "data/oddspapi-bruk/2026-10/x.json"]))
sjekk("listen: matches.json, fixtures.json, prekick.json, odds, kode og nesten-like stier er ikke på den (ingen mønstre)",
      not any(_fpv.generert(f) for f in ["obos/data/matches.json", "eliteserien/data/fixtures.json", "obos/data/prekick.json",
              "obos/data/odds_upcoming.json", "scripts/update_data.py", "eliteserien/index.html", "data/hentelogg",
              "eliteserien/data/grunnlag.json.bak", "x/eliteserien/data/grunnlag.json", "elo-test/emodell/model.json"]))
_B = _fpv.beslutt
sjekk("bare genererte filer fra origin og ingen egne endringer: kort", _B(True, True, True, _gen[:2], _gen)[0] == "kort")
sjekk("ingenting endret siden den grønne kjøringen: kort", _B(True, True, True, [], [])[0] == "kort")
for _navn, _a, _ventet_ord in [
        ("ingen lagret grønn kjøring", (False, True, True, [], []), "ingen grønn"),
        ("endringer som ikke er committet", (True, False, True, [], []), "ikke er committet"),
        ("ikke rebasert på origin/main", (True, True, False, [], []), "ikke rebasert"),
        ("egen endring siden den grønne kjøringen", (True, True, True, ["eliteserien/index.html"], []), "ikke fra origin: eliteserien/index.html"),
        ("matches.json fra origin", (True, True, True, ["obos/data/matches.json"], ["obos/data/matches.json"]), "obos/data/matches.json"),
        ("fixtures.json fra origin", (True, True, True, [], ["eliteserien/data/fixtures.json", "obos/data/grunnlag.json"]), "fixtures.json"),
        ("ukjent fil fra origin", (True, True, True, [], ["noe/nytt.txt"]), "noe/nytt.txt")]:
    _v, _g = _B(*_a)
    sjekk(f"{_navn}: full ({_g[:70]})", _v == "full" and _ventet_ord in _g, _g)
# Et ekte forløp i et midlertidig repo: grønn kjøring, origin endrer en
# generert fil, rebase: kort. Origin endrer matches.json: full.
import tempfile as _tf6, subprocess as _sp6, shutil as _sh6
_rot6 = Path(_tf6.mkdtemp())
def _g6(cwd, *a):
    return _sp6.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
try:
    _g6(_rot6, "init", "-q", "--bare", "-b", "main", "origin.git")
    _g6(_rot6, "clone", "-q", "origin.git", "her"); _her = _rot6 / "her"
    (_her / "obos" / "data").mkdir(parents=True)
    for _f in ("grunnlag.json", "matches.json"):
        (_her / "obos" / "data" / _f).write_text("{}\n")
    _g6(_her, "add", "-A"); _g6(_her, "commit", "-qm", "start"); _g6(_her, "branch", "-M", "main"); _g6(_her, "push", "-q", "origin", "main")
    (_her / "kode.js").write_text("// min endring\n"); _g6(_her, "add", "-A"); _g6(_her, "commit", "-qm", "min")
    _g6(_her, "fetch", "-q")
    (Path(_g6(_her, "rev-parse", "--absolute-git-dir")) / "for-push-gronn").write_text(json.dumps({"commit": _g6(_her, "rev-parse", "HEAD"), "tid": "nå"}))
    _g6(_rot6, "clone", "-q", "origin.git", "bot"); _bot = _rot6 / "bot"
    def _bot_endrer(f, innhold):
        (_bot / f).write_text(innhold); _g6(_bot, "add", "-A"); _g6(_bot, "commit", "-qm", f"bot {f}"); _g6(_bot, "push", "-q", "origin", "HEAD:main")
    def _kjor6():
        _g6(_her, "fetch", "-q"); _g6(_her, "rebase", "-q", "origin/main")
        r = _sp6.run([sys.executable, str(ROT / "tests" / "for_push_valg.py")], cwd=_her, capture_output=True, text=True)
        return r.stdout
    _bot_endrer("obos/data/grunnlag.json", '{"ny": 1}\n')
    # En hentelogg med æ i navnet (jobben «Odds nær avspark»): også generert.
    (_bot / "data" / "hentelogg" / "2026-10").mkdir(parents=True, exist_ok=True)
    _bot_endrer("data/hentelogg/2026-10/2026-10-04-Odds_nær_avspark-1-1.jsonl", "{}\n")
    _u1 = _kjor6()
    sjekk("ekte rebase: origin endret bare obos/data/grunnlag.json, koden er den samme: VALG=kort, og utskriften sier hvorfor",
          _u1.strip().endswith("VALG=kort") and "full for_push sist grønn på" in _u1 and "bot obos/data/grunnlag.json" in _u1
          and "generert  obos/data/grunnlag.json" in _u1 and "generert  data/hentelogg/2026-10/2026-10-04-Odds_nær_avspark-1-1.jsonl" in _u1, _u1)
    _bot_endrer("obos/data/matches.json", '{"ny": 2}\n')
    _u2 = _kjor6()
    sjekk("ekte rebase: origin endret obos/data/matches.json: VALG=full, med filen som grunn",
          _u2.strip().endswith("VALG=full") and "IKKE PÅ LISTEN  obos/data/matches.json" in _u2, _u2)
    (_her / "kode.js").write_text("// endret igjen\n")
    _u3 = _sp6.run([sys.executable, str(ROT / "tests" / "for_push_valg.py")], cwd=_her, capture_output=True, text=True).stdout
    sjekk("endring som ikke er committet: VALG=full", _u3.strip().endswith("VALG=full") and "ikke er committet" in _u3, _u3)
finally:
    _sh6.rmtree(_rot6, ignore_errors=True)

print("\n=== Livstegn eller varsel til healthchecks (scripts/livstegn.py, 12.10.2026) ===")
# Regelen: er kjøringen rød, eller har status.json ok: false, sendes /fail med
# teksten. Ellers livstegn. 9.10.2026 kom det aldri noe varsel: kjøringene med
# lukket port var grønne og sendte livstegn mellom de røde.
import io as _io_l, contextlib as _cl_l, tempfile as _tf_l, urllib.request as _ur_l
import livstegn as _lt
_lt_dir = Path(_tf_l.mkdtemp())
_lt_ekte = (_lt.LIGAER, _lt.urllib.request.urlopen)
_lt.LIGAER = {"eliteserien": ("Eliteserien", _lt_dir / "e"), "obos": ("OBOS-ligaen", _lt_dir / "o")}
for _d in ("e", "o"):
    (_lt_dir / _d).mkdir()
_HC = "https://hc.example/ping/hemmelig-uuid"
_lt_ping = []


class _LtSvar:
    def read(self):
        return b"OK"


def _lt_aapne(req, timeout=None):
    _lt_ping.append((req.full_url, req.data.decode("utf-8") if req.data else None))
    return _LtSvar()


def _lt_kjor(liga="eliteserien", jobb="success", steg=None, status=None, hc=_HC, aapne=_lt_aapne, test=False):
    """(pingene, utskriften, exit-koden) for én kjøring av livstegn.main."""
    sti = _lt.LIGAER[liga][1] / "status.json"
    if status is None:
        sti.unlink(missing_ok=True)
    else:
        sti.write_text(_json.dumps(status), encoding="utf-8")
    _lt_ping.clear()
    _lt.urllib.request.urlopen = aapne
    ut = _io_l.StringIO()
    with _cl_l.redirect_stdout(ut):
        kode = _lt.main([liga], {"HC_URL": hc, "JOBB_STATUS": jobb, "STEG": _json.dumps(steg or {}),
                                 "TESTVARSEL": "true" if test else "false", "GITHUB_SERVER_URL": "https://github.com",
                                 "GITHUB_REPOSITORY": "fiskentnt/eliteserien", "GITHUB_RUN_ID": "123"})
    return list(_lt_ping), ut.getvalue(), kode


_GATE_AAPEN = {"gate": {"outputs": {"should_fetch": "true"}, "outcome": "success"}}
_GATE_LUKKET = {"gate": {"outputs": {"should_fetch": "false"}, "outcome": "success"}}
_feiler = lambda sid, port=_GATE_AAPEN: {**port, sid: {"outcome": "failure"}}
_GRONN = {"last_checked": "2026-10-12T10:00:00+00:00", "ok": True}
_TAB = "2 kritisk(e) avvik mellom tabellen vår og tabellen på ligasiden: Tabell, Brann: 2 uavgjort hos oss, 3 hos eliteserien.no"
_REV = "1 kritisk(e) avvik mellom terminlisten og kalenderfeeden: Rosenborg-Start: dato 2026-11-18 hos oss, 2026-11-07 i kalenderfeeden"
_DAT = "1 kamp(er) mangler sluttresultat mer enn 3 timer etter avspark:\nRosenborg-Start (2026-01-07 18:00): 6591.9 timer siden avspark"

_p, _ut, _k = _lt_kjor(steg=_GATE_AAPEN, status=_GRONN)
sjekk("grønn kjøring og grønn status: livstegn (GET til adressen, ikke /fail)", _p == [(_HC, None)] and _k == 0 and "Livstegn sendt" in _ut, f"{_p} {_ut}")
_p, _ut, _k = _lt_kjor(steg=_GATE_LUKKET, status=_GRONN)
sjekk("grønn kjøring med lukket port og grønn status: livstegn", _p == [(_HC, None)], str(_p))
# Tilfelle 1 fra brukeren: grønn kjøring med LUKKET port, status rød.
_p, _ut, _k = _lt_kjor(steg=_GATE_LUKKET, status={"ok": False, "error": _REV, "revisjon_avvik": 1})
sjekk("grønn kjøring, lukket port, status.json ok: false: /fail, ikke livstegn",
      len(_p) == 1 and _p[0][0] == _HC + "/fail" and _k == 0, str(_p))
sjekk("og teksten sier revisjon, feilen, at porten var lukket, og har lenke til kjøringen",
      _p[0][1].startswith("Eliteserien: revisjon\n" + _REV) and "Porten var lukket" in _p[0][1]
      and "https://github.com/fiskentnt/eliteserien/actions/runs/123" in _p[0][1], _p[0][1])
# Tilfelle 2: grønn kjøring med ÅPEN port, men revisjonen holder status rød.
_p, _ut, _k = _lt_kjor(steg=_GATE_AAPEN, status={"ok": False, "error": _REV, "revisjon_avvik": 1})
sjekk("grønn kjøring, åpen port, status.json ok: false (avvik i revisjonen): /fail, ikke livstegn",
      len(_p) == 1 and _p[0][0] == _HC + "/fail" and "Eliteserien: revisjon" in _p[0][1] and "Kjøringen hentet data" in _p[0][1], str(_p))
sjekk("og i en grønn kjøring er det en ::warning, ikke ::error", "::warning title=Eliteserien: revisjon::" in _ut and "::error" not in _ut, _ut)
# Røde kjøringer: /fail med kategorien.
_p, _ut, _k = _lt_kjor(jobb="failure", steg=_feiler("oppdater"), status={"ok": False, "error": _TAB})
sjekk("rød kjøring, tabellkontrollen: /fail med «tabellkontroll» og feilen",
      _p[0][0] == _HC + "/fail" and _p[0][1].startswith("Eliteserien: tabellkontroll\n" + _TAB) and "::error title=Eliteserien: tabellkontroll::" in _ut, f"{_p} {_ut}")
_p, _ut, _k = _lt_kjor(jobb="failure", steg=_feiler("oppdater"), status={"ok": False, "error": _DAT})
sjekk("rød kjøring, kamp uten sluttresultat: «datafeil», med hele feilen (selve avviket, 17.10.2026)",
      _p[0][1].startswith("Eliteserien: datafeil\n" + _DAT + "\nKjøringen hentet data."), _p[0][1])
sjekk("og i ::error-linjen er linjeskiftet %0A (én workflow-kommando)",
      "::error title=Eliteserien: datafeil::1 kamp(er) mangler sluttresultat mer enn 3 timer etter avspark:%0ARosenborg-Start" in _ut, _ut)
# 16.10.2026: e-posten sa «1 avvik mellom matches.json og kontrollkilden:» og ikke hvilken kamp.
_KFUM = ("1 avvik mellom matches.json og kontrollkilden:\nKFUM Oslo-Vålerenga (2026-10-12): vi har 2-1, "
         "ffksupporter.net har 1-1")
_p, _ut, _k = _lt_kjor(steg=_GATE_LUKKET, status={"ok": False, "error": _KFUM, "revisjon_avvik": 1})
sjekk("rød status: /fail har selve avviket (kampen og resultatene), ikke bare første linje",
      _p[0][0] == _HC + "/fail" and "KFUM Oslo-Vålerenga (2026-10-12): vi har 2-1, ffksupporter.net har 1-1" in _p[0][1], _p[0][1])
# Advarsler (17.10.2026): grønn status med advarsler gir livstegn MED teksten.
_ADV = "KFUM Oslo-Vålerenga (2026-10-12): vi har 2-1, ffksupporter.net mangler resultatet 114 timer etter avspark; bekreftet av espn, football-data"
_STOPP = "ffksupporter.net har ikke registrert noe nytt på 6 døgn (siden 11.10.) og mangler 1 resultat(er) fra kamper spilt etter det: kilden ser ut til å ha stoppet"
_p, _ut, _k = _lt_kjor(steg=_GATE_AAPEN, status={**_GRONN, "advarsler": [_STOPP, _ADV]})
sjekk("grønn status med advarsler: livstegn (ikke /fail), med advarslene som tekst",
      len(_p) == 1 and _p[0][0] == _HC and _p[0][1] is not None
      and _p[0][1].startswith("Eliteserien: grønn, 2 advarsel(er)\n- " + _STOPP + "\n- " + _ADV)
      and "https://github.com/fiskentnt/eliteserien/actions/runs/123" in _p[0][1], str(_p))
sjekk("og en ::notice i loggen, ikke ::warning eller ::error",
      "::notice title=Eliteserien: 2 advarsel(er)::" in _ut and "::warning" not in _ut and "::error" not in _ut, _ut)
_p, _ut, _k = _lt_kjor(steg=_GATE_AAPEN, status={"ok": False, "error": _REV, "advarsler": [_ADV]})
sjekk("rød status med advarsler: /fail med feilen og advarslene",
      _p[0][0] == _HC + "/fail" and _p[0][1].startswith("Eliteserien: revisjon\n" + _REV)
      and "Advarsler (ikke rødt):\n- " + _ADV in _p[0][1], _p[0][1])
_p, _ut, _k = _lt_kjor(jobb="failure", steg=_feiler("revisjon"), status={"ok": False, "error": _REV})
sjekk("rød kjøring, revisjonssteget: «revisjon» med feilen fra status.json", _p[0][1].startswith("Eliteserien: revisjon\n" + _REV), _p[0][1])
_p, _ut, _k = _lt_kjor(jobb="failure", steg=_feiler("resultatregel", _GATE_LUKKET), status=_GRONN)
sjekk("rød kjøring, resultat uten kontroll (lukket port, grønn status): /fail med kategorien",
      _p[0][0] == _HC + "/fail" and _p[0][1].startswith("Eliteserien: resultat uten kontroll eller i konflikt\nsteget «resultatregel» feilet"), _p[0][1])
_p, _ut, _k = _lt_kjor(jobb="failure", steg=_feiler("kildevakt", _GATE_LUKKET), status=_GRONN)
sjekk("rød kjøring, kildevakten: «kilde ute»", _p[0][1].startswith("Eliteserien: kilde ute\n"), _p[0][1])
_p, _ut, _k = _lt_kjor(jobb="failure", steg=_feiler("sesongskifte"), status=_GRONN)
sjekk("rød kjøring, sesongskiftet: «sesongskifte»", _p[0][1].startswith("Eliteserien: sesongskifte\n"), _p[0][1])
_p, _ut, _k = _lt_kjor(jobb="failure", steg=_GATE_AAPEN, status=_GRONN)
sjekk("rød kjøring uten kjent steg: «annet», fortsatt /fail", _p[0][0] == _HC + "/fail" and _p[0][1].startswith("Eliteserien: annet\n"), _p[0][1])
_p, _ut, _k = _lt_kjor(liga="obos", jobb="failure", steg=_feiler("bygg"),
                       status={"ok": False, "error": "2 kritisk(e) avvik mellom terminlisten eller tabellen og kalenderfeeden: x"})
sjekk("OBOS: egen status.json, og «terminlisten eller tabellen» får sin egen kategori",
      _p[0][1].startswith("OBOS-ligaen: revisjon eller tabellkontroll\n"), _p[0][1])
# Et steg med continue-on-error (outcome failure) gjør ikke en grønn kjøring til en feil.
_p, _ut, _k = _lt_kjor(jobb="success", steg={**_GATE_AAPEN, "frys": {"outcome": "failure", "conclusion": "success"}}, status=_GRONN)
sjekk("grønn kjøring der et steg med continue-on-error feilet, grønn status: livstegn", _p == [(_HC, None)], str(_p))
_p, _ut, _k = _lt_kjor(jobb="cancelled", steg=_GATE_AAPEN, status={"ok": False, "error": _REV})
sjekk("avbrutt kjøring: verken livstegn eller varsel", _p == [] and _k == 0, f"{_p} {_ut}")
_p, _ut, _k = _lt_kjor(steg=_GATE_LUKKET, status=None)
sjekk("status.json mangler og kjøringen er grønn: livstegn", _p == [(_HC, None)], str(_p))
# Skriptet kan aldri gjøre kjøringen rød, og skriver aldri ut adressen.
_p, _ut, _k = _lt_kjor(jobb="failure", steg=_feiler("oppdater"), status={"ok": False, "error": _TAB}, hc="")
sjekk("uten hemmeligheten: ingen ping, exit 0, og feilen står som ::warning", _p == [] and _k == 0 and "ikke satt" in _ut and "::warning" in _ut, _ut)


def _lt_nede(req, timeout=None):
    raise _ue.URLError("nede")


_p, _ut, _k = _lt_kjor(jobb="failure", steg=_feiler("oppdater"), status={"ok": False, "error": _TAB}, aapne=_lt_nede)
sjekk("healthchecks svarer ikke: exit 0 likevel, og det sies", _k == 0 and "feilet" in _ut and "ble ikke sendt" in _ut, _ut)
_alle_ut = "".join(_lt_kjor(jobb=j, steg=s, status=st)[1] for j, s, st in
                   [("success", _GATE_AAPEN, _GRONN), ("failure", _feiler("oppdater"), {"ok": False, "error": _TAB}),
                    ("success", _GATE_LUKKET, {"ok": False, "error": _REV})])
sjekk("adressen (hemmeligheten) skrives aldri ut", "hemmelig-uuid" not in _alle_ut and "hc.example" not in _alle_ut, _alle_ut[:200])
_p, _ut, _k = _lt_kjor(steg=_GATE_LUKKET, status=_GRONN, test=True)
sjekk("testvarsel: først /fail merket TEST, så et livstegn rett etter",
      [u for u, _ in _p] == [_HC + "/fail", _HC] and _p[0][1].startswith("TEST av varslingen") and _k == 0, str(_p))
_lt.LIGAER, _lt.urllib.request.urlopen = _lt_ekte

print("\n=== Ingen tellende kall når UTEN_TELLENDE=true (nytt forsøk ved rød status) ===")
import oddspapi as _op_u, highlightly_source as _hls_u, hentelogg as _hl_u
_u_dir = Path(_tf_l.mkdtemp())
_u_ekte = (_op_u.urllib.request.urlopen, _op_u.budsjett_stopp, _op_u.BRUK_KATALOG, _hls_u._http, _hls_u.BRUK_KATALOG, _hl_u.KATALOG)
_op_u.BRUK_KATALOG, _hls_u.BRUK_KATALOG, _hl_u.KATALOG = _u_dir / "op", _u_dir / "hl", _u_dir / "logg"
_op_u.budsjett_stopp = lambda *a, **k: (False, "")
_u_http = []


class _USvar:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"data": []}'

    headers = {}


def _u_aapne(req, timeout=None):
    _u_http.append(req.full_url.split("?")[0])
    return _USvar()


_op_u.urllib.request.urlopen = _u_aapne
_hls_u._http = lambda sti, param: (_u_http.append("highlightly" + sti) or {"data": []})
_for_op, _for_hl = _op_u.dagsbruk(), _hls_u.dagsbruk()
with _vern.miljo(UTEN_TELLENDE="true"):
    _svar = _op_u.call("/v4/fixtures", {"tournamentId": 20}, "nokkel")
    sjekk("OddsPapi, tellende endepunkt (/v4/fixtures): ingen forespørsel, og svaret sier hvorfor",
          _u_http == [] and _svar[0] is None and "tellende kall er slått av" in _svar[1], f"{_u_http} {_svar}")
    sjekk("og kallet er ikke talt", _op_u.dagsbruk() == _for_op, f"{_for_op} -> {_op_u.dagsbruk()}")
    sjekk("og det logges som «hoppet», ikke feil (gjør ikke kildevakten rød)",
          [r["utfall"] for r in _hl_u.les() if r["kilde"] == "oddspapi-fixtures"] == ["hoppet"], str(_hl_u.les()))
    _op_u.call("/v4/historical-odds", {"fixtureId": "x"}, "nokkel")
    sjekk("OddsPapi, gratisoppslaget (/v4/historical-odds) går som før", len(_u_http) == 1 and "historical-odds" in _u_http[0], str(_u_http))
    _u_http.clear()
    try:
        _hls_u.kall("/matches", {"date": "2026-10-12"}); _kast = None
    except _hls_u.Budsjett as e:
        _kast = str(e)
    sjekk("Highlightly: ingen forespørsel, Budsjett med begrunnelsen", _u_http == [] and _kast is not None and "tellende kall er slått av" in _kast, f"{_u_http} {_kast}")
    sjekk("og kallet er ikke talt", _hls_u.dagsbruk() == _for_hl, f"{_for_hl} -> {_hls_u.dagsbruk()}")
# Motprøve: uten flagget går begge kallene ut og telles.
_u_http.clear()
_op_u.call("/v4/fixtures", {"tournamentId": 20}, "nokkel")
_hls_u.kall("/matches", {"date": "2026-10-12"})
sjekk("motprøve uten UTEN_TELLENDE: begge kallene går ut og telles",
      len(_u_http) == 2 and _op_u.dagsbruk() == _for_op + 1 and _hls_u.dagsbruk() == _for_hl + 1,
      f"{_u_http} {_op_u.dagsbruk()} {_hls_u.dagsbruk()}")
(_op_u.urllib.request.urlopen, _op_u.budsjett_stopp, _op_u.BRUK_KATALOG, _hls_u._http, _hls_u.BRUK_KATALOG, _hl_u.KATALOG) = _u_ekte

print("\n=== Workflowene: siste steg er livstegn.py, og porten sender sperren videre ===")
for _wf_navn, _liga_l, _hem in (("update-data.yml", "eliteserien", "HEALTHCHECK_UPDATE_DATA"), ("obos-results.yml", "obos", "HEALTHCHECK_OBOS")):
    _wt = (ROT / ".github" / "workflows" / _wf_navn).read_text("utf-8")
    _stegene = _wt.split("\n      - ")[1:]
    _siste = "\n".join(l for l in _stegene[-1].splitlines() if not l.strip().startswith("#"))
    sjekk(f"{_wf_navn}: siste steg kjører scripts/livstegn.py {_liga_l}, også når kjøringen er rød (ikke ved avbrutt)",
          f"python3 scripts/livstegn.py {_liga_l}" in _siste and "if: ${{ !cancelled() }}" in _siste
          and "hentelogg.py sjekk" in _stegene[-2], _siste[:200])
    sjekk(f"{_wf_navn}: steget får hemmeligheten {_hem}, job.status og stegenes utfall, og har ingen curl eller continue-on-error",
          f"HC_URL: ${{{{ secrets.{_hem} }}}}" in _siste and "JOBB_STATUS: ${{ job.status }}" in _siste
          and "STEG: ${{ toJSON(steps) }}" in _siste and "curl" not in _siste and "continue-on-error" not in _siste, _siste)
    _ider = set(_re_u.findall(r"\n        id: (\w+)", _wt))
    sjekk(f"{_wf_navn}: stegene som kan gjøre kjøringen rød har id-ene livstegn.py kjenner",
          {"gate", "revisjon", "sesongskifte", "resultatregel", "kildevakt"} <= _ider
          and ("oppdater" in _ider if _liga_l == "eliteserien" else {"resultater", "bygg"} <= _ider), str(sorted(_ider)))
    sjekk(f"{_wf_navn}: porten kjører should_fetch.py, som skriver UTEN_TELLENDE til resten av jobben",
          "python3 scripts/should_fetch.py" in _wt and 'f.write("UTEN_TELLENDE=true\\n")' in (ROT / "scripts" / "should_fetch.py").read_text("utf-8"))
sjekk("alle steg-id-ene i livstegn.py finnes i minst én av de to workflowene",
      all(any(f"\n        id: {sid}\n" in (ROT / ".github" / "workflows" / w).read_text("utf-8") for w in ("update-data.yml", "obos-results.yml"))
          for sid, _ in _lt.STEG_KATEGORI), str([s for s, _ in _lt.STEG_KATEGORI]))

print("\n=== Kontrollene stopper ikke resten (update_data.etter_skriving, 12.10.2026) ===")
# Før stoppet «mangler sluttresultat» og datovaktene kjøringen FØR sluttoddsen
# og modellen. Nå: arbeidet først, kontrollene til slutt, alle kjøres, og
# kjøringen blir rød med alle som slo ut. Rekkefølgen måles med innbyttede
# funksjoner som skriver seg inn i en liste.
import update_data as _uda
import leaguedata as _lda
import livstegn as _lta
import tempfile as _tfa
import shutil as _sha
from datetime import timedelta as _tda

_a_naa = _dt(2026, 10, 9, 21, 30, tzinfo=_tz.utc)
_a_kamper = [{"date": "2026-10-04", "time": "17:00", "round": 21, "home": "Brann", "away": "Molde", "hg": 2, "ag": 1}]
# Brann-Viking hadde avspark 9.10. kl. 19:00 norsk tid (17:00Z): 4,5 timer før _a_naa.
_a_fx_sen = [{"round": 22, "matches": [{"home": "Brann", "away": "Viking", "date": "2026-10-09", "time": "19:00", "played": False}]}]
_a_fx_ok = [{"round": 23, "matches": [{"home": "Viking", "away": "Brann", "date": "2026-10-18", "time": "17:00", "played": False}]}]
_a_tk_ok = {"errors": 0, "avvik": []}
_a_tk_rod = {"errors": 2, "avvik": ["Tabell, Brann: 2 uavgjort hos oss, 3 hos ligasiden", "Tabell, Viking: 17 vunnet hos oss, 16 hos ligasiden"]}


def _a_kjor(fixtures, tk, datofeil=None, utenfor=(), merged=None, daglig=None, modell=None):
    """Kjører etter_skriving med innbyttet arbeid. Returnerer (rekkefølgen, feilen eller None)."""
    logg = []
    ekte = (_uda.fetch_odds_history.main, _uda.merge_odds.main, _uda.fit_model.main, _uda.run_daily_audit,
            _uda.write_status, _uda.should_fetch.merk_ok, _lda.meld_data_skrevet, _uda.sjekk_manglende_resultat)
    ekte_mangler = _uda.sjekk_manglende_resultat

    def _mangler(fx, naa, log):
        logg.append("kontroll: mangler sluttresultat")
        return ekte_mangler(fx, naa, log)

    def _daglig(m, k, naa, log):
        logg.append("kontroll: daglig")
        return daglig() if daglig else True
    _uda.fetch_odds_history.main = lambda: logg.append("sluttodds")
    _uda.merge_odds.main = lambda: logg.append("odds slått sammen")
    _uda.fit_model.main = modell or (lambda: logg.append("modell"))
    _uda.run_daily_audit = _daglig
    _uda.write_status = lambda ok, now, error=None: logg.append(f"status ok={ok}")
    _uda.should_fetch.merk_ok = lambda liga, naa=None: logg.append("20-timersklokka nullstilt")
    _lda.meld_data_skrevet = lambda miljo=None: logg.append("data skrevet")
    _uda.sjekk_manglende_resultat = _mangler
    try:
        with _vern.miljo(ODDSPAPI_KEY=None):
            _uda.etter_skriving(_a_kamper, fixtures, merged if merged is not None else _a_kamper, list(utenfor),
                                datofeil, tk, [], _a_naa, lambda _s: None)
        feilen = None
    except Exception as e:
        feilen = e
    finally:
        (_uda.fetch_odds_history.main, _uda.merge_odds.main, _uda.fit_model.main, _uda.run_daily_audit,
         _uda.write_status, _uda.should_fetch.merk_ok, _lda.meld_data_skrevet, _uda.sjekk_manglende_resultat) = ekte
    return logg, feilen


_ARBEID = ["sluttodds", "odds slått sammen", "modell", "data skrevet"]
_logg, _e = _a_kjor(_a_fx_ok, _a_tk_ok)
sjekk("alt i orden: arbeidet først, så kontrollene, så grønn status og nullstilt 20-timersklokke",
      _e is None and _logg == _ARBEID + ["kontroll: mangler sluttresultat", "kontroll: daglig", "20-timersklokka nullstilt", "status ok=True"],
      f"{_logg} {_e!r}")

_logg, _e = _a_kjor(_a_fx_sen, _a_tk_ok)
sjekk("kamp uten resultat 4,5 timer etter avspark: sluttodds, odds og modell er kjørt FØR kontrollen slår ut",
      isinstance(_e, _uda.DataAuditError) and _logg[:4] == _ARBEID and _logg.index("modell") < _logg.index("kontroll: mangler sluttresultat"),
      f"{_logg} {_e!r}")
sjekk("og den daglige kontrollen kjørte selv om «mangler sluttresultat» slo ut (ingen kontroll stopper de andre)",
      "kontroll: daglig" in _logg and _logg.index("kontroll: daglig") > _logg.index("kontroll: mangler sluttresultat"), str(_logg))
sjekk("én kontroll: feilteksten er den samme som før, og status skrives ikke grønn",
      str(_e).startswith("1 kamp(er) mangler sluttresultat mer enn 3 timer etter avspark:") and "Brann-Viking" in str(_e)
      and "status ok=True" not in _logg, f"{str(_e)[:200]} {_logg}")

_logg, _e = _a_kjor(_a_fx_sen, _a_tk_rod)
_l1 = str(_e).splitlines()[0]
sjekk("to kontroller slår ut samtidig: første linje nevner begge, og begge tekstene står under",
      isinstance(_e, _uda.DataAuditError) and _l1 == "2 kontroller fant avvik: mangler sluttresultat; tabellkontroll"
      and "Brann-Viking (2026-10-09 19:00)" in str(_e) and "2 kritisk(e) avvik mellom tabellen vår og tabellen på ligasiden: Tabell, Brann" in str(_e),
      str(_e)[:500])
sjekk("og modellen er likevel tilpasset, og «data skrevet» er meldt før kontrollene", _logg[:4] == _ARBEID, str(_logg))

# Den daglige kontrollen slår ut: vedlikeholdet er ikke utført, så
# 20-timersklokka nullstilles ikke (da prøves det igjen etter en time).
def _a_daglig_rod():
    raise _uda.DataAuditError("1 avvik mellom matches.json og kontrollkilden:\nBrann-Molde: 2-1 hos oss, 3-1 hos kontrollkilden")
_logg, _e = _a_kjor(_a_fx_ok, _a_tk_rod, daglig=_a_daglig_rod)
sjekk("den daglige kontrollen slår ut: rødt, 20-timersklokka nullstilles IKKE, og tabellkontrollen sies fra om i samme feil",
      isinstance(_e, _uda.DataAuditError) and "20-timersklokka nullstilt" not in _logg
      and str(_e).splitlines()[0] == "2 kontroller fant avvik: daglig kontroll; tabellkontroll", f"{_logg} {str(_e)[:300]}")
_logg, _e = _a_kjor(_a_fx_ok, _a_tk_rod)
sjekk("bare tabellkontrollen slår ut: det daglige vedlikeholdet er utført, så klokka nullstilles (som før), og feilteksten er uendret",
      isinstance(_e, _uda.DataAuditError) and "20-timersklokka nullstilt" in _logg
      and str(_e) == "2 kritisk(e) avvik mellom tabellen vår og tabellen på ligasiden: Tabell, Brann: 2 uavgjort hos oss, 3 hos ligasiden",
      f"{_logg} {str(_e)[:300]}")

# Datovaktene: bare det å gjøre kjøringen rød ligger til slutt.
_a_mange = [{"home": f"A{i}", "away": f"B{i}"} for i in range(100)]
_logg, _e = _a_kjor(_a_fx_ok, _a_tk_ok, utenfor=[f"A{i}-B{i} (2026-01-07)" for i in range(26)], merged=_a_mange)
sjekk("26 av 100 datoer utenfor sesongen: rødt til slutt, etter modellen",
      isinstance(_e, _uda.DataAuditError) and _logg[:4] == _ARBEID and str(_e).startswith("26 av 100 kamper hadde dato utenfor sesongen"),
      f"{_logg} {str(_e)[:200]}")
_logg, _e = _a_kjor(_a_fx_ok, _a_tk_ok, utenfor=[f"A{i}-B{i} (2026-01-07)" for i in range(25)], merged=_a_mange)
sjekk("motprøve: 25 av 100 er enkeltfeil (datoene er alt beholdt), ikke rødt", _e is None and "status ok=True" in _logg, f"{_logg} {_e!r}")

# Et krasj i arbeidet er ikke en kontroll: det stopper som før, og «data
# skrevet» meldes ikke.
def _a_modell_krasj():
    raise RuntimeError("modellen konvergerte ikke")
_logg, _e = _a_kjor(_a_fx_sen, _a_tk_rod, modell=_a_modell_krasj)
sjekk("krasjer modellen: kjøringen stopper der (som før), «data skrevet» meldes ikke, og kontrollene kjøres ikke",
      isinstance(_e, RuntimeError) and "data skrevet" not in _logg and not any(l.startswith("kontroll") for l in _logg), f"{_logg} {_e!r}")

# data_skrevet til workflowen.
_a_ut = Path(_tfa.mkdtemp()) / "github_output"
_a_ut.write_text("should_fetch=true\n", encoding="utf-8")
sjekk("meld_data_skrevet legger data_skrevet=true til i stegets utdata (GITHUB_OUTPUT)",
      _lda.meld_data_skrevet({"GITHUB_OUTPUT": str(_a_ut)}) is True
      and _a_ut.read_text("utf-8") == "should_fetch=true\ndata_skrevet=true\n", _a_ut.read_text("utf-8"))
sjekk("utenfor Actions (ingen GITHUB_OUTPUT) gjør den ingenting", _lda.meld_data_skrevet({}) is False)

# Varselet: flere kontroller i én e-post.
_a_status = {"ok": False, "error": _uda.samlet_feiltekst([("mangler sluttresultat", "1 kamp(er) mangler sluttresultat"),
                                                           ("tabellkontroll", "2 kritisk(e) avvik mellom tabellen vår og tabellen på ligasiden")])[:300]}
sjekk("livstegn: to kontroller gir kategorien «flere kontroller», og detaljen nevner begge",
      _lta.hva_feilet("failure", {"oppdater": {"outcome": "failure"}}, _a_status)
      == ("flere kontroller", "2 kontroller fant avvik: mangler sluttresultat; tabellkontroll\n"
          "mangler sluttresultat: 1 kamp(er) mangler sluttresultat\n"
          "tabellkontroll: 2 kritisk(e) avvik mellom tabellen vår og tabellen på ligasiden"),
      str(_lta.hva_feilet("failure", {"oppdater": {"outcome": "failure"}}, _a_status)))
sjekk("livstegn: én kontroll gir samme kategori som før (tabellkontroll)",
      _lta.hva_feilet("failure", {"oppdater": {"outcome": "failure"}},
                      {"ok": False, "error": "2 kritisk(e) avvik mellom tabellen vår og tabellen på ligasiden: Tabell, Brann"})[0] == "tabellkontroll")

print("\n=== Datovakten beholder den gamle datoen FØR noe skrives (hele update_data.main i en sandkasse) ===")
# 9.10.2026 viste ligasiden Rosenborg-Start (7.11.) som 7.1. En mistenkelig
# dato skal aldri ut på siden: rimelige_datoer() setter den gamle datoen
# tilbake før matches.json og fixtures.json skrives. Det eneste som ligger til
# slutt, er å gjøre kjøringen rød når det er mange slike. Her kjøres hele
# main() med dataene fra 1.10. og kildene byttet ut.
_a_sb = Path(_tfa.mkdtemp())
(_a_sb / "eliteserien" / "data").mkdir(parents=True)
(_a_sb / "data").mkdir()
for _f in ("matches.json", "fixtures.json"):
    _sha.copy(ROT / "tests" / "data" / "2026-10-01" / "eliteserien" / "data" / _f, _a_sb / "eliteserien" / "data" / _f)
(_a_sb / "data" / "sesonger.json").write_text(json.dumps(
    {"version": 2, "ligaer": {"eliteserien": {"aktiv": "2026", "sesonger": {"2026": {"status": "aktiv"}}}}}), encoding="utf-8")
_a_liste = _lda.forrige_terminliste(_a_sb / "eliteserien" / "data", "2026")
_a_uspilte = [r for r in _a_liste if r["hg"] is None]
_a_forste = min(_dt.fromisoformat(f"{r['date']}T{r['time']}").replace(tzinfo=ZoneInfo("Europe/Oslo")) for r in _a_uspilte)
_a_naa_m = (_a_forste - _tda(hours=2)).astimezone(_tz.utc)      # ingen kamp venter på resultat
_a_offer = _a_uspilte[-1]                                        # siste uspilte kamp i terminlisten
_a_gamle = {(r["home"], r["away"]): (r["date"], r["time"]) for r in _a_liste}


_a_hentet = []     # kildene sandkassen ble spurt om i siste kjøring («ligasiden»)


def _a_main(ntf_rader, naa=None, tabell=None, state=None, espn=None, forbered=None):
    """Kjører update_data.main i sandkassen. Returnerer (feilen eller None, rekkefølgen, datoene på disk da modellen ble tilpasset).
    naa: klokka (standard: to timer før første uspilte kamp). tabell: tabellen fra ligasiden. state: results_state.json før kjøringen.
    espn: radene ESPN-sesongkallet svarer med (uten: kallet feiler, og «NETTKALL» står i rekkefølgen). forbered(d): endrer filene i
    sandkassen før kjøringen (d er datakatalogen; sesongregisteret ligger i d.parent.parent / "data" / "sesonger.json")."""
    import tabellkontroll as _tka, daglig_revisjon as _dra
    logg, paa_disk = [], {}
    d = _a_sb / "eliteserien" / "data"
    for _f in ("matches.json", "fixtures.json"):
        _sha.copy(ROT / "tests" / "data" / "2026-10-01" / "eliteserien" / "data" / _f, d / _f)
    for _f in ("status.json", "audit_state.json", "audit_tabell.json", "results_state.json", "github_output",
               "flytting_venter.json", "flytting_overstyring.json"):
        (d / _f).unlink(missing_ok=True)
    (_a_sb / "data" / "sesonger.json").write_text(json.dumps(
        {"version": 2, "ligaer": {"eliteserien": {"aktiv": "2026", "sesonger": {"2026": {"status": "aktiv"}}}}}), encoding="utf-8")
    if forbered:
        forbered(d)
    if state is not None:
        (d / "results_state.json").write_text(json.dumps(state), encoding="utf-8")
    ekte = (_uda.ROOT, _uda.LEAGUE, _uda.STATE, _uda.STATUS_PATH, _uda.AUDIT_STATE_PATH, _uda.espn_source.fetch_all,
            _uda.ligasiden_eller_reserve, _uda.get_ffk_rows, _uda.espn_source.fetch_season, _uda.ntf_source.hent_kalender,
            _uda.ntf_source.siste_tabell, _uda.fetch_odds_history.main, _uda.merge_odds.main, _uda.fit_model.main,
            _uda.should_fetch.merk_ok, _tka.avvik, _dra.data_katalog)

    def _modell():
        logg.append("modell")
        paa_disk.update({(r["home"], r["away"]): (r["date"], r["time"]) for r in _lda.forrige_terminliste(d, "2026")})

    def _ikke_kall(*a, **k):
        logg.append("NETTKALL")
        raise RuntimeError("testen skal ikke trenge denne kilden")
    _ekte_avvik = _tka.avvik
    (_uda.ROOT, _uda.LEAGUE, _uda.STATE, _uda.STATUS_PATH, _uda.AUDIT_STATE_PATH) = (
        _a_sb, _a_sb / "eliteserien", d / "results_state.json", d / "status.json", d / "audit_state.json")
    _uda.espn_source.fetch_all = lambda cache_dir=None, log=None: []
    _a_hentet.clear()
    _uda.ligasiden_eller_reserve = lambda cache_dir=None, log=None: (_a_hentet.append("ligasiden"), [dict(r) for r in ntf_rader])[1]
    _uda.get_ffk_rows = lambda cache_dir, log: [dict(r) for r in _a_liste if r["hg"] is not None]
    _uda.espn_source.fetch_season = _ikke_kall if espn is None else (lambda aar, log=None: (logg.append("ESPN"), [dict(r) for r in espn])[1])
    _uda.ntf_source.hent_kalender = _ikke_kall
    _uda.ntf_source.siste_tabell = lambda liga: tabell
    _uda.fetch_odds_history.main = lambda: logg.append("sluttodds")
    _uda.merge_odds.main = lambda: logg.append("odds slått sammen")
    _uda.fit_model.main = _modell
    _uda.should_fetch.merk_ok = lambda liga, naa=None: logg.append("20-timersklokka nullstilt")
    _tka.avvik = lambda liga, data_dir=None: _ekte_avvik(liga, data_dir=data_dir or d)
    _dra.data_katalog = lambda liga, sesong=None: d
    try:
        with _vern.miljo(ODDSPAPI_KEY=None, GITHUB_OUTPUT=str(d / "github_output")):
            _uda.main(now=naa or _a_naa_m)
        feilen = None
    except Exception as e:
        feilen = e
    finally:
        (_uda.ROOT, _uda.LEAGUE, _uda.STATE, _uda.STATUS_PATH, _uda.AUDIT_STATE_PATH, _uda.espn_source.fetch_all,
         _uda.ligasiden_eller_reserve, _uda.get_ffk_rows, _uda.espn_source.fetch_season, _uda.ntf_source.hent_kalender,
         _uda.ntf_source.siste_tabell, _uda.fetch_odds_history.main, _uda.merge_odds.main, _uda.fit_model.main,
         _uda.should_fetch.merk_ok, _tka.avvik, _dra.data_katalog) = ekte
    return feilen, logg, paa_disk


def _a_fil(navn):
    return json.loads((_a_sb / "eliteserien" / "data" / navn).read_text("utf-8"))


def _a_utdata():
    sti = _a_sb / "eliteserien" / "data" / "github_output"
    return sti.read_text("utf-8") if sti.exists() else ""


# 0) Motprøve: kilden er lik det vi har. Grønt, og ingenting flyttes.
_e, _logg, _disk = _a_main(_a_liste)
sjekk("sandkassen: uendret kilde gir grønn kjøring, grønn status og «data skrevet»",
      _e is None and _a_fil("status.json")["ok"] is True and "data_skrevet=true" in _a_utdata() and "NETTKALL" not in _logg
      and _disk == _a_gamle, f"{_e!r} {_logg}")

# 1) Én mistenkelig dato: kampen beholder den gamle datoen på disk.
_k_offer = (_a_offer["home"], _a_offer["away"])
_e, _logg, _disk = _a_main([{**r, "date": "2026-01-07", "time": "18:00"} if (r["home"], r["away"]) == _k_offer else r for r in _a_liste])
_fx_offer = [m for r in _a_fil("fixtures.json") for m in r["matches"] if (m["home"], m["away"]) == _k_offer]
sjekk(f"{_k_offer[0]}-{_k_offer[1]} oppgis med 7.1.: fixtures.json har den gamle datoen ({_a_offer['date']} {_a_offer['time']}), og 2026-01-07 står ingen steder",
      _e is None and "NETTKALL" not in _logg and len(_fx_offer) == 1 and (_fx_offer[0]["date"], _fx_offer[0]["time"]) == (_a_offer["date"], _a_offer["time"])
      and "2026-01-07" not in json.dumps(_a_fil("fixtures.json")) + json.dumps(_a_fil("matches.json")),
      f"{_e!r} {_fx_offer}")
sjekk("og den gamle datoen sto på disk FØR modellen ble tilpasset (datovakten ligger før skrivingen)",
      _disk.get(_k_offer) == (_a_offer["date"], _a_offer["time"]) and _disk == _a_gamle, str(_disk.get(_k_offer)))

# 2) Mange mistenkelige datoer: alle de uspilte kampene (over 25 % av
#    terminlisten) og 40 spilte. De spilte er frosset før datovakten (en spilt
#    kamp flyttes aldri), de uspilte beholder den gamle datoen i datovakten.
#    Alt skjer før skriving; arbeidet kjøres, og kjøringen blir rød TIL SLUTT.
_a_gale = {(r["home"], r["away"]) for r in _a_uspilte} | {(r["home"], r["away"]) for r in [x for x in _a_liste if x["hg"] is not None][:40]}
_e, _logg, _disk = _a_main([{**r, "date": "2026-01-07"} if (r["home"], r["away"]) in _a_gale else r for r in _a_liste])
sjekk(f"{len(_a_gale)} av {len(_a_liste)} datoer er gale ({len(_a_uspilte)} uspilte): kjøringen blir rød med datovaktens beskjed om de uspilte",
      len(_a_uspilte) > len(_a_liste) * 0.25 and isinstance(_e, _uda.DataAuditError)
      and str(_e).startswith(f"{len(_a_uspilte)} av {len(_a_liste)} kamper hadde dato utenfor sesongen"), f"{len(_a_gale)} {_e!r}"[:300])
sjekk("men ingen gal dato er skrevet: matches.json og fixtures.json har de gamle datoene for alle kampene",
      "2026-01-07" not in json.dumps(_a_fil("fixtures.json")) + json.dumps(_a_fil("matches.json"))
      and {(r["home"], r["away"]): (r["date"], r["time"]) for r in _lda.forrige_terminliste(_a_sb / "eliteserien" / "data", "2026")} == _a_gamle)
sjekk("de gamle datoene sto på disk da modellen ble tilpasset, og sluttodds, odds og modell kjørte før kjøringen ble rød",
      _disk == _a_gamle and _logg[:3] == ["sluttodds", "odds slått sammen", "modell"], f"{_logg}")
sjekk("status.json er rød med beskjeden, og «data skrevet» er meldt så stegene etterpå kjøres",
      _a_fil("status.json")["ok"] is False and "dato utenfor" in _a_fil("status.json")["error"] and "data_skrevet=true" in _a_utdata(),
      f"{_a_fil('status.json')} {_a_utdata()!r}")

print("\n=== OBOS-byggingen: begge kontrollene til slutt, etter «data skrevet» ===")
_a_ob = (ROT / "scripts" / "obos_build_data.py").read_text("utf-8")
_a_hale = _a_ob[_a_ob.index('print("  skrev matches.json, fixtures.json, model.json, status.json")'):]
sjekk("obos_build_data: «data skrevet» meldes etter at modellen og status er skrevet, og før kontrollene avgjør utfallet",
      _a_ob.index('(DATA / "model.json").write_text') < _a_ob.index("leaguedata.meld_data_skrevet()") < _a_ob.index("return 1 if feil else 0")
      and _a_hale.index("leaguedata.meld_data_skrevet()") < _a_hale.index("if DATOVAKT_FEIL:") < _a_hale.index('if _tk["errors"]:'))
sjekk("obos_build_data: datovakten og tabellkontrollen samles (ingen return mellom dem), så begge sies fra om",
      "return" not in _a_hale[_a_hale.index("if DATOVAKT_FEIL:"):_a_hale.index("for f in feil:")])

print("\n=== Workflowene: stegene etter dataskriptet kjøres når dataene er skrevet ===")
for _wf_a, _sid_a, _steg_a, _ekstra_a in (
        ("update-data.yml", "oppdater", ("uses: actions/setup-node", "name: Lagre sannsynlighetene etter nye resultater", "name: Treffsikkerhetslogg",
                                         "name: Lag delingsbilde", "name: Daglig revisjon av terminlisten"), ""),
        ("obos-results.yml", "bygg", ("name: Rundens viktigste kamp, forrige kamp og historikk", "name: Treffsikkerhetslogg",
                                      "name: Daglig revisjon av terminlisten", "name: Tegn delingsbildet"), " && !inputs.dry_run")):
    _wt_a = (ROT / ".github" / "workflows" / _wf_a).read_text("utf-8")
    _biter_a = _wt_a.split("\n      - ")[1:]
    _vilkaar_a = (f"if: ${{{{ !cancelled() && steps.gate.outputs.should_fetch == 'true'{_ekstra_a} && "
                  f"(steps.{_sid_a}.outcome == 'success' || steps.{_sid_a}.outputs.data_skrevet == 'true') }}}}")
    _funnet_a = [b for b in _biter_a if any(b.startswith(n) for n in _steg_a)]
    sjekk(f"{_wf_a}: {len(_steg_a)} steg etter dataskriptet kjøres når skriptet var grønt ELLER meldte «data skrevet» (ikke ved avbrutt)",
          len(_funnet_a) == len(_steg_a) and all(sum(1 for l in b.splitlines() if l.strip().startswith("if:")) == 1
                                                 and f"        {_vilkaar_a}\n" in b for b in _funnet_a),
          str([b.splitlines()[0] for b in _funnet_a]))
    _etter_a = _biter_a[next(i for i, b in enumerate(_biter_a) if f"\n        id: {_sid_a}\n" in b) + 1:]
    _lagre_a = next(i for i, b in enumerate(_etter_a) if b.startswith("name: Committer og pusher") or b.startswith("name: Lagre hvis noe endret seg"))
    _uten_a = [b.splitlines()[0] for b in _etter_a[:_lagre_a]
               if "always()" not in b and "!cancelled()" not in b and "Merk daglig vedlikehold" not in b]
    sjekk(f"{_wf_a}: ingen andre steg mellom dataskriptet og lagringen hoppes over ved rød kontroll (bare «Merk daglig vedlikehold»)",
          not _uten_a, str(_uten_a))
_wt_o = (ROT / ".github" / "workflows" / "obos-results.yml").read_text("utf-8")
_merk_o = next(b for b in _wt_o.split("\n      - ")[1:] if b.startswith("name: Merk daglig vedlikehold"))
sjekk("obos-results.yml: «Merk daglig vedlikehold» krever fortsatt grønn bygging (vedlikeholdet prøves igjen etter en time)",
      "&& steps.bygg.outcome == 'success'" in _merk_o and "data_skrevet" not in _merk_o, _merk_o[-400:])

print("\n=== Bekreftelsen lagres når resultatet publiseres (resultatregel.py, 12.10.2026) ===")
import resultatregel as _rrb
import tabellkontroll as _tkb
_TEK = TESTDATA / "tabell_etter_kamp"
_b_les = lambda navn: json.loads((_TEK / navn).read_text("utf-8"))
sjekk("uavhengige_enige: bare kildene utenfor NTF med nøyaktig samme resultat (ligasiden og fotball.no er NTF)",
      _rrb.uavhengige_enige({"ligasiden": (0, 2), "fotball.no": (0, 2), "espn": (0, 2), "highlightly": (0, 0),
                             "ffksupporter": None, "wikipedia": (0, 2)}, (0, 2)) == ["espn", "wikipedia"])
_b_1900 = _dt(2026, 10, 9, 19, 0, tzinfo=_tz.utc)
_b_t = _rrb.bekreftet_tilstand(
    {"Gammel|Kamp": {"resultat": [1, 0], "kilder": ["espn"], "publisert": "2026-10-07T19:00:00+00:00"},
     "Nyere|Kamp": {"resultat": [1, 1], "kilder": ["espn"], "publisert": "2026-10-07T19:10:00+00:00"}},
    {("Brann", "Viking"): ((0, 2), ["highlightly", "espn"]), ("Bare", "NTF"): ((1, 0), [])}, _b_1900)
sjekk("bekreftet_tilstand: nytt resultat lagres med kildene og tidspunktet; uten kilde utenfor NTF lagres ingenting; 48 timer gammelt tas ut",
      _b_t == {"Nyere|Kamp": {"resultat": [1, 1], "kilder": ["espn"], "publisert": "2026-10-07T19:10:00+00:00"},
               "Brann|Viking": {"resultat": [0, 2], "kilder": ["espn", "highlightly"], "publisert": "2026-10-09T19:00:00+00:00"}}, str(_b_t))


print("\n=== Ferske kamper med bekreftet resultat (resultatregel.ferske_bekreftede) ===")
# 9.10.2026: Brann-Viking 0-2, avspark 19:00 norsk tid (17:00Z). Fristen er seks timer etter avspark.
_b_es = _b_les("eliteserien_matches.json")
_b_k0910 = [m for m in _b_es if m["date"] <= "2026-10-09"]
_b_sb = Path(_tf2.mkdtemp())
_b_state = _b_sb / "results_state.json"


def _b_skriv(bekreftet):
    _b_state.write_text(json.dumps({"bekreftet": bekreftet}), encoding="utf-8")


_BV = {"Brann|Viking": {"resultat": [0, 2], "kilder": ["espn", "highlightly"], "publisert": "2026-10-09T19:00:00+00:00"}}
_b_skriv(_BV)
_b_f = _rrb.ferske_bekreftede("eliteserien", _b_k0910, _b_1900, state_sti=_b_state)
sjekk("to timer etter avspark, bekreftet av espn og highlightly: kampen er fersk, med avspark og frist (seks timer etter avspark)",
      _b_f == [{"home": "Brann", "away": "Viking", "hg": 0, "ag": 2, "avspark": "2026-10-09T17:00:00+00:00",
                "frist": "2026-10-09T23:00:00+00:00", "kilder": ["espn", "highlightly"]}], str(_b_f))
sjekk("5 t 59 min etter avspark: fortsatt fersk",
      len(_rrb.ferske_bekreftede("eliteserien", _b_k0910, _dt(2026, 10, 9, 22, 59, tzinfo=_tz.utc), state_sti=_b_state)) == 1)
sjekk("seks timer etter avspark: ikke lenger fersk",
      _rrb.ferske_bekreftede("eliteserien", _b_k0910, _dt(2026, 10, 9, 23, 0, tzinfo=_tz.utc), state_sti=_b_state) == [])
_b_skriv({})
sjekk("resultatet står ikke som bekreftet: ikke med", _rrb.ferske_bekreftede("eliteserien", _b_k0910, _b_1900, state_sti=_b_state) == [])
_b_skriv({"Brann|Viking": {**_BV["Brann|Viking"], "resultat": [0, 0]}})
sjekk("det bekreftede resultatet (0-0) er et annet enn det vi har (0-2): ikke med",
      _rrb.ferske_bekreftede("eliteserien", _b_k0910, _b_1900, state_sti=_b_state) == [])
_b_skriv({"Brann|Viking": {**_BV["Brann|Viking"], "kilder": []}})
sjekk("ingen kilde utenfor NTF: ikke med", _rrb.ferske_bekreftede("eliteserien", _b_k0910, _b_1900, state_sti=_b_state) == [])
_b_state.unlink()
sjekk("ingen results_state.json: ikke med", _rrb.ferske_bekreftede("eliteserien", _b_k0910, _b_1900, state_sti=_b_state) == [])
_b_skriv(_BV)

print("\n=== Tabellkontrollen rett etter kampslutt: advarsel og ny sjekk, ikke rødt (tabellkontroll.ferske_unntak) ===")
# De ekte tabellene fra ligasiden 9.10.2026 (labens kildearkiv): kl. 21:00
# (19:00Z) var Brann-Viking ført som 0-0, kl. 22:10 (20:10Z) var den rettet.
_b_t1900, _b_t2010 = _b_les("eliteserien_tabell_2026-10-09T1900Z.json"), _b_les("eliteserien_tabell_2026-10-09T2010Z.json")
_B_URL = "https://www.eliteserien.no/resultater"


def _b_kontroll(kamper, tabell, naa, ferske, mappe=None, liga="eliteserien", url=_B_URL, just=None):
    d = mappe or Path(_tf2.mkdtemp())
    if just is not None:
        (d / "justeringer.json").write_text(json.dumps({"justeringer": just}, ensure_ascii=False), encoding="utf-8")
    linjer = []
    ut = _tkb.kontroller(liga, 2026, kamper, tabell, naa=naa, data_dir=d, kilde_url=url, kjoring="test",
                         log=linjer.append, ferske=ferske)
    return ut, linjer, d


def _b_endre(tabell, **endringer):
    """Tabellen med noen felt lagt til for enkelte lag: _b_endre(t, Molde={"mm": 1})."""
    return [{**r, **{f: r[f] + v for f, v in endringer.get(r["lag"], {}).items()}} for r in tabell]


def _b_tabell(kamper, erstatt=None, uten=()):
    """En «offisiell» tabell regnet av kampene, der noen er ført med et annet resultat (erstatt) eller mangler (uten)."""
    k = [{**m, **dict(zip(("hg", "ag"), (erstatt or {}).get((m["home"], m["away"]), (m["hg"], m["ag"]))))}
         for m in kamper if (m["home"], m["away"]) not in uten]
    lag = sorted({m["home"] for m in kamper} | {m["away"] for m in kamper})
    v = _tkb.vaar_tabell(k, lag)
    return [{"plass": r["plass"], "lag": l, **{f: r[f] for f in ("k", "v", "u", "t", "mf", "mm", "poeng")}, "diff": r["mf"] - r["mm"]}
            for l, r in v.items()]


_ut, _lin, _b_d = _b_kontroll(_b_k0910, _b_t1900, _b_1900, _b_f)
sjekk("9.10. kl. 21:00, Brann-Viking ført som 0-0 hos ligasiden, resultatet vårt bekreftet: ingen kritiske avvik",
      _ut["errors"] == 0 and _ut["avvik"] == [] and _ut["sammenlignet"] is True, str(_ut))
sjekk("advarselen sier hvilken kamp, hva tabellen viser, resultatet vårt, hvem som bekreftet det og fristen",
      _ut["advarsler"] == ["Tabell: Brann og Viking avviker bare i Brann-Viking, som er ført som 0-0 i tabellen på eliteserien.no. "
                           "Hos oss 0-2, bekreftet av espn og highlightly. Avspark 19:00, sjekkes på nytt i neste kjøring (frist 01:00)."],
      str(_ut["advarsler"]))
sjekk("kampen står i «venter» med resultatet, kildene, fristen og grunnen",
      _ut["venter"] == [{"kamp": "Brann|Viking", "resultat": [0, 2], "avspark": "2026-10-09T17:00:00+00:00",
                         "frist": "2026-10-09T23:00:00+00:00", "kilder": ["espn", "highlightly"], "grunn": "ført som 0-0 i tabellen"}],
      str(_ut["venter"]))
sjekk("«alle like» settes ikke, så frysingen kan ikke bygge på denne kontrollen", _ut["alle_like"] is False and _ut["siste_like"] is None)
sjekk("gul merknad i Actions, og status.json blir ikke rød av dette (tabellkontroll.avvik er 0)",
      any(l.startswith("::warning title=Tabellen på eliteserien.no henger etter::Tabell: Brann og Viking") for l in _lin)
      and _tkb.avvik("eliteserien", data_dir=_b_d) == 0, str(_lin))
_ut, _lin, _ = _b_kontroll(_b_k0910, _b_t2010, _dt(2026, 10, 9, 20, 10, tzinfo=_tz.utc),
                           _rrb.ferske_bekreftede("eliteserien", _b_k0910, _dt(2026, 10, 9, 20, 10, tzinfo=_tz.utc), state_sti=_b_state), mappe=_b_d)
sjekk("ny sjekk kl. 22:10, tabellen er rettet: alle like, ingenting venter, og den vellykkede kontrollen er lagret",
      _ut["errors"] == 0 and _ut["alle_like"] is True and _ut["venter"] == [] and _ut["siste_like"]
      and not any("henger etter" in l for l in _lin), str(_ut)[:400])

# Regelen som før når vilkårene ikke er oppfylt.
_ut, _lin, _ = _b_kontroll(_b_k0910, _b_t1900, _b_1900, [])
sjekk("samme tabell, resultatet IKKE bekreftet: to kritiske avvik som før (Brann og Viking)",
      _ut["errors"] == 2 and _ut["venter"] == [] and _ut["avvik"][0].startswith("Tabell, Brann: 2 uavgjort hos oss, 3 hos eliteserien.no; 11 tap hos oss, 10 hos")
      and _ut["avvik"][1].startswith("Tabell, Viking: 17 vunnet hos oss, 16 hos"), str(_ut["avvik"]))
_ut, _lin, _ = _b_kontroll(_b_k0910, _b_t1900, _b_1900, None)
sjekk("og uten ferske kamper i det hele tatt (kalleren sender ingen): som før", _ut["errors"] == 2 and _ut["venter"] == [])
_b_2310 = _dt(2026, 10, 9, 23, 10, tzinfo=_tz.utc)
_ut, _lin, _ = _b_kontroll(_b_k0910, _b_t1900, _b_2310, _rrb.ferske_bekreftede("eliteserien", _b_k0910, _b_2310, state_sti=_b_state), mappe=_b_d)
sjekk("tabellen er fortsatt feil 6 t 10 min etter avspark (fristen er ute): kritisk som før, og ingenting venter lenger",
      _ut["errors"] == 2 and _ut["venter"] == [] and _tkb.avvik("eliteserien", data_dir=_b_d) == 2, str(_ut)[:300])
_ut, _lin, _ = _b_kontroll(_b_k0910, _b_endre(_b_t1900, Molde={"mm": 1, "diff": -1}), _b_1900, _b_f)
sjekk("et tredje lag (Molde) avviker i tillegg: det er kritisk og gjør kjøringen rød; Brann-Viking venter fortsatt",
      _ut["errors"] == 1 and _ut["avvik"][0].startswith("Tabell, Molde:") and [v["kamp"] for v in _ut["venter"]] == ["Brann|Viking"], str(_ut)[:400])
_ut, _lin, _ = _b_kontroll(_b_k0910, _b_endre(_b_t1900, Brann={"mf": 2, "diff": 2}), _b_1900, _b_f)
sjekk("resten går ikke opp (Brann har to mål mer hos ligasiden enn en 0-0 forklarer): noe eldre er ulikt, kritisk for begge lagene",
      _ut["errors"] == 2 and _ut["venter"] == [] and {a.split(":")[0] for a in _ut["avvik"]} == {"Tabell, Brann", "Tabell, Viking"}, str(_ut)[:400])
_ut, _lin, _ = _b_kontroll(_b_k0910, _b_endre(_b_t1900, Viking={"v": 1, "u": -1, "mf": 1, "diff": 1, "poeng": 2}), _b_1900, _b_f)
sjekk("de to radene speiler ikke hverandre (Brann pluss en 0-0, Viking pluss en 1-0-seier): kritisk for begge",
      _ut["errors"] == 2 and _ut["venter"] == [], str(_ut)[:400])

# Halvveis oppdatert tabell: Brann er ført med 0-0, Viking mangler kampen.
_b_halv = [dict(r) for r in _b_t1900]
_b_vik = next(r for r in _b_halv if r["lag"] == "Viking")
_b_vik.update(k=_b_vik["k"] - 1, u=_b_vik["u"] - 1, poeng=_b_vik["poeng"] - 1)
_ut, _lin, _ = _b_kontroll(_b_k0910, _b_halv, _b_1900, _b_f)
sjekk("halvveis oppdatert tabell (Brann ført med 0-0, Viking uten kampen): gjelder bare den kampen, venter",
      _ut["errors"] == 0 and [(v["kamp"], v["grunn"]) for v in _ut["venter"]] == [("Brann|Viking", "ført som 0-0 i tabellen")], str(_ut)[:400])
# Samme halvveis oppdaterte tabell, men Brann-raden er ikke «vår rad uten
# kampen pluss én kamp»: da er noe eldre ulikt, og Brann er kritisk som før.
# (Viking mangler bare kampen, og har advarselen om ulikt antall kamper.)
for _b_navn, _b_felt in (("en uavgjort med to mål for og ingen mot finnes ikke", {"mf": 2, "diff": 2}),
                         ("en seier og en uavgjort mer, ett tap mindre: et eldre tap er blitt uavgjort", {"v": 1, "t": -1, "mf": 1, "diff": 1, "poeng": 3})):
    _ut, _lin, _ = _b_kontroll(_b_k0910, _b_endre(_b_halv, Brann=_b_felt), _b_1900, _b_f)
    sjekk(f"Brann-raden går ikke opp som én kamp ({_b_navn}): kritisk for Brann, ingenting venter",
          _ut["errors"] == 1 and _ut["avvik"][0].startswith("Tabell, Brann:") and _ut["venter"] == []
          and any("Viking: 22 kamper hos oss, 21 hos" in a for a in _ut["advarsler"]), str(_ut)[:500])

# To ferske kamper samme kveld, begge ført feil (10.10.: Bodø/Glimt-Kristiansund 3-1 og Rosenborg-Sandefjord 1-1).
_b_1810 = _dt(2026, 10, 10, 18, 10, tzinfo=_tz.utc)
_b_skriv({"Bodø/Glimt|Kristiansund": {"resultat": [3, 1], "kilder": ["espn"], "publisert": "2026-10-10T16:00:00+00:00"},
          "Rosenborg|Sandefjord": {"resultat": [1, 1], "kilder": ["highlightly"], "publisert": "2026-10-10T18:00:00+00:00"}})
_b_f2 = _rrb.ferske_bekreftede("eliteserien", _b_es, _b_1810, state_sti=_b_state)
_ut, _lin, _ = _b_kontroll(_b_es, _b_tabell(_b_es, erstatt={("Bodø/Glimt", "Kristiansund"): (0, 0), ("Rosenborg", "Sandefjord"): (0, 1)}), _b_1810, _b_f2)
sjekk("to ferske kamper, begge ført med et annet resultat: begge venter, ingen kritiske avvik",
      len(_b_f2) == 2 and _ut["errors"] == 0
      and sorted((v["kamp"], v["grunn"]) for v in _ut["venter"]) == [("Bodø/Glimt|Kristiansund", "ført som 0-0 i tabellen"),
                                                                    ("Rosenborg|Sandefjord", "ført som 0-1 i tabellen")], str(_ut)[:500])
sjekk("motprøve: den konstruerte tabellen uten endringer er lik vår (alle like)",
      _b_kontroll(_b_es, _b_tabell(_b_es), _b_1810, _b_f2)[0]["alle_like"] is True)

# Et nytt poengtrekk for et annet lag mens noe venter: legges inn, men «alle like» settes ikke.
_ut, _lin, _b_d2 = _b_kontroll(_b_k0910, _b_endre(_b_t1900, Molde={"poeng": -1}), _b_1900, _b_f)
sjekk("nytt poengtrekk (Molde) mens Brann-Viking venter: trekket legges inn, og kontrollen regnes ikke som vellykket",
      [(j["lag"], j["poeng"]) for j in _ut["nye"]] == [("Molde", -1)] and _ut["errors"] == 0 and _ut["venter"]
      and _ut["alle_like"] is False and _ut["siste_like"] is None, str(_ut)[:500])

# Tabellen kan ikke leses i en ny sjekk: det som ventet, venter videre til fristen.
_ut, _lin, _b_d3 = _b_kontroll(_b_k0910, _b_t1900, _b_1900, _b_f)
_ut, _lin, _ = _b_kontroll(_b_k0910, {"feil": "fant ingen tabell på resultatsiden"}, _dt(2026, 10, 9, 19, 10, tzinfo=_tz.utc), _b_f, mappe=_b_d3)
sjekk("ny sjekk der tabellen ikke kan leses: ikke sammenlignet, og Brann-Viking venter videre",
      _ut["sammenlignet"] is False and _ut["errors"] == 0 and [v["kamp"] for v in _ut["venter"]] == ["Brann|Viking"], str(_ut)[:400])
_ut, _lin, _ = _b_kontroll(_b_k0910, {"feil": "fant ingen tabell på resultatsiden"}, _b_2310, [], mappe=_b_d3)
sjekk("og etter fristen venter ingenting lenger (da gjelder kontrollen som før når tabellen kan leses)", _ut["venter"] == [], str(_ut)[:300])

print("\n=== Tillegget: den ferske kampen mangler i tabellen på ligasiden ===")
# 10.10.2026 kl. 17:50 (15:50Z), den ekte tabellen: Bodø/Glimt-Kristiansund (3-1,
# avspark 16:00) var ikke kommet inn (21 kamper der, 22 hos oss).
_b_t1550 = _b_les("eliteserien_tabell_2026-10-10T1550Z.json")
_b_1550 = _dt(2026, 10, 10, 15, 50, tzinfo=_tz.utc)
_b_k1550 = [m for m in _b_es if (m["home"], m["away"]) != ("Rosenborg", "Sandefjord")]
_b_fm = _rrb.ferske_bekreftede("eliteserien", _b_k1550, _b_1550, state_sti=_b_state)
_ut, _lin, _b_d4 = _b_kontroll(_b_k1550, _b_t1550, _b_1550, _b_fm)
sjekk("kampen mangler i tabellen, resultatet er bekreftet: advarsel med kampen og fristen, og den venter på ny sjekk",
      _ut["errors"] == 0 and _ut["advarsler"] == ["Tabell: Bodø/Glimt-Kristiansund mangler i tabellen på eliteserien.no. Hos oss 3-1, bekreftet av espn. "
                                                 "Avspark 16:00, sjekkes på nytt i neste kjøring (frist 22:00)."]
      and [(v["kamp"], v["grunn"], v["frist"]) for v in _ut["venter"]] == [("Bodø/Glimt|Kristiansund", "mangler i tabellen", "2026-10-10T20:00:00+00:00")],
      f"{_ut['advarsler']} {_ut['venter']}")
_ut, _lin, _ = _b_kontroll(_b_k1550, _b_t1550, _b_1550, [])
sjekk("motprøve uten bekreftelse: de to advarslene som før («hentet på ulike tidspunkt»), og ingen ny sjekk",
      _ut["errors"] == 0 and _ut["venter"] == [] and len(_ut["advarsler"]) == 2
      and all("hentet på ulike tidspunkt, ikke sammenlignet" in a for a in _ut["advarsler"]), str(_ut["advarsler"]))
_b_2010 = _dt(2026, 10, 10, 20, 10, tzinfo=_tz.utc)
_ut, _lin, _ = _b_kontroll(_b_k1550, _b_t1550, _b_2010, _rrb.ferske_bekreftede("eliteserien", _b_k1550, _b_2010, state_sti=_b_state), mappe=_b_d4)
sjekk("kampen mangler fortsatt når fristen er ute: advarselen står som før, ikke rødt, og ingenting venter",
      _ut["errors"] == 0 and _ut["venter"] == [] and len(_ut["advarsler"]) == 2, str(_ut)[:400])

# OBOS 11.10.2026 kl. 18:50 (16:50Z), den ekte tabellen: alle åtte kampene manglet.
_b_ob = _b_les("obos_matches.json")
_b_obt = _b_les("obos_tabell_2026-10-11T1650Z.json")
_b_ob_naa = _dt(2026, 10, 11, 16, 50, tzinfo=_tz.utc)
_b_ob_ferske = [m for m in _b_ob if m["date"] == "2026-10-11"]
_b_ob_state = _b_sb / "obos_state.json"
_b_ob_state.write_text(json.dumps({"bekreftet": {f"{m['home']}|{m['away']}": {"resultat": [m["hg"], m["ag"]], "kilder": ["highlightly"],
                                                                                "publisert": "2026-10-11T16:50:00+00:00"} for m in _b_ob_ferske}}), encoding="utf-8")
_b_obf = _rrb.ferske_bekreftede("obos", _b_ob, _b_ob_naa, state_sti=_b_ob_state)
_b_just_ob = [{"sesong": 2026, "lag": "Åsane", "poeng": -1, "dato": "2026-03-04"}]
_ut, _lin, _ = _b_kontroll(_b_ob, _b_obt, _b_ob_naa, _b_obf, liga="obos", url="https://www.obos-ligaen.no/resultater", just=_b_just_ob)
sjekk(f"OBOS 11.10.: alle {len(_b_ob_ferske)} kampene i runden mangler i tabellen på obos-ligaen.no; alle venter, ingen kritiske avvik, ingen nye poengtrekk",
      len(_b_ob_ferske) == 8 and len(_b_obf) == 8 and _ut["errors"] == 0 and _ut["nye"] == []
      and sorted(v["kamp"] for v in _ut["venter"]) == sorted(f"{m['home']}|{m['away']}" for m in _b_ob_ferske)
      and all(v["grunn"] == "mangler i tabellen" for v in _ut["venter"]) and all("obos-ligaen.no" in a for a in _ut["advarsler"]),
      f"{len(_b_obf)} {_ut['errors']} {_ut['advarsler'][:2]}")
_b_obk = (ROT / "scripts" / "obos_build_data.py").read_text("utf-8")
sjekk("obos_build_data.py sender de ferske, bekreftede kampene fra obos/data/results_state.json til tabellkontrollen",
      'ferske=resultatregel.ferske_bekreftede("obos", matches_ut, datetime.now(timezone.utc),' in _b_obk
      and 'state_sti=DATA / "results_state.json"' in _b_obk)

print("\n=== Hele update_data.main: fersk kamp ført feil i tabellen gir grønn kjøring og ny sjekk ===")
# Sandkassen fra over (dataene fra 1.10.). Den siste spilte kampen er fersk
# (avspark for to timer siden), og tabellen fra ligasiden har ført den som
# 0-0. Bekreftelsen står i results_state.json fra kjøringen som publiserte
# resultatet; denne kjøringen har ingen nye resultater.
_b_spilte = sorted([r for r in _a_liste if r["hg"] is not None], key=lambda r: (r["date"], r["time"]))
_b_siste = next(r for r in reversed(_b_spilte) if (r["hg"], r["ag"]) != (0, 0))
_b_avsp = _dt.fromisoformat(f"{_b_siste['date']}T{_b_siste['time']}").replace(tzinfo=ZoneInfo("Europe/Oslo")).astimezone(_tz.utc)
_b_nokkel = f"{_b_siste['home']}|{_b_siste['away']}"
_b_feil_tabell = {"tabell": _b_tabell(_b_spilte, erstatt={(_b_siste["home"], _b_siste["away"]): (0, 0)}), "kilde": _B_URL}
_b_st_main = {"conflicts": [], "waiting": [], "ukontrollert": {}, "ukontrollert_sjekket": None, "forst_sett": {},
              "bekreftet": {_b_nokkel: {"resultat": [_b_siste["hg"], _b_siste["ag"]], "kilder": ["espn"],
                                        "publisert": (_b_avsp + _tda(minutes=115)).isoformat(timespec="seconds")}}}
_e, _logg, _ = _a_main(_a_liste, naa=_b_avsp + _tda(hours=2), tabell=_b_feil_tabell, state=_b_st_main)
_b_aud = _a_fil("audit_tabell.json")
sjekk(f"{_b_siste['home']}-{_b_siste['away']} er fersk og bekreftet, tabellen har ført den som 0-0: kjøringen er grønn, status.json er grønn",
      _e is None and _a_fil("status.json")["ok"] is True and _b_aud["errors"] == 0, f"{_e!r} {_b_aud}"[:500])
sjekk("og kampen venter i audit_tabell.json, så porten åpner i neste kjøring",
      [(v["kamp"], v["grunn"]) for v in _b_aud["venter"]] == [(_b_nokkel, "ført som 0-0 i tabellen")]
      and _a_fil("results_state.json")["bekreftet"] == _b_st_main["bekreftet"], str(_b_aud.get("venter")))
_e, _logg, _ = _a_main(_a_liste, naa=_b_avsp + _tda(hours=2), tabell=_b_feil_tabell, state={**_b_st_main, "bekreftet": {}})
sjekk("samme kjøring uten bekreftelsen: tabellkontrollen gjør kjøringen rød, men først etter sluttodds, odds og modell",
      isinstance(_e, _uda.DataAuditError) and "kritisk(e) avvik mellom tabellen vår og tabellen på ligasiden" in str(_e)
      and _logg[:3] == ["sluttodds", "odds slått sammen", "modell"] and _a_fil("status.json")["ok"] is False
      and _a_fil("audit_tabell.json")["venter"] == [], f"{_e!r} {_logg}"[:400])
_e, _logg, _ = _a_main(_a_liste, naa=_b_avsp + _tda(hours=6, minutes=10), tabell=_b_feil_tabell, state=_b_st_main)
sjekk("og 6 t 10 min etter avspark, fortsatt feil i tabellen: rød kjøring (fristen er ute)",
      isinstance(_e, _uda.DataAuditError) and _a_fil("audit_tabell.json")["errors"] == 2 and _a_fil("audit_tabell.json")["venter"] == [],
      f"{_e!r}"[:300])

print("\n=== En ren revisjon gjør ikke stempelet grønt når dataskriptet var rødt (13.10.2026) ===")
# Siden 12.10. kjøres den daglige revisjonen også når en kontroll gjorde
# dataskriptet rødt. skriv_stempel satte da ok=True og fjernet feilteksten.
import daglig_revisjon as _drs
_s_dir = Path(_tf2.mkdtemp())
_s_ekte_kat, _s_ekte_avvik = _drs.data_katalog, _drs.tabellkontroll.avvik
_drs.data_katalog = lambda liga, sesong=None: _s_dir
_s_naa = _dt(2026, 10, 13, 9, 20, tzinfo=_tz.utc)
_S_ROD = {"last_checked": "2026-10-13T09:19:00+00:00", "ok": False,
          "error": "2 kritisk(e) avvik mellom tabellen vår og tabellen på ligasiden: Tabell, Brann: 2 uavgjort hos oss, 3 hos ligasiden"}


def _s_stempel(for_, feil, annet):
    (_s_dir / "status.json").write_text(json.dumps(for_), encoding="utf-8")
    _drs.skriv_stempel("eliteserien", feil, _s_naa, annet_rodt=annet)
    return json.loads((_s_dir / "status.json").read_text("utf-8"))


_s = _s_stempel(_S_ROD, [], True)
sjekk("dataskriptet var rødt, revisjonen er ren: status.json er fortsatt rød med feilteksten fra dataskriptet",
      _s["ok"] is False and _s["error"] == _S_ROD["error"] and _s["revidert_at"] == "2026-10-13T09:20:00+00:00", str(_s))
_s = _s_stempel(_S_ROD, [], False)
sjekk("motprøve, dataskriptet var grønt og revisjonen er ren: stempelet blir grønt som før (avviket fra en tidligere revisjon er borte)",
      _s["ok"] is True and "error" not in _s, str(_s))
_s = _s_stempel({"last_checked": "2026-10-13T09:19:00+00:00", "ok": True}, [], True)
sjekk("grønn status røres ikke av en ren revisjon", _s["ok"] is True and "error" not in _s, str(_s))
_s = _s_stempel(_S_ROD, ["Rosenborg-Start: dato 2026-11-07 hos oss, 2026-11-18 i kalenderfeeden"], True)
sjekk("revisjonen finner selv et avvik: rødt, uansett",
      _s["ok"] is False and _s["revisjon_avvik"] == 1 and "kalenderfeeden" in _s["error"], str(_s))
_drs.tabellkontroll.avvik = lambda liga, data_dir=None: 0
sjekk("annet_rodt: DATASTEG_UTFALL=failure fra workflowen", _drs.annet_rodt("eliteserien", {"DATASTEG_UTFALL": "failure"}) is True)
sjekk("annet_rodt: dataskriptet grønt og ingen avvik i tabellkontrollen: nei",
      _drs.annet_rodt("eliteserien", {"DATASTEG_UTFALL": "success"}) is False and _drs.annet_rodt("eliteserien", {}) is False)
_drs.tabellkontroll.avvik = lambda liga, data_dir=None: 2
sjekk("annet_rodt: tabellkontrollen står med kritiske avvik (også uten workflowens variabel)", _drs.annet_rodt("eliteserien", {}) is True)
_drs.data_katalog, _drs.tabellkontroll.avvik = _s_ekte_kat, _s_ekte_avvik
_s_kilde = (ROT / "scripts" / "daglig_revisjon.py").read_text("utf-8")
sjekk("daglig_revisjon.main sender annet_rodt til skriv_stempel", "skriv_stempel(liga, feil, naa, annet_rodt=annet_rodt(liga))" in _s_kilde)
for _wf_s, _sid_s in (("update-data.yml", "oppdater"), ("obos-results.yml", "bygg")):
    _rev_s = next(b for b in (ROT / ".github" / "workflows" / _wf_s).read_text("utf-8").split("\n      - ")[1:]
                  if b.startswith("name: Daglig revisjon av terminlisten"))
    sjekk(f"{_wf_s}: revisjonssteget får utfallet av dataskriptet (DATASTEG_UTFALL fra steps.{_sid_s}.outcome)",
          f"DATASTEG_UTFALL: ${{{{ steps.{_sid_s}.outcome }}}}" in _rev_s, _rev_s[-300:])

print("\n=== Ingen enkeltkilde setter eller flytter en dato: kildene i rekkefølge, nye kamper og avgjørelser for hånd (bekreft_datoer, 13.10.2026) ===")
from reconcile_ny import bekreft_datoer as _bd, uten_lagret_dato as _uld
import flytting as _fl
import daglig_revisjon as _dr3
import sesong as _ses3
_f3_forr = [{"home": "Odd", "away": "Bryne", "round": 28, "date": "2026-10-25", "time": "15:00", "hg": None, "ag": None},
            {"home": "Lyn", "away": "Moss", "round": 28, "date": "2026-10-25", "time": "15:00", "hg": None, "ag": None},
            {"home": "Hødd", "away": "Odd", "round": 24, "date": "2026-10-03", "time": "17:00", "hg": 2, "ag": 3}]
_OB = ("Odd", "Bryne")
_f3_flyttet = [dict(r) for r in _f3_forr]
_f3_flyttet[0].update(date="2026-10-26", time="18:00")


def _f3_kilde(svar, kall, navn="Highlightly"):
    def hent():
        kall.append(navn)
        if isinstance(svar, Exception):
            raise svar
        return svar
    return (navn, hent)


def _f3_kjor(rader, hl, nye=(), overstyringer=None, forrige=_f3_forr):
    kall, logg = [], []
    ut, utfall = _bd(rader, forrige, [_f3_kilde(hl, kall)], log=logg.append, nye=nye, overstyringer=overstyringer or {})
    return {(r["home"], r["away"]): (r["date"], r.get("time")) for r in ut}, utfall, kall, logg


# OBOS: én kilde (Highlightly-listen fra den daglige hentingen), ingen reserve.
_r, _u, _kall, _logg = _f3_kjor(_f3_flyttet, {_OB: ("2026-10-26", "18:00")})
sjekk("OBOS: Highlightly-listen viser samme nye dato og tid: Odd-Bryne flyttes",
      _r[_OB] == ("2026-10-26", "18:00") and [(u["kamp"], u["type"], u["utfall"], u["kilde"]) for u in _u] == [("Odd-Bryne", "flytting", "flyttet", "Highlightly")]
      and any("flyttet fra 25.10. 15:00 til 26.10. 18:00, bekreftet av Highlightly" in m for m in _logg), f"{_r[_OB]} {_u} {_logg}")
_r, _u, _kall, _logg = _f3_kjor(_f3_flyttet, {_OB: ("2026-10-25", "15:00")})
sjekk("OBOS: listen viser den gamle datoen: kampen beholder 25.10. 15:00, med ADVARSEL, og flyttingen venter",
      _r[_OB] == ("2026-10-25", "15:00") and _u[0]["utfall"] == "beholdt" and _u[0]["ny"] == ("2026-10-26", "18:00") and _u[0]["har"] == ("2026-10-25", "15:00")
      and any("ADVARSEL" in m and "ligasiden viser 26.10. 18:00" in m and "Highlightly viser 25.10. 15:00" in m and "beholder 25.10. 15:00" in m for m in _logg),
      f"{_r[_OB]} {_u} {_logg}")
_r, _u, _kall, _logg = _f3_kjor(_f3_flyttet, ValueError("den lagrede Highlightly-listen er 49 timer gammel (grensen er 48)"))
sjekk("OBOS: listen er eldre enn 48 timer: ingen reserve, kampen beholder datoen, og det står hvorfor",
      _r[_OB] == ("2026-10-25", "15:00") and _u[0]["utfall"] == "beholdt" and _u[0]["kilde"] is None
      and any("Highlightly kan ikke brukes" in m and "49 timer gammel" in m for m in _logg)
      and any("ADVARSEL" in m and "Highlightly kunne ikke brukes" in m for m in _logg), f"{_u} {_logg}")
_r, _u, _kall, _logg = _f3_kjor([dict(r) for r in _f3_forr], {_OB: ("2026-10-26", "18:00")})
sjekk("ingen flytting: listen leses ikke, ingenting endres", _kall == [] and _u == [] and _r[_OB] == ("2026-10-25", "15:00"))

# Avgjort for hånd (overstyringsfilen).
_o_godta = {_OB: {"valg": "godta", "dato": "2026-10-26", "tid": "18:00"}}
_r, _u, _kall, _logg = _f3_kjor(_f3_flyttet, {_OB: ("2026-10-25", "15:00")}, overstyringer=_o_godta)
sjekk("godta for hånd: kampen flyttes selv om kilden viser den gamle datoen, og kilden spørres ikke",
      _r[_OB] == ("2026-10-26", "18:00") and _kall == [] and (_u[0]["utfall"], _u[0]["kilde"]) == ("flyttet", "overstyring")
      and any("godtatt for hånd" in m for m in _logg), f"{_r[_OB]} {_kall} {_u} {_logg}")
_o_avvis = {_OB: {"valg": "avvis", "dato": "2026-10-26", "tid": "18:00"}}
_r, _u, _kall, _logg = _f3_kjor(_f3_flyttet, {_OB: ("2026-10-26", "18:00")}, overstyringer=_o_avvis)
sjekk("avvis for hånd: kampen beholder datoen selv om kilden er enig med ligasiden, uten ADVARSEL",
      _r[_OB] == ("2026-10-25", "15:00") and _kall == [] and _u[0]["utfall"] == "avvist"
      and any("avvist for hånd" in m for m in _logg) and not any("ADVARSEL" in m for m in _logg), f"{_r[_OB]} {_u} {_logg}")
_f3_annen = [dict(r) for r in _f3_forr]
_f3_annen[0].update(date="2026-10-27", time="18:00")       # ligasiden viser nå noe annet enn linjen gjelder
_r, _u, _kall, _logg = _f3_kjor(_f3_annen, {_OB: ("2026-10-25", "15:00")}, overstyringer=_o_godta)
sjekk("linjen gjelder 26.10., ligasiden viser nå 27.10.: linjen brukes ikke, kilden avgjør, og det står i loggen",
      _r[_OB] == ("2026-10-25", "15:00") and _kall == ["Highlightly"] and _u[0]["utfall"] == "beholdt"
      and any("overstyringen for Odd-Bryne gjelder 26.10. 18:00, men ligasiden viser nå 27.10. 18:00 -- brukes ikke" in m for m in _logg), str(_logg))

# En NY kamp uten lagret dato må bekreftes.
_f3_ny = [dict(r) for r in _f3_forr] + [{"home": "Moss", "away": "Odd", "round": 29, "date": "2026-11-01", "time": "15:00", "hg": None, "ag": None}]
_MO = ("Moss", "Odd")
_r, _u, _kall, _logg = _f3_kjor(_f3_ny, {_MO: ("2026-11-01", "15:00")}, nye={_MO})
sjekk("ny kamp, kilden viser samme dato og tid: bekreftet, og datoen står",
      _r[_MO] == ("2026-11-01", "15:00") and [(u["type"], u["utfall"], u["kilde"]) for u in _u] == [("ny", "bekreftet", "Highlightly")]
      and any("Ny kamp: Moss-Odd 1.11. 15:00, bekreftet av Highlightly" in m for m in _logg), f"{_u} {_logg}")
for _f3_navn, _f3_svar, _f3_hva in (("kilden viser en annen tid", {_MO: ("2026-11-01", "18:00")}, "Highlightly viser 1.11. 18:00"),
                                     ("kilden har ikke kampen", {}, "Highlightly har ikke kampen"),
                                     ("kilden kan ikke brukes", ValueError("mangler"), "Highlightly kunne ikke brukes")):
    _r, _u, _kall, _logg = _f3_kjor(_f3_ny, _f3_svar, nye={_MO})
    sjekk(f"ny kamp, {_f3_navn}: ubekreftet (kalleren skal ikke skrive noe), og det står hva kilden viser",
          [(u["type"], u["utfall"]) for u in _u] == [("ny", "ubekreftet")] and _u[0]["hva"] == _f3_hva
          and any("AVVIK" in m and "vi har ingen lagret dato" in m and "ikke bekreftet" in m for m in _logg), f"{_u} {_logg}")
_r, _u, _kall, _logg = _f3_kjor(_f3_ny, {}, nye={_MO}, overstyringer={_MO: {"valg": "godta", "dato": "2026-11-01", "tid": "15:00"}})
sjekk("ny kamp godtatt for hånd: bekreftet uten kilde", (_u[0]["utfall"], _u[0]["kilde"]) == ("bekreftet", "overstyring") and _kall == [], f"{_u} {_kall}")
_r, _u, _kall, _logg = _f3_kjor(_f3_ny, {}, nye=())
sjekk("motprøve: samme kamp når den ikke regnes som ny (sesongstart), slipper gjennom uten oppslag", _u == [] and _kall == [])

print("\n=== Hvilke kamper mangler en brukbar lagret dato (reconcile_ny.uten_lagret_dato) ===")
# Sandkassens terminliste fra 1.10. (Eliteserien): vinduet er 8.3.2026 til 27.1.2027.
_f3_usp = _a_uspilte[0]
_f3_k = (_f3_usp["home"], _f3_usp["away"])
sjekk("hele terminlisten er lagret: ingen kamp er ny", _uld([dict(r) for r in _a_liste], _a_liste, "2026") == set())
sjekk("kampen mangler i den lagrede listen: den er ny",
      _uld([dict(r) for r in _a_liste], [r for r in _a_liste if (r["home"], r["away"]) != _f3_k], "2026") == {_f3_k})
sjekk("den lagrede datoen ligger utenfor sesongvinduet (7.1.2026): kampen regnes som ny",
      _uld([dict(r) for r in _a_liste], [{**r, "date": "2026-01-07"} if (r["home"], r["away"]) == _f3_k else r for r in _a_liste], "2026") == {_f3_k})
_f3_spilt = next(r for r in _a_liste if r["hg"] is not None)
sjekk("en SPILT kamp er aldri ny her (den er frosset)",
      _uld([dict(r) for r in _a_liste], [r for r in _a_liste if r is not _f3_spilt], "2026") == set())
sjekk("sesongstart (under 20 lagrede kamper i sesongen): ingen regnes som nye, hele listen godtas som før",
      _uld([dict(r) for r in _a_liste], _a_liste[:19], "2026") == set() and _uld([dict(r) for r in _a_liste], [], "2026") == set())
from reconcile_ny import rimelige_datoer as _rd3
_l3 = []
_f3_urunde = [{k: v for k, v in r.items() if k != "round"} for r in _a_liste]
_ut3, _utenfor3, _kode3 = _rd3([dict(r) for r in _a_liste], _f3_urunde, "2026", log=_l3.append)
sjekk("de lagrede kampene mangler rundenummer: vakten står ikke over i stillhet, feilkoden er «ingen_runder» og det logges som AVVIK",
      _kode3 == "ingen_runder" and _utenfor3 is None and any(m.startswith("AVVIK") and "rundenummer" in m for m in _l3), f"{_kode3} {_l3}")

print("\n=== Overstyringsfilen: godta eller avvis en flytting per kamp (flytting.les_overstyringer) ===")
_f3_d = Path(_tf2.mkdtemp())
_f3_par = {("Odd", "Bryne"), ("Lyn", "Moss"), ("Moss", "Odd")}


def _f3_les(innhold, raa=None):
    (_f3_d / "flytting_overstyring.json").write_text(raa if raa is not None else json.dumps(innhold, ensure_ascii=False), encoding="utf-8")
    logg = []
    return _fl.les_overstyringer(_f3_d, _f3_par, log=logg.append), logg


_o, _logg = _f3_les({"_bruk": ["..."], "overstyringer": [
    {"hjemme": "Odd", "borte": "Bryne", "valg": "godta", "dato": "2026-10-26", "tid": "18:00"},
    {"hjemme": "Lyn", "borte": "Moss", "valg": "avvis", "dato": "2026-10-24", "tid": "13:00"}]})
sjekk("to gyldige linjer leses: godta og avvis, med dato og tid",
      _o == {("Odd", "Bryne"): {"valg": "godta", "dato": "2026-10-26", "tid": "18:00"},
             ("Lyn", "Moss"): {"valg": "avvis", "dato": "2026-10-24", "tid": "13:00"}} and _logg == [], f"{_o} {_logg}")
for _f3_navn, _f3_linje, _f3_tekst in (
        ("ukjent lagpar (skrivefeil i lagnavnet)", {"hjemme": "Od", "borte": "Bryne", "valg": "godta", "dato": "2026-10-26", "tid": "18:00"}, "ikke en kamp i terminlisten"),
        ("annet valg enn godta/avvis", {"hjemme": "Odd", "borte": "Bryne", "valg": "ja", "dato": "2026-10-26", "tid": "18:00"}, "valg må være"),
        ("dato i feil form", {"hjemme": "Odd", "borte": "Bryne", "valg": "godta", "dato": "26.10.2026", "tid": "18:00"}, "dato må være"),
        ("tid mangler", {"hjemme": "Odd", "borte": "Bryne", "valg": "godta", "dato": "2026-10-26"}, "dato må være"),
        ("linjen er ikke et objekt", "Odd-Bryne godta", "ikke på formen")):
    _o, _logg = _f3_les({"overstyringer": [_f3_linje, {"hjemme": "Lyn", "borte": "Moss", "valg": "avvis", "dato": "2026-10-24", "tid": "13:00"}]})
    sjekk(f"{_f3_navn}: linjen hoppes over med ADVARSEL, den gyldige linjen brukes",
          set(_o) == {("Lyn", "Moss")} and len(_logg) == 1 and _logg[0].startswith("ADVARSEL: flytting_overstyring.json:") and _f3_tekst in _logg[0], f"{_o} {_logg}")
_o, _logg = _f3_les({"overstyringer": [{"hjemme": "Odd", "borte": "Bryne", "valg": "godta", "dato": "2026-10-26", "tid": "18:00"},
                                       {"hjemme": "Odd", "borte": "Bryne", "valg": "avvis", "dato": "2026-10-26", "tid": "18:00"}]})
sjekk("samme kamp to ganger (godta og avvis): ingen av linjene brukes, med ADVARSEL", _o == {} and any("står flere ganger" in m for m in _logg), f"{_o} {_logg}")
_o, _logg = _f3_les(None, raa='{"overstyringer": [ {"hjemme": "Odd", ]}')
sjekk("filen er ikke gyldig JSON: ingen overstyringer brukes, med ADVARSEL (kjeden stopper ikke)",
      _o == {} and len(_logg) == 1 and "kan ikke leses" in _logg[0], f"{_o} {_logg}")
(_f3_d / "flytting_overstyring.json").unlink()
sjekk("ingen fil: ingen overstyringer", _fl.les_overstyringer(_f3_d, _f3_par) == {})
for _f3_liga in ("eliteserien", "obos"):
    _f3_mal = json.loads((ROT / _f3_liga / "data" / "flytting_overstyring.json").read_text("utf-8"))
    sjekk(f"{_f3_liga}/data/flytting_overstyring.json finnes, med bruksanvisning og et eksempel på formen linjene skal ha",
          isinstance(_f3_mal.get("_bruk"), list) and set(_f3_mal["_eksempel"]) == {"hjemme", "borte", "valg", "dato", "tid"}
          and isinstance(_f3_mal["overstyringer"], list))
sjekk("linjen som skrives i varselet, er på samme form som filen leser",
      json.loads(_fl.linje("Odd", "Bryne", "godta", "2026-10-26", "18:00")) == {"hjemme": "Odd", "borte": "Bryne", "valg": "godta", "dato": "2026-10-26", "tid": "18:00"})

print("\n=== Flyttinger som venter: advarsel, og rødt etter 3 døgn eller under 48 timer før avspark (flytting.py) ===")
_f3_n0 = _dt(2026, 10, 13, 10, 0, tzinfo=_tz.utc)
_f3_utfall = [{"kamp": "Odd-Bryne", "nokkel": ("Odd", "Bryne"), "type": "flytting", "utfall": "beholdt", "kilde": "Highlightly",
               "ny": ("2026-10-26", "18:00"), "har": ("2026-10-25", "15:00"), "hva": "Highlightly viser 25.10. 15:00"}]
_v = _fl.skriv_venter(_f3_d, _f3_utfall, _f3_n0)
sjekk("en tilbakeholdt flytting skrives til flytting_venter.json med vår dato, ligasidens dato og når den først ble sett",
      _v == [{"kamp": "Odd|Bryne", "vaar": ["2026-10-25", "15:00"], "ligasiden": ["2026-10-26", "18:00"],
              "forst_sett": "2026-10-13T10:00:00+00:00", "avvist": False, "hva": "Highlightly viser 25.10. 15:00"}]
      and _fl.les_venter(_f3_d) == _v, str(_v))
_f3_mtid = (_f3_d / "flytting_venter.json").stat().st_mtime_ns
_v = _fl.skriv_venter(_f3_d, _f3_utfall, _f3_n0 + _tda(days=1))
sjekk("neste dag viser ligasiden det samme: klokka fra første gang står, og filen skrives ikke på nytt",
      _v[0]["forst_sett"] == "2026-10-13T10:00:00+00:00" and (_f3_d / "flytting_venter.json").stat().st_mtime_ns == _f3_mtid, str(_v))
_v = _fl.skriv_venter(_f3_d, [{**_f3_utfall[0], "ny": ("2026-10-27", "18:00")}], _f3_n0 + _tda(days=2))
sjekk("ligasiden viser en NY dato for kampen: ny påstand, ny klokke",
      _v[0]["ligasiden"] == ["2026-10-27", "18:00"] and _v[0]["forst_sett"] == "2026-10-15T10:00:00+00:00", str(_v))
_v = _fl.skriv_venter(_f3_d, [{**_f3_utfall[0], "utfall": "avvist"}, {"kamp": "Lyn-Moss", "nokkel": ("Lyn", "Moss"), "type": "flytting",
                              "utfall": "flyttet", "kilde": "Highlightly", "ny": ("2026-10-24", "13:00"), "har": ("2026-10-25", "15:00"), "hva": ""}],
                      _f3_n0)
sjekk("en avvist flytting står med avvist: true; en gjennomført flytting står ikke i filen",
      [(x["kamp"], x["avvist"]) for x in _v] == [("Odd|Bryne", True)], str(_v))
_v = _fl.skriv_venter(_f3_d, [], _f3_n0)
sjekk("ingenting holdes tilbake lenger: listen er tom", _v == [] and _fl.les_venter(_f3_d) == [])

_VENT = [{"kamp": "Odd|Bryne", "vaar": ["2026-10-25", "15:00"], "ligasiden": ["2026-10-26", "18:00"],
          "forst_sett": "2026-10-13T10:00:00+00:00", "avvist": False, "hva": "Highlightly viser 25.10. 15:00"}]
_f, _a = _fl.revider_flyttinger(_VENT, _f3_n0 + _tda(hours=5), data_navn="obos/data")
sjekk("fem timer etter første gang, 12 dager til avspark: ADVARSEL, ikke rødt",
      _f == [] and _a == ["Odd-Bryne: ligasiden viser 26.10. 18:00, vi har 25.10. 15:00 -- flyttingen venter på bekreftelse (siden 13.10. 12:00)"], f"{_f} {_a}")
_f, _a = _fl.revider_flyttinger(_VENT, _f3_n0 + _tda(days=3) - _tda(minutes=1), data_navn="obos/data")
sjekk("2 døgn 23 t 59 min: fortsatt bare advarsel", _f == [] and len(_a) == 1)
_f, _a = _fl.revider_flyttinger(_VENT, _f3_n0 + _tda(days=3), data_navn="obos/data")
sjekk("3 døgn ubekreftet: KRITISK, med filen og linjen som skal limes inn",
      _a == [] and _f == ['Odd-Bryne: ligasiden viser 26.10. 18:00, vi har 25.10. 15:00, ubekreftet i 3 døgn. Godta eller avvis i '
                         'obos/data/flytting_overstyring.json: {"hjemme": "Odd", "borte": "Bryne", "valg": "godta", "dato": "2026-10-26", "tid": "18:00"}'],
      str(_f))
_VENT_NY = [{**_VENT[0], "forst_sett": "2026-10-23T12:00:00+00:00"}]
# 25.10.2026 er dagen klokka stilles tilbake: 15:00 norsk tid er 14:00Z (ikke 13:00Z).
_f, _a = _fl.revider_flyttinger(_VENT_NY, _dt(2026, 10, 23, 13, 59, tzinfo=_tz.utc), data_navn="obos/data")
sjekk("48 t 1 min til den tidligste av de to datoene (25.10. 15:00 norsk vintertid): advarsel", _f == [] and len(_a) == 1, f"{_f} {_a}")
_f, _a = _fl.revider_flyttinger(_VENT_NY, _dt(2026, 10, 23, 14, 1, tzinfo=_tz.utc), data_navn="obos/data")
sjekk("47 t 59 min til avspark: KRITISK, selv om flyttingen bare er en time gammel",
      len(_f) == 1 and "ubekreftet, og under 48 timer til avspark" in _f[0] and _a == [], f"{_f} {_a}")
_VENT_FRAM = [{**_VENT[0], "ligasiden": ["2026-10-24", "13:00"], "forst_sett": "2026-10-22T10:00:00+00:00"}]
_f, _a = _fl.revider_flyttinger(_VENT_FRAM, _dt(2026, 10, 22, 10, 59, tzinfo=_tz.utc), data_navn="obos/data")
sjekk("ligasiden har flyttet kampen FRAM til 24.10. 13:00 (11:00Z): 48 t 1 min før den datoen er det advarsel", _f == [] and len(_a) == 1, f"{_f} {_a}")
_f, _a = _fl.revider_flyttinger(_VENT_FRAM, _dt(2026, 10, 22, 12, 0, tzinfo=_tz.utc), data_navn="obos/data")
sjekk("ligasiden har flyttet kampen FRAM til 24.10. 13:00: 48 timer regnes fra den tidligste datoen (47 timer igjen), kritisk",
      len(_f) == 1, f"{_f} {_a}")
_f, _a = _fl.revider_flyttinger(_VENT_NY, _dt(2026, 10, 25, 14, 30, tzinfo=_tz.utc), data_navn="obos/data")
sjekk("kampen har startet etter avsparket vi har (ligasiden endrer oppføringen underveis): 48-timersregelen gjelder ikke, bare advarsel",
      _f == [] and len(_a) == 1, f"{_f} {_a}")
_f, _a = _fl.revider_flyttinger([{**_VENT[0], "avvist": True}], _f3_n0 + _tda(days=10), data_navn="obos/data")
sjekk("avvist for hånd: verken advarsel eller rødt, heller ikke etter ti døgn", _f == [] and _a == [])

# Den daglige revisjonen mot kalenderfeeden.
_f3_vaare = {("Odd", "Bryne"): {"round": 28, "date": "2026-10-25", "time": "15:00", "hg": None, "ag": None},
             ("Lyn", "Moss"): {"round": 28, "date": "2026-10-25", "time": "15:00", "hg": None, "ag": None}}
_f3_kal = [{"home": "Odd", "away": "Bryne", "round": 28, "date": "2026-10-26", "time": "18:00"},
           {"home": "Lyn", "away": "Moss", "round": 28, "date": "2026-10-25", "time": "15:00"}]
_f, _a = _dr3.revider_kalender(_f3_vaare, _f3_kal, sesong="2026", naa=_f3_n0)
sjekk("motprøve: feeden viser 26.10., vi har 25.10., og ingen flytting venter: kritisk som før",
      _f == ["Odd-Bryne: dato 2026-10-25 hos oss, 2026-10-26 i kalenderfeeden"], str(_f))
_f, _a = _dr3.revider_kalender(_f3_vaare, _f3_kal, sesong="2026", naa=_f3_n0, venter=_VENT)
sjekk("samme avvik når flyttingen er holdt tilbake: ADVARSEL «venter på bekreftelse», ikke kritisk",
      _f == [] and _a == ["Odd-Bryne: dato 2026-10-25 hos oss, 2026-10-26 i kalenderfeeden -- flyttingen venter på bekreftelse"], f"{_f} {_a}")
_f, _a = _dr3.revider_kalender(_f3_vaare, _f3_kal, sesong="2026", naa=_f3_n0, venter=[{**_VENT[0], "avvist": True}])
sjekk("og når den er avvist for hånd: ADVARSEL «avvist for hånd»", _f == [] and _a[0].endswith("flyttingen er avvist for hånd"), f"{_f} {_a}")
_f, _a = _dr3.revider_kalender(_f3_vaare, [{**_f3_kal[0], "date": "2026-10-31"}, _f3_kal[1]], sesong="2026", naa=_f3_n0, venter=_VENT)
sjekk("feeden viser en TREDJE dato (31.10.), ikke den som venter: kritisk", len(_f) == 1 and "2026-10-31" in _f[0], f"{_f} {_a}")
_f3_drk = (ROT / "scripts" / "daglig_revisjon.py").read_text("utf-8")
sjekk("daglig_revisjon.main leser flyttingene som venter, sender dem til kalenderrevisjonen og setter de kritiske først (til e-posten)",
      "_venter = flytting.les_venter(_datadir)" in _f3_drk and "venter=_venter)" in _f3_drk
      and "_ff, _fa = flytting.revider_flyttinger(_venter, naa, data_navn=oppsett(liga)[\"data\"])" in _f3_drk
      and "feil, advarsler = _ff + feil, advarsler + _fa" in _f3_drk)

print("\n=== OBOS: Highlightly-listen fra den daglige hentingen lagres og brukes i byggingen, uten nye kall ===")
_f3_hl = {("Odd", "Bryne"): {"home": "Odd", "away": "Bryne", "date": "2026-10-26", "time": "18:00", "round": 28},
          ("Lyn", "Moss"): {"home": "Lyn", "away": "Moss", "date": "2026-10-25", "time": "15:00", "round": 28}}
_fl.lagre_kontrolliste(_f3_d, _f3_hl, _f3_n0)
sjekk("listen lagres med hentetidspunktet og leses tilbake som {(hjemme, borte): (dato, tid)}",
      _fl.highlightly_lagret(_f3_d, _f3_n0 + _tda(hours=20)) == {("Odd", "Bryne"): ("2026-10-26", "18:00"), ("Lyn", "Moss"): ("2026-10-25", "15:00")}
      and json.loads((_f3_d / "kontroll_highlightly.json").read_text("utf-8"))["hentet"] == "2026-10-13T10:00:00+00:00")
sjekk("48 timer gammel: brukes fortsatt", len(_fl.highlightly_lagret(_f3_d, _f3_n0 + _tda(hours=48))) == 2)
for _f3_navn, _f3_naa in (("48 t 1 min gammel", _f3_n0 + _tda(hours=48, minutes=1)),):
    try:
        _fl.highlightly_lagret(_f3_d, _f3_naa)
        _f3_kastet = ""
    except ValueError as e:
        _f3_kastet = str(e)
    sjekk(f"{_f3_navn}: kan ikke brukes (flyttingen venter)", "48 timer gammel (grensen er 48)" in _f3_kastet, _f3_kastet)
(_f3_d / "kontroll_highlightly.json").unlink()
try:
    _fl.highlightly_lagret(_f3_d, _f3_n0)
    _f3_kastet = ""
except ValueError as e:
    _f3_kastet = str(e)
sjekk("ingen lagret liste: kan ikke brukes", "mangler eller kan ikke leses" in _f3_kastet, _f3_kastet)
# Revisjonen lagrer listen når kildene hentes på nytt, ikke når dagens funn gjenbrukes.
_f3_lagret = []
_f3_hent = lambda liga, vaare, naa: ({"Highlightly": _f3_hl}, [])
_res1 = _dr3.kontroller_i_dag("obos", _f3_vaare, _f3_n0, None, hent=_f3_hent, lagre=_f3_lagret.append)
sjekk("første revisjon i døgnet: listene hentes, og lagre() får Highlightly-listen", len(_f3_lagret) == 1 and _f3_lagret[0]["Highlightly"] is _f3_hl)
_res2 = _dr3.kontroller_i_dag("obos", _f3_vaare, _f3_n0 + _tda(hours=2), {"kontroller": _res1[3]}, hent=_f3_hent, lagre=_f3_lagret.append)
sjekk("senere samme dag: funnene gjenbrukes, ingenting hentes og ingenting lagres på nytt", _res2[4] is True and len(_f3_lagret) == 1)
sjekk("daglig_revisjon.main lagrer listen bare for OBOS, i obos/data/kontroll_highlightly.json",
      'if liga == "obos" and kontroller.get("Highlightly"):' in _f3_drk and "flytting.lagre_kontrolliste(_datadir, kontroller[\"Highlightly\"], naa)" in _f3_drk
      and "lagre=_lagre_liste)" in _f3_drk)

# Byggingen (obos_build_data.rows_for) i en sandkasse med terminlisten fra 1.10.
import obos_build_data as _obd3
import obos_results as _obr3
import highlightly_source as _hls3
_f3_ob = Path(_tf2.mkdtemp())
for _f in ("matches.json", "fixtures.json"):
    _sha.copy(ROT / "tests" / "data" / "2026-10-01" / "obos" / "data" / _f, _f3_ob / _f)
_f3_obl = _lda.forrige_terminliste(_f3_ob, "2026")
_f3_offer = [r for r in _f3_obl if r["hg"] is None][-1]
_f3_ok = (_f3_offer["home"], _f3_offer["away"])
_f3_nydato = ((_dt.fromisoformat(_f3_offer["date"]) + _tda(days=1)).strftime("%Y-%m-%d"), "18:00")
_f3_ntf = [{**m, "ferdig": m["hg"] is not None, **({"date": _f3_nydato[0], "time": _f3_nydato[1]} if (m["home"], m["away"]) == _f3_ok else {})}
           for m in _f3_obl]
_f3_hl_kall, _f3_ntf_kall, _f3_res_kall = [], [], []
_f3_ekte = (_obd3.DATA, _obr3.DATA, ntf_source.fetch_all, _hls3._http, _ses3.aktiv_sesong)
# Resultatkjeden i samme sandkasse, og kildene dens byttet ut: stopper den
# ikke der den skal, skal testen feile -- ikke hente fra nettet eller skrive
# i de ekte filene.
_f3_ekte_res = {n: getattr(_obr3, n) for n in ("MATCHES", "STATE", "ligasiden_og_reserve", "wikipedia_results",
                                               "highlightly_resultater", "oddspapi_fixtures")}


def _f3_ingen_kilde(navn):
    def kalt(*a, **k):
        _f3_res_kall.append(navn)
        raise AssertionError(f"resultatkjeden skulle ha stoppet før {navn} ble hentet")
    return kalt
_f3_naa_ekte = _dt.now(_tz.utc)


def _f3_bygg(liste_dato=None, alder_timer=1, overstyring=None):
    """rows_for i sandkassen. liste_dato: det Highlightly-listen viser for kampen (None: ingen liste)."""
    for _f in ("flytting_venter.json", "flytting_overstyring.json", "kontroll_highlightly.json", "status.json"):
        (_f3_ob / _f).unlink(missing_ok=True)
    if liste_dato is not None:
        _fl.lagre_kontrolliste(_f3_ob, {(r["home"], r["away"]): ({**r, "date": liste_dato[0], "time": liste_dato[1]} if (r["home"], r["away"]) == _f3_ok else r)
                                        for r in _f3_obl}, _f3_naa_ekte - _tda(hours=alder_timer))
    if overstyring:
        (_f3_ob / "flytting_overstyring.json").write_text(json.dumps({"overstyringer": [overstyring]}, ensure_ascii=False), encoding="utf-8")
    logg = []
    rader = _obd3.rows_for(log=logg.append)
    r = next(x for x in rader if (x["home"], x["away"]) == _f3_ok)
    return (r["date"], r["time"]), logg


try:
    _obd3.DATA, _obr3.DATA = _f3_ob, _f3_ob
    _obr3.MATCHES, _obr3.STATE = _f3_ob / "matches.json", _f3_ob / "results_state.json"
    for _n3 in ("ligasiden_og_reserve", "wikipedia_results", "highlightly_resultater", "oddspapi_fixtures"):
        setattr(_obr3, _n3, _f3_ingen_kilde(_n3))
    ntf_source.fetch_all = lambda *a, **k: (_f3_ntf_kall.append(1), [dict(r) for r in _f3_ntf])[1]
    _hls3._http = lambda sti, param: (_f3_hl_kall.append(sti), (_ for _ in ()).throw(RuntimeError("byggingen skal ikke kalle Highlightly")))[1]
    _f3_gml = (_f3_offer["date"], _f3_offer["time"])
    _dato, _logg = _f3_bygg(liste_dato=_f3_nydato)
    sjekk(f"byggingen: ligasiden flytter {_f3_ok[0]}-{_f3_ok[1]}, den lagrede Highlightly-listen (en time gammel) viser det samme: kampen flyttes",
          _dato == _f3_nydato and any("bekreftet av Highlightly" in l for l in _logg) and _obd3.FLYTTING_UTFALL[0]["utfall"] == "flyttet", f"{_dato} {_logg[-3:]}")
    _dato, _logg = _f3_bygg(liste_dato=_f3_gml)
    sjekk("byggingen: listen viser den gamle datoen: kampen beholder den, med ADVARSEL",
          _dato == _f3_gml and any(l.startswith("ADVARSEL") and "Highlightly viser" in l for l in _logg) and _obd3.FLYTTING_UTFALL[0]["utfall"] == "beholdt",
          f"{_dato} {_logg[-3:]}")
    _dato, _logg = _f3_bygg(liste_dato=_f3_nydato, alder_timer=49)
    sjekk("byggingen: listen er 49 timer gammel: flyttingen venter (kampen beholder datoen) selv om listen er enig",
          _dato == _f3_gml and any("49 timer gammel" in l for l in _logg), f"{_dato} {_logg[-3:]}")
    _dato, _logg = _f3_bygg(liste_dato=None)
    sjekk("byggingen: ingen lagret liste: flyttingen venter", _dato == _f3_gml and any("mangler eller kan ikke leses" in l for l in _logg), f"{_dato} {_logg[-3:]}")
    _dato, _logg = _f3_bygg(liste_dato=_f3_gml, overstyring={"hjemme": _f3_ok[0], "borte": _f3_ok[1], "valg": "godta", "dato": _f3_nydato[0], "tid": _f3_nydato[1]})
    sjekk("byggingen: godtatt for hånd i obos/data/flytting_overstyring.json: kampen flyttes", _dato == _f3_nydato and any("godtatt for hånd" in l for l in _logg),
          f"{_dato} {_logg[-3:]}")
    sjekk("byggingen gjorde ingen kall til Highlightly i noen av tilfellene", _f3_hl_kall == [], str(_f3_hl_kall))
    # Uten sesongregister skrives ingenting (B).
    _f3_bytes = {f: (_f3_ob / f).read_bytes() for f in ("matches.json", "fixtures.json")}
    _ses3.aktiv_sesong = lambda rot, liga, log=lambda s: None: None
    _f3_ntf_kall.clear()
    try:
        _obd3.rows_for(log=lambda _s: None)
        _f3_stoppet = None
    except SystemExit as e:
        _f3_stoppet = str(e)
    sjekk("OBOS-byggingen uten sesongregister stopper før ligasiden hentes", _f3_ntf_kall == [], str(_f3_ntf_kall))
    _f3_st = json.loads((_f3_ob / "status.json").read_text("utf-8"))
    sjekk("OBOS-byggingen uten sesongregister: stopper før noe skrives, og status.json får ok: false med «Sesongregisteret ...»",
          _f3_stoppet is not None and "Sesongregisteret (data/sesonger.json)" in _f3_stoppet and "Ingenting er skrevet" not in ""
          and _f3_st["ok"] is False and _f3_st["error"].startswith("Sesongregisteret (data/sesonger.json)")
          and all((_f3_ob / f).read_bytes() == b for f, b in _f3_bytes.items()), f"{_f3_stoppet} {_f3_st}")
    (_f3_ob / "status.json").unlink()
    _f3_argv = sys.argv
    sys.argv = ["obos_results.py"]
    try:
        _f3_kode = _obr3.main()
    except AssertionError as e:
        _f3_kode = f"stoppet ikke: {e}"
    finally:
        sys.argv = _f3_argv
    _f3_st = json.loads((_f3_ob / "status.json").read_text("utf-8")) if (_f3_ob / "status.json").exists() else {"ok": None, "error": ""}
    sjekk("OBOS-resultatkjeden uten sesongregister: stopper (kode 4) før kildene hentes, matches.json er urørt, og status.json er rød",
          _f3_kode == 4 and _f3_st["ok"] is False and "Sesongregisteret" in _f3_st["error"] and _f3_res_kall == []
          and all((_f3_ob / f).read_bytes() == b for f, b in _f3_bytes.items()) and not (_f3_ob / "results_state.json").exists(), f"{_f3_kode} {_f3_st} {_f3_res_kall}")
finally:
    (_obd3.DATA, _obr3.DATA, ntf_source.fetch_all, _hls3._http, _ses3.aktiv_sesong) = _f3_ekte
    for _n3, _v3 in _f3_ekte_res.items():
        setattr(_obr3, _n3, _v3)
_f3_obk = (ROT / "scripts" / "obos_build_data.py").read_text("utf-8")
sjekk("obos_build_data.py: bekreftelsen ligger etter datovakten og før første skriving, og bruker bare den lagrede listen",
      _f3_obk.index("rimelige_datoer(offisiell, forrige or fra_csv, _aktiv") < _f3_obk.index("offisiell, FLYTTING_UTFALL = bekreft_datoer(")
      < _f3_obk.index('leaguedata.write_json(DATA / "matches.json"')
      and '[("Highlightly", lambda: flytting.highlightly_lagret(DATA, _naa))]' in _f3_obk and "hent_sesong" not in _f3_obk)
for _wf3, _filer3 in (("update-data.yml", ("eliteserien/data/flytting_venter.json",)),
                      ("obos-results.yml", ("obos/data/flytting_venter.json", "obos/data/kontroll_highlightly.json"))):
    _wt3 = (ROT / ".github" / "workflows" / _wf3).read_text("utf-8")
    sjekk(f"{_wf3}: lagrer {' og '.join(f.split('/')[-1] for f in _filer3)}, og ikke overstyringsfilen (den skrives for hånd)",
          all(f in _wt3 for f in _filer3) and "flytting_overstyring" not in _wt3)

print("\n=== Hele update_data.main: uten sesongregister, nye kamper og flyttinger (sandkassen) ===")
def _f3_bytes_e():
    return {f: (_a_sb / "eliteserien" / "data" / f).read_bytes() for f in ("matches.json", "fixtures.json")}


_f3_reg = _a_sb / "data" / "sesonger.json"
_f3_for = {f: (ROT / "tests" / "data" / "2026-10-01" / "eliteserien" / "data" / f).read_bytes() for f in ("matches.json", "fixtures.json")}
for _f3_navn, _f3_gjor in (("mangler", lambda d: _f3_reg.unlink()),
                           ("kan ikke leses (ikke gyldig JSON)", lambda d: _f3_reg.write_text("{ikke json", encoding="utf-8")),
                           ("har ingen aktiv sesong for ligaen", lambda d: _f3_reg.write_text(json.dumps({"version": 2, "ligaer": {"obos": {"aktiv": "2026"}}}), encoding="utf-8"))):
    _e, _logg, _ = _a_main([{**r, "date": "2026-01-07"} if r["hg"] is None else r for r in _a_liste], forbered=_f3_gjor)
    sjekk(f"sesongregisteret {_f3_navn}: ingenting skrives (matches.json og fixtures.json er bit for bit som før), modellen kjøres ikke, og kjøringen er rød",
          isinstance(_e, _uda.DataAuditError) and str(_e).startswith("Sesongregisteret (data/sesonger.json)") and _f3_bytes_e() == _f3_for
          and _logg == [] and not (_a_sb / "eliteserien" / "data" / "results_state.json").exists(), f"{_e!r} {_logg}")
    sjekk("  og kjøringen stoppet før ligasiden ble hentet", _a_hentet == [], str(_a_hentet))
    sjekk(f"  og status.json er rød med teksten, så e-posten sier «sesongregister»",
          _a_fil("status.json")["ok"] is False and _lta.hva_feilet("failure", {"oppdater": {"outcome": "failure"}}, _a_fil("status.json"))[0] == "sesongregister",
          str(_a_fil("status.json")))

# En kamp mangler i den lagrede terminlisten (filen vår er skadet): den er NY og må bekreftes.
_f3_ny_k = (_a_offer["home"], _a_offer["away"])


def _f3_fjern(d):
    fx = json.loads((d / "fixtures.json").read_text("utf-8"))
    for r in fx:
        r["matches"] = [m for m in r["matches"] if (m["home"], m["away"]) != _f3_ny_k]
    (d / "fixtures.json").write_text(json.dumps(fx, ensure_ascii=False), encoding="utf-8")


def _f3_skadet(d):
    _f3_fjern(d)
    _f3_skadet.for_ = {f: (d / f).read_bytes() for f in ("matches.json", "fixtures.json")}


_f3_espn_lik = [{"home": r["home"], "away": r["away"], "date": r["date"], "time": r["time"]} for r in _a_liste]
_e, _logg, _ = _a_main(_a_liste, forbered=_f3_skadet, espn=_f3_espn_lik)
_f3_fx = [m for r in _a_fil("fixtures.json") for m in r["matches"] if (m["home"], m["away"]) == _f3_ny_k]
sjekk(f"{_f3_ny_k[0]}-{_f3_ny_k[1]} mangler i den lagrede listen, ESPN viser samme dato og tid som ligasiden: kampen skrives, kjøringen er grønn",
      _e is None and "ESPN" in _logg and len(_f3_fx) == 1 and (_f3_fx[0]["date"], _f3_fx[0]["time"]) == (_a_offer["date"], _a_offer["time"]), f"{_e!r} {_logg} {_f3_fx}")
_f3_espn_ulik = [{**r, "time": "13:00"} if (r["home"], r["away"]) == _f3_ny_k else r for r in _f3_espn_lik]
_e, _logg, _ = _a_main(_a_liste, forbered=_f3_skadet, espn=_f3_espn_ulik)
sjekk("ESPN viser en annen tid: ikke bekreftet, INGENTING skrives, modellen kjøres ikke, og feilen sier hva kildene viser og hvilken linje som godtar den",
      isinstance(_e, _uda.DataAuditError) and str(_e).startswith("1 ny(e) kamp(er) uten lagret dato er ikke bekreftet av en uavhengig kilde. Ingenting er skrevet:")
      and f"{_f3_ny_k[0]}-{_f3_ny_k[1]}: ligasiden viser {_a_offer['date']} {_a_offer['time']}; ESPN viser" in str(_e)
      and _fl.linje(_f3_ny_k[0], _f3_ny_k[1], "godta", _a_offer["date"], _a_offer["time"]) in str(_e)
      and _f3_bytes_e() == _f3_skadet.for_ and "modell" not in _logg, f"{str(_e)[:400]} {_logg}")
sjekk("  og e-posten sier «ny kamp ikke bekreftet»",
      _lta.hva_feilet("failure", {"oppdater": {"outcome": "failure"}}, _a_fil("status.json"))[0] == "ny kamp ikke bekreftet", str(_a_fil("status.json")))


def _f3_skadet_godta(d):
    _f3_fjern(d)
    (d / "flytting_overstyring.json").write_text(json.dumps({"overstyringer": [json.loads(
        _fl.linje(_f3_ny_k[0], _f3_ny_k[1], "godta", _a_offer["date"], _a_offer["time"]))]}, ensure_ascii=False), encoding="utf-8")


_e, _logg, _ = _a_main(_a_liste, forbered=_f3_skadet_godta, espn=_f3_espn_ulik)
_f3_fx = [m for r in _a_fil("fixtures.json") for m in r["matches"] if (m["home"], m["away"]) == _f3_ny_k]
sjekk("samme tilfelle med linjen fra feilen limt inn i overstyringsfilen: kampen skrives, kjøringen er grønn, og datafilene ble ikke redigert for hånd",
      _e is None and len(_f3_fx) == 1 and (_f3_fx[0]["date"], _f3_fx[0]["time"]) == (_a_offer["date"], _a_offer["time"]), f"{_e!r} {_f3_fx}")


def _f3_lagret_gal(d):
    fx = json.loads((d / "fixtures.json").read_text("utf-8"))
    for r in fx:
        for m in r["matches"]:
            if (m["home"], m["away"]) == _f3_ny_k:
                m["date"] = "2026-01-07"
    (d / "fixtures.json").write_text(json.dumps(fx, ensure_ascii=False), encoding="utf-8")
    _f3_lagret_gal.for_ = {f: (d / f).read_bytes() for f in ("matches.json", "fixtures.json")}


_e, _logg, _ = _a_main(_a_liste, forbered=_f3_lagret_gal, espn=_f3_espn_ulik)
sjekk("den LAGREDE datoen er gal (7.1.), ligasiden viser en dato i sesongen, ESPN er ikke enig: kampen er ny og ubekreftet, ingenting skrives (før ble 7.1. stående)",
      isinstance(_e, _uda.DataAuditError) and "uten lagret dato" in str(_e) and _f3_bytes_e() == _f3_lagret_gal.for_, f"{str(_e)[:300]}")
_e, _logg, _ = _a_main(_a_liste, forbered=_f3_lagret_gal, espn=_f3_espn_lik)
sjekk("samme, men ESPN er enig med ligasiden: datoen rettes, og 7.1. står ingen steder",
      _e is None and "2026-01-07" not in json.dumps(_a_fil("fixtures.json")), f"{_e!r}")

# Flytting innenfor sesongvinduet (det som slapp gjennom 10.10.: Rosenborg-Start 7.11. vist som 18.11.).
_f3_fl_k = (_a_uspilte[5]["home"], _a_uspilte[5]["away"])
_f3_fl_gml = (_a_uspilte[5]["date"], _a_uspilte[5]["time"])
_f3_fl_ny = ((_dt.fromisoformat(_f3_fl_gml[0]) + _tda(days=11)).strftime("%Y-%m-%d"), _f3_fl_gml[1])
_f3_kilde_fl = [{**r, "date": _f3_fl_ny[0]} if (r["home"], r["away"]) == _f3_fl_k else r for r in _a_liste]


def _f3_dato_paa_disk():
    return next((m["date"], m["time"]) for r in _a_fil("fixtures.json") for m in r["matches"] if (m["home"], m["away"]) == _f3_fl_k)


_e, _logg, _ = _a_main(_f3_kilde_fl, espn=_f3_espn_lik)
_f3_vent = _a_fil("flytting_venter.json")["venter"]
sjekk(f"ligasiden flytter {_f3_fl_k[0]}-{_f3_fl_k[1]} elleve dager, ESPN viser den gamle datoen: fixtures.json beholder den, kjøringen er grønn",
      _e is None and _f3_dato_paa_disk() == _f3_fl_gml and _a_fil("status.json")["ok"] is True, f"{_e!r} {_f3_dato_paa_disk()}")
sjekk("og flyttingen står i flytting_venter.json med begge datoene og tidspunktet",
      [(v["kamp"], v["vaar"], v["ligasiden"], v["avvist"]) for v in _f3_vent] == [(f"{_f3_fl_k[0]}|{_f3_fl_k[1]}", list(_f3_fl_gml), list(_f3_fl_ny), False)]
      and _f3_vent[0]["forst_sett"] == _a_naa_m.isoformat(timespec="seconds"), str(_f3_vent))
_e, _logg, _ = _a_main(_f3_kilde_fl, espn=[{**r, "date": _f3_fl_ny[0]} if (r["home"], r["away"]) == _f3_fl_k else r for r in _f3_espn_lik])
sjekk("ESPN viser den nye datoen: kampen flyttes, og ingenting venter",
      _e is None and _f3_dato_paa_disk() == _f3_fl_ny and _a_fil("flytting_venter.json")["venter"] == [], f"{_e!r} {_f3_dato_paa_disk()}")


def _f3_overstyr(valg):
    def gjor(d):
        (d / "flytting_overstyring.json").write_text(json.dumps({"overstyringer": [
            {"hjemme": _f3_fl_k[0], "borte": _f3_fl_k[1], "valg": valg, "dato": _f3_fl_ny[0], "tid": _f3_fl_ny[1]}]}, ensure_ascii=False), encoding="utf-8")
    return gjor


_e, _logg, _ = _a_main(_f3_kilde_fl, forbered=_f3_overstyr("godta"))
sjekk("godtatt i overstyringsfilen: kampen flyttes uten at ESPN eller kalenderfeeden spørres",
      _e is None and _f3_dato_paa_disk() == _f3_fl_ny and "NETTKALL" not in _logg and "ESPN" not in _logg
      and _a_fil("flytting_venter.json")["venter"] == [], f"{_e!r} {_f3_dato_paa_disk()} {_logg}")
_e, _logg, _ = _a_main(_f3_kilde_fl, forbered=_f3_overstyr("avvis"),
                       espn=[{**r, "date": _f3_fl_ny[0]} if (r["home"], r["away"]) == _f3_fl_k else r for r in _f3_espn_lik])
_f3_vent = _a_fil("flytting_venter.json")["venter"]
sjekk("avvist i overstyringsfilen: kampen beholder datoen, og flyttingen står som avvist (ingen varsling, se revider_flyttinger over)",
      _e is None and _f3_dato_paa_disk() == _f3_fl_gml and [(v["kamp"], v["avvist"]) for v in _f3_vent] == [(f"{_f3_fl_k[0]}|{_f3_fl_k[1]}", True)],
      f"{_e!r} {_f3_dato_paa_disk()} {_f3_vent}")

print("\n=== Rangeringen etter kampreglementet § 5-3: innbyrdes oppgjør (scripts/rangering.py, 16.10.2026) ===")
import rangering as _rg
import random as _rnd12
import subprocess as _sp12
_k12 = lambda h, a, hg, ag: {"home": h, "away": a, "hg": hg, "ag": ag}


def _r12(lag, kamper):
    """lag: [(navn, poeng, målforskjell, scorede)] -> navnene i rekkefølge."""
    return _rg.rekkefolge([x[0] for x in lag], kamper, {x[0]: x[1] for x in lag}, {x[0]: x[2] for x in lag}, {x[0]: x[3] for x in lag})


sjekk("to lag helt likt: B vant innbyrdes (2-0, 1-1) og står over A, selv om A kommer først alfabetisk",
      _r12([("A", 50, 10, 40), ("B", 50, 10, 40), ("C", 60, 5, 30)], [_k12("A", "B", 0, 2), _k12("B", "A", 1, 1), _k12("A", "C", 3, 0)]) == ["C", "B", "A"])
sjekk("tre lag helt likt: minitabellen avgjør (alle 3 poeng innbyrdes, målforskjell innbyrdes C +2, B 0, A -2)",
      _r12([("A", 40, 0, 30), ("B", 40, 0, 30), ("C", 40, 0, 30)], [_k12("A", "B", 1, 0), _k12("B", "C", 1, 0), _k12("C", "A", 3, 0)]) == ["C", "B", "A"])
sjekk("innbyrdes teller ikke før målforskjell (B slo A, men A har bedre målforskjell)",
      _r12([("B", 40, 2, 30), ("A", 40, 5, 30)], [_k12("A", "B", 0, 1)]) == ["A", "B"])
sjekk("innbyrdes teller ikke før scorede mål", _r12([("B", 40, 2, 30), ("A", 40, 2, 31)], [_k12("A", "B", 0, 1)]) == ["A", "B"])
sjekk("helt likt også innbyrdes: navn (i virkeligheten kvalifiseringsspill)", _r12([("B", 40, 0, 30), ("A", 40, 0, 30)], [_k12("A", "B", 1, 1)]) == ["A", "B"])
sjekk("innbyrdes poeng før innbyrdes målforskjell (A 6 poeng og +2, B 3 poeng og +5: A først)",
      _r12([("A", 40, 0, 30), ("B", 40, 0, 30), ("C", 40, 0, 30)],
           [_k12("A", "B", 1, 0), _k12("A", "C", 1, 0), _k12("B", "C", 6, 0)]) == ["A", "B", "C"])
sjekk("innbyrdes målforskjell før innbyrdes scorede mål (3 poeng hver: C +1 og 6 mål, B 0 og 1 mål, A -1 og 5 mål)",
      _r12([("A", 40, 0, 30), ("B", 40, 0, 30), ("C", 40, 0, 30)],
           [_k12("A", "B", 1, 0), _k12("B", "C", 1, 0), _k12("C", "A", 6, 4)]) == ["C", "B", "A"])
sjekk("kamper uten resultat og kamper mot andre lag teller ikke i minitabellen",
      _r12([("A", 40, 0, 30), ("B", 40, 0, 30)], [_k12("A", "B", None, None), _k12("B", "C", 5, 0)]) == ["A", "B"])
# Poengtrekk: likt på poeng ETTER trekket; minitabellen teller bare kampene.
sjekk("poengtrekk ligger i poengene, ikke i minitabellen (B trukket ett poeng står likt med A, men vant innbyrdes)",
      _r12([("A", 40, 0, 30), ("B", 40, 0, 30)], [_k12("B", "A", 2, 1)]) == ["B", "A"])

# Det ekte tilfellet: Viking og Bodø/Glimt etter 11.10.2026, og tabellen på ligasiden 11.10. kl. 23:10.
_m12 = json.loads((TESTDATA / "tabell_etter_kamp" / "eliteserien_matches_2026-10-11.json").read_text("utf-8"))
_lag12 = sorted({m["home"] for m in _m12} | {m["away"] for m in _m12})
import tabellkontroll as _tk12
_v12 = _tk12.vaar_tabell(_m12, _lag12, {})
sjekk("tabellen 11.10.: Viking og Bodø/Glimt står helt likt (53, +36, 56), og Viking står først (innbyrdes 5-0)",
      [(_v12[n]["poeng"], _v12[n]["mf"] - _v12[n]["mm"], _v12[n]["mf"]) for n in ("Viking", "Bodø/Glimt")] == [(53, 36, 56)] * 2
      and _v12["Viking"]["plass"] == 1 and _v12["Bodø/Glimt"]["plass"] == 2, str({n: _v12[n] for n in ("Viking", "Bodø/Glimt")}))
_d12 = Path(_tf2.mkdtemp())
_ut12 = _tk12.kontroller("eliteserien", 2026, _m12, json.loads((TESTDATA / "tabell_etter_kamp" / "eliteserien_tabell_2026-10-11T2110Z.json").read_text("utf-8")),
                         naa=_dt(2026, 10, 11, 21, 10, tzinfo=_tz.utc), data_dir=_d12, kilde_url="https://www.eliteserien.no/resultater", kjoring="test", log=lambda _s: None)
sjekk("tabellkontrollen mot tabellen på ligasiden 11.10.: alle like, og advarselen «lik poengsum, ulik rangering» er borte",
      _ut12["alle_like"] is True and _ut12["errors"] == 0 and _ut12["advarsler"] == [], str(_ut12["advarsler"]))
import make_og as _og12
_og_rader = _og12.standings(_m12)
sjekk("delingsbildet (make_og.standings): Viking først, Bodø/Glimt andre", [r["name"] for r in _og_rader[:2]] == ["Viking", "Bodø/Glimt"], str([r["name"] for r in _og_rader[:3]]))
import backtest_zones as _bz12
_TI12 = {t: i for i, t in enumerate(_lag12)}
_pos12 = _bz12.final_positions(*_bz12.standings(_m12, _TI12, len(_lag12)), _lag12, _m12)
sjekk("backtest_zones.final_positions: Viking 1, Bodø/Glimt 2", (_pos12[_TI12["Viking"]], _pos12[_TI12["Bodø/Glimt"]]) == (1, 2), str((_pos12[_TI12["Viking"]], _pos12[_TI12["Bodø/Glimt"]])))

# Samme regel på sidene: rangerTabell() er lik i eliteserien, obos og elo-test, og gir samme rekkefølge som Python.
import re as _re12
_fn12 = {}
for _side12 in ("eliteserien/index.html", "obos/index.html", "elo-test/index.html"):
    _src12 = (ROT / _side12).read_text("utf-8")
    _m = _re12.search(r"\nfunction rangerTabell\(rows, kamper, navn\)\{.*?\n\}\n", _src12, _re12.S)
    _fn12[_side12] = _m.group(0) if _m else None
    sjekk(f"{_side12}: de tre sorteringene bruker rangerTabell (computeAt, compute, basePos), og ingen sorterer selv på poeng",
          _src12.count("rangerTabell(rows, games);") == 1 and _src12.count("rangerTabell(rows, MATCHES.concat(") == 1
          and _src12.count("rangerTabell(r, MATCHES, x=>x.n);") == 1 and _src12.count("y.pts-x.pts") == 1)
sjekk("rangerTabell er identisk på de tre sidene", len(set(_fn12.values())) == 1 and None not in _fn12.values())
_rnd12.seed(20261016)
_tilf12 = []
for _ in range(300):
    n = _rnd12.randint(2, 6)
    navn = [f"Lag {chr(65 + i)}" for i in range(n)]
    pts = {x: _rnd12.choice([40, 40, 41]) for x in navn}
    gd = {x: _rnd12.choice([0, 0, 1]) for x in navn}
    gf = {x: _rnd12.choice([30, 30, 31]) for x in navn}
    kamper = [_k12(h, a, _rnd12.randint(0, 3), _rnd12.randint(0, 3)) for h in navn for a in navn if h != a and _rnd12.random() < 0.6]
    _tilf12.append({"rader": [{"name": x, "pts": pts[x], "gd": gd[x], "gf": gf[x]} for x in navn], "kamper": kamper,
                    "py": _rg.rekkefolge(navn, kamper, pts, gd, gf)})
_js12 = _fn12["eliteserien/index.html"] + "\nconst T = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" \
        "process.stdout.write(JSON.stringify(T.map(t => rangerTabell(t.rader.map(r => ({...r})), t.kamper).map(r => r.name))));\n"
_ut_js12 = json.loads(_sp12.run(["node", "-e", _js12], input=json.dumps(_tilf12), capture_output=True, text=True, check=True).stdout)
_ulik12 = [(t["py"], j) for t, j in zip(_tilf12, _ut_js12) if t["py"] != j]
sjekk(f"Python og siden gir samme rekkefølge i 300 tilfeldige tilfeller med mange like lag ({sum(1 for t in _tilf12 if len(set((r['pts'], r['gd'], r['gf']) for r in t['rader'])) < len(t['rader']))} med likhet)",
      not _ulik12, str(_ulik12[:3]))

print("\n=== puppeteer-core i en fast mappe, sjekket med require (tests/puppeteer_sti.sh, 16.10.2026) ===")
# macOS ryddet den midlertidige mappa 10.10. og 14.10.2026: mappa sto igjen,
# men pakken kunne ikke lastes. En falsk npm installerer en tom «pakke» og
# skriver ned kallet, så testen verken laster ned noe eller rører den ekte mappa.
import subprocess as _sp6, os as _os6, stat as _st6
_d6 = Path(_tf2.mkdtemp())
_npm6 = _d6 / "falsk_npm"
_npm6.write_text('''#!/bin/sh
echo "$@" >> "$PP_LOGG"
[ -n "$PP_NPM_FEIL" ] && exit 0
p=""; neste=0
for a in "$@"; do [ $neste = 1 ] && p="$a"; neste=0; [ "$a" = "--prefix" ] && neste=1; done
mkdir -p "$p/node_modules/puppeteer-core"
echo '{"name":"puppeteer-core","main":"index.js"}' > "$p/node_modules/puppeteer-core/package.json"
echo 'module.exports = {}' > "$p/node_modules/puppeteer-core/index.js"
''', encoding="utf-8")
_npm6.chmod(_npm6.stat().st_mode | _st6.S_IEXEC)


def _pp6(pp_dir, feil=False):
    """Leser inn tests/puppeteer_sti.sh i et rent skall. Returnerer (kode, NODE_PATH, kallene til npm, utskrift)."""
    logg = _d6 / "npm.logg"
    logg.unlink(missing_ok=True)
    miljo = {k: v for k, v in _os6.environ.items() if k != "NODE_PATH"}
    miljo.update(TABELLKALKULATOR_PP=str(pp_dir), PP_NPM=str(_npm6), PP_LOGG=str(logg), HOME=str(_d6 / "hjem"))
    if feil:
        miljo["PP_NPM_FEIL"] = "1"
    r = _sp6.run(["bash", "-c", f'. "{ROT}/tests/puppeteer_sti.sh" || exit 1; echo "NODE_PATH=$NODE_PATH"'],
                 cwd=_d6, env=miljo, capture_output=True, text=True)
    np_ = next((l[10:] for l in r.stdout.splitlines() if l.startswith("NODE_PATH=")), None)
    kall = logg.read_text().splitlines() if logg.exists() else []
    return r.returncode, np_, kall, r.stdout + r.stderr


_pp_a = _d6 / "tom"
_k, _np, _kall, _ut = _pp6(_pp_a)
sjekk("tom mappe: puppeteer-core 25.11.0 installeres én gang i den faste mappa, og NODE_PATH peker dit",
      _k == 0 and len(_kall) == 1 and "puppeteer-core@25.11.0" in _kall[0] and f"--prefix {_pp_a}" in _kall[0]
      and _np == str(_pp_a / "node_modules"), f"{_k} {_kall} {_np} {_ut[-300:]}")
_k, _np, _kall, _ut = _pp6(_pp_a)
sjekk("pakken kan lastes: ingen ny installasjon", _k == 0 and _kall == [] and _np == str(_pp_a / "node_modules"), f"{_k} {_kall} {_np}")
(_pp_a / "node_modules" / "puppeteer-core" / "package.json").unlink()
(_pp_a / "node_modules" / "puppeteer-core" / "index.js").unlink()
_k, _np, _kall, _ut = _pp6(_pp_a)
sjekk("halvt ryddet (katalogen står, filene er borte, som 10.10. og 14.10.): installeres på nytt",
      _k == 0 and len(_kall) == 1 and _np == str(_pp_a / "node_modules"), f"{_k} {_kall} {_np} {_ut[-300:]}")
_pp_b = _d6 / "uten_pakke"
(_pp_b / "node_modules" / "annen-pakke").mkdir(parents=True)
_k, _np, _kall, _ut = _pp6(_pp_b)
sjekk("node_modules finnes, men uten puppeteer-core: installeres", _k == 0 and len(_kall) == 1, f"{_k} {_kall}")
_k, _np, _kall, _ut = _pp6(_d6 / "feiler", feil=True)
sjekk("installasjonen gir ingen pakke som kan lastes: stopper med en tydelig beskjed",
      _k != 0 and "kan fortsatt ikke lastes" in _ut and _np is None, f"{_k} {_ut[-300:]}")
_kilde6 = {f: (ROT / f).read_text("utf-8") for f in ("tests/run.sh", "tests/for_push.sh", "scripts/frys_sesong.py", "scripts/sjekk_frosset.py")}
sjekk("run.sh og for_push.sh leser inn tests/puppeteer_sti.sh, og ingen bruker den midlertidige mappa lenger",
      all(". tests/puppeteer_sti.sh || exit 1" in _kilde6[f] for f in ("tests/run.sh", "tests/for_push.sh"))
      and not any("tabellkalkulator-pp" in v for v in _kilde6.values())
      and all('".local/share/tabellkalkulator/pp"' in _kilde6[f] for f in ("scripts/frys_sesong.py", "scripts/sjekk_frosset.py")))

# Hver suite vokter seg selv: en lekkasje herfra skal ikke vaere usynlig til
# noen tilfeldigvis kjorer failsafe etterpaa.
_vern.sjekk_urort(sjekk)

print(f"\n{antall[0] - len(feil)} av {antall[0]} tester gikk gjennom.")
if feil:
    print("FEILET: " + ", ".join(feil))
sys.exit(1 if feil else 0)
