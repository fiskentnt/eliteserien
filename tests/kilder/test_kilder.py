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

import os as _os
_os.environ["ARKIV_TVING_KAMPDAG"] = "1"
sjekk("testbryteren overstyrer vinduet", _paa("03:00")[0])
del _os.environ["ARKIV_TVING_KAMPDAG"]
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

print(f"\n{antall[0] - len(feil)} av {antall[0]} tester gikk gjennom.")
if feil:
    print("FEILET: " + ", ".join(feil))
sys.exit(1 if feil else 0)
