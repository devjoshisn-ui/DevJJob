#!/usr/bin/env python3
"""
Apoio ao comando /radar (busca de vagas na internet feita pelo Claude).

Recebe as vagas encontradas na busca (arquivo JSON: lista de objetos com
"titulo", "empresa", "link" e, opcional, "onde" e "publicado") e diz, para
cada uma:
  - JÁ NO SCRIPT  -> o screen.py já coleta essa vaga (mostra a nota/recomendação)
  - JÁ NO RADAR   -> já foi mostrada numa busca /radar anterior
  - NOVA          -> nem o script nem o radar tinham

Compara pelo título + empresa, com tolerância (nomes de empresa variam entre
sites: "Doctoralia Brasil" x "docplanner"). As NOVAS são gravadas em
output/radar_historico.json pra não aparecerem de novo como novas.

Uso:
    python radar_cruzar.py vagas_encontradas.json
    python radar_cruzar.py vagas_encontradas.json --nao-gravar   # só consulta
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import json
import re
import sys
from pathlib import Path

from collectors._util import _fold

OUT = Path("output")
HISTORICO = OUT / "radar_historico.json"
_GENERICAS = {"brasil", "brazil", "grupo", "group", "ltda", "the", "inc", "sa", "s/a", "empresa", "confidencial"}


def _palavras(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", _fold(s)).split()


def _mesma_empresa(a: str, b: str) -> bool:
    pa = [w for w in _palavras(a) if len(w) > 2 and w not in _GENERICAS]
    pb = [w for w in _palavras(b) if len(w) > 2 and w not in _GENERICAS]
    if not pa or not pb:
        return False  # "Empresa Confidencial" não casa com nada
    ja, jb = "".join(pa), "".join(pb)
    return any(w in jb for w in pa) or any(w in ja for w in pb)


def _similaridade(t1: str, t2: str) -> float:
    return difflib.SequenceMatcher(None, " ".join(_palavras(t1)), " ".join(_palavras(t2))).ratio()


def _achar(vaga: dict, base: list[dict], limiar: float = 0.8) -> dict | None:
    candidatas = [b for b in base if _mesma_empresa(vaga["empresa"], b.get("empresa", ""))]
    melhor = max(candidatas, key=lambda b: _similaridade(vaga["titulo"], b.get("titulo", "")), default=None)
    if melhor and _similaridade(vaga["titulo"], melhor.get("titulo", "")) >= limiar:
        return melhor
    return None


def _relatorio_mais_recente() -> dict:
    csvs = sorted(OUT.glob("vagas_triadas_*.csv"))
    if not csvs:
        return {}
    with csvs[-1].open(encoding="utf-8-sig") as f:
        return {r["link"]: r for r in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivo")
    ap.add_argument("--nao-gravar", action="store_true")
    args = ap.parse_args()

    vagas = json.loads(Path(args.arquivo).read_text(encoding="utf-8"))
    coletadas_path = OUT / "vagas_coletadas.json"
    if not coletadas_path.exists():
        sys.exit("output/vagas_coletadas.json não existe — rode o screen.py (ou --collect-only) antes.")
    coletadas = json.loads(coletadas_path.read_text(encoding="utf-8"))
    relatorio = _relatorio_mais_recente()
    historico = json.loads(HISTORICO.read_text(encoding="utf-8")) if HISTORICO.exists() else []

    novas = []
    for v in vagas:
        no_script = _achar(v, coletadas)
        if no_script:
            r = relatorio.get(no_script["link"], {})
            print(f"JÁ NO SCRIPT | {v['titulo']} — {v['empresa']} "
                  f"[{r.get('recomendacao', 'sem nota')} {r.get('nota_fit', '')}]")
            continue
        ja_visto = _achar(v, historico)
        if ja_visto:
            print(f"JÁ NO RADAR  | {v['titulo']} — {v['empresa']} (mostrada em {ja_visto.get('visto_em', '?')})")
            continue
        print(f"NOVA         | {v['titulo']} — {v['empresa']} | {v.get('link', '')}")
        novas.append({**v, "visto_em": dt.date.today().isoformat()})

    print(f"\n{len(vagas)} vagas: {len(novas)} novas, {len(vagas) - len(novas)} já conhecidas.")
    if novas and not args.nao_gravar:
        OUT.mkdir(exist_ok=True)
        HISTORICO.write_text(json.dumps(historico + novas, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Novas gravadas em {HISTORICO}.")


if __name__ == "__main__":
    main()
