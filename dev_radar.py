#!/usr/bin/env python3

import csv
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import yaml

from collectors.ashby import fetch_ashby
from collectors.greenhouse import fetch_greenhouse
from collectors.lever import fetch_lever


# ============================================================
# DEV RADAR
# ============================================================

ROOT = Path(__file__).parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

STATE = OUT / "dev_seen.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 DevJobRadar/1.0"
}


# ============================================================
# BASIC HELPERS
# ============================================================

def norm(value):
    return str(value or "").lower().strip()


def contains(text, terms):
    text = norm(text)
    return any(norm(term) in text for term in terms)


def full_text(job):
    return " ".join([
        norm(job.get("titulo")),
        norm(job.get("cidade")),
        norm(job.get("descricao")),
    ])


def strip_html(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ============================================================
# DATE HANDLING
# ============================================================

def parse_date(value):

    if not value:
        return None

    value = str(value).strip()

    try:
        parsed = dt.datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=dt.timezone.utc
            )

        return parsed.astimezone(dt.timezone.utc)

    except Exception:
        pass

    try:
        parsed = parsedate_to_datetime(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=dt.timezone.utc
            )

        return parsed.astimezone(dt.timezone.utc)

    except Exception:
        pass

    try:
        parsed = dt.datetime.strptime(
            value[:10],
            "%Y-%m-%d",
        )

        return parsed.replace(
            tzinfo=dt.timezone.utc
        )

    except Exception:
        return None


def age_hours(job):

    posted = parse_date(
        job.get("publicado_em")
    )

    if not posted:
        return None

    delta = (
        dt.datetime.now(dt.timezone.utc)
        - posted
    )

    return round(
        delta.total_seconds() / 3600,
        1,
    )


def is_fresh(job, hours=48):

    age = age_hours(job)

    return (
        age is not None
        and 0 <= age <= hours
    )


# ============================================================
# BROAD PUBLIC SOURCES
# ============================================================

def fetch_remoteok():

    url = "https://remoteok.com/api"

    r = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    r.raise_for_status()

    jobs = []

    for j in r.json():

        if not isinstance(j, dict):
            continue

        if not j.get("id"):
            continue

        description = (
            strip_html(j.get("description"))
            + " "
            + " ".join(j.get("tags") or [])
        )

        jobs.append({
            "id": f"remoteok:{j.get('id')}",
            "fonte": "remoteok",
            "titulo": j.get("position", ""),
            "empresa": j.get("company", ""),
            "cidade": j.get("location") or "Remote",
            "estado": "",
            "remoto": True,
            "link": j.get("url", ""),
            "descricao": description,
            "publicado_em": j.get("date", ""),
        })

    return jobs


def fetch_remotive():

    url = "https://remotive.com/api/remote-jobs"

    r = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    r.raise_for_status()

    jobs = []

    for j in r.json().get("jobs", []):

        description = (
            strip_html(j.get("description"))
            + " "
            + str(j.get("salary") or "")
        )

        jobs.append({
            "id": f"remotive:{j.get('id')}",
            "fonte": "remotive",
            "titulo": j.get("title", ""),
            "empresa": j.get("company_name", ""),
            "cidade": (
                j.get("candidate_required_location")
                or "Remote"
            ),
            "estado": "",
            "remoto": True,
            "link": j.get("url", ""),
            "descricao": description,
            "publicado_em": (
                j.get("publication_date", "")
            ),
        })

    return jobs


def fetch_wwr():

    url = (
        "https://weworkremotely.com/"
        "remote-jobs.rss"
    )

    r = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    r.raise_for_status()

    root = ET.fromstring(r.content)

    jobs = []

    for item in root.iter("item"):

        raw_title = (
            item.findtext("title") or ""
        ).strip()

        company = ""
        role = raw_title

        if ": " in raw_title:
            company, role = raw_title.split(
                ": ",
                1,
            )

        link = (
            item.findtext("link") or ""
        ).strip()

        jobs.append({
            "id": f"wwr:{link}",
            "fonte": "weworkremotely",
            "titulo": role,
            "empresa": company,
            "cidade": "Remote",
            "estado": "",
            "remoto": True,
            "link": link,
            "descricao": strip_html(
                item.findtext("description")
            ),
            "publicado_em": (
                item.findtext("pubDate")
                or ""
            ),
        })

    return jobs


# ============================================================
# GEOGRAPHY
# ============================================================

INDIA = [
    "india",
    "bengaluru",
    "bangalore",
    "gurgaon",
    "gurugram",
    "mumbai",
    "new delhi",
    "delhi",
    "noida",
    "pune",
    "hyderabad",
    "chennai",
    "kolkata",
    "ahmedabad",
    "indore",
    "jaipur",
    "kochi",
    "coimbatore",
    "chandigarh",
    "surat",
    "vadodara",
]


UK = [
    "united kingdom",
    "london",
    "manchester",
    "birmingham",
    "edinburgh",
    "glasgow",
    "bristol",
    "england",
    "scotland",
    "wales",
    "northern ireland",
]


EUROPE = [
    "austria",
    "vienna",
    "belgium",
    "brussels",
    "bulgaria",
    "sofia",
    "croatia",
    "zagreb",
    "cyprus",
    "czechia",
    "czech republic",
    "prague",
    "denmark",
    "copenhagen",
    "estonia",
    "tallinn",
    "finland",
    "helsinki",
    "france",
    "paris",
    "germany",
    "berlin",
    "munich",
    "hamburg",
    "frankfurt",
    "greece",
    "athens",
    "hungary",
    "budapest",
    "iceland",
    "ireland",
    "dublin",
    "italy",
    "milan",
    "rome",
    "latvia",
    "riga",
    "liechtenstein",
    "lithuania",
    "vilnius",
    "luxembourg",
    "malta",
    "netherlands",
    "amsterdam",
    "rotterdam",
    "norway",
    "oslo",
    "poland",
    "warsaw",
    "krakow",
    "portugal",
    "lisbon",
    "porto",
    "romania",
    "bucharest",
    "slovakia",
    "bratislava",
    "slovenia",
    "ljubljana",
    "spain",
    "madrid",
    "barcelona",
    "sweden",
    "stockholm",
    "switzerland",
    "zurich",
    "geneva",
]


GLOBAL_REMOTE = [
    "worldwide",
    "world wide",
    "anywhere in the world",
    "work from anywhere",
    "global remote",
    "remote globally",
    "remote worldwide",
    "anywhere",
]


REMOTE_BLOCKED = [
    "us only",
    "u.s. only",
    "united states only",
    "must be based in the us",
    "must reside in the us",
    "remote - us",
    "remote us",
    "canada only",
    "remote canada",
    "uk only",
    "remote uk",
    "europe only",
    "eu only",
    "emea only",
]


def market(job):

    location = norm(job.get("cidade"))
    text = full_text(job)

    # UK ALWAYS excluded.
    if contains(location, UK):
        return ""

    if contains(location, INDIA):
        return "India"

    if contains(location, EUROPE):
        return "Europe"

    # Some ATS put country only in description.
    if contains(text[:5000], INDIA):
        return "India"

    # Remote jobs must actually look globally accessible.
    if job.get("remoto"):

        if contains(text, REMOTE_BLOCKED):
            return ""

        if contains(text, GLOBAL_REMOTE):
            return "Global Remote"

        # Explicit India eligibility.
        if "india" in text:
            return "India"

    return ""


# ============================================================
# EUROPE VISA
# ============================================================

VISA_YES = [
    "visa sponsorship",
    "visa support",
    "work visa sponsorship",
    "sponsorship available",
    "sponsor visas",
    "sponsor a visa",
    "immigration support",
    "relocation and visa",
    "relocation support",
    "global mobility",
]


VISA_NO = [
    "no visa sponsorship",
    "unable to sponsor",
    "cannot sponsor",
    "no sponsorship available",
    "must already have the right to work",
    "must have the right to work",
    "existing right to work",
    "without sponsorship",
]


LIKELY_SPONSORS = [
    "deel",
    "remote",
    "revolut",
    "wise",
    "datadog",
    "cloudflare",
    "mongodb",
    "notion",
    "miro",
    "typeform",
    "commercetools",
    "rippling",
]


def visa_check(job, job_market):

    if job_market == "India":
        return "NOT REQUIRED", True

    if job_market == "Global Remote":
        return "REMOTE FROM INDIA", True

    text = full_text(job)

    if contains(text, VISA_NO):
        return "NO", False

    if contains(text, VISA_YES):
        return "SPONSORSHIP", True

    company = norm(job.get("empresa"))

    if any(x in company for x in LIKELY_SPONSORS):
        return "LIKELY", True

    # User asked for sponsorship or VERY likely.
    # Unknown Europe roles therefore do not pass.
    return "UNKNOWN", False


# ============================================================
# HARD EXCLUSIONS
# ============================================================

TECH = [
    "software engineer",
    "software developer",
    "developer",
    "devops",
    "site reliability",
    "sre",
    "engineering manager",
    "technical program manager",
    "technical programme manager",
    "technical project manager",
    "technical product manager",
    "solutions architect",
    "cloud engineer",
    "data engineer",
    "data scientist",
    "machine learning",
    "security operations",
    "security engineer",
    "cybersecurity",
    "cyber security",
    "soc analyst",
    "it operations",
    "it support",
    "network engineer",
]


SALES = [
    "account executive",
    "sales executive",
    "sales manager",
    "sales director",
    "head of sales",
    "business development",
    "bd manager",
    "sales development",
    "sales representative",
    "enterprise sales",
    "inside sales",
    "field sales",
    "regional sales",
]


ADMIN = [
    "executive assistant",
    "personal assistant",
    "administrative assistant",
    "receptionist",
    "office assistant",
]


JUNIOR = [
    "intern",
    "internship",
    "graduate trainee",
    "management trainee",
    "junior analyst",
]


SPECIALIST = [
    "accountant",
    "legal counsel",
    "lawyer",
    "payroll",
    "graphic designer",
    "product designer",
]


def hard_reject(job):

    title = norm(job.get("titulo"))

    if contains(title, TECH):
        return "Technical"

    if contains(title, SALES):
        return "Sales / BD"

    if contains(title, ADMIN):
        return "Administrative"

    if contains(title, JUNIOR):
        return "Too junior"

    if contains(title, SPECIALIST):
        return "Specialist function"

    return ""


# ============================================================
# ADMIN-HEAVY CHIEF OF STAFF
# ============================================================

COS_ADMIN = [
    "calendar management",
    "manage calendar",
    "schedule meetings",
    "travel booking",
    "travel arrangements",
    "expense reports",
    "personal errands",
    "administrative support",
]


def admin_cos(job):

    title = norm(job.get("titulo"))

    if not contains(
        title,
        [
            "chief of staff",
            "founder",
            "ceo office",
        ],
    ):
        return False

    body = norm(job.get("descricao"))

    hits = sum(
        term in body
        for term in COS_ADMIN
    )

    return hits >= 2


# ============================================================
# DEV RESPONSIBILITY FIT
# ============================================================

FIT = {

    "Founder/CEO exposure": (
        [
            "work directly with the founder",
            "work closely with the founder",
            "report to the founder",
            "partner with the founder",
            "work directly with the ceo",
            "report directly to the ceo",
            "office of the ceo",
            "office of the founder",
            "founder's office",
            "founders office",
            "executive leadership team",
        ],
        12,
    ),

    "Strategy → execution": (
        [
            "strategic initiatives",
            "strategic priorities",
            "strategy and execution",
            "strategy through execution",
            "translate strategy",
            "execute strategic",
            "drive strategic",
            "business strategy",
            "company strategy",
            "strategic planning",
        ],
        10,
    ),

    "Cross-functional leadership": (
        [
            "cross-functional",
            "cross functional",
            "across functions",
            "multiple functions",
            "senior stakeholders",
            "stakeholder management",
        ],
        7,
    ),

    "P&L / commercial ownership": (
        [
            "p&l",
            "profit and loss",
            "business performance",
            "commercial performance",
            "profitability",
            "unit economics",
            "revenue growth",
            "margin improvement",
        ],
        9,
    ),

    "Operating model / KPIs": (
        [
            "operating model",
            "operating cadence",
            "business cadence",
            "management reporting",
            "business reviews",
            "weekly business review",
            "monthly business review",
            "performance management",
            "kpi",
            "okr",
            "governance",
        ],
        8,
    ),

    "Transformation": (
        [
            "business transformation",
            "transformation program",
            "transformation programme",
            "operational excellence",
            "process improvement",
            "business improvement",
            "cost optimization",
            "cost optimisation",
            "operating efficiency",
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
            "build from scratch",
            "launch new",
            "market expansion",
        ],
        8,
    ),

    "GTM strategy": (
        [
            "go-to-market strategy",
            "go to market strategy",
            "gtm strategy",
            "market entry",
            "international expansion",
        ],
        6,
    ),

    "Portfolio/value creation": (
        [
            "portfolio operations",
            "portfolio companies",
            "value creation",
            "portfolio acceleration",
            "operating partner",
            "portfolio support",
            "portfolio strategy",
        ],
        10,
    ),

    "Executive special projects": (
        [
            "special projects",
            "strategic projects",
            "executive priorities",
            "ceo priorities",
            "founder priorities",
            "mission critical initiatives",
        ],
        8,
    ),
}


TITLE_BONUS = {
    "chief of staff": 12,
    "founder's office": 12,
    "founders office": 12,
    "ceo office": 12,
    "office of the ceo": 12,
    "strategy and operations": 11,
    "strategy & operations": 11,
    "strategic initiatives": 10,
    "business operations": 9,
    "bizops": 9,
    "special projects": 9,
    "corporate strategy": 8,
    "business transformation": 8,
    "portfolio operations": 10,
    "value creation": 10,
    "venture builder": 9,
    "venture lead": 8,
    "business head": 9,
    "general manager": 8,
    "country manager": 8,
    "product strategy": 6,
}


# ============================================================
# EXPERIENCE
# ============================================================

def required_years(job):

    text = full_text(job)

    patterns = [
        r"(\d+)\+\s*years",
        r"(\d+)\+\s*yrs",
        r"at least\s+(\d+)\s+years",
        r"minimum\s+(?:of\s+)?(\d+)\s+years",
    ]

    values = []

    for pattern in patterns:

        for value in re.findall(pattern, text):

            try:
                values.append(int(value))
            except Exception:
                pass

    return min(values) if values else None


# ============================================================
# INDIA COMPENSATION
# ============================================================

def india_salary(job):

    text = full_text(job)

    patterns = [
        r"₹\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakh|lakhs)",
        r"inr\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakh|lakhs)",
        r"(\d+(?:\.\d+)?)\s*lpa",
    ]

    values = []

    for pattern in patterns:

        for x in re.findall(
            pattern,
            text,
            flags=re.I,
        ):

            try:
                value = float(x)

                if 10 <= value <= 300:
                    values.append(value)

            except Exception:
                pass

    return max(values) if values else None


EQUITY = [
    "equity",
    "esop",
    "esops",
    "stock options",
    "employee stock",
]


def compensation(job, job_market):

    if job_market != "India":
        return "UNKNOWN", True

    salary = india_salary(job)

    if salary is None:
        return "UNKNOWN", True

    if salary >= 40:
        return f"₹{salary:g}L+ indicated", True

    if salary >= 35 and contains(
        full_text(job),
        EQUITY,
    ):
        return f"₹{salary:g}L + equity", True

    return f"₹{salary:g}L indicated", False


# ============================================================
# SCORE
# ============================================================

def score(job, job_market, visa):

    text = full_text(job)
    title = norm(job.get("titulo"))

    total = 0
    reasons = []
    concerns = []

    responsibility = 0

    for label, (terms, points) in FIT.items():

        if contains(text, terms):

            responsibility += points
            reasons.append(label)

    responsibility = min(
        responsibility,
        40,
    )

    # Actual work matters most.
    if responsibility < 14:
        return 0, reasons, [
            "Insufficient responsibility fit"
        ]

    total += responsibility

    # Title is only a bonus.
    title_points = 0

    for phrase, points in TITLE_BONUS.items():

        if phrase in title:
            title_points = max(
                title_points,
                points,
            )

    total += title_points

    # Experience.
    years = required_years(job)

    if years is None:
        total += 8

    elif years <= 7:
        total += 15

    elif years <= 8:
        total += 13

    elif years <= 10:
        total += 9
        concerns.append(
            f"JD asks {years}+ years"
        )

    elif years <= 11:

        if responsibility >= 28:
            total += 3
            concerns.append(
                f"Stretch: {years}+ years"
            )
        else:
            return 0, reasons, [
                f"Too senior: {years}+ years"
            ]

    else:
        return 0, reasons, [
            f"Normally exclude: {years}+ years"
        ]

    # Founder/executive exposure.
    if contains(
        text,
        [
            "founder",
            "ceo",
            "chief executive",
            "executive leadership",
        ],
    ):
        total += 10

    # Geography/work rights.
    if job_market == "India":
        total += 10

    elif job_market == "Europe":

        if visa == "SPONSORSHIP":
            total += 10
        else:
            total += 7

    elif job_market == "Global Remote":
        total += 9

    # Compensation.
    salary, ok = compensation(
        job,
        job_market,
    )

    if not ok:
        return 0, reasons, [salary]

    if salary == "UNKNOWN":
        total += 5
        concerns.append(
            "Compensation not published"
        )
    else:
        total += 10

    # Freshness.
    age = age_hours(job)

    if age is not None:

        if age <= 12:
            total += 5
        elif age <= 24:
            total += 4
        elif age <= 36:
            total += 3
        else:
            total += 2

    # Penalise disguised technical work.
    if contains(
        norm(job.get("descricao")),
        [
            "software development lifecycle",
            "site reliability engineering",
            "technical architecture",
            "cloud infrastructure",
            "security operations center",
            "security operations centre",
        ],
    ):
        total -= 30
        concerns.append(
            "Technical delivery content"
        )

    # Penalise disguised quota sales.
    if contains(
        norm(job.get("descricao")),
        [
            "sales quota",
            "quota-carrying",
            "quota carrying",
            "cold calling",
            "prospecting",
            "close deals",
        ],
    ):
        total -= 35
        concerns.append(
            "Sales/quota content"
        )

    return (
        max(0, min(round(total), 100)),
        reasons[:5],
        concerns[:4],
    )


# ============================================================
# ACTION
# ============================================================

def action(score_value):

    if score_value >= 85:
        return "APPLY TODAY"

    if score_value >= 75:
        return "STRONG - REVIEW TODAY"

    if score_value >= 65:
        return "REVIEW"

    return "IGNORE"


# ============================================================
# COLLECTION
# ============================================================

def collect(cfg):

    jobs = []

    # --------------------------------------------------------
    # Direct company ATS boards
    # --------------------------------------------------------

    collectors = [
        ("ashby", fetch_ashby),
        ("greenhouse", fetch_greenhouse),
        ("lever", fetch_lever),
    ]

    for source, fn in collectors:

        for company in (
            cfg.get("sources", {})
            .get(source, [])
        ):

            try:

                found = fn(company)

                jobs.extend(found)

                print(
                    f"[{source}] "
                    f"{company}: "
                    f"{len(found)}"
                )

            except Exception as exc:

                print(
                    f"[WARNING] "
                    f"{source}/{company}: "
                    f"{exc}"
                )

    # --------------------------------------------------------
    # Broad market feeds
    # --------------------------------------------------------

    broad_sources = [
        ("remoteok", fetch_remoteok),
        ("remotive", fetch_remotive),
        ("weworkremotely", fetch_wwr),
    ]

    for name, fn in broad_sources:

        try:

            found = fn()

            jobs.extend(found)

            print(
                f"[{name}] "
                f"{len(found)}"
            )

        except Exception as exc:

            print(
                f"[WARNING] "
                f"{name}: "
                f"{exc}"
            )

    return jobs


# ============================================================
# MAIN
# ============================================================

def main():

    cfg = yaml.safe_load(
        (
            ROOT / "dev_config.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    freshness = (
        cfg.get("candidate", {})
        .get("freshness_hours", 48)
    )

    target = (
        cfg.get("candidate", {})
        .get("daily_target", 20)
    )

    # --------------------------------------------------------
    # Memory
    # --------------------------------------------------------

    if STATE.exists():

        try:

            seen = set(
                json.loads(
                    STATE.read_text(
                        encoding="utf-8"
                    )
                )
            )

        except Exception:
            seen = set()

    else:
        seen = set()

    # --------------------------------------------------------
    # Collect
    # --------------------------------------------------------

    raw = collect(cfg)

    # --------------------------------------------------------
    # Deduplicate
    # --------------------------------------------------------

    unique = {}

    for job in raw:

        jid = (
            job.get("id")
            or job.get("link")
        )

        if jid:
            unique[str(jid)] = job

    counters = {
        "fresh": 0,
        "geography": 0,
        "visa": 0,
        "role": 0,
        "fit65": 0,
        "fit75": 0,
        "fit85": 0,
    }

    candidates = []

    # --------------------------------------------------------
    # Eligibility funnel
    # --------------------------------------------------------

    for jid, job in unique.items():

        # STRICT <=48h
        if not is_fresh(
            job,
            freshness,
        ):
            continue

        counters["fresh"] += 1

        # INDIA / EU-EEA-SWISS / TRUE GLOBAL REMOTE
        job_market = market(job)

        if not job_market:
            continue

        counters["geography"] += 1

        # VISA
        visa, visa_ok = visa_check(
            job,
            job_market,
        )

        if not visa_ok:
            continue

        counters["visa"] += 1

        # HARD ROLE EXCLUSIONS
        rejection = hard_reject(job)

        if rejection:
            continue

        # ADMIN-HEAVY COS
        if admin_cos(job):
            continue

        counters["role"] += 1

        # SCORE
        fit, reasons, concerns = score(
            job,
            job_market,
            visa,
        )

        if fit < 65:
            continue

        counters["fit65"] += 1

        if fit >= 75:
            counters["fit75"] += 1

        if fit >= 85:
            counters["fit85"] += 1

        # DEDUPE BETWEEN DAYS
        if jid in seen:
            continue

        salary, _ = compensation(
            job,
            job_market,
        )

        candidates.append({
            "score": fit,
            "posted": job.get(
                "publicado_em",
                "",
            ),
            "age_hours": age_hours(job),
            "company": job.get(
                "empresa",
                "",
            ),
            "role": job.get(
                "titulo",
                "",
            ),
            "location": job.get(
                "cidade",
                "",
            ),
            "market": job_market,
            "salary": salary,
            "visa": visa,
            "why_you_fit": "; ".join(
                reasons
            ),
            "concern": (
                "; ".join(concerns)
                if concerns
                else "None identified"
            ),
            "action": action(fit),
            "source": job.get(
                "fonte",
                "",
            ),
            "job_link": job.get(
                "link",
                "",
            ),
            "status": "NEW",
            "id": jid,
        })

    # --------------------------------------------------------
    # Ranking
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: (
            x["score"],
            -(x["age_hours"] or 999),
        ),
        reverse=True,
    )

    # If >=20 strong jobs exist, show ALL strong jobs.
    strong = [
        x
        for x in candidates
        if x["score"] >= 75
    ]

    if len(strong) >= target:
        selected = strong
    else:
        # Never manufacture weak jobs just to reach 20.
        selected = candidates[:target]

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------

    today = (
        dt.datetime.now(
            dt.timezone.utc
        )
        .date()
        .isoformat()
    )

    path = (
        OUT
        / f"dev_radar_{today}.csv"
    )

    fields = [
        "score",
        "posted",
        "age_hours",
        "company",
        "role",
        "location",
        "market",
        "salary",
        "visa",
        "why_you_fit",
        "concern",
        "action",
        "source",
        "job_link",
        "status",
        "id",
    ]

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()
        writer.writerows(selected)

    # Remember only jobs actually surfaced.
    seen.update(
        row["id"]
        for row in selected
    )

    STATE.write_text(
        json.dumps(
            sorted(seen),
            indent=2,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    print()
    print(
        "============== DEV RADAR =============="
    )

    print(
        f"Raw jobs collected:       {len(raw)}"
    )

    print(
        f"Unique jobs:              {len(unique)}"
    )

    print(
        f"Fresh <=48h:              {counters['fresh']}"
    )

    print(
        f"Eligible geography:       {counters['geography']}"
    )

    print(
        f"Visa/work rights passed:  {counters['visa']}"
    )

    print(
        f"Role exclusions passed:   {counters['role']}"
    )

    print(
        f"Fit >=65:                 {counters['fit65']}"
    )

    print(
        f"Strong >=75:              {counters['fit75']}"
    )

    print(
        f"Exceptional >=85:         {counters['fit85']}"
    )

    print(
        f"NEW jobs surfaced:        {len(selected)}"
    )

    print(
        f"Output:                   {path}"
    )

    print(
        "======================================="
    )

    for row in selected:

        print()

        print(
            f'{row["score"]}/100 | '
            f'{row["action"]}'
        )

        print(
            f'{row["company"]} | '
            f'{row["role"]}'
        )

        print(
            f'{row["location"]} | '
            f'{row["market"]} | '
            f'Visa: {row["visa"]}'
        )

        print(
            f'Why: {row["why_you_fit"]}'
        )

        print(
            f'Concern: {row["concern"]}'
        )


if __name__ == "__main__":
    main()
