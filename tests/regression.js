#!/usr/bin/env node
/* Regresjonstest for Tabellkalkulator. Kjøres med tests/run.sh.
 *
 * Alt testes mot den ekte siden i en headless Chrome, ikke mot kopier av
 * logikken: serveren under betjener repoet slik GitHub Pages gjør, og testene
 * klikker og leser det en bruker ville sett.
 *
 * Dekker det som har gått galt før, i denne rekkefølgen:
 *   1. lasting og JS-feil
 *   2. ingen sidelengs scroll på fire bredder
 *   3. "Spør om tabellen": hvert spørsmål må svare med DEN STØRRELSEN
 *      spørsmålet ber om (prosent, poeng, prosentpoeng, plass eller runde),
 *      i flere situasjoner: dagens tabell, delvis utfylt og ferdig sesong
 *   4. svar blir aldri stående fra et annet lag eller et annet scenario
 *   5. grå (simulerte) resultater: fylles, slettes aldri av seg selv,
 *      og forsvinner bare med Nullstill
 *   6. sortering: syklus, rekkefølge, merknad og skjulte sonestreker
 *   7. delingslenker: scenario ut og inn igjen gir samme tabell
 *   8. datafilene workflowen skriver (keymatch/lastmatch) vises i banneret
 *      og i lagboksen
 *   9. tabellen pa mobil: alle tallkolonnene synlige ved 390 px, ogsa med
 *      merke og det lengste lagnavnet, og merket forklares ved trykk
 *  10. bytte av lag scroller ikke siden; bare et trykk pa et sporsmal gjor det
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const MIME = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.json': 'application/json',
  '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.ttf': 'font/ttf'};

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
  const c = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  const found = c.find(x => fs.existsSync(x));
  if (!found) throw new Error('Fant ikke Chrome. Sett CHROME_PATH.');
  return found;
}

// ---- liten testramme: samler feil i stedet for å stoppe ved første ----
const results = [];
let group = '';
const setGroup = g => { group = g; console.log(`\n${g}`); };
function check(name, ok, detail) {
  results.push({group, name, ok: !!ok, detail});
  console.log(`  ${ok ? '✓' : '✗'} ${name}${ok ? '' : `\n      ${detail || ''}`}`);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---- Størrelsen hvert spørsmål må svare med ----
// pat: svaret MÅ inneholde dette. alt: gyldige svar der tallet ikke finnes,
// fordi saken er avgjort, ingenting er i spill, eller sesongen er ferdig.
const PCT = String.raw`(?:\d+\s%|<1\s%|>99\s%|\d+ prosent)`;
const PP = String.raw`(?:[+−±]\d+|\d+ prosentpoeng|to prosentpoeng)`;
const SETTLED = /(sikret|kan ikke lenger|Sesongen er ferdig|så godt som|ingen gjenstående|Ingen kamper igjen|Ingen data|betydde lite|betyr lite|ingen spilte kamper|ingen runde|har ingen|Alle kampene|Ingen av de|Ingen kamp i|Ingenting er i spill)/i;
const QA_EXPECT = {
  why:        {what: 'prosent',       pat: new RegExp(PCT)},
  howto:      {what: 'poeng',         pat: /\d+ (?:av \d+ mulige )?poeng|poengsummer/},
  keymatches: {what: 'prosentpoeng',  pat: new RegExp(PP)},
  runin:      {what: 'prosent',       pat: new RegExp(PCT)},
  // Svaret navngir kampen og viser hva den flytter; rundenummeret står i banneret.
  // Lagnavn kan ha æ, ø og å, som \w ikke dekker i JavaScript.
  keyround:   {what: 'kamp og prosent', pat: new RegExp(String.raw`\S+ mot \S+[\s\S]*${PCT}`)},
  lastmatch:  {what: 'prosent',       pat: new RegExp(PCT)},
  nextmatch:  {what: 'prosent',       pat: new RegExp(PCT)},
  cheer:      {what: 'prosentpoeng',  pat: new RegExp(PP)},
  // Spennet, ikke bare ordet "plass": svaret nevner plasseringer flere steder,
  // så et løsere mønster ville ikke merket om selve spennet forsvant.
  range:      {what: 'plasseringsspenn', pat: /mellom \d+\. og \d+\. plass|Nesten sikkert \d+\. plass|ender på \d+\. plass uansett/},
  decided:    {what: 'runde',         pat: /runde \d+/},
  rivals:     {what: 'prosent',       pat: new RegExp(PCT)},
  // Fortegnet er ute av ordlyden: tallet står nå som "9,3 poeng mer enn
  // modellen forventet" / "5,6 poeng under forventning".
  luck:       {what: 'poengavvik',    pat: /\d+,\d poeng (mer enn modellen forventet|under forventning)/},
};

async function main() {
  const puppeteer = require('puppeteer-core');
  // Uten argument testes filene i repoet, servert fra en lokal server. Med
  // --live testes den publiserte siden i stedet, så en lansering kan
  // kontrolleres slik publikum faktisk ser den:
  //   node tests/regression.js --live
  //   node tests/regression.js --live https://tabellkalkulator.no
  const liveArg = process.argv.indexOf('--live');
  const live = liveArg >= 0;
  const origin = live ? (process.argv[liveArg + 1] || '').replace(/^-.*/, '') || 'https://tabellkalkulator.no' : null;
  const server = live ? null : await serve();
  const base = live ? `${origin.replace(/\/$/, '')}/eliteserien/`
                    : `http://127.0.0.1:${server.address().port}/eliteserien/`;
  if (live) console.log(`Tester den publiserte siden: ${origin}`);
  const browser = await puppeteer.launch({executablePath: chromePath(), headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']});
  const errors = [];

  const open = async (w = 1400, h = 900, url = base) => {
    const page = await browser.newPage();
    page.on('pageerror', e => errors.push(`${url}: ${e.message}`));
    await page.setViewport({width: w, height: h});
    await page.goto(url, {waitUntil: 'networkidle0'});
    await page.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 120000});
    return page;
  };
  const settle = page => page.waitForFunction(
    'lastMCFinal===true && lastMCScenarioKey===qaScenarioKey()', {timeout: 120000});
  // Utfyllingsknappene er asynkrone, og scenarionøkkelen rekker ikke å endre
  // seg før settle() ville sagt "ferdig". Vent på at kampene faktisk er fylt.
  const filled = (page, n) => page.waitForFunction(
    `matches.filter(m=>m.hg!=null).length===${n}`, {timeout: 120000});

  try {
    // ---- 1. lasting ----
    setGroup('Lasting');
    let page = await open();
    const rows = await page.$$eval('#tbl tbody tr', r => r.length);
    check('tabellen har 16 lag', rows === 16, `fant ${rows}`);
    const teams = await page.$$eval('#teamSelect option', o => o.map(x => x.value).filter(Boolean));
    check('16 lag i lagvelgeren', teams.length === 16, `fant ${teams.length}`);
    const sums = await page.evaluate(() => TEAMS.map(t => lastMC[t].reduce((a, b) => a + b, 0)));
    check('fordelingen summerer til 1 for hvert lag', sums.every(x => Math.abs(x - 1) < 1e-9),
      sums.filter(x => Math.abs(x - 1) >= 1e-9).join(', '));

    // ---- 2. sidelengs scroll ----
    setGroup('Ingen sidelengs scroll');
    for (const [w, h] of [[1400, 900], [1180, 900], [900, 800], [390, 800]]) {
      await page.setViewport({width: w, height: h});
      await sleep(400);
      const over = await page.evaluate(() => Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ...[...document.querySelectorAll('.tblwrap,.tblscroll')].map(e => 0)));
      check(`${w} px`, over === 0, `${over} px for bredt`);
    }
    await page.setViewport({width: 1400, height: 900});

    // ---- 3. Spør om tabellen: riktig størrelse i svaret ----
    setGroup('Spør om tabellen: svaret inneholder størrelsen spørsmålet ber om');
    const ask = (id, team) => page.evaluate(async (id, team) => {
      const q = QA_QUESTIONS.find(x => x.id === id);
      if (!q) return 'MANGLER';
      try { return await q.run(team); } catch (e) { return 'ERROR ' + e.message; }
    }, id, team);
    const ids = await page.evaluate(() => QA_QUESTIONS.map(q => q.id));
    check('alle spørsmål har en forventning i testen', ids.every(i => QA_EXPECT[i]),
      ids.filter(i => !QA_EXPECT[i]).join(', '));

    const scenarios = [
      ['dagens tabell', null],
      ['delvis utfylt', async () => { await page.evaluate(() => {
        document.getElementById('autoFillToggle').checked = false;
        matches.slice(0, 10).forEach(m => setMatch(m, 2, 1)); render(); }); await settle(page); }],
      ['ferdig sesong', async () => { await page.evaluate(async () => {
        await simulateTypicalAsync(matches.filter(m => isEmpty(m))); render(); }); await settle(page); }],
    ];
    for (const [label, setup] of scenarios) {
      if (setup) await setup();
      for (const team of ['Bodø/Glimt', 'Start', 'Molde']) {
        await page.select('#teamSelect', team);
        await sleep(300);
        await settle(page);
        for (const id of ids) {
          const a = await ask(id, team);
          const exp = QA_EXPECT[id];
          const bad = /^(ERROR|MANGLER)/.test(a) || /undefined|NaN|\[object/.test(a);
          const ok = !bad && (exp.pat.test(a) || SETTLED.test(a));
          check(`${label} · ${team} · ${id} (${exp.what})`, ok, a.slice(0, 160));
        }
      }
    }
    await page.evaluate(() => { matches.forEach(m => setMatch(m, null, null)); render(); });
    await settle(page);

    // ---- 4. svaret hører til laget og scenarioet ----
    setGroup('Svaret blir aldri stående fra en annen tilstand');
    await page.select('#teamSelect', 'Brann');
    await sleep(300);
    await page.evaluate(() => { qaSetOpen(true); runQaQuestion('range'); });
    await page.waitForFunction(`(()=>{const a=document.getElementById('qaAnswer');return a&&!a.classList.contains('loading')})()`, {timeout: 60000});
    const shownBrann = await page.evaluate(() => document.getElementById('qaAnswer').textContent);
    check('svaret gjelder laget som er valgt', shownBrann.includes('Brann'), shownBrann.slice(0, 120));
    // bytt lag og mål om et utdatert svar noen gang er synlig
    await page.evaluate(() => { window.__bad = 0; window.__iv = setInterval(() => {
      const a = document.getElementById('qaAnswer');
      if (a && !a.classList.contains('loading') && qaAnswerKey !== qaStateKey()) window.__bad++;
    }, 20); });
    await page.select('#teamSelect', 'Molde');
    await settle(page);
    await page.waitForFunction(`(()=>{const a=document.getElementById('qaAnswer');return a&&!a.classList.contains('loading')&&qaAnswerKey===qaStateKey()})()`, {timeout: 60000});
    const badTicks = await page.evaluate(() => { clearInterval(window.__iv); return window.__bad; });
    const shownMolde = await page.evaluate(() => document.getElementById('qaAnswer').textContent);
    check('utdatert svar er aldri synlig etter lagbytte', badTicks < 2, `${badTicks} målinger`);
    check('svaret er regnet om for det nye laget', shownMolde.includes('Molde'), shownMolde.slice(0, 120));

    // ---- 5. grå (simulerte) resultater ----
    setGroup('Grå resultater');
    await page.evaluate(() => { matches.forEach(m => setMatch(m, null, null)); document.getElementById('autoFillToggle').checked = false; render(); });
    await settle(page);
    const total = await page.evaluate(() => matches.length);
    await page.click('#fxPanel #simRest');
    await filled(page, total);
    await settle(page);
    const greyAll = await page.evaluate(() => matches.filter(m => m.sim).length);
    check('"Simuler tomme kamper" fyller alle tomme', greyAll === total, `${greyAll} grå av ${total}`);
    const greyBefore = await page.evaluate(() => matches.filter(m => m.sim).length);
    await page.evaluate(() => {
      const m = matches[0]; setMatch(m, 4, 0); render();
    });
    await settle(page);
    const greyAfter = await page.evaluate(() => matches.filter(m => m.sim).length);
    check('eget resultat sletter ikke de grå', greyAfter === greyBefore - 1,
      `før ${greyBefore}, etter ${greyAfter}`);
    const ownStays = await page.evaluate(() => { const m = matches[0]; return m.hg === 4 && m.ag === 0 && !m.sim; });
    check('eget resultat er lagret som eget (ikke grått)', ownStays);
    await page.click('#fxPanel #reset');
    await settle(page);
    const afterReset = await page.evaluate(() => matches.filter(m => m.hg != null).length);
    check('Nullstill tømmer alt', afterReset === 0, `${afterReset} igjen`);

    // ---- 6. sortering ----
    setGroup('Sortering');
    const posOrder = () => page.$$eval('#tbl tbody tr td.pos', c => c.map(x => +x.textContent));
    for (const key of ['gull', 'europa', 'ned', 'form']) {
      await page.evaluate(k => { tableSort = null; render(); cycleSort(k); }, key);
      await sleep(400);
      const vals = await page.evaluate(k => [...document.querySelectorAll('#tbl tbody tr')]
        .map(tr => k === 'form' ? Math.round(parseFloat(tr.querySelector('.formbox').textContent.replace(',', '.')) * 10)
          : Math.round(probOf(tr.dataset.team, k) * 100)), key);
      const asc = vals.every((v, i) => i === 0 || vals[i - 1] <= v);
      const desc = vals.every((v, i) => i === 0 || vals[i - 1] >= v);
      // nedrykk sorteres lavest først (som en vanlig tabell), de andre høyest først
      check(`${key} sorterer riktig vei`, key === 'ned' ? asc : desc, vals.join(','));
      const note = await page.evaluate(() => { const n = document.getElementById('sortNote'); return n.hidden ? null : n.textContent; });
      check(`${key} viser merknaden`, !!note && /Sortert etter/.test(note || ''), String(note));
      const dashed = await page.evaluate(() => [...document.querySelectorAll('#tbl tbody tr.cut')]
        .filter(tr => getComputedStyle(tr.querySelector('td')).borderBottomStyle === 'dashed').length);
      check(`${key} skjuler sonestrekene`, dashed === 0, `${dashed} stiplede`);
    }
    // Tre klikk fra usortert: synkende, stigende, av.
    await page.evaluate(() => { tableSort = null; render(); cycleSort('gull'); cycleSort('gull'); cycleSort('gull'); });
    await sleep(400);
    const backToPos = await posOrder();
    check('tredje klikk gir vanlig tabell',
      await page.evaluate(() => tableSort === null) &&
      backToPos.join(',') === backToPos.slice().sort((a, b) => a - b).join(','), backToPos.join(','));
    await page.evaluate(k => cycleSort(k), 'gull');
    await sleep(300);
    await page.click('#fxPanel #simRest');
    await filled(page, total);
    await settle(page);
    check('sortering nullstilles ved simulering', await page.evaluate(() => tableSort === null));
    await page.click('#fxPanel #reset');
    await settle(page);

    // ---- 7. delingslenker ----
    setGroup('Delingslenker');
    await page.evaluate(() => {
      document.getElementById('autoFillToggle').checked = false;
      matches.slice(0, 6).forEach((m, i) => setMatch(m, i % 3, 1)); render();
    });
    await settle(page);
    const before = await page.evaluate(() => ({
      hash: encodeScenario(),
      table: [...document.querySelectorAll('#tbl tbody tr')].map(tr => tr.dataset.team + ':' + tr.querySelector('.pts').textContent).join('|'),
      filled: matches.filter(m => m.hg != null).map(m => `${m.id}:${m.hg}-${m.ag}${m.sim ? 's' : ''}`).join(','),
    }));
    check('scenarioet blir kodet', before.hash.length > 0, before.hash.slice(0, 60));
    const page2 = await open(1400, 900, `${base}#s=${before.hash}`);
    await settle(page2);
    const after = await page2.evaluate(() => ({
      table: [...document.querySelectorAll('#tbl tbody tr')].map(tr => tr.dataset.team + ':' + tr.querySelector('.pts').textContent).join('|'),
      filled: matches.filter(m => m.hg != null).map(m => `${m.id}:${m.hg}-${m.ag}${m.sim ? 's' : ''}`).join(','),
    }));
    check('lenken gjenskaper resultatene', after.filled === before.filled, `${before.filled}\n      mot ${after.filled}`);
    check('lenken gjenskaper tabellen', after.table === before.table);
    await page2.close();
    await page.bringToFront();
    // grått sett: frø-snarveien i lenken skal gi samme sesong
    await page.evaluate(() => { matches.forEach(m => setMatch(m, null, null)); render(); });
    await settle(page);
    await page.click('#fxPanel #simRest');
    await filled(page, total);
    await settle(page);
    const simBefore = await page.evaluate(() => ({hash: encodeScenario(),
      filled: matches.filter(m => m.hg != null).map(m => `${m.id}:${m.hg}-${m.ag}`).join(',')}));
    const page3 = await open(1400, 900, `${base}#s=${simBefore.hash}`);
    await settle(page3);
    const simAfter = await page3.evaluate(() => matches.filter(m => m.hg != null).map(m => `${m.id}:${m.hg}-${m.ag}`).join(','));
    check('lenken gjenskaper en simulert sesong', simAfter === simBefore.filled,
      `${simBefore.filled.slice(0, 80)}\n      mot ${simAfter.slice(0, 80)}`);
    await page3.close();
    await page.bringToFront();

    // ---- 8. datafilene fra workflowen ----
    setGroup('Datafiler fra workflowen');
    for (const f of ['keymatch.json', 'lastmatch.json', 'history.json']) {
      const p = path.join(ROOT, 'eliteserien', 'data', f);
      let ok = false, detail = 'mangler';
      if (fs.existsSync(p)) {
        try { const j = JSON.parse(fs.readFileSync(p, 'utf8'));
          ok = f === 'keymatch.json' ? !!(j.banner && j.match) : f === 'lastmatch.json' ? !!j.teams : Array.isArray(j.snapshots);
          detail = ok ? '' : 'uventet innhold';
        } catch (e) { detail = e.message; }
      }
      check(`${f} finnes og har riktig form`, ok, detail);
    }
    const fresh = await open();
    // Banneret viser lagspørsmålet når et lag er valgt (localStorage husker
    // valget mellom faner), så velg bort laget først.
    await fresh.select('#teamSelect', '');
    await sleep(600);
    const banner = await fresh.evaluate(() => ({txt: document.getElementById('qaHighlight').textContent,
      qid: document.getElementById('qaHighlight').dataset.qid}));
    // To gyldige former: én tydelig viktigste kamp, eller flere som betyr
    // omtrent like mye (se qaKeyBanner).
    check('banneret viser rundens viktigste kamp fra datafilen',
      banner.qid === 'keyround' &&
      /påvirker .+ mest denne runden/.test(banner.txt) &&
      / mot /.test(banner.txt), JSON.stringify(banner));
    await fresh.select('#teamSelect', 'Bodø/Glimt');
    await sleep(500);
    const lm = await fresh.evaluate(() => {
      const el = document.querySelector('.status .lastmatch');
      return el ? el.textContent : null;
    });
    check('lagboksen viser forrige kamp', !!lm && /^Forrige kamp: /.test(lm || ''), String(lm));
    await fresh.close();

    // ---- 9. tabellen på mobil ----
    setGroup('Tabellen på mobil');
    const mob = await open(390, 800);
    const m9 = await mob.evaluate(() => {
      const wrap = document.querySelector('.tblwrap');
      const th = [...document.querySelectorAll('#tbl thead th')].filter(t => getComputedStyle(t).display !== 'none');
      const withBadge = [...document.querySelectorAll('#tbl tbody tr')].filter(tr => tr.querySelector('.badge').className !== 'badge');
      const longest = [...document.querySelectorAll('.teamname')].sort((a, b) => b.textContent.length - a.textContent.length)[0];
      const nedCells = [...document.querySelectorAll('#tbl tbody td.ned')];
      const wr = wrap.getBoundingClientRect();
      return {
        overflow: wrap.scrollWidth - wrap.clientWidth,
        sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        cols: th.map(t => t.innerText.trim()),
        badges: withBadge.length,
        badgeTextHidden: withBadge.length ? getComputedStyle(withBadge[0].querySelector('.bt')).display === 'none' : null,
        badgeIconShown: withBadge.length ? getComputedStyle(withBadge[0].querySelector('.bi')).display !== 'none' : null,
        longestName: longest.innerText.trim(),
        longestClipped: longest.scrollWidth > longest.clientWidth + 1,
        // siste tallkolonne må ligge helt innenfor tabellens synlige bredde
        nedInside: nedCells.every(c => c.getBoundingClientRect().right <= wr.right + 0.5),
      };
    });
    check('ingen sidelengs scroll i tabellen ved 390 px', m9.overflow === 0 && m9.sideways === 0,
      `tabell ${m9.overflow} px, side ${m9.sideways} px`);
    check('alle tallkolonnene er synlige', m9.cols.join(',').includes('Nedr.') && m9.nedInside,
      `${m9.cols.join(' | ')} | siste kolonne innenfor: ${m9.nedInside}`);
    check('merket vises som ikon, ikke tekst', m9.badges > 0 && m9.badgeTextHidden === true && m9.badgeIconShown === true,
      `${m9.badges} merker, tekst skjult: ${m9.badgeTextHidden}, ikon: ${m9.badgeIconShown}`);
    check('det lengste lagnavnet klippes ikke', !m9.longestClipped, m9.longestName);
    await mob.evaluate(() => {
      const tr = [...document.querySelectorAll('#tbl tbody tr')].find(x => x.querySelector('.badge').className !== 'badge');
      tr.querySelector('.badge').click();
    });
    await sleep(300);
    const tip = await mob.evaluate(() => {
      const t = document.getElementById('badgeTip');
      return {vist: t && !t.hidden, txt: t ? t.textContent : null};
    });
    check('trykk på merket forklarer det', tip.vist && /kan (ikke|verken)/.test(tip.txt || ''), JSON.stringify(tip));
    // Smale skjermer: alt skal få plass, og under 340 px brukes de korte
    // lagnavnene fra kamplisten.
    for (const w of [390, 360, 339, 320]) {
      await mob.setViewport({width: w, height: 800});
      await sleep(500);
      const n = await mob.evaluate(() => {
        const wrap = document.querySelector('.tblwrap');
        const wr = wrap.getBoundingClientRect();
        const ned = [...document.querySelectorAll('#tbl tbody td.ned')];
        const names = [...document.querySelectorAll('.teamname')].map(e => e.innerText.trim());
        return {
          overflow: wrap.scrollWidth - wrap.clientWidth,
          sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          nedInside: ned.every(c => c.getBoundingClientRect().right <= wr.right + 0.5),
          short: names.includes('S08') && names.includes('Glimt'),
          longest: names.slice().sort((a, b) => b.length - a.length)[0],
        };
      });
      check(`${w} px: alt får plass uten sidelengs scroll`,
        n.overflow === 0 && n.sideways === 0 && n.nedInside,
        `tabell ${n.overflow}, side ${n.sideways}, siste kolonne innenfor ${n.nedInside}`);
      check(`${w} px: ${w < 340 ? 'korte' : 'fulle'} lagnavn`, w < 340 ? n.short : !n.short,
        `bredeste navn "${n.longest}"`);
    }
    await mob.setViewport({width: 390, height: 800});

    // ---- 10. lagbytte skal ikke scrolle ----
    setGroup('Lagbytte scroller ikke siden');
    for (const [w, h, label] of [[390, 800, 'mobil'], [1400, 900, 'PC']]) {
      const q = await open(w, h);
      await q.select('#teamSelect', 'Brann');
      await sleep(500);
      await q.evaluate(() => { qaSetOpen(true); runQaQuestion('range'); });
      await q.waitForFunction(`(()=>{const a=document.getElementById('qaAnswer');return a&&!a.classList.contains('loading')})()`, {timeout: 60000});
      await sleep(700);
      const afterClick = await q.evaluate(() => Math.round(window.scrollY));
      check(`${label}: trykk på et spørsmål scroller til svaret`, afterClick > 50, `scrollY ${afterClick}`);
      await q.evaluate(() => window.scrollBy(0, -300));
      await sleep(500);
      // Det som måles, er hvor det aktive spørsmålet står PÅ SKJERMEN, ikke
      // scrollY. Blir noe over skjermkanten høyere ved lagbyttet (lagboksen,
      // en lengre linje), justerer nettleseren scrollY nettopp for at det man
      // ser skal stå stille -- da endres scrollY uten at siden flytter seg.
      const topp = 'Math.round(document.querySelector(".qa-item.active").getBoundingClientRect().top)';
      const before = await q.evaluate(topp);
      await q.evaluate(t => { window.__mx = -1e9; window.__mn = 1e9;
        window.__iv = setInterval(() => { const el = document.querySelector('.qa-item.active'); if (!el) return;
          const y = Math.round(el.getBoundingClientRect().top);
          window.__mx = Math.max(window.__mx, y); window.__mn = Math.min(window.__mn, y); }, 20); }, topp);
      await q.select('#teamSelect', 'Tromsø');
      await q.waitForFunction(`(()=>{const a=document.getElementById('qaAnswer');return a&&!a.classList.contains('loading')&&qaAnswerKey===qaStateKey()})()`, {timeout: 60000});
      await sleep(900);
      const mv = await q.evaluate(() => { clearInterval(window.__iv); return {mx: window.__mx, mn: window.__mn}; });
      check(`${label}: lagbytte flytter ikke siden`,
        Math.abs(mv.mx - before) <= 5 && Math.abs(mv.mn - before) <= 5,
        `spørsmålet sto ${before} px fra toppen av skjermen, spenn ${mv.mn}–${mv.mx}`);
      const txt = await q.evaluate(() => document.getElementById('qaAnswer').textContent);
      check(`${label}: svaret er regnet om for det nye laget`, txt.includes('Tromsø'), txt.slice(0, 90));
      await q.close();
    }
    await mob.close();
    await page.bringToFront();

    // ---- 11. OBOS-ligaen: soner, tekster og grenser ----
    setGroup('OBOS-ligaen');
    const ob = await open(1400, 900, base.replace('/eliteserien/', '/obos/'));
    const o1 = await ob.evaluate(() => ({
      liga: LEAGUE.name, id: LEAGUE.id,
      rows: document.querySelectorAll('#tbl tbody tr').length,
      cols: [...document.querySelectorAll('#tbl thead th')].map(t => t.innerText.trim()).filter(Boolean),
      legend: [...document.querySelectorAll('.legend span')].map(s => s.textContent),
      cards: [...document.querySelectorAll('.card-title')].map(t => t.textContent),
      // soneklasse og stiplet linje per plassering
      bands: [...document.querySelectorAll('#tbl tbody tr')].map((tr, i) =>
        `${i + 1}:${[...tr.classList].filter(c => ['cl','eu','playoff','ned','cut'].includes(c)).join('+')}`),
      sums: TEAMS.map(t => lastMC[t].reduce((a, b) => a + b, 0)),
    }));
    check('OBOS: riktig liga og 16 lag', o1.id === 'obos' && o1.rows === 16, `${o1.liga}, ${o1.rows} rader`);
    check('OBOS: kolonnene heter Opprykk, Topp 6 og Nedrykk',
      o1.cols.includes('Opprykk') && o1.cols.includes('Topp 6') && o1.cols.includes('Nedrykk'),
      o1.cols.join(' | '));
    check('OBOS: ingen Gull- eller Topp 4-kolonne',
      !o1.cols.includes('Gull') && !o1.cols.includes('Topp 4'), o1.cols.join(' | '));
    check('OBOS: fargeforklaringen nevner opprykkskvalifisering',
      o1.legend.some(l => /Direkte opprykk \(1 og 2\)/.test(l)) &&
      o1.legend.some(l => /Opprykkskvalifisering \(3 til 6\)/.test(l)), o1.legend.join(' / '));
    check('OBOS: kortene heter Direkte opprykk, Topp 6, Nedrykk',
      o1.cards.slice(0, 3).join(',') === 'Direkte opprykk,Topp 6,Nedrykk', o1.cards.join(','));
    // sonene: 1-2 direkte opprykk, 3-6 opprykkskvalifisering, 14 kvalik, 15-16 ned,
    // med stiplet linje etter 2, 6 og 13
    const vent = ['1:cl','2:cl+cut','3:eu','4:eu','5:eu','6:eu+cut','7:','8:','9:','10:','11:','12:','13:cut','14:playoff','15:ned','16:ned'];
    check('OBOS: sonefarger og stiplede linjer på riktige plasser',
      o1.bands.join(' ') === vent.join(' '), `${o1.bands.join(' ')}\n      ventet: ${vent.join(' ')}`);
    check('OBOS: fordelingen summerer til 1 per lag', o1.sums.every(x => Math.abs(x - 1) < 1e-9));

    // hvert spørsmål må svare med riktig størrelse, og aldri arve Eliteserien-sonene
    const obTeams = await ob.$$eval('#teamSelect option', o => o.map(x => x.value).filter(Boolean));
    const obIds = await ob.evaluate(() => QA_QUESTIONS.map(q => q.id));
    for (const team of [obTeams[0], obTeams[8]]) {
      await ob.select('#teamSelect', team);
      await sleep(300);
      await settle(ob);
      for (const id of obIds) {
        const a = await ob.evaluate(async (id, t) => {
          const q = QA_QUESTIONS.find(x => x.id === id);
          try { return await q.run(t); } catch (e) { return 'ERROR ' + e.message; }
        }, id, team);
        const exp = QA_EXPECT[id];
        const bad = /^ERROR/.test(a) || /undefined|NaN/.test(a);
        const leak = /Europa|topp 4|gullsjansen|seriemester/i.test(a);
        check(`OBOS: ${team} · ${id} (${exp.what})`,
          !bad && !leak && (exp.pat.test(a) || SETTLED.test(a)), a.slice(0, 150));
      }
    }

    // ---- grensene: et lag som flytter seg over hver grense ----
    setGroup('OBOS: grensene');
    const boundaries = [[3, 2, 'eu', 'cl'], [7, 6, '', 'eu'], [15, 14, 'ned', 'playoff'], [14, 13, 'playoff', '']];
    for (const [from, to, clsFrom, clsTo] of boundaries) {
      const r = await ob.evaluate(({from, to}) => {
        // Kunstig scenario: gi laget på plass `from` nok poeng til å gå forbi
        // laget på plass `to`, og ingen andre kamper fylles ut.
        matches.forEach(m => setMatch(m, null, null));
        document.getElementById('autoFillToggle').checked = false;
        const rows = compute().rows;
        const mover = rows[from - 1].name, target = rows[to - 1].name;
        const need = rows[to - 1].pts - rows[from - 1].pts + 1;
        let won = 0;
        matches.filter(m => m.home === mover || m.away === mover).forEach(m => {
          if (won * 3 >= need) return;
          setMatch(m, m.home === mover ? 5 : 0, m.home === mover ? 0 : 5);
          won++;
        });
        render();
        const after = compute().rows;
        const nyPos = after.findIndex(x => x.name === mover) + 1;
        const tr = document.querySelector(`#tbl tbody tr[data-team="${CSS.escape(mover)}"]`);
        const band = LEAGUE.bands.find(b => nyPos >= b.lo && nyPos <= b.hi);
        return {mover, target, need, nyPos, ventetCls: band ? band.cls : '',
                cls: [...tr.classList].filter(c => ['cl','eu','playoff','ned'].includes(c)).join(''),
                tittel: tr.querySelector('td.pos').title || ''};
      }, {from, to});
      check(`${from}. til ${to}. plass: ${r.mover} krysset grensen`, r.nyPos <= to,
        `endte på ${r.nyPos}. plass (trengte ${r.need} poeng)`);
      // Sonefargen skal stemme med plasseringen laget FAKTISK endte på, ikke
      // bare med målplassen: et lag som hopper for langt skal ha sonen der.
      check(`${from}. til ${to}. plass: sonefargen følger ny plassering`,
        r.cls === r.ventetCls, `på ${r.nyPos}. plass fikk "${r.cls}", ventet "${r.ventetCls}"`);
    }
    await ob.evaluate(() => { matches.forEach(m => setMatch(m, null, null)); render(); });
    await ob.close();
    await page.bringToFront();

    // stempelet: dato og klokkeslett skal være ekte tekst, aldri undefined
    setGroup('Stempelet');
    for (const [url, navn] of [[base, 'Eliteserien'], [base.replace('/eliteserien/', '/obos/'), 'OBOS']]) {
      const sp = await open(1400, 900, url);
      await sleep(1200);
      const txt = await sp.evaluate(() => document.querySelector('.stamp').textContent);
      check(`${navn}: stempelet har ingen hull`, !/undefined|NaN|null/.test(txt), txt.slice(0, 140));
      check(`${navn}: neste sjekk har dato`, !/Neste sjekk/.test(txt) || /\d+\. \w+/.test(txt), txt.slice(0, 140));
      await sp.close();
    }
    await page.bringToFront();

    // ---- 11. ligaene skal ikke lekke inn i hverandre ----
    // Ligaene deler domene og dermed localStorage. Følger man Tromsø på
    // Eliteserien-siden, skal OBOS-siden ikke kjenne laget: det spiller ikke
    // der, og spørsmålene skal ikke handle om det.
    setGroup('Ingen lekkasje mellom ligaene');
    const obosUrl = base.replace('/eliteserien/', '/obos/');
    const peek = await open(1400, 900, obosUrl);
    const obosLag = await peek.evaluate(() => TEAMS.slice());
    await peek.close();

    const es = await open(1400, 900, base);
    const fulgt = await es.evaluate(lag => {
      const t = TEAMS.find(x => !lag.includes(x));
      const sel = document.getElementById('teamSelect');
      sel.value = t; sel.dispatchEvent(new Event('change'));
      return t;
    }, obosLag);
    check('fant et lag som bare finnes i Eliteserien', !!fulgt, `fikk "${fulgt}"`);
    await sleep(300);
    const lagret = await es.evaluate(() => Object.fromEntries(
      Object.keys(localStorage).map(k => [k, localStorage.getItem(k)])));
    check('fulgt lag lagres med ligaens id i nøkkelen',
      lagret['eliteserien:followTeam'] === fulgt && lagret.followTeam === undefined,
      JSON.stringify(lagret));
    await es.close();

    const ob2 = await open(1400, 900, obosUrl);
    await settle(ob2);
    const valgt = await ob2.evaluate(() => document.getElementById('teamSelect').value);
    // Enten ingen lag, eller et lag som faktisk spiller i OBOS -- aldri laget
    // fra den andre ligaen. (Testen kjører i samme nettleser som resten, så
    // OBOS kan ha sitt EGET lagrede lag fra en tidligere blokk. Det er riktig.)
    check('OBOS-siden har ikke valgt Eliteserien-laget',
      valgt !== fulgt && (valgt === '' || obosLag.includes(valgt)), `valgte "${valgt}"`);
    const nokler = await ob2.evaluate(() => Object.fromEntries(
      Object.keys(localStorage).map(k => [k, localStorage.getItem(k)])));
    check('ingen ligaløs nøkkel er igjen i localStorage',
      !('followTeam' in nokler) && !('qaOpen' in nokler), JSON.stringify(nokler));
    // Alt brukeren kan lese: overskrifter, banner, lagboks, kort og tabell.
    const synlig = await ob2.evaluate(() => document.body.innerText);
    check(`ingen tekst på OBOS-siden nevner ${fulgt}`, !synlig.includes(fulgt),
      (synlig.split('\n').find(l => l.includes(fulgt)) || '').slice(0, 140));
    // Og hvert spørsmål skal svare om et OBOS-lag, uten spor av det andre laget.
    const obIds2 = await ob2.evaluate(() => QA_QUESTIONS.map(q => q.id));
    for (const id of obIds2) {
      const a = await ob2.evaluate(async (id, t) => {
        const q = QA_QUESTIONS.find(x => x.id === id);
        try { return await q.run(t); } catch (e) { return 'ERROR ' + e.message; }
      }, id, obosLag[0]);
      check(`OBOS · ${id} nevner ikke ${fulgt}`,
        !a.includes(fulgt) && !/^ERROR/.test(a), a.slice(0, 160));
    }
    await ob2.close();
    await page.bringToFront();

    // ---- 12. tallene, ikke ordene ----
    // Kolonnene og kortene skal vise sonen LIGAEN har, ikke Eliteserien sin.
    // Auditen lette bare etter feil ord og så derfor ikke at OBOS viste
    // sjansen for 1. plass under "Opprykk" (som er 1. og 2.) og topp 4 under
    // "Topp 6". Derfor regnes fasiten ut her, fra lastMC og plasseringene
    // under -- som står i TESTEN, ikke i siden, så en feil i LEAGUE også
    // fanges opp.
    setGroup('Tallene i kolonnene og kortene');
    const SONER = {
      eliteserien: {gull: [1, 1], europa: [1, 4], ned: [15, 16]},
      obos:        {gull: [1, 2], europa: [1, 6], ned: [15, 16]},
    };
    for (const [url, liga] of [[base, 'eliteserien'], [obosUrl, 'obos']]) {
      const tp = await open(1400, 900, url);
      await settle(tp);
      const id = await tp.evaluate(() => LEAGUE.id);
      check(`${liga}: siden melder riktig liga-id`, id === liga, `fikk "${id}"`);
      const fasit = SONER[liga];
      const funn = await tp.evaluate(soner => {
        const pct = x => x === 0 ? '0 %' : x < 0.005 ? '<1 %' : x > 0.995 && x < 1 ? '>99 %' : Math.round(x * 100) + ' %';
        const sum = (d, [lo, hi]) => { let v = 0; for (let q = lo; q <= hi; q++) v += d[q - 1]; return v; };
        const celle = {gull: 'td.gull', europa: 'td.p3', ned: 'td.ned'};
        const rader = [...document.querySelectorAll('#tbl tbody tr')].map(tr => {
          const t = tr.dataset.team, d = lastMC[t], o = {team: t};
          for (const k of Object.keys(soner)) {
            const vist = tr.querySelector(celle[k]).textContent.trim();
            const ventet = sum(d, soner[k]);
            o[k] = {vist, ventet: ventet === 0 ? '–' : pct(ventet), andel: ventet};
          }
          return o;
        });
        const kort = {};
        for (const k of Object.keys(soner)) {
          const ul = document.querySelector(`[data-card="${k}"] .card-list`);
          kort[k] = [...ul.querySelectorAll('li')].map(li => ({
            team: (li.querySelector('.card-team') || {}).textContent,
            pct: (li.querySelector('.card-pct') || {}).textContent,
            tom: li.classList.contains('empty'),
          }));
        }
        return {rader, kort};
      }, fasit);
      for (const k of Object.keys(fasit)) {
        const gale = funn.rader.filter(r => r[k].vist !== r[k].ventet);
        check(`${liga}: kolonnen "${k}" viser plass ${fasit[k][0]}–${fasit[k][1]}`, gale.length === 0,
          gale.slice(0, 4).map(r => `${r.team}: viste ${r[k].vist}, ventet ${r[k].ventet}`).join('; '));
        // Kortet skal liste lag fra SAMME sone, med samme prosent som tabellen.
        const rader = funn.kort[k].filter(x => !x.tom);
        const feilKort = rader.filter(x => {
          const r = funn.rader.find(y => y.team === x.team);
          return !r || r[k].ventet !== x.pct;
        });
        check(`${liga}: kortet "${k}" viser samme tall som kolonnen`, feilKort.length === 0,
          feilKort.map(x => `${x.team}: kort ${x.pct}`).join('; '));
        // Et tomt kort er bare riktig hvis ingen lag faktisk er i kampen.
        if (funn.kort[k].some(x => x.tom) && k === 'europa') {
          const iKamp = funn.rader.filter(r => r[k].andel >= 0.05 && r[k].andel <= 0.95);
          check(`${liga}: kortet "${k}" er tomt bare når ingen kjemper om plassene`,
            iKamp.length === 0, `${iKamp.length} lag mellom 5 og 95 %: ` +
            iKamp.slice(0, 4).map(r => `${r.team} ${r[k].ventet}`).join(', '));
        }
      }
      // Merkene skal passe til sonen laget faktisk kjemper om. "Sikret plass"
      // (berget kontrakten) er ikke saken for et lag som fortsatt kan nå topp 6.
    // Regelen gjelder der ligaen ber om den (hideIfChance). OBOS gjør det;
    // Eliteserien viser "Sikret plass" til alle som har berget kontrakten.
      const merker = await tp.evaluate(soner => {
        const sum = (d, [lo, hi]) => { let v = 0; for (let q = lo; q <= hi; q++) v += d[q - 1]; return v; };
        const regler = LEAGUE.badges.filter(b => b.hideIfChance)
          .map(b => ({tekst: b.text, sone: b.hideIfChance.zone, over: b.hideIfChance.over}));
        return {regler, rader: [...document.querySelectorAll('#tbl tbody tr')].map(tr => ({
          team: tr.dataset.team,
          merke: (tr.querySelector('.badge .bt') || {}).textContent || '',
          topp: sum(lastMC[tr.dataset.team], soner.europa),
        }))};
      }, fasit);
      for (const regel of merker.regler) {
        const feilMerke = merker.rader.filter(m => m.merke === regel.tekst && m.topp > regel.over);
        check(`${liga}: "${regel.tekst}" bare for lag uten sjanse i topp-striden`,
          feilMerke.length === 0,
          feilMerke.map(m => `${m.team} har ${Math.round(m.topp * 100)} %`).join('; '));
      }
      await tp.close();
    }
    await page.bringToFront();

    // ---- 13. kamplisten viser bare gjenstående kamper ----
    setGroup('Kamplisten');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      const fp = await open(1400, 900, url);
      const f = await fp.evaluate(() => ({
        spilte: [...document.querySelectorAll('#rounds .match.played')].length,
        igjen: [...document.querySelectorAll('#rounds .match')].length,
        // Merkede runder skal bare finnes der ligaen sier at en runde er flyttet.
        flyttet: [...document.querySelectorAll('#rounds .round.moved')].map(d => +d.dataset.round),
        sierFlyttet: Object.keys(LEAGUE.movedRounds || {}).map(Number),
      }));
      check(`${liga}: kamplisten har ingen spilte kamper`, f.spilte === 0, `fant ${f.spilte}`);
      check(`${liga}: kamplisten har kamper igjen`, f.igjen > 0, `fant ${f.igjen}`);
      check(`${liga}: "(utsatt)" bare der ligaen sier det`,
        f.flyttet.every(r => f.sierFlyttet.includes(r)),
        `merket ${f.flyttet.join(', ')}, ligaen sier ${f.sierFlyttet.join(', ') || 'ingen'}`);
      await fp.close();
    }
    await page.bringToFront();

    // ---- 14. ligavelgeren i overskriften ----
    // Tittelen er en meny som bytter liga. Den skal gå til samme del av siden,
    // og laget du følger skal IKKE bli med over -- det spiller i den andre ligaen.
    setGroup('Ligavelgeren');
    const lp = await open(1400, 900, base);
    await settle(lp);
    const meny = await lp.evaluate(() => {
      const tabs = document.getElementById('leagueTabs');
      return {
        finnes: !!tabs,
        // Nedtrekket i tittelen er borte; tittelen er vanlig tekst.
        nedtrekk: !!(document.getElementById('leagueMenu') || document.getElementById('leagueBtn')),
        tittel: document.getElementById('leagueName').textContent,
        tittelErTekst: !document.querySelector('h1 button'),
        valg: [...(tabs ? tabs.querySelectorAll('a') : [])].map(a => ({
          href: a.getAttribute('href'), navn: a.textContent.trim(),
          her: a.getAttribute('aria-current') === 'page',
        })),
        // Fanene skal stå til HØYRE for logoen, før seksjonslenkene.
        etterLogo: tabs ? tabs.compareDocumentPosition(document.querySelector('.brand')) === Node.DOCUMENT_POSITION_PRECEDING : false,
        forLenker: tabs ? tabs.compareDocumentPosition(document.getElementById('navLinks')) === Node.DOCUMENT_POSITION_FOLLOWING : false,
        // Seksjonslenkene skal være urørt.
        lenker: [...document.querySelectorAll('#navLinks a[data-target]')].map(a => a.dataset.target),
      };
    });
    check('ligafanene ligger i toppmenyen', meny.finnes && meny.etterLogo && meny.forLenker,
      JSON.stringify({finnes: meny.finnes, etterLogo: meny.etterLogo, forLenker: meny.forLenker}));
    check('nedtrekket i tittelen er borte', !meny.nedtrekk && meny.tittelErTekst,
      `nedtrekk=${meny.nedtrekk}, tittelErTekst=${meny.tittelErTekst}`);
    check('tittelen er ligaens navn og sesong', /^Eliteserien \d{4}$/.test(meny.tittel), meny.tittel);
    check('fanene har begge ligaene', meny.valg.length === 2
      && meny.valg.some(v => v.href === '/eliteserien/') && meny.valg.some(v => v.href === '/obos/'),
      JSON.stringify(meny.valg));
    check('ligaen du er på er merket', meny.valg.filter(v => v.her).length === 1
      && meny.valg.find(v => v.her).href === '/eliteserien/', JSON.stringify(meny.valg));
    check('seksjonslenkene står der de står',
      JSON.stringify(meny.lenker) === JSON.stringify(['tabell', 'fxPanel', 'qaPanel', 'omModellen']),
      meny.lenker.join(', '));
    // Mobil: fanene på egen linje under logoen, så seksjonslenkene ikke blir trangere.
    await lp.setViewport({width: 390, height: 844});
    await sleep(400);
    const fanerMobil = await lp.evaluate(() => {
      const t = document.getElementById('leagueTabs').getBoundingClientRect();
      const n = document.querySelector('.nav-links').getBoundingClientRect();
      const b = document.querySelector('.brand').getBoundingClientRect();
      return {egenLinje: t.bottom <= n.top + 1, underLogo: t.top >= b.top,
              innenfor: t.left >= -1 && t.right <= innerWidth + 1,
              scroll: document.documentElement.scrollWidth - document.documentElement.clientWidth};
    });
    check('mobil: fanene har egen linje under logoen',
      fanerMobil.egenLinje && fanerMobil.underLogo, JSON.stringify(fanerMobil));
    check('mobil: fanene er innenfor skjermen, ingen sidelengs scroll',
      fanerMobil.innenfor && fanerMobil.scroll === 0, JSON.stringify(fanerMobil));
    await lp.setViewport({width: 1400, height: 900});
    await sleep(300);
    // Følg et lag, stå i kamplisten, og bytt.
    await lp.evaluate(lag => {
      const s = document.getElementById('teamSelect');
      s.value = lag; s.dispatchEvent(new Event('change'));
      location.hash = '#fxPanel';
    }, fulgt);
    await sleep(400);
    await lp.evaluate(() => document.querySelector('#leagueTabs a[data-league="obos"]').click());
    await sleep(1500);
    await lp.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 120000});
    const etter = await lp.evaluate(() => ({
      url: location.href, tittel: document.getElementById('leagueName').textContent,
      lag: document.getElementById('teamSelect').value, tekst: document.body.innerText,
      herHref: (() => {
        const a = [...document.querySelectorAll('#leagueTabs a')].find(x => x.getAttribute('aria-current'));
        return a ? a.getAttribute('href') : null;
      })(),
    }));
    check('byttet går til samme del av siden', /\/obos\/#fxPanel$/.test(etter.url), etter.url);
    check('tittelen viser den nye ligaen', /^OBOS-ligaen \d{4}$/.test(etter.tittel), etter.tittel);
    check('den nye ligaen er markert som aktiv', etter.herHref === '/obos/', String(etter.herHref));
    check('fulgt lag følger ikke med over', etter.lag === '' || obosLag.includes(etter.lag), `valgte "${etter.lag}"`);
    check(`ingen tekst nevner ${fulgt} etter byttet`, !etter.tekst.includes(fulgt),
      (etter.tekst.split('\n').find(l => l.includes(fulgt)) || '').slice(0, 120));
    await lp.close();
    await page.bringToFront();

    // ---- 15. forsiden ----
    // Folk sendes rett til ligaen de sist brukte, førstegangsbesøkende til
    // Eliteserien. Teksten og lenkene skal likevel STÅ i HTML-en, for
    // søkemotorer og for /?velg.
    setGroup('Forsiden');
    const rot = base.replace('/eliteserien/', '/');
    const ferskt = async (url) => {
      const ctx = await browser.createBrowserContext();
      const p = await ctx.newPage();
      await p.setViewport({width: 1400, height: 900});
      await p.goto(url, {waitUntil: 'networkidle0'});
      await sleep(900);
      const u = p.url();
      await ctx.close();
      return u;
    };
    check('førstegangsbesøk sendes til Eliteserien', /\/eliteserien\/$/.test(await ferskt(rot)),
      await ferskt(rot));
    // Forsiden har ingen simulering, så den vanlige open() (som venter på
    // lastMCFinal) kan ikke brukes her.
    const oversikt = await browser.newPage();
    oversikt.on('pageerror', e => errors.push(`${rot}?velg: ${e.message}`));
    await oversikt.setViewport({width: 1400, height: 900});
    await oversikt.goto(rot + '?velg', {waitUntil: 'networkidle0'});
    await sleep(600);
    const fp2 = await oversikt.evaluate(() => ({
      url: location.href,
      lenker: [...document.querySelectorAll('.leagues a')].map(a => a.getAttribute('href')),
      tekst: document.body.innerText,
    }));
    check('/?velg blir stående på oversikten', /\?velg$/.test(fp2.url), fp2.url);
    check('oversikten lenker til begge ligaene',
      fp2.lenker.includes('/eliteserien/') && fp2.lenker.includes('/obos/'), fp2.lenker.join(', '));
    check('oversikten omtaler begge ligaene',
      /Eliteserien/.test(fp2.tekst) && /OBOS-ligaen/.test(fp2.tekst), fp2.tekst.slice(0, 120));
    await oversikt.close();
    // Og HTML-en selv, uten JS, slik en søkemotor først ser den.
    const raa = await (await fetch(rot)).text().catch(() => '');
    if (raa) {
      check('lenkene står i HTML-en, ikke bare etter JS',
        raa.includes('href="/eliteserien/"') && raa.includes('href="/obos/"'), 'fant dem ikke');
    }
    await page.bringToFront();

    // ---- 16. lagfarger ----
    // Hver liga har sine egne klubbfarger. Ingen lag skal falle til den
    // nøytrale reservefargen -- da ville OBOS-lagene fått Tabellkalkulators
    // egen blå i stedet for draktfargen sin.
    setGroup('Lagfarger');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      const cp = await open(1400, 900, url);
      const farger = await cp.evaluate(() => {
        const felt = ['fill', 'deep', 'fillText', 'textLight', 'textDark', 'topDark', 'topDeepDark'];
        const mangler = TEAMS.filter(t => !TEAM_COLORS[t]);
        const ufullstendig = TEAMS.filter(t => TEAM_COLORS[t] &&
          felt.some(f => !/^#[0-9a-f]{6}$/i.test(TEAM_COLORS[t][f] || '')));
        // To lag KAN ha samme farge: bare ett lag vises om gangen, så de står
        // aldri side om side (Lillestrøm og Start i Eliteserien, Bryne,
        // Kongsvinger og Lyn i OBOS). Kravet er at hvert lag HAR en farge.
        return {
          lag: TEAMS.length, mangler, ufullstendig,
          reserve: NEUTRAL_ACCENT.fill,
          somReserve: TEAMS.filter(t => TEAM_COLORS[t] && TEAM_COLORS[t].fill === NEUTRAL_ACCENT.fill),
          ekstra: Object.keys(TEAM_COLORS).filter(t => !TEAMS.includes(t)),
        };
      });
      check(`${liga}: alle ${farger.lag} lag har en farge`, farger.mangler.length === 0,
        `mangler: ${farger.mangler.join(', ')}`);
      check(`${liga}: alle fargene har alle sju variantene`, farger.ufullstendig.length === 0,
        farger.ufullstendig.join(', '));
      check(`${liga}: ingen bruker reservefargen`, farger.somReserve.length === 0,
        `${farger.somReserve.join(', ')} har ${farger.reserve}`);
      check(`${liga}: ingen farger for lag som ikke er i ligaen`, farger.ekstra.length === 0,
        farger.ekstra.join(', '));
      // Og fargen skal faktisk bli brukt når laget følges, ikke bare finnes.
      const brukt = await cp.evaluate(() => {
        const t = TEAMS[0];
        const s = document.getElementById('teamSelect');
        s.value = t; s.dispatchEvent(new Event('change'));
        const v = getComputedStyle(document.documentElement).getPropertyValue('--team-fill').trim();
        return {t, v, ventet: TEAM_COLORS[t].fill};
      });
      check(`${liga}: fargen tas i bruk når laget følges`,
        brukt.v.toLowerCase() === brukt.ventet.toLowerCase(),
        `${brukt.t}: siden brukte ${brukt.v}, ventet ${brukt.ventet}`);
      await cp.close();
    }
    await page.bringToFront();

    // ---- 17. forrige kamp mot forventningen før avspark ----
    // Tallet skal komme fra det som var lagret FØR kampen (prekick.json),
    // ellers sluttoddsen. Aldri regnet på nytt nå: dagens lagstyrker har sett
    // resultatet, og da ville "overraskende" vært etterpåklokskap.
    setGroup('Forrige kamp mot forventningen');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      const fk = await open(1400, 900, url);
      await settle(fk);
      const f = await fk.evaluate(() => {
        // Kilden skal aldri være dagens modell.
        const kilder = new Set();
        const linjer = [];
        for (const t of TEAMS) {
          const e = lastMatchEntry(t);
          if (!e) continue;
          const p = e.home ? preKickProbs(e.home, e.away) : null;
          if (p) kilder.add(p.kilde);
          const l = qaLastMatchLine(e);
          if (l) linjer.push({team: t, html: l.html, harTall: !!p,
                              sum: p ? p.H + p.U + p.B : null});
        }
        return {kilder: [...kilder], linjer, prekick: PREKICK ? Object.keys(PREKICK).length : 0,
                closing: CLOSING ? Object.keys(CLOSING).length : 0};
      });
      check(`${liga}: kildene er lagrede tall, ikke dagens modell`,
        f.kilder.every(k => ['odds og modell', 'modellen', 'sluttoddsen'].includes(k)),
        f.kilder.join(', '));
      const medTall = f.linjer.filter(l => l.harTall);
      check(`${liga}: sannsynlighetene summerer til 1`,
        medTall.every(l => Math.abs(l.sum - 1) < 1e-3),
        medTall.filter(l => Math.abs(l.sum - 1) >= 1e-3).map(l => `${l.team}: ${l.sum}`).join('; '));
      // Der vi har tallet, skal linja si hvor overraskende resultatet var,
      // fra lagets synsvinkel ("tap", ikke "borteseier").
      // "bare" er fjernet fra ordlyden: siden oppgir sannsynligheten, den
      // vurderer den ikke.
      const mangler = medTall.filter(l => !/(ventet i (<1|>99|\d+) % av tilfellene|med (<1|\d+) % sjanse)/.test(l.html));
      check(`${liga}: linja sier hvor overraskende resultatet var`,
        mangler.length === 0, mangler.slice(0, 3).map(l => `${l.team}: ${l.html}`).join(' | '));
      const galtOrd = medTall.filter(l => /(hjemmeseier|borteseier) (som var ventet|med bare)/.test(l.html));
      check(`${liga}: ordlyden er lagets egen (seier/tap/uavgjort)`,
        galtOrd.length === 0, galtOrd.slice(0, 2).map(l => l.html).join(' | '));
      // Og det skal faktisk finnes tall å bruke for minst ett lag.
      check(`${liga}: har lagrede tall å måle mot`,
        f.prekick + f.closing > 0, `prekick ${f.prekick}, sluttodds ${f.closing}`);
      // Kjernen: tallet skal være endringen mot FORVENTNINGEN, ikke mot seier.
      // Et tap som var ventet i 72 % av tilfellene kan ikke flytte sjansen
      // mer enn avstanden fra forventningen til utfallet.
      const regnestykke = await fk.evaluate(async () => {
        const ut = [];
        for (const t of TEAMS) {
          const d = await qaLastMatchData(t);
          if (!d || d.noMatch || d.pp == null) continue;
          const sjanse = o => o === d.actual ? d.tableP
            : Math.min(1, Math.max(0, d.tableP + d.alts.find(x => x.o === o).d));
          const qFor = o => o === 'draw' ? 'U' : ((o === 'win') === d.isHome ? 'H' : 'B');
          const E = ['win', 'draw', 'loss'].reduce((s, o) => s + (d.preKick[qFor(o)] || 0) * sjanse(o), 0);
          // Avstanden fra forventningen til det beste/verste utfallet: pp kan
          // aldri være større enn spennet mellom utfallene.
          const alle = ['win', 'draw', 'loss'].map(sjanse);
          ut.push({team: t, pp: d.pp, E, tableP: d.tableP,
                   ventet: Math.round(d.tableP * 100) - Math.round(E * 100),
                   spenn: (Math.max(...alle) - Math.min(...alle)) * 100,
                   pSum: ['win', 'draw', 'loss'].reduce((s, o) => s + (d.preKick[qFor(o)] || 0), 0)});
        }
        return ut;
      });
      const feilPp = regnestykke.filter(r => r.pp !== r.ventet);
      check(`${liga}: pp er endringen mot forventningen`, feilPp.length === 0,
        feilPp.slice(0, 3).map(r => `${r.team}: pp ${r.pp}, mot forventning ${r.ventet}`).join('; '));
      const forStort = regnestykke.filter(r => Math.abs(r.pp) > r.spenn + 1);
      check(`${liga}: pp er aldri større enn spennet mellom utfallene`,
        forStort.length === 0,
        forStort.slice(0, 3).map(r => `${r.team}: pp ${r.pp}, spenn ${r.spenn.toFixed(0)}`).join('; '));
      check(`${liga}: utfallssannsynlighetene før kampen summerer til 1`,
        regnestykke.every(r => Math.abs(r.pSum - 1) < 1e-3),
        regnestykke.filter(r => Math.abs(r.pSum - 1) >= 1e-3).map(r => `${r.team}: ${r.pSum}`).join('; '));
      await fk.close();
    }
    await page.bringToFront();

    // ---- 18. rulling til svaret på iPad-bredder ----
    // Trykker man på et spørsmål, skal SPØRSMÅLET stå øverst, rett under den
    // faste menylinja, med svaret under. Før ble svaret rullet inn med
    // block:'nearest', og på iPad havnet spørsmålet nederst på skjermen.
    setGroup('Rulling til svaret');
    for (const [w, h] of [[768, 1024], [820, 1180], [1024, 768], [1180, 820], [1366, 1024]]) {
      const sp = await open(w, h, obosUrl);
      await settle(sp);
      await sp.evaluate(() => { qaSetOpen(true); });
      await sleep(300);
      await sp.evaluate(() => document.querySelector('#qaButtons button').click());
      await sp.waitForFunction(
        'document.getElementById("qaAnswer") && document.getElementById("qaAnswer").textContent.length > 20',
        {timeout: 60000});
      await sleep(1400);   // den myke rullingen må få gå ferdig
      const r = await sp.evaluate(() => {
        const item = document.querySelector('.qa-item.active');
        const q = item.querySelector('button').getBoundingClientRect();
        const nav = document.querySelector('.topnav').getBoundingClientRect();
        const svar = document.getElementById('qaAnswer').getBoundingClientRect();
        return {qTop: Math.round(q.top), navBunn: Math.round(nav.bottom),
                svarTop: Math.round(svar.top), vh: innerHeight,
                scroll: document.documentElement.scrollWidth - document.documentElement.clientWidth};
      });
      // Under menylinja, ikke bak den.
      check(`${w} px: spørsmålet står under menylinja`, r.qTop >= r.navBunn - 2,
        `spørsmål ${r.qTop}, menylinja slutter ${r.navBunn}`);
      // Øverst, ikke nederst: godt over midten av skjermen.
      check(`${w} px: spørsmålet står øverst, ikke nederst`, r.qTop < r.vh * 0.5,
        `spørsmål ${r.qTop} av ${r.vh} px høyde`);
      // Og svaret skal begynne på skjermen, ikke under kanten.
      check(`${w} px: svaret begynner synlig`, r.svarTop < r.vh,
        `svaret starter ${r.svarTop} av ${r.vh}`);
      check(`${w} px: ingen sidelengs scroll`, r.scroll === 0, `${r.scroll} px`);
      await sp.close();
    }
    await page.bringToFront();

    // ---- 19. tokolonnesgrensen på 1100 px ----
    // iPad Air på tvers (1180) får tabell og sidekolonne ved siden av hverandre,
    // 1024 beholder én kolonne. Tabellen skal få plass uten å scrolle sidelengs
    // -- målt på .tblwrap rundt #tbl, ikke på en av tabellene i forklaringene.
    setGroup('Tokolonnesgrensen');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      for (const [w, h, kol] of [[1024, 768, 1], [1099, 800, 1], [1100, 800, 2], [1180, 820, 2], [1219, 900, 2], [1366, 1024, 2]]) {
        const gp = await open(w, h, url);
        await sleep(500);
        const r = await gp.evaluate(() => {
          const g = getComputedStyle(document.querySelector('.wrap')).gridTemplateColumns.split(' ').filter(Boolean).length;
          const tw = document.getElementById('tbl').parentElement;
          const ikon = [...document.querySelectorAll('#tbl .badge .bt')].some(b => b.offsetParent !== null);
          return {g, scroll: tw.scrollWidth - tw.clientWidth, tekstmerke: ikon,
                  side: document.documentElement.scrollWidth - document.documentElement.clientWidth};
        });
        check(`${liga} ${w} px: ${kol} kolonne${kol > 1 ? 'r' : ''}`, r.g === kol, `fikk ${r.g}`);
        check(`${liga} ${w} px: tabellen scroller ikke sidelengs`, r.scroll <= 0 && r.side === 0,
          `tabell ${r.scroll} px, side ${r.side} px`);
        if (w >= 1100 && w <= 1219) {
          check(`${liga} ${w} px: merket vises som ikon`, !r.tekstmerke, 'merketekst synlig');
        }
        await gp.close();
      }
    }
    await page.bringToFront();

    // ---- 20. "Siste runde" sammenfoldet som standard, valget huskes per liga ----
    setGroup('Forrige runde');
    {
      const ctx = await browser.createBrowserContext();   // rent localStorage
      const nySide = async (url, w, h) => {
        const p = await ctx.newPage();
        p.on('pageerror', e => errors.push(`${url}: ${e.message}`));
        await p.setViewport({width: w, height: h});
        await p.goto(url, {waitUntil: 'networkidle0'});
        await p.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 120000});
        return p;
      };
      const tilstand = p => p.evaluate(() => {
        const el = document.getElementById('recentPanel');
        const s = el.querySelector('summary');
        return {open: el.open, tittel: s.textContent.replace(/\s+/g, ' ').trim(),
                // checkVisibility, ikke offsetParent: Chrome skjuler innholdet i en lukket
                // <details> med content-visibility, og da er offsetParent fortsatt satt.
                kamperSynlige: [...el.querySelectorAll('.match')].some(m => m.checkVisibility())};
      });
      for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
        for (const [w, h, enhet] of [[1400, 900, 'PC'], [390, 844, 'mobil']]) {
          const p = await nySide(url, w, h);
          const t = await tilstand(p);
          check(`${liga} ${enhet}: sammenfoldet som standard`, !t.open && !t.kamperSynlige, JSON.stringify(t));
          check(`${liga} ${enhet}: overskriften viser runden`, /^Forrige runde .*Runde \d+/.test(t.tittel), t.tittel);
          await p.close();
        }
      }
      // Åpne på Eliteserien: huskes der, men ikke på OBOS.
      let p = await nySide(base, 1400, 900);
      await p.click('#recentPanel > summary');
      await sleep(300);
      const etterKlikk = await tilstand(p);
      check('åpnes med et trykk på overskriften', etterKlikk.open && etterKlikk.kamperSynlige, JSON.stringify(etterKlikk));
      await p.close();
      p = await nySide(base, 1400, 900);
      check('Eliteserien husker at den er åpnet', (await tilstand(p)).open);
      await p.close();
      p = await nySide(obosUrl, 1400, 900);
      check('OBOS er fortsatt sammenfoldet (valget gjelder én liga)', !(await tilstand(p)).open);
      const nokkel = await p.evaluate(() => Object.keys(localStorage).filter(k => /recentOpen/.test(k)));
      check('valget lagres med ligaens id i nøkkelen', nokkel.length === 1 && nokkel[0] === 'eliteserien:recentOpen',
        nokkel.join(', '));
      await p.close();
      await ctx.close();
    }
    await page.bringToFront();

    // ---- 21. trykk i tabellen: lagnavnet følger laget, Form-tallet viser grafen ----
    setGroup('Trykk i tabellen');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      for (const [w, h, enhet] of [[1400, 900, 'PC'], [390, 844, 'mobil']]) {
        const ctx = await browser.createBrowserContext();
        const p = await ctx.newPage();
        p.on('pageerror', e => errors.push(`${url}: ${e.message}`));
        await p.setViewport({width: w, height: h});
        await p.goto(url, {waitUntil: 'networkidle0'});
        await p.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 120000});
        const lag = await p.evaluate(() => TEAMS[3]);
        const tilstand = () => p.evaluate(() => ({
          valgt: document.getElementById('teamSelect').value,
          fulgt: (document.querySelector('#tbl tr.followed') || {}).dataset?.team || '',
          boks: !document.getElementById('verdict').hidden,
          graf: !document.getElementById('formModalBackdrop').hidden,
        }));
        // Lagnavnet: velger laget, som "Følg laget ditt", og åpner ikke grafen.
        await p.click(`#tbl .teamname[data-team="${lag}"]`);
        await sleep(600);
        let t = await tilstand();
        check(`${liga} ${enhet}: trykk på lagnavnet følger laget`,
          t.valgt === lag && t.fulgt === lag && t.boks, JSON.stringify(t));
        check(`${liga} ${enhet}: lagnavnet åpner ikke formgrafen`, !t.graf, JSON.stringify(t));
        // Et nytt trykk på samme lag velger det bort.
        await p.click(`#tbl .teamname[data-team="${lag}"]`);
        await sleep(600);
        t = await tilstand();
        check(`${liga} ${enhet}: nytt trykk velger laget bort`, t.valgt === '' && t.fulgt === '', JSON.stringify(t));
        // Form-tallet: åpner formgrafen for riktig lag, og endrer ikke hvilket lag som følges.
        await p.click(`#tbl button.formbox[data-team="${lag}"]`);
        await sleep(400);
        t = await tilstand();
        const tittel = await p.evaluate(() => document.getElementById('formModalTitle').textContent);
        check(`${liga} ${enhet}: trykk på Form-tallet åpner formgrafen for laget`,
          t.graf && tittel === lag, `${JSON.stringify(t)} tittel "${tittel}"`);
        check(`${liga} ${enhet}: Form-tallet endrer ikke fulgt lag`, t.valgt === '', JSON.stringify(t));
        await ctx.close();
      }
    }
    await page.bringToFront();

    // ---- 22. "Rundens viktigste kamp i ligaen" følger den faste malen ----
    setGroup('Rundens viktigste kamp');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      const kp = await open(1400, 900, url);
      await settle(kp);
      const svar = await kp.evaluate(async () => {
        const q = QA_QUESTIONS.find(x => x.id === 'keyround');
        return await q.run('');
      });
      const l = svar.split('\n');
      check(`${liga}: første linje sier kamp og strid`,
        /^Rundens viktigste kamp er .+ mot .+ \S+ \d+\. \w+\. Den påvirker .+ mest\.$/.test(l[0]), l[0]);
      check(`${liga}: andre linje sier hvem kampen betyr mest for`,
        /^Kampen betyr mest for .+:$/.test(l[1]), l[1]);
      // Nøyaktig tre utfallslinjer, og bare ett lag får tall.
const PCTL = String.raw`(?:\d+ %|<1 %|>99 %)`;
      const utfall = l.slice(2, 5);
      const egen = utfall.every((x, i) => new RegExp(`^${['Seier', 'Uavgjort', 'Tap'][i]}: ${PCTL}$`).test(x));
      const annet = utfall.every((x, i) => new RegExp(i === 1 ? `^Uavgjort: ${PCTL}$` : `^.+-seier: ${PCTL}$`).test(x));
      check(`${liga}: tre utfall, i rekkefølgen seier, uavgjort, tap`, egen || annet, utfall.join(' | '));
      check(`${liga}: så dagens nivå`, new RegExp(`^.+(sjansen|faren) er ${PCTL} før kampen\.$`).test(l[5]), l[5]);
      // Resten: retning uten tall.
      const rest = l.slice(6).join(' ');
      check(`${liga}: de andre lagene får ingen tall`,
        !rest || !new RegExp(PCTL).test(rest.replace(/ligger like bak.*/, '')), rest.slice(0, 160));
      check(`${liga}: bare ett lag har utfallstall`,
        (svar.match(new RegExp(PCTL, 'g')) || []).length === 4,
        (svar.match(new RegExp(PCTL, 'g')) || []).join(', '));
      await kp.close();
    }
    await page.bringToFront();

    // ---- 23. kamplisten: odds-merket og utsatte kamper ----
    setGroup('Kamplisten');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      const kl = await open(1400, 900, url);
      const r = await kl.evaluate(() => {
        const merke = document.querySelector('#rounds .pct.src.odds');
        const muted = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim();
        const hex = c => '#' + (c.match(/\d+/g) || []).slice(0, 3)
          .map(x => (+x).toString(16).padStart(2, '0')).join('');
        // Runder der en kamp er merket utsatt: datospennet i overskriften skal
        // ikke dekke den kampen.
        const runder = [...document.querySelectorAll('#rounds .round')].map(d => ({
          tittel: d.querySelector('h3').textContent.replace(/\s+/g, ' ').trim(),
          utsatte: [...d.querySelectorAll('.match .when .ut')].length,
          datoer: [...d.querySelectorAll('.match')].map(m => m.dataset.date || ''),
        }));
        return {harMerke: !!merke, farge: merke ? hex(getComputedStyle(merke).color) : null,
                muted, utsatte: runder.reduce((a, x) => a + x.utsatte, 0), runder};
      });
      if (r.harMerke) {
        check(`${liga}: "odds"-merket er dempet, ikke rødt`, r.farge === r.muted.toLowerCase(),
          `merket ${r.farge}, dempet ${r.muted}`);
      }
      // Alle utsatte kamper ligger etter datospennet i overskriften sin.
      const feil = r.runder.filter(x => x.utsatte > 0 && !/\d+\. \w+/.test(x.tittel));
      check(`${liga}: runder med utsatt kamp har fortsatt et datospenn`, feil.length === 0,
        feil.map(x => x.tittel).join('; '));
      await kl.close();
    }
    await page.bringToFront();

    // ---- 24. Styrke og Form er to ulike tall ----
    setGroup('Styrke og Form');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      const sp = await open(1400, 900, url);
      await settle(sp);
      const r = await sp.evaluate(() => {
        const hd = [...document.querySelectorAll('#tbl thead th')].map(t => t.textContent.trim());
        const rader = [...document.querySelectorAll('#tbl tbody tr')].map(tr => ({
          lag: tr.dataset.team,
          styrke: parseFloat((tr.querySelector('.formbox') || {}).textContent.replace(',', '.')),
          form: parseFloat(((tr.querySelector('.form5') || {}).textContent || '').replace(',', '.')),
          tips: ((tr.querySelector('.form5') || {}).title || ''),
        }));
        // Fasit regnet på nytt fra resultatrutene: vanlige poeng, 3 for seier
        // og 1 for uavgjort, delt på maks mulige og ganget med 10.
        const fasit = {};
        [...document.querySelectorAll('#tbl tbody tr')].forEach(tr => {
          const res = [...tr.querySelectorAll('.form b')].map(b => b.className);
          fasit[tr.dataset.team] = res.length
            ? res.reduce((a, c) => a + (c === 'W' ? 3 : c === 'D' ? 1 : 0), 0) / (3 * res.length) * 10
            : null;
        });
        // Selve regnestykket, mot tallene oppgaven navngir.
        const skala = {
          femSeirer: form5From(['W', 'W', 'W', 'W', 'W']),
          femUavgjort: form5From(['D', 'D', 'D', 'D', 'D']),
          femTap: form5From(['L', 'L', 'L', 'L', 'L']),
          toKamper: form5From(['W', 'D']),
          ingen: form5From([]),
        };
        return {hd, rader, fasit, skala,
                kort: [...document.querySelectorAll('.card .card-title')].map(e => e.textContent)};
      });
      check(`${liga}: kolonnen heter Form`, r.hd.includes('Form'), r.hd.join(' | '));
      check(`${liga}: kolonnen Styrke står ved siden av`, r.hd.includes('Styrke'), r.hd.join(' | '));
      check(`${liga}: ingen kolonne heter "Siste 5" lenger`, !r.hd.includes('Siste 5'), r.hd.join(' | '));
      check(`${liga}: kortet heter Styrke`, r.kort.includes('Styrke'), r.kort.join(', '));

      // Skalaen: fem seirer = 15 av 15 = 10,0, fem uavgjorte = 5 av 15 = 3,3.
      check(`${liga}: fem seirer gir 10,0`, Math.abs(r.skala.femSeirer - 10) < 1e-9, `${r.skala.femSeirer}`);
      check(`${liga}: fem uavgjorte gir 3,3`, Math.abs(r.skala.femUavgjort - 10 / 3) < 1e-9, `${r.skala.femUavgjort}`);
      check(`${liga}: fem tap gir 0,0`, r.skala.femTap === 0, `${r.skala.femTap}`);
      // Uavgjort er en tredjedel av en seier, ikke en halv: en 2-1-0-skala
      // ville gitt 5,0 for fem uavgjorte.
      check(`${liga}: uavgjort teller en tredjedel, ikke en halv`,
        Math.abs(r.skala.femUavgjort - 5) > 1, `${r.skala.femUavgjort}`);
      check(`${liga}: færre enn fem kamper regnes av dem som er spilt`,
        Math.abs(r.skala.toKamper - 4 / 6 * 10) < 1e-9, `${r.skala.toKamper}`);
      check(`${liga}: ingen kamper gir ingen tall`, r.skala.ingen === null, `${r.skala.ingen}`);

      const feil = r.rader.filter(x => Math.abs(x.form - r.fasit[x.lag]) > 0.051);
      check(`${liga}: Form er regnet av de samme rutene`, feil.length === 0,
        feil.slice(0, 3).map(x => `${x.lag}: ${x.form} mot ${r.fasit[x.lag]}`).join('; '));
      check(`${liga}: begge tallene finnes for alle lagene`,
        r.rader.every(x => !Number.isNaN(x.styrke) && !Number.isNaN(x.form)),
        `${r.rader.length} rader`);
      // Tipsteksten viser regnestykket, og sier antallet når det er under fem.
      const tipsFeil = r.rader.filter(x => !/^\d+ av \d+ poeng i (den siste kampen|de (to|tre|fire|fem) siste)$/.test(x.tips));
      check(`${liga}: tipsteksten viser regnestykket`, tipsFeil.length === 0,
        tipsFeil.slice(0, 3).map(x => `${x.lag}: "${x.tips}"`).join('; '));
      // De to tallene er ikke det samme: det er hele poenget med å vise begge.
      const like = r.rader.filter(x => Math.abs(x.styrke - x.form) < 0.05).length;
      check(`${liga}: Styrke og Form er ikke samme tall`, like < r.rader.length / 2,
        `${like} av ${r.rader.length} rader like`);

      const sortert = await sp.evaluate(() => {
        cycleSort('form5');
        return [...document.querySelectorAll('#tbl tbody tr')]
          .map(tr => parseFloat(((tr.querySelector('.form5') || {}).textContent || '').replace(',', '.')));
      });
      check(`${liga}: Form kan sorteres`,
        sortert.every((v, i) => i === 0 || sortert[i - 1] >= v), sortert.join(' '));
      await sp.close();
    }
    await page.bringToFront();

    // ---- 25. Merkenavn, Nullstill i overskriften, oddsmerket, formtallet ----
    // Synlighet måles med checkVisibility({visibilityProperty:true}), ALDRI med
    // .hidden-egenskapen: Nullstill-knappen sto synlig i produksjon fordi
    // .head-reset{display:inline-flex} slår nettleserens [hidden]{display:none},
    // og en test som leste .hidden så ingenting galt.
    setGroup('Toppmeny, Nullstill, odds og form');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      for (const w of [320, 500, 1400]) {
        const sp = await open(w, 900, url);
        await settle(sp);
        const synlig = 'checkVisibility({visibilityProperty:true})';
        const f = await sp.evaluate(() => {
          const el = document.querySelector('.brand span');
          const hr = document.getElementById('headReset');
          const rn = document.getElementById('roundNav').getBoundingClientRect();
          return {navn: el.checkVisibility({visibilityProperty:true}) && el.getBoundingClientRect().width > 10,
                  navnTekst: el.textContent.trim(),
                  knapp: hr.checkVisibility({visibilityProperty:true}),
                  rnL: Math.round(rn.left), rnT: Math.round(rn.top),
                  scroll: document.documentElement.scrollWidth - document.documentElement.clientWidth};
        });
        check(`${liga} ${w}px: merkenavnet vises`, f.navn && f.navnTekst === 'Tabellkalkulator', f.navnTekst);
        check(`${liga} ${w}px: ingen vannrett sidescroll`, f.scroll <= 0, `${f.scroll}`);
        check(`${liga} ${w}px: Nullstill er skjult uten scenario`, !f.knapp);

        const e = await sp.evaluate(() => { setMatch(matches[0], 2, 1); render(); return null; });
        await new Promise(r => setTimeout(r, 900));
        const g = await sp.evaluate(() => {
          const hr = document.getElementById('headReset');
          const rn = document.getElementById('roundNav').getBoundingClientRect();
          const b = hr.getBoundingClientRect();
          return {knapp: hr.checkVisibility({visibilityProperty:true}),
                  tekst: hr.querySelector('span').checkVisibility(),
                  rnL: Math.round(rn.left), rnT: Math.round(rn.top),
                  overlapp: b.right > rn.left + 0.5};
        });
        check(`${liga} ${w}px: Nullstill vises når et scenario er aktivt`, g.knapp);
        check(`${liga} ${w}px: rundevelgeren står stille`,
          g.rnL === f.rnL && g.rnT === f.rnT, `${f.rnL},${f.rnT} -> ${g.rnL},${g.rnT}`);
        check(`${liga} ${w}px: Nullstill dekker ikke rundevelgeren`, !g.overlapp);
        check(`${liga} ${w}px: ${w >= 500 ? 'tekst ved siden av ikonet' : 'bare ikon'}`,
          g.tekst === (w >= 500));
        // Knappen gjør samme jobb som den nede ved kamplisten.
        const h = await sp.evaluate(() => {
          document.getElementById('headReset').click();
          return {igjen: matches.filter(m => m.hg != null).length,
                  forklaring: document.getElementById('resetSaid').textContent};
        });
        check(`${liga} ${w}px: Nullstill tømmer scenarioet`, h.igjen === 0, `${h.igjen}`);
        check(`${liga} ${w}px: forklaringen vises ved trykk`,
          /nullstilt/i.test(h.forklaring), h.forklaring);
        await sp.close();
      }

      // Oddsmerket: popoveren viser desimaloddsen, kilden og tidspunktet.
      const sp = await open(1400, 900, url);
      await settle(sp);
      const o = await sp.evaluate(() => {
        const merker = [...document.querySelectorAll('.pct.odds[data-mid]')];
        if (!merker.length) return {antall: 0};
        merker[0].click();
        const pop = document.getElementById('oddsPop');
        const m = matches.find(x => String(x.id) === String(merker[0].dataset.mid));
        const info = RATES[m.home + '|' + m.away];
        return {antall: merker.length, apen: !pop.hidden,
                tall: [...pop.querySelectorAll('.rad b')].map(x => parseFloat(x.textContent.replace(',', '.'))),
                // Er råoddsen lagret, skal DEN vises. Ellers den marginfrie,
                // og da SKAL forbeholdet stå.
                raa: (info.meta && info.meta.odds) || null,
                fasit: ((info.meta && info.meta.odds)
                  ? [info.meta.odds.H, info.meta.odds.U, info.meta.odds.B]
                  : info.mk.map(x => 1 / x)).map(x => +x.toFixed(2)),
                tekst: pop.textContent.replace(/\s+/g, ' '),
                liste: [...document.querySelectorAll('.match .pct[data-o]')].slice(0, 3).map(x => x.textContent.trim())};
      });
      check(`${liga}: oddsmerket åpner oddsen`, o.antall > 0 && o.apen, `${o.antall} merker`);
      check(`${liga}: oddsen i boksen er den lagrede`,
        o.tall && o.tall.every((v, i) => Math.abs(v - o.fasit[i]) < 0.011),
        `${(o.tall || []).join('/')} mot ${(o.fasit || []).join('/')}`);
      // Med råodds: ingen forklaring, for tallet ER prisen. Uten: forbeholdet
      // må stå, så et marginfritt tall ikke leses som en pris.
      const harForbehold = /Råoddsen er ikke lagret/.test(o.tekst || '');
      check(`${liga}: forbeholdet står bare når råoddsen mangler`,
        o.raa ? !harForbehold : harForbehold,
        o.raa ? 'råodds lagret' : 'ingen råodds');
      check(`${liga}: listen viser fortsatt sannsynligheter`,
        (o.liste || []).every(t => /%$/.test(t)), (o.liste || []).join(' '));

      // Formtallet står til HØYRE for resultatrutene.
      const fm = await sp.evaluate(() => {
        const rader = [...document.querySelectorAll('#tbl tbody tr')].map(tr => {
          const t = tr.querySelector('.form5'), r = tr.querySelector('.form');
          if (!t || !r) return null;
          const tb = t.getBoundingClientRect(), rb = r.getBoundingClientRect();
          return {begge: tb.width > 0 && rb.width > 0, hoyre: tb.left >= rb.right - 0.5};
        }).filter(Boolean);
        return {n: rader.filter(x => x.begge).length, ok: rader.filter(x => x.begge).every(x => x.hoyre)};
      });
      check(`${liga}: formtallet står til høyre for rutene`, fm.n > 0 && fm.ok, `${fm.n} rader`);
      await sp.close();
    }
    await page.bringToFront();

    // ---- 26. Nullstill begge veier, ny ordlyd, og "Ditt scenario" ----
    // Ikke alle lag har en forventning: en kamp uten pris i sluttoddsvinduet
    // har ingen, og da sier svaret det i stedet for å gjette.
    const TEAMS_MIN = 10;
    setGroup('Nullstill, ordlyd og scenariosum');
    for (const [url, liga, lag] of [[base, 'Eliteserien', 'Brann'], [obosUrl, 'OBOS', 'Bryne']]) {
      for (const w of [390, 1400]) {
        const sp = await open(w, 900, url);
        await settle(sp);
        const synlig = () => sp.evaluate(() =>
          document.getElementById('headReset').checkVisibility({visibilityProperty: true}));
        check(`${liga} ${w}px: Nullstill skjult på frisk side`, !(await synlig()));
        // Simuler slik en bruker gjør: klikk knappen, ikke sett matches direkte.
        await sp.evaluate(() => document.getElementById('simRest').click());
        await new Promise(r => setTimeout(r, 2500));
        const etterSim = await sp.evaluate(() => ({
          synlig: document.getElementById('headReset').checkVisibility({visibilityProperty: true}),
          sim: matches.filter(m => m.sim).length,
        }));
        check(`${liga} ${w}px: Nullstill kommer fram når man simulerer`,
          etterSim.synlig && etterSim.sim > 0, `synlig=${etterSim.synlig} sim=${etterSim.sim}`);
        // ... og forsvinner igjen når man nullstiller.
        await sp.evaluate(() => document.getElementById('headReset').click());
        await new Promise(r => setTimeout(r, 1200));
        const etterNull = await sp.evaluate(() => ({
          synlig: document.getElementById('headReset').checkVisibility({visibilityProperty: true}),
          igjen: matches.filter(m => m.hg != null).length,
        }));
        check(`${liga} ${w}px: Nullstill forsvinner når scenarioet tømmes`,
          !etterNull.synlig && etterNull.igjen === 0,
          `synlig=${etterNull.synlig} igjen=${etterNull.igjen}`);

        // "Ditt scenario": bare når alle lagets egne kamper er fylt inn selv.
        await sp.evaluate((t) => {
          const s = document.getElementById('teamSelect');
          s.value = t; s.dispatchEvent(new Event('change', {bubbles: true}));
        }, lag);
        await new Promise(r => setTimeout(r, 2200));
        const tom = await sp.evaluate(() => !!document.querySelector('.scenario-sum'));
        check(`${liga} ${w}px: ingen scenariosum uten resultater`, !tom);
        await sp.evaluate((t) => {
          matches.filter(m => m.home === t || m.away === t)
            .forEach(m => setMatch(m, m.home === t ? 2 : 0, m.home === t ? 0 : 2));
          render();
        }, lag);
        await new Promise(r => setTimeout(r, 2800));
        const sum = await sp.evaluate(() => {
          const el = document.querySelector('.scenario-sum');
          return el ? el.textContent.trim() : null;
        });
        check(`${liga} ${w}px: scenariosum vises når lagets kamper er fylt`,
          !!sum && /^Ditt scenario: med disse resultatene ender .+ på \d+ poeng\. .+ sjanse for .+\.$/.test(sum),
          sum || '(mangler)');
        // Simuleres resten, er hele sesongen fylt og prosenten sier ingenting.
        await sp.evaluate(() => document.getElementById('simRest').click());
        await new Promise(r => setTimeout(r, 2800));
        const etter = await sp.evaluate(() => !!document.querySelector('.scenario-sum'));
        check(`${liga} ${w}px: scenariosum borte når hele sesongen er fylt`, !etter);
        await sp.close();
      }

      // Ordlyden i "Hva betydde forrige kamp": tre avsnitt, riktige ord.
      const sp = await open(1400, 900, url);
      await settle(sp);
      const svar = await sp.evaluate(async () => {
        const ut = [];
        for (const t of TEAMS) ut.push([t, await qaLastMatch(t)]);
        return ut;
      });
      const medForventning = svar.filter(([, tx]) => /ventet når alle mulige utfall/.test(tx));
      check(`${liga}: svarene har en forventning å måle mot`,
        medForventning.length >= TEAMS_MIN, `${medForventning.length} av ${svar.length}`);
      const avsnitt = medForventning.filter(([, tx]) => tx.split('\n\n').length === 3);
      check(`${liga}: svaret står i tre avsnitt`,
        avsnitt.length === medForventning.length,
        `${avsnitt.length} av ${medForventning.length}`);
      const ordlyd = medForventning.filter(([, tx]) =>
        /Før kampen var .+ ventet når alle mulige utfall ble tatt med/.test(tx) &&
        /\d+ prosentpoeng (bedre|verre) enn ventet/.test(tx) &&
        /Med \w+ ville .+ vært /.test(tx));
      check(`${liga}: ny ordlyd i alle svarene`, ordlyd.length === medForventning.length,
        (medForventning.find(([, tx]) => !ordlyd.some(([t2]) => t2 === tx)) || ['', ''])[1].slice(0, 120));
      const gamle = svar.filter(([, tx]) =>
        /når alle tre mulige utfall/.test(tx) ||
        /Før kampen var den forventede/.test(tx) ||
        /prosentpoeng (høyere|lavere|mer|mindre) enn forventet/.test(tx) ||
        /ga \w+ bare \d/.test(tx) || /mest sannsynlige/.test(tx));
      check(`${liga}: ingen rester av gammel ordlyd`, gamle.length === 0,
        (gamle[0] || ['', ''])[1].slice(0, 120));
      await sp.close();
    }
    await page.bringToFront();

    // ---- 27. Nullstill rydder også adressen ----
    // "Del scenario" legger scenariet i hashen. Nullstill tømte tabellen, men
    // lot s= stå -- og en oppfriskning leste scenariet inn igjen, så tabellen
    // fylte seg selv på nytt.
    setGroup('Nullstill rydder adressen');
    for (const [url, liga, lag] of [[base, 'Eliteserien', 'Brann'], [obosUrl, 'OBOS', 'Bryne']]) {
      for (const knapp of ['reset', 'headReset']) {
        const sp = await open(1400, 900, url);
        await settle(sp);
        await sp.evaluate(t => { const s = document.getElementById('teamSelect');
          s.value = t; s.dispatchEvent(new Event('change', {bubbles: true})); }, lag);
        await new Promise(r => setTimeout(r, 1800));
        await sp.evaluate(t => { matches.filter(m => m.home === t || m.away === t).slice(0, 3)
          .forEach(m => setMatch(m, m.home === t ? 2 : 0, m.home === t ? 0 : 2)); render(); }, lag);
        await new Promise(r => setTimeout(r, 2200));
        await sp.evaluate(() => document.getElementById('share').click());
        await new Promise(r => setTimeout(r, 700));
        const med = await sp.evaluate(() => location.hash);
        check(`${liga}/${knapp}: "Del scenario" legger scenariet i adressen`, /s=/.test(med), med.slice(0, 40));
        await sp.evaluate(i => document.getElementById(i).click(), knapp);
        await new Promise(r => setTimeout(r, 1200));
        const etter = await sp.evaluate(() => ({hash: location.hash,
          fylte: matches.filter(m => m.hg != null).length}));
        check(`${liga}/${knapp}: nullstill tømmer tabellen`, etter.fylte === 0, `${etter.fylte}`);
        check(`${liga}/${knapp}: nullstill fjerner scenariet fra adressen`,
          !/s=/.test(etter.hash), etter.hash || '(tom)');
        // Det avgjørende: en oppfriskning skal ikke hente scenariet tilbake.
        await sp.reload({waitUntil: 'networkidle0', timeout: 60000});
        await settle(sp);
        await new Promise(r => setTimeout(r, 1500));
        const igjen = await sp.evaluate(() => ({fylte: matches.filter(m => m.hg != null).length,
                                                lag: SELECTED_TEAM}));
        check(`${liga}/${knapp}: oppfriskning gir ikke scenariet tilbake`, igjen.fylte === 0,
          `${igjen.fylte} fylte`);
        check(`${liga}/${knapp}: fulgt lag er beholdt`, igjen.lag === lag, igjen.lag);
        await sp.close();
      }
    }
    await page.bringToFront();

    // ---- 28. Linja under "Neste kamp" ----
    // Lagvalget settes via adressen, så det gjelder ALLEREDE ved sidelasting:
    // linja manglet nettopp da, fordi kortet tegnes før simuleringen er ferdig
    // og fillOdds() ikke oppdaterte den. Et lagbytte i testen ville skjult det.
    setGroup('Neste kamp: hva utfallene betyr');
    for (const [url, liga] of [[base, 'Eliteserien'], [obosUrl, 'OBOS']]) {
      const finn = await open(1400, 900, url);
      await settle(finn);
      const valg = await finn.evaluate(() => {
        let hjemme = null, borte = null;
        for (const t of TEAMS) {
          const m = matches.find(x => x.home === t || x.away === t);
          if (!m) continue;
          if (m.home === t && !hjemme) hjemme = t;
          if (m.away === t && !borte) borte = t;
        }
        return {hjemme, borte};
      });
      await finn.close();
      for (const [rolle, lag] of [['hjemmelag', valg.hjemme], ['bortelag', valg.borte]]) {
        if (!lag) continue;
        const sp = await open(1400, 900, url + '#team=' + encodeURIComponent(lag));
        await settle(sp);
        await new Promise(r => setTimeout(r, 1500));
        const r = await sp.evaluate(() => ({
          lag: SELECTED_TEAM,
          synlig: document.getElementById('nmImpact').checkVisibility({visibilityProperty: true}),
          tekst: document.getElementById('nmImpact').textContent,
        }));
        check(`${liga}: linja er der ved sidelasting (fulgt ${rolle})`,
          r.synlig && r.tekst.trim().length > 10, r.tekst.trim().slice(0, 60) || '(tom)');
        // Utfallet etter tallet: H/U/B over gjelder hjemmelaget, så "seier 5 %"
        // ble lest som hjemmeseier når man fulgte bortelaget.
        check(`${liga}: utfallet står etter tallet (fulgt ${rolle})`,
          /% med seier, .+% med uavgjort, .+% med tap\.$/.test(r.tekst.trim()), r.tekst.trim());
        check(`${liga}: sjansen er lagets egen (fulgt ${rolle})`,
          r.tekst.includes(`for ${r.lag}`), `${r.lag}`);
        await sp.close();
      }
      // Uten fulgt lag skal linja ikke vises.
      const u = await open(1400, 900, url + '#team=');
      await settle(u);
      await new Promise(r => setTimeout(r, 1200));
      check(`${liga}: linja er skjult uten fulgt lag`,
        await u.evaluate(() => !document.getElementById('nmImpact').checkVisibility({visibilityProperty: true})));
      await u.close();
    }
    await page.bringToFront();

    setGroup('JS-feil');
    check('ingen feil i konsollen', errors.length === 0, errors.join('\n      '));
    await page.close();
  } finally {
    await browser.close();
    if (server) server.close();
  }

  const failed = results.filter(r => !r.ok);
  console.log(`\n${results.length - failed.length} av ${results.length} tester gikk gjennom.`);
  if (failed.length) {
    console.log('\nFeilet:');
    failed.forEach(f => console.log(`  ${f.group} · ${f.name}`));
  }
  return failed.length ? 1 : 0;
}

main().then(c => process.exit(c)).catch(e => { console.error(e); process.exit(1); });
