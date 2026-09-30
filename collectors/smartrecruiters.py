"""
Coletor via API pública oficial do SmartRecruiters (Posting API, sem
autenticação) — usado pela Serasa Experian, entre outras. Confirmado em
29/09/2026 (Experian: 204 vagas no Brasil):

    GET https://api.smartrecruiters.com/v1/companies/<empresa>/postings?country=br&limit=100&offset=<n>
      -> {"totalFound": N, "content": [{id, name, location{city, remote}, releasedDate}]}
    GET https://api.smartrecruiters.com/v1/companies/<empresa>/postings/<id>
      -> jobAd.sections.{jobDescription, qualifications, ...}.text (HTML), postingUrl

<empresa> é o identificador que aparece em jobs.smartrecruiters.com/<empresa>/...
(ex.: "Experian"). O filtro country=br já vem da própria API.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import requests

from ._util import strip_html, title_matches

SR_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
_PAGE = 100
_WORKERS = 6


def fetch_smartrecruiters(company: str, empresa: str = "", term_filter="", limit: int | None = None,
                          fetch_descriptions: bool = True) -> list[dict]:
    url = SR_URL.format(company=company)
    postings: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(url, params={"country": "br", "limit": _PAGE, "offset": offset}, timeout=30)
        if resp.status_code == 404:
            return []  # identificador errado, ou a empresa não usa SmartRecruiters
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("content") or []
        postings += batch
        offset += _PAGE
        if not batch or offset >= (data.get("totalFound") or 0):
            break

    escolhidas = [p for p in postings if title_matches(p.get("name") or "", term_filter)]
    if limit is not None:
        escolhidas = escolhidas[:limit]

    if fetch_descriptions:
        with ThreadPoolExecutor(_WORKERS) as ex:
            detalhes = list(ex.map(lambda p: _detail(url, p["id"]), escolhidas))
    else:
        detalhes = [{}] * len(escolhidas)

    jobs = []
    for p, det in zip(escolhidas, detalhes):
        loc = p.get("location") or {}
        secoes = (det.get("jobAd") or {}).get("sections") or {}
        descricao = "\n\n".join(
            strip_html((secoes.get(k) or {}).get("text", ""))
            for k in ("jobDescription", "qualifications")
            if (secoes.get(k) or {}).get("text")
        )
        jobs.append(
            {
                "id": f"smartrecruiters:{company}:{p['id']}",
                "fonte": "smartrecruiters",
                "titulo": (p.get("name") or "").strip(),
                "empresa": empresa or (p.get("company") or {}).get("name") or company,
                "cidade": loc.get("city") or "",
                "estado": loc.get("region") or "",
                "remoto": bool(loc.get("remote")),
                "link": det.get("postingUrl") or f"https://jobs.smartrecruiters.com/{company}/{p['id']}",
                "descricao": descricao,
                "publicado_em": (p.get("releasedDate") or "")[:10],
            }
        )
    return jobs


def _detail(url: str, posting_id: str) -> dict:
    try:
        resp = requests.get(f"{url}/{posting_id}", timeout=30)
        return resp.json() if resp.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        return {}
