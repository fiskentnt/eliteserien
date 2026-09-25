"""Tester for de offisielle kildene, reconcile() og sesongskiftet.
Kjør: python3 test_kilder.py

Testdataene er sidene slik de sto 25. september 2026, lagret i testdata/.
Fasiten er produksjonens egne filer, bortsett fra de 22 Eliteserie-kampene
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
PROD = ROT

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


def prod_kamper(liga):
    d = PROD / LIGAER[liga]["data"]
    ut = {(r["home"], r["away"]): r for r in json.loads((d / "matches.json").read_text("utf-8"))}
    for runde in json.loads((d / "fixtures.json").read_text("utf-8")):
        for k in runde["matches"]:
            ut[(k["home"], k["away"])] = {**k, "round": runde["round"]}
    return ut


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

    print(f"--- {LIGAER[liga]['visningsnavn']}: mot produksjonen ---")
    prod = prod_kamper(liga)
    sjekk("samme kampsett som produksjon", set(ntf_ix) == set(prod),
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
    sjekk("alle resultater stemmer mot produksjon", not ulikt_res, str(ulikt_res[:2]))

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


LAG_2027 = sorted(LIGAER["eliteserien"]["lag"] - {"Start"} | {"Bryne"})
god = dikt_terminliste(2027, LAG_2027)
ok, funn = sesong.valider(god, "2027", sorted(LIGAER["eliteserien"]["lag"]))
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

flyttet_beholdt = behold_eksisterende(
    [{**r, "date": "2026-12-01", "time": "20:00"} for r in glemt], ferdige, log=lambda s: None)
mål2 = next(r for r in flyttet_beholdt if (r["home"], r["away"]) == GLEMT)
sjekk("men dato og avspark oppdateres fortsatt",
      (mål2["date"], mål2["time"]) == ("2026-12-01", "20:00"), str(mål2))

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
_p, _c, _v = _R.decide(_off_ferdig, {}, {}, _sched, {}, _naa2)
sjekk("og den publiseres i SAMME kjøring, uten å vente på Wikipedia",
      _p.get(("Ranheim", "Egersund")) == (2, 1) and not _v, f"{_p} {_v}")
_p, _c, _v = _R.decide(_off_ferdig, {}, {("Ranheim", "Egersund"): (3, 1)}, _sched, {}, _naa2)
sjekk("uenighet med Wikipedia holder resultatet tilbake",
      not _p and len(_c) == 1, f"{_p} {_c}")

# Pågående kamp: 40 minutter etter avspark, stilling på tavla hos begge.
_underveis = _NTF.replace("schedule__match--played", "schedule__match--live")
_off_live = _off(_underveis, _dt(2026, 10, 2, 19, 40, tzinfo=ZoneInfo("Europe/Oslo")))
sjekk("pågående kamp: INGEN av de offisielle kildene gir resultat", not _off_live, str(_off_live))
_p, _c, _v = _R.decide(_off_live, {}, {}, _sched, {}, _naa2)
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

# 4) Gaarsdagens avvik skal ikke faerge dagens stempel
_ud.AUDIT_STATE_PATH.write_text(
    _json.dumps({"checked_date": "2020-01-01", "errors": 5}), encoding="utf-8")
_ud.write_status(ok=True, now=_naa4)
sjekk("gårsdagens avvik holder ikke stempelet rødt", _status()["ok"] is True)

# 5) En ekte feil i kjoringen gjor det fortsatt roedt, uavhengig av revisjonen
_ud.write_status(ok=False, now=_naa4, error="noe annet gikk galt")
sjekk("en vanlig feil gjør det fortsatt rødt", _status()["ok"] is False)
_ud.AUDIT_STATE_PATH = _ekte

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

# Hver suite vokter seg selv: en lekkasje herfra skal ikke vaere usynlig til
# noen tilfeldigvis kjorer failsafe etterpaa.
_vern.sjekk_urort(sjekk)

print(f"\n{antall[0] - len(feil)} av {antall[0]} tester gikk gjennom.")
if feil:
    print("FEILET: " + ", ".join(feil))
sys.exit(1 if feil else 0)
