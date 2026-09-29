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

// Grunnlagsfilen (<liga>/data/grunnlag.json) svarer 404 som standard, så
// testene prøver sidens egen regning, som før filen fantes (den brukes fortsatt
// med et scenario). Testsidens fil ligger i elo-test/emodell. Gruppen
// «Grunnlagsfilen på siden» slår den på:
//   {}                          filen fra repoet
//   {innhold: {<liga>: tekst}}  dette innholdet i stedet
//   {forsinkelse: ms}           svaret kommer så mye senere
let GRUNNLAG_MODUS = null;
// Sesongstart: med SESONGSTART = true svarer serveren som før første
// serierunde: matches.json er tom, og alle de spilte kampene står som uspilte i
// terminlisten (fixtures.json), i sin egen runde. Gjelder alle sidene
// (testsiden leser kampene fra eliteserien/data).
let SESONGSTART = false;
function sesongstartData(rot, liga, fil) {
  if (fil === 'matches') return '[]';
  const M = JSON.parse(fs.readFileSync(path.join(rot, liga, 'data', 'matches.json'), 'utf8'));
  const F = JSON.parse(fs.readFileSync(path.join(rot, liga, 'data', 'fixtures.json'), 'utf8'));
  for (const m of M) {
    let r = F.find(x => x.round === m.round);
    if (!r) { r = {round: m.round, when: '', matches: []}; F.push(r); }
    r.matches.push({home: m.home, away: m.away, date: m.date, time: m.time, played: false, hg: null, ag: null});
  }
  F.sort((a, b) => a.round - b.round);
  return JSON.stringify(F);
}
function serve(rot = ROOT) {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p.endsWith('/')) p += 'index.html';
    const f = path.join(rot, p);
    const sm = SESONGSTART && /^\/([^/]+)\/data\/(matches|fixtures)\.json$/.exec(p);
    if (sm) { res.writeHead(200, {'Content-Type': 'application/json'}); res.end(sesongstartData(rot, sm[1], sm[2])); return; }
    const gm = /^\/([^/]+)\/(?:data|emodell)\/grunnlag\.json$/.exec(p);
    if (gm) {
      const modus = GRUNNLAG_MODUS;
      const svar = () => {
        const inn = modus && modus.innhold && modus.innhold[gm[1]] != null ? modus.innhold[gm[1]]
          : modus && fs.existsSync(f) ? fs.readFileSync(f) : null;
        if (inn == null) { res.writeHead(404); res.end(); return; }
        res.writeHead(200, {'Content-Type': 'application/json'}); res.end(inn);
      };
      if (modus && modus.forsinkelse) setTimeout(svar, modus.forsinkelse); else svar();
      return;
    }
    if (!f.startsWith(rot) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
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
// Prosenttall med vanlig mellomrom, slik utfallslinjene i rundesvaret skriver dem.
const PCTL = String.raw`(?:\d+ %|<1 %|>99 %)`;
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
  // Vanskeligst/lettest: begge ytterpunktene skal ha et tall.
  hardest:    {what: 'prosent',       pat: new RegExp(PCT)},
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
  // Klikk som en bruker, men med elementet midt i vinduet. puppeteer ruller
  // bare når elementet er utenfor vinduet, og den faste menyen øverst dekker
  // et element som ligger rett under den (29.9.2026: Nullstill lå under menyen
  // når kortet "Neste kamp" var skjult, og klikket traff menyen).
  const klikk = async (pg, sel) => { await pg.$eval(sel, el => el.scrollIntoView({block: 'center'})); await pg.click(sel); };
  const settle = page => page.waitForFunction(
    'lastMCFinal===true && lastMCScenarioKey===qaScenarioKey()', {timeout: 120000});
  // Utfyllingsknappene er asynkrone, og scenarionøkkelen rekker ikke å endre
  // seg før settle() ville sagt "ferdig". Vent på at kampene faktisk er fylt.
  const filled = (page, n) => page.waitForFunction(
    `matches.filter(m=>m.hg!=null).length===${n}`, {timeout: 120000});

  // Treffsikkerhetsdelen: teksten uten kamper, med 1 kamp, 3 kamper samme dag
  // og over to dager, over månedsskiftet og med 50 kamper, på alle tre
  // sidene. Datoene skrives helt ut, med måneden bare én gang når den er lik.
  // Kjøres med resten av suiten, eller alene:
  //   node tests/regression.js --bare treffsikkerhet
  const treffsikkerhetTekst = async () => {
    setGroup('Treffsikkerhet og sluttoddsen: teksten i modellsjekken');
    const lite = 'og sier lite før det er flere.';
    const tilfeller = [
      {navn: 'ingen kamper', n: 0, fra: null, til: null,
       ventet: 'Treffsikkerheten vises her etter hvert som kampene spilles. De første tallene kommer etter neste runde.'},
      {navn: '1 kamp', n: 1, fra: '2026-10-02', til: '2026-10-02', ventet: `Tallene bygger på 1 kamp, ${lite} Kampen ble spilt 2. oktober.`},
      {navn: '3 kamper samme dag', n: 3, fra: '2026-10-02', til: '2026-10-02', ventet: `Tallene bygger på 3 kamper, ${lite} Kampene ble spilt 2. oktober.`},
      {navn: '3 kamper over to dager', n: 3, fra: '2026-10-02', til: '2026-10-03', ventet: `Tallene bygger på 3 kamper, ${lite} Kampene ble spilt mellom 2. og 3. oktober.`},
      {navn: 'kamper over månedsskiftet', n: 3, fra: '2026-09-30', til: '2026-10-02', ventet: `Tallene bygger på 3 kamper, ${lite} Kampene ble spilt mellom 30. september og 2. oktober.`},
      {navn: '50 kamper', n: 50, fra: '2026-10-02', til: '2026-11-08', ventet: 'Tallene bygger på 50 kamper. Kampene ble spilt mellom 2. oktober og 8. november.'},
    ];
    for (const sti of ['/eliteserien/', '/obos/', '/elo-test/']) {
      const feil0 = errors.length;
      const pg = await open(1400, 900, base.replace('/eliteserien/', sti));
      const r = await pg.evaluate(t => t.map(c => {
        const kilde = {n: c.n, treff: 0.5, logloss: 1.01};
        renderAccuracy({n: c.n, fra: c.fra, til: c.til, kilder: c.n ? {side: kilde, modell: kilde, odds: kilde} : {}, kalibrering: []});
        const el = document.getElementById('accuracyLog'), ps = [...el.querySelectorAll('p.note')];
        return {tekst: ps.length ? ps[ps.length - 1].textContent.trim() : '',
                forklaring: ps.length > 1 ? ps[0].textContent.trim() : '',
                kamper: [...el.querySelectorAll('tbody tr td:nth-child(2)')].map(x => x.textContent)};
      }), tilfeller);
      // Avsnittet om sluttoddsen i "Hvordan vet vi at modellen virker?", med
      // log loss-tallet under "Vis detaljer".
      const sl = await pg.evaluate(() => {
        const h = [...document.querySelectorAll('.modelcheck h3')].find(x => x.textContent === 'Hvorfor oddsen hentes rett før avspark');
        if (!h) return null;
        const ps = [], d = [];
        for (let e = h.nextElementSibling; e && e.tagName !== 'H3'; e = e.nextElementSibling) {
          if (e.tagName === 'P') ps.push(e.textContent.trim());
          if (e.tagName === 'DETAILS') d.push(e.querySelector('summary').textContent.trim(), e.querySelector('p').textContent.trim());
        }
        return {ps, d};
      });
      await pg.close();
      const side = sti.replace(/\//g, '');
      tilfeller.forEach((c, i) => check(`${side}: ${c.navn}: "${c.ventet}"`,
        r[i].tekst === c.ventet && (c.n === 0 ? r[i].kamper.length === 0 : r[i].kamper.length === 3 && r[i].kamper.every(k => k === String(c.n))),
        JSON.stringify(r[i])));
      check(`${side}: forklaringen til tabellen har "Traff utfallet" med vanlige anførselstegn`,
        r.filter((x, i) => tilfeller[i].n > 0).every(x => x.forklaring.startsWith('"Traff utfallet" er hvor ofte')) && !r.some(x => x.forklaring.includes('«')),
        JSON.stringify(r.map(x => x.forklaring)));
      const slVentet = [
        'Sluttoddsen er den siste oddsen vi henter mellom 60 og 15 minutter før avspark. Da er som regel også laguttaket kjent.',
        'Dette har faktisk betydning. I 351 kamper i Eliteserien og OBOS endret sannsynlighetene seg i snitt 2,9 prosentpoeng fra dagen før til rett før kamp. I 2–4 prosent av kampene skiftet også favoritten. Oddsen rett før kamp traff litt bedre enn oddsen fra dagen før.',
        'Får vi ikke hentet odds i dette tidsrommet, står kampen uten sluttodds. Vi bruker aldri en eldre odds i stedet.'];
      check(`${side}: avsnittet om sluttoddsen, med log loss-tallet under "Vis detaljer"`,
        !!sl && JSON.stringify(sl.ps) === JSON.stringify(slVentet) && sl.d[0] === 'Vis detaljer'
          && /0,0082 ± 0,0041 høyere log loss enn sluttoddsen, altså 2,0 standardfeil/.test(sl.d[1] || '')
          && /0,0130 i Eliteserien \(2,3 standardfeil\) og 0,0024 i OBOS \(0,4 standardfeil/.test(sl.d[1] || ''),
        JSON.stringify(sl));
      // Ingen « » i det brukeren ser: teksten på siden (også lukkede
      // seksjoner) og anførselstegnene banneret setter rundt spørsmålet.
      const gaase = await (async () => {
        const p2 = await open(1400, 900, base.replace('/eliteserien/', sti));
        const r2 = await p2.evaluate(async () => {
          // Tekstnodene utenfor <script> og <style>: det siden viser, også i
          // lukkede seksjoner.
          const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT,
            {acceptNode: n => ['SCRIPT', 'STYLE'].includes(n.parentNode.nodeName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
          const funn = [];
          for (let n = w.nextNode(); n; n = w.nextNode()) if (/[«»]/.test(n.nodeValue)) funn.push(n.nodeValue.trim().slice(0, 80));
          // Banneret med et valgt lag er et spørsmål i anførselstegn.
          const sel = document.getElementById('teamSelect'); sel.value = TEAMS[0]; sel.dispatchEvent(new Event('change'));
          await new Promise(r => setTimeout(r, 300));
          const el = document.getElementById('qaHighlight');
          return {tekst: funn.slice(0, 5), sporsmal: !el.classList.contains('plain'),
                  foer: getComputedStyle(el, '::before').content, etter: getComputedStyle(el, '::after').content};
        });
        await p2.close();
        return r2;
      })();
      check(`${side}: ingen « » i teksten på siden, og banneret bruker vanlige anførselstegn`,
        !gaase.tekst.length && gaase.sporsmal && gaase.foer === '"\\""' && gaase.etter.startsWith('"\\"') && !/[«»]/.test(gaase.foer + gaase.etter),
        JSON.stringify(gaase));
      check(`${side}: ingen JS-feil`, errors.length === feil0, errors.slice(feil0).join('; '));
    }
  };

  // ---- Sesongstart: siden uten spilte kamper ----
  // Før første serierunde er matches.json tom. Stempelet øverst leste da
  // datoen til siste resultat (last.date), og tabellteksten den siste kampen,
  // uten at noen fantes: oppstarten stoppet, og tabellen ble aldri regnet. På
  // alle tre sidene: tabellen regnes, stempelet og tabellteksten sier at ingen
  // kamper er spilt, alle spørsmålene svarer, et innfylt resultat regnes som
  // vanlig, og ingen JS-feil. Kjøres med resten av suiten, eller alene:
  //   node tests/regression.js --bare sesongstart
  // ---- "Del scenario": én knapp ----
  // På PC og Mac kopieres lenken, også når nettleseren har navigator.share. På
  // berøringsskjerm (ingen hover, grov peker) åpnes systemets delingsmeny, og
  // lenken kopieres når den ikke finnes, eller når menyen avviser delingen av
  // en annen grunn enn at brukeren avbrøt. Del-knappen øverst gjør det samme og
  // beholder ikonet. "Del …" (egen knapp for systemmenyen) finnes ikke lenger.
  // navigator.share og utklippstavlen byttes ut med opptakere, så testen ser
  // hva knappene gjør uten systemdialog. Kjøres med resten av suiten, eller alene:
  //   node tests/regression.js --bare del
  const delKnapp = async () => {
    setGroup('"Del scenario": én knapp, delingsmenyen bare på berøringsskjerm');
    const {KnownDevices} = require('puppeteer-core');
    const prov = async (side, {telefon = false, share = true, shareFeil = null} = {}) => {
      const url = base.replace('/eliteserien/', `/${side}/`);
      const pg = await browser.newPage();
      const feil0 = errors.length;
      pg.on('pageerror', e => errors.push(`${url} (del): ${e.message}`));
      if (telefon) await pg.emulate(KnownDevices['iPhone 13']); else await pg.setViewport({width: 1280, height: 900});
      await pg.goto(url, {waitUntil: 'networkidle0'});
      await pg.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 120000});
      await pg.evaluate(() => { matches.filter(x => x.hg == null).slice(0, 2).forEach(x => setMatch(x, 2, 1)); render(); });
      await pg.waitForFunction('lastMCFinal===true && lastMCScenarioKey===qaScenarioKey()', {timeout: 120000});
      const r = await pg.evaluate(async (share, shareFeil) => {
        const delt = [], kopiert = [];
        navigator.clipboard.writeText = async t => { kopiert.push(t); };
        if (share) navigator.share = async d => { delt.push(d.url); if (shareFeil) { const e = new Error(shareFeil); e.name = shareFeil; throw e; } };
        else { try { delete Navigator.prototype.share; } catch (_) {} try { delete navigator.share; } catch (_) {} }
        const vent = () => new Promise(ok => setTimeout(ok, 300));
        const knapper = [...document.querySelectorAll('.tools button.share')].filter(b => !b.hidden).map(b => b.textContent.trim());
        document.getElementById('share').click(); await vent();
        const bunn = {delt: delt.splice(0), kopiert: kopiert.splice(0), tekst: document.getElementById('share').textContent.trim()};
        document.getElementById('headShare').click(); await vent();
        const h = document.getElementById('headShare');
        const topp = {delt: delt.splice(0), kopiert: kopiert.splice(0), tekst: h.textContent.trim(), ikon: !!h.querySelector('svg')};
        return {knapper, finnesDelPrikker: !!document.getElementById('shareSystem'), beroring: matchMedia('(hover: none) and (pointer: coarse)').matches,
                url: scenarioUrl(), adresse: location.href, bunn, topp};
      }, share, shareFeil);
      r.jsFeil = errors.slice(feil0);
      errors.splice(feil0);
      await pg.close();
      return r;
    };
    for (const side of ['eliteserien', 'obos', 'elo-test']) {
      const pc = await prov(side), tlf = await prov(side, {telefon: true});
      check(`${side}: én delingsknapp nederst ("Del scenario"), og "Del …" finnes ikke`,
        JSON.stringify(pc.knapper) === '["Del scenario"]' && !pc.finnesDelPrikker && JSON.stringify(tlf.knapper) === '["Del scenario"]', JSON.stringify([pc.knapper, tlf.knapper]));
      check(`${side}: på PC kopierer "Del scenario" og Del øverst lenken, også når navigator.share finnes, og ikonet øverst står`,
        !pc.beroring && pc.bunn.delt.length === 0 && JSON.stringify(pc.bunn.kopiert) === JSON.stringify([pc.url]) && pc.bunn.tekst === 'Lenke kopiert'
          && pc.topp.delt.length === 0 && JSON.stringify(pc.topp.kopiert) === JSON.stringify([pc.url]) && pc.topp.tekst === 'Lenke kopiert' && pc.topp.ikon
          && pc.adresse === pc.url && pc.jsFeil.length === 0, JSON.stringify(pc).slice(0, 500));
      check(`${side}: på telefon åpner begge knappene delingsmenyen med lenken, og ingenting kopieres`,
        tlf.beroring && JSON.stringify(tlf.bunn.delt) === JSON.stringify([tlf.url]) && tlf.bunn.kopiert.length === 0
          && JSON.stringify(tlf.topp.delt) === JSON.stringify([tlf.url]) && tlf.topp.kopiert.length === 0 && tlf.jsFeil.length === 0, JSON.stringify(tlf).slice(0, 500));
    }
    const uten = await prov('eliteserien', {telefon: true, share: false});
    check('telefon uten navigator.share: lenken kopieres', uten.bunn.delt.length === 0 && JSON.stringify(uten.bunn.kopiert) === JSON.stringify([uten.url])
      && JSON.stringify(uten.topp.kopiert) === JSON.stringify([uten.url]), JSON.stringify(uten).slice(0, 400));
    const avbrutt = await prov('eliteserien', {telefon: true, shareFeil: 'AbortError'});
    check('telefon, brukeren avbryter delingsmenyen: ingenting kopieres', avbrutt.bunn.delt.length === 1 && avbrutt.bunn.kopiert.length === 0
      && avbrutt.bunn.tekst === 'Del scenario', JSON.stringify(avbrutt).slice(0, 400));
    const avvist = await prov('eliteserien', {telefon: true, shareFeil: 'NotAllowedError'});
    check('telefon, delingsmenyen avviser av en annen grunn: lenken kopieres', avvist.bunn.delt.length === 1
      && JSON.stringify(avvist.bunn.kopiert) === JSON.stringify([avvist.url]), JSON.stringify(avvist).slice(0, 400));
  };
  const sesongstart = async () => {
    setGroup('Sesongstart: siden uten spilte kamper');
    if (live) { console.log('  (hoppes over med --live: trenger den lokale serveren)'); return; }
    SESONGSTART = true;
    try {
      for (const side of ['eliteserien', 'obos', 'elo-test']) {
        const feil0 = errors.length, url = base.replace('/eliteserien/', `/${side}/`);
        const pg = await browser.newPage();
        pg.on('pageerror', e => errors.push(`${url} (uten spilte kamper): ${e.message}`));
        await pg.setViewport({width: 1400, height: 900});
        await pg.goto(url, {waitUntil: 'networkidle0'});
        const ferdig = await pg.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 60000})
          .then(() => true, () => false);
        const r = !ferdig ? null : await pg.evaluate(async () => {
          const vent = f => new Promise(ok => { const i = setInterval(() => { if (f()) { clearInterval(i); ok(); } }, 20); });
          const sum1 = () => TEAMS.every(t => Math.abs(lastMC[t].reduce((a, b) => a + b, 0) - 1) < 1e-9);
          const rader = [...document.querySelectorAll('#tbl tbody tr')];
          const tabell = {spilt: MATCHES.length, lag: TEAMS.length, sum: sum1(),
            celler: rader.length === TEAMS.length && rader.every(tr => tr.querySelector('td.gull') && tr.querySelector('td.gull').textContent.trim() !== '')};
          const tekst = {stempel: document.querySelector('.stamp').textContent, info: document.getElementById('tblInfo').textContent};
          const lag = TEAMS[0], sel = document.getElementById('teamSelect');
          sel.value = lag; sel.dispatchEvent(new Event('change'));
          await new Promise(ok => setTimeout(ok, 500));
          const svar = {};
          for (const q of QA_QUESTIONS) {
            try { svar[q.id] = String(await q.run(lag, () => {})); } catch (e) { svar[q.id] = `KASTET: ${e.message}`; }
          }
          // Alle lagene: plassen i tabellen er tilfeldig før første kamp og
          // nevnes ikke, og "altså 61 poeng til" gjentar bare tallet.
          const plassord = /(første|andre|tredje|fjerde|femte|sjette)plassen|\d+\. plass|serieleder/;
          const alle = {hvorfor: [], ende: [], hva: []};
          for (const t of TEAMS) {
            const hv = await qaWhy(t), en = qaRange(t), hm = await qaHowTo(t);
            if (plassord.test(hv)) alle.hvorfor.push(`${t}: ${hv.split('\n')[0]}`);
            if (/ligger på \d+\. plass nå/.test(en)) alle.ende.push(`${t}: ${en}`);
            if (/poeng til/.test(hm)) alle.hva.push(`${t}: ${hm.split('\n')[0]}`);
          }
          const m = matches.find(x => x.hg == null);
          m.hg = 1; m.ag = 0; mcStraks = true; render();
          await vent(() => lastMCFinal && lastMCScenarioKey === qaScenarioKey());
          const etter = {scenario: qaScenarioKey() !== '', sum: sum1()};
          m.hg = null; m.ag = null; render();
          return {tabell, tekst, svar, alle, etter};
        });
        await pg.close();
        check(`${side}: uten spilte kamper blir tabellen regnet (16 lag, fordelingen summerer til 1, prosentene vises)`,
          !!r && r.tabell.spilt === 0 && r.tabell.lag === 16 && r.tabell.sum && r.tabell.celler, JSON.stringify(r && r.tabell));
        check(`${side}: stempelet og tabellteksten sier at ingen kamper er spilt`,
          !!r && r.tekst.stempel.startsWith('Ingen kamper er spilt ennå.') && r.tekst.info === 'før første runde', JSON.stringify(r && r.tekst));
        const ids = r ? Object.keys(r.svar) : [];
        check(`${side}: alle ${ids.length} spørsmålene i "Spør om tabellen" svarer`,
          ids.length >= 12 && ids.every(k => r.svar[k].length > 10 && !r.svar[k].startsWith('KASTET') && r.svar[k] !== 'Ingen data å regne på ennå.'),
          JSON.stringify(r && r.svar).slice(0, 500));
        // Svarene som bygger på spilte kamper, sier at ingen er spilt, og
        // ingen svar oppgir et avvik på 0,0 poeng som om det var et funn.
        check(`${side}: svarene om spilte kamper sier at ingen er spilt ennå (forrige kamp${r && r.svar.luck ? ', heldig eller uheldig' : ''}), og ingen oppgir 0,0 poeng`,
          !!r && /ingen spilte kamper ennå/.test(r.svar.lastmatch)
            && (!('luck' in r.svar) || r.svar.luck === 'Ingen kamper er spilt ennå, så ingen har tatt flere eller færre poeng enn modellen forventet.')
            && Object.values(r.svar).every(t => !/0,0 poeng/.test(t)),
          JSON.stringify(r && {lastmatch: r.svar.lastmatch, luck: r.svar.luck}));
        check(`${side}: for alle lagene nevner "Hvorfor har ...?" ikke tabellplassen, "Hvor kan ... ende?" ikke "ligger på X. plass nå", og "Hva må ... gjøre?" ikke "altså X poeng til"`,
          !!r && !r.alle.hvorfor.length && !r.alle.ende.length && !r.alle.hva.length,
          JSON.stringify(r && {hvorfor: r.alle.hvorfor.slice(0, 2), ende: r.alle.ende.slice(0, 2), hva: r.alle.hva.slice(0, 2)}));
        check(`${side}: et innfylt resultat regnes som vanlig`, !!r && r.etter.scenario && r.etter.sum, JSON.stringify(r && r.etter));
        check(`${side}: ingen JS-feil uten spilte kamper`, errors.length === feil0, errors.slice(feil0).join('; '));
        errors.splice(feil0);   // feilene er rapportert her, ikke igjen under "JS-feil"
      }
    } finally { SESONGSTART = false; }
  };

  // ---- "Hva må ... gjøre?": grensen fra den glattede kurven, og tekstmodellen ----
  // Deterministisk: tellingene er laget her (innsiktData byttes ut), og
  // sonen og sjansen settes direkte, så testen ikke avhenger av dagens
  // tabell. Grensen er punktet der den glattede kurven passerer 50 %, rundet
  // av (den gamle regelen, første poengsum over 50 %, ga ett poeng mer i
  // tilfellet under). Neste setning sier laget som nesten alltid er det b-te
  // beste av de andre (minst QA_DOMINANS = 75 % av sesongene), ellers plassen.
  // Kjøres med resten av suiten, eller alene:
  //   node tests/regression.js --bare hvamaa
  const hvaMaaTekst = async () => {
    setGroup('"Hva må ... gjøre?": grensen fra den glattede kurven, og lagnavn eller plass');
    for (const [url, liga] of [[base, 'Eliteserien'], [base.replace('/eliteserien/', '/obos/'), 'OBOS']]) {
      const sp = await open(1400, 900, url);
      const r = await sp.evaluate(async () => {
        const orig = {innsiktData, qaTargetZone, qaSettled};
        const t = TEAMS[0], R = TEAMS[1], ti = TI[t], n = TEAMS.length, PM = 200;
        const soner = innsiktSoner().map(z => z.key), Z = soner.length;
        const m = compute().rows.find(x => x.name === t).pts;
        const maxPts = 3 * buildQaOpen().open.filter(o => o[0] === ti || o[1] === ti).length;
        // Tellinger for laget i én sone: kurve {poeng: [sesonger, i mål]},
        // bLag {lag: andel av sesongene}, R ender alltid på rPoeng.
        const lagA = (sone, kurve, bLag, rPoeng) => {
          const N = Object.values(kurve).reduce((s, [a]) => s + a, 0), zi = soner.indexOf(sone);
          const A = {N, PM, soner, runder: [], P0: new Array(n).fill(0), pts: new Float64Array(n * PM), succ: new Float64Array(n * Z * PM),
            kteLag: new Float64Array(n * Z * n), dec: new Float64Array(n * Z), ahead: new Float64Array(n * n), behind: new Float64Array(n * n)};
          A.P0[ti] = m;
          for (const [p, [a, b]] of Object.entries(kurve)) { A.pts[ti * PM + +p] = a; A.succ[(ti * Z + zi) * PM + +p] = b; }
          let rest = N;
          for (const [l, andel] of Object.entries(bLag)) { const c = Math.round(andel * N); A.kteLag[(ti * Z + zi) * n + TI[l]] = c; rest -= c; }
          A.kteLag[(ti * Z + zi) * n + TI[TEAMS[2]]] += rest;
          A.pts[TI[R] * PM + rPoeng] = N;
          return A;
        };
        const svar = async (sone, pct, A) => {
          const z = {...qaZoneByKey(t, sone), pct};
          qaTargetZone = () => z; qaSettled = () => null; innsiktData = () => Promise.resolve(A);
          try { return await qaHowTo(t); } finally { innsiktData = orig.innsiktData; qaTargetZone = orig.qaTargetZone; qaSettled = orig.qaSettled; }
        };
        const T = m + 17, ut = {t, R, m, T, maxPts};
        // Den gamle regelen ga T + 1 her: 49,9 % ved T, 70 % ved T + 1.
        const kurve = {[T - 1]: [10000, 4000], [T]: [10000, 4990], [T + 1]: [10000, 7000], [T + 2]: [10000, 7500], [T + 3]: [10000, 8200], [T + 4]: [10000, 9000]};
        ut.gull = await svar('gull', 0.79, lagA('gull', kurve, {[R]: 0.9}, T));
        ut.gull75 = await svar('gull', 0.79, lagA('gull', kurve, {[R]: 0.75}, T));
        ut.gull7499 = await svar('gull', 0.79, lagA('gull', kurve, {[R]: 0.7499}, T));
        ut.lang = await svar('gull', 0.2, lagA('gull', kurve, {[R]: 0.9}, T));
        ut.langPlass = await svar('gull', 0.2, lagA('gull', kurve, {[R]: 0.5}, T));
        // Sjansen ved grensen er 38 %: tallet sies, ikke "omtrent halvparten".
        const k38 = {[T - 1]: [10000, 2000], [T]: [10000, 3800], [T + 1]: [10000, 6500], [T + 3]: [10000, 9000]};
        ut.ikkeHalv = await svar('gull', 0.79, lagA('gull', k38, {[R]: 0.9}, T));
        ut.ikkeHalvLang = await svar('gull', 0.2, lagA('gull', k38, {[R]: 0.9}, T));
        // Rå tall som faller (48 % ved T, 35 % ved T + 1): glattet til samme sjanse.
        const kGlatt = qaGlattKurve({totalAtPts: Object.assign(new Array(PM).fill(0), {[T]: 1000, [T + 1]: 1000}),
          successAtPts: Object.assign(new Array(PM).fill(0), {[T]: 480, [T + 1]: 350})});
        ut.glatt = kGlatt.map(([p, s]) => [p - T, +s.toFixed(4)]);
        // Nesten sikkert (97 %): marginen er der kurven passerer 95 %, rundet
        // av (94,9 % ved m + 4, 99 % ved m + 5: m + 4; den gamle regelen: m + 5).
        ut.sikker = await svar('gull', 0.97, lagA('gull', {[m + 3]: [10000, 8000], [m + 4]: [10000, 9490], [m + 5]: [10000, 9900]}, {[R]: 0.9}, T));
        // Kryssingen rundes ned til poengene laget alt har (45 % der): da er
        // grensen neste poengsum. Holder de alt (60 %): "har allerede".
        ut.kant = await svar('gull', 0.5, lagA('gull', {[m]: [10000, 4500], [m + 1]: [10000, 9000], [m + 4]: [10000, 9900]}, {[R]: 0.9}, T));
        ut.allerede = await svar('gull', 0.5, lagA('gull', {[m]: [10000, 6000], [m + 1]: [10000, 9000]}, {[R]: 0.9}, T));
        // Plassen for hver sone, uten et lag som dominerer (også 'direkte', 14. plass).
        ut.plass = innsiktSoner().map(z => { const A = lagA(z.key, kurve, {[R]: 0.5}, T);
          return [z.key, z.dir === 'front' ? z.hi : z.boundary, qaHvorfor(A, innsiktFor(A, t, z.key), z).plass]; });
        ut.reach = QA_REACH_PHRASE.gull; ut.verb = QA_VERB.gull;
        // Kvalikavsnittet i nedrykksstriden: tabellens sjanser for laget settes
        // direkte (trygg 1.-13., kvalik 14., direkte nedrykk 15.-16.), og
        // tellingene har grensen for 13. plass ved T13 og for 14. plass ved T14
        // (20 % poengsummen før, 60 % ved grensen: kurven passerer 50 % ved
        // grensen minus 0,25). Ingen dominerer, så første avsnitt sier plassen.
        const kvalik = async (trygg, kval, direkte, T13, T14) => {
          const N = 72000, A = {N, PM, soner, runder: [], P0: new Array(n).fill(0), pts: new Float64Array(n * PM), succ: new Float64Array(n * Z * PM),
            kteLag: new Float64Array(n * Z * n), dec: new Float64Array(n * Z), ahead: new Float64Array(n * n), behind: new Float64Array(n * n)};
          A.P0[ti] = m;
          const andel = (p, G) => p < G - 1 ? 0.1 : p === G - 1 ? 0.2 : p === G ? 0.6 : 0.9;
          for (let p = m + 1; p <= m + 18; p++) {
            A.pts[ti * PM + p] = 4000;
            for (const [sone, G] of [['nedrykk', T13], ['kvalik', T13], ['direkte', T14]]) A.succ[(ti * Z + soner.indexOf(sone)) * PM + p] = 4000 * andel(p, G);
          }
          for (const sone of soner) { A.kteLag[(ti * Z + soner.indexOf(sone)) * n + TI[TEAMS[1]]] = N / 2; A.kteLag[(ti * Z + soner.indexOf(sone)) * n + TI[TEAMS[2]]] = N / 2; }
          const fordeling = new Array(n).fill(0); fordeling[0] = trygg; fordeling[13] = kval; fordeling[14] = direkte;
          const z = {...qaZoneByKey(t, 'nedrykk'), pct: direkte}, lmc = lastMC;
          qaTargetZone = () => z; qaSettled = () => null; innsiktData = () => Promise.resolve(A); lastMC = {...lmc, [t]: fordeling};
          try { return await qaHowTo(t); } finally { lastMC = lmc; innsiktData = orig.innsiktData; qaTargetZone = orig.qaTargetZone; qaSettled = orig.qaSettled; }
        };
        ut.kv = {
          vanlig: await kvalik(0.63, 0.18, 0.19, m + 7, m + 5),     // to poeng lavere: grensen for 14. plass med
          ettPoeng: await kvalik(0.63, 0.18, 0.19, m + 7, m + 6),   // ett poeng lavere: bare sjansene
          under15: await kvalik(0.70, 0.151, 0.149, m + 7, m + 5),  // direkte nedrykk under 15 %: ikke noe avsnitt
          akkurat15: await kvalik(0.70, 0.15, 0.15, m + 7, m + 5),  // akkurat 15 %: avsnittet
          lang: await kvalik(0.16, 0.13, 0.71, m + 14, m + 11),     // lang sjanse: første avsnitt har alt sjansen for å bli trygg
        };
        ut.reachNed = QA_REACH_PHRASE.nedrykk; ut.verbNed = QA_VERB.nedrykk;
        return ut;
      });
      await sp.close();
      const {t, R, T, m, maxPts} = r, ord = {1: 'førsteplass', 2: 'andreplass', 4: 'fjerdeplass', 6: 'sjetteplass', 13: '13. plass', 14: '14. plass'};
      const pt = x => `${x >= 0 && x < 10 ? ['null', 'ett', 'to', 'tre', 'fire', 'fem', 'seks', 'sju', 'åtte', 'ni'][x] : x} poeng`;
      const forste = `${t} trenger trolig rundt ${pt(T)} for å ${r.reach}, altså ${pt(T - m)} til.`;
      check(`${liga}: grensen er der den glattede kurven passerer 50 %, rundet av (${T}, ikke ${T + 1} som den gamle regelen), og laget som dominerer nevnes`,
        r.gull === `${forste} Det holder i omtrent halvparten av simuleringene, fordi ${R} vanligvis ender rundt ${T} poeng. Med ${T + 3} poeng er sjansen rundt 82 %.`, r.gull);
      check(`${liga}: laget nevnes fra 75 % av sesongene, under det sies plassen uten eget tall`,
        r.gull75 === r.gull && r.gull7499 === `${forste} Det er omtrent det som vanligvis kreves for ${ord[r.plass[0][1]]}. Med ${T + 3} poeng er sjansen rundt 82 %.`,
        JSON.stringify([r.gull75, r.gull7499]));
      check(`${liga}: lang sjanse: sjansen først, så grensen og hvorfor`,
        r.lang === `Det skal mye til: ${t} ${r.verb} i rundt 20 % av simuleringene. Rundt ${T} poeng gir dem omtrent halvparten, fordi ${R} vanligvis ender rundt ${T} poeng.`
          && r.langPlass === `Det skal mye til: ${t} ${r.verb} i rundt 20 % av simuleringene. Rundt ${T} poeng gir dem omtrent halvparten. Det er omtrent det som vanligvis kreves for ${ord[r.plass[0][1]]}.`,
        JSON.stringify([r.lang, r.langPlass]));
      check(`${liga}: er sjansen ved grensen utenfor 40 til 60 %, sies tallet (38 %)`,
        r.ikkeHalv === `${forste} Det holder i rundt 38 % av simuleringene, fordi ${R} vanligvis ender rundt ${T} poeng. Med ${T + 3} poeng er sjansen rundt 90 %.`
          && r.ikkeHalvLang.endsWith(`Rundt ${T} poeng gir dem en sjanse på rundt 38 %, fordi ${R} vanligvis ender rundt ${T} poeng.`),
        JSON.stringify([r.ikkeHalv, r.ikkeHalvLang]));
      check(`${liga}: kurven glattes (48 % og 35 % blir 41,5 % begge)`, JSON.stringify(r.glatt) === JSON.stringify([[0, 0.415], [1, 0.415]]), JSON.stringify(r.glatt));
      check(`${liga}: "nesten sikkert"-marginen er der den samme kurven passerer 95 %, rundet av`,
        r.sikker === `${t} ${r.verb} i nesten alle simuleringene. Det skal mye til for at det glipper, men rundt 4 av ${maxPts} mulige poeng holder med god margin.`, r.sikker);
      check(`${liga}: rundes grensen ned til poengene laget alt har uten at de holder, er den neste poengsum; holder de, "har allerede"`,
        r.kant.startsWith(`${t} trenger trolig rundt ${pt(m + 1)} for å ${r.reach}, altså ett poeng til.`)
          && r.allerede === `${t} har allerede ${pt(m)}, og med det klarer laget å ${r.reach} i mer enn halvparten av simuleringene.`,
        JSON.stringify([r.kant, r.allerede]));
      check(`${liga}: plassen er sonegrensen for hver sone (${r.plass.map(x => `${x[0]} ${x[2]}`).join(', ')})`,
        r.plass.every(([, b, p]) => p === ord[b]), JSON.stringify(r.plass));
      // Kvalikavsnittet
      const kv = r.kv, forsteNed = `${t} trenger trolig rundt ${pt(m + 7)} for å ${r.reachNed}, altså ${pt(7)} til. Det er omtrent det som vanligvis kreves for 13. plass.`;
      check(`${liga}: kvalikavsnittet med minst 15 % direkte nedrykk: sjansen for minst kvalikplass, for å bli helt trygg, og grensen for 14. plass når den er to poeng lavere`,
        kv.vanlig.startsWith(forsteNed) && kv.vanlig.endsWith(`\n\n${t} når minst kvalikplass i rundt 81 % av simuleringene, men blir helt trygg i 63 %. `
          + `For minst kvalikplass holder trolig rundt ${pt(m + 5)}, to poeng færre enn for å bli helt trygg.`), kv.vanlig);
      check(`${liga}: grensen for 14. plass bare ett poeng lavere: den tas ikke med`,
        kv.ettPoeng.endsWith(`\n\n${t} når minst kvalikplass i rundt 81 % av simuleringene, men blir helt trygg i 63 %.`), kv.ettPoeng);
      check(`${liga}: under 15 % direkte nedrykk ikke noe kvalikavsnitt, fra 15 % avsnittet`,
        !kv.under15.includes('kvalikplass') && kv.akkurat15.includes(`\n\n${t} når minst kvalikplass i rundt 85 % av simuleringene, men blir helt trygg i 70 %.`),
        JSON.stringify([kv.under15, kv.akkurat15]));
      check(`${liga}: står sjansen for å bli helt trygg alt i første avsnitt (lang sjanse), gjentas den ikke; forskjellen i poeng er den faktiske (tre)`,
        kv.lang.startsWith(`Det skal mye til: ${t} ${r.verbNed} i rundt 16 % av simuleringene.`)
          && kv.lang.endsWith(`\n\n${t} når minst kvalikplass i rundt 29 % av simuleringene. For minst kvalikplass holder trolig rundt ${pt(m + 11)}, tre poeng færre enn for å bli helt trygg.`)
          && (kv.lang.match(/16 %/g) || []).length === 1, kv.lang);
    }
  };
  // Tabellen på telefon. Under 760 px står kortnavnene fra LEAGUE.shortNames
  // i tabellen (Strømmen og Sandefjord står fullt ut), og Gull (Opprykk i
  // OBOS) vises ved siden av Styrke. Under 340 px viker Gull. Ingen bredde
  // skal gi sidelengs scroll, og lagnavn, merke og pil står på én linje. Med
  // merke og plasspil (▼15) på hver rad (verste scenario) gjelder det samme på
  // 390 og 430 px; på 360 px godtas noen få piksler (målt 29.9.2026: 1-2 px,
  // før 14-16). Alle tre sidene. Kjøres med
  // resten av suiten, eller alene:
  //   node tests/regression.js --bare telefon
  const telefonTabell = async () => {
    setGroup('Tabellen på telefon: kortnavn, Gull og Styrke');
    for (const [sti, korte, fulle] of [
      ['/eliteserien/', ['S08', 'Glimt', 'FFK', 'KBK'], ['Sandefjord']],
      ['/obos/', ['KIL', 'Godset', 'FKH'], ['Strømmen']],
      ['/elo-test/', ['S08', 'Glimt', 'FFK', 'KBK'], ['Sandefjord']],
    ]) {
      const liga = sti.slice(1, -1);
      const pg = await open(800, 900, base.replace('/eliteserien/', sti));
      // Verste scenario: hvert merke i LEAGUE.badges på alle radene etter tur
      // (tegnet av applyBadgesToDom, som på siden), med plasspil på hver rad.
      // Det dårligste tallet for hvert mål teller.
      const verst = () => pg.evaluate(() => {
        const ekte = badgeFor, res = [];
        try {
          for (const cfg of LEAGUE.badges) {
            badgeFor = () => cfg;
            applyBadgesToDom();
            res.push(maalTabell(true));
          }
        } finally { badgeFor = ekte; applyBadgesToDom(); }
        return {overflow: Math.max(...res.map(r => r.overflow)), sideways: Math.max(...res.map(r => r.sideways)),
          inside: res.every(r => r.inside), tolinjer: [...new Set(res.flatMap(r => r.tolinjer))],
          merke: Math.max(...res.map(r => r.merke)), merker: LEAGUE.badges.length};
      });
      const maal = () => pg.evaluate(() => maalTabell(false));
      await pg.evaluate(() => { window.maalTabell = medPil => {
        const vis = el => !!el && getComputedStyle(el).display !== 'none';
        document.querySelectorAll('#tbl td.team .diff').forEach(e => e.remove());
        if (medPil) document.querySelectorAll('#tbl td.team').forEach(td =>
          td.insertAdjacentHTML('beforeend', '<span class="diff down">▼15</span>'));
        const wrap = document.querySelector('.tblwrap'), wr = wrap.getBoundingClientRect();
        const cells = [...document.querySelectorAll('#tbl tbody td')].filter(vis);
        // Én linje: alle bitene i lagcellen overlapper i høyden.
        const tolinjer = [...document.querySelectorAll('#tbl td.team')].filter(td => {
          const r = [...td.children].filter(vis).flatMap(e => [...e.getClientRects()]);
          return Math.max(...r.map(x => x.top)) >= Math.min(...r.map(x => x.bottom));
        }).map(td => td.querySelector('.teamname').innerText.trim());
        const gull = document.getElementById('gullHeader');
        const merker = [...document.querySelectorAll('#tbl tbody .badge')].filter(b => b.className !== 'badge');
        const r = {
          overflow: wrap.scrollWidth - wrap.clientWidth,
          sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          inside: cells.every(c => c.getBoundingClientRect().right <= wr.right + 0.5),
          tolinjer,
          names: [...document.querySelectorAll('#tbl .teamname')].map(e => e.innerText.trim()),
          gull: vis(gull) ? gull.innerText.trim() : null,
          gullCeller: [...document.querySelectorAll('#tbl tbody td.gull')].filter(vis).length,
          styrke: vis(document.getElementById('formHeader')),
          merke: merker.length ? Math.max(...merker.map(b => Math.round(b.getBoundingClientRect().width * 10) / 10)) : null,
        };
        document.querySelectorAll('#tbl td.team .diff').forEach(e => e.remove());
        return r;
      }; });
      for (const w of [800, 760, 430, 390, 360, 339, 320]) {
        await pg.setViewport({width: w, height: 900});
        await sleep(400);
        const n = await maal();
        const kort = w <= 760;
        check(`${liga} ${w} px: ingen sidelengs scroll, alle kolonnene innenfor`,
          n.overflow === 0 && n.sideways === 0 && n.inside,
          `tabell ${n.overflow}, side ${n.sideways}, innenfor ${n.inside}`);
        check(`${liga} ${w} px: ${kort ? `kortnavn (${korte.join(', ')}), ${fulle.join(', ')} fullt ut` : 'fulle lagnavn'}, aldri "SIF"`,
          (kort ? korte.every(k => n.names.includes(k)) : !korte.some(k => n.names.includes(k)))
            && fulle.every(k => n.names.includes(k)) && !n.names.includes('SIF') && n.tolinjer.length === 0,
          `${n.names.join(', ')}${n.tolinjer.length ? ` | på to linjer: ${n.tolinjer.join(', ')}` : ''}`);
        check(`${liga} ${w} px: Styrke vises, ${w < 340 ? 'Gull viker' : 'Gull vises'}`,
          n.styrke && (w < 340 ? n.gull === null && n.gullCeller === 0 : !!n.gull && n.gullCeller === 16),
          `Styrke ${n.styrke}, Gull-overskrift ${JSON.stringify(n.gull)}, ${n.gullCeller} Gull-celler`);
        if (w <= 430 && w >= 360) {
          const p = await verst(), tol = w === 360 ? 3 : 0;
          check(`${liga} ${w} px: merke og plasspil på hver rad gir ${tol ? `høyst ${tol} px` : 'ingen'} sidelengs scroll`,
            p.merker > 0 && p.overflow <= tol && p.sideways === 0 && (tol > 0 || p.inside) && p.tolinjer.length === 0,
            `${p.merker} merker prøvd, tabell ${p.overflow}, side ${p.sideways}, innenfor ${p.inside}, på to linjer: ${p.tolinjer.join(', ') || 'ingen'}`);
          // Kompakt merke: pillen var 20 px bred før 29.9.2026, nå 15.
          if (w === 390) check(`${liga} 390 px: merket er kompakt (under 17 px bredt)`, p.merke > 0 && p.merke < 17, `bredeste ${p.merke} px`);
        }
      }
      await pg.close();
    }
  };
  // "Forrige kamp" i lagboksen og svaret på "Hva betydde forrige kamp?" (29.9.2026).
  // Boksen sier bare resultatet og hva det gjorde med lagets sjanse: "Forrige
  // kamp: 2-1 mot Bodø/Glimt. Seieren økte Branns sjanse for topp 4 med 6
  // prosentpoeng." Under 2 prosentpoeng: "Resultatet endret lite på ...". Er
  // lagets siste kamp simulert eller fylt inn: "Simulert forrige kamp: ...",
  // og "Det simulerte tapet ..." i svaret. Svaret starter med samme kamp, sone
  // og endring, med tallet nå og før kampen.
  // Sonen er en av dem kortet over viser, tallet nå er kortets, og "økte" /
  // "senket" følger fortegnet, ikke resultatet: uavgjort skal kunne gå begge
  // veier. Meldt samme dag: med runde 23 simulert og Vålerenga 4-0 borte mot
  // KFUM viste boksen og svaret fortsatt Fredrikstad-kampen og 6 %, mens
  // tabellen viste 1 %. Alle tre sidene. Kjøres med resten av suiten, eller
  // alene:
  //   node tests/regression.js --bare forrige
  const forrigeKampScenario = async () => {
    setGroup('Forrige kamp: boksen, svaret og kortet');
    const tall = x => x === '<1' ? 0 : x === '>99' ? 100 : +x;
    // "Forrige kamp" er alltid en spilt kamp; en simulert eller innfylt kamp
    // heter "Simulert forrige kamp", og svaret starter med "Det simulerte
    // tapet", "Den simulerte seieren" eller "Simulert uavgjort".
    const SIM = {'Den simulerte seieren': 'Seieren', 'Simulert uavgjort': 'Uavgjort', 'Det simulerte tapet': 'Tapet'};
    const boksRe = /^(?<pre>Simulert forrige kamp|Forrige kamp): (?<res>\d+-\d+) mot (?<opp>[^.]+)\.(?: (?<ord>Seieren|Uavgjort|Tapet) (?<verb>økte|senket) (?<sone>.+) med (?<n>\d+) prosentpoeng\.| Resultatet endret lite på (?<liteSone>.+)\.)?$/;
    const PC = '(?:<1|>99|\\d+)';
    const svarRe = new RegExp(`^(?<ord>Seieren|Uavgjort|Tapet|${Object.keys(SIM).join('|')}) (?<res>\\d+-\\d+) mot (?<opp>.+?) (?:(?<verb>økte|senket) (?<sone>.+) med (?<n>\\d+) prosentpoeng, til (?<naa>${PC}) %\\. Før kampen var den (?<foer>${PC}) %\\.|endret lite på (?<liteSone>.+)\\. Den er (?<liteNaa>${PC}) %(?:, det samme som før kampen|, og før kampen var den (?<liteFoer>${PC}) %)\\.)$`);
    // Leser boksen, første avsnitt i svaret, kortets tall for sonen og
    // spørsmålsknappen.
    const les = (pg, lag) => pg.evaluate(async t => {
      const el = document.querySelector('#odds .lastmatch'), z = qaTargetZone(t);
      const knapp = z && document.querySelector(`#odds .odds-jump[data-zone="${z.key}"] strong`);
      const svar = await qaLastMatch(t);
      return {boks: el ? el.textContent.trim() : '', svar: svar.split('\n\n')[0], helt: svar,
        kort: knapp ? knapp.textContent.trim() : null, flat: !!document.querySelector('#odds .odds-row.flat'),
        frase: z && typeof lagSone === 'function' ? lagSone(t, z.key) : null,
        lag: t, spm: (b => b ? b.textContent.trim() : null)(document.querySelector('#qaButtons button[data-id="lastmatch"]'))};
    }, lag);
    // Feilene for ett lag (tom liste = alt stemmer), og hva boksen sa.
    const vurder = (r, simulert) => {
      const bm = r.boks.match(boksRe), sm = r.svar.match(svarRe), f = [];
      if (!bm) return {f: [`boksen: "${r.boks}"`]};
      if (!sm) return {f: [`svaret: "${r.svar}"`]};
      const b = bm.groups, s = sm.groups;
      if (/scenari/i.test(r.boks + r.helt)) f.push('"scenario" i boksen eller svaret');
      if ((b.pre === 'Simulert forrige kamp') !== simulert) f.push(`boksen skulle ${simulert ? '' : 'ikke '}sagt "Simulert forrige kamp"`);
      if ((s.ord in SIM) !== simulert) f.push(`svaret skulle ${simulert ? '' : 'ikke '}sagt "simulert"`);
      if (r.spm !== `Hva betydde ${simulert ? 'simulert forrige kamp' : 'forrige kamp'} for ${r.lag}?`) f.push(`spørsmålet: "${r.spm}"`);
      if (b.res !== s.res || b.opp !== s.opp) f.push(`ulik kamp: ${b.res} mot ${b.opp} / ${s.res} mot ${s.opp}`);
      const naa = s.verb ? s.naa : s.liteNaa, foer = s.verb ? s.foer : (s.liteFoer || s.liteNaa);
      const n = tall(naa) - tall(foer);
      if (!r.flat && r.kort !== `${naa} %`) f.push(`kortet viser ${r.kort}, svaret ${naa} %`);
      if (b.verb) {
        const N = +b.n * (b.verb === 'økte' ? 1 : -1);
        if (!s.verb) f.push('boksen har en endring, svaret "endret lite"');
        else if (b.ord !== (SIM[s.ord] || s.ord) || b.verb !== s.verb || b.sone !== s.sone || b.n !== s.n) f.push(`ulik endring: ${b.ord} ${b.verb} ${b.sone} ${b.n} / ${s.ord} ${s.verb} ${s.sone} ${s.n}`);
        if (N !== n) f.push(`${b.verb} ${b.n}, men ${naa} % nå og ${foer} % før`);
        if (Math.abs(N) < 2) f.push(`endring ${N} under 2, skulle vært "endret lite"`);
        if (b.sone !== r.frase) f.push(`sonen "${b.sone}", kortet og svaret bruker "${r.frase}"`);
        if (!r.flat && (tall(naa) - N < 0 || tall(naa) - N > 100)) f.push(`motsier kortet: ${b.verb} ${b.n} og ${r.kort}`);
      } else if (b.liteSone) {
        if (s.verb) f.push('boksen "endret lite", svaret har en endring');
        if (Math.abs(n) >= 2) f.push(`"endret lite", men ${naa} % nå og ${foer} % før`);
        if (b.liteSone !== r.frase || s.liteSone !== r.frase) f.push(`sonen "${b.liteSone}"/"${s.liteSone}", kortet "${r.frase}"`);
      } else f.push('boksen har bare resultatet, svaret har tall');
      return {f, ord: b.ord, verb: b.verb, n};
    };
    const velg = async (pg, lag) => {
      await pg.select('#teamSelect', lag);
      await settle(pg);
      await pg.waitForFunction(() => { const el = document.querySelector('#odds .lastmatch');
        return !!el && /prosentpoeng\.$|endret lite på .+\.$/.test(el.textContent.trim()); }, {timeout: 30000}).catch(() => {});
    };
    // Alle lagene, som valgt lag i boksen.
    const alleLag = async (pg, iScen) => {
      const lagene = await pg.evaluate(() => TEAMS.slice()), feil = [], uavgjort = {økte: [], senket: []};
      for (const t of lagene) {
        await velg(pg, t);
        const v = vurder(await les(pg, t), iScen);
        if (v.f.length) feil.push(`${t}: ${v.f.join('; ')}`);
        if (v.ord === 'Uavgjort') uavgjort[v.verb].push(`${t} ${v.n > 0 ? '+' : ''}${v.n}`);
      }
      return {feil, uavgjort, n: lagene.length};
    };
    for (const [sti, lag, alle] of [['/eliteserien/', 'Vålerenga', true], ['/obos/', 'Moss', true], ['/elo-test/', 'Vålerenga', false]]) {
      const liga = sti.slice(1, -1);
      const pg = await open(1400, 900, base.replace('/eliteserien/', sti));
      // 1) Uten scenario: lagets siste spilte kamp.
      await velg(pg, lag);
      const k = await pg.evaluate(t => {
        const f = lastPlayedFor(t);
        const m = matches.filter(x => x.hg == null && (x.home === t || x.away === t)).sort((a, b) => a.date.localeCompare(b.date))[0];
        return {forrige: f.home === t ? f.away : f.home, opp: m.home === t ? m.away : m.home, runde: m.round};
      }, lag);
      const u = await les(pg, lag), vu = vurder(u, false);
      check(`${liga}: uten scenario handler boksen og svaret om ${k.forrige}, med samme sone og endring som kortet`,
        vu.f.length === 0 && u.boks.includes(`mot ${k.forrige}.`), `${u.boks} | ${u.svar} | kortet ${u.kort} | ${vu.f.join('; ')}`);
      // 2) Runden simulert, laget vinner 4-0.
      await pg.evaluate(t => {
        const m = matches.filter(x => x.hg == null && (x.home === t || x.away === t)).sort((a, b) => a.date.localeCompare(b.date))[0];
        const hjemme = m.home === t;
        matches.filter(x => x.round === m.round && x.hg == null).forEach(x =>
          x === m ? setMatch(x, hjemme ? 4 : 0, hjemme ? 0 : 4, true, true) : setMatch(x, 1, 1, true, true));
        render();
      }, lag);
      await velg(pg, lag);
      const m = await les(pg, lag), vm = vurder(m, true);
      check(`${liga}: med runde ${k.runde} simulert: "Simulert forrige kamp: 4-0 mot ${k.opp}", "Den simulerte seieren 4-0 ..." i svaret, samme sone og endring`,
        vm.f.length === 0 && m.boks.startsWith(`Simulert forrige kamp: 4-0 mot ${k.opp}.`) && m.svar.startsWith(`Den simulerte seieren 4-0 mot ${k.opp} `) && !m.svar.includes(k.forrige),
        `${m.boks} | ${m.svar} | kortet ${m.kort} | ${vm.f.join('; ')}`);
      await pg.click('#odds .lastmatch');
      await pg.waitForFunction(`(()=>{const a=document.getElementById('qaAnswer');return a&&!a.classList.contains('loading')&&a.textContent.length>20})()`, {timeout: 60000});
      const klikk = await pg.evaluate(() => document.getElementById('qaAnswer').textContent);
      check(`${liga}: trykk på boksen viser svaret om samme kamp`, klikk.startsWith(m.svar), klikk.slice(0, 120));
      // 3) Et scenario uten lagets egne kamper: forrige kamp er fortsatt den
      // spilte, men tallene er scenarioets.
      await pg.evaluate(() => { matches.forEach(x => setMatch(x, null, null)); render(); });
      await settle(pg);
      await pg.evaluate(t => { const x = matches.find(y => y.hg == null && y.home !== t && y.away !== t); setMatch(x, 3, 0); render(); }, lag);
      await velg(pg, lag);
      const a = await les(pg, lag), va = vurder(a, false);
      check(`${liga}: scenario uten lagets kamper: "Forrige kamp: ... mot ${k.forrige}", regnet for scenarioet`,
        va.f.length === 0 && a.boks.includes(`mot ${k.forrige}.`), `${a.boks} | ${a.svar} | kortet ${a.kort} | ${va.f.join('; ')}`);
      await pg.evaluate(() => { matches.forEach(x => setMatch(x, null, null)); render(); });
      await velg(pg, lag);
      // 4) Den lagrede forventningen brukes både i boksen og i svaret, også
      // når siden ville regnet et annet tall (odds endret siden filen ble
      // regnet). Og en lagret rad med en annen sone enn kortet brukes ikke:
      // da regnes linja på siden, som svaret.
      const lagret = await pg.evaluate(async t => {
        const e = LASTMATCH.teams[t], gml = JSON.stringify(e), z = qaTargetZone(t);
        const d = await qaLastMatchData(t);
        const ny = Math.min(1, Math.max(0, (d.expected || 0) + (z.pct > 0.5 ? -0.07 : 0.07)));
        LASTMATCH.teams[t] = {...e, expected: +ny.toFixed(4)};
        forrigeLinje = null; fillOdds();
        return {gml, ny: Math.round(ny * 100)};
      }, lag);
      const l1 = await les(pg, lag), vl1 = vurder(l1, false);
      check(`${liga}: lagret forventning brukes både i boksen og i svaret (${lagret.ny} % før kampen)`,
        vl1.f.length === 0 && (l1.svar.toLowerCase().includes(`før kampen var den ${lagret.ny} %`) || l1.svar.includes(`Den er ${lagret.ny} %, det samme`)),
        `${l1.boks} | ${l1.svar} | ${vl1.f.join('; ')}`);
      await pg.evaluate((t, gml) => {
        const e = JSON.parse(gml), z = qaTargetZone(t);
        LASTMATCH.teams[t] = {...e, zone: Object.keys(LEAGUE.zones).find(k => k !== z.key && LEAGUE.zones[k].lagSone), expected: 0.5};
        forrigeLinje = null; fillOdds();
      }, lag, lagret.gml);
      await velg(pg, lag);
      const l2 = await les(pg, lag), vl2 = vurder(l2, false);
      check(`${liga}: lagret rad med en annen sone enn kortet brukes ikke; boksen regnes som svaret`,
        vl2.f.length === 0, `${l2.boks} | ${l2.svar} | ${vl2.f.join('; ')}`);
      await pg.evaluate((t, gml) => { LASTMATCH.teams[t] = JSON.parse(gml); forrigeLinje = null; fillOdds(); }, lag, lagret.gml);
      // 5) Alle lagene, uten scenario og med neste runde simulert som 1-1 i
      // alle kampene: boksen og svaret like, og uavgjort både øker og senker.
      if (alle) {
        const r0 = await alleLag(pg, false);
        check(`${liga}: uten scenario stemmer boksen, svaret og kortet for alle ${r0.n} lagene`,
          r0.feil.length === 0, r0.feil.slice(0, 3).join(' | '));
        await pg.evaluate(() => { const R = Math.min(...matches.map(x => x.round));
          matches.filter(x => x.round === R).forEach(x => setMatch(x, 1, 1, true, true)); render(); });
        await settle(pg);
        const r1 = await alleLag(pg, true);
        check(`${liga}: runden simulert som 1-1: boksen, svaret og kortet stemmer for alle ${r1.n} lagene`,
          r1.feil.length === 0, r1.feil.slice(0, 3).join(' | '));
        check(`${liga}: uavgjort som øker (${r1.uavgjort.økte.join(', ') || 'ingen'}) og som senker (${r1.uavgjort.senket.join(', ') || 'ingen'}), ordet følger fortegnet`,
          r1.uavgjort.økte.length > 0 && r1.uavgjort.senket.length > 0 && r1.feil.length === 0,
          `økte ${r1.uavgjort.økte.length}, senket ${r1.uavgjort.senket.length}`);
      }
      await pg.close();
    }
  };
  // Kortet "Neste kamp" viser bare kamper uten resultat (29.9.2026). Før tok
  // det lagets første gjenstående kamp uansett resultat: med runde 23
  // simulert, eller KFUM Oslo-Vålerenga skrevet inn, sto den kampen der med
  // dato og H/U/B-prosenter, som om den var uspilt. Nå: lagets tidligste kamp
  // uten resultat (uten valgt lag: seriens), og kortet skjules når laget ikke
  // har flere. Etter et trykk på H/U/B står "Simulert: ..." øverst, og neste
  // kamp uten resultat under; et nytt trykk gjelder den. Formtipsene sier
  // "simulert" også om resultater som er fylt inn. Kjøres med resten av
  // suiten, eller alene:
  //   node tests/regression.js --bare neste
  const nesteKampKort = async () => {
    setGroup('Neste kamp: bare kamper uten resultat');
    // Kortet slik brukeren ser det, og hvilken kamp det burde vist (regnet
    // her, uten sidens egen hjelper).
    const kort = (pg, lag) => pg.evaluate(t => {
      const nm = document.getElementById('nextMatch'), m = matches.find(x => x.id === nm.dataset.id);
      const ventet = matches.filter(x => (x.hg == null || x.ag == null) && (!t || x.home === t || x.away === t))
        .sort((a, b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''))[0];
      const res = document.getElementById('nmRes');
      return {skjult: nm.hidden, kamp: m && !nm.hidden ? `${m.home}-${m.away}` : null, harResultat: !!m && m.hg != null,
        ventet: ventet ? `${ventet.home}-${ventet.away}` : null, tekst: nm.innerText.replace(/\s+/g, ' ').trim(),
        bekreftelse: res && !res.hidden ? res.textContent.replace(/\s+/g, ' ').trim() : null};
    }, lag);
    const ferdig = async pg => { await settle(pg); await new Promise(r => setTimeout(r, 400)); };
    const boksen = pg => pg.evaluate(() => { const el = document.querySelector('#odds .lastmatch'); return el ? el.textContent.trim() : ''; });
    for (const [sti, lag] of [['/eliteserien/', 'Vålerenga'], ['/obos/', 'Moss']]) {
      const liga = sti.slice(1, -1), url = base.replace('/eliteserien/', sti);
      const pg = await open(1400, 1000, url + '#team=' + encodeURIComponent(lag));
      await ferdig(pg);
      const r0 = await kort(pg, lag);
      const runde = await pg.evaluate(t => matches.filter(x => x.home === t || x.away === t).sort((a, b) => a.date.localeCompare(b.date))[0].round, lag);
      check(`${liga}: uten scenario viser kortet lagets neste kamp (${r0.ventet})`,
        !r0.skjult && r0.kamp === r0.ventet && !r0.harResultat && !r0.bekreftelse, JSON.stringify(r0));
      // 1) Runden simulert med sidens egen knapp.
      await pg.evaluate(R => document.querySelector(`.round-sim[data-round="${R}"]`).scrollIntoView({block: 'center'}), runde);
      await new Promise(r => setTimeout(r, 300));
      await pg.click(`.round-sim[data-round="${runde}"]`);
      await pg.waitForFunction(R => matches.filter(m => m.round === R).every(m => m.hg != null), {timeout: 60000}, runde);
      await ferdig(pg);
      const r1 = await kort(pg, lag), b1 = await boksen(pg);
      check(`${liga}: runde ${runde} simulert: kortet viser ${r1.ventet}, ikke den simulerte kampen`,
        !r1.skjult && r1.kamp === r1.ventet && !r1.harResultat && !r1.bekreftelse, JSON.stringify(r1));
      check(`${liga}: runde ${runde} simulert: lagboksen sier "Simulert forrige kamp"`, /^Simulert forrige kamp: \d+-\d+ mot /.test(b1), b1);
      // 2) Nullstilt, og lagets kamp skrevet inn med tastaturet: hjemmelaget
      // vinner 2-0.
      await klikk(pg, '#reset');
      await ferdig(pg);
      const id = await pg.evaluate(t => matches.filter(x => x.home === t || x.away === t).sort((a, b) => a.date.localeCompare(b.date))[0].id, lag);
      const rad = `.match[data-id="${id}"]`;
      await pg.evaluate(r => document.querySelector(r).scrollIntoView({block: 'center'}), rad);
      await new Promise(r => setTimeout(r, 300));
      await pg.click(`${rad} [data-side=h]`); await pg.keyboard.type('2');
      await pg.click(`${rad} [data-side=a]`); await pg.keyboard.type('0');
      await pg.keyboard.press('Tab');
      await pg.waitForFunction(i => { const m = matches.find(x => x.id === i); return m.hg === 2 && m.ag === 0; }, {timeout: 20000}, id);
      await ferdig(pg);
      const r2 = await kort(pg, lag);
      // Siste kamp med resultat for laget, regnet her. "Tabell på samme
      // tidspunkt" kan ha fylt inn flere av lagets kamper etter den som ble
      // skrevet inn (OBOS: Moss); da er det den seneste som er "simulert
      // forrige kamp".
      const k2 = await pg.evaluate((i, t) => {
        const m = matches.filter(x => x.hg != null && (x.home === t || x.away === t)).sort((a, b) => b.date.localeCompare(a.date))[0];
        const h = m.home === t;
        return {home: m.home, away: m.away, skrevet: m.id === i, opp: h ? m.away : m.home, res: `${h ? m.hg : m.ag}-${h ? m.ag : m.hg}`,
          ord: m.hg === m.ag ? 'Simulert uavgjort' : (m.hg > m.ag) === h ? 'Den simulerte seieren' : 'Det simulerte tapet'};
      }, id, lag);
      await pg.waitForFunction(() => { const el = document.querySelector('#odds .lastmatch'); return !!el && /prosentpoeng\.$|endret lite på .+\.$/.test(el.textContent.trim()); }, {timeout: 30000}).catch(() => {});
      const b2 = await boksen(pg);
      const svar2 = await pg.evaluate(async t => (await qaLastMatch(t)).split('\n')[0], lag);
      check(`${liga}: kamp skrevet inn: kortet viser ${r2.ventet}, ikke den innfylte kampen`,
        !r2.skjult && r2.kamp === r2.ventet && !r2.harResultat && (lag !== 'Vålerenga' || k2.skrevet), JSON.stringify({r2, k2}));
      check(`${liga}: skrevet inn: "Simulert forrige kamp: ${k2.res} mot ${k2.opp}" og "${k2.ord} ${k2.res} mot ${k2.opp}" i svaret${k2.skrevet ? ' (kampen som ble skrevet inn)' : ' (fylt inn av "Tabell på samme tidspunkt")'}`,
        b2.startsWith(`Simulert forrige kamp: ${k2.res} mot ${k2.opp}.`) && svar2.startsWith(`${k2.ord} ${k2.res} mot ${k2.opp} `) && !/scenari/i.test(b2 + svar2),
        `${b2} | ${svar2}`);
      // 3) H i kortet: kampen får resultat, "Simulert: ..." står øverst, og
      // kortet går videre. Så B, som gjelder den nye kampen.
      for (const q of ['H', 'B']) {
        const foer = await kort(pg, lag);
        await pg.evaluate(() => document.getElementById('nextMatch').scrollIntoView({block: 'center'}));
        await pg.click(`#nmHub button[data-q="${q}"]`);
        await pg.waitForFunction(k => { const m = matches.find(x => `${x.home}-${x.away}` === k && x.hg != null); return !!m; }, {timeout: 20000}, foer.kamp);
        await ferdig(pg);
        const etter = await kort(pg, lag);
        const trukket = await pg.evaluate(k => { const m = matches.find(x => `${x.home}-${x.away}` === k); return {hg: m.hg, ag: m.ag, home: m.home, away: m.away}; }, foer.kamp);
        const ok = q === 'H' ? trukket.hg > trukket.ag : trukket.hg < trukket.ag;
        check(`${liga}: ${q} i kortet for ${foer.kamp}: "Simulert: ${trukket.home} ${trukket.hg}-${trukket.ag} ${trukket.away}" øverst, og kortet viser ${etter.ventet}`,
          ok && etter.bekreftelse === `Simulert: ${trukket.home} ${trukket.hg}-${trukket.ag} ${trukket.away}` && etter.kamp === etter.ventet && etter.kamp !== foer.kamp && !etter.harResultat
            && etter.tekst.indexOf('Simulert:') < etter.tekst.indexOf(etter.kamp.split('-')[0]),
          JSON.stringify({foer: foer.kamp, etter}));
      }
      // 4) Formtipset: minst tre av lagets fem siste er fylt inn eller
      // trukket (skrevet inn, H og B i kortet, og det "Tabell på samme
      // tidspunkt" fylte), og alle heter "simulert": tallet i tipset er det
      // samme som rutene merket "(simulert)".
      const tips = await pg.evaluate(t => {
        const rad = document.querySelector(`#tbl tr[data-team="${t}"]`);
        return {tips: (rad.querySelector('.form5') || {}).title || '', ruter: [...rad.querySelectorAll('.form b')].map(b => b.title)};
      }, lag);
      const nSim = tips.ruter.filter(x => /\(simulert\)$/.test(x)).length;
      check(`${liga}: formtipset: "${['', 'én', 'to', 'tre', 'fire', 'fem'][nSim]} av dem simulert", like mange som rutene merket "(simulert)", ingen "lagt inn" eller "scenario"`,
        nSim >= 3 && tips.tips.endsWith(`, ${['', 'én', 'to', 'tre', 'fire', 'fem'][nSim]} av dem simulert`) && !/lagt inn|scenari/.test(tips.tips + tips.ruter.join()),
        `${tips.tips} | ${tips.ruter.join(', ')}`);
      // 5) Alle lagets kamper fylt: kortet skjules, og "Hva betyr neste
      // kamp?" sier at laget ikke har flere. Resultatene velges så sonen ikke
      // er avgjort (da svarer spørsmålet med det i stedet): uavgjort i alle,
      // ellers annenhver seier og tap, fra dagens tabell.
      let r5 = null, nesteSvar = null, moenster = null;
      for (const mo of ['uavgjort', 'seier og tap']) {
        await klikk(pg, '#reset');
        await ferdig(pg);
        await pg.evaluate((t, mo) => {
          matches.filter(x => x.hg == null && (x.home === t || x.away === t)).forEach((x, i) => {
            const vinn = mo === 'uavgjort' ? null : i % 2 === 0;
            if (vinn === null) setMatch(x, 1, 1);
            else if ((x.home === t) === vinn) setMatch(x, 2, 0); else setMatch(x, 0, 2);
          });
          render();
        }, lag, mo);
        await ferdig(pg);
        r5 = await kort(pg, lag);
        nesteSvar = await pg.evaluate(async t => { const z = qaTargetZone(t); return {svar: await qaNextMatch(t), avgjort: !!qaSettled(t, z)}; }, lag);
        moenster = mo;
        if (!nesteSvar.avgjort) break;
      }
      check(`${liga}: alle lagets kamper fylt (${moenster}): kortet er skjult, og "Hva betyr neste kamp?" sier "${lag} har ingen kamper uten resultat igjen."`,
        r5.skjult && !nesteSvar.avgjort && nesteSvar.svar === `${lag} har ingen kamper uten resultat igjen.`, `${JSON.stringify(r5)} | ${JSON.stringify(nesteSvar)}`);
      await pg.close();
      // 6) Uten valgt lag: seriens neste kamp uten resultat, også når den
      // første er fylt inn.
      const u = await open(1400, 1000, url + '#team=');
      await ferdig(u);
      const u0 = await kort(u, null);
      await u.evaluate(() => { const m = matches.filter(x => x.hg == null).sort((a, b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''))[0]; setMatch(m, 3, 1); render(); });
      await ferdig(u);
      const u1 = await kort(u, null);
      check(`${liga}: uten valgt lag: kortet viser seriens neste kamp uten resultat (${u0.ventet}, så ${u1.ventet})`,
        !u0.skjult && u0.kamp === u0.ventet && !u1.skjult && u1.kamp === u1.ventet && u1.kamp !== u0.kamp && !u1.harResultat,
        JSON.stringify({u0, u1}));
      // Ingen "scenariet" i sidens kilde: bøyningen er "scenarioet".
      const kilde = await u.evaluate(async () => (await fetch(location.pathname)).text());
      check(`${liga}: sidens kilde har ikke "scenariet"`, !kilde.includes('scenariet'), `${(kilde.match(/scenariet/g) || []).length} treff`);
      await u.close();
    }
  };
  // Linja under "Neste kamp" ("Nedrykksfaren for Vålerenga: 3 % med seier,
  // 10 % med uavgjort, 18 % med tap.") skal ha nøyaktig tallene i svaret på
  // "Hva betyr neste kamp?", også rett etter "Simuler runden". Før ble linja
  // regnet før tabellen var ferdig med det nye scenarioet, med det gamle
  // scenarioets tall som utgangspunkt, og ble ikke regnet om (29.9.2026,
  // Vålerenga: 0/5/13 i linja, 3/10/18 i svaret). Uten scenario skal ingenting
  // endre seg. Kjøres med resten av suiten, eller alene:
  //   node tests/regression.js --bare nestelinje
  const nesteKampLinje = async () => {
    setGroup('Neste kamp: linja og svaret fra samme ferdige tabell');
    const linjeRe = /^(.+) for (.+): (\S+ %) med seier, (\S+ %) med uavgjort, (\S+ %) med tap\.$/;
    // Venter til linja er regnet for tabellen slik den er nå (eller skjult
    // fordi sonen er avgjort), og leser linja, kortet og svaret.
    const les = async (pg, lag) => {
      await pg.waitForFunction(t => {
        const el = document.getElementById('nmImpact'), z = qaTargetZone(t);
        if (z && qaSettled(t, z)) return true;
        return !!el && !el.hidden && !el.classList.contains('venter') && el.textContent.trim().length > 10
          && !!nmImpactKey && nmImpactKey.startsWith(`${t}|`) && nmImpactKey.split('|')[3] === qaScenarioKey();
      }, {timeout: 60000}, lag).catch(() => {});
      return pg.evaluate(async t => {
        const el = document.getElementById('nmImpact'), nm = document.getElementById('nextMatch');
        const m = matches.find(x => x.id === nm.dataset.id), z = qaTargetZone(t);
        const v = matches.filter(x => x.hg == null && (x.home === t || x.away === t))
          .sort((a, b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''))[0];
        return {lag: t, linje: el.hidden ? null : el.textContent.trim(), svar: await qaNextMatch(t),
          avgjort: !!(z && qaSettled(t, z)), kort: m && !nm.hidden ? `${m.home}-${m.away}` : null,
          kortRunde: m ? m.round : null, ventet: v ? `${v.home}-${v.away}` : null};
      }, lag);
    };
    // Tallene i svaret, der det har dem ("endrer lite" og "betyr lite" har
    // ikke alle), mot tallene i linja.
    const sammenlign = r => {
      if (r.avgjort) return {f: r.linje ? [`sonen er avgjort, men linja vises: ${r.linje}`] : [], n: 0, avgjort: true};
      const l = r.linje && r.linje.match(linjeRe);
      if (!l) return {f: [`linja: "${r.linje}"`], n: 0};
      const s = r.svar, seier = s.match(/^Seier mot .+? (?:endrer .+? lite \((\S+ %)\)|(?:øker|senker) .+? til (\S+ %) \()/) || [];
      const svar = {seier: seier[1] || seier[2] || null, uavgjort: (s.match(/Uavgjort gir (\S+ %),/) || [])[1] || null,
        tap: (s.match(/mens tap (?:senker|øker) den til (\S+ %)\./) || [])[1] || null};
      const linje = {seier: l[3], uavgjort: l[4], tap: l[5]}, f = [];
      let n = 0;
      for (const k of ['seier', 'uavgjort', 'tap']) if (svar[k] !== null) { n++; if (svar[k] !== linje[k]) f.push(`${k}: linja ${linje[k]}, svaret ${svar[k]}`); }
      if (l[2] !== r.lag) f.push(`linja gjelder ${l[2]}`);
      if (!s.toLowerCase().includes(l[1].toLowerCase())) f.push(`sonen "${l[1]}" står ikke i svaret`);
      return {f, n, linje: `${linje.seier}/${linje.uavgjort}/${linje.tap}`, svar: `${svar.seier}/${svar.uavgjort}/${svar.tap}`};
    };
    // Alle lagene, som valgt lag: feil, og hvor mange som hadde alle tre tall.
    const alleLag = async pg => {
      const lagene = await pg.evaluate(() => TEAMS.slice()), feil = [];
      let tre = 0, sjekket = 0;
      for (const t of lagene) {
        await pg.select('#teamSelect', t);
        await settle(pg);
        const v = sammenlign(await les(pg, t));
        if (v.f.length) feil.push(`${t}: ${v.f.join('; ')}`);
        if (v.n === 3) tre++;
        if (v.n > 0) sjekket++;
      }
      return {feil, tre, sjekket, n: lagene.length};
    };
    for (const [sti, lag, alle] of [['/eliteserien/', 'Vålerenga', true], ['/obos/', 'Moss', true], ['/elo-test/', 'Vålerenga', false]]) {
      const liga = sti.slice(1, -1), url = base.replace('/eliteserien/', sti);
      const pg = await open(1400, 1000, url + '#team=' + encodeURIComponent(lag));
      await settle(pg);
      // 1) Uten scenario.
      const u = await les(pg, lag), vu = sammenlign(u);
      check(`${liga}: uten scenario: kortet viser ${u.ventet}, og linja har svarets tall (${vu.linje || '-'})`,
        u.kort === u.ventet && vu.f.length === 0 && vu.n >= 1, `${vu.f.join('; ')} | linja ${u.linje} | svaret ${u.svar}`);
      if (alle) {
        const a0 = await alleLag(pg);
        check(`${liga}: uten scenario: linja har svarets tall for alle lagene (${a0.sjekket} sammenlignet, ${a0.tre} med alle tre tall)`,
          a0.feil.length === 0 && a0.tre >= 3, a0.feil.slice(0, 3).join(' | '));
        await pg.select('#teamSelect', lag);
        await settle(pg);
      }
      // 2) Lagets neste runde simulert med sidens egen knapp, mens laget er
      // valgt. Vent til tabellen er ferdig, så på linja.
      const R = await pg.evaluate(t => matches.filter(x => x.hg == null && (x.home === t || x.away === t)).sort((a, b) => a.date.localeCompare(b.date))[0].round, lag);
      await klikk(pg, `.round-sim[data-round="${R}"]`);
      await pg.waitForFunction(r => matches.filter(m => m.round === r).every(m => m.hg != null), {timeout: 60000}, R);
      await settle(pg);
      const s = await les(pg, lag), vs = sammenlign(s);
      check(`${liga}: runde ${R} simulert: "Neste kamp" har flyttet til ${s.ventet}`,
        s.kort === s.ventet && s.kortRunde !== R, JSON.stringify({kort: s.kort, runde: s.kortRunde}));
      check(`${liga}: runde ${R} simulert: seier, uavgjort og tap i linja er svarets tall (linja ${vs.linje || '-'}, svaret ${vs.svar || '-'})`,
        vs.f.length === 0 && vs.n >= 1, `${vs.f.join('; ')} | linja ${s.linje} | svaret ${s.svar}`);
      if (alle) {
        const a1 = await alleLag(pg);
        check(`${liga}: runde ${R} simulert: linja har svarets tall for alle lagene (${a1.sjekket} sammenlignet, ${a1.tre} med alle tre tall)`,
          a1.feil.length === 0 && a1.tre >= 3, a1.feil.slice(0, 3).join(' | '));
      }
      await pg.close();
    }
  };
  const BARE = process.argv.includes('--bare') ? process.argv[process.argv.indexOf('--bare') + 1] : null;

  try {
    if (BARE) {
      // Bare én gruppe (se over).
      if (BARE === 'treffsikkerhet') await treffsikkerhetTekst();
      else if (BARE === 'sesongstart') await sesongstart();
      else if (BARE === 'hvamaa') await hvaMaaTekst();
      else if (BARE === 'del') await delKnapp();
      else if (BARE === 'telefon') await telefonTabell();
      else if (BARE === 'forrige') await forrigeKampScenario();
      else if (BARE === 'neste') await nesteKampKort();
      else if (BARE === 'nestelinje') await nesteKampLinje();
      else throw new Error(`--bare: ukjent gruppe ${BARE} (kjent: treffsikkerhet, sesongstart, hvamaa, del, telefon, forrige, neste, nestelinje)`);
    } else {
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
    await klikk(page, '#fxPanel #simRest');
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
    await klikk(page, '#fxPanel #reset');
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
    await klikk(page, '#fxPanel #simRest');
    await filled(page, total);
    await settle(page);
    check('sortering nullstilles ved simulering', await page.evaluate(() => tableSort === null));
    await klikk(page, '#fxPanel #reset');
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
    await klikk(page, '#fxPanel #simRest');
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
    // Smale skjermer: kortnavn, Gull og Styrke, ingen sidelengs scroll.
    await telefonTabell();

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
          const l = qaLastMatchLine(t, e);
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
      // Linja i lagboksen sier bare resultatet og hva det gjorde med lagets
      // sjanse (29.9.2026): ingen odds, marked eller hva som var ventet. Det
      // står i svaret på "Hva betydde forrige kamp?". Store bokstaver teller:
      // "Odds" er et lag i OBOS.
      const kildeOrd = f.linjer.filter(l => /ventet|markedet|modellen|\bodds\b|sluttodds|av tilfellene|sjanse for (seier|uavgjort|tap)/.test(l.html));
      check(`${liga}: linja nevner ikke odds, marked eller hva som var ventet`,
        kildeOrd.length === 0, kildeOrd.slice(0, 3).map(l => `${l.team}: ${l.html}`).join(' | '));
      // Samme form for alle lagene, også når resultatet endret lite.
      const form = f.linjer.filter(l => !/^Forrige kamp: \d+-\d+ mot [^.]+\.( (Seieren|Uavgjort|Tapet) (økte|senket) .+ med <b class="(good|bad)">\d+<\/b> prosentpoeng\.| Resultatet endret lite på .+\.)?$/.test(l.html));
      check(`${liga}: linja har samme form for alle lagene`,
        form.length === 0 && f.linjer.length === 16, form.slice(0, 3).map(l => `${l.team}: ${l.html}`).join(' | ') || `${f.linjer.length} linjer`);
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
    await forrigeKampScenario();
    await nesteKampKort();
    await nesteKampLinje();
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
      // Leses som AVSNITT, ikke linjeindekser: svaret står nå i fire avsnitt,
      // og en indeks ville brutt neste gang ordlyden deles opp.
      const avsnitt = svar.split('\n\n');
      check(`${liga}: fire avsnitt`, avsnitt.length === 4, `${avsnitt.length}`);
      check(`${liga}: første avsnitt sier kamp og strid`,
        /^Rundens viktigste kamp er .+ mot .+ \S+ \d+\. \w+\. Den påvirker .+ mest\.$/.test(avsnitt[0]),
        avsnitt[0]);
      const l = (avsnitt[1] || '').split('\n');
      check(`${liga}: andre avsnitt sier hvem kampen betyr mest for`,
        /^Kampen betyr mest for .+:$/.test(l[0]), l[0]);
      // Nøyaktig tre utfallslinjer, og bare ett lag får tall.
      const utfall = l.slice(1, 4);
      const egen = utfall.every((x, i) => new RegExp(`^${['Seier', 'Uavgjort', 'Tap'][i]}: ${PCTL}$`).test(x));
      const annet = utfall.every((x, i) => new RegExp(i === 1 ? `^Uavgjort: ${PCTL}$` : `^.+-seier: ${PCTL}$`).test(x));
      check(`${liga}: tre utfall, i rekkefølgen seier, uavgjort, tap`, egen || annet, utfall.join(' | '));
      check(`${liga}: så dagens nivå`,
        new RegExp(`^.+(sjansen|faren) er ${PCTL} før kampen\.$`).test(l[4]), l[4]);
      // De øvrige avsnittene: retning uten tall.
      const rest = avsnitt.slice(2).join(' ');
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
      const medForventning = svar.filter(([, tx]) => /Før kampen var den|det samme som før kampen/.test(tx));
      check(`${liga}: svarene har en forventning å måle mot`,
        medForventning.length >= TEAMS_MIN, `${medForventning.length} av ${svar.length}`);
      const avsnitt = medForventning.filter(([, tx]) => tx.split('\n\n').length === 3);
      check(`${liga}: svaret står i tre avsnitt`,
        avsnitt.length === medForventning.length,
        `${avsnitt.length} av ${medForventning.length}`);
      // Første avsnitt: endringen og tallet før kampen, som linja i
      // lagboksen. Oddsen (kildeordet følger kilden, se «Forrige kamp:
      // kildeordet følger kilden») står i avsnittet etter.
      const pc = '(<1|>99|\\d+) %';
      const forste = new RegExp(`^(Seieren|Uavgjort|Tapet) \\d+-\\d+ mot [^\\n]+?( (økte|senket) [^\\n]+ med \\d+ prosentpoeng, til ${pc}\\. Før kampen var den ${pc}\\.| endret lite på [^\\n]+\\. Den er ${pc}(, det samme som før kampen|, og før kampen var den ${pc})\\.)\\n\\n(Sluttoddsen|Modellen) ga `);
      const ordlyd = medForventning.filter(([, tx]) => forste.test(tx));
      check(`${liga}: ny ordlyd i alle svarene`, ordlyd.length === medForventning.length,
        (medForventning.find(x => !ordlyd.includes(x)) || ['', ''])[1].slice(0, 160));
      const gamle = svar.filter(([, tx]) =>
        /ventet når alle mulige utfall|prosentpoeng (bedre|verre) enn|betydde lite|Poengdelingen|løftet|reduserte/.test(tx) ||
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
    // "Del scenario" legger scenarioet i hashen. Nullstill tømte tabellen, men
    // lot s= stå -- og en oppfriskning leste scenarioet inn igjen, så tabellen
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
        check(`${liga}/${knapp}: "Del scenario" legger scenarioet i adressen`, /s=/.test(med), med.slice(0, 40));
        await sp.evaluate(i => document.getElementById(i).click(), knapp);
        await new Promise(r => setTimeout(r, 1200));
        const etter = await sp.evaluate(() => ({hash: location.hash,
          fylte: matches.filter(m => m.hg != null).length}));
        check(`${liga}/${knapp}: nullstill tømmer tabellen`, etter.fylte === 0, `${etter.fylte}`);
        check(`${liga}/${knapp}: nullstill fjerner scenarioet fra adressen`,
          !/s=/.test(etter.hash), etter.hash || '(tom)');
        // Det avgjørende: en oppfriskning skal ikke hente scenarioet tilbake.
        await sp.reload({waitUntil: 'networkidle0', timeout: 60000});
        await settle(sp);
        await new Promise(r => setTimeout(r, 1500));
        const igjen = await sp.evaluate(() => ({fylte: matches.filter(m => m.hg != null).length,
                                                lag: SELECTED_TEAM}));
        check(`${liga}/${knapp}: oppfriskning gir ikke scenarioet tilbake`, igjen.fylte === 0,
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

    // ---- 29. "Hvilken kamp blir vanskeligst?" ----
    setGroup('Vanskeligste kamp');
    for (const [url, liga, lag] of [[base, 'Eliteserien', 'Brann'], [obosUrl, 'OBOS', 'Bryne']]) {
      const sp = await open(1400, 900, url);
      await settle(sp);
      // Uten fulgt lag skal spørsmålet ikke vises i det hele tatt.
      await sp.evaluate(() => { const s = document.getElementById('teamSelect');
        s.value = ''; s.dispatchEvent(new Event('change', {bubbles: true})); });
      await new Promise(r => setTimeout(r, 1500));
      const utenLag = await sp.evaluate(() =>
        [...document.querySelectorAll('.qa-item button')].some(b => /vanskeligst/i.test(b.textContent)));
      check(`${liga}: spørsmålet vises ikke uten fulgt lag`, !utenLag);

      await sp.evaluate(t => { const s = document.getElementById('teamSelect');
        s.value = t; s.dispatchEvent(new Event('change', {bubbles: true})); }, lag);
      await new Promise(r => setTimeout(r, 2000));
      const r = await sp.evaluate(async t => {
        const q = QA_QUESTIONS.find(x => x.id === 'hardest');
        // Fasit regnet av de SAMME vinnersjansene svaret skal bruke.
        const egne = matches.filter(m => isEmpty(m) && (m.home === t || m.away === t))
          .map(m => { const [lh, la] = rateFor(m.home, m.away), o = outcome(lh, la);
                      const hjemme = m.home === t;
                      return {opp: hjemme ? m.away : m.home, p: hjemme ? o.H : o.B}; })
          .sort((a, b) => a.p - b.p);
        return {svar: String(await q.run(t, () => {})), label: q.label(t),
                verst: egne[0], best: egne[egne.length - 1], n: egne.length};
      }, lag);
      check(`${liga}: spørsmålet heter det det skal`,
        r.label === `Hvilken kamp blir vanskeligst for ${lag}?`, r.label);
      check(`${liga}: svaret har begge ytterpunktene`,
        /^Vanskeligst blir (hjemme|borte) mot .+ \d+\. \w+, der modellen gir .+ sjanse for seier\. Lettest blir (hjemme|borte) mot .+ \d+\. \w+, med .+\.$/.test(r.svar),
        r.svar);
      check(`${liga}: vanskeligste kamp er den med lavest vinnersjanse`,
        r.svar.includes(`mot ${r.verst.opp} `) &&
        r.svar.indexOf(r.verst.opp) < r.svar.indexOf('Lettest'),
        `ventet ${r.verst.opp} (${Math.round(r.verst.p * 100)} %)`);
      check(`${liga}: letteste kamp er den med høyest vinnersjanse`,
        r.svar.indexOf(r.best.opp) > r.svar.indexOf('Lettest'),
        `ventet ${r.best.opp} (${Math.round(r.best.p * 100)} %)`);
      // En kamp man har fylt inn selv står ikke igjen, og skal ut av listen.
      const etter = await sp.evaluate(async t => {
        const m = matches.filter(x => isEmpty(x) && (x.home === t || x.away === t))[0];
        const opp = m.home === t ? m.away : m.home;
        setMatch(m, 1, 1); render();
        await new Promise(r => setTimeout(r, 600));
        const q = QA_QUESTIONS.find(x => x.id === 'hardest');
        return {opp, svar: String(await q.run(t, () => {}))};
      }, lag);
      check(`${liga}: en utfylt kamp regnes ikke som gjenstående`,
        !etter.svar.includes(`mot ${etter.opp} `), `${etter.opp}: ${etter.svar.slice(0, 80)}`);
      await sp.close();
    }
    await page.bringToFront();

    // ---- 30. Ofte spurt (FAQ) ----
    setGroup('Ofte spurt');
    for (const [url, liga, ventet] of [
        [base, 'Eliteserien', ['Hvem vinner Eliteserien 2026?', 'Hvem rykker ned fra Eliteserien 2026?']],
        [obosUrl, 'OBOS', ['Hvem rykker opp fra OBOS-ligaen 2026?', 'Hvem rykker ned fra OBOS-ligaen 2026?']]]) {
      const sp = await open(1400, 900, url);
      await settle(sp);
      await new Promise(r => setTimeout(r, 1200));
      const r = await sp.evaluate(() => {
        const sp3 = [...document.querySelectorAll('#faqList h3')].map(h => h.textContent);
        const sv = [...document.querySelectorAll('#faqList p')].map(p => p.textContent);
        let schema = null;
        try { schema = JSON.parse(document.getElementById('faqSchema').textContent); } catch (e) {}
        // Fasit for tallene: samme summering som resten av siden.
        const topp = k => TEAMS.map(t => ({t, v: sonesjanse(lastMC[t], k)}))
          .filter(x => x.v != null && x.v >= 0.005).sort((a, b) => b.v - a.v)[0];
        return {
          synlig: document.getElementById('faq').checkVisibility({visibilityProperty: true}),
          sp3, sv, schema,
          gull: topp('gull'), ned: topp('nedrykk'),
          antallLd: document.querySelectorAll('script[type="application/ld+json"]').length,
        };
      });
      check(`${liga}: FAQ-seksjonen vises`, r.synlig && r.sp3.length >= 3, `${r.sp3.length} spørsmål`);
      for (const q of ventet)
        check(`${liga}: har spørsmålet "${q}"`, r.sp3.includes(q), r.sp3.join(' | '));
      check(`${liga}: svarene er korte`, r.sv.every(x => x.length > 0 && x.length < 260),
        r.sv.map(x => x.length).join(', '));
      // Schemaet må speile det brukeren ser -- ellers er det et brudd på
      // Googles krav, og et tall kan bli stående feil i søkeresultatet.
      check(`${liga}: FAQPage-schema finnes ved siden av det gamle`,
        r.schema && r.schema['@type'] === 'FAQPage' && r.antallLd === 2, `${r.antallLd} blokker`);
      const fraSchema = (r.schema ? r.schema.mainEntity : []).map(x => ({q: x.name, a: x.acceptedAnswer.text}));
      const fraSiden = r.sp3.map((q, i) => ({q, a: r.sv[i]}));
      check(`${liga}: schemaet er identisk med den synlige teksten`,
        JSON.stringify(fraSchema) === JSON.stringify(fraSiden),
        JSON.stringify(fraSchema.slice(0, 1)));
      // Tallene skal komme fra modellen, ikke være skrevet inn.
      const alle = r.sv.join(' ');
      check(`${liga}: laget med størst sjanse i sonen står i svaret`,
        alle.includes(r.gull.t) && alle.includes(r.ned.t),
        `ventet ${r.gull.t} og ${r.ned.t}`);
      await sp.close();
    }
    await page.bringToFront();

    // ---- Merker ved poenglikhet ----
    // Et merke ("Seriemester", "Sikret topp 4", "Rykket ned" ...) skal ALDRI
    // være feil. Tabellen sorteres på poeng, målforskjell og scorede mål, så:
    //  - ferdigspilt, likt på poeng, ulik målforskjell: bare laget som faktisk
    //    står over grensen får merket for den grensen
    //  - kamper igjen: et lag som kan nå samme poengsum kan gå forbi på
    //    målforskjell, så merket skal vente
    //  - helt likt på poeng, målforskjell og scorede mål ved en grense: ingen
    //    av dem får merket, fordi innbyrdes oppgjør ikke er regnet inn
    // Hver grense i LEAGUE.badges testes, pluss nedrykksgrensen (14./15.), i
    // begge ligaene. Scenarioet bygges fra dagens tabell: alt 1-1, så justeres
    // lagene på plass K og K+1 med kamper mot lag langt fra grensen.
    setGroup('Merker ved poenglikhet');
    for (const [url, liga] of [[base, 'Eliteserien'], [base.replace('/eliteserien/', '/obos/'), 'OBOS']]) {
      const mp = await open(1400, 900, url);
      const grenser = await mp.evaluate(() =>
        [...LEAGUE.badges.map(b => ({K: b.above, tekst: b.text})),
         {K: TEAMS.length - 2, tekst: LEAGUE.relegatedBadge.text, ned: true}]);
      const bygg = (K, delta, apen) => mp.evaluate(({K, delta, apen}) => {
        document.getElementById('autoFillToggle').checked = false;
        matches.forEach(m => setMatch(m, null, null, false));
        const r0 = compute().rows, n = r0.length;
        const a = r0[K - 1].name, b = r0[K].name;
        const lag = {}; r0.forEach((r, i) => lag[r.name] = i < K - 1 ? 0 : (r.name === a || r.name === b ? 1 : 2));
        const tom = matches.filter(m => m.hg == null);
        // Fast seed, så en feil kan gjenskapes.
        let frø = 12345;
        const tilf = () => { frø = (frø * 1103515245 + 12345) % 2147483648; return frø / 2147483648; };
        const sett = (m, t, u) => { const h = m.home === t;   // u: 'S', 'U' eller 'T' sett fra t
          if (u === 'U') setMatch(m, 1, 1, false);
          else if (u === 'S') setMatch(m, h ? 1 : 0, h ? 0 : 1, false);
          else setMatch(m, h ? 0 : 1, h ? 1 : 0, false); };
        const utfall = (m, t) => { const [x, y] = m.home === t ? [m.hg, m.ag] : [m.ag, m.hg]; return x > y ? 'S' : x < y ? 'T' : 'U'; };
        const rad = t => compute().rows.find(r => r.name === t);
        const mot = t => tom.filter(m => (m.home === t || m.away === t) && ![a, b].includes(m.home === t ? m.away : m.home));
        for (let forsøk = 0; forsøk < 300; forsøk++) {
          // Lagene over grensen slår alle under, lagene under taper for alle
          // over; innen samme gruppe trekkes utfallet. a mot b blir 1-1.
          tom.forEach(m => {
            const th = lag[m.home], tb = lag[m.away];
            if (th !== tb) sett(m, th < tb ? m.home : m.away, 'S');
            else { const x = tilf(); sett(m, m.home, x < 0.4 ? 'S' : x < 0.7 ? 'U' : 'T'); }
          });
          // Juster a og b til like mange poeng med kampene deres mot andre.
          for (let i = 0; i < 30 && rad(a).pts !== rad(b).pts; i++) {
            const d = rad(a).pts - rad(b).pts, hi = d > 0 ? a : b, lo = d > 0 ? b : a, D = Math.abs(d);
            const opp = mot(lo).map(m => [m, lo, utfall(m, lo)]).filter(([, , u]) => u !== 'S')
              .map(([m, t, u]) => [m, t, u === 'T' && D >= 3 ? 'S' : 'U', u === 'T' && D >= 3 ? 3 : u === 'T' ? 1 : 2]).filter(x => x[3] <= D);
            const ned = mot(hi).map(m => [m, hi, utfall(m, hi)]).filter(([, , u]) => u !== 'T')
              .map(([m, t, u]) => [m, t, u === 'S' && D >= 2 ? 'U' : 'T', u === 'S' && D >= 2 ? 2 : u === 'S' ? 3 : 1]).filter(x => x[3] <= D);
            const valg = [...opp, ...ned];
            if (!valg.length) break;
            const [m, t, u] = valg[Math.floor(tilf() * valg.length)];
            sett(m, t, u);
          }
          if (rad(a).pts !== rad(b).pts) continue;
          const vA = mot(a).find(m => utfall(m, a) === 'S'), vB = mot(b).find(m => utfall(m, b) === 'S');
          if (!vA || !vB) continue;
          // Målene: a skal ha `delta` bedre målforskjell, og like mange scorede
          // mål når delta er 0. Justeres i en seier for hver, så poengene står.
          const sum = (t, unntak) => { let gf = 0, ga = 0; BASE.forEach(r => { if (r[0] === t) { gf += r[5]; ga += r[6]; } });
            matches.forEach(m => { if (m === unntak || m.hg == null) return;
              if (m.home === t) { gf += m.hg; ga += m.ag; } else if (m.away === t) { gf += m.ag; ga += m.hg; } });
            return {gf, ga}; };
          const ra = sum(a, vA), rb = sum(b, vB);
          const x = rb.gf - ra.gf + delta, y = rb.ga - ra.ga;
          const B2 = Math.max(0, -y), A2 = B2 + y;
          const B1 = Math.max(B2 + 1, A2 + 1 - x, 1), A1 = B1 + x;
          setMatch(vA, vA.home === a ? A1 : A2, vA.home === a ? A2 : A1, false);
          setMatch(vB, vB.home === b ? B1 : B2, vB.home === b ? B2 : B1, false);
          if (apen) setMatch(vB, null, null, false);
          const rows = compute().rows, P = rad(a).pts;
          // Bare a og b skal være med i avgjørelsen: strengt poenggap til
          // nabolagene på begge sider, ellers prøv på nytt.
          const over = rows.filter(r => r.name !== a && r.name !== b && lag[r.name] === 0);
          const under = rows.filter(r => r.name !== a && r.name !== b && lag[r.name] === 2);
          if (!over.every(r => r.pts > P) || !under.every(r => (apen ? r.max : r.pts) < P)) continue;
          render();
          const rA = rad(a), rB = rad(b), rr = compute().rows;
          return {a, b, forsøk, posA: rr.indexOf(rr.find(r => r.name === a)) + 1, posB: rr.indexOf(rr.find(r => r.name === b)) + 1,
                  A: `${rA.pts}p ${rA.gd >= 0 ? '+' : ''}${rA.gd} (${rA.gf}-${rA.ga})`,
                  B: `${rB.pts}p ${rB.gd >= 0 ? '+' : ''}${rB.gd} (${rB.gf}-${rB.ga})${apen ? ', 1 kamp igjen' : ''}`,
                  likt: rA.pts === rB.pts + (apen ? 3 : 0), tomme: matches.filter(m => m.hg == null).length};
        }
        return {feil: `fant ikke et scenario med ${a} og ${b} alene ved grensen etter 300 forsøk`};
      }, {K, delta, apen});
      // Merkene regnes i en Worker og patches inn etterpå. Vent til både
      // simuleringen (hideIfChance leser den) og et merkesvar er på plass.
      const merker = async (s, forvent) => {
        await settle(mp);
        await mp.waitForFunction(forvent, {timeout: 6000}, s).catch(() => {});
        return mp.evaluate(s => Object.fromEntries([s.a, s.b].map(t =>
          [t, (document.querySelector(`#tbl tbody tr[data-team="${CSS.escape(t)}"] .badge .bt`) || {}).textContent || ''])), s);
      };
      const merkeAv = (s, t) => `(document.querySelector('#tbl tbody tr[data-team="${t.replace(/"/g, '\\"')}"] .badge .bt')||{}).textContent||''`;
      for (const g of grenser) {
        const hvor = g.ned ? `${g.K}./${g.K + 1}. plass (${g.tekst})` : `grensen ${g.K}./${g.K + 1}. (${g.tekst})`;
        // 1) ferdigspilt, likt på poeng, a har 4 bedre målforskjell
        let s = await bygg(g.K, 4, false);
        let ok = !s.feil && s.posA === g.K && s.posB === g.K + 1 && s.likt && s.tomme === 0;
        check(`${liga} ${hvor}: scenarioet ble bygget (ferdigspilt, likt på poeng)`, ok, JSON.stringify(s));
        if (ok) {
          const lav = g.ned ? s.b : s.a, hoy = g.ned ? s.a : s.b;
          const m = await merker(s, `${merkeAv(s, lav)}===${JSON.stringify(g.tekst)} && ${merkeAv(s, hoy)}!==${JSON.stringify(g.tekst)}`);
          check(`${liga} ${hvor}: ferdigspilt, bare ${g.ned ? s.b : s.a} får «${g.tekst}»`,
            m[lav] === g.tekst && m[hoy] !== g.tekst,
            `${s.a} ${s.A}: «${m[s.a]}», ${s.b} ${s.B}: «${m[s.b]}»`);
        }
        // 2) helt likt på poeng, målforskjell og scorede mål -- ingen får merket.
        // Bygges fra 1), så bare målene endres: merkene må regnes på nytt
        // også når poengene står stille.
        s = await bygg(g.K, 0, false);
        ok = !s.feil && s.likt && s.tomme === 0 && s.A === s.B && [s.posA, s.posB].sort((x, y) => x - y).join() === `${g.K},${g.K + 1}`;
        check(`${liga} ${hvor}: scenarioet ble bygget (helt likt)`, ok, JSON.stringify(s));
        if (ok) {
          const m = await merker(s, `${merkeAv(s, s.a)}!==${JSON.stringify(g.tekst)} && ${merkeAv(s, s.b)}!==${JSON.stringify(g.tekst)}`);
          check(`${liga} ${hvor}: helt likt, ingen av dem får «${g.tekst}»`,
            m[s.a] !== g.tekst && m[s.b] !== g.tekst,
            `${s.a} ${s.A}: «${m[s.a]}», ${s.b} ${s.B}: «${m[s.b]}»`);
        }
        // 3) kamper igjen: b har én kamp igjen og kan nå a på poeng og gå
        // forbi på målforskjell. a skal ikke ha merket ennå.
        if (!g.ned) {
          s = await bygg(g.K, 4, true);
          ok = !s.feil && s.likt && s.tomme === 1 && s.posA === g.K;
          check(`${liga} ${hvor}: scenarioet ble bygget (én kamp igjen)`, ok, JSON.stringify(s));
          if (ok) {
            const m = await merker(s, `${merkeAv(s, s.a)}!==${JSON.stringify(g.tekst)}`);
            check(`${liga} ${hvor}: ${s.b} kan ta igjen ${s.a}, så ${s.a} har ikke «${g.tekst}» ennå`,
              m[s.a] !== g.tekst, `${s.a} ${s.A}: «${m[s.a]}», ${s.b} ${s.B}: «${m[s.b]}»`);
          }
        }
      }
      // Den øvre grensen i solveDirection. Når søket når tidsgrensen, gir
      // "above" metBase + bound(0), og computeOneBadge godtar det som bevis.
      // Det holder bare hvis grensen ALDRI er lavere enn det eksakte antallet.
      // Tidsgrensen sjekkes bare hver 512. node, så deadline = 0 alene gir
      // ofte et ferdig søk og ikke grensen. Testen bruker derfor en kopi av
      // Worker-koden der sjekken skjer ved første node -- nøyaktig én
      // tekstbytting, ellers feiler testen. Produksjonskoden er urørt.
      // Tabellene er tilfeldige med fast seed: alt fylles ut bortsett fra de
      // siste 2 eller 3 rundene, så det lange søket blir eksakt.
      await mp.evaluate(() => { matches.forEach(m => setMatch(m, null, null)); render(); });
      const grenseOk = await mp.evaluate(() => {
        const lag = src => { const W = {}; (new Function('W', 'var postMessage=function(){}; var self={};' + src + '; W.solve=solveDirection;'))(W); return W.solve; };
        const fra = '(visited & 511)===0 && Date.now()>deadline', til = 'Date.now()>deadline';
        const treff = WORKER_SRC.split(fra).length - 1;
        window.__grense = {treff, bare: lag(WORKER_SRC.replace(fra, til)), eksakt: lag(WORKER_SRC)};
        return treff;
      });
      check(`${liga}: grensetesten kan tvinge søket til å bruke bare grensen`, grenseOk === 1, `${grenseOk} treff på tidsgrensesjekken`);
      const stat = {tabeller: 0, tilfeller: 0, lik: 0, hoyere: 0, storst: 0, utenSok: 0, ikkeEksakt: 0, lavere: [], igjen: []};
      for (let bunke = 0; bunke < 10 && grenseOk === 1; bunke++) {
        const s = await mp.evaluate(bunke => {
          let frø = 777 + bunke;
          const tilf = () => { frø = (frø * 1103515245 + 12345) % 2147483648; return frø / 2147483648; };
          const tomme = matches.filter(m => m.hg == null || m.sim);
          const runder = [...new Set(tomme.map(m => m.round))].sort((a, b) => a - b);
          const ut = {tabeller: 0, tilfeller: 0, lik: 0, hoyere: 0, storst: 0, utenSok: 0, ikkeEksakt: 0, lavere: [], igjen: []};
          for (let n = 0; n < 20; n++) {
            const R = 2 + (n % 2), apne = new Set(runder.slice(-R));
            tomme.forEach(m => {
              if (apne.has(m.round)) { m.hg = null; m.ag = null; return; }
              const x = tilf(), g = () => Math.floor(tilf() * 4);
              let h = g(), a = g();
              if (x < 0.45) { if (h <= a) h = a + 1; } else if (x < 0.72) a = h; else if (a <= h) a = h + 1;
              m.hg = h; m.ag = a;
            });
            const {rows} = compute(), byname = {};
            rows.forEach(r => byname[r.name] = {name: r.name, pts: r.pts, gd: r.gd, gf: r.gf, left: r.left, max: r.max});
            const rem = matches.filter(m => m.hg == null).map(m => [m.home, m.away]);
            ut.igjen.push(rem.length);
            ut.tabeller++;
            rows.forEach(r => {
              const b = window.__grense.bare(byname, rem, r.name, r.pts, 'above', 0);
              const e = window.__grense.eksakt(byname, rem, r.name, r.pts, 'above', Date.now() + 10000);
              if (!e.exact) { ut.ikkeEksakt++; return; }
              if (b.exact) { ut.utenSok++; return; }   // svart før søket: ingen grense brukt
              ut.tilfeller++;
              const d = b.count - e.count;
              if (d < 0) ut.lavere.push(`${r.name}: grense ${b.count}, eksakt ${e.count}, ${rem.length} kamper igjen`);
              else if (d === 0) ut.lik++; else ut.hoyere++;
              ut.storst = Math.max(ut.storst, d);
            });
          }
          tomme.forEach(m => { m.hg = null; m.ag = null; });
          return ut;
        }, bunke);
        for (const k of ['tabeller', 'tilfeller', 'lik', 'hoyere', 'utenSok', 'ikkeEksakt']) stat[k] += s[k];
        stat.storst = Math.max(stat.storst, s.storst); stat.lavere.push(...s.lavere); stat.igjen.push(...s.igjen);
      }
      await mp.evaluate(() => { matches.forEach(m => setMatch(m, null, null)); render(); });
      const igjenMin = Math.min(...stat.igjen), igjenMaks = Math.max(...stat.igjen);
      console.log(`      ${liga}: ${stat.tabeller} tabeller med ${igjenMin} til ${igjenMaks} kamper igjen, ${stat.tilfeller} tilfeller der bare grensen ble brukt: ` +
        `${stat.lik} lik, ${stat.hoyere} høyere, største forskjell ${stat.storst}. ` +
        `${stat.utenSok} svart uten søk (teller ikke), ${stat.ikkeEksakt} der det lange søket ikke ble eksakt.`);
      check(`${liga}: ${stat.tabeller} tilfeldige tabeller, grensen er aldri lavere enn det eksakte antallet`,
        stat.tabeller >= 200 && igjenMin > 0 && stat.tilfeller > 0 && stat.lavere.length === 0 && stat.ikkeEksakt === 0,
        `${stat.lavere.length} lavere: ${stat.lavere.slice(0, 5).join('; ')}; ${stat.tilfeller} tilfeller, ${stat.ikkeEksakt} ikke eksakte`);

      // Tidlig stopp i merkesøket. Merket avgjøres av tersklene i
      // LEAGUE.badges, så søket stopper når det beste funnet og den øvre
      // grensen ligger mellom de samme to tersklene. Merket skal være LIKT det
      // søket uten tidlig stopp gir (dagens kode før rettelsen): testen bygger
      // den varianten ved å fjerne tersklene fra de to kallene i
      // computeOneBadge -- nøyaktig én tekstbytting hver, ellers feiler den.
      // Sammenlignes på dagens tabell og grensetestens 200 tilfeldige tabeller
      // (samme frø), med produksjonens tidsgrense (500 ms per lag).
      const stopp = await mp.evaluate(() => {
        const fra1 = "cfg.badges.map(function(b){ return b.above; })", fra2 = "'atmost', deadline, [2])";
        const treff = [WORKER_SRC.split(fra1).length - 1, WORKER_SRC.split(fra2).length - 1];
        const lag = src => { const W = {}; (new Function('W', 'var postMessage=function(){}; var self={};' + src + '; W.f=computeOneBadge;'))(W); return W.f; };
        const ny = lag(WORKER_SRC), uten = lag(WORKER_SRC.replace(fra1, 'undefined').replace(fra2, "'atmost', deadline)"));
        const cfg = {badges: LEAGUE.badges, relegatedBadge: LEAGUE.relegatedBadge};
        const ut = {treff, tabeller: 0, lag: 0, ulike: [], tregeNy: [], tidNy: 0, tidUten: 0, dagensUten: []};
        const sammenlign = dagens => {
          const {rows} = compute(), byname = {};
          rows.forEach(r => byname[r.name] = {name: r.name, pts: r.pts, gd: r.gd, gf: r.gf, left: r.left, max: r.max});
          const rem = matches.filter(isEmpty).map(m => [m.home, m.away]);
          ut.tabeller++;
          rows.forEach(r => {
            let t0 = performance.now(); const u = uten(byname, rem, r.name, 500, cfg); const dU = performance.now() - t0;
            t0 = performance.now(); const n = ny(byname, rem, r.name, 500, cfg); const dN = performance.now() - t0;
            ut.lag++; ut.tidNy += dN; ut.tidUten += dU;
            if (JSON.stringify(u) !== JSON.stringify(n)) ut.ulike.push(`${dagens ? 'dagens' : 'tilfeldig'}: ${r.name} uten ${JSON.stringify(u)}, med ${JSON.stringify(n)}`);
            if (dagens && dU > 100) ut.dagensUten.push(`${r.name} ${dU.toFixed(0)} ms`);
          });
        };
        // Tiden måles på sidens egen kode, uavhengig av tekstbyttingen over.
        {
          const {rows} = compute(), byname = {};
          rows.forEach(r => byname[r.name] = {name: r.name, pts: r.pts, gd: r.gd, gf: r.gf, left: r.left, max: r.max});
          const rem = matches.filter(isEmpty).map(m => [m.home, m.away]);
          rows.forEach(r => { const t0 = performance.now(); ny(byname, rem, r.name, 500, cfg);
            const d = performance.now() - t0; if (d > 100) ut.tregeNy.push(`${r.name} ${d.toFixed(0)} ms`); });
        }
        if (treff[0] !== 1 || treff[1] !== 1) return ut;
        sammenlign(true);
        for (let bunke = 0; bunke < 10; bunke++) {
          let frø = 777 + bunke;
          const tilf = () => { frø = (frø * 1103515245 + 12345) % 2147483648; return frø / 2147483648; };
          const tomme = matches.filter(m => m.hg == null || m.sim);
          const runder = [...new Set(tomme.map(m => m.round))].sort((a, b) => a - b);
          for (let n = 0; n < 20; n++) {
            const R = 2 + (n % 2), apne = new Set(runder.slice(-R));
            tomme.forEach(m => {
              if (apne.has(m.round)) { m.hg = null; m.ag = null; return; }
              const x = tilf(), g = () => Math.floor(tilf() * 4);
              let h = g(), a = g();
              if (x < 0.45) { if (h <= a) h = a + 1; } else if (x < 0.72) a = h; else if (a <= h) a = h + 1;
              m.hg = h; m.ag = a;
            });
            sammenlign(false);
          }
          tomme.forEach(m => { m.hg = null; m.ag = null; });
        }
        return ut;
      });
      await mp.evaluate(() => { matches.forEach(m => setMatch(m, null, null)); render(); });
      console.log(`      ${liga}: ${stopp.lag} merker i ${stopp.tabeller} tabeller, søketid uten tidlig stopp ${(stopp.tidUten / 1000).toFixed(2)} s, med ${(stopp.tidNy / 1000).toFixed(2)} s` +
        (stopp.dagensUten.length ? `; dagens tabell uten tidlig stopp: ${stopp.dagensUten.join(', ')}` : ''));
      check(`${liga}: testen finner tersklene i computeOneBadge (én gang hver)`, stopp.treff.join() === '1,1', `treff ${stopp.treff}`);
      check(`${liga}: tidlig stopp gir samme merke som søket uten, i dagens tabell og ${stopp.tabeller - 1} tilfeldige`,
        stopp.treff.join() === '1,1' && stopp.tabeller === 201 && stopp.ulike.length === 0,
        `${stopp.ulike.length} ulike av ${stopp.lag}: ${stopp.ulike.slice(0, 5).join('; ')}`);
      check(`${liga}: dagens tabell, ingen lag bruker over 100 ms på merket`, stopp.tregeNy.length === 0,
        stopp.tregeNy.join(', '));

      // Merkene i egen Worker: simuleringen skal aldri stå i kø bak dem.
      const egen = await mp.evaluate(async () => {
        if (typeof getBadgeWorker !== 'function') return {finnes: false};
        const tell = {merke: 0, sim: 0};
        const bw = getBadgeWorker(), mw = getWorker();
        const lM = e => { if (e.data.mode === 'badges') tell.merke++; }, lS = e => { if (e.data.mode === 'badges') tell.sim++; };
        bw.addEventListener('message', lM); mw.addEventListener('message', lS);
        const f = lastBadges; lastBadgeSignature = null; computeBadgesAsync(compute().rows);
        const t0 = Date.now(); while (tell.merke + tell.sim === 0 && Date.now() - t0 < 5000) await new Promise(r => setTimeout(r, 10));
        bw.removeEventListener('message', lM); mw.removeEventListener('message', lS);
        return {finnes: true, ulike: bw !== mw, tell, oppdatert: lastBadges !== f};
      });
      check(`${liga}: merkene regnes i en egen Worker, ikke i simuleringens`,
        egen.finnes && egen.ulike && egen.tell.merke === 1 && egen.tell.sim === 0 && egen.oppdatert, JSON.stringify(egen));
      await mp.close();
    }
    await page.bringToFront();

    // ---- Tabellsimuleringen i egen Worker ----
    // Tabellens prosenter (runMCAsync) skal aldri stå i kø bak noe annet. Før
    // gikk kortet "Neste kamp" (matchImpact, 2500 × 4 sesonger) i samme Worker
    // og ble sendt FØR tabellsimuleringen etter et innfylt resultat. Testen
    // følger hjemmelaget i første åpne kamp, slår av «Fyll ut runden» (ellers
    // fylles lagets kamp grått og kortet regner ikke), og skriver et resultat
    // i en annen kamp, som en bruker. Kortet gjøres ti ganger tyngre (N × 10)
    // så rekkefølgen ikke avhenger av maskinen: på en rask maskin er kortet
    // ellers ferdig før tabellsimuleringen sendes (render() + 250 ms).
    // Kortets oppgaver går nå i poolen (én per utfall); kravet er at ingen av
    // dem går i tabellens Worker.
    // Kontrollert på de tre sidene: Eliteserien, OBOS og testsiden.
    setGroup('Tabellsimuleringen i egen Worker');
    for (const [sti, liga] of [['/eliteserien/', 'Eliteserien'], ['/obos/', 'OBOS'], ['/elo-test/', 'ELO-test']]) {
      const url = base.replace('/eliteserien/', sti);
      const probe = await open(1400, 900, url);
      const lag = await probe.evaluate(() => matches.find(m => m.hg == null).home);
      await probe.close();
      const wp = await browser.newPage();
      wp.on('pageerror', e => errors.push(`${url}: ${e.message}`));
      await wp.evaluateOnNewDocument(() => {
        window.__ws = {poster: [], svar: []};
        const W = window.Worker;
        window.Worker = function (u, o) {
          const w = new W(u, o), id = window.__ws.poster.length + ':' + Math.random().toString(36).slice(2, 6);
          const post = w.postMessage.bind(w);
          w.postMessage = m => { window.__ws.poster.push({id, mode: m.mode || 'tabell', t: performance.now()}); return post(m); };
          w.addEventListener('message', e => window.__ws.svar.push({id, mode: e.data.mode, done: e.data.done, t: performance.now()}));
          return w;
        };
      });
      await wp.setViewport({width: 1400, height: 900});
      await wp.goto(`${url}#team=${encodeURIComponent(lag)}`, {waitUntil: 'networkidle0'});
      await wp.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 120000});
      await wp.evaluate(() => { const t = document.getElementById('autoFillToggle'); if (t.checked) t.click(); });
      await settle(wp);
      await sleep(1500);
      const r = await wp.evaluate(async lag => {
        // Kortet gjøres tyngre, og tiden det er ferdig måles når kortets kall
        // er ferdig (oppgavene går i poolen eller, før, i én Worker).
        const orig = window.runMatchImpactAsync; let kortFerdig = null;
        window.runMatchImpactAsync = (t, z, c, k, b, g) => orig(t, z, c, k, {...b, N: (b.N || 400) * 10}, g)
          .then(r => { if (kortFerdig === null) kortFerdig = performance.now(); return r; });
        const row = [...document.querySelectorAll('.match')].find(r => { const m = matches.find(x => x.id === r.dataset.id);
          return m && m.hg == null && m.home !== lag && m.away !== lag && !r.querySelector('[data-side=h]').value; });
        const nP = __ws.poster.length, nS = __ws.svar.length;
        const h = row.querySelector('[data-side=h]'), a = row.querySelector('[data-side=a]');
        h.value = '2'; h.dispatchEvent(new Event('input', {bubbles: true}));
        a.value = '1'; a.dispatchEvent(new Event('input', {bubbles: true}));
        const t0 = Date.now();
        while (Date.now() - t0 < 60000 && !(__ws.svar.slice(nS).some(x => x.mode === 'prob' && x.done >= 10000)
                                             && kortFerdig !== null)) await new Promise(r => setTimeout(r, 20));
        window.runMatchImpactAsync = orig;
        const poster = __ws.poster.slice(nP), svar = __ws.svar.slice(nS);
        const tabellW = new Set(poster.filter(x => x.mode === 'tabell').map(x => x.id));
        const kortW = new Set(poster.filter(x => x.mode === 'matchImpact' || x.mode === 'zoneTask').map(x => x.id));
        const forste = svar.find(x => x.mode === 'prob'), kort = kortFerdig === null ? null : {t: kortFerdig};
        const kortPost = poster.find(x => x.mode === 'matchImpact' || x.mode === 'zoneTask'), tabPost = poster.find(x => x.mode === 'tabell');
        return {tabellW: [...tabellW], kortW: [...kortW], felles: [...tabellW].filter(x => kortW.has(x)),
                kortForTabell: !!(kortPost && tabPost && kortPost.t < tabPost.t),
                forste: forste ? Math.round(forste.t - poster[0].t) : null, kort: kort ? Math.round(kort.t - poster[0].t) : null};
      }, lag);
      console.log(`      ${liga} (følger ${lag}): kortet sendt før tabellen: ${r.kortForTabell}; første prosenter ${r.forste} ms, «Neste kamp» ferdig ${r.kort} ms (kortet × 10)`);
      check(`${liga}: tabellsimuleringen og «Neste kamp» går i ulike Workere`,
        r.tabellW.length === 1 && r.kortW.length >= 1 && r.felles.length === 0, JSON.stringify(r));
      check(`${liga}: tabellens første prosenter kommer før «Neste kamp» er ferdig`,
        r.forste != null && r.kort != null && r.forste < r.kort, `første ${r.forste} ms, kortet ${r.kort} ms`);
      await wp.close();
    }
    await page.bringToFront();

    // ---- Tabellprosentene: minne i fitRates og "send straks" ----
    // fitRates (~25 ms per kamp med odds) husker svaret for samme inndata, de
    // 500 sist brukte. Tabellsimuleringen sendes med en gang når en kamp er
    // ferdig utfylt eller H/U/B er trykket, men aldri mens en annen pågår: da
    // sendes bare den siste, når den pågående er ferdig.
    //  1. Samme handlinger med fast frø i Math.random gir bit-like RATES,
    //     prosenter i kamplisten, lastMC og merker med og uten minnet. Varianten
    //     uten minnet bygges ved tekstbytting i HTML-en (nøyaktig ett treff).
    //  2. Minnet overstiger aldri 500 etter mange ulike scenarioer.
    //  3. Straks: ferdig utfylt kamp og H/U/B sender simuleringen inne i
    //     render(), uten ventetiden; bare ett felt venter 250 ms som før.
    //  4. Raske klikk: fem H/U/B med 100 ms mellomrom. Ingen simulering sendes
    //     mens en annen pågår, og det siste scenarioet sendes uten ventetiden.
    setGroup('Tabellprosentene: minne og straks');
    const RP_INSTR = () => {
      let frø = 20260928; Math.random = () => { frø = (frø * 1103515245 + 12345) % 2147483648; return frø / 2147483648; };
      const R = window.__rp = {post: [], fin: [], render: [], mcKall: [], merke: -1, sendt: 0, ferdig: 0, regn: 0};
      const W = window.Worker;
      window.Worker = function (u, o) {
        const w = new W(u, o), post = w.postMessage.bind(w);
        w.postMessage = m => { if (m && !m.mode) { R.post.push({t: performance.now(), iGang: R.sendt - R.ferdig}); R.sendt++; } return post(m); };
        w.addEventListener('message', e => { const d = e.data;
          if (d.mode === 'prob' && d.done >= d.total) { R.ferdig++; R.fin.push(performance.now()); }
          if (d.mode === 'badges') R.merke = d.runId; });
        return w;
      };
      document.addEventListener('DOMContentLoaded', () => {
        const r = window.render;
        window.render = function () { const t = performance.now(); try { return r.apply(this, arguments); } finally { R.render.push([t, performance.now()]); } };
        const mc = window.runMCAsync;
        window.runMCAsync = function () { R.mcKall.push(performance.now()); return mc.apply(this, arguments); };
        if (typeof window.fitRatesRegn === 'function') { const f = window.fitRatesRegn; window.fitRatesRegn = function () { R.regn++; return f.apply(this, arguments); }; }
      });
    };
    const rpApne = async (url, bytt) => {
      const p = await browser.newPage();
      p.on('pageerror', e => errors.push(`${url}: ${e.message}`));
      await p.evaluateOnNewDocument(RP_INSTR);
      let treff = null;
      if (bytt) {
        const html = await (await fetch(url)).text();
        treff = html.split(bytt[0]).length - 1;
        const ny = html.replace(bytt[0], bytt[1]);
        await p.setRequestInterception(true);
        p.on('request', q => q.url().split('#')[0] === url ? q.respond({status: 200, contentType: 'text/html; charset=utf-8', body: ny}) : q.continue());
      }
      await p.setViewport({width: 1400, height: 900});
      await p.goto(`${url}#team=${encodeURIComponent(rpLag)}`, {waitUntil: 'networkidle0'});
      await p.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 120000, polling: 50});
      return {p, treff};
    };
    const rpRolig = async p => {
      await p.waitForFunction(`lastMCFinal===true && lastMCScenarioKey===qaScenarioKey() && __rp.merke===badgeRunId
        && (typeof mcVenter==='undefined' || !mcVenter)`, {timeout: 60000, polling: 50}).catch(async e => {
        const st = await p.evaluate(() => JSON.stringify({final: lastMCFinal, key: lastMCScenarioKey === qaScenarioKey(), merke: __rp.merke, badgeRunId,
          venter: typeof mcVenter === 'undefined' ? null : mcVenter, pagar: typeof mcPagar === 'undefined' ? null : mcPagar, sendt: __rp.sendt, ferdig: __rp.ferdig}));
        throw new Error(`rpRolig: ${st}`); });
      await sleep(600);
    };
    // Radene handlingene velger mellom: åpne kamper laget som følges ikke spiller.
    const RP_RADER = `[...document.querySelectorAll('.match')].filter(r => { const m = matches.find(x => x.id === r.dataset.id);
      return m && m.hg == null && m.home !== ${'${JSON.stringify(rpLag)}'} && m.away !== ${'${JSON.stringify(rpLag)}'} && !r.classList.contains('played'); })`;
    let rpLag = '';
    for (const [sti, liga] of [['/eliteserien/', 'Eliteserien'], ['/obos/', 'OBOS']]) {
      const url = base.replace('/eliteserien/', sti);
      { const q = await open(1400, 900, url); rpLag = await q.evaluate(() => matches.find(m => m.hg == null).home); await q.close(); }
      const rader = RP_RADER.replace(/\$\{JSON\.stringify\(rpLag\)\}/g, JSON.stringify(rpLag));
      const handling = (p, h) => p.evaluate(async (h, rader) => {
        const row = eval(rader)[h.nr];
        if (h.type === 'skriv') {
          const a = row.querySelector('[data-side=h]'), b = row.querySelector('[data-side=a]');
          a.value = String(h.s[0]); a.dispatchEvent(new Event('input', {bubbles: true}));
          await new Promise(r => setTimeout(r, 400));
          b.value = String(h.s[1]); b.dispatchEvent(new Event('input', {bubbles: true}));
        } else if (h.type === 'knapp') row.querySelector(`button[data-q="${h.q}"]`).click();
        else { const t = document.getElementById('autoFillToggle'); if (t.checked) t.click(); }
      }, h, rader);
      const bilde = p => p.evaluate(() => JSON.stringify({
        res: matches.map(m => [m.id, m.hg, m.ag, !!m.sim]),
        rates: Object.keys(RATES).sort().map(k => [k, RATES[k].r[0], RATES[k].r[1]]),
        pct: [...document.querySelectorAll('.match .quick')].map(q => [...q.querySelectorAll('.pct')].map(x => x.textContent + (x.classList.contains('best') ? '*' : '')).join('/')),
        mc: lastMC, merker: lastBadges}));

      // 1. Bit-like tall med og uten minnet.
      const MINNE = ['const husket = FIT_MINNE.get(k);', 'const husket = undefined;'];
      const med = await rpApne(url), uten = await rpApne(url, MINNE);
      const steg = [{type: 'skriv', nr: 0, s: [2, 1]}, {type: 'knapp', nr: 3, q: 'H'}, {type: 'av'}, {type: 'skriv', nr: 5, s: [0, 0]},
                    {type: 'knapp', nr: 7, q: 'B'}, {type: 'knapp', nr: 9, q: 'U'}, {type: 'skriv', nr: 2, s: [1, 3]}];
      const ulike = []; let tilstander = 0;
      const sml = async navn => { await rpRolig(med.p); await rpRolig(uten.p); tilstander++;
        const a = await bilde(med.p), b = await bilde(uten.p);
        if (a !== b) { const ja = JSON.parse(a), jb = JSON.parse(b); ulike.push(`${navn}: ${Object.keys(ja).filter(k => JSON.stringify(ja[k]) !== JSON.stringify(jb[k])).join(',')}`); } };
      if (uten.treff === 1) {
        await sml('lastet');
        for (const h of steg) { await handling(med.p, h); await handling(uten.p, h); await sml(JSON.stringify(h)); }
      }
      const regn = [await med.p.evaluate(() => __rp.regn), await uten.p.evaluate(() => __rp.regn)];
      console.log(`      ${liga}: ${tilstander} tilstander; fitRates regnet ${regn[0]} ganger med minnet, ${regn[1]} uten`);
      check(`${liga}: varianten uten minnet bygges (nøyaktig ett treff i tekstbyttingen)`, uten.treff === 1, `${uten.treff} treff`);
      check(`${liga}: samme handlinger og frø gir bit-like RATES, prosenter, lastMC og merker med og uten minnet`,
        uten.treff === 1 && tilstander === steg.length + 1 && ulike.length === 0 && regn[0] < regn[1], `${ulike.join('; ')}; regnet ${regn}`);
      await med.p.close(); await uten.p.close();

      // 2. Minnet overstiger aldri 500.
      { const {p} = await rpApne(url);
        const g = await p.evaluate(() => {
          if (typeof FIT_MINNE === 'undefined') return {finnes: false};
          let frø = 4242; const tilf = () => { frø = (frø * 1103515245 + 12345) % 2147483648; return frø / 2147483648; };
          const odds = matches.filter(m => ODDS_UP[m.home + '|' + m.away]);
          const apne = matches.filter(m => m.hg == null && !ODDS_UP[m.home + '|' + m.away]);
          const r0 = __rp.regn; let maks = 0, scen = 0;
          while (__rp.regn - r0 < 560 && scen < 400) {
            scen++;
            apne.forEach(m => { if (tilf() < 0.3) setMatch(m, Math.floor(tilf() * 4), Math.floor(tilf() * 4), false); else setMatch(m, null, null, false); });
            refreshLiveState(); odds.forEach(m => rateFor(m.home, m.away));
            maks = Math.max(maks, FIT_MINNE.size);
          }
          // Sist brukt skal fortsatt være i minnet (eldste kastes, ikke nyeste).
          const r1 = __rp.regn; odds.forEach(m => { delete RATES[m.home + '|' + m.away]; rateFor(m.home, m.away); });
          const sistBruktHusket = __rp.regn === r1;
          apne.forEach(m => setMatch(m, null, null, false)); render();
          return {finnes: true, regnet: __rp.regn - r0, scen, maks, naa: FIT_MINNE.size, grense: FIT_MINNE_MAKS, sistBruktHusket};
        });
        check(`${liga}: minnet overstiger aldri 500 etter mange ulike scenarioer`,
          g.finnes && g.grense === 500 && g.regnet > 500 && g.maks <= 500 && g.naa === 500 && g.sistBruktHusket, JSON.stringify(g));
        await p.close(); }

      // 3. Straks: ferdig utfylt kamp og H/U/B uten ventetid; ett felt venter som før.
      { const {p} = await rpApne(url);
        await handling(p, {type: 'av'}); await rpRolig(p);
        const st = await p.evaluate(async rader => {
          const R = __rp, vent = ms => new Promise(r => setTimeout(r, ms));
          const iRender = t => R.render.some(([a, b]) => t >= a && t <= b);
          const row = eval(rader)[0], a = row.querySelector('[data-side=h]'), b = row.querySelector('[data-side=a]');
          // Ett felt: runMCAsync kommer først etter ventetiden, ikke inne i render().
          let n = R.mcKall.length, nR = R.render.length;
          a.value = '2'; a.dispatchEvent(new Event('input', {bubbles: true}));
          await vent(600);
          const ettFelt = R.mcKall.slice(n).map(t => ({iRender: iRender(t), etterRender: R.render[nR] ? t - R.render[nR][1] : null}));
          // Begge felt.
          n = R.mcKall.length; const nP = R.post.length;
          b.value = '1'; b.dispatchEvent(new Event('input', {bubbles: true}));
          await vent(600);
          const begge = {kall: R.mcKall.slice(n).map(t => iRender(t)), sendt: R.post.length - nP};
          await vent(1500);
          // H-knapp i en annen kamp.
          n = R.mcKall.length; const nP2 = R.post.length;
          eval(rader)[2].querySelector('button[data-q="H"]').click();
          await vent(600);
          const hKnapp = {kall: R.mcKall.slice(n).map(t => iRender(t)), sendt: R.post.length - nP2};
          return {ettFelt, begge, hKnapp};
        }, rader);
        check(`${liga}: begge tallene fylt ut sender tabellsimuleringen uten ventetiden (inne i render())`,
          st.begge.kall[0] === true && st.begge.sendt >= 1, JSON.stringify(st.begge));
        check(`${liga}: H/U/B sender tabellsimuleringen uten ventetiden (inne i render())`,
          st.hKnapp.kall[0] === true && st.hKnapp.sendt >= 1, JSON.stringify(st.hKnapp));
        check(`${liga}: bare ett felt fylt: venter 250 ms som før`,
          st.ettFelt.length >= 1 && st.ettFelt[0].iRender === false && st.ettFelt[0].etterRender >= 240, JSON.stringify(st.ettFelt));
        await p.close(); }

      // 4. Raske klikk, med «Fyll ut runden» av og på.
      for (const autofyll of ['av', 'på']) {
        const {p} = await rpApne(url);
        if (autofyll === 'av') { await handling(p, {type: 'av'}); await rpRolig(p); }
        const rk = await p.evaluate(async rader => {
          const R = __rp, nP = R.post.length, rr = eval(rader);
          const valg = [[1, 'H'], [4, 'U'], [6, 'B'], [8, 'H'], [10, 'B']];
          let tSiste = 0;
          await new Promise(res => valg.forEach(([nr, q], i) => setTimeout(() => {
            rr[nr].querySelector(`button[data-q="${q}"]`).click(); if (i === valg.length - 1) { tSiste = performance.now(); res(); } }, 100 * i)));
          const t0 = Date.now();
          while (Date.now() - t0 < 30000 && !(lastMCFinal === true && lastMCScenarioKey === qaScenarioKey() && !(typeof mcVenter !== 'undefined' && mcVenter))) await new Promise(r => setTimeout(r, 5));
          await new Promise(r => setTimeout(r, 500));
          const poster = R.post.slice(nP), siste = poster[poster.length - 1];
          const iRender = R.render.some(([a, b]) => siste.t >= a && siste.t <= b);
          const etterFerdig = R.fin.filter(t => t <= siste.t + 0.001).map(t => siste.t - t).filter(d => d >= 0);
          return {sendt: poster.length, iKo: poster.filter(x => x.iGang > 0).length, sisteIRender: iRender,
                  sisteRettEtterFerdig: etterFerdig.length ? Math.min(...etterFerdig) < 30 : false,
                  sisteEtterKlikk: Math.round(siste.t - tSiste), riktig: lastMCScenarioKey === qaScenarioKey() && lastMCFinal === true};
        }, rader);
        console.log(`      ${liga}, fyll ut runden ${autofyll}: fem raske klikk ga ${rk.sendt} simuleringer, den siste sendt ${rk.sisteEtterKlikk} ms etter siste klikk`);
        check(`${liga}, fyll ut runden ${autofyll}: raske klikk sender ingen simulering mens en annen pågår`, rk.iKo === 0 && rk.riktig, JSON.stringify(rk));
        check(`${liga}, fyll ut runden ${autofyll}: det siste scenarioet sendes uten ventetiden (i render() eller rett etter den pågående)`,
          rk.riktig && (rk.sisteIRender || rk.sisteRettEtterFerdig), JSON.stringify(rk));
        await p.close();
      }
    }
    await page.bringToFront();

    // ---- Svarene: låste utfall regnes som scenarioet ----
    // Et svar som låser en åpen kamp til et resultat skal regne med samme
    // lagstyrker og målrater som scenarioet bruker med samme resultat utfylt
    // (som kontroll U på testsiden). Utgangsstillingen regnes i Workerne. Testen
    // fanger oppgavene svarveien faktisk sender ("Rundens viktigste kamp", "Hva
    // betyr neste kamp?", "Heie på", finsilingen i "Hvilke kamper betyr
    // mest?"), spiller hver låste oppgave av i en Worker (mode laastStilling,
    // samme kode som oppgaven kjører) og sammenligner bit for bit med LIVE og
    // oddsOverrideFor etter setMatch + refreshLiveState. Uten og med et annet
    // resultat allerede fylt inn. Før fikk den låste kjøringen lagstyrkene og
    // oddsratene fra før resultatet.
    //  I tillegg: de delte funksjonene i WORKER_SRC er tegn for tegn
    // hovedtrådens (Function.toString), deklarert én gang, og konstantene er
    // like; og grovsilingen i "Hvilke kamper betyr mest?" går i poolen med
    // egen stilling per låst utfall.
    setGroup('Svarene: låste utfall som scenarioet');
    for (const [sti, liga] of [['/eliteserien/', 'Eliteserien'], ['/obos/', 'OBOS']]) {
      const url = base.replace('/eliteserien/', sti);
      const lp = await browser.newPage();
      lp.on('pageerror', e => errors.push(`${url}: ${e.message}`));
      await lp.evaluateOnNewDocument(() => {
        window.__sendt = [];
        const W = window.Worker;
        window.Worker = function (u, o) { const w = new W(u, o), post = w.postMessage.bind(w);
          w.postMessage = m => { if (m && (m.mode === 'zoneTask' || m.mode === 'matchImpact')) window.__sendt.push(m); return post(m); }; return w; };
      });
      await lp.setViewport({width: 1400, height: 900});
      await lp.goto(url, {waitUntil: 'networkidle0'});
      await lp.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 120000, polling: 50});

      // Én kilde: de delte funksjonene og konstantene.
      const kilde = await lp.evaluate(() => {
        const navn = ['pois', 'poisFyll', 'outcome', 'stateRate', 'computeLiveState', 'rateMedStilling', 'fitRates', 'fitRatesRegn',
                      'liveMedLaast', 'aapenKampFor', 'laastOver', 'dcTau', 'applyDrift'];
        const ut = {mangler: [], ulik: [], flere: [], konst: []};
        for (const n of navn) {
          const hoved = typeof window[n] === 'function' ? window[n].toString() : null;
          const antall = WORKER_SRC.split(`function ${n}(`).length - 1;
          if (!hoved || antall === 0) { ut.mangler.push(n); continue; }
          if (antall !== 1) ut.flere.push(`${n} (${antall})`);
          const i = WORKER_SRC.indexOf(`function ${n}(`);
          if (WORKER_SRC.slice(i, i + hoved.length) !== hoved) ut.ulik.push(n);
        }
        const W = {}; try { (new Function('W', 'var self={}; var postMessage=function(){};' + WORKER_SRC +
          '; W.v={GMAX, DC_RHO, DRIFT_CAP_ATTCON, DRIFT_CAP_HAHC, DRIFT_REVERSION, MAX_LAMBDA_LOG, FIT_MINNE_MAKS};'))(W); } catch (e) { ut.konst.push('feil: ' + e.message); }
        const hk = {GMAX, DC_RHO, DRIFT_CAP_ATTCON, DRIFT_CAP_HAHC, DRIFT_REVERSION, MAX_LAMBDA_LOG,
                    FIT_MINNE_MAKS: typeof FIT_MINNE_MAKS === 'undefined' ? null : FIT_MINNE_MAKS};
        for (const k in hk) if (!W.v || !Object.is(W.v[k], hk[k])) ut.konst.push(`${k}: ${W.v && W.v[k]} mot ${hk[k]}`);
        return {navn: navn.length, ...ut};
      });
      check(`${liga}: de delte funksjonene i WORKER_SRC er tegn for tegn hovedtrådens, én gang hver, og konstantene er like`,
        !kilde.mangler.length && !kilde.ulik.length && !kilde.flere.length && !kilde.konst.length,
        `mangler ${kilde.mangler.join(',')}; ulik ${kilde.ulik.join(',')}; flere ${kilde.flere.join(',')}; konstanter ${kilde.konst.join('; ')}`);

      // outcome(): bit-lik referansen bygget på pois() for hver celle (slik den
      // var), over fitRates-rutenettets område og tilfeldige lambda, og minst
      // dobbelt så rask. Fartskravet er relativt (samme side, samme maskin).
      const ut = await lp.evaluate(() => {
        const ref = (lh, la) => { let H = 0, U = 0, B = 0;
          for (let h = 0; h <= GMAX; h++) for (let a = 0; a <= GMAX; a++) { const p = pois(lh, h) * pois(la, a) * dcTau(h, a, lh, la); if (h > a) H += p; else if (h === a) U += p; else B += p; }
          const t = H + U + B; return {H: H / t, U: U / t, B: B / t}; };
        let n = 0, ulike = 0, frø = 99; const tilf = () => { frø = (frø * 1103515245 + 12345) % 2147483648; return frø / 2147483648; };
        const sjekk = (lh, la) => { n++; const a = outcome(lh, la), b = ref(lh, la); if (!Object.is(a.H, b.H) || !Object.is(a.U, b.U) || !Object.is(a.B, b.B)) ulike++; };
        for (let lh = 0.15; lh <= 4.5; lh += 0.01) for (let la = 0.15; la <= 4.5; la += 0.1) sjekk(lh, la);
        for (let i = 0; i < 50000; i++) sjekk(0.01 + 7 * tilf(), 0.01 + 7 * tilf());
        const tid = f => { const t = performance.now(); for (let i = 0; i < 20000; i++) f(0.5 + (i % 40) * 0.1, 1.1); return performance.now() - t; };
        tid(outcome); tid(ref);
        const tNy = Math.min(tid(outcome), tid(outcome)), tRef = Math.min(tid(ref), tid(ref));
        return {n, ulike, tNy: Math.round(tNy), tRef: Math.round(tRef)};
      });
      check(`${liga}: outcome() er bit-lik referansen med pois() per celle (${ut.n} lambda-par) og minst dobbelt så rask`,
        ut.n > 60000 && ut.ulike === 0 && ut.tNy * 2 <= ut.tRef, `${ut.ulike} ulike; 20 000 kall: ${ut.tNy} ms mot ${ut.tRef} ms`);

      for (const medAnnet of [false, true]) {
        if (medAnnet) {
          await lp.evaluate(() => { const m = matches.filter(x => x.hg == null).slice(-1)[0]; setMatch(m, 2, 0); render(); });
          await settle(lp);
        }
        const r = await lp.evaluate(async () => {
          const {openMatches} = buildQaOpen(); const nr = qaNextRoundMatches(openMatches);
          const lag = TEAMS.find(t => { const z = qaTargetZone(t); return z && !qaSettled(t, z) && nr.list.some(m => m.home === t || m.away === t); });
          __sendt.length = 0;
          await qaKeyRoundData(); await qaNextMatch(lag); await qaCheerFor(lag); await qaKeyMatches(lag);
          // Hver låste oppgave, spilt av i en egen Worker: stillingen den regner.
          const laaste = __sendt.filter(m => m.mode === 'zoneTask' && m.forcedIdx >= 0);
          const merket = laaste.filter(m => m.laastStilling).length;
          const kanSpille = WORKER_SRC.includes("d.mode==='laastStilling'");
          const stillinger = [];
          if (kanSpille) {
            const w = new Worker(URL.createObjectURL(new Blob([WORKER_SRC], {type: 'application/javascript'})));
            const svar = new Map(); w.onmessage = e => svar.set(e.data.runId, e.data);
            laaste.forEach((m, i) => w.postMessage({...m, mode: 'laastStilling', runId: i}));
            const t0 = Date.now(); while (svar.size < laaste.length && Date.now() - t0 < 60000) await new Promise(r => setTimeout(r, 20));
            w.terminate();
            laaste.forEach((m, i) => stillinger.push(svar.get(i)));
          }
          const likt = (a, b) => a.length === b.length && a.every((x, i) => Object.is(x, b[i]));
          const ulike = []; let par = 0, maksAvvik = 0;
          laaste.forEach((m, i) => {
            const st = stillinger[i] || {att: m.att, con: m.con, ha: m.ha, hc: m.hc, oddsOverride: m.oddsOverride};
            const o = m.open[m.forcedIdx], x = matches.find(y => !(y.hg != null && y.ag != null) && TI[y.home] === o[0] && TI[y.away] === o[1]);
            setMatch(x, m.forcedScore[0], m.forcedScore[1], false); refreshLiveState();
            const navn = `${x.home}-${x.away} ${m.forcedScore.join('-')}`;
            for (const f of ['att', 'con', 'ha', 'hc']) { par++;
              if (!likt(Array.from(st[f]), Array.from(LIVE[f]))) { ulike.push(`${navn}: ${f}`); maksAvvik = Math.max(maksAvvik, ...Array.from(LIVE[f]).map((v, j) => Math.abs(v - st[f][j]))); } }
            m.open.forEach((oo, j) => { if (j === m.forcedIdx) return;
              const sc = oddsOverrideFor(TEAMS[oo[0]], TEAMS[oo[1]]), sendt = (st.oddsOverride || [])[j] || null; par++;
              if (!((sc === null && sendt === null) || (sc && sendt && likt(sc, sendt)))) ulike.push(`${navn}: oddsOverride ${TEAMS[oo[0]]}-${TEAMS[oo[1]]}`); });
            setMatch(x, null, null, false); refreshLiveState();
          });
          render();
          return {lag, kjoringer: laaste.length, merket, kanSpille, kamper: new Set(laaste.map(m => m.forcedIdx)).size, par, ulike: ulike.length, eks: ulike.slice(0, 4), maksAvvik};
        });
        await settle(lp);
        const hvor = medAnnet ? 'med et annet resultat fylt inn' : 'uten scenario';
        console.log(`      ${liga} ${hvor} (følger ${r.lag}): ${r.kjoringer} låste oppgaver i ${r.kamper} kamper, ${r.merket} regnet i Workeren, ${r.par} sammenligninger`);
        check(`${liga}, ${hvor}: lagstyrkene og målratene Workerne regner for låste utfall er bit-like scenarioets med samme resultat`,
          r.kanSpille && r.kjoringer >= 20 && r.kamper >= 5 && r.merket === r.kjoringer && r.ulike === 0,
          `${r.ulike} ulike av ${r.par}, største avvik ${r.maksAvvik.toExponential(1)}, avspilling mulig: ${r.kanSpille}: ${r.eks.join('; ')}`);
      }

      // Grovsilingen i "Hvilke kamper betyr mest?" går i poolen, 400 sesonger,
      // med egen utgangsstilling per låst utfall (før: hjelpe-Workeren, uten
      // egen stilling). Alle oppgavene med N = QA_N_IMPACT er låste og merket
      // laastStilling, to per kandidatkamp, og ingen matchImpact-melding sendes.
      const grov = await lp.evaluate(async () => {
        const {openMatches} = buildQaOpen(); const nr = qaNextRoundMatches(openMatches);
        const lag = TEAMS.find(t => { const z = qaTargetZone(t); return z && !qaSettled(t, z) && nr.list.some(m => m.home === t || m.away === t); });
        const kand = buildMatchImpactCandidates(lag, openMatches).length;
        __sendt.length = 0;
        await qaKeyMatches(lag);
        const g = __sendt.filter(m => m.mode === 'zoneTask' && m.N === QA_N_IMPACT);
        return {lag, kand, N: QA_N_IMPACT, oppgaver: g.length, laaste: g.filter(m => m.forcedIdx >= 0 && m.laastStilling).length,
                matchImpact: __sendt.filter(m => m.mode === 'matchImpact').length};
      });
      check(`${liga}: grovsilingen går i poolen med 400 sesonger og egen utgangsstilling per låst utfall`,
        grov.N === 400 && grov.kand >= 10 && grov.oppgaver === 2 * grov.kand && grov.laaste === grov.oppgaver && grov.matchImpact === 0,
        JSON.stringify(grov));
      // matchImpact-svarene i poolen blir ferdige også når et annet svar starter
      // imens. Poolen forkaster køede oppgaver når et nytt kall i samme gruppe
      // starter; lå "Hva betyr neste kamp?" i samme gruppe som "Heie på", ble
      // det aldri ferdig. Hvert matchImpact-kall har derfor egen gruppe.
      const samtidig = await lp.evaluate(async () => {
        const {openMatches} = buildQaOpen(); const nr = qaNextRoundMatches(openMatches);
        const lag = TEAMS.find(t => { const z = qaTargetZone(t); return z && !qaSettled(t, z) && nr.list.some(m => m.home === t || m.away === t); });
        const ferdig = [];
        const svar = [['neste kamp', () => qaNextMatch(lag)], ['heie på', () => qaCheerFor(lag)], ['betyr mest', () => qaKeyMatches(lag)],
                      ['neste kamp igjen', () => qaNextMatch(lag)]]
          .map(([n, f]) => f().then(() => ferdig.push(n)));
        await Promise.race([Promise.all(svar), new Promise(r => setTimeout(r, 30000))]);
        return {ferdig, av: svar.length};
      });
      check(`${liga}: «Hva betyr neste kamp?» og finsilingen blir ferdige når «Heie på» starter samtidig`, samtidig.ferdig.length === samtidig.av, JSON.stringify(samtidig));
      // "Heie på", "Rundens viktigste kamp" og "Hva betydde forrige kamp?" har
      // hver sin forkastingsgruppe: startet to og to rett etter hverandre blir
      // begge ferdige, med nøyaktig samme tall som når de kjøres hver for seg.
      // Før delte de gruppen "svar", og det første ble aldri ferdig.
      const par = await lp.evaluate(async () => {
        const {openMatches} = buildQaOpen(); const nr = qaNextRoundMatches(openMatches);
        const lag = TEAMS.find(t => { const z = qaTargetZone(t); return z && !qaSettled(t, z) && nr.list.some(m => m.home === t || m.away === t); });
        const svar = {
          heie: () => qaCheerFor(lag),
          runde: async () => { const d = await qaKeyRoundData(); return JSON.stringify(d.list.map(r => [r.m.id, r.total])) + '|' + d.close.map(r => r.m.id).join(); },
          forrige: () => qaLastMatch(lag)};
        const alene = {}; for (const k in svar) alene[k] = await svar[k]();
        const ut = [];
        for (const [a, b] of [['heie', 'runde'], ['heie', 'forrige'], ['runde', 'forrige'], ['runde', 'heie']]) {
          const ferdig = {}, pa = svar[a]().then(v => ferdig[a] = v), pb = svar[b]().then(v => ferdig[b] = v);
          await Promise.race([Promise.all([pa, pb]), new Promise(r => setTimeout(r, 30000))]);
          ut.push({par: `${a}+${b}`, ferdig: Object.keys(ferdig), like: [a, b].filter(k => ferdig[k] === alene[k])});
        }
        return {lag, ut, forrigeSvar: String(alene.forrige).slice(0, 60)};
      });
      check(`${liga}: «Heie på», «Rundens viktigste kamp» og «Hva betydde forrige kamp?» startet to og to blir begge ferdige med samme tall som hver for seg`,
        par.ut.length === 4 && par.ut.every(x => x.ferdig.length === 2 && x.like.length === 2), JSON.stringify(par));
      await lp.close();
    }
    await page.bringToFront();

    // ---- Rundens viktigste kamp: lav N i nettleseren, høy N i CI ----
    // Svaret som regnes i nettleseren bruker QA_KEY_N / QA_KEY_CLOSE (3 000 /
    // 0,901). Innleggene (lag_innlegg.js) regnes med QA_KEY_N_CI /
    // QA_KEY_CLOSE_CI: minst 6 000 og 0,93. Banneret i keymatch.json regnes fra
    // grunnlagsfilen (lag_grunnlag.js, 100 000 sesonger, grensa 0,93, se
    // «Grunnlagsfilen på siden»). Testen fanger N som faktisk sendes til
    // poolen, og sjekker hvilke konstanter skriptene bruker.
    setGroup('Rundens viktigste kamp: N i nettleseren og i CI');
    {
      const innl = fs.readFileSync(path.join(ROOT, 'scripts', 'lag_innlegg.js'), 'utf8');
      check('lag_innlegg.js regner kåringen med CI-nivået (QA_KEY_N_CI, QA_KEY_CLOSE_CI)',
        innl.includes('qaKeyRoundData({N: QA_KEY_N_CI, close: QA_KEY_CLOSE_CI})') && !/qaKeyRoundData\(\)/.test(innl), 'lag_innlegg.js');
      const lg = fs.readFileSync(path.join(ROOT, 'scripts', 'lag_grunnlag.js'), 'utf8'), sp = fs.readFileSync(path.join(ROOT, 'scripts', 'snapshot_probs.js'), 'utf8');
      check('banneret regnes fra grunnlagsfilen av lag_grunnlag.js (samme kall som svaret), ikke av snapshot_probs.js',
        lg.includes('keymatchFra(await qaKeyRoundData())') && !sp.includes('qaKeyRoundData'), '');
      for (const [sti, liga] of [['/eliteserien/', 'Eliteserien'], ['/obos/', 'OBOS']]) {
        const kp = await open(1400, 900, base.replace('/eliteserien/', sti));
        const r = await kp.evaluate(async () => {
          if (typeof QA_KEY_N_CI === 'undefined') return {finnes: false};
          const zt = window.runZoneTasks, N = [];
          window.runZoneTasks = function (payload, ...rest) { N.push(payload.N); return zt.call(this, payload, ...rest); };
          try {
            const nett = await qaKeyRoundData(), ci = await qaKeyRoundData({N: QA_KEY_N_CI, close: QA_KEY_CLOSE_CI});
            return {finnes: true, konst: [QA_KEY_N, QA_KEY_CLOSE, QA_KEY_N_CI, QA_KEY_CLOSE_CI], sendt: N,
                    nett: [nett.sesonger, nett.grense], ci: [ci.sesonger, ci.grense],
                    // grensa brukes: med CI-grensa er ingen i "close" under 93 % av lederen
                    ciGrenseHolder: ci.close.every(x => x.total >= ci.best.total * QA_KEY_CLOSE_CI)};
          } finally { window.runZoneTasks = zt; }
        });
        check(`${liga}: nettleseren regner rundens viktigste kamp med 3 000 sesonger og grense 0,901`,
          r.finnes && r.konst[0] === 3000 && r.konst[1] === 0.901 && r.sendt[0] === 3000 && r.nett.join() === '3000,0.901', JSON.stringify(r));
        check(`${liga}: CI-nivået er minst 6 000 sesonger med grense 0,93, og brukes når det sendes`,
          r.finnes && r.konst[2] >= 6000 && r.konst[3] === 0.93 && r.sendt[1] === r.konst[2] && r.ci.join() === `${r.konst[2]},0.93` && r.ciGrenseHolder,
          JSON.stringify(r));
        await kp.close();
      }
    }
    await page.bringToFront();

    // ---- Dødmannsknappen: livstegn bare når alt gikk bra ----
    // planlegger/worker.js sender livstegn til healthchecks.io bare etter en
    // PLANLAGT runde innenfor vinduet der alle utløsningene fikk 204.
    // Feiler en runde, sendes ingenting (varselet skal komme når noe har vært
    // galt en stund, ikke ved hver feil), og aldri til /fail. update-data.yml
    // og obos-results.yml sender livstegn i SISTE steg, bare når jobben er
    // grønn, og steget kan aldri gjøre jobben rød. Workeren kjøres her i Node
    // med fetch og klokka byttet ut.
    setGroup('Dødmannsknappen: livstegn bare når alt gikk bra');
    {
      const {pathToFileURL} = require('url');
      const kilde = fs.readFileSync(path.join(ROOT, 'planlegger', 'worker.js'), 'utf8');
      const W = (await import(pathToFileURL(path.join(ROOT, 'planlegger', 'worker.js')).href + `?t=${Date.now()}`)).default;
      const EkteDate = Date, ekteFetch = globalThis.fetch;
      const kjor = async ({utc, status = () => 204, env = {}, manuell = false}) => {
        const kall = [];
        globalThis.Date = class extends EkteDate { constructor(...a) { super(...(a.length ? a : [utc])); } static now() { return new EkteDate(utc).getTime(); } };
        globalThis.fetch = async (url, o = {}) => { kall.push(String(url));
          if (String(url).startsWith('https://api.github.com/')) { const st = status(String(url)); return {status: st, ok: st === 204, text: async () => 'feil'}; }
          return {status: 200, ok: true, text: async () => ''}; };
        const fullEnv = {GITHUB_TOKEN: 'x', HEALTHCHECK_URL: 'https://hc-ping.com/test', UTLOSER_NOKKEL: 'n', ...env};
        const ekteLog = console.log; console.log = () => {};   // workerens egen logg hører ikke hjemme i testutskriften
        try {
          if (manuell) await W.fetch(new Request('https://w.example/?kjor=1', {headers: {'x-planlegger-nokkel': 'n'}}), fullEnv);
          else { const vent = []; await W.scheduled({}, fullEnv, {waitUntil: p => vent.push(p)}); await Promise.all(vent); }
        } finally { globalThis.Date = EkteDate; globalThis.fetch = ekteFetch; console.log = ekteLog; }
        return {utlost: kall.filter(u => u.startsWith('https://api.github.com/')).length, ping: kall.filter(u => u.startsWith('https://hc-ping.com/')),
                fail: kall.filter(u => u.includes('/fail')).length};
      };
      const inne = '2026-10-02T12:00:00Z', ute = '2026-10-02T23:00:00Z';
      const liste = (kilde.match(/const WORKFLOWS = \[([\s\S]*?)\];/) || [])[1] || '';
      const antall = (liste.match(/"[a-z-]+\.yml"/g) || []).length;
      check('planleggeren: WORKFLOWS har update-odds.yml (tidsporten avgjør om The Odds API kalles)', /"update-odds\.yml"/.test(liste) && antall >= 5, `${antall} workflows`);
      const r1 = await kjor({utc: inne});
      check('planleggeren: planlagt runde, alle 204: ett livstegn', r1.utlost === antall && r1.ping.length === 1 && r1.ping[0] === 'https://hc-ping.com/test', JSON.stringify(r1));
      const r2 = await kjor({utc: inne, status: u => u.includes('update-data') ? 500 : 204});
      check('planleggeren: én utløsning feilet: ingen livstegn, ingen /fail', r2.utlost === antall && r2.ping.length === 0 && r2.fail === 0, JSON.stringify(r2));
      const r3 = await kjor({utc: ute});
      check('planleggeren: utenfor vinduet 09-21 UTC: ingen utløsning, ingen livstegn', r3.utlost === 0 && r3.ping.length === 0, JSON.stringify(r3));
      const r4 = await kjor({utc: inne, manuell: true});
      check('planleggeren: manuell utløsning teller ikke som livstegn', r4.utlost === antall && r4.ping.length === 0, JSON.stringify(r4));
      const r5 = await kjor({utc: inne, env: {HEALTHCHECK_URL: ''}});
      const r6 = await kjor({utc: inne, env: {GITHUB_TOKEN: ''}});
      check('planleggeren: uten HEALTHCHECK_URL eller GITHUB_TOKEN: ingen livstegn, ingen krasj', r5.utlost === antall && r5.ping.length === 0 && r6.utlost === 0 && r6.ping.length === 0, JSON.stringify({r5, r6}));
      check('planleggeren: koden sender aldri til /fail', !kilde.includes('/fail'), '');
      for (const [wf, navn] of [['update-data.yml', 'HEALTHCHECK_UPDATE_DATA'], ['obos-results.yml', 'HEALTHCHECK_OBOS']]) {
        const t = fs.readFileSync(path.join(ROOT, '.github', 'workflows', wf), 'utf8');
        const steg = t.split('\n      - ').slice(1), siste = steg[steg.length - 1] || '', nest = steg[steg.length - 2] || '';
        const kode = siste.split('\n').filter(l => !l.trim().startsWith('#')).join('\n');
        check(`${wf}: livstegnet er siste steg, etter kildevakten, bare når jobben er grønn`,
          /healthchecks/i.test(siste.split('\n')[0]) && nest.includes('hentelogg.py sjekk') && !/\n\s*if:/.test(kode) && !kode.includes('continue-on-error'),
          siste.split('\n')[0]);
        check(`${wf}: livstegnet bruker hemmeligheten ${navn} og kan aldri gjøre jobben rød`,
          kode.includes(`HC_URL: \${{ secrets.${navn} }}`) && kode.includes('exit 0') && /if curl .*; then .*; else .*; fi/.test(kode) && !kode.includes('/fail'),
          '');
      }
    }

    // ---- Prekick: frysing ved avspark ----
    // prekick.json skal bare oppdateres FØR avspark fra terminlisten, og
    // fryses med siste stempel fra før avspark når resultatet kommer. Før
    // denne regelen ble raden skrevet på nytt til resultatet var inne, og den
    // frosne prognosen fikk som regel et stempel etter avspark. Testene kaller
    // regelen direkte (scripts/prekick_frys.js), den samme koden
    // snapshot_probs.js bruker for begge ligaer.
    setGroup('Prekick: frysing ved avspark');
    {
      const F = require(path.join(ROOT, 'scripts', 'prekick_frys.js'));
      // Norsk tid til UTC, også over sommertidsskiftet 25. oktober 2026.
      const utc = (y, mo, d, h, mi) => Date.UTC(y, mo - 1, d, h, mi);
      const tider = [['2026-10-09', '19:00', utc(2026, 10, 9, 17, 0)],
                     ['2026-10-24', '17:00', utc(2026, 10, 24, 15, 0)],
                     ['2026-10-25', '17:00', utc(2026, 10, 25, 16, 0)],
                     ['2026-12-05', '18:00', utc(2026, 12, 5, 17, 0)]];
      const feilTid = tider.filter(([d, tt, v]) => F.avsparkUtcMs(d, tt) !== v);
      check('avspark regnes om fra norsk tid til UTC, også over sommertidsskiftet', feilTid.length === 0,
        feilTid.map(([d, tt, v]) => `${d} ${tt}: ${new Date(F.avsparkUtcMs(d, tt)).toISOString()} mot ${new Date(v).toISOString()}`).join('; '));

      for (const liga of ['eliteserien', 'obos']) {
        const fx = JSON.parse(fs.readFileSync(path.join(ROOT, liga, 'data', 'fixtures.json'), 'utf8'));
        const avspark = F.avsparkFraTerminliste(fx);
        const kamper = fx.flatMap(r => r.matches);
        check(`${liga}: hver kamp i terminlisten får et avspark`,
          kamper.length > 0 && kamper.every(m => Number.isFinite(avspark[`${m.home}|${m.away}`])),
          `${kamper.filter(m => !Number.isFinite(avspark[`${m.home}|${m.away}`])).length} uten`);
        const m = kamper[0], a = avspark[`${m.home}|${m.away}`];
        const k = `2026|${m.home}|${m.away}`;
        const rad = (H) => ({[k]: {home: m.home, away: m.away, date: m.date, H, U: 0.3, B: 0.7 - H}});
        const iso = ms => new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
        const fil = {version: 1, matches: {}};
        // 1) før avspark: raden skrives, og en ny kjøring før avspark oppdaterer den
        F.oppdaterPrekick(fil, rad(0.40), [], avspark, a - 3 * 3600e3, iso(a - 3 * 3600e3));
        const n1 = F.oppdaterPrekick(fil, rad(0.41), [], avspark, a - 60e3, iso(a - 60e3));
        check(`${liga}: en kamp før avspark oppdateres (${m.home} - ${m.away})`,
          n1.oppdatert === 1 && fil.matches[k].H === 0.41 && fil.matches[k].stamp === iso(a - 60e3),
          JSON.stringify(fil.matches[k]));
        // 2) ved og etter avspark: raden røres ikke
        const n2 = F.oppdaterPrekick(fil, rad(0.55), [], avspark, a, iso(a));
        const n3 = F.oppdaterPrekick(fil, rad(0.60), [], avspark, a + 105 * 60e3, iso(a + 105 * 60e3));
        check(`${liga}: ved og etter avspark røres ikke raden`,
          n2.etterAvspark === 1 && n3.etterAvspark === 1 && fil.matches[k].H === 0.41 && fil.matches[k].stamp === iso(a - 60e3),
          JSON.stringify(fil.matches[k]));
        const tom = {version: 1, matches: {}};
        F.oppdaterPrekick(tom, rad(0.5), [], avspark, a + 60e3, iso(a + 60e3));
        check(`${liga}: en rad som mangler, lages ikke etter avspark`, !tom.matches[k], JSON.stringify(tom.matches));
        // 3) resultatet kommer: fryses med stempelet fra før avspark
        const n4 = F.oppdaterPrekick(fil, {}, [k], avspark, a + 3 * 3600e3, iso(a + 3 * 3600e3));
        const s = Date.parse(fil.matches[k].stamp);
        check(`${liga}: frysingen skjer når resultatet kommer, med stempelet fra før avspark`,
          n4.frosne === 1 && fil.matches[k].frosset === true && s < a && fil.matches[k].H === 0.41,
          `${JSON.stringify(fil.matches[k])}, avspark ${iso(a)}`);
        const n5 = F.oppdaterPrekick(fil, rad(0.9), [k], avspark, a - 3600e3, iso(a - 3600e3));
        check(`${liga}: en frosset rad røres aldri`, fil.matches[k].H === 0.41 && n5.oppdatert === 0,
          JSON.stringify(fil.matches[k]));
      }
      // HVEM SOM SKRIVER RADEN. Datajobbene (--uten-prekick-vindu) lar rader
      // med avspark innen 80 minutter være; "Odds nær avspark" (--bare-prekick)
      // skriver bare dem, når oddsen i kjøringen ble hentet 70 til 15 minutter
      // før avspark og skrivingen lander senest 10 minutter før. Se
      // scripts/prekick_frys.js. Feiler på koden fra før (uten modus skrev
      // begge alt).
      {
        const a = F.avsparkUtcMs('2026-10-02', '19:00'), a2 = a + 3 * 3600e3, M = 60e3;
        const avspark = {'A|B': a, 'C|D': a2};
        const iso = ms => new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
        const rad = (H) => ({'2026|A|B': {home: 'A', away: 'B', H, U: 0.3, B: 0.7 - H},
                             '2026|C|D': {home: 'C', away: 'D', H, U: 0.3, B: 0.7 - H}});
        const start = () => ({version: 1, matches: {'2026|A|B': {home: 'A', away: 'B', H: 0.1, stamp: 'gml'},
                                                     '2026|C|D': {home: 'C', away: 'D', H: 0.1, stamp: 'gml'}}});
        // Datajobben
        const dj = min => { const f = start(); const n = F.oppdaterPrekick(f, rad(0.5), [], avspark, a - min * M, iso(a - min * M), 'uten-vindu'); return {f, n}; };
        const d81 = dj(81), d80 = dj(80), d40 = dj(40), d5 = dj(5);
        check('datajobben skriver raden 81 minutter før avspark',
          d81.f.matches['2026|A|B'].H === 0.5 && d81.n.vinduHoppet === 0, JSON.stringify(d81.f.matches['2026|A|B']));
        check('datajobben lar raden være fra 80 minutter før avspark (80, 40 og 5 min), men skriver kampen tre timer senere',
          [d80, d40, d5].every(x => x.f.matches['2026|A|B'].H === 0.1 && x.n.vinduHoppet === 1 && x.f.matches['2026|C|D'].H === 0.5),
          [d80, d40, d5].map(x => JSON.stringify(x.n)).join(' '));
        const df = start(); F.oppdaterPrekick(df, {}, ['2026|A|B'], avspark, a + 3 * 3600e3, iso(a + 3 * 3600e3), 'uten-vindu');
        check('datajobben fryser fortsatt raden når resultatet kommer', df.matches['2026|A|B'].frosset === true && df.matches['2026|A|B'].stamp === 'gml',
          JSON.stringify(df.matches['2026|A|B']));
        // "Odds nær avspark": oddstid (porten) og klokken når raden skrives
        const pk = (odds, ekte, spilte = []) => { const f = start(); const n = F.oppdaterPrekick(f, rad(0.5), spilte, avspark, a - odds * M, iso(a - odds * M), 'bare-vindu', a - ekte * M); return {f, n, r: f.matches['2026|A|B']}; };
        const skrevet = x => x.r.H === 0.5, urort = x => x.r.H === 0.1 && x.r.stamp === 'gml';
        const tilfeller = [[71, 71, false], [70, 70, true], [40, 40, true], [16, 16, true], [15, 15, true], [14, 14, false],
                           [16, 14, true], [16, 10, true], [16, 9, false], [40, 41, false], [5, 5, false], [-1, -1, false]];
        const feil = tilfeller.filter(([o, e, ja]) => { const x = pk(o, e); return ja ? !(skrevet(x) && x.r.stamp === iso(a - o * M)) : !urort(x); });
        check('"Odds nær avspark" skriver raden bare når oddsen ble hentet 70 til 15 min før avspark, og senest 10 min før',
          feil.length === 0, feil.map(([o, e, ja]) => `odds ${o} min, skrevet ${e} min: ${ja ? 'skulle skrives' : 'skulle ikke'}`).join('; '));
        const strad = pk(16, 14);
        check('odds hentet 16 min før, skrevet 14 min før: raden får oddsen, med stempelet fra hentingen',
          skrevet(strad) && strad.r.stamp === iso(a - 16 * M), JSON.stringify(strad.r));
        const pkAnnen = pk(40, 40, ['2026|C|D']);
        check('"Odds nær avspark" rører ikke rader utenfor vinduet og fryser ingenting',
          pkAnnen.f.matches['2026|C|D'].H === 0.1 && pkAnnen.f.matches['2026|C|D'].stamp === 'gml' && !pkAnnen.f.matches['2026|C|D'].frosset && pkAnnen.n.frosne === 0,
          JSON.stringify(pkAnnen.f.matches['2026|C|D']));
        // De to skriverne tar aldri samme rad tett i tid: regner datajobben
        // raden dMin minutter før avspark, kan "Odds nær avspark" tidligst
        // skrive den over ti minutter senere (bufferen). Da rekker datajobben
        // å pushe først (målt: under ti sekunder fra snapshot til push), og
        // rebasen går rent. Uten bufferen (BUFFER_MIN = 0) feiler denne.
        const kollisjon = [];
        for (let dMin = 300; dMin > 0; dMin--) {
          if (F.datajobbenHopperOver(a, a - dMin * M)) continue;
          for (let s = 0; s <= 10; s++) {
            const o = dMin - s;
            if (F.prekickSkriver(a, a - o * M, a - o * M)) kollisjon.push(`datajobb ${dMin} min, odds ${o} min før`);
          }
        }
        check('datajobben og "Odds nær avspark" skriver aldri samme rad innen ti minutter av hverandre', kollisjon.length === 0,
          kollisjon.slice(0, 5).join('; '));
        const fx = [{matches: [{home: 'A', away: 'B', date: '2026-10-02', time: '19:00', played: false},
                               {home: 'C', away: 'D', date: '2026-10-02', time: '22:00', played: false},
                               {home: 'E', away: 'F', date: '2026-10-02', time: '19:00', played: true}]}];
        check('kamperIVinduet finner de uspilte kampene "Odds nær avspark" skal skrive',
          JSON.stringify(F.kamperIVinduet(fx, a - 40 * M)) === '["A|B"]' && F.kamperIVinduet(fx, a - 16 * M, a - 14 * M).length === 1
            && F.kamperIVinduet(fx, a - 16 * M, a - 9 * M).length === 0 && F.kamperIVinduet(fx, a - 90 * M).length === 0,
          JSON.stringify(F.kamperIVinduet(fx, a - 40 * M)));
        // Grensene er de samme som i porten og sluttoddsvinduet (Python).
        const {execFileSync} = require('child_process');
        const [fra, til, cFra, cTil] = execFileSync('python3', ['-c',
          'import sys; sys.path.insert(0, "scripts"); import prekick_vindu as v, oddswindow as w; print(v.FRA_MIN, v.TIL_MIN, w.CLOSE_FROM_MIN, w.CLOSE_TO_MIN)'],
          {cwd: ROOT, encoding: 'utf8'}).trim().split(' ').map(Number);
        check('grensene følger porten og sluttoddsvinduet: 70 = FRA_MIN, 15 = CLOSE_TO_MIN, 10 = TIL_MIN, og vinduet dekker 60 = CLOSE_FROM_MIN',
          F.VINDU_MIN === fra && F.SLUTT_MIN === cTil && F.SKRIVESTOPP_MIN === til && F.VINDU_MIN >= cFra && F.BUFFER_MIN >= 5,
          `VINDU_MIN ${F.VINDU_MIN}/${fra}, SLUTT_MIN ${F.SLUTT_MIN}/${cTil}, SKRIVESTOPP_MIN ${F.SKRIVESTOPP_MIN}/${til}, CLOSE_FROM_MIN ${cFra}`);
        // Hentingen av oddsen er uendret: prekick_odds.py velger kampene med
        // sluttoddsvinduet (60 til 15 min), ikke med noe fra frysregelen.
        const po = fs.readFileSync(path.join(ROOT, 'scripts', 'prekick_odds.py'), 'utf8');
        check('prekick_odds.py henter fortsatt oddsen 60 til 15 minutter før avspark, uavhengig av når raden skrives',
          po.includes('fra = now + timedelta(minutes=oddswindow.CLOSE_TO_MIN)') && po.includes('til = now + timedelta(minutes=oddswindow.CLOSE_FROM_MIN)')
            && po.includes('if ko and fra <= ko <= til:') && !/prekick_frys|SKRIVESTOPP|SLUTT_MIN|prekick\.json/.test(po), '');
      }

      // Samme skript for begge ligaer: snapshot_probs.js bruker regelen og
      // leser terminlisten i ligaens egen mappe, og OBOS-jobben kjører det.
      const snap = fs.readFileSync(path.join(ROOT, 'scripts', 'snapshot_probs.js'), 'utf8');
      const obosWf = fs.readFileSync(path.join(ROOT, '.github', 'workflows', 'obos-results.yml'), 'utf8');
      check('snapshot_probs.js bruker frysregelen og ligaens egen terminliste',
        /require\('\.\/prekick_frys'\)/.test(snap) && /const naa = BARE_PREKICK \? ODDSTID : Date\.now\(\);/.test(snap)
          && /oppdaterPrekick\(old, pre, spilte, avspark, naa, isoSek\(naa\), PREKICK_MODUS, BARE_PREKICK \? Date\.now\(\) : naa\)/.test(snap)
          && /path\.join\(DATA, 'fixtures\.json'\)/.test(snap) && !/old\.matches\[k\] = \{\.\.\.v, stamp/.test(snap),
        'koblingen mangler, eller den gamle oppdateringen står igjen');
      check('OBOS-jobben kjører det samme skriptet (snapshot_probs.js obos)', /snapshot_probs\.js obos/.test(obosWf));
    }

    // ---- Prekick: «Odds nær avspark» regner raden med de nyeste lagstyrkene ----
    // Prognosen før avspark er 30 prosent modell. Blir en tidligere kamp samme
    // dag ferdig mens en senere er i vinduet, skal neste kjøring av «Odds nær
    // avspark» (snapshot_probs.js --bare-prekick) regne raden med lagstyrkene
    // etter den kampen, også når prisen for den senere kampen er den samme.
    // Testen kjører det ekte skriptet i en kopi av repoet med falsk klokke
    // (tests/falsk_klokke.js). Resultatet legges inn slik OBOS-jobben gjør
    // (matches.json, fixtures.json), og modellen tilpasses på nytt med samme
    // tilpasning som den (fit_fast med parameterne i obos_build_data.py).
    // At hjelperen gir samme modell som jobben, sjekkes først mot siste
    // commit som bygde model.json, med filene fra den commiten: sluttoddsen
    // kan ha blitt hentet på nytt etterpå uten at modellen er bygget igjen
    // (28.9: odds_closing.json skrevet om 14:46Z, modellen bygget 09:02Z).
    // Før kjøring A tilpasses modellen derfor på nytt med dagens filer, så A
    // og B skiller seg BARE i resultatet.
    setGroup('Prekick: «Odds nær avspark» bruker de nyeste lagstyrkene');
    if (!live) {
      const os = require('os'), {execFileSync, spawnSync} = require('child_process');
      const F = require(path.join(ROOT, 'scripts', 'prekick_frys.js'));
      const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'prekick-'));
      let tmpServer = null;
      try {
        const filer = execFileSync('git', ['ls-files', '-co', '--exclude-standard', '-z'], {cwd: ROOT}).toString().split('\0').filter(Boolean);
        for (const f of filer) {
          const fra = path.join(ROOT, f);
          if (!fs.existsSync(fra) || fs.statSync(fra).isDirectory()) continue;
          fs.mkdirSync(path.dirname(path.join(TMP, f)), {recursive: true});
          fs.copyFileSync(fra, path.join(TMP, f));
        }
        const D = path.join(TMP, 'obos', 'data');
        const tekst = f => fs.existsSync(path.join(D, f)) ? fs.readFileSync(path.join(D, f), 'utf8') : null;
        const les = f => JSON.parse(tekst(f));
        const skriv = (f, d) => fs.writeFileSync(path.join(D, f), JSON.stringify(d, null, 1) + '\n');
        const iso = ms => new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
        const M = 60e3;
        const py = fs.existsSync(path.join(ROOT, '.venv', 'bin', 'python3')) ? path.join(ROOT, '.venv', 'bin', 'python3') : 'python3';
        const TILPASS = [
          'import json, sys',
          'sys.path.insert(0, "scripts")',
          'import fit_fast, obos_build_data as B',
          'from pathlib import Path',
          'D = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "obos/data/"',
          'B.ODDS_PATH = Path(D) / "odds_closing.json"',
          'spilte = json.load(open(D + "matches.json", encoding="utf-8"))',
          'model = json.load(open(D + "model.json", encoding="utf-8"))',
          'lag = model["teams"]; TI = {t: i for i, t in enumerate(lag)}',
          'closing = B.load_closing_odds()',
          'fm = [{"date": m["date"], "home": m["home"], "away": m["away"], "hg": m["hg"], "ag": m["ag"], "odds": closing.get((m["home"], m["away"]))} for m in spilte]',
          'n = sum(1 for m in fm if m["odds"])',
          'res = fit_fast.fit_model_fast(fm, lag, TI, odds_weight=B.ODDS_WEIGHT if n else 0.0, half_life_goals=B.HALF_LIFE, half_life_odds=B.HALF_LIFE, l1=B.L1, l2=B.L2, ref_date=max(m["date"] for m in spilte), isolate_global=True)',
          'ny = dict(model, mu=res["mu"], H=res["H"], att=list(res["att"]), con=list(res["con"]), ha=list(res["ha"]), hc=list(res["hc"]))',
          'if "--skriv" in sys.argv: open(D + "model.json", "w", encoding="utf-8").write(json.dumps(ny, ensure_ascii=False, indent=1) + "\\n")',
          'print(json.dumps({k: ny[k] for k in ("mu", "H", "att", "con", "ha", "hc")}))'].join('\n');
        const tilpass = (...a) => JSON.parse(execFileSync(py, ['-c', TILPASS, ...a], {cwd: TMP, encoding: 'utf8'}));

        // Hjelperen gir samme modell som OBOS-jobben: filene fra siste commit
        // som skrev model.json, tilpasset på nytt, gir den samme model.json.
        const rev = execFileSync('git', ['log', '-1', '--format=%h', '--', 'obos/data/model.json'], {cwd: ROOT, encoding: 'utf8'}).trim();
        const REV = path.join(TMP, 'rev', 'obos', 'data');
        fs.mkdirSync(REV, {recursive: true});
        for (const f of ['matches.json', 'model.json', 'odds_closing.json'])
          fs.writeFileSync(path.join(REV, f), execFileSync('git', ['show', `${rev}:obos/data/${f}`], {cwd: ROOT}));
        const jobb = JSON.parse(fs.readFileSync(path.join(REV, 'model.json'), 'utf8')), gjen = tilpass(REV + path.sep);
        const avvik = (x, y) => Math.max(Math.abs(x.mu - y.mu), Math.abs(x.H - y.H),
          ...['att', 'con', 'ha', 'hc'].flatMap(f => x[f].map((v, i) => Math.abs(v - y[f][i]))));
        check(`tilpasningen i testen gir samme modell som OBOS-jobben (filene fra ${rev})`, avvik(gjen, jobb) < 1e-9,
          `største avvik ${avvik(gjen, jobb)}`);
        const naaModell = les('model.json');
        const modellA = tilpass('--skriv');

        // To kamper i samme runde samme dag: E kl. 15 og S kl. 19, norsk tid.
        const fx = les('fixtures.json');
        const runde = fx.find(r => r.matches.filter(m => !m.played).length >= 2);
        const [E, S] = runde.matches.filter(m => !m.played);
        E.date = S.date; E.time = '15:00'; S.time = '19:00';
        skriv('fixtures.json', fx);
        const a = F.avsparkUtcMs(S.date, '19:00');
        // Pinnacle-prisen for S slik «Odds nær avspark» skrev den. Den står
        // uendret gjennom hele testen.
        const opp = les('odds_upcoming.json');
        opp.matches = (opp.matches || []).filter(m => !(m.home === S.home && m.away === S.away));
        opp.matches.push({home: S.home, away: S.away, commence_time: new Date(a).toISOString(), H: 0.4, D: 0.27, A: 0.33,
          odds: {H: 2.4, U: 3.55, B: 2.9}, n_bookmakers: 1, bookmaker: 'pinnacle', priced_at: iso(a - 45 * M), prekick: true, minutter_for: 45});
        skriv('odds_upcoming.json', opp);
        const oddsTekst = tekst('odds_upcoming.json');
        const andre = ['keymatch.json', 'lastmatch.json', 'history.json'].map(f => [f, tekst(f)]);
        const foer = les('prekick.json');
        const k = `${naaModell.meta.season}|${S.home}|${S.away}`;
        const pp = require.resolve('puppeteer-core');
        const nodePath = [pp.slice(0, pp.lastIndexOf(`${path.sep}puppeteer-core${path.sep}`)), process.env.NODE_PATH].filter(Boolean).join(path.delimiter);
        const kjor = (oddsMin, klokkeMin) => {
          const r = spawnSync(process.execPath, ['--require', path.join(TMP, 'tests', 'falsk_klokke.js'), path.join(TMP, 'scripts', 'snapshot_probs.js'),
            'obos', '--bare-prekick', '--oddstid', iso(a - oddsMin * M)],
            {cwd: TMP, encoding: 'utf8', timeout: 300000,
             env: {...process.env, NODE_PATH: nodePath, FALSK_KLOKKE: new Date(a - klokkeMin * M).toISOString()}});
          return {kode: r.status, ut: `${r.stdout || ''}${r.stderr || ''}`.trim(), rad: les('prekick.json').matches[k]};
        };
        // Sidens egne tall for S med filene slik de står nå: modellen alene
        // (lagstyrkene fra model.json), og prognosen siden viser.
        tmpServer = await serve(TMP);
        const sidenNaa = async () => {
          const pg = await browser.newPage();
          pg.on('pageerror', e => errors.push(`prekick-kopi: ${e.message}`));
          await pg.goto(`http://127.0.0.1:${tmpServer.address().port}/obos/`, {waitUntil: 'networkidle0'});
          await pg.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 180000});
          const r = await pg.evaluate((h, b) => {
            const mf = MODEL, ih = mf.teams.indexOf(h), ib = mf.teams.indexOf(b);
            // Rett fra model.json, uten sidens tilstand: samme formel som stateRate.
            const lh = Math.exp(Math.min(MAX_LAMBDA_LOG, mf.mu + mf.H + mf.att[ih] + mf.ha[ih] + mf.con[ib] - mf.hc[ib]));
            const lb = Math.exp(Math.min(MAX_LAMBDA_LOG, mf.mu + mf.att[ib] - mf.ha[ib] + mf.con[ih] + mf.hc[ih]));
            const md = outcome(lh, lb), o = outcome(...rateFor(h, b));
            return {md: {H: md.H, U: md.U, B: md.B}, o: {H: o.H, U: o.U, B: o.B}};
          }, S.home, S.away);
          await pg.close();
          return r;
        };
        const likt = (rad, tall) => rad && ['H', 'U', 'B'].every(x => Math.abs(rad[x] - tall[x]) <= 0.00005 + 1e-12);

        // 1) 18.20: E er ferdig, men resultatet er ikke inne ennå.
        const A = kjor(40, 40), sideA = await sidenNaa();
        check(`kjøring 40 min før avspark skriver raden for ${S.home} - ${S.away}, med stempelet fra hentingen`,
          A.kode === 0 && A.rad && A.rad.stamp === iso(a - 40 * M) && A.rad.odds && A.rad.odds.bookmaker === 'pinnacle',
          `kode ${A.kode}, rad ${JSON.stringify(A.rad)}\n${A.ut.slice(-600)}`);
        check('modelldelen er modellen fra model.json, og prognosen er den siden viser',
          likt(A.rad && A.rad.modell, sideA.md) && likt(A.rad, sideA.o), `rad ${JSON.stringify(A.rad)}, siden ${JSON.stringify(sideA)}`);
        check('raden har prisens tidspunkt og minutter før avspark fra «Odds nær avspark» (priced_at, minutter_for)',
          A.rad && A.rad.odds && A.rad.odds.priced_at === iso(a - 45 * M) && A.rad.odds.minutter_for === 45,
          JSON.stringify(A.rad && A.rad.odds));

        // 2) Resultatet i E kommer inn (OBOS-jobben): matches.json,
        // fixtures.json og ny modell. Oddsen for S er den samme.
        const ms = les('matches.json');
        ms.push({date: E.date, time: '15:00', round: runde.round, home: E.home, away: E.away, hg: 5, ag: 0});
        skriv('matches.json', ms);
        Object.assign(E, {played: true, hg: 5, ag: 0});
        skriv('fixtures.json', fx);
        tilpass('--skriv');
        const B = kjor(30, 30), sideB = await sidenNaa();
        const flytt = A.rad && B.rad ? Math.max(...['H', 'U', 'B'].map(x => Math.abs(B.rad.modell[x] - A.rad.modell[x]))) : 0;
        check(`neste kjøring (30 min før) bruker lagstyrkene etter ${E.home} - ${E.away} 5-0: modelldelen flytter seg (${flytt.toFixed(4)})`,
          B.kode === 0 && B.rad && B.rad.stamp === iso(a - 30 * M) && flytt >= 0.001,
          `flyttet ${flytt.toFixed(4)}; A ${JSON.stringify(A.rad && A.rad.modell)}, B ${JSON.stringify(B.rad && B.rad.modell)}\n${B.ut.slice(-600)}`);
        const modellB = les('model.json');
        check('... med modellen fra den nye model.json, og prognosen siden viser nå',
          likt(B.rad && B.rad.modell, sideB.md) && likt(B.rad, sideB.o) && !likt(B.rad && B.rad.modell, sideA.md) && avvik(modellA, modellB) > 0,
          `rad ${JSON.stringify(B.rad)}, siden ${JSON.stringify(sideB)}`);
        check('... selv om prisen for kampen er den samme (odds_upcoming.json uendret, samme odds i raden)',
          tekst('odds_upcoming.json') === oddsTekst && A.rad && B.rad && JSON.stringify(A.rad.odds) === JSON.stringify(B.rad.odds),
          `${JSON.stringify(A.rad && A.rad.odds)} mot ${JSON.stringify(B.rad && B.rad.odds)}`);

        // 3) Oddsen hentet 16 min før, raden skrevet 14 min før: skrives,
        // med stempelet fra hentingen. Senere enn 10 min før, eller odds
        // hentet 14 min før: ingenting.
        const C = kjor(16, 14);
        check('odds hentet 16 min før og skrevet 14 min før: raden skrives, stempel 16 min før',
          C.kode === 0 && C.rad && C.rad.stamp === iso(a - 16 * M), `kode ${C.kode}, ${JSON.stringify(C.rad)}\n${C.ut.slice(-400)}`);
        const etterC = tekst('prekick.json');
        const Dk = kjor(16, 9), Ek = kjor(14, 14);
        check('skrevet 9 min før, eller odds hentet 14 min før: ingenting skrives',
          Dk.kode === 0 && Ek.kode === 0 && tekst('prekick.json') === etterC && /ingen kamp i vinduet/.test(Dk.ut) && /ingen kamp i vinduet/.test(Ek.ut),
          `${Dk.ut}\n${Ek.ut}`);

        // Uten priced_at og minutter_for i oddsraden (samme priser): heller
        // ikke i den frosne raden.
        const uten = les('odds_upcoming.json');
        uten.matches.filter(m => m.home === S.home && m.away === S.away).forEach(m => { delete m.priced_at; delete m.minutter_for; });
        skriv('odds_upcoming.json', uten);
        const F2 = kjor(20, 20);
        check('uten priced_at og minutter_for i oddsraden står de heller ikke i den frosne raden, med samme priser',
          F2.kode === 0 && F2.rad && F2.rad.odds && !('priced_at' in F2.rad.odds) && !('minutter_for' in F2.rad.odds)
            && ['H', 'U', 'B', 'bookmaker'].every(x => F2.rad.odds[x] === B.rad.odds[x]) && F2.rad.stamp === iso(a - 20 * M),
          `${JSON.stringify(F2.rad && F2.rad.odds)}\n${F2.ut.slice(-300)}`);

        // 4) Ingenting annet er rørt: bare raden for S, og verken keymatch,
        // lastmatch eller historikken.
        const etter = les('prekick.json');
        const endret = [...new Set([...Object.keys(foer.matches), ...Object.keys(etter.matches)])]
          .filter(x => JSON.stringify(foer.matches[x]) !== JSON.stringify(etter.matches[x]));
        check('bare raden i vinduet er endret i prekick.json', endret.length === 1 && endret[0] === k, endret.join(', '));
        check('keymatch, lastmatch og historikken er urørt', andre.every(([f, t]) => tekst(f) === t),
          andre.filter(([f, t]) => tekst(f) !== t).map(([f]) => f).join(', '));
      } finally {
        if (tmpServer) tmpServer.close();
        fs.rmSync(TMP, {recursive: true, force: true});
      }
    }

    // ---- Grunnlagsfilen: fingeravtrykket, oppgavene og regningen ----
    // Del 2, steg 2: grunnlag.json regnes i CI med sidens egne funksjoner
    // (grunnlagRegn, grunnlagAvtrykk), av scripts/lag_grunnlag.js. Siden
    // bruker ikke filen ennå. Testene krever at avtrykket er det samme ved hver
    // lasting og endres med hver inndata, at oppgavene dekker det svarene
    // faktisk sender til poolen (samme id, kamp, resultat og frø), at
    // regningen er bit for bit poolens, og at skriptet bare skriver en fil
    // når alt stemmer. Alle tre sidene; på testsiden går de låste utfallene
    // gjennom eloTaskOver, og ELO-modellen og -koden er med i avtrykket.
    setGroup('Grunnlagsfilen: fingeravtrykket, oppgavene og regningen');
    for (const [url, liga] of [[base, 'eliteserien'], [base.replace('/eliteserien/', '/obos/'), 'obos'],
                               [base.replace('/eliteserien/', '/elo-test/'), 'elo-test']]) {
      const s1 = await open(1400, 900, url), s2 = await open(1400, 900, url);
      const a1 = await s1.evaluate(() => grunnlagAvtrykk()), a2 = await s2.evaluate(() => grunnlagAvtrykk());
      await s2.close();
      check(`${liga}: avtrykket er det samme ved to lastinger (SHA-256), og avhenger av N`,
        /^[0-9a-f]{64}$/.test(a1) && a1 === a2 && (await s1.evaluate(() => grunnlagAvtrykk(1000))) !== a1, `${a1} / ${a2}`);
      // Hver inndata endrer avtrykket; tilstanden settes tilbake etterpå.
      const endr = await s1.evaluate(async () => {
        const f = await grunnlagAvtrykk(), ut = {};
        const prov = async (navn, gjor, angre) => { gjor(); ut[navn] = (await grunnlagAvtrykk()) !== f; angre(); };
        const m = matches.find(x => x.hg == null);
        await prov('et resultat fylt inn', () => { m.hg = 1; m.ag = 0; }, () => { m.hg = null; m.ag = null; });
        if (typeof ELO !== 'undefined' && ELO) {
          // Testsiden: ELO-modellen (emodell/model.json) og -koden.
          const lag0 = Object.keys(ELO.rating_alle || ELO.rating)[0], R = ELO.rating_alle || ELO.rating, r0 = R[lag0];
          await prov('ratingen i ELO-modellen', () => { R[lag0] = r0 + 1e-9; }, () => { R[lag0] = r0; });
          const h0 = ELO.hjemmefordel_rating;
          await prov('hjemmefordelen i ELO-modellen', () => { ELO.hjemmefordel_rating = h0 + 1e-9; }, () => { ELO.hjemmefordel_rating = h0; });
          const l0 = ELO.lam_tabell.lh[0];
          await prov('lambda-tabellen i ELO-modellen', () => { ELO.lam_tabell.lh[0] = l0 + 1e-9; }, () => { ELO.lam_tabell.lh[0] = l0; });
          const e = grunnlagInndata(GRUNNLAG_N).ekstra;
          ut['ELO-koden og ELO_HVA er med, ikke tidsstempelet og rating_historikk'] = !!e && /function eloMixLap/.test(e.kode)
            && /function eloTaskOver/.test(e.kode) && JSON.stringify(e.ELO_HVA) === JSON.stringify(ELO_HVA)
            && !('built' in e.modell) && !('rating_historikk' in e.modell) && 'lam_tabell' in e.modell;
        } else {
          const a0 = MODEL.att[0];
          await prov('lagstyrke i modellen', () => { MODEL.att[0] = a0 + 1e-12; }, () => { MODEL.att[0] = a0; });
          const mu0 = MODEL.mu;
          await prov('mu i modellen', () => { MODEL.mu = mu0 + 1e-12; }, () => { MODEL.mu = mu0; });
        }
        const k = Object.keys(ODDS_UP)[0], h0 = k && ODDS_UP[k].H;
        if (k) await prov('en oddspris', () => { ODDS_UP[k].H = h0 + 1e-6; }, () => { ODDS_UP[k].H = h0; });
        else ut['en oddspris'] = 'ingen odds';
        const inn = grunnlagInndata(GRUNNLAG_N);
        ut['Worker-koden, FORM_K og ODDS_W er med'] = inn.worker === WORKER_SRC && inn.FORM_K === FORM_K && inn.ODDS_W === ODDS_W;
        ut['tilbake til utgangspunktet'] = (await grunnlagAvtrykk()) === f;
        return ut;
      });
      check(`${liga}: avtrykket endres med et resultat, modellen og oddsen, og har Worker-koden og konstantene`,
        Object.values(endr).every(v => v === true), JSON.stringify(endr));

      // Oppgavene svarene sender til poolen (runZoneTasks byttes ut og
      // fanger dem), for alle 16 lag: "Heie på", "Hva betyr neste kamp?",
      // "Hvilke kamper betyr mest?" (grov- og finsiling) og "Rundens
      // viktigste kamp". Hver av dem skal finnes i filens oppgaver med samme
      // kamp og resultat, og frøet skal være filens.
      const dekn = await s1.evaluate(async () => {
        const {openMatches, scenarioKey} = buildQaOpen();
        const fil = new Map(grunnlagOppgaver(openMatches).map(t => [t.id, t])), seed = hashStr(scenarioKey + '|impact');
        const n = TEAMS.length, sett = [], ekte = runZoneTasks;
        runZoneTasks = (payload, tasks, onTask, gruppe) => {
          tasks.forEach(t => sett.push({t, seed: payload.seed, gruppe}));
          const res = {};
          tasks.forEach(t => { res[t.id] = {prob: 0.5, pos: new Array(n * n).fill(1 / n)}; });
          if (onTask) tasks.forEach(t => onTask(t.id, res));
          return Promise.resolve(res);
        };
        try {
          for (const lag of TEAMS) { await qaCheerFor(lag); await qaNextMatch(lag); await qaKeyMatches(lag); }
          await qaKeyRoundData();
        } finally { runZoneTasks = ekte; }
        const mangler = sett.filter(x => { const f = fil.get(x.t.id);
          return !f || f.idx !== x.t.idx || JSON.stringify(f.score) !== JSON.stringify(x.t.score); });
        return {antall: sett.length, grupper: [...new Set(sett.map(x => x.gruppe.split(':')[0]))].sort(),
                mangler: mangler.slice(0, 5).map(x => `${x.gruppe} ${x.t.id} ${JSON.stringify(x.t.score)}`), nMangler: mangler.length,
                feilFro: sett.filter(x => x.seed !== seed).length, oppgaver: fil.size};
      });
      check(`${liga}: filens ${dekn.oppgaver} oppgaver dekker alle ${dekn.antall} oppgavene svarene sender, med samme frø`,
        dekn.antall > 100 && dekn.nMangler === 0 && dekn.feilFro === 0 && ['heie', 'impact', 'runde'].every(g => dekn.grupper.includes(g)),
        JSON.stringify(dekn));

      // Regningen er poolens, bit for bit: samme oppgave med samme frø og N
      // rett i runZoneTasks gir samme antall. Hver fordeling går opp.
      const regn = await s1.evaluate(async () => {
        const N = 300, r = await grunnlagRegn(N);
        const {P0, G0, F0, open, openMatches, oddsOverride, scenarioKey} = buildQaOpen();
        const utvalg = grunnlagOppgaver(openMatches).filter((t, i, a) => t.id === 'base' || t.id.endsWith(':U') || i === a.length - 1).slice(0, 3);
        const res = await runZoneTasks({mu: MODEL.mu, H: MODEL.H, k: FORM_K,
          att: Array.from(LIVE.att), con: Array.from(LIVE.con), ha: Array.from(LIVE.ha), hc: Array.from(LIVE.hc),
          P0: Array.from(P0), G0: Array.from(G0), F0: Array.from(F0), open, oddsOverride,
          N, ti: 3, zone: QA_KEY_ZONES[1], seed: hashStr(scenarioKey + '|impact'), wantAll: true}, utvalg, null, 'grunnlag-test');
        const n = TEAMS.length;
        const like = utvalg.every(t => JSON.stringify(res[t.id].pos.map(p => Math.round(p * N))) === JSON.stringify(r.utfall[t.id]));
        const summer = r.oppgaver.every(([id]) => { const u = r.utfall[id];
          for (let i = 0; i < n; i++) { let a = 0, b = 0; for (let j = 0; j < n; j++) { a += u[i * n + j]; b += u[j * n + i]; } if (a !== N || b !== N) return false; }
          return true; });
        let avvist = null;
        const m = matches.find(x => x.hg == null); m.hg = 2; m.ag = 1;
        try { await grunnlagRegn(N); } catch (e) { avvist = e.message; } finally { m.hg = null; m.ag = null; }
        return {like, summer, utvalg: utvalg.map(t => t.id), avtrykk: r.fingeravtrykk === await grunnlagAvtrykk(N), avvist, n: r.oppgaver.length};
      });
      check(`${liga}: grunnlagRegn gir poolens tall bit for bit (${regn.utvalg.join(', ')}), fordelingene går opp, og avtrykket er sidens`,
        regn.like && regn.summer && regn.avtrykk, JSON.stringify(regn));
      check(`${liga}: grunnlagRegn nekter å regne med et resultat fylt inn`, /resultater er fylt inn/.test(regn.avvist || ''), String(regn.avvist));
      await s1.close();
    }

    // Skriptet (scripts/lag_grunnlag.js) i en kopi av repoet, med liten N:
    // filen skrives med sidens avtrykk og én linje per oppgave; med et avtrykk
    // som er ulikt fra lasting til lasting, eller en side som ikke finnes,
    // skrives ingenting og den forrige filen står.
    setGroup('Grunnlagsfilen: skriptet skriver bare når alt stemmer');
    if (!live) {
      const os = require('os'), {execFileSync, spawnSync} = require('child_process');
      const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'grunnlag-'));
      let tmpServer = null;
      try {
        for (const f of execFileSync('git', ['ls-files', '-co', '--exclude-standard', '-z'], {cwd: ROOT}).toString().split('\0').filter(Boolean)) {
          const fra = path.join(ROOT, f);
          if (!fs.existsSync(fra) || fs.statSync(fra).isDirectory()) continue;
          fs.mkdirSync(path.dirname(path.join(TMP, f)), {recursive: true});
          fs.copyFileSync(fra, path.join(TMP, f));
        }
        const pp = require.resolve('puppeteer-core');
        const nodePath = [pp.slice(0, pp.lastIndexOf(`${path.sep}puppeteer-core${path.sep}`)), process.env.NODE_PATH].filter(Boolean).join(path.delimiter);
        const kjor = (...a) => spawnSync(process.execPath, [path.join(TMP, 'scripts', 'lag_grunnlag.js'), ...a],
          {cwd: TMP, encoding: 'utf8', timeout: 300000, env: {...process.env, NODE_PATH: nodePath}});
        const FIL = path.join(TMP, 'obos', 'data', 'grunnlag.json');
        const r = kjor('obos', '--n', '300', '--inndata', 'abc123');
        const tekst = fs.existsSync(FIL) ? fs.readFileSync(FIL, 'utf8') : '';
        const g = tekst ? JSON.parse(tekst) : {};
        tmpServer = await serve(TMP);
        const pg = await open(1400, 900, `http://127.0.0.1:${tmpServer.address().port}/obos/`);
        const sidens = await pg.evaluate(() => grunnlagAvtrykk(300)), sidensN = await pg.evaluate(() => grunnlagAvtrykk());
        const oppg = await pg.evaluate(() => grunnlagOppgaver(buildQaOpen().openMatches).map(t => [t.id, t.idx, t.score]));
        await pg.close();
        check('lag_grunnlag.js skriver filen med sidens avtrykk for N = 300, inndata og alle oppgavene',
          r.status === 0 && g.versjon === 2 && g.side === 'obos' && g.sesonger === 300 && g.fingeravtrykk === sidens && g.inndata === 'abc123'
            && JSON.stringify(g.oppgaver) === JSON.stringify(oppg) && Object.keys(g.utfall || {}).length === oppg.length,
          `kode ${r.status}: ${(r.stdout + r.stderr).slice(-400)}`);
        check('... og siden godtar den ikke som en fil for N = 100 000 (annet avtrykk)', g.fingeravtrykk !== sidensN, '');
        const utfallLinjer = (tekst.split(' "utfall": {\n')[1] || '').split('\n }')[0].split('\n');
        check('... med én linje per oppgave', utfallLinjer.filter(l => /^  "[^"]+": \[/.test(l)).length === oppg.length && utfallLinjer.length === oppg.length,
          `${utfallLinjer.length} linjer under "utfall", ${oppg.length} oppgaver`);
        check('... og innsiktsblokken med én linje per lag, i lagenes rekkefølge',
          !!g.innsikt && Array.isArray(g.innsikt.lag) && g.innsikt.lag.length === g.lag.length
            && tekst.split('\n').filter(l => /^   \{"fra":/.test(l)).length === g.lag.length
            && g.innsikt.lag.every(x => x.poeng.reduce((s, v) => s + v, 0) === 300), JSON.stringify(g.innsikt || null).slice(0, 200));
        // Avtrykk som er ulikt fra lasting til lasting: kontrollen med en ny
        // lasting skal stoppe skrivingen.
        const sideFil = path.join(TMP, 'obos', 'index.html'), sideTekst = fs.readFileSync(sideFil, 'utf8');
        fs.writeFileSync(sideFil, sideTekst.replace('function grunnlagEkstra(){ return null; }',
          'const EKSTRA_TILF = Math.random(); function grunnlagEkstra(){ return EKSTRA_TILF; }'));
        const foer = fs.readFileSync(FIL, 'utf8');
        const r2 = kjor('obos', '--n', '300');
        check('et avtrykk som endres fra lasting til lasting: ingen fil skrives, den forrige står',
          r2.status === 1 && fs.readFileSync(FIL, 'utf8') === foer && /IKKE skrevet.*annet avtrykk/s.test(r2.stderr) && !fs.existsSync(FIL + '.tmp'),
          `kode ${r2.status}: ${r2.stderr.slice(-300)}`);
        fs.writeFileSync(sideFil, sideTekst);
        const r3 = kjor('finnes-ikke', '--n', '300', '--ut', 'obos/data');
        check('en side som ikke finnes: exit 1, den forrige filen står', r3.status === 1 && fs.readFileSync(FIL, 'utf8') === foer,
          `kode ${r3.status}: ${r3.stderr.slice(-300)}`);
        const KM = path.join(TMP, 'obos', 'data', 'keymatch.json');
        const kmFoer = fs.existsSync(KM) ? fs.readFileSync(KM, 'utf8') : null;
        check('i testmodus (--n) prøves ikke filen på siden, og banneret skrives ikke',
          /Testmodus/.test(r.stdout) && (fs.existsSync(KM) ? fs.readFileSync(KM, 'utf8') : null) === kmFoer, r.stdout.slice(-300));

        // Hele veien, billig: siden i kopien regner med GRUNNLAG_N = 300.
        // Filen prøves på siden med den nye filen, og banneret skrives fra den.
        const N300 = sideTekst.replace('const GRUNNLAG_VERSJON = 2, GRUNNLAG_N = 100000;', 'const GRUNNLAG_VERSJON = 2, GRUNNLAG_N = 300;');
        fs.writeFileSync(sideFil, N300);
        const r4 = kjor('obos', '--inndata', 'def456');
        const g4 = JSON.parse(fs.readFileSync(FIL, 'utf8')), km4 = fs.existsSync(KM) ? JSON.parse(fs.readFileSync(KM, 'utf8')) : null;
        check('siden godtar den nye filen, og banneret (keymatch.json) skrives fra den, med filens sesonger',
          r4.status === 0 && g4.sesonger === 300 && g4.inndata === 'def456' && !!km4 && km4.sesonger === 300 && /keymatch\.json/.test(r4.stdout),
          `kode ${r4.status}: ${(r4.stdout + r4.stderr).slice(-400)}`);
        // Banneret er svaret: siden med de to filene kårer det samme, og viser
        // banneret som det står.
        GRUNNLAG_MODUS = {};
        const pb = await open(1400, 900, `http://127.0.0.1:${tmpServer.address().port}/obos/`);
        await pb.waitForFunction('GRUNNLAG_STATUS!=="venter"', {timeout: 60000, polling: 50});
        const b4 = await pb.evaluate(async () => ({status: GRUNNLAG_STATUS, key: keymatchFra(await qaKeyRoundData()),
          vist: document.getElementById('qaHighlight') ? document.getElementById('qaHighlight').textContent : null, gammelt: qaKeyBannerStale()}));
        await pb.close();
        GRUNNLAG_MODUS = null;
        const felt = k => k && JSON.stringify([k.banner, k.round, k.match, k.zone, k.teams, k.sesonger, k.grense]);
        check('svaret på siden med filen kårer det samme som banneret, og banneret vises som det står',
          b4.status === 'i bruk' && felt(b4.key) === felt(km4) && (b4.gammelt || b4.vist === km4.banner), JSON.stringify({b4, km4}).slice(0, 700));
        // Godtar ikke siden filen, skrives verken filen eller banneret.
        const g4tekst = fs.readFileSync(FIL, 'utf8'), km4tekst = fs.readFileSync(KM, 'utf8');
        fs.writeFileSync(sideFil, N300.replace("if(avtrykk!==g.fingeravtrykk){ GRUNNLAG_STATUS='feil avtrykk'; return; }",
          "if(true){ GRUNNLAG_STATUS='feil avtrykk'; return; }"));
        const r5 = kjor('obos', '--inndata', 'ghi789');
        check('godtar ikke siden den nye filen: exit 1, og verken filen eller banneret er endret',
          r5.status === 1 && /godtok ikke den nye filen/.test(r5.stderr) && fs.readFileSync(FIL, 'utf8') === g4tekst && fs.readFileSync(KM, 'utf8') === km4tekst,
          `kode ${r5.status}: ${r5.stderr.slice(-300)}`);
        fs.writeFileSync(sideFil, sideTekst);
      } finally {
        if (tmpServer) tmpServer.close();
        fs.rmSync(TMP, {recursive: true, force: true});
      }
    }

    // ---- Grunnlagsfilen på siden (del 2, steg 3) ----
    // Siden henter grunnlag.json samtidig med de andre datafilene, venter
    // ikke på den, og bytter til filens tall når den er lastet og avtrykket
    // stemmer. Da kommer tabellen og svarene fra filen, uten simulering, også
    // for en annen sone enn lagets egen (qaWhyZoneOverride). Med et resultat
    // fylt inn, feil avtrykk, en ødelagt eller manglende fil regner siden selv.
    setGroup('Grunnlagsfilen på siden: tabellen og svarene fra filen');
    if (!live) {
      const {execFileSync, spawnSync} = require('child_process'), os = require('os');
      // Siden med tellere for alt som sendes til Workerne (modus 'tabell' er
      // tabellsimuleringen, 'zoneTask' oppgavene i poolen).
      const aapneMaalt = async url => {
        const pg = await browser.newPage();
        pg.on('pageerror', e => errors.push(`${url}: ${e.message}`));
        await pg.evaluateOnNewDocument(() => {
          // Hver melding til og fra en Worker, med Workerens nummer og tidspunkt,
          // og hvor mange Workere som er stoppet (avbrutt innsikt).
          window.__poster = []; window.__svar = []; window.__avsluttet = 0;
          const W = window.Worker; let nr = 0;
          window.Worker = function (u, o) { const w = new W(u, o), id = ++nr, post = w.postMessage.bind(w), stopp = w.terminate.bind(w);
            w.postMessage = m => { window.__poster.push({mode: (m && m.mode) || 'tabell', N: m && m.N, w: id, t: performance.now()}); return post(m); };
            w.addEventListener('message', e => window.__svar.push({mode: e.data && e.data.mode, w: id, t: performance.now()}));
            w.terminate = () => { window.__avsluttet++; return stopp(); };
            return w; };
        });
        await pg.setViewport({width: 1400, height: 900});
        await pg.goto(url, {waitUntil: 'domcontentloaded'});
        return pg;
      };
      const ferdig = pg => pg.waitForFunction('typeof GRUNNLAG_STATUS!=="undefined" && GRUNNLAG_STATUS!=="venter" && lastMC && lastMCFinal',
        {timeout: 120000, polling: 50});
      const lagMedSone = `TEAMS.find(t => { const z = qaTargetZone(t); return z && !qaSettled(t, z) && z.pct > 0.05 && z.pct < 0.95; }) || TEAMS[0]`;
      // Filen for hver side: den i repoet når siden godtar den (samme data som
      // da CI regnet den), ellers regnet på nytt med lag_grunnlag.js i en kopi.
      const SIDENE = ['eliteserien', 'obos', 'elo-test'];
      const utMappe = liga => liga === 'elo-test' ? 'elo-test/emodell' : `${liga}/data`;
      const filer = {};
      for (const liga of SIDENE) {
        GRUNNLAG_MODUS = {};
        const pr = await aapneMaalt(base.replace('/eliteserien/', `/${liga}/`));
        await ferdig(pr);
        const st = await pr.evaluate(() => GRUNNLAG_STATUS);
        await pr.close();
        if (st === 'i bruk') { filer[liga] = fs.readFileSync(path.join(ROOT, utMappe(liga), 'grunnlag.json'), 'utf8'); continue; }
        const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'grunnlag-side-'));
        try {
          for (const f of execFileSync('git', ['ls-files', '-co', '--exclude-standard', '-z'], {cwd: ROOT}).toString().split('\0').filter(Boolean)) {
            const fra = path.join(ROOT, f);
            if (!fs.existsSync(fra) || fs.statSync(fra).isDirectory()) continue;
            fs.mkdirSync(path.dirname(path.join(TMP, f)), {recursive: true});
            fs.copyFileSync(fra, path.join(TMP, f));
          }
          const pp = require.resolve('puppeteer-core');
          const r = spawnSync(process.execPath, [path.join(TMP, 'scripts', 'lag_grunnlag.js'), liga, '--ut', utMappe(liga)], {cwd: TMP, encoding: 'utf8', timeout: 900000,
            env: {...process.env, NODE_PATH: [pp.slice(0, pp.lastIndexOf(`${path.sep}puppeteer-core${path.sep}`)), process.env.NODE_PATH].filter(Boolean).join(path.delimiter)}});
          console.log(`    (${liga}: filen i repoet ble ikke godtatt (${st}); regnet på nytt: ${(r.stdout || '').trim().split('\n')[0]})`);
          filer[liga] = fs.readFileSync(path.join(TMP, utMappe(liga), 'grunnlag.json'), 'utf8');
        } finally { fs.rmSync(TMP, {recursive: true, force: true}); }
      }

      for (const liga of SIDENE) {
        const url = base.replace('/eliteserien/', `/${liga}/`), g = JSON.parse(filer[liga]);
        GRUNNLAG_MODUS = {innhold: {[liga]: filer[liga]}};
        const pg = await aapneMaalt(url);
        await ferdig(pg);
        const tab = await pg.evaluate(g => {
          const n = TEAMS.length, N = g.sesonger, fra = (t, i) => g.utfall.base.slice(i * n, i * n + n).map(c => c / N);
          const celler = [...document.querySelectorAll('#tbl tbody tr')].map(tr => {
            const d = lastMC[tr.dataset.team], v = zoneSum(d, 'gull');
            return tr.querySelector('td.gull').textContent === (v === 0 ? '–' : pctTxt(v)); });
          return {status: GRUNNLAG_STATUS, N: lastMCN,
            tabell: TEAMS.every((t, i) => JSON.stringify(lastMC[t]) === JSON.stringify(fra(t, i))),
            basis: TEAMS.every((t, i) => JSON.stringify(BASE_MC[t]) === JSON.stringify(fra(t, i))),
            celler: celler.length === n && celler.every(Boolean)};
        }, g);
        check(`${liga}: med gyldig fil og uten scenario er tabellen filens (100 000 sesonger), også grunnlaget for delingsteksten`,
          tab.status === 'i bruk' && tab.N === 100000 && tab.tabell && tab.basis && tab.celler, JSON.stringify(tab));

        // Svarene fra filen: ingen oppgaver til poolen og ingen ny
        // tabellsimulering. Kortet "Neste kamp" for et valgt lag også.
        const sv = await pg.evaluate(async lagKode => {
          const lag = eval(lagKode), z0 = __poster.filter(p => p.mode === 'zoneTask').length, t0 = __poster.filter(p => p.mode === 'tabell').length;
          const tekster = {heie: await qaCheerFor(lag), neste: await qaNextMatch(lag), betyr: await qaKeyMatches(lag), runde: await qaKeyRound()};
          const kd = await qaKeyRoundData();
          const sel = document.getElementById('teamSelect'); sel.value = lag; sel.dispatchEvent(new Event('change'));
          await new Promise(r => setTimeout(r, 600));
          const kort = document.getElementById('nmImpact');
          return {lag, tekster, sesonger: kd.sesonger, kort: kort && !kort.hidden ? kort.textContent : null,
                  zoneTask: __poster.filter(p => p.mode === 'zoneTask').length - z0, tabell: __poster.filter(p => p.mode === 'tabell').length - t0};
        }, lagMedSone);
        const kg = await pg.evaluate(async () => { const d = await qaKeyRoundData();
          return {sesonger: d.sesonger, grense: d.grense, CI: QA_KEY_CLOSE_CI, holder: d.close.every(x => x.total >= d.best.total * QA_KEY_CLOSE_CI)}; });
        check(`${liga}: rundens viktigste kamp fra filen bruker 100 000 sesonger og den strammere grensa (0,93)`,
          kg.sesonger === 100000 && kg.grense === 0.93 && kg.CI === 0.93 && kg.holder, JSON.stringify(kg));
        check(`${liga}: svarene og kortet kommer fra filen, uten simulering (0 oppgaver til poolen, ingen ny tabellsimulering), for ${sv.lag}`,
          sv.zoneTask === 0 && sv.tabell === 0 && sv.sesonger === 100000 && Object.values(sv.tekster).every(t => t && t.length > 20) && !!sv.kort,
          JSON.stringify({zoneTask: sv.zoneTask, tabell: sv.tabell, sesonger: sv.sesonger, kort: sv.kort}));

        // Innsiktssvarene ("Hvorfor har ...?", "Hva må ... gjøre?", "Når kan
        // det være avgjort?", "Hvem kjemper ... mot?") kommer fra filens blokk,
        // uten kjøring i Workeren. Blokken er bit for bit det siden regner selv
        // med samme frø og N, og suksessen i den går opp mot tabellen (de
        // samme sesongene).
        const ins = await pg.evaluate(async (lagKode, g) => {
          const lag = eval(lagKode), tell = () => __poster.filter(p => p.mode === 'insightsAlle').length, i0 = tell();
          const tekster = {why: await qaWhy(lag), howto: await qaHowTo(lag), decided: await qaWhenDecided(lag), rivals: await qaRivals(lag)};
          const fraFil = tell() - i0;
          const live = await innsiktKjor(innsiktPayload(g.sesonger));
          const bitlik = JSON.stringify(innsiktPakk(live)) === JSON.stringify(g.innsikt);
          const n = TEAMS.length, soner = innsiktSoner();
          const motTabell = TEAMS.every((t, ti) => soner.every((z, zi) => {
            const lo = z.dir === 'front' ? z.lo : 1, hi = z.dir === 'front' ? z.hi : z.boundary;
            let tab = 0; for (let k = lo; k <= hi; k++) tab += g.utfall.base[ti * n + k - 1];
            return g.innsikt.lag[ti].suksess[zi].reduce((s, v) => s + v, 0) === tab; }));
          return {lag, fraFil, bitlik, motTabell, N: GRUNNLAG.innsikt.N, tekster};
        }, lagMedSone, g);
        check(`${liga}: innsiktssvarene kommer fra filens blokk (100 000 sesonger), uten kjøring i Workeren, for ${ins.lag}`,
          ins.fraFil === 0 && ins.N === 100000 && Object.values(ins.tekster).every(t => t && t.length > 20), JSON.stringify(ins).slice(0, 600));
        check(`${liga}: blokken er bit for bit det siden regner selv med samme frø og N, og suksessen går opp mot tabellen`,
          ins.bitlik && ins.motTabell, JSON.stringify({bitlik: ins.bitlik, motTabell: ins.motTabell}));

        // Teksten er bygget av de samme funksjonene: med poolen byttet ut med
        // en som gir filens tall, og filen slått av, blir teksten den samme.
        const tk = await pg.evaluate(async lag => {
          const kjor = async () => ({heie: await qaCheerFor(lag), neste: await qaNextMatch(lag), betyr: await qaKeyMatches(lag), runde: await qaKeyRound()});
          const medFil = await kjor(), G = GRUNNLAG, ekte = runZoneTasks;
          // Samme tall som filen, også hvor mange sesonger de bygger på (som
          // poolen oppgir sin N): da velger svaret samme grense.
          runZoneTasks = (payload, tasks) => { GRUNNLAG = G; try { const r = grunnlagSvar(payload, tasks, 'test');
            Object.defineProperty(r, 'sesonger', {value: G.N}); return Promise.resolve(r); } finally { GRUNNLAG = null; } };
          GRUNNLAG = null;
          let utenFil;
          try { utenFil = await kjor(); } finally { runZoneTasks = ekte; GRUNNLAG = G; }
          return {medFil, utenFil};
        }, sv.lag);
        check(`${liga}: teksten i svarene er den samme med filen og med poolen som gir samme tall`,
          JSON.stringify(tk.medFil) === JSON.stringify(tk.utenFil), JSON.stringify(tk).slice(0, 600));

        // Filens tall mot siden selv: bit for bit med samme frø og N, og
        // innenfor 3 standardfeil mot en regning med annet frø og N = 20 000,
        // for en kamp i neste runde (Brann mot Viking når den er der): H, U, B
        // og utgangspunktet, for de to lagene og ett til.
        const st = await pg.evaluate(async g => {
          const n = TEAMS.length, N = g.sesonger;
          const {P0, G0, F0, open, openMatches, oddsOverride, scenarioKey} = buildQaOpen();
          const nr = qaNextRoundMatches(openMatches), m = nr.list.find(x => x.home === 'Brann' && x.away === 'Viking') || nr.list[0], idx = openMatches.indexOf(m);
          const tasks = grunnlagOppgaver(openMatches).filter(t => t.id === 'base' || t.idx === idx);
          const payload = (N, seed) => ({mu: MODEL.mu, H: MODEL.H, k: FORM_K, att: Array.from(LIVE.att), con: Array.from(LIVE.con),
            ha: Array.from(LIVE.ha), hc: Array.from(LIVE.hc), P0: Array.from(P0), G0: Array.from(G0), F0: Array.from(F0), open, oddsOverride,
            N, ti: 0, zone: QA_KEY_ZONES[0], seed, wantAll: true});
          const utvalg = tasks.filter(t => t.id === 'base' || t.id.endsWith(':U'));
          const samme = await runZoneTasks(payload(N, hashStr(scenarioKey + '|impact')), utvalg, null, 'grunnlag-test');
          const bitlik = utvalg.every(t => samme[t.id].pos.every((p, i) => Math.round(p * N) === g.utfall[t.id][i]));
          const NL = 20000, annen = await runZoneTasks(payload(NL, hashStr(scenarioKey + '|kontroll')), tasks, null, 'grunnlag-test');
          const tredje = TEAMS.map((t, i) => i).filter(i => i !== TI[m.home] && i !== TI[m.away] && qaTargetZone(TEAMS[i]))
            .sort((a, b) => Math.abs(qaTargetZone(TEAMS[a]).pct - 0.5) - Math.abs(qaTargetZone(TEAMS[b]).pct - 0.5))[0];
          const rader = [];
          for (const t of tasks) for (const ti of [TI[m.home], TI[m.away], tredje]) {
            const zone = qaTargetZone(TEAMS[ti]); if (!zone) continue;
            const pf = qaZoneFromPos(g.utfall[t.id].map(c => c / N), n, zone)[ti], pl = qaZoneFromPos(annen[t.id].pos, n, zone)[ti];
            const pp = (pf * N + pl * NL) / (N + NL), se = Math.sqrt(pp * (1 - pp) * (1 / N + 1 / NL));
            rader.push({id: t.id, lag: TEAMS[ti], sone: zone.key, fil: +pf.toFixed(4), live: +pl.toFixed(4), z: se > 0 ? +(Math.abs(pf - pl) / se).toFixed(2) : (pf === pl ? 0 : 99)});
          }
          return {kamp: `${m.home} mot ${m.away}`, bitlik, utvalg: utvalg.map(t => t.id), rader};
        }, g);
        check(`${liga}: filen er bit for bit det siden regner selv med samme frø og N (${st.utvalg.join(', ')})`, st.bitlik, JSON.stringify(st.utvalg));
        check(`${liga}: filen og siden selv med annet frø (N = 20 000) ligger innenfor 3 standardfeil: ${st.kamp}, ${st.rader.length} tall, største ${Math.max(...st.rader.map(r => r.z))} SE`,
          st.rader.length >= 9 && st.rader.every(r => r.z <= 3), JSON.stringify(st.rader.filter(r => r.z > 3)));

        // Et resultat fylt inn: siden regner selv, innsikten med like mange
        // sesonger som tabellen, én gang for alle spørsmålene i scenarioet.
        // Nullstill: filen igjen, uten ny simulering. En annen sone
        // (qaWhyZoneOverride): også fra filen.
        const sc = await pg.evaluate(async lagKode => {
          const lag = eval(lagKode), vent = f => new Promise(r => { const i = setInterval(() => { if (f()) { clearInterval(i); r(); } }, 20); });
          // Som vent, men gir opp etter ms (så en manglende forhåndsregning feiler i stedet for å henge).
          const ventMaks = (f, ms) => new Promise(r => { const s = performance.now(), i = setInterval(() => { if (f() || performance.now() - s > ms) { clearInterval(i); r(!!f()); } }, 20); });
          const tell = modus => __poster.filter(p => p.mode === modus).length;
          const ferdigFor = () => lastMCFinal && lastMCScenarioKey !== '' && lastMCScenarioKey === qaScenarioKey();
          // Med færre enn fire kjerner starter innsikten når tabellen er ferdig
          // (INNSIKT_SAMTIDIG_KJERNER); antall kjerner settes her, så testen ikke
          // avhenger av maskinen den kjører på.
          const kjerner = k => Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => k, configurable: true});
          kjerner(2);
          const m = matches.find(x => x.hg == null), t0 = tell('tabell'), z0 = tell('zoneTask'), i0 = tell('insightsAlle');
          m.hg = 2; m.ag = 0; mcStraks = true; render();
          await vent(ferdigFor);
          // Innsikten regnes i bakgrunnen uten at noen spør, når poolen er ledig
          // etter tabellen (kortet "Neste kamp" regnes da), i sin egen Worker.
          const startet = await ventMaks(() => tell('insightsAlle') > i0, 20000);
          const forhand = __poster.filter(p => p.mode === 'insightsAlle').slice(-1)[0] || {};
          const zoneFoer = __poster.filter(p => p.mode === 'zoneTask' && p.t < forhand.t).length,
                zoneSvarFoer = __svar.filter(s => s.mode === 'zoneTask' && s.t <= forhand.t).length;
          const innsiktW = new Set(__poster.filter(p => p.mode === 'insightsAlle').map(p => p.w));
          const bareInnsikt = __poster.filter(p => innsiktW.has(p.w)).every(p => p.mode === 'insightsAlle');
          await qaCheerFor(lag);
          const med = {tabell: tell('tabell') - t0, zoneTask: tell('zoneTask') - z0, N: lastMCN, MC_N};
          await qaHowTo(lag); await qaWhy(TEAMS.find(t => t !== lag)); await qaRivals(lag); await qaWhenDecided(lag);
          const innsikt = {startet, N: forhand.N, antall: tell('insightsAlle') - i0, poolLedig: zoneFoer === zoneSvarFoer, zoneFoer, zoneSvarFoer, bareInnsikt};
          // Et nytt resultat mens innsikten for det forrige regnes: den gamle
          // regningen stoppes, og svaret gjelder det nye scenarioet.
          const a0 = __avsluttet, j0 = tell('insightsAlle'), m2 = matches.find(x => x.hg == null);
          m2.hg = 1; m2.ag = 1; mcStraks = true; render();
          await vent(ferdigFor);
          const startet2 = await ventMaks(() => tell('insightsAlle') > j0, 20000);
          const m3 = matches.find(x => x.hg == null);
          m3.hg = 0; m3.ag = 3; mcStraks = true; render();
          const avbrutt = __avsluttet - a0;
          await vent(ferdigFor);
          await ventMaks(() => tell('insightsAlle') > j0 + 1, 20000);
          const A = await innsiktData(), P0naa = Array.from(buildQaOpen().P0);
          const j1 = tell('insightsAlle'); await qaHowTo(lag);
          const avbrudd = {startet2, avbrutt, kjoringer: tell('insightsAlle') - j0, gjelderNye: JSON.stringify(A.P0) === JSON.stringify(P0naa), etterpa: tell('insightsAlle') - j1};
          // Med fire kjerner starter innsikten samtidig med tabellen: rett etter
          // at tabellen er sendt, før den er ferdig, én gang for scenarioet.
          kjerner(4);
          const k0 = __poster.length, m4 = matches.find(x => x.hg == null);
          m4.hg = 3; m4.ag = 3; mcStraks = true; render();
          await vent(ferdigFor);
          const nye = __poster.slice(k0), tabP = nye.find(p => p.mode === 'tabell'), innP = nye.filter(p => p.mode === 'insightsAlle');
          const tabSlutt = tabP ? __svar.filter(s => s.mode === 'prob' && s.t > tabP.t).slice(-1)[0] : null;
          const j2 = tell('insightsAlle'); await qaHowTo(lag);
          const fire = {kjerner: navigator.hardwareConcurrency, jobber: innP.length, N: innP[0] && innP[0].N,
            etterTabellen: !!tabP && !!innP[0] && innP[0].t >= tabP.t, forTabellenErFerdig: !!innP[0] && !!tabSlutt && innP[0].t < tabSlutt.t,
            gjenbruk: tell('insightsAlle') - j2 === 0};
          delete navigator.hardwareConcurrency;
          m2.hg = null; m2.ag = null; m3.hg = null; m3.ag = null; m4.hg = null; m4.ag = null;
          m.hg = null; m.ag = null; mcStraks = true; render();
          await vent(() => lastMCScenarioKey === '' && lastMCFinal);
          const t1 = tell('tabell'), g = GRUNNLAG.fil, n = TEAMS.length;
          const tilbake = lastMCN === g.sesonger && TEAMS.every((t, i) => lastMC[t].every((v, k) => v === g.utfall.base[i * n + k] / g.sesonger));
          await new Promise(r => setTimeout(r, 400));
          // Et lag og en annen sone enn lagets egen som ikke er avgjort
          // (ellers svarer spørsmålet med en fast tekst uten å regne).
          let lagA = null, andre = null;
          for (const t of TEAMS) for (const k of Object.keys(LEAGUE.zones)) {
            const z = !lagA && qaTargetZone(t) && k !== qaTargetZone(t).key && qaZoneByKey(t, k);
            if (z && !qaSettled(t, z) && z.pct > 0.02 && z.pct < 0.98) { lagA = t; andre = k; }
          }
          const iT = tell('insightsAlle'); await qaHowTo(lag); const utenScenario = tell('insightsAlle') - iT;
          const z1 = tell('zoneTask'), i2 = tell('insightsAlle');
          qaWhyZoneOverride = andre;
          const nesteAnnen = await qaNextMatch(lagA), hvorforAnnen = await qaWhy(lagA);
          qaWhyZoneOverride = null;
          const zN = tell('zoneTask') - z1, iA = tell('insightsAlle') - i2; await qaNextMatch(lagA);
          return {med, innsikt, avbrudd, fire, utenScenario, tilbake, nyTabell: tell('tabell') - t1, annenSone: zN, annenInnsikt: iA,
                  egenSone: tell('zoneTask') - z1 - zN, lagA, andre, pctAnnen: pctTxt(qaZoneByKey(lagA, andre).pct), hvorforAnnen, nesteAnnen};
        }, lagMedSone);
        check(`${liga}: med ett resultat fylt inn regner siden selv (tabellsimulering og oppgaver til poolen)`,
          sc.med.tabell >= 1 && sc.med.zoneTask > 0 && sc.med.N === sc.med.MC_N, JSON.stringify(sc.med));
        check(`${liga}: med to kjerner regnes innsikten i bakgrunnen (uten at noen spør) når tabellen er ferdig og poolen ledig, i sin egen Worker`,
          sc.innsikt.startet && sc.innsikt.poolLedig && sc.innsikt.zoneFoer > 0 && sc.innsikt.bareInnsikt, JSON.stringify(sc.innsikt));
        check(`${liga}: innsikten regnes én gang med MC_N sesonger, og spørsmålene etterpå gjenbruker den`,
          sc.innsikt.N === sc.med.MC_N && sc.innsikt.antall === 1, JSON.stringify(sc.innsikt));
        check(`${liga}: et nytt resultat mens innsikten regnes, stopper den gamle regningen, og svaret gjelder det nye scenarioet`,
          sc.avbrudd.startet2 && sc.avbrudd.avbrutt >= 1 && sc.avbrudd.kjoringer === 2 && sc.avbrudd.gjelderNye && sc.avbrudd.etterpa === 0, JSON.stringify(sc.avbrudd));
        check(`${liga}: med fire kjerner starter innsikten samtidig med tabellen (etter at tabellen er sendt, før den er ferdig), én gang, og svarene gjenbruker den`,
          sc.fire.kjerner === 4 && sc.fire.jobber === 1 && sc.fire.N === sc.med.MC_N && sc.fire.etterTabellen && sc.fire.forTabellenErFerdig && sc.fire.gjenbruk,
          JSON.stringify(sc.fire));
        check(`${liga}: tømmes scenarioet, gjelder filen igjen, uten ny simulering`, sc.tilbake && sc.nyTabell === 0 && sc.utenScenario === 0, JSON.stringify(sc));
        check(`${liga}: svar for en annen sone enn lagets egen (qaWhyZoneOverride) kommer fra filen, med den sonens sjanse (${sc.lagA}, ${sc.andre})`,
          !!sc.andre && sc.annenSone === 0 && sc.annenInnsikt === 0 && sc.egenSone === 0 && sc.hvorforAnnen.includes(` ${sc.pctAnnen} av dem`),
          JSON.stringify(sc).slice(0, 900));
        await pg.close();

        // Filen gjelder ikke: siden regner selv, uten JS-feil.
        const feil0 = errors.length;
        const tilfeller = {
          'feil avtrykk': JSON.stringify({...g, fingeravtrykk: g.fingeravtrykk.replace(/.$/, c => c === '0' ? '1' : '0')}),
          'ugyldig': JSON.stringify({...g, sesonger: 1000}),
          'mangler (ødelagt JSON)': filer[liga].slice(0, 5000),
          'mangler (404)': null,
        };
        const utfall = {};
        for (const [navn, inn] of Object.entries(tilfeller)) {
          GRUNNLAG_MODUS = inn == null ? null : {innhold: {[liga]: inn}};
          const pf = await aapneMaalt(url);
          await ferdig(pf);
          utfall[navn] = await pf.evaluate(async lagKode => {
            const lag = eval(lagKode), z0 = __poster.filter(p => p.mode === 'zoneTask').length;
            await qaCheerFor(lag);
            return {status: GRUNNLAG_STATUS, N: lastMCN, MC_N, zoneTask: __poster.filter(p => p.mode === 'zoneTask').length - z0};
          }, lagMedSone);
          await pf.close();
        }
        check(`${liga}: feil avtrykk, feil N, ødelagt eller manglende fil: siden regner selv, uten JS-feil`,
          Object.entries(utfall).every(([navn, u]) => navn.startsWith(u.status) && u.N === u.MC_N && u.zoneTask > 0) && errors.length === feil0,
          JSON.stringify(utfall) + errors.slice(feil0).join('; '));

        // Filen kommer sent (2,5 s): tabellen og et svar som står, regnes
        // først av siden selv, og byttes til filens når den kommer.
        GRUNNLAG_MODUS = {innhold: {[liga]: filer[liga]}, forsinkelse: 2500};
        const ps = await aapneMaalt(url);
        await ps.waitForFunction('typeof lastMC!=="undefined" && lastMC && lastMCFinal', {timeout: 120000, polling: 50});
        const sen = await ps.evaluate(async lagKode => {
          const lag = eval(lagKode), foer = {status: GRUNNLAG_STATUS, N: lastMCN};
          const sel = document.getElementById('teamSelect'); sel.value = lag; sel.dispatchEvent(new Event('change'));
          runQaQuestion('cheer', false, true);
          const vent = f => new Promise(r => { const i = setInterval(() => { if (f()) { clearInterval(i); r(); } }, 20); });
          const svarTekst = () => { const el = document.getElementById('qaAnswer'); return el && !el.className.includes('loading') ? el.textContent : null; };
          await vent(() => svarTekst());
          const svarFoer = svarTekst();
          await vent(() => GRUNNLAG_STATUS !== 'venter');
          await vent(() => { const el = document.getElementById('qaAnswer'); return el && !el.className.includes('loading') && qaAnswerKey === qaStateKey(); });
          await new Promise(r => setTimeout(r, 300));
          return {foer, etter: {status: GRUNNLAG_STATUS, N: lastMCN}, svarFoer, svarEtter: svarTekst(), fraFil: await qaCheerFor(lag)};
        }, lagMedSone);
        await ps.close();
        check(`${liga}: kommer filen sent, regner siden selv først, og bytter tabellen og svaret som står til filens når den kommer`,
          sen.foer.status === 'venter' && sen.foer.N === 10000 && sen.etter.status === 'i bruk' && sen.etter.N === 100000
            && sen.svarEtter === sen.fraFil, JSON.stringify(sen).slice(0, 800));
      }

      // Tid til første prosenter i tabellen: ikke lengre med filen enn uten,
      // heller ikke når den er treg. Median av fem lastinger per tilfelle.
      const tidTil = async (liga, modus) => {
        const tider = [];
        for (let i = 0; i < 5; i++) {
          GRUNNLAG_MODUS = modus;
          const pg = await browser.newPage();
          await pg.setViewport({width: 1400, height: 900});
          const t0 = Date.now();
          await pg.goto(base.replace('/eliteserien/', `/${liga}/`), {waitUntil: 'domcontentloaded'});
          await pg.waitForFunction(() => { const c = document.querySelector('#tbl tbody tr td.gull'); return c && c.textContent.trim() !== ''; }, {timeout: 60000, polling: 10});
          tider.push(Date.now() - t0);
          await pg.close();
        }
        return tider.sort((a, b) => a - b)[2];
      };
      for (const liga of SIDENE) {
        const uten = await tidTil(liga, null), med = await tidTil(liga, {innhold: {[liga]: filer[liga]}}),
              treg = await tidTil(liga, {innhold: {[liga]: filer[liga]}, forsinkelse: 3000});
        const grense = uten * 1.15 + 30;
        check(`${liga}: tid til første prosenter i tabellen er ikke lengre med filen (${med} ms) eller en treg fil (${treg} ms) enn uten (${uten} ms)`,
          med <= grense && treg <= grense, `grense ${Math.round(grense)} ms`);
      }
      GRUNNLAG_MODUS = null;
    }

    await hvaMaaTekst();

    // ---- Svarene: vist nivå minus vist nå = vist differanse ----
    // Svarene viser nivået avrundet og differansen i parentes. Ble differansen
    // regnet før avrunding, gikk tallene i samme setning ikke opp ("til 15 %
    // (+8) ... er 8 % nå"). Testen er DETERMINISTISK: simuleringen byttes ut
    // med valgte tall, og nå-nivået settes direkte (0,3 %, 1,2 %, 2,4 %, 50 %,
    // 98,8 %, 99,7 %), for én fremre og én bakre sone i hver liga. Da dekkes
    // "<1 %" -> lite tall og tilbake, ">99 %" og ned, og "reduserer ... med N".
    setGroup('Svarene: vist nivå minus vist nå = vist differanse');
    for (const [url, liga] of [[base, 'Eliteserien'], [base.replace('/eliteserien/', '/obos/'), 'OBOS']]) {
      const sp = await open(1400, 900, url);
      const r = await sp.evaluate(async () => {
        const tall = s => s === '<1 %' ? 0 : s === '>99 %' ? 100 : parseInt(s, 10);
        const vis = x => { const y = Math.min(1, Math.max(0, x)); return y < 0.005 ? 0 : y > 0.995 ? 100 : Math.round(y * 100); };
        const PCT = '(<1 %|>99 %|\\d+ %)';
        const orig = {runMatchImpactAsync, runZoneTasks, qaTargetZone, qaZoneByKey, qaSettled};
        const t = TEAMS[0];
        const fremre = ['europa', 'gull'].find(k => LEAGUE.zones[k]), bakre = ['nedrykk', 'kvalik'].find(k => LEAGUE.zones[k]);
        const brudd = [], eks = {}; let n = 0, nBakre = 0;
        for (const key of [fremre, bakre]) {
          const ekte = orig.qaZoneByKey(t, key);
          for (const P of [0.003, 0.012, 0.024, 0.5, 0.988, 0.997]) {
            const z = {...ekte, pct: P};
            qaTargetZone = () => z; qaZoneByKey = () => z; qaSettled = () => null; qaWhyZoneOverride = null;
            for (const d of [0.0249, -0.009, 0.009, -0.02, -0.022, 0.0760, -0.0760, 0.0351, -0.0449, 0.9, -0.9]) {
              runMatchImpactAsync = async (team, zone, specs) => ({results: specs.map(c => ({
                idx: c.idx, baseProb: 0.5, homeProb: 0.5 + d, awayProb: 0.5 - d / 2, drawProb: 0.5 + d / 3, diff: Math.abs(1.5 * d)}))});
              runZoneTasks = async (payload, tasks) => { const res = {};
                tasks.forEach(k => { res[k.id] = {prob: k.id === 'base' ? 0.5 : 0.5 + (k.id.endsWith(':H') ? d : k.id.endsWith(':U') ? d / 3 : -d / 2), pos: null}; });
                return res; };
              const nm = await qaNextMatch(t), naa = nm.match(new RegExp(`er ${PCT} nå`));
              for (const m of nm.matchAll(new RegExp(`til ${PCT} \\(([+−]\\d+|±0) prosentpoeng\\)`, 'g'))) {
                n++; const a = tall(m[1]), b = m[2] === '±0' ? 0 : parseInt(m[2].replace('−', '-'), 10), N = tall(naa[1]);
                if (a - N !== b) brudd.push(`neste kamp (${key}, nå ${naa[1]}): ${m[1]} − ${naa[1]} ≠ ${m[2]}`);
                const s = nm.split('. ')[0] + '. … ' + nm.match(/[^.]* er [^.]* nå\./)[0];
                if (naa[1] === '<1 %' && a > 0 && !eks.fraUnder1) eks.fraUnder1 = s;
                if (m[1] === '<1 %' && N > 0 && !eks.tilUnder1) eks.tilUnder1 = s;
                if (naa[1] === '>99 %' && a < 100 && !eks.fraOver99) eks.fraOver99 = s;
              }
              const km = await qaKeyMatches(t), naa2 = km.match(new RegExp(`Den er ${PCT} nå`));
              if (naa2) for (const m of km.matchAll(new RegExp(`${PCT} \\(([+-]?\\d+)\\)`, 'g'))) {
                n++; if (key === bakre) nBakre++;
                if (tall(m[1]) - tall(naa2[1]) !== parseInt(m[2], 10)) brudd.push(`kamper som betyr mest (${key}): ${m[1]} − ${naa2[1]} ≠ ${m[2]}`);
                if (key === bakre && !eks.kmBakre && tall(naa2[1]) !== tall(m[1])) eks.kmBakre = km.split('\n').filter(Boolean).slice(0, 2).join(' | ');
              }
              // Heie på: differansen står alene. Fremre: "+N prosentpoeng",
              // bakre: "reduserer ... med N prosentpoeng". N skal være
              // forskjellen mellom de viste tallene for det beste utfallet.
              const ch = await qaCheerFor(t);
              const kand = [d, d / 3, -d / 2].map(dd => vis(P + dd) - vis(P));
              for (const m of ch.matchAll(/: ([+−]\d+|±0) prosentpoeng|reduserer [^\n]*? med (\d+) prosentpoeng/g)) {
                n++;
                if (m[1]) { const v = m[1] === '±0' ? 0 : parseInt(m[1].replace('−', '-'), 10);
                  if (!kand.includes(v)) brudd.push(`heie på (${key}, nå ${vis(P)}): ${m[1]} er ikke vist nivå minus vist nå (${kand.join('/')})`); }
                else { nBakre++; const v = parseInt(m[2], 10);
                  if (!kand.map(x => -x).includes(v)) brudd.push(`heie på (${key}, nå ${vis(P)}): «reduserer med ${v}» er ikke forskjellen mellom de viste tallene (${kand.join('/')})`);
                  if (!eks.cheerBakre) eks.cheerBakre = `nå ${P < 0.005 ? '<1' : P > 0.995 ? '>99' : Math.round(P * 100)} %: ` + ch.split('\n')[1]; }
              }
            }
          }
        }
        Object.assign(window, {}); runMatchImpactAsync = orig.runMatchImpactAsync; runZoneTasks = orig.runZoneTasks;
        qaTargetZone = orig.qaTargetZone; qaZoneByKey = orig.qaZoneByKey; qaSettled = orig.qaSettled; qaWhyZoneOverride = null;
        return {soner: [fremre, bakre], n, nBakre, brudd, eks,
                bruddBakre: brudd.filter(b => b.includes(`(${bakre}`) || b.includes('reduserer'))};
      });
      for (const [k, v] of Object.entries(r.eks)) console.log(`      ${liga} ${k}: ${v}`);
      check(`${liga}: vist nivå minus vist nå = vist differanse i ${r.n} tall (${r.soner.join(' og ')}, nå fra <1 % til >99 %)`,
        r.n > 100 && r.brudd.length === 0, `${r.brudd.length} brudd: ${r.brudd.slice(0, 4).join('; ')}`);
      check(`${liga}: overgangene er med: <1 % -> lite tall, lite tall -> <1 %, >99 % og ned`,
        r.eks.fraUnder1 && r.eks.tilUnder1 && r.eks.fraOver99, JSON.stringify(r.eks));
      check(`${liga}: bakre sone (${r.soner[1]}): "reduserer ... med N" og differansene i kamper som betyr mest går opp (${r.nBakre} tall)`,
        r.nBakre > 10 && r.eks.cheerBakre && r.eks.kmBakre && r.bruddBakre.length === 0,
        `${r.bruddBakre.length} brudd: ${r.bruddBakre.slice(0, 3).join('; ')}`);
      // Og uten utbytting: ekte simulering for to lag.
      const ekte = await sp.evaluate(async () => {
        const tall = s => s === '<1 %' ? 0 : s === '>99 %' ? 100 : parseInt(s, 10);
        const PCT = '(<1 %|>99 %|\\d+ %)', brudd = []; let n = 0;
        for (const t of TEAMS.slice(0, 2)) {
          qaWhyZoneOverride = null;
          const nm = await qaNextMatch(t), naa = nm.match(new RegExp(`er ${PCT} nå`));
          if (naa) for (const m of nm.matchAll(new RegExp(`til ${PCT} \\(([+−]\\d+|±0) prosentpoeng\\)`, 'g'))) {
            n++; if (tall(m[1]) - tall(naa[1]) !== (m[2] === '±0' ? 0 : parseInt(m[2].replace('−', '-'), 10))) brudd.push(nm.slice(0, 120));
          }
        }
        return {n, brudd};
      });
      check(`${liga}: ekte simulering, neste kamp: tallene går opp`, ekte.brudd.length === 0, ekte.brudd.join('; '));
      await sp.close();
    }

    // ---- Forrige kamp: kildeordet i svaret følger kilden ----
    // Sjansen for resultatet før kampen er en frosset prognose eller, som
    // reserve, sluttoddsen. Svaret sier hvilken: "Sluttoddsen ga ..." eller
    // "Modellen ga ...", i avsnittet etter endringen. Linja i lagboksen nevner
    // ingen kilde (29.9.2026; før sto "enn markedet/modellen ventet" begge
    // steder).
    setGroup('Forrige kamp: kildeordet følger kilden');
    for (const [url, liga] of [[base, 'Eliteserien'], [base.replace('/eliteserien/', '/obos/'), 'OBOS']]) {
      const sp = await open(1400, 900, url);
      const r = await sp.evaluate(async () => {
        const ut = {odds: 0, modell: 0, feil: []};
        const ordet = pk => pk && pk.kilde === 'sluttoddsen' ? 'Sluttoddsen' : 'Modellen';
        const gml = PREKICK;
        for (const t of TEAMS.slice(0, 6)) {
          const d = await qaLastMatchData(t);
          if (!d || d.noMatch || !d.preKick) continue;
          // 1) Som dataene står (i dag: sluttoddsen).
          let txt = await qaLastMatch(t);
          let m = txt.split('\n\n')[1].match(/^(\S+) ga /);
          const f = ordet(d.preKick);
          if (!m || m[1] !== f) ut.feil.push(`${t}: «${m && m[1]}» med kilde ${d.preKick.kilde}`); else ut[f === 'Sluttoddsen' ? 'odds' : 'modell']++;
          // 2) Med en frosset prognose for kampen: da er det modellen.
          const k = `${LEAGUE.season}|${d.m.home}|${d.m.away}`;
          PREKICK = Object.assign({}, gml || {}, {[k]: {H: 0.2, U: 0.3, B: 0.5, kilde: 'odds+modell', frosset: true}});
          txt = await qaLastMatch(t);
          m = txt.split('\n\n')[1].match(/^(\S+) ga /);
          if (!m || m[1] !== 'Modellen') ut.feil.push(`${t} med frosset prognose: «${m && m[1]}»`); else ut.modell++;
          PREKICK = gml;
        }
        // Linja i lagboksen: ingen kilde, for alle lagene.
        for (const t of TEAMS) {
          const l = qaLastMatchLine(t, lastMatchEntry(t));
          if (l && /ventet|markedet|modellen|Sluttoddsen|sluttodds/.test(l.html)) ut.feil.push(`lagboksen, ${t}: ${l.html}`);
        }
        return ut;
      });
      check(`${liga}: sluttodds gir «Sluttoddsen ga», frosset prognose «Modellen ga», lagboksen ingen kilde (${r.odds} sluttodds, ${r.modell} modell)`,
        r.feil.length === 0 && r.odds > 0 && r.modell > 0, r.feil.slice(0, 4).join('; ') || `sluttodds ${r.odds}, modell ${r.modell}`);
      await sp.close();
    }
    await page.bringToFront();

    await treffsikkerhetTekst();
    await sesongstart();
    await delKnapp();

    setGroup('JS-feil');
    check('ingen feil i konsollen', errors.length === 0, errors.join('\n      '));
    await page.close();
    }
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
