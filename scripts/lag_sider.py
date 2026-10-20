#!/usr/bin/env python3
"""Lager de statiske delene av sidene fra <liga>/data/tekster.json (20.10.2026).

Chrome henter, Python lager sidene: scripts/lag_grunnlag.js skriver
tekster.json fra siden selv med den ferdige grunnlagsfilen (tabellen slik siden
viser den, overskriftene for sjansene, når det ble regnet). Dette skriptet
skriver ut fra den, uten Chrome og uten å regne noe:

  <liga>/index.html  regionene STATISK-KOLONNER, STATISK-TABELL og
                     STATISK-OPPDATERT (scripts/statisk_region.py): tabellen
                     med tall og sjanser i HTML-en, for søkemotorer og uten
                     JavaScript; render() på siden tar over. OPPDATERT er en
                     liten linje nederst ved «Om modellen». STATISK-LIGAMENY,
                     -STEMPEL, -FORKLARING og -KORT* (20.10.2026): det JS
                     fyller over og under tabellen, slik siden viste det, så
                     ingenting flytter seg ved lasting. Ingen oppsummering.
                     STATISK-LAGSIDER (fase 3): en enkel liste over lagsidene
                     nederst ved «Om modellen»
  index.html         (forsiden) STATISK-ELITESERIEN og STATISK-OBOS: de
                     samme setningene under «Akkurat nå», for hver liga
  <liga>/<spørsmål>/index.html  spørsmålssidene (fase 2, SPORSMAL): «Hvem
                     vinner Eliteserien 2026?» osv., med svaret først, «Hvorfor»
                     fra Spør om tabellen, tabellutsnitt og kampene som avgjør
  <liga>/<lag>/index.html  lagsidene (fase 3, lag_slug): «Brann 2026: sjanse
                     for topp 4» med plassen og sjansene, de tre øverste svarene
                     i Spør om tabellen for laget, hvilken plass laget ender på,
                     og kampene som er igjen med sjansen i hver

Setningene bygges av tallene slik siden viste dem (vist tekst og status for
hver sone); ingenting regnes.

Kjøres av grunnlag-workflowen etter lag_grunnlag.js, og alt committes sammen.

  python3 scripts/lag_sider.py [liga ...]          skriv (standard: begge)
  python3 scripts/lag_sider.py --check [liga ...]  er sidene laget fra filen?
  python3 scripts/lag_sider.py --filer [liga ...]  undersidene skriptet har laget
                     (spørsmåls- og lagsidene), til git add i workflowen
"""
import html
import json
import re
import sys
from urllib.parse import quote
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from statisk_region import med_statiske, statiske  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIGAER = ("eliteserien", "obos")
VERT = "https://tabellkalkulator.no"
# Spørsmålssidene (fase 2): faste adresser som lever hele sesongen og videre,
# (sti, sone). I OBOS er toppsonen direkte opprykk.
SPORSMAL = {
    "eliteserien": [("hvem-vinner", "gull"), ("hvem-rykker-ned", "nedrykk")],
    "obos": [("hvem-rykker-opp", "gull"), ("hvem-rykker-ned", "nedrykk")],
}


def arkiv_sti(liga, sesong, sti):
    """Hvor en ferdig sesongs spørsmålsside skal stå når en ny sesong tar over
    adressen (/eliteserien/2026/hvem-rykker-ned/). Ikke bygget ennå: det skjer
    ved sesongskiftet."""
    return f"{liga}/{sesong}/{sti}/"
MAANEDER = ("januar", "februar", "mars", "april", "mai", "juni", "juli", "august",
            "september", "oktober", "november", "desember")


def norsk_tid(iso):
    """'2026-10-20T02:42:09Z' -> '20. oktober 2026 kl. 04.42' (norsk tid)."""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Oslo"))
    return f"{t.day}. {MAANEDER[t.month - 1]} {t.year} kl. {t.hour:02d}.{t.minute:02d}"


def tall(n):
    """100000 -> '100 000' med hardt mellomrom, som på siden."""
    return f"{n:,}".replace(",", " ")


def liste(ord_):
    return ord_[0] if len(ord_) == 1 else ", ".join(ord_[:-1]) + " og " + ord_[-1]


def les(liga, root=ROOT):
    t = json.loads((root / liga / "data" / "tekster.json").read_text(encoding="utf-8"))
    t["_liga"] = liga
    return t


def oppdatert(t):
    """Den lille linja nederst ved «Om modellen» (20.10.2026; før en merknad
    over tabellen, som forsvant når JS tok over og flyttet siden)."""
    return f"Oppdatert {norsk_tid(t['laget'])}, {tall(t['sesonger'])} simulerte sesonger."


def sone_navn(t, key):
    """Sonens navn i setningene, slik siden kaller den («direkte opprykk» i
    OBOS, ikke kolonnenavnet «Opprykk»)."""
    k = next(x for x in t["tabell"]["kolonner"] if x["key"] == key)
    return k.get("sone") or (k["navn"][0].lower() + k["navn"][1:])


def _vist(r, key):
    """Sjansen slik siden viste den, med hardt mellomrom foran %, som på siden
    (ellers kan «42» og «%» havne på hver sin linje)."""
    return r["sjanser"][key]["vist"].replace(" %", "\u00a0%")


def _lag_pst(r, key, parentes=False):
    return f"{r['lag']} ({_vist(r, key)})" if parentes else f"{r['lag']} {_vist(r, key)}"


def _tabellorden(rader, nedenfra=False):
    """Lagene i tabellens rekkefølge (rangert som på siden, § 5-3), for
    «Hvorfor», utsnittet og kampene, så de aldri sier noe annet om plassene
    enn tabellen (OBOS 20.10.2026: Kongsvinger er nr. 2 på målforskjell, men
    Haugesund har større sjanse). Svarsetningen og oppsummeringen står etter
    sjanse, høyest først (brukeren 20.10.2026). Nedrykk leses nedenfra (16.,
    15., ...), også i setningene: da kommer laget nærmest først."""
    return sorted(rader, key=lambda r: r["plass"], reverse=nedenfra)


def _aapne(t, key, minst):
    """Lagene der sonen fortsatt er åpen og sjansen er minst «minst», størst først."""
    rader = [r for r in t["tabell"]["rader"] if r["sjanser"][key]["avgjort"] == 0 and r["sjanser"][key]["andel"] >= minst]
    return sorted(rader, key=lambda r: -r["sjanser"][key]["andel"])


def _sikre(t, key):
    return [r["lag"] for r in t["tabell"]["rader"] if r["sjanser"][key]["avgjort"] == 1]


def topp_setning(t):
    """«Bodø/Glimt har 69 % sjanse for gull og Viking 31 %.» Sikret: «X har sikret gull.»"""
    navn, deler = sone_navn(t, "gull"), []
    sikre = _sikre(t, "gull")
    if sikre:
        deler.append(f"{liste(sikre)} har sikret {navn}.")
    aapne = _aapne(t, "gull", 0.005)[:3]   # etter sjanse, høyest først
    if aapne:
        resten = [_lag_pst(r, "gull") for r in aapne[1:]]
        deler.append(f"{aapne[0]['lag']} har {_vist(aapne[0], 'gull')} sjanse for {navn}"
                     + (f" og {resten[0]}" if len(resten) == 1 else f", {liste(resten)}" if resten else "") + ".")
    return " ".join(deler)


def bunn_setning(t):
    """«Start (90 %) og Kristiansund (76 %) ligger nærmest nedrykk.» Avgjort: «X er rykket ned.»"""
    deler = []
    sikre = _sikre(t, "ned")
    if sikre:
        deler.append(f"{liste(sikre)} er rykket ned.")
    aapne = _tabellorden(_aapne(t, "ned", 0.01)[:2], nedenfra=True)
    if aapne:
        deler.append(f"{liste([_lag_pst(r, 'ned', True) for r in aapne])} ligger nærmest {sone_navn(t, 'ned')}.")
    return " ".join(deler)


def _lenker(liga, t):
    """Lenkene til spørsmålssidene for ligaen (tom når den ikke har noen)."""
    sider = SPORSMAL.get(liga, [])
    if not sider:
        return ""
    a = " · ".join(f'<a href="/{liga}/{sti}/">{html.escape(sporsmal_tittel(t, sti))}</a>' for sti, _ in sider)
    return f' <span class="opps-lenker">Les mer: {a}</span>'


def oppsummering(t):
    """Den korte oppsummeringen på forsiden («Akkurat nå»): lederne og hvem som
    ligger nærmest nedrykk, når det ble regnet, og lenkene til spørsmålssidene."""
    tekst = " ".join(html.escape(d, quote=False) for d in (topp_setning(t), bunn_setning(t)) if d)
    return f'{tekst} <span class="opps-dato">Oppdatert {norsk_tid(t["laget"])}.</span>{_lenker(t.get("_liga", ""), t)}'


# ---- Spørsmålssidene (fase 2) ----
def sporsmal_tittel(t, sti):
    liga, aar = t["liga"]["navn"], t["liga"]["sesong"]
    return {"hvem-vinner": f"Hvem vinner {liga} {aar}?",
            "hvem-rykker-opp": f"Hvem rykker opp fra {liga} {aar}?",
            "hvem-rykker-ned": f"Hvem rykker ned fra {liga} {aar}?"}[sti]


def _prosa(vist):
    """«>99 %» og «<1 %» som ord i en setning."""
    return {">99 %": "over 99 %", "<1 %": "under 1 %"}.get(vist, vist)


def _nb(s):
    """Hardt mellomrom mellom tall og % og mellom tall og poeng, som på siden."""
    s = re.sub(r"(\d+|<1|>99) %", "\\1\u00a0%", s)
    s = re.sub(r"([+−]?\d+) (prosentpoeng)", "\\1\u00a0\\2", s)
    return re.sub(r"\b(\d+) (poeng)", "\\1\u00a0\\2", s)


def _rekke(forst, resten):
    """«A, B og C» der første ledd er en hel setningsdel."""
    if not resten:
        return forst
    return f"{forst} og {resten[0]}" if len(resten) == 1 else f"{forst}, {', '.join(resten[:-1])} og {resten[-1]}"


def sporsmal_svar(t, sti, sone):
    """Første setning(er): svaret med lag og prosent. Avgjort sies rett ut;
    etter sesongslutt i fortid."""
    liga, aar, ferdig = t["liga"]["navn"], t["liga"]["sesong"], t["liga"]["ferdig"]
    kol = t["sporsmal"][sone]["kolonne"]
    rader = {r["lag"]: r for r in t["tabell"]["rader"]}
    # Svaret: etter sjanse, høyest først; nedrykk nedenfra i tabellen.
    lag = [rader[x["lag"]] for x in t["sporsmal"][sone]["lag"]]
    lag = _tabellorden(lag, nedenfra=True) if kol == "ned" else sorted(lag, key=lambda r: -r["sjanser"][kol]["andel"])
    sikre = [r["lag"] for r in lag if r["sjanser"][kol]["avgjort"] == 1]
    aapne = [r for r in lag if r["sjanser"][kol]["avgjort"] == 0]
    sikret_txt = {"hvem-vinner": ("er seriemester", "vant " + f"{liga} {aar}"),
                  "hvem-rykker-opp": ("har sikret direkte opprykk", "rykket direkte opp"),
                  "hvem-rykker-ned": ("er rykket ned", "rykket ned")}[sti]
    mal = {"hvem-vinner": f"sjanse for å vinne {liga}", "hvem-rykker-opp": "sjanse for direkte opprykk",
           "hvem-rykker-ned": "sjanse for å rykke ned"}[sti]
    deler = []
    if sikre:
        deler.append(f"{liste(sikre)} {sikret_txt[1] if ferdig else sikret_txt[0]}.")
    if aapne and not ferdig:
        v = lambda r: _prosa(r["sjanser"][kol]["vist"])
        deler.append(_rekke(f"{aapne[0]['lag']} har {v(aapne[0])} {mal}", [f"{r['lag']} {v(r)}" for r in aapne[1:]]) + ".")
        if aapne[0]["sjanser"][kol]["vist"].startswith(">"):
            deler.append("Det er så godt som avgjort.")
    if not deler:
        deler.append(f"Ingen lag har en reell sjanse lenger.")
    return " ".join(deler)


def _kamper_html(tekst):
    """«Hvilke kamper betyr mest» slik siden svarer: en innledning, så hver kamp
    med utfallene på hver sin linje."""
    blokker = [b for b in tekst.split("\n\n") if b.strip()]
    ut = [f'<p>{_nb(html.escape(blokker[0]))}</p>'] if blokker else []
    kamper = []
    for b in blokker[1:]:
        linjer = b.split("\n")
        utfall = " · ".join(_nb(html.escape(x)) for x in linjer[1:])
        kamper.append(f'<li><strong>{html.escape(linjer[0])}</strong><br><span class="utfall">{utfall}</span></li>')
    if kamper:
        ut.append(f'<ul class="kamper">{"".join(kamper)}</ul>')
    return "".join(ut)


def _utsnitt_html(t, sone):
    """Tabellen for de aktuelle lagene: plassene fra den første til den siste av dem."""
    kol = t["sporsmal"][sone]["kolonne"]
    navn = next(k for k in t["tabell"]["kolonner"] if k["key"] == kol)["navn"]
    aktuelle = {x["lag"] for x in t["sporsmal"][sone]["lag"]}
    plasser = [r["plass"] for r in t["tabell"]["rader"] if r["lag"] in aktuelle]
    if not plasser:
        return ""
    rader = [r for r in t["tabell"]["rader"] if min(plasser) <= r["plass"] <= max(plasser)]
    linjer = []
    for r in rader:
        klasse = ' class="aktuell"' if r["lag"] in aktuelle else ""
        linjer.append(f'<tr{klasse}><td>{r["plass"]}</td><td>{_laglenke(t, r["lag"])}</td><td>{r["kamper"]}</td>'
                      f'<td>{html.escape(r["poeng_vist"])}</td><td>{_nb(html.escape(r["sjanser"][kol]["vist"]))}</td></tr>')
    tr = "".join(linjer)
    return (f'<table class="utsnitt"><thead><tr><th>Plass</th><th>Lag</th><th>Kamper</th><th>Poeng</th>'
            f'<th>{html.escape(navn)}</th></tr></thead><tbody>{tr}</tbody></table>')


LOGO = ('<svg viewBox="0 0 16 16" aria-hidden="true"><rect x=".5" y=".5" width="15" height="15" rx="3.5" fill="#13305f" '
        'stroke="#4f7fc4" stroke-opacity=".6"/><rect x="3" y="4" width="10" height="2" rx="1" fill="#34d399"/><rect x="3" '
        'y="7" width="7" height="2" rx="1" fill="#e8f0fc"/><rect x="3" y="10" width="5" height="2" rx="1" fill="#e8f0fc"/></svg>')

SPORSMAL_CSS = """
  :root{--bg:#eef2f7;--panel:#ffffff;--ink:#0f1b2d;--muted:#56667d;--line:#d8e0ec;--accent:#2f6fed;--accent-text:#1f5fd6;--knapp-tekst:#ffffff}
  @media (prefers-color-scheme: dark){:root{--bg:#0a1220;--panel:#111c2e;--ink:#e9eff8;--muted:#93a3ba;--line:#2a3a54;--accent:#7aa8ff;--accent-text:#7aa8ff;--knapp-tekst:#0a1220}}
  a{color:var(--accent-text)}
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Barlow",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  .wrap{max-width:760px;margin:0 auto;padding:24px 16px 56px}
  header{display:flex;align-items:center;gap:10px;margin-bottom:22px}
  header a{display:flex;align-items:center;gap:10px;color:inherit;text-decoration:none}
  header svg{width:30px;height:30px;display:block;flex:none}
  .brand{font:800 21px/1 "Barlow Condensed","Arial Narrow",sans-serif;letter-spacing:.02em}
  .sti{font-size:14px;color:var(--muted);margin:0 0 8px}
  .sti a{color:var(--accent-text)}
  h1{font:800 clamp(28px,5vw,40px)/1.08 "Barlow Condensed","Arial Narrow",sans-serif;margin:0 0 14px;letter-spacing:-.01em;text-wrap:balance}
  h2{font:700 22px/1.2 "Barlow Condensed","Arial Narrow",sans-serif;margin:30px 0 10px}
  h3{font:700 18px/1.25 "Barlow Condensed","Arial Narrow",sans-serif;margin:20px 0 6px}
  p{margin:0 0 12px;max-width:68ch}
  .svar{font-size:19px;font-weight:600}
  .dato,.om{color:var(--muted);font-size:14px}
  .utsnitt{border-collapse:collapse;width:100%;max-width:560px;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .utsnitt th,.utsnitt td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
  .utsnitt th:nth-child(2),.utsnitt td:nth-child(2){text-align:left}
  .utsnitt th{font-size:13px;color:var(--muted);font-weight:600}
  .utsnitt tr.aktuell td{font-weight:700}
  .kamper{list-style:none;margin:0;padding:0;display:grid;gap:10px;max-width:68ch}
  .kamper li{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
  .utfall{color:var(--muted);font-size:14.5px}
  .knapp{display:inline-block;margin:8px 10px 0 0;padding:10px 16px;border-radius:10px;background:var(--accent);color:var(--knapp-tekst);font-weight:700;text-decoration:none}
  .knapp.lys{background:transparent;color:var(--accent-text);border:1px solid var(--line)}
  footer{margin-top:40px;color:var(--muted);font-size:13.5px}
  footer a{color:var(--accent-text)}
  a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
"""

TELLING = """<script>
  (function(){
    if(location.hostname !== 'tabellkalkulator.no') return;
    var s = document.createElement('script');
    s.async = true; s.src = '//gc.zgo.at/count.js';
    s.setAttribute('data-goatcounter', 'https://tabellkalkulator.goatcounter.com/count');
    s.onerror = function(){}; document.head.appendChild(s);
  })();
</script>"""


# Regelsvarene (20.10.2026): korte svar om reglene på spørsmålssidene, med
# plassene fra LEAGUE og siste runde fra terminlisten (tekster.json «regler»).
REGLER = {
    "eliteserien": {"hvem-rykker-ned": ("ned", "slutt")},
    "obos": {"hvem-rykker-opp": ("opp", "kvalik"), "hvem-rykker-ned": ("ned", "kvalik")},
}
# Hvem nummer 14 møter i kvaliken, der det er bekreftet; ellers står bare at
# laget spiller kvalik (OBOS mot 2. divisjon er ikke bekreftet for 2026).
KVALIK_MOT = {"eliteserien": "mot et lag fra OBOS-ligaen om plassen i Eliteserien"}
UKEDAGER = ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag")
TALLORD = {1: "ett", 2: "to", 3: "tre", 4: "fire"}


def _plasser(lo, hi):
    """«nummer 15 og 16», «nummer 3 til 6», «nummer 14»."""
    return f"nummer {lo}" if lo == hi else f"nummer {lo} og {hi}" if hi == lo + 1 else f"nummer {lo} til {hi}"


def _dag(iso):
    """'2026-12-13' -> 'søndag 13. desember'."""
    d = datetime.fromisoformat(iso)
    return f"{UKEDAGER[d.weekday()]} {d.day}. {MAANEDER[d.month - 1]}"


def _stor(s):
    return s[0].upper() + s[1:]


def regelsvar(t, nokkel, root=ROOT):
    """(spørsmål, svar) for ett regelspørsmål: høyst to setninger, svaret først."""
    r, liga, aar, ferdig = t["regler"], t["liga"]["navn"], t["liga"]["sesong"], t["liga"]["ferdig"]
    soner, baand = r["soner"], {b["cls"]: b for b in r["baand"]}
    kv = soner["kvalik"]["lo"]
    if nokkel == "ned":
        ned = soner["nedrykk"]
        antall = ned["hi"] - ned["lo"] + 1
        return (f"Hvor mange rykker ned fra {liga}?",
                f"{_stor(TALLORD.get(antall, str(antall)))} lag rykker direkte ned fra {liga}: {_plasser(ned['lo'], ned['hi'])}. "
                f"{_stor(_plasser(kv, kv))} spiller kvalik{' ' + KVALIK_MOT[t['_liga']] if t.get('_liga') in KVALIK_MOT else ''}.")
    if nokkel == "slutt":
        siste, dag = r["siste_runde"], _dag(r["siste_dato"])
        hvor = (f"med runde {siste}, den siste i terminlisten" if siste in r["runder_siste_dato"]
                else "med den siste kampen i terminlisten")
        return (f"Når avsluttes {liga}?",
                f"{liga} {aar} {'ble avsluttet' if ferdig else 'avsluttes'} {dag} {hvor}. "
                f"Da {'var' if ferdig else 'er'} alle de {r['kamper']} kampene spilt, og kvaliken for {_plasser(kv, kv)} kommer etterpå.")
    if nokkel == "opp":
        opp, eu = soner["gull"], baand["eu"]
        antall = opp["hi"] - opp["lo"] + 1
        return (f"Hvor mange rykker opp fra {liga}?",
                f"{_stor(TALLORD.get(antall, str(antall)))} lag rykker direkte opp fra {liga}: {_plasser(opp['lo'], opp['hi'])}. "
                f"Ett lag til kan rykke opp gjennom kvaliken, der lagene på {eu['lo']}. til {eu['hi']}. plass er med.")
    if nokkel == "kvalik":
        eu = baand["eu"]
        es = root / "eliteserien" / "data" / "tekster.json"
        es_r = json.loads(es.read_text(encoding="utf-8")).get("regler") if es.exists() else None
        es_kv = es_r["soner"]["kvalik"]["lo"] if es_r else kv
        return ("Hvordan fungerer kvaliken?",
                f"Lagene på {eu['lo']}. til {eu['hi']}. plass spiller opprykkskvalifisering, og vinneren møter "
                f"{_plasser(es_kv, es_kv)} i Eliteserien om en plass der.")
    raise KeyError(nokkel)


def _regler_html(liga, sti, t):
    """«Om reglene» på spørsmålssiden (tom når siden ikke har regelsvar)."""
    nokler = REGLER.get(liga, {}).get(sti, ())
    if not nokler or not t.get("regler"):
        return ""
    deler = [regelsvar(t, n) for n in nokler]
    return "<h2>Om reglene</h2>\n  " + "".join(
        f"<h3>{html.escape(sp)}</h3><p>{_nb(html.escape(sv))}</p>\n  " for sp, sv in deler)


def sporsmal_side(liga, sti, sone, t):
    """Hele spørsmålssiden som HTML, bare fra tekster.json."""
    tittel = sporsmal_tittel(t, sti)
    svar = sporsmal_svar(t, sti, sone)
    url = f"{VERT}/{liga}/{sti}/"
    sp = dict(t["sporsmal"][sone])
    plass = {r["lag"]: r["plass"] for r in t["tabell"]["rader"]}
    sp["lag"] = sorted(sp["lag"], key=lambda x: plass[x["lag"]], reverse=(sp["kolonne"] == "ned"))   # tabellens rekkefølge
    kol = sp["kolonne"]
    k = next(x for x in t["tabell"]["kolonner"] if x["key"] == kol)
    om = (k.get("tittel") or "").replace(" Klikk for å sortere.", "").strip()
    hvorfor = "".join(f'<h3>{html.escape(x["sporsmal"])}</h3>' + "".join(f'<p>{_nb(html.escape(p))}</p>' for p in x["hvorfor"].split("\n\n") if p.strip())
                      for x in sp["lag"])
    kamper = "".join(f'<h3>Kampene som betyr mest for {html.escape(x["lag"])}</h3>{_kamper_html(x["kamper"])}' for x in sp["lag"] if x.get("kamper"))
    forst = sp["lag"][0]["lag"] if sp["lag"] else None
    liganavn = f'{t["liga"]["navn"]} {t["liga"]["sesong"]}'
    knapper = f'<a class="knapp" href="/{liga}/">Prøv selv i tabellkalkulatoren</a>'
    if forst:
        knapper += f' <a class="knapp lys" href="/{liga}/#team={quote(forst, safe="")}">Følg {html.escape(forst)}</a>'
    andre = " · ".join(f'<a href="/{liga}/{s2}/">{html.escape(sporsmal_tittel(t, s2))}</a>' for s2, _ in SPORSMAL.get(liga, []) if s2 != sti)
    beskrivelse = html.escape(svar, quote=True)
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<!-- Laget av scripts/lag_sider.py fra {liga}/data/tekster.json. Ikke rediger:
     siden lages på nytt hver gang tallene regnes. -->
{TELLING}
<title>{html.escape(tittel)}</title>
<meta name="description" content="{beskrivelse}">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#13305f">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" type="image/png" sizes="32x32">
<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Tabellkalkulator">
<meta property="og:locale" content="nb_NO">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{html.escape(tittel, quote=True)}">
<meta property="og:description" content="{beskrivelse}">
<meta property="og:image" content="{VERT}/{liga}/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Barlow:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{SPORSMAL_CSS}</style>
</head>
<body>
<div class="wrap">
  <header><a href="/">{LOGO}<span class="brand">Tabellkalkulator</span></a></header>
  <p class="sti"><a href="/{liga}/">{html.escape(liganavn)}</a></p>
  <h1>{html.escape(tittel)}</h1>
  <p class="svar">{_nb(html.escape(svar))}</p>
  <p class="dato">Oppdatert {norsk_tid(t["laget"])}. Sjansene er regnet fra {tall(t["sesonger"])} simulerte sesonger.</p>
  <h2>Hvorfor</h2>
  {hvorfor}
  <h2>Tabellen</h2>
  {_utsnitt_html(t, sone)}
  <p class="om">{html.escape(om)}</p>
  <h2>Kampene som avgjør</h2>
  {kamper}
  {_regler_html(liga, sti, t)}<p>{knapper}</p>
  {f'<p>Se også: {andre}</p>' if andre else ''}
  <footer><a href="/">Tabellkalkulator</a> viser tabellen og sjansene for Eliteserien og OBOS-ligaen.</footer>
</div>
</body>
</html>
"""


# ---- Lagsidene (fase 3) ----
def lag_slug(lag):
    """Adressen til lagsiden: små bokstaver, æ/ø/å som ae/o/a, mellomrom og / som
    bindestrek (Bodø/Glimt blir bodo-glimt, Sarpsborg 08 blir sarpsborg-08)."""
    s = lag.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _laglenke(t, lag):
    return f'<a href="/{t["_liga"]}/{lag_slug(lag)}/">{html.escape(lag)}</a>'


def lagsider(t):
    """Den enkle lista over lagsidene nederst på ligasiden, i tabellens rekkefølge."""
    return "Lagsidene: " + " · ".join(_laglenke(t, r["lag"]) for r in t["tabell"]["rader"])


def _lagets_soner(d):
    """Sonene laget kjemper om: de med 1 til 99 % sjanse, ellers den mest åpne."""
    soner = [s for s in d["soner"] if s["avgjort"] == 0 and s["vist"] not in ("<1 %", ">99 %")]
    return soner or [s for s in d["soner"] if s["key"] == d.get("aapnest")]


def _rad(t, lag):
    return next(r for r in t["tabell"]["rader"] if r["lag"] == lag)


def lag_tittel(t, lag):
    aar = t["liga"]["sesong"]
    if t["liga"]["ferdig"]:
        return f"{lag} {aar}: endte på {_rad(t, lag)['plass']}. plass"
    soner = _lagets_soner(t["lag"][lag])
    return f"{lag} {aar}: sjanse for {liste([s['navn'] for s in soner])}" if soner else f"{lag} {aar}: tabellen og sjansene"


def lag_svar(t, lag):
    """Første setning(er): plassen, poengene og sjansen i sonene i tittelen."""
    r, liga = _rad(t, lag), f'{t["liga"]["navn"]} {t["liga"]["sesong"]}'
    if t["liga"]["ferdig"]:
        return f"{lag} endte på {r['plass']}. plass i {liga} med {r['poeng']} poeng."
    deler = [f"{lag} ligger på {r['plass']}. plass i {liga} med {r['poeng']} poeng etter {r['kamper']} kamper."]
    soner = _lagets_soner(t["lag"][lag])
    if soner:
        deler.append(_rekke(f"Sjansen for {soner[0]['navn']} er {_prosa(soner[0]['vist'])}",
                            [f"for {s['navn']} {_prosa(s['vist'])}" for s in soner[1:]]) + ".")
    return " ".join(deler)


def _avsnitt(tekst):
    return "".join(f"<p>{_nb(html.escape(p))}</p>" for p in tekst.split("\n\n") if p.strip())


def _lag_sporsmal_html(d):
    """De tre øverste spørsmålene i Spør om tabellen for laget. Et svar som bare
    gjentar et svar over (et avgjort lag får samme forklaring på flere spørsmål),
    vises én gang. «Hvilken plass ender X på?» til slutt hvis det ikke var med."""
    vist, ut = [], []
    for q in d["topp"] + ([] if any(q["id"] == "range" for q in d["topp"]) else [dict(d["plass"], id="range")]):
        svar = q["svar"].strip()
        if not svar or any(svar.endswith(v) or v.endswith(svar) for v in vist):
            continue
        vist.append(svar)
        kamper = q["id"] == "keymatches" and any("\n" in b for b in svar.split("\n\n")[1:])
        ut.append(f'<h3>{html.escape(q["sporsmal"])}</h3>{_kamper_html(svar) if kamper else _avsnitt(svar)}')
    return "\n  ".join(ut)


def _lag_utsnitt_html(t, lag):
    """Tabellen rundt laget (to plasser over og under), med sjansene slik tabellen viser dem."""
    rader, p = t["tabell"]["rader"], _rad(t, lag)["plass"]
    fra = max(1, min(p - 2, len(rader) - 4))
    kol = t["tabell"]["kolonner"]
    linjer = []
    for r in rader[fra - 1:fra + 4]:
        klasse = ' class="aktuell"' if r["lag"] == lag else ""
        celler = "".join(f'<td>{_nb(html.escape(r["sjanser"][k["key"]]["vist"]))}</td>' for k in kol)
        navn = html.escape(r["lag"]) if r["lag"] == lag else _laglenke(t, r["lag"])
        linjer.append(f'<tr{klasse}><td>{r["plass"]}</td><td>{navn}</td><td>{r["kamper"]}</td>'
                      f'<td>{html.escape(r["poeng_vist"])}</td>{celler}</tr>')
    hode = "".join(f"<th>{html.escape(k['navn'])}</th>" for k in kol)
    return (f'<table class="utsnitt lag"><thead><tr><th>Plass</th><th>Lag</th><th>Kamper</th><th>Poeng</th>{hode}</tr></thead>'
            f'<tbody>{"".join(linjer)}</tbody></table>')


def _rest_html(d):
    li = []
    for k in d["rest"]:
        utfall = _nb(f"Seier {k['seier']} · uavgjort {k['uavgjort']} · tap {k['tap']}")
        li.append(f'<li><strong>{html.escape(k["naar"])}</strong>: {"hjemme" if k["hjemme"] else "borte"} '
                  f'mot <span class="lagnavn">{html.escape(k["motstander"])}</span><br><span class="utfall">{utfall}</span></li>')
    return f'<ul class="kamper rest">{"".join(li)}</ul>' if li else ""


def lag_side(liga, lag, t):
    """Hele lagsiden som HTML, bare fra tekster.json."""
    d = t["lag"][lag]
    tittel, svar = lag_tittel(t, lag), lag_svar(t, lag)
    url = f"{VERT}/{liga}/{lag_slug(lag)}/"
    liganavn = f'{t["liga"]["navn"]} {t["liga"]["sesong"]}'
    andre_lag = " · ".join(f'<a href="/{liga}/{lag_slug(r["lag"])}/">{html.escape(r["lag"])}</a>' if r["lag"] != lag
                           else f'<strong>{html.escape(r["lag"])}</strong>' for r in t["tabell"]["rader"])
    sporsmal = " · ".join(f'<a href="/{liga}/{s2}/">{html.escape(sporsmal_tittel(t, s2))}</a>' for s2, _ in SPORSMAL.get(liga, []))
    rest = _rest_html(d)
    rest_del = ("<h2>Kampene som er igjen</h2>\n  <p>Sjansen for seier, uavgjort og tap i hver kamp, slik kalkulatoren "
                f"regner den.</p>\n  {rest}") if rest else ""
    utsnitt = _lag_utsnitt_html(t, lag)
    om = (f"Sjansene for {liste([sone_navn(t, k['key']) for k in t['tabell']['kolonner']])} er de samme som i tabellen på "
          "ligasiden." + (" «–» betyr at det ikke lenger er mulig." if "<td>–</td>" in utsnitt else ""))
    beskrivelse = html.escape(svar, quote=True)
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<!-- Laget av scripts/lag_sider.py fra {liga}/data/tekster.json. Ikke rediger:
     siden lages på nytt hver gang tallene regnes. -->
{TELLING}
<title>{html.escape(tittel)}</title>
<meta name="description" content="{beskrivelse}">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#13305f">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" type="image/png" sizes="32x32">
<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Tabellkalkulator">
<meta property="og:locale" content="nb_NO">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{html.escape(tittel, quote=True)}">
<meta property="og:description" content="{beskrivelse}">
<meta property="og:image" content="{VERT}/{liga}/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Barlow:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{SPORSMAL_CSS}{LAG_CSS}</style>
</head>
<body>
<div class="wrap">
  <header><a href="/">{LOGO}<span class="brand">Tabellkalkulator</span></a></header>
  <p class="sti"><a href="/{liga}/">{html.escape(liganavn)}</a></p>
  <h1>{html.escape(tittel)}</h1>
  <p class="svar">{_nb(html.escape(svar))}</p>
  <p class="dato">Oppdatert {norsk_tid(t["laget"])}. Sjansene er regnet fra {tall(t["sesonger"])} simulerte sesonger.</p>
  {utsnitt}
  <p class="om">{html.escape(om)}</p>
  <h2>Spør om tabellen</h2>
  {_lag_sporsmal_html(d)}
  {rest_del}
  <p><a class="knapp" href="/{liga}/#team={quote(lag, safe="")}">Følg {html.escape(lag)} i tabellkalkulatoren</a></p>
  <h2>Lagene i {html.escape(t["liga"]["navn"])}</h2>
  <p class="andre-lag">{andre_lag}</p>
  {f'<p>Se også: {sporsmal}</p>' if sporsmal else ''}
  <footer><a href="/">Tabellkalkulator</a> viser tabellen og sjansene for Eliteserien og OBOS-ligaen.</footer>
</div>
</body>
</html>
"""


LAG_CSS = """
  .utsnitt.lag th,.utsnitt.lag td{padding:7px 8px}
  .andre-lag{line-height:1.9}
  .andre-lag a,.lagnavn{white-space:nowrap}
  @media (max-width:520px){.utsnitt.lag th:nth-child(3),.utsnitt.lag td:nth-child(3){display:none}.utsnitt.lag th,.utsnitt.lag td{padding:6px 5px;font-size:14px}}
"""


def forside(root=ROOT, ligaer=LIGAER):
    """Forsiden med den korte oppsummeringen for hver liga som har tekster.json."""
    side = (root / "index.html").read_text(encoding="utf-8")
    regioner = statiske(side)
    for liga in ligaer:
        if (root / liga / "data" / "tekster.json").exists():
            regioner[liga.upper()] = oppsummering(les(liga, root))
    return med_statiske(side, regioner)


def ligaside(liga, root=ROOT):
    """Ligasiden med de statiske regionene fra tekster.json."""
    side = (root / liga / "index.html").read_text(encoding="utf-8")
    t = les(liga, root)
    return med_statiske(side, {**statiske(side),
                               "KOLONNER": t["tabell"]["kolonner_html"],
                               "TABELL": t["tabell"]["rader_html"],
                               "OPPDATERT": oppdatert(t),
                               "LAGSIDER": lagsider(t),
                               **_side_statisk(t)})


def _side_statisk(t):
    """Ligamenyen, stempelet, fargeforklaringen og de fire boksene slik siden
    viste dem (tekster.json «statisk», 20.10.2026). Mangler de, står regionene
    som de er."""
    st = t.get("statisk")
    if not st:
        return {}
    return {"LIGAMENY": st["ligameny"], "STEMPEL": st["stempel"], "FORKLARING": st["forklaring"],
            **{f"KORT{k.upper()}": st["kort"][k] for k in ("gull", "europa", "ned", "form")}}


MERKE = "<!-- Laget av scripts/lag_sider.py fra "


def undersider(liga, root=ROOT):
    """Undersidene til ligaen som dette skriptet har laget (spørsmåls- og
    lagsidene), funnet på merket øverst i filen, ikke på tekster.json: da kan
    workflowen legge dem til også når lag_sider.py feilet."""
    return sorted(f.relative_to(root).as_posix() for f in (root / liga).glob("*/index.html")
                  if MERKE in f.read_text(encoding="utf-8")[:2000])


def main(argv):
    sjekk = "--check" in argv
    ligaer = [a for a in argv if not a.startswith("-")] or list(LIGAER)
    if "--filer" in argv:
        print("\n".join(f for liga in ligaer for f in undersider(liga)))
        return 0
    feil = 0
    # Forsiden har én region per liga; hver liga skriver bare sin egen, så de
    # to grunnlag-jobbene ikke endrer de samme linjene.
    sider = [(f"{liga}/index.html", ROOT / liga / "index.html", ligaside(liga)) for liga in ligaer]
    sider += [(f"{liga}/{sti}/index.html", ROOT / liga / sti / "index.html", sporsmal_side(liga, sti, sone, les(liga)))
              for liga in ligaer for sti, sone in SPORSMAL.get(liga, [])]
    sider += [(f"{liga}/{lag_slug(lag)}/index.html", ROOT / liga / lag_slug(lag) / "index.html", lag_side(liga, lag, t))
              for liga in ligaer for t in [les(liga)] for lag in t.get("lag", {})]
    sider += [("index.html (forsiden)", ROOT / "index.html", forside(ligaer=ligaer))]
    for navn, fil, ny in sider:
        gml = fil.read_text(encoding="utf-8") if fil.exists() else None
        if sjekk:
            if ny == gml:
                print(f"{navn} er laget fra tekster.json.")
            else:
                print(f"{navn} er IKKE laget fra tekster.json.\n"
                      f"  Kjør: python3 scripts/lag_sider.py", file=sys.stderr)
                feil = 1
        elif ny != gml:
            fil.parent.mkdir(parents=True, exist_ok=True)
            fil.write_text(ny, encoding="utf-8")
            print(f"Skrev {navn} fra tekster.json.")
        else:
            print(f"{navn} var uendret.")
    return feil


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
