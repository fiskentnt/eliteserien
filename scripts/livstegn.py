#!/usr/bin/env python3
"""Livstegn eller varsel til healthchecks.io: siste steg i update-data.yml og
obos-results.yml (12.10.2026).

    python3 scripts/livstegn.py eliteserien|obos

REGELEN: er kjøringen rød, eller har <liga>/data/status.json ok: false, sendes
/fail med en tekst som sier hva som feilet. Ellers sendes et livstegn.

  * /fail gir e-post med en gang. Gjentatte /fail mens sjekken alt er nede gir
    ingen ny e-post, så en feil som står, varsles én gang.
  * Det gjelder også grønne kjøringer, med åpen eller lukket port: et avvik i
    revisjonen holder status.json rød mens kjøringene er grønne. Før sendte en
    grønn kjøring alltid livstegn, og en rød sendte ingenting (e-post først
    etter 60 minutter uten livstegn). 9.10.2026 sto Rosenborg-Start med 7.1. i
    fire timer uten varsel: mellom de røde timekjøringene sendte kjøringene med
    lukket port livstegn hvert tiende minutt (6 røde, 21 grønne).
  * Livstegnet kommer igjen når en kjøring er grønn OG status.json er grønn,
    altså etter en ekte kjøring som har rettet det.
  * SELVE AVVIKET (17.10.2026): /fail har hele feilteksten fra status.json,
    ikke bare første linje. Før sto det «1 avvik mellom matches.json og
    kontrollkilden:» uten hvilken kamp det gjaldt. Advarslene i status.json
    ("advarsler": en kilde mangler et resultat en annen bekrefter, eller en
    kilde har stoppet) gjør ikke rødt, men går med livstegnet som tekst
    (POST til samme adresse) og med /fail.

Skriptet kan aldri gjøre kjøringen rød: mangler hemmeligheten, eller svarer
ikke healthchecks, avsluttes det med 0. Hemmeligheten (HC_URL) skrives aldri ut.

Miljø: HC_URL, JOBB_STATUS (job.status), STEG (toJSON(steps)), TESTVARSEL
(true = send et /fail merket TEST og et livstegn rett etter, for å se hva
e-posten inneholder), og GitHubs egne for lenken til kjøringen.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent
LIGAER = {"eliteserien": ("Eliteserien", ROT / "eliteserien" / "data"),
          "obos": ("OBOS-ligaen", ROT / "obos" / "data")}

# Stegene som kan gjøre kjøringen rød, i den rekkefølgen de skal forklare
# feilen: (steg-id i workflowen, kategori). Datajobben først, så kontrollene.
STEG_KATEGORI = (
    ("oppdater", None),          # update_data.py: kategorien leses av feilteksten
    ("resultater", None),        # obos_results.py
    ("bygg", None),              # obos_build_data.py
    ("revisjon", "revisjon"),
    ("sesongskifte", "sesongskifte"),
    ("frys", "sesongskifte"),
    ("resultatregel", "resultat uten kontroll eller i konflikt"),
    ("kildevakt", "kilde ute"),
)


def kategori_av_tekst(tekst):
    """Hva feilteksten i status.json gjelder."""
    t = (tekst or "").lower()
    if "kontroller fant avvik" in t:            # flere kontroller slo ut i samme kjøring
        return "flere kontroller"
    if "sesongregisteret" in t:                 # data/sesonger.json kan ikke leses: ingenting er skrevet
        return "sesongregister"
    if "uten lagret dato" in t:                 # en ny kamp er ikke bekreftet: ingenting er skrevet
        return "ny kamp ikke bekreftet"
    if "terminlisten eller tabellen" in t:      # OBOS-byggingen skriver begge i én feil
        return "revisjon eller tabellkontroll"
    if "tabellen" in t:
        return "tabellkontroll"
    if "terminlisten" in t or "kalenderfeeden" in t or "revisjon" in t:
        return "revisjon"
    return "datafeil"


def les_status(liga):
    try:
        return json.loads((LIGAER[liga][1] / "status.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def hva_feilet(jobb_status, steg, status):
    """(kategori, detalj) eller None når alt er i orden.

    jobb_status: job.status ('success', 'failure'). steg: {id: {'outcome': ...}}
    fra toJSON(steps). status: innholdet i status.json."""
    feilet = [sid for sid, _ in STEG_KATEGORI if (steg.get(sid) or {}).get("outcome") == "failure"]
    # Hele teksten som detalj (17.10.2026), første linje til kategorien.
    feiltekst = str(status.get("error") or "").strip()
    forste = feiltekst.splitlines()[0] if feiltekst else ""
    status_rod = status.get("ok") is False
    # Bare når JOBBEN er rød: et steg med continue-on-error har outcome
    # 'failure' uten at kjøringen er rød, og da avgjør status.json.
    if jobb_status != "success":
        for sid, kategori in STEG_KATEGORI:
            if sid in feilet:
                if kategori is None:
                    return kategori_av_tekst(forste), feiltekst or f"steget «{sid}» feilet, se kjøringen"
                # Detaljen fra status.json bare når den gjelder samme sak.
                detalj = feiltekst if (status_rod and kategori_av_tekst(forste) == kategori) else ""
                return kategori, detalj or f"steget «{sid}» feilet, se kjøringen"
        return "annet", feiltekst or "et steg feilet, se kjøringen"
    if status_rod:
        return kategori_av_tekst(forste), feiltekst or "status.json har ok: false uten feiltekst"
    return None


def advarsler(status):
    """Advarslene i status.json (17.10.2026): gjør ikke rødt, men står i
    livstegnet og i /fail."""
    return [str(a) for a in status.get("advarsler") or [] if str(a).strip()]


def merknad(tekst):
    """Tekst til en workflow-kommando (::warning::): linjeskift som %0A."""
    return str(tekst).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def kjoringslenke(env=None):
    env = os.environ if env is None else env
    srv, repo, run = (env.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{srv}/{repo}/actions/runs/{run}" if srv and repo and run else ""


def varseltekst(liga, feil, port_aapen=None, env=None, adv=None):
    kategori, detalj = feil
    linjer = [f"{LIGAER[liga][0]}: {kategori}", detalj]
    if port_aapen is not None:
        linjer.append("Kjøringen hentet data." if port_aapen else "Porten var lukket: feilen står fra en tidligere kjøring.")
    if adv:
        linjer.append("Advarsler (ikke rødt):\n" + "\n".join(f"- {a}" for a in adv))
    linjer.append(kjoringslenke(env))
    return "\n".join(l for l in linjer if l)


def livstegntekst(liga, adv, env=None):
    """Teksten som går med livstegnet når status er grønn med advarsler."""
    linjer = [f"{LIGAER[liga][0]}: grønn, {len(adv)} advarsel(er)"] + [f"- {a}" for a in adv]
    linjer.append(kjoringslenke(env))
    return "\n".join(l for l in linjer if l)


def send(url, tekst=None):
    """GET (livstegn) eller POST med teksten. Sier fra om det feiler, kaster aldri."""
    try:
        req = urllib.request.Request(url, data=tekst.encode("utf-8") if tekst is not None else None,
                                     headers={"User-Agent": "tabellkalkulator-livstegn"})
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print(f"  pinget til healthchecks feilet: {type(e).__name__} (ingen betydning for kjøringen)")
        return False


def main(argv=None, env=None):
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    liga = argv[0] if argv else "eliteserien"
    if liga not in LIGAER:
        print(f"ukjent liga: {liga}")
        return 0
    hc = (env.get("HC_URL") or "").strip().rstrip("/")
    jobb = (env.get("JOBB_STATUS") or "success").strip()
    try:
        steg = json.loads(env.get("STEG") or "{}")
    except ValueError:
        steg = {}
    port = (steg.get("gate") or {}).get("outputs", {}).get("should_fetch")
    port_aapen = None if port is None else port == "true"
    if jobb == "cancelled":
        print("Kjøringen ble avbrutt -- verken livstegn eller varsel.")
        return 0
    status = les_status(liga)
    feil = hva_feilet(jobb, steg, status)
    if not hc:
        print("Hemmeligheten for healthchecks er ikke satt -- ingen livstegn og ingen e-post.")
        if feil:
            print(f"::warning title={LIGAER[liga][0]}: {feil[0]}::{merknad(feil[1])}")
        return 0
    if (env.get("TESTVARSEL") or "").strip() == "true":
        tekst = "TEST av varslingen, ingen feil.\n" + varseltekst(liga, ("tabellkontroll", "eksempel på feiltekst"), port_aapen, env)
        print("Testvarsel: /fail " + ("sendt" if send(hc + "/fail", tekst) else "IKKE sendt") + ", så et livstegn.")
        print("Livstegn sendt." if send(hc) else "Livstegnet ble ikke sendt.")
        return 0
    adv = advarsler(status)
    if feil:
        tekst = varseltekst(liga, feil, port_aapen, env, adv)
        tittel = f"{LIGAER[liga][0]}: {feil[0]}"
        print(f"::{'error' if jobb != 'success' else 'warning'} title={tittel}::{merknad(feil[1])}")
        print("/fail sendt til healthchecks: " + tekst.replace("\n", " | ") if send(hc + "/fail", tekst)
              else "/fail ble ikke sendt.")
        return 0
    if adv:
        tekst = livstegntekst(liga, adv, env)
        print(f"::notice title={LIGAER[liga][0]}: {len(adv)} advarsel(er)::{merknad(chr(10).join(adv))}")
        print("Livstegn sendt med advarslene: " + tekst.replace("\n", " | ") if send(hc, tekst)
              else "Livstegnet ble ikke sendt.")
        return 0
    print("Livstegn sendt." if send(hc) else "Livstegnet ble ikke sendt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
