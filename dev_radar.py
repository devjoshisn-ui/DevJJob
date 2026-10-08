
#!/usr/bin/env python3
"""Dev Radar V6 — self-contained job collector, hard gates, ranking and rejection audit.
Requires requests and PyYAML (already in the existing repository requirements).
Optional: ADZUNA_APP_ID + ADZUNA_APP_KEY environment secrets for broader India/EU search.
"""
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'
OUT.mkdir(exist_ok=True)
UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
TODAY = NOW.strftime('%Y-%m-%d')
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'DevRadar/6.0 (personal job research; respectful public APIs)', 'Accept': 'application/json, */*'})
FIELDS = ['Score','Posted','Company','Role','Location','Salary','Visa','Why You Fit','Concern','Action','Link']


def clean(v):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(v or '')))).strip()


def low(v): return clean(v).casefold()


def has(text, patterns):
    s = low(text)
    return any(re.search(p, s, re.I) for p in patterns)


def parse_date(value):
    if value is None or value == '': return None
    if isinstance(value, (int, float)):
        try: return dt.datetime.fromtimestamp(value / (1000 if value > 1e11 else 1), UTC)
        except (ValueError, OverflowError): return None
    s = str(value).strip()
    try:
        d = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
        return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    except ValueError: pass
    try:
        d = parsedate_to_datetime(s)
        return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    except (ValueError, TypeError): return None


def request_json(url, params=None):
    r = SESSION.get(url, params=params, timeout=22)
    r.raise_for_status()
    return r.json()


def make(source, company, title, location, url, description, published, remote=False, salary='', id_=None, date_quality='original'):
    return dict(source=source, company=clean(company), title=clean(title), location=clean(location),
                url=str(url or ''), description=clean(description), published=published, remote=bool(remote),
                salary=clean(salary), id=str(id_ or url or ''), date_quality=date_quality)


def greenhouse(board):
    data = request_json(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs', {'content':'true'})
    jobs=[]
    for j in data.get('jobs', []):
        # Greenhouse public boards expose updated_at, NOT a reliable original posting date.
        # Never pass updated_at as original posting under the user's strict freshness rule.
        jobs.append(make('greenhouse', j.get('company_name') or board, j.get('title'),
                         (j.get('location') or {}).get('name'), j.get('absolute_url'), j.get('content'),
                         None, id_=f'gh:{board}:{j.get("id")}', date_quality='unknown_updated_only'))
    return jobs


def lever(board):
    data=request_json(f'https://api.lever.co/v0/postings/{board}', {'mode':'json'})
    jobs=[]
    for j in data:
        cats=j.get('categories') or {}
        desc=' '.join([str(j.get('descriptionPlain') or ''),clean(j.get('description')),
                       ' '.join(clean(x.get('content')) for x in j.get('lists',[]) if isinstance(x,dict))])
        jobs.append(make('lever',board,j.get('text'),cats.get('location') or ', '.join(cats.get('allLocations') or []),
                         j.get('hostedUrl') or j.get('applyUrl'),desc,j.get('createdAt'),
                         remote=has(cats.get('workplaceType',''),[r'remote']),id_=f'lever:{j.get("id")}'))
    return jobs


def ashby(board):
    data=request_json(f'https://api.ashbyhq.com/posting-api/job-board/{board}', {'includeCompensation':'true'})
    jobs=[]
    for j in data.get('jobs',[]):
        comp=j.get('compensation') or {}
        salary=comp.get('compensationTierSummary') or comp.get('scrapeableCompensationSalarySummary') or ''
        jobs.append(make('ashby',board,j.get('title'),j.get('location'),j.get('jobUrl') or j.get('applyUrl'),
                         j.get('descriptionPlain') or j.get('descriptionHtml'),j.get('publishedAt'),
                         remote=j.get('isRemote') or False,salary=salary,id_=f'ashby:{board}:{j.get("id")}'))
    return jobs


def smartrecruiters(board):
    jobs=[]; offset=0
    for _ in range(12):
        data=request_json(f'https://api.smartrecruiters.com/v1/companies/{board}/postings',{'limit':100,'offset':offset})
        content=data.get('content') or []
        for j in content:
            loc=j.get('location') or {}
            location=', '.join(str(loc.get(k)) for k in ('city','country') if loc.get(k))
            desc=clean(j.get('name'))+' '+clean(j.get('department',{}).get('label') if isinstance(j.get('department'),dict) else '')
            jobs.append(make('smartrecruiters',j.get('company',{}).get('name',board) if isinstance(j.get('company'),dict) else board,
                             j.get('name'),location,j.get('ref') or f'https://jobs.smartrecruiters.com/{board}/{j.get("id")}',
                             desc,j.get('releasedDate'),remote=loc.get('remote',False),id_=f'sr:{j.get("id")}'))
        offset+=len(content)
        if len(content)<100: break
    return jobs


def remotive():
    data=request_json('https://remotive.com/api/remote-jobs')
    return [make('remotive',j.get('company_name'),j.get('title'),j.get('candidate_required_location'),j.get('url'),
                 j.get('description'),j.get('publication_date'),True,j.get('salary'),f'remotive:{j.get("id")}') for j in data.get('jobs',[])]


def remoteok():
    data=request_json('https://remoteok.com/api')
    return [make('remoteok',j.get('company'),j.get('position'),j.get('location'),j.get('url'),
                 (j.get('description') or '')+' '+ ' '.join(j.get('tags') or []),j.get('date'),True,
                 j.get('salary') or '',f'remoteok:{j.get("id")}') for j in data if isinstance(j,dict) and j.get('id')]


def wwr():
    r=SESSION.get('https://weworkremotely.com/remote-jobs.rss',timeout=22);r.raise_for_status()
    root=ET.fromstring(r.content);out=[]
    for item in root.iter('item'):
        raw=item.findtext('title') or ''
        company,title=(raw.split(': ',1)+[''])[:2] if ': ' in raw else ('',raw)
        link=item.findtext('link')
        out.append(make('weworkremotely',company,title,'Remote',link,item.findtext('description'),item.findtext('pubDate'),True,id_=link))
    return out


def arbeitnow():
    # Public job board API; results may include Europe and remote roles.
    out=[]
    for page in range(1,5):
        data=request_json('https://www.arbeitnow.com/api/job-board-api',{'page':page})
        for j in data.get('data',[]):
            out.append(make('arbeitnow',j.get('company_name'),j.get('title'),j.get('location'),j.get('url'),
                            j.get('description'),j.get('created_at'),j.get('remote',False),id_=f'arbeitnow:{j.get("slug")}'))
        if not data.get('links',{}).get('next'): break
    return out


def adzuna(country, query):
    app_id=os.getenv('ADZUNA_APP_ID');key=os.getenv('ADZUNA_APP_KEY')
    if not app_id or not key: return []
    out=[]
    for page in range(1,4):
        data=request_json(f'https://api.adzuna.com/v1/api/jobs/{country}/search/{page}',
                          {'app_id':app_id,'app_key':key,'results_per_page':50,'what':query,'sort_by':'date','max_days_old':2,'content-type':'application/json'})
        for j in data.get('results',[]):
            loc=j.get('location') or {}
            salary=f"{j.get('salary_min') or ''}–{j.get('salary_max') or ''} {country.upper()}" if j.get('salary_min') else ''
            out.append(make('adzuna', (j.get('company') or {}).get('display_name'),j.get('title'),
                            loc.get('display_name'),j.get('redirect_url'),j.get('description'),j.get('created'),
                            remote=has(j.get('title','')+' '+j.get('description',''),[r'\bremote\b']),salary=salary,
                            id_=f'adzuna:{country}:{j.get("id")}'))
    return out


UK=r'\b(?:united kingdom|great britain|england|scotland|wales|northern ireland|london|manchester|birmingham|edinburgh|glasgow|bristol|leeds|liverpool|cardiff|belfast|uk)\b'
INDIA=r'\b(?:india|bengaluru|bangalore|gurugram|gurgaon|mumbai|delhi|noida|pune|hyderabad|chennai|kolkata|ahmedabad|indore|jaipur|kochi|coimbatore|chandigarh|surat|vadodara|navi mumbai)\b'
EU_COUNTRIES=r'\b(?:austria|belgium|bulgaria|croatia|cyprus|czechia|czech republic|denmark|estonia|finland|france|germany|greece|hungary|iceland|ireland|italy|latvia|liechtenstein|lithuania|luxembourg|malta|netherlands|norway|poland|portugal|romania|slovakia|slovenia|spain|sweden|switzerland)\b'
EU_CITIES=r'\b(?:vienna|brussels|sofia|zagreb|prague|copenhagen|tallinn|helsinki|paris|berlin|munich|hamburg|frankfurt|athens|budapest|dublin|milan|rome|riga|vilnius|amsterdam|rotterdam|oslo|warsaw|krakow|lisbon|porto|bucharest|bratislava|ljubljana|madrid|barcelona|stockholm|zurich|geneva)\b'
REMOTE_BLOCK=r'\b(?:us only|usa only|united states only|canada only|uk only|europe only|eu only|emea only|latam only|north america only|must be based in (?:the )?(?:us|usa|uk|eu)|remote[ -]+(?:us|usa|uk|canada))\b'
REMOTE_INDIA=r'\b(?:india|indian residents|work from india|remote from india|asia[ -]pacific|apac)\b'
REMOTE_GLOBAL=r'\b(?:worldwide|world[ -]wide|anywhere in the world|work from anywhere|globally remote|remote globally|remote worldwide)\b'
VISA_NEG=r'\b(?:no visa sponsorship|cannot sponsor|unable to sponsor|will not sponsor|without sponsorship|must already have (?:the )?right to work|must have (?:the )?right to work|must be (?:authorized|authorised) to work|existing work authorization|existing right to work)\b'
VISA_POS=r'\b(?:visa sponsorship (?:available|provided|offered)|sponsorship available|we sponsor visas|visa and relocation|relocation and visa|immigration sponsorship|work permit sponsorship|work visa sponsorship|visa support provided)\b'
# A company name alone does not establish sponsorship for this particular role.


def geography(j):
    loc=low(j['location']);desc=low(j['description']);title=low(j['title'])
    if has(loc,[UK]): return None,'UK excluded'
    if has(loc,[INDIA]): return 'India',''
    if has(loc,[EU_COUNTRIES,EU_CITIES]): return 'Europe',''
    # Location may be unspecified; don't classify based on incidental India/Europe mentions in a long JD.
    if j['remote'] or has(loc+' '+title,[r'\bremote\b']):
        if has(loc,[REMOTE_BLOCK]): return None,'Remote region excludes India'
        if has(loc,[REMOTE_INDIA]) or has(desc,[r'\bremote (?:from|within|in) india\b',r'\b(?:candidates|applicants|employees) (?:based|located) in india\b']):
            return 'India remote',''
        if has(loc,[REMOTE_GLOBAL]) and not has(desc,[REMOTE_BLOCK]): return 'Global remote',''
        # Explicitly global in job description only if not countermanded by restricted location.
        if has(desc,[REMOTE_GLOBAL]) and not has(loc+' '+desc,[REMOTE_BLOCK]): return 'Global remote',''
        return None,'Remote India eligibility unverified'
    return None,'Outside eligible geography / location unknown'


def visa(j,market):
    if market != 'Europe': return 'Not required (India)',True
    text=low(j['description'])
    if has(text,[VISA_NEG]): return 'No sponsorship',False
    if has(text,[VISA_POS]): return 'Sponsorship stated',True
    return 'Sponsorship unverified',False


ROLE_REJECT=[
 ('Sales / BD',r'\b(?:sales|business development|account executive|sales operations|revenue operations|sales enablement|sales development|bdr|sdr|quota|customer acquisition executive)\b'),
 ('Technical',r'\b(?:software engineer|software developer|developer|devops|site reliability|sre|engineering manager|technical program|technical programme|technical project|technical product manager|solutions architect|data engineer|data scientist|machine learning engineer|security engineer|cybersecurity|it support|network engineer|cloud engineer|full.?stack|backend engineer|frontend engineer)\b'),
 ('Administrative',r'\b(?:executive assistant|personal assistant|administrative assistant|receptionist|office assistant)\b'),
 ('Junior',r'\b(?:intern|internship|graduate trainee|management trainee|junior analyst)\b'),
 ('Specialist',r'\b(?:accountant|legal counsel|lawyer|payroll|graphic designer|product designer|recruiter|talent acquisition)\b'),
 ('Investment execution',r'\b(?:investment analyst|investment associate|private equity associate|venture capital associate|investment banking|m&a analyst|m&a associate)\b'),
]
STRATEGY_PATTERNS=[r'\bstrateg(?:y|ic)\b',r'\bbusiness operations\b',r'\btransformation\b',r'\bportfolio\b',r'\bmarket expansion\b',r'\boperating model\b',r'\bexecutive priorit',r'\bcommercial excellence\b',r'\bbusiness building\b',r'\bchief of staff\b',r'\bfounder']
ADMIN_PATTERNS=[r'calendar management',r'schedul(?:e|ing) meetings',r'travel arrangements',r'expense reports',r'personal errands',r'administrative support']
DELIVERY_PATTERNS=[r'\bpmo\b',r'\bscrum\b',r'\bsprint planning\b',r'\bsoftware delivery\b',r'\btechnical delivery\b',r'\bjira\b']
QUOTA_PATTERNS=[r'\bquota.carrying\b',r'\bsales quota\b',r'\bcold calling\b',r'\bprospecting\b',r'\bclose deals\b',r'\bmanage sales pipeline\b']


def role_gate(j):
    title=low(j['title']);desc=low(j['description'])
    for reason,pattern in ROLE_REJECT:
        if has(title,[pattern]): return reason
    if has(title,[r'\b(?:product manager|product owner)\b']) and not has(title,[r'\bproduct strategy\b',r'\bnew ventures\b']): return 'Conventional product management'
    if has(title,[r'\b(?:program|programme|project) manager\b']) and (not has(desc,STRATEGY_PATTERNS) or sum(bool(has(desc,[p])) for p in DELIVERY_PATTERNS)>=2):
        return 'Delivery / PMO rather than strategic program'
    if has(title,[r'chief of staff',r'founder.?s office',r'ceo.?s office']) and sum(bool(has(desc,[p])) for p in ADMIN_PATTERNS)>=2:
        return 'Administrative Chief of Staff'
    if sum(bool(has(desc,[p])) for p in QUOTA_PATTERNS)>=2: return 'Quota sales responsibilities'
    return None


FIT_GROUPS=[
 ('Founder / CEO partnership',10,[r'\bfounder',r'\bceo\b',r'\bchief executive\b',r'\bexecutive team\b',r'\bboard of directors\b']),
 ('Strategy and execution',9,[r'\bstrateg',r'\bbusiness planning\b',r'\bprioriti[sz]',r'\bdecision.making\b']),
 ('Cross-functional leadership',7,[r'\bcross.functional\b',r'\bstakeholder',r'\bmultiple teams\b',r'\binterdepartmental\b']),
 ('Business / P&L ownership',8,[r'\bp&l\b',r'\bprofitab',r'\bunit economics\b',r'\bbusiness performance\b',r'\bmargin\b',r'\bbudget ownership\b']),
 ('Operating systems / KPIs',7,[r'\boperat',r'\bkpi',r'\bokr',r'\bperformance management\b',r'\bprocess improvement\b',r'\bgovernance\b']),
 ('Transformation / growth',8,[r'\btransform',r'\bscal',r'\bexpansion\b',r'\bturnaround\b',r'\bgrowth initiatives\b',r'\bchange management\b']),
 ('New ventures / GTM',7,[r'\bnew venture',r'\bmarket entry\b',r'\bgo.to.market\b',r'\bbusiness build',r'\blaunch\b']),
 ('Portfolio value creation',9,[r'\bportfolio compan',r'\bvalue creation\b',r'\bportfolio operations\b',r'\boperating partner\b']),
 ('Special projects',6,[r'\bspecial projects\b',r'\bstrategic projects\b',r'\bexecutive initiatives\b',r'\bhigh.impact initiatives\b']),
]
STRONG_TITLES=[r'chief of staff',r'founder.?s office',r'office of the ceo',r'strategy.{0,5}operations',r'\bbizops\b',r'corporate strategy',r'business operations',r'general manager',r'business head',r'portfolio operations',r'value creation',r'venture build',r'operating partner',r'business transformation',r'special projects',r'product strategy']


def responsibility(j):
    desc=low(j['description']);title=low(j['title'])
    matches=[];raw=0
    for label,pts,patterns in FIT_GROUPS:
        if has(desc,patterns): matches.append(label);raw+=pts
    # Actual responsibilities dominate; title only small tie-breaker.
    if has(title,STRONG_TITLES): raw+=4
    if not desc or len(desc)<110: return min(40,raw),matches,'Insufficient job description'
    return min(40,raw),matches,None


def years_required(j):
    desc=low(j['description'])
    patterns=[r'(?:at least|minimum(?: of)?|requires?|must have)\s+(\d{1,2})\+?\s*(?:years|yrs)',
              r'\b(\d{1,2})\+\s*(?:years|yrs)(?: of)? (?:relevant |professional |work |management |leadership )?experience',
              r'\b(\d{1,2})\s*(?:-|to|–)\s*\d{1,2}\s*(?:years|yrs)(?: of)? experience']
    vals=[]
    for p in patterns: vals += [int(x) for x in re.findall(p,desc) if 1<=int(x)<=25]
    return max(vals) if vals else None


def salary_check(j,market):
    salary=j['salary'];desc=low(j['description']);text=low(salary)
    if market not in ('India','India remote'):
        return salary or 'Not published',True,'European savings target unverified'
    # Only interpret India-specific LPA units. Avoid reading irrelevant numbers as pay.
    found=[float(x) for x in re.findall(r'(?:₹|inr\s*)?\s*(\d{2,3}(?:\.\d+)?)\s*(?:lpa|lakhs?\s*(?:per annum|annually|pa)?)\b',text+' '+desc)]
    if not found: return salary or 'Not published',True,'India compensation unverified'
    # Reject only when the known top end is below 35, or 35-40 without explicit equity.
    top=max(found)
    if top<35: return salary or f'₹{top:g} LPA',False,'Known salary below ₹35L'
    if top<40 and not has(desc+' '+text,[r'\bequity\b',r'\besops?\b',r'\bstock options\b']):
        return salary or f'₹{top:g} LPA',False,'₹35–40L without evidenced equity'
    return salary or f'₹{top:g} LPA',True,''


def score(j,market,visa_status,fit,reasons,salary_concern):
    concerns=[]
    y=years_required(j)
    if y is None: seniority=9;concerns.append('Experience requirement unverified')
    elif y<=7: seniority=15
    elif y==8: seniority=13
    elif y<=10: seniority=9;concerns.append(f'{y}+ years stretch')
    elif y<=11 and fit>=28 and has(j['title'],[r'\b(?:head|director|general manager|chief of staff)\b']): seniority=4;concerns.append('Exceptional seniority stretch')
    else: return None,['Experience too senior']
    executive=10 if has(j['description'],[r'\bfounder',r'\bceo\b',r'\bexecutive team\b',r'\bboard\b']) else 3
    comp=6 if salary_concern else 10
    location=10 if market in ('India','India remote','Global remote') or visa_status=='Sponsorship stated' else 0
    company=3
    if has(j['description'],[r'\bscale.?up\b',r'\bhigh.growth\b',r'\bseries [a-d]\b',r'\bventure.backed\b',r'\bprivate equity.backed\b']): company+=4
    if has(j['description'],[r'\bnew markets\b',r'\bnew venture\b',r'\bbusiness building\b',r'\btransform']): company+=3
    age=(NOW-parse_date(j['published'])).total_seconds()/3600
    freshness=5 if age<=12 else 4 if age<=24 else 3 if age<=36 else 2
    if salary_concern: concerns.append(salary_concern)
    if not reasons: concerns.append('Fit inferred primarily from title')
    return min(100,fit+seniority+executive+comp+location+company+freshness),concerns


def dedupe(j):
    company=re.sub(r'[^a-z0-9]','',low(j['company']))
    title=re.sub(r'[^a-z0-9]','',low(j['title']))
    loc=re.sub(r'[^a-z0-9]','',low(j['location']))
    return f'{company}|{title}|{loc}' if company and title else j['url'] or j['id']


def collect(config):
    sources=config.get('sources') or {}
    jobs=[];tasks=[]
    funcs={'greenhouse':greenhouse,'lever':lever,'ashby':ashby,'smartrecruiters':smartrecruiters}
    for name,func in funcs.items():
        boards=sources.get(name) or []
        for b in boards:
            if isinstance(b,dict): b=b.get('board') or b.get('company') or b.get('slug')
            if b: tasks.append((f'{name}/{b}',func,str(b)))
    for name,func in [('remoteok',remoteok),('remotive',remotive),('weworkremotely',wwr),('arbeitnow',arbeitnow)]:
        tasks.append((name,func,None))
    if os.getenv('ADZUNA_APP_ID') and os.getenv('ADZUNA_APP_KEY'):
        # Broad discovery across India and EEA markets, with the search key provided by user.
        for country in ['in','de','fr','nl','ie','es','it','at','be','pl','se','ch']:
            for q in ['chief of staff','strategy operations','business transformation','portfolio operations','general manager']:
                tasks.append((f'adzuna/{country}/{q}',adzuna,(country,q)))
    print(f'Collectors scheduled: {len(tasks)}',flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(fn,*(arg if isinstance(arg,tuple) else (() if arg is None else (arg,)))):name for name,fn,arg in tasks}
        for f in as_completed(futures):
            name=futures[f]
            try:
                found=f.result();jobs.extend(found)
                print(f'[SOURCE] {name}: {len(found)}',flush=True)
            except Exception as e:
                print(f'[SOURCE ERROR] {name}: {type(e).__name__}: {str(e)[:130]}',flush=True)
    return jobs


def main():
    cfg_path=ROOT/'dev_config.yaml'
    cfg=yaml.safe_load(cfg_path.read_text(encoding='utf-8')) if cfg_path.exists() else {}
    cfg=cfg or {}
    target=int((cfg.get('candidate') or {}).get('daily_target',20))
    freshness=min(48,int((cfg.get('candidate') or {}).get('freshness_hours',48)))
    state_path=OUT/'dev_seen.json'
    try:
        loaded=json.loads(state_path.read_text()) if state_path.exists() else []
        seen=set(loaded if isinstance(loaded,list) else [])
    except (OSError,ValueError): seen=set()
    raw=collect(cfg)
    unique={}
    for j in raw:
        if j['title'] and j['url']:
            key=dedupe(j)
            if key not in unique or len(j['description'])>len(unique[key]['description']): unique[key]=j
    counts=Counter();rejected=[];eligible=[]
    def reject(j,reason,stage):
        counts[f'rejected:{stage}']+=1
        rejected.append({'Stage':stage,'Reason':reason,'Company':j['company'],'Role':j['title'],
                         'Location':j['location'],'Source':j['source'],'Posted':str(j['published'] or ''),'Link':j['url']})
    for j in unique.values():
        counts['unique']+=1
        if j['date_quality']!='original': reject(j,'Original posting date unavailable; updated date is not enough','freshness');continue
        posted=parse_date(j['published'])
        if not posted: reject(j,'Missing/unparseable original timestamp','freshness');continue
        age=(NOW-posted).total_seconds()/3600
        if not 0<=age<=freshness: reject(j,f'Outside {freshness}h ({age:.1f}h)','freshness');continue
        counts['fresh']+=1
        market,geo_reason=geography(j)
        if not market: reject(j,geo_reason,'geography');continue
        counts['geography']+=1
        visa_status,visa_ok=visa(j,market)
        if not visa_ok: reject(j,visa_status,'visa');continue
        counts['visa']+=1
        role_reason=role_gate(j)
        if role_reason: reject(j,role_reason,'role');continue
        counts['role']+=1
        fit,reasons,fit_warning=responsibility(j)
        # Wider than V5, but still requires meaningful responsibility evidence.
        if fit<10 or (fit_warning and fit<18): reject(j,f'Insufficient responsibilities ({fit}/40)'+(' - '+fit_warning if fit_warning else ''),'fit');continue
        counts['responsibility']+=1
        salary,salary_ok,salary_concern=salary_check(j,market)
        if not salary_ok: reject(j,salary_concern,'compensation');continue
        scored,concerns=score(j,market,visa_status,fit,reasons,salary_concern)
        if scored is None: reject(j,'Seniority requirement too high','experience');continue
        counts['scored']+=1
        # Ranking threshold; do not discard otherwise eligible jobs because score <60.
        if scored<50: reject(j,f'Low confidence score ({scored})','ranking');continue
        counts['qualified']+=1
        ident=dedupe(j)
        if ident in seen: reject(j,'Previously surfaced','seen');continue
        eligible.append((ident,{'Score':scored,'Posted':posted.isoformat(),'Company':j['company'],'Role':j['title'],
                                'Location':j['location'],'Salary':salary,'Visa':visa_status,
                                'Why You Fit':'; '.join(reasons[:5]) or 'Relevant leadership title; verify scope',
                                'Concern':'; '.join(concerns) or 'None identified',
                                'Action':'APPLY TODAY' if scored>=85 else 'STRONG - REVIEW' if scored>=72 else 'REVIEW',
                                'Link':j['url']}))
    eligible.sort(key=lambda pair:(pair[1]['Score'],pair[1]['Posted']),reverse=True)
    strong=[x for x in eligible if x[1]['Score']>=72]
    selected=strong if len(strong)>=target else eligible[:target]
    csv_path=OUT/f'dev_radar_{TODAY}.csv'
    with csv_path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(row for _,row in selected)
    audit_path=OUT/f'dev_radar_rejections_{TODAY}.csv'
    with audit_path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['Stage','Reason','Company','Role','Location','Source','Posted','Link']);w.writeheader();w.writerows(rejected)
    # Keep seen records stable; avoid replacing previous V5 IDs with incompatible keys.
    seen.update(ident for ident,_ in selected)
    state_path.write_text(json.dumps(sorted(seen),indent=2),encoding='utf-8')
    print('\n================ DEV RADAR V6 ================')
    for name in ['unique','fresh','geography','visa','role','responsibility','scored','qualified']:
        print(f'{name:22s} {counts[name]:5d}')
    print(f'NEW surfaced           {len(selected):5d}')
    print('Rejection stages:')
    for k,v in counts.most_common():
        if k.startswith('rejected:'): print(f'  {k:25s} {v}')
    print('Results:',csv_path)
    print('Rejection audit:',audit_path)
    print('================================================')

if __name__=='__main__': main()
