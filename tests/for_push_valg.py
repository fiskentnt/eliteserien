#!/usr/bin/env python3
"""Kort eller full kontroll før push (4.10.2026), for tests/for_push.sh.

KORT kontroll (failsafe, kontroll.py, kontroll_paneler.py og
regression.js --bare del) bare når BEGGE gjelder:
  * full for_push var grønn på samme kode før rebasen: commiten den var grønn
    på er lagret (.git/for-push-gronn, skrevet av for_push.sh), og alt som er
    endret siden den, kom fra origin
  * alle filer origin endret, står på listen over genererte filer under
Alt annet gir FULL for_push: matches.json, fixtures.json, en fil som ikke
står på listen, en ukjent fil, endringer som ikke er committet, ingen lagret
grønn kjøring, eller HEAD som ikke er rebasert på origin/main.

Listen er eksplisitt: hele stier, og tre mapper for logger og tellere. Ingen
mønstre som *.json.

Skriver ut commiten full for_push sist var grønn på, commitene fra origin,
filene de endret, og hvorfor det ble kort eller full. Siste linje er
VALG=kort eller VALG=full.
"""
import json
import subprocess
import sys

# Filer automatjobbene lager av siden og dataene, og som testene ikke bygger på.
GENERERTE = {
    "eliteserien/data/grunnlag.json", "obos/data/grunnlag.json", "elo-test/emodell/grunnlag.json",
    "eliteserien/data/lastmatch.json", "obos/data/lastmatch.json", "elo-test/emodell/lastmatch.json",
    "eliteserien/data/keymatch.json", "obos/data/keymatch.json", "elo-test/emodell/keymatch.json",
    # Panelfilene på testsiden (elo-test.yml).
    "elo-test/emodell/prekick.json", "elo-test/emodell/accuracy.json", "elo-test/emodell/paneler_grunnlag.json",
}
GENERERTE_MAPPER = ("data/hentelogg/", "data/highlightly-bruk/", "data/oddspapi-bruk/")


def generert(sti):
    return sti in GENERERTE or any(sti.startswith(m) for m in GENERERTE_MAPPER)


def beslutt(har_gronn, ren, rebasert, endret_siden, fra_origin):
    """(valg, grunn). endret_siden: filer endret fra den grønne commiten til
    HEAD; fra_origin: filer origin endret siden den grønne kjøringen."""
    if not har_gronn:
        return "full", "ingen grønn full for_push er lagret for denne koden"
    if not ren:
        return "full", "det finnes endringer som ikke er committet"
    if not rebasert:
        return "full", "HEAD er ikke rebasert på origin/main"
    egne = sorted(set(endret_siden) - set(fra_origin))
    if egne:
        return "full", "endret siden den grønne kjøringen, ikke fra origin: " + ", ".join(egne[:8])
    andre = sorted(f for f in fra_origin if not generert(f))
    if andre:
        return "full", "origin endret filer som ikke står på listen over genererte: " + ", ".join(andre[:8])
    if not fra_origin:
        return "kort", "ingenting er endret siden den grønne kjøringen"
    return "kort", "origin endret bare genererte filer, og koden er den samme som i den grønne kjøringen"


def git(*a):
    # core.quotepath=off: filnavn med æøå ("Odds_nær_avspark") kommer som de
    # er, ikke i anførselstegn med oktale koder, så listen kjenner dem igjen.
    return subprocess.run(["git", "-c", "core.quotepath=off", *a], capture_output=True, text=True).stdout.strip()


def main():
    status_fil = git("rev-parse", "--git-dir") + "/for-push-gronn"
    try:
        st = json.loads(open(status_fil, encoding="utf-8").read())
        gronn = st["commit"]
        har_gronn = subprocess.run(["git", "cat-file", "-e", gronn + "^{commit}"]).returncode == 0
    except Exception:
        st, gronn, har_gronn = {}, None, False
    ren = git("status", "--porcelain", "--untracked-files=no") == ""
    rebasert = subprocess.run(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"]).returncode == 0
    endret_siden, fra_origin, commits = [], [], ""
    if har_gronn:
        base = git("merge-base", gronn, "origin/main")
        endret_siden = [f for f in git("diff", "--name-only", gronn, "HEAD").splitlines() if f]
        fra_origin = [f for f in git("diff", "--name-only", base, "origin/main").splitlines() if f]
        commits = git("log", "--oneline", f"{base}..origin/main")
    valg, grunn = beslutt(har_gronn, ren, rebasert, endret_siden, fra_origin)

    print("Kort eller full kontroll før push:")
    if har_gronn:
        print(f"  full for_push sist grønn på: {git('log', '-1', '--format=%h %s', gronn)[:110]} ({st.get('tid', '?')})")
        print("  commitene fra origin siden da: " + ("\n    " + commits.replace("\n", "\n    ") if commits else "ingen"))
        if fra_origin:
            print("  filene de endret:")
            for f in fra_origin:
                print(f"    {'generert ' if generert(f) else 'IKKE PÅ LISTEN '} {f}")
    else:
        print("  ingen grønn full for_push er lagret")
    print(f"  valg: {valg.upper()} -- {grunn}")
    print(f"VALG={valg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
