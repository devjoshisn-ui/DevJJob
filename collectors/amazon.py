"""
Coletor via API pública (não documentada oficialmente, mas usada pelo
próprio front-end de amazon.jobs) — descoberta inspecionando a rede da
página de busca em 21/09/2026: https://www.amazon.jobs/en/search.json

Sem autenticação. Busca por termo livre + país, igual à Gupy.
"""
from __future__ import annotations

import requests

from ._util import strip_html

AMAZON_SEARCH_URL = "https://www.amazon.jobs/en/search.json"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; job-fit-screener/1.0)"}


def fetch_amazon(term: str, limit: int = 15, country: str = "BRA") -> list[dict]:
    params = {
        "base_query": term,
        "result_limit": limit,
        "sort": "relevant",
        "offset": 0,
    }
    if country:
        params["country"] = country

    resp = requests.get(AMAZON_SEARCH_URL, params=params, headers=_HEADERS, timeout=20)
    if resp.status_code != 200:
        return []
    payload = resp.json()

    jobs = []
    for j in payload.get("jobs", []):
        titulo = j.get("title", "")
        job_path = j.get("job_path", "")
        location = j.get("location", "") or j.get("normalized_location", "")
        descricao = strip_html(j.get("description") or j.get("description_short") or "")
        # os requisitos vêm em campos separados da descrição — sem eles o Jev
        # avaliava a vaga sem saber o que ela exige.
        basic = strip_html(j.get("basic_qualifications") or "")
        preferred = _cut_boilerplate(strip_html(j.get("preferred_qualifications") or ""))
        if basic:
            descricao += f"\n\nRequisitos obrigatórios: {basic}"
        if preferred:
            descricao += f"\n\nRequisitos desejáveis: {preferred}"
        job_id = j.get("id_icims") or j.get("id")

        jobs.append(
            {
                "id": f"amazon:{job_id}",
                "fonte": "amazon",
                "titulo": titulo,
                "empresa": j.get("company_name", "Amazon") or "Amazon",
                "cidade": j.get("city", ""),
                "estado": j.get("state", ""),
                "remoto": "remote" in (location or "").lower() or "remoto" in titulo.lower(),
                "link": f"https://www.amazon.jobs{job_path}" if job_path else "",
                "descricao": descricao,
                "publicado_em": j.get("posted_date", ""),
            }
        )
    return jobs


def _cut_boilerplate(text: str) -> str:
    # os "preferred_qualifications" terminam com um texto institucional padrão
    # (política de inclusão/acessibilidade) que não diz nada sobre a vaga.
    i = text.find("Our inclusive culture")
    return text[:i].strip() if i >= 0 else text
