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

  // Manuell sjekk: åpne workerens URL for å se at token og tilgang virker.
  // Sender ingenting med mindre ?kjor=1 er med.
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.searchParams.get("kjor") !== "1") {
      return new Response(
        `Planlegger for ${EIER}/${REPO}.\n` +
          `Utløser ${WORKFLOWS.join(", ")} hvert 10. minutt, ${FRA_TIME}-${TIL_TIME} UTC.\n` +
          `Legg til ?kjor=1 for å sende nå.\n`,
        { headers: { "content-type": "text/plain; charset=utf-8" } },
      );
    }
    const r = await kjor(env);
    return new Response(JSON.stringify(r, null, 1), {
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  },
};
