#!/usr/bin/env python3
"""Vakt for publiseringen (GitHub Pages), 7.10.2026.

6.10. hang publiseringen av f3fe1df i deploy ("waiting") fra kl. 15:17Z til
den ble avbrutt kl. 22:53Z. Siden viste commiten før i over sju timer, og det
ble oppdaget tilfeldig. Vakten sjekker hvert tiende minutt (etter «Oppdater
kampdata», se .github/workflows/pages-vakt.yml) at alt på main er publisert,
med 30 minutter slingringsmonn for publiseringer som er i gang.

Varselet går samme vei som de andre (planlegger/README.md, «Dødmannsknapp»),
til sjekken tabellkalkulator-pages hos healthchecks.io:
  - alt publisert, eller den eldste upubliserte commiten er under 30 minutter
    gammel: livstegn
  - eldre enn det: /fail, og healthchecks sender e-post med en gang
  - vakten kan ikke avgjøre det (GitHub svarer ikke): ingenting sendes, og
    dødmannsknappen sier fra hvis det varer
Mangler hemmeligheten (HEALTHCHECK_PAGES), skrives bare en ::warning. Vakten
gjør aldri kjøringen rød.

Publisert betyr at commiten er med i den nyeste publiseringen (deployment til
miljøet github-pages) som har status success. Commitene etter den (GitHub
compare mot main) er upubliserte. Alderen regnes fra da den første av dem kom
til main: den eldste pushen (GitHubs aktivitetslogg) med en av dem som nytt
hode. Tiden commiten ble laget, gjelder bare når loggen ikke har den: en
commit laget lokalt en time før pushen, ville ellers gitt varsel med en gang
(7.10.2026).

  GITHUB_TOKEN=... GITHUB_REPOSITORY=eier/repo python3 scripts/pages_vakt.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

GRENSE = timedelta(minutes=30)
MILJO = "github-pages"


def api(sti):
    """GET mot GitHub-API-et, som JSON. Kaster ved feil."""
    req = urllib.request.Request(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{sti}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=20) as svar:
        return json.loads(svar.read().decode("utf-8"))


def ping(url):
    """Livstegn (eller /fail) til healthchecks. Feiler det, sies det bare."""
    try:
        urllib.request.urlopen(url, timeout=10).read()
        return True
    except Exception as e:
        print(f"  pinget til healthchecks feilet: {type(e).__name__}")
        return False


def _tid(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _klokke(t):
    from zoneinfo import ZoneInfo
    t = t.astimezone(ZoneInfo("Europe/Oslo"))
    return f"{t.day}.{t.month}. kl. {t.strftime('%H.%M')}"


def siste_publiserte():
    """(sha, tid) for den nyeste publiseringen med status success."""
    for d in api(f"deployments?environment={MILJO}&per_page=30"):
        for s in api(f"deployments/{d['id']}/statuses?per_page=30"):
            if s.get("state") == "success":
                return d["sha"], _tid(s["created_at"])
    raise RuntimeError("fant ingen vellykket publisering blant de 30 siste")


def upubliserte(sha):
    """Commitene på main som ikke er med i sha, eldst først: [(sha, tid, tittel)]."""
    d = api(f"compare/{sha}...main")
    return sorted(((c["sha"], _tid(c["commit"]["committer"]["date"]), c["commit"]["message"].split("\n")[0])
                   for c in d.get("commits") or []), key=lambda c: c[1])


def ankomst(upub):
    """Da den første av de upubliserte commitene kom til main: den eldste
    pushen med en av dem som nytt hode, eller None (ikke i loggen)."""
    shaer = {c[0] for c in upub}
    tider = [_tid(a["timestamp"]) for a in api("activity?ref=refs/heads/main&activity_type=push&per_page=100")
             if a.get("after") in shaer]
    return min(tider) if tider else None


def vurder(upub, publisert, naa, grense=GRENSE, kom=None):
    """("ok" | "henger", tekst). kom: da den første upubliserte commiten kom
    til main (ankomst); uten den tiden commiten ble laget."""
    if not upub:
        return "ok", f"alt på main er publisert ({publisert[:7]})"
    sha, tid, tittel = upub[0]
    tid = kom or tid
    alder = naa - tid
    minutter = int(alder.total_seconds() // 60)
    if alder <= grense:
        return "ok", (f"{len(upub)} commit(er) venter på publisering, den eldste ({sha[:7]}) kom til main for {minutter} min siden")
    return "henger", (f"Publiseringen henger: {sha[:7]} ({tittel[:60]}) kom til main {_klokke(tid)} og er ikke publisert etter "
                      f"{minutter} min, og {len(upub)} commit(er) venter. Siden viser {publisert[:7]}.")


def main():
    naa = datetime.now(timezone.utc)
    hc = os.environ.get("HC_URL", "").strip()
    try:
        publisert, _ = siste_publiserte()
        upub = upubliserte(publisert)
        try:
            kom = ankomst(upub) if upub else None
        except Exception as e:
            print(f"  (aktivitetsloggen svarte ikke: {type(e).__name__}; regner fra da commiten ble laget)")
            kom = None
        tilstand, tekst = vurder(upub, publisert, naa, kom=kom)
    except Exception as e:
        # Uten svar fra GitHub vet vi ikke: ingenting sendes, og
        # dødmannsknappen sier fra hvis det varer.
        print(f"Kunne ikke avgjøre om alt er publisert ({type(e).__name__}: {e}) -- sender ingenting.")
        return 0
    print(tekst)
    if tilstand == "henger" and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning title=Publiseringen henger::{tekst}")
    if not hc:
        print("HEALTHCHECK_PAGES er ikke satt -- ingen livstegn og ingen e-post.")
        if os.environ.get("GITHUB_ACTIONS"):
            print("::warning title=Pages-vakt::HEALTHCHECK_PAGES er ikke satt, så vakten kan ikke varsle.")
        return 0
    if ping(hc.rstrip("/") + ("/fail" if tilstand == "henger" else "")):
        print("Varsel sendt til healthchecks." if tilstand == "henger" else "Livstegn sendt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
