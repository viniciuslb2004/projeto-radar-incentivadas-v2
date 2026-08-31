"""API FastAPI do Radar de Credito Incentivado (BNDES + FINEP)."""
import datetime
import logging
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from db import MODO_HOSPEDADO, get_connection
from webapp.detalhe import montar_detalhe_amigavel

# As rotas de IA/busca (abaixo) capturam Exception generico e devolvem {"erro": ...}
# de proposito -- uma falha de IA nao deve derrubar a pagina inteira pro usuario.
# Mas sem logar em algum lugar, um bug de verdade (KeyError, etc) fica indistinguivel
# de "IA indisponivel no momento" tanto pra quem chamou quanto nos logs do Render --
# logger.exception() abaixo manda o traceback completo pro stdout/stderr do processo
# (que o Render ja captura), sem mudar a resposta HTTP que o cliente recebe.
logger = logging.getLogger("radar")

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

# ============ Instalador da IA local (1 script, um clique) ============
# O modal "Baixar IA local" (ver webapp/static/js/local-ai.js) precisa que o
# visitante rode "ollama pull" + "setx OLLAMA_ORIGINS" com a origem CORRETA
# deste app -- que muda dependendo de onde o app esta rodando (localhost no
# desktop, dominio da Vercel no deploy hospedado). Por isso a origem nao pode
# ser fixa no script: descobrimos ela em tempo real a partir do request de
# quem pediu o download, com fallback pro que ja estiver configurado no
# ambiente (mesma fonte que o CORS ja usa, ver ALLOWED_ORIGINS acima).
OLLAMA_MODELO_PADRAO = "llama3.1:8b-instruct-q4_K_M"
_ORIGEM_RE = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$")


def _origem_valida(origem: str) -> bool:
    return bool(origem) and bool(_ORIGEM_RE.match(origem.strip()))


def _detectar_origem_publica(request: Request) -> str:
    """Descobre a origem (scheme://host[:porta]) de onde este app esta sendo
    servido para este visitante especifico. Tenta, em ordem: o header Origin
    do proprio request (o jeito mais confiavel -- e literalmente de onde o
    navegador fez a chamada), o header Referer, a variavel de ambiente
    PUBLIC_BASE_URL (se alguem quiser fixar isso no deploy), a primeira
    entrada nao-localhost de ALLOWED_ORIGINS, e por fim um fallback local.
    Cada candidato passa por validacao de formato antes de ser aceito -- os
    headers vem do visitante e vao parar dentro de um script que ele mesmo
    vai rodar, entao nao da pra confiar neles sem checar."""
    candidatos = []

    origin_header = request.headers.get("origin")
    if origin_header:
        candidatos.append(origin_header.strip())

    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            candidatos.append(f"{parsed.scheme}://{parsed.netloc}")

    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if public_base_url:
        candidatos.append(public_base_url.rstrip("/"))

    for o in [x.strip() for x in _allowed_origins.split(",") if x.strip()]:
        if "localhost" not in o and "127.0.0.1" not in o:
            candidatos.append(o)

    candidatos.append("http://127.0.0.1:8001")

    for c in candidatos:
        if _origem_valida(c):
            return c
    return "http://127.0.0.1:8001"


_SCRIPT_INSTALAR_IA_TEMPLATE = r"""# ============================================================
#  Instalador automatico da IA local - Radar de Credito Incentivado
#  Gerado automaticamente por __ORIGIN__ -- seguro rodar mais de uma vez.
# ============================================================

function Escrever($msg, $cor = "White") {
    Write-Host $msg -ForegroundColor $cor
}

Write-Host ""
Escrever "=====================================================" "Cyan"
Escrever " Configurando a IA local para o Radar de Credito Incentivado" "Cyan"
Escrever "=====================================================" "Cyan"
Write-Host ""

$origem = "__ORIGIN__"
$modelo = "__MODEL__"

# 1) Verifica se o Ollama esta instalado
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaCmd) {
    Escrever "[ERRO] O Ollama nao foi encontrado neste computador." "Red"
    Escrever "Instale primeiro em https://ollama.com/download e rode este script de novo." "Yellow"
    Write-Host ""
    Read-Host "Pressione ENTER para fechar"
    exit 1
}
Escrever "[OK] Ollama encontrado em $($ollamaCmd.Source)" "Green"

# 2) Baixa o modelo de IA (comando idempotente -- se ja tiver, so confirma)
Write-Host ""
Escrever "Baixando o modelo de IA ($modelo)... pode demorar alguns minutos na primeira vez." "Cyan"
& ollama pull $modelo
if ($LASTEXITCODE -ne 0) {
    Escrever "[ERRO] Nao foi possivel baixar o modelo. Verifique sua internet e rode o script de novo." "Red"
    Write-Host ""
    Read-Host "Pressione ENTER para fechar"
    exit 1
}
Escrever "[OK] Modelo pronto." "Green"

# 3) Libera este site para conversar com o Ollama (OLLAMA_ORIGINS).
#    Some com origens ja liberadas antes em vez de apagar (script idempotente
#    e seguro mesmo se voce ja tiver liberado outro endereco antes).
Write-Host ""
Escrever "Liberando $origem para acessar a IA local..." "Cyan"
$atual = [Environment]::GetEnvironmentVariable("OLLAMA_ORIGINS", "User")
$origensExistentes = @()
if ($atual) {
    $origensExistentes = @($atual -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
}
if ($origensExistentes -notcontains $origem) {
    $origensExistentes += $origem
}
$novoValor = ($origensExistentes -join ",")
[Environment]::SetEnvironmentVariable("OLLAMA_ORIGINS", $novoValor, "User")
$env:OLLAMA_ORIGINS = $novoValor
Escrever "[OK] OLLAMA_ORIGINS = $novoValor" "Green"

# 4) Reinicia o Ollama para a configuracao nova valer de verdade (setx so
#    afeta processos novos -- por isso derrubamos e subimos de novo aqui,
#    dentro desta mesma sessao, que ja tem a variavel atualizada).
Write-Host ""
Escrever "Reiniciando o Ollama para aplicar a configuracao..." "Cyan"
$processos = Get-Process -Name "ollama*" -ErrorAction SilentlyContinue
if ($processos) {
    $processos | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Escrever "[OK] Processo(s) anterior(es) do Ollama encerrado(s)." "Green"
} else {
    Escrever "Nenhum processo do Ollama estava rodando ainda (tudo bem, seguindo em frente)." "Yellow"
}

$appPath = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
if (Test-Path $appPath) {
    Start-Process -FilePath $appPath
    Escrever "[OK] Ollama reiniciado." "Green"
} else {
    Start-Process -FilePath $ollamaCmd.Source -ArgumentList "serve" -WindowStyle Hidden
    Escrever "[OK] Servidor do Ollama iniciado (ollama serve)." "Green"
}

Start-Sleep -Seconds 2

Write-Host ""
Escrever "=====================================================" "Cyan"
Escrever " Tudo pronto!" "Green"
Escrever " Volte para a aba do navegador, recarregue a pagina (F5)" "Green"
Escrever " e a IA local ja deve aparecer ativa." "Green"
Escrever "=====================================================" "Cyan"
Write-Host ""
Read-Host "Pressione ENTER para fechar esta janela"
"""


@app.get("/api/config/instalar-ia.ps1")
def instalar_ia_script(request: Request):
    """Devolve um script PowerShell pronto para o visitante rodar (duplo-clique) depois
    de instalar o Ollama: baixa o modelo, libera este site no OLLAMA_ORIGINS e reinicia
    o Ollama -- tudo em um unico passo, com a origem certa para ESTE deploy especifico."""
    origem = _detectar_origem_publica(request)
    script = _SCRIPT_INSTALAR_IA_TEMPLATE.replace("__ORIGIN__", origem).replace("__MODEL__", OLLAMA_MODELO_PADRAO)
    return Response(
        content=script,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="instalar-ia-local.ps1"'},
    )


@app.on_event("startup")
def _warmup_busca():
    """Carrega o modelo de embeddings no startup do servidor, nao na primeira busca do usuario
    (sem isso, a primeira busca de cada reinicio parecia travada por ~20-30s).

    Modo HOSPEDADO (Render, free tier, 512MB de RAM): NUNCA chama warmup() aqui --
    carregar o sentence-transformers no processo estouraria esse limite (foi
    literalmente o que derrubou o deploy antes desta mudanca, ver DEPLOY.md). So
    carrega os vetores precalculados (.npz); o embedding da query e calculado no
    navegador de quem esta usando (ver webapp/static/js/embeddings-client.js)."""
    try:
        from search import warmup, warmup_hospedado

        if MODO_HOSPEDADO:
            warmup_hospedado()
            print("Motor de busca pronto (so vetores do corpus -- modo hospedado, sem modelo carregado no servidor).")
        else:
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
    from search import (
        _expandir_query,
        buscar_por_termo_com_vetor,
        buscar_rapido,
        buscar_rapido_com_vetor,
        gerar_narrativa,
        preparar_texto_enriquecido,
        refinar_resultados,
    )
    # Aliases: editais_search.py TAMBEM exporta montar_prompt_refino (com uma
    # assinatura/formato de dados completamente diferente -- editais em vez de
    # operacoes). Sem o alias, o segundo `from editais_search import
    # montar_prompt_refino` (mais abaixo) sobrescreveria silenciosamente este nome no
    # namespace do modulo, e as rotas de busca (definidas ANTES, mas resolvidas em
    # tempo de CHAMADA) passariam a usar por engano a versao de editais -- foi
    # exatamente esse bug que apareceu ao testar (KeyError: 'titulo').
    from search import montar_prompt_narrativa as montar_prompt_narrativa_busca
    from search import montar_prompt_refino as montar_prompt_refino_busca

    # ============ Modo LOCAL (desktop): identico a sempre -- o proprio backend calcula
    # o embedding (get_model()) e chama o Ollama. Estas rotas GET recusam explicitamente
    # rodar em modo hospedado (nunca chamam get_model() nesse caso) -- ver as rotas POST
    # abaixo, que sao as usadas pelo navegador quando MODO_HOSPEDADO=True (busca.js). ============

    @app.get("/api/busca")
    def busca(q: str = Query(..., min_length=3)):
        if MODO_HOSPEDADO:
            return {"erro": "modo hospedado: use GET /api/busca/preparar + POST /api/busca com o vetor calculado no navegador"}
        try:
            return buscar_rapido(q)
        except Exception as e:
            logger.exception("motor de busca indisponivel")
            return {"erro": f"motor de busca indisponivel no momento: {e}"}

    @app.get("/api/busca/refinar")
    def busca_refinar(q: str = Query(..., min_length=3)):
        """2a etapa (lenta, Ollama): revisa a lista rapida, remove falsos-positivos,
        reordena por relevancia real e busca termos correlatos que podem ter ficado
        de fora. Devolve a lista de resultados ja atualizada."""
        if MODO_HOSPEDADO:
            return {"erro": "modo hospedado: use POST /api/busca/refinar com os resultados ja calculados"}
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
            logger.exception("refinamento indisponivel")
            return {"erro": f"refinamento indisponivel no momento: {e}"}

    @app.get("/api/busca/narrativa")
    def busca_narrativa(q: str = Query(..., min_length=3)):
        if MODO_HOSPEDADO:
            return {"erro": "modo hospedado: use POST /api/busca/narrativa com os resultados ja calculados"}
        try:
            r = buscar_rapido(q)
            narrativa = gerar_narrativa(
                r["query_expandida"], r["tendencia_segmento"], r["tendencia_setor"], r["resultados"], r["confianca_baixa"]
            )
            return {"narrativa": narrativa}
        except Exception as e:
            logger.exception("narrador indisponivel")
            return {"erro": f"narrador indisponivel no momento: {e}"}

    # ============ Modo HOSPEDADO: o navegador calcula o embedding (transformers.js, ver
    # embeddings-client.js) e manda o vetor pronto -- o servidor so faz numpy, nunca
    # importa/chama sentence_transformers aqui. Ollama tambem roda no navegador (ver
    # local-ai.js); estas rotas so montam o prompt. ============

    @app.get("/api/busca/preparar")
    def busca_preparar(q: str = Query(..., min_length=3)):
        """So usado no modo hospedado: devolve a query ja expandida (ex: 'fintech' ->
        vocabulario mais proximo do corpus, ver EXPANSAO_TERMOS em search.py) para o
        navegador gerar o vetor com o MESMO texto que o modo local sempre embutiu --
        sem isso o resultado nao seria comparavel. So string processing, sem modelo."""
        return {"query_expandida": _expandir_query(q)}

    @app.get("/api/busca/preparar_enriquecido")
    def busca_preparar_enriquecido(q: str = Query(..., min_length=3)):
        """So usado no modo hospedado: equivalente ao bloco de enriquecimento via web
        que buscar_rapido() faz sozinho no modo local -- so que aqui o embedding roda
        no navegador, entao o cliente precisa de 2 idas e vindas: 1a chamada (POST
        /api/busca) volta com confianca_baixa=True, o navegador chama esta rota para
        pesquisar `q` na web (buscar_atividade_empresa, so requests puro -- nunca
        chama get_model()/SentenceTransformer aqui) e reembute o texto devolvido antes
        de chamar POST /api/busca de novo. Ver o retry em webapp/static/js/busca.js."""
        try:
            return preparar_texto_enriquecido(q)
        except Exception as e:
            logger.exception("enriquecimento indisponivel")
            return {"erro": f"enriquecimento indisponivel no momento: {e}"}

    @app.post("/api/busca")
    def busca_com_vetor(body: dict):
        """Modo hospedado: recebe {q, vetor} com o vetor ja calculado no navegador
        contra o texto de /api/busca/preparar. So faz a matematica (numpy) contra os
        vetores precalculados do corpus -- nunca chama get_model()."""
        q = (body or {}).get("q", "")
        vetor = (body or {}).get("vetor")
        if not q or not vetor:
            return {"erro": "parametros 'q' e 'vetor' sao obrigatorios"}
        try:
            return buscar_rapido_com_vetor(q, vetor)
        except Exception as e:
            logger.exception("motor de busca indisponivel")
            return {"erro": f"motor de busca indisponivel no momento: {e}"}

    @app.post("/api/busca/refinar")
    def busca_refinar_com_vetor(body: dict):
        """Modo hospedado: recebe {query_expandida, resultados} (resultados = o que
        veio de POST /api/busca) e devolve so o PROMPT -- quem gera e o Ollama local de
        quem esta usando (ver local-ai.js), a filtragem do JSON acontece no navegador."""
        query_expandida = (body or {}).get("query_expandida", "")
        resultados = (body or {}).get("resultados", [])
        try:
            prep = montar_prompt_refino_busca(query_expandida, resultados)
            return {
                "prompt": prep.get("prompt"),
                "modelo": prep.get("modelo"),
                "opcoes": prep.get("opcoes"),
                "candidatos_ids": prep.get("candidatos_ids", []),
            }
        except Exception as e:
            logger.exception("refinamento indisponivel")
            return {"erro": f"refinamento indisponivel no momento: {e}"}

    @app.post("/api/busca/termo")
    def busca_termo_com_vetor(body: dict):
        """Modo hospedado: parte do refino -- busca operacoes por um termo correlato
        sugerido pela IA (o navegador ja calculou o vetor do termo), equivalente ao
        _buscar_por_termo() do modo local, sem chamar get_model()."""
        termo = (body or {}).get("termo", "")
        vetor = (body or {}).get("vetor")
        ja_incluidos = (body or {}).get("ja_incluidos", []) or []
        if not vetor:
            return {"erro": "parametro 'vetor' e obrigatorio"}
        try:
            achados = buscar_por_termo_com_vetor(termo, vetor, set(ja_incluidos))
            return {"resultados": achados}
        except Exception as e:
            logger.exception("busca por termo indisponivel")
            return {"erro": f"busca por termo indisponivel no momento: {e}"}

    @app.post("/api/busca/narrativa")
    def busca_narrativa_com_vetor(body: dict):
        """Modo hospedado: recebe os dados ja calculados (query_expandida, tendencias,
        resultados finais apos refino) e devolve so o prompt -- o Ollama local de quem
        esta usando e quem gera o texto (ver local-ai.js)."""
        query_expandida = (body or {}).get("query_expandida", "")
        tendencia_segmento = (body or {}).get("tendencia_segmento")
        tendencia_setor = (body or {}).get("tendencia_setor")
        resultados = (body or {}).get("resultados", [])
        confianca_baixa = bool((body or {}).get("confianca_baixa", False))
        try:
            prep = montar_prompt_narrativa_busca(query_expandida, tendencia_segmento, tendencia_setor, resultados, confianca_baixa)
            return {
                "prompt": prep.get("prompt"),
                "modelo": prep.get("modelo"),
                "opcoes": prep.get("opcoes"),
                "fallback": prep.get("fallback"),
            }
        except Exception as e:
            logger.exception("narrador indisponivel")
            return {"erro": f"narrador indisponivel no momento: {e}"}
except ImportError as e:
    @app.get("/api/busca")
    def busca_indisponivel(q: str = ""):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.post("/api/busca")
    def busca_indisponivel_post(body: dict = None):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.get("/api/busca/preparar")
    def busca_preparar_indisponivel(q: str = ""):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.get("/api/busca/preparar_enriquecido")
    def busca_preparar_enriquecido_indisponivel(q: str = ""):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.get("/api/busca/refinar")
    def busca_refinar_indisponivel(q: str = ""):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.post("/api/busca/refinar")
    def busca_refinar_indisponivel_post(body: dict = None):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.post("/api/busca/termo")
    def busca_termo_indisponivel(body: dict = None):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.get("/api/busca/narrativa")
    def busca_narrativa_indisponivel(q: str = ""):
        return {"erro": f"motor de busca ainda nao configurado: {e}"}

    @app.post("/api/busca/narrativa")
    def busca_narrativa_indisponivel_post(body: dict = None):
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
        buscar_editais_por_projeto_com_vetor,
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
        """Modo HOSPEDADO: so carrega o .npz de vetores dos editais (warmup_hospedado,
        numpy, barato) -- NUNCA chama get_model() aqui (estouraria a RAM do free tier
        do Render). Modo local: warmup() completo, como sempre."""
        try:
            from editais_search import warmup as warmup_editais
            from editais_search import warmup_hospedado as warmup_editais_hospedado

            if MODO_HOSPEDADO:
                warmup_editais_hospedado()
                print("Motor de busca de editais pronto (so vetores -- modo hospedado, sem modelo carregado no servidor).")
            else:
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
        """Modo local (desktop) apenas -- calcula o embedding no proprio processo
        (get_model()). Modo hospedado usa POST /api/editais/buscar (vetor do navegador)."""
        if MODO_HOSPEDADO:
            return {"erro": "modo hospedado: use POST /api/editais/buscar com o vetor calculado no navegador"}
        try:
            return buscar_editais_por_projeto(q)
        except Exception as e:
            logger.exception("busca de editais indisponivel")
            return {"erro": f"busca de editais indisponivel no momento: {e}"}

    @app.post("/api/editais/buscar")
    def editais_buscar_com_vetor(body: dict):
        """Modo hospedado: recebe {q, vetor} com o vetor ja calculado no navegador
        (transformers.js, ver embeddings-client.js) -- so faz a matematica (numpy)
        contra os vetores precalculados dos editais abertos, nunca chama get_model()."""
        q = (body or {}).get("q", "")
        vetor = (body or {}).get("vetor")
        if not q or not vetor:
            return {"erro": "parametros 'q' e 'vetor' sao obrigatorios"}
        try:
            return buscar_editais_por_projeto_com_vetor(q, vetor)
        except Exception as e:
            logger.exception("busca de editais indisponivel")
            return {"erro": f"busca de editais indisponivel no momento: {e}"}

    @app.get("/api/editais/buscar/refinar")
    def editais_buscar_refinar(q: str = Query(..., min_length=3)):
        """Etapa lenta (IA): remove falsos-positivos da busca rapida -- editais que so
        bateram por semelhanca generica de texto mas nao tem elegibilidade real para o
        que foi descrito. O frontend so mostra os cards depois desta etapa.

        Modo local (desktop) apenas: o proprio backend roda a busca (get_model()) e
        chama o Ollama, ja devolve o resultado filtrado, como sempre. Modo hospedado
        usa POST /api/editais/buscar/refinar (resultados ja vem do POST /api/editais/
        buscar, calculado com o vetor do navegador)."""
        if MODO_HOSPEDADO:
            return {"erro": "modo hospedado: use POST /api/editais/buscar/refinar com os resultados ja calculados"}
        try:
            r = buscar_editais_por_projeto(q)
            refino = refinar_editais(q, r["resultados"])
            return {
                "hospedado": False,
                "resultados": refino["resultados"],
                "refinado": refino["refinado"],
                "n_removidos": refino["n_removidos"],
                "n_originais": refino["n_originais"],
            }
        except Exception as e:
            logger.exception("refinamento indisponivel")
            return {"erro": f"refinamento indisponivel no momento: {e}"}

    @app.post("/api/editais/buscar/refinar")
    def editais_buscar_refinar_com_vetor(body: dict):
        """Modo hospedado: recebe {q, resultados} (resultados = o que veio de POST
        /api/editais/buscar) e devolve so o PROMPT -- nao ha Ollama no servidor, quem
        gera e o navegador de quem esta usando (ver local-ai.js), que tambem faz a
        filtragem do JSON de resposta (aplicarRefinoLocal, ver common.js)."""
        q = (body or {}).get("q", "")
        resultados = (body or {}).get("resultados", [])
        try:
            prep = montar_prompt_refino(q, resultados)
            return {
                "hospedado": True,
                "resultados_sem_filtro": resultados,
                "prompt": prep["prompt"],
                "modelo": prep["modelo"],
                "opcoes": prep["opcoes"],
                "candidatos_ids": prep["candidatos_ids"],
            }
        except Exception as e:
            logger.exception("refinamento indisponivel")
            return {"erro": f"refinamento indisponivel no momento: {e}"}

    @app.get("/api/editais/buscar/leitura")
    def editais_buscar_leitura(q: str = Query(..., min_length=3), ids: str = None):
        """Gera a leitura em texto a partir de uma lista de editais ja refinada (ids
        vem do resultado de /buscar/refinar) -- evita rodar o refino de novo so para
        montar o texto. Mesma logica local x hospedado do /buscar/refinar acima.

        Em modo hospedado, 'ids' e sempre informado pelo navegador (a lista ja
        refinada) -- o fallback abaixo (buscar_editais_por_projeto(q), que chamaria
        get_model()) so roda em modo local, quando 'ids' nao vem."""
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
            elif MODO_HOSPEDADO:
                return {"erro": "modo hospedado: informe 'ids' (resultados ja calculados no navegador)"}
            else:
                resultados = buscar_editais_por_projeto(q)["resultados"]

            if MODO_HOSPEDADO:
                prep = montar_prompt_leitura(q, resultados)
                return {"hospedado": True, "prompt": prep.get("prompt"), "modelo": prep.get("modelo"),
                        "opcoes": prep.get("opcoes"), "fallback": prep.get("fallback")}
            leitura = gerar_leitura_elegibilidade(q, resultados)
            return {"hospedado": False, "leitura": leitura}
        except Exception as e:
            logger.exception("leitura indisponivel")
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
                    "fallback": prep["fallback"], "prefixo": prep.get("prefixo", ""),
                }
            return resumir_edital(edital_id, forcar=forcar)
        except Exception as e:
            logger.exception("resumo indisponivel")
            return {"erro": f"resumo indisponivel no momento: {e}"}

    @app.post("/api/editais/{edital_id}/resumo")
    def edital_resumo_salvar(edital_id: int, body: dict):
        """So usada no modo hospedado -- o navegador de quem gerou o resumo via
        Ollama local manda o texto aqui pra virar cache compartilhado."""
        try:
            resumo_texto = (body or {}).get("resumo", "")
            return salvar_resumo(edital_id, resumo_texto)
        except Exception as e:
            logger.exception("falha ao salvar resumo")
            return {"erro": f"nao foi possivel salvar o resumo: {e}"}
except ImportError as e:
    @app.get("/api/editais/buscar")
    def editais_buscar_indisponivel(q: str = ""):
        return {"erro": f"motor de busca de editais ainda nao configurado: {e}"}

    @app.post("/api/editais/buscar")
    def editais_buscar_indisponivel_post(body: dict = None):
        return {"erro": f"motor de busca de editais ainda nao configurado: {e}"}

    @app.get("/api/editais/buscar/refinar")
    def editais_buscar_refinar_indisponivel(q: str = ""):
        return {"erro": f"motor de busca de editais ainda nao configurado: {e}"}

    @app.post("/api/editais/buscar/refinar")
    def editais_buscar_refinar_indisponivel_post(body: dict = None):
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


# ============ Elegibilidade ("Minha Empresa"): o visitante digita o CNPJ da PROPRIA
# empresa e o sistema resolve setor/porte (BrasilAPI, consulta ao vivo -- ver
# elegibilidade.py) para cruzar com editais abertos e o historico de operacoes por
# setor. Rota unica, sem split local/hospedado: so SQL simples + 1 chamada HTTP
# externa, nada de embeddings/Ollama aqui. ============

def _editais_elegiveis_para_setor(conn, limit: int = 20) -> dict:
    """Mesmo filtro/ordenacao de '/api/editais?situacao=aberta&aplicavel_empresa=1'
    (ver _editais_where acima): aberto de verdade (respeita prazo vencido mesmo que a
    FINEP ainda marque como 'aberta') e com publico-alvo que inclui empresas. NAO
    filtra por regiao: na base atual, 100% dos editais abertos aplicaveis a empresas
    tem regiao='Todo Brasil' (conferido em produção), entao um filtro estrito so
    esconderia oportunidades sem ganho nenhum -- fica so como possível refinamento
    futuro se a FINEP passar a publicar editais regionais de novo."""
    where, params = _editais_where(situacao="aberta", aplicavel_empresa=1)
    cur = conn.cursor()
    total = cur.execute(f"SELECT COUNT(*) FROM editais_raw {where}", params).fetchone()[0]
    rows = cur.execute(
        f"SELECT {', '.join(EDITAIS_COLS)} FROM editais_raw {where} "
        f"ORDER BY prazo_proposto ASC NULLS LAST LIMIT ?",
        params + [limit],
    ).fetchall()
    return {"total": total, "resultados": [_edital_row_to_dict(r) for r in rows]}


def _operacoes_parecidas(conn, setor_bndes: str, porte_bndes: str = None, n_exemplos: int = 5) -> dict:
    """Agregados de operations por setor (e por porte, quando resolvivel -- ver
    porte_bndes_equivalente em elegibilidade.py) para responder 'empresas parecidas
    com a minha ja pegaram credito?'. Se filtrar por porte nao achar nada, refaz so por
    setor -- silenciosamente cai pro filtro mais largo em vez de devolver zero
    resultados por causa de um porte que a Receita informou de um jeito que o BNDES
    classifica diferente."""
    cur = conn.cursor()

    def _consulta(incluir_porte: bool):
        where = "WHERE setor_bndes = ?"
        params = [setor_bndes]
        if incluir_porte and porte_bndes:
            where += " AND porte_cliente = ?"
            params.append(porte_bndes)
        total_row = cur.execute(
            f"SELECT COUNT(*), SUM(valor_contratado), AVG(valor_contratado) FROM operations {where}", params
        ).fetchone()
        por_agencia = cur.execute(
            f"SELECT agencia, COUNT(*), SUM(valor_contratado), AVG(valor_contratado) FROM operations {where} GROUP BY agencia",
            params,
        ).fetchall()
        exemplos = cur.execute(
            f"SELECT cliente, agencia, uf, valor_contratado, data_contratacao FROM operations {where} "
            f"ORDER BY valor_contratado DESC LIMIT ?",
            params + [n_exemplos],
        ).fetchall()
        # "Linhas enquadraveis": diferente dos editais (chamada publica, com prazo),
        # produto e a LINHA DE CREDITO PERMANENTE do BNDES/FINEP (ex: "BNDES FINEM",
        # "BNDES FINAME", "Credito Direto (FINEP)") -- sem data de validade, sempre
        # aberta pra quem se enquadrar. Rankeada por frequencia de uso por empresas do
        # MESMO setor/porte: e a resposta pra "alem do que ja foi financiado, que linha
        # eu poderia tentar mesmo sem um edital ativo agora?".
        linhas = cur.execute(
            f"SELECT produto, COUNT(*), AVG(valor_contratado) FROM operations {where} "
            f"AND produto IS NOT NULL AND produto != '' GROUP BY produto ORDER BY COUNT(*) DESC LIMIT 10",
            params,
        ).fetchall()
        return total_row, por_agencia, exemplos, linhas

    porte_considerado = bool(porte_bndes)
    total_row, por_agencia, exemplos, linhas = _consulta(incluir_porte=True)
    if porte_considerado and (total_row[0] or 0) == 0:
        porte_considerado = False
        total_row, por_agencia, exemplos, linhas = _consulta(incluir_porte=False)

    return {
        "total": total_row[0] or 0,
        "valor_total": total_row[1] or 0,
        "valor_medio": total_row[2] or 0,
        "porte_considerado_no_filtro": porte_considerado,
        "por_agencia": [
            {"agencia": r[0], "n_operacoes": r[1], "valor_total": r[2] or 0, "valor_medio": r[3] or 0}
            for r in por_agencia
        ],
        "exemplos": [
            {"cliente": r[0], "agencia": r[1], "uf": r[2], "valor_contratado": r[3], "data_contratacao": r[4]}
            for r in exemplos
        ],
        "linhas_enquadraveis": [
            {"produto": r[0], "n_operacoes": r[1], "valor_medio": r[2] or 0} for r in linhas
        ],
    }


@app.get("/api/elegibilidade")
def elegibilidade(cnpj: str = Query(...)):
    # Sem min_length aqui de proposito: um CNPJ mal formatado deve virar a mensagem
    # amigavel de resolver_empresa() (erro esperado, texto em portugues claro), nao o
    # 422 padrao do FastAPI (JSON tecnico em ingles que a pagina nao trata e o dono da
    # empresa nao entenderia).
    from elegibilidade import mapear_setor, porte_bndes_equivalente, resolver_empresa

    empresa = resolver_empresa(cnpj)
    if empresa.get("erro"):
        # CNPJ invalido / nao encontrado / API externa fora do ar sao desfechos
        # esperados desta consulta, nao bugs -- nao logar como excecao (ver
        # comentario no topo do arquivo sobre logger.exception).
        return {"erro": empresa["erro"]}

    conn = get_connection()
    try:
        setor_mapeado = mapear_setor(conn, empresa.get("cnae_codigo"))
        porte_bndes = porte_bndes_equivalente(empresa.get("porte_receita"))
        setor_mapeado["porte_bndes_equivalente"] = porte_bndes

        editais = {"total": 0, "resultados": []}
        operacoes_parecidas = {
            "total": 0, "valor_total": 0, "valor_medio": 0,
            "porte_considerado_no_filtro": False, "por_agencia": [], "exemplos": [],
            "linhas_enquadraveis": [],
        }
        if setor_mapeado["mapeado"]:
            editais = _editais_elegiveis_para_setor(conn)
            operacoes_parecidas = _operacoes_parecidas(conn, setor_mapeado["setor_bndes"], porte_bndes)
        else:
            # setor nao mapeado: ainda mostramos editais abertos p/ empresas em geral
            # (nao dependem de setor), so os agregados de operacoes ficam vazios (nao
            # ha setor_bndes pra filtrar operations de forma minimamente confiavel).
            editais = _editais_elegiveis_para_setor(conn)

        return {
            "empresa": empresa,
            "setor_mapeado": setor_mapeado,
            "editais": editais,
            "operacoes_parecidas": operacoes_parecidas,
        }
    except Exception as e:
        logger.exception("elegibilidade indisponivel")
        return {"erro": f"Não foi possível concluir a análise agora ({e}). Tente novamente em instantes."}
    finally:
        conn.close()


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
