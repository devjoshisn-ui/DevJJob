"""
Coletor via feed RSS oficial do We Work Remotely — sem scraping, sem
autenticação. Formato estável e documentado pelo próprio site
(https://weworkremotely.com/remote-job-rss-feed), confirmado em 21/09/2026:
cada <item> tem title (formato "Empresa: Cargo"), region, country, state,
category, type, description (HTML), pubDate, link.

Cobertura majoritariamente remota/internacional em inglês — bom complemento
à Gupy/InHire/Greenhouse (Brasil) e à beBee, não substituto.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from ._util import aceita_brasil, strip_html

WWR_CATEGORY_URL = "https://weworkremotely.com/categories/{category}.rss"
WWR_ALL_URL = "https://weworkremotely.com/remote-jobs.rss"

# Categorias do próprio site que fazem sentido pro perfil de negócios/estratégia.
# Passe o slug completo (sem o .rss) em config.yaml se quiser outra.
DEFAULT_CATEGORY = "remote-sales-and-marketing-jobs"


def fetch_weworkremotely(term: str = "", category: str = DEFAULT_CATEGORY, limit: int = 15) -> list[dict]:
    url = WWR_CATEGORY_URL.format(category=category) if category else WWR_ALL_URL
    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (compatible; job-fit-screener/1.0)"})
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    items = root.findall("./channel/item")

    term_lower = term.lower()
    jobs = []
    for item in items:
        raw_title = (item.findtext("title") or "").strip()
        empresa, _, titulo = raw_title.partition(":")
        titulo = titulo.strip() or raw_title
        empresa = empresa.strip() if titulo != raw_title else ""

        if term_lower and term_lower not in raw_title.lower():
            continue

        region = (item.findtext("region") or "").strip()
        link = (item.findtext("link") or "").strip()
        descricao = strip_html(item.findtext("description") or "")
        if not aceita_brasil(region, descricao):
            continue  # ex.: "USA Only", "Europe Only"
        pub_date = (item.findtext("pubDate") or "").strip()

        jobs.append(
            {
                "id": f"weworkremotely:{link}",
                "fonte": "weworkremotely",
                "titulo": titulo,
                "empresa": empresa,
                "cidade": region,
                "estado": "",
                "remoto": True,
                "link": link,
                "descricao": descricao,
                "publicado_em": pub_date,
            }
        )
        if len(jobs) >= limit:
            break

    return jobs
