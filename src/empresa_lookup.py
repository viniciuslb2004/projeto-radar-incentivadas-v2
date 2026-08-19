"""Enriquecimento de busca via web para nomes de empresa/termos desconhecidos.

A busca principal (search.py) so conhece o vocabulario que aparece nas operacoes do
BNDES/FINEP -- se alguem procura o nome de uma empresa que nunca pegou credito
incentivado (ex: "Quicksoft"), o embedding da query nao tem nada para se agarrar e o
resultado vira ruido (ver CONFIANCA_MINIMA em search.py). Nao ha, localmente, uma base
de CNPJ -> atividade pesquisavel por NOME: o cache em enrich_cnae.py so cobre CNPJs que
ja aparecem nas planilhas brutas da FINEP (indexado por CNPJ, nao por nome), e baixar a
base publica da Receita Federal (arquivos de varios GB) a cada busca nao e viavel.

A alternativa deste modulo: uma busca web leve, SEM chave de API (via o endpoint HTML
do DuckDuckGo, que nao exige autenticacao/JS), para descobrir em 1-2 frases o que a
empresa/termo parece ser -- e devolver esse texto para search.py usar como reforco da
query antes de reembutir (mesmo espirito de EXPANSAO_TERMOS, so que descoberto em tempo
real em vez de vir de um dicionario fixo).

Melhor esforco DE VERDADE: qualquer falha (rede fora do ar, DuckDuckGo bloqueando ou
mudando o HTML, resposta vazia) devolve None em vez de propagar excecao -- isso nunca
pode travar ou derrubar a busca principal, que ja funciona bem sozinha na maioria dos
casos (esta funcao so entra em cena quando confianca_baixa=True)."""
import re

import requests

DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
TIMEOUT_SEGUNDOS = 7
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Sem BeautifulSoup no requirements.txt -- o HTML do DuckDuckGo e simples o bastante
# (resultados sempre num <a class="result__snippet">) para um regex direto resolver
# sem trazer uma dependencia nova so para isto.
_TAG_RE = re.compile(r"<[^>]+>")
_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")

MAX_CHARS_DESCRICAO = 400  # texto vira sufixo da query (" | " + isso) -- curto de proposito


def _limpar_html(trecho: str) -> str:
    texto = _TAG_RE.sub("", trecho)
    texto = (
        texto.replace("&amp;", "&")
        .replace("&#x27;", "'")
        .replace("&quot;", '"')
        .replace("&nbsp;", " ")
    )
    return _WHITESPACE_RE.sub(" ", texto).strip()


def buscar_atividade_empresa(nome: str):
    """Pesquisa `nome` na web (DuckDuckGo, sem chave de API) e devolve um texto curto
    (algumas frases, ate MAX_CHARS_DESCRICAO caracteres) descrevendo o que a empresa/
    termo parece ser -- pensado para ser anexado a query original antes de reembutir
    (ver buscar_rapido() em search.py). Devolve None se a busca nao trouxer nada
    usavel ou se qualquer etapa falhar (rede, timeout, parsing) -- best-effort mesmo,
    nunca deve propagar excecao para quem chamou."""
    if not nome or not nome.strip():
        return None
    try:
        resp = requests.post(
            DUCKDUCKGO_URL,
            data={"q": f"{nome.strip()} empresa"},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SEGUNDOS,
        )
        resp.raise_for_status()
        trechos = _SNIPPET_RE.findall(resp.text)
        if not trechos:
            return None

        snippets = [s for s in (_limpar_html(t) for t in trechos[:3]) if s]
        if not snippets:
            return None

        combinado = " ".join(snippets)
        if len(combinado) > MAX_CHARS_DESCRICAO:
            combinado = combinado[:MAX_CHARS_DESCRICAO].rsplit(" ", 1)[0] + "..."
        return combinado or None
    except Exception:
        return None


if __name__ == "__main__":
    import sys

    nome_teste = " ".join(sys.argv[1:]) or "Quicksoft"
    resultado = buscar_atividade_empresa(nome_teste)
    print(resultado if resultado else "(nenhum resultado / falha)")
