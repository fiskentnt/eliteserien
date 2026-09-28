#!/usr/bin/env python3
"""Norsk klokkeslett for planlagte kjøringer, uavhengig av sommertid.

GitHub sin cron er i UTC. En jobb som skal gå på et norsk klokkeslett (for
eksempel obos-results.yml kl. 07.17) har derfor to cron-linjer: én for
sommertid (UTC+2) og én for vintertid (UTC+1). Dette skriptet avgjør hvilken
av dem som gjelder i dag; den andre avslutter med en gang.

Det er den PLANLAGTE tiden som avgjør (cron-linja som utløste kjøringen,
github.event.schedule), ikke når jobben faktisk startet. GitHub sin cron er
ofte forsinket, målt opptil flere timer, og en forsinket kjøring skal ikke
gå tapt. Regelen: timen i cron-linja pluss dagens forskyvning i Europe/Oslo
skal være den norske timen jobben skal gå i.

Andre hendelser (workflow_dispatch fra planleggeren eller manuelt) kjører
alltid.

Ingen avhengigheter utover standardbiblioteket.

Bruk:  python3 scripts/norsk_klokke.py <norsk time>
  Miljø:  HENDELSE    github.event_name
          PLAN        github.event.schedule (cron-linja)
          KLOKKE_NAA  ISO-tid, BARE for testene (falsk klokke)
  Skriver kjor=true|false til GITHUB_OUTPUT.
"""
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")


def utc_time(plan):
    """UTC-timen i en cron-linje «M H ...». Timen er ett tall i linjene
    dette brukes for."""
    return int(plan.split()[1])


def skal_kjore(hendelse, plan, norsk_time, naa):
    """(kjør, grunn). naa er et tidspunkt med tidssone."""
    if hendelse != "schedule":
        return True, f"{hendelse}: kjører alltid"
    if not plan:
        return True, "planlagt kjøring uten cron-linje: kjører"
    t = utc_time(plan)
    forskyvning = int(naa.astimezone(OSLO).utcoffset().total_seconds() // 3600)
    lokal = (t + forskyvning) % 24
    if lokal == norsk_time:
        return True, (f"cron «{plan}»: {t:02d} UTC er {lokal:02d} norsk tid "
                      f"(UTC+{forskyvning}) -- kjører")
    return False, (f"cron «{plan}»: {t:02d} UTC er {lokal:02d} norsk tid (UTC+{forskyvning}), "
                   f"ikke {norsk_time:02d} -- den andre cron-linja gjelder nå, avslutter")


def main(argv):
    norsk_time = int(argv[0])
    naa = datetime.fromisoformat(os.environ["KLOKKE_NAA"]) if os.environ.get("KLOKKE_NAA") \
        else datetime.now(timezone.utc)
    if naa.tzinfo is None:
        naa = naa.replace(tzinfo=timezone.utc)
    kjor, grunn = skal_kjore(os.environ.get("HENDELSE", ""), os.environ.get("PLAN", ""), norsk_time, naa)
    print(grunn, file=sys.stderr)
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"kjor={'true' if kjor else 'false'}\n")
    print(f"kjor={'true' if kjor else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
