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
from datetime import date
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROT / "scripts"))
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
sesong.bytt(rot, date(2027, 1, 1), utfor=True, log=stille)
d = sesong.les(rot)
sjekk("etter byttet er 2027 aktiv for Eliteserien",
      d["ligaer"]["eliteserien"]["aktiv"] == "2027")
sjekk("2026 er merket frosset",
      d["ligaer"]["eliteserien"]["sesonger"]["2026"]["status"] == "frosset")
sjekk("OBOS står fortsatt på 2026", d["ligaer"]["obos"]["aktiv"] == "2026")

obos_2027 = dikt_terminliste(2027, sorted(LIGAER["obos"]["lag"]))
sesong.oppdag(rot, "obos", "2027", obos_2027, log=stille)
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
rader = ntf_source.parse_side(FERDIG, "resultater", "eliteserien", log=lambda s: None)
sjekk("eksplisitt ferdigspilt: resultatet tas inn",
      (rader[0]["hg"], rader[0]["ag"]) == (1, 0), str(rader[0]))

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

print(f"\n{antall[0] - len(feil)} av {antall[0]} tester gikk gjennom.")
if feil:
    print("FEILET: " + ", ".join(feil))
sys.exit(1 if feil else 0)
