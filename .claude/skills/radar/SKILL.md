---
name: radar
description: Busca vagas do perfil do Michel na internet (Google, LinkedIn, páginas de ATS), mostra só as que o screen.py ainda não coleta e adiciona ao config.yaml as empresas novas cujo sistema de vagas o script sabe ler. Use quando ele digitar /radar ou pedir "busca no Google", "tem vaga nova na internet?", "roda o radar".
---

# Radar de vagas na internet

Complementa o `screen.py`: ele coleta em massa das fontes do `config.yaml`; o
radar procura na internet o que ficou de fora — principalmente empresas que
não estão no config (foi assim que a vaga da Jet Brasil apareceu, via Jack &
Jill, em 29/09/2026). Fale em português, direto e sem enrolação.

Regras que valem o tempo todo:
- Nunca invente vaga, empresa, link, salário ou modelo de trabalho. O que não
  estiver na página vira "não informado".
- Só apresente vaga com link que você realmente abriu ou que veio do resultado
  da busca. Prefira o link oficial (ATS/site da empresa) ao do LinkedIn.
- Nunca se candidate nem tome ação em nome dele.
- Diga quais fontes foram consultadas e quais falharam/bloquearam.

## 1. Preparar

1. Leia do `config.yaml`: `search_terms`, `preferencias` e `title_exclude`.
   É isso que define o que ele quer (e não quer: vendedor/hunter com meta,
   analista júnior, loja, logística operacional, estágio, engenharia).
2. Veja a data de `output/vagas_coletadas.json`. Se tiver mais de 3 dias,
   avise que o cruzamento fica menos preciso e ofereça rodar
   `python screen.py --collect-only` antes (não rode sem ele pedir).

## 2. Buscar

Faça de 8 a 15 buscas (WebSearch), variando cargos em português e inglês e
nomes alternativos (RevOps/Revenue Operations, Sales Ops/Operações
Comerciais/Planejamento Comercial, Business Analyst/Analista de Negócios,
GTM/Go-to-Market, E-commerce/Marketplace/Key Account/Vendor/Category,
Growth, Estratégia, Parcerias, DTC/D2C), com "São Paulo" ou "remoto".
Misture três tipos de busca:

- **Páginas de ATS** (onde aparecem empresas fora do radar):
  `site:gupy.io`, `site:inhire.app`, `site:teamtailor.com`,
  `site:myworkdayjobs.com`, `site:jobs.lever.co`,
  `site:job-boards.greenhouse.io`, `site:jobs.ashbyhq.com`,
  `site:jobs.smartrecruiters.com` + cargo.
- **Listagens públicas do LinkedIn**: páginas como
  `https://br.linkedin.com/jobs/<cargo>-vagas` (ex.
  `analista-de-planejamento-comercial-vagas`) abertas com WebFetch, pedindo
  "TITULO | EMPRESA | LOCAL | DATA | URL" de todas as vagas. Anúncio do
  LinkedIn pode estar velho ("há 5 meses") — trate como não confirmado.
- **Busca aberta** ("vaga gerente de e-commerce marketplace São Paulo").

Descarte já na leitura: fora do Brasil (salvo remoto aceitando Brasil), e
títulos que batem com `title_exclude` ou com o NÃO QUERO das preferências.

## 3. Cruzar com o que o script já tem

Grave as vagas encontradas num JSON no scratchpad — lista de
`{"titulo", "empresa", "link", "onde", "publicado"}` — e rode:

    python radar_cruzar.py <arquivo.json>

Ele marca cada vaga como JÁ NO SCRIPT (com a nota do Jev), JÁ NO RADAR
(mostrada numa busca anterior) ou NOVA, e grava as novas em
`output/radar_historico.json`. Só as NOVAS vão pro relatório.

## 4. Conferir as novas que parecem boas

Pra cada NOVA com cara de match (no máximo ~10), abra a página (WebFetch):
confirme se continua aberta, pegue local, modelo, senioridade e requisitos
principais, e procure o link oficial se veio do LinkedIn.

## 5. Trazer a empresa pro script

Pra cada empresa nova com vaga relevante:

    python descobrir_ats.py --link "<link oficial da vaga>"
    python descobrir_ats.py <nomeempresa> [variações]

Se o ATS for um que o script lê (Gupy, InHire, Greenhouse, Lever, Ashby,
Workday, SmartRecruiters, Teamtailor), **confira que o board é da empresa
certa e tem vaga no Brasil** (abra algumas vagas pelo coletor em
`collectors/`) e adicione no `config.yaml`, na seção da fonte, com um
comentário datado dizendo de onde veio (ex. `# 29/09/2026 via /radar —
"Gerente de E-commerce"`). Nunca adicione board sem conferir — "via" no
Greenhouse, por exemplo, é outra empresa, dos EUA. Se o ATS não for
suportado, só registre no relatório.

## 6. Relatório

Comece com:

    📡 RADAR — <data>
    buscas feitas: N | vagas encontradas: N | novas: N | já no script: N

Depois:
- **🟢 Novas com match forte** e **🟡 Novas pra conferir** (quando falta
  informação importante). Pra cada uma: cargo, empresa, local, modelo
  (ou "não informado"), data, por que combina com as preferências, lacunas,
  situação ("aberta confirmada" ou "não foi possível confirmar") e link.
- **Empresas adicionadas ao script** (fonte e motivo) — elas entram na
  próxima rodada do `screen.py` e passam pelo Jev.
- **Fontes consultadas** e as que não deu pra acessar.

Prefira poucas vagas boas a uma lista longa. Se não houver nada novo que
valha, diga isso.
