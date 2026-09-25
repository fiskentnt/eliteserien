#!/usr/bin/env node
/* Leser tabellen og sannsynlighetene UT AV en ligaside i headless Chrome.
 *
 * Poenget: siden regner ut prosentene i nettleseren. Vil man vite hva den
 * faktisk viser, maa man spoerre siden -- ikke gjenskape modellen.
 *
 * Bruk:  node les_side.js <rot> <liga-sti> [ut.json]
 *   rot        mappe som serveres (f.eks. en sandkasse-kopi av repoet)
 *   liga-sti   f.eks. eliteserien/ eller eliteserien/2026/
 */
const http = require('http'), fs = require('fs'), path = require('path');
const MIME = {'.html':'text/html','.js':'text/javascript','.json':'application/json',
  '.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon',
  '.webmanifest':'application/manifest+json','.txt':'text/plain'};
function serve(rot){
  const s = http.createServer((rq,rs)=>{
    let p = decodeURIComponent(rq.url.split('?')[0]);
    if(p.endsWith('/')) p += 'index.html';
    const f = path.join(rot, p);
    if(!fs.existsSync(f) || !fs.statSync(f).isFile()){ rs.writeHead(404); return rs.end(); }
    rs.writeHead(200, {'Content-Type': MIME[path.extname(f)] || 'application/octet-stream'});
    fs.createReadStream(f).pipe(rs);
  });
  return new Promise(r => s.listen(0,'127.0.0.1',()=>r(s)));
}
function chrome(){
  const c = [process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  const f = c.find(x => fs.existsSync(x));
  if(!f) throw new Error('Fant ikke Chrome. Sett CHROME_PATH.');
  return f;
}
(async () => {
  const [rot, liga, ut] = process.argv.slice(2);
  if(!rot || !liga){ console.error('bruk: node les_side.js <rot> <liga-sti> [ut.json]'); process.exit(2); }
  const pp = require('puppeteer-core');
  const srv = await serve(rot);
  const b = await pp.launch({executablePath: chrome(), headless: 'new',
    args: ['--no-sandbox','--disable-setuid-sandbox']});
  const pg = await b.newPage();
  const feil = [];
  pg.on('pageerror', e => feil.push(e.message));
  const url = `http://127.0.0.1:${srv.address().port}/${liga.replace(/^\/+/,'')}`;
  await pg.goto(url, {waitUntil: 'networkidle0'});
  // Vent til tabellen har rader OG prosentene er fylt inn
  await pg.waitForFunction(() => {
    const r = document.querySelectorAll('#tbl tbody tr');
    return r.length >= 10 && /\d/.test(r[0].textContent);
  }, {timeout: 60000});
  await new Promise(r => setTimeout(r, 2500));   // la simuleringen sette seg
  const data = await pg.evaluate(() => {
    const rader = [...document.querySelectorAll('#tbl tbody tr')].map(tr => {
      const c = [...tr.querySelectorAll('th,td')].map(x => x.textContent.trim());
      return c;
    });
    const hoder = [...document.querySelectorAll('#tbl thead th')].map(x => x.textContent.trim());
    return {hoder, rader,
            tittel: (document.querySelector('#leagueName') || {}).textContent || null,
            stempel: (document.querySelector('.stamp') || {}).textContent || null};
  });
  data.feil = feil;
  await b.close(); srv.close();
  const s = JSON.stringify(data, null, 1);
  if(ut) fs.writeFileSync(ut, s + '\n'); else console.log(s);
  if(feil.length){ console.error('JS-FEIL: ' + feil.join(' | ')); process.exit(1); }
})();
