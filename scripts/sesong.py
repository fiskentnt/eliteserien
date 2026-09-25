#!/usr/bin/env python3
"""Sesongskifte etter kalender, med validert terminliste som vilkår.

Reglene, og hva som skiller dem fra den forrige prototypen:

  OPPDAGET   Den offisielle kilden har publisert neste sesongs terminliste.
             Skjer typisk i november eller desember. Endrer ingenting for
             det brukerne ser.

  KLAR       Terminlisten er OPPDAGET og har bestått valideringen under
             (valider()). Endrer fortsatt ingenting for brukerne.

  AKTIV      Siden viser sesongen. Byttet skjer 1. januar, ikke før, og bare
             hvis neste sesong er KLAR. Er den ikke klar 1. januar, står den
             gamle sesongen som aktiv og systemet sier fra -- det er en feil
             som skal fikses, ikke noe som skal gli stille forbi.

  FROSSET    Den avsluttede sesongen fryses ved byttet, slik at
             historikksiden beholder de samme dataene og de samme beregnede
             sannsynlighetene. Se eksperimenter/sesongskifte/frys_sesong.py.

Forskjellen fra forrige prototyp er bevisst: vi venter IKKE på at første
kamp i ny sesong er spilt. Terminlisten er nok. Det gjør at siden er riktig
fra 1. januar, ikke først i april, og at vinteren ikke viser en ferdigspilt
sesong som om den var aktiv.

Den gamle sesongen er aktiv ut kalenderåret selv om den er ferdigspilt i
november. Det er med vilje: gjennom hele desember er det 2026 folk leter
etter, ikke en tom 2027-tabell.

LIGAENE ER UAVHENGIGE. Eliteserien og OBOS har hver sin aktive sesong og hver
sin status. At 2027 er klar i den ene skal aldri blokkere eller framskynde
den andre. All tilstand ligger under ligaer.<liga>, aldri på rota.

Bruk:
    python3 sesong.py <rot> init <liga> <sesong>   (én gang, første gang)
    python3 sesong.py <rot> status
    python3 sesong.py <rot> oppdag <liga> <sesong> <terminliste.json>
    python3 sesong.py <rot> bytt [--dato ÅÅÅÅ-MM-DD] [--utfor]
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from ligaer import ANTALL_KAMPER, ANTALL_LAG, ANTALL_RUNDER, LIGAER

VERSJON = 2


def reg_sti(rot):
    return Path(rot) / "data" / "sesonger.json"


def les(rot):
    p = reg_sti(rot)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("version") != VERSJON:
            raise ValueError(f"sesonger.json har version {d.get('version')}, venter {VERSJON}")
        return d
    return {"version": VERSJON, "ligaer": {},
            "note": ("Autoritativ kilde for hvilken sesong hver liga viser. "
                     "Endres bare av sesong.py. Ligaene er uavhengige.")}


def skriv(rot, d):
    p = reg_sti(rot)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def init(rot, liga, sesong, log=print):
    """Setter den FORSTE aktive sesongen for en liga. Administrativ handling.

    Registeret har ingen mekanisme for dette fra for: oppdag() registrerer
    bare NESTE sesong, og bytt() returnerer tidlig naar aktiv mangler. Den
    forste verdien maa derfor settes en gang, av et menneske.

    Aarstallet oppgis EKSPLISITT. Vi utleder det ikke av kampdataene -- et
    utledet aarstall blir feil nettopp ved et sesongskifte, der dataene
    fortsatt er fjoraarets mens terminlisten er ny. Kampdataene brukes bare
    til aa KONTROLLERE at det oppgitte aarstallet er rimelig.

    Bruker les(), liga_blokk() og skriv() som alt annet. Ingen ny state-fil.
    """
    from ligaer import oppsett
    sesong = str(sesong)
    if not (sesong.isdigit() and len(sesong) == 4):
        log(f"FEIL: {sesong!r} er ikke et årstall.")
        return 2

    d = les(rot)
    blokk = liga_blokk(d, liga)
    if blokk.get("aktiv"):
        log(f"NEKTER: {liga} har allerede aktiv sesong {blokk['aktiv']}. "
            f"init setter bare den første. Et ordinært sesongskifte går "
            f"gjennom 'bytt', som krever validert terminliste og 1. januar.")
        return 1

    # Kontroll mot kampdataene -- kontroll, ikke autoritet.
    try:
        m = json.loads((Path(rot) / oppsett(liga)["data"] / "matches.json")
                       .read_text(encoding="utf-8"))
        aar = sorted({r["date"][:4] for r in m if r.get("date")})
        if aar and sesong not in aar:
            log(f"FEIL: oppgitt sesong {sesong}, men matches.json for {liga} "
                f"inneholder bare {', '.join(aar)}. Sjekk årstallet.")
            return 2
        if aar:
            log(f"  kontroll: matches.json for {liga} har kamper i {', '.join(aar)}")
    except Exception as e:
        log(f"  kunne ikke kontrollere mot matches.json ({type(e).__name__}) "
            f"-- fortsetter, kontrollen er ikke et krav.")

    blokk["aktiv"] = sesong
    blokk["sesonger"].setdefault(sesong, {})["status"] = "aktiv"
    blokk["initiert_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    skriv(rot, d)
    log(f"{liga}: aktiv sesong satt til {sesong}.")
    return 0


def aktiv_sesong(rot, liga, log=lambda s: None):
    """Sesongen kjeden skal kjore, eller None.

    data/sesonger.json er ENESTE autoritet. Den skrives bare av dette
    skriptet og leses ogsaa av frys_sesong.py.

    Det finnes med vilje INGEN reserve. Aa utlede sesongen fra matches.json
    ville vaert aa gjette -- og gjettet blir feil nettopp ved et
    sesongskifte, der dataene fortsatt er fjoraarets mens terminlisten er ny.
    Det er da datovakten trengs mest, og det er da et feil gjett ville slaatt
    den ut eller fatt den til aa skrive fjoraarets datoer inn i den nye
    sesongen.

    Mangler autoriteten, skal kalleren staa over vakten, kjore resten som
    normalt, og la kjoringen feile synlig til slutt."""
    p = reg_sti(rot)
    if not p.exists():
        log(f"INGEN SESONGAUTORITET: {p.relative_to(Path(rot))} finnes ikke. "
            f"Datovakten står over -- den skal ikke gjette.")
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"INGEN SESONGAUTORITET: klarte ikke lese data/sesonger.json "
            f"({type(e).__name__}: {e}). Datovakten står over.")
        return None
    s = d.get("ligaer", {}).get(liga, {}).get("aktiv")
    if not s:
        log(f"INGEN SESONGAUTORITET: data/sesonger.json har ingen aktiv "
            f"sesong for {liga}. Datovakten står over.")
        return None
    log(f"Aktiv sesong for {liga}: {s} (data/sesonger.json)")
    return str(s)


def liga_blokk(d, liga):
    return d["ligaer"].setdefault(liga, {"aktiv": None, "sesonger": {}})


# ---------------------------------------------------------------- validering

def valider(rader, sesong, forrige_lag=None):
    """Er denne terminlisten god nok til å bytte sesong på?

    Returnerer (ok, funn). funn er en liste (alvor, tekst), der alvor er
    "feil" eller "merk". Bare "feil" blokkerer.

    Lagsettet kan IKKE sjekkes mot en fast liste: opprykk og nedrykk bytter
    ut lag hver sesong. Det som sjekkes er at settet er komplett og
    konsistent, og endringene fra forrige sesong rapporteres som "merk" slik
    at de er synlige uten å blokkere.
    """
    funn = []
    if not rader:
        return False, [("feil", "terminlisten er tom")]

    if len(rader) != ANTALL_KAMPER:
        funn.append(("feil", f"{len(rader)} kamper, venter {ANTALL_KAMPER}"))

    nøkler = [(r["home"], r["away"]) for r in rader]
    duplikater = {k for k in nøkler if nøkler.count(k) > 1}
    if duplikater:
        funn.append(("feil", f"{len(duplikater)} lagpar forekommer flere ganger: "
                             f"{sorted(duplikater)[:3]}"))

    lag = sorted({r["home"] for r in rader} | {r["away"] for r in rader})
    if len(lag) != ANTALL_LAG:
        funn.append(("feil", f"{len(lag)} lag, venter {ANTALL_LAG}: {lag}"))
    else:
        for t in lag:
            h = sum(1 for r in rader if r["home"] == t)
            b = sum(1 for r in rader if r["away"] == t)
            if (h, b) != (ANTALL_LAG - 1, ANTALL_LAG - 1):
                funn.append(("feil", f"{t} har {h} hjemme- og {b} bortekamper, "
                                     f"venter {ANTALL_LAG - 1} av hver"))
        mangler = [(a, b) for a in lag for b in lag
                   if a != b and (a, b) not in set(nøkler)]
        if mangler:
            funn.append(("feil", f"{len(mangler)} oppgjør mangler, f.eks. {mangler[:3]}"))

    runder = sorted({r["round"] for r in rader})
    if runder != list(range(1, ANTALL_RUNDER + 1)):
        funn.append(("feil", f"runder er {runder[:5]}... ({len(runder)} stk), "
                             f"venter 1-{ANTALL_RUNDER}"))

    uten_dato = [r for r in rader if not r.get("date")]
    if uten_dato:
        funn.append(("feil", f"{len(uten_dato)} kamper uten dato"))
    feil_år = [r for r in rader if r.get("date") and r["date"][:4] != str(sesong)]
    if feil_år:
        funn.append(("feil", f"{len(feil_år)} kamper er ikke i {sesong}, "
                             f"f.eks. {feil_år[0]['date']}"))

    uten_tid = [r for r in rader if not r.get("time")]
    if uten_tid:
        funn.append(("merk", f"{len(uten_tid)} kamper mangler avspark "
                             f"(vanlig før tv-tidene er satt)"))

    spilt = [r for r in rader if r.get("hg") is not None]
    if spilt:
        funn.append(("merk", f"{len(spilt)} kamper har allerede resultat"))

    if forrige_lag is not None and len(lag) == ANTALL_LAG:
        inn = sorted(set(lag) - set(forrige_lag))
        ut = sorted(set(forrige_lag) - set(lag))
        if inn or ut:
            funn.append(("merk", f"lagendringer mot forrige sesong: inn {inn}, ut {ut}"))
        if len(inn) != len(ut):
            funn.append(("feil", f"{len(inn)} lag inn, men {len(ut)} ut"))

    ok = not any(a == "feil" for a, _ in funn)
    return ok, funn


# ---------------------------------------------------------------- oppdagelse

def oppdag(rot, liga, sesong, rader, log=print):
    """Registrerer en publisert terminliste og validerer den. Endrer ALDRI
    aktiv sesong -- det gjør bare bytt(), og bare fra 1. januar."""
    d = les(rot)
    blokk = liga_blokk(d, liga)
    sesong = str(sesong)

    forrige = blokk.get("aktiv")
    forrige_lag = blokk["sesonger"].get(forrige, {}).get("lag") if forrige else None

    ok, funn = valider(rader, sesong, forrige_lag)
    s = blokk["sesonger"].setdefault(sesong, {})
    s["lag"] = sorted({r["home"] for r in rader} | {r["away"] for r in rader})
    s["kamper"] = len(rader)
    s["status"] = "klar" if ok else "oppdaget"
    s["validering"] = {"ok": ok, "funn": [f"{a}: {t}" for a, t in funn],
                       "sett": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    log(f"{liga}: {sesong} {'KLAR' if ok else 'OPPDAGET (ikke klar)'} "
        f"-- {len(rader)} kamper, {len(s['lag'])} lag")
    for a, t in funn:
        log(f"    {a}: {t}")
    skriv(rot, d)
    return ok


# ------------------------------------------------------------------- byttet

def skal_bytte(blokk, i_dag):
    """(bytt?, neste, begrunnelse) for én liga. Ren funksjon, ingen filer."""
    aktiv = blokk.get("aktiv")
    if aktiv is None:
        return False, None, "ingen aktiv sesong registrert"
    neste = str(int(aktiv) + 1)
    s = blokk["sesonger"].get(neste, {})
    status = s.get("status", "ukjent")

    if i_dag.year <= int(aktiv):
        return False, neste, (f"{aktiv} er aktiv ut kalenderåret "
                              f"(i dag {i_dag.isoformat()}); {neste} er {status}")
    if status != "klar":
        return False, neste, (f"VENTER: det er {i_dag.year}, men {neste} er {status} "
                              f"-- terminlisten er ikke validert, {aktiv} blir stående")
    return True, neste, f"det er {i_dag.year} og {neste} er klar"


def bytt(rot, i_dag, utfor, log=print):
    """Vurderer byttet for HVER liga for seg."""
    d = les(rot)
    endret = False
    for liga in LIGAER:
        blokk = d["ligaer"].get(liga)
        if blokk is None:
            log(f"{liga:12} ingen tilstand registrert")
            continue
        gjør, neste, hvorfor = skal_bytte(blokk, i_dag)
        merke = "BYTTER" if gjør else "står"
        log(f"{liga:12} {blokk['aktiv']} -> {neste}  [{merke}]  {hvorfor}")
        if gjør and utfor:
            blokk["sesonger"].setdefault(blokk["aktiv"], {})["status"] = "frosset"
            blokk["sesonger"][neste]["status"] = "aktiv"
            blokk["aktiv"] = neste
            blokk["byttet_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            endret = True
            log(f"{'':12} utført: {liga} viser nå {neste}, {blokk['sesonger']} ")
    if endret:
        skriv(rot, d)
    return 0


def status(rot, log=print):
    d = les(rot)
    for liga in LIGAER:
        blokk = d["ligaer"].get(liga, {})
        log(f"{liga:12} aktiv: {blokk.get('aktiv')}")
        for s in sorted(blokk.get("sesonger", {})):
            i = blokk["sesonger"][s]
            v = i.get("validering", {})
            log(f"{'':14}{s}: {i.get('status'):9}"
                + (f" {i.get('kamper')} kamper" if i.get("kamper") else "")
                + ("" if v.get("ok", True) else "  VALIDERING FEILET"))
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    rot, cmd = sys.argv[1], sys.argv[2]
    if cmd == "status":
        return status(rot)
    if cmd == "init":
        if len(sys.argv) < 5:
            print("bruk: sesong.py <rot> init <liga> <sesong>", file=sys.stderr)
            return 2
        return init(rot, sys.argv[3], sys.argv[4])
    if cmd == "oppdag":
        liga, sesong, fil = sys.argv[3], sys.argv[4], sys.argv[5]
        rader = json.loads(Path(fil).read_text(encoding="utf-8"))
        return 0 if oppdag(rot, liga, sesong, rader) else 1
    if cmd == "bytt":
        i_dag = date.today()
        if "--dato" in sys.argv:
            i_dag = date.fromisoformat(sys.argv[sys.argv.index("--dato") + 1])
        return bytt(rot, i_dag, "--utfor" in sys.argv)
    print(f"ukjent kommando {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
