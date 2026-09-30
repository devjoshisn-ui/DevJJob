#!/usr/bin/env python3
"""
Mede se o ranking do Jev concorda com a sua opinião, usando um gabarito de
vagas que você mesmo marcou (gabarito.csv) — pra calibrar preferências,
perguntas etc. com número, não com um caso isolado.

gabarito.csv tem as colunas:
    rotulo   -> boa / media / ruim   (sua opinião; linhas sem rótulo são ignoradas)
    link     -> link da vaga (é por ele que a vaga é encontrada)
    titulo, empresa, comentario -> só pra você se orientar

As vagas precisam estar em output/vagas_coletadas.json (gerado por toda rodada
do screen.py, ou só a coleta com `python screen.py --collect-only`).

Uso:
    python calibrar.py                     # config atual (com preferências)
    python calibrar.py --sem-preferencias  # compara: como fica sem o bloco de preferências
    python calibrar.py --mock              # testa o script sem gastar chamadas

Cada vaga do gabarito é uma chamada ao Jev (sem histórico — é sempre medido do zero).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import itertools
import json
import sys
from pathlib import Path

import yaml

from jev_client import JevClient, JevError, MockJevClient
from screen import RECOMENDACAO_ORDEM, ajustar_recomendacao, build_questions, carregar_preferencias, score_job

ROTULO_ORDEM = {"boa": 0, "media": 1, "ruim": 2}


def rank_key(r: dict):
    # mesma ordenação do relatório: recomendação primeiro, depois nota
    return (RECOMENDACAO_ORDEM.get(r["recomendacao"], 9), -r["nota_fit"])


def pares_corretos(results: list[dict]) -> tuple[int, int]:
    """Entre pares de vagas com rótulos diferentes, quantos o ranking põe na
    ordem certa (a de melhor rótulo acima). Empate conta meio acerto."""
    certos = total = 0.0
    for a, b in itertools.combinations(results, 2):
        ra, rb = ROTULO_ORDEM[a["rotulo"]], ROTULO_ORDEM[b["rotulo"]]
        if ra == rb:
            continue
        melhor, pior = (a, b) if ra < rb else (b, a)
        total += 1
        if rank_key(melhor) < rank_key(pior):
            certos += 1
        elif rank_key(melhor) == rank_key(pior):
            certos += 0.5
    return certos, total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--gabarito", default="gabarito.csv")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--sem-preferencias", action="store_true", help="ignora o bloco `preferencias` do config")
    args = ap.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    cv_text = Path(config["cv_path"]).read_text(encoding="utf-8")
    preferencias = "" if args.sem_preferencias else carregar_preferencias(config)
    out_dir = Path(config.get("output_dir", "output"))

    coletadas_path = out_dir / "vagas_coletadas.json"
    if not coletadas_path.exists():
        sys.exit(f"{coletadas_path} não existe — rode antes: python screen.py --collect-only")
    por_link = {j["link"]: j for j in json.loads(coletadas_path.read_text(encoding="utf-8"))}

    with open(args.gabarito, encoding="utf-8-sig") as f:
        texto = f.read()
    # Excel em português salva CSV com ";" — aceita os dois separadores
    delim = ";" if texto.splitlines()[0].count(";") > texto.splitlines()[0].count(",") else ","
    linhas = [
        r for r in csv.DictReader(texto.splitlines(), delimiter=delim)
        if (r.get("rotulo") or "").strip().lower() in ROTULO_ORDEM
    ]
    if not linhas:
        sys.exit(f"Nenhuma linha com rótulo boa/media/ruim em {args.gabarito}.")

    client = MockJevClient() if args.mock else JevClient(model=config.get("jev_model", "jev-latest"))
    questions = build_questions(com_preferencias=bool(preferencias))

    results = []
    for linha in linhas:
        job = por_link.get(linha["link"].strip())
        if not job:
            print(f"  [pulada] não está na última coleta (vaga encerrada?): {linha['titulo']} — {linha['link']}")
            continue
        try:
            r = score_job(client, cv_text, job, questions, preferencias)
        except JevError as e:
            print(f"  [aviso] falha ao pontuar '{job['titulo']}': {e}", file=sys.stderr)
            continue
        ajustar_recomendacao(r)  # mesmas regras do relatório
        r["rotulo"] = linha["rotulo"].strip().lower()
        results.append(r)

    results.sort(key=rank_key)
    variante = "sem preferências" if args.sem_preferencias else "com preferências"
    print(f"\nRanking do Jev ({variante}) x seu rótulo:")
    for r in results:
        print(f"  {r['rotulo']:5s} | [{r['recomendacao']:15s}] {r['nota_fit']:4.1f}  {r['titulo']} — {r['empresa']}")

    certos, total = pares_corretos(results)
    boas_rebaixadas = [r for r in results if r["rotulo"] == "boa" and r["recomendacao"] in ("baixa_prioridade", "nao_aplicar")]
    ruins_promovidas = [r for r in results if r["rotulo"] == "ruim" and r["recomendacao"] == "aplicar_agora"]
    print(f"\nPares na ordem certa: {certos:g}/{total:g}" + (f" ({certos / total:.0%})" if total else ""))
    print(f"Vagas 'boa' marcadas como baixa_prioridade/nao_aplicar: {len(boas_rebaixadas)}")
    print(f"Vagas 'ruim' marcadas como aplicar_agora: {len(ruins_promovidas)}")

    if args.mock:
        return  # notas simuladas não valem registro — só testam o script

    out_path = out_dir / f"calibragem_{dt.datetime.now():%Y-%m-%d_%H%M}_{'sem' if args.sem_preferencias else 'com'}_pref.csv"
    cols = ["rotulo", "recomendacao", "nota_fit", "aderencia_nivel", "senioridade_ok", "gap_critico", "titulo", "empresa", "link"]
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow({c: r.get(c, "") for c in cols})
    print(f"Detalhes em {out_path}")


if __name__ == "__main__":
    main()
