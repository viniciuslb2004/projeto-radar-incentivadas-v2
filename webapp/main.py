"""API FastAPI do Radar de Credito Incentivado (BNDES + FINEP)."""
import datetime
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from db import MODO_HOSPEDADO, get_connection
from webapp.detalhe import montar_detalhe_amigavel

# ============ Acesso (so ativo no deploy hospedado) ============
# O app local (desktop) roda sem senha nenhuma, como sempre -- isso so entra em
# jogo quando SITE_PASSWORD estiver configurada (deploy compartilhado, ver
# DEPLOY.md). Sem custom login/cookie: o navegador mostra o dialogo nativo de
# usuario/senha (HTTP Basic) na primeira chamada à API e lembra pelo resto da sessao.
SITE_USER = os.environ.get("SITE_USER", "radar")
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "")
_basic_auth = HTTPBasic(auto_error=False)


def _verificar_acesso(credentials: HTTPBasicCredentials = Depends(_basic_auth)):
    if not SITE_PASSWORD:
        return
    ok = credentials is not None and secrets.compare_digest(
        credentials.username, SITE_USER
    ) and secrets.compare_digest(credentials.password, SITE_PASSWORD)
    if not ok:
        raise HTTPException(status_code=401, detail="Acesso restrito", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="Radar de Credito Incentivado", dependencies=[Depends(_verificar_acesso)])

# ============ CORS (so importa quando frontend e backend estao em dominios
# diferentes -- ex: frontend na Vercel, backend no Render) ============
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins.split(",") if o.strip()] or ["http://localhost:8001", "http://127.0.0.1:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.on_event("startup")
def _warmup_busca():
    """Carrega o modelo de embeddings no startup do servidor, nao na primeira busca do usuario
    (sem isso, a primeira busca de cada reinicio parecia travada por ~20-30s)."""
    try:
        from search import warmup

        warmup()
        print("Motor de busca pronto (modelo de embeddings carregado).")
    except Exception as e:
        print(f"Aviso: motor de busca nao pode ser pre-carregado ({e}).")


def _filters_clause(agencia=None, setor=None, uf=None, data_inicio=None, data_fim=None, instrumento=None, subsetor=None, segmento=None):
    clauses = []
    params = []
    if agencia and agencia != "Todas":
        clauses.append("agencia = ?")
        params.append(agencia)
    if setor and setor != "Todos":
        clauses.append("setor_bndes = ?")
        params.append(setor)
    if subsetor and subsetor != "Todos":
        clauses.append("subsetor_bndes = ?")
        params.append(subsetor)
    if segmento and segmento != "Todos":
        clauses.append("segmento = ?")
        params.append(segmento)
    if uf and uf != "Todas":
        clauses.append("uf = ?")
        params.append(uf)
    if instrumento and instrumento != "Todos":
        clauses.append("instrumento = ?")
        params.append(instrumento)
    if data_inicio:
        clauses.append("data_contratacao >= ?")
        params.append(data_inicio)
    if data_fim:
        clauses.append("data_contratacao < ?")
        params.append(data_fim)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _parse_date(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s[:10])


JANELA_TENDENCIA_MAX_DIAS = 365


def _periodo_anterior(data_inicio: str, data_fim: str, conn):
    """Dado um periodo [data_inicio, data_fim), devolve (periodo atual, periodo anterior) para
    comparacao de tendencia. O periodo atual e o final da janela selecionada, limitado a no
    maximo 12 meses -- assim, tanto o padrao "toda a base" (2002-hoje) quanto uma janela curta
    escolhida pelo usuario (ex: jan/25 a jan/26) sempre comparam um recorte recente contra o
    recorte equivalente imediatamente anterior, em vez de comparar contra decadas sem dado algum."""
    cur = conn.cursor()
    if not data_inicio or not data_fim:
        max_data = cur.execute("SELECT MAX(data_contratacao) FROM operations").fetchone()[0]
        if not max_data:
            hoje = datetime.date.today()
        else:
            hoje = _parse_date(max_data) + datetime.timedelta(days=1)
        data_fim = hoje.isoformat()
        data_inicio = (hoje - datetime.timedelta(days=JANELA_TENDENCIA_MAX_DIAS)).isoformat()

    inicio_selecionado = _parse_date(data_inicio)
    fim = _parse_date(data_fim)
    delta = fim - inicio_selecionado
    if delta.days <= 0:
        delta = datetime.timedelta(days=JANELA_TENDENCIA_MAX_DIAS)
    delta = min(delta, datetime.timedelta(days=JANELA_TENDENCIA_MAX_DIAS))

    inicio = fim - delta
    anterior_fim = inicio
    anterior_inicio = inicio - delta
    return inicio.isoformat(), data_fim, anterior_inicio.isoformat(), anterior_fim.isoformat()


@app.get("/api/status")
def status():
    conn = get_connection()
    try:
        cur = conn.cursor()
        n_ops = cur.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        n_pendente = cur.execute("SELECT COUNT(*) FROM operations WHERE setor_origem = 'pendente'").fetchone()[0]
        min_max = cur.execute("SELECT MIN(data_contratacao), MAX(data_contratacao) FROM operations").fetchone()
        last = cur.execute(
            "SELECT started_at, finished_at, status FROM refresh_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "n_operacoes": n_ops,
            "setores_pendentes": n_pendente,
            "data_min": min_max[0],
            "data_max": min_max[1],
            "ultimo_refresh": {"started_at": last[0], "finished_at": last[1], "status": last[2]} if last else None,
            "hospedado": MODO_HOSPEDADO,
        }
    finally:
        conn.close()


@app.get("/api/filtros")
def filtros():
    conn = get_connection()
    try:
        cur = conn.cursor()

        def col_values(col):
            return [r[0] for r in cur.execute(f"SELECT DISTINCT {col} FROM operations WHERE {col} IS NOT NULL ORDER BY {col}").fetchall()]

        min_max = cur.execute("SELECT MIN(data_contratacao), MAX(data_contratacao) FROM operations").fetchone()
        return {
            "agencias": col_values("agencia"),
            "setores": col_values("setor_bndes"),
            "ufs": col_values("uf"),
            "instrumentos": col_values("instrumento"),
            "anos": col_values("ano"),
            "data_min": min_max[0],
            "data_max": min_max[1],
        }
    finally:
        conn.close()


@app.get("/api/kpis")
def kpis(agencia: str = None, setor: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None, instrumento: str = None):
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim, instrumento)
    conn = get_connection()
    try:
        cur = conn.cursor()
        total = cur.execute(
            f"SELECT COUNT(*), SUM(valor_contratado), SUM(valor_desembolsado), AVG(valor_contratado) FROM operations {where}",
            params,
        ).fetchone()
        por_agencia = cur.execute(
            f"SELECT agencia, COUNT(*), SUM(valor_contratado), AVG(valor_contratado) FROM operations {where} GROUP BY agencia",
            params,
        ).fetchall()
        return {
            "n_operacoes": total[0] or 0,
            "valor_contratado_total": total[1] or 0,
            "valor_desembolsado_total": total[2] or 0,
            "cheque_medio": total[3] or 0,
            "por_agencia": [
                {"agencia": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "cheque_medio": r[3] or 0}
                for r in por_agencia
            ],
        }
    finally:
        conn.close()


@app.get("/api/serie_temporal")
def serie_temporal(agencia: str = None, setor: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None, instrumento: str = None):
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim, instrumento)
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT ano, trimestre, agencia, COUNT(*), SUM(valor_contratado)
            FROM operations {where}
            {"AND" if where else "WHERE"} ano IS NOT NULL
            GROUP BY ano, trimestre, agencia
            ORDER BY ano, trimestre
            """,
            params,
        ).fetchall()
        return [
            {"ano": r[0], "trimestre": r[1], "agencia": r[2], "n_operacoes": r[3], "valor_total": r[4] or 0}
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/api/setores")
def setores(agencia: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None, instrumento: str = None):
    where, params = _filters_clause(agencia, None, uf, data_inicio, data_fim, instrumento)
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(setor_bndes, 'Nao classificado'), COUNT(*), SUM(valor_contratado), AVG(valor_contratado)
            FROM operations {where}
            GROUP BY setor_bndes
            ORDER BY SUM(valor_contratado) DESC
            """,
            params,
        ).fetchall()
        return [
            {"setor": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "cheque_medio": r[3] or 0}
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/api/subsetores")
def subsetores(setor: str = None, agencia: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None, instrumento: str = None):
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim, instrumento)
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(subsetor_bndes, 'Nao classificado'), COUNT(*), SUM(valor_contratado), AVG(valor_contratado)
            FROM operations {where}
            GROUP BY subsetor_bndes
            ORDER BY SUM(valor_contratado) DESC
            """,
            params,
        ).fetchall()
        return [
            {"subsetor": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "cheque_medio": r[3] or 0}
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/api/segmentos")
def segmentos(setor: str = None, subsetor: str = None, agencia: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None, instrumento: str = None, limit: int = 20):
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim, instrumento, subsetor)
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(segmento, 'Nao classificado'), COUNT(*), SUM(valor_contratado), AVG(valor_contratado)
            FROM operations {where}
            GROUP BY segmento
            ORDER BY SUM(valor_contratado) DESC
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


@app.get("/api/uf")
def uf_breakdown(agencia: str = None, setor: str = None, data_inicio: str = None, data_fim: str = None, instrumento: str = None):
    where, params = _filters_clause(agencia, setor, None, data_inicio, data_fim, instrumento)
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(uf, 'NI'), COUNT(*), SUM(valor_contratado)
            FROM operations {where}
            GROUP BY uf
            ORDER BY SUM(valor_contratado) DESC
            """,
            params,
        ).fetchall()
        return [{"uf": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0} for r in rows]
    finally:
        conn.close()


@app.get("/api/porte")
def porte_breakdown(agencia: str = None, setor: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None):
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim)
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(porte_cliente, 'Nao informado'), COUNT(*), SUM(valor_contratado)
            FROM operations {where}
            GROUP BY porte_cliente
            ORDER BY SUM(valor_contratado) DESC
            """,
            params,
        ).fetchall()
        return [{"porte": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0} for r in rows]
    finally:
        conn.close()


def _ranking_variacao(conn, group_col: str, agencia, uf, instrumento, setor_pai, data_inicio, data_fim, subsetor_pai=None):
    """Ranking generico de variacao de participacao entre periodo atual e anterior, respeitando filtros."""
    data_inicio, data_fim, ant_inicio, ant_fim = _periodo_anterior(data_inicio, data_fim, conn)
    where_base, params_base = _filters_clause(agencia, setor_pai, uf, None, None, instrumento, subsetor_pai)
    cur = conn.cursor()

    def valor_por_grupo(d_ini, d_fim):
        where = where_base + (" AND " if where_base else "WHERE ") + "data_contratacao >= ? AND data_contratacao < ?"
        rows = cur.execute(
            f"SELECT COALESCE({group_col}, 'Nao classificado'), SUM(valor_contratado), COUNT(*) "
            f"FROM operations {where} GROUP BY {group_col}",
            params_base + [d_ini, d_fim],
        ).fetchall()
        total = sum(r[1] or 0 for r in rows) or 1
        return {r[0]: {"valor": r[1] or 0, "n": r[2], "part": (r[1] or 0) / total} for r in rows}, total

    atual, total_atual = valor_por_grupo(data_inicio, data_fim)
    anterior, total_anterior = valor_por_grupo(ant_inicio, ant_fim)

    grupos = set(atual) | set(anterior)
    out = []
    for g in grupos:
        a = atual.get(g, {"valor": 0, "n": 0, "part": 0})
        p = anterior.get(g, {"valor": 0, "n": 0, "part": 0})
        variacao_pp = (a["part"] - p["part"]) * 100
        out.append({
            "grupo": g,
            "participacao_atual_pct": a["part"] * 100,
            "participacao_anterior_pct": p["part"] * 100,
            "variacao_pp": variacao_pp,
            "valor_atual": a["valor"],
            "n_operacoes_atual": a["n"],
        })
    out.sort(key=lambda r: r["variacao_pp"], reverse=True)
    return {
        "data_inicio": data_inicio, "data_fim": data_fim,
        "data_inicio_anterior": ant_inicio, "data_fim_anterior": ant_fim,
        "grupos": out,
    }


@app.get("/api/tendencias/setores")
def tendencias_setores(agencia: str = None, uf: str = None, instrumento: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de setores por variacao de participacao entre o periodo selecionado e o periodo anterior equivalente."""
    conn = get_connection()
    try:
        r = _ranking_variacao(conn, "setor_bndes", agencia, uf, instrumento, None, data_inicio, data_fim)
        return {
            "periodo_atual": [r["data_inicio"], r["data_fim"]],
            "periodo_anterior": [r["data_inicio_anterior"], r["data_fim_anterior"]],
            "setores": [{**g, "setor": g["grupo"]} for g in r["grupos"]],
        }
    finally:
        conn.close()


@app.get("/api/tendencias/subsetores")
def tendencias_subsetores(setor: str = Query(...), agencia: str = None, uf: str = None, instrumento: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de subsetores (dentro de um setor) por variacao de participacao."""
    conn = get_connection()
    try:
        r = _ranking_variacao(conn, "subsetor_bndes", agencia, uf, instrumento, setor, data_inicio, data_fim)
        return {
            "setor": setor,
            "periodo_atual": [r["data_inicio"], r["data_fim"]],
            "periodo_anterior": [r["data_inicio_anterior"], r["data_fim_anterior"]],
            "subsetores": [{**g, "subsetor": g["grupo"]} for g in r["grupos"]],
        }
    finally:
        conn.close()


@app.get("/api/tendencias/segmentos")
def tendencias_segmentos(setor: str = Query(...), subsetor: str = None, agencia: str = None, uf: str = None, instrumento: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de segmentos CNAE (granularidade fina) dentro de um setor, por variacao de participacao."""
    conn = get_connection()
    try:
        r = _ranking_variacao(conn, "segmento", agencia, uf, instrumento, setor, data_inicio, data_fim, subsetor_pai=subsetor)
        return {
            "setor": setor,
            "subsetor": subsetor,
            "periodo_atual": [r["data_inicio"], r["data_fim"]],
            "periodo_anterior": [r["data_inicio_anterior"], r["data_fim_anterior"]],
            "segmentos": [{**g, "segmento": g["grupo"]} for g in r["grupos"]],
        }
    finally:
        conn.close()


@app.get("/api/tendencias/produtos")
def tendencias_produtos(agencia: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None):
    where, params = _filters_clause(agencia, None, uf, data_inicio, data_fim)
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(produto, instrumento, 'Nao informado'), COUNT(*), SUM(valor_contratado)
            FROM operations {where}
            GROUP BY produto
            ORDER BY SUM(valor_contratado) DESC
            LIMIT 20
            """,
            params,
        ).fetchall()
        return [{"produto": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0} for r in rows]
    finally:
        conn.close()


ORDENACAO_COLUNAS = {
    "valor": "valor_contratado",
    "data": "data_contratacao",
    "instituicao": "agente_financeiro",
    "agencia": "agencia",
    "cliente": "cliente",
}


@app.get("/api/operacoes")
def operacoes(
    agencia: str = None,
    setor: str = None,
    subsetor: str = None,
    segmento: str = None,
    uf: str = None,
    data_inicio: str = None,
    data_fim: str = None,
    instrumento: str = None,
    order_by: str = "valor",
    order_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
):
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim, instrumento, subsetor, segmento)
    coluna_ordenacao = ORDENACAO_COLUNAS.get(order_by, "valor_contratado")
    direcao = "ASC" if order_dir == "asc" else "DESC"
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT id, agencia, instrumento, cliente, cnpj, uf, municipio, data_contratacao,
                   valor_contratado, valor_desembolsado, setor_bndes, subsetor_bndes, segmento,
                   produto, descricao_projeto, agente_financeiro
            FROM operations {where}
            ORDER BY {coluna_ordenacao} {direcao} NULLS LAST
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
        cols = [
            "id", "agencia", "instrumento", "cliente", "cnpj", "uf", "municipio", "data_contratacao",
            "valor_contratado", "valor_desembolsado", "setor_bndes", "subsetor_bndes", "segmento",
            "produto", "descricao_projeto", "agente_financeiro",
        ]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


@app.get("/api/operacoes/{op_id}")
def operacao_detalhe(op_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT raw_table, raw_id, agencia, instrumento FROM operations WHERE id = ?", (op_id,)
        ).fetchone()
        if not row:
            return {"erro": "operacao nao encontrada"}
        raw_table, raw_id, agencia, instrumento = row
        raw_row = cur.execute(f"SELECT * FROM {raw_table} WHERE id = ?", (raw_id,)).fetchone()
        if not raw_row:
            return {"raw_table": raw_table, "secoes": []}
        col_names = [d[0] for d in cur.description]
        raw = dict(zip(col_names, raw_row))
        secoes = montar_detalhe_amigavel(raw_table, raw)
        return {"raw_table": raw_table, "agencia": agencia, "instrumento": instrumento, "secoes": secoes}
    finally:
        conn.close()


try:
    from search import buscar_rapido, gerar_narrativa, refinar_resultados

    @app.get("/api/busca")
    def busca(q: str = Query(..., min_length=3)):
        try:
            return buscar_rapido(q)
        except Exception as e:
            return {"erro": f"motor de busca indisponivel no momento: {e}"}

    @app.get("/api/busca/refinar")
    def busca_refinar(q: str = Query(..., min_length=3)):
        """2a etapa (lenta, Ollama): revisa a lista rapida, remove falsos-positivos,
        reordena por relevancia real e busca termos correlatos que podem ter ficado
        de fora. Devolve a lista de resultados ja atualizada."""
        try:
            r = buscar_rapido(q)
            refinado = refinar_resultados(r["query_expandida"], r["resultados"])
            return {
                "resultados": refinado["resultados"],
                "refinado": refinado["refinado"],
                "n_removidos": refinado["n_removidos"],
                "n_adicionados": refinado["n_adicionados"],
                "termos_adicionais": refinado.get("termos_adicionais", []),
            }
        except Exception as e:
            return {"erro": f"refinamento indisponivel no momento: {e}"}

    @app.get("/api/busca/narrativa")
    def busca_narrativa(q: str = Query(..., min_length=3)):
        try:
            r = buscar_rapido(q)
            narrativa = gerar_narrativa(
                r["query_expandida"], r["tendencia_segmento"], r["tendencia_setor"], r["resultados"], r["confianca_baixa"]
            )
            return {"narrativa": narrativa}
        except Exception as e:
            return {"erro": f"narrador indisponivel no momento: {e}"}
except ImportError as e:
    @app.get("/api/busca")
    def busca_indisponivel(q: str = ""):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.get("/api/busca/refinar")
    def busca_refinar_indisponivel(q: str = ""):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.get("/api/busca/narrativa")
    def busca_narrativa_indisponivel(q: str = ""):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}


EDITAIS_COLS = [
    "id", "titulo", "tema_principal", "temas", "situacao", "tipo_oportunidade",
    "tipo_cooperacao", "contrapartida", "regiao", "publico_alvo", "aplicavel_empresa",
    "data_publicacao", "vigencia_inicio", "vigencia_fim", "prazo_proposto",
    "descricao_texto", "documentos",
]


def _edital_row_to_dict(row) -> dict:
    import json

    from editais_search import _dias_restantes

    d = dict(zip(EDITAIS_COLS, row))
    d["publico_alvo"] = json.loads(d["publico_alvo"]) if d.get("publico_alvo") else []
    d["documentos"] = json.loads(d["documentos"]) if d.get("documentos") else []
    d["dias_restantes"] = _dias_restantes(d.get("prazo_proposto"))
    return d


def _editais_where(situacao=None, aplicavel_empresa=None, tema=None, regiao=None,
                    tipo_oportunidade=None, tipo_cooperacao=None, q=None):
    """Monta o WHERE da lista de editais. IMPORTANTE: o campo situacao da propria FINEP
    as vezes fica desatualizado (edital continua 'aberta' com prazo_proposto ja vencido).
    Por isso, ao filtrar por situacao='aberta', tambem exigimos que o prazo de submissao
    (quando existe) ainda nao tenha passado -- senao mostraria como aberto algo que na
    pratica ja fechou."""
    clauses = []
    params = []
    if situacao == "aberta":
        clauses.append("situacao = ? AND (prazo_proposto IS NULL OR date(prazo_proposto) >= date('now'))")
        params.append("aberta")
    elif situacao:
        clauses.append("situacao = ?")
        params.append(situacao)
    if aplicavel_empresa is not None:
        clauses.append("aplicavel_empresa = ?")
        params.append(1 if aplicavel_empresa else 0)
    if tema:
        clauses.append("tema_principal = ?")
        params.append(tema)
    if regiao:
        clauses.append("regiao = ?")
        params.append(regiao)
    if tipo_oportunidade:
        clauses.append("tipo_oportunidade = ?")
        params.append(tipo_oportunidade)
    if tipo_cooperacao:
        clauses.append("tipo_cooperacao = ?")
        params.append(tipo_cooperacao)
    if q:
        clauses.append("titulo LIKE ?")
        params.append(f"%{q}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@app.get("/api/editais/filtros")
def editais_filtros():
    conn = get_connection()
    try:
        cur = conn.cursor()

        def col_values(col):
            return [r[0] for r in cur.execute(
                f"SELECT DISTINCT {col} FROM editais_raw WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}"
            ).fetchall()]

        return {
            "temas": col_values("tema_principal"),
            "regioes": col_values("regiao"),
            "tipos_oportunidade": col_values("tipo_oportunidade"),
            "tipos_cooperacao": col_values("tipo_cooperacao"),
        }
    finally:
        conn.close()


@app.get("/api/editais/dashboard")
def editais_dashboard(situacao: str = None, aplicavel_empresa: int = None, tema: str = None,
                       regiao: str = None, tipo_oportunidade: str = None, tipo_cooperacao: str = None,
                       q: str = None):
    from editais_search import _dias_restantes

    where, params = _editais_where(situacao, aplicavel_empresa, tema, regiao, tipo_oportunidade, tipo_cooperacao, q)
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(f"SELECT prazo_proposto, tema_principal FROM editais_raw {where}", params).fetchall()
        n_total = len(rows)
        n_30_dias = 0
        por_tema = {}
        for prazo, tema_row in rows:
            dias = _dias_restantes(prazo)
            if dias is not None and 0 <= dias <= 30:
                n_30_dias += 1
            chave = tema_row or "Não classificado"
            por_tema[chave] = por_tema.get(chave, 0) + 1
        tema_lista = sorted(({"tema": k, "n_editais": v} for k, v in por_tema.items()), key=lambda x: -x["n_editais"])
        return {"n_total": n_total, "n_fecham_30_dias": n_30_dias, "por_tema": tema_lista}
    finally:
        conn.close()


@app.get("/api/editais")
def editais_lista(situacao: str = None, aplicavel_empresa: int = None, tema: str = None,
                   regiao: str = None, tipo_oportunidade: str = None, tipo_cooperacao: str = None,
                   q: str = None, order_by: str = "prazo", order_dir: str = "asc", limit: int = 200):
    where, params = _editais_where(situacao, aplicavel_empresa, tema, regiao, tipo_oportunidade, tipo_cooperacao, q)
    colunas_ordenacao = {
        "prazo": "prazo_proposto",
        "publicacao": "data_publicacao",
        "titulo": "titulo",
    }
    coluna = colunas_ordenacao.get(order_by, "prazo_proposto")
    direcao = "DESC" if order_dir == "desc" else "ASC"
    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"SELECT {', '.join(EDITAIS_COLS)} FROM editais_raw {where} "
            f"ORDER BY {coluna} {direcao} NULLS LAST LIMIT ?",
            params + [limit],
        ).fetchall()
        return [_edital_row_to_dict(r) for r in rows]
    finally:
        conn.close()


try:
    import editais_search
    from editais_search import (
        _COLS_EDITAL,
        _montar_edital,
        buscar_editais_por_projeto,
        gerar_leitura_elegibilidade,
        montar_prompt_leitura,
        montar_prompt_refino,
        montar_prompt_resumo,
        refinar_editais,
        resumir_edital,
        salvar_resumo,
    )

    @app.on_event("startup")
    def _warmup_editais():
        try:
            from editais_search import warmup as warmup_editais

            warmup_editais()
            print("Motor de busca de editais pronto (embeddings de editais carregados).")
        except Exception as e:
            print(f"Aviso: motor de busca de editais nao pode ser pre-carregado ({e}).")

    def _edital_por_id(edital_id: int):
        conn = get_connection()
        try:
            row = conn.execute(
                f"SELECT {', '.join(_COLS_EDITAL)} FROM editais_raw WHERE id=?", (edital_id,)
            ).fetchone()
        finally:
            conn.close()
        return _montar_edital(dict(zip(_COLS_EDITAL, row))) if row else None

    # IMPORTANTE: estas duas rotas de path fixo (/buscar, /buscar/leitura) precisam
    # ser registradas ANTES de /api/editais/{edital_id} -- senao o FastAPI casa
    # "buscar" como se fosse um edital_id (rota generica registrada primeiro vence).
    @app.get("/api/editais/buscar")
    def editais_buscar(q: str = Query(..., min_length=3)):
        try:
            return buscar_editais_por_projeto(q)
        except Exception as e:
            return {"erro": f"busca de editais indisponivel no momento: {e}"}

    @app.get("/api/editais/buscar/refinar")
    def editais_buscar_refinar(q: str = Query(..., min_length=3)):
        """Etapa lenta (IA): remove falsos-positivos da busca rapida -- editais que so
        bateram por semelhanca generica de texto mas nao tem elegibilidade real para o
        que foi descrito. O frontend so mostra os cards depois desta etapa.

        Modo local (desktop): o proprio backend chama o Ollama e ja devolve o
        resultado filtrado, como sempre.
        Modo hospedado: nao ha Ollama no servidor -- devolve os resultados AINDA
        NAO filtrados + o prompt, pro navegador de quem esta usando gerar via o
        Ollama local dela e filtrar no proprio navegador (ver local-ai.js)."""
        try:
            r = buscar_editais_por_projeto(q)
            if MODO_HOSPEDADO:
                prep = montar_prompt_refino(q, r["resultados"])
                return {
                    "hospedado": True,
                    "resultados_sem_filtro": r["resultados"],
                    "prompt": prep["prompt"],
                    "modelo": prep["modelo"],
                    "opcoes": prep["opcoes"],
                    "candidatos_ids": prep["candidatos_ids"],
                }
            refino = refinar_editais(q, r["resultados"])
            return {
                "hospedado": False,
                "resultados": refino["resultados"],
                "refinado": refino["refinado"],
                "n_removidos": refino["n_removidos"],
                "n_originais": refino["n_originais"],
            }
        except Exception as e:
            return {"erro": f"refinamento indisponivel no momento: {e}"}

    @app.get("/api/editais/buscar/leitura")
    def editais_buscar_leitura(q: str = Query(..., min_length=3), ids: str = None):
        """Gera a leitura em texto a partir de uma lista de editais ja refinada (ids
        vem do resultado de /buscar/refinar) -- evita rodar o refino de novo so para
        montar o texto. Mesma logica local x hospedado do /buscar/refinar acima."""
        try:
            if ids:
                id_list = [int(i) for i in ids.split(",") if i.strip().lstrip("-").isdigit()]
                conn = get_connection()
                try:
                    placeholders = ",".join("?" * len(id_list))
                    rows = conn.execute(
                        f"SELECT {', '.join(EDITAIS_COLS)} FROM editais_raw WHERE id IN ({placeholders})", id_list
                    ).fetchall()
                finally:
                    conn.close()
                by_id = {r[0]: _edital_row_to_dict(r) for r in rows}
                resultados = [by_id[i] for i in id_list if i in by_id]
            else:
                resultados = buscar_editais_por_projeto(q)["resultados"]

            if MODO_HOSPEDADO:
                prep = montar_prompt_leitura(q, resultados)
                return {"hospedado": True, "prompt": prep.get("prompt"), "modelo": prep.get("modelo"),
                        "opcoes": prep.get("opcoes"), "fallback": prep.get("fallback")}
            leitura = gerar_leitura_elegibilidade(q, resultados)
            return {"hospedado": False, "leitura": leitura}
        except Exception as e:
            return {"erro": f"leitura indisponivel no momento: {e}"}

    @app.get("/api/editais/{edital_id}/resumo")
    def edital_resumo(edital_id: int, forcar: bool = False):
        """Modo local: gera (ou reusa cache) chamando o Ollama do proprio backend.
        Modo hospedado: se ja tem cache compartilhado, devolve na hora; senao,
        devolve o prompt pro navegador gerar e depois avisar via POST nesta mesma
        rota (quem gerar primeiro salva pra todo mundo)."""
        try:
            if MODO_HOSPEDADO:
                edital = _edital_por_id(edital_id)
                if not edital:
                    return {"erro": "Edital não encontrado."}
                if edital.get("resumo_ia") and not forcar:
                    return {"hospedado": True, "resumo": edital["resumo_ia"], "gerado_em": edital.get("resumo_gerado_em"), "cache": True}
                prep = montar_prompt_resumo(edital)
                return {
                    "hospedado": True, "cache": False, "precisa_gerar": True,
                    "prompt": prep["prompt"], "modelo": prep["modelo"], "opcoes": prep["opcoes"],
                    "fallback": prep["fallback"],
                }
            return resumir_edital(edital_id, forcar=forcar)
        except Exception as e:
            return {"erro": f"resumo indisponivel no momento: {e}"}

    @app.post("/api/editais/{edital_id}/resumo")
    def edital_resumo_salvar(edital_id: int, body: dict):
        """So usada no modo hospedado -- o navegador de quem gerou o resumo via
        Ollama local manda o texto aqui pra virar cache compartilhado."""
        try:
            resumo_texto = (body or {}).get("resumo", "")
            return salvar_resumo(edital_id, resumo_texto)
        except Exception as e:
            return {"erro": f"nao foi possivel salvar o resumo: {e}"}
except ImportError as e:
    @app.get("/api/editais/buscar")
    def editais_buscar_indisponivel(q: str = ""):
        return {"erro": f"motor de busca de editais ainda nao configurado: {e}"}

    @app.get("/api/editais/buscar/refinar")
    def editais_buscar_refinar_indisponivel(q: str = ""):
        return {"erro": f"motor de busca de editais ainda nao configurado: {e}"}

    @app.get("/api/editais/buscar/leitura")
    def editais_buscar_leitura_indisponivel(q: str = "", ids: str = None):
        return {"erro": f"motor de busca de editais ainda nao configurado: {e}"}

    @app.get("/api/editais/{edital_id}/resumo")
    def edital_resumo_indisponivel(edital_id: int, forcar: bool = False):
        return {"erro": f"motor de resumo de editais ainda nao configurado: {e}"}


@app.get("/api/editais/{edital_id}")
def edital_detalhe(edital_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
        row = cur.execute(
            f"SELECT {', '.join(EDITAIS_COLS)} FROM editais_raw WHERE id = ?", (edital_id,)
        ).fetchone()
        if not row:
            return {"erro": "edital nao encontrado"}
        return _edital_row_to_dict(row)
    finally:
        conn.close()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
