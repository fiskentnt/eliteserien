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
  luck:       {what: 'poengavvik',    pat: /[+−]\d+,\d/},
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
      /(Rundens viktigste kamp|kamper betyr omtrent like mye)/.test(banner.txt) &&
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
      const before = await q.evaluate(() => Math.round(window.scrollY));
      await q.evaluate(() => { window.__mx = 0; window.__mn = 1e9;
        window.__iv = setInterval(() => { const y = Math.round(window.scrollY);
          window.__mx = Math.max(window.__mx, y); window.__mn = Math.min(window.__mn, y); }, 20); });
      await q.select('#teamSelect', 'Tromsø');
      await q.waitForFunction(`(()=>{const a=document.getElementById('qaAnswer');return a&&!a.classList.contains('loading')&&qaAnswerKey===qaStateKey()})()`, {timeout: 60000});
      await sleep(900);
      const mv = await q.evaluate(() => { clearInterval(window.__iv); return {mx: window.__mx, mn: window.__mn}; });
      check(`${label}: lagbytte flytter ikke siden`,
        Math.abs(mv.mx - before) <= 5 && Math.abs(mv.mn - before) <= 5,
        `sto på ${before}, spenn ${mv.mn}–${mv.mx}`);
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
    check('OBOS: fargeforklaringen nevner opprykksspill',
      o1.legend.some(l => /Direkte opprykk \(1 og 2\)/.test(l)) &&
      o1.legend.some(l => /Opprykksspill \(3 til 6\)/.test(l)), o1.legend.join(' / '));
    check('OBOS: kortene heter Direkte opprykk, Topp 6, Nedrykk',
      o1.cards.slice(0, 3).join(',') === 'Direkte opprykk,Topp 6,Nedrykk', o1.cards.join(','));
    // sonene: 1-2 direkte opprykk, 3-6 opprykksspill, 14 kvalik, 15-16 ned,
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
