#!/usr/bin/env python3
"""
Se a beBee mudar a estrutura da página e collectors/bebee.py parar de achar
empresa/cidade direito, rode:

    python debug_bebee.py "algum termo de busca"

Isso salva o HTML bruto da primeira página de resultados em
output/_debug_bebee.html (abra num editor e procure pelos cards de vaga) e
imprime, pra cada link de vaga encontrado, o texto puro do card — compare
com o que collectors/bebee.py está extraindo e ajuste os seletores.
"""
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from collectors.bebee import BEBEE_SEARCH_URL, _HEADERS

term = sys.argv[1] if len(sys.argv) > 1 else "business development"
resp = requests.get(BEBEE_SEARCH_URL, params={"q": term}, headers=_HEADERS, timeout=20)
resp.raise_for_status()

Path("output").mkdir(exist_ok=True)
Path("output/_debug_bebee.html").write_text(resp.text, encoding="utf-8")
print(f"HTML salvo em output/_debug_bebee.html ({len(resp.text)} chars)\n")

soup = BeautifulSoup(resp.text, "html.parser")
for i, a in enumerate(soup.select('a[href^="/br/jobs/"]')):
    heading = a.find(["h1", "h2", "h3", "h4"])
    if not heading:
        continue
    print(f"--- card {i} ---")
    print("href:", a.get("href"))
    print("texto:", a.get_text(" ", strip=True)[:300])
    print()
