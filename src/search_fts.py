"""Motor de busca SEM IA (full-text search Postgres: tsvector + unaccent + pg_trgm).

Substitui, no caminho padrao de producao, o motor de embeddings (ver search.py,
embeddings.py) -- que continua intacto e religavel (ver MOTOR_BUSCA_IA em
webapp/main.py), so nao roda por padrao. Toda a "inteligencia" (sinonimos, taxonomia)
foi pre-calculada no enriquecimento (ver src/search_taxonomy.py e
unify.py::_search_document()) e gravada em `operations.search_document`/`search_vector`
-- esta busca so consulta o que ja esta pronto, sem nenhuma chamada a modelo.

Prioridade de ranking (da mais forte para a mais fraca -- ver PRIORIDADE_MOTIVO):
1. Correspondencia exata/prefixo com CNPJ ou nome do cliente.
2. Correspondencia com setor/subsetor/segmento (CNAE).
3. Correspondencia com produto/instrumento/indexador.
4. Correspondencia no texto completo (full-text search, inclui sinonimos/taxonomia).
5. Correspondencia aproximada por trigrama (tolera erro de digitacao / nome parecido).
"""
import re

from db import get_connection

_COLS_OPERACAO = [
    "id", "agencia", "instrumento", "cliente", "cnpj", "uf", "setor_bndes", "subsetor_bndes", "segmento",
    "valor_contratado", "data_contratacao", "descricao_projeto",
]

PRIORIDADE_MOTIVO = {
    1: "Correspondência exata com CNPJ ou nome da empresa",
    2: "Correspondência com setor, subsetor ou segmento (CNAE)",
    3: "Correspondência com produto, instrumento ou indexador",
    4: "Correspondência no texto completo (descrição, sinônimos e taxonomia)",
    5: "Correspondência aproximada (nome parecido, possível erro de digitação)",
}

LIMIAR_SIMILARIDADE_TRGM = 0.25

# Palavras genericas DESTE dominio -- nao sao stopword em portugues "de verdade" (o
# dicionario 'portuguese' do Postgres ja remove preposicoes/artigos), mas em uma base
# onde TODO registro e uma operacao de credito de uma empresa, a palavra "empresa"
# nao discrimina nada (aparece por acaso, como substring literal, no nome legal de
# muitas empresas -- ex: "IGUATEMI EMPRESA DE SHOPPING CENTERS", "EMPRESA ELETRICA
# BRAGANTINA"). Confirmado empiricamente: buscar "empresa de hospitais em SP" media o
# match generico de "empresa" no NOME (peso A, o mais alto) por cima do match
# especifico de "hospitais" no setor/segmento (peso B) -- essas ficam de fora do
# OR-tsquery de texto livre (tier 4), mas continuam valendo normalmente nos tiers 1-3
# (comparam a FRASE completa digitada, nao palavra a palavra).
PALAVRAS_GENERICAS_QUERY = {"empresa", "empresas", "companhia", "companhias"}

# UF (2 letras) e um FILTRO estruturado, nao um termo de conteudo -- deixa-lo entrar
# no OR-tsquery de texto livre (tier 4) e um problema pior do que "empresa": o codigo
# aparece no campo `uf` de MILHARES de operacoes (sigla curta, sem stem, sem sinonimo
# nenhum competindo por peso), entao qualquer busca combinando um termo raro (ex:
# "hospitais", so numa operacao) com uma UF (ex: "SP", em milhares) faz o volume de
# matches de UF dominar o ranking, mesmo com peso mais baixo. Confirmado
# empiricamente: "empresa de hospitais em SP" so passou a achar o unico hospital real
# da base depois de tratar a UF como filtro (AND uf = ?), tirando-a do ts_rank.
_UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _extrair_uf(palavras: list) -> tuple:
    """Devolve (uf_detectada_ou_None, palavras_restantes) -- so reconhece a UF quando
    aparece como uma palavra ISOLADA de 2 letras (nao dispara em falso dentro de uma
    palavra maior)."""
    for p in palavras:
        if p.upper() in _UFS_VALIDAS:
            return p.upper(), [x for x in palavras if x is not p]
    return None, palavras


MINIMO_ANTES_DE_TRIGRAMA = 10  # so paga o custo de similarity() (varre a tabela toda) se as tiers 1-4 (indexadas) vierem com poucos resultados


def _rows_para_resultados(rows) -> list:
    resultados = []
    for r in rows:
        d = dict(zip(_COLS_OPERACAO, r[:len(_COLS_OPERACAO)]))
        prioridade = r[len(_COLS_OPERACAO)]
        d["motivo"] = PRIORIDADE_MOTIVO.get(prioridade, "Correspondência no texto completo")
        d["prioridade"] = prioridade
        resultados.append(d)
    return resultados


def buscar_texto(query: str, limite: int = 200) -> dict:
    """Busca determinística: normalizacao de acento/caixa (unaccent/lower, via SQL),
    correspondencia exata/prefixo e full-text em portugues primeiro (tiers 1-4, todas
    apoiadas por indice -- rapidas mesmo em tabela grande); so paga o custo de
    similarity() por trigrama (tier 5 -- sem indice utilizavel pra essa comparacao
    especifica, varre a tabela inteira) se as tiers indexadas voltarem com poucos
    resultados. Ordenado por prioridade e depois por relevancia dentro de cada
    prioridade."""
    query = (query or "").strip()
    if not query:
        return {"query": query, "n_resultados": 0, "resultados": []}

    cnpj_digitos = _so_digitos(query)
    eh_cnpj = len(cnpj_digitos) >= 8  # CNPJ parcial (raiz) ou completo (14 digitos)
    # So usa o fragmento numerico no tier 1 (match de CNPJ) se ele proprio parecer um
    # CNPJ (>=8 digitos): sem isso, uma query como "xyzabc123nada" extraia "123" e
    # desse falso-positivo de "correspondencia exata" com qualquer CNPJ que comece
    # com 123, no topo do ranking -- bug real encontrado ao validar a busca.
    cnpj_para_match = cnpj_digitos if eh_cnpj else ""

    # websearch_to_tsquery, por padrao, combina palavras separadas por espaco com AND
    # (exige TODAS as palavras no mesmo documento) -- bom pra 2-3 palavras-chave, ruim
    # pra uma busca livre em linguagem natural ("fintech de credito para pequenas
    # empresas"): nenhum documento teria as 6 palavras ao mesmo tempo. Junta as
    # palavras com " or " (palavra-chave que websearch_to_tsquery reconhece) antes de
    # passar pra ele -- assim documentos com QUALQUER uma das palavras (ou sinonimo
    # gravado em search_document) entram, ranqueados por ts_rank_cd (mais palavras
    # batendo = rank mais alto), em vez de exigir a frase inteira.
    palavras = [p for p in query.split() if p.lower() not in PALAVRAS_GENERICAS_QUERY] or query.split()
    uf_detectada, palavras = _extrair_uf(palavras)
    query_fts = " or ".join(palavras) or query

    conn = get_connection()
    try:
        cur = conn.cursor()
        filtro_uf = "AND uf = ?" if uf_detectada else ""

        sql_principal = f"""
            SELECT {", ".join(_COLS_OPERACAO)}, prioridade, rank_fts FROM (
                SELECT {", ".join(_COLS_OPERACAO)},
                    CASE
                        WHEN ? != '' AND regexp_replace(cnpj, '\\D', '', 'g') LIKE ? || '%%' THEN 1
                        WHEN unaccent(lower(cliente)) LIKE unaccent(lower(?)) || '%%' THEN 1
                        WHEN unaccent(lower(coalesce(setor_bndes,''))) LIKE '%%' || unaccent(lower(?)) || '%%'
                          OR unaccent(lower(coalesce(subsetor_bndes,''))) LIKE '%%' || unaccent(lower(?)) || '%%'
                          OR unaccent(lower(coalesce(segmento,''))) LIKE '%%' || unaccent(lower(?)) || '%%'
                        THEN 2
                        WHEN unaccent(lower(coalesce(produto,''))) LIKE '%%' || unaccent(lower(?)) || '%%'
                          OR unaccent(lower(coalesce(instrumento_financeiro,''))) LIKE '%%' || unaccent(lower(?)) || '%%'
                          OR unaccent(lower(coalesce(indexador,''))) LIKE '%%' || unaccent(lower(?)) || '%%'
                        THEN 3
                        WHEN search_vector @@ websearch_to_tsquery('portuguese', unaccent(?)) THEN 4
                        ELSE NULL
                    END AS prioridade,
                    ts_rank_cd(search_vector, websearch_to_tsquery('portuguese', unaccent(?))) AS rank_fts
                FROM operations
                WHERE 1=1 {filtro_uf}
            ) sub
            WHERE prioridade IS NOT NULL
            ORDER BY prioridade ASC, rank_fts DESC
            LIMIT ?
        """
        params_principal = [
            cnpj_para_match, cnpj_para_match,  # tier 1 cnpj
            query,  # tier 1 cliente prefixo
            query, query, query,  # tier 2 setor/subsetor/segmento
            query, query, query,  # tier 3 produto/instrumento/indexador
            query_fts,  # tier 4 fts (WHEN)
            query_fts,  # tier 4 fts (rank_fts)
        ]
        if uf_detectada:
            params_principal.append(uf_detectada)
        params_principal.append(limite)
        rows = cur.execute(sql_principal, params_principal).fetchall()

        if len(rows) < MINIMO_ANTES_DE_TRIGRAMA:
            sql_trigrama = f"""
                SELECT {", ".join(_COLS_OPERACAO)}, 5 AS prioridade,
                    GREATEST(
                        similarity(unaccent(lower(cliente)), unaccent(lower(?))),
                        similarity(unaccent(lower(coalesce(segmento,''))), unaccent(lower(?)))
                    ) AS rank_fts
                FROM operations
                WHERE (
                    similarity(unaccent(lower(cliente)), unaccent(lower(?))) > {LIMIAR_SIMILARIDADE_TRGM}
                    OR similarity(unaccent(lower(coalesce(segmento,''))), unaccent(lower(?))) > {LIMIAR_SIMILARIDADE_TRGM}
                )
                {filtro_uf}
                ORDER BY rank_fts DESC
                LIMIT ?
            """
            params_trigrama = [query, query, query, query]
            if uf_detectada:
                params_trigrama.append(uf_detectada)
            params_trigrama.append(limite - len(rows))
            ja_incluidos = {r[0] for r in rows}
            rows_trigrama = cur.execute(sql_trigrama, params_trigrama).fetchall()
            rows = rows + [r for r in rows_trigrama if r[0] not in ja_incluidos]
    finally:
        conn.close()

    resultados = _rows_para_resultados(rows)
    return {
        "query": query,
        "eh_busca_cnpj": eh_cnpj,
        "n_resultados": len(resultados),
        "resultados": resultados,
    }


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "empresa de hospitais em SP"
    out = buscar_texto(q)
    print(f"query={out['query']!r} n_resultados={out['n_resultados']}")
    for r in out["resultados"][:15]:
        print(f"  [{r['prioridade']}] {r['cliente']} | {r['setor_bndes']} | {r['segmento']} -- {r['motivo']}")
