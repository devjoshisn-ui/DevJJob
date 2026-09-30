#!/usr/bin/env python3
"""
A página de vagas do Mercado Livre/Mercado Pago é a fonte mais frágil e
arriscada do pipeline (ver aviso no topo de collectors/mercadolivre.py) —
sem API pública e com possível proteção antibot. Se fetch_mercadolivre()
vier sempre vazio, rode:

    python debug_mercadolivre.py

Isso salva o HTML bruto da primeira página em
output/_debug_mercadolivre.html e mostra o status HTTP da resposta:

  - status 403 (ou parecido) = bloqueio antibot mesmo, não tem muito o que
    ajustar no código — a fonte provavelmente não é viável de automatizar
    daqui.
  - status 200 mas sem cards nenhum = a estrutura do HTML mudou; abra o
    arquivo salvo, ache um card de vaga e ajuste os seletores em
    collectors/mercadolivre.py (_find_card / _guess_location).
"""
from pathlib import Path

import requests

from collectors.mercadolivre import MELI_CAREERS_URL, _HEADERS

resp = requests.get(MELI_CAREERS_URL, params={"country": "Brazil", "page": 1}, headers=_HEADERS, timeout=20)

Path("output").mkdir(exist_ok=True)
Path("output/_debug_mercadolivre.html").write_text(resp.text, encoding="utf-8")

print(f"Status HTTP: {resp.status_code}")
print(f"HTML salvo em output/_debug_mercadolivre.html ({len(resp.text)} chars)")

if resp.status_code != 200:
    print("\nNão veio 200 — provável bloqueio antibot. Veja o HTML salvo para confirmar.")
else:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select('a[href*="positions?id="]')
    print(f"\n{len(cards)} links de vaga encontrados na página.")
    if not cards:
        print("Zero cards com status 200 — a estrutura do HTML provavelmente mudou.")
