/* Chrome-start med romslig tid og ett nytt forsøk (8.10.2026).
 *
 * På GitHubs runnere starter Chrome av og til ikke innen puppeteers 30
 * sekunder ("Timed out after 30000 ms while waiting for the WS endpoint URL"):
 * to ganger i panelsteget i elo-test.yml 7.10. og flere ganger før, og i
 * Chrome-sjekken i kontroll_paneler.py. Ingenting var galt med koden, men
 * kjøringen ble rød og ga e-post. Nå: 90 sekunder, og ett forsøk til. Feiler
 * begge, kastes feilen, og kjøringen blir rød som før.
 *
 *   const {startChrome} = require('./chrome_start');
 *   const browser = await startChrome(puppeteer, {executablePath, headless: 'new', args});
 */
const TIMEOUT_MS = 90000;
const FORSOK = 2;

async function startChrome(puppeteer, opts, {forsok = FORSOK, timeout = TIMEOUT_MS, logg = console.warn} = {}) {
  let sist;
  for (let i = 1; i <= forsok; i++) {
    try {
      return await puppeteer.launch({...opts, timeout});
    } catch (e) {
      sist = e;
      if (i < forsok) logg(`Chrome startet ikke (${e && e.name}: ${String(e && e.message).slice(0, 140)}); prøver igjen (forsøk ${i + 1} av ${forsok}).`);
    }
  }
  throw sist;
}

module.exports = {startChrome, TIMEOUT_MS, FORSOK};
