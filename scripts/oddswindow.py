#!/usr/bin/env python3
"""Sluttodds: siste gyldige observasjon mellom 60 og 15 minutter før avspark.

Hvorfor et fast vindu, og ikke bare «den siste prisen vi har»:

  For tidlig, og laguttaket er ikke priset inn. Målt på 351 kamper
  (22. september 2026, scripts/odds_drift.py) flytter sannsynlighetene seg
  i snitt 3,0 prosentpoeng i OBOS og 2,8 i Eliteserien fra dagen før til
  vinduet, favoritten bytter i 2-4 prosent av kampene, og odds fra dagen før
  traff målbart dårligere: +0,0082 ± 0,0041 i log loss, 2,0 standardfeil.

  For sent, og prisen beveger seg uten å bli bedre. Den aller siste prisen
  før avspark (median under to minutter) målte 1,1 standardfeil BEDRE i OBOS
  og 0,8 DÅRLIGERE i Eliteserien -- sprikende, altså støy. Verre: 22.
  september kom en pris hentet 91 minutter ETTER avspark inn som sluttodds
  for Brann mot Bodø/Glimt og kostet Glimt 5,3 prosentpoeng på gullsjansen.
  En pris fra en kamp som pågår kjenner stillingen.

En kamp uten observasjon i vinduet er en kamp UTEN sluttodds. Vi bruker
aldri noe eldre i stedet: da ville tallet hete sluttodds og være noe annet.
Vinduet dekker 182 av 184 OBOS-kamper og 163 av 167 Eliteserien-kamper, så
det koster under to prosent av kampene.
"""
from datetime import datetime, timedelta, timezone

CLOSE_FROM_MIN = 60     # tidligst så lenge før avspark
CLOSE_TO_MIN = 15       # senest så lenge før avspark


def _parse(iso):
    if not iso or len(iso) < 16:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _stamp(dt, slutt_av_sekundet):
    """ISO-tekst å sammenligne createdAt mot.

    Brøkdelen avgjør om sekundet selv er med. Gulvet må starte på .000, ellers
    faller en pris satt nøyaktig 60 minutter før utenfor; taket må slutte på
    .999, ellers faller en pris satt nøyaktig 15 minutter før utenfor. Begge
    grensene er med i vinduet.
    """
    frac = ".999Z" if slutt_av_sekundet else ".000Z"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + frac


def bounds(kickoff_iso):
    """(gulv, tak) som ISO-strenger å sammenligne createdAt mot, eller (None, None).

    Grensene er tekst med vilje: createdAt fra OddsPapi er ISO i UTC, og da
    er strengsammenligning det samme som tidssammenligning -- uten å tolke
    hver eneste pris som en dato.
    """
    ko = _parse(kickoff_iso)
    if ko is None:
        return None, None
    return (_stamp(ko - timedelta(minutes=CLOSE_FROM_MIN), False),
            _stamp(ko - timedelta(minutes=CLOSE_TO_MIN), True))


def prices_in_window(outcomes, floor_iso, cutoff_iso):
    """Siste pris per utfall innenfor vinduet: liste med tre priser, eller None.

    outcomes er OddsPapi sin utfallsdict. Utfallene kommer i rekkefølgen
    hjemme, uavgjort, borte sortert på utfallsid. Mangler ETT av de tre en
    pris i vinduet, faller hele kampen ut: to priser fra vinduet og én fra i
    går er ikke en sluttodds.
    """
    if len(outcomes or {}) != 3:
        return None, None
    vals, stamp = [], None
    for oid in sorted(outcomes, key=str):
        entries = []
        for plist in ((outcomes[oid] or {}).get("players") or {}).values():
            if isinstance(plist, list):
                entries.extend(e for e in plist if isinstance(e, dict)
                               and e.get("price") and e.get("createdAt"))
        i_vinduet = [e for e in entries if floor_iso <= e["createdAt"] <= cutoff_iso]
        if not i_vinduet:
            return None, None
        siste = max(i_vinduet, key=lambda e: e["createdAt"])
        vals.append(float(siste["price"]))
        stamp = max(stamp or "", siste["createdAt"])
    return vals, stamp


def closing_from(payload, market_id, kickoff_iso, bookmakers):
    """Sluttoddsen for én kamp: (bookmaker, {H,U,B}, tidspunkt).

    Bookmakerne prøves i rekkefølgen de står i -- Pinnacle, så bet365, så
    Unibet -- og den første med en komplett observasjon i vinduet vinner.
    Aldri et snitt av flere: én kilde per kamp, og hvilken står i filen.

    Returnerer (None, None, None) når ingen har pris i vinduet. Den som
    kaller SKAL lagre det som «uten sluttodds», ikke falle tilbake på noe
    eldre.
    """
    floor_iso, cutoff_iso = bounds(kickoff_iso)
    if floor_iso is None:
        return None, None, None
    root = payload.get("data", payload) if isinstance(payload, dict) else {}
    books = root.get("bookmakers") or {}
    for bm in bookmakers:
        node = books.get(bm)
        if not isinstance(node, dict):
            continue
        m = (node.get("markets") or {}).get(str(market_id))
        vals, stamp = prices_in_window((m or {}).get("outcomes"), floor_iso, cutoff_iso)
        if vals:
            return bm, {"H": vals[0], "U": vals[1], "B": vals[2]}, stamp
    return None, None, None


def minutter_for(kickoff_iso, stamp_iso):
    """Hvor mange minutter før avspark prisen ble satt. None når noe mangler."""
    ko, pa = _parse(kickoff_iso), _parse(stamp_iso)
    if ko is None or pa is None:
        return None
    return (ko - pa).total_seconds() / 60
