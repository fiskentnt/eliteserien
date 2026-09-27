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
 */

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

/* Oppdaterer prekick-innholdet på stedet og returnerer tellinger.
 *   gml      {version, matches: {...}} slik filen står
 *   pre      {nøkkel: rad} for kamper som er uspilte NÅ (fra siden)
 *   spilte   nøkler for kamper som er spilt nå
 *   avspark  {"hjemme|borte": ms UTC}
 *   naaMs    klokken nå, ms UTC
 *   stempel  ISO-stempel for rader som skrives nå
 */
function oppdaterPrekick(gml, pre, spilte, avspark, naaMs, stempel) {
  gml.matches = gml.matches || {};
  let nye = 0, oppdatert = 0, etterAvspark = 0, frosne = 0;
  for (const [k, v] of Object.entries(pre)) {
    // En frosset rad røres aldri.
    if (gml.matches[k] && gml.matches[k].frosset) continue;
    // Etter avspark: raden står som den var (eller mangler, hvis den aldri
    // ble skrevet før avspark). Den fryses når resultatet kommer.
    const a = avspark[`${v.home}|${v.away}`];
    if (a != null && naaMs >= a) { etterAvspark++; continue; }
    if (gml.matches[k]) oppdatert++; else nye++;
    gml.matches[k] = {...v, stamp: stempel};
  }
  for (const k of spilte) {
    if (gml.matches[k] && !gml.matches[k].frosset) { gml.matches[k].frosset = true; frosne++; }
  }
  return {nye, oppdatert, etterAvspark, frosne};
}

module.exports = {osloForskyvning, avsparkUtcMs, avsparkFraTerminliste, oppdaterPrekick};
