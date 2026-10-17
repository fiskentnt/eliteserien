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

  * NY FEIL GIR NYTT VARSEL (17.10.2026, varsle_issues): healthchecks sender
    bare e-post ved overgangen oppe -> nede, så en ny feil mens status alt er
    rød, ga ingen e-post. Hver linje i avviket får en nøkkel (tall som «#», så
    «3.3 timer» og «119 timer» er samme feil), og en ny nøkkel gir en
    GitHub-issue med @fiskentnt (e-post). Samme nøkkel som står, gir ingenting
    nytt. En issue lukkes først når nøkkelen har vært borte i én time, og kommer
    samme nøkkel tilbake innen et døgn, gjenåpnes den i stedet for en ny: en
    status som veksler, skal ikke gi ny e-post hver gang.

Miljø: HC_URL, JOBB_STATUS (job.status), STEG (toJSON(steps)), TESTVARSEL
(true = send et /fail merket TEST og et livstegn rett etter, for å se hva
e-posten inneholder), TESTISSUE (true = lag én test-issue med @fiskentnt),
GH_TOKEN (varsel-issuene; uten den ingen issues) og GitHubs egne for lenken
til kjøringen.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
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
    # «frys» er ikke med (17.10.2026): steget har continue-on-error og utfallet
    # failure i hver kjøring med åpen port («ikke ferdig ennå»), og kan aldri
    # gjøre kjøringen rød. Sto det her, ble en kjøring som var rød av
    # resultatregel eller kildevakt merket «sesongskifte».
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


# Varsel-issuene (17.10.2026).
VARSEL_MERKE = "[varsel "
LUKK_ETTER = timedelta(hours=1)          # nøkkelen borte så lenge: issuen lukkes
GJENAAPNE_INNEN = timedelta(days=1)      # samme nøkkel tilbake innen: gjenåpnes
DELTAKER = "@fiskentnt"                  # nevnt i teksten, så eieren er deltaker og får e-post


def feilnokler(liga, kategori, detalj):
    """{nøkkel: linje} for avviket. Hver linje er én feil; en overskriftslinje
    («1 kamp(er) mangler sluttresultat ...:», «2 kontroller fant avvik: ...»)
    hoppes over når det finnes linjer under. Tall (også med desimaler) blir «#», og bare de første
    150 tegnene teller: feilteksten i status.json er kuttet ved 300 tegn, og et
    nytt antall timer skal ikke flytte kuttet inn i nøkkelen."""
    linjer = [l.strip() for l in str(detalj or "").splitlines() if l.strip()]
    if len(linjer) > 1 and (linjer[0].endswith(":") or re.match(r"\d+ kontroller fant avvik", linjer[0])):
        linjer = linjer[1:]
    ut = {}
    for l in linjer:
        norm = re.sub(r"\d+(?:[.,]\d+)*", "#", l)[:150]     # «3.3» og «119» er begge ett tall
        ut[hashlib.sha1(f"{liga}|{kategori}|{norm}".encode("utf-8")).hexdigest()[:8]] = l
    return ut


def _gh(args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=True).stdout


def _iso(t):
    return datetime.fromisoformat(str(t).replace("Z", "+00:00"))


def resultatdetalj(liga):
    """Konfliktene og resultatene uten kontroll fra results_state.json, når steget
    «resultatregel» er rødt: én linje per kamp, så hver kamp får sin nøkkel."""
    try:
        st = json.loads((LIGAER[liga][1] / "results_state.json").read_text(encoding="utf-8"))
    except Exception:
        return ""
    linjer = [f"konflikt: {c}" for c in st.get("conflicts") or []]
    linjer += [f"uten kontroll: {k.replace('|', '-')} {v[0]}-{v[1]}" for k, v in (st.get("ukontrollert") or {}).items()]
    return "\n".join(linjer)


def varsle_issues(liga, feil, naa, lenke="", kjor=None, log=print):
    """Varsel-issuene for denne kjøringen (se modulteksten). feil: (kategori,
    detalj) eller None når alt er i orden. kjor(args) kjører gh og gir stdout
    (byttes ut i testene). Returnerer en liste over det som ble gjort."""
    kjor = kjor or _gh
    navn = LIGAER[liga][0]
    aktive = feilnokler(liga, feil[0], feil[1]) if feil else {}
    issues = json.loads(kjor(["issue", "list", "--state", "all", "--limit", "200",
                              "--json", "number,title,state,updatedAt,closedAt"]) or "[]")
    mine = {}
    for i in issues:
        t = i.get("title") or ""
        if not (t.startswith(f"{navn}:") and VARSEL_MERKE in t):
            continue
        n = t.rsplit(VARSEL_MERKE, 1)[1].split("]", 1)[0].strip()
        g = mine.get(n)
        if g is None or (i["state"] == "OPEN") > (g["state"] == "OPEN") or \
                ((i["state"] == "OPEN") == (g["state"] == "OPEN") and i["number"] > g["number"]):
            mine[n] = i
    gjort = []
    for n, linje in aktive.items():
        tekst = (f"{DELTAKER}\n\n**{navn}: {feil[0]}**\n\n{linje}\n\nHele avviket:\n```\n{feil[1]}\n```\n\n"
                 f"Sist sett: {naa:%Y-%m-%d %H:%M} UTC\n{lenke}\n\nLukkes når feilen har vært borte i én time. "
                 f"Kommer den tilbake innen et døgn, gjenåpnes denne i stedet for en ny.")
        i = mine.get(n)
        if i and i["state"] == "OPEN":
            kjor(["issue", "edit", str(i["number"]), "--body", tekst])          # sist sett
            gjort.append(("står", n))
        elif i and i.get("closedAt") and naa - _iso(i["closedAt"]) < GJENAAPNE_INNEN:
            kjor(["issue", "reopen", str(i["number"]), "--comment",
                  f"{DELTAKER} Feilen er tilbake ({naa:%d.%m. %H:%M} UTC)."])
            kjor(["issue", "edit", str(i["number"]), "--body", tekst])
            gjort.append(("gjenåpnet", n))
        else:
            # Kolon, ikke tankestrek: «Eliteserien: datafeil: Viking-Fredrikstad ... [varsel 3f2a91c0]».
            kjor(["issue", "create", "--title", f"{navn}: {feil[0]}: {linje[:110]} {VARSEL_MERKE}{n}]", "--body", tekst])
            gjort.append(("ny", n))
    for n, i in mine.items():
        if i["state"] == "OPEN" and n not in aktive and naa - _iso(i["updatedAt"]) >= LUKK_ETTER:
            kjor(["issue", "close", str(i["number"]), "--comment",
                  f"Feilen har vært borte i over én time (sist sett {_iso(i['updatedAt']):%d.%m. %H:%M} UTC). Lukket automatisk."])
            gjort.append(("lukket", n))
    for hva, n in gjort:
        if hva != "står":
            log(f"  varsel-issue {n}: {hva}")
    return gjort


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
    # Varsel-issuene (17.10.2026): bare i Actions med GH_TOKEN. Kan aldri gjøre
    # kjøringen rød.
    if env.get("GITHUB_ACTIONS") and env.get("GH_TOKEN"):
        naa = datetime.now(timezone.utc)
        try:
            if (env.get("TESTISSUE") or "").strip() == "true":
                _gh(["issue", "create", "--title", f"{LIGAER[liga][0]}: TEST av varsel-issue [test]", "--body",
                     f"{DELTAKER} Test av varsel-issuene fra Actions ({naa:%Y-%m-%d %H:%M} UTC). Kommer denne som "
                     f"e-post, virker varslingen. Lukk den gjerne.\n{kjoringslenke(env)}"])
                print("Test-issue laget.")
            f2 = feil
            if f2 and f2[0] == "resultat uten kontroll eller i konflikt" and f2[1].startswith("steget"):
                f2 = (f2[0], resultatdetalj(liga) or f2[1])
            varsle_issues(liga, f2, naa, lenke=kjoringslenke(env))
        except Exception as e:
            print(f"  varsel-issuene: {type(e).__name__}: {str(e)[:200]} (ingen betydning for kjøringen)")
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
    # Kilder som er ute, men bare gir advarsel (hentelogg.RODE_KILDER,
    # 17.10.2026). Bare i Actions, der jobben er kjent.
    if env.get("GITHUB_WORKFLOW"):
        try:
            import hentelogg
            adv = adv + hentelogg.advarsler(jobb=hentelogg._jobbnavn(env["GITHUB_WORKFLOW"]))
        except Exception:
            pass
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
