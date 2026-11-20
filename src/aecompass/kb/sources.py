"""The official pages the agent may quote from about triage, A&E fees and where to seek care.

All are Hong Kong Government press releases on info.gov.hk (statements by the Hospital Authority or the
Health Bureau), plus the fee table published as an annex to one of them. The Hospital Authority's own
website could not be reached from the development machine (DECISIONS.md D1), so its triage and fee pages
are not included; these press releases state the same rules.

Only this list is committed to the repository. The page text is downloaded to `data/kb/` (git-ignored) by
`python -m aecompass.kb.build` and is not redistributed.
"""

from __future__ import annotations

from dataclasses import dataclass

BASE = "https://www.info.gov.hk/gia/general/"


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    publisher: str
    date: str  # date of the press release, YYYY-MM-DD
    url: str
    about: str  # why it is in the knowledge base
    kind: str = "html"  # "html" press release, or "pdf" annex
    old_fees: bool = False  # describes fees and refunds as they were before the 1 Jan 2026 change


SOURCES = [
    Source("fee-list-2026", "Hospital Authority List of Major Public Healthcare Fees & Charges for Eligible Persons (effective 1 January 2026)",
           "Hospital Authority", "2026-01-01", "https://gia.info.gov.hk/general/202601/01/P2026010100712_527081_1_1767268893643.pdf",
           "The fee table itself: A&E, clinics, inpatient; annex to the 1 Jan 2026 press release", kind="pdf"),
    Source("fee-reform-day1", "Hospital Authority successfully implements public healthcare fees and charges reform",
           "Hospital Authority", "2026-01-01", BASE + "202601/01/P2026010100712.htm",
           "A&E fee from 1 Jan 2026, who is exempt, refunds"),
    Source("fee-schedule-gazetted", "Fee schedule for public healthcare services gazetted to take effect on January 1 next year",
           "Hospital Authority", "2025-04-25", BASE + "202504/25/P2025042500709.htm",
           "The gazetted fee schedule and medical fee waivers"),
    Source("lcq7-fee-reform", "LCQ7: Implementation of fees and charges reform for public healthcare",
           "Health Bureau", "2026-01-28", BASE + "202601/28/P2026012800253.htm",
           "How the reform is working: attendances, waivers, refunds"),
    Source("lcq19-fee-reform", "LCQ19: Implementation and effectiveness of public healthcare fees and charges reform",
           "Health Bureau", "2026-10-07", BASE + "202610/07/P2026100700432.htm",
           "Later figures on the reform's effect on A&E attendances"),
    Source("lcq22-ae-services", "LCQ22: Services of accident and emergency departments of public hospitals",
           "Health Bureau", "2024-03-20", BASE + "202403/20/P2024032000495.htm",
           "Triage categories, waiting-time pledges, alternatives to A&E at night", old_fees=True),
    Source("lcq14-ae-services", "LCQ14: Services of accident and emergency departments of public hospitals",
           "Health Bureau", "2023-10-18", BASE + "202310/18/P2023101800327.htm",
           "Triage categories, waiting times by category, measures to relieve A&E", old_fees=True),
    Source("surge-measures-2025", "HA activates service demand surge special measures",
           "Hospital Authority", "2025-12-19", BASE + "202512/19/P2025121900497.htm",
           "Advice for people with mild symptoms during the winter surge; clinic options", old_fees=True),
]
BY_ID = {source.id: source for source in SOURCES}
