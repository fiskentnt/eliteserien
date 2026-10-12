#!/usr/bin/env python3
"""Avgjør om en tung kjøring (pip install, scraping, tellende API-kall) skal
kjøre i det hele tatt. Brukes av update-data.yml (Eliteserien) og
obos-results.yml (OBOS, der hvert kall mot OddsPapi teller mot en kvote på
250 i måneden). Leser bare data/fixtures.json fra den allerede
sjekket-ut repoen (ingen nettverkskall, ingen avhengigheter utover
standardbiblioteket) — kjøres som eget, raskt steg FØR pip install, slik at
de aller fleste av døgnets 96 kvarter-kjøringer kan avslutte umiddelbart.

Kjører videre hvis:
  - en kamp startet for over 105 minutter siden uten registrert resultat, og
    det er under 6 timer siden avspark (normal, hvert-kvarter-kadens), ELLER
  - alle ventende kamper er over 6 timer gamle, men vi er i den første
    kvarter-slotten etter en time (fanger dem opp uten å hamre hvert kvarter
    på en kamp som bare henger, se update_data.py sin log), ELLER
  - klokka er rundt 06 norsk tid (den daglige football-data.co.uk-sjekken,
    se fetch_odds_history.py — den trenger et vertskap selv på stille dager
    uten kamper), ELLER
  - FORCE_FETCH=true (manuell workflow_dispatch skal alltid kjøre), ELLER
  - status.json har ok: false, og det er minst 55 minutter siden siste sjekk
    (12.10.2026). Da er kjøringen et NYTT FORSØK UTEN TELLENDE KALL
    (uten_tellende=true, og UTEN_TELLENDE=true til resten av jobben): bare
    gratiskildene brukes. Uten dette åpnet porten først ved neste kamp eller
    etter 20 timer, og en feil kunne stå i et døgn i en landskampspause.
    Tiden regnes fra siste sjekk, ikke fra klokkeslettet: GitHub forsinker
    planlagte kjøringer, så et minuttvindu treffer tilfeldig.
  - tabellkontrollen venter på en ny sjekk etter en fersk kamp (feltet
    "venter" i audit_tabell.json, 12.10.2026, se tabellkontroll.py). Da åpner
    porten i HVER kjøring til tabellen på ligasiden stemmer eller fristen er
    ute, også uten tellende kall.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
OSLO = ZoneInfo("Europe/Oslo")

# Ligamappen velges av argumentet, med Eliteserien som standard slik at
# eksisterende kall uten argument oppfører seg som før.
LIGAER = {"eliteserien": ROOT / "eliteserien", "obos": ROOT / "obos"}

# Daglig vedlikehold (football-data.co.uk, revisjonen mot kontrollkilden)
# styres av NAAR DET SIST GIKK BRA, ikke av klokkeslettet.
#
# Den gamle regelen var "time 06, minutt under 10". Den har aldri slaatt til:
# GitHub sine planlagte kjoringer i 06-timen landet paa minutt 33-43 hver
# eneste dag 21.-24. september, og falt dermed utenfor vinduet. Med en
# ekstern utloser hvert tiende minutt blir et smalt klokkeslettvindu enda mer
# tilfeldig -- det avhenger av at en kjoering treffer akkurat da.
DAGLIG_TIMER = 20

# Etter et MISLYKKET forsok maa det gaa minst saa lenge for vi proever igjen.
# Uten denne ville den eksterne utloseren proevd hvert tiende minutt saa
# lenge feilen varer, og brent baade kjoretid og eventuelle API-kall.
DAGLIG_SPERRE_TIMER = 1


def daglig_sti(liga):
    return LIGAER[liga] / "data" / "daglig_state.json"


def les_daglig(liga):
    p = daglig_sti(liga)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tid(x):
    try:
        return datetime.fromisoformat(x) if x else None
    except ValueError:
        return None


def merk_forsok(liga, now):
    """Skrives NAAR porten aapner for daglig vedlikehold, for arbeidet gjores.
    Da teller et forsok som feiler ogsaa, og sperren paa en time gjelder."""
    d = les_daglig(liga)
    d["siste_forsok"] = now.isoformat(timespec="seconds")
    p = daglig_sti(liga)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def merk_ok(liga, now=None):
    """Skrives av update_data.py naar en kjoring er ferdig uten feil."""
    now = now or datetime.now(timezone.utc)
    d = les_daglig(liga)
    d["siste_ok"] = now.isoformat(timespec="seconds")
    p = daglig_sti(liga)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def daglig_forfalt(liga, now):
    """(slipp gjennom?, begrunnelse)"""
    d = les_daglig(liga)
    ok, forsok = _tid(d.get("siste_ok")), _tid(d.get("siste_forsok"))
    if forsok and (now - forsok) < timedelta(hours=DAGLIG_SPERRE_TIMER):
        minutter = (now - forsok).total_seconds() / 60
        return False, (f"daglig vedlikehold forsøkt for {minutter:.0f} min siden, "
                       f"venter minst {DAGLIG_SPERRE_TIMER} time mellom forsøk")
    if ok is None:
        return True, "daglig vedlikehold har aldri kjørt"
    timer = (now - ok).total_seconds() / 3600
    if timer >= DAGLIG_TIMER:
        return True, f"daglig vedlikehold: siste vellykkede kjøring var {timer:.0f} timer siden"
    return False, f"daglig vedlikehold gjort for {timer:.0f} timer siden"


def kickoff_utc(date_str, time_str):
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=OSLO).astimezone(timezone.utc)


def pending_elapsed_minutes(fixtures, now):
    out = []
    for r in fixtures:
        for m in r["matches"]:
            if m["played"] or not m.get("time"):
                continue
            elapsed = (now - kickoff_utc(m["date"], m["time"])).total_seconds() / 60
            if elapsed > 105:
                out.append(elapsed)
    return out


# Nytt forsøk når status.json er rød: tidligst så lenge etter siste sjekk.
ROD_FORSOK_MIN = 55


def _siste_sjekk(liga):
    """Siste tidspunkt vi vet om for en sjekk eller et forsøk: last_checked
    (Eliteserien) eller built_at (OBOS) i status.json, og forrige forsøk på
    grunn av rød status (daglig_state.json, så et forsøk som feiler før
    status.json er skrevet på nytt, også teller)."""
    try:
        st = json.loads((LIGAER[liga] / "data" / "status.json").read_text(encoding="utf-8"))
    except Exception:
        st = {}
    tider = [_tid(st.get(k)) for k in ("last_checked", "built_at")]
    tider.append(_tid(les_daglig(liga).get("siste_rodt_forsok")))
    tider = [x if x.tzinfo else x.replace(tzinfo=timezone.utc) for x in tider if x]
    return st, (max(tider) if tider else None)


def rodt_forsok(liga, now):
    """(nytt forsøk?, begrunnelse). Bare når status.json har ok: false."""
    st, sist = _siste_sjekk(liga)
    if st.get("ok") is not False:
        return False, ""
    if sist is None:
        return True, "status.json er rød (ingen tidligere sjekk registrert): nytt forsøk uten tellende kall"
    minutter = (now - sist).total_seconds() / 60
    if minutter >= ROD_FORSOK_MIN:
        return True, f"status.json er rød, og siste sjekk var for {minutter:.0f} min siden: nytt forsøk uten tellende kall"
    return False, f"status.json er rød, men siste sjekk var for {minutter:.0f} min siden (nytt forsøk etter {ROD_FORSOK_MIN})"


def merk_rodt_forsok(liga, now):
    d = les_daglig(liga)
    d["siste_rodt_forsok"] = now.isoformat(timespec="seconds")
    p = daglig_sti(liga)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# Tabellkontrollen venter på en ny sjekk etter en fersk kamp: så lenge etter
# fristen åpner porten fortsatt, for sjekken som avgjør saken. Feiler de
# kjøringene, tar timesforsøket ved rød status over.
TABELL_VENTER_ETTER_MIN = 60


def tabell_venter(liga, now):
    """(ny sjekk?, begrunnelse). Sant når siste tabellkontroll lot en fersk
    kamp vente (audit_tabell.json, "venter"): tabellen på ligasiden hadde
    ført kampen med et annet resultat, eller manglet den, og resultatet vårt
    er bekreftet utenfor NTF. Kontrollen tømmer feltet selv når tabellen
    stemmer eller fristen er ute."""
    try:
        d = json.loads((LIGAER[liga] / "data" / "audit_tabell.json").read_text(encoding="utf-8"))
    except Exception:
        return False, ""
    venter = d.get("venter") or []
    frister = [x for x in (_tid(v.get("frist")) for v in venter) if x]
    if not venter or not frister:
        return False, ""
    siste = max(x if x.tzinfo else x.replace(tzinfo=timezone.utc) for x in frister)
    if now > siste + timedelta(minutes=TABELL_VENTER_ETTER_MIN):
        return False, ""
    kamper = ", ".join(str(v.get("kamp", "")).replace("|", "-") for v in venter[:4])
    return True, f"tabellkontrollen venter på ny sjekk etter {kamper}: uten tellende kall"


def vurder(now=None, liga="eliteserien"):
    """(kjør?, begrunnelse, uten_tellende). De vanlige reglene først, uendret;
    åpner ingen av dem, og status.json er rød, åpner porten for et nytt forsøk
    uten tellende kall. Likedan når tabellkontrollen venter på en ny sjekk
    etter en fersk kamp (tabell_venter)."""
    now = now or datetime.now(timezone.utc)
    ok, grunn = _vanlig(now, liga)
    if ok:
        return True, grunn, False
    nytt, hvorfor = rodt_forsok(liga, now)
    if nytt:
        merk_rodt_forsok(liga, now)
        return True, hvorfor, True
    venter, vgrunn = tabell_venter(liga, now)
    if venter:
        return True, vgrunn, True
    return False, grunn + (f"; {hvorfor}" if hvorfor else ""), False


def should_fetch(now=None, liga="eliteserien"):
    """(kjør?, begrunnelse), som før. Se vurder() for uten_tellende."""
    ok, grunn, _ = vurder(now, liga)
    return ok, grunn


def _vanlig(now, liga):
    if os.environ.get("FORCE_FETCH") == "true":
        return True, "manuelt trigget (workflow_dispatch uten planlagt=true)"

    path = LIGAER[liga] / "data" / "fixtures.json"
    if not path.exists():
        return True, "data/fixtures.json finnes ikke ennå"
    fixtures = json.loads(path.read_text(encoding="utf-8"))
    pending = pending_elapsed_minutes(fixtures, now)

    if pending and min(pending) <= 360:
        return True, f"{len(pending)} kamp(er) venter på resultat, ferskeste startet {min(pending):.0f} min siden"
    if pending:  # alle over 6 timer -- bare i time-slotten (kvarteret nærmest hel time)
        if now.minute < 10:
            return True, f"{len(pending)} kamp(er) over 6 timer uten resultat ('venter på resultat'), prøver i timeslotten"
        return False, f"{len(pending)} kamp(er) over 6 timer uten resultat, venter til neste timeslott"
    # Resultater publisert uten kontroll (bare ligasiden, etter 24 timer,
    # resultatregel.py): sjekkes på nytt i timeslotten til en uavhengig kilde
    # har bekreftet dem.
    try:
        st = json.loads((LIGAER[liga] / "data" / "results_state.json").read_text(encoding="utf-8"))
    except Exception:
        st = {}
    if st.get("ukontrollert") and now.minute < 10:
        return True, f"{len(st['ukontrollert'])} resultat(er) uten kontroll, sjekkes på nytt i timeslotten"
    forfalt, hvorfor = daglig_forfalt(liga, now)
    if forfalt:
        merk_forsok(liga, now)
        return True, f"ingen ventende kamper, men {hvorfor}"
    return False, f"ingen kamper har startet for over 105 minutter siden uten resultat ({hvorfor})"


def meld(liga, ok, reason, uten_tellende, miljo=None):
    """Skriver utfallet: begrunnelsen til stderr, should_fetch og uten_tellende
    til GITHUB_OUTPUT, og UTEN_TELLENDE=true til GITHUB_ENV, altså til ALLE
    senere steg i jobben. Sperren ligger i oddspapi.call og
    highlightly_source.kall, så ingen kodevei kan gjøre et tellende kall."""
    miljo = os.environ if miljo is None else miljo
    print(f"[{liga}] {reason}", file=sys.stderr)
    if miljo.get("GITHUB_OUTPUT"):
        with open(miljo["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"should_fetch={'true' if ok else 'false'}\n")
            f.write(f"uten_tellende={'true' if uten_tellende else 'false'}\n")
    if miljo.get("GITHUB_ENV") and uten_tellende:
        with open(miljo["GITHUB_ENV"], "a", encoding="utf-8") as f:
            f.write("UTEN_TELLENDE=true\n")
    print(f"should_fetch={ok}")
    print(f"uten_tellende={uten_tellende}")


if __name__ == "__main__":
    liga = sys.argv[1] if len(sys.argv) > 1 else "eliteserien"
    meld(liga, *vurder(liga=liga))
