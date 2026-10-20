#!/usr/bin/env python3
"""IndexNow (fase 1c, 20.10.2026): melder fra til søkemotorene (Bing og de andre
som bruker IndexNow) om sider som er endret, så de leses på nytt.

Nøkkelen står i en fil i roten, <nøkkel>.txt, med nøkkelen som innhold
(protokollens krav). Kjøres av grunnlag-workflowen etter pushen, med filene i
grunnlag-commiten: en side er <sti>/index.html og blir adressen
https://tabellkalkulator.no/<sti>/ (forsiden: index.html -> /). Andre filer
(data, sitemap.xml) meldes ikke. Feiler kallet, blir det bare en advarsel:
skriptet avslutter alltid med 0.

  python3 scripts/indexnow.py <fil> ...         meld fra
  python3 scripts/indexnow.py --vis <fil> ...   vis hva som ville blitt sendt
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERT = "tabellkalkulator.no"
API = "https://api.indexnow.org/indexnow"


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


def main(argv):
    vis = "--vis" in argv
    filer = [a for a in argv if not a.startswith("--")]
    urls = adresser(filer)
    if not urls:
        print("IndexNow: ingen endrede sider.")
        return 0
    try:
        k = nokkel()
        data = {"host": VERT, "key": k, "keyLocation": f"https://{VERT}/{k}.txt", "urlList": urls}
        if vis:
            print(json.dumps(data, ensure_ascii=False, indent=1))
            return 0
        req = urllib.request.Request(API, data=json.dumps(data).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as svar:
            print(f"IndexNow: {svar.status} for {', '.join(urls)}")
    except Exception as e:  # aldri rødt: bare en advarsel
        print(f"::warning::IndexNow feilet ({e}) for {', '.join(urls)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
