"""Autenticacao do painel de admin -- e, por uma EXCECAO DOCUMENTADA e deliberada
(ver CLAUDE.md, secao "Painel de Admin"), tambem do login do site principal desde
que este passou a usar contas individuais em vez da senha unica `SITE_PASSWORD`.
Contas (`admin_usuarios`, com coluna `role`: 'admin' | 'usuario') com senha com hash
(PBKDF2-HMAC-SHA256) + sessao por token opaco (`admin_sessoes`), COMPARTILHADA entre
o painel `/admin` e o site principal -- um `admin` acessa os dois; um `usuario`
comum acessa so o site principal (ver `exigir_admin` vs `sessao_atual` abaixo).

Formato do hash de senha: "pbkdf2_sha256$<iteracoes>$<salt_base64>$<hash_base64>" -- a
senha em si NUNCA e armazenada nem loga em lugar nenhum, so este hash. Ver
webapp/admin/seed.py para como as contas seed sao criadas, e `gerar_hash_senha()`
abaixo para como uma conta nova (criada pelo painel) gera o hash dela.
"""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from db import get_connection

SESSION_COOKIE = "admin_session"
SESSION_TTL_HORAS = 24
PBKDF2_ALGORITMO = "pbkdf2_sha256"
PBKDF2_ITERACOES = 600_000


def gerar_hash_senha(senha: str) -> str:
    """Gera um hash no MESMO formato/parametros usados pelas contas seed (ver
    seed.py) -- usado só quando uma conta nova é criada pelo próprio painel
    (POST /admin/api/usuarios). A senha em texto puro fica só na memória deste
    request, nunca é persistida nem devolvida na resposta."""
    salt = os.urandom(16)
    hash_calculado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, PBKDF2_ITERACOES)
    return f"{PBKDF2_ALGORITMO}${PBKDF2_ITERACOES}${base64.b64encode(salt).decode()}${base64.b64encode(hash_calculado).decode()}"


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Recalcula o PBKDF2-HMAC-SHA256 com o mesmo salt/iteracoes do hash armazenado e
    compara com hmac.compare_digest (nunca ==) para evitar timing attack."""
    try:
        algoritmo, iteracoes_str, salt_b64, hash_b64 = hash_armazenado.split("$")
        if algoritmo != PBKDF2_ALGORITMO:
            return False
        iteracoes = int(iteracoes_str)
        salt = base64.b64decode(salt_b64)
        hash_esperado = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    hash_calculado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, iteracoes)
    return hmac.compare_digest(hash_calculado, hash_esperado)


def _cookie_secure() -> bool:
    # Mesmo sinal de "estamos no deploy hospedado" ja usado em webapp/main.py
    # (VERCEL e a env var que a propria Vercel expoe).
    return bool(os.environ.get("VERCEL"))


def autenticar_credenciais(conn, username: str, senha: str):
    """Verifica username+senha contra admin_usuarios (precisa estar ativo) e devolve
    {'id','username','role','status'} se validas, None caso contrario -- usado tanto
    pelo login do painel /admin quanto pelo login do site principal (MESMA tabela de
    contas, ver docstring do modulo). NAO filtra por `status` aqui de proposito --
    devolve o usuario mesmo com status='pendente'/'rejeitado' pra quem chamou poder
    mostrar uma mensagem especifica (ver `mensagem_status_bloqueado`) em vez do
    generico "usuario ou senha incorretos"."""
    row = conn.execute(
        "SELECT id, password_hash, ativo, role, status FROM admin_usuarios WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None:
        return None
    usuario_id, password_hash, ativo, role, status = row
    if not ativo or not verificar_senha(senha, password_hash):
        return None
    return {"id": usuario_id, "username": username, "role": role, "status": status}


def mensagem_status_bloqueado(status: str):
    """Devolve uma mensagem de login clara pra status='pendente'/'rejeitado', ou
    None se status='aprovado' (login pode prosseguir). Contas seed/antigas (criadas
    antes deste cadastro publico existir) tem status='aprovado' por default via
    migracao (ver seed.py), entao nunca caem aqui."""
    if status == "pendente":
        return "Sua conta ainda nao foi aprovada por um administrador."
    if status == "rejeitado":
        return "Sua solicitacao de conta foi rejeitada."
    return None


def criar_sessao(conn, usuario_id: int) -> str:
    token = secrets.token_urlsafe(32)
    agora = datetime.now(timezone.utc)
    expira_em = agora + timedelta(hours=SESSION_TTL_HORAS)
    conn.execute(
        "INSERT INTO admin_sessoes (token, usuario_id, criado_em, expira_em) VALUES (?, ?, ?, ?)",
        (token, usuario_id, agora.isoformat(), expira_em.isoformat()),
    )
    conn.commit()
    return token


def encerrar_sessao(conn, token: str) -> None:
    conn.execute("DELETE FROM admin_sessoes WHERE token = ?", (token,))
    conn.commit()


def validar_sessao_token(conn, token: str):
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id, u.username, u.ativo, u.role, s.expira_em "
        "FROM admin_sessoes s JOIN admin_usuarios u ON u.id = s.usuario_id "
        "WHERE s.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None
    usuario_id, username, ativo, role, expira_em = row
    if not ativo:
        return None
    expira = datetime.fromisoformat(expira_em)
    if expira.tzinfo is None:
        expira = expira.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expira:
        return None
    return {"id": usuario_id, "username": username, "role": role}


def definir_cookie_sessao(response: Response, token: str) -> None:
    # path="/" (nao mais so "/admin"): a mesma sessao agora vale tanto pro painel de
    # admin quanto pro site principal (ver docstring do modulo) -- o cookie precisa
    # ser enviado em requisicoes pra ambos.
    #
    # BUG REAL encontrado ao vivo (2026-09-10, antes de ir pra producao): contas que
    # ja tinham logado no painel /admin ANTES desta mudanca de path (versao antiga,
    # path="/admin") continuam com aquele cookie guardado no navegador. Depois desta
    # mudanca, um login novo grava um SEGUNDO cookie de mesmo nome com path="/" -- o
    # navegador manda os DOIS num request pro site principal (`Cookie: admin_session=
    # <antigo>; admin_session=<novo>`), e o parser de cookie do Starlette
    # (`cookie_parser` em starlette/requests.py) e so um dict preenchido em ORDEM DE
    # ITERACAO da string recebida -- last-write-wins, sem nenhuma logica de
    # especificidade de path (diferente do que um navegador faria sozinho). Dependendo
    # da ordem que o navegador decidiu mandar as duas, `request.cookies["admin_session"]`
    # podia pegar o token ANTIGO/invalido e derrubar a sessao (401 imprevisivel logo
    # depois de um login bem-sucedido). Corrigido limpando explicitamente o cookie no
    # path antigo (`/admin`) toda vez que uma sessao nova e criada -- depois do
    # primeiro login/logout no esquema novo, o navegador nunca mais tem os dois ao
    # mesmo tempo.
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_HORAS * 3600,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


def limpar_cookie_sessao(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    # Mesmo motivo do comentario em definir_cookie_sessao -- garante que um cookie
    # remanescente do esquema antigo (path="/admin") tambem some no logout.
    response.delete_cookie(SESSION_COOKIE, path="/admin")


def exigir_admin(request: Request):
    """Dependency que barra qualquer rota de dado do painel /admin sem sessao
    valida E com role='admin' -- uma conta 'usuario' (site principal) autentica
    mas nao passa daqui. Nunca confia em esconder a rota so no frontend."""
    token = request.cookies.get(SESSION_COOKIE)
    conn = get_connection(pooled=True)
    try:
        usuario = validar_sessao_token(conn, token)
    finally:
        conn.close()
    if usuario is None or usuario["role"] != "admin":
        raise HTTPException(status_code=401, detail="Sessao invalida ou expirada")
    return usuario


def verificar_acesso_principal(request: Request):
    """Gate do SITE PRINCIPAL (usado por webapp/main.py::_verificar_acesso) -- e a
    parte da EXCECAO documentada a segregacao (ver docstring do modulo e CLAUDE.md):
    o login do site inteiro passou a depender de admin_usuarios. Abre UMA conexao
    pra resolver os dois casos:
      1. Nenhuma conta cadastrada ainda (banco novo/dev local sem seed rodado) --
         acesso livre, mesmo espirito de rodar sem SITE_PASSWORD configurada antes.
      2. Pelo menos uma conta existe -- exige sessao valida (qualquer role; so as
         rotas do painel /admin, via exigir_admin, exigem role='admin' especificamente).
    Levanta HTTPException(401) se autenticacao for necessaria e a sessao for
    invalida/ausente; devolve None (silenciosamente) nos outros dois casos."""
    conn = get_connection(pooled=True)
    try:
        tem_conta = conn.execute("SELECT 1 FROM admin_usuarios LIMIT 1").fetchone() is not None
        if not tem_conta:
            return None
        token = request.cookies.get(SESSION_COOKIE)
        usuario = validar_sessao_token(conn, token)
    finally:
        conn.close()
    if usuario is None:
        raise HTTPException(status_code=401, detail="Acesso restrito")
    return usuario


def registrar_acesso(conn, usuario_id, username: str, origem: str, evento: str, ip: str = None, detalhe: str = None) -> None:
    """Log de acessos (ver CLAUDE.md) -- login/logout (V1) + navegacao por aba
    ('view_aba', V2, `detalhe` = nome da aba). username_snapshot garante que o log
    continua legivel mesmo depois de um usuario ser excluido de verdade
    (usuario_id vira NULL)."""
    conn.execute(
        "INSERT INTO admin_acessos_log (usuario_id, username_snapshot, origem, evento, ip, detalhe, criado_em) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (usuario_id, username, origem, evento, ip, detalhe, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
