#!/usr/bin/env python3
"""Felles klient for OddsPapi, med egen kallteller.

Kvoten (250 kall i måneden på gratisnivået) vises IKKE i svarene fra API-et:
verken /v4/account eller svarhodene inneholder noen teller. Derfor teller vi
selv, i data/oddspapi_usage.json, per måned og endepunkt.

/v4/historical-odds er gratis og teller ikke (dokumentert av OddsPapi, og
derfor merket billable=False her). Alt annet teller 1 per kall.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
USAGE_PATH = ROOT / "data" / "oddspapi_usage.json"
BASE = "https://api.oddspapi.io"
# Cloudflare foran API-et avviser Python-urllib sin standardsignatur (feil 1010).
HEADERS = {
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
}
FREE_ENDPOINTS = {"/v4/historical-odds"}
TIMEOUT = 45
MONTHLY_LIMIT = 250

# VAARE EGNE SIKKERHETSGRENSER, strengere enn kvoten.
#
# Telleren her er VAAR egen, ikke en autoritativ kvote fra OddsPapi -- API-et
# oppgir ingen. Tallet skal derfor leses som et MINIMUM: faktisk forbruk kan
# vaere hoyere, for eksempel hvis en kjoring dode etter at forespoerselen gikk
# ut men for filen ble skrevet. Derfor stopper vi godt for 250.
MAANEDSTAK = 200

# Dagstak. Maalt paa tvers av ALLE workflows og begge ligaer, etter at de
# offisielle gratiskildene ble hovedkilde for OBOS-resultatene:
#
#   /v4/historical-odds  GRATIS -- selve oddsen teller ikke
#   prekick_odds         /v4/fixtures, 24 t cache per liga      2/dag
#   obos_results         /v4/fixtures, 20 t cache               1/dag
#   obos_results         /v4/scores                             0 (gratis kilder)
#   obos_upcoming_odds   fixtures 30 t + markets permanent      0/dag
#   elite_closing_odds   fixtures + markets, cachet            <=1/dag
#   odds_compare         cachet, cron to ganger i doegnet      <=1/dag
#   odds-drift, elite-check  ingen cron -- bare manuelt         0
#
#   vanlig dag                        ~4
#   full runde i begge ligaer         ~5-6 (kampantall rorer ikke cachene)
#   alle cacher kalde og begge
#   gratiskilder nede for 8 kamper    ~20
#
# 12 ligger godt over normal drift, men under det katastrofale tilfellet --
# og det er meningen: et tak skal stoppe noe som loper lopsk, ikke romme
# verste tenkelige dag. Blir en dag kappet, venter arbeidet til i morgen.
#
# Maanedstaket er likevel den bindende grensen: 12 x 30 = 360, godt over 200.
# Normal drift er ~4/dag = ~120 i maaneden, saa det er 80 i margin.
DAGSTAK = 12

# Hver kjoring skriver SIN EGEN fil. To jobber som er i luften samtidig rorer
# dermed aldri samme sti, og ingen oppdatering gaar tapt i en rebase. Summen
# for maaneden er summen over filene. Den gamle samlefilen beholdes som
# historikk for september, men skrives ikke lenger.
# ODDSPAPI_BRUK_KATALOG finnes for testene, av samme grunn som
# HENTELOGG_KATALOG: failsafe-suiten kjorer de ekte skriptene i EGNE
# PROSESSER, og en subprosess ser ikke at testen har satt BRUK_KATALOG i sin
# egen. Uten den telte en testkjoring fakturerbare kall som aldri skjedde.
# Produksjonen setter den ikke.
BRUK_KATALOG = Path(os.environ.get("ODDSPAPI_BRUK_KATALOG")
                    or ROOT / "data" / "oddspapi-bruk")


def _kjoring_id():
    """Unik per kjoring. I Actions er run_id + forsok unikt; lokalt bruker vi
    tidspunkt og prosess-id."""
    rid = os.environ.get("GITHUB_RUN_ID")
    if rid:
        return f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f"lokal-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{os.getpid()}"


def _bruk_fil(month=None):
    m = month or datetime.now(timezone.utc).strftime("%Y-%m")
    return BRUK_KATALOG / m / f"{_kjoring_id()}.json"


def _les_alle(month=None):
    """Alle bruksfilene for maaneden, som liste av dict."""
    m = month or datetime.now(timezone.utc).strftime("%Y-%m")
    katalog = BRUK_KATALOG / m
    ut = []
    if katalog.exists():
        for f in sorted(katalog.glob("*.json")):
            try:
                ut.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
    return ut


def dagsbruk(dag=None):
    """Tellende kall i dag, summert over alle kjoringers filer."""
    dag = dag or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(d.get("dager", {}).get(dag, 0) for d in _les_alle())


def budsjett_stopp():
    """(stopp?, begrunnelse) -- kalles FOR ethvert tellende kall."""
    brukt, _ = usage()
    if brukt >= MAANEDSTAK:
        return True, (f"maanedstaket er naadd: {brukt} av maks {MAANEDSTAK} "
                      f"(kvoten er {MONTHLY_LIMIT}, vi stopper for) -- "
                      f"bruker bare gratiskilder resten av maaneden")
    i_dag = dagsbruk()
    if i_dag >= DAGSTAK:
        return True, (f"dagstaket er naadd: {i_dag} av maks {DAGSTAK} kall i dag "
                      f"-- venter til i morgen")
    return False, ""


def _load():
    if USAGE_PATH.exists():
        return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    return {"note": "Egen teller for OddsPapi-kall. Kvoten vises ikke i API-svarene. "
                    "/v4/historical-odds er gratis og telles ikke.",
            "monthly_limit": MONTHLY_LIMIT, "months": {}}


def usage(month=None):
    """(tellende kall denne maaneden, kvoten). Summen av den gamle samlefilen
    og alle per-kjoring-filene, slik at historikken fra september blir med."""
    d = _load()
    m = month or datetime.now(timezone.utc).strftime("%Y-%m")
    gammelt = d["months"].get(m, {}).get("billable", 0)
    nytt = sum(x.get("billable", 0) for x in _les_alle(m))
    return gammelt + nytt, d.get("monthly_limit", MONTHLY_LIMIT)


def _count(path, billable):
    """Skriver til DENNE kjoringens egen fil. Kalles FOR forespoerselen gaar
    ut, slik at et kall som sendes men aldri svarer likevel er talt -- vi vil
    heller tro vi har brukt for mye enn for lite."""
    if not billable:
        return
    fil = _bruk_fil()
    d = {}
    if fil.exists():
        try:
            d = json.loads(fil.read_text(encoding="utf-8"))
        except Exception:
            d = {}
    naa = datetime.now(timezone.utc)
    d["billable"] = d.get("billable", 0) + 1
    d.setdefault("endpoints", {})[path] = d.get("endpoints", {}).get(path, 0) + 1
    dag = naa.strftime("%Y-%m-%d")
    d.setdefault("dager", {})[dag] = d.get("dager", {}).get(dag, 0) + 1
    d["last"] = naa.isoformat(timespec="seconds")
    d["kjoring"] = _kjoring_id()
    fil.parent.mkdir(parents=True, exist_ok=True)
    fil.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _logg(path, utfall, melding=""):
    """Logger til hentelogg uten aa kunne velte noe. OddsPapi logges i call(),
    saa alle kallere daekkes uten at noen maa huske det.

    Kilden navngis per ENDEPUNKT (oddspapi-fixtures, oddspapi-markets, ...).
    Ett navn for hele API-et ville blandet et dodt endepunkt sammen med et
    friskt, og da kan ingen se hvilket av dem som er nede.

    Ligaen er "alle": kvoten og nokkelen er felles for begge ligaer, og de
    fleste kallene her er ikke knyttet til en enkelt liga."""
    kilde = "oddspapi-" + (str(path).strip("/").split("/")[-1] or "ukjent")
    try:
        import hentelogg
        hentelogg.logg("alle", kilde, utfall, melding=melding)
    except Exception:
        pass


def call(path, params=None, key=None, timeout=TIMEOUT):
    """Returnerer (data, feilmelding). Teller kallet hvis endepunktet koster."""
    key = key or os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        return None, "ODDSPAPI_KEY er ikke satt"
    billable = path not in FREE_ENDPOINTS
    if billable:
        # Sperren ligger FOR alt som koster. Ingen tellende forespoersel skal
        # kunne gaa ut naar et av takene er naadd.
        stopp, hvorfor = budsjett_stopp()
        if stopp:
            _logg(path, "hoppet", hvorfor)
            return None, f"stopper: {hvorfor}"
    q = dict(params or {})
    q["apiKey"] = key
    url = f"{BASE}{path}?" + urllib.parse.urlencode(q)
    _count(path, billable)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        _logg(path, "ok")
        return d, None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        # 429 er ikke en kilde som er nede: svaret sier selv hvor lenge vi
        # skal vente, og call_retry folger den beskjeden. Tre slike forsok i
        # EN kjoring skal ikke gjore kjoringen rod -- derfor "hoppet".
        # Er retryene oppbrukt, logger call_retry en ekte "feil".
        _logg(path, "hoppet" if e.code == 429 else "feil", f"HTTP {e.code}")
        return None, f"HTTP {e.code}: {body}"
    except Exception as e:
        _logg(path, "feil", type(e).__name__)
        return None, f"{type(e).__name__}: {e}"


def call_retry(path, params=None, key=None, timeout=TIMEOUT, forsok=4):
    """Som call(), men følger serverens egen ventetid ved 429.

    /v4/historical-odds har en kortvarig grense, og svaret sier nøyaktig hvor
    lenge man skal vente ("retryMs"). Vi ventet før en fast pause og prøvde én
    gang til; da ble seks av åtte OBOS-kamper stående uten odds fordi samme
    kjøring nettopp hadde hentet sluttodds fra samme endepunkt. Nå leses
    ventetiden ut av svaret, med et lite påslag.

    Returnerer (data, feilmelding), som call().
    """
    import re
    import time as _time
    siste = None
    for n in range(forsok):
        d, err = call(path, params, key, timeout=timeout)
        if not err or "RATE_LIMITED" not in str(err) and "429" not in str(err):
            return d, err
        siste = err
        m = re.search(r'"retryMs"\s*:\s*(\d+)', str(err))
        vent = (int(m.group(1)) / 1000.0 + 0.4) if m else 5.0
        # Aldri mer enn et halvt minutt: da er det noe annet galt.
        _time.sleep(min(vent, 30))
    # Oppbrukte forsok: NA er det en ekte feil, og den skal telle.
    _logg(path, "feil", f"oppbrukte {forsok} forsøk: {str(siste)[:80]}")
    return None, siste


def unwrap(d):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("data", "items", "results", "response", "fixtures"):
            if isinstance(d.get(k), list):
                return d[k]
    return []
