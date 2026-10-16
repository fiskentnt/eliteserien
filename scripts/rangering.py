#!/usr/bin/env python3
"""Rangeringen på tabellen etter NFFs kampreglement § 5-3 (16.10.2026).

Turneringsbestemmelsene for Eliteserien og OBOS-ligaen 2026 sier i pkt. 4.1 d):
«Lagenes plassering på tabellen reguleres av Kampreglementet § 5-3.»
§ 5-3 (Lovdata, NFFFOR-2014-03-09-1, sist endret 24.02.2026):

  (1) poengtallet
  (2) flest kamper laget har møtt til -- gjelder bare walkover, og er ikke med her
  (3) målforskjell
  (4) flest scorede mål
  (5) innbyrdes oppgjør. To lag: «resultatet av innbyrdes kamper er avgjørende».
      Tre eller flere: «en tabell satt opp etter de innbyrdes oppgjør mellom
      disse lagene».
  (6) fortsatt likt, og det gjelder mesterskap eller opp- /nedrykk:
      kvalifiseringsspill

TOLKNINGEN FOR TO LAG (vår lesning, ikke NFFs ordlyd): «resultatet av innbyrdes
kamper» leses som en minitabell av kampene mellom de to, slik (5) sier for tre
eller flere: poeng, så målforskjell, så scorede mål i de kampene. Bortemål
teller ikke; verken § 5-3 eller turneringsbestemmelsene nevner dem.
Minitabellen settes opp én gang for hele gruppen som står likt på poeng,
målforskjell og scorede mål. Lag som fortsatt står likt i den, rangeres etter
navn her (i virkeligheten kvalifiseringsspill etter (6) når det gjelder
mesterskap eller opp- og nedrykk).

Poengtrekk fra NFF (justeringer.json) ligger i poengene i (1), men ikke i
minitabellen: den teller bare kampene.

Samme regel på sidene: rangerTabell() i eliteserien/index.html (og dermed
obos/index.html) og elo-test/index.html. Kildetestene sjekker at de gir samme
rekkefølge som denne.
"""


def minitabell(gruppe, kamper):
    """{lag: (poeng, målforskjell, scorede mål)} i kampene mellom lagene i gruppe."""
    med = set(gruppe)
    t = {n: [0, 0, 0] for n in gruppe}
    for m in kamper:
        if m.get("hg") is None or m.get("ag") is None or m["home"] not in med or m["away"] not in med:
            continue
        h, a = t[m["home"]], t[m["away"]]
        h[1] += m["hg"] - m["ag"]; a[1] += m["ag"] - m["hg"]
        h[2] += m["hg"]; a[2] += m["ag"]
        if m["hg"] > m["ag"]:
            h[0] += 3
        elif m["hg"] < m["ag"]:
            a[0] += 3
        else:
            h[0] += 1; a[0] += 1
    return {n: tuple(v) for n, v in t.items()}


def rekkefolge(lag, kamper, poeng, malforskjell, scoret):
    """Lagene i tabellrekkefølge.

    lag: navnene. poeng, malforskjell, scoret: {lag: tall}, poengene med
    eventuelle poengtrekk. kamper: de spilte kampene tabellen bygger på
    ({home, away, hg, ag}); kamper uten resultat hoppes over."""
    nokkel = lambda n: (poeng[n], malforskjell[n], scoret[n])
    ordnet = sorted(lag, key=lambda n: (-poeng[n], -malforskjell[n], -scoret[n], n))
    ut, i = [], 0
    while i < len(ordnet):
        j = i + 1
        while j < len(ordnet) and nokkel(ordnet[j]) == nokkel(ordnet[i]):
            j += 1
        gruppe = ordnet[i:j]
        if len(gruppe) > 1:
            mini = minitabell(gruppe, kamper)
            gruppe = sorted(gruppe, key=lambda n: (-mini[n][0], -mini[n][1], -mini[n][2], n))
        ut += gruppe
        i = j
    return ut
