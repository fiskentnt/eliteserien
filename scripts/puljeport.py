#!/usr/bin/env python3
"""Porten for runder av utløsninger (8.10.2026): bare den siste kjøringen i en
runde gjør jobben, de andre ender grønne uten å gjøre noe.

Hvorfor: GitHub holder bare én VENTENDE kjøring per concurrency-gruppe.
Kommer en tredje mens én kjører og én venter, avbrytes den som venter, også
med cancel-in-progress: false. Planleggeren starter «Oppdater kampdata»,
«Oppdater odds for kommende kamper» og «Odds nær avspark» samtidig, og hver av
dem som blir ferdig, starter ELO-test: tre starter per runde, den midterste
avbrutt etter noen sekunder (78 av 238 siste døgn 7.10.), og hver avbrutt
kjøring ga e-posten «Run failed». Grunnlag hadde det samme rundt pusher (4).

  python3 scripts/puljeport.py elo
      elo-test.yml, jobben port. Bygger bare når ingen av de tre utløserne
      kjører fortsatt og det ikke finnes en nyere ELO-test-kjøring (den
      bygger da i stedet). Manuelt: bygger alltid.
  LIGAER='["eliteserien","obos"]' python3 scripts/puljeport.py grunnlag
      grunnlag.yml, etter grunnlag_port.py. Tar bort en liga som en nyere
      grunnlagskjøring alt regner (den har jobben "regn (<liga>)"). Venter
      først til de nyere kjøringenes port er ferdig. Manuelt: alle.

Skriver bygg=true|false (elo) eller ligaer=<json> (grunnlag) til
GITHUB_OUTPUT, og i loggen hvorfor. Svarer ikke GitHub, gjør kjøringen
jobben, som før: det er tryggere å regne én gang for mye enn å la være.
"""
import json
import os
import sys
import time
import urllib.request

ELO_UTLOSERE = {"update-data.yml": "Oppdater kampdata",
                "update-odds.yml": "Oppdater odds for kommende kamper",
                "prekick-odds.yml": "Odds nær avspark"}
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


def elo(run_id, hendelse, sov=time.sleep):
    """(bygg, hvorfor)."""
    if hendelse == "workflow_dispatch":
        return True, "bygg=true: manuell kjøring"
    sov(VENT)
    nyere = sorted((r for r in kjoringer("elo-test.yml", 20) if r["id"] > run_id), key=lambda r: r["id"])
    if nyere:
        r = nyere[-1]
        return False, (f"bygg=false: nyere kjøring -- ELO-test #{r['id']} (startet {r['created_at'][11:19]}Z) "
                       f"er nyere og bygger i stedet")
    for wf, navn in ELO_UTLOSERE.items():
        aktive = [r for r in kjoringer(wf, 5) if r["status"] != "completed"]
        if aktive:
            return False, (f"bygg=false: aktiv utløser -- «{navn}» (#{aktive[0]['id']}) kjører fortsatt, og "
                           f"ELO-test-kjøringen den starter når den er ferdig, bygger")
    return True, "bygg=true: ingen nyere ELO-test-kjøring, og ingen av utløserne kjører"


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
    if modus == "elo":
        try:
            bygg, hvorfor = elo(run_id, hendelse)
        except Exception as e:
            bygg, hvorfor = True, f"bygg=true: GitHub svarte ikke ({type(e).__name__}: {e}), så denne bygger"
        print(hvorfor)
        linje = f"bygg={'true' if bygg else 'false'}"
    elif modus == "grunnlag":
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
        print("Bruk: puljeport.py elo|grunnlag", file=sys.stderr)
        return 2
    if ut:
        with open(ut, "a", encoding="utf-8") as f:
            f.write(linje + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
