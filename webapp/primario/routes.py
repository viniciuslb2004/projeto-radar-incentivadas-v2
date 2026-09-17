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
import datetime

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


def _filters_clause_primario_exato(instrumento=None, uf=None, setor=None, subsetor=None, data_inicio=None, data_fim=None):
    """Variante de `_filters_clause_primario` com `setor`/`subsetor` como filtros
    EXATOS e SEPARADOS (nunca OR combinados) -- usada pelas rotas de
    tendencias/subsetores/segmentos (tanto o ranking de variacao quanto a versao
    "simples"), onde `setor` e o PAI de quem se quer o detalhe (ex: ranking de
    subsetores DENTRO de um setor escolhido num select proprio -- ver
    `tendencias.js::subsetor-setor-select`, populado com valores EXATOS do
    ranking, nunca o dropdown compartilhado que combina setor+subsetor numa so
    lista). Mesmo papel que setor/subsetor tem em
    `webapp/main.py::_filters_clause`/`_ranking_variacao` (BNDES/FINEP) --
    distinto do uso combinado em `_filters_clause_primario` acima, que serve o
    filtro UNICO do dropdown compartilhado (Consolidado/Tendencias/Busca)."""
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
        clauses.append("setor_emissor = ?")
        params.append(setor)
    if subsetor and subsetor != "Todos":
        clauses.append("subsetor_emissor = ?")
        params.append(subsetor)
    if data_inicio:
        clauses.append("data_referencia >= ?")
        params.append(data_inicio)
    if data_fim:
        clauses.append("data_referencia < ?")
        params.append(data_fim)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# Mesma janela padrao (365 dias) usada por webapp/main.py::JANELA_TENDENCIA_MAX_DIAS
# -- so vale quando NENHum filtro de data e passado (ver _periodo_anterior_primario).
JANELA_TENDENCIA_MAX_DIAS_PRIMARIO = 365


def _periodo_anterior_primario(data_inicio: str, data_fim: str, conn):
    """Espelha `webapp/main.py::_periodo_anterior`, trocando `operations`/
    `data_contratacao` por `operations_primario`/`data_referencia` -- mesma
    semantica: periodo anterior SEMPRE do MESMO TAMANHO EXATO do periodo atual,
    nunca um teto fixo de 365 dias quando o usuario escolheu datas explicitas."""
    cur = conn.cursor()
    if data_inicio and data_fim and data_inicio > data_fim:
        data_inicio, data_fim = data_fim, data_inicio
    if not data_inicio or not data_fim:
        max_data = cur.execute("SELECT MAX(data_referencia) FROM operations_primario").fetchone()[0]
        if not max_data:
            hoje = datetime.date.today()
        else:
            hoje = datetime.date.fromisoformat(max_data[:10]) + datetime.timedelta(days=1)
        data_fim = hoje.isoformat()
        data_inicio = (hoje - datetime.timedelta(days=JANELA_TENDENCIA_MAX_DIAS_PRIMARIO)).isoformat()

    inicio_selecionado = datetime.date.fromisoformat(data_inicio[:10])
    fim = datetime.date.fromisoformat(data_fim[:10])
    delta = fim - inicio_selecionado
    if delta.days <= 0:
        delta = datetime.timedelta(days=JANELA_TENDENCIA_MAX_DIAS_PRIMARIO)

    anterior_fim = inicio_selecionado
    anterior_inicio = inicio_selecionado - delta
    return data_inicio, data_fim, anterior_inicio.isoformat(), anterior_fim.isoformat()


def _ranking_variacao_primario(conn, group_col: str, instrumento, uf, setor_pai, data_inicio, data_fim, subsetor_pai=None):
    """Espelha `webapp/main.py::_ranking_variacao`, sem o conceito de `agencia`
    (nao existe neste mercado -- ver CLAUDE.md). Ranking generico de variacao de
    participacao entre periodo atual e anterior, respeitando filtros."""
    data_inicio, data_fim, ant_inicio, ant_fim = _periodo_anterior_primario(data_inicio, data_fim, conn)
    where_base, params_base = _filters_clause_primario_exato(instrumento, uf, setor_pai, subsetor_pai, None, None)
    cur = conn.cursor()

    def valor_por_grupo(d_ini, d_fim):
        where = where_base + (" AND " if where_base else "WHERE ") + "data_referencia >= ? AND data_referencia < ?"
        rows = cur.execute(
            f"SELECT COALESCE({group_col}, 'Nao classificado'), SUM(valor_total), COUNT(*) "
            f"FROM operations_primario {where} GROUP BY {group_col}",
            params_base + [d_ini, d_fim],
        ).fetchall()
        total = sum(r[1] or 0 for r in rows)
        return {r[0]: {"valor": r[1] or 0, "n": r[2], "part": (r[1] or 0) / total if total else 0} for r in rows}, total

    atual, total_atual = valor_por_grupo(data_inicio, data_fim)
    anterior, total_anterior = valor_por_grupo(ant_inicio, ant_fim)

    # Mesma guarda documentada em webapp/main.py::_ranking_variacao -- so compara
    # de verdade se o periodo anterior INTEIRO estiver dentro da cobertura real
    # da base (min(data_referencia)), senao a variacao fica None (nunca uma
    # comparacao fabricada contra "nada"/cobertura incompleta).
    min_data_base = cur.execute("SELECT MIN(data_referencia) FROM operations_primario").fetchone()[0]
    comparavel = total_anterior > 0 and (not min_data_base or ant_inicio >= min_data_base)

    grupos = set(atual) | set(anterior)
    out = []
    for g in grupos:
        a = atual.get(g, {"valor": 0, "n": 0, "part": 0})
        p = anterior.get(g, {"valor": 0, "n": 0, "part": 0})
        out.append({
            "grupo": g,
            "participacao_atual_pct": a["part"] * 100,
            "participacao_anterior_pct": (p["part"] * 100) if comparavel else None,
            "variacao_pp": ((a["part"] - p["part"]) * 100) if comparavel else None,
            "valor_atual": a["valor"],
            "n_operacoes_atual": a["n"],
        })
    out.sort(key=lambda r: (r["variacao_pp"] if comparavel else r["valor_atual"]), reverse=True)
    return {
        "data_inicio": data_inicio, "data_fim": data_fim,
        "data_inicio_anterior": ant_inicio, "data_fim_anterior": ant_fim,
        "comparavel": comparavel,
        "grupos": out,
    }


GRANULARIDADES_SERIE_PRIMARIO = {
    # Mesma logica de webapp/main.py::GRANULARIDADES_SERIE, trocando
    # data_contratacao por data_referencia (ja normalizada AAAA-MM-DD, ver
    # unify_primario.py::_data_referencia).
    "mensal": "CAST(SUBSTRING(data_referencia FROM 6 FOR 2) AS INTEGER)",
    "trimestral": "trimestre",
    "semestral": "CASE WHEN trimestre <= 2 THEN 1 ELSE 2 END",
    "anual": "1",
}


@router.get("/status")
def status():
    """Espelha `GET /api/status` (BNDES/FINEP, ver webapp/main.py::status()).
    `setores_pendentes` aqui e a contagem de `setor_emissor IS NULL` -- nao existe
    coluna `setor_origem` em `operations_primario` (ver CLAUDE.md, secao Pipeline
    CVM: "o estado pendente e so setor_emissor IS NULL"). `busca_ia_ativa` e
    SEMPRE False -- nao existe motor de embeddings pro Radar de Credito Primario
    (so FTS sem IA, ver src/search_fts_primario.py), diferente do MOTOR_BUSCA_IA
    opcional do motor BNDES/FINEP."""
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        n_ops = cur.execute("SELECT COUNT(*) FROM operations_primario").fetchone()[0]
        n_pendente = cur.execute("SELECT COUNT(*) FROM operations_primario WHERE setor_emissor IS NULL").fetchone()[0]
        min_max = cur.execute("SELECT MIN(data_referencia), MAX(data_referencia) FROM operations_primario").fetchone()
        last = cur.execute(
            "SELECT started_at, finished_at, status FROM refresh_primario_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "n_operacoes": n_ops,
            "setores_pendentes": n_pendente,
            "data_min": min_max[0],
            "data_max": min_max[1],
            "ultimo_refresh": {"started_at": last[0], "finished_at": last[1], "status": last[2]} if last else None,
            "hospedado": True,
            "busca_ia_ativa": False,
        }
    finally:
        conn.close()


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
    equivalente mais natural aqui) e `valor_desembolsado_total` (nao existe
    "desembolso" parcelado numa oferta de mercado de capitais, ver CLAUDE.md) por
    `n_emissores_distintos` -- mais informativo aqui.

    BUG REAL encontrado e corrigido nesta reconciliacao (2026-09-16), testado ao
    vivo com o frontend de verdade (Consolidado, modo Primario): esta rota ja
    existia de uma sessao anterior, mas devolvia `valor_total_total` (nunca lido
    por nenhum consumidor) em vez de `valor_contratado_total` (a chave que
    `consolidado.js::loadKPIs` de fato le, com fallback pra `valor_total`) e
    nunca calculava `n_emissores_distintos` -- os cards "Volume total emitido" e
    "Emissores distintos" apareciam vazios ("-") na tela. Corrigido para bater
    com o contrato documentado no CLAUDE.md (secao Frontend, tabela de
    endpoints) -- `valor_total` mantido tambem, por completude/consistencia com
    `por_instrumento`, mas `valor_contratado_total` e a chave que o frontend
    realmente le primeiro."""
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        total = cur.execute(
            f"""
            SELECT COUNT(*), SUM(valor_total), AVG(valor_total),
                   COUNT(DISTINCT cnpj_emissor)
            FROM operations_primario {where}
            """,
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
            "valor_contratado_total": total[1] or 0,
            "valor_total": total[1] or 0,
            "n_emissores_distintos": total[3] or 0,
            "cheque_medio": total[2] or 0,
            "por_instrumento": [
                {"instrumento": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "cheque_medio": r[3] or 0}
                for r in por_instrumento
            ],
        }
    finally:
        conn.close()


@router.get("/serie_temporal")
def serie_temporal(
    instrumento: str = None, uf: str = None, setor: str = None, data_inicio: str = None,
    data_fim: str = None, granularidade: str = "trimestral",
):
    """Espelha `GET /api/serie_temporal`, trocando o agrupamento por `agencia`
    (nao existe neste mercado) por `instrumento_padronizado` -- mesma dualidade
    do original: `instrumento` funciona tanto como FILTRO estruturado quanto
    como coluna de agrupamento (selecionar um instrumento especifico no filtro
    compartilhado mostra so a linha daquele instrumento na serie, mesmo
    comportamento de filtrar `agencia=BNDES` no motor original)."""
    if granularidade not in GRANULARIDADES_SERIE_PRIMARIO:
        granularidade = "trimestral"
    periodo_expr = GRANULARIDADES_SERIE_PRIMARIO[granularidade]
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT ano, {periodo_expr} AS periodo, instrumento_padronizado, COUNT(*), SUM(valor_total)
            FROM operations_primario {where}
            {"AND" if where else "WHERE"} ano IS NOT NULL
            GROUP BY ano, periodo, instrumento_padronizado
            ORDER BY ano, periodo
            """,
            params,
        ).fetchall()
        return [
            {"ano": r[0], "periodo": r[1], "instrumento": r[2], "n_operacoes": r[3], "valor_total": r[4] or 0}
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/instrumentos")
def instrumentos(uf: str = None, setor: str = None, data_inicio: str = None, data_fim: str = None):
    """Mesmo formato de `GET /api/setores` (BNDES/FINEP), agrupando por
    `instrumento_padronizado` em vez de `setor_bndes` -- a dimensao mais
    distintiva de renda fixa neste mercado (ver CLAUDE.md, secao Frontend,
    tabela de labels). Nao aceita `instrumento` como filtro (e a propria
    dimensao agrupada), mesmo padrao de `/api/setores` nao aceitar `setor`."""
    where, params = _filters_clause_primario(None, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(instrumento_padronizado, 'Nao classificado'), COUNT(*), SUM(valor_total), AVG(valor_total)
            FROM operations_primario {where}
            GROUP BY instrumento_padronizado
            ORDER BY SUM(valor_total) DESC
            """,
            params,
        ).fetchall()
        return [
            {"instrumento": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "cheque_medio": r[3] or 0}
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/uf")
def uf_breakdown(instrumento: str = None, setor: str = None, data_inicio: str = None, data_fim: str = None):
    """Espelha `GET /api/uf`, via `uf_emissor` -- SEM o tratamento especial de
    `IE` que o motor BNDES/FINEP tem (ver CLAUDE.md, secao "Frontend:
    roteamento e abas"): `IE` e uma categoria REAL da planilha do BNDES
    (operacoes de abrangencia nacional/interestadual, ex: Petrobras) que nao
    tem equivalente no dataset da CVM -- inventar essa categoria aqui seria
    alucinar um conceito que a fonte nao tem. `uf_emissor` so tem 2 estados
    possiveis: uma UF de verdade (resolvida via CNPJ->cnpj_cnae) ou NULL
    (emissor ainda pendente/sem CNPJ na oferta, ver CLAUDE.md secao Pipeline
    CVM) -- o segundo caso usa o MESMO sentinela `NI` que o motor original usa
    pra UF nao informada (`COALESCE(uf, 'NI')`), unico rotulo fora dos 27
    estados que este endpoint pode devolver."""
    where, params = _filters_clause_primario(instrumento, None, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(uf_emissor, 'NI'), COUNT(*), SUM(valor_total)
            FROM operations_primario {where}
            GROUP BY uf_emissor
            ORDER BY SUM(valor_total) DESC
            """,
            params,
        ).fetchall()
        return [{"uf": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0} for r in rows]
    finally:
        conn.close()


@router.get("/porte")
def porte_breakdown(setor: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None):
    """Espelha `GET /api/porte`, via `porte_emissor` (mesmo cache `cnpj_cnae`
    usado pra enriquecer a FINEP) -- mesma assinatura do original (que tambem
    nao aceita filtro `instrumento`, so agencia/setor/uf/data). SEM
    `PORTE_NORMALIZADO_SQL` (ver src/search_fts.py): aquela normalizacao existe
    pra unificar o vocabulario HETEROGENEO de `porte_cliente` (BNDES nativo +
    FINEP enriquecido via 2 fontes diferentes, MICRO/PEQUENA/GRANDE/MÉDIA
    misturado com "Micro Empresa"/"Empresa de Pequeno Porte"). Aqui
    `porte_emissor` vem de UMA SO fonte (cnpj_cnae, sempre via BrasilAPI/RFB,
    ver src/enrich_cnae.py::PORTE_EMPRESA_RFB) com um vocabulario proprio e ja
    homogeneo (`Micro Empresa`/`Empresa de Pequeno Porte`/`Demais`/`Não
    informado pela fonte`/NULL) -- aplicar aquele CASE aqui so devolveria
    'Não informado' pra tudo (nenhum desses rotulos bate as chaves daquele
    CASE), entao agrupar direto pelo valor cru (com COALESCE so pro NULL) e o
    correto, sem inventar uma categoria 'GRANDE'/'MÉDIA' que a RFB nao
    distingue neste layout simplificado."""
    where, params = _filters_clause_primario(None, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(porte_emissor, 'Não informado'), COUNT(*), SUM(valor_total)
            FROM operations_primario {where}
            GROUP BY porte_emissor
            ORDER BY SUM(valor_total) DESC
            """,
            params,
        ).fetchall()
        return [{"porte": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0} for r in rows]
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


@router.get("/operacoes/{op_id}/grupo-economico")
def operacao_grupo_economico(op_id: int):
    """Espelha `GET /api/operacoes/{op_id}/grupo-economico` (BNDES/FINEP),
    agrupando por RAIZ de `cnpj_emissor` (8 primeiros digitos -- identifica a
    EMPRESA, matriz+filiais compartilham a raiz) em vez de `cnpj`. Chaves de
    resposta (`emissor`/`instrumento`/`valor_emissao`) escolhidas para bater
    direto no fallback ja escrito em `common.js::openOperacaoDetalhe`
    (`o.cliente ?? o.emissor`, `o.agencia ?? o.instrumento`,
    `o.valor_contratado ?? o.valor_emissao`) -- nunca precisou mudar o
    frontend, so nomear os campos do jeito que ele ja espera."""
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT left(regexp_replace(cnpj_emissor, '\\D', '', 'g'), 8) FROM operations_primario WHERE id = ?",
            (op_id,),
        ).fetchone()
        if not row or not row[0] or len(row[0]) < 8:
            return {"resultados": []}
        raiz = row[0]
        rows = cur.execute(
            "SELECT id, nome_emissor, instrumento_padronizado, data_referencia, valor_total FROM operations_primario "
            "WHERE left(regexp_replace(cnpj_emissor, '\\D', '', 'g'), 8) = ? AND id != ? "
            "ORDER BY data_referencia DESC LIMIT 20",
            (raiz, op_id),
        ).fetchall()
        cols = ["id", "emissor", "instrumento", "data_referencia", "valor_emissao"]
        return {"resultados": [dict(zip(cols, r)) for r in rows]}
    finally:
        conn.close()


@router.get("/tendencias/setores")
def tendencias_setores(instrumento: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de `setor_emissor` por variacao de participacao entre o periodo
    selecionado e o periodo anterior equivalente -- espelha
    `GET /api/tendencias/setores` (BNDES/FINEP)."""
    conn = get_connection(pooled=True)
    try:
        r = _ranking_variacao_primario(conn, "setor_emissor", instrumento, uf, None, data_inicio, data_fim)
        return {
            "periodo_atual": [r["data_inicio"], r["data_fim"]],
            "periodo_anterior": [r["data_inicio_anterior"], r["data_fim_anterior"]],
            "comparavel": r["comparavel"],
            "setores": [{**g, "setor": g["grupo"]} for g in r["grupos"]],
        }
    finally:
        conn.close()


@router.get("/tendencias/subsetores")
def tendencias_subsetores(setor: str = Query(...), instrumento: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de `subsetor_emissor` (dentro de um `setor_emissor`) por variacao
    de participacao -- espelha `GET /api/tendencias/subsetores`."""
    conn = get_connection(pooled=True)
    try:
        r = _ranking_variacao_primario(conn, "subsetor_emissor", instrumento, uf, setor, data_inicio, data_fim)
        return {
            "setor": setor,
            "periodo_atual": [r["data_inicio"], r["data_fim"]],
            "periodo_anterior": [r["data_inicio_anterior"], r["data_fim_anterior"]],
            "comparavel": r["comparavel"],
            "subsetores": [{**g, "subsetor": g["grupo"]} for g in r["grupos"]],
        }
    finally:
        conn.close()


@router.get("/tendencias/segmentos")
def tendencias_segmentos(setor: str = Query(...), subsetor: str = None, instrumento: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de `segmento_emissor` (CNAE, granularidade fina) dentro de um
    setor, por variacao de participacao -- espelha
    `GET /api/tendencias/segmentos`."""
    conn = get_connection(pooled=True)
    try:
        r = _ranking_variacao_primario(conn, "segmento_emissor", instrumento, uf, setor, data_inicio, data_fim, subsetor_pai=subsetor)
        return {
            "setor": setor,
            "subsetor": subsetor,
            "periodo_atual": [r["data_inicio"], r["data_fim"]],
            "periodo_anterior": [r["data_inicio_anterior"], r["data_fim_anterior"]],
            "comparavel": r["comparavel"],
            "segmentos": [{**g, "segmento": g["grupo"]} for g in r["grupos"]],
        }
    finally:
        conn.close()


@router.get("/tendencias/indexadores")
def tendencias_indexadores(instrumento: str = None, uf: str = None, setor: str = None, data_inicio: str = None, data_fim: str = None):
    """ENDPOINT NOVO (nao espelha nome nenhum do motor BNDES/FINEP) -- pedido
    pelo frontend (`tendencias.js::loadProdutos`) como substituto de
    "Destinação de recursos" no modo Primario: distribuicao por
    `indexador_padronizado` (CDI/IPCA+/SELIC/Prefixado/Outro/Nao informado),
    mesmo shape geral `[{<dimensao>, valor_total}]` de `GET
    /api/tendencias/produtos` (sem ranking de variacao -- so a composicao
    ATUAL, ver CLAUDE.md)."""
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(indexador_padronizado, 'Não informado'), COUNT(*), SUM(valor_total)
            FROM operations_primario {where}
            GROUP BY COALESCE(indexador_padronizado, 'Não informado')
            ORDER BY SUM(valor_total) DESC
            LIMIT 20
            """,
            params,
        ).fetchall()
        return [{"indexador": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0} for r in rows]
    finally:
        conn.close()


@router.get("/subsetores")
def subsetores(setor: str = None, instrumento: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None):
    """Espelha `GET /api/subsetores` -- usado por `tendencias.js::loadSubsetores`
    em conjunto com `/tendencias/subsetores` (mesmo `setor` exato de pai, ver
    `_filters_clause_primario_exato`, nunca o OR combinado do dropdown
    compartilhado -- o select que alimenta este `setor` e um select PROPRIO,
    populado com valores exatos do ranking, ver `subsetor-setor-select`)."""
    where, params = _filters_clause_primario_exato(instrumento, uf, setor, None, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(subsetor_emissor, 'Nao classificado'), COUNT(*), SUM(valor_total), AVG(valor_total)
            FROM operations_primario {where}
            GROUP BY subsetor_emissor
            ORDER BY SUM(valor_total) DESC
            """,
            params,
        ).fetchall()
        return [
            {"subsetor": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "cheque_medio": r[3] or 0}
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/segmentos")
def segmentos(setor: str = None, subsetor: str = None, instrumento: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None, limit: int = 20):
    """Espelha `GET /api/segmentos` -- usado por `tendencias.js::loadSegmentos`
    em conjunto com `/tendencias/segmentos` (mesma nota de `setor`/`subsetor`
    exatos de `subsetores()` acima)."""
    where, params = _filters_clause_primario_exato(instrumento, uf, setor, subsetor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(segmento_emissor, 'Nao classificado'), COUNT(*), SUM(valor_total), AVG(valor_total)
            FROM operations_primario {where}
            GROUP BY segmento_emissor
            ORDER BY SUM(valor_total) DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        return [
            {"segmento": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "cheque_medio": r[3] or 0}
            for r in rows
        ]
    finally:
        conn.close()


# Taxa_tipo excluido deste grafico -- 'percentual_indexador' e MULTIPLICATIVO
# (ex: "108% do CDI"), unidade DIFERENTE de 'spread'/'taxa_fixa' (pontos
# percentuais a.a., aditivos) -- misturar os dois no mesmo eixo seria
# enganoso (ver CLAUDE.md, secao Pipeline CVM, taxa_tipo). So contado a parte
# no aviso de cobertura do frontend (chart-taxas-aviso, ver consolidado.js).
_TAXA_TIPOS_COMPARAVEIS = ("spread", "taxa_fixa")


@router.get("/graficos/taxas")
def graficos_taxas(instrumento: str = None, uf: str = None, setor: str = None, data_inicio: str = None, data_fim: str = None):
    """ENDPOINT NOVO -- pedido central desta reconciliacao (ver CLAUDE.md, secao
    Frontend, "Dashboards novos"). Distribuicao de `taxa_valor` (mediana) por
    `indexador_padronizado` + `taxa_tipo`, SEM as linhas `percentual_indexador`
    (ver `_TAXA_TIPOS_COMPARAVEIS` acima). `taxa_mediana` via
    `percentile_cont(0.5) WITHIN GROUP` (mediana real, nao media -- mais
    robusta a outliers num campo de melhor-esforco como `taxa_valor`, ver
    CLAUDE.md). `cobertura_pct` sempre calculada a partir de contagens reais
    (nunca um numero fixo), pra continuar correta conforme a base
    crescer/for reenriquecida."""
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        n_total = cur.execute(f"SELECT COUNT(*) FROM operations_primario {where}", params).fetchone()[0] or 0
        where_taxa = where + (" AND " if where else "WHERE ") + (
            f"taxa_valor IS NOT NULL AND taxa_tipo IN ({', '.join(['?'] * len(_TAXA_TIPOS_COMPARAVEIS))})"
        )
        params_taxa = params + list(_TAXA_TIPOS_COMPARAVEIS)
        n_com_taxa = cur.execute(f"SELECT COUNT(*) FROM operations_primario {where_taxa}", params_taxa).fetchone()[0] or 0
        rows = cur.execute(
            f"""
            SELECT indexador_padronizado, taxa_tipo, COUNT(*),
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY taxa_valor)
            FROM operations_primario {where_taxa}
            GROUP BY indexador_padronizado, taxa_tipo
            ORDER BY COUNT(*) DESC
            """,
            params_taxa,
        ).fetchall()
        return {
            "n_total": n_total,
            "n_com_taxa": n_com_taxa,
            "cobertura_pct": (n_com_taxa / n_total * 100) if n_total else 0,
            "linhas": [
                {"indexador": r[0], "taxa_tipo": r[1], "n": r[2], "taxa_mediana": r[3]}
                for r in rows
            ],
        }
    finally:
        conn.close()


@router.get("/serie_temporal_incentivada")
def serie_temporal_incentivada(
    instrumento: str = None, uf: str = None, setor: str = None, data_inicio: str = None,
    data_fim: str = None, granularidade: str = "trimestral",
):
    """ENDPOINT NOVO -- redesenho do Consolidado/Tendencias pra emissao primaria
    (ver CLAUDE.md, secao Frontend, tabela de decisoes card-a-card). Espelha
    `/serie_temporal`, trocando o agrupamento por `instrumento_padronizado`
    por `incentivada` (Lei 12.431, mapeado pra 'Sim'/'Não'/'Não informado') --
    complementa o donut estatico "Estrutura da oferta" (`/estrutura_mercado`,
    so a composicao ATUAL) com a dimensao de TEMPO: como a participação de
    emissões incentivadas evoluiu.

    **Por que este endpoint existe e não um equivalente para `indexador_padronizado`**:
    a primeira versão desta reconciliação tentou uma série temporal por
    indexador, mas os dados reais mostraram um problema de fundo, não um
    detalhe de implementação -- `indexador_padronizado` só vem do arquivo
    principal da CVM (`cvm_oferta_distribuicao_raw`), que praticamente para de
    contribuir linhas a partir de 2023 (a atividade recente é quase toda via
    `cvm_oferta_resolucao_160_raw`, que NUNCA tem indexador -- ver CLAUDE.md,
    seção "Segunda fonte CVM"). Um gráfico de evolução por indexador cairia a
    zero exatamente nos anos mais recentes (2023-2026), o que pareceria "o
    mercado indexado sumiu" quando na verdade é só um artefato de qual
    arquivo CVM cobre qual período -- enganoso demais pra publicar. `incentivada`
    não tem esse problema: é populada a partir de AMBOS os arquivos CVM
    (`oferta_incentivo_fiscal`/`titulo_incentivado`, ver `unify_primario.py`),
    com cobertura real e contínua 2010-2026 (confirmado ao vivo, 2026-09-17)."""
    if granularidade not in GRANULARIDADES_SERIE_PRIMARIO:
        granularidade = "trimestral"
    periodo_expr = GRANULARIDADES_SERIE_PRIMARIO[granularidade]
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT ano, {periodo_expr} AS periodo,
                   CASE incentivada WHEN TRUE THEN 'Sim' WHEN FALSE THEN 'Não' ELSE 'Não informado' END,
                   COUNT(*), SUM(valor_total)
            FROM operations_primario {where}
            {"AND" if where else "WHERE"} ano IS NOT NULL
            GROUP BY ano, periodo, CASE incentivada WHEN TRUE THEN 'Sim' WHEN FALSE THEN 'Não' ELSE 'Não informado' END
            ORDER BY ano, periodo
            """,
            params,
        ).fetchall()
        return [
            {"ano": r[0], "periodo": r[1], "incentivada": r[2], "n_operacoes": r[3], "valor_total": r[4] or 0}
            for r in rows
        ]
    finally:
        conn.close()


# Mesmo padrao de "nunca filtrar/esconder silenciosamente" ja usado em
# status_requerimento (ver CLAUDE.md, secao Pipeline CVM) -- COALESCE NULL
# como rotulo explicito em vez de excluir a linha da contagem.
_LIMIT_RANKING_ESTRUTURA = 10


def _ranking_texto_com_cobertura(cur, where, params, coluna, limit=_LIMIT_RANKING_ESTRUTURA):
    """Ranking generico top-N de uma coluna de texto esparsa (agente_fiduciario/
    custodiante -- so preenchidas para linhas vindas de cvm_oferta_resolucao_160_raw,
    ver CLAUDE.md) + cobertura real (nunca um numero fixo, mesmo padrao de
    /graficos/taxas e /graficos/prazos)."""
    n_total = cur.execute(f"SELECT COUNT(*) FROM operations_primario {where}", params).fetchone()[0] or 0
    where_col = where + (" AND " if where else "WHERE ") + f"{coluna} IS NOT NULL"
    n_com_dado = cur.execute(f"SELECT COUNT(*) FROM operations_primario {where_col}", params).fetchone()[0] or 0
    rows = cur.execute(
        f"""
        SELECT {coluna}, COUNT(*), SUM(valor_total)
        FROM operations_primario {where_col}
        GROUP BY {coluna}
        ORDER BY SUM(valor_total) DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return {
        "n_total": n_total,
        "n_com_dado": n_com_dado,
        "cobertura_pct": (n_com_dado / n_total * 100) if n_total else 0,
        "linhas": [{"nome": r[0], "n": r[1], "valor_total": r[2] or 0} for r in rows],
    }


@router.get("/estrutura_mercado")
def estrutura_mercado(instrumento: str = None, uf: str = None, setor: str = None, data_inicio: str = None, data_fim: str = None):
    """ENDPOINT NOVO -- redesenho do Consolidado/Tendencias (ver CLAUDE.md,
    secao Frontend). Reune 3 dimensoes de ESTRUTURA da oferta que nunca
    tinham nenhum card, deliberadamente num UNICO endpoint (mesmo espirito de
    `/kpis` bundlar varias agregacoes pequenas): `incentivada` (Lei 12.431) e
    `regime_fiduciario` (booleanos, alimentam o card "Estrutura da oferta" do
    Consolidado) + `agentes_fiduciarios`/`custodiantes` (ranking top-10,
    alimentam o card "Principais agentes fiduciários e custodiantes" de
    Tendencias) + `tipo_lastro` (Pulverizado/Concentrado, mesmo card de
    Consolidado). `incentivada`/`regime_fiduciario` sao S/N na fonte CVM mas
    podem ser NULL (campo vazio) -- SEMPRE as 3 categorias (sim/nao/
    nao_informado) na resposta, nunca só 2, pra nunca esconder uma fatia
    real dos dados atras de um booleano que assume sempre preenchido."""
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        n_total = cur.execute(f"SELECT COUNT(*) FROM operations_primario {where}", params).fetchone()[0] or 0

        def bool_breakdown(coluna):
            rows = cur.execute(
                f"SELECT {coluna}, COUNT(*), SUM(valor_total) FROM operations_primario {where} GROUP BY {coluna}",
                params,
            ).fetchall()
            out = {
                "sim": {"n": 0, "valor_total": 0},
                "nao": {"n": 0, "valor_total": 0},
                "nao_informado": {"n": 0, "valor_total": 0},
            }
            for valor, n, soma in rows:
                chave = "sim" if valor is True else ("nao" if valor is False else "nao_informado")
                out[chave] = {"n": n, "valor_total": soma or 0}
            return out

        tipo_lastro_rows = cur.execute(
            f"""
            SELECT COALESCE(tipo_lastro, 'Não informado'), COUNT(*), SUM(valor_total)
            FROM operations_primario {where}
            GROUP BY COALESCE(tipo_lastro, 'Não informado')
            ORDER BY SUM(valor_total) DESC
            """,
            params,
        ).fetchall()

        return {
            "n_total": n_total,
            "incentivada": bool_breakdown("incentivada"),
            "regime_fiduciario": bool_breakdown("regime_fiduciario"),
            "tipo_lastro": [{"tipo_lastro": r[0], "n": r[1], "valor_total": r[2] or 0} for r in tipo_lastro_rows],
            "agentes_fiduciarios": _ranking_texto_com_cobertura(cur, where, params, "agente_fiduciario"),
            "custodiantes": _ranking_texto_com_cobertura(cur, where, params, "custodiante"),
        }
    finally:
        conn.close()


@router.get("/graficos/prazos")
def graficos_prazos(instrumento: str = None, uf: str = None, setor: str = None, data_inicio: str = None, data_fim: str = None):
    """ENDPOINT NOVO -- ver CLAUDE.md, secao Frontend, "Dashboards novos".
    Distribuicao de `prazo_meses` (mediana) por `instrumento_padronizado`.
    Diferente de `taxa_valor` (melhor esforco), `prazo_meses` e dado EXATO
    quando existe (data_vencimento - data_emissao) -- a cobertura parcial vem
    so de faltar uma das duas datas na fonte (CVM), ja filtrado/documentado em
    `unify_primario.py::_prazo_dias_e_meses` (nunca precisa refiltrar aqui,
    `prazo_meses IS NULL` ja e o estado correto pros casos sem dado/invertidos)."""
    where, params = _filters_clause_primario(instrumento, uf, setor, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        n_total = cur.execute(f"SELECT COUNT(*) FROM operations_primario {where}", params).fetchone()[0] or 0
        where_prazo = where + (" AND " if where else "WHERE ") + "prazo_meses IS NOT NULL"
        n_com_prazo = cur.execute(f"SELECT COUNT(*) FROM operations_primario {where_prazo}", params).fetchone()[0] or 0
        rows = cur.execute(
            f"""
            SELECT instrumento_padronizado, COUNT(*),
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY prazo_meses)
            FROM operations_primario {where_prazo}
            GROUP BY instrumento_padronizado
            ORDER BY COUNT(*) DESC
            """,
            params,
        ).fetchall()
        return {
            "n_total": n_total,
            "n_com_prazo": n_com_prazo,
            "cobertura_pct": (n_com_prazo / n_total * 100) if n_total else 0,
            "linhas": [
                {"instrumento": r[0], "n": r[1], "prazo_mediano_meses": r[2]}
                for r in rows
            ],
        }
    finally:
        conn.close()
