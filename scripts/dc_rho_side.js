#!/usr/bin/env node
// Dixon-Coles-rho på siden i dag: hva variantene gjør med dagens tall.
// Hører til scripts/dc_rho_studie.py (enkeltkamper ut av utvalg) og
// backtest_zones.py --dc-rho-alt (sluttplasseringene); se forklaringen der.
//
// Hver variant er en kopi av ligasiden der DC_RHO er byttet ut (valgfritt en
// egen rho bare i oddstilpasningen, fitRates, og et målnivå). Alle
// variantene kjøres samtidig, én Chrome-side hver, og måler:
//   1. sonesjansene for dagens stilling med 100 000 sesonger, uten
//      grunnlagsfilen og med samme frø (tabellsimuleringen på siden);
//   2. sidens egen trekning ("typisk sesong", som "Simuler runden" og
//      "Simuler tomme kamper"): runden med odds og alle gjenstående kamper,
//      rundt 10 000 kamper hver, med målfordeling og uavgjortandel;
//   3. uavgjortandelen i ratene: outcome(rateFor(...)).U for runden med odds
//      mot oddsblandingen (70 % odds + 30 % modell) og for alle kampene.
//      NB: outcome() gir {H, U, B}; uavgjort heter U, ikke D.
//
// Bruk (puppeteer-core via NODE_PATH, Chrome som i testene):
//   node scripts/dc_rho_side.js                          # Eliteserien, -0,38 mot -0,04
//   node scripts/dc_rho_side.js --liga obos
//   node scripts/dc_rho_side.js --variant "1a=-0.38,0" --variant "3=-0.38,,1.043,1.033"
// Variant: navn=rho[,rho i oddstilpasningen[,nivå hjemme,nivå borte]].
const puppeteer = require('puppeteer-core');
const http = require('http'), fs = require('fs'), path = require('path');
const ROT = path.join(__dirname, '..');

const arg = (n, d) => { const i = process.argv.indexOf(n); return i >= 0 ? process.argv[i + 1] : d; };
const liga = arg('--liga', 'eliteserien'), N = +arg('--n', 100000), ut = arg('--ut', null);
const spes = process.argv.flatMap((a, i) => a === '--variant' ? [process.argv[i + 1]] : []);
const VAR = (spes.length ? spes : ['I dag=-0.38', 'rho -0,04=-0.04']).map(s => {
  const [navn, rest] = s.split('='), [rho, rhoOdds, ch, ca] = rest.split(',');
  return {navn, rho: +rho, rhoOdds: rhoOdds === undefined || rhoOdds === '' ? null : +rhoOdds, c: ch ? [+ch, +ca] : null};
});
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const kilde = fs.readFileSync(path.join(ROT, liga, 'index.html'), 'utf8');
const RHO_LINJE = 'const DC_RHO = -0.38;';
if (!kilde.includes(RHO_LINJE)) throw new Error(`fant ikke «${RHO_LINJE}» i ${liga}/index.html`);
const lagSide = v => {
  let s = kilde.replace(RHO_LINJE, `const DC_RHO = ${v.rho};`);
  if (v.rhoOdds !== null) {
    const gml = 'const tryAt=(lh,la)=>{ const o=outcome(lh,la),';
    if (!s.includes(gml)) throw new Error('fant ikke fitRatesRegn');
    s = s.replace(gml, 'const tryAt=(lh,la)=>{ const o=outcomeOdds(lh,la),').replace('function fitRatesRegn(pH,pB,start){',
      `const RHO_ODDS = ${v.rhoOdds};
function outcomeOdds(lh,la){ let H=0,U=0,B=0; for(let h=0;h<=GMAX;h++) for(let a=0;a<=GMAX;a++){ let p=pois(lh,h)*pois(la,a);
  if(h===0&&a===0)p*=Math.max(0,1-lh*la*RHO_ODDS); else if(h===1&&a===0)p*=Math.max(0,1+la*RHO_ODDS);
  else if(h===0&&a===1)p*=Math.max(0,1+lh*RHO_ODDS); else if(h===1&&a===1)p*=Math.max(0,1-RHO_ODDS);
  if(h>a)H+=p; else if(h===a)U+=p; else B+=p; } const t=H+U+B; return {H:H/t,U:U/t,B:B/t}; }
function fitRatesRegn(pH,pB,start){`);
  }
  return s;
};
const SIDER = VAR.map(lagSide);
const TYPER = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.json': 'application/json', '.svg': 'image/svg+xml'};
const srv = http.createServer((q, s) => {
  let p = decodeURIComponent(q.url.split('?')[0]);
  const m = p.match(/^\/v(\d+)(\/.*)$/), vi = m ? +m[1] : null;
  if (m) p = m[2];
  if (p.endsWith('/')) p += 'index.html';
  if (vi !== null && p === `/${liga}/index.html`) { s.writeHead(200, {'Content-Type': TYPER['.html']}); return s.end(SIDER[vi]); }
  if (/grunnlag\.json$/.test(p)) { s.writeHead(404); return s.end(); }   // sidens egen regning, ikke filen
  const f = path.join(ROT, p);
  if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) { s.writeHead(404); return s.end(); }
  s.writeHead(200, {'Content-Type': TYPER[path.extname(f)] || 'application/octet-stream'});
  fs.createReadStream(f).pipe(s);
});

const maal = kamper => {
  const n = kamper.length, f = c => kamper.filter(([x, y]) => c(x, y)).length / n;
  return {n, mål: kamper.reduce((s, [x, y]) => s + x + y, 0) / n, uavgjort: f((x, y) => x === y), '0-0': f((x, y) => x === 0 && y === 0),
    '1-0/0-1': f((x, y) => x + y === 1), '≥5 ett lag': f((x, y) => x >= 5 || y >= 5), 'margin ≥4': f((x, y) => Math.abs(x - y) >= 4),
    '≥6 totalt': f((x, y) => x + y >= 6)};
};

srv.listen(0, '127.0.0.1', async () => {
  const port = srv.address().port;
  const b = await puppeteer.launch({executablePath: CHROME, headless: 'new', protocolTimeout: 1800000});
  const kjor = async (v, vi) => {
    const pg = await b.newPage();
    pg.on('pageerror', e => console.error(`${v.navn}: ${e.message}`));
    await pg.goto(`http://127.0.0.1:${port}/v${vi}/${liga}/`, {waitUntil: 'networkidle0'});
    await pg.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 300000});
    const r = await pg.evaluate(async (c, N) => {
      if (c) { MODEL.mu += Math.log(c[1]); MODEL.H += Math.log(c[0]) - Math.log(c[1]); refreshLiveState(); }
      // 1. Sonene, N sesonger, samme frø for alle variantene.
      lastMCScenarioKey = null; runMCAsync(N);
      await new Promise(res => { const t = setInterval(() => { if (lastMCFinal && lastMCN === N) { clearInterval(t); res(); } }, 100); });
      const soner = {};
      for (const k of ['gull', 'europa', 'kvalik', 'nedrykk']) {
        const z = LEAGUE.zones[k]; if (!z) continue;
        soner[k] = Object.fromEntries(TEAMS.map(t => { let v = 0; for (let p = z.lo; p <= z.hi; p++) v += lastMC[t][p - 1]; return [t, v]; }));
      }
      // 3. Uavgjort i ratene (U, ikke D).
      const oddsKamper = matches.filter(m => ODDS_UP[m.home + '|' + m.away]);
      const R = oddsKamper.length ? oddsKamper[0].round : Math.min(...matches.map(m => m.round));
      const runde = matches.filter(m => m.round === R);
      const u = ms => ms.reduce((s, m) => { const [lh, la] = rateFor(m.home, m.away); return s + outcome(lh, la).U; }, 0) / ms.length;
      const blandU = oddsKamper.length ? oddsKamper.reduce((s, m) => { const r = rateMedStilling(LIVE, m.home, m.away);
        return s + 1 - (ODDS_W * r.mk[0] + (1 - ODDS_W) * r.md.H) - (ODDS_W * r.mk[2] + (1 - ODDS_W) * r.md.B); }, 0) / oddsKamper.length : null;
      const forventet = ms => ms.reduce((s, m) => { const [lh, la] = rateFor(m.home, m.away); return s + lh + la; }, 0) / ms.length;
      // 2. Sidens trekning, i hjelpe-Workeren.
      const w = getHjelpWorker(), trekk = open => new Promise(res => {
        const runId = Math.floor(Math.random() * 1e9);
        const f = e => { if (e.data.mode === 'typical' && e.data.runId === runId) { w.removeEventListener('message', f); res(e.data.result); } };
        w.addEventListener('message', f);
        w.postMessage({mode: 'typical', runId, seed: (Math.random() * 4294967296) >>> 0, mu: MODEL.mu, H: MODEL.H, k: FORM_K,
          att: Array.from(LIVE.att), con: Array.from(LIVE.con), ha: Array.from(LIVE.ha), hc: Array.from(LIVE.hc),
          open: open.map(m => [TI[m.home], TI[m.away], m.round]), oddsOverride: open.map(m => oddsOverrideFor(m.home, m.away))});
      });
      const kR = [], kA = [];
      for (let i = 0; i < Math.ceil(10000 / runde.length); i++) (await trekk(runde)).forEach(x => kR.push(x));
      for (let i = 0; i < Math.ceil(10000 / matches.length); i++) (await trekk(matches)).forEach(x => kA.push(x));
      return {soner, R, oddsN: oddsKamper.length, U: {runde: u(runde), blanding: blandU, alle: u(matches)},
        forventet: {runde: forventet(runde), alle: forventet(matches)}, runde: kR, alle: kA};
    }, v.c, N);
    await pg.close();
    return r;
  };
  const res = await Promise.all(VAR.map(kjor));
  await b.close(); srv.close();

  console.log(`${liga}: ${VAR.length} varianter, ${N} sesonger, runde ${res[0].R} har odds for ${res[0].oddsN} kamper\n`);
  const kol = ['mål', 'uavgjort', '0-0', '1-0/0-1', '≥5 ett lag', 'margin ≥4', '≥6 totalt'];
  const pst = (k, v) => k === 'mål' ? v.toFixed(2) : (v * 100).toFixed(1);
  console.log(`Sidens trekning og uavgjort i ratene:`);
  console.log(`  ${''.padEnd(30)}${'utvalg'.padEnd(9)}${kol.map(k => k.padStart(11)).join('')}${'forventet'.padStart(11)}${'U i ratene'.padStart(12)}${'U odds'.padStart(9)}`);
  VAR.forEach((v, i) => {
    for (const [del_, navn] of [['runde', `runde ${res[i].R}`], ['alle', 'alle']]) {
      const s = maal(res[i][del_]);
      console.log(`  ${v.navn.padEnd(30)}${navn.padEnd(9)}${kol.map(k => pst(k, s[k]).padStart(11)).join('')}${res[i].forventet[del_].toFixed(2).padStart(11)}` +
        `${(res[i].U[del_] * 100).toFixed(1).padStart(12)}${del_ === 'runde' && res[i].U.blanding != null ? (res[i].U.blanding * 100).toFixed(1).padStart(9) : ''.padStart(9)}`);
    }
  });
  console.log(`\nSonesjansene mot ${VAR[0].navn} (prosentpoeng):`);
  for (let i = 1; i < VAR.length; i++) {
    const linje = Object.keys(res[0].soner).map(z => {
      const d = Object.keys(res[0].soner[z]).map(t => [t, (res[i].soner[z][t] - res[0].soner[z][t]) * 100]).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
      return `${z}: ${d[0]} ${d[1] >= 0 ? '+' : ''}${d[1].toFixed(1)}`;
    });
    console.log(`  ${VAR[i].navn.padEnd(30)}${linje.join('   ')}`);
  }
  console.log(`\nLag med en sone mellom 1 og 99 % (${VAR.map(v => v.navn).join(' / ')}):`);
  const lag = Object.keys(res[0].soner.gull);
  for (const t of lag) {
    const deler = Object.keys(res[0].soner).filter(z => res[0].soner[z][t] > 0.01 && res[0].soner[z][t] < 0.99)
      .map(z => `${z} ${res.map(r => (r.soner[z][t] * 100).toFixed(1)).join(' / ')}`);
    if (deler.length) console.log(`  ${t.padEnd(16)}${deler.join('   ')}`);
  }
  if (ut) fs.writeFileSync(ut, JSON.stringify({liga, N, VAR, res: res.map(r => ({...r, runde: maal(r.runde), alle: maal(r.alle)}))}, null, 1));
});
