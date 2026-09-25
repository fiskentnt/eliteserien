"""Kilde 2 (ferskhet): ESPN sitt åpne API for Eliteserien (nor.1), ingen nøkkel.

ESPN oppdaterer resultater raskere enn ffksupporter.net, men har vist seg å
kunne gi feil resultat for enkeltkamper (verifisert manuelt: to kamper i mai
2026 sto låst på 0-0 i ESPN sin data). Brukes derfor i update_data.py kun til
å fylle inn resultater ffksupporter.net ikke har lagt inn ennå — ffksupporter
er alltid fasit når den har et resultat. ESPN gir ingen rundenummer, så runde
kommer alltid fra ffksupporter.net.

Ett API-kall per kjøring (rundetavle-endepunktet for dagens dato), i stedet
for tidligere 32 kall (16 lag x 2 endepunkt) — ESPN sin rolle er bare "har
noe blitt spilt i dag", ikke hele sesongoppsettet.
"""
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

USER_AGENT = "eliteserien-tabell (+https://github.com/fiskentnt/eliteserien)"
LEAGUE = "nor.1"
OSLO = ZoneInfo("Europe/Oslo")

# ESPN lag-id -> visningsnavn slik det brukes i index.html
TEAM_ID_TO_NAME = {
    "3278": "Aalesund",
    "2980": "Bodø/Glimt",
    "3039": "Fredrikstad",
    "21380": "HamKam",
    "6750": "Start",
    "22165": "KFUM Oslo",
    "6672": "Kristiansund",
    "987": "Lillestrøm",
    "2715": "Molde",
    "438": "Rosenborg",
    "620": "Brann",
    "3279": "Sandefjord",
    "5002": "Sarpsborg 08",
    "5270": "Tromsø",
    "510": "Viking",
    "2791": "Vålerenga",
}


class RateLimited(Exception):
    """429/403 fra ESPN -- ikke prøv igjen med en gang, vent til neste kjøring."""
    def __init__(self, code):
        self.code = code
        super().__init__(f"ESPN svarte {code}")


class EspnDataError(Exception):
    """En ferdigspilt kamp kunne ikke tolkes (ukjent lag eller manglende
    resultat) -- et tegn på at ESPN har endret svarformatet igjen (som da
    scoreboard-endepunktet viste seg å mangle score.value 20. sep 2026).
    Skal IKKE fanges stille som en vanlig ESPN-feil (se update_data.py) --
    kjøringen skal feile synlig, ikke risikere å hoppe over et ekte
    resultat uten at noen merker det."""
    pass


def _logg(utfall, melding="", kamper=None):
    """ESPN er resultatkontrollen for Eliteserien. Loggingen er ren
    observasjon og kan aldri velte hentingen."""
    try:
        import hentelogg
        hentelogg.logg("eliteserien", "espn", utfall, melding=melding,
                       kamper=kamper)
    except Exception:
        pass


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            raise RateLimited(e.code) from e
        raise


def fetch_all(cache_dir=None, log=lambda s: None):
    """Ett kall til rundetavle-endepunktet. MERK: nøyaktig spørreparameter-
    format for ESPN sitt scoreboard-endepunkt for fotball er ikke verifisert
    mot live API (ingen nettverkstilgang tilgjengelig da dette ble skrevet) —
    et forsøk med datoperiode (?dates=YYYYMMDD-YYYYMMDD) ga 400 Bad Request i
    produksjon. Bruker nå en enkelt dato (i dag, norsk tid) som et enklere,
    mer sannsynlig gyldig forsøk. Feiler dette også: update_data.py fanger
    ALLTID opp feil herfra og fortsetter uten ESPN (se main() sin try/except)
    — ffksupporter.net er uansett fasit, så en feilende ESPN-sjekk degraderer
    aldri til et ødelagt resultat, bare til sjeldnere friskhet."""
    now_oslo = datetime.now(OSLO)
    day = now_oslo.strftime("%Y%m%d")
    cache_file = cache_dir and (cache_dir / "espn_scoreboard.json")
    if cache_file and cache_file.exists():
        d = json.loads(cache_file.read_text(encoding="utf-8"))
        log("[espn] scoreboard: fra lokal cache")
        _logg("cache", f"scoreboard {day}")
    else:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{LEAGUE}/scoreboard?dates={day}"
        log(f"[espn] Henter rundetavle for {day} (ett kall) ...")
        try:
            d = get_json(url)
        except Exception as e:
            # Loggfor forsoket FOR vi kaster videre. update_data.py fanger
            # ESPN-feil og fortsetter, saa uten denne linjen ville en ESPN
            # som er nede i en uke ikke vaere synlig noe sted.
            _logg("feil", f"{type(e).__name__}: {e}")
            raise
        if cache_file:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(d), encoding="utf-8")

    events = d.get("events", [])
    log(f"[espn] {len(events)} kamp(er) i svaret for {day}.")
    out = []
    problems = []  # ferdigspilte kamper som ikke kunne tolkes -- se EspnDataError under
    for e in events:
        comp = e["competitions"][0]
        utc_dt = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        date = utc_dt.astimezone(OSLO).strftime("%Y-%m-%d")
        completed = comp["status"]["type"]["completed"]
        home = away = hg = ag = None
        winner_home = winner_away = False
        for c in comp["competitors"]:
            # ID-en har kommet både som str og int fra ESPN avhengig av
            # endepunkt -- normaliser til str, ellers stryker oppslaget
            # stille (Ingen -> hele kampen droppes lenger ned).
            raw_id = c.get("team", {}).get("id")
            name = TEAM_ID_TO_NAME.get(str(raw_id)) if raw_id is not None else None
            if name is None:
                msg = f"ukjent lag-id {raw_id!r} ({type(raw_id).__name__}) i {e.get('name')} ({date})"
                log(f"[espn]   {msg}, hopper over laget")
                if completed:
                    problems.append(msg)
                continue
            score = c.get("score")
            if isinstance(score, dict):
                v = score.get("value")
                if v is None and score.get("displayValue") not in (None, ""):
                    v = score["displayValue"]  # scoreboard-endepunktet ser ut til å mangle "value", bare "displayValue"
            elif isinstance(score, (int, float, str)):
                v = score
            else:
                v = None
            if v is not None:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    v = None
            if completed and v is None:
                log(f"[espn]   rått score-felt for lag-id {raw_id} i {e.get('name')}: {score!r}")
            if c["homeAway"] == "home":
                home, hg, winner_home = name, v, bool(c.get("winner"))
            else:
                away, ag, winner_away = name, v, bool(c.get("winner"))
        if not (home and away):
            msg = f"{e.get('name')} ({date}): mangler ett eller begge lag (hjemme={home!r} borte={away!r})"
            log(f"[espn]   {msg}, hopper over hele kampen")
            if completed:
                problems.append(msg)
            continue
        log(f"[espn]   {home}-{away} ({date}): completed={completed} hg={hg!r} ag={ag!r}")
        if completed and (hg is None or ag is None):
            problems.append(f"{home}-{away} ({date}): markert ferdigspilt (completed=True) men resultatet kunne ikke leses (hg={hg!r} ag={ag!r})")
        if completed and hg is not None and ag is not None:
            # Selvmotsigende data sett i praksis: 0-0 men en "winner" merket.
            # Slikt forkastes her (ikke None -> spilt, men markert usikkert)
            # og overlates til ffksupporter.net i update_data.py.
            suspect = (hg == 0 and ag == 0) and (winner_home or winner_away)
            out.append({"home": home, "away": away, "date": date,
                        "hg": int(hg), "ag": int(ag), "suspect": suspect})
        else:
            out.append({"home": home, "away": away, "date": date, "hg": None, "ag": None, "suspect": False})

    if problems:
        _logg("feil", f"{len(problems)} ferdigspilt(e) kamp(er) kunne ikke tolkes")
        raise EspnDataError(
            f"{len(problems)} ferdigspilt(e) kamp(er) fra ESPN kunne ikke tolkes riktig:\n" +
            "\n".join(f"  - {p}" for p in problems)
        )
    _logg("ok", f"scoreboard {day}", kamper=len(out))
    return out


if __name__ == "__main__":
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = fetch_all(cache_dir=cache, log=lambda s: print(s, file=sys.stderr))
    played = sum(1 for r in rows if r["hg"] is not None)
    suspect = [r for r in rows if r.get("suspect")]
    print(f"Kamper i vinduet: {len(rows)} ({played} spilt)", file=sys.stderr)
    if suspect:
        print(f"MISTENKELIGE ({len(suspect)}): 0-0 men med vinner merket:", file=sys.stderr)
        for r in suspect:
            print(" ", r, file=sys.stderr)
