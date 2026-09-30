"""
Coletor do Remote.io (https://www.remote.io) — sem API pública (o robots.txt
bloqueia /api/, então não usamos); lemos as páginas HTML de listagem, que o
robots.txt libera. Confirmado em 29/09/2026:

- /remote-jobs/<local>/<área> lista até 20 vagas (as mais recentes), com
  título, empresa e os países aceitos ("Argentina, Mexico, ..., Brazil").
  Locais úteis: brazil, latin-america, anywhere. Não há paginação no HTML —
  por isso combinamos local x área pra cobrir mais vagas.
- a página de cada vaga tem um JSON-LD JobPosting (descrição, data, salário).

Só abrimos a página das vagas que passam no filtro de título e de local, pra
não fazer centenas de requisições.
"""
from __future__ import annotations

import concurrent.futures as cf
import html as _html
import json
import re

import requests

from ._util import aceita_brasil, strip_html, title_matches

BASE = "https://www.remote.io"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"}
DEFAULT_LOCAIS = ["brazil", "latin-america", "anywhere"]
DEFAULT_AREAS = [
    "", "operations", "sales-partnerships", "business-development", "marketing",
    "product", "finance", "data", "executive-c-suite", "other",
]
_CARD_RE = re.compile(
    r'<a href="(/remote-jobs/[^"]+-\d+)"[^>]*><h3[^>]*>(.*?)</h3></a>\s*'
    r"<p[^>]*>(.*?)</p>\s*<div[^>]*>\s*<span>(.*?)</span>",
    re.S,
)
_LDJSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _get(url: str) -> str:
    resp = requests.get(url, headers=UA, timeout=30)
    resp.raise_for_status()
    return resp.content.decode("utf-8", "replace")


def _listar(local: str, area: str) -> list[tuple[str, str, str, str]]:
    url = f"{BASE}/remote-jobs/{local}" + (f"/{area}" if area else "")
    try:
        pagina = _get(url)
    except requests.RequestException:
        return []  # uma listagem fora do ar não derruba as outras
    return [
        (link, _html.unescape(t).strip(), _html.unescape(e).strip(), _html.unescape(loc).strip())
        for link, t, e, loc in _CARD_RE.findall(pagina)
    ]


def _salario(base: dict) -> str:
    v = (base or {}).get("value") or {}
    lo, hi = v.get("minValue"), v.get("maxValue")
    moeda = base.get("currency", "") if base else ""
    if lo and hi:
        return f"{moeda} {lo:,} a {hi:,}".strip()
    return ""


def _detalhe(card: tuple[str, str, str, str]) -> dict:
    link, titulo, empresa, local = card
    posting: dict = {}
    try:
        for bloco in _LDJSON_RE.findall(_get(BASE + link)):
            d = json.loads(bloco)
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                posting = d
                break
    except (requests.RequestException, ValueError):
        pass  # fica sem descrição; o Jev avalia pelo título
    salario = ""
    if isinstance(posting.get("baseSalary"), dict):
        salario = _salario(posting["baseSalary"])
    return {
        "id": f"remoteio:{link.rsplit('-', 1)[-1]}",
        "fonte": "remoteio",
        "titulo": titulo,
        "empresa": empresa or (posting.get("hiringOrganization") or {}).get("name", ""),
        "cidade": f"Remoto internacional — {local}",
        "estado": "",
        "remoto": True,
        "link": BASE + link,
        "descricao": strip_html(posting.get("description", "")),
        "publicado_em": posting.get("datePosted", ""),
        "salario": salario,
    }


def fetch_remoteio(
    locais: list[str] | None = None,
    areas: list[str] | None = None,
    term_filter=None,
    limit: int | None = None,
) -> list[dict]:
    pares = [(l, a) for l in (locais or DEFAULT_LOCAIS) for a in (areas if areas is not None else DEFAULT_AREAS)]
    cards: dict[str, tuple] = {}
    with cf.ThreadPoolExecutor(4) as ex:
        for lista in ex.map(lambda p: _listar(*p), pares):
            for c in lista:
                cards.setdefault(c[0], c)

    escolhidos = [
        c for c in cards.values()
        if (term_filter is None or title_matches(c[1], term_filter))
        and (aceita_brasil(c[3], anywhere_confiavel=False) or _ambiguo(c[3]))
    ]
    if limit is not None:
        escolhidos = escolhidos[:limit]
    with cf.ThreadPoolExecutor(4) as ex:
        jobs = list(ex.map(_detalhe, escolhidos))
    return [
        j for j in jobs
        if aceita_brasil(j["cidade"].split("— ", 1)[-1], j["descricao"], anywhere_confiavel=False)
    ]


def _ambiguo(local: str) -> bool:
    # no Remote.io "Anywhere" muitas vezes é vaga dos EUA (Philadelphia, salário
    # em USD) — decide pela descrição, depois de abrir a vaga
    return local.strip().lower() in ("", "remote", "remoto", "anywhere", "worldwide")
