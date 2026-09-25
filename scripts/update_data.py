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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import ffk_source
import espn_source
import should_fetch
import ntf_source
import nff_source
from reconcile_ny import reconcile as reconcile_kilder, behold_eksisterende, rimelige_datoer
import fetch_odds_history
import merge_odds
import fit_model
import leaguedata

ROOT = Path(__file__).parent.parent
LEAGUE = ROOT / "eliteserien"  # ligamappen (data/ ligger under den, så flere ligaer kan komme ved siden av)
OSLO = ZoneInfo("Europe/Oslo")

FFK_CACHE_PATH = LEAGUE / "data" / "ffk_cache.json"
LIGA = "eliteserien"
FFK_MIN_INTERVAL_MIN = 60  # ffksupporter.net skrapes (16 sider) maks én gang i timen
STATUS_PATH = LEAGUE / "data" / "status.json"
AUDIT_STATE_PATH = LEAGUE / "data" / "audit_state.json"


class DataAuditError(Exception):
    """Avvik funnet i den daglige kontrollen mot ffksupporter.net (se
    run_daily_audit). Skal feile kjøringen synlig, som EspnDataError."""
    pass


def reconcile(ntf_rows, nff_rows, ffk_rows, espn_rows, log=lambda s: None):
    """Ligasiden er fasit for terminliste, runde, dato og avspark.
    fotball.no er uavhengig offisiell kontroll og reserve. ffksupporter er
    degradert til siste utvei, ESPN er resultatkontroll. Se reconcile_ny.py."""
    return reconcile_kilder(
        ntf_rows, nff_rows,
        reserver=[("ffksupporter", ffk_rows)],
        resultatkontroll=[("ESPN", espn_rows)],
        log=log)


def reconcile_gammel(ffk_rows, espn_rows, log=lambda s: None):
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


def dagens_revisjonsavvik(now):
    """Antall kritiske avvik i DAGENS revisjon, eller 0 hvis den ikke er
    kjørt i dag.

    Revisjonen kjører én gang per kalenderdag. Finner den et kritisk avvik,
    feiler kjøringen og stempelet blir rødt -- men NESTE kjøring samme dag
    hopper over revisjonen, og uten dette ville den skrevet ok=True og gjort
    stempelet grønt igjen mens avviket fortsatt sto. Med en utløser hvert
    tiende minutt ville det skjedd innen en time."""
    if not AUDIT_STATE_PATH.exists():
        return 0
    try:
        st = json.loads(AUDIT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if st.get("checked_date") != now.astimezone(OSLO).strftime("%Y-%m-%d"):
        return 0
    return int(st.get("errors") or 0)


def write_status(ok, now, error=None):
    """data/status.json -- leses av index.html sitt stempel. Skrives KUN her,
    dvs. bare når update_data.py faktisk har kjørt (ikke når should_fetch.py
    avsluttet kjøringen tidlig uten å hente noe), slik at "Sist sjekket" i
    stempelet bare oppdateres ved reelle sjekker.

    Dagens revisjon er sannhetskilden for om stempelet kan være grønt: står
    det kritiske avvik fra revisjonen i dag, forblir det rødt uansett hvor
    fint resten av kjøringen gikk. Det blir grønt igjen først når en NY
    revisjon faktisk bekrefter at avviket er borte."""
    avvik = dagens_revisjonsavvik(now)
    # Terminlisterevisjonen (daglig_revisjon.py) skriver sin egen tilstand.
    # Den maa med her, ellers ville denne kjoringen overskrevet et rodt
    # stempel med ok=True.
    try:
        import daglig_revisjon
        avvik += daglig_revisjon.dagens_avvik(LIGA, now)
    except Exception:
        pass
    if ok and avvik:
        ok = False
        error = error or (f"{avvik} kritisk(e) avvik i dagens revisjon står "
                          f"fortsatt uløst (se audit_state.json)")
    data = {"last_checked": now.isoformat(timespec="seconds"), "ok": ok}
    if error:
        data["error"] = str(error)[:300]
    if avvik:
        data["revisjon_avvik"] = avvik
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
                                 f"kontrollkilden har ikke registrert resultat ennå{suffix}")
        elif (ffk["hg"], ffk["ag"]) != (m["hg"], m["ag"]):
            errors.append(f"{m['home']}-{m['away']} ({m['date']}): vi har {m['hg']}-{m['ag']}, kontrollkilden har {ffk['hg']}-{ffk['ag']}")

    for r in ffk_rows:
        if r["hg"] is None or r["ag"] is None:
            continue
        if (r["home"], r["away"]) not in matches_by_pair:
            errors.append(f"{r['home']}-{r['away']} ({r['date']}): kontrollkilden har {r['hg']}-{r['ag']}, vi mangler kampen helt")

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
    if state.get("checked_date") == today and not int(state.get("errors") or 0):
        # Gjort i dag OG ren. Revisjonen har sin egen DATO-sperre, mens porten
        # bruker en 20-TIMERS klokke. Returnerte vi False her, ville siste_ok
        # aldri blitt satt paa en dag der revisjonen alt var kjort, og porten
        # ville proevd hver time resten av dagen.
        log("Daglig kontroll: alt gjort i dag uten avvik -- hopper over.")
        return True

    if state.get("checked_date") == today:
        # Gjort i dag, MEN med kritiske avvik. Da skal den kjores paa nytt,
        # ikke regnes som gjort: et avvik kan vaere rettet hos kontrollkilden
        # i mellomtiden. Sperren paa en time i porten (should_fetch.py)
        # hindrer at dette skjer oftere enn det er vits i.
        log(f"Daglig kontroll: {state['errors']} avvik fra tidligere i dag "
            f"-- kjører revisjonen på nytt.")
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
        raise DataAuditError(f"{len(errors)} avvik mellom matches.json og kontrollkilden:\n" + "\n".join(errors))
    log(f"Daglig kontroll: ingen kritiske avvik ({len(warnings)} advarsel(er)).")
    return True


RESULTAT_FRIST_TIMER = 3


def sjekk_manglende_resultat(fixtures_out, now, log):
    """Står en kamp uten sluttresultat mer enn tre timer etter avspark, er
    noe galt -- og da skal kjøringen feile synlig samme kveld, ikke bare
    legge en linje i loggen som ingen leser. Alternativet er at tabellen står
    feil til noen tilfeldigvis oppdager det.

    Kaster DataAuditError, som allerede gjør stempelet rødt."""
    sent = []
    for runde in fixtures_out:
        for m in runde.get("matches", []):
            if m.get("played"):
                continue
            if not m.get("date") or not m.get("time"):
                continue  # uten avspark kan vi ikke vite om fristen er ute
            avspark = _kickoff_utc(m["date"], m["time"])
            timer = (now - avspark).total_seconds() / 3600
            if timer > RESULTAT_FRIST_TIMER:
                sent.append(f"{m['home']}-{m['away']} ({m['date']} {m.get('time')}): "
                            f"{timer:.1f} timer siden avspark, fortsatt uten sluttresultat")
    if sent:
        for e in sent:
            log(f"AVVIK: {e}")
        raise DataAuditError(
            f"{len(sent)} kamp(er) mangler sluttresultat mer enn "
            f"{RESULTAT_FRIST_TIMER} timer etter avspark:\n" + "\n".join(sent))
    return 0


def main(cache_dir=None):
    log = lambda s: print(s, file=sys.stderr)
    now = datetime.now(timezone.utc)

    # En frossen sesong er uforanderlig. Rundt aarsskiftet viser kildene
    # NESTE sesong, saa en kjoring her ville skrevet neste sesongs kamper inn
    # i den frosne. Vi venter paa at bytt() gjor jobben 1. januar.
    import sesong as _ses
    _aktiv0 = _ses.aktiv_sesong(ROOT, LIGA, log=log)
    if _aktiv0 and _ses.er_frosset(ROOT, LIGA, _aktiv0):
        log(f"Sesongen {_aktiv0} er frosset -- rører ingenting. "
            f"Venter på sesongskiftet.")
        return 0

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

        # Hovedkilde: ligasiden. Uten den kan vi ikke bygge terminlisten.
        ntf_rows = ntf_source.fetch_all(LIGA, cache_dir=cache_dir, log=log)

        # fotball.no, hoeyst ett forsok per dogn (nff_source styrer det selv).
        # Brukes BARE i den daglige revisjonen under, aldri i avstemmingen.
        try:
            nff_rows = nff_source.fetch_all(LIGA, cache_dir=cache_dir, log=log)
        except Exception as e:
            log(f"ADVARSEL: fotball.no feilet ({e}) -- fortsetter uten "
                f"uavhengig kontroll av terminlisten denne runden.")
            nff_rows = []

        # Reserve. Feiler den, er det ikke lenger kritisk.
        try:
            ffk_rows = get_ffk_rows(cache_dir, log)
        except Exception as e:
            log(f"ADVARSEL: ffksupporter (reserve) feilet ({e}) -- fortsetter.")
            ffk_rows = []

        # fotball.no er IKKE med i avstemmingen. Cachen kan vaere opptil 20
        # timer gammel, og da ville et ferskt avspark eller resultat fra
        # ligasiden gitt en falsk advarsel i hver kjoring i 20 timer.
        # Ligasiden ville vunnet uansett -- stoyen var hele problemet.
        # Kontrollen mot fotball.no skjer i den daglige revisjonen i stedet,
        # der dataene er like gamle paa begge sider.
        merged = reconcile(ntf_rows, [], ffk_rows, espn_rows, log=log)

        # Et publisert resultat skal aldri forsvinne fordi en kilde midlertidig
        # ikke melder kampen som ferdig. Se behold_eksisterende().
        tidligere = json.loads((LEAGUE / "data" / "matches.json").read_text(encoding="utf-8")) \
            if (LEAGUE / "data" / "matches.json").exists() else []
        merged = behold_eksisterende(merged, tidligere, log=log)
        # En dato utenfor sesongens vindu er alltid feil hos kilden, aldri
        # hos oss. Se rimelige_datoer() for hendelsen som gjorde den
        # nodvendig. Sesongen kommer fra registeret, ikke fra dataene.
        import sesong as _sesong
        _aktiv = _sesong.aktiv_sesong(ROOT, LIGA, log=log)
        merged, utenfor, _datofeil = rimelige_datoer(merged, tidligere, _aktiv, log=log)
        matches_out, fixtures_out = build(merged)

        fordeling = {}
        for r in merged:
            if r["src"]:
                fordeling[r["src"]] = fordeling.get(r["src"], 0) + 1
        log(f"Ferdig: {len(matches_out)} spilte kamper ({fordeling}), "
            f"{len(fixtures_out)} runder med gjenstående kamper.")

        data_dir = LEAGUE / "data"
        data_dir.mkdir(exist_ok=True)
        write_json(data_dir / "matches.json", matches_out)
        write_json(data_dir / "fixtures.json", fixtures_out)

        # Etter skriving: filene er riktige så langt kildene rekker, men en
        # kamp som mangler resultat lenge etter avspark skal stoppe kjøringen.
        sjekk_manglende_resultat(fixtures_out, now, log)

        # Mange datoer utenfor sesongen er ikke enkeltfeil -- da er det noe
        # galt med kilden, typisk en markupendring. Datoene er rettet over,
        # men kjoringen skal feile synlig.
        if _datofeil:
            raise DataAuditError({'ingen_autoritet': 'Ingen autoritativ sesong i data/sesonger.json, så datovakten sto over. Dataene er skrevet som normalt, men en gal dato fra kilden ville ikke blitt fanget. Kjør: python3 scripts/sesong.py . init <liga> <år>', 'sesongskifte_mangler': 'Terminlisten er for en annen sesong enn registeret sier. Sesongskiftet er ikke kjørt, så datovakten sto over -- den ville ellers skrevet hele den nye sesongen tilbake til fjorårets datoer. Kjør: python3 scripts/sesong.py . bytt --utfor'}[_datofeil])
        if len(utenfor) > len(merged) * 0.25:
            raise DataAuditError(
                f"{len(utenfor)} av {len(merged)} kamper hadde dato utenfor "
                f"sesongen. Datoene er beholdt fra før, men kilden må sjekkes:\n"
                + "\n".join(utenfor[:10]))

        log("--- Sluttodds (football-data.co.uk, maks én gang i døgnet) ---")
        fetch_odds_history.main()
        # Sluttodds fra OddsPapi-vinduet: 60 til 15 minutter før avspark, den
        # eneste kilden vi vet tidspunktet for. Gratis oppslag, og bare for
        # kamper som ikke alt er hentet. Skal ALDRI kunne stoppe kjeden: uten
        # nøkkel eller ved feil faller alt tilbake på football-data.
        if os.environ.get("ODDSPAPI_KEY", "").strip():
            log("--- Sluttodds (OddsPapi, vinduet 60-15 min før avspark) ---")
            try:
                import elite_closing_odds
                elite_closing_odds.main([])
            except Exception as e:
                log(f"  OddsPapi-sluttodds feilet ({type(e).__name__}: {e}) "
                    f"-- fortsetter med football-data")
        log("--- Slår sammen oddskilder ---")
        merge_odds.main()
        log("--- Tilpasser modellen ---")
        fit_model.main()

        # Etter alt det normale arbeidet er gjort og lagret: den daglige
        # kontrollen mot ffksupporter.net. Kan fortsatt feile KJØRINGEN
        # (stempelet blir rødt), men hindrer ikke dagens resultater/odds/
        # modell i å bli skrevet og committet først.
        # Den daglige kontrollen går nå mot fotball.no (NFF), ikke mot
        # ffksupporter. Den er offisiell, uavhengig av ligasiden vi bygger
        # fra, og komplett for hele sesongen. Faller den ut, bruker vi
        # ffksupporter som før, slik at kontrollen aldri blir helt borte.
        kontroll = nff_rows or ffk_rows
        gjorde_daglig = run_daily_audit(matches_out, kontroll, now, log)

        write_status(ok=True, now=now)
        # BARE naar det daglige vedlikeholdet faktisk ble utfort i denne
        # kjoringen. En vanlig resultatkjoring midt paa dagen skal ikke
        # nullstille 20-timersklokka -- da ville revisjonen og
        # football-data-sjekken kunne bli utsatt i det uendelige.
        if gjorde_daglig:
            should_fetch.merk_ok(LIGA, now)
            log("Daglig vedlikehold utfort -- 20-timersklokka nullstilt.")
    except Exception as e:
        write_status(ok=False, now=now, error=e)
        raise


if __name__ == "__main__":
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    main(cache_dir=cache)
