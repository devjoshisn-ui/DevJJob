#!/usr/bin/env python3
"""
Dev Radar V2
Fresh job discovery + relevance scoring for Dev Joshi.

Rules:
- Jobs must be <= 48 hours old
- India priority
- Europe accepted
- Global remote accepted where plausible
- Business/founder/strategy/operations roles prioritised
- Technical, engineering, security, IT and specialist roles rejected
- Previously surfaced jobs deduplicated
"""

import csv
import datetime as dt
import json
from pathlib import Path

import yaml

from collectors.ashby import fetch_ashby
from collectors.greenhouse import fetch_greenhouse
from collectors.lever import fetch_lever


ROOT = Path(__file__).parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

STATE = OUT / "dev_seen.json"


# ---------------------------------------------------------
# DATE / FRESHNESS
# ---------------------------------------------------------

def parse_date(value):
    if not value:
        return None

    try:
        value = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)

        return parsed.astimezone(dt.timezone.utc)

    except ValueError:
        try:
            return dt.datetime.fromisoformat(
                value[:10]
            ).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def age_hours(job):
    posted = parse_date(job.get("publicado_em", ""))

    if not posted:
        return None

    delta = dt.datetime.now(dt.timezone.utc) - posted
    return round(delta.total_seconds() / 3600, 1)


def is_fresh(job, hours):
    age = age_hours(job)
    return age is not None and 0 <= age <= hours


# ---------------------------------------------------------
# GEOGRAPHY
# ---------------------------------------------------------

INDIA_TERMS = [
    "india",
    "bengaluru",
    "bangalore",
    "gurugram",
    "gurgaon",
    "mumbai",
    "delhi",
    "new delhi",
    "pune",
    "hyderabad",
    "chennai",
    "noida",
    "ahmedabad",
    "indore",
    "jaipur",
    "kolkata",
    "kochi",
    "coimbatore",
    "chandigarh",
    "vadodara",
    "surat",
]

EUROPE_TERMS = [
    "europe",
    "emea",
    "germany",
    "berlin",
    "munich",
    "netherlands",
    "amsterdam",
    "france",
    "paris",
    "spain",
    "madrid",
    "barcelona",
    "portugal",
    "lisbon",
    "ireland",
    "dublin",
    "sweden",
    "stockholm",
    "denmark",
    "copenhagen",
    "finland",
    "helsinki",
    "norway",
    "oslo",
    "switzerland",
    "zurich",
    "austria",
    "vienna",
    "belgium",
    "brussels",
    "poland",
    "warsaw",
    "czech",
    "prague",
    "estonia",
    "tallinn",
    "italy",
    "milan",
    "romania",
    "bucharest",
    "luxembourg",
]


def relevant_market(job):
    location = (job.get("cidade") or "").lower()
    description = (job.get("descricao") or "").lower()

    text = location + " " + description[:3000]

    if any(term in text for term in INDIA_TERMS):
        return "India"

    if any(term in text for term in EUROPE_TERMS):
        return "Europe"

    if any(
        term in text
        for term in [
            "worldwide",
            "work from anywhere",
            "remote globally",
            "global remote",
            "anywhere in the world",
        ]
    ):
        return "Global Remote"

    return ""


# ---------------------------------------------------------
# HARD REJECTIONS
# ---------------------------------------------------------

HARD_REJECT_TITLE = [
    # Engineering / technical
    "software engineer",
    "software developer",
    "developer",
    "devops",
    "site reliability",
    "sre",
    "engineering manager",
    "technical program manager",
    "technical project manager",
    "technical product manager",
    "solutions architect",
    "cloud engineer",
    "data engineer",
    "data scientist",
    "machine learning engineer",

    # Security / IT
    "security operations",
    "security engineer",
    "cyber security",
    "cybersecurity",
    "soc analyst",
    "it operations",
    "it support",
    "systems administrator",
    "network engineer",

    # Specialist functions
    "accountant",
    "legal counsel",
    "lawyer",
    "tax manager",
    "payroll",
    "recruiter",
    "talent acquisition",
    "graphic designer",
    "product designer",

    # Junior
    "intern",
    "internship",
    "graduate trainee",
    "junior analyst",
    "management trainee",

    # EA / admin
    "executive assistant",
    "personal assistant",
    "administrative assistant",
    "office assistant",
    "receptionist",
]


# ---------------------------------------------------------
# POSITIVE ROLE SIGNALS
# ---------------------------------------------------------

TITLE_SIGNALS = {
    "chief of staff": 35,
    "founder's office": 35,
    "founders office": 35,
    "founder office": 35,
    "ceo office": 32,
    "office of the ceo": 32,
    "promoter office": 32,

    "strategy and operations": 32,
    "strategy & operations": 32,
    "strategic operations": 28,

    "strategic initiatives": 28,
    "special projects": 27,
    "business operations": 27,
    "bizops": 27,

    "business transformation": 25,
    "transformation lead": 25,
    "transformation manager": 22,

    "commercial strategy": 24,
    "corporate strategy": 25,

    "business head": 25,
    "general manager": 20,
    "country manager": 20,

    "portfolio operations": 28,
    "portfolio strategy": 25,
    "value creation": 28,

    "venture builder": 27,
    "venture lead": 25,
    "venture development": 22,

    "operating partner": 25,
    "operations lead": 18,
    "operations manager": 14,

    "program manager": 10,
    "programme manager": 10,
}


# ---------------------------------------------------------
# DESCRIPTION SIGNALS
# ---------------------------------------------------------

DESCRIPTION_SIGNALS = {
    "Founder/CEO exposure": (
        [
            "work directly with the founder",
            "work closely with the founder",
            "partner with the founder",
            "report to the founder",
            "report directly to the ceo",
            "work directly with the ceo",
            "office of the ceo",
            "leadership team",
        ],
        12,
    ),

    "Strategy to execution": (
        [
            "strategy and execution",
            "strategic initiatives",
            "strategic priorities",
            "translate strategy",
            "execution of strategic",
            "cross-functional initiatives",
        ],
        10,
    ),

    "P&L / commercial": (
        [
            "p&l",
            "profit and loss",
            "revenue growth",
            "commercial strategy",
            "commercial performance",
            "unit economics",
            "profitability",
        ],
        9,
    ),

    "Operating systems": (
        [
            "operating model",
            "operating cadence",
            "business cadence",
            "kpi",
            "okr",
            "management reporting",
            "performance management",
        ],
        8,
    ),

    "Cross-functional leadership": (
        [
            "cross-functional",
            "cross functional",
            "stakeholder management",
            "multiple functions",
            "across functions",
        ],
        7,
    ),

    "Business building": (
        [
            "0 to 1",
            "zero to one",
            "new business",
            "new venture",
            "business building",
            "launch new",
            "go-to-market",
            "go to market",
        ],
        8,
    ),

    "Transformation": (
        [
            "transformation",
            "process improvement",
            "operational excellence",
            "business improvement",
            "cost optimization",
            "cost optimisation",
        ],
        7,
    ),

    "International": (
        [
            "international expansion",
            "global expansion",
            "multiple markets",
            "new markets",
            "international markets",
        ],
        5,
    ),
}


# ---------------------------------------------------------
# NEGATIVE SIGNALS
# ---------------------------------------------------------

NEGATIVE_DESCRIPTION_SIGNALS = {
    "Technical role": (
        [
            "software development lifecycle",
            "engineering teams",
            "software engineering",
            "technical architecture",
            "cloud infrastructure",
            "site reliability engineering",
            "production systems",
            "technical roadmap",
        ],
        -35,
    ),

    "Security role": (
        [
            "security operations center",
            "security operations centre",
            "incident response",
            "cybersecurity",
            "threat detection",
            "security monitoring",
            "soc team",
        ],
        -45,
    ),

    "IT role": (
        [
            "it infrastructure",
            "information technology",
            "network infrastructure",
            "systems administration",
        ],
        -35,
    ),

    "Pure finance/investment": (
        [
            "financial modelling",
            "financial modeling",
            "investment banking",
            "equity research",
            "valuation models",
            "deal execution",
            "due diligence models",
        ],
        -15,
    ),

    "Administrative": (
        [
            "calendar management",
            "manage calendar",
            "travel booking",
            "schedule meetings",
            "administrative support",
        ],
        -35,
    ),
}


# ---------------------------------------------------------
# SCORING
# ---------------------------------------------------------

def rank(job):
    title = (job.get("titulo") or "").lower()
    body = (job.get("descricao") or "").lower()

    # Immediate rejection
    for bad_title in HARD_REJECT_TITLE:
        if bad_title in title:
            return 0, [], f"Rejected: {bad_title}"

    score = 0
    reasons = []

    # Title score
    title_score = 0

    for signal, points in TITLE_SIGNALS.items():
        if signal in title:
            title_score = max(title_score, points)

    if title_score == 0:
        return 0, [], "No relevant title signal"

    score += title_score

    # Description positives
    for label, (terms, points) in DESCRIPTION_SIGNALS.items():
        if any(term in body for term in terms):
            score += points
            reasons.append(label)

    # Description negatives
    negative_reasons = []

    for label, (terms, penalty) in NEGATIVE_DESCRIPTION_SIGNALS.items():
        if any(term in body for term in terms):
            score += penalty
            negative_reasons.append(label)

    # Geography bonus
    market = relevant_market(job)

    if market == "India":
        score += 12
        reasons.append("India priority")

    elif market == "Global Remote":
        score += 8
        reasons.append("Global remote")

    elif market == "Europe":
        score += 6
        reasons.append("Europe")

    # Founder/strategy roles get a slight priority
    if any(
        x in title
        for x in [
            "chief of staff",
            "founder",
            "ceo office",
            "strategic initiatives",
            "strategy and operations",
            "strategy & operations",
        ]
    ):
        score += 8

    score = max(0, min(score, 100))

    concern = "; ".join(negative_reasons)

    return score, reasons[:5], concern


# ---------------------------------------------------------
# VERDICT
# ---------------------------------------------------------

def verdict(score):
    if score >= 85:
        return "APPLY NOW"
    if score >= 70:
        return "STRONG"
    if score >= 55:
        return "REVIEW"
    return "IGNORE"


# ---------------------------------------------------------
# COLLECTION
# ---------------------------------------------------------

def collect(cfg):
    jobs = []

    collectors = [
        ("ashby", fetch_ashby),
        ("greenhouse", fetch_greenhouse),
        ("lever", fetch_lever),
    ]

    for source, fn in collectors:

        for company in cfg["sources"].get(source, []):

            try:
                found = fn(company)
                jobs.extend(found)

                print(
                    f"[{source}] {company}: "
                    f"{len(found)} jobs"
                )

            except Exception as exc:
                print(
                    f"[WARNING] {source}/{company}: {exc}"
                )

    return jobs


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    cfg = yaml.safe_load(
        (ROOT / "dev_config.yaml").read_text()
    )

    freshness_hours = cfg["candidate"]["freshness_hours"]

    if STATE.exists():
        seen = set(json.loads(STATE.read_text()))
    else:
        seen = set()

    raw_jobs = collect(cfg)

    # Deduplicate jobs returned during same run
    unique = {}

    for job in raw_jobs:
        jid = job.get("id") or job.get("link")

        if jid:
            unique[jid] = job

    fresh_count = 0
    scored = []

    for jid, job in unique.items():

        if jid in seen:
            continue

        if not is_fresh(job, freshness_hours):
            continue

        fresh_count += 1

        market = relevant_market(job)

        if not market:
            continue

        score, reasons, concern = rank(job)

        # Do not show weak matches
        if score < 55:
            continue

        scored.append({
            "score": score,
            "verdict": verdict(score),
            "age_hours": age_hours(job),
            "posted": job.get("publicado_em", ""),
            "company": job.get("empresa", ""),
            "role": job.get("titulo", ""),
            "location": job.get("cidade", ""),
            "market": market,
            "source": job.get("fonte", ""),
            "why_fit": "; ".join(reasons),
            "concern": concern,
            "job_link": job.get("link", ""),
            "status": "NEW",
            "id": jid,
        })

    scored.sort(
        key=lambda row: (
            row["score"],
            -(row["age_hours"] or 999)
        ),
        reverse=True,
    )

    # We want 20+, but never pad with junk.
    strong = [
        row
        for row in scored
        if row["score"] >= 70
    ]

    target = cfg["candidate"]["daily_target"]

    number_to_show = max(
        target,
        len(strong)
    )

    selected = scored[:number_to_show]

    # CSV
    today = dt.date.today().isoformat()

    path = OUT / f"dev_radar_{today}.csv"

    fields = [
        "score",
        "verdict",
        "age_hours",
        "posted",
        "company",
        "role",
        "location",
        "market",
        "source",
        "why_fit",
        "concern",
        "job_link",
        "status",
        "id",
    ]

    with path.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(selected)

    # Only mark jobs actually surfaced to Dev as seen
    seen.update(
        row["id"]
        for row in selected
    )

    STATE.write_text(
        json.dumps(
            sorted(seen),
            indent=2
        )
    )

    print()
    print("========= DEV RADAR =========")
    print(f"Jobs collected:       {len(raw_jobs)}")
    print(f"Unique jobs:          {len(unique)}")
    print(f"Fresh <=48h:          {fresh_count}")
    print(f"Relevant >=55:        {len(scored)}")
    print(f"Strong >=70:          {len(strong)}")
    print(f"Surfaced today:       {len(selected)}")
    print(f"Output:               {path}")
    print("=============================")

    for row in selected:
        print()
        print(
            f'{row["score"]} | '
            f'{row["verdict"]} | '
            f'{row["company"]} | '
            f'{row["role"]}'
        )


if __name__ == "__main__":
    main()
