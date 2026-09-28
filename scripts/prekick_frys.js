/* Frysregelen for prekick.json, delt av scripts/snapshot_probs.js og testene.
 *
 * REGELEN: en rad oppdateres bare mens klokken er FØR avspark. Avsparket tas
 * fra terminlisten (<liga>/data/fixtures.json: date + time, norsk lokaltid,
 * Europe/Oslo -> UTC), samme regel som testsidens prognoselogg. Etter avspark
 * røres raden ikke, og når resultatet kommer, fryses den med det siste
 * stempelet fra før avspark.
 *
 * HVORFOR: før denne regelen ble raden skrevet på nytt ved hver kjøring til
 * resultatet var inne. Porten i "Oppdater kampdata" åpner først 105 minutter
 * etter avspark, så den siste skrivingen -- og dermed den frosne prognosen --
 * ville som regel hatt et stempel ETTER avspark, og kunne inneholdt
 * informasjon fra etter avspark (for eksempel resultater i andre kamper som
 * ble ferdige mens kampen pågikk).
 *
 * Mangler klokkeslettet, regnes avsparket som 00:00 norsk tid den dagen: da
 * oppdateres raden ikke på kampdagen. Forsiktig heller enn for sent.
 *
 * HVEM SOM SKRIVER RADEN (modus). Fra porten til "Odds nær avspark" åpner,
 * VINDU_MIN = 70 minutter før avspark (FRA_MIN i scripts/prekick_vindu.py),
 * eies raden av prekick-odds.yml: den skriver prisen fra OddsPapi (Pinnacle)
 * i odds_upcoming.json og regner raden på nytt ved hver kjøring
 * (snapshot_probs.js --bare-prekick), så den frosne prognosen bruker
 * sluttoddsen og de nyeste lagstyrkene. Datajobbene (update-data,
 * obos-results: --uten-prekick-vindu) rører ikke rader med avspark innen
 * VINDU_MIN + BUFFER_MIN = 80 minutter. Da skriver de to jobbene aldri samme
 * rad, og en rebase mellom dem går rent. Bufferen: en datajobb som regnet
 * raden 81 minutter før avspark, har over ti minutter på å pushe før
 * "Odds nær avspark" kan skrive den (målt i CI: under ti sekunder fra
 * snapshot til push). Uten den kunne begge skrive samme rad rundt grensen,
 * og da ville datajobben få rebasekonflikt og miste commiten sin.
 *   'alle'        som før: alle uspilte rader før avspark (testsiden, der
 *                 elo-test.yml er eneste skriver)
 *   'uten-vindu'  datajobbene: ikke rader med avspark innen 80 minutter
 *   'bare-vindu'  prekick-odds.yml: bare rader i vinduet, og ingen frysing
 *                 (den gjør datajobben når resultatet kommer)
 *
 * NÅR ODDSEN HENTES OG NÅR RADEN SKRIVES er to ting. Hentingen er uendret:
 * porten er åpen 70 til 10 minutter før avspark, og prekick_odds.py henter
 * pris for kamper 60 til 15 minutter før avspark (oddswindow.py). Raden
 * skrives av en kjøring som hentet oddsen SENEST SLUTT_MIN = 15 minutter før
 * avspark (CLOSE_TO_MIN i oddswindow.py), med det tidspunktet som stempel,
 * så den frosne prognosen aldri bygger på en pris fra etter sluttoddsvinduet.
 * Selve skrivingen kommer noen sekunder etter hentingen (Chrome, siden). Den
 * får lande senest SKRIVESTOPP_MIN = 10 minutter før avspark (TIL_MIN i
 * prekick_vindu.py, der porten stenger): ellers ville en kjøring som hentet
 * 16 minutter før og skrev 14 minutter før, mistet den siste prisen. Senere
 * enn 10 minutter før avspark skriver ingen raden.
 */
const VINDU_MIN = 70, BUFFER_MIN = 10, SLUTT_MIN = 15, SKRIVESTOPP_MIN = 10;

// Minutter Europe/Oslo ligger foran UTC ved et gitt UTC-tidspunkt.
function osloForskyvning(utcMs) {
  const f = new Intl.DateTimeFormat('en-GB', {timeZone: 'Europe/Oslo', hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'});
  const p = Object.fromEntries(f.formatToParts(new Date(utcMs)).map(x => [x.type, x.value]));
  return (Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - utcMs) / 60000;
}

// Avsparket i millisekunder UTC for dato (YYYY-MM-DD) og klokkeslett (HH:MM) i norsk tid.
function avsparkUtcMs(dato, tid) {
  const [Y, M, D] = dato.split('-').map(Number);
  const [h, m] = (tid || '00:00').split(':').map(Number);
  const naiv = Date.UTC(Y, M - 1, D, h, m);
  let t = naiv - osloForskyvning(naiv) * 60000;
  t = naiv - osloForskyvning(t) * 60000;   // andre runde: riktig på dager med tidsskifte
  return t;
}

// {"hjemme|borte": avspark i ms UTC} fra fixtures.json (liste av runder).
function avsparkFraTerminliste(fixtures) {
  const ut = {};
  for (const r of fixtures || []) for (const m of r.matches || []) {
    ut[`${m.home}|${m.away}`] = avsparkUtcMs(m.date, m.time);
  }
  return ut;
}

const MIN = 60000;
// Datajobbene lar raden være fra 80 minutter før avspark.
function datajobbenHopperOver(a, naaMs) {
  return a != null && naaMs < a && naaMs >= a - (VINDU_MIN + BUFFER_MIN) * MIN;
}
// "Odds nær avspark" skriver raden når oddsen i kjøringen ble hentet 70 til
// 15 minutter før avspark, og skrivingen lander senest 10 minutter før. Alle
// grensene er med, som i porten og i sluttoddsvinduet.
//   oddstidMs  da kjøringen hentet oddsen (porten), ms UTC
//   ekteMs     klokken når raden skrives
function prekickSkriver(a, oddstidMs, ekteMs = oddstidMs) {
  return a != null && oddstidMs >= a - VINDU_MIN * MIN && oddstidMs <= a - SLUTT_MIN * MIN
    && ekteMs >= oddstidMs && ekteMs <= a - SKRIVESTOPP_MIN * MIN;
}

/* Oppdaterer prekick-innholdet på stedet og returnerer tellinger.
 *   gml      {version, matches: {...}} slik filen står
 *   pre      {nøkkel: rad} for kamper som er uspilte NÅ (fra siden)
 *   spilte   nøkler for kamper som er spilt nå
 *   avspark  {"hjemme|borte": ms UTC}
 *   naaMs    klokken nå, ms UTC ('bare-vindu': da oddsen ble hentet)
 *   stempel  ISO-stempel for rader som skrives nå
 *   modus    'alle' | 'uten-vindu' | 'bare-vindu', se over
 *   ekteMs   'bare-vindu': klokken når raden skrives (standard naaMs)
 */
function oppdaterPrekick(gml, pre, spilte, avspark, naaMs, stempel, modus = 'alle', ekteMs = naaMs) {
  if (!['alle', 'uten-vindu', 'bare-vindu'].includes(modus)) throw new Error(`ukjent modus ${modus}`);
  gml.matches = gml.matches || {};
  let nye = 0, oppdatert = 0, etterAvspark = 0, frosne = 0, vinduHoppet = 0;
  for (const [k, v] of Object.entries(pre)) {
    // En frosset rad røres aldri.
    if (gml.matches[k] && gml.matches[k].frosset) continue;
    // Etter avspark: raden står som den var (eller mangler, hvis den aldri
    // ble skrevet før avspark). Den fryses når resultatet kommer.
    const a = avspark[`${v.home}|${v.away}`];
    if (a != null && Math.max(naaMs, ekteMs) >= a) { etterAvspark++; continue; }
    if (modus === 'uten-vindu' && datajobbenHopperOver(a, naaMs)) { vinduHoppet++; continue; }
    if (modus === 'bare-vindu' && !prekickSkriver(a, naaMs, ekteMs)) continue;
    if (gml.matches[k]) oppdatert++; else nye++;
    gml.matches[k] = {...v, stamp: stempel};
  }
  if (modus !== 'bare-vindu') {
    for (const k of spilte) {
      if (gml.matches[k] && !gml.matches[k].frosset) { gml.matches[k].frosset = true; frosne++; }
    }
  }
  return {nye, oppdatert, etterAvspark, frosne, vinduHoppet};
}

// Kampene ("hjemme|borte") som prekick-odds.yml skal skrive raden for nå
// (uspilte, se prekickSkriver), fra fixtures.json.
function kamperIVinduet(fixtures, oddstidMs, ekteMs = oddstidMs) {
  const ut = [];
  for (const r of fixtures || []) for (const m of r.matches || []) {
    if (m.played || !m.time) continue;
    if (prekickSkriver(avsparkUtcMs(m.date, m.time), oddstidMs, ekteMs)) ut.push(`${m.home}|${m.away}`);
  }
  return ut;
}

module.exports = {osloForskyvning, avsparkUtcMs, avsparkFraTerminliste, oppdaterPrekick, kamperIVinduet,
                  datajobbenHopperOver, prekickSkriver, VINDU_MIN, BUFFER_MIN, SLUTT_MIN, SKRIVESTOPP_MIN};
