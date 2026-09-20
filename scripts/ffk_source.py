"""Kilde 1 (fasit): ffksupporter.net.

Henter "Serie"-tabellen fra hvert lags terminliste-side (16 sider, 1 forespørsel
i sekundet, egen User-Agent). Dekker hele sesongens kampoppsett (runde, dato,
lag), med resultat for spilte kamper og "Ikke spilt" for resten. Brukt som
fasit av update_data.py når den har et resultat; ESPN (espn_source.py) fyller
inn friskere resultater når ffksupporter ikke har oppdatert ennå.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

USER_AGENT = "eliteserien-tabell (+https://github.com/fiskentnt/eliteserien)"
BASE_URL = "https://ffksupporter.net/terminliste/2026-eliteserien/{slug}/"
REQUEST_DELAY = 1.0  # sekunder mellom hver forespørsel

# Rekkefølge og slugs som oppgitt av bruker
SLUGS = [
    "bodo-glimt", "viking", "molde", "tromso", "lillestrom", "rosenborg",
    "fredrikstad", "brann", "sarpsborg-08", "kfum", "ham-kam", "valerenga",
    "aalesund", "sandefjord", "kristiansund", "start",
]

# Slug -> visningsnavn slik det brukes i index.html i dag
SLUG_TO_NAME = {
    "bodo-glimt": "Bodø/Glimt",
    "viking": "Viking",
    "molde": "Molde",
    "tromso": "Tromsø",
    "lillestrom": "Lillestrøm",
    "rosenborg": "Rosenborg",
    "fredrikstad": "Fredrikstad",
    "brann": "Brann",
    "sarpsborg-08": "Sarpsborg 08",
    "kfum": "KFUM Oslo",
    "ham-kam": "HamKam",
    "valerenga": "Vålerenga",
    "aalesund": "Aalesund",
    "sandefjord": "Sandefjord",
    "kristiansund": "Kristiansund",
    "start": "Start",
}

class FixtureTableParser(HTMLParser):
    """Plukker ut rader fra <table class="fixture-table"> som står rett under
    <h2 class="fixture-group-title">Serie</h2>. Siden har også en tilsvarende
    tabell under "Cup" (NM Cupen) med samme klassenavn, som må ignoreres."""

    def __init__(self):
        super().__init__()
        self.section = None
        self.in_h2 = False
        self.h2_text = ""
        self.in_table = False
        self.in_tr = False
        self.current_td = None
        self.tds = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h2" and "fixture-group-title" in (attrs.get("class") or ""):
            self.in_h2 = True
            self.h2_text = ""
            return
        if tag == "table" and "fixture-table" in (attrs.get("class") or ""):
            self.in_table = (self.section == "Serie")
            return
        if not self.in_table:
            return
        if tag == "tr":
            self.in_tr = True
            self.tds = []
        elif tag == "td" and self.in_tr:
            self.current_td = {"text": "", "hrefs": [], "datetime": None}
            self.tds.append(self.current_td)
        elif tag == "a" and self.current_td is not None:
            href = attrs.get("href")
            if href:
                self.current_td["hrefs"].append(href)
        elif tag == "time" and self.current_td is not None:
            self.current_td["datetime"] = attrs.get("datetime")

    def handle_endtag(self, tag):
        if tag == "h2" and self.in_h2:
            self.in_h2 = False
            self.section = self.h2_text.strip()
        elif tag == "table" and self.in_table:
            self.in_table = False
        elif tag == "tr" and self.in_tr:
            if len(self.tds) == 4:
                self.rows.append(self.tds)
            self.in_tr = False
            self.current_td = None

    def handle_data(self, data):
        if self.in_h2:
            self.h2_text += data
        if self.current_td is not None:
            self.current_td["text"] += data


def slug_from_href(href):
    return href.strip("/").split("/")[-1]


def parse_page(html, source_slug):
    p = FixtureTableParser()
    p.feed(html)
    out = []
    for tds in p.rows:
        date_td, round_td, teams_td, result_td = tds
        if not date_td["datetime"]:
            continue
        date = date_td["datetime"][:10]
        kickoff = date_td["datetime"][11:16]  # HH:MM, norsk lokaltid (siden datetime-attributtet har norsk UTC-offset)
        round_no = int(round_td["text"].strip())
        if len(teams_td["hrefs"]) != 2:
            raise ValueError(f"Uventet antall lag-lenker i rad ({source_slug}, runde {round_no}): {teams_td['hrefs']}")
        home_slug = slug_from_href(teams_td["hrefs"][0])
        away_slug = slug_from_href(teams_td["hrefs"][1])
        home = SLUG_TO_NAME.get(home_slug)
        away = SLUG_TO_NAME.get(away_slug)
        if not home or not away:
            raise ValueError(f"Ukjent lag-slug ({source_slug}, runde {round_no}): {home_slug} / {away_slug}")
        text = result_td["text"].strip()
        if text.lower() == "ikke spilt" or text == "":
            hg = ag = None
        else:
            m = re.match(r"^(\d+)\s*[–-]\s*(\d+)$", text)
            if not m:
                raise ValueError(f"Klarte ikke tolke resultat ({source_slug}, runde {round_no}): {text!r}")
            hg, ag = int(m.group(1)), int(m.group(2))
        out.append({"date": date, "time": kickoff, "round": round_no, "home": home, "away": away, "hg": hg, "ag": ag})
    return out


class RateLimited(Exception):
    """429/403 fra ffksupporter.net -- ikke prøv igjen med en gang, vent til neste kjøring."""
    def __init__(self, code):
        self.code = code
        super().__init__(f"ffksupporter.net svarte {code}")


def fetch(slug):
    url = BASE_URL.format(slug=slug)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            raise RateLimited(e.code) from e
        raise


def fetch_all(cache_dir=None, log=lambda s: None):
    """Henter og parser alle 16 lagsider. Returnerer deduplisert liste av
    {round, date, home, away, hg, ag} (hg/ag er None for uspilte kamper),
    og en liste advarsler om kamper der de to sidene (hjemme/borte) er uenige
    med hverandre om resultat/dato for samme kamp."""
    all_rows = []
    for i, slug in enumerate(SLUGS):
        cached = cache_dir and (cache_dir / f"{slug}.html").exists()
        if cached:
            html = (cache_dir / f"{slug}.html").read_text(encoding="utf-8")
            log(f"[ffk {i+1}/16] {slug}: fra lokal cache")
        else:
            log(f"[ffk {i+1}/16] Henter {slug} ...")
            html = fetch(slug)
            if cache_dir:
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / f"{slug}.html").write_text(html, encoding="utf-8")
            time.sleep(REQUEST_DELAY)
        all_rows.extend(parse_page(html, slug))

    by_key, warnings = {}, []
    for r in all_rows:
        key = (r["round"], r["home"], r["away"])
        if key not in by_key:
            by_key[key] = r
        elif (by_key[key]["date"], by_key[key]["hg"], by_key[key]["ag"]) != (r["date"], r["hg"], r["ag"]):
            warnings.append((key, by_key[key], r))
    return list(by_key.values()), warnings


if __name__ == "__main__":
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    rows, warnings = fetch_all(cache_dir=cache, log=lambda s: print(s, file=sys.stderr))
    played = sum(1 for r in rows if r["hg"] is not None)
    print(f"Unike kamper: {len(rows)} ({played} spilt)", file=sys.stderr)
    for key, prev, r in warnings:
        print(f"ADVARSEL {key}: {prev} vs {r}", file=sys.stderr)
