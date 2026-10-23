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
 * TILLEGGET (5.10.2026): med filen i bruk finner siden kampene "Hvilke kamper
 * betyr mest?" velger for hvert lag (grunnlagKeymatchKamper), og uavgjort for
 * dem som ikke alt har det, regnes med samme frø og N (grunnlagTilleggRegn)
 * og legges i filen som "tillegg". Siden med den ferdige filen skal godta den,
 * og "Hvilke kamper betyr mest?" skal komme helt fra filen for alle lagene.
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
 *   --bare-tekster  regner ingenting: skriver tekster.json (under) fra
 *             grunnlagsfilen som finnes, når siden godtar den
 *
 * TEKSTER.JSON (20.10.2026): med den ferdige filen i bruk hentes det sidene
 * utenfor kalkulatoren trenger, slik siden selv viser det, og skrives til
 * <ut>/tekster.json: tabellen (radene i #tbl som HTML, sortert med innbyrdes
 * oppgjør, og de samme tallene strukturert: poeng, kamper, sjansene med vist
 * tekst og andel) og overskriftene for sjansene, rundens viktigste kamp
 * (bannerteksten), med når filen ble regnet og antall sesonger. Chrome henter, Python lager sidene: scripts/lag_sider.py
 * skriver de statiske delene av sidene fra tekster.json, uten Chrome. Ingen
 * tall regnes utenfor siden. tekster.json teller ikke i grunnlag-porten.
 * Feiler dette, skrives grunnlagsfilen likevel, med en advarsel. Testsiden
 * (elo-test) har ingen statiske sider og får ingen tekster.json.
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
const BARE_TEKSTER = ARGS.includes('--bare-tekster');
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
const SIDEFIL = path.join(ROOT, SIDE, 'index.html');
const TEKSTER = path.join(UT, 'tekster.json');
// Bare ligasidene med statiske regioner (STATISK-*) får tekster.json.
const harStatisk = () => /<!-- STATISK-TABELL -->/.test(fs.readFileSync(SIDEFIL, 'utf8'));
// Det sidene utenfor kalkulatoren trenger, slik siden viser det med filen i
// bruk. Venter til merkene (matematisk avgjort, "–" og "100 %") er regnet for
// denne stillingen.
async function hentTekster(page) {
  await page.waitForFunction('lastMCFinal===true && lastYtterSig===badgeSignatureOf(compute().rows, matches.filter(isEmpty).map(m=>[m.home,m.away]))',
    {timeout: 120000, polling: 100});
  return page.evaluate(async () => {
    // Rundens viktigste kamp: bannerteksten slik siden lager den fra filen
    // (samme som keymatch.json), til oppsummeringen (fase 1a).
    let viktigste = null;
    try { const k = keymatchFra(await qaKeyRoundData()); if (k) viktigste = {banner: k.banner, runde: k.round, sone: k.zone}; } catch (e) {}
    // navn: kolonnen; sone: sonens eget navn i setningene ("direkte opprykk"
    // i OBOS, ikke "opprykk"); tittel: forklaringen på kolonnen.
    const kolonner = ['gull', 'europa', 'ned'].map(key => { const c = LEAGUE.cols.find(x => x.key === key) || {};
      const z = LEAGUE.zones[key === 'ned' ? 'nedrykk' : key] || {};
      return {key, navn: c.head, kort: c.headSm || null, sone: z.label || null, tittel: c.title || null}; });
    const tb = document.querySelector('#tbl tbody'), rad = Object.fromEntries(compute().rows.map(r => [r.name, r]));
    const rader = [...tb.querySelectorAll('tr')].map((tr, i) => {
      const r = rad[tr.dataset.team], d = lastMC[r.name];
      return {plass: i + 1, lag: r.name, kort: shortTeam(r.name), kamper: r.p, v: r.w, u: r.d, t: r.l, maal_for: r.gf, maal_mot: r.ga,
        diff: r.gd, poeng: r.pts, poeng_vist: tr.querySelector('td.pts').textContent, igjen: r.left, maks: r.max,
        sjanser: Object.fromEntries(kolonner.map(c => { const v = zoneSum(d, c.key), st = soneStatus(r.name, c.key);
          return [c.key, {vist: sjanseCelle(v, st).tekst, andel: Math.round(v * 1e6) / 1e6, avgjort: st}]; }))};
    });
    // Det JS fyller over og under tabellen (20.10.2026), slik siden viser det
    // uten lag valgt (statiskeDeler() på siden): ligamenyen, stempelet,
    // fargeforklaringen og de fire boksene. lag_sider.py setter det inn i
    // HTML-en, så ingenting flytter seg når JS tar over.
    const statisk = statiskeDeler();
    // Regelsvarene på spørsmålssidene (20.10.2026): plassene fra LEAGUE
    // (sonene og fargeforklaringen) og siste runde og dato fra terminlisten
    // slik siden har den: de spilte (MATCHES) og de som gjenstår (matches).
    // Soner ligaen ikke har (Champions League i OBOS), er null og hoppes over.
    const terminliste = MATCHES.concat(matches), sisteDato = terminliste.reduce((a, m) => (m.date > a ? m.date : a), '');
    const regler = {soner: Object.fromEntries(Object.entries(LEAGUE.zones).filter(([, z]) => z).map(([k, z]) => [k, {lo: z.lo, hi: z.hi, label: z.label}])),
      baand: LEAGUE.bands.map(b => ({cls: b.cls, lo: b.lo, hi: b.hi, tekst: b.legend})),
      utsatte_runder: Object.fromEntries(Object.entries(LEAGUE.movedRounds || {}).map(([r, v]) => [r, v.label])),
      lag: TEAMS.length, kamper: terminliste.length, siste_runde: Math.max(...terminliste.map(m => m.round)), siste_dato: sisteDato,
      runder_siste_dato: [...new Set(terminliste.filter(m => m.date === sisteDato).map(m => m.round))].sort((a, b) => a - b)};
    // Tabellen som HTML, før noe lag velges under (valgt lag gir markering i radene).
    const kolonnerHtml = ['gullHeader', 'europaHeader', 'nedHeader'].map(id => document.getElementById(id).outerHTML).join('\n          ');
    const raderHtml = tb.innerHTML;
    // Spørsmålssidene (fase 2): for toppsonen (gull; OBOS: direkte opprykk)
    // og nedrykk de aktuelle lagene (sikret, eller minst 1 % i tabellen,
    // størst først, høyst fire) med "Hvorfor"-svaret i Spør om tabellen for
    // den sonen og "Hvilke kamper betyr mest" med sonen satt, for alle (det er
    // ofte lag tre og fire det står om; qaTargetZone byttes bare mens svaret
    // regnes).
    const sporsmal = {};
    for (const [kol, sone] of [['gull', 'gull'], ['ned', 'nedrykk']]) {
      const sikret = r => r.sjanser[kol].avgjort === 1;
      const aktuelle = rader.filter(r => sikret(r) || r.sjanser[kol].andel >= 0.01)
        .sort((a, b) => (sikret(b) - sikret(a)) || (b.sjanser[kol].andel - a.sjanser[kol].andel)).slice(0, 4);
      const lag = [];
      for (const r of aktuelle) {
        let sp, svar, kamper = null;
        qaWhyZoneOverride = sone;
        try { sp = qaWhyLabel(r.lag); svar = await qaWhy(r.lag); } finally { qaWhyZoneOverride = null; }
        const ekte = qaTargetZone; qaTargetZone = t => qaZoneByKey(t, sone);
        try { kamper = await qaKeyMatches(r.lag); } finally { qaTargetZone = ekte; }
        lag.push({lag: r.lag, sporsmal: sp, hvorfor: svar, kamper});
      }
      sporsmal[sone] = {kolonne: kol, lag};
    }
    // Lagsidene (fase 3): for hvert lag, valgt i lagvelgeren som en besøkende
    // ville gjort, de tre øverste spørsmålene i Spør om tabellen med svarene,
    // «Hvilken plass ender X på?», restprogrammet (sjansene i hver kamp slik
    // kamplisten regner dem) og sjansen i hver sone med matematisk status.
    const sel = document.getElementById('teamSelect'), velg = async v => { sel.value = v; sel.dispatchEvent(new Event('change')); await new Promise(r => setTimeout(r, 30)); };
    const lagTekst = {}, rq = QA_QUESTIONS.find(q => q.id === 'range');
    // Restprogrammet (23.10.2026): plassen blant lagene etter motstandernes
    // vinnersjanse i snitt (restprogram(), som «Hvem har det tøffeste
    // restprogrammet?»), og «Vanskeligst» som kalkulatoren (restKamperEtterSjanse).
    const rp = restprogram().sort((a, b) => b.avg - a.avg);
    // «Har X vært heldig eller uheldig?» (lagspørsmålet i kalkulatoren,
    // qaTeamLuck): lagsiden viser svaret derfra, så det regnes ett sted.
    const tl = QA_QUESTIONS.find(q => q.id === 'teamluck');
    try {
      for (const t of TEAMS) {
        await velg(t);
        const x = qaRetninger(t), topp = [];
        for (const q of qaSynligeSporsmal(t).slice(0, QA_TOP_N)) topp.push({id: q.id, sporsmal: q.label(t), svar: await q.run(t, () => {})});
        const rest = matches.filter(m => isEmpty(m) && (m.home === t || m.away === t)).sort((a, b) => a.date.localeCompare(b.date)).map(m => {
          const [lh, la] = rateFor(m.home, m.away), o = outcome(lh, la), hjemme = m.home === t;
          return {naar: qaKampNaar(m), motstander: hjemme ? m.away : m.home, hjemme,
            seier: pctTxt(hjemme ? o.H : o.B), uavgjort: pctTxt(o.U), tap: pctTxt(hjemme ? o.B : o.H)};
        });
        const soner = ZONE_KEYS.filter(k => LEAGUE.zones[k]).map(k => { const z = qaZoneByKey(t, k);
          return {key: k, navn: LEAGUE.zones[k].label, vist: pctTxt(z.pct, z.mat), andel: Math.round(z.pct * 1e6) / 1e6, avgjort: z.mat}; });
        const ri = rp.findIndex(r => r.team === t), v = restKamperEtterSjanse(t)[0];
        const restprogram_ = ri < 0 ? null : {plass: ri + 1, av: rp.length, snitt: pctTxt(rp[ri].avg), andel: Math.round(rp[ri].avg * 1e6) / 1e6, kamper: rp[ri].n,
          vanskeligst: v ? {motstander: v.opp, hjemme: v.hjemme, dato: v.m.date, dato_tekst: dateNoLong(v.m.date), naar: qaKampNaar(v.m), seier: pctTxt(v.p)} : null};
        // Plassfordelingen (andel på hver plass, 1 til 16), som stripen i lagboksen.
        const fordeling = (lastMC[t] || []).map(p => Math.round(p * 1e6) / 1e6);
        lagTekst[t] = {kort: shortTeam(t), tilstand: x.tilstand, regel: x.regel, aapnest: x.aapnest ? x.aapnest.key : null,
          topp, plass: {sporsmal: rq.label(t), svar: qaRange(t)}, rest, soner, restprogram: restprogram_, fordeling,
          heldig: {sporsmal: tl.label(t), svar: await tl.run(t)}};
      }
    } finally { await velg(''); }
    return {status: GRUNNLAG_STATUS, sesonger: lastMCN, lag: TEAMS.length, viktigste,
      liga: {navn: LEAGUE.name, sesong: LEAGUE.season, ferdig: !matches.some(isEmpty)}, sporsmal, statisk, regler, lagTekst, tabell: {kolonner,
      kolonner_html: kolonnerHtml, rader_html: raderHtml, rader}};
  });
}
function skrivTekster(t, laget, N) {
  if (t.status !== 'i bruk' || t.sesonger !== N || t.tabell.rader.length !== t.lag)
    throw new Error(`siden viste ikke tabellen fra filen (${t.status}, ${t.sesonger} sesonger, ${t.tabell.rader.length} av ${t.lag} rader)`);
  const ut = {versjon: 1, side: SIDE, laget, sesonger: t.sesonger,
    note: 'Hentet av scripts/lag_grunnlag.js fra siden selv med grunnlagsfilen i bruk. scripts/lag_sider.py lager de statiske sidene fra denne filen.',
    liga: t.liga, tabell: t.tabell, viktigste: t.viktigste, sporsmal: t.sporsmal, statisk: t.statisk, regler: t.regler, lag: t.lagTekst};
  const json = JSON.stringify(ut, null, 1) + '\n', midl = TEKSTER + '.tmp';
  fs.writeFileSync(midl, json); JSON.parse(fs.readFileSync(midl, 'utf8')); fs.renameSync(midl, TEKSTER);
  console.log(`Skrev ${path.relative(ROOT, TEKSTER)} (${t.tabell.rader.length} lag, ${(json.length / 1024).toFixed(0)} KB).`);
}

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
    if (BARE_TEKSTER) {
      if (!harStatisk()) throw new Error(`${SIDE}/index.html har ingen statiske regioner`);
      const fil = JSON.parse(fs.readFileSync(FIL, 'utf8'));
      const ps = await aapne(browser, port, feil);
      await ps.waitForFunction('GRUNNLAG_STATUS!=="venter"', {timeout: 60000, polling: 50});
      skrivTekster(await hentTekster(ps), fil.laget, fil.sesonger);
      await ps.close();
      if (feil.length) throw new Error(`JS-feil på siden: ${feil.slice(0, 3).join('; ')}`);
      return;
    }
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
    const lagTekst = r => {
    const hode = {versjon: r.versjon, side: SIDE, sesonger: r.sesonger, laget: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
      fingeravtrykk: r.fingeravtrykk, inndata: INNDATA || null, lag: r.lag,
      note: 'Tabellen og svarene med låste utfall for dagens stilling, regnet på forhånd av scripts/lag_grunnlag.js med sidens egen kode. utfall[oppgave][lag*n + plass] = antall sesonger. innsikt: tellingene bak "Hvorfor har ...?", "Hva må ... gjøre?", "Når kan det være avgjort?" og "Hvem kjemper ... mot?" for de samme sesongene som utfall.base, per lag (i samme rekkefølge som lag) og sone. Brukes bare når fingeravtrykket stemmer med det siden selv regner, og ingen resultater er fylt inn.'};
    const linjer = Object.entries(hode).map(([k, v]) => ` ${JSON.stringify(k)}: ${JSON.stringify(v)}`);
    linjer.push(` "oppgaver": [\n${r.oppgaver.map(o => `  ${JSON.stringify(o)}`).join(',\n')}\n ]`);
    if (r.tillegg) linjer.push(` "tillegg": [\n${r.tillegg.map(o => `  ${JSON.stringify(o)}`).join(',\n')}\n ]`);
    linjer.push(` "utfall": {\n${[...r.oppgaver, ...(r.tillegg || [])].map(([id]) => `  ${JSON.stringify(id)}: ${JSON.stringify(r.utfall[id])}`).join(',\n')}\n }`);
    linjer.push(` "innsikt": {\n  "soner": ${JSON.stringify(r.innsikt.soner)},\n  "runder": ${JSON.stringify(r.innsikt.runder)},\n  "lag": [\n` +
      `${r.innsikt.lag.map(x => `   ${JSON.stringify(x)}`).join(',\n')}\n  ]\n }`);
    const tekst = `{\n${linjer.join(',\n')}\n}\n`;
    JSON.parse(tekst);   // gyldig JSON
    return tekst;
    };
    let tekst = lagTekst(r);

    // Siden med den NYE filen: den skal godta den. Så tillegget (uavgjort for
    // kampene "Hvilke kamper betyr mest?" velger), og siden med den ferdige
    // filen: den skal godta den, svaret skal komme helt fra filen, og banneret
    // regnes fra den.
    let key, tekster = null;
    if (TEST_N == null) {
      const p0 = await browser.newPage();
      await p0.goto(`http://127.0.0.1:${port}/${SIDE}/`, {waitUntil: 'domcontentloaded'});
      await p0.waitForFunction('typeof grunnlagFil==="function"', {timeout: 60000});
      const sti = await p0.evaluate(() => new URL(grunnlagFil(), location.href).pathname);
      await p0.close();
      OVERSTYR.set(sti, tekst);
      const pt = await aapne(browser, port, feil);
      await pt.waitForFunction('GRUNNLAG_STATUS!=="venter"', {timeout: 60000, polling: 50});
      const medU = r.oppgaver.filter(o => /:U$/.test(o[0])).map(o => o[1]);
      const t1 = Date.now();
      const t = await pt.evaluate(async medU => {
        if (GRUNNLAG_STATUS !== 'i bruk') return {status: GRUNNLAG_STATUS};
        const valgt = await grunnlagKeymatchKamper(), nye = valgt.filter(i => !medU.includes(i));
        return {status: GRUNNLAG_STATUS, valgt, ...(await grunnlagTilleggRegn(nye))};
      }, medU);
      await pt.close();
      if (t.status !== 'i bruk') throw new Error(`siden godtok ikke den nye filen (${t.status})`);
      r.tillegg = t.oppgaver;
      Object.assign(r.utfall, t.utfall);
      const ft = sjekkFordelinger({...r, oppgaver: r.tillegg});
      if (ft.length) throw new Error(`fordelingene i tillegget går ikke opp: ${ft.slice(0, 3).join('; ')}`);
      console.log(`Tillegget: uavgjort for ${r.tillegg.length} kamper "Hvilke kamper betyr mest?" velger (${t.valgt.length} i alt, ` +
        `${t.valgt.length - r.tillegg.length} hadde det alt) på ${((Date.now() - t1) / 1000).toFixed(1)} s.`);
      tekst = lagTekst(r);
      OVERSTYR.set(sti, tekst);
      const pv = await aapne(browser, port, feil);
      await pv.waitForFunction('GRUNNLAG_STATUS!=="venter"', {timeout: 60000, polling: 50});
      const v = await pv.evaluate(async () => {
        const status = GRUNNLAG_STATUS;
        if (status !== 'i bruk') return {status};
        // "Hvilke kamper betyr mest?" for alle lagene, helt fra filen.
        const ekte = grunnlagSvar; let bom = 0;
        grunnlagSvar = (p, t, g) => { const x = ekte(p, t, g); if (!x && !g.startsWith('grunnlag')) bom++; return x; };
        try { for (const lag of TEAMS) await qaKeyMatches(lag); } finally { grunnlagSvar = ekte; }
        return {status, N: lastMCN, bom, key: keymatchFra(await qaKeyRoundData())};
      });
      await pv.close();
      // tekster.json, fra en ny lasting med den ferdige filen.
      if (harStatisk()) {
        try {
          const ps = await aapne(browser, port, []);
          await ps.waitForFunction('GRUNNLAG_STATUS!=="venter"', {timeout: 60000, polling: 50});
          tekster = await hentTekster(ps);
          await ps.close();
        } catch (e) { console.log(`ADVARSEL: tekster.json ble ikke hentet: ${e.message || e}`); }
      }
      OVERSTYR.delete(sti);
      if (v.status !== 'i bruk') throw new Error(`siden godtok ikke den ferdige filen (${v.status})`);
      if (v.bom) throw new Error(`"Hvilke kamper betyr mest?" kom ikke helt fra filen (${v.bom} kall regnet på siden)`);
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
    if (tekster) {
      const laget = JSON.parse(tekst).laget;
      try { skrivTekster(tekster, laget, r.sesonger); }
      catch (e) { console.log(`ADVARSEL: tekster.json ble ikke skrevet: ${e.message || e}`); }
    }
    if (process.env.GITHUB_STEP_SUMMARY)
      fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `- ${SIDE}: ${r.oppgaver.length} oppgaver x ${r.sesonger} sesonger på ${sek.toFixed(0)} s\n`);
  } finally {
    await browser.close(); server.close();
  }
})().catch(e => { console.error(`Grunnlagsfilen for ${SIDE} ble IKKE skrevet: ${e.message || e}`); process.exit(1); });
