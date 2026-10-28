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
import skrifter  # noqa: E402

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
  /* Tema som kalkulatoren (23.10.2026): systemets innstilling til brukeren
     har valgt med knappen (localStorage «theme», data-theme på <html>, satt i
     <head> før siden tegnes); data-theme vinner over systemet. */
  :root{--bg:#eef2f7;--panel:#ffffff;--ink:#0f1b2d;--muted:#56667d;--line:#d8e0ec;--accent:#2f6fed;--accent-text:#1f5fd6;--knapp-tekst:#ffffff;color-scheme:light}
  @media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0a1220;--panel:#111c2e;--ink:#e9eff8;--muted:#93a3ba;--line:#2a3a54;--accent:#7aa8ff;--accent-text:#7aa8ff;--knapp-tekst:#0a1220;color-scheme:dark}}
  :root[data-theme="dark"]{--bg:#0a1220;--panel:#111c2e;--ink:#e9eff8;--muted:#93a3ba;--line:#2a3a54;--accent:#7aa8ff;--accent-text:#7aa8ff;--knapp-tekst:#0a1220;color-scheme:dark}
  a{color:var(--accent-text)}
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Barlow",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  .wrap{max-width:672px;margin:0 auto;padding:24px 16px 56px}
  header{display:flex;align-items:center;gap:10px;margin-bottom:22px}
  .theme-toggle{margin-left:auto;flex:none;width:36px;height:36px;border-radius:50%;border:1px solid var(--line);background:transparent;color:var(--ink);display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0}
  .theme-toggle[hidden]{display:none}
  .theme-toggle svg{width:18px;height:18px;display:block}
  .theme-toggle .icon-moon{display:none}
  :root[data-theme="dark"] .theme-toggle .icon-sun{display:none}
  :root[data-theme="dark"] .theme-toggle .icon-moon{display:block}
  @media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .theme-toggle .icon-sun{display:none}:root:not([data-theme="light"]) .theme-toggle .icon-moon{display:block}}
  header a{display:flex;align-items:center;gap:10px;color:inherit;text-decoration:none}
  header svg{width:30px;height:30px;display:block;flex:none}
  .brand{font:800 21px/1 "Barlow Condensed","Arial Narrow",sans-serif;letter-spacing:.02em}
  .sti{font-size:14px;color:var(--muted);margin:0 0 8px}
  .sti a{color:var(--accent-text)}
  h1{font:800 clamp(28px,5vw,40px)/1.08 "Barlow Condensed","Arial Narrow",sans-serif;margin:0 0 14px;letter-spacing:-.01em;text-wrap:balance}
  h2{font:700 22px/1.2 "Barlow Condensed","Arial Narrow",sans-serif;margin:36px 0 12px}
  h3{font:700 18px/1.25 "Barlow Condensed","Arial Narrow",sans-serif;margin:22px 0 6px}
  p{margin:0 0 12px}
  .svar{font-size:19px;font-weight:600}
  .dato,.om{color:var(--muted);font-size:14px}
  .utsnitt{border-collapse:collapse;width:100%;margin:0 0 12px;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .utsnitt th,.utsnitt td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
  .utsnitt th:nth-child(2),.utsnitt td:nth-child(2){text-align:left}
  .utsnitt th{font-size:13px;color:var(--muted);font-weight:600}
  .utsnitt tr.aktuell td{font-weight:700}
  .kamper{list-style:none;margin:0 0 12px;padding:0;display:grid;gap:10px}
  .kamper li{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
  .utfall{color:var(--muted);font-size:14.5px}
  .knapp{display:inline-block;margin:8px 10px 0 0;padding:10px 16px;border-radius:10px;background:var(--accent);color:var(--knapp-tekst);font-weight:700;text-decoration:none}
  .knapp.lys{background:transparent;color:var(--accent-text);border:1px solid var(--line)}
  footer{margin-top:40px;color:var(--muted);font-size:13.5px}
  footer a{color:var(--accent-text)}
  a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
"""

# Temaet (23.10.2026): det lagrede valget settes i <head> før siden tegnes,
# så den ikke blinker i systemfargen først, som i kalkulatoren.
TEMA_HEAD = """<script>
  (function(){
    try{
      var s = localStorage.getItem('theme');
      if(s==='dark'||s==='light') document.documentElement.dataset.theme = s;
    }catch(e){}
  })();
</script>"""
# Månknappen øverst: skjult uten JavaScript (den gjør ingenting da), og bytter
# og lagrer temaet som knappen i kalkulatoren.
TEMA_KNAPP = ('<button class="theme-toggle" id="themeToggle" type="button" aria-label="Bytt til mørkt tema" title="Bytt til mørkt tema" hidden>'
              + """<svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4.5"></circle><path d="M12 2.5v2.5M12 19v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M2.5 12H5M19 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8"></path></svg>
<svg class="icon-moon" viewBox="0 0 24 24" fill="currentColor"><path d="M20.5 14.6A8.5 8.5 0 0 1 9.4 3.5a.6.6 0 0 0-.7-.8A9.5 9.5 0 1 0 21.3 15.3a.6.6 0 0 0-.8-.7Z"></path></svg>""" + "</button>")
TEMA_JS = """<script>
  (function(){
    var b = document.getElementById('themeToggle'); if(!b) return;
    function naa(){ var s = document.documentElement.dataset.theme;
      if(s==='dark'||s==='light') return s;
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; }
    function etikett(){ var l = naa()==='dark' ? 'Bytt til lyst tema' : 'Bytt til mørkt tema'; b.setAttribute('aria-label', l); b.title = l; }
    b.addEventListener('click', function(){ var n = naa()==='dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = n; try{ localStorage.setItem('theme', n); }catch(e){} etikett(); });
    b.hidden = false; etikett();
  })();
</script>"""

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
    beskrivelse = html.escape(kort_beskrivelse(svar), quote=True)
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<!-- Laget av scripts/lag_sider.py fra {liga}/data/tekster.json. Ikke rediger:
     siden lages på nytt hver gang tallene regnes. -->
{TEMA_HEAD}
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
<meta property="og:image" content="{url}og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{url}og.png">
{skrifter.blokk(skrifter.SPORSMAL)}
<style>{SPORSMAL_CSS}</style>
</head>
<body>
<div class="wrap">
  <header><a href="/">{LOGO}<span class="brand">Tabellkalkulator</span></a>{TEMA_KNAPP}</header>
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
{TEMA_JS}
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


BESKRIVELSE_MAKS = 155


def kort_beskrivelse(tekst):
    """meta description høyst 155 tegn (Bing: høyst 160, 28.10.2026). Svaret
    brukes som det er når det er kort nok; ellers første setning, og er den
    også for lang, kuttes den ved et ord med «…». Setningen deles bare ved
    punktum som ikke står rett etter et tall, så ordenstall som «3. plass»
    ikke deler den."""
    if len(tekst) <= BESKRIVELSE_MAKS:
        return tekst
    forste = re.split(r"(?<!\d)\. ", tekst)[0].rstrip(".") + "."
    if len(forste) <= BESKRIVELSE_MAKS:
        return forste
    return tekst[:BESKRIVELSE_MAKS - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


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


# ---- Lagsidene utvidet (23.10.2026) ----
# A: sjansen etter hver runde (data/sjansehistorikk.json, scripts/sjansehistorikk.py),
# som tekst, og som figur fra fire punkter. B: restprogrammet blant alle lagene
# og «Vanskeligst» som kalkulatoren. C: plassfordelingen 1 til 16. Figurene er
# inline SVG med tekstalternativ (title og desc), uten JavaScript. Hver figur
# viser én serie: to soner blir to figurer, så fargen aldri må skille dem.
HIST_MIN_FIGUR = 4
HIST_TEKST_MAKS = 6


def _pst(andel):
    """Andelen som siden viser den (pctTxt uten matematisk status)."""
    if andel <= 0:
        return "0 %"
    if andel >= 1:
        return "100 %"
    if andel < 0.005:
        return "<1 %"
    if andel >= 0.995:
        return ">99 %"
    return f"{int(andel * 100 + 0.5)} %"


def les_historikk(liga, root=ROOT):
    f = root / liga / "data" / "sjansehistorikk.json"
    return json.loads(f.read_text(encoding="utf-8"))["runder"] if f.exists() else []


def _fig_farge(liga, sone):
    """Klassen for sonens farge i figurene (fargene i LAG_CSS, validert for
    lyst og mørkt tema): som delingsbildet, blått for direkte opprykk i OBOS."""
    if sone == "nedrykk":
        return "rod"
    if sone == "kvalik":
        return "gul"
    if sone == "cl" or (sone == "gull" and liga == "obos"):
        return "blaa"
    return "gronn"


def _y_topp(maks):
    for t in (5, 10, 20, 25, 50, 100):
        if maks * 100 <= t:
            return t
    return 100


def _soyle(cx, bw, base, hh, klasse):
    """Søyle med 4 px avrundet topp og rett bunn, fra grunnlinjen."""
    r = min(4, hh)
    xl, xr, yt = cx - bw / 2, cx + bw / 2, base - hh
    return (f'<path class="soyle {klasse}" d="M{xl:.1f},{base} V{yt + r:.1f} Q{xl:.1f},{yt:.1f} {xl + r:.1f},{yt:.1f} '
            f'H{xr - r:.1f} Q{xr:.1f},{yt:.1f} {xr:.1f},{yt + r:.1f} V{base} Z"/>')


HIST_FIGUR_MAKS = 8


def _hist_svg(liga, sone, navn, punkter, tittel_id, bildetekst=True):
    """Én sone etter hver runde (de siste åtte): én søyle per runde, tallet over
    søylen og «Runde 23» under. Ingen y-akse; tallene står på søylene."""
    vis = punkter[-HIST_FIGUR_MAKS:]
    n, w, h, x0, x1, base, topp = len(vis), 640, 172, 8, 632, 112, 28
    slot = (x1 - x0) / n
    skala = _y_topp(max(a for _, a in vis))
    farge = _fig_farge(liga, sone)
    deler = [f'<line class="rutenett" x1="{x0}" x2="{x1}" y1="{base}" y2="{base}"/>']
    for i, (merke, a) in enumerate(vis):
        cx = x0 + slot * (i + 0.5)
        hh = (base - topp) * min(1, a * 100 / skala)
        if a > 0:
            hh = max(2, hh)
            deler.append(_soyle(cx, min(48, slot * 0.45), base, hh, farge))
        deler.append(f'<text class="verdi" x="{cx:.1f}" y="{base - hh - 8:.1f}" text-anchor="middle">{_nb(_pst(a))}</text>')
        deler.append(f'<text class="akse" x="{cx:.1f}" y="{base + 24}" text-anchor="middle">Runde</text>')
        deler.append(f'<text class="akse na" x="{cx:.1f}" y="{base + 50}" text-anchor="middle">{html.escape(merke)}</text>')
    desc = " ".join(f"Etter runde {m}: {_pst(a)}." for m, a in vis)
    tekst_ = f'<figcaption>{html.escape(navn[0].upper() + navn[1:])}</figcaption>' if bildetekst else ""
    return (f'<figure class="fig hist">{tekst_}'
            f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="{tittel_id}-t {tittel_id}-d">'
            f'<title id="{tittel_id}-t">Sjansen for {html.escape(navn)} etter hver runde</title>'
            f'<desc id="{tittel_id}-d">{_nb(html.escape(desc))}</desc>{"".join(deler)}</svg></figure>')


def _historikk_html(liga, t, lag, historikk):
    """A: sjansen etter hver runde, som (linje, seksjon). Fra fire punkter en
    seksjon «Sjansen for topp 4 de siste rundene» med søylene; før det én
    setning rett under tabellen, uten overskrift (brukeren 23.10.2026)."""
    d = t["lag"][lag]
    soner = [] if t["liga"]["ferdig"] else _lagets_soner(d)
    punkter = [x for x in historikk if lag in x["lag"]]
    if not soner or not punkter:
        return "", ""
    navn = {s["key"]: s["navn"] for s in d["soner"]}
    nokler = [s["key"] for s in soner]
    if len(punkter) >= HIST_MIN_FIGUR:
        overskrift = f"Sjansen for {liste([navn[k] for k in nokler])} de siste rundene"
        figurer = '<div class="figurer">' + "".join(
            _hist_svg(liga, k, navn[k], [(p["merke"], p["lag"][lag][k]) for p in punkter], f"hist-{k}", len(nokler) > 1)
            for k in nokler) + "</div>"
        return "", f'<h2>{html.escape(overskrift)}</h2>\n  {figurer}'
    vist_naa = {s["key"]: s["vist"] for s in d["soner"]}
    # «Nå» bare når tallene er regnet på nytt etter siste punkt (en ny runde
    # er i gang): ellers er siste punkt det siden viser nå.
    nyere = punkter[-1].get("laget") != t["laget"]
    if len(nokler) == 1:
        k = nokler[0]
        deler = [f"{_pst(p['lag'][lag][k])} etter runde {p['merke']}" for p in punkter]
        tekst = f"Sjansen for {navn[k]} var " + _rekke(deler[0], deler[1:]) + "."
        if nyere:
            tekst += f" Nå er den {vist_naa[k]}."
    else:
        a, b = nokler[0], nokler[1]
        forste, resten = punkter[0], punkter[1:]
        tekst = (f"Etter runde {forste['merke']} var sjansen for {navn[a]} {_pst(forste['lag'][lag][a])} "
                 f"og for {navn[b]} {_pst(forste['lag'][lag][b])}.")
        tekst += "".join(f" Etter runde {p['merke']}: {_pst(p['lag'][lag][a])} og {_pst(p['lag'][lag][b])}." for p in resten)
        if nyere:
            tekst += f" Nå: {vist_naa[a]} og {vist_naa[b]}."
    return f'<p class="historikk">{_nb(html.escape(tekst))}</p>\n  ', ""


def _fordeling_svg(lag, d, plass_na, baand=()):
    """C: plassfordelingen 1 til 16 som søyler i tabellens sonefarger (nedrykk
    skravert), med fargeforklaringens navn under aksen, og høyeste søyle og
    dagens plass merket."""
    f = d.get("fordeling") or []
    if len(f) < 2 or not any(f):
        return ""
    n, w, h, x0, x1, base, topp = len(f), 640, 166, 12, 628, 132, 24
    slot = (x1 - x0) / n
    bw = min(24, slot - 6)
    maks = max(f)
    deler = [f'<line class="rutenett" x1="{x0}" x2="{x1}" y1="{base}" y2="{base}"/>']
    for i, a in enumerate(f):
        cx = x0 + slot * (i + 0.5)
        if a > 0:
            hh = max(2, (base - topp) * a / maks)
            sone_ = next((b["cls"] for b in baand if b["lo"] <= i + 1 <= b["hi"]), "ingen")
            deler.append(_soyle(cx, bw, base, hh, f"b-{sone_}"))
        klasse = "akse na" if i + 1 == plass_na else "akse"
        deler.append(f'<text class="{klasse}" x="{cx:.1f}" y="{base + 26}" text-anchor="middle">{i + 1}</text>')
    im = f.index(maks)
    deler.append(f'<text class="verdi" x="{x0 + slot * (im + 0.5):.1f}" y="{base - (base - topp) - 8}" text-anchor="middle">{_nb(_pst(maks))}</text>')
    storst = sorted(((a, i + 1) for i, a in enumerate(f) if a >= 0.005), reverse=True)[:5]
    desc = ", ".join(f"{p}. plass {_pst(a)}" for a, p in storst) + "."
    skravur = ('<defs><pattern id="skravur" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
               '<rect class="skravur" width="3" height="6"/></pattern></defs>')
    # Korte navn, så forklaringen står på én linje på PC: «Champions League
    # (1 og 2)» for «Champions League-kvalifisering (1 og 2)».
    forklaring = ('<ul class="sonefarger">' + "".join(f'<li><i class="b-{b["cls"]}"></i>{html.escape(b["tekst"].replace(" League-kvalifisering", " League"))}</li>' for b in baand)
                  + "</ul>") if baand else ""
    return (f'<figure class="fig fordeling"><svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="ford-t ford-d">'
            f'<title id="ford-t">Hvilken plass {html.escape(lag)} ender på, plass 1 til {n}</title>'
            f'<desc id="ford-d">{_nb(html.escape(desc))}</desc>{skravur}{"".join(deler)}</svg>{forklaring}'
            f'<figcaption>Andelen av de simulerte sesongene på hver plass. Uthevet: plassen nå.</figcaption></figure>')


def _restprogram_tekst(lag, d):
    """B: plassen blant lagene etter motstandernes vinnersjanse, og «Vanskeligst»
    som kalkulatoren (lagets sjanse for seier)."""
    r = d.get("restprogram")
    if not r:
        return ""
    # Øvre halvdel som tøffeste, nedre som letteste regnet nedenfra (brukeren
    # 23.10.2026): med 16 lag er plass 13 «det 4. letteste».
    if r["plass"] <= r["av"] // 2:
        hvor = "det tøffeste restprogrammet" if r["plass"] == 1 else f"det {r['plass']}. tøffeste restprogrammet"
    else:
        fra_bunn = r["av"] - r["plass"] + 1
        hvor = "det letteste restprogrammet" if fra_bunn == 1 else f"det {fra_bunn}. letteste restprogrammet"
    av = f"av {r['av']} lag" if r["av"] == 16 else f"av de {r['av']} lagene som har kamper igjen"
    tekst = f"{lag} har {hvor} {av}: motstanderne har i snitt {r['snitt']} vinnersjanse."
    v = r.get("vanskeligst")
    if v:
        kamp = f"{'hjemme' if v['hjemme'] else 'borte'} mot {v['motstander']} {v['dato_tekst']}"
        tekst += (f" Eneste kamp igjen er {kamp}, der modellen gir {v['seier']} sjanse for seier." if r["kamper"] == 1
                  else f" Vanskeligst blir {kamp}, der modellen gir {v['seier']} sjanse for seier.")
    return tekst


KAMPER_MIN_PP = 3


def kamper_flytter(svar):
    """Største endring (prosentpoeng) et utfall gir i «Hvilke kamper betyr mest»,
    lest av svaret slik kalkulatoren skriver det («(+2 prosentpoeng)»; «endrer
    lite» er under grensen)."""
    tall_ = [abs(int(x.replace("−", "-"))) for x in re.findall(r"\(([+−-]?\d+) prosentpoeng\)", svar)]
    return max(tall_, default=0)


def _lag_sporsmal_html(d, lag=None, plass_na=None, baand=(), heldig=None):
    """De tre øverste spørsmålene i Spør om tabellen for laget. Et svar som bare
    gjentar et svar over (et avgjort lag får samme forklaring på flere spørsmål),
    vises én gang. «Hvilken plass ender X på?» til slutt hvis det ikke var med."""
    vist, ut = [], []
    for q in d["topp"] + ([] if any(q["id"] == "range" for q in d["topp"]) else [dict(d["plass"], id="range")]):
        svar = q["svar"].strip()
        if not svar or any(svar.endswith(v) or v.endswith(svar) for v in vist):
            continue
        kamper = q["id"] == "keymatches" and any("\n" in b for b in svar.split("\n\n")[1:])
        # Ingen kamp flytter sjansen mer enn 3 prosentpoeng: spørsmålet sier
        # ingenting (tre like kort med «endrer lite»), og står ikke (23.10.2026).
        if kamper and kamper_flytter(svar) <= KAMPER_MIN_PP:
            continue
        vist.append(svar)
        ut.append(f'<h3>{html.escape(q["sporsmal"])}</h3>{_kamper_html(svar) if kamper else _avsnitt(svar)}'
                  + (_fordeling_svg(lag, d, plass_na, baand) if q["id"] == "range" and lag else ""))
    # «Har X tatt flere eller færre poeng enn ventet?»: lagspørsmålet i kalkulatoren, hentet
    # via tekster.json som de andre (23.10.2026).
    if heldig and heldig.get("svar"):
        ut.append(f'<h3>{html.escape(heldig["sporsmal"])}</h3>{_avsnitt(heldig["svar"])}')
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
    v = (d.get("restprogram") or {}).get("vanskeligst") or {}
    for k in d["rest"]:
        utfall = _nb(f"Seier {k['seier']} · uavgjort {k['uavgjort']} · tap {k['tap']}")
        verst = k["naar"] == v.get("naar") and k["motstander"] == v.get("motstander")
        li.append(f'<li{" class=" + chr(34) + "vanskeligst" + chr(34) if verst else ""}><strong>{html.escape(k["naar"])}</strong>: '
                  f'{"hjemme" if k["hjemme"] else "borte"} mot <span class="lagnavn">{html.escape(k["motstander"])}</span>'
                  f'{" <span class=" + chr(34) + "merke" + chr(34) + ">Vanskeligst</span>" if verst else ""}<br><span class="utfall">{utfall}</span></li>')
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
    rp_tekst = _restprogram_tekst(lag, d)
    rest_del = ("<h2>Kampene som er igjen</h2>\n  "
                + (f'<p class="restprogram">{_nb(html.escape(rp_tekst))}</p>\n  ' if rp_tekst else "")
                + "<p>Sjansen for seier, uavgjort og tap i hver kamp, slik kalkulatoren "
                f"regner den.</p>\n  {rest}") if rest else ""
    hist_linje, historikk = _historikk_html(liga, t, lag, les_historikk(liga))
    utsnitt = _lag_utsnitt_html(t, lag)
    om = (f"Sjansene for {liste([sone_navn(t, k['key']) for k in t['tabell']['kolonner']])} er de samme som i tabellen på "
          "ligasiden." + (" «–» betyr at det ikke lenger er mulig." if "<td>–</td>" in utsnitt else ""))
    beskrivelse = html.escape(kort_beskrivelse(svar), quote=True)
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<!-- Laget av scripts/lag_sider.py fra {liga}/data/tekster.json. Ikke rediger:
     siden lages på nytt hver gang tallene regnes. -->
{TEMA_HEAD}
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
<meta property="og:image" content="{url}og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{url}og.png">
{skrifter.blokk(skrifter.LAGSIDE)}
<style>{SPORSMAL_CSS}{LAG_CSS}</style>
</head>
<body>
<div class="wrap">
  <header><a href="/">{LOGO}<span class="brand">Tabellkalkulator</span></a>{TEMA_KNAPP}</header>
  <p class="sti"><a href="/{liga}/">{html.escape(liganavn)}</a></p>
  <h1>{html.escape(tittel)}</h1>
  <p class="svar">{_nb(html.escape(svar))}</p>
  <p class="dato">Oppdatert {norsk_tid(t["laget"])}. Sjansene er regnet fra {tall(t["sesonger"])} simulerte sesonger.</p>
  {utsnitt}
  <p class="om">{html.escape(om)}</p>
  {hist_linje}{historikk}
  <h2>Spør om tabellen</h2>
  {_lag_sporsmal_html(d, lag, _rad(t, lag)["plass"], (t.get("regler") or {}).get("baand", []), d.get("heldig"))}
  {rest_del}
  <p><a class="knapp" href="/{liga}/#team={quote(lag, safe="")}">Følg {html.escape(lag)} i tabellkalkulatoren</a></p>
  <h2>Lagene i {html.escape(t["liga"]["navn"])}</h2>
  <p class="andre-lag">{andre_lag}</p>
  {f'<p>Se også: {sporsmal}</p>' if sporsmal else ''}
  <footer><a href="/">Tabellkalkulator</a> viser tabellen og sjansene for Eliteserien og OBOS-ligaen.</footer>
</div>
{TEMA_JS}
</body>
</html>
"""


LAG_CSS = """
  :root{--fig-gronn:#0f8468;--fig-blaa:#1d5fb4;--fig-gul:#a8770a;--fig-rod:#c0135a;--fig-soyle:#2f6fed;--b-cl:#1d5fb4;--b-eu:#1d7a63;--b-q:#cf951a;--b-ned:#6c7479;--b-ingen:#a3afc0}
  @media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--fig-gronn:#27a985;--fig-blaa:#4f8fe0;--fig-gul:#ad8f22;--fig-rod:#e04879;--fig-soyle:#7aa8ff;--b-cl:#4f8fe0;--b-eu:#1d7a63;--b-q:#cf951a;--b-ned:#8b939a;--b-ingen:#3f5170}}
  :root[data-theme="dark"]{--fig-gronn:#27a985;--fig-blaa:#4f8fe0;--fig-gul:#ad8f22;--fig-rod:#e04879;--fig-soyle:#7aa8ff;--b-cl:#4f8fe0;--b-eu:#1d7a63;--b-q:#cf951a;--b-ned:#8b939a;--b-ingen:#3f5170}
  /* Alle boksene (tabell, figurer, kort) er like brede: kolonnen, 640 px på PC. */
  .figurer{display:grid;gap:12px}
  .fig{margin:0 0 12px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px 10px}
  .fig figcaption{font-size:14px;color:var(--muted);margin:0 0 4px}
  .fig.fordeling figcaption{margin:2px 0 4px}
  .fig svg{display:block;width:100%;height:auto;overflow:visible}
  .fig .rutenett{stroke:var(--line);stroke-width:1}
  .fig .akse{fill:var(--muted);font:500 13px "Barlow",system-ui,sans-serif}
  .fig .akse.na{fill:var(--ink);font-weight:700}
  .fig .verdi{fill:var(--ink);font:700 15px "Barlow",system-ui,sans-serif}
  .fig .linje{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
  .fig .punkt{stroke:var(--panel);stroke-width:2}
  .fig .linje.gronn{stroke:var(--fig-gronn)}.fig .punkt.gronn{fill:var(--fig-gronn)}
  .fig .linje.blaa{stroke:var(--fig-blaa)}.fig .punkt.blaa{fill:var(--fig-blaa)}
  .fig .linje.gul{stroke:var(--fig-gul)}.fig .punkt.gul{fill:var(--fig-gul)}
  .fig .linje.rod{stroke:var(--fig-rod)}.fig .punkt.rod{fill:var(--fig-rod)}
  .fig .soyle{fill:var(--fig-soyle)}
  .fig .soyle.gronn{fill:var(--fig-gronn)}.fig .soyle.blaa{fill:var(--fig-blaa)}.fig .soyle.gul{fill:var(--fig-gul)}.fig .soyle.rod{fill:var(--fig-rod)}
  /* Plassfordelingen i tabellens sonefarger, nedrykk skravert som i tabellen. */
  .fig .soyle.b-cl{fill:var(--b-cl)}.fig .soyle.b-eu{fill:var(--b-eu)}.fig .soyle.b-playoff{fill:var(--b-q)}.fig .soyle.b-ingen{fill:var(--b-ingen)}
  .fig .soyle.b-ned{fill:url(#skravur);stroke:var(--b-ned);stroke-width:1.5}
  .fig .skravur{fill:var(--b-ned)}
  .sonefarger{list-style:none;margin:8px 0 2px;padding:0;display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12.5px;color:var(--muted)}
  .sonefarger li{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
  .sonefarger i{display:inline-block;width:12px;height:12px;border-radius:2px}
  .sonefarger .b-cl{background:var(--b-cl)}.sonefarger .b-eu{background:var(--b-eu)}.sonefarger .b-playoff{background:var(--b-q)}
  .sonefarger .b-ned{background:repeating-linear-gradient(135deg,var(--b-ned) 0 2px,transparent 2px 4px);border:1px solid var(--b-ned)}

  /* Smal skjerm: figuren skaleres ned, så teksten får større skrift i
     figurens egne enheter (her omtrent 12 px på skjermen). */
  @media (max-width:520px){.fig{padding:10px 10px 8px}.fig .akse{font-size:23px}.fig .verdi{font-size:26px}}
  .historikk{font-size:15px}
  .kamper li.vanskeligst{border-color:var(--accent-text)}
  .kamper .merke{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:999px;font-size:12px;font-weight:700;color:var(--accent-text);border:1px solid var(--accent-text);vertical-align:1px}
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
    viste dem (tekster.json «statisk», 20.10.2026), og fra 24.10.2026 «Neste
    kamp», spørsmålslista, «Forrige runde», de to første rundene i kamplista,
    banneret, «etter ...» ved tabelltittelen, rundetallet og tellerne, uten
    lag. Mangler de, står regionene som de er."""
    st = t.get("statisk")
    if not st:
        return {}
    ekstra = {k: st[n] for k, n in (("NESTEKAMP", "nestekamp"), ("SPORSMALSLISTE", "sporsmalsliste"),
                                    ("FORRIGERUNDE", "forrigerunde"), ("RUNDER", "runder"), ("BANNER", "banner")) if st.get(n)}
    ekstra.update({k.upper(): v for k, v in (st.get("tekster") or {}).items()})
    return {**ekstra, "LIGAMENY": st["ligameny"], "STEMPEL": st["stempel"], "FORKLARING": st["forklaring"],
            **{f"KORT{k.upper()}": st["kort"][k] for k in ("gull", "europa", "ned", "form")}}


# ---- Delingsbildene (23.10.2026) ----
# Ett bilde per lagside og spørsmålsside (<side>/og.png), tegnet av
# scripts/og_bilder.py av innholdet under: de samme tallene som teksten på
# siden. Innholdet lagres i PNG-filen (iTXt BILDE_NOKKEL), og filen skrives
# bare på nytt når det er endret, så bare endrede bilder kommer med i
# grunnlag-commiten.
BILDE_NOKKEL = "tabellkalkulator"


def bilde_lag(t, lag):
    """Delingsbildet for lagsiden: lagnavnet, plass og poeng, og tallet fra
    tittelen («1 %», «sjanse for topp 4»), som første setning på siden."""
    r = _rad(t, lag)
    b = {"art": "lag", "liga_id": t["_liga"], "liga": f'{t["liga"]["navn"]} {t["liga"]["sesong"]}', "navn": lag,
         "tall_venstre": [[f"{r['plass']}.", "plass"], [str(r["poeng"]), "poeng"]]}
    soner = [] if t["liga"]["ferdig"] else _lagets_soner(t["lag"][lag])
    b["under"] = "Sesongen er ferdig." if t["liga"]["ferdig"] else f"etter {r['kamper']} kamper"
    b["tall"] = ([{"tall": s["vist"], "tekst": f"sjanse for {s['navn']}", "sone": s["key"]} for s in soner]
                 or [{"tall": f"{r['plass']}.", "tekst": "plass til slutt" if t["liga"]["ferdig"] else "plass nå", "sone": "plass"}])
    return b


def bilde_sporsmal(t, sti, sone):
    """Delingsbildet for spørsmålssiden: spørsmålet og svaret, som på siden."""
    return {"art": "sporsmal", "liga_id": t["_liga"], "liga": f'{t["liga"]["navn"]} {t["liga"]["sesong"]}',
            "tittel": sporsmal_tittel(t, sti), "svar": sporsmal_svar(t, sti, sone), "sone": sone}


def bilde_tekst(innhold):
    """Innholdet som tekst, slik det lagres i bildet og sammenlignes."""
    return json.dumps(innhold, ensure_ascii=False, sort_keys=True)


def les_bilde(fil):
    """Innholdet som er lagret i bildet (iTXt BILDE_NOKKEL), eller None. Leser
    PNG-bitene selv, så --check og failsafe ikke trenger Pillow."""
    try:
        data = fil.read_bytes()
    except OSError:
        return None
    i, merke = 8, BILDE_NOKKEL.encode() + b"\0"
    while i + 8 <= len(data):
        n = int.from_bytes(data[i:i + 4], "big")
        typ, bit = data[i + 4:i + 8], data[i + 8:i + 8 + n]
        if typ == b"iTXt" and bit.startswith(merke):
            rest = bit[len(merke):]
            if rest[0] != 0:
                return None
            rest = rest[2:]
            rest = rest[rest.index(b"\0") + 1:]
            rest = rest[rest.index(b"\0") + 1:]
            return rest.decode("utf-8")
        i += 12 + n
    return None


def bilder(ligaer=LIGAER, root=ROOT):
    """(fil, innhold) for alle delingsbildene til ligaene."""
    ut = []
    for liga in ligaer:
        t = les(liga, root)
        ut += [(root / liga / sti / "og.png", bilde_sporsmal(t, sti, sone)) for sti, sone in SPORSMAL.get(liga, [])]
        ut += [(root / liga / lag_slug(lag) / "og.png", bilde_lag(t, lag)) for lag in t.get("lag", {})]
    return ut


MERKE = "<!-- Laget av scripts/lag_sider.py fra "


def undersider(liga, root=ROOT):
    """Undersidene til ligaen som dette skriptet har laget (spørsmåls- og
    lagsidene), funnet på merket øverst i filen, ikke på tekster.json: da kan
    workflowen legge dem til også når lag_sider.py feilet."""
    sider = [f for f in (root / liga).glob("*/index.html") if MERKE in f.read_text(encoding="utf-8")[:2000]]
    # Delingsbildet ved siden av siden; git add tar bare med de endrede.
    return sorted(g.relative_to(root).as_posix() for f in sider for g in (f, f.parent / "og.png") if g.exists())


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
    # Delingsbildene: sammenlign innholdet før lagring, skriv bare de endrede.
    try:
        import og_bilder
    except ImportError as e:
        og_bilder = None
        if not sjekk:
            print(f"::warning::Delingsbildene ble ikke laget ({e}); sidene er skrevet.")
    endret = 0
    for fil, innhold in bilder(ligaer):
        navn, tekst = fil.relative_to(ROOT).as_posix(), bilde_tekst(innhold)
        if les_bilde(fil) == tekst:
            continue
        if sjekk:
            print(f"{navn} er IKKE laget fra tekster.json.\n  Kjør: python3 scripts/lag_sider.py", file=sys.stderr)
            feil = 1
        elif og_bilder:
            og_bilder.skriv(fil, innhold, BILDE_NOKKEL, tekst)
            endret += 1
            print(f"Skrev {navn} ({fil.stat().st_size // 1024} KB).")
    if not sjekk:
        print(f"Delingsbilder: {endret} endret.")
    return feil


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
