/* Falsk klokke for Node, til tester og tørrkjøringer: lastes med
 *   node --require ./tests/falsk_klokke.js ...   (eller NODE_OPTIONS)
 * og FALSK_KLOKKE=<ISO-tidspunkt>. Klokka FORSKYVES med en fast avstand, så
 * den går fortsatt (puppeteer og tidsavbrudd oppfører seg normalt); Date.now()
 * og new Date() uten argument starter på FALSK_KLOKKE. Uten variabelen gjør
 * filen ingenting. Produksjonskoden har ingen testkrok: dette er den eneste.
 */
const maal = Date.parse(process.env.FALSK_KLOKKE || '');
if (!Number.isNaN(maal)) {
  const Ekte = Date, avstand = maal - Ekte.now();
  class Falsk extends Ekte {
    constructor(...a) { if (a.length) super(...a); else super(Ekte.now() + avstand); }
    static now() { return Ekte.now() + avstand; }
  }
  global.Date = Falsk;
}
