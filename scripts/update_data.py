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
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import ffk_source
import espn_source
import fetch_odds_history
import merge_odds
import fit_model
import leaguedata

ROOT = Path(__file__).parent.parent
LEAGUE = ROOT / "eliteserien"  # ligamappen (data/ ligger under den, så flere ligaer kan komme ved siden av)
OSLO = ZoneInfo("Europe/Oslo")

FFK_CACHE_PATH = LEAGUE / "data" / "ffk_cache.json"
FFK_MIN_INTERVAL_MIN = 60  # ffksupporter.net skrapes (16 sider) maks én gang i timen
STATUS_PATH = LEAGUE / "data" / "status.json"
AUDIT_STATE_PATH = LEAGUE / "data" / "audit_state.json"


class DataAuditError(Exception):
    """Avvik funnet i den daglige kontrollen mot ffksupporter.net (se
    run_daily_audit). Skal feile kjøringen synlig, som EspnDataError."""
    pass


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
    """matches.json og fixtures.json. Reglene er felles for ligaene, se
    scripts/leaguedata.py."""
    return leaguedata.build_matches(merged), leaguedata.build_fixtures(merged)


def write_json(path, data):
    leaguedata.write_json(path, data)


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
        except Exception as e:
            wait_msg = "venter til neste times-sjekk" if isinstance(e, ffk_source.RateLimited) else "prøver igjen neste kjøring"
            log(f"ADVARSEL: ffksupporter.net feilet ({e}) -- {wait_msg}.")
            if cached:
                log(f"Bruker mellomlagrede ffksupporter-data fra for {age_min:.0f} min siden i mellomtiden.")
                return cached["rows"]
            raise  # ingen mellomlagrede data å falle tilbake på -- da skal kjøringen faktisk feile synlig

    log(f"ffksupporter.net sjekket for {age_min:.0f} min siden (maks én gang i timen) -- bruker mellomlagrede data.")
    return cached["rows"]


def _kickoff_utc(date_str, time_str):
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=OSLO).astimezone(timezone.utc)


def audit_against_ffk(matches_out, ffk_rows, now):
    """Sammenligner ALLE spilte kamper i matches_out (vår fasit akkurat nå,
    uansett hvilken kilde hvert resultat kom fra) mot ffksupporter.net sin
    egen liste (ffk_rows, fra denne kjøringens get_ffk_rows()). ffksupporter
    oppdateres for hånd og ligger ofte etter, så avvik deles i to
    alvorlighetsgrader:
      1. Begge kilder har et resultat, men de er ULIKE -- feil med en gang.
      2. Vi har et resultat (typisk fra ESPN) som ffksupporter.net ikke har
         registrert ennå -- bare en advarsel, siden dette er normalt og
         forbigående. Blir en feil først når det er over 72 timer siden
         avspark og ffksupporter.net FORTSATT ikke har det.
      3. ffksupporter.net har et resultat vi mangler helt -- feil med en
         gang (skal være umulig gitt at reconcile() alltid bruker
         ffksupporter sitt tall når det finnes, så dette er et tegn på en
         reell feil i sammenslåingen).
    Returnerer (errors, warnings), begge lister med tekst."""
    ffk_by_pair = {(r["home"], r["away"]): r for r in ffk_rows}
    matches_by_pair = {(m["home"], m["away"]): m for m in matches_out}
    errors, warnings = [], []

    for m in matches_out:
        ffk = ffk_by_pair.get((m["home"], m["away"]))
        if ffk is None:
            errors.append(f"{m['home']}-{m['away']} ({m['date']}): finnes hos oss, men ikke i det hele tatt hos ffksupporter.net")
        elif ffk["hg"] is None or ffk["ag"] is None:
            hours_since = None
            if m.get("time"):
                try:
                    hours_since = (now - _kickoff_utc(m["date"], m["time"])).total_seconds() / 3600
                except ValueError:
                    hours_since = None
            if hours_since is not None and hours_since > 72:
                errors.append(f"{m['home']}-{m['away']} ({m['date']}): vi har {m['hg']}-{m['ag']}, "
                               f"ffksupporter.net har fortsatt ikke registrert resultat {hours_since:.0f} timer etter avspark")
            else:
                suffix = f" ({hours_since:.0f}t siden avspark)" if hours_since is not None else ""
                warnings.append(f"{m['home']}-{m['away']} ({m['date']}): vi har {m['hg']}-{m['ag']}, "
                                 f"ffksupporter.net har ikke registrert resultat ennå{suffix}")
        elif (ffk["hg"], ffk["ag"]) != (m["hg"], m["ag"]):
            errors.append(f"{m['home']}-{m['away']} ({m['date']}): vi har {m['hg']}-{m['ag']}, ffksupporter.net har {ffk['hg']}-{ffk['ag']}")

    for r in ffk_rows:
        if r["hg"] is None or r["ag"] is None:
            continue
        if (r["home"], r["away"]) not in matches_by_pair:
            errors.append(f"{r['home']}-{r['away']} ({r['date']}): ffksupporter.net har {r['hg']}-{r['ag']}, vi mangler kampen helt")

    return errors, warnings


def run_daily_audit(matches_out, ffk_rows, now, log):
    """Én gang i døgnet: full kontroll av alle spilte kamper mot
    ffksupporter.net. Kjøres på den første kjøringen som når hit hver dag --
    egen dato-sperre her, ikke avhengig av noe bestemt klokkeslett. Kritiske
    avvik feiler kjøringen (stempelet blir rødt); "ikke registrert ennå" er
    bare en advarsel i loggen med mindre den har stått i over 72 timer.
    "Sjekket i dag"-merket settes uansett utfall, så en reell feil ikke
    spammer hvert kvarter resten av dagen."""
    today = now.astimezone(OSLO).strftime("%Y-%m-%d")
    state = json.loads(AUDIT_STATE_PATH.read_text(encoding="utf-8")) if AUDIT_STATE_PATH.exists() else {}
    if state.get("checked_date") == today:
        return
    log(f"--- Daglig kontroll: {len(matches_out)} spilte kamper mot ffksupporter.net ---")
    errors, warnings = audit_against_ffk(matches_out, ffk_rows, now)
    AUDIT_STATE_PATH.write_text(json.dumps(
        {"checked_date": today, "errors": len(errors), "warnings": len(warnings)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    for w in warnings:
        log(f"ADVARSEL: {w}")
    if errors:
        for e in errors:
            log(f"AVVIK: {e}")
        raise DataAuditError(f"{len(errors)} avvik mellom matches.json og ffksupporter.net:\n" + "\n".join(errors))
    log(f"Daglig kontroll: ingen kritiske avvik ({len(warnings)} advarsel(er)).")


def main(cache_dir=None):
    log = lambda s: print(s, file=sys.stderr)
    now = datetime.now(timezone.utc)
    try:
        try:
            espn_rows = espn_source.fetch_all(cache_dir=cache_dir, log=log)
        except espn_source.EspnDataError:
            # Datakvalitetsproblem (ferdigspilt kamp som ikke lot seg tolke),
            # ikke en vanlig nettverks-/API-feil -- skal IKKE skjules. Feiler
            # kjøringen synlig (stempelet blir rødt) i stedet for å risikere
            # å bare hoppe stille over et ekte resultat, slik det gjorde
            # 20. september 2026 (se git-historikken for den hendelsen).
            raise
        except Exception as e:
            # Alt annet (429, 400, timeout, DNS...) er bare ESPN som er
            # utilgjengelig -- ffksupporter.net er fasit uansett, så dette
            # skal aldri felle hele kjøringen.
            log(f"ADVARSEL: ESPN feilet ({e}) -- fortsetter uten ESPN denne runden (ffksupporter dekker fortsatt resultatet).")
            espn_rows = []

        ffk_rows = get_ffk_rows(cache_dir, log)

        merged = reconcile(ffk_rows, espn_rows, log=log)
        matches_out, fixtures_out = build(merged)

        from_espn = sum(1 for r in merged if r["src"] == "espn")
        log(f"Ferdig: {len(matches_out)} spilte kamper ({from_espn} fra ESPN, resten ffksupporter.net), "
            f"{len(fixtures_out)} runder med gjenstående kamper.")

        data_dir = LEAGUE / "data"
        data_dir.mkdir(exist_ok=True)
        write_json(data_dir / "matches.json", matches_out)
        write_json(data_dir / "fixtures.json", fixtures_out)

        log("--- Sluttodds (football-data.co.uk, maks én gang i døgnet) ---")
        fetch_odds_history.main()
        log("--- Slår sammen oddskilder ---")
        merge_odds.main()
        log("--- Tilpasser modellen ---")
        fit_model.main()

        # Etter alt det normale arbeidet er gjort og lagret: den daglige
        # kontrollen mot ffksupporter.net. Kan fortsatt feile KJØRINGEN
        # (stempelet blir rødt), men hindrer ikke dagens resultater/odds/
        # modell i å bli skrevet og committet først.
        run_daily_audit(matches_out, ffk_rows, now, log)

        write_status(ok=True, now=now)
    except Exception as e:
        write_status(ok=False, now=now, error=e)
        raise


if __name__ == "__main__":
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    main(cache_dir=cache)
