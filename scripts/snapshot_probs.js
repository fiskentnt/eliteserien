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
const {avsparkFraTerminliste, oppdaterPrekick, kamperIVinduet} = require('./prekick_frys');

const ROOT = path.join(__dirname, '..');
// Hvilken liga. Alt som skiller ligaene ligger i LEAGUE på selve siden, så
// dette skriptet trenger bare å vite hvilken mappe det skal lese og skrive:
//   node scripts/snapshot_probs.js            -- Eliteserien
//   node scripts/snapshot_probs.js obos       -- OBOS-ligaen
//
// Side og utmappe kan velges, med dagens verdier som standard:
//   --side <mappe>     siden som åpnes (standard: ligaen), f.eks. elo-test
//   --ut <mappe>       hvor filene skrives (standard: <liga>/data)
//   --uten-historikk   ikke skriv history.json
// Terminlisten (frysregelen) leses alltid fra <liga>/data/fixtures.json.
//   node scripts/snapshot_probs.js eliteserien --side elo-test --ut elo-test/emodell --uten-historikk
//
// Prognosen før avspark (prekick.json) har to skrivere, delt etter tid (se
// scripts/prekick_frys.js):
//   --uten-prekick-vindu  datajobbene (update-data, obos-results): rør ikke
//                         rader med avspark innen 80 minutter
//   --bare-prekick        prekick-odds.yml: BARE prekick.json, og bare radene
//                         i vinduet, med oddsen fra "Odds nær avspark" og de
//                         nyeste lagstyrkene. Ingen keymatch, lastmatch eller
//                         historikk. Er ingen kamp i vinduet, avsluttes det
//                         før Chrome startes.
//   --oddstid <ISO>       (bare med --bare-prekick) da kjøringen hentet oddsen.
//                         Raden skrives når det var 70 til 15 minutter før
//                         avspark (og senest 10 minutter før avspark nå), og
//                         tidspunktet blir stempelet. Standard: nå.
//   --dry-run             (bare med --bare-prekick) skriv ingenting, vis hva
//                         som ville blitt endret
// Uten noen av dem: alle uspilte rader før avspark (testsiden, der
// elo-test.yml er eneste skriver).
const ARGS = process.argv.slice(2);
const flagg = navn => { const i = ARGS.indexOf(navn); return i >= 0 ? ARGS[i + 1] : null; };
const LEAGUE_DIR = ARGS.filter((a, i) => !a.startsWith('--') && !(i > 0 && ['--side', '--ut', '--oddstid'].includes(ARGS[i - 1])))[0] || 'eliteserien';
const DATA = path.join(ROOT, LEAGUE_DIR, 'data');
const SIDE = flagg('--side') || LEAGUE_DIR;
const UT = flagg('--ut') ? path.join(ROOT, flagg('--ut')) : DATA;
const MED_HISTORIKK = !ARGS.includes('--uten-historikk');
const BARE_PREKICK = ARGS.includes('--bare-prekick');
const PREKICK_MODUS = BARE_PREKICK ? 'bare-vindu' : ARGS.includes('--uten-prekick-vindu') ? 'uten-vindu' : 'alle';
const DRY_RUN = ARGS.includes('--dry-run');
if (DRY_RUN && !BARE_PREKICK) { console.error('--dry-run gjelder bare sammen med --bare-prekick.'); process.exit(2); }
if (flagg('--oddstid') != null && !BARE_PREKICK) { console.error('--oddstid gjelder bare sammen med --bare-prekick.'); process.exit(2); }
const ODDSTID = flagg('--oddstid') != null ? Date.parse(flagg('--oddstid')) : Date.now();
if (!Number.isFinite(ODDSTID)) { console.error(`--oddstid: ugyldig tidspunkt ${flagg('--oddstid')}`); process.exit(2); }
const isoSek = ms => new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
const HISTORY = path.join(UT, 'history.json');
const KEYMATCH = path.join(UT, 'keymatch.json');
const LASTMATCH = path.join(UT, 'lastmatch.json');
const PREKICK = path.join(UT, 'prekick.json');
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
  if (BARE_PREKICK) {
    const fx = JSON.parse(fs.readFileSync(path.join(DATA, 'fixtures.json'), 'utf8'));
    const iVindu = kamperIVinduet(fx, ODDSTID, Date.now());
    if (!iVindu.length) { console.log(`prekick.json (${LEAGUE_DIR}): ingen kamp i vinduet med odds hentet ${isoSek(ODDSTID)} -- ingenting å gjøre.`); return; }
    console.log(`prekick.json (${LEAGUE_DIR}): ${iVindu.length} kamp(er) i vinduet med odds hentet ${isoSek(ODDSTID)}: ${iVindu.join(', ')}`);
  }
  const puppeteer = require('puppeteer-core');
  const server = await serve();
  const port = server.address().port;
  const browser = await puppeteer.launch({executablePath: chromePath(), headless: 'new', args: ['--no-sandbox', '--disable-setuid-sandbox']});
  try {
    const page = await browser.newPage();
    const errs = [];
    page.on('pageerror', e => errs.push(e.message));
    await page.goto(`http://127.0.0.1:${port}/${SIDE}/`, {waitUntil: 'domcontentloaded'});
    await page.waitForFunction('typeof lastMCFinal!=="undefined" && lastMCFinal===true && lastMC', {timeout: 180000});
    // Testsiden (/elo-test/) regner "forrige kamp" med ratingen etter det
    // alternative resultatet, og trenger da sluttoddsen for spilte kamper
    // (ELO_ODDS_SPILT, hentes ved siden av i boot()). Uten den ville
    // lastmatch.json blitt regnet med fast rating. Produksjonssidene har ikke
    // variabelen, og da venter ikke dette. Lastes den aldri, feiler kjøringen
    // heller enn å skrive feil tall.
    await page.waitForFunction('typeof ELO_ODDS_SPILT === "undefined" || ELO_ODDS_SPILT !== null', {timeout: 60000});
    const snap = BARE_PREKICK ? null : await page.evaluate(() => {
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
    // qaKeyBanner, så ordlyden finnes bare ett sted. Her i CI med sidens
    // QA_KEY_N_CI / QA_KEY_CLOSE_CI (mange sesonger, stram grense), ikke
    // nettleserens lavere N; filen sier hvilke som ble brukt.
    const key = BARE_PREKICK ? undefined : await page.evaluate(async () => {
      const d = await qaKeyRoundData({N: QA_KEY_N_CI, close: QA_KEY_CLOSE_CI});
      const banner = qaKeyBanner(d);
      if (!d || !d.best || !banner) return null;
      return {round: d.round, banner, sesonger: d.sesonger, grense: d.grense,
        match: {home: d.best.m.home, away: d.best.m.away, date: d.best.m.date},
        zone: d.best.topZone.key,
        teams: d.best.teams.map(t => t.team)};
    });
    if (errs.length) console.warn('Sidefeil:', errs.join('; '));
    if (BARE_PREKICK) { /* keymatch hoppes over */ }
    else if (key) {
      const next = {version: 1, note: 'Rundens viktigste kamp, regnet ut av scripts/snapshot_probs.js etter hver oppdatering. Banneret på siden viser "banner" som den er.', ...key};
      const same = fs.existsSync(KEYMATCH) && (() => {
        const old = JSON.parse(fs.readFileSync(KEYMATCH, 'utf8'));
        return old.banner === next.banner && old.round === next.round && JSON.stringify(old.teams) === JSON.stringify(next.teams)
          && old.sesonger === next.sesonger && old.grense === next.grense;
      })();
      if (same) console.log('Rundens viktigste kamp uendret.');
      else {
        fs.writeFileSync(KEYMATCH, JSON.stringify({...next, updated: new Date().toISOString().replace(/\.\d+Z$/, 'Z')}, null, 1) + '\n');
        console.log('Skrev keymatch.json:', next.banner);
      }
    } else {
      console.log('Ingen viktigste kamp å lagre (ingen runde igjen, eller ingen kamp flytter nok).');
    }
    // Sannsynlighetene for hvert utfall FØR avspark, per kamp. Lagres mens
    // kampen fortsatt er uspilt, og fryses i det den er spilt: da er tallet
    // fritt for etterpåklokskap. Uten dette måtte "forrige kamp" regne
    // sannsynligheten med lagstyrker som alt hadde sett resultatet.
    const pre = await page.evaluate(() => {
      const ut = {};
      for (const m of matches) {
        if (m.hg != null) continue;              // spilt, eller fylt inn av noen
        const [lh, la] = rateFor(m.home, m.away);
        const o = outcome(lh, la);
        const info = RATES[m.home + '|' + m.away] || {};
        ut[`${LEAGUE.season}|${m.home}|${m.away}`] = {
          home: m.home, away: m.away, date: m.date, round: m.round,
          H: +o.H.toFixed(4), U: +o.U.toFixed(4), B: +o.B.toFixed(4),
          kilde: info.odds ? 'odds+modell' : 'modell',
          oddsvekt: info.odds ? ODDS_W : 0,
          // Oddsen slik den sto, og modellen alene, så de kan skilles senere.
          odds: info.odds ? {H: +info.mk[0].toFixed(4), U: +info.mk[1].toFixed(4), B: +info.mk[2].toFixed(4),
                             bookmaker: (info.meta || {}).bookmaker || null} : null,
          modell: {H: +(info.md ? info.md.H : o.H).toFixed(4),
                   U: +(info.md ? info.md.U : o.U).toFixed(4),
                   B: +(info.md ? info.md.B : o.B).toFixed(4)},
        };
      }
      return ut;
    });
    {
      // Frysregelen ligger i scripts/prekick_frys.js: en rad oppdateres bare
      // FØR avspark fra terminlisten, og fryses med siste stempel fra før
      // avspark når resultatet kommer. Se kommentaren der.
      const old = fs.existsSync(PREKICK) ? JSON.parse(fs.readFileSync(PREKICK, 'utf8')) : {version: 1, matches: {}};
      const avspark = avsparkFraTerminliste(JSON.parse(fs.readFileSync(path.join(DATA, 'fixtures.json'), 'utf8')));
      const spilte = await page.evaluate(() =>
        MATCHES.map(m => `${LEAGUE.season}|${m.home}|${m.away}`));
      const foer = JSON.parse(JSON.stringify(old.matches || {}));
      // 'bare-vindu': tiden for oddsen i kjøringen avgjør og blir stempelet,
      // og klokken nå må være før skrivestoppen (prekick_frys.js).
      const naa = BARE_PREKICK ? ODDSTID : Date.now();
      const n = oppdaterPrekick(old, pre, spilte, avspark, naa, isoSek(naa), PREKICK_MODUS, BARE_PREKICK ? Date.now() : naa);
      old.version = 1;
      old.note = 'Sannsynlighet for hvert utfall før avspark, per kamp. Oppdateres bare før avspark fra terminlisten og fryses med siste stempel fra før avspark når kampen er spilt, så "forrige kamp" og treffsikkerheten er uten etterpåklokskap. Fra 70 til 15 minutter før avspark skrives raden av "Odds nær avspark", med sluttoddsen.';
      const endret = Object.keys(old.matches).filter(k => JSON.stringify(old.matches[k]) !== JSON.stringify(foer[k]));
      if (BARE_PREKICK) for (const k of endret) {
        const r = old.matches[k], f = foer[k];
        console.log(`  ${r.home} - ${r.away}: H/U/B ${f ? `${f.H}/${f.U}/${f.B} -> ` : ''}${r.H}/${r.U}/${r.B}, ` +
          `odds ${r.odds ? `${r.odds.bookmaker || 'snitt'} ${r.odds.H}/${r.odds.U}/${r.odds.B}` : 'ingen'}, modell ${r.modell.H}/${r.modell.U}/${r.modell.B}, stempel ${r.stamp}`);
      }
      if (DRY_RUN) console.log(`prekick.json: TØRRKJØRING -- ville endret ${endret.length} rad(er), skrev ingenting.`);
      else fs.writeFileSync(PREKICK, JSON.stringify(old, null, 1) + '\n');
      console.log(`prekick.json (${PREKICK_MODUS}): ${n.nye} nye, ${n.oppdatert} oppdatert, ${n.etterAvspark} ikke rørt etter avspark, ` +
        `${n.vinduHoppet} i vinduet til "Odds nær avspark", ${n.frosne} frosset, ${Object.keys(old.matches).length} totalt.`);
    }
    if (BARE_PREKICK) return;
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
          // pp er endringen mot FORVENTNINGEN før kampen. basis-feltet gjør at
          // siden kan se forskjell på nye rader og gamle, der pp ble målt mot
          // det beste alternative utfallet.
          pp: d.pp, good: d.good, basis: 'forventning',
          expected: d.expected==null ? null : +d.expected.toFixed(4)
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
    if (!MED_HISTORIKK) { console.log('history.json: hoppet over (--uten-historikk).'); return; }
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
