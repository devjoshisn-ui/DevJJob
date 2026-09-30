"""
Coletor das vagas da TikTok no Brasil (lifeattiktok.com).

O site busca as vagas numa API JSON pública, sem login — descoberta em
25/09/2026. Só exige o header `website-path: tiktok` (sem ele responde
"invalid request"):

    POST https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts
         {"keyword": "", "limit": 50, "offset": 0, "location_code_list": ["CT_130"], ...}
      -> {"data": {"job_post_list": [{id, title, description, requirement,
                                      city_info, job_category, ...}], "count": N}}

O filtro por país (CN_15 = Brasil) não funciona — só por cidade. Cidades
brasileiras com vaga em 25/09/2026: São Paulo (CT_130) e Brasília (CT_1102325).
Se a TikTok abrir vaga em outra cidade, adicione o código em BRASIL_CITIES (dá
pra descobrir buscando keyword "Brazil" e olhando city_info.code).

A lista já traz descrição e requisitos completos — nenhuma requisição extra
por vaga.
"""
from __future__ import annotations

import requests

from ._util import title_matches

TIKTOK_URL = "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
TIKTOK_JOB_URL = "https://lifeattiktok.com/search/{id}"
BRASIL_CITIES = {"CT_130": "São Paulo", "CT_1102325": "Brasília"}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "website-path": "tiktok",
    "Origin": "https://lifeattiktok.com",
    "Referer": "https://lifeattiktok.com/",
}
_PAGE = 50


def fetch_tiktok(term_filter="", limit: int | None = None) -> list[dict]:
    """term_filter: trecho ou lista de trechos do título (ver title_matches)."""
    posts: list[dict] = []
    offset = 0
    while True:
        body = {
            "keyword": "",
            "limit": _PAGE,
            "offset": offset,
            "job_category_id_list": [],
            "location_code_list": list(BRASIL_CITIES),
            "subject_id_list": [],
            "recruitment_id_list": [],
        }
        resp = requests.post(TIKTOK_URL, json=body, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}
        page = data.get("job_post_list") or []
        posts += page
        offset += _PAGE
        if not page or offset >= (data.get("count") or 0):
            break

    jobs = []
    for p in posts:
        if limit is not None and len(jobs) >= limit:
            break
        titulo = (p.get("title") or "").strip()
        if not title_matches(titulo, term_filter):
            continue
        city = p.get("city_info") or {}
        descricao = (p.get("description") or "").strip()
        if p.get("requirement"):
            descricao += "\n\nRequisitos: " + p["requirement"].strip()
        jobs.append(
            {
                "id": f"tiktok:{p.get('id')}",
                "fonte": "tiktok",
                "titulo": titulo,
                "empresa": "TikTok",
                "cidade": BRASIL_CITIES.get(city.get("code"), city.get("en_name") or ""),
                "estado": "",
                "remoto": "remote" in titulo.lower(),
                "link": TIKTOK_JOB_URL.format(id=p.get("id")),
                "descricao": descricao,
                "publicado_em": "",
            }
        )
    return jobs
