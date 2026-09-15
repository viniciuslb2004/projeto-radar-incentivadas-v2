"""Rotas do painel de admin (`/admin/api/*`) -- pacote isolado, ver `webapp/admin/auth.py`
para a sessao/hash de senha e `webapp/admin/seed.py` para a migracao/seed das contas.

COMO REMOVER ESTE PAINEL INTEIRO (se um dia for descontinuado):
  1. Apagar as tabelas do banco: `DROP TABLE admin_sessoes; DROP TABLE admin_acessos_log;
     DROP TABLE admin_usuarios;`
  2. Apagar a pasta `webapp/admin/` inteira (este arquivo, auth.py, seed.py, __init__.py).
  3. Apagar `webapp/static/admin.html` e `webapp/static/js/admin.js` (+ admin.css, se existir).
  4. Remover a linha `app.include_router(admin_router, prefix="/admin")` (e o import
     correspondente) de `webapp/main.py`.
  5. Remover o rewrite `/admin` -> `/admin.html` de `vercel.json`.
  6. ATENCAO -- EXCECAO a segregacao (ver CLAUDE.md, secao "Painel de Admin"): desde que
     o login do SITE PRINCIPAL passou a usar `admin_usuarios` (substituindo o antigo
     SITE_PASSWORD), remover so os itens 1-5 acima QUEBRA o login do site inteiro. Reverta
     primeiro `_verificar_acesso`/`/api/login`/`/api/logout` em `webapp/main.py` para algum
     mecanismo de auth do site principal (o antigo SITE_PASSWORD ou outro) ANTES de apagar
     as tabelas/pacote.
Fora essa excecao documentada, nada neste painel toca em `operations`,
`linhas_incentivadas`, `editais_raw` nem em qualquer outra tabela do dado de negocio.
"""
import logging
import os

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from db import get_connection

logger = logging.getLogger("radar")

from .auth import (
    SESSION_COOKIE,
    autenticar_credenciais,
    criar_sessao,
    definir_cookie_sessao,
    encerrar_sessao,
    exigir_admin,
    gerar_hash_senha,
    limpar_cookie_sessao,
    registrar_acesso,
)

router = APIRouter()

GITHUB_REPO = os.environ.get("GITHUB_REPO", "viniciuslb2004/Projeto-Radar-Incentivadas")
GITHUB_ACTIONS_TOKEN = os.environ.get("GITHUB_ACTIONS_TOKEN")


def _ip_do_request(request: Request) -> str:
    return request.headers.get("x-forwarded-for", request.client.host if request.client else None)


@router.post("/api/login")
def login(payload: dict, request: Request, response: Response):
    username = (payload.get("username") or "").strip()
    senha = payload.get("password") or ""
    conn = get_connection(pooled=True)
    try:
        usuario = autenticar_credenciais(conn, username, senha)
        if usuario is None:
            raise HTTPException(status_code=401, detail="Usuario ou senha incorretos")
        if usuario["role"] != "admin":
            raise HTTPException(status_code=403, detail="Esta conta nao tem acesso ao painel de admin")
        token = criar_sessao(conn, usuario["id"])
        registrar_acesso(conn, usuario["id"], usuario["username"], "admin", "login", _ip_do_request(request))
    finally:
        conn.close()
    definir_cookie_sessao(response, token)
    return {"ok": True, "username": username}


@router.post("/api/logout")
def logout(request: Request, response: Response, usuario: dict = Depends(exigir_admin)):
    token = request.cookies.get(SESSION_COOKIE)
    conn = get_connection(pooled=True)
    try:
        encerrar_sessao(conn, token)
        registrar_acesso(conn, usuario["id"], usuario["username"], "admin", "logout", _ip_do_request(request))
    finally:
        conn.close()
    limpar_cookie_sessao(response)
    return {"ok": True}


@router.get("/api/me")
def me(usuario: dict = Depends(exigir_admin)):
    return {"username": usuario["username"], "role": usuario["role"]}


@router.get("/api/dashboard")
def dashboard(usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        refresh_operacoes = conn.execute(
            "SELECT started_at, finished_at, operations_rows, setores_pendentes, status, detalhe "
            "FROM refresh_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        refresh_editais = conn.execute(
            "SELECT started_at, finished_at, total_editais, abertos, status, detalhe "
            "FROM refresh_editais_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        total_usuarios = conn.execute("SELECT COUNT(*) FROM admin_usuarios").fetchone()[0]
        total_operacoes = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        total_linhas = conn.execute("SELECT COUNT(*) FROM linhas_incentivadas").fetchone()[0]
        total_editais = conn.execute("SELECT COUNT(*) FROM editais_raw").fetchone()[0]
        pendentes_enriquecimento = conn.execute(
            "SELECT COUNT(*) FROM operations WHERE setor_origem = 'pendente'"
        ).fetchone()[0]
    finally:
        conn.close()

    def _log_dict(row, campos):
        if row is None:
            return None
        return dict(zip(campos, row))

    return {
        "refresh_operacoes": _log_dict(
            refresh_operacoes,
            ["started_at", "finished_at", "operations_rows", "setores_pendentes", "status", "detalhe"],
        ),
        "refresh_editais": _log_dict(
            refresh_editais,
            ["started_at", "finished_at", "total_editais", "abertos", "status", "detalhe"],
        ),
        "total_usuarios": total_usuarios,
        "total_operacoes": total_operacoes,
        "total_linhas_incentivadas": total_linhas,
        "total_editais": total_editais,
        "pendentes_enriquecimento": pendentes_enriquecimento,
        "github_actions_configurado": bool(GITHUB_ACTIONS_TOKEN),
    }


@router.get("/api/usuarios")
def listar_usuarios(q: str = "", usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        termo = f"%{q.strip()}%" if q.strip() else "%"
        rows = conn.execute(
            "SELECT id, username, role, ativo, criado_em FROM admin_usuarios "
            "WHERE username ILIKE ? ORDER BY username",
            (termo,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "usuarios": [
            {"id": r[0], "username": r[1], "role": r[2], "ativo": r[3], "criado_em": r[4]} for r in rows
        ]
    }


def _contar_admins_ativos(conn, excluir_id: int = None) -> int:
    if excluir_id is None:
        return conn.execute(
            "SELECT COUNT(*) FROM admin_usuarios WHERE role = 'admin' AND ativo = TRUE"
        ).fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM admin_usuarios WHERE role = 'admin' AND ativo = TRUE AND id != ?",
        (excluir_id,),
    ).fetchone()[0]


@router.post("/api/usuarios")
def criar_usuario(payload: dict, usuario: dict = Depends(exigir_admin)):
    username = (payload.get("username") or "").strip()
    senha = payload.get("password") or ""
    role = payload.get("role") or "usuario"
    if not username or not senha:
        raise HTTPException(status_code=400, detail="Usuario e senha sao obrigatorios")
    if role not in ("admin", "usuario"):
        raise HTTPException(status_code=400, detail="Papel invalido (use 'admin' ou 'usuario')")

    from datetime import datetime, timezone

    password_hash = gerar_hash_senha(senha)
    conn = get_connection(pooled=True)
    try:
        ja_existe = conn.execute("SELECT 1 FROM admin_usuarios WHERE username = ?", (username,)).fetchone()
        if ja_existe:
            raise HTTPException(status_code=409, detail="Ja existe um usuario com esse nome")
        conn.execute(
            "INSERT INTO admin_usuarios (username, password_hash, role, ativo, criado_em) "
            "VALUES (?, ?, ?, TRUE, ?)",
            (username, password_hash, role, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/usuarios/{usuario_id}/ativo")
def alterar_ativo(usuario_id: int, payload: dict, usuario: dict = Depends(exigir_admin)):
    ativo = bool(payload.get("ativo"))
    conn = get_connection(pooled=True)
    try:
        row = conn.execute("SELECT id, role FROM admin_usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        _, role = row
        if not ativo and role == "admin" and _contar_admins_ativos(conn, excluir_id=usuario_id) == 0:
            raise HTTPException(status_code=409, detail="Nao e possivel desativar o ultimo admin ativo")
        conn.execute("UPDATE admin_usuarios SET ativo = ? WHERE id = ?", (ativo, usuario_id))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.delete("/api/usuarios/{usuario_id}")
def excluir_usuario(usuario_id: int, usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        row = conn.execute("SELECT id, role FROM admin_usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        _, role = row
        if role == "admin" and _contar_admins_ativos(conn, excluir_id=usuario_id) == 0:
            raise HTTPException(status_code=409, detail="Nao e possivel excluir o ultimo admin ativo")
        # admin_sessoes tem ON DELETE CASCADE (sessoes deste usuario somem junto);
        # admin_acessos_log tem ON DELETE SET NULL + username_snapshot (log continua
        # legivel mesmo depois da exclusao, ver seed.py).
        conn.execute("DELETE FROM admin_usuarios WHERE id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.get("/api/acessos")
def listar_acessos(limit: int = 100, usuario: dict = Depends(exigir_admin)):
    limit = max(1, min(limit, 500))
    conn = get_connection(pooled=True)
    try:
        rows = conn.execute(
            "SELECT username_snapshot, origem, evento, ip, criado_em FROM admin_acessos_log "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "acessos": [
            {"username": r[0], "origem": r[1], "evento": r[2], "ip": r[3], "criado_em": r[4]} for r in rows
        ]
    }


@router.get("/api/usuarios/{usuario_id}/acessos")
def acessos_do_usuario(usuario_id: int, usuario: dict = Depends(exigir_admin)):
    """Drill-down do log de acessos por PESSOA (pedido do usuario) -- reaproveita
    admin_acessos_log, so filtra por usuario_id -- NAO e a V2 de analytics (sem
    tracking de navegacao/clique dentro da pagina, so login/logout, ver CLAUDE.md)."""
    conn = get_connection(pooled=True)
    try:
        alvo = conn.execute("SELECT username FROM admin_usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if alvo is None:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        rows = conn.execute(
            "SELECT origem, evento, ip, criado_em FROM admin_acessos_log "
            "WHERE usuario_id = ? ORDER BY id DESC LIMIT 200",
            (usuario_id,),
        ).fetchall()
        total_logins = conn.execute(
            "SELECT COUNT(*) FROM admin_acessos_log WHERE usuario_id = ? AND evento = 'login'",
            (usuario_id,),
        ).fetchone()[0]
        primeiro = conn.execute(
            "SELECT MIN(criado_em) FROM admin_acessos_log WHERE usuario_id = ? AND evento = 'login'",
            (usuario_id,),
        ).fetchone()[0]
        ultimo = conn.execute(
            "SELECT MAX(criado_em) FROM admin_acessos_log WHERE usuario_id = ? AND evento = 'login'",
            (usuario_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "username": alvo[0],
        "total_logins": total_logins,
        "primeiro_acesso": primeiro,
        "ultimo_acesso": ultimo,
        "eventos": [{"origem": r[0], "evento": r[1], "ip": r[2], "criado_em": r[3]} for r in rows],
    }


def _disparar_workflow_github(arquivo_workflow: str) -> None:
    if not GITHUB_ACTIONS_TOKEN:
        raise HTTPException(
            status_code=503,
            detail=(
                "GITHUB_ACTIONS_TOKEN nao configurado. Peca pro usuario criar um Personal "
                "Access Token do GitHub (escopo 'actions:write' no repo) e configurar essa "
                "variavel de ambiente na Vercel -- isso so pode ser feito pelo proprio usuario."
            ),
        )
    resp = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{arquivo_workflow}/dispatches",
        json={"ref": "master"},
        headers={
            "Authorization": f"Bearer {GITHUB_ACTIONS_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15,
    )
    if resp.status_code != 204:
        raise HTTPException(status_code=502, detail=f"GitHub API respondeu {resp.status_code}: {resp.text[:300]}")


@router.post("/api/refresh/operacoes")
def disparar_refresh_operacoes(usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        ultimo = conn.execute(
            "SELECT started_at, finished_at FROM refresh_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if ultimo and ultimo[1] is None:
        raise HTTPException(
            status_code=409,
            detail=f"Ja existe um refresh de operacoes em andamento (iniciado em {ultimo[0]}).",
        )
    _disparar_workflow_github("refresh-operacoes.yml")
    return {"ok": True, "mensagem": "Workflow de refresh de operacoes disparado."}


@router.post("/api/refresh/editais")
def disparar_refresh_editais(usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        ultimo = conn.execute(
            "SELECT started_at, finished_at FROM refresh_editais_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if ultimo and ultimo[1] is None:
        raise HTTPException(
            status_code=409,
            detail=f"Ja existe um refresh de editais em andamento (iniciado em {ultimo[0]}).",
        )
    _disparar_workflow_github("refresh-editais.yml")
    return {"ok": True, "mensagem": "Workflow de refresh de editais disparado."}


@router.post("/api/enriquecer-pendentes")
def enriquecer_pendentes_lote(payload: dict = None, usuario: dict = Depends(exigir_admin)):
    """Processa um LOTE limitado de CNPJs 'pendente' via BrasilAPI (reaproveita
    enrich_cnae.py::enrich_pendentes_via_api + unify.py::reclassificar_pendentes, o
    MESMO codigo do refresh semanal, so chamado sob demanda e em lote pequeno --
    rodar TODOS os pendentes de uma vez arrisca estourar o timeout de uma function
    serverless da Vercel, ver CLAUDE.md). Cada CNPJ leva ~0.6s (rate limit da
    BrasilAPI) + tempo de rede -- um lote de 20 fica bem dentro de qualquer timeout
    razoavel; peca pro admin clicar de novo pra processar o proximo lote."""
    tamanho_lote = min(max(int((payload or {}).get("tamanho_lote") or 20), 1), 50)

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    import enrich_cnae
    import unify
    from sector_taxonomy import build_divisao_map

    conn = get_connection(pooled=True)
    try:
        cnpjs = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT cnpj FROM operations WHERE setor_origem = 'pendente' "
                "AND cnpj IS NOT NULL ORDER BY cnpj LIMIT ?",
                (tamanho_lote,),
            ).fetchall()
        ]
        if not cnpjs:
            restantes = conn.execute(
                "SELECT COUNT(*) FROM operations WHERE setor_origem = 'pendente'"
            ).fetchone()[0]
            return {"ok": True, "processados": 0, "resolvidos_cnpj_cnae": 0, "operacoes_reclassificadas": 0, "restantes": restantes}

        # BUG REAL em producao (2026-09-10): esta chamada (via unify.reclassificar_
        # pendentes -> _load_cnae_lookup -> db.get_engine()) so funciona se sqlalchemy
        # estiver instalado no runtime -- ver comentario em api/requirements.txt. Sem
        # isso, quebrava com 500 cru (ModuleNotFoundError) em vez de uma mensagem
        # clara. O try/except aqui e defesa em profundidade (cobre TAMBEM falhas de
        # rede da BrasilAPI, timeout, etc) -- a causa raiz especifica ja foi corrigida
        # adicionando sqlalchemy a api/requirements.txt.
        try:
            divisao_map = build_divisao_map(conn)
            resolvidos = enrich_cnae.enrich_pendentes_via_api(conn, set(cnpjs), divisao_map)
            reclassificados = unify.reclassificar_pendentes(conn)
        except Exception as e:
            logger.exception("enriquecer-pendentes falhou processando o lote")
            raise HTTPException(
                status_code=500,
                detail=f"Nao foi possivel processar este lote agora ({e}). Tente novamente em instantes.",
            )
        restantes = conn.execute(
            "SELECT COUNT(*) FROM operations WHERE setor_origem = 'pendente'"
        ).fetchone()[0]
    finally:
        conn.close()

    return {
        "ok": True,
        "processados": len(cnpjs),
        "resolvidos_cnpj_cnae": resolvidos,
        "operacoes_reclassificadas": len(reclassificados),
        "restantes": restantes,
    }


# ============ Correcoes manuais (operations_correcoes_manuais) ============
# So uma TELA sobre a tabela que ja existe (ver src/db.py) -- toda a logica de
# aplicar/revalidar a correcao contra `operations` ja existe em
# unify.py::registrar_correcao_manual (mesma funcao usada por
# webapp/main.py::enriquecimento_corrigir) e unify.py::_reaplicar_correcoes_manuais
# (chamada automaticamente a cada refresh semanal) -- nada disso e duplicado aqui.


def _importar_unify():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    import unify

    return unify


@router.get("/api/operacoes/buscar")
def buscar_operacoes(q: str = "", usuario: dict = Depends(exigir_admin)):
    """Busca simples (id exato OU cliente por ILIKE) so pra apoiar o formulario de
    correcao manual -- NAO e o motor de busca completo do site (src/search_fts.py),
    que existe pra outro proposito (ranking/relevancia pro usuario final)."""
    termo = q.strip()
    if not termo:
        return {"operacoes": []}
    conn = get_connection(pooled=True)
    try:
        if termo.isdigit():
            rows = conn.execute(
                "SELECT id, cliente, cnpj, setor_bndes, subsetor_bndes, segmento FROM operations "
                "WHERE id = ? LIMIT 20",
                (int(termo),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, cliente, cnpj, setor_bndes, subsetor_bndes, segmento FROM operations "
                "WHERE cliente ILIKE ? ORDER BY id DESC LIMIT 20",
                (f"%{termo}%",),
            ).fetchall()
    finally:
        conn.close()
    campos = ["id", "cliente", "cnpj", "setor_bndes", "subsetor_bndes", "segmento"]
    return {"operacoes": [dict(zip(campos, r)) for r in rows]}


@router.get("/api/correcoes")
def listar_correcoes(limit: int = 50, usuario: dict = Depends(exigir_admin)):
    limit = max(1, min(limit, 200))
    conn = get_connection(pooled=True)
    try:
        rows = conn.execute(
            "SELECT c.id, c.operation_id, o.cliente, c.campo, c.valor_anterior, c.valor_novo, "
            "c.usuario, c.criado_em, c.ativa FROM operations_correcoes_manuais c "
            "LEFT JOIN operations o ON o.id = c.operation_id "
            "ORDER BY c.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    campos = ["id", "operation_id", "cliente", "campo", "valor_anterior", "valor_novo", "usuario", "criado_em", "ativa"]
    return {"correcoes": [dict(zip(campos, r)) for r in rows]}


@router.post("/api/correcoes")
def criar_correcao(payload: dict, usuario: dict = Depends(exigir_admin)):
    operation_id = payload.get("operation_id")
    campo = payload.get("campo")
    valor_novo = payload.get("valor_novo")
    if not operation_id or not campo or not valor_novo:
        raise HTTPException(status_code=400, detail="operation_id, campo e valor_novo sao obrigatorios")

    unify = _importar_unify()
    conn = get_connection(pooled=True)
    try:
        unify.registrar_correcao_manual(conn, int(operation_id), campo, valor_novo, usuario["username"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/correcoes/{correcao_id}/desativar")
def desativar_correcao(correcao_id: int, usuario: dict = Depends(exigir_admin)):
    """So marca ativa=FALSE (NUNCA DELETE -- e historico, ver comentario no topo desta
    secao). Nao reverte o valor ja aplicado em `operations` -- isso so muda o que o
    PROXIMO refresh semanal vai (deixar de) reforcar (ver
    unify.py::_reaplicar_correcoes_manuais)."""
    conn = get_connection(pooled=True)
    try:
        row = conn.execute("SELECT id FROM operations_correcoes_manuais WHERE id = ?", (correcao_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Correcao nao encontrada")
        conn.execute("UPDATE operations_correcoes_manuais SET ativa = FALSE WHERE id = ?", (correcao_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ============ Saude do banco (proxy -- NAO e o %% de disco oficial da Aiven) ============
# Descoberta real do incidente de disco cheio (ver CLAUDE.md): pg_database_size() so
# mostra o tamanho LOGICO, nao bate com o "disco cheio" que a Aiven alerta (que conta
# WAL/backup tambem) -- o numero oficial so aparece no console.aiven.io, e exigiria a
# API deles (token novo) pra puxar aqui. Esses proxies (tamanho logico, bloat via
# n_dead_tup, conexoes abertas, ultimo vacuum) sao uteis e baratos (so SQL, sem
# credencial nova), mas a UI precisa deixar claro que NAO sao o numero oficial.
@router.get("/api/saude-banco")
def saude_banco(usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        tamanho_logico_bytes = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        conexoes_abertas = conn.execute("SELECT COUNT(*) FROM pg_stat_activity").fetchone()[0]
        tabelas = conn.execute(
            "SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum "
            "FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10"
        ).fetchall()
    finally:
        conn.close()
    campos = ["tabela", "linhas_vivas", "linhas_mortas", "ultimo_vacuum", "ultimo_autovacuum"]
    return {
        "tamanho_logico_mb": round(tamanho_logico_bytes / (1024 * 1024), 1),
        "conexoes_abertas": conexoes_abertas,
        "tabelas_por_bloat": [dict(zip(campos, (t[0], t[1], t[2], str(t[3]) if t[3] else None, str(t[4]) if t[4] else None))) for t in tabelas],
    }
