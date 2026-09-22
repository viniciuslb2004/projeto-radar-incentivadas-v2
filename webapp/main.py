"""API FastAPI do Radar de Credito Incentivado (BNDES + FINEP)."""
import datetime
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from db import get_connection
from search_fts import PORTE_NORMALIZADO_SQL
from webapp.detalhe import montar_detalhe_amigavel
from webapp.admin.auth import (
    SESSION_COOKIE,
    criar_sessao,
    definir_cookie_sessao,
    encerrar_sessao,
    limpar_cookie_sessao,
    registrar_acesso,
    validar_sessao_token,
    verificar_acesso_principal,
)

# As rotas de IA/busca (abaixo) capturam Exception generico e devolvem {"erro": ...}
# de proposito -- uma falha de IA nao deve derrubar a pagina inteira pro usuario.
# Mas sem logar em algum lugar, um bug de verdade (KeyError, etc) fica indistinguivel
# de "IA indisponivel no momento" tanto pra quem chamou quanto nos logs do Render --
# logger.exception() abaixo manda o traceback completo pro stdout/stderr do processo
# (que o Render ja captura), sem mudar a resposta HTTP que o cliente recebe.
logger = logging.getLogger("radar")

# ============ Motor de busca (item 4/5 do pedido de melhorias) ============
# Por padrao a busca online e SEM IA (full-text/trigram, ver src/search_fts.py) --
# nenhuma chamada a modelo/embeddings acontece no caminho padrao de producao. O
# motor por IA (embeddings, ver src/search.py e src/embeddings.py) continua
# intacto e religavel: virar MOTOR_BUSCA_IA=1 (variavel de ambiente) volta o
# comportamento anterior (rotas /api/busca/preparar*, calculo de vetor no
# navegador via embeddings-client.js) sem precisar mudar nenhuma linha de codigo.
MOTOR_BUSCA_IA = os.environ.get("MOTOR_BUSCA_IA", "0") == "1"

# ============ Acesso (so ativo quando ha pelo menos uma conta cadastrada) ============
# HISTORICO: HTTP Basic (SITE_PASSWORD) -> contas individuais com login+senha
# (`admin_usuarios`) -> (2026-09-22) IDENTIFICACAO PASSWORDLESS por e-mail, unica
# forma de acesso ao site principal hoje (reposicionamento pra plataforma publica
# de geracao de leads -- ver CLAUDE.md/docs/painel-admin.md). O painel `/admin`
# (uso interno da Artica) CONTINUA exigindo usuario+senha normalmente -- essa
# mudanca e' so pro site principal (ver webapp/admin/auth.py, inalterado).
# Sessao por cookie opaco (`admin_session`, COMPARTILHADO com o painel /admin --
# mesma tabela de contas/mesmo mecanismo de sessao, so sem verificar senha pro
# site). O app local sem nenhuma conta cadastrada (banco novo, seed.py nunca
# rodado) continua rodando sem exigir identificacao, mesmo espirito de antes sem
# SITE_PASSWORD. O HTML/CSS/JS estatico e publico de proposito -- so as rotas
# /api/* exigem; a propria pagina carrega uma landing/tela de identificacao
# customizada (ver #landing-overlay em index.html, common.js) que faz POST
# /api/identificar (e, se precisar de mais dados, POST /api/cadastrar) -- cookie
# de sessao devolvido nos dois casos, NUNCA senha em nenhum ponto deste fluxo.
_ROTAS_PUBLICAS_API = {"/api/identificar", "/api/cadastrar", "/api/logout"}


def _verificar_acesso(request: Request):
    if not request.url.path.startswith("/api/") or request.url.path in _ROTAS_PUBLICAS_API:
        return
    verificar_acesso_principal(request)


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

# Painel de admin (/admin) -- pacote isolado e auto-contido, ver webapp/admin/routes.py
# (comentario no topo) para o que fazer se este painel for descontinuado um dia.
from webapp.admin.routes import router as admin_router  # noqa: E402
app.include_router(admin_router, prefix="/admin")

# Potenciais Linhas (item 3 do pedido) -- pacote isolado, mesmo espirito de
# webapp/admin/: so consulta linhas_incentivadas/operations ja existentes (nenhuma
# tabela nova), sem logica propria fora deste arquivo. Prefixo comeca com "/api/",
# entao ja cai automaticamente sob o gate de _verificar_acesso acima (mesma
# protecao de /api/operacoes, /api/linhas etc.).
from webapp.potenciais import router as potenciais_router  # noqa: E402
app.include_router(potenciais_router, prefix="/api/potenciais")


def _ip_do_request(request: Request) -> str:
    return request.headers.get("x-forwarded-for", request.client.host if request.client else None)


def _usuario_logado(request: Request):
    """Username da sessao atual (site principal OU admin, mesma tabela/cookie), ou
    None se ninguem estiver logado -- usado so pra atribuir autoria (ex: correcao
    manual), nunca pra controle de acesso (isso e' _verificar_acesso, acima)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    conn = get_connection(pooled=True)
    try:
        usuario = validar_sessao_token(conn, token)
    finally:
        conn.close()
    return usuario["username"] if usuario else None


def _usuario_atual(request: Request):
    """{'id','username','role'} da sessao atual, ou None -- usado pra log de
    navegacao por aba (ver registrar_navegacao abaixo). Dependency OPCIONAL (nunca
    levanta 401 sozinha)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    conn = get_connection(pooled=True)
    try:
        return validar_sessao_token(conn, token)
    finally:
        conn.close()


@app.post("/api/eventos/navegacao")
def registrar_navegacao(payload: dict, request: Request):
    """V2 do log de acessos (pedido explicito do usuario, ver CLAUDE.md secao
    'Painel de Admin') -- grava qual ABA um usuario LOGADO visitou, reaproveitando
    admin_acessos_log (evento='view_aba', `detalhe`=nome da aba) em vez de criar
    tabela nova. Best-effort: nunca bloqueia a navegacao (front so chama isso
    quando ja sabe que ha alguem logado, ver common.js::_ativarView, e ignora
    qualquer erro daqui silenciosamente)."""
    usuario = _usuario_atual(request)
    if usuario is None:
        return {"ok": True}
    aba = (payload.get("aba") or "").strip()
    if not aba:
        return {"ok": True}
    conn = get_connection(pooled=True)
    try:
        registrar_acesso(conn, usuario["id"], usuario["username"], "site", "view_aba", _ip_do_request(request), detalhe=aba)
    except Exception:
        logger.exception("falha ao gravar evento de navegacao")
    finally:
        conn.close()
    return {"ok": True}


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


# "Ja usado nos ultimos 3 meses" (pedido do usuario) -- aproximado em dias, mesmo
# espirito de outras janelas ja usadas neste projeto (ex: SESSION_TTL_HORAS).
JANELA_RENOVACAO_DIAS = 90


@app.post("/api/identificar")
def site_identificar(payload: dict, request: Request, response: Response):
    """1o passo do fluxo de identificacao PASSWORDLESS do site principal (substitui
    login+senha -- ver CLAUDE.md/docs/painel-admin.md, e docs/archive/removed-
    features.md secao 4 pro fluxo antigo de cadastro com aprovacao que isso
    substituiu). So pede e-mail: se ja usado pra logar nos ultimos
    JANELA_RENOVACAO_DIAS dias, renova o acesso NA HORA (cria sessao, registra um
    evento 'login' novo) sem pedir mais nada; senao (e-mail novo OU ultimo acesso
    mais antigo que a janela), devolve precisa_dados=True pro frontend mostrar o
    formulario completo (POST /api/cadastrar abaixo)."""
    email = (payload.get("email") or "").strip().lower()
    if not _email_valido(email):
        raise HTTPException(status_code=400, detail="Informe um e-mail válido.")
    conn = get_connection(pooled=True)
    try:
        row = conn.execute(
            "SELECT id, ativo FROM admin_usuarios WHERE lower(email) = ?", (email,)
        ).fetchone()
        if row is None:
            return {"ok": True, "precisa_dados": True}
        usuario_id, ativo = row
        if not ativo:
            raise HTTPException(status_code=403, detail="Este acesso foi desativado. Entre em contato com a Ártica.")
        limite = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=JANELA_RENOVACAO_DIAS)
        ).isoformat()
        ultimo_login = conn.execute(
            "SELECT MAX(criado_em) FROM admin_acessos_log WHERE usuario_id = ? AND evento = 'login'",
            (usuario_id,),
        ).fetchone()[0]
        if ultimo_login is None or ultimo_login < limite:
            return {"ok": True, "precisa_dados": True}
        # E-mail usado recentemente -- "Voce ja esta cadastrado", acesso imediato,
        # sem pedir mais nada (renova/atualiza o acesso: novo evento de login).
        token = criar_sessao(conn, usuario_id)
        registrar_acesso(conn, usuario_id, email, "site", "login", _ip_do_request(request))
    finally:
        conn.close()
    definir_cookie_sessao(response, token)
    return {"ok": True, "precisa_dados": False}


@app.post("/api/cadastrar")
def site_cadastrar(payload: dict, request: Request, response: Response):
    """2o passo (e-mail novo OU ultimo acesso ha mais de JANELA_RENOVACAO_DIAS dias)
    -- pede nome/empresa/cargo/e-mail e concede acesso IMEDIATO, sem nenhuma
    aprovacao de admin (substitui o antigo cadastro publico com aprovacao -- ver
    docs/archive/removed-features.md secao 4). Upsert por e-mail (nunca cria uma
    segunda conta pro mesmo e-mail). Sem senha em NENHUM caso -- password_hash fica
    com string vazia (sentinela; verificar_senha() sempre devolve False pra esse
    formato, entao essa conta nunca autentica por senha por engano em nenhum outro
    fluxo, ex: /admin/api/login)."""
    email = (payload.get("email") or "").strip().lower()
    nome = (payload.get("nome") or "").strip()
    empresa = (payload.get("empresa") or "").strip()
    cargo = (payload.get("cargo") or "").strip()
    if not _email_valido(email):
        raise HTTPException(status_code=400, detail="Informe um e-mail válido.")
    if not nome or not empresa or not cargo:
        raise HTTPException(status_code=400, detail="Nome, empresa e cargo são obrigatórios.")

    conn = get_connection(pooled=True)
    try:
        existente = conn.execute(
            "SELECT id, ativo FROM admin_usuarios WHERE lower(email) = ?", (email,)
        ).fetchone()
        if existente:
            usuario_id, ativo = existente
            if not ativo:
                raise HTTPException(status_code=403, detail="Este acesso foi desativado. Entre em contato com a Ártica.")
            conn.execute(
                "UPDATE admin_usuarios SET nome = ?, empresa = ?, cargo = ? WHERE id = ?",
                (nome, empresa, cargo, usuario_id),
            )
        else:
            # username e' UNIQUE NOT NULL (schema antigo, ver seed.py) -- usa o
            # proprio e-mail como username (funcionalmente unico o suficiente);
            # o loop cobre so o caso improvavel de colisao (ex: mesmo e-mail com
            # capitalizacao diferente ja usado como username por uma conta antiga).
            username = email
            sufixo = 1
            while conn.execute("SELECT 1 FROM admin_usuarios WHERE username = ?", (username,)).fetchone():
                sufixo += 1
                username = f"{email}+{sufixo}"
            conn.execute(
                "INSERT INTO admin_usuarios "
                "(username, email, nome, empresa, cargo, password_hash, role, status, ativo, criado_em) "
                "VALUES (?, ?, ?, ?, ?, '', 'usuario', 'aprovado', TRUE, ?)",
                (username, email, nome, empresa, cargo, datetime.datetime.now(datetime.timezone.utc).isoformat()),
            )
            usuario_id = conn.execute("SELECT id FROM admin_usuarios WHERE username = ?", (username,)).fetchone()[0]
        token = criar_sessao(conn, usuario_id)
        registrar_acesso(conn, usuario_id, email, "site", "login", _ip_do_request(request))
        conn.commit()
    finally:
        conn.close()
    definir_cookie_sessao(response, token)
    return {"ok": True}


@app.post("/api/interesse")
def site_interesse(request: Request):
    """'Quero saber mais' (substitui usuario logado+Sair na topbar, ver CLAUDE.md) --
    registra um lead IMEDIATAMENTE (evento='interesse_lead' em admin_acessos_log,
    mesmo padrao ja usado por 'view_aba') usando os dados que a pessoa ja informou
    na identificacao -- sem formulario adicional. Rota protegida (fora de
    _ROTAS_PUBLICAS_API, entao _verificar_acesso/verificar_acesso_principal ja
    garante sessao valida antes de chegar aqui)."""
    usuario = _usuario_atual(request)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Sessão inválida")
    conn = get_connection(pooled=True)
    try:
        registrar_acesso(conn, usuario["id"], usuario["username"], "site", "interesse_lead", _ip_do_request(request))
    finally:
        conn.close()
    return {"ok": True}


@app.get("/api/me")
def site_me(request: Request):
    """Quem esta identificado no site principal AGORA (ou None, se nao houver
    sessao) -- usado pra mostrar o botao "Quero saber mais" na topbar (ver
    common.js), nunca pra controle de acesso."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return {"username": None, "nome": None}
    conn = get_connection(pooled=True)
    try:
        usuario = validar_sessao_token(conn, token)
        nome = None
        if usuario is not None:
            row = conn.execute("SELECT nome FROM admin_usuarios WHERE id = ?", (usuario["id"],)).fetchone()
            nome = row[0] if row else None
    finally:
        conn.close()
    return {"username": usuario["username"] if usuario else None, "nome": nome}


@app.post("/api/logout")
def site_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        conn = get_connection(pooled=True)
        try:
            usuario = validar_sessao_token(conn, token)
            if usuario is not None:
                registrar_acesso(conn, usuario["id"], usuario["username"], "site", "logout", _ip_do_request(request))
            encerrar_sessao(conn, token)
        finally:
            conn.close()
    limpar_cookie_sessao(response)
    return {"ok": True}


@app.on_event("startup")
def _warmup_busca():
    """Carrega os vetores de embeddings precalculados (.npz) no startup do servidor,
    nao na primeira busca do usuario (sem isso, a primeira busca de cada reinicio
    parecia travada). NUNCA chama get_model() aqui -- carregar o sentence-transformers
    no processo do servidor web e um custo que so vale a pena pago sob demanda (rota
    GET local mais abaixo), nao a cada boot do processo (ver DEPLOY.md)."""
    try:
        from search import warmup_hospedado

        warmup_hospedado()
        print("Motor de busca pronto (vetores do corpus carregados).")
    except Exception as e:
        print(f"Aviso: motor de busca nao pode ser pre-carregado ({e}).")


def _filters_clause(
    agencia=None, setor=None, uf=None, data_inicio=None, data_fim=None, instrumento=None,
    subsetor=None, segmento=None, porte=None, valor_min=None, valor_max=None, produto=None,
):
    # Defesa contra intervalo invertido (data_inicio > data_fim): o frontend ja impede
    # o usuario de chegar nesse estado (ver validarIntervaloDatas em common.js), mas
    # uma chamada direta a API, um link salvo antigo, ou o botao "voltar" do navegador
    # ainda poderiam mandar os dois trocados -- em vez de devolver silenciosamente uma
    # lista vazia (comparacao textual data_contratacao >= inicio AND < fim nunca bate
    # se inicio > fim), so troca os dois, aplicando a mesma correcao em TODAS as ~12
    # rotas que usam este filtro de uma vez so.
    if data_inicio and data_fim and data_inicio > data_fim:
        data_inicio, data_fim = data_fim, data_inicio

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
    # porte/valor_min/valor_max/produto: filtros novos (2026-09-22, "Potenciais
    # Linhas" -- ver webapp/potenciais.py/"Transações Semelhantes"), adicionados no
    # FINAL da assinatura pra nao quebrar nenhuma das chamadas posicionais ja
    # existentes acima. porte usa a MESMA normalizacao canonica (4 categorias) ja
    # usada pelo filtro de porte da Busca (ver PORTE_NORMALIZADO_SQL, importado de
    # search_fts.py).
    if porte and porte != "Todos":
        clauses.append(f"({PORTE_NORMALIZADO_SQL}) = ?")
        params.append(porte)
    if valor_min is not None:
        clauses.append("valor_contratado >= ?")
        params.append(valor_min)
    if valor_max is not None:
        clauses.append("valor_contratado <= ?")
        params.append(valor_max)
    if produto and produto != "Todos":
        clauses.append("produto = ?")
        params.append(produto)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _parse_date(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s[:10])


JANELA_TENDENCIA_MAX_DIAS = 365


def _periodo_anterior(data_inicio: str, data_fim: str, conn):
    """Dado um periodo [data_inicio, data_fim), devolve (periodo atual, periodo anterior) para
    comparacao de tendencia. O periodo anterior e SEMPRE o intervalo imediatamente anterior, do
    MESMO TAMANHO EXATO do periodo atual -- ex: filtro Ago/22 a Ago/24 (2 anos) compara contra
    Ago/20 a Ago/22 (2 anos), nunca contra so os ultimos 12 meses do filtro. BUG REAL corrigido
    aqui: uma versao anterior desta funcao limitava o periodo atual a no maximo 365 dias
    incondicionalmente -- um filtro de 2 anos escolhido pelo usuario virava, por baixo dos
    panos, uma comparacao dos ultimos 12 meses contra os 12 anteriores a esses, sem o
    frontend nem o usuario saberem que o "periodo atual" exibido nao era o filtro de verdade.
    Esse teto de JANELA_TENDENCIA_MAX_DIAS agora so vale para o caso SEM NENHUM filtro (o
    padrao "toda a base", 2002-hoje, onde comparar o historico inteiro contra decadas sem
    dado nenhum nao faria sentido) -- uma vez que o usuario escolhe datas explicitas, elas sao
    respeitadas exatamente, seja qual for o tamanho. Quando o recorte anterior calculado cai
    INTEIRAMENTE antes do inicio historico da base (sem dado algum), quem chama
    (_ranking_variacao) suprime a indicacao de alta/queda em vez de mostrar uma variacao
    fabricada contra "nada"."""
    cur = conn.cursor()
    if data_inicio and data_fim and data_inicio > data_fim:
        data_inicio, data_fim = data_fim, data_inicio
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
        # Filtro degenerado (inicio == fim) -- sem um tamanho de periodo real pra replicar
        # pra tras, cai no mesmo padrao do caso "sem filtro".
        delta = datetime.timedelta(days=JANELA_TENDENCIA_MAX_DIAS)

    anterior_fim = inicio_selecionado
    anterior_inicio = inicio_selecionado - delta
    return data_inicio, data_fim, anterior_inicio.isoformat(), anterior_fim.isoformat()


@app.get("/api/status")
def status():
    conn = get_connection(pooled=True)
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
            # Sempre True: o app so tem um modo agora (banco Postgres compartilhado,
            # sem SQLite local). Mantido por compatibilidade com o frontend (ver
            # webapp/static/js/common.js), que ainda le este campo para decidir se
            # calcula o embedding da busca no navegador (transformers.js) ou pede
            # pro servidor calcular -- so o primeiro caminho continua existindo.
            "hospedado": True,
            # Ver MOTOR_BUSCA_IA acima -- o frontend (busca.js) le este campo pra
            # decidir entre o caminho sem IA (uma chamada, sem vetor) e o caminho
            # antigo por embeddings (preparar -> calcular vetor no navegador -> postar).
            "busca_ia_ativa": MOTOR_BUSCA_IA,
        }
    finally:
        conn.close()


@app.get("/api/filtros")
def filtros():
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()

        def col_values(col):
            return [r[0] for r in cur.execute(f"SELECT DISTINCT {col} FROM operations WHERE {col} IS NOT NULL ORDER BY {col}").fetchall()]

        # Portes: categorias CANONICAS (ver PORTE_NORMALIZADO_SQL), nao os 7 valores
        # crus de porte_cliente -- ordem de tamanho fixa (nao alfabetica), "Não
        # informado" so aparece se alguma operacao realmente cair nela.
        portes_presentes = {
            r[0] for r in cur.execute(f"SELECT DISTINCT ({PORTE_NORMALIZADO_SQL}) FROM operations").fetchall()
        }
        portes = [p for p in ("MICRO", "PEQUENA", "MÉDIA", "GRANDE", "Não informado") if p in portes_presentes]

        min_max = cur.execute("SELECT MIN(data_contratacao), MAX(data_contratacao) FROM operations").fetchone()
        return {
            "agencias": col_values("agencia"),
            "setores": col_values("setor_bndes"),
            "subsetores": col_values("subsetor_bndes"),
            "ufs": col_values("uf"),
            "instrumentos": col_values("instrumento"),
            "produtos": col_values("produto"),
            "portes": portes,
            "anos": col_values("ano"),
            "data_min": min_max[0],
            "data_max": min_max[1],
        }
    finally:
        conn.close()


@app.get("/api/kpis")
def kpis(agencia: str = None, setor: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None, instrumento: str = None):
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim, instrumento)
    conn = get_connection(pooled=True)
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


GRANULARIDADES_SERIE = {
    # "periodo" e um numero por ano que identifica o recorte (trimestre 1-4,
    # semestre 1-2, sempre 1 para anual) -- trimestral usa a coluna `trimestre` ja
    # persistida (identico ao comportamento de sempre); mensal precisa extrair o mes
    # de `data_contratacao` (TEXT ISO "AAAA-MM-DD") porque a tabela nao guarda mes
    # separado, so ano/trimestre (ver src/unify.py::_add_periodo).
    "mensal": "CAST(SUBSTRING(data_contratacao FROM 6 FOR 2) AS INTEGER)",
    "trimestral": "trimestre",
    "semestral": "CASE WHEN trimestre <= 2 THEN 1 ELSE 2 END",
    "anual": "1",
}


@app.get("/api/serie_temporal")
def serie_temporal(
    agencia: str = None, setor: str = None, uf: str = None, data_inicio: str = None,
    data_fim: str = None, instrumento: str = None, granularidade: str = "trimestral",
):
    if granularidade not in GRANULARIDADES_SERIE:
        granularidade = "trimestral"
    periodo_expr = GRANULARIDADES_SERIE[granularidade]
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim, instrumento)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT ano, {periodo_expr} AS periodo, agencia, COUNT(*), SUM(valor_contratado)
            FROM operations {where}
            {"AND" if where else "WHERE"} ano IS NOT NULL
            GROUP BY ano, periodo, agencia
            ORDER BY ano, periodo
            """,
            params,
        ).fetchall()
        return [
            {"ano": r[0], "periodo": r[1], "agencia": r[2], "n_operacoes": r[3], "valor_total": r[4] or 0}
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/api/setores")
def setores(agencia: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None, instrumento: str = None):
    where, params = _filters_clause(agencia, None, uf, data_inicio, data_fim, instrumento)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(setor_bndes, 'Não classificado'), COUNT(*), SUM(valor_contratado), AVG(valor_contratado)
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
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(subsetor_bndes, 'Não classificado'), COUNT(*), SUM(valor_contratado), AVG(valor_contratado)
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
    limit = max(1, min(limit, 500))
    where, params = _filters_clause(agencia, setor, uf, data_inicio, data_fim, instrumento, subsetor)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT COALESCE(segmento, 'Não classificado'), COUNT(*), SUM(valor_contratado), AVG(valor_contratado)
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
    conn = get_connection(pooled=True)
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
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT ({PORTE_NORMALIZADO_SQL}) AS porte_normalizado, COUNT(*), SUM(valor_contratado)
            FROM operations {where}
            GROUP BY porte_normalizado
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
            f"SELECT COALESCE({group_col}, 'Não classificado'), SUM(valor_contratado), COUNT(*) "
            f"FROM operations {where} GROUP BY {group_col}",
            params_base + [d_ini, d_fim],
        ).fetchall()
        total = sum(r[1] or 0 for r in rows)
        return {r[0]: {"valor": r[1] or 0, "n": r[2], "part": (r[1] or 0) / total if total else 0} for r in rows}, total

    atual, total_atual = valor_por_grupo(data_inicio, data_fim)
    anterior, total_anterior = valor_por_grupo(ant_inicio, ant_fim)

    # Sem NENHUM dado no periodo anterior inteiro (ex: a janela cai antes do inicio
    # historico da base) -- nao ha nada de verdade para comparar. Devolver
    # variacao_pp=0 pareceria "sem mudanca" e devolver a participacao_atual crua
    # pareceria uma alta fabricada de 100pp; nenhum dos dois e uma comparacao real,
    # entao a variacao fica None e quem consome (frontend) remove a indicacao de
    # alta/queda por completo, em vez de mostrar uma variacao enganosa.
    # BUG REAL corrigido (2026-09-10): essa guarda so cobria o periodo anterior cair
    # INTEIRO antes do inicio da base (total_anterior=0) -- faltava o caso dele cair
    # SO PARCIALMENTE antes (ex: anterior=1997-2011, base comeca em 2002): ai
    # total_anterior fica positivo (tem dado real de 2002-2011), a guarda liberava a
    # comparacao, mas o total ficava artificialmente baixo por faltar ~5 anos que a
    # base nunca poderia ter tido -- a variacao percentual saia enganosa (parecia
    # queda/alta de negocio, era so cobertura temporal incompleta). Corrigido
    # exigindo tambem que o periodo anterior INTEIRO esteja dentro da cobertura real
    # da base (ant_inicio >= MIN(data_contratacao)), nao so que tenha algum dado.
    min_data_base = cur.execute("SELECT MIN(data_contratacao) FROM operations").fetchone()[0]
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


@app.get("/api/tendencias/setores")
def tendencias_setores(agencia: str = None, uf: str = None, instrumento: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de setores por variacao de participacao entre o periodo selecionado e o periodo anterior equivalente."""
    conn = get_connection(pooled=True)
    try:
        r = _ranking_variacao(conn, "setor_bndes", agencia, uf, instrumento, None, data_inicio, data_fim)
        return {
            "periodo_atual": [r["data_inicio"], r["data_fim"]],
            "periodo_anterior": [r["data_inicio_anterior"], r["data_fim_anterior"]],
            "comparavel": r["comparavel"],
            "setores": [{**g, "setor": g["grupo"]} for g in r["grupos"]],
        }
    finally:
        conn.close()


@app.get("/api/tendencias/subsetores")
def tendencias_subsetores(setor: str = Query(...), agencia: str = None, uf: str = None, instrumento: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de subsetores (dentro de um setor) por variacao de participacao."""
    conn = get_connection(pooled=True)
    try:
        r = _ranking_variacao(conn, "subsetor_bndes", agencia, uf, instrumento, setor, data_inicio, data_fim)
        return {
            "setor": setor,
            "periodo_atual": [r["data_inicio"], r["data_fim"]],
            "periodo_anterior": [r["data_inicio_anterior"], r["data_fim_anterior"]],
            "comparavel": r["comparavel"],
            "subsetores": [{**g, "subsetor": g["grupo"]} for g in r["grupos"]],
        }
    finally:
        conn.close()


@app.get("/api/tendencias/segmentos")
def tendencias_segmentos(setor: str = Query(...), subsetor: str = None, agencia: str = None, uf: str = None, instrumento: str = None, data_inicio: str = None, data_fim: str = None):
    """Ranking de segmentos CNAE (granularidade fina) dentro de um setor, por variacao de participacao."""
    conn = get_connection(pooled=True)
    try:
        r = _ranking_variacao(conn, "segmento", agencia, uf, instrumento, setor, data_inicio, data_fim, subsetor_pai=subsetor)
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


@app.get("/api/tendencias/produtos")
def tendencias_produtos(agencia: str = None, uf: str = None, data_inicio: str = None, data_fim: str = None):
    where, params = _filters_clause(agencia, None, uf, data_inicio, data_fim)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        # GROUP BY na propria expressao COALESCE (nao so em `produto`): Postgres, ao
        # contrario do SQLite, exige que toda coluna no SELECT que nao seja agregada
        # apareca IGUAL no GROUP BY -- agrupar so por `produto` e depois exibir
        # `instrumento` como fallback (para as linhas com produto NULO) e rejeitado
        # com "column operations.instrumento must appear in the GROUP BY clause or be
        # used in an aggregate function" (erro real, confirmado migrando para
        # Postgres). Agrupar pela propria expressao produz o mesmo agrupamento
        # pretendido (por rotulo efetivo exibido), so que de forma valida nos dois
        # bancos.
        rows = cur.execute(
            f"""
            SELECT COALESCE(produto, instrumento, 'Nao informado'), COUNT(*), SUM(valor_contratado)
            FROM operations {where}
            GROUP BY COALESCE(produto, instrumento, 'Nao informado')
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
    porte: str = None,
    valor_min: float = None,
    valor_max: float = None,
    produto: str = None,
    order_by: str = "valor",
    order_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
):
    limit = max(1, min(limit, 2000))
    offset = max(0, offset)
    where, params = _filters_clause(
        agencia, setor, uf, data_inicio, data_fim, instrumento, subsetor, segmento,
        porte, valor_min, valor_max, produto,
    )
    coluna_ordenacao = ORDENACAO_COLUNAS.get(order_by, "valor_contratado")
    direcao = "ASC" if order_dir == "asc" else "DESC"
    conn = get_connection(pooled=True)
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
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT raw_table, raw_id, agencia, instrumento, setor_bndes, cnpj FROM operations WHERE id = ?", (op_id,)
        ).fetchone()
        if not row:
            return {"erro": "operacao nao encontrada"}
        raw_table, raw_id, agencia, instrumento, setor_bndes, cnpj = row

        raw_row = cur.execute(f"SELECT * FROM {raw_table} WHERE id = ?", (raw_id,)).fetchone()
        if not raw_row:
            return {"raw_table": raw_table, "secoes": []}
        col_names = [d[0] for d in cur.description]
        raw = dict(zip(col_names, raw_row))
        secoes = montar_detalhe_amigavel(raw_table, raw)

        # Identificacao da empresa (item 3.2 do pedido) -- CNAE/razao social oficial/
        # natureza juridica/porte/capital social, ja enriquecidos localmente em
        # cnpj_cnae (ver enrich_cnae.py); so aparece quando o CNPJ ja foi resolvido.
        if cnpj:
            empresa = cur.execute(
                "SELECT razao_social_oficial, natureza_juridica, porte_empresa, capital_social, "
                "cnae_codigo, cnae_descricao FROM cnpj_cnae WHERE cnpj = ?", (cnpj,)
            ).fetchone()
            if empresa and any(v is not None for v in empresa):
                razao_oficial, natureza, porte, capital, cnae_codigo, cnae_descricao = empresa
                campos_empresa = [
                    {"label": "Razão social", "tipo": "texto", "valor": razao_oficial},
                    {"label": "Natureza jurídica", "tipo": "texto", "valor": natureza},
                    {"label": "Porte", "tipo": "texto", "valor": porte},
                    {"label": "Capital social", "tipo": "moeda", "valor": capital},
                    {"label": "CNAE principal", "tipo": "texto", "valor": f"{cnae_codigo} - {cnae_descricao}" if cnae_codigo else None},
                ]
                campos_empresa = [c for c in campos_empresa if c["valor"] not in (None, "")]
                if campos_empresa:
                    secoes = [{"titulo": "Identificação da empresa", "campos": campos_empresa}] + secoes

        return {
            "raw_table": raw_table, "agencia": agencia, "instrumento": instrumento,
            "setor_bndes": setor_bndes, "secoes": secoes,
        }
    finally:
        conn.close()


@app.get("/api/operacoes/{op_id}/grupo-economico")
def operacao_grupo_economico(op_id: int):
    """Outras operacoes que compartilham a mesma RAIZ de CNPJ (8 primeiros digitos --
    identifica a EMPRESA, matriz+filiais compartilham a raiz, so o 9o-14o digito muda
    por estabelecimento) que a operacao op_id -- cross-link simples, sem tabela/indice
    novo (o dado ja existe em operations.cnpj)."""
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT left(regexp_replace(cnpj, '\\D', '', 'g'), 8) FROM operations WHERE id = ?", (op_id,)
        ).fetchone()
        if not row or not row[0] or len(row[0]) < 8:
            return {"resultados": []}
        raiz = row[0]
        rows = cur.execute(
            "SELECT id, cliente, agencia, data_contratacao, valor_contratado FROM operations "
            "WHERE left(regexp_replace(cnpj, '\\D', '', 'g'), 8) = ? AND id != ? ORDER BY data_contratacao DESC LIMIT 20",
            (raiz, op_id),
        ).fetchall()
        cols = ["id", "cliente", "agencia", "data_contratacao", "valor_contratado"]
        return {"resultados": [dict(zip(cols, r)) for r in rows]}
    finally:
        conn.close()


if not MOTOR_BUSCA_IA:
    # ============ Motor de busca SEM IA (padrao) -- full-text/trigram Postgres, ver
    # src/search_fts.py. Uma chamada so, sem calculo de vetor em lugar nenhum
    # (navegador ou servidor) -- nunca importa search.py/embeddings.py. ============
    from search_fts import buscar_texto

    @app.get("/api/busca")
    def busca(
        q: str = Query(..., min_length=3), agencia: str = None,
        valor_minimo: float = None, regiao: str = None, produto: str = None, porte: str = None,
        setor: str = None, uf: str = None,
    ):
        try:
            return buscar_texto(
                q, agencia=agencia or None, valor_minimo=valor_minimo, regiao=regiao or None,
                produto=produto or None, porte=porte or None, setor=setor or None, uf=uf or None,
            )
        except Exception as e:
            logger.exception("motor de busca indisponivel")
            return {"erro": f"motor de busca indisponivel no momento: {e}"}

    # Rotas do modo por IA (preparar/preparar_enriquecido/termo) nao se aplicam nesse
    # modo -- devolvem um erro claro em vez de 404 caso algum cliente antigo (JS em
    # cache no navegador de alguem) ainda tente chamar.
    @app.get("/api/busca/preparar")
    def busca_preparar_indisponivel(q: str = ""):
        return {"erro": "motor de busca por IA desativado (ver MOTOR_BUSCA_IA)"}

    @app.get("/api/busca/preparar_enriquecido")
    def busca_preparar_enriquecido_indisponivel(q: str = ""):
        return {"erro": "motor de busca por IA desativado (ver MOTOR_BUSCA_IA)"}

    @app.post("/api/busca/termo")
    def busca_termo_indisponivel(body: dict = None):
        return {"erro": "motor de busca por IA desativado (ver MOTOR_BUSCA_IA)"}

else:
    try:
        from search import (
            _expandir_query,
            buscar_por_termo_com_vetor,
            buscar_rapido,
            buscar_rapido_com_vetor,
            preparar_texto_enriquecido,
        )

        # ============ Rota GET: calcula o embedding no proprio processo do servidor
        # (get_model()) -- so serve sob demanda (lazy-load do sentence-transformers na
        # primeira chamada, ver embeddings.get_model()), nunca pre-carregada no startup
        # (ver _warmup_busca acima). AMBIGUO/nao removido: o frontend (busca.js) so chama
        # esta rota quando window.MODO_HOSPEDADO e falsy, o que na pratica nunca mais
        # acontece agora que /api/status sempre devolve hospedado=True -- mas como isso
        # depende do JS (fora do escopo desta migracao), a rota fica funcional em vez de
        # ser removida (ver relatorio da migracao). ============

        @app.get("/api/busca")
        def busca(q: str = Query(..., min_length=3)):
            try:
                return buscar_rapido(q)
            except Exception as e:
                logger.exception("motor de busca indisponivel")
                return {"erro": f"motor de busca indisponivel no momento: {e}"}

        # ============ Rota usada pelo navegador: calcula o embedding no NAVEGADOR
        # (transformers.js, ver embeddings-client.js) e manda o vetor pronto -- o servidor
        # so faz numpy, nunca importa/chama sentence_transformers aqui. ============

        @app.get("/api/busca/preparar")
        def busca_preparar(q: str = Query(..., min_length=3)):
            """Devolve a query ja expandida (ex: 'fintech' -> vocabulario mais proximo do
            corpus, ver EXPANSAO_TERMOS em search.py) para o navegador gerar o vetor com o
            MESMO texto que o servidor embutiria -- sem isso o resultado nao seria
            comparavel. So string processing, sem modelo."""
            return {"query_expandida": _expandir_query(q)}

        @app.get("/api/busca/preparar_enriquecido")
        def busca_preparar_enriquecido(q: str = Query(..., min_length=3)):
            """Equivalente ao bloco de enriquecimento via web que buscar_rapido() faz
            sozinho quando o embedding roda no proprio servidor -- aqui o embedding roda
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
            """Recebe {q, vetor} com o vetor ja calculado no navegador contra o texto de
            /api/busca/preparar. So faz a matematica (numpy) contra os vetores
            precalculados do corpus -- nunca chama get_model()."""
            q = (body or {}).get("q", "")
            vetor = (body or {}).get("vetor")
            if not q or not vetor:
                return {"erro": "parametros 'q' e 'vetor' sao obrigatorios"}
            try:
                return buscar_rapido_com_vetor(q, vetor)
            except Exception as e:
                logger.exception("motor de busca indisponivel")
                return {"erro": f"motor de busca indisponivel no momento: {e}"}

        @app.post("/api/busca/termo")
        def busca_termo_com_vetor(body: dict):
            """Parte do refino -- busca operacoes por um termo correlato sugerido pela IA
            (o navegador ja calculou o vetor do termo), sem chamar get_model()."""
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

        @app.post("/api/busca/termo")
        def busca_termo_indisponivel(body: dict = None):
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
        clauses.append("situacao = ? AND (prazo_proposto IS NULL OR prazo_proposto::date >= CURRENT_DATE)")
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
    conn = get_connection(pooled=True)
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
    conn = get_connection(pooled=True)
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
    limit = max(1, min(limit, 2000))
    where, params = _editais_where(situacao, aplicavel_empresa, tema, regiao, tipo_oportunidade, tipo_cooperacao, q)
    colunas_ordenacao = {
        "prazo": "prazo_proposto",
        "publicacao": "data_publicacao",
        "titulo": "titulo",
    }
    coluna = colunas_ordenacao.get(order_by, "prazo_proposto")
    direcao = "DESC" if order_dir == "desc" else "ASC"
    conn = get_connection(pooled=True)
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
        buscar_editais_por_projeto,
        buscar_editais_por_projeto_com_vetor,
    )

    @app.on_event("startup")
    def _warmup_editais():
        """So carrega o .npz de vetores dos editais (warmup_hospedado, numpy, barato)
        -- NUNCA chama get_model() aqui (custo alto de RAM: carregar sentence-
        transformers no boot do processo so vale a pena sob demanda, ver rota GET
        abaixo, nao a cada reinicio do servidor)."""
        try:
            from editais_search import warmup_hospedado as warmup_editais_hospedado

            warmup_editais_hospedado()
            print("Motor de busca de editais pronto (vetores carregados).")
        except Exception as e:
            print(f"Aviso: motor de busca de editais nao pode ser pre-carregado ({e}).")

    # IMPORTANTE: esta rota de path fixo (/buscar) precisa ser registrada ANTES de
    # /api/editais/{edital_id} -- senao o FastAPI casa "buscar" como se fosse um
    # edital_id (rota generica registrada primeiro vence).
    #
    # AMBIGUO/nao removida (mesmo caso da rota GET /api/busca acima): calcula o
    # embedding no proprio processo do servidor (get_model(), sob demanda). O
    # frontend (editais.js) so chama esta rota quando window.MODO_HOSPEDADO e falsy,
    # o que na pratica nunca mais acontece agora que /api/status sempre devolve
    # hospedado=True -- mantida funcional em vez de removida (ver relatorio).
    @app.get("/api/editais/buscar")
    def editais_buscar(q: str = Query(..., min_length=3)):
        try:
            return buscar_editais_por_projeto(q)
        except Exception as e:
            logger.exception("busca de editais indisponivel")
            return {"erro": f"busca de editais indisponivel no momento: {e}"}

    @app.post("/api/editais/buscar")
    def editais_buscar_com_vetor(body: dict):
        """Recebe {q, vetor} com o vetor ja calculado no navegador (transformers.js,
        ver embeddings-client.js) -- so faz a matematica (numpy) contra os vetores
        precalculados dos editais abertos, nunca chama get_model()."""
        q = (body or {}).get("q", "")
        vetor = (body or {}).get("vetor")
        if not q or not vetor:
            return {"erro": "parametros 'q' e 'vetor' sao obrigatorios"}
        try:
            return buscar_editais_por_projeto_com_vetor(q, vetor)
        except Exception as e:
            logger.exception("busca de editais indisponivel")
            return {"erro": f"busca de editais indisponivel no momento: {e}"}

except ImportError as e:
    @app.get("/api/editais/buscar")
    def editais_buscar_indisponivel(q: str = ""):
        return {"erro": f"motor de busca de editais ainda nao configurado: {e}"}

    @app.post("/api/editais/buscar")
    def editais_buscar_indisponivel_post(body: dict = None):
        return {"erro": f"motor de busca de editais ainda nao configurado: {e}"}


@app.get("/api/editais/{edital_id}")
def edital_detalhe(edital_id: int):
    conn = get_connection(pooled=True)
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


# ============ Linhas Incentivadas: catalogo de linhas/programas de credito do BNDES,
# FINEP, Desenvolve SP e BNB (ver src/linhas_incentivadas.py) -- substitui a antiga aba
# "Minha Empresa"/elegibilidade (removida: cruzava CNPJ com editais via BrasilAPI ao
# vivo, escopo diferente do pedido agora). So le a tabela ja enriquecida localmente,
# nunca acessa os sites das instituicoes em tempo real. ============

LINHAS_COLS_LISTA = [
    "id", "instituicao", "nome_oficial", "nome_simplificado", "sigla", "status",
    "descricao_resumida", "setor_padronizado", "porte_padronizado", "regiao_elegivel",
    "fluxo", "modalidade", "valor_minimo", "valor_maximo", "taxa_completa", "indexador",
    "url_oficial", "data_atualizacao",
]

LINHAS_COLS_DETALHE = LINHAS_COLS_LISTA + [
    "descricao_completa", "tipo_apoio", "setores_elegiveis", "setores_nao_elegiveis",
    "faixa_receita", "destinacao", "itens_financiaveis", "itens_nao_financiaveis",
    "percentual_financiavel", "contrapartida", "spread", "prazo_total", "carencia",
    "amortizacao", "garantias", "restricoes", "criterios_elegibilidade",
    "agente_financeiro", "canal_contratacao", "prazo_inscricao", "documentos_necessarios",
    "data_vigencia", "data_captura", "trecho_fonte", "origem_dado",
    "subsetor_padronizado", "cnaes_relacionados", "tecnologias_relacionadas",
    "temas_inovacao", "temas_sustentabilidade",
]


def _linhas_where(instituicao=None, setor=None, porte=None, regiao=None, status=None, fluxo=None, q=None):
    clauses, params = [], []
    if instituicao and instituicao != "Todas":
        clauses.append("instituicao = ?")
        params.append(instituicao)
    if setor and setor != "Todos":
        clauses.append("setor_padronizado = ?")
        params.append(setor)
    if porte and porte != "Todos":
        # Filtra pelo bucket CANONICO (porte_grupo, ver src/linhas_incentivadas.py::
        # _calcular_porte_grupo), nao porte_padronizado bruto -- porte_padronizado
        # tem 42 valores de texto livre (ver docs/linhas-incentivadas.md), fragmentado
        # demais pra um filtro de UI. O parametro continua se chamando "porte" (o
        # frontend so manda um dos poucos valores de porte_grupo agora).
        clauses.append("porte_grupo = ?")
        params.append(porte)
    if regiao and regiao != "Todas":
        clauses.append("regiao_elegivel = ?")
        params.append(regiao)
    if status and status != "Todos":
        clauses.append("status = ?")
        params.append(status)
    if fluxo and fluxo != "Todos":
        clauses.append("fluxo = ?")
        params.append(fluxo)
    if q:
        clauses.append("search_vector @@ websearch_to_tsquery('portuguese', unaccent(?))")
        params.append(q)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@app.get("/api/linhas/filtros")
def linhas_filtros():
    """Opcoes de filtro geradas a partir dos dados existentes -- nunca exibe opcao
    vazia (ver item 7 do pedido: "Não exibir opções vazias")."""
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()

        def valores(col):
            return [r[0] for r in cur.execute(
                f"SELECT DISTINCT {col} FROM linhas_incentivadas WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}"
            ).fetchall()]

        # Portes: bucket canonico (porte_grupo, ver _linhas_where acima), numa ordem
        # de faixa crescente em vez de alfabetica -- "Nao informado"/"Todos os portes"
        # ficam nas pontas de proposito (nem excluem nem sao uma faixa especifica).
        ORDEM_PORTE = ["Micro/Pequena", "Média", "Grande", "Todos os portes", "Não informado"]
        portes_existentes = set(valores("porte_grupo"))
        portes = [p for p in ORDEM_PORTE if p in portes_existentes]

        return {
            "instituicoes": valores("instituicao"),
            "setores": valores("setor_padronizado"),
            "portes": portes,
            "regioes": valores("regiao_elegivel"),
            "status": valores("status"),
            "fluxos": valores("fluxo"),
        }
    finally:
        conn.close()


@app.get("/api/linhas")
def linhas(
    instituicao: str = None, setor: str = None, porte: str = None, regiao: str = None,
    status: str = None, fluxo: str = None, q: str = None,
    order_by: str = "data_atualizacao", order_dir: str = "desc",
    limit: int = 20, offset: int = 0,
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    where, params = _linhas_where(instituicao, setor, porte, regiao, status, fluxo, q)
    col_ordenacao = order_by if order_by in LINHAS_COLS_LISTA else "data_atualizacao"
    direcao = "ASC" if order_dir == "asc" else "DESC"
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        total = cur.execute(f"SELECT COUNT(*) FROM linhas_incentivadas {where}", params).fetchone()[0]
        # Tiebreaker por id e necessario: sem ele, ORDER BY numa coluna com valores repetidos
        # (ex.: varias linhas atualizadas no mesmo lote, mesmo data_atualizacao) nao tem ordem
        # estavel entre paginas -- o Postgres pode devolver a mesma linha em duas paginas
        # diferentes (ou pular linhas), especialmente se a tabela for escrita entre as duas
        # requisicoes de paginacao. Com o id como desempate, LIMIT/OFFSET fica deterministico.
        rows = cur.execute(
            f"SELECT {', '.join(LINHAS_COLS_LISTA)} FROM linhas_incentivadas {where} "
            f"ORDER BY {col_ordenacao} {direcao} NULLS LAST, id ASC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return {
            "total": total,
            "resultados": [dict(zip(LINHAS_COLS_LISTA, r)) for r in rows],
        }
    finally:
        conn.close()


@app.get("/api/linhas/{linha_id}")
def linha_detalhe(linha_id: int):
    conn = get_connection(pooled=True)
    try:
        row = conn.execute(
            f"SELECT {', '.join(LINHAS_COLS_DETALHE)} FROM linhas_incentivadas WHERE id = ?", (linha_id,)
        ).fetchone()
        if not row:
            return {"erro": "linha nao encontrada"}
        return dict(zip(LINHAS_COLS_DETALHE, row))
    finally:
        conn.close()


# ============ Enriquecimento (item 3 do pedido de melhorias) ============
# So cobre as transacoes ja importadas (bndes_raw/finep_*_raw -> operations, ver
# unify.py) -- NAO tem upload de planilha nesta versao: os dados vem sempre de
# download automatico das planilhas oficiais do BNDES/FINEP (ver refresh.py), nunca
# de arquivo enviado por um usuario, entao nao ha um fluxo de "importar arquivo" pra
# expor aqui. O que existe: historico de importacoes (refresh_log/refresh_editais_log,
# ja gravados por refresh.py/refresh_editais.py), fila de registros pendentes (setor
# nao resolvido pela classificacao automatica) e correcao manual, que passa a
# prevalecer sobre reclassificacoes automaticas futuras (ver unify.py).

@app.get("/api/enriquecimento/importacoes")
def enriquecimento_importacoes(limit: int = 20):
    limit = max(1, min(limit, 200))
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        transacoes = cur.execute(
            "SELECT started_at, finished_at, bndes_rows, finep_credito_direto_rows, "
            "finep_credito_descentralizado_rows, operations_rows, setores_pendentes, status, detalhe "
            "FROM refresh_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        editais = cur.execute(
            "SELECT started_at, finished_at, total_editais, abertos, status, detalhe "
            "FROM refresh_editais_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        cols_transacoes = ["started_at", "finished_at", "bndes_rows", "finep_credito_direto_rows",
                           "finep_credito_descentralizado_rows", "operations_rows", "setores_pendentes",
                           "status", "detalhe"]
        cols_editais = ["started_at", "finished_at", "total_editais", "abertos", "status", "detalhe"]
        return {
            "transacoes": [dict(zip(cols_transacoes, r)) for r in transacoes],
            "editais": [dict(zip(cols_editais, r)) for r in editais],
        }
    finally:
        conn.close()


@app.get("/api/enriquecimento/pendentes")
def enriquecimento_pendentes(limit: int = 20, offset: int = 0):
    """Fila de revisao manual: operacoes que a classificacao automatica NAO conseguiu
    resolver (ver setor_origem='pendente' em unify.py) -- tipicamente FINEP sem CNPJ
    informado na planilha de origem, caso em que nenhum enriquecimento automatico
    (CNPJ->CNAE) tem como resolver; so uma correcao manual (quem conhece a operacao)
    pode."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM operations WHERE setor_origem = 'pendente'").fetchone()[0]
        rows = cur.execute(
            "SELECT id, agencia, instrumento, cliente, cnpj, uf, data_contratacao, valor_contratado, "
            "descricao_projeto FROM operations WHERE setor_origem = 'pendente' "
            "ORDER BY valor_contratado DESC NULLS LAST LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        cols = ["id", "agencia", "instrumento", "cliente", "cnpj", "uf", "data_contratacao",
                "valor_contratado", "descricao_projeto"]
        return {"total": total, "resultados": [dict(zip(cols, r)) for r in rows]}
    finally:
        conn.close()


@app.get("/api/enriquecimento/correcoes")
def enriquecimento_correcoes(limit: int = 50):
    limit = max(1, min(limit, 500))
    conn = get_connection(pooled=True)
    try:
        rows = conn.execute(
            "SELECT c.id, c.operation_id, o.cliente, c.campo, c.valor_anterior, c.valor_novo, "
            "c.usuario, c.criado_em, c.ativa FROM operations_correcoes_manuais c "
            "LEFT JOIN operations o ON o.id = c.operation_id "
            "ORDER BY c.id DESC LIMIT ?", (limit,)
        ).fetchall()
        cols = ["id", "operation_id", "cliente", "campo", "valor_anterior", "valor_novo", "usuario", "criado_em", "ativa"]
        return {"resultados": [dict(zip(cols, r)) for r in rows]}
    finally:
        conn.close()


@app.post("/api/enriquecimento/corrigir")
def enriquecimento_corrigir(body: dict, request: Request):
    operation_id = (body or {}).get("operation_id")
    campo = (body or {}).get("campo")
    valor_novo = (body or {}).get("valor_novo")
    # Antes usava um usuario generico compartilhado (SITE_USER) -- agora que o login
    # e por conta individual, atribui a correcao a quem esta de fato logado.
    usuario = (body or {}).get("usuario") or _usuario_logado(request)
    if not operation_id or not campo or not valor_novo:
        return {"erro": "parametros 'operation_id', 'campo' e 'valor_novo' sao obrigatorios"}
    from unify import registrar_correcao_manual

    conn = get_connection(pooled=True)
    try:
        registrar_correcao_manual(conn, int(operation_id), campo, valor_novo, usuario)
        return {"ok": True}
    except ValueError as e:
        return {"erro": str(e)}
    except Exception as e:
        logger.exception("correcao manual falhou")
        return {"erro": f"nao foi possivel salvar a correcao agora ({e})"}
    finally:
        conn.close()


# Rotas da SPA por caminho (/consolidado, /tendencias, /busca, /editais,
# /linhas-incentivadas): so servem o MESMO index.html, a troca de aba de verdade e
# 100% client-side (ver _ativarView em common.js). No deploy hospedado (Vercel), quem
# resolve isso e o rewrite em vercel.json direto na CDN -- estas rotas aqui so
# importam pro modo local (`uvicorn webapp.main:app`), onde nao existe CDN
# reescrevendo nada antes de chegar no FastAPI.
_SPA_PAGINAS = ["consolidado", "tendencias", "busca", "editais", "linhas-incentivadas", "potenciais-linhas"]


@app.get("/{pagina}", include_in_schema=False)
async def spa_pagina(pagina: str):
    # admin/admin.html: pagina propria e ISOLADA do painel de admin (ver
    # webapp/admin/), nao faz parte da SPA principal -- tratada aqui em vez de em
    # _SPA_PAGINAS so porque, sem isso, este catch-all (que roda ANTES do mount de
    # arquivos estaticos abaixo) intercepta e devolve 404 pra qualquer caminho de UM
    # segmento so que nao esteja na lista, inclusive um arquivo estatico que existe
    # de verdade (admin.html). So importa no modo local (`uvicorn`) -- no deploy
    # hospedado, o rewrite em vercel.json resolve "/admin" direto na CDN.
    if pagina in ("admin", "admin.html"):
        return FileResponse(STATIC_DIR / "admin.html")
    if pagina not in _SPA_PAGINAS:
        raise HTTPException(status_code=404)
    return FileResponse(STATIC_DIR / "index.html")


# So monta o servico de arquivos estaticos quando NAO estamos rodando como funcao
# serverless da Vercel -- e o que faz `uvicorn webapp.main:app` local (dev no PC,
# app desktop) continuar servindo front+back no mesmo processo, de um jeito
# identico a antes desta migracao. No deploy hospedado (ver vercel.json e
# DEPLOY.md), a propria Vercel serve webapp/static/ direto pela CDN a partir de
# `outputDirectory` -- rodar este mount ali tambem nao quebraria nada (so seria
# alcancado por requisicoes que a CDN nunca deixa chegar ate a funcao), mas
# empacotaria o HTML/CSS/JS inteiro dentro do bundle da funcao Python a toa.
#
# VERCEL=1 e a variavel de ambiente que a propria Vercel expõe (documentada em
# https://vercel.com/docs/environment-variables/system-environment-variables) --
# usada aqui como sinal de "estamos rodando na Vercel". NAO TESTADO contra um
# deploy real (ver relatorio da migracao): confirmar no primeiro deploy que essa
# variavel realmente chega ao processo (a Vercel documenta que a opcao "Enable
# access to System Environment Variables" precisa estar marcada nas configuracoes
# do projeto para isso) -- se nao chegar, o pior caso e so este mount rodar
# desnecessariamente dentro da funcao (peso extra no bundle), nunca um erro.
if not os.environ.get("VERCEL"):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
