"""
Coletor via scraping best-effort da página de vagas do Mercado Livre/Mercado
Pago (careers-meli.mercadolibre.com).

Diferente da Gupy/Amazon, não achei uma API JSON pública por trás dela — a
página é uma SPA em Next.js e, mesmo inspecionando a rede no navegador
enquanto pagina os resultados, nenhuma chamada XHR/fetch de dados de vaga
apareceu (os cards já vêm prontos assim que a página carrega). Ou seja, o
scraping aqui é de HTML mesmo, sem meio-termo de API.

RISCO CONHECIDO: uma requisição HTTP simples (sem navegador de verdade) para
essa URL retornou 403 num teste em 21/09/2026 — provável proteção antibot
(Akamai/Cloudflare, comum em sites de e-commerce grandes). Os headers abaixo
tentam simular um navegador real, mas isso pode não ser suficiente — se
`fetch_mercadolivre` vier sempre vazio, rode `debug_mercadolivre.py` pra ver
se a resposta é mesmo bloqueada (403) ou se só o HTML mudou de estrutura.

Não há busca por termo livre na página (só filtros de país/setor/senioridade
etc.) — por isso este coletor não filtra por search_terms, igual à
Greenhouse/InHire: traz as N primeiras páginas de vagas abertas no Brasil e
deixa o Jev decidir a aderência de cada uma.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from ._util import strip_html

MELI_CAREERS_URL = "https://careers-meli.mercadolibre.com/en/positions"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
_PUBLISHED_RE = re.compile(r"Published\s+\d+\s+\w+", re.IGNORECASE)


def fetch_mercadolivre(max_pages: int = 2, country: str = "Brazil") -> list[dict]:
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        params = {"country": country, "page": page}
        resp = requests.get(MELI_CAREERS_URL, params=params, headers=_HEADERS, timeout=20)
        if resp.status_code != 200:
            break  # provável bloqueio antibot (403) ou fim das páginas
        soup = BeautifulSoup(resp.text, "html.parser")

        page_jobs = 0
        for link in soup.select('a[href*="positions?id="]'):
            href = link.get("href", "")
            job_id = _extract_id(href)
            if not job_id or job_id in seen_ids:
                continue

            card = _find_card(link)
            heading = card.find("h3") if card else None
            if not heading:
                continue

            seen_ids.add(job_id)
            page_jobs += 1

            titulo = heading.get_text(strip=True)
            card_text = card.get_text(" ", strip=True)
            published_match = _PUBLISHED_RE.search(card_text)

            jobs.append(
                {
                    "id": f"mercadolivre:{job_id}",
                    "fonte": "mercadolivre",
                    "titulo": titulo,
                    "empresa": "Mercado Livre/Mercado Pago",
                    "cidade": _guess_location(card),
                    "estado": "",
                    "remoto": "remote" in card_text.lower() or "remoto" in card_text.lower(),
                    "link": f"https://careers-meli.mercadolibre.com{href}" if href.startswith("/") else href,
                    "descricao": strip_html(card_text),
                    "publicado_em": published_match.group(0) if published_match else "",
                }
            )

        if page_jobs == 0:
            break

    return jobs


def _extract_id(href: str) -> str:
    qs = parse_qs(urlparse(href).query)
    return (qs.get("id") or [""])[0]


def _find_card(link):
    # sobe a árvore a partir do link "Learn more" até achar um ancestral que
    # já contenha o título (h3) — é o card inteiro da vaga.
    node = link
    for _ in range(8):
        node = node.parent
        if node is None:
            return None
        if node.find("h3"):
            return node
    return None


def _guess_location(card) -> str:
    img = card.find("img")
    if img:
        span = img.find_next_sibling("span")
        if span:
            return span.get_text(strip=True)
    return ""
