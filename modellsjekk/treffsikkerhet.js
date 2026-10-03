// Treffsikkerheten denne sesongen på modellsjekk-sidene: log loss og
// kalibrering fra ../data/accuracy.json (scripts/accuracy_log.py), med samme
// tall, ordlyd og terskel som kortversjonen på ligasiden (renderAccuracy i
// index.html). Bygges inn i <liga>/modellsjekk/index.html av
// scripts/build_modellsjekk.py. Tall vises først når minst MIN_KAMPER kamper
// er loggført denne sesongen.
(function(){
  const MIN_KAMPER = 20;
  const MND = ['januar','februar','mars','april','mai','juni','juli','august','september','oktober','november','desember'];
  const datoLang = iso => { const d = new Date(iso + 'T12:00:00Z'); return `${d.getUTCDate()}. ${MND[d.getUTCMonth()]}`; };
  const NAVN = {side: 'Siden (odds og modell)', modell: 'Modellen alene', odds: 'Sluttoddsen alene'};
  const pct = v => v == null ? '–' : `${Math.round(v * 100)} %`;
  function tegn(data){
    const el = document.getElementById('accuracyTall');
    if(!el) return;
    const n = data && data.n || 0;
    if(n < MIN_KAMPER){
      el.innerHTML = `<p class="note">Loggføringen er i gang. Tall vises når det er spilt minst ${MIN_KAMPER} kamper.</p>`;
      return;
    }
    const rader = Object.keys(NAVN).filter(k => data.kilder[k] && data.kilder[k].n).map(k => { const v = data.kilder[k];
      return `<tr><td>${NAVN[k]}</td><td>${v.n}</td><td>${pct(v.treff)}</td><td>${v.logloss.toFixed(4).replace('.', ',')}</td></tr>`; }).join('');
    const kal = (data.kalibrering || []).filter(b => b.n > 0).map(b =>
      `<tr><td>${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)} %</td><td>${b.n}</td><td>${pct(b.ventet)}</td><td>${pct(b.faktisk)}</td></tr>`).join('');
    const antall = `${n} kamper`;
    const usikker = n < 50 ? `Tallene bygger på ${antall}, og sier lite før det er flere.` : `Tallene bygger på ${antall}.`;
    const spilt = !data.fra ? '' : ' Kampene ble spilt '
      + (data.fra === data.til ? `${datoLang(data.fra)}.`
        : data.fra.slice(0, 7) === data.til.slice(0, 7) ? `mellom ${+data.fra.slice(8, 10)}. og ${datoLang(data.til)}.`
        : `mellom ${datoLang(data.fra)} og ${datoLang(data.til)}.`);
    const side = data.kilder.side;
    const kort = side && side.n ? `Utfallet siden ga størst sjanse, skjedde i ${pct(side.treff)} av kampene. ` : '';
    el.innerHTML = `<p class="note">${kort}${usikker}${spilt}</p>`
      + `<div class="tblscroll"><table class="mt">`
      + `<thead><tr><th>Kilde</th><th>Kamper</th><th>Traff utfallet</th><th>Log loss</th></tr></thead>`
      + `<tbody>${rader}</tbody></table></div>`
      + `<p class="note">"Traff utfallet" er hvor ofte det mest sannsynlige utfallet ble det som skjedde. `
      + `Log loss straffer sikre prediksjoner som bommer; lavere er bedre.</p>`
      + (kal ? `<h3>Kalibrering denne sesongen</h3>`
        + `<div class="tblscroll"><table class="mt calib">`
        + `<thead><tr><th>Modellen sa</th><th>Tilfeller</th><th>Snitt</th><th>Skjedde</th></tr></thead>`
        + `<tbody>${kal}</tbody></table></div>` : '');
  }
  window.tegnTreffsikkerhet = tegn;    // testene kaller denne med egne tall
  fetch('../data/accuracy.json').then(r => r.ok ? r.json() : null).then(tegn).catch(() => tegn(null));
})();
