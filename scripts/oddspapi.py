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


def _load():
    if USAGE_PATH.exists():
        return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    return {"note": "Egen teller for OddsPapi-kall. Kvoten vises ikke i API-svarene. "
                    "/v4/historical-odds er gratis og telles ikke.",
            "monthly_limit": MONTHLY_LIMIT, "months": {}}


def usage(month=None):
    d = _load()
    m = month or datetime.now(timezone.utc).strftime("%Y-%m")
    return d["months"].get(m, {}).get("billable", 0), d.get("monthly_limit", MONTHLY_LIMIT)


def _count(path, billable):
    if not billable:
        return
    d = _load()
    m = datetime.now(timezone.utc).strftime("%Y-%m")
    mon = d["months"].setdefault(m, {"billable": 0, "free": 0, "endpoints": {}})
    mon["billable"] += 1
    mon["endpoints"][path] = mon["endpoints"].get(path, 0) + 1
    mon["last"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    USAGE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def call(path, params=None, key=None, timeout=TIMEOUT):
    """Returnerer (data, feilmelding). Teller kallet hvis endepunktet koster."""
    key = key or os.environ.get("ODDSPAPI_KEY", "").strip()
    if not key:
        return None, "ODDSPAPI_KEY er ikke satt"
    billable = path not in FREE_ENDPOINTS
    if billable:
        used, limit = usage()
        if used >= limit:
            return None, f"stopper: {used} av {limit} tellende kall brukt denne måneden"
    q = dict(params or {})
    q["apiKey"] = key
    url = f"{BASE}{path}?" + urllib.parse.urlencode(q)
    _count(path, billable)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        return None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def unwrap(d):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("data", "items", "results", "response", "fixtures"):
            if isinstance(d.get(k), list):
                return d[k]
    return []
