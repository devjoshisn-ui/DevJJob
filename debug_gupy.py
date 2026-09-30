#!/usr/bin/env python3
"""
Se a Gupy mudar o formato da API pública e collectors/gupy.py parar de
devolver título/empresa/etc., rode:

    python debug_gupy.py "algum termo de busca"

Isso imprime o JSON bruto do primeiro resultado, pra você comparar com os
nomes de campo usados em collectors/gupy.py (função fetch_gupy) e ajustar.
"""
import json
import sys

import requests

from collectors.gupy import GUPY_URL

term = sys.argv[1] if len(sys.argv) > 1 else "analista"
resp = requests.get(GUPY_URL, params={"jobName": term, "offset": 0, "limit": 1}, timeout=20)
resp.raise_for_status()
payload = resp.json()
raw = (payload.get("data") or payload.get("results") or payload.get("jobs") or [None])[0]
print(json.dumps(raw, ensure_ascii=False, indent=2))
