#!/usr/bin/env python3
"""ETT sted som hindrer at en testkjoring skriver i produksjonsdataene.

HVORFOR DEN FINNES: suitene kaller de EKTE kildene og de ekte skriptene, og
hentelogget, OddsPapi-telleren og fotball.no-cachen har katalogene sine paa
modulnivaa. Uten dette vernet la en vanlig testkjoring igjen loggfiler i
data/hentelogg, og OddsPapi-telleren fikk tre fakturerbare kall som aldri
skjedde -- kvoteregnskapet ble altsaa feil av aa teste.

HVORFOR MILJOVARIABLER, ikke bare modulattributter: failsafe-suiten kjorer
scripts/obos_results.py i en EGEN PROSESS. Aa sette hentelogg.KATALOG i
testens prosess naar ikke inn i subprosessen. Miljovariabler arves.
Modulattributtene settes i tillegg, for modulene kan alt vaere importert naar
vernet slaar til, og da er katalogen alt regnet ut.

EN MEKANISME, ikke to. Her sto det en autouse-fixture for pytest ved siden
av. Repoet bruker ikke pytest -- ingen suite er en pytest-suite -- og en
fixture ingen kjorer er ikke et vern, bare noe som ser ut som ett. Alle
suitene kaller vern() paa forste linje etter sys.path-oppsettet.

Bruk:
    vern()                 # forst i suiten
    ...
    sjekk_urort(check)     # sist, sammenligner sha256 med forsteavtrykket
"""
import contextlib
import hashlib
import os
import tempfile
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent

# De tre stiene en kilde kan skrive til, og miljovariabelen som flytter hver
# av dem. Alle tre maa ha en variabel: uten NFF_CACHE_KATALOG ville en
# subprosess skrevet fotball.no-cachen rett i produksjonsdataene.
MILJO = {
    "hentelogg": "HENTELOGG_KATALOG",
    "oddspapi-bruk": "ODDSPAPI_BRUK_KATALOG",
    "nff-cache": "NFF_CACHE_KATALOG",
}

_FOER = None


def avtrykk():
    """sha256 per fil under de tre stiene, relativt til reporoten.

    git status duger ikke som maalestokk: den ser ikke filer som er
    .gitignore-et, og den ville heller ikke fange en fil som ble endret og
    skrevet tilbake. Dette er innholdet, uavhengig av git."""
    ut = {}
    for navn in MILJO:
        rot = ROT / "data" / navn
        if not rot.exists():
            continue
        for f in sorted(rot.rglob("*")):
            if f.is_file():
                ut[str(f.relative_to(ROT))] = hashlib.sha256(
                    f.read_bytes()).hexdigest()
    return ut


def _sett_modulattributter(kataloger):
    """Modulene kan vaere importert alt, og da er katalogen regnet ut."""
    import importlib
    for modul, felt, navn in (("hentelogg", "KATALOG", "hentelogg"),
                              ("oddspapi", "BRUK_KATALOG", "oddspapi-bruk"),
                              ("nff_source", "CACHE_KATALOG", "nff-cache")):
        try:
            setattr(importlib.import_module(modul), felt, kataloger[navn])
        except Exception:
            pass


def vern():
    """Flytter alt en kilde kan skrive, til en midlertidig rot.

    Tar samtidig forsteavtrykket av produksjonsstiene, slik at
    sjekk_urort() kan sammenligne."""
    global _FOER
    rot = Path(tempfile.mkdtemp(prefix="tabellkalkulator-test-"))
    kataloger = {navn: rot / navn for navn in MILJO}
    for navn, var in MILJO.items():
        os.environ[var] = str(kataloger[navn])
    _sett_modulattributter(kataloger)
    _FOER = avtrykk()
    return kataloger


def sjekk_urort(check):
    """Sist i suiten: produksjonsstiene skal vaere bit for bit uendret.

    Hver suite vokter seg selv. La bare failsafe gjore det, ville en lekkasje
    fra kildetestene vaert usynlig til noen tilfeldigvis kjorte failsafe
    etterpaa."""
    endret = sorted(set(avtrykk().items()) ^ set((_FOER or {}).items()))
    check("testene skriver ikke i data/hentelogg, oddspapi-bruk eller nff-cache",
          not endret, "; ".join(f"{k}: {v[:16]}" for k, v in endret[:6]))


@contextlib.contextmanager
def miljo(**kv):
    """Setter miljovariabler og GJENOPPRETTER dem noyaktig etterpaa.

    Ikke environ.pop(): den sletter en verdi vi ikke satte. Kjores suiten
    inne i en ekte Actions-jobb, finnes GITHUB_RUN_ID fra for, og en pop
    ville fjernet den for resten av prosessen. Her gjenopprettes bade
    verdien og fravaeret av den, og finally gjor det ogsaa naar testen
    kaster."""
    foer = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in foer.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
