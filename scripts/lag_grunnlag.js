#!/usr/bin/env node
/* Grunnlagsfilen (<liga>/data/grunnlag.json): tabellen og svarene med låste
 * utfall for dagens stilling, regnet på forhånd med N = GRUNNLAG_N sesonger
 * per oppgave (100 000), med sidens EGEN kode i Chrome: grunnlagRegn() på
 * siden, i poolen maskinen gir. Se kommentaren ved GRUNNLAG_VERSJON i
 * eliteserien/index.html for hva filen inneholder.
 *
 * Kjøres av .github/workflows/grunnlag.yml. Skriver filen bare når alt har
 * gått bra:
 *   - siden har ingen resultater fylt inn, og dataene ble ikke endret mens
 *     den regnet (grunnlagRegn sjekker avtrykket før og etter)
 *   - en NY lasting av siden regner det samme fingeravtrykket
 *   - hver fordeling går opp: hvert lag har én plass og hver plass ett lag i
 *     hver sesong, så radene og kolonnene summerer til N
 * Feiler noe, står den forrige filen urørt, og kjøringen avslutter med 1.
 *
 *   NODE_PATH=<puppeteer-core> node scripts/lag_grunnlag.js <side> [--ut <mappe>] [--inndata <hash>]
 *   side      eliteserien | obos | elo-test (sidens mappe)
 *   --ut      mappen filen skrives til (standard <side>/data; testsiden:
 *             elo-test/emodell)
 *   --inndata sha256 av inndatafilene fra scripts/grunnlag_port.py, lagres i
 *             filen så porten kan se om noe er endret siden
 *   --n       BARE for testene: annen N enn sidens GRUNNLAG_N. Avtrykket
 *             regnes med den N-en, så siden godtar aldri en slik fil.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const ARGS = process.argv.slice(2);
const flagg = navn => { const i = ARGS.indexOf(navn); return i >= 0 ? ARGS[i + 1] : null; };
const SIDE = ARGS.filter((a, i) => !a.startsWith('--') && !(i > 0 && ['--ut', '--inndata', '--n'].includes(ARGS[i - 1])))[0];
if (!SIDE) { console.error('Bruk: node scripts/lag_grunnlag.js <side> [--ut <mappe>] [--inndata <hash>]'); process.exit(2); }
const UT = path.resolve(ROOT, flagg('--ut') || path.join(SIDE, 'data'));
const FIL = path.join(UT, 'grunnlag.json');
const INNDATA = flagg('--inndata');
const TEST_N = flagg('--n') != null ? +flagg('--n') : null;
if (TEST_N != null && !(Number.isInteger(TEST_N) && TEST_N > 0)) { console.error(`--n: ugyldig ${flagg('--n')}`); process.exit(2); }
const MIME = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.ttf': 'font/ttf'};

function chromePath() {
  const c = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  const f = c.find(x => fs.existsSync(x));
  if (!f) throw new Error('Fant ikke Chrome (sett CHROME_PATH)');
  return f;
}

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

// Én fersk side, lastet ferdig (tabellsimuleringen i nettleseren er ferdig,
// så den ikke deler kjernene med regningen).
async function aapne(browser, port, feil) {
  const page = await browser.newPage();
  page.on('pageerror', e => feil.push(e.message));
  const svar = await page.goto(`http://127.0.0.1:${port}/${SIDE}/`, {waitUntil: 'domcontentloaded'});
  if (!svar || !svar.ok()) throw new Error(`/${SIDE}/ svarte ${svar ? svar.status() : 'ikke'}`);
  await page.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 180000, polling: 100});
  if (!(await page.evaluate(() => typeof grunnlagRegn === 'function')))
    throw new Error(`/${SIDE}/ har ikke grunnlagRegn()`);
  return page;
}

// Hver fordeling: n*n antall (lag*n + plass). Hvert lag har én plass, og hver
// plass ett lag, i hver av de N sesongene.
function sjekkFordelinger(r) {
  const n = r.lag.length, feil = [];
  for (const [id] of r.oppgaver) {
    const u = r.utfall[id];
    if (!Array.isArray(u) || u.length !== n * n || !u.every(x => Number.isInteger(x) && x >= 0)) { feil.push(`${id}: feil form`); continue; }
    for (let i = 0; i < n; i++) {
      let rad = 0, kol = 0;
      for (let j = 0; j < n; j++) { rad += u[i * n + j]; kol += u[j * n + i]; }
      if (rad !== r.sesonger || kol !== r.sesonger) { feil.push(`${id}: lag/plass ${i} summerer til ${rad}/${kol}, ikke ${r.sesonger}`); break; }
    }
  }
  return feil;
}

(async () => {
  const puppeteer = require('puppeteer-core');
  const server = await serve();
  const port = server.address().port;
  const browser = await puppeteer.launch({executablePath: chromePath(), headless: 'new', protocolTimeout: 3600000,
    args: ['--no-sandbox', '--disable-setuid-sandbox']});
  const feil = [];
  try {
    const page = await aapne(browser, port, feil);
    const t0 = Date.now();
    const r = await page.evaluate(N => grunnlagRegn(N == null ? undefined : N), TEST_N);
    const sek = (Date.now() - t0) / 1000;
    const kjerner = await page.evaluate(() => [poolWorkers.length, navigator.hardwareConcurrency]);
    await page.close();
    console.log(`${SIDE}: ${r.oppgaver.length} oppgaver x ${r.sesonger} sesonger på ${sek.toFixed(1)} s ` +
      `(pool ${kjerner[0]}, ${kjerner[1]} kjerner), avtrykk ${r.fingeravtrykk.slice(0, 16)}...`);

    // En ny lasting av siden skal regne samme avtrykk: ellers ville siden
    // aldri godta filen.
    const ny = await aapne(browser, port, feil);
    const igjen = await ny.evaluate(N => grunnlagAvtrykk(N), r.sesonger);
    await ny.close();
    if (igjen !== r.fingeravtrykk) throw new Error(`en ny lasting av siden ga et annet avtrykk (${igjen.slice(0, 16)}... mot ${r.fingeravtrykk.slice(0, 16)}...)`);
    const f = sjekkFordelinger(r);
    if (f.length) throw new Error(`fordelingene går ikke opp: ${f.slice(0, 3).join('; ')}`);
    if (feil.length) throw new Error(`JS-feil på siden: ${feil.slice(0, 3).join('; ')}`);

    // Én linje per oppgave, så filen er lesbar og diffen følger oppgavene.
    const hode = {versjon: r.versjon, side: SIDE, sesonger: r.sesonger, laget: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
      fingeravtrykk: r.fingeravtrykk, inndata: INNDATA || null, lag: r.lag,
      note: 'Tabellen og svarene med låste utfall for dagens stilling, regnet på forhånd av scripts/lag_grunnlag.js med sidens egen kode. utfall[oppgave][lag*n + plass] = antall sesonger. Brukes bare når fingeravtrykket stemmer med det siden selv regner, og ingen resultater er fylt inn.'};
    const linjer = Object.entries(hode).map(([k, v]) => ` ${JSON.stringify(k)}: ${JSON.stringify(v)}`);
    linjer.push(` "oppgaver": [\n${r.oppgaver.map(o => `  ${JSON.stringify(o)}`).join(',\n')}\n ]`);
    linjer.push(` "utfall": {\n${r.oppgaver.map(([id]) => `  ${JSON.stringify(id)}: ${JSON.stringify(r.utfall[id])}`).join(',\n')}\n }`);
    fs.mkdirSync(UT, {recursive: true});
    const tmp = FIL + '.tmp';
    fs.writeFileSync(tmp, `{\n${linjer.join(',\n')}\n}\n`);
    try { JSON.parse(fs.readFileSync(tmp, 'utf8')); }   // gyldig JSON før den erstatter den gamle
    catch (e) { fs.unlinkSync(tmp); throw e; }
    fs.renameSync(tmp, FIL);
    console.log(`Skrev ${FIL.startsWith(ROOT) ? path.relative(ROOT, FIL) : FIL} (${(fs.statSync(FIL).size / 1024).toFixed(0)} KB).`);
    if (process.env.GITHUB_STEP_SUMMARY)
      fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `- ${SIDE}: ${r.oppgaver.length} oppgaver x ${r.sesonger} sesonger på ${sek.toFixed(0)} s\n`);
  } finally {
    await browser.close(); server.close();
  }
})().catch(e => { console.error(`Grunnlagsfilen for ${SIDE} ble IKKE skrevet: ${e.message || e}`); process.exit(1); });
