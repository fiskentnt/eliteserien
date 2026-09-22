// ==== LIGAINNSTILLINGER ====================================================
// OBOS-ligaen. Se eliteserien/index.html for hva feltene betyr: denne blokken
// byttes inn av scripts/build_league.py, resten av koden er identisk.
//
// Sonenøklene er de samme i begge ligaer, men står for andre plasseringer:
// "gull" er direkte opprykk (1. og 2. plass) her, og "europa" er topp 6.
// Det finnes ingen egen Champions League-sone, så zones.cl er null.
const LEAGUE = {
  id: 'obos',
  name: 'OBOS-ligaen',
  season: 2026,
  path: '/obos/',
  bands: [
    {cls: 'cl', lo: 1, hi: 2, legend: 'Direkte opprykk (1 og 2)'},
    {cls: 'eu', lo: 3, hi: 6, legend: 'Opprykksspill (3 til 6)'},
    {cls: 'playoff', lo: 14, hi: 14, legend: 'Kvalik (14)'},
    {cls: 'ned', lo: 15, hi: 16, legend: 'Nedrykk (15 og 16)'},
  ],
  cuts: [2, 6, 13],
  legendNote: 'Lagene på 3. til 6. plass spiller opprykksspill mot et lag fra Eliteserien. ' +
    'Det er ikke det samme som opprykk: de kampene er ikke regnet inn her, så tallene sier ' +
    'hvor sannsynlig det er å komme dit, ikke hvor sannsynlig det er å rykke opp gjennom dem.',
  posTitles: {1: 'Direkte opprykk til Eliteserien', 2: 'Direkte opprykk til Eliteserien',
              3: 'Opprykksspill', 4: 'Opprykksspill', 5: 'Opprykksspill', 6: 'Opprykksspill',
              14: 'Kvalik mot nedrykk'},
  cols: [
    {key: 'gull', head: 'Opprykk', card: 'Direkte opprykk', cls: 'gull hide-m',
     title: 'Sannsynlighet for direkte opprykk, altså 1. eller 2. plass. Klikk for å sortere.'},
    {key: 'europa', head: 'Topp 6', card: 'Topp 6', cls: 'p3',
     title: 'Sannsynlighet for 1. til 6. plass, altså direkte opprykk eller opprykksspill. Klikk for å sortere.'},
    {key: 'ned', head: 'Nedrykk', headSm: 'Nedr.', card: 'Nedrykk', cls: 'ned',
     title: 'Sannsynlighet for 15. eller 16. plass. Kvalik på 14. plass er ikke regnet med. Klikk for å sortere.'},
  ],
  zones: {
    gull: {lo: 1, hi: 2, label: 'direkte opprykk', chance: 'opprykkssjansen',
           reach: 'rykke direkte opp', safe: 'sikret direkte opprykk',
           verb: 'rykker direkte opp', strid: 'opprykksstriden',
           da: 'rykker {team} direkte opp', past: 'og rykket direkte opp',
           pastNot: 'og rykket ikke direkte opp', boxLabel: 'Opprykk', boxRange: [0.01, 1.01]},
    cl: null,
    europa: {lo: 1, hi: 6, label: 'topp 6', chance: 'topp 6-sjansen', reach: 'nå topp 6',
             safe: 'sikret topp 6', verb: 'ender i topp 6', strid: 'kampen om topp 6',
             da: 'når {team} topp 6', past: 'og endte i topp 6', pastNot: 'og nådde ikke topp 6',
             boxLabel: 'Topp 6', boxAlways: true},
    kvalik: {lo: 14, hi: 14, boundary: 13, label: 'kvalik', chance: 'kvaliksjansen',
             reach: 'sikre plassen direkte', safe: 'sikret plassen direkte',
             verb: 'sikrer plassen direkte (13. plass eller bedre)', strid: 'kvalikstriden',
             da: 'sikrer {team} plassen direkte', boxLabel: 'Kvalik', boxAlways: true},
    nedrykk: {lo: 15, hi: 16, boundary: 13, label: 'nedrykk', chance: 'nedrykkssjansen',
              reach: 'sikre plassen direkte', safe: 'sikret plassen direkte',
              verb: 'sikrer plassen direkte (13. plass eller bedre)', strid: 'nedrykksstriden',
              da: 'sikrer {team} plassen direkte', boxLabel: 'Nedrykk', boxAlways: true},
  },
  badges: [
    {above: 1, cls: 'champ', text: 'Vinner ligaen', note: 'Vinner OBOS-ligaen: ingen kan ta dem igjen.'},
    {above: 2, cls: 'champ', text: 'Sikret opprykk', note: 'Sikret direkte opprykk: kan ikke havne lavere enn 2. plass.'},
    {above: 6, cls: 'europe', text: 'Sikret topp 6', note: 'Sikret topp 6: kan ikke havne lavere enn 6. plass, så laget får minst opprykksspill.'},
    // Vises ikke for lag som fortsatt kan nå topp 6: for dem er opprykksspill
    // saken, ikke at de har berget plassen.
    {above: 13, cls: 'safe', text: 'Sikret plass', note: 'Sikret plass: kan verken rykke ned eller havne i kvalik.',
     hideIfChance: {zone: 'europa', over: 0.01}},
  ],
  relegatedBadge: {cls: 'relegated', text: 'Rykket ned', note: 'Rykket ned: kan ikke berge plassen.'},
  shortNames: {
    'Kongsvinger': 'KIL', 'Strømsgodset': 'Godset', 'Sandnes Ulf': 'Sandnes',
    'Strømmen': 'Strømmen', 'Haugesund': 'FKH',
  },
  movedRounds: {},
};
const ZONE_KEYS = ['gull', 'cl', 'europa', 'kvalik', 'nedrykk'];
// Plasseringene en sone dekker, som [fra, til].
const zoneRange = key => { const z = LEAGUE.zones[key]; return z ? [z.lo, z.hi] : null; };
// ==== SLUTT PÅ LIGAINNSTILLINGER ===========================================
