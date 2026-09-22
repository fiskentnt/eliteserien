#!/usr/bin/env node
/* Lagrer to ting, begge lest ut av selve siden:
 *
 *   eliteserien/data/history.json   lagenes sannsynligheter (gull, Europa,
 *                                   kvalik, nedrykk) hver gang nye resultater
 *                                   har kommet inn -- ett punkt per runde.
 *   eliteserien/data/keymatch.json  rundens viktigste kamp, med den ferdige
 *                                   banner-setningen. Siden viser den med en
 *                                   gang ved innlasting i stedet for å regne
 *                                   den ut i nettleseren.
 *   eliteserien/data/lastmatch.json hva forrige kamp betydde, for alle 16 lag
 *                                   -- linja nederst i lagboksen.
 *
 * Tallene hentes fra selve siden (headless Chrome), ikke fra en egen
 * gjenskapning av modellen: da er de nøyaktig de samme som tabellen viser,
 * med samme styrker, odds og 10 000 simuleringer (fast frø per scenario, så
 * samme datagrunnlag gir samme tall). Ingen visning bruker filen ennå.
 *
 * Bruk (fra repo-roten):
 *   NODE_PATH=<mappe med puppeteer-core> node scripts/snapshot_probs.js
 *   CHROME_PATH=/sti/til/chrome  (valgfritt; ellers letes vanlige steder)
 *
 * Et nytt historikkpunkt legges til bare når fingeravtrykket av de spilte
 * kampene (dato, lag og resultat) er et annet enn i forrige punkt, så filen
 * vokser bare når noe faktisk har skjedd. keymatch.json skrives når innholdet
 * er endret -- den avhenger også av oddsen, som oppdateres oftere enn
 * resultatene. lastmatch.json skrives på samme vilkår.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.join(__dirname, '..');
const HISTORY = path.join(ROOT, 'eliteserien', 'data', 'history.json');
const KEYMATCH = path.join(ROOT, 'eliteserien', 'data', 'keymatch.json');
const LASTMATCH = path.join(ROOT, 'eliteserien', 'data', 'lastmatch.json');
const MIME = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.json':'application/json','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.ttf':'font/ttf'};

function serve() {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p.endsWith('/')) p += 'index.html';
    const f = path.join(ROOT, p);
    if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, {'Content-Type': MIME[path.extname(f)] || 'application/octet-stream'});
    fs.createReadStream(f).pipe(res);
  });
  return new Promise(r => server.listen(0, '127.0.0.1', () => r(server)));
}

function chromePath() {
  const c = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  const found = c.find(x => fs.existsSync(x));
  if (!found) throw new Error('Fant ikke Chrome (sett CHROME_PATH)');
  return found;
}

(async () => {
  const puppeteer = require('puppeteer-core');
  const server = await serve();
  const port = server.address().port;
  const browser = await puppeteer.launch({executablePath: chromePath(), headless: 'new', args: ['--no-sandbox', '--disable-setuid-sandbox']});
  try {
    const page = await browser.newPage();
    const errs = [];
    page.on('pageerror', e => errs.push(e.message));
    await page.goto(`http://127.0.0.1:${port}/eliteserien/`, {waitUntil: 'domcontentloaded'});
    await page.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 180000});
    const snap = await page.evaluate(() => {
      if (matches.some(m => m.sim || (m.hg != null && !m.played && m.sim))) throw new Error('Siden har simulerte resultater');
      const teams = {};
      TEAMS.forEach(t => {
        // Sonene leses fra sidens egen LEAGUE gjennom zoneSum, ikke fra faste
        // plasseringer her: "europa" er topp 4 i Eliteserien og topp 6 i OBOS.
        const d = lastMC[t];
        teams[t] = {gull: zoneSum(d, 'gull'), europa: zoneSum(d, 'europa'),
                    kvalik: zoneSum(d, 'kvalik'), nedrykk: zoneSum(d, 'nedrykk')};
      });
      return {
        round: ROUND_SEQ[currentRoundIdx()].round,
        played: MATCHES.length,
        lastMatch: MATCHES.reduce((a, m) => m.date > a ? m.date : a, ''),
        games: MATCHES.map(m => `${m.date}|${m.home}|${m.away}|${m.hg}-${m.ag}`).sort(),
        teams
      };
    });
    // Rundens viktigste kamp. Samme regnestykke som spørsmålet i "Spør om
    // tabellen" (qaKeyRoundData), og banner-setningen bygges av sidens egen
    // qaKeyBanner, så ordlyden finnes bare ett sted.
    const key = await page.evaluate(async () => {
      const d = await qaKeyRoundData();
      const banner = qaKeyBanner(d);
      if (!d || !d.best || !banner) return null;
      return {round: d.round, banner,
        match: {home: d.best.m.home, away: d.best.m.away, date: d.best.m.date},
        zone: d.best.topZone.key,
        teams: d.best.teams.map(t => t.team)};
    });
    if (errs.length) console.warn('Sidefeil:', errs.join('; '));
    if (key) {
      const next = {version: 1, note: 'Rundens viktigste kamp, regnet ut av scripts/snapshot_probs.js etter hver oppdatering. Banneret på siden viser "banner" som den er.', ...key};
      const same = fs.existsSync(KEYMATCH) && (() => {
        const old = JSON.parse(fs.readFileSync(KEYMATCH, 'utf8'));
        return old.banner === next.banner && old.round === next.round && JSON.stringify(old.teams) === JSON.stringify(next.teams);
      })();
      if (same) console.log('Rundens viktigste kamp uendret.');
      else {
        fs.writeFileSync(KEYMATCH, JSON.stringify({...next, updated: new Date().toISOString().replace(/\.\d+Z$/, 'Z')}, null, 1) + '\n');
        console.log('Skrev keymatch.json:', next.banner);
      }
    } else {
      console.log('Ingen viktigste kamp å lagre (ingen runde igjen, eller ingen kamp flytter nok).');
    }
    // Hva forrige kamp betydde, for alle 16 lag. Samme regnestykke som
    // spørsmålet i "Spør om tabellen" (qaLastMatchData), og siden bygger selve
    // linja av disse feltene (qaLastMatchLine), så ordlyden finnes ett sted.
    const lastPer = await page.evaluate(async () => {
      const out = {};
      for (const t of TEAMS) {
        const d = await qaLastMatchData(t);
        if (!d || d.noMatch) continue;
        out[t] = {
          date: d.m.date, home: d.m.home, away: d.m.away, hg: d.m.hg, ag: d.m.ag,
          opp: d.opp, gf: d.gf, ga: d.ga, actual: d.actual,
          zone: d.zone.key, chance: QA_CHANCE[d.zone.key],
          pp: d.pp, good: d.good
        };
      }
      return out;
    });
    if (Object.keys(lastPer).length) {
      const next = {version: 1, note: 'Hva forrige kamp betydde per lag, regnet ut av scripts/snapshot_probs.js. Siden bygger linja i lagboksen av feltene her.', teams: lastPer};
      const cmp = o => JSON.stringify(Object.fromEntries(Object.entries(o || {}).sort()));
      const old = fs.existsSync(LASTMATCH) ? JSON.parse(fs.readFileSync(LASTMATCH, 'utf8')) : null;
      if (old && cmp(old.teams) === cmp(next.teams)) console.log('Forrige kamp uendret for alle lag.');
      else {
        fs.writeFileSync(LASTMATCH, JSON.stringify({...next, updated: new Date().toISOString().replace(/\.\d+Z$/, 'Z')}, null, 1) + '\n');
        console.log(`Skrev lastmatch.json for ${Object.keys(lastPer).length} lag.`);
      }
    }
    const fingerprint = crypto.createHash('sha1').update(snap.games.join('\n')).digest('hex').slice(0, 12);
    let hist = {version: 1, note: 'Sannsynligheter (0 til 1) etter hver oppdatering med nye resultater. Se scripts/snapshot_probs.js.', snapshots: []};
    if (fs.existsSync(HISTORY)) hist = JSON.parse(fs.readFileSync(HISTORY, 'utf8'));
    const last = hist.snapshots[hist.snapshots.length - 1];
    if (last && last.fingerprint === fingerprint) { console.log('Ingen nye resultater siden forrige punkt.'); return; }
    const r4 = x => Math.round(x * 10000) / 10000;
    const teams = {};
    Object.keys(snap.teams).sort((a, b) => a.localeCompare(b, 'no')).forEach(t => {
      teams[t] = {}; Object.keys(snap.teams[t]).forEach(k => teams[t][k] = r4(snap.teams[t][k]));
    });
    hist.snapshots.push({
      date: snap.lastMatch, round: snap.round, played: snap.played,
      updated: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
      fingerprint, teams
    });
    fs.writeFileSync(HISTORY, JSON.stringify(hist, null, 1) + '\n');
    console.log(`La til punkt: runde ${snap.round}, ${snap.played} kamper spilt, ${snap.lastMatch}.`);
  } finally {
    await browser.close(); server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
