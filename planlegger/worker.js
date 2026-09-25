/**
 * Ekstern utløser for GitHub Actions.
 *
 * HVORFOR: GitHub sin egen cron er sterkt strupet for dette repoet. Målt over
 * fem døgn i september 2026 fyrte update-data 27 av 233 planlagte luker
 * (12 %), med median 251 minutter mellom kjøringer der cronen ber om 20.
 * update-odds fyrte 9 av 10 luker, men 3 til 7 timer for sent.
 * workflow_dispatch går derimot umiddelbart.
 *
 * Denne workeren gjør derfor én ting: den sender workflow_dispatch hvert
 * tiende minutt. GitHub forblir eneste produksjonsmiljø — ingenting regnes ut
 * her, ingen data lagres her.
 *
 * WORKEREN ER DUM MED VILJE. All kunnskap om kampvinduer, porter og kvoter
 * ligger i repoet, der den kan testes og versjoneres. Legger vi vinduslogikk
 * her, har vi to steder å holde i synk og ett av dem uten tester.
 *
 * planlagt=true forteller workflowen at dette er en planlagt kjøring, ikke et
 * menneske som vil ha data nå: porten og kampvinduet skal gjelde som ved
 * schedule. En manuell kjøring uten flagget tvinger fortsatt henting.
 *
 * GitHub sin egen schedule beholdes parallelt som reserve. Faller workeren
 * ut, går kjeden tilbake til dagens (dårlige, men fungerende) kadens.
 */

const EIER = "fiskentnt";
const REPO = "eliteserien";

// Rekkefølgen er bevisst: arkiveringen først, fordi den er den eneste som er
// tidskritisk. Den skal fange markup mens en kamp pågår.
const WORKFLOWS = [
  // prekick foerst: den har et vindu paa 45 minutter og er den eneste her
  // som virkelig ikke taaler aa vente.
  "prekick-odds.yml",
  "arkiver-kildehtml.yml",
  "update-data.yml",
  "obos-results.yml",
];

// Timer (UTC) da vi utløser. 09–21 UTC dekker 12–23 norsk tid både sommer
// (UTC+2) og vinter (UTC+1), uten å måtte kjenne til sommertidsomlegging.
const FRA_TIME = 9;
const TIL_TIME = 21;

async function dispatch(workflow, gren, token) {
  const svar = await fetch(
    `https://api.github.com/repos/${EIER}/${REPO}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tabellkalkulator-planlegger",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: gren, inputs: { planlagt: "true" } }),
    },
  );
  // 204 er suksess. Alt annet logges med kropp, ellers står vi igjen med et
  // tall og ingen anelse om hvorfor.
  const tekst = svar.status === 204 ? "" : await svar.text();
  return { workflow, status: svar.status, ok: svar.status === 204, tekst };
}

function likeStrenger(a, b) {
  // Konstant tid: en vanlig === returnerer med en gang ved første ulike tegn,
  // og lekker dermed hvor langt en gjetning kom.
  const ab = new TextEncoder().encode(a);
  const bb = new TextEncoder().encode(b);
  let ulik = ab.length ^ bb.length;
  const n = Math.max(ab.length, bb.length);
  for (let i = 0; i < n; i++) ulik |= (ab[i] ?? 0) ^ (bb[i] ?? 0);
  return ulik === 0;
}


async function kjor(env) {
  const token = env.GITHUB_TOKEN;
  if (!token) {
    console.log("FEIL: GITHUB_TOKEN mangler som hemmelighet -- gjør ingenting.");
    return [];
  }
  const gren = env.GREN || "main";
  const naa = new Date();
  const time = naa.getUTCHours();
  if (time < FRA_TIME || time > TIL_TIME) {
    console.log(`Utenfor vinduet ${FRA_TIME}-${TIL_TIME} UTC (nå ${time}) -- sender ingenting.`);
    return [];
  }

  const resultater = [];
  for (const w of WORKFLOWS) {
    try {
      resultater.push(await dispatch(w, gren, token));
    } catch (e) {
      resultater.push({ workflow: w, status: 0, ok: false, tekst: String(e) });
    }
  }
  for (const r of resultater) {
    console.log(r.ok ? `OK  ${r.workflow}` : `FEIL ${r.workflow}: ${r.status} ${r.tekst}`);
  }
  return resultater;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(kjor(env));
  },

  // Manuell utløsning. Adressen til en Cloudflare-worker er lett å gjette, og
  // uten nøkkel kunne hvem som helst fylt Actions med kjøringer. Portene
  // hindrer at det gjør skade, men ikke at det lager støy og brenner
  // kjøretid. Derfor kreves en egen hemmelighet, UTLOSER_NOKKEL, i tillegg
  // til GITHUB_TOKEN -- to ulike hemmeligheter, ingen av dem i koden.
  //
  // Nøkkelen sendes i headeren X-Planlegger-Nokkel, ikke i URL-en.
  //
  // Er nøkkelen ikke satt, er manuell utløsning AV. Den skal ikke kunne
  // omgås ved å la være å konfigurere den. scheduled() bryr seg ikke om
  // denne nøkkelen -- den planlagte kjøringen skal virke uansett.
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.searchParams.get("kjor") !== "1") {
      return new Response(`Planlegger for ${EIER}/${REPO}. Ingenting å se her.\n`, {
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }

    // Nøkkelen tas BARE fra en header, aldri fra query-strengen. En
    // query-streng havner i Cloudflare-loggen, i referrer-headeren til alt
    // siden laster, og i nettleserhistorikken -- en header gjør ikke det.
    const fasit = env.UTLOSER_NOKKEL;
    const gitt = request.headers.get("x-planlegger-nokkel") || "";

    // ETT svar for alle avslag: manglende header, feil nøkkel og manglende
    // konfigurasjon ser likt ut utenfra. Ellers ville svaret fortalt en som
    // prøver seg hvor langt hen kom. 404 framfor 401, slik at det heller
    // ikke bekreftes at endepunktet finnes.
    if (!fasit || !likeStrenger(gitt, fasit)) {
      if (!fasit) {
        // Bare i loggen, aldri i svaret -- og aldri nøkkelen selv.
        console.log("Manuell utløsning avvist: UTLOSER_NOKKEL er ikke satt.");
      }
      return new Response("Ikke funnet.\n", {
        status: 404,
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }

    const r = await kjor(env);
    return new Response(JSON.stringify(r, null, 1), {
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  },
};
