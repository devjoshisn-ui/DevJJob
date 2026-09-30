"""
Coletor de vagas via API pública do Remotive (vagas remotas, majoritariamente
internacionais/em inglês) — https://remotive.com/api/remote-jobs
Não requer chave. Formato de campos documentado e estável.
"""
from __future__ import annotations

import requests

from ._util import aceita_brasil, strip_html as _strip_html

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"


def fetch_remotive(term: str, category: str = "", limit: int = 15) -> list[dict]:
    params = {"search": term}
    if category:
        params["category"] = category

    resp = requests.get(REMOTIVE_URL, params=params, timeout=20)
    resp.raise_for_status()
    payload = resp.json()

    # só vagas que aceitam quem mora no Brasil ("USA", "Europe" ficam de fora)
    raw_jobs = [
        j for j in (payload.get("jobs") or [])
        if aceita_brasil(j.get("candidate_required_location", ""), j.get("description", ""))
    ][:limit]

    jobs = []
    for j in raw_jobs:
        jobs.append(
            {
                "id": f"remotive:{j.get('id')}",
                "fonte": "remotive",
                "titulo": j.get("title", ""),
                "empresa": j.get("company_name", ""),
                "cidade": j.get("candidate_required_location", ""),
                "estado": "",
                "remoto": True,
                "link": j.get("url", ""),
                "descricao": _strip_html(j.get("description", "")),
                "publicado_em": j.get("publication_date", ""),
            }
        )
    return jobs
