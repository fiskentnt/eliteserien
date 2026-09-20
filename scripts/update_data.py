#!/usr/bin/env python3
"""Bygger data/matches.json og data/fixtures.json for Eliteserien 2026.

To kilder, ingen nøkler:
  - ffksupporter.net (ffk_source.py): fasit. Har hele sesongens kampoppsett
    (runde + dato for alle 240 kamper), og resultat for de som er spilt.
  - ESPN sitt åpne API (espn_source.py): raskere med ferske resultater, men
    har vist seg å kunne gi feil resultat for enkeltkamper. Brukes derfor kun
    til å fylle inn resultater ffksupporter ikke har lagt inn ennå.

Kjøres av GitHub Actions-workflowen (.github/workflows/update-data.yml) og
lokalt for verifisering. Skriver kun til disk — commit/push håndteres av
workflowen (kun hvis noe faktisk endret seg).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ffk_source
import espn_source
import fetch_odds_history
import merge_odds
import fit_model

ROOT = Path(__file__).parent.parent
MONTH_ABBR = {1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "mai", 6: "jun",
              7: "jul", 8: "aug", 9: "sep", 10: "okt", 11: "nov", 12: "des"}

FFK_CACHE_PATH = ROOT / "data" / "ffk_cache.json"
FFK_MIN_INTERVAL_MIN = 60  # ffksupporter.net skrapes (16 sider) maks én gang i timen
STATUS_PATH = ROOT / "data" / "status.json"


def month_range_label(dates):
    """Formaterer en liste ISO-datoer til f.eks. '18. til 20. sep' eller '13. des'."""
    days = sorted({d for d in dates})
    parts = [(int(d[8:10]), int(d[5:7])) for d in days]
    first, last = parts[0], parts[-1]
    if first == last:
        return f"{first[0]}. {MONTH_ABBR[first[1]]}"
    joiner = "og" if len(parts) <= 2 or (last[0] - first[0] == 1 and first[1] == last[1]) else "til"
    if first[1] == last[1]:
        return f"{first[0]}. {joiner} {last[0]}. {MONTH_ABBR[first[1]]}"
    return f"{first[0]}. {MONTH_ABBR[first[1]]} {joiner} {last[0]}. {MONTH_ABBR[last[1]]}"


def reconcile(ffk_rows, espn_rows, log=lambda s: None):
    """Slår sammen kilder per kamp (nøkkel: lagpar, unikt i en dobbel serie).
    Runde og dato kommer alltid fra ffksupporter (har hele sesongoppsettet).
    Resultat: ffksupporter hvis satt, ellers ESPN. Uenighet mellom kildene
    når begge har et resultat logges, men ffksupporter vinner alltid."""
    espn_by_pair = {(r["home"], r["away"]): r for r in espn_rows}

    merged = []
    for r in ffk_rows:
        pair = (r["home"], r["away"])
        espn = espn_by_pair.get(pair)
        hg, ag, src = r["hg"], r["ag"], "ffk"

        if hg is None and espn and espn["hg"] is not None:
            if espn.get("suspect"):
                log(f"ADVARSEL: ESPN har mistenkelig resultat for {pair} (0-0 med vinner merket), "
                    f"hopper over og venter på ffksupporter.net")
            else:
                hg, ag, src = espn["hg"], espn["ag"], "espn"
        elif hg is not None and espn and espn["hg"] is not None and (hg, ag) != (espn["hg"], espn["ag"]):
            log(f"ADVARSEL: uenighet for {pair} runde {r['round']}: "
                f"ffksupporter={hg}-{ag} ESPN={espn['hg']}-{espn['ag']} — bruker ffksupporter")

        merged.append({"date": r["date"], "time": r.get("time"), "round": r["round"], "home": r["home"],
                        "away": r["away"], "hg": hg, "ag": ag, "src": src if hg is not None else None})
    return merged


def build(merged):
    matches = [r for r in merged if r["hg"] is not None]
    matches.sort(key=lambda r: (r["date"], r["round"], r["home"]))
    matches_out = [{"date": r["date"], "time": r.get("time"), "round": r["round"], "home": r["home"],
                     "away": r["away"], "hg": r["hg"], "ag": r["ag"]} for r in matches]

    by_round = {}
    for r in merged:
        by_round.setdefault(r["round"], []).append(r)

    # Sorter rundene kronologisk (etter tidligste kampdato i runden), ikke etter
    # rundenummer — runde 12 er flyttet til oktober og skal vises der kronologisk,
    # ikke først i listen fordi "12" er et lavt tall.
    round_order = sorted(by_round, key=lambda rn: min(r["date"] for r in by_round[rn]))

    fixtures_out = []
    for round_no in round_order:
        group = by_round[round_no]
        if not any(r["hg"] is None for r in group):
            continue  # runden er ferdigspilt, ikke ta den med
        group.sort(key=lambda r: (r["date"], r.get("time") or "", r["home"]))
        fixtures_out.append({
            "round": round_no,
            "when": month_range_label([r["date"] for r in group]),
            "matches": [
                {"home": r["home"], "away": r["away"], "date": r["date"], "time": r.get("time"),
                 "played": r["hg"] is not None, "hg": r["hg"], "ag": r["ag"]}
                for r in group
            ],
        })
    return matches_out, fixtures_out


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_status(ok, now, error=None):
    """data/status.json -- leses av index.html sitt stempel. Skrives KUN her,
    dvs. bare når update_data.py faktisk har kjørt (ikke når should_fetch.py
    avsluttet kjøringen tidlig uten å hente noe), slik at "Sist sjekket" i
    stempelet bare oppdateres ved reelle sjekker."""
    data = {"last_checked": now.isoformat(timespec="seconds"), "ok": ok}
    if error:
        data["error"] = str(error)[:300]
    STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_ffk_rows(cache_dir, log):
    """Henter ffksupporter.net sine 16 sider maks én gang i timen (se
    FFK_MIN_INTERVAL_MIN) — resten av tiden gjenbrukes mellomlagrede rader
    fra forrige skraping (data/ffk_cache.json, committes av workflowen så den
    overlever til neste kjøring). ESPN (ett kall, se main()) dekker friskhet
    i mellomtiden; ffksupporter er fortsatt fasit når begge har et resultat."""
    cached = json.loads(FFK_CACHE_PATH.read_text(encoding="utf-8")) if FFK_CACHE_PATH.exists() else None
    now = datetime.now(timezone.utc)
    age_min = (now - datetime.fromisoformat(cached["fetched_at"])).total_seconds() / 60 if cached else None
    due = cached is None or age_min >= FFK_MIN_INTERVAL_MIN

    if due:
        try:
            rows, warnings = ffk_source.fetch_all(cache_dir=cache_dir, log=log)
            for key, prev, r in warnings:
                log(f"ADVARSEL ffksupporter: uenighet mellom lagenes sider for {key}: {prev} vs {r}")
            FFK_CACHE_PATH.write_text(json.dumps(
                {"fetched_at": now.isoformat(timespec="seconds"), "rows": rows}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            return rows
        except ffk_source.RateLimited as e:
            log(f"ADVARSEL: {e} -- venter til neste times-sjekk.")
            if cached:
                log(f"Bruker mellomlagrede ffksupporter-data fra for {age_min:.0f} min siden i mellomtiden.")
                return cached["rows"]
            raise  # ingen mellomlagrede data å falle tilbake på

    log(f"ffksupporter.net sjekket for {age_min:.0f} min siden (maks én gang i timen) -- bruker mellomlagrede data.")
    return cached["rows"]


def main(cache_dir=None):
    log = lambda s: print(s, file=sys.stderr)
    now = datetime.now(timezone.utc)
    try:
        try:
            espn_rows = espn_source.fetch_all(cache_dir=cache_dir, log=log)
        except espn_source.RateLimited as e:
            log(f"ADVARSEL: {e} -- fortsetter uten ESPN denne runden (ffksupporter dekker fortsatt resultatet).")
            espn_rows = []

        ffk_rows = get_ffk_rows(cache_dir, log)

        merged = reconcile(ffk_rows, espn_rows, log=log)
        matches_out, fixtures_out = build(merged)

        from_espn = sum(1 for r in merged if r["src"] == "espn")
        log(f"Ferdig: {len(matches_out)} spilte kamper ({from_espn} fra ESPN, resten ffksupporter.net), "
            f"{len(fixtures_out)} runder med gjenstående kamper.")

        data_dir = ROOT / "data"
        data_dir.mkdir(exist_ok=True)
        write_json(data_dir / "matches.json", matches_out)
        write_json(data_dir / "fixtures.json", fixtures_out)

        log("--- Sluttodds (football-data.co.uk, maks én gang i døgnet) ---")
        fetch_odds_history.main()
        log("--- Slår sammen oddskilder ---")
        merge_odds.main()
        log("--- Tilpasser modellen ---")
        fit_model.main()

        write_status(ok=True, now=now)
    except Exception as e:
        write_status(ok=False, now=now, error=e)
        raise


if __name__ == "__main__":
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    main(cache_dir=cache)
