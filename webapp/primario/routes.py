"""Rotas do Radar de Credito Primario (`/api/primario/*`) -- mercado de capitais
primario (debentures/CRI/CRA/notas comerciais/letras financeiras/CDCA/CCB, dados da
CVM), consumindo a tabela `operations_primario` construida em sessao anterior (ver
CLAUDE.md, secao "Radar de Credito Primario -- Pipeline CVM"). Pacote ISOLADO, mesmo
espirito de `webapp/admin/` -- nunca misturado com `webapp/main.py` (grande, do outro
mercado). Registrado em `webapp/main.py` via `app.include_router(primario_router,
prefix="/api/primario")` -- autenticacao: NENHUMA dependency propria aqui, o gate
global `_verificar_acesso` (ver webapp/main.py) ja cobre qualquer rota sob `/api/*`
(inclusive `/api/primario/*`, testado ao vivo -- ver CLAUDE.md).

Sem frontend/toggle de mercado/Transacoes Salvas aqui -- isso e trabalho de outra
sessao, construida em cima destas rotas (ver CLAUDE.md)."""
from fastapi import APIRouter, Query

from db import get_connection
from search_fts_primario import buscar_texto_primario

router = APIRouter()

_COLS_OPERACAO_LISTA = [
    "id", "cnpj_emissor", "nome_emissor", "razao_social_oficial_emissor",
    "instrumento", "instrumento_padronizado", "setor_emissor", "subsetor_emissor",
    "segmento_emissor", "uf_emissor", "municipio_emissor",
    "valor_total", "quantidade_total", "preco_unitario",
    "data_referencia", "ano", "trimestre",
    "indexador_padronizado", "taxa_valor", "taxa_tipo",
    "prazo_dias", "prazo_meses", "incentivada", "regime_fiduciario",
]

ORDENACAO_COLUNAS = {
    "valor": "valor_total",
    "data": "data_referencia",
    "prazo": "prazo_meses",
    "taxa": "taxa_valor",
    "nome": "nome_emissor",
}


def _filters_clause_primario(instrumento=None, uf=None, setor=None, data_inicio=None, data_fim=None):
    """Filtros estruturados equivalentes a `webapp/main.py::_filters_clause`, adaptados
    ao schema de `operations_primario` -- NAO existe conceito de `agencia` neste
    mercado (ver CLAUDE.md), entao nao ha parametro equivalente. `setor` combina
    setor_emissor (4 categorias amplas, MESMA taxonomia BNDES via cnpj_cnae) e
    subsetor_emissor (mais granular) num OR simples, mesmo padrao ja usado pelo
    filtro `setor` do motor de busca BNDES/FINEP (ver search_fts.py) -- o front nao
    precisa saber se o valor escolhido e setor ou subsetor. Datas comparam
    `data_referencia` (melhor data disponivel, ver unify_primario.py), mesma
    convencao textual ISO (AAAA-MM-DD) de `operations.data_contratacao`."""
    if data_inicio and data_fim and data_inicio > data_fim:
        data_inicio, data_fim = data_fim, data_inicio
    clauses = []
    params = []
    if instrumento and instrumento != "Todos":
        clauses.append("instrumento_padronizado = ?")
        params.append(instrumento)
    if uf and uf != "Todas":
        clauses.append("uf_emissor = ?")
        params.append(uf)
    if setor and setor != "Todos":
        clauses.append("(setor_emissor = ? OR subsetor_emissor = ?)")
        params.extend([setor, setor])
    if data_inicio:
        clauses.append("data_referencia >= ?")
        params.append(data_inicio)
    if data_fim:
        clauses.append("data_referencia < ?")
        params.append(data_fim)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@router.get("/filtros")
def filtros():
    """Valores distintos para popular selects -- espelha `GET /api/filtros` (BNDES/
    FINEP). `setores`/`subsetores` só têm os valores que já resolveram via CNPJ (ver
    CLAUDE.md -- emissor `setor_emissor IS NULL` é um estado normal/esperado, não um
    bug); um emissor pendente simplesmente não aparece nesses dois selects até
    resolver, mas continua contável em `/api/primario/kpis`/`operacoes`."""
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()

        def col_values(col, tabela="operations_primario"):
            return [r[0] for r in cur.execute(
                f"SELECT DISTINCT {col} FROM {tabela} WHERE {col} IS NOT NULL ORDER BY {col}"
            ).fetchall()]

        min_max = cur.execute("SELECT MIN(data_referencia), MAX(data_referencia) FROM operations_primario").fetchone()
        return {
            "instrumentos": col_values("instrumento_padronizado"),
            "setores": col_values("setor_emissor"),
            "subsetores": col_values("subsetor_emissor"),
            "ufs": col_values("uf_emissor"),
            "indexadores": col_values("indexador_padronizado"),
            "anos": col_values("ano"),
            "data_min": min_max[0],
            "data_max": min_max[1],
        }
    finally:
        conn.close()


@router.get("/kpis")
def kpis(instrumento: str = None, uf: str = None, setor: str = None, data_inicio: str = None, data_fim: str = None):
    """Agregados basicos -- espelha `GET /api/kpis`, trocando `por_agencia` (nao existe
    neste mercado) por `por_instrumento` (debenture/CRI/CRA/etc, o agrupamento
    equivalente mais natural aqui)."""
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        total = cur.execute(
            f"SELECT COUNT(*), SUM(valor_total), AVG(valor_total) FROM operations_primario {where}",
            params,
        ).fetchone()
        por_instrumento = cur.execute(
            f"""
            SELECT instrumento_padronizado, COUNT(*), SUM(valor_total), AVG(valor_total)
            FROM operations_primario {where}
            GROUP BY instrumento_padronizado
            ORDER BY SUM(valor_total) DESC NULLS LAST
            """,
            params,
        ).fetchall()
        return {
            "n_operacoes": total[0] or 0,
            "valor_total_total": total[1] or 0,
            "cheque_medio": total[2] or 0,
            "por_instrumento": [
                {"instrumento": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "cheque_medio": r[3] or 0}
                for r in por_instrumento
            ],
        }
    finally:
        conn.close()


@router.get("/operacoes")
def operacoes(
    instrumento: str = None,
    uf: str = None,
    setor: str = None,
    data_inicio: str = None,
    data_fim: str = None,
    order_by: str = "valor",
    order_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
):
    """Listagem paginada/ordenavel -- espelha `GET /api/operacoes` (BNDES/FINEP)."""
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    coluna_ordenacao = ORDENACAO_COLUNAS.get(order_by, "valor_total")
    direcao = "ASC" if order_dir == "asc" else "DESC"
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT {", ".join(_COLS_OPERACAO_LISTA)}
            FROM operations_primario {where}
            ORDER BY {coluna_ordenacao} {direcao} NULLS LAST
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
        return [dict(zip(_COLS_OPERACAO_LISTA, r)) for r in rows]
    finally:
        conn.close()


@router.get("/busca")
def busca(
    q: str = Query(..., min_length=3),
    instrumento: str = None,
    uf: str = None,
    setor: str = None,
    valor_minimo: float = None,
):
    """Motor de busca sem IA -- espelha `GET /api/busca` (BNDES/FINEP), ver
    src/search_fts_primario.py."""
    try:
        return buscar_texto_primario(
            q, instrumento=instrumento or None, uf=uf or None,
            setor=setor or None, valor_minimo=valor_minimo,
        )
    except Exception as e:  # motor de busca indisponivel nao deve derrubar a rota
        return {"erro": f"motor de busca indisponivel no momento: {e}"}


@router.get("/operacoes/{op_id}")
def operacao_detalhe(op_id: int):
    """Detalhe de uma operacao -- espelha `GET /api/operacoes/{op_id}` (BNDES/FINEP),
    mais simples (sem `montar_detalhe_amigavel`, especifico do schema bndes_raw/
    finep_*_raw -- ver webapp/detalhe.py): devolve as colunas de `operations_primario`
    (ja e o dado tratado/legivel) + os campos crus adicionais de
    `cvm_oferta_distribuicao_raw` que nao viraram coluna propria na tabela unificada
    (ex: nome_ofertante, modalidade_registro) + identificacao da empresa via
    `cnpj_cnae` quando o CNPJ ja foi resolvido (mesmo padrao do detalhe BNDES/FINEP)."""
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM operations_primario WHERE id = ?", (op_id,)
        ).fetchone()
        if not row:
            return {"erro": "operacao nao encontrada"}
        cols = [d[0] for d in cur.description]
        operacao = dict(zip(cols, row))
        # search_document/search_vector sao campos INTERNOS do motor de busca (ver
        # src/search_fts_primario.py) -- nunca uteis no detalhe de uma operacao pro
        # frontend, tirados da resposta por limpeza (mesmo espirito de operacao_detalhe
        # no motor BNDES/FINEP, que tambem nao expoe search_vector cru).
        operacao.pop("search_document", None)
        operacao.pop("search_vector", None)

        raw_extra = {}
        raw_row = cur.execute(
            "SELECT nome_ofertante, cnpj_ofertante, nome_vendedor, tipo_societario_emissor, "
            "tipo_fundo_investimento, modalidade_registro, modalidade_dispensa_registro, "
            "tipo_componente_oferta_mista, data_abertura_processo, data_protocolo, "
            "data_dispensa_oferta, quantidade_sem_lote_suplementar, quantidade_no_lote_suplementar, "
            "ultimo_comunicado, data_comunicado "
            "FROM cvm_oferta_distribuicao_raw WHERE id = ?",
            (operacao["raw_id"],),
        ).fetchone()
        if raw_row:
            raw_cols = [d[0] for d in cur.description]
            raw_extra = dict(zip(raw_cols, raw_row))

        empresa = None
        if operacao.get("cnpj_emissor"):
            empresa_row = cur.execute(
                "SELECT razao_social_oficial, natureza_juridica, porte_empresa, capital_social, "
                "cnae_codigo, cnae_descricao FROM cnpj_cnae WHERE cnpj = ?",
                (operacao["cnpj_emissor"],),
            ).fetchone()
            if empresa_row and any(v is not None for v in empresa_row):
                empresa = dict(zip(
                    ["razao_social_oficial", "natureza_juridica", "porte_empresa", "capital_social",
                     "cnae_codigo", "cnae_descricao"],
                    empresa_row,
                ))

        return {"operacao": operacao, "raw_extra": raw_extra, "empresa": empresa}
    finally:
        conn.close()
