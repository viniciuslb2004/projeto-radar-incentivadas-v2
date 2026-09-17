"""Motor de busca SEM IA do Radar de Credito Primario (CVM -- debentures/CRI/CRA/etc),
espelhando src/search_fts.py (BNDES/FINEP) mas MAIS SIMPLES: nao ha uma taxonomia de 3
niveis com dicionario de sinonimos curado (setor/subsetor/segmento do emissor vem do
MESMO cnpj_cnae que enriquece a FINEP, mas ninguem curou sinonimos especificos pra isso
ainda -- ver CLAUDE.md). Toda a "inteligencia" que existe (search_document/search_vector)
foi pre-calculada em unify_primario.py::_atualizar_busca_primario e gravada em
operations_primario -- esta busca so consulta o que ja esta pronto, sem chamada a modelo.

Prioridade de ranking (da mais forte para a mais fraca -- ver PRIORIDADE_MOTIVO):
1. Correspondencia exata/prefixo com CNPJ ou nome do emissor.
2. Correspondencia com instrumento (padronizado) ou setor/subsetor do emissor.
3. Correspondencia por QUALQUER palavra (OR) no texto completo (search_vector).
4. Correspondencia aproximada por trigrama (tolera erro de digitacao / nome parecido).

LICAO DE PERFORMANCE (ja documentada em detalhe no CLAUDE.md para o motor BNDES/FINEP,
reaplicada aqui desde o primeiro commit -- nao repetir o erro): NUNCA colocar
`search_vector @@ tsquery` dentro do mesmo CASE/subquery que roda incondicionalmente sobre
a tabela inteira -- isso ja causou uma regressao real de ~9s para 55s numa query contra o
Aiven no motor BNDES/FINEP (ver secao "Bugs reais ja corrigidos"). A tier 3 (full-text)
aqui e SEMPRE sua propria query com `search_vector @@ tsquery(...)` direto no WHERE (usa o
indice GIN idx_operations_primario_search_vector), nunca embutida num CASE."""
import re

from db import get_connection
from search_fts import PALAVRAS_GENERICAS_QUERY, _normaliza_ortografia_sql

_COLS_OPERACAO = [
    "id", "cnpj_emissor", "nome_emissor", "razao_social_oficial_emissor",
    "instrumento", "instrumento_padronizado", "setor_emissor", "subsetor_emissor",
    "segmento_emissor", "uf_emissor", "municipio_emissor", "valor_total",
    "data_referencia", "ano", "indexador_padronizado", "taxa_valor", "taxa_tipo",
]

PRIORIDADE_MOTIVO = {
    1: "Correspondência exata com CNPJ ou nome do emissor",
    2: "Correspondência com instrumento ou setor/subsetor do emissor",
    3: "Correspondência por palavra no texto completo (nome, setor, instrumento)",
    4: "Correspondência aproximada (nome parecido, possível erro de digitação)",
}

LIMIAR_SIMILARIDADE_TRGM = 0.25
MINIMO_ANTES_DE_TRIGRAMA = 10  # so paga o custo de similarity() (varre a tabela toda) se as tiers 1-3 vierem com poucos resultados


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _rows_para_resultados(rows) -> list:
    resultados = []
    for r in rows:
        d = dict(zip(_COLS_OPERACAO, r[:len(_COLS_OPERACAO)]))
        prioridade = r[len(_COLS_OPERACAO)]
        d["motivo"] = PRIORIDADE_MOTIVO.get(prioridade, "Correspondência no texto completo")
        d["prioridade"] = prioridade
        resultados.append(d)
    return resultados


def buscar_texto_primario(
    query: str, limite: int = 200, instrumento: str = None, uf: str = None,
    setor: str = None, valor_minimo: float = None,
) -> dict:
    """Busca deterministica em 4 tiers (ver PRIORIDADE_MOTIVO). instrumento/uf/setor/
    valor_minimo sao FILTROS ESTRUTURADOS (AND, nunca dentro do ranking de texto) --
    mesmo principio ja documentado pra UF no motor BNDES/FINEP: um filtro estruturado
    nunca deve competir por relevancia, so restringe o universo de linhas candidatas
    antes do ranking rodar. `setor` combina setor_emissor (4 categorias amplas, mesma
    taxonomia do BNDES) e subsetor_emissor (mais granular) NA MESMA lista de opcoes,
    mesmo padrao ja usado pelo filtro `setor` do motor BNDES/FINEP (ver search_fts.py)."""
    query = (query or "").strip()
    if not query:
        return {"query": query, "n_resultados": 0, "resultados": []}

    cnpj_digitos = _so_digitos(query)
    eh_cnpj = len(cnpj_digitos) >= 8
    cnpj_para_match = cnpj_digitos if eh_cnpj else ""

    # websearch_to_tsquery combina palavras com AND por padrao -- junta com " or " pra
    # aceitar QUALQUER palavra (mesmo motivo documentado em search_fts.py).
    palavras = [p for p in query.split() if p.lower() not in PALAVRAS_GENERICAS_QUERY] or query.split()
    query_fts = " or ".join(palavras) or query

    filtros_extra = []
    params_extra = []
    if instrumento:
        filtros_extra.append("instrumento_padronizado = ?")
        params_extra.append(instrumento)
    if uf:
        filtros_extra.append("uf_emissor = ?")
        params_extra.append(uf)
    if setor:
        filtros_extra.append("(setor_emissor = ? OR subsetor_emissor = ?)")
        params_extra.extend([setor, setor])
    if valor_minimo is not None:
        filtros_extra.append("valor_total >= ?")
        params_extra.append(valor_minimo)
    filtro_sql = ("AND " + " AND ".join(filtros_extra)) if filtros_extra else ""

    _norm = _normaliza_ortografia_sql

    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()

        # Tiers 1-2: seq scan (sem indice funcional pra unaccent(lower(campo)), mesma
        # limitacao ja documentada no motor BNDES/FINEP) -- mas SEM ts_rank_cd embutido
        # aqui dentro (ver TETO abaixo e a licao de performance no topo do arquivo):
        # calculado a parte, so nos candidatos que sobrarem, exatamente como
        # search_fts.py::TETO_TIERS123 faz.
        TETO_TIERS12 = max(limite, 3000)
        sql_tiers12 = f"""
            SELECT {", ".join(_COLS_OPERACAO)}, prioridade FROM (
                SELECT {", ".join(_COLS_OPERACAO)},
                    CASE
                        WHEN ? != '' AND regexp_replace(coalesce(cnpj_emissor, ''), '\\D', '', 'g') LIKE ? || '%%' THEN 1
                        WHEN {_norm("unaccent(lower(coalesce(nome_emissor,'')))")} LIKE {_norm("unaccent(lower(?))")} || '%%' THEN 1
                        WHEN {_norm("unaccent(lower(coalesce(instrumento_padronizado,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                          OR {_norm("unaccent(lower(coalesce(setor_emissor,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                          OR {_norm("unaccent(lower(coalesce(subsetor_emissor,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                        THEN 2
                        ELSE NULL
                    END AS prioridade
                FROM operations_primario
                WHERE 1=1 {filtro_sql}
            ) sub
            WHERE prioridade IS NOT NULL
            ORDER BY prioridade ASC
            LIMIT ?
        """
        params_tiers12 = [
            cnpj_para_match, cnpj_para_match,  # tier 1 cnpj
            query,  # tier 1 nome prefixo
            query, query, query,  # tier 2 instrumento/setor/subsetor
        ]
        params_tiers12.extend(params_extra)
        params_tiers12.append(TETO_TIERS12)
        rows_tiers12 = cur.execute(sql_tiers12, params_tiers12).fetchall()
        rows = [r + (0.0,) for r in rows_tiers12]  # placeholder de rank_fts

        ids_ja_vistos = [r[0] for r in rows]
        faltam = limite - len(rows)
        rows_tier3 = []
        if faltam > 0:
            exclusao_sql, params_exclusao = "", []
            if ids_ja_vistos:
                exclusao_sql = "AND NOT (id = ANY(?))"
                params_exclusao = [ids_ja_vistos]
            sql_tier3 = f"""
                SELECT {", ".join(_COLS_OPERACAO)}, 3 AS prioridade,
                    ts_rank_cd(search_vector, websearch_to_tsquery('portuguese', {_norm("unaccent(?)")})) AS rank_fts
                FROM operations_primario
                WHERE search_vector @@ websearch_to_tsquery('portuguese', {_norm("unaccent(?)")})
                    {exclusao_sql} {filtro_sql}
                ORDER BY rank_fts DESC
                LIMIT ?
            """
            params_tier3 = [query_fts, query_fts] + params_exclusao + params_extra + [faltam]
            rows_tier3 = cur.execute(sql_tier3, params_tier3).fetchall()
        rows += rows_tier3

        # rank_fts de verdade so pros candidatos das tiers 1-2 (mesmo truque id = ANY(?)
        # bounded aos poucos candidatos que sobreviveram ao filtro, ver search_fts.py).
        idx_prioridade = len(_COLS_OPERACAO)
        idx_rank_fts = idx_prioridade + 1
        ids_tiers12 = [r[0] for r in rows if r[idx_prioridade] <= 2]
        if ids_tiers12:
            sql_rank = f"""
                SELECT id, ts_rank_cd(search_vector, websearch_to_tsquery('portuguese', {_norm("unaccent(?)")})) AS rank_fts
                FROM operations_primario WHERE id = ANY(?)
            """
            rank_fts_por_id = dict(cur.execute(sql_rank, [query_fts, ids_tiers12]).fetchall())
            rows = [
                r[:-1] + (rank_fts_por_id.get(r[0], 0.0),) if r[idx_prioridade] <= 2 else r
                for r in rows
            ]

        rows.sort(key=lambda r: (r[idx_prioridade], -r[idx_rank_fts]))

        if len(rows) < MINIMO_ANTES_DE_TRIGRAMA:
            sql_trigrama = f"""
                SELECT {", ".join(_COLS_OPERACAO)}, 4 AS prioridade,
                    GREATEST(
                        similarity(unaccent(lower(coalesce(nome_emissor,''))), unaccent(lower(?))),
                        similarity(unaccent(lower(coalesce(segmento_emissor,''))), unaccent(lower(?)))
                    ) AS rank_fts
                FROM operations_primario
                WHERE (
                    similarity(unaccent(lower(coalesce(nome_emissor,''))), unaccent(lower(?))) > {LIMIAR_SIMILARIDADE_TRGM}
                    OR similarity(unaccent(lower(coalesce(segmento_emissor,''))), unaccent(lower(?))) > {LIMIAR_SIMILARIDADE_TRGM}
                )
                {filtro_sql}
                ORDER BY rank_fts DESC
                LIMIT ?
            """
            params_trigrama = [query, query, query, query]
            params_trigrama.extend(params_extra)
            params_trigrama.append(limite - len(rows))
            ja_incluidos = {r[0] for r in rows}
            rows_trigrama = cur.execute(sql_trigrama, params_trigrama).fetchall()
            rows = rows + [r for r in rows_trigrama if r[0] not in ja_incluidos]
    finally:
        conn.close()

    rows = rows[:limite]
    resultados = _rows_para_resultados(rows)
    return {
        "query": query,
        "eh_busca_cnpj": eh_cnpj,
        "n_resultados": len(resultados),
        "resultados": resultados,
    }


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "debenture"
    out = buscar_texto_primario(q)
    print(f"query={out['query']!r} n_resultados={out['n_resultados']}")
    for r in out["resultados"][:15]:
        print(f"  [{r['prioridade']}] {r['nome_emissor']} | {r['instrumento_padronizado']} | {r['setor_emissor']} -- {r['motivo']}")
