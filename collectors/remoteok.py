"""
Coletor via API pública do Remote OK (https://remoteok.com/api), sem chave.
Confirmado em 29/09/2026: devolve uma lista JSON cujo 1º item é o aviso legal
e os demais são vagas (position, company, location, description em HTML,
salary_min/salary_max, url, date). `?tag=<tag>` traz as vagas daquela tag.

Termos de uso da API: dar crédito e linkar a página da vaga no Remote OK — por
isso o link salvo é sempre o `url` do Remote OK (não o apply_url).

A API não tem filtro de país: fica só o que aceita Brasil/LATAM/anywhere
(ver _util.aceita_brasil). Não tem busca por termo — as tags abaixo cobrem o
perfil e o screen.py aplica o filtro de título (title_keywords).
"""
from __future__ import annotations

import time

import requests

from ._util import aceita_brasil, strip_html, title_matches

REMOTEOK_URL = "https://remoteok.com/api"
UA = {"User-Agent": "Mozilla/5.0 (compatible; job-fit-screener/1.0)"}
DEFAULT_TAGS = [
    "sales", "marketing", "operations", "business", "strategy", "ecommerce",
    "analyst", "account manager", "growth", "product manager", "customer success",
]


def _salario(j: dict) -> str:
    lo, hi = j.get("salary_min") or 0, j.get("salary_max") or 0
    if lo and hi:
        return f"US$ {lo:,} a US$ {hi:,} /ano"
    if lo or hi:
        return f"US$ {(lo or hi):,} /ano"
    return ""


def fetch_remoteok(tags: list[str] | None = None, term_filter=None, limit: int | None = None) -> list[dict]:
    brutas: dict[str, dict] = {}
    for tag in [""] + list(tags if tags is not None else DEFAULT_TAGS):
        resp = requests.get(REMOTEOK_URL, params={"tag": tag} if tag else None, headers=UA, timeout=30)
        resp.raise_for_status()
        for j in resp.json():
            if j.get("id") and j.get("position"):
                brutas[str(j["id"])] = j
        time.sleep(1)  # API gratuita — sem martelar

    jobs = []
    for j in brutas.values():
        titulo = strip_html(j.get("position", ""))
        if term_filter is not None and not title_matches(titulo, term_filter):
            continue
        descricao = strip_html(j.get("description", ""))
        local = (j.get("location") or "").strip()
        if not aceita_brasil(local, descricao):
            continue
        jobs.append(
            {
                "id": f"remoteok:{j['id']}",
                "fonte": "remoteok",
                "titulo": titulo,
                "empresa": (j.get("company") or "").strip(),
                "cidade": f"Remoto internacional — {local or 'local não informado'}",
                "estado": "",
                "remoto": True,
                "link": j.get("url", ""),
                "descricao": descricao,
                "publicado_em": (j.get("date") or "")[:10],
                "salario": _salario(j),
            }
        )
        if limit is not None and len(jobs) >= limit:
            break
    return jobs
