#!/usr/bin/env python3
"""IndexNow (fase 1c, 20.10.2026): melder fra til søkemotorene (Bing og de andre
som bruker IndexNow) om sider som er endret, så de leses på nytt.

Nøkkelen står i en fil i roten, <nøkkel>.txt, med nøkkelen som innhold
(protokollens krav). En side er <sti>/index.html og blir adressen
https://tabellkalkulator.no/<sti>/ (forsiden: index.html -> /). elo-test
meldes ikke. Feiler kallet, blir det bare en advarsel: skriptet avslutter
alltid med 0.

BARE NÅR INNHOLDET ER ENDRET (28.10.2026). Før ble alle sidene i hver
grunnlag-commit meldt, opptil 40 ganger i døgnet (800 innmeldinger 25.10.),
også når bare «Oppdatert ... kl.» var nytt. Nå velger grunnlag-workflowen
sidene før commiten (--planlegg): en side meldes når innholdet, uten
tidsfeltene (TIDSFELT), er et annet enn sist den ble meldt. Ingen tidsgrense:
med «høyst én gang per døgn» ventet en endring på neste kjøring, og den kunne
komme dager senere (porten regner bare når inndataene er endret). Simulert
20.-27.10.: 1748 -> 1282 (25.10.: 800 -> 563); på kampdager endrer nesten hver
commit sjansene. Alle sidene vurderes hver gang, så en side endret utenfor
grunnlag meldes i neste grunnlag-commit. Siste innmelding per adresse
(tidspunkt og innholdssum) og antallet per dag står i data/indexnow.json, som
committes med sidene; konflikt i den flettes (scripts/flett_konflikt.py).
Adressene sendes etter pushen (--send).

  python3 scripts/indexnow.py --planlegg <liste>   velg sidene, oppdater data/indexnow.json, skriv lista
  python3 scripts/indexnow.py --send <liste>       meld adressene i lista
  python3 scripts/indexnow.py --vis                vis hva --planlegg ville valgt nå (skriver ingenting)
"""
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
VERT = "tabellkalkulator.no"
API = "https://api.indexnow.org/indexnow"
TILSTAND = ROOT / "data" / "indexnow.json"
OSLO = ZoneInfo("Europe/Oslo")

# Tidsfelt som endres uten at innholdet gjør det: stempelet på lag- og
# spørsmålssidene, på ligasiden (STATISK-OPPDATERT) og på forsiden, og når
# oddsen ble hentet (forklaringen i tabellcellene).
TIDSFELT = [
    re.compile(r'<p class="dato">.*?</p>', re.S),
    re.compile(r'<span class="opps-dato">.*?</span>', re.S),
    re.compile(r"<!-- STATISK-OPPDATERT -->.*?<!-- /STATISK-OPPDATERT -->", re.S),
    re.compile(r"hentet [^:\"<]{0,40}kl\. \d{2}\.\d{2}"),
]


def nokkel(root=ROOT):
    """Nøkkelen fra nøkkelfilen i roten (32 heksadesimale tegn + .txt)."""
    filer = [p for p in root.glob("*.txt") if re.fullmatch(r"[0-9a-f]{32}", p.stem)]
    if len(filer) != 1:
        raise RuntimeError(f"fant {len(filer)} nøkkelfiler i roten, ventet én")
    k = filer[0].read_text(encoding="utf-8").strip()
    if k != filer[0].stem:
        raise RuntimeError("nøkkelfilen inneholder ikke sin egen nøkkel")
    return k


def adresser(filer):
    """Sidene blant filene, som adresser, uten dubletter. elo-test meldes ikke."""
    ut = []
    for f in filer:
        f = f.strip()
        if not f.endswith("index.html") or f.startswith("elo-test/"):
            continue
        sti = f[: -len("index.html")]
        a = f"https://{VERT}/{sti}"
        if a not in ut:
            ut.append(a)
    return ut


def sider(root=ROOT):
    """Alle sidene som meldes: forsiden og alt under eliteserien/ og obos/."""
    filer = [root / "index.html", *root.glob("eliteserien/**/index.html"), *root.glob("obos/**/index.html")]
    return sorted(str(f.relative_to(root)) for f in filer if f.is_file())


def innholdssum(tekst):
    """sha256 av siden uten tidsfeltene."""
    for m in TIDSFELT:
        tekst = m.sub("", tekst)
    return hashlib.sha256(tekst.encode("utf-8")).hexdigest()


def les_tilstand(sti=TILSTAND):
    if sti.exists():
        return json.loads(sti.read_text(encoding="utf-8"))
    return {"note": "IndexNow: siste innmelding per adresse (UTC) med innholdssummen, og antall per dag (norsk dato). "
                    "Skrives av scripts/indexnow.py --planlegg.", "adresser": {}, "dager": {}}


def velg(tilstand, summer, naa):
    """Adressene som skal meldes nå: innholdet er endret siden sist de ble meldt.
    Oppdaterer tilstanden (tidspunkt, sum og antallet for dagen) for dem.
    summer: {adresse: innholdssum}."""
    ut = []
    for a, s in summer.items():
        sist = tilstand["adresser"].get(a)
        if sist and sist.get("hash") == s:
            continue
        ut.append(a)
        tilstand["adresser"][a] = {"meldt": naa.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "hash": s}
    if ut:
        dag = naa.astimezone(OSLO).date().isoformat()
        tilstand["dager"][dag] = tilstand["dager"].get(dag, 0) + len(ut)
    return ut


def summer_fra_disk(root=ROOT):
    return {adresser([f])[0]: innholdssum((root / f).read_text(encoding="utf-8")) for f in sider(root)}


def send(urls):
    if not urls:
        print("IndexNow: ingen sider å melde (ingen endret innhold siden sist meldt).")
        return 0
    try:
        k = nokkel()
        data = {"host": VERT, "key": k, "keyLocation": f"https://{VERT}/{k}.txt", "urlList": urls}
        req = urllib.request.Request(API, data=json.dumps(data).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as svar:
            print(f"IndexNow: {svar.status} for {len(urls)} sider: {', '.join(urls)}")
    except Exception as e:  # aldri rødt: bare en advarsel
        print(f"::warning::IndexNow feilet ({e}) for {', '.join(urls)}")
    return 0


def main(argv):
    try:
        if "--send" in argv:
            liste = Path(argv[argv.index("--send") + 1])
            return send([l.strip() for l in liste.read_text(encoding="utf-8").splitlines() if l.strip()] if liste.exists() else [])
        naa = datetime.now(timezone.utc)
        tilstand = les_tilstand()
        urls = velg(tilstand, summer_fra_disk(), naa)
        if "--vis" in argv:
            print(f"IndexNow: ville meldt {len(urls)} sider: {', '.join(urls)}")
            return 0
        if "--planlegg" in argv:
            TILSTAND.write_text(json.dumps(tilstand, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            Path(argv[argv.index("--planlegg") + 1]).write_text("".join(u + "\n" for u in urls), encoding="utf-8")
            print(f"IndexNow: {len(urls)} sider skal meldes etter pushen ({tilstand['dager'].get(naa.astimezone(OSLO).date().isoformat(), 0)} i dag).")
            return 0
        print("Bruk: indexnow.py --planlegg <liste> | --send <liste> | --vis", file=sys.stderr)
    except Exception as e:  # aldri rødt: bare en advarsel
        print(f"::warning::IndexNow: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
