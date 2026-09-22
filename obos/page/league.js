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
    // Kortform i det smale tokolonnesområdet (1100 til 1219 px), som «Nedr.»:
    // «Opprykk» er 16 px bredere enn Eliteseriens «Gull», og uten kortformen
    // måtte OBOS-tabellen scrolles sidelengs ved 1100 px.
    {key: 'gull', head: 'Opprykk', headSm: 'Oppr.', card: 'Direkte opprykk', cls: 'gull hide-m',
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
  // Oddsen for OBOS kommer fra OddsPapi (sluttodds fra Pinnacle, bet365 og
  // unibet). Eliteserien bruker The Odds API.
  oddsSource: 'OddsPapi',
  // Sluttodds for spilte kamper, reserve når prekick.json ikke har kampen.
  closingOddsFile: 'data/odds_closing.json',
  // Klubbfarger, én per lag i DENNE ligaen. Draktfargen (trøyens hovedfarge)
  // fra draktboksen på Wikipedia, krysssjekket mot NFFs lagsider. Tre valg
  // som ikke kommer rett fra kilden, alle etter samme regel som Eliteserien:
  //   Haugesund, Odd og Sogndal spiller i HVITT. Hvit gir 1:1 mot hvit tekst
  //   og mot det lyse panelet, så de får andrefargen på drakten: Haugesund
  //   blå (shorts), Odd og Sogndal nesten-sort, som Rosenborg.
  //   Bryne, Kongsvinger og Lyn har alle ren rød (#ff0000) hos kilden. Ren rød
  //   når ikke 4,5:1 mot noen tekstfarge, så alle tre er dempet like mye, til
  //   #eb0000. De er fortsatt like, og det er greit: bare ett lag vises om
  //   gangen (alle --team-*-variablene følger laget du følger), som med
  //   Lillestrøm og Start i Eliteserien.
  //   Strømmen sin grå er løftet fra #808080 til #828282 av samme grunn.
  // Egersund fikk en drakt-gul i samme sjikt som Eliteserien-gulene i stedet
  // for malens neongule #ffff33, og Åsane klubbens egen #f5821f i stedet for
  // malens pastell. Variantene er laget med scripts/team_colors.py --json,
  // og «--check» kontrollerer kontrasten på nytt.
  teamColors: {
    "Bryne": {fill:"#eb0000", deep:"#a90000", fillText:"#ffffff", textLight:"#eb0000", textDark:"#ff2525", topDark:"#741313", topDeepDark:"#530d0d"},
    "Egersund": {fill:"#f7c800", deep:"#b29000", fillText:"#15191c", textLight:"#8f7400", textDark:"#f7c800", topDark:"#7a6614", topDeepDark:"#584a0e"},
    "Haugesund": {fill:"#1b56a8", deep:"#133e79", fillText:"#ffffff", textLight:"#1b56a8", textDark:"#4083e0", topDark:"#1b3355", topDeepDark:"#13253d"},
    "Hødd": {fill:"#0033cc", deep:"#002593", fillText:"#ffffff", textLight:"#0033cc", textDark:"#4e7aff", topDark:"#102565", topDeepDark:"#0c1b49"},
    "Kongsvinger": {fill:"#eb0000", deep:"#a90000", fillText:"#ffffff", textLight:"#eb0000", textDark:"#ff2525", topDark:"#741313", topDeepDark:"#530d0d"},
    "Lyn": {fill:"#eb0000", deep:"#a90000", fillText:"#ffffff", textLight:"#eb0000", textDark:"#ff2525", topDark:"#741313", topDeepDark:"#530d0d"},
    "Moss": {fill:"#ffde00", deep:"#b8a000", fillText:"#15191c", textLight:"#887600", textDark:"#ffde00", topDark:"#7e7014", topDeepDark:"#5b510f"},
    "Odd": {fill:"#2a2e32", deep:"#1e2124", fillText:"#ffffff", textLight:"#2a2e32", textDark:"#7a858f", topDark:"#191a1c", topDeepDark:"#121314"},
    "Ranheim": {fill:"#0b3fd4", deep:"#082d99", fillText:"#ffffff", textLight:"#0b3fd4", textDark:"#517cf6", topDark:"#162c69", topDeepDark:"#101f4c"},
    "Raufoss": {fill:"#ffcc00", deep:"#b89300", fillText:"#15191c", textLight:"#907300", textDark:"#ffcc00", topDark:"#7e6914", topDeepDark:"#5b4b0f"},
    "Sandnes Ulf": {fill:"#6caddf", deep:"#2b81c4", fillText:"#15191c", textLight:"#297bbb", textDark:"#6caddf", topDark:"#33658b", topDeepDark:"#254864"},
    "Sogndal": {fill:"#2a2e32", deep:"#1e2124", fillText:"#ffffff", textLight:"#2a2e32", textDark:"#7a858f", topDark:"#191a1c", topDeepDark:"#121314"},
    "Stabæk": {fill:"#1130d6", deep:"#0c239a", fillText:"#ffffff", textLight:"#1130d6", textDark:"#6279f3", topDark:"#19266b", topDeepDark:"#121c4d"},
    "Strømmen": {fill:"#828282", deep:"#5e5e5e", fillText:"#15191c", textLight:"#767676", textDark:"#838383", topDark:"#4a4a4a", topDeepDark:"#363636"},
    "Strømsgodset": {fill:"#000060", deep:"#000045", fillText:"#ffffff", textLight:"#000060", textDark:"#7272ff", topDark:"#08082f", topDeepDark:"#050522"},
    "Åsane": {fill:"#f5821f", deep:"#be5d08", fillText:"#15191c", textLight:"#bc5b08", textDark:"#f5821f", topDark:"#834b1b", topDeepDark:"#5e3613"},
  },
  // "Forrige runde" sammenfoldet som standard, som i Eliteserien.
  recentOpen: false,
  movedRounds: {},
};
const ZONE_KEYS = ['gull', 'cl', 'europa', 'kvalik', 'nedrykk'];
// Plasseringene en sone dekker, som [fra, til].
const zoneRange = key => { const z = LEAGUE.zones[key]; return z ? [z.lo, z.hi] : null; };
// ==== SLUTT PÅ LIGAINNSTILLINGER ===========================================
