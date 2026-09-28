#!/usr/bin/env node
/* Måling før del 2 (svarene og tabellen for dagens stilling regnet på forhånd):
 * hvor lang tid tar forhåndsregningen i CI med N sesonger per oppgave?
 *
 * Regner, med sidens EGEN kode i Chrome og poolen den får på maskinen den
 * kjører på (navigator.hardwareConcurrency, høyst 8), nøyaktig oppgavene
 * filen skal inneholde:
 *   - utgangspunktet uten låst kamp (tabellen)
 *   - H, U og B for hver kamp i neste runde
 *   - H og B for alle andre åpne kamper ("Hvilke kamper betyr mest?")
 * alle med hele plasseringsfordelingen (wantAll) og samme frø. Skriver
 * ingenting, verken filer eller commits: bare tider til loggen og
 * GITHUB_STEP_SUMMARY.
 *
 *   NODE_PATH=<puppeteer-core> node scripts/maal_grunnlag.js [N] [side ...]
 *   standard: N = 100000, sider eliteserien obos elo-test
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.join(__dirname, '..');
const ARGS = process.argv.slice(2);
const N = +(ARGS.find(a => /^\d+$/.test(a)) || 100000);
const SIDER = ARGS.filter(a => !/^\d+$/.test(a));
if (!SIDER.length) SIDER.push('eliteserien', 'obos', 'elo-test');
const MIME = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png'};

function chromePath() {
  const c = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  const f = c.find(x => fs.existsSync(x));
  if (!f) throw new Error('Fant ikke Chrome (sett CHROME_PATH)');
  return f;
}

(async () => {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p.endsWith('/')) p += 'index.html';
    const f = path.join(ROOT, p);
    if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, {'Content-Type': MIME[path.extname(f)] || 'application/octet-stream'});
    fs.createReadStream(f).pipe(res);
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const browser = await puppeteer.launch({executablePath: chromePath(), headless: 'new', protocolTimeout: 3600000,
    args: ['--no-sandbox', '--disable-setuid-sandbox']});
  const linjer = [];
  try {
    for (const side of SIDER) {
      const page = await browser.newPage();
      const t0 = Date.now();
      await page.goto(`http://127.0.0.1:${server.address().port}/${side}/`, {waitUntil: 'domcontentloaded'});
      await page.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 300000, polling: 100});
      const lastet = (Date.now() - t0) / 1000;
      const r = await page.evaluate(async N => {
        const {P0, G0, F0, open, openMatches, oddsOverride, scenarioKey} = buildQaOpen();
        const nr = qaNextRoundMatches(openMatches), iNeste = new Set(nr.list.map(m => openMatches.indexOf(m)));
        const tasks = [{id: 'base', idx: -1, score: null}];
        openMatches.forEach((m, idx) => {
          tasks.push({id: idx + ':H', idx, score: forcedScoreline(m.home, m.away, true)},
                     {id: idx + ':B', idx, score: forcedScoreline(m.home, m.away, false)});
          if (iNeste.has(idx)) tasks.push({id: idx + ':U', idx, score: forcedDrawScoreline(m.home, m.away)});
        });
        const t = performance.now();
        await runZoneTasks({mu: MODEL.mu, H: MODEL.H, k: FORM_K,
          att: Array.from(LIVE.att), con: Array.from(LIVE.con), ha: Array.from(LIVE.ha), hc: Array.from(LIVE.hc),
          P0: Array.from(P0), G0: Array.from(G0), F0: Array.from(F0), open, oddsOverride,
          N, ti: 0, zone: QA_KEY_ZONES[0], seed: hashStr(scenarioKey + '|impact'), wantAll: true}, tasks, null, 'maaling');
        return {aapne: open.length, oppgaver: tasks.length, s: (performance.now() - t) / 1000,
                kjerner: navigator.hardwareConcurrency, pool: poolWorkers.length};
      }, N);
      const l = `${side}: ${r.aapne} åpne kamper, ${r.oppgaver} oppgaver x ${N} sesonger, pool ${r.pool} (${r.kjerner} kjerner): ` +
        `${r.s.toFixed(1)} s regning, ${lastet.toFixed(1)} s lasting (${Math.round(r.oppgaver * N / r.s)} sesonger/s)`;
      console.log(l); linjer.push(l);
      await page.close();
    }
  } finally {
    await browser.close(); server.close();
  }
  if (process.env.GITHUB_STEP_SUMMARY)
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, '### Forhåndsregning, målt\n\n' + linjer.map(l => `- ${l}`).join('\n') + '\n');
})().catch(e => { console.error(e); process.exit(1); });
