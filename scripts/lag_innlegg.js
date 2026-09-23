#!/usr/bin/env node
/**
 * Forslag til innlegg på X og Bluesky, med bilde.
 *
 * LOKALT VERKTØY. Ingenting av det dette lager havner på GitHub eller på
 * nettstedet: alt skrives til innlegg/, som står i .gitignore. Repoet er
 * offentlig, og både Actions-logger og artefakter er lesbare for alle der,
 * så forslagene kan ikke lages i en workflow uten å bli synlige.
 *
 * Tallene regnes ikke ut på nytt. Skriptet åpner de ekte sidene i Chrome og
 * leser nøyaktig det de viser -- samme framgangsmåte som snapshot_probs.js.
 *
 *   node scripts/lag_innlegg.js              begge ligaer, begge tidspunkt
 *   node scripts/lag_innlegg.js --for        bare "før runden"
 *   node scripts/lag_innlegg.js --etter      bare "etter runden"
 *   node scripts/lag_innlegg.js --liga obos
 *
 * Åpne innlegg/index.html etterpå: der ligger tekstene med kopiknapp og
 * bildene klare til å legges ved.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const UT = path.join(ROOT, 'innlegg');
const TILSTAND = path.join(UT, 'tilstand.json');   // hvilke lag som er brukt
const MIME = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.json':'application/json','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.ttf':'font/ttf'};

// Klubbene med størst supportermiljø, brukt BARE til å skille to endringer
// som er omtrent like store (innenfor to prosentpoeng).
const STORE = {
  eliteserien: ['Brann', 'Rosenborg', 'Vålerenga', 'Viking', 'Bodø/Glimt'],
  obos: ['Lyn', 'Stabæk', 'Strømsgodset', 'Sandnes Ulf', 'Bryne'],
};
const NAVN = {eliteserien: 'Eliteserien', obos: 'OBOS-ligaen'};
// "Omtrent like store": innenfor så mange prosentpoeng.
const JEVNT = 2;
// Et lag som nylig er brukt velges likevel hvis endringen er så mye større.
const KLART_STORRE = 5;

function serve(){
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if(p.endsWith('/')) p += 'index.html';
    const f = path.join(ROOT, p);
    if(!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()){ res.writeHead(404); res.end(); return; }
    res.writeHead(200, {'Content-Type': MIME[path.extname(f)] || 'application/octet-stream'});
    fs.createReadStream(f).pipe(res);
  });
  return new Promise(r => server.listen(0, '127.0.0.1', () => r(server)));
}
function chromePath(){
  const c = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  const f = c.find(x => fs.existsSync(x));
  if(!f) throw new Error('Fant ikke Chrome (sett CHROME_PATH)');
  return f;
}
const les = f => { try{ return JSON.parse(fs.readFileSync(f, 'utf8')); }catch(e){ return null; } };
const pst = v => Math.round(v * 100);

// ---- Kandidatene, hentet fra sidens egne tall ----

// FØR runden: kampen som flytter mest, og hva hvert utfall gjør for laget den
// betyr mest for. Samme data som banneret og svaret "rundens viktigste kamp".
async function forRunden(page, liga){
  return page.evaluate(async () => {
    const d = await qaKeyRoundData();
    if(!d || !d.best) return null;
    const ut = [];
    // Toppkampen og de som er omtrent like viktige: alle er kandidater, så
    // rotasjonsregelen har noe å velge mellom.
    for(const b of [d.best].concat(d.close || [])){
      const h = (b.teams || [])[0];
      if(!h || !h.d) continue;
      const naa = h.now, hjemme = b.m.home === h.team;
      const ved = k => Math.min(1, Math.max(0, naa + (h.d[k] || 0)));
      const seier = ved(hjemme ? 'H' : 'B'), tap = ved(hjemme ? 'B' : 'H');
      ut.push({
        lag: h.team, sone: h.zone,
        // Sonens eget navn: "topp 4", "gull", "direkte opprykk".
        sonenavn: (LEAGUE.zones[h.zone] || {}).label || h.zone,
        kamp: `${b.m.home} mot ${b.m.away}`, dato: b.m.date,
        dag: formatDateNo(b.m.date).split(' ')[0],
        naa: naa, seier, uavgjort: ved('U'), tap,
        // Størrelsen på saken: hele spennet mellom beste og verste utfall.
        endring: Math.abs(seier - tap),
      });
    }
    return ut;
  });
}

// ETTER runden: den største endringen som faktisk skjedde. Leses av
// history.json, som lagrer sannsynlighetene etter hver oppdatering.
function etterRunden(liga){
  const h = les(path.join(ROOT, liga, 'data', 'history.json'));
  const m = les(path.join(ROOT, liga, 'data', 'matches.json'));
  if(!h || !h.snapshots || h.snapshots.length < 2) return [];
  const nu = h.snapshots[h.snapshots.length - 1], for_ = h.snapshots[h.snapshots.length - 2];
  const SONER = {gull: 'gullsjansen', europa: null, kvalik: null, nedrykk: 'nedrykksfaren'};
  const ut = [];
  for(const lag of Object.keys(nu.teams)){
    const a = for_.teams[lag]; if(!a) continue;
    for(const sone of Object.keys(nu.teams[lag])){
      const fra = a[sone], til = nu.teams[lag][sone];
      if(fra == null || til == null) continue;
      const d = pst(til) - pst(fra);
      if(!d) continue;
      // Kampen laget spilte i runden som nettopp ble ferdig.
      const kamp = (m || []).filter(x => x.round === nu.round && (x.home === lag || x.away === lag))[0];
      ut.push({lag, sone, fra: pst(fra), til: pst(til), endring: Math.abs(d) / 100,
               runde: nu.round, kamp});
    }
  }
  // Én sak per lag: den største endringen laget hadde.
  const beste = {};
  for(const x of ut) if(!beste[x.lag] || x.endring > beste[x.lag].endring) beste[x.lag] = x;
  return Object.values(beste);
}

// ---- Prioritering ----
// Største endring vinner. Er to omtrent like store (innenfor JEVNT), velges
// laget med størst supportermiljø. Et lag som er brukt i et av de to siste
// forslagene hoppes over, med mindre endringen er klart større.
// Kjører man verktøyet to ganger samme dag, skal svaret være det samme:
// ellers rullerte forslaget videre bare fordi man så på det en gang til.
// Derfor huskes dato sammen med laget, og et treff på samme dag og samme
// tidspunkt låser valget.
function velg(kandidater, liga, brukt, laast){
  if(!kandidater.length) return null;
  if(laast){
    const t = kandidater.find(x => x.lag === laast);
    if(t) return t;
  }
  const store = STORE[liga] || [];
  const rang = x => {
    const i = store.indexOf(x.lag);
    return i < 0 ? store.length : i;         // lavere er større miljø
  };
  const sortert = kandidater.slice().sort((a, b) => {
    const d = b.endring - a.endring;
    if(Math.abs(d) * 100 > JEVNT) return d;   // klart størst vinner
    return rang(a) - rang(b);                 // ellers: supportermiljø
  });
  const ferske = sortert.filter(x => !brukt.includes(x.lag));
  if(!ferske.length) return sortert[0];
  const topp = sortert[0], neste = ferske[0];
  // Brukt nylig, men klart større enn det ferskeste alternativet: ta den.
  if(brukt.includes(topp.lag) && (topp.endring - neste.endring) * 100 >= KLART_STORRE) return topp;
  return neste;
}

// ---- Tekstene ----
// Hvilket utfall setningen skal lede med: det som flytter tallet mest. Ofte
// er det tapet, og da sier setningen mer om kampen enn en seier som knapt
// endrer noe.
function vinkel(x){
  const naa = pst(x.naa), s = pst(x.seier), t = pst(x.tap);
  const forst = Math.abs(t - naa) > Math.abs(s - naa)
    ? {ord: 'tap', v: t, annet: {ord: 'seier', v: s}}
    : {ord: 'seier', v: s, annet: {ord: 'tap', v: t}};
  return {
    naa, forst,
    // "går" når tallet stiger, "faller" når det synker -- som i de to
    // formene som ble avtalt.
    verb: forst.v < naa ? 'faller' : forst.v > naa ? 'går' : 'står',
    // Retningen for det andre utfallet, sett fra dagens tall.
    retning: forst.annet.v > naa ? 'opp til' : forst.annet.v < naa ? 'ned til' : 'til',
  };
}
function tekstFor(x, liga){
  const dag = x.dag ? ` ${x.dag}` : '';
  const v = vinkel(x);
  return `${x.kamp}${dag}: med ${v.forst.ord} ${v.verb} ${x.lag} fra ${v.naa} til ${v.forst.v} % `
    + `for ${x.sonenavn}, med ${v.forst.annet.ord} ${v.retning} ${v.forst.annet.v} %.`;
}
function tekstEtter(x, liga){
  const m = x.kamp;
  const navn = {gull: 'gullsjansen', europa: 'topp 4-sjansen', kvalik: 'kvaliksjansen',
                nedrykk: 'nedrykksfaren'}[x.sone] || x.sone;
  let hale = '';
  if(m){
    const hjemme = m.home === x.lag;
    const gf = hjemme ? m.hg : m.ag, ga = hjemme ? m.ag : m.hg;
    const mot = hjemme ? m.away : m.home;
    const ord = gf > ga ? 'seieren' : gf === ga ? 'uavgjort' : 'tapet';
    hale = ` etter ${ord} mot ${mot}`;
  }
  const retning = x.til > x.fra ? 'steg' : 'falt';
  const eier = x.lag.endsWith('s') ? `${x.lag}'` : `${x.lag}s`;
  return `${eier} ${navn} ${retning} fra ${x.fra} til ${x.til} %${hale}.`;
}

// ---- Bildet ----
// Tegnes i den samme nettleseren, med sidens egne farger, og fotograferes.
function kortHtml(tittel, hovedtall, undertekst, liga){
  // Systemskrifter, ingen henting utenfra: verktøyet skal virke uten nett,
  // og en treg fontforespørsel hang hele bildetakingen.
  return `<!DOCTYPE html><html lang="nb"><head><meta charset="utf-8">
<style>
  html,body{margin:0;padding:0}
  body{width:1200px;height:630px;background:#0a1220;color:#e9eff8;
    font-family:system-ui,-apple-system,'Helvetica Neue',Arial,sans-serif;display:flex;flex-direction:column;
    justify-content:center;padding:0 72px;box-sizing:border-box}
  .liga{font:600 26px system-ui,sans-serif;color:#93a3ba;letter-spacing:.06em;text-transform:uppercase}
  h1{font:800 60px/1.1 system-ui,sans-serif;margin:14px 0 0;max-width:1000px}
  .tall{font:800 120px/1 system-ui,sans-serif;color:#34d399;margin:18px 0 0}
  p{font:400 30px/1.4 system-ui,sans-serif;color:#93a3ba;margin:16px 0 0;max-width:1000px}
  .merke{position:absolute;right:72px;bottom:56px;font:600 24px system-ui,sans-serif;color:#60a5fa}
</style></head><body>
  <div class="liga">${liga}</div>
  <h1>${tittel}</h1>
  <div class="tall">${hovedtall}</div>
  <p>${undertekst}</p>
  <div class="merke">tabellkalkulator.no</div>
</body></html>`;
}

(async () => {
  const puppeteer = require('puppeteer-core');
  const args = process.argv.slice(2);
  const barestFor = args.includes('--for'), barestEtter = args.includes('--etter');
  const i = args.indexOf('--liga');
  const ligaer = i >= 0 ? [args[i + 1]] : ['eliteserien', 'obos'];

  fs.mkdirSync(UT, {recursive: true});
  const tilstand = les(TILSTAND) || {};
  const server = await serve(); const port = server.address().port;
  const browser = await puppeteer.launch({executablePath: chromePath(), headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']});
  const forslag = [], mangler = [];
  try{
    for(const liga of ligaer){
      const logg = tilstand[liga] || [];
      const idag = new Date().toISOString().slice(0, 10);
      // De to siste lagene, men bare fra ANDRE dager: dagens eget valg skal
      // ikke telle som "nylig brukt" mot seg selv.
      const brukt = logg.filter(x => x.dato !== idag).slice(-2).map(x => x.lag);
      const laast = naar => (logg.find(x => x.dato === idag && x.naar === naar) || {}).lag;
      const page = await browser.newPage();
      await page.setViewport({width: 1400, height: 1000});
      await page.goto(`http://127.0.0.1:${port}/${liga}/`, {waitUntil: 'networkidle0'});
      await page.waitForFunction(() => typeof lastMCFinal !== 'undefined' && lastMCFinal, {timeout: 120000});

      if(!barestEtter){
        const k = await forRunden(page, liga);
        const v = velg(k || [], liga, brukt, laast('for'));
        if(!v) mangler.push(`${NAVN[liga]} før runden: fant ingen kamp som flytter nok.`);
        if(v) forslag.push({liga, naar: 'for', lag: v.lag,
          tekst: tekstFor(v, liga),
          kort: (() => { const a = vinkel(v);
                   return {tittel: `${v.kamp}`, tall: `${a.naa} → ${a.forst.v} %`,
                     // Si HVA prosenten gjelder -- uten sonen er tallet meningsløst.
                     under: `${v.lag} for ${v.sonenavn}, med ${a.forst.ord}. `
                       + `Med ${a.forst.annet.ord}: ${a.forst.annet.v} %.`}; })()});
      }
      if(!barestFor){
        const k = etterRunden(liga);
        const v = velg(k, liga, brukt, laast('etter'));
        if(!v) mangler.push(`${NAVN[liga]} etter runden: history.json har ikke to målepunkter ennå, `
          + `så det finnes ingen endring å sammenligne. Kommer av seg selv etter neste runde.`);
        if(v) forslag.push({liga, naar: 'etter', lag: v.lag,
          tekst: tekstEtter(v, liga),
          kort: {tittel: `Runde ${v.runde}`, tall: `${v.fra} → ${v.til} %`,
                 under: tekstEtter(v, liga)}});
      }
      await page.close();
    }

    // Bildene
    const bilde = await browser.newPage();
    await bilde.setViewport({width: 1200, height: 630, deviceScaleFactor: 2});
    for(const f of forslag){
      await bilde.setContent(kortHtml(f.kort.tittel, f.kort.tall, f.kort.under, NAVN[f.liga]),
        {waitUntil: 'domcontentloaded'});
      await new Promise(r => setTimeout(r, 120));
      f.bilde = `${f.liga}-${f.naar}.png`;
      await bilde.screenshot({path: path.join(UT, f.bilde)});
    }
    await bilde.close();

    // Husk hvem som er brukt, så det ikke blir de samme hver uke.
    const idag = new Date().toISOString().slice(0, 10);
    for(const f of forslag){
      const logg = (tilstand[f.liga] || []).filter(x => !(x.dato === idag && x.naar === f.naar));
      tilstand[f.liga] = logg.concat({dato: idag, naar: f.naar, lag: f.lag}).slice(-6);
    }
    fs.writeFileSync(TILSTAND, JSON.stringify(tilstand, null, 1) + '\n');

    // Siden du ser på
    const kort = f => `<section>
      <h2>${NAVN[f.liga]} — ${f.naar === 'for' ? 'før runden' : 'etter runden'}</h2>
      <textarea readonly rows="3">${f.tekst}</textarea>
      <button data-t="${f.tekst.replace(/"/g, '&quot;')}">Kopier teksten</button>
      <img src="${f.bilde}" alt="">
      <a href="${f.bilde}" download>Last ned bildet</a>
    </section>`;
    fs.writeFileSync(path.join(UT, 'index.html'), `<!DOCTYPE html><html lang="nb"><head>
<meta charset="utf-8"><title>Forslag til innlegg</title>
<meta name="robots" content="noindex, nofollow">
<style>
 body{margin:0;padding:24px;background:#0a1220;color:#e9eff8;font:15px/1.6 system-ui,sans-serif}
 h1{font-size:22px;margin:0 0 4px} .naar{color:#93a3ba;margin:0 0 20px;font-size:13px}
 section{margin:0 0 28px;padding:16px;border:1px solid #223049;border-radius:10px;max-width:760px}
 h2{font-size:15px;margin:0 0 10px;color:#60a5fa}
 textarea{width:100%;box-sizing:border-box;background:#111c2f;color:#e9eff8;border:1px solid #223049;
   border-radius:8px;padding:10px;font:15px/1.5 system-ui,sans-serif;resize:vertical}
 button{margin:8px 8px 0 0;padding:7px 14px;border-radius:8px;border:1px solid #223049;
   background:#111c2f;color:#e9eff8;cursor:pointer;font-weight:600}
 button.ok{border-color:#34d399;color:#34d399}
 img{display:block;margin:14px 0 8px;width:100%;border-radius:8px;border:1px solid #223049}
 a{color:#60a5fa}
</style></head><body>
<h1>Forslag til innlegg</h1>
<p class="naar">Laget ${new Date().toLocaleString('nb-NO')}. Ligger bare lokalt — ikke i repoet, ikke på nettstedet.</p>
${forslag.map(kort).join('\n')}
<script>
 document.addEventListener('click', async e => {
   const b = e.target.closest('button[data-t]'); if(!b) return;
   try{ await navigator.clipboard.writeText(b.dataset.t); b.textContent='Kopiert'; b.classList.add('ok'); }
   catch(_){ const t=b.parentElement.querySelector('textarea'); t.focus(); t.select(); b.textContent='Merk og kopier'; }
   setTimeout(()=>{ b.textContent='Kopier teksten'; b.classList.remove('ok'); }, 2500);
 });
</script>
</body></html>\n`);

    console.log(`\nSkrev ${forslag.length} forslag til ${path.relative(process.cwd(), UT)}/\n`);
    for(const f of forslag){
      console.log(`  ${NAVN[f.liga]} — ${f.naar === 'for' ? 'før runden' : 'etter runden'}`);
      console.log(`    ${f.tekst}`);
      console.log(`    bilde: ${f.bilde}\n`);
    }
    for(const m of mangler) console.log(`  (${m})`);
    if(mangler.length) console.log('');
    console.log(`  Åpne: open ${path.relative(process.cwd(), path.join(UT, 'index.html'))}\n`);
  } finally {
    await browser.close(); server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
