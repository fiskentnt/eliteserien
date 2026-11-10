#!/usr/bin/env python3
"""Porten for runder av utløsninger (8.10.2026): bare den siste kjøringen i en
runde gjør jobben, de andre ender grønne uten å gjøre noe.

Hvorfor: GitHub holder bare én VENTENDE kjøring per concurrency-gruppe.
Kommer en tredje mens én kjører og én venter, avbrytes den som venter, også
med cancel-in-progress: false, og hver avbrutt kjøring ga e-posten «Run
failed» (78 av 238 kjøringer av ELO-testen siste døgn 7.10.; den ble fjernet
10.11.2026). Grunnlag har det samme rundt pusher.

  LIGAER='["eliteserien","obos"]' python3 scripts/puljeport.py grunnlag
      grunnlag.yml, etter grunnlag_port.py. Tar bort en liga som en nyere
      grunnlagskjøring alt regner (den har jobben "regn (<liga>)"). Venter
      først til de nyere kjøringenes port er ferdig. Manuelt: alle.

Skriver ligaer=<json> til GITHUB_OUTPUT, og i loggen hvorfor. Svarer ikke GitHub, gjør kjøringen
jobben, som før: det er tryggere å regne én gang for mye enn å la være.
"""
import json
import os
import sys
import time
import urllib.request

VENT = 20          # sekunder: la de andre i runden rekke å starte sin kjøring
MAKS_VENT = 90     # sekunder: lengst vi venter på de nyere kjøringenes port


def api(sti):
    """GET mot GitHub-API-et, som JSON. Kaster ved feil."""
    req = urllib.request.Request(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{sti}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=20) as svar:
        return json.loads(svar.read().decode("utf-8"))


def kjoringer(workflow, n):
    return api(f"actions/workflows/{workflow}/runs?per_page={n}")["workflow_runs"]


def grunnlag(run_id, hendelse, ligaer, sov=time.sleep, klokke=time.monotonic):
    """(ligaene som skal regnes, [(liga, nyere kjøring)] som ble tatt bort)."""
    if hendelse == "workflow_dispatch" or not ligaer:
        return ligaer, []
    sov(VENT)
    start = klokke()
    while True:
        nyere = [r for r in kjoringer("grunnlag.yml", 20) if r["id"] > run_id and r.get("conclusion") != "cancelled"]
        jobber = {r["id"]: api(f"actions/runs/{r['id']}/jobs?per_page=20")["jobs"] for r in nyere}
        venter = [i for i, js in jobber.items() if any(j["name"] == "port" and j["status"] != "completed" for j in js)
                  or not js]
        if not venter or klokke() - start > MAKS_VENT:
            break
        sov(5)
    behold, borte = [], []
    for liga in ligaer:
        hvem = sorted(i for i, js in jobber.items()
                      if any(j["name"] == f"regn ({liga})" and j.get("conclusion") not in ("cancelled", "skipped") for j in js))
        if hvem:
            borte.append((liga, hvem[-1]))
        else:
            behold.append(liga)
    return behold, borte


def main():
    modus = sys.argv[1] if len(sys.argv) > 1 else ""
    run_id, hendelse = int(os.environ.get("GITHUB_RUN_ID", "0")), os.environ.get("GITHUB_EVENT_NAME", "")
    ut = os.environ.get("GITHUB_OUTPUT")
    if modus == "grunnlag":
        ligaer = json.loads(os.environ.get("LIGAER") or "[]")
        try:
            behold, borte = grunnlag(run_id, hendelse, ligaer)
            for liga, i in borte:
                print(f"regn ({liga}): hoppet over -- den nyere grunnlagskjøringen #{i} regner den")
        except Exception as e:
            behold = ligaer
            print(f"GitHub svarte ikke ({type(e).__name__}: {e}), så denne regner alle ligaene porten sa")
        print(f"ligaer={json.dumps(behold)}")
        linje = f"ligaer={json.dumps(behold)}"
    else:
        print("Bruk: puljeport.py grunnlag", file=sys.stderr)
        return 2
    if ut:
        with open(ut, "a", encoding="utf-8") as f:
            f.write(linje + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
