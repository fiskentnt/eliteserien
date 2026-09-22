#!/usr/bin/env python3
"""Henter resultater for OBOS-ligaen og publiserer dem bare når de er trygge.

Kilder:
  OddsPapi  hovedkilde. Kamplisten hentes én gang per kjøring (1 tellende kall)
            og gir status og tidspunkt. For hver kamp som er ferdigspilt og
            mangler resultat hos oss, hentes resultatet med /v4/scores
            (1 tellende kall per kamp).
  Wikipedia kontroll og reserve. Gratis, ingen nøkkel. Resultatrutenettet på
            "OBOS-ligaen 2026" leses og sammenlignes.

Regler:
  * Kamper identifiseres på sesong, hjemmelag og bortelag. Dato og tid er
    metadata som kan endres -- en flyttet kamp blir aldri to kamper.
  * Ingenting publiseres før kampen er ferdigspilt hos minst én kilde, og
    aldri et delresultat. Utsatte og avbrutte kamper får ikke resultat.
  * Begge kilder har sluttresultat og er enige  -> publiser.
  * Begge har sluttresultat og er uenige        -> hold tilbake, logg konflikt.
  * Bare én kilde har det, under 24 timer siden -> vent (ikke en feil).
  * Bare én kilde har det, over 24 timer siden  -> publiser den kilden.

Failsafe: det nye datasettet valideres før noe skrives. Feiler valideringen,
beholdes forrige gyldige datasett uendret, og kjøringen sier fra.

  python3 scripts/obos_results.py            # hent og publiser
  python3 scripts/obos_results.py --dry-run  # vis hva som ville skjedd
  python3 scripts/obos_results.py --no-oddspapi   # bare Wikipedia (test)
"""
import argparse
import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import oddspapi

ROOT = Path(__file__).parent.parent
DATA = ROOT / "obos" / "data"
MATCHES = DATA / "matches.json"
STATE = DATA / "results_state.json"
NAME_MAP = DATA / "name_map.json"
CSV_PATH = DATA / "obos_2012-2026.csv"
FIXTURES_CACHE = DATA / "oddspapi_fixtures_2026.json"

OBOS_TOURNAMENT = 22
SEASON = "2026"
WAIT_HOURS = 24
WIKI_PAGE = "OBOS-ligaen 2026"
WIKI_UA = "tabellkalkulator (+https://tabellkalkulator.no)"
STATUS_FINISHED = 2


def log(msg):
    print(msg, flush=True)


def norm(name):
    s = unicodedata.normalize("NFKD", (name or "").lower())
    s = s.replace("ø", "o").replace("æ", "ae").replace("å", "a")
    s = "".join(c for c in s if not unicodedata.combining(c))
    for w in (" fotball", " toppfotball", " fk", " if", " il", " ik", " sk", " bk", " ff", " fc"):
        if s.endswith(w):
            s = s[: -len(w)]
    return " ".join(s.split())


def load_names():
    m = json.loads(NAME_MAP.read_text(encoding="utf-8")) if NAME_MAP.exists() else {}
    return {k: v for k, v in m.items() if not k.startswith("_")}


def schedule():
    """Terminlisten fra CSV-en: nøkkel (hjemme, borte) -> kamp."""
    import csv
    out = {}
    for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")):
        if r["sesong"] != SEASON:
            continue
        out[(r["hjemme"], r["borte"])] = {
            "round": int(r["runde"]), "date": r["dato"], "time": r["tid"],
            "home": r["hjemme"], "away": r["borte"],
        }
    return out


def published():
    """Resultater vi alt har publisert: (hjemme, borte) -> (hg, ag)."""
    if not MATCHES.exists():
        return {}
    return {(m["home"], m["away"]): (m["hg"], m["ag"])
            for m in json.loads(MATCHES.read_text(encoding="utf-8"))}


# ---------------------------------------------------------------- OddsPapi
def oddspapi_fixtures(key, max_age_hours=20):
    """Kamplisten. Mellomlagres, så gjentatte kjøringer samme dag er gratis."""
    if FIXTURES_CACHE.exists():
        d = json.loads(FIXTURES_CACHE.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched_at"])
        if age < timedelta(hours=max_age_hours):
            log(f"  kampliste fra mellomlager ({len(d['fixtures'])} kamper, {age.seconds//3600} t gammel)")
            return d["fixtures"]
    d, err = oddspapi.call("/v4/fixtures", {"tournamentId": OBOS_TOURNAMENT,
                                            "from": f"{SEASON}-01-01", "to": f"{SEASON}-12-31"}, key)
    if err:
        log(f"  FEIL ved kampliste: {err}")
        return None
    fl = oddspapi.unwrap(d)
    FIXTURES_CACHE.write_text(json.dumps(
        {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "tournamentId": OBOS_TOURNAMENT, "fixtures": fl}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  kampliste hentet: {len(fl)} kamper (1 tellende kall)")
    return fl


def oddspapi_score(key, fixture_id):
    """Sluttresultatet for én kamp. Returnerer (hg, ag) eller None."""
    d, err = oddspapi.call("/v4/scores", {"fixtureId": fixture_id}, key)
    if err:
        log(f"    /v4/scores feilet: {err}")
        return None
    root = d.get("data", d) if isinstance(d, dict) else {}
    items = root if isinstance(root, list) else [root]
    for it in items:
        if not isinstance(it, dict):
            continue
        # Feltnavnene er ikke dokumentert i detalj: let etter et par vanlige
        # former, og bare på SLUTTresultat (ikke omgang eller delresultat).
        for hk, ak in (("homeScore", "awayScore"), ("participant1Score", "participant2Score"),
                       ("home", "away"), ("score1", "score2")):
            h, a = it.get(hk), it.get(ak)
            if isinstance(h, dict):
                h, a = h.get("total") or h.get("fullTime"), (a or {}).get("total") or (a or {}).get("fullTime")
            if isinstance(h, (int, float)) and isinstance(a, (int, float)):
                return int(h), int(a)
        sc = it.get("scores") or it.get("result")
        if isinstance(sc, dict):
            ft = sc.get("fullTime") or sc.get("ft") or sc
            h, a = ft.get("home"), ft.get("away")
            if isinstance(h, (int, float)) and isinstance(a, (int, float)):
                return int(h), int(a)
    log(f"    fant ikke sluttresultat i svaret: {json.dumps(d, ensure_ascii=False)[:200]}")
    return None


# ---------------------------------------------------------------- Wikipedia
def wikipedia_results(names):
    """Resultatrutenettet fra Wikipedia: (hjemme, borte) -> (hg, ag).

    Rutenettet har lagene som rader og motstanderne som kolonner. Bare celler
    med et ferdig resultat ("2–1") leses; tomme celler og strek hoppes over."""
    url = ("https://no.wikipedia.org/w/api.php?action=parse&format=json&prop=text&page="
           + urllib.parse.quote(WIKI_PAGE))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA})
        with urllib.request.urlopen(req, timeout=45) as r:
            page = json.loads(r.read().decode("utf-8"))
        doc = page["parse"]["text"]["*"]
    except Exception as e:
        log(f"  Wikipedia feilet: {type(e).__name__}: {e}")
        return None
    tables = re.findall(r"<table[^>]*>.*?</table>", doc, re.S)
    known = {norm(v): v for v in names.values()}
    txt = lambda h: " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h)).split())
    for t in tables:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
        if len(rows) < 16:
            continue
        head = [txt(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.S)]
        # Rutenettet kjennes igjen på hjørnecellen "Hjemme \ Borte" og 16 kolonner.
        if len(head) != 17 or "hjemme" not in head[0].lower():
            continue
        # Kolonnene er forkortelser (BRY, EIK, ...), men står i SAMME rekkefølge
        # som radene, og radene har fulle lagnavn. Derfor leses lagene av radene.
        teams, cells_by_row = [], []
        for row in rows[1:]:
            cells = [c[1] for c in re.findall(r"<(t[hd])[^>]*>(.*?)</\1>", row, re.S)]
            if len(cells) != 17:
                continue
            name = known.get(norm(txt(cells[0])))
            if not name:
                log(f"  Wikipedia: ukjent lagnavn i rutenettet: {txt(cells[0])!r}")
                return None
            teams.append(name)
            cells_by_row.append(cells[1:])
        if len(teams) != 16:
            continue
        out = {}
        for ri, home in enumerate(teams):
            for ci, cell in enumerate(cells_by_row[ri]):
                v = txt(cell)
                if ri == ci:
                    # Diagonalen skal være tom. Er den ikke det, stemmer ikke
                    # rekkefølgen, og da leses ingenting.
                    if re.match(r"^\d+\s*[–\-−:]\s*\d+$", v):
                        log("  Wikipedia: diagonalen har resultat, rekkefølgen stemmer ikke")
                        return None
                    continue
                m = re.match(r"^(\d+)\s*[–\-−:]\s*(\d+)$", v)
                if m:
                    out[(home, teams[ci])] = (int(m.group(1)), int(m.group(2)))
        log(f"  Wikipedia: {len(out)} resultater fra rutenettet")
        return out
    log("  Wikipedia: fant ikke resultatrutenettet")
    return None


# ---------------------------------------------------------------- validering
def validate(new_rows, sched, prev):
    """Sier fra om noe er galt med datasettet. Tom liste = trygt å publisere."""
    problems = []
    teams = {t for k in sched for t in k}
    if len(teams) != 16:
        problems.append(f"terminlisten har {len(teams)} lag, ventet 16")
    seen = set()
    for m in new_rows:
        key = (m["home"], m["away"])
        if key in seen:
            problems.append(f"kampen finnes to ganger: {key}")
        seen.add(key)
        if key not in sched:
            problems.append(f"kamp som ikke står i terminlisten: {key}")
        if not isinstance(m["hg"], int) or not isinstance(m["ag"], int) or m["hg"] < 0 or m["ag"] < 0:
            problems.append(f"ugyldig resultat for {key}: {m['hg']}-{m['ag']}")
    for key, val in prev.items():
        if key not in seen:
            problems.append(f"tidligere publisert resultat er borte: {key}")
        else:
            now = next(m for m in new_rows if (m["home"], m["away"]) == key)
            if (now["hg"], now["ag"]) != val:
                problems.append(f"tidligere resultat endret: {key} {val} -> {(now['hg'], now['ag'])}")
    if len(new_rows) < len(prev):
        problems.append(f"færre resultater enn før: {len(new_rows)} mot {len(prev)}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-oddspapi", action="store_true", help="bare Wikipedia (for test)")
    ap.add_argument("--max-scores", type=int, default=20, help="høyst så mange /v4/scores-kall")
    ap.add_argument("--forget-round", type=int, help="glem resultatene i denne runden først "
                                                     "(for å vise at kjeden henter dem på nytt)")
    ap.add_argument("--break-wikipedia", action="store_true", help="test: lat som Wikipedia er ødelagt")
    ap.add_argument("--break-all", action="store_true", help="test: lat som ingen kilder svarer")
    args = ap.parse_args()

    names = load_names()
    sched = schedule()
    prev = published()
    if args.forget_round:
        drop = [k for k, s2 in sched.items() if s2["round"] == args.forget_round and k in prev]
        for k in drop:
            del prev[k]
        log(f"Glemmer runde {args.forget_round}: {len(drop)} resultater tas ut, så kjeden må hente dem på nytt.")
    log(f"Terminliste: {len(sched)} kamper. Publisert fra før: {len(prev)} resultater.")

    key = None if args.no_oddspapi else (oddspapi and __import__("os").environ.get("ODDSPAPI_KEY", "").strip())
    op_scores, fixtures = {}, []
    if key:
        fixtures = oddspapi_fixtures(key) or []
        by_pair = {}
        for f in fixtures:
            h = names.get(f.get("participant1Name"), f.get("participant1Name"))
            a = names.get(f.get("participant2Name"), f.get("participant2Name"))
            hn = {norm(x): x for x in {t for k in sched for t in k}}
            h, a = hn.get(norm(h)), hn.get(norm(a))
            if h and a:
                by_pair[(h, a)] = f
        missing = [(k2, f) for k2, f in by_pair.items()
                   if k2 not in prev and f.get("statusId") == STATUS_FINISHED]
        log(f"  ferdigspilte kamper uten publisert resultat: {len(missing)}")
        for k2, f in missing[: args.max_scores]:
            sc = oddspapi_score(key, f.get("fixtureId"))
            if sc:
                op_scores[k2] = sc
                log(f"    {k2[0]} mot {k2[1]}: {sc[0]}-{sc[1]}")
            time.sleep(1.2)
    elif not args.no_oddspapi:
        log("  ODDSPAPI_KEY mangler: hopper over OddsPapi")

    wiki = None if args.break_all or args.break_wikipedia else wikipedia_results(names)
    if args.break_wikipedia or args.break_all:
        log("  (test: later som kilden er ødelagt)")
    if args.break_all:
        op_scores = {}
    if wiki is None and not op_scores:
        log("INGEN KILDER SVARTE. Beholder forrige datasett uendret.")
        return 2

    # Kryssjekk av det som ALT er publisert: endrer ingenting, men sier fra
    # hvis en kilde er uenig i noe vi har stående.
    if wiki:
        old_conf = [f"{h} mot {a}: vi har {v[0]}-{v[1]}, Wikipedia {wiki[(h,a)][0]}-{wiki[(h,a)][1]}"
                    for (h, a), v in prev.items() if (h, a) in wiki and wiki[(h, a)] != v]
        log(f"  kryssjekk mot Wikipedia: {len(prev)} publiserte, "
            f"{sum(1 for k2 in prev if k2 in wiki)} finnes hos Wikipedia, {len(old_conf)} uenige")
        for c in old_conf[:10]:
            log(f"    UENIGHET {c}")

    # ---- sammenlign og avgjør
    now = datetime.now(timezone.utc)
    publish, conflicts, waiting = dict(prev), [], []
    cand = set(op_scores) | {k2 for k2 in (wiki or {}) if k2 not in prev}
    for k2 in sorted(cand):
        if k2 in prev or k2 not in sched:
            continue
        o, w = op_scores.get(k2), (wiki or {}).get(k2)
        s = sched[k2]
        try:
            kickoff = datetime.fromisoformat(f"{s['date']}T{s['time']}").replace(
                tzinfo=ZoneInfo("Europe/Oslo")).astimezone(timezone.utc)
        except Exception:
            kickoff = now
        old_enough = (now - kickoff) > timedelta(hours=WAIT_HOURS)
        if o and w:
            if o == w:
                publish[k2] = o
            else:
                conflicts.append(f"{k2[0]} mot {k2[1]}: OddsPapi {o[0]}-{o[1]}, Wikipedia {w[0]}-{w[1]}")
        elif o or w:
            src, val = ("OddsPapi", o) if o else ("Wikipedia", w)
            if old_enough:
                publish[k2] = val
                log(f"  bare {src} har {k2[0]} mot {k2[1]} ({val[0]}-{val[1]}), over {WAIT_HOURS} t siden: publiseres")
            else:
                waiting.append(f"{k2[0]} mot {k2[1]}: bare {src} har det ennå")
    log(f"\nNye resultater: {len(publish) - len(prev)}. Venter: {len(waiting)}. Konflikter: {len(conflicts)}.")
    for c in conflicts:
        log(f"  KONFLIKT {c}")
    for w2 in waiting:
        log(f"  venter: {w2}")

    rows = []
    for k2, (hg, ag) in publish.items():
        s = sched.get(k2)
        if not s:
            continue
        rows.append({"date": s["date"], "time": s["time"], "round": s["round"],
                     "home": k2[0], "away": k2[1], "hg": hg, "ag": ag})
    rows.sort(key=lambda m: (m["date"], m["time"], m["home"]))

    problems = validate(rows, sched, prev)
    if problems:
        log("\nVALIDERINGEN FEILET. Forrige datasett beholdes uendret:")
        for p in problems:
            log(f"  {p}")
        return 3

    STATE.write_text(json.dumps({
        "checked_at": now.isoformat(timespec="seconds"),
        "published": len(rows), "new": len(publish) - len(prev),
        "conflicts": conflicts, "waiting": waiting,
        "oddspapi_usage": oddspapi.usage()[0],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    if args.dry_run:
        log(f"\n--dry-run: ville publisert {len(rows)} resultater (ingenting skrevet)")
    else:
        MATCHES.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        log(f"\nPubliserte {len(rows)} resultater til {MATCHES.relative_to(ROOT)}")
    used, limit = oddspapi.usage()
    log(f"OddsPapi-forbruk denne måneden: {used} av {limit} tellende kall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
