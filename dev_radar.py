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
# DEV JOB RADAR V5
# ============================================================

ROOT = Path(__file__).parent
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

STATE = OUT / "dev_seen.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DevJobRadar/5.0)"
}


# ============================================================
# BASIC HELPERS
# ============================================================

def norm(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").lower()
    ).strip()


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
    text = re.sub(
        r"<[^>]+>",
        " ",
        str(value or "")
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


# ============================================================
# DATE / FRESHNESS
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

        return parsed.astimezone(
            dt.timezone.utc
        )

    except Exception:
        pass

    try:
        parsed = parsedate_to_datetime(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=dt.timezone.utc
            )

        return parsed.astimezone(
            dt.timezone.utc
        )

    except Exception:
        pass

    try:
        parsed = dt.datetime.strptime(
            value[:10],
            "%Y-%m-%d"
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
        1
    )


def is_fresh(job, hours=48):

    age = age_hours(job)

    return (
        age is not None
        and 0 <= age <= hours
    )


# ============================================================
# BROAD PUBLIC JOB SOURCES
# ============================================================

def fetch_remoteok():

    response = requests.get(
        "https://remoteok.com/api",
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    jobs = []

    data = response.json()

    if not isinstance(data, list):
        return jobs

    for j in data:

        if not isinstance(j, dict):
            continue

        if not j.get("id"):
            continue

        description = " ".join([
            strip_html(j.get("description")),
            " ".join(j.get("tags") or []),
        ])

        jobs.append({
            "id": f"remoteok:{j.get('id')}",
            "fonte": "remoteok",
            "titulo": j.get("position", ""),
            "empresa": j.get("company", ""),
            "cidade": (
                j.get("location")
                or "Remote"
            ),
            "estado": "",
            "remoto": True,
            "link": j.get("url", ""),
            "descricao": description,
            "publicado_em": j.get("date", ""),
        })

    return jobs


def fetch_remotive():

    response = requests.get(
        "https://remotive.com/api/remote-jobs",
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    jobs = []

    for j in response.json().get(
        "jobs",
        []
    ):

        description = " ".join([
            strip_html(j.get("description")),
            f"Salary: {j.get('salary') or ''}",
            (
                "Candidate location: "
                + str(
                    j.get(
                        "candidate_required_location"
                    )
                    or ""
                )
            ),
        ])

        jobs.append({
            "id": f"remotive:{j.get('id')}",
            "fonte": "remotive",
            "titulo": j.get("title", ""),
            "empresa": (
                j.get("company_name", "")
            ),
            "cidade": (
                j.get(
                    "candidate_required_location"
                )
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

    response = requests.get(
        "https://weworkremotely.com/remote-jobs.rss",
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    root = ET.fromstring(
        response.content
    )

    jobs = []

    for item in root.iter("item"):

        raw_title = (
            item.findtext("title") or ""
        ).strip()

        company = ""
        role = raw_title

        if ": " in raw_title:
            company, role = (
                raw_title.split(": ", 1)
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

INDIA_TERMS = [
    "india",
    "bengaluru",
    "bangalore",
    "gurugram",
    "gurgaon",
    "mumbai",
    "delhi",
    "new delhi",
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


# UK IS EXPLICITLY EXCLUDED

UK_TERMS = [
    "united kingdom",
    "great britain",
    "england",
    "scotland",
    "wales",
    "northern ireland",
    "london",
    "manchester",
    "birmingham",
    "edinburgh",
    "glasgow",
    "bristol",
    "cambridge, uk",
    "oxford, uk",
]


EUROPE_TERMS = [
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


GLOBAL_REMOTE_TERMS = [
    "worldwide",
    "world wide",
    "work from anywhere",
    "anywhere in the world",
    "remote worldwide",
    "remote globally",
    "global remote",
    "globally remote",
]


REMOTE_RESTRICTED = [
    "us only",
    "u.s. only",
    "usa only",
    "united states only",
    "remote - us",
    "remote us",
    "north america only",
    "canada only",
    "remote canada",
    "uk only",
    "remote uk",
    "europe only",
    "eu only",
    "emea only",
    "latin america only",
    "latam only",
    "australia only",
]


def classify_market(job):

    location = norm(
        job.get("cidade")
    )

    description = norm(
        job.get("descricao")
    )

    # --------------------------------------------------------
    # UK hard rejection.
    # Location is authoritative.
    # --------------------------------------------------------

    if contains(
        location,
        UK_TERMS
    ):
        return ""

    # --------------------------------------------------------
    # India
    # --------------------------------------------------------

    if contains(
        location,
        INDIA_TERMS
    ):
        return "India"

    # --------------------------------------------------------
    # Continental Europe / EEA / Switzerland
    # --------------------------------------------------------

    if contains(
        location,
        EUROPE_TERMS
    ):
        return "Europe"

    # --------------------------------------------------------
    # Remote
    # --------------------------------------------------------

    if job.get("remoto"):

        combined = (
            location
            + " "
            + description
        )

        if contains(
            combined,
            REMOTE_RESTRICTED
        ):
            return ""

        # Explicitly available from India.
        if (
            "india" in location
            or "india" in description
        ):
            return "India"

        # Explicit global availability.
        if contains(
            combined,
            GLOBAL_REMOTE_TERMS
        ):
            return "Global Remote"

    return ""


# ============================================================
# VISA / WORK RIGHTS
# ============================================================

VISA_POSITIVE = [
    "visa sponsorship",
    "visa support",
    "sponsorship available",
    "work visa sponsorship",
    "sponsor visas",
    "sponsor your visa",
    "immigration support",
    "immigration assistance",
    "relocation and visa",
    "visa and relocation",
    "global mobility",
]


VISA_NEGATIVE = [
    "no visa sponsorship",
    "visa sponsorship is not available",
    "unable to sponsor",
    "cannot sponsor",
    "will not sponsor",
    "without sponsorship",
    "must already have the right to work",
    "must have the right to work",
    "existing right to work",
    "must be authorised to work",
    "must be authorized to work",
]


# Conservative list only.
LIKELY_SPONSOR_COMPANIES = [
    "revolut",
    "wise",
    "deel",
    "remote",
    "datadog",
    "mongodb",
    "cloudflare",
    "miro",
    "typeform",
    "commercetools",
    "rippling",
]


def check_visa(job, market):

    if market == "India":
        return "Not required", True

    if market == "Global Remote":
        return "Remote from India", True

    text = full_text(job)

    if contains(
        text,
        VISA_NEGATIVE
    ):
        return "No sponsorship", False

    if contains(
        text,
        VISA_POSITIVE
    ):
        return "Sponsorship indicated", True

    company = norm(
        job.get("empresa")
    )

    if any(
        x in company
        for x in LIKELY_SPONSOR_COMPANIES
    ):
        return "Sponsorship likely - verify", True

    return "Sponsorship unknown", False


# ============================================================
# HARD ROLE GATES
# ============================================================

TECH_TITLE_TERMS = [
    "software engineer",
    "software developer",
    "frontend engineer",
    "front-end engineer",
    "backend engineer",
    "back-end engineer",
    "full stack",
    "fullstack",
    "developer",
    "devops",
    "site reliability",
    "sre",
    "engineering manager",
    "technical program",
    "technical programme",
    "technical project",
    "technical product manager",
    "solutions architect",
    "solution architect",
    "cloud engineer",
    "data engineer",
    "data scientist",
    "machine learning",
    "ml engineer",
    "security engineer",
    "security operations",
    "cybersecurity",
    "cyber security",
    "soc analyst",
    "it operations",
    "it support",
    "network engineer",
    "systems administrator",
]


SALES_BD_TITLE_TERMS = [
    "sales",
    "business development",
    "account executive",
    "account manager",
    "sales development",
    "business development representative",
    "bdr",
    "sdr",
    "revenue operations",
    "sales operations",
    "sales ops",
    "revenue enablement",
    "sales enablement",
    "commercial sales",
    "partnerships manager",
    "partnership manager",
]


ADMIN_TITLE_TERMS = [
    "executive assistant",
    "personal assistant",
    "administrative assistant",
    "office assistant",
    "receptionist",
]


JUNIOR_TITLE_TERMS = [
    "intern",
    "internship",
    "graduate trainee",
    "management trainee",
    "junior analyst",
]


IRRELEVANT_FUNCTIONS = [
    "accountant",
    "legal counsel",
    "lawyer",
    "payroll",
    "graphic designer",
    "product designer",
    "recruiter",
    "talent acquisition",
]


INVESTMENT_EXECUTION = [
    "investment analyst",
    "investment associate",
    "private equity associate",
    "venture capital associate",
    "venture capital analyst",
    "investment banking",
    "m&a analyst",
    "m&a associate",
]


def conventional_product_manager(title):

    title = norm(title)

    conventional = (
        re.search(
            r"\bproduct manager\b",
            title
        )
        or re.search(
            r"\bproduct owner\b",
            title
        )
    )

    if not conventional:
        return False

    allowed = [
        "product strategy",
        "new ventures",
        "venture",
        "business strategy",
    ]

    return not contains(
        title,
        allowed
    )


def hard_role_gate(job):

    title = norm(
        job.get("titulo")
    )

    if contains(
        title,
        TECH_TITLE_TERMS
    ):
        return False, "Technical role"

    # Explicit user rule:
    # NO SALES OR BD.
    if contains(
        title,
        SALES_BD_TITLE_TERMS
    ):
        return False, "Sales / BD role"

    if contains(
        title,
        ADMIN_TITLE_TERMS
    ):
        return False, "Administrative role"

    if contains(
        title,
        JUNIOR_TITLE_TERMS
    ):
        return False, "Too junior"

    if contains(
        title,
        IRRELEVANT_FUNCTIONS
    ):
        return False, "Different function"

    if contains(
        title,
        INVESTMENT_EXECUTION
    ):
        return False, "Investment execution"

    if conventional_product_manager(
        title
    ):
        return False, "Conventional Product Manager"

    return True, ""


# ============================================================
# SPECIAL ROLE CHECKS
# ============================================================

STRATEGIC_PROGRAM_SIGNALS = [
    "business transformation",
    "strategic initiatives",
    "strategic priorities",
    "ceo priorities",
    "founder priorities",
    "market expansion",
    "business operations",
    "operating model",
    "commercial transformation",
    "enterprise transformation",
    "business strategy",
]


DELIVERY_PROGRAM_SIGNALS = [
    "pmo",
    "software delivery",
    "engineering delivery",
    "technical delivery",
    "implementation project",
    "scrum",
    "agile delivery",
    "jira",
    "sprint planning",
]


def program_manager_allowed(job):

    title = norm(
        job.get("titulo")
    )

    if not contains(
        title,
        [
            "program manager",
            "programme manager",
            "project manager",
        ],
    ):
        return True

    body = norm(
        job.get("descricao")
    )

    strategic = contains(
        body,
        STRATEGIC_PROGRAM_SIGNALS
    )

    delivery = contains(
        body,
        DELIVERY_PROGRAM_SIGNALS
    )

    return strategic and not delivery


COS_ADMIN_SIGNALS = [
    "calendar management",
    "manage calendar",
    "schedule meetings",
    "travel arrangements",
    "travel booking",
    "expense reports",
    "personal errands",
    "administrative support",
]


def strategic_cos_allowed(job):

    title = norm(
        job.get("titulo")
    )

    if not contains(
        title,
        [
            "chief of staff",
            "founder's office",
            "founders office",
            "ceo office",
        ],
    ):
        return True

    body = norm(
        job.get("descricao")
    )

    admin_hits = sum(
        phrase in body
        for phrase in COS_ADMIN_SIGNALS
    )

    return admin_hits < 2


# ============================================================
# RESPONSIBILITY FIT
# ============================================================

RESPONSIBILITY_SIGNALS = {

    "Founder/CEO partnership": (
        [
            "work directly with the founder",
            "work closely with the founder",
            "partner with the founder",
            "report to the founder",
            "work directly with the ceo",
            "work closely with the ceo",
            "report directly to the ceo",
            "office of the ceo",
            "office of the founder",
            "founder's office",
            "founders office",
        ],
        10,
    ),

    "Strategy to execution": (
        [
            "strategic initiatives",
            "strategic priorities",
            "strategy and execution",
            "strategy through execution",
            "translate strategy",
            "execute strategic",
            "drive strategic",
            "business strategy",
            "corporate strategy",
            "strategic planning",
        ],
        8,
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
        5,
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
        5,
    ),

    "Operating model / governance": (
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
        5,
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
        5,
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
        5,
    ),

    "International / GTM": (
        [
            "go-to-market strategy",
            "go to market strategy",
            "gtm strategy",
            "market entry",
            "international expansion",
            "new markets",
            "global expansion",
        ],
        4,
    ),

    "Portfolio / value creation": (
        [
            "portfolio operations",
            "portfolio companies",
            "value creation",
            "portfolio acceleration",
            "operating partner",
            "portfolio support",
            "portfolio strategy",
        ],
        7,
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
        5,
    ),
}


TITLE_SIGNALS = [
    "chief of staff",
    "founder's office",
    "founders office",
    "founder office",
    "ceo office",
    "office of the ceo",
    "strategy and operations",
    "strategy & operations",
    "strategic operations",
    "strategic initiatives",
    "corporate strategy",
    "business operations",
    "bizops",
    "special projects",
    "business transformation",
    "business head",
    "general manager",
    "country manager",
    "portfolio operations",
    "value creation",
    "venture builder",
    "venture lead",
    "operating partner",
    "product strategy",
]


def responsibility_fit(job):

    text = full_text(job)
    title = norm(
        job.get("titulo")
    )

    points = 0
    reasons = []

    for label, (
        terms,
        value,
    ) in RESPONSIBILITY_SIGNALS.items():

        if contains(
            text,
            terms
        ):

            points += value
            reasons.append(label)

    # Title is evidence, NOT a gate.
    if contains(
        title,
        TITLE_SIGNALS
    ):
        points += 4

    return (
        min(points, 40),
        reasons
    )


# ============================================================
# EXPERIENCE
# ============================================================

def required_experience(job):

    text = norm(
        job.get("descricao")
    )

    patterns = [
        r"(\d{1,2})\+\s*years(?:\s+of)?\s+experience",
        r"minimum(?:\s+of)?\s+(\d{1,2})\s+years(?:\s+of)?\s+experience",
        r"at least\s+(\d{1,2})\s+years(?:\s+of)?\s+experience",
        r"(\d{1,2})\s*-\s*(\d{1,2})\s+years(?:\s+of)?\s+experience",
        r"(\d{1,2})\s+to\s+(\d{1,2})\s+years(?:\s+of)?\s+experience",
    ]

    requirements = []

    for pattern in patterns:

        for match in re.findall(
            pattern,
            text
        ):

            if isinstance(
                match,
                tuple
            ):

                nums = [
                    int(x)
                    for x in match
                    if x
                ]

                if nums:
                    requirements.append(
                        min(nums)
                    )

            else:

                try:
                    requirements.append(
                        int(match)
                    )
                except Exception:
                    pass

    if not requirements:
        return None

    # Overall JDs may mention multiple experience
    # requirements. Highest credible minimum is safer.
    credible = [
        x
        for x in requirements
        if 1 <= x <= 20
    ]

    return (
        max(credible)
        if credible
        else None
    )


def experience_score(job, responsibility):

    years = required_experience(job)

    if years is None:
        return 8, "Experience requirement unclear", True

    if years <= 5:
        return 11, f"{years}+ years requested", True

    if years <= 7:
        return 15, f"{years}+ years - strong match", True

    if years == 8:
        return 13, "8+ years - viable", True

    if years <= 10:
        return 9, f"{years}+ years - stretch", True

    if years == 11:

        if responsibility >= 30:
            return 4, "11+ years - exceptional stretch", True

        return 0, "11+ years - too senior", False

    return (
        0,
        f"{years}+ years - reject",
        False
    )


# ============================================================
# COMPENSATION
# ============================================================

EQUITY_TERMS = [
    "equity",
    "esop",
    "esops",
    "stock options",
    "employee stock",
]


def india_salary_lpa(job):

    text = full_text(job)

    values = []

    patterns = [
        r"₹\s*(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*₹?\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakh|lakhs)",
        r"inr\s*(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakh|lakhs)",
        r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*lpa",
        r"₹\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakh|lakhs)",
        r"inr\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakh|lakhs)",
        r"(\d+(?:\.\d+)?)\s*lpa",
    ]

    for pattern in patterns:

        for match in re.findall(
            pattern,
            text,
            flags=re.I
        ):

            if isinstance(
                match,
                tuple
            ):

                for value in match:

                    if not value:
                        continue

                    try:
                        n = float(value)

                        if 10 <= n <= 300:
                            values.append(n)

                    except Exception:
                        pass

            else:

                try:
                    n = float(match)

                    if 10 <= n <= 300:
                        values.append(n)

                except Exception:
                    pass

    return max(values) if values else None


def compensation_check(
    job,
    market
):

    if market != "India":
        return (
            "Salary unknown / verify",
            True,
            5
        )

    salary = india_salary_lpa(job)

    if salary is None:
        return (
            "Salary unknown",
            True,
            5
        )

    if salary >= 40:
        return (
            f"₹{salary:g}L+ indicated",
            True,
            10
        )

    if (
        35 <= salary < 40
        and contains(
            full_text(job),
            EQUITY_TERMS
        )
    ):
        return (
            f"₹{salary:g}L + equity indicated",
            True,
            8
        )

    return (
        f"₹{salary:g}L indicated",
        False,
        0
    )


# ============================================================
# PROFILE SCORE
#
# Responsibilities             40
# Seniority / experience       15
# Founder / executive exposure 10
# Compensation                 10
# Location / visa              10
# Company / upside             10
# Freshness                     5
# ============================================================

def calculate_score(
    job,
    market,
    visa
):

    concerns = []

    responsibility, reasons = (
        responsibility_fit(job)
    )

    # Need meaningful evidence of actual
    # work alignment.
    if responsibility < 12:

        return (
            0,
            reasons,
            ["Insufficient responsibility fit"],
            False
        )

    total = responsibility

    # --------------------------------------------------------
    # Experience - 15
    # --------------------------------------------------------

    exp_points, exp_note, exp_ok = (
        experience_score(
            job,
            responsibility
        )
    )

    if not exp_ok:

        return (
            0,
            reasons,
            [exp_note],
            False
        )

    total += exp_points

    if "strong match" not in exp_note:
        concerns.append(exp_note)

    # --------------------------------------------------------
    # Founder/executive exposure - 10
    # --------------------------------------------------------

    text = full_text(job)

    executive = contains(
        text,
        [
            "founder",
            "ceo",
            "chief executive",
            "executive leadership",
            "leadership team",
            "c-suite",
        ],
    )

    if executive:
        total += 10

    # --------------------------------------------------------
    # Compensation - 10
    # --------------------------------------------------------

    salary, comp_ok, comp_points = (
        compensation_check(
            job,
            market
        )
    )

    if not comp_ok:

        return (
            0,
            reasons,
            [salary],
            False
        )

    total += comp_points

    if "unknown" in salary.lower():
        concerns.append(
            "Compensation needs verification"
        )

    # --------------------------------------------------------
    # Geography / visa - 10
    # --------------------------------------------------------

    if market == "India":
        total += 10

    elif market == "Global Remote":
        total += 10

    elif market == "Europe":

        if visa == "Sponsorship indicated":
            total += 10

        else:
            total += 7

    # --------------------------------------------------------
    # Company/upside - 10
    #
    # Evidence-based rather than brand-name based.
    # --------------------------------------------------------

    upside = 0

    if contains(
        text,
        [
            "high growth",
            "high-growth",
            "scale-up",
            "scaleup",
            "series a",
            "series b",
            "series c",
            "series d",
            "venture backed",
            "venture-backed",
            "private equity backed",
            "pe-backed",
            "global expansion",
            "rapid growth",
        ],
    ):
        upside += 5

    if contains(
        text,
        [
            "build from scratch",
            "0 to 1",
            "zero to one",
            "new market",
            "new venture",
            "business building",
            "transformation",
        ],
    ):
        upside += 5

    total += min(
        upside,
        10
    )

    # --------------------------------------------------------
    # Freshness - 5
    # --------------------------------------------------------

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

    return (
        min(round(total), 100),
        reasons[:5],
        concerns[:4],
        True
    )


# ============================================================
# ACTION
# ============================================================

def action(score):

    if score >= 85:
        return "APPLY TODAY"

    if score >= 72:
        return "STRONG - REVIEW TODAY"

    if score >= 60:
        return "REVIEW"

    return "DO NOT SURFACE"


# ============================================================
# COLLECTION
# ============================================================

def collect(cfg):

    jobs = []

    # --------------------------------------------------------
    # DIRECT ATS SOURCES
    # --------------------------------------------------------

    direct_collectors = [
        ("ashby", fetch_ashby),
        ("greenhouse", fetch_greenhouse),
        ("lever", fetch_lever),
    ]

    for source, fn in direct_collectors:

        companies = (
            cfg.get("sources", {})
            .get(source, [])
        )

        for company in companies:

            try:

                found = fn(company)

                jobs.extend(found)

                print(
                    f"[{source}] "
                    f"{company}: "
                    f"{len(found)} jobs"
                )

            except Exception as exc:

                print(
                    f"[WARNING] "
                    f"{source}/{company}: "
                    f"{exc}"
                )

    # --------------------------------------------------------
    # MARKET-WIDE PUBLIC FEEDS
    # --------------------------------------------------------

    broad = [
        (
            "remoteok",
            fetch_remoteok
        ),
        (
            "remotive",
            fetch_remotive
        ),
        (
            "weworkremotely",
            fetch_wwr
        ),
    ]

    for source, fn in broad:

        try:

            found = fn()

            jobs.extend(found)

            print(
                f"[{source}] "
                f"{len(found)} jobs"
            )

        except Exception as exc:

            print(
                f"[WARNING] "
                f"{source}: "
                f"{exc}"
            )

    return jobs


# ============================================================
# DEDUPLICATION
# ============================================================

def dedupe_key(job):

    company = re.sub(
        r"[^a-z0-9]",
        "",
        norm(job.get("empresa"))
    )

    role = re.sub(
        r"[^a-z0-9]",
        "",
        norm(job.get("titulo"))
    )

    location = re.sub(
        r"[^a-z0-9]",
        "",
        norm(job.get("cidade"))
    )

    if company and role:
        return (
            f"{company}|{role}|{location}"
        )

    return (
        job.get("id")
        or job.get("link")
    )


# ============================================================
# MAIN
# ============================================================

def main():

    cfg = yaml.safe_load(
        (
            ROOT
            / "dev_config.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    freshness_hours = (
        cfg.get("candidate", {})
        .get("freshness_hours", 48)
    )

    target = (
        cfg.get("candidate", {})
        .get("daily_target", 20)
    )

    # --------------------------------------------------------
    # Seen memory
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

    raw_jobs = collect(cfg)

    unique = {}

    for job in raw_jobs:

        key = dedupe_key(job)

        if key:
            unique[key] = job

    # --------------------------------------------------------
    # Funnel diagnostics
    # --------------------------------------------------------

    funnel = {
        "fresh": 0,
        "geography": 0,
        "visa": 0,
        "role_gate": 0,
        "special_gate": 0,
        "responsibility": 0,
        "experience_comp": 0,
        "qualified": 0,
        "strong": 0,
    }

    candidates = []

    for key, job in unique.items():

        # ----------------------------------------------------
        # 1. <= 48 hours
        # ----------------------------------------------------

        if not is_fresh(
            job,
            freshness_hours
        ):
            continue

        funnel["fresh"] += 1

        # ----------------------------------------------------
        # 2. Geography
        # ----------------------------------------------------

        job_market = classify_market(
            job
        )

        if not job_market:
            continue

        funnel["geography"] += 1

        # ----------------------------------------------------
        # 3. Visa/work rights
        # ----------------------------------------------------

        visa, visa_ok = check_visa(
            job,
            job_market
        )

        if not visa_ok:
            continue

        funnel["visa"] += 1

        # ----------------------------------------------------
        # 4. Hard role categories
        # ----------------------------------------------------

        role_ok, rejection = (
            hard_role_gate(job)
        )

        if not role_ok:
            continue

        funnel["role_gate"] += 1

        # ----------------------------------------------------
        # 5. Special role logic
        # ----------------------------------------------------

        if not program_manager_allowed(
            job
        ):
            continue

        if not strategic_cos_allowed(
            job
        ):
            continue

        funnel["special_gate"] += 1

        # ----------------------------------------------------
        # 6. Responsibility fit
        # ----------------------------------------------------

        responsibility, _ = (
            responsibility_fit(job)
        )

        if responsibility < 12:
            continue

        funnel["responsibility"] += 1

        # ----------------------------------------------------
        # 7. Score
        # ----------------------------------------------------

        (
            score,
            reasons,
            concerns,
            eligible,
        ) = calculate_score(
            job,
            job_market,
            visa
        )

        if not eligible:
            continue

        funnel["experience_comp"] += 1

        # 60 = minimum qualified.
        if score < 60:
            continue

        funnel["qualified"] += 1

        if score >= 72:
            funnel["strong"] += 1

        # ----------------------------------------------------
        # 8. Seen state
        # ----------------------------------------------------

        jid = (
            job.get("id")
            or job.get("link")
            or key
        )

        if jid in seen:
            continue

        salary, _, _ = (
            compensation_check(
                job,
                job_market
            )
        )

        candidates.append({
            "Score": score,
            "Posted": (
                job.get(
                    "publicado_em",
                    ""
                )
            ),
            "Company": (
                job.get(
                    "empresa",
                    ""
                )
            ),
            "Role": (
                job.get(
                    "titulo",
                    ""
                )
            ),
            "Location": (
                job.get(
                    "cidade",
                    ""
                )
            ),
            "Salary": salary,
            "Visa": visa,
            "Why You Fit": (
                "; ".join(reasons)
            ),
            "Concern": (
                "; ".join(concerns)
                if concerns
                else "None identified"
            ),
            "Action": action(score),
            "Link": (
                job.get(
                    "link",
                    ""
                )
            ),
            "_id": jid,
            "_age": age_hours(job),
        })

    # --------------------------------------------------------
    # Ranking
    # --------------------------------------------------------

    candidates.sort(
        key=lambda row: (
            row["Score"],
            -(row["_age"] or 999),
        ),
        reverse=True
    )

    # 20 is target, not quota.
    #
    # If >20 strong roles genuinely exist,
    # show all strong roles.
    strong = [
        row
        for row in candidates
        if row["Score"] >= 72
    ]

    if len(strong) >= target:
        selected = strong
    else:
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

    output_path = (
        OUT
        / f"dev_radar_{today}.csv"
    )

    fields = [
        "Score",
        "Posted",
        "Company",
        "Role",
        "Location",
        "Salary",
        "Visa",
        "Why You Fit",
        "Concern",
        "Action",
        "Link",
    ]

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()

        writer.writerows(
            selected
        )

    # --------------------------------------------------------
    # Seen memory
    # --------------------------------------------------------

    seen.update(
        row["_id"]
        for row in selected
    )

    STATE.write_text(
        json.dumps(
            sorted(seen),
            indent=2
        ),
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # Diagnostics
    # --------------------------------------------------------

    print()
    print(
        "============== DEV RADAR V5 =============="
    )

    print(
        f"Raw jobs collected:         {len(raw_jobs)}"
    )

    print(
        f"Unique jobs:                {len(unique)}"
    )

    print(
        f"Fresh <=48h:                {funnel['fresh']}"
    )

    print(
        f"Eligible geography:         {funnel['geography']}"
    )

    print(
        f"Visa/work rights passed:    {funnel['visa']}"
    )

    print(
        f"Role category passed:       {funnel['role_gate']}"
    )

    print(
        f"Special role checks passed: {funnel['special_gate']}"
    )

    print(
        f"Responsibility fit passed:  {funnel['responsibility']}"
    )

    print(
        f"Experience/comp passed:     {funnel['experience_comp']}"
    )

    print(
        f"Qualified >=60:             {funnel['qualified']}"
    )

    print(
        f"Strong >=72:                {funnel['strong']}"
    )

    print(
        f"NEW jobs surfaced:          {len(selected)}"
    )

    print(
        f"Output:                     {output_path}"
    )

    print(
        "=========================================="
    )

    if selected:

        print()
        print("TOP RESULTS")

        for row in selected:

            print()

            print(
                f'{row["Score"]}/100 | '
                f'{row["Action"]}'
            )

            print(
                f'{row["Company"]} | '
                f'{row["Role"]}'
            )

            print(
                f'{row["Location"]}'
            )

            print(
                f'Visa: {row["Visa"]}'
            )

            print(
                f'Why: {row["Why You Fit"]}'
            )

            print(
                f'Concern: {row["Concern"]}'
            )

    else:

        print()
        print(
            "No genuinely qualified NEW jobs "
            "were found in this run."
        )


if __name__ == "__main__":
    main()
