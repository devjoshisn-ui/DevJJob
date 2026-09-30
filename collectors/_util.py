import html as _html
import re
import unicodedata

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str, max_len: int = 12000) -> str:
    # desfaz o escape antes de remover as tags: a Greenhouse devolve o HTML
    # escapado ("&lt;p&gt;"), que antes passava direto como lixo pro Jev.
    text = _html.unescape(text or "")
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)  # entidades que estavam dentro do HTML (&amp;nbsp; etc.)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _fold(text: str) -> str:
    """minúsculas e sem acento, pra "Negócios" bater com "negocios"."""
    sem_acento = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return sem_acento.lower()


def title_matches(titulo: str, keywords) -> bool:
    """True se o título contém algum dos trechos em `keywords` (string única ou
    lista), ignorando maiúsculas e acentos. Sem keywords, tudo passa.
    `keywords` também pode ser uma função titulo -> bool (ver title_filter)."""
    if callable(keywords):
        return keywords(titulo)
    if not keywords:
        return True
    if isinstance(keywords, str):
        keywords = [keywords]
    t = _fold(titulo)
    return any(_fold(k) in t for k in keywords)


def title_filter(keywords, excludes):
    """Função titulo -> bool: passa se bater com `keywords` e NÃO bater com
    nenhum trecho de `excludes`. Pode ser passada como term_filter pros coletores."""
    def ok(titulo: str) -> bool:
        return title_matches(titulo, keywords) and not (excludes and title_matches(titulo, excludes))
    return ok


# Vagas remotas internacionais: só servem se aceitam quem mora no Brasil.
# Forte: o local cita Brasil/LATAM/Américas. Fraco: "anywhere/worldwide" — vale
# só se o local não restringir a país/região ("Anywhere in the United States").
_LOCAL_FORTE = re.compile(r"\b(brazil|brasil|latam|latin america|america latina|south america|americas)\b")
_LOCAL_FRACO = re.compile(r"\b(worldwide|anywhere|global|world)\b")
_RESTRICAO = re.compile(
    r"\b(united states|usa|us|u\.s|canada|uk|united kingdom|europe|emea|apac|asia|india|"
    r"germany|france|spain|australia|north america|cet|est|pst|timezone)\b"
)
_TEXTO_ACEITA_BR = re.compile(
    r"\b(brazil|brasil|latam|latin america|america latina|south america|"
    r"anywhere in the world|remote worldwide|work from anywhere in the world|globally remote)\b"
)


def aceita_brasil(local: str, descricao: str = "", anywhere_confiavel: bool = True) -> bool:
    """True se a vaga remota aceita candidato no Brasil: o local cita Brasil,
    LATAM ou Américas, ou diz "anywhere/worldwide" sem restringir a país.
    "USA", "Europe", "Argentina, Mexico" etc. ficam de fora. Local vazio, só
    "Remote" — ou "Anywhere" em site onde isso não é confiável
    (anywhere_confiavel=False) — só passa se a descrição citar Brasil/LATAM/
    "anywhere in the world"."""
    loc = _fold(local).strip()
    if _LOCAL_FORTE.search(loc):
        return True
    if anywhere_confiavel and _LOCAL_FRACO.search(loc) and not _RESTRICAO.search(loc):
        return True
    ambiguo = loc in ("", "remote", "remoto", "fully remote", "100% remote") or (
        not anywhere_confiavel and loc in ("anywhere", "worldwide")
    )
    if ambiguo:
        return bool(_TEXTO_ACEITA_BR.search(_fold(descricao)))
    return False
