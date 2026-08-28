"""Enriquecimento de busca via web para nomes de empresa/termos desconhecidos.

A busca principal (search.py) so conhece o vocabulario que aparece nas operacoes do
BNDES/FINEP -- se alguem procura o nome de uma empresa que nunca pegou credito
incentivado (ex: "Quicksoft"), o embedding da query nao tem nada para se agarrar e o
resultado vira ruido (ver CONFIANCA_MINIMA em search.py). Nao ha, localmente, uma base
de CNPJ -> atividade pesquisavel por NOME: o cache em enrich_cnae.py so cobre CNPJs que
ja aparecem nas planilhas brutas da FINEP (indexado por CNPJ, nao por nome), e baixar a
base publica da Receita Federal (arquivos de varios GB) a cada busca nao e viavel.

A alternativa deste modulo: buscas web leves, SEM chave de API, para descobrir em 1-2
frases o que a empresa/termo parece ser -- e devolver esse texto para search.py usar
como reforco da query antes de reembutir (mesmo espirito de EXPANSAO_TERMOS, so que
descoberto em tempo real em vez de vir de um dicionario fixo).

TRES fontes, tentadas em cadeia (para no primeiro sucesso):
1. DuckDuckGo (html.duckduckgo.com/html) -- scrape sem JS/auth, mas e a fonte mais
   propensa a bloqueio: depois de um punhado de requisicoes ela passa a devolver uma
   pagina "anomaly" (deteccao de trafego automatizado) em vez de resultados -- foi
   observado acontecendo em uso real, nao e so teorico.
2. Bing (www.bing.com/search) -- scrape equivalente, mas empiricamente mais tolerante a
   uso esporadico sem chave/autenticacao; serve de rede de seguranca quando o DDG esta
   bloqueando.
3. Wikipedia PT (opensearch + REST summary, API oficial) -- so cobre empresas grandes o
   bastante para ter verbete, mas nunca bloqueia (e API publica de verdade, nao scrape).
   So aceitamos MATCH EXATO de titulo (case-insensitive): o opensearch "corrige" termos
   sem correspondencia exata para o titulo mais parecido, o que para siglas/nomes curtos
   pode vir totalmente errado (ex: "MPR" -> "Mpreg", "Quicksoft" -> "Quicksort") -- nesses
   casos e mais seguro devolver None do que injetar uma descricao de outro assunto.

Melhor esforco DE VERDADE: qualquer falha (rede fora do ar, fonte bloqueando ou mudando
o HTML, resposta vazia) passa para a proxima fonte; se todas falharem, devolve None em
vez de propagar excecao -- isso nunca pode travar ou derrubar a busca principal, que ja
funciona bem sozinha na maioria dos casos (esta funcao so entra em cena quando
confianca_baixa=True). Timeout curto por fonte para o orcamento total (3 fontes) nao
estourar uns 15-20s no pior caso.
"""
import html
import re
from urllib.parse import quote

import requests

DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
BING_URL = "https://www.bing.com/search"
WIKIPEDIA_OPENSEARCH_URL = "https://pt.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY_URL = "https://pt.wikipedia.org/api/rest_v1/page/summary"

TIMEOUT_SEGUNDOS = 6
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Sem BeautifulSoup no requirements.txt -- o HTML do DuckDuckGo/Bing e simples o
# bastante (resultados sempre num bloco reconhecivel por classe) para um regex direto
# resolver sem trazer uma dependencia nova so para isto.
_TAG_RE = re.compile(r"<[^>]+>")
_DDG_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_BING_SNIPPET_RE = re.compile(r'<p class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")

MAX_CHARS_DESCRICAO = 400  # texto vira sufixo da query (" | " + isso) -- curto de proposito


def _limpar_html(trecho: str) -> str:
    texto = _TAG_RE.sub("", trecho)
    # html.unescape (stdlib) cobre entidades nomeadas E numericas (ex: "&#231;" -> "c")
    # -- o Bing em particular devolve os snippets cheios de entidades numericas, que o
    # replace() manual antigo (so &amp;/&quot;/&nbsp;) deixava passar direto como lixo.
    texto = html.unescape(texto)
    return _WHITESPACE_RE.sub(" ", texto).strip()


def _cortar(texto: str) -> str:
    if len(texto) > MAX_CHARS_DESCRICAO:
        return texto[:MAX_CHARS_DESCRICAO].rsplit(" ", 1)[0] + "..."
    return texto


def _via_duckduckgo(nome: str):
    resp = requests.post(
        DUCKDUCKGO_URL,
        data={"q": f"{nome} empresa"},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SEGUNDOS,
    )
    resp.raise_for_status()
    trechos = _DDG_SNIPPET_RE.findall(resp.text)
    snippets = [s for s in (_limpar_html(t) for t in trechos[:3]) if s]
    if not snippets:
        return None
    return _cortar(" ".join(snippets))


def _via_bing(nome: str):
    resp = requests.get(
        BING_URL,
        params={"q": f"{nome} empresa"},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SEGUNDOS,
    )
    resp.raise_for_status()
    trechos = _BING_SNIPPET_RE.findall(resp.text)
    snippets = [s for s in (_limpar_html(t) for t in trechos[:3]) if s]
    if not snippets:
        return None
    return _cortar(" ".join(snippets))


def _via_wikipedia(nome: str):
    resp = requests.get(
        WIKIPEDIA_OPENSEARCH_URL,
        params={"action": "opensearch", "search": nome, "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SEGUNDOS,
    )
    resp.raise_for_status()
    dados = resp.json()
    titulos = dados[1] if len(dados) > 1 else []
    if not titulos:
        return None
    titulo = titulos[0]
    # Match exato (case-insensitive) -- ver docstring do modulo. O opensearch devolve
    # "sugestao mais parecida" mesmo sem correspondencia real, e para siglas/nomes
    # curtos isso costuma vir para um assunto totalmente diferente.
    if titulo.strip().lower() != nome.strip().lower():
        return None

    resp2 = requests.get(
        f"{WIKIPEDIA_SUMMARY_URL}/{quote(titulo)}",
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SEGUNDOS,
    )
    resp2.raise_for_status()
    extrato = (resp2.json().get("extract") or "").strip()
    if not extrato:
        return None
    return _cortar(extrato)


# Ordem importa: DDG primeiro (historicamente o melhor cobrindo empresas pequenas/medias
# quando nao esta bloqueado), Bing como rede de seguranca (mesma cobertura, bloqueia
# menos), Wikipedia por ultimo (nunca bloqueia, mas so cobre entidades notaveis).
_FONTES = (_via_duckduckgo, _via_bing, _via_wikipedia)


def buscar_atividade_empresa(nome: str):
    """Pesquisa `nome` na web (sem chave de API, ver _FONTES) e devolve um texto curto
    (algumas frases, ate MAX_CHARS_DESCRICAO caracteres) descrevendo o que a empresa/
    termo parece ser -- pensado para reforcar a query original antes de reembutir (ver
    buscar_rapido() em search.py). Devolve None se nenhuma fonte trouxer algo usavel ou
    se todas falharem -- best-effort mesmo, nunca deve propagar excecao para quem chamou."""
    if not nome or not nome.strip():
        return None
    termo = nome.strip()
    for fonte in _FONTES:
        try:
            resultado = fonte(termo)
        except Exception:
            resultado = None
        if resultado:
            return resultado
    return None


if __name__ == "__main__":
    import sys

    nome_teste = " ".join(sys.argv[1:]) or "Quicksoft"
    resultado = buscar_atividade_empresa(nome_teste)
    print(resultado if resultado else "(nenhum resultado / falha)")
