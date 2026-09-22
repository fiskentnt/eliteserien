#!/usr/bin/env node
/* Lagrer lagenes sannsynligheter (gull, Europa, kvalik, nedrykk) i
 * eliteserien/data/history.json hver gang nye resultater har kommet inn.
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
 * Et nytt punkt legges til bare når fingeravtrykket av de spilte kampene
 * (dato, lag og resultat) er et annet enn i forrige punkt. Ellers skjer
 * ingenting, så filen vokser bare når noe faktisk har skjedd.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.join(__dirname, '..');
const HISTORY = path.join(ROOT, 'eliteserien', 'data', 'history.json');
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
        const d = lastMC[t];
        teams[t] = {gull: d[0], europa: d[0]+d[1]+d[2]+d[3], kvalik: d[13], nedrykk: d[14]+d[15]};
      });
      return {
        round: ROUND_SEQ[currentRoundIdx()].round,
        played: MATCHES.length,
        lastMatch: MATCHES.reduce((a, m) => m.date > a ? m.date : a, ''),
        games: MATCHES.map(m => `${m.date}|${m.home}|${m.away}|${m.hg}-${m.ag}`).sort(),
        teams
      };
    });
    if (errs.length) console.warn('Sidefeil:', errs.join('; '));
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
