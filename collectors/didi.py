"""
Coletor do site de vagas da DiDi (careers.didiglobal.com), onde a 99 publica
as vagas do Brasil. Descoberto lendo o JavaScript do próprio site em
30/09/2026 (Nuxt; axios com baseURL https://cdncareers.didiglobal.com:34003/):

- POST /icims/searchJobList {"country": "Brazil", "keyValue": "", "teamId": "",
  "typeId": ""} -> todas as vagas do país (~100), só com título/time/local.
- GET /icims/searchJob?id=<id> -> detalhe da vaga (HTML em teamRoleDetail,
  roleDetail, eagerDetail; "hire" traz a empresa, ex. "435 - 99 FOOD LTDA").
- página pública da vaga: https://careers.didiglobal.com/jobDetail:<id>

Certificado: o servidor da API não envia o certificado intermediário (o
navegador busca sozinho, o Python não). Em vez de desligar a verificação
(como o próprio site faz), usamos os certificados raiz padrão (certifi) + o
intermediário da DigiCert salvo em didi_intermediate.pem (baixado de
http://cacerts.digicert.cn/GeoTrustG2TLSCNRSA4096SHA2562022CA1.crt, válido
até 2032).
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import re
import tempfile
from pathlib import Path

import certifi
import requests

from ._util import strip_html, title_matches

API = "https://cdncareers.didiglobal.com:34003"
PAGINA_VAGA = "https://careers.didiglobal.com/jobDetail:{id}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; job-fit-screener/1.0)",
           "front-version": "1.0.0", "device-type": "pc"}
_INTERMEDIARIO = Path(__file__).with_name("didi_intermediate.pem")


def _ca_bundle() -> str:
    caminho = os.path.join(tempfile.gettempdir(), "job-fit-screener-didi-ca.pem")
    if not os.path.exists(caminho):
        with open(caminho, "w", encoding="ascii") as f:
            f.write(Path(certifi.where()).read_text(encoding="ascii"))
            f.write("\n" + _INTERMEDIARIO.read_text(encoding="ascii"))
    return caminho


def _empresa(hire: str | None) -> str:
    # "435 - 99 FOOD LTDA" -> "99 FOOD LTDA"; sem info -> "99 / DiDi"
    nome = re.sub(r"^\s*\d+\s*-\s*", "", hire or "").strip()
    return nome if nome and nome != "-" else "99 / DiDi"


def _detalhe(job: dict, verify: str) -> dict:
    d: dict = {}
    try:
        resp = requests.get(f"{API}/icims/searchJob", params={"id": job["id"]},
                            headers=HEADERS, timeout=30, verify=verify)
        d = (resp.json() or {}).get("result") or {}
    except (requests.RequestException, ValueError):
        pass  # fica sem descrição; o Jev avalia pelo título
    partes = [d.get(k) for k in ("teamRoleDetail", "roleDetail", "eagerDetail")]
    local = job.get("address") or ""
    cidade, _, pais = local.partition(" - ")
    return {
        "id": f"didi:{job['id']}",
        "fonte": "didi",
        "titulo": (job.get("jobTitle") or "").strip(),
        "empresa": _empresa(d.get("hire")),
        "cidade": cidade.strip() if cidade.strip() != "null" else "",
        "estado": "",
        "remoto": False,
        "link": PAGINA_VAGA.format(id=job["id"]),
        "descricao": strip_html(" ".join(p for p in partes if p and p != "None")),
        "publicado_em": "",
    }


def fetch_didi(country: str = "Brazil", term_filter=None, limit: int | None = None) -> list[dict]:
    verify = _ca_bundle()
    resp = requests.post(
        f"{API}/icims/searchJobList",
        json={"country": country, "keyValue": "", "teamId": "", "typeId": ""},
        headers=HEADERS, timeout=30, verify=verify,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"API da DiDi respondeu erro: {payload.get('message')}")
    vagas = [
        j for j in payload.get("result") or []
        if j.get("id") and (term_filter is None or title_matches(j.get("jobTitle", ""), term_filter))
    ]
    if limit is not None:
        vagas = vagas[:limit]
    with cf.ThreadPoolExecutor(6) as ex:
        return list(ex.map(lambda j: _detalhe(j, verify), vagas))
