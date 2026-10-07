#!/usr/bin/env python3
"""Dev Radar: fresh-job ranking from the existing public ATS collectors."""
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
        return None

def is_fresh(job, hours):
    posted = parse_date(job.get("publicado_em", ""))
    return posted is not None and dt.datetime.now(dt.timezone.utc) - posted <= dt.timedelta(hours=hours)

def relevant_market(job):
    text = ((job.get("cidade") or "") + " " + (job.get("descricao") or "")[:2000]).lower()
    india = ["india","bengaluru","bangalore","gurugram","gurgaon","mumbai","delhi","pune","hyderabad","chennai","noida"]
    europe = ["europe","emea","germany","netherlands","france","spain","portugal","ireland","sweden","denmark","finland","norway","switzerland","austria","belgium","poland","prague","tallinn"]
    if any(x in text for x in india):
        return "India"
    if any(x in text for x in europe):
        return "Europe"
    if any(x in text for x in ["worldwide","anywhere","global remote"]):
        return "Global remote"
    return ""

def rank(job, cfg):
    title = (job.get("titulo") or "").lower()
    body = (job.get("descricao") or "").lower()
    if any(x.lower() in title for x in cfg["exclude_title_keywords"]):
        return 0, ""
    title_hits = [x for x in cfg["role_keywords"] if x.lower() in title]
    body_hits = [x for x in cfg["role_keywords"] if x.lower() in body]
    if not title_hits:
        return 0, ""
    score = min(65, 35 + 10 * len(title_hits)) + min(20, 3 * len(body_hits))
    evidence = []
    for label, terms in {
        "founder/CEO": ["founder","ceo"],
        "strategy to execution": ["strategy","execution"],
        "P&L/commercial": ["p&l","commercial","revenue"],
        "cross-functional": ["cross-functional","stakeholder"],
        "KPI/OKR": ["kpi","okr"],
        "GTM/new ventures": ["go-to-market","gtm","new venture"],
    }.items():
        if any(term in body for term in terms):
            score += 3
            evidence.append(label)
    return min(score, 100), "; ".join(evidence[:4])

def collect(cfg):
    jobs = []
    for source, fn in [("ashby", fetch_ashby), ("greenhouse", fetch_greenhouse), ("lever", fetch_lever)]:
        for company in cfg["sources"].get(source, []):
            try:
                jobs.extend(fn(company))
            except Exception as exc:
                print(f"WARNING {source}/{company}: {exc}")
    return jobs

def main():
    cfg = yaml.safe_load((ROOT / "dev_config.yaml").read_text())
    seen = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    jobs = {j.get("id") or j.get("link"): j for j in collect(cfg)}
    rows = []
    for jid, job in jobs.items():
        if jid in seen or not is_fresh(job, cfg["candidate"]["freshness_hours"]):
            continue
        market = relevant_market(job)
        if not market:
            continue
        score, why = rank(job, cfg)
        if score < 50:
            continue
        rows.append({"score":score,"posted":job.get("publicado_em",""),"company":job.get("empresa",""),"role":job.get("titulo",""),"location":job.get("cidade",""),"market":market,"source":job.get("fonte",""),"why_fit":why,"job_link":job.get("link",""),"status":"NEW","id":jid})
    rows.sort(key=lambda row: (row["score"], row["posted"]), reverse=True)
    target = cfg["candidate"]["daily_target"]
    selected = rows[:max(target, len([r for r in rows if r["score"] >= 80]))]
    path = OUT / f"dev_radar_{dt.date.today().isoformat()}.csv"
    fields = ["score","posted","company","role","location","market","source","why_fit","job_link","status","id"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)
    seen.update(r["id"] for r in selected)
    STATE.write_text(json.dumps(sorted(seen), indent=2))
    print(f"eligible_new={len(rows)} selected={len(selected)} output={path}")

if __name__ == "__main__":
    main()
