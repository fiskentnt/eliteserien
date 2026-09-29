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
 *   - innsiktsblokken er regnet fra de samme sesongene som tabellen: for hvert
 *     lag og hver sone er antall sesonger laget nådde målet det samme som
 *     tabellens ('base') plasseringer i sonen gir, og hver telling går opp
 *   - en ny lasting av siden med den NYE filen godtar den (GRUNNLAG_STATUS
 *     "i bruk")
 *
 * BANNERET (keymatch.json i samme mappe) regnes i den samme lastingen, fra
 * filen: rundens viktigste kamp med qaKeyRoundData(), altså akkurat det svaret
 * i "Spør om tabellen" gir med filen, og keymatchFra() på siden. Filen og
 * banneret skrives sammen, eller ingen av dem. Feiler noe, står de forrige
 * filene urørt, og kjøringen avslutter med 1.
 *
 *   NODE_PATH=<puppeteer-core> node scripts/lag_grunnlag.js <side> [--ut <mappe>] [--inndata <hash>]
 *   side      eliteserien | obos | elo-test (sidens mappe)
 *   --ut      mappen filen skrives til (standard <side>/data; testsiden:
 *             elo-test/emodell)
 *   --inndata sha256 av inndatafilene fra scripts/grunnlag_port.py, lagres i
 *             filen så porten kan se om noe er endret siden
 *   --n       BARE for testene: annen N enn sidens GRUNNLAG_N. Avtrykket
 *             regnes med den N-en, så siden godtar aldri en slik fil; derfor
 *             prøves den ikke på siden, og banneret skrives ikke.
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

// Filer serveren gir med annet innhold enn på disk (den nye grunnlagsfilen,
// før den er skrevet).
const OVERSTYR = new Map();
function serve() {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p.endsWith('/')) p += 'index.html';
    if (OVERSTYR.has(p)) { res.writeHead(200, {'Content-Type': 'application/json'}); res.end(OVERSTYR.get(p)); return; }
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

// Innsiktsblokken mot tabellen ('base'): hver telling dekker N sesonger, og
// sesongene der laget nådde målet i en sone er like mange som tabellens
// plasseringer i sonen gir. Det holder bare når blokken er regnet fra de samme
// sesongene. Et lag er aldri ved siden av seg selv eller det b-te beste av
// "de andre".
function sjekkInnsikt(r) {
  const n = r.lag.length, N = r.sesonger, b = r.innsikt, base = r.utfall.base, feil = [];
  const sum = a => a.reduce((s, x) => s + x, 0);
  if (!b || JSON.stringify(b.soner) !== JSON.stringify(r.soner.map(z => z.key)) || !Array.isArray(b.lag) || b.lag.length !== n)
    return ['feil form (sonene eller lagene)'];
  b.lag.forEach((x, t) => {
    const navn = r.lag[t];
    if (sum(x.poeng) !== N) feil.push(`${navn}: poengene summerer til ${sum(x.poeng)}`);
    if (x.foran[t] || x.bak[t]) feil.push(`${navn}: ved siden av seg selv`);
    if (sum(x.foran) !== N - base[t * n]) feil.push(`${navn}: rett foran summerer til ${sum(x.foran)}, ikke ${N - base[t * n]}`);
    if (sum(x.bak) !== N - base[t * n + n - 1]) feil.push(`${navn}: rett bak summerer til ${sum(x.bak)}, ikke ${N - base[t * n + n - 1]}`);
    r.soner.forEach((z, zi) => {
      const lo = z.dir === 'front' ? z.lo : 1, hi = z.dir === 'front' ? z.hi : z.boundary;
      let tabell = 0;
      for (let k = lo; k <= hi; k++) tabell += base[t * n + k - 1];
      if (sum(x.suksess[zi]) !== tabell) feil.push(`${navn} ${z.key}: ${sum(x.suksess[zi])} sesonger i mål, tabellen gir ${tabell}`);
      if (x.suksess[zi].some((s, p) => s > x.poeng[p])) feil.push(`${navn} ${z.key}: flere i mål enn med poengsummen`);
      if (sum(x.bLag[zi]) !== N || x.bLag[zi][t]) feil.push(`${navn} ${z.key}: det b-te beste av de andre går ikke opp`);
      if (sum(x.avgjort[zi]) !== N) feil.push(`${navn} ${z.key}: avgjort summerer til ${sum(x.avgjort[zi])}`);
    });
  });
  return feil;
}

// keymatch.json ved siden av filen. Uendret banner (samme kåring, runde, lag,
// sesonger og grense) skrives ikke på nytt, så et nytt tidsstempel alene ikke
// gir en commit.
function skrivBanner(key) {
  const KEYMATCH = path.join(UT, 'keymatch.json');
  if (!key) { console.log('Ingen viktigste kamp å lagre (ingen runde igjen, eller ingen kamp flytter nok).'); return; }
  const next = {version: 1, note: 'Rundens viktigste kamp, regnet fra grunnlagsfilen av scripts/lag_grunnlag.js, med de samme tallene som svaret i "Spør om tabellen". Banneret på siden viser "banner" som den er.', ...key};
  const same = fs.existsSync(KEYMATCH) && (() => {
    const old = JSON.parse(fs.readFileSync(KEYMATCH, 'utf8'));
    return old.banner === next.banner && old.round === next.round && JSON.stringify(old.teams) === JSON.stringify(next.teams)
      && old.sesonger === next.sesonger && old.grense === next.grense && JSON.stringify(old.match) === JSON.stringify(next.match);
  })();
  if (same) { console.log('Rundens viktigste kamp uendret.'); return; }
  fs.writeFileSync(KEYMATCH, JSON.stringify({...next, updated: new Date().toISOString().replace(/\.\d+Z$/, 'Z')}, null, 1) + '\n');
  console.log(`Skrev ${path.relative(ROOT, KEYMATCH)}: ${next.banner}`);
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `  - banneret: ${next.banner}\n`);
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
    const r = await page.evaluate(async N => ({...await grunnlagRegn(N == null ? undefined : N), soner: innsiktSoner()}), TEST_N);
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
    const fi = sjekkInnsikt(r);
    if (fi.length) throw new Error(`innsiktsblokken går ikke opp mot tabellen: ${fi.slice(0, 3).join('; ')}`);

    // Én linje per oppgave, så filen er lesbar og diffen følger oppgavene.
    const hode = {versjon: r.versjon, side: SIDE, sesonger: r.sesonger, laget: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
      fingeravtrykk: r.fingeravtrykk, inndata: INNDATA || null, lag: r.lag,
      note: 'Tabellen og svarene med låste utfall for dagens stilling, regnet på forhånd av scripts/lag_grunnlag.js med sidens egen kode. utfall[oppgave][lag*n + plass] = antall sesonger. innsikt: tellingene bak "Hvorfor har ...?", "Hva må ... gjøre?", "Når kan det være avgjort?" og "Hvem kjemper ... mot?" for de samme sesongene som utfall.base, per lag (i samme rekkefølge som lag) og sone. Brukes bare når fingeravtrykket stemmer med det siden selv regner, og ingen resultater er fylt inn.'};
    const linjer = Object.entries(hode).map(([k, v]) => ` ${JSON.stringify(k)}: ${JSON.stringify(v)}`);
    linjer.push(` "oppgaver": [\n${r.oppgaver.map(o => `  ${JSON.stringify(o)}`).join(',\n')}\n ]`);
    linjer.push(` "utfall": {\n${r.oppgaver.map(([id]) => `  ${JSON.stringify(id)}: ${JSON.stringify(r.utfall[id])}`).join(',\n')}\n }`);
    linjer.push(` "innsikt": {\n  "soner": ${JSON.stringify(r.innsikt.soner)},\n  "runder": ${JSON.stringify(r.innsikt.runder)},\n  "lag": [\n` +
      `${r.innsikt.lag.map(x => `   ${JSON.stringify(x)}`).join(',\n')}\n  ]\n }`);
    const tekst = `{\n${linjer.join(',\n')}\n}\n`;
    JSON.parse(tekst);   // gyldig JSON

    // Siden med den NYE filen: den skal godta den, og banneret regnes fra den.
    let key;
    if (TEST_N == null) {
      const p0 = await browser.newPage();
      await p0.goto(`http://127.0.0.1:${port}/${SIDE}/`, {waitUntil: 'domcontentloaded'});
      await p0.waitForFunction('typeof grunnlagFil==="function"', {timeout: 60000});
      const sti = await p0.evaluate(() => new URL(grunnlagFil(), location.href).pathname);
      await p0.close();
      OVERSTYR.set(sti, tekst);
      const pv = await aapne(browser, port, feil);
      await pv.waitForFunction('GRUNNLAG_STATUS!=="venter"', {timeout: 60000, polling: 50});
      const v = await pv.evaluate(async () => {
        const status = GRUNNLAG_STATUS;
        if (status !== 'i bruk') return {status};
        return {status, N: lastMCN, key: keymatchFra(await qaKeyRoundData())};
      });
      await pv.close();
      OVERSTYR.delete(sti);
      if (v.status !== 'i bruk') throw new Error(`siden godtok ikke den nye filen (${v.status})`);
      if (v.N !== r.sesonger) throw new Error(`tabellen på siden bygger på ${v.N} sesonger, ikke filens ${r.sesonger}`);
      if (v.key && v.key.sesonger !== r.sesonger) throw new Error(`banneret bygger på ${v.key.sesonger} sesonger, ikke filens ${r.sesonger}`);
      key = v.key;
    } else console.log(`Testmodus (--n ${TEST_N}): filen prøves ikke på siden, og banneret skrives ikke.`);
    if (feil.length) throw new Error(`JS-feil på siden: ${feil.slice(0, 3).join('; ')}`);

    fs.mkdirSync(UT, {recursive: true});
    const tmp = FIL + '.tmp';
    fs.writeFileSync(tmp, tekst);
    try { JSON.parse(fs.readFileSync(tmp, 'utf8')); }   // gyldig JSON før den erstatter den gamle
    catch (e) { fs.unlinkSync(tmp); throw e; }
    fs.renameSync(tmp, FIL);
    console.log(`Skrev ${FIL.startsWith(ROOT) ? path.relative(ROOT, FIL) : FIL} (${(fs.statSync(FIL).size / 1024).toFixed(0)} KB).`);
    if (TEST_N == null) skrivBanner(key);
    if (process.env.GITHUB_STEP_SUMMARY)
      fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `- ${SIDE}: ${r.oppgaver.length} oppgaver x ${r.sesonger} sesonger på ${sek.toFixed(0)} s\n`);
  } finally {
    await browser.close(); server.close();
  }
})().catch(e => { console.error(`Grunnlagsfilen for ${SIDE} ble IKKE skrevet: ${e.message || e}`); process.exit(1); });
