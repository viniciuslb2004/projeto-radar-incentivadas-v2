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
  6. ATENCAO -- EXCECAO a segregacao (ver CLAUDE.md/docs/painel-admin.md, secao "Painel de
     Admin"): desde que o login do SITE PRINCIPAL passou a usar `admin_usuarios`
     (substituindo o antigo SITE_PASSWORD, depois login+senha, depois identificacao
     passwordless por e-mail -- ver docs/painel-admin.md), remover so os itens 1-5 acima
     QUEBRA o acesso ao site inteiro. Reverta primeiro `_verificar_acesso`/
     `/api/identificar`/`/api/cadastrar`/`/api/interesse`/`/api/logout` em `webapp/main.py`
     pra algum outro mecanismo de auth do site principal ANTES de apagar as tabelas/pacote.
     Reverter tambem exige tirar a landing/identificacao (`#landing-overlay`) de
     `webapp/static/index.html`/`common.js`.
Fora essa excecao documentada, nada neste painel toca em `operations`,
`linhas_incentivadas`, `editais_raw` nem em qualquer outra tabela do dado de negocio.
"""
import logging
import os
import re

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
    mensagem_status_bloqueado,
    registrar_acesso,
)

router = APIRouter()

GITHUB_REPO = os.environ.get("GITHUB_REPO", "viniciuslb2004/Projeto-Radar-Incentivadas")
GITHUB_ACTIONS_TOKEN = os.environ.get("GITHUB_ACTIONS_TOKEN")

# Mesmo padrao simples usado por webapp/main.py::_email_valido (so confere "@" +
# "." na parte depois do @, sem verificar entrega) -- duplicado aqui (nao
# importado de main.py) pra nao criar import circular (main.py e' quem importa
# este pacote, nao o contrario).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


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
        mensagem_bloqueio = mensagem_status_bloqueado(usuario["status"])
        if mensagem_bloqueio:
            raise HTTPException(status_code=401, detail=mensagem_bloqueio)
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
        # Distincao staff (conta com senha real, gerenciada pelo CRUD abaixo) vs
        # usuario/lead do site (password_hash = '' -- sentinela de conta criada
        # pelo fluxo passwordless, ver webapp/main.py::site_cadastrar). Mantem os
        # dois totais separados no dashboard pra nao confundir "conta do painel"
        # com "pessoa que se identificou no site publico".
        total_usuarios = conn.execute(
            "SELECT COUNT(*) FROM admin_usuarios WHERE password_hash != ''"
        ).fetchone()[0]
        total_usuarios_site = conn.execute(
            "SELECT COUNT(*) FROM admin_usuarios WHERE password_hash = ''"
        ).fetchone()[0]
        total_leads = conn.execute(
            "SELECT COUNT(*) FROM admin_acessos_log WHERE evento = 'interesse_lead'"
        ).fetchone()[0]
        leads_pendentes = conn.execute(
            "SELECT COUNT(*) FROM admin_acessos_log WHERE evento = 'interesse_lead' AND NOT contatado"
        ).fetchone()[0]
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
        "total_usuarios_site": total_usuarios_site,
        "total_leads": total_leads,
        "leads_pendentes": leads_pendentes,
        "total_operacoes": total_operacoes,
        "total_linhas_incentivadas": total_linhas,
        "total_editais": total_editais,
        "pendentes_enriquecimento": pendentes_enriquecimento,
        "github_actions_configurado": bool(GITHUB_ACTIONS_TOKEN),
    }


@router.get("/api/usuarios")
def listar_usuarios(q: str = "", usuario: dict = Depends(exigir_admin)):
    # So CONTAS DO PAINEL (staff Artica, senha real) -- distinguidas de
    # usuarios/leads do site publico por password_hash != '' (sentinela de conta
    # passwordless criada por webapp/main.py::site_cadastrar, ver comentario em
    # /api/dashboard acima). Usuarios/leads do site tem secao propria
    # (GET /api/usuarios-site) pra nao misturar gestao de acesso interno (CRUD com
    # senha/role) com a lista de leads/usuarios publicos.
    conn = get_connection(pooled=True)
    try:
        termo = f"%{q.strip()}%" if q.strip() else "%"
        rows = conn.execute(
            "SELECT id, username, role, ativo, criado_em FROM admin_usuarios "
            "WHERE username ILIKE ? AND password_hash != '' ORDER BY username",
            (termo,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "usuarios": [
            {"id": r[0], "username": r[1], "role": r[2], "ativo": r[3], "criado_em": r[4]} for r in rows
        ]
    }


# ============ Usuarios do site (identificacao passwordless) ============
# "Usuarios" no sentido do reposicionamento pra lead-gen (ver CLAUDE.md) -- gente
# que passou por POST /api/identificar ou /api/cadastrar (site principal), NUNCA
# uma conta com senha do painel (ver filtro password_hash acima/abaixo).
@router.get("/api/usuarios-site")
def listar_usuarios_site(q: str = "", usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        termo = f"%{q.strip()}%" if q.strip() else "%"
        rows = conn.execute(
            "SELECT u.id, u.nome, u.email, u.empresa, u.cargo, "
            "  (SELECT MIN(l.criado_em) FROM admin_acessos_log l WHERE l.usuario_id = u.id AND l.evento = 'login') AS primeiro_acesso, "
            "  (SELECT MAX(l.criado_em) FROM admin_acessos_log l WHERE l.usuario_id = u.id AND l.evento = 'login') AS ultimo_acesso, "
            "  (SELECT COUNT(*) FROM admin_acessos_log l WHERE l.usuario_id = u.id AND l.evento = 'login') AS qtd_acessos "
            "FROM admin_usuarios u "
            "WHERE u.password_hash = '' "
            "  AND (u.nome ILIKE ? OR u.email ILIKE ? OR u.empresa ILIKE ?) "
            "ORDER BY ultimo_acesso DESC NULLS LAST",
            (termo, termo, termo),
        ).fetchall()
    finally:
        conn.close()
    campos = ["id", "nome", "email", "empresa", "cargo", "primeiro_acesso", "ultimo_acesso", "qtd_acessos"]
    return {"usuarios": [dict(zip(campos, r)) for r in rows]}


@router.get("/api/usuarios-site/{usuario_id}")
def detalhe_usuario_site(usuario_id: int, usuario: dict = Depends(exigir_admin)):
    """Drill-down por USUARIO DO SITE (lead/pessoa identificada via passwordless) --
    mesmo espirito do drill-down de staff (GET /api/usuarios/{id}/acessos), mas
    trazendo o perfil certo pra esse tipo de conta (nome/e-mail/empresa/cargo, sem
    username/role/senha, que nao existem de verdade pra esse fluxo) + o historico
    de manifestacoes de interesse comercial ('quero saber mais', mesma tabela
    usada por GET /api/leads). A timeline de sessoes/paginas fica numa chamada
    separada do frontend (GET /api/atividade?usuario_id=...), mesma rota
    reaproveitada pelo drill-down de staff (ver atividade() abaixo)."""
    conn = get_connection(pooled=True)
    try:
        row = conn.execute(
            "SELECT id, nome, email, empresa, cargo, criado_em FROM admin_usuarios "
            "WHERE id = ? AND password_hash = ''",
            (usuario_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario do site nao encontrado")
        primeiro_acesso = conn.execute(
            "SELECT MIN(criado_em) FROM admin_acessos_log WHERE usuario_id = ? AND evento = 'login'",
            (usuario_id,),
        ).fetchone()[0]
        ultimo_acesso = conn.execute(
            "SELECT MAX(criado_em) FROM admin_acessos_log WHERE usuario_id = ? AND evento = 'login'",
            (usuario_id,),
        ).fetchone()[0]
        qtd_acessos = conn.execute(
            "SELECT COUNT(*) FROM admin_acessos_log WHERE usuario_id = ? AND evento = 'login'",
            (usuario_id,),
        ).fetchone()[0]
        leads = conn.execute(
            "SELECT id, criado_em, contatado FROM admin_acessos_log "
            "WHERE usuario_id = ? AND evento = 'interesse_lead' ORDER BY criado_em DESC",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()
    campos_usuario = ["id", "nome", "email", "empresa", "cargo", "criado_em"]
    campos_lead = ["id", "criado_em", "contatado"]
    return {
        "usuario": dict(zip(campos_usuario, row)),
        "primeiro_acesso": primeiro_acesso,
        "ultimo_acesso": ultimo_acesso,
        "qtd_acessos": qtd_acessos,
        "interesses": [dict(zip(campos_lead, r)) for r in leads],
    }


@router.post("/api/usuarios-site/{usuario_id}")
def editar_usuario_site(usuario_id: int, payload: dict, usuario: dict = Depends(exigir_admin)):
    """Edita nome/empresa/cargo/e-mail de uma conta do SITE (password_hash = '',
    ver comentario em /api/dashboard). Username/role/senha NAO sao editaveis aqui
    -- username continua sendo o e-mail ORIGINAL do cadastro (ver
    webapp/main.py::site_cadastrar); trocar o e-mail aqui de proposito nao
    reescreve o username junto (evitaria duplicidade sem o mesmo loop de fallback
    que so existe no cadastro -- se um dia precisar sincronizar os dois, e'
    trabalho novo). Valida formato de e-mail (mesmo padrao simples de
    webapp/main.py::_email_valido) e checa duplicidade contra QUALQUER outra conta
    (site ou staff) com o mesmo e-mail antes de salvar."""
    nome = (payload.get("nome") or "").strip() or None
    empresa = (payload.get("empresa") or "").strip() or None
    cargo = (payload.get("cargo") or "").strip() or None
    email = (payload.get("email") or "").strip().lower()
    if not email or not _email_valido(email):
        raise HTTPException(status_code=400, detail="E-mail invalido")
    conn = get_connection(pooled=True)
    try:
        alvo = conn.execute(
            "SELECT id FROM admin_usuarios WHERE id = ? AND password_hash = ''", (usuario_id,)
        ).fetchone()
        if alvo is None:
            raise HTTPException(status_code=404, detail="Usuario do site nao encontrado")
        duplicado = conn.execute(
            "SELECT 1 FROM admin_usuarios WHERE lower(email) = ? AND id != ?", (email, usuario_id)
        ).fetchone()
        if duplicado:
            raise HTTPException(status_code=409, detail="Ja existe uma conta com esse e-mail")
        conn.execute(
            "UPDATE admin_usuarios SET nome = ?, empresa = ?, cargo = ?, email = ? WHERE id = ?",
            (nome, empresa, cargo, email, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# Exclusao de usuario do site: reaproveita DE PROPOSITO a MESMA rota generica
# usada pra excluir conta de staff (DELETE /api/usuarios/{usuario_id}, mais
# abaixo neste arquivo) -- ela ja opera sobre `admin_usuarios` por id, sem
# filtrar por password_hash, e ja trata o FK corretamente (admin_sessoes ON
# DELETE CASCADE, admin_acessos_log ON DELETE SET NULL + username_snapshot). A
# guarda do "ultimo admin ativo" daquela rota nunca dispara pra um usuario do
# site (role sempre 'usuario' nesse fluxo), entao nao ha necessidade de uma rota
# separada -- ver excluir_usuario() abaixo.


# ============ Interessados / Leads ("Quero saber mais") ============
@router.get("/api/leads")
def listar_leads(usuario: dict = Depends(exigir_admin)):
    """Quem clicou 'Quero saber mais' (POST /api/interesse, site principal) --
    reaproveita admin_acessos_log (evento='interesse_lead'), sem tabela nova.
    `contatado` (coluna generica em admin_acessos_log, ver seed.py) alimenta o
    indicador de 'precisa ser abordado' no frontend."""
    conn = get_connection(pooled=True)
    try:
        rows = conn.execute(
            "SELECT l.id, u.nome, u.email, u.empresa, u.cargo, l.criado_em, l.contatado "
            "FROM admin_acessos_log l JOIN admin_usuarios u ON u.id = l.usuario_id "
            "WHERE l.evento = 'interesse_lead' ORDER BY l.criado_em DESC LIMIT 300"
        ).fetchall()
    finally:
        conn.close()
    campos = ["id", "nome", "email", "empresa", "cargo", "criado_em", "contatado"]
    return {"leads": [dict(zip(campos, r)) for r in rows]}


@router.post("/api/leads/{log_id}/contatado")
def marcar_lead_contatado(log_id: int, payload: dict, usuario: dict = Depends(exigir_admin)):
    contatado = bool(payload.get("contatado"))
    conn = get_connection(pooled=True)
    try:
        row = conn.execute(
            "SELECT id FROM admin_acessos_log WHERE id = ? AND evento = 'interesse_lead'", (log_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Lead nao encontrado")
        conn.execute("UPDATE admin_acessos_log SET contatado = ? WHERE id = ?", (contatado, log_id))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ============ Atividade (sessoes agregadas: login -> logout/proximo login) ============
@router.get("/api/atividade")
def atividade(limit: int = 300, usuario_id: int = None, usuario: dict = Depends(exigir_admin)):
    """Visao agregada e legivel de 'quem entrou, quando, o que visitou, por quanto
    tempo' -- reaproveita admin_acessos_log (login/logout/view_aba/interesse_lead,
    ja gravados por outros fluxos), sem nenhum sistema de analytics novo. Uma
    'sessao' comeca num evento 'login' e termina no proximo 'logout' OU no proximo
    'login' da MESMA pessoa (o que vier primeiro) -- cobre o caso comum de fechar
    a aba sem clicar em nada (nao ha botao de Sair no site publico, ver CLAUDE.md).
    Agrupamento feito em Python (nao SQL) de proposito -- o volume de
    admin_acessos_log e pequeno o suficiente pra isso ser simples e correto, em vez
    de uma janela SQL correlacionada mais dificil de revisar.

    `usuario_id` (opcional): restringe a MESMA logica de agrupamento a uma pessoa
    so -- usado pelo modal de drill-down por usuario (staff E site, ver admin.js)
    pra montar uma timeline all-in-one (sessoes + paginas visitadas + manifestacoes
    de interesse) em vez de uma lista de eventos crus. Sem esse filtro, mantem o
    comportamento antigo: so origem='site' (pensado originalmente pra uma visao
    GERAL, que nao tem mais tela propria no admin -- ver CLAUDE.md -- mas a rota
    continua servindo o drill-down por pessoa). COM o filtro, nao restringe mais
    por origem (drill-down de staff usa origem='admin', que ficaria de fora do
    filtro antigo)."""
    limit = max(1, min(limit, 1000))
    conn = get_connection(pooled=True)
    try:
        condicoes = ["evento IN ('login', 'logout', 'view_aba', 'interesse_lead')"]
        params = []
        if usuario_id is not None:
            condicoes.append("usuario_id = ?")
            params.append(usuario_id)
        else:
            condicoes.append("origem = 'site'")
        rows = conn.execute(
            "SELECT usuario_id, username_snapshot, origem, evento, detalhe, criado_em "
            "FROM admin_acessos_log WHERE " + " AND ".join(condicoes) + " ORDER BY usuario_id, criado_em",
            tuple(params),
        ).fetchall()
    finally:
        conn.close()

    sessoes = []
    atual = None
    for usuario_id_linha, username, origem, evento, detalhe, criado_em in rows:
        if evento == "login":
            if atual:
                sessoes.append(atual)
            atual = {
                "usuario_id": usuario_id_linha,
                "username": username,
                "origem": origem,
                "entrada": criado_em,
                "saida": None,
                "paginas": [],
                "interesses": [],
            }
        elif atual is not None and atual["usuario_id"] == usuario_id_linha:
            if evento == "logout":
                atual["saida"] = criado_em
                sessoes.append(atual)
                atual = None
            elif evento == "view_aba":
                atual["paginas"].append(detalhe)
            elif evento == "interesse_lead":
                atual["interesses"].append(criado_em)
    if atual:
        sessoes.append(atual)

    sessoes.sort(key=lambda s: s["entrada"], reverse=True)
    sessoes = sessoes[:limit]

    from datetime import datetime as _dt

    resultado = []
    for s in sessoes:
        duracao_min = None
        if s["saida"]:
            try:
                entrada_dt = _dt.fromisoformat(s["entrada"])
                saida_dt = _dt.fromisoformat(s["saida"])
                duracao_min = round((saida_dt - entrada_dt).total_seconds() / 60, 1)
            except ValueError:
                duracao_min = None
        resultado.append(
            {
                "username": s["username"],
                "origem": s["origem"],
                "entrada": s["entrada"],
                "saida": s["saida"],
                "duracao_min": duracao_min,
                "paginas_visitadas": len(s["paginas"]),
                "paginas": s["paginas"][:20],
                "interesses": s["interesses"],
            }
        )
    return {"sessoes": resultado}


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


@router.post("/api/usuarios/{usuario_id}/role")
def alterar_role(usuario_id: int, payload: dict, usuario: dict = Depends(exigir_admin)):
    """Promove/rebaixa uma conta existente entre 'admin' e 'usuario' -- ate aqui o
    role so era definido na criacao (POST /api/usuarios). Mesma guarda do ultimo
    admin ja usada em ativo/desativar e excluir: nao deixa rebaixar (admin ->
    usuario) o ULTIMO admin ativo restante, pra nunca travar o painel sem ninguem
    pra reativar ninguem."""
    role_novo = payload.get("role")
    if role_novo not in ("admin", "usuario"):
        raise HTTPException(status_code=400, detail="Papel invalido (use 'admin' ou 'usuario')")
    conn = get_connection(pooled=True)
    try:
        row = conn.execute("SELECT id, role, ativo FROM admin_usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        _, role_atual, ativo = row
        if (
            role_novo == "usuario"
            and role_atual == "admin"
            and ativo
            and _contar_admins_ativos(conn, excluir_id=usuario_id) == 0
        ):
            raise HTTPException(status_code=409, detail="Nao e possivel rebaixar o ultimo admin ativo")
        conn.execute("UPDATE admin_usuarios SET role = ? WHERE id = ?", (role_novo, usuario_id))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/usuarios/{usuario_id}/senha")
def alterar_senha(usuario_id: int, payload: dict, usuario: dict = Depends(exigir_admin)):
    """Reset administrativo de senha (NAO e' fluxo de "esqueci minha senha" -- so um
    admin pode fazer isso, por qualquer outro usuario). Mesmo esquema de hash de
    sempre (gerar_hash_senha). Invalida TODAS as sessoes ativas do usuario-alvo na
    hora -- sem isso, uma sessao aberta antes da troca continuaria valida com a
    senha antiga ja sem efeito, ate expirar sozinha (24h)."""
    senha_nova = payload.get("senha_nova") or ""
    if len(senha_nova) < 8:
        raise HTTPException(status_code=400, detail="Senha precisa ter pelo menos 8 caracteres")
    conn = get_connection(pooled=True)
    try:
        row = conn.execute("SELECT id FROM admin_usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        conn.execute(
            "UPDATE admin_usuarios SET password_hash = ? WHERE id = ?",
            (gerar_hash_senha(senha_nova), usuario_id),
        )
        conn.execute("DELETE FROM admin_sessoes WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.delete("/api/usuarios/{usuario_id}")
def excluir_usuario(usuario_id: int, usuario: dict = Depends(exigir_admin)):
    """Exclusao de conta em admin_usuarios -- generica por `id`, entao tambem e'
    reaproveitada pelo frontend pra excluir um USUARIO DO SITE (password_hash = '',
    ver /api/usuarios-site acima), nao so conta de staff. A guarda do "ultimo admin
    ativo" abaixo so tem efeito quando role == 'admin' (nunca o caso de um usuario
    do site), entao nenhum comportamento muda pra esse uso novo."""
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
    """So login/logout de proposito -- NAO inclui 'view_aba' (navegacao por aba),
    que gera MUITO mais volume e afogaria o sinal de "quem entrou/saiu" que esta
    lista existe pra mostrar. Navegacao por aba fica visivel no drill-down POR
    PESSOA (GET .../usuarios/{id}/acessos), onde faz mais sentido olhar."""
    limit = max(1, min(limit, 500))
    conn = get_connection(pooled=True)
    try:
        rows = conn.execute(
            "SELECT username_snapshot, origem, evento, ip, criado_em FROM admin_acessos_log "
            "WHERE evento IN ('login', 'logout') ORDER BY id DESC LIMIT ?",
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
    """Drill-down do log de acessos por PESSOA (pedido do usuario) -- reune
    login/logout (V1) + navegacao por aba ('view_aba', V2 -- ambos em
    admin_acessos_log, so filtrando por usuario_id). `eventos` fica limitado a 200
    linhas mais recentes (login+logout+view_aba misturados) -- navegacao por aba
    gera MUITO mais volume que login/logout (uma linha por troca de aba, de cada
    usuario), entao esse teto existe de proposito pra nao devolver uma resposta
    gigante; nao ha paginacao ainda (fora de escopo por ora, ver CLAUDE.md).
    NAO inclui mais historico de busca (usuario_busca_historico) -- essa tabela
    era da feature "Transacoes Salvas", removida (ver
    docs/archive/removed-features.md)."""
    conn = get_connection(pooled=True)
    try:
        alvo = conn.execute("SELECT username FROM admin_usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if alvo is None:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        rows = conn.execute(
            "SELECT origem, evento, detalhe, ip, criado_em FROM admin_acessos_log "
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
        "eventos": [
            {"origem": r[0], "evento": r[1], "detalhe": r[2], "ip": r[3], "criado_em": r[4]} for r in rows
        ],
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
        # uf/municipio adicionados 2026-09-16 junto com a expansao de
        # CAMPOS_CORRIGIVEIS (ver src/unify.py) -- sem isso, selecionar "UF" ou
        # "Município" no formulario de correcao pre-preenchia com undefined (o
        # objeto de resultado nao tinha essas chaves).
        if termo.isdigit():
            rows = conn.execute(
                "SELECT id, cliente, cnpj, setor_bndes, subsetor_bndes, segmento, uf, municipio FROM operations "
                "WHERE id = ? LIMIT 20",
                (int(termo),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, cliente, cnpj, setor_bndes, subsetor_bndes, segmento, uf, municipio FROM operations "
                "WHERE cliente ILIKE ? ORDER BY id DESC LIMIT 20",
                (f"%{termo}%",),
            ).fetchall()
    finally:
        conn.close()
    campos = ["id", "cliente", "cnpj", "setor_bndes", "subsetor_bndes", "segmento", "uf", "municipio"]
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


# "Saude do banco" (proxy via pg_database_size/pg_stat_*) foi REMOVIDA do painel
# em 2026-09-22 (reestruturacao focada em usuarios/leads/comportamento, pedido
# explicito do usuario) -- ver docs/archive/removed-features.md secao 4 pro
# codigo original, caso precise reconstruir como uma tela tecnica separada.
