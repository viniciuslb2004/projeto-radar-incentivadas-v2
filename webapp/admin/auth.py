"""Autenticacao do painel de admin -- sistema SEPARADO do login unico (`SITE_PASSWORD`)
do site publico (ver `_verificar_acesso` em webapp/main.py). Contas individuais
(`admin_usuarios`) com senha com hash (PBKDF2-HMAC-SHA256) + sessao por cookie assinado
opaco (`admin_sessoes`), nada disso reaproveita ou depende do mecanismo do site publico.

Formato do hash de senha: "pbkdf2_sha256$<iteracoes>$<salt_base64>$<hash_base64>" -- a
senha em si NUNCA e armazenada nem loga em lugar nenhum, so este hash. Ver
webapp/admin/seed.py para como a conta inicial e criada.
"""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response

from db import get_connection

SESSION_COOKIE = "admin_session"
SESSION_TTL_HORAS = 24
PBKDF2_ALGORITMO = "pbkdf2_sha256"


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


def _usuario_da_sessao(conn, token: str):
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id, u.username, u.ativo, s.expira_em "
        "FROM admin_sessoes s JOIN admin_usuarios u ON u.id = s.usuario_id "
        "WHERE s.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None
    usuario_id, username, ativo, expira_em = row
    if not ativo:
        return None
    expira = datetime.fromisoformat(expira_em)
    if expira.tzinfo is None:
        expira = expira.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expira:
        return None
    return {"id": usuario_id, "username": username}


def definir_cookie_sessao(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_HORAS * 3600,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/admin",
    )


def limpar_cookie_sessao(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/admin")


def exigir_admin(request: Request):
    """Dependency que barra qualquer rota de dado do admin sem sessao valida --
    nunca confia em esconder a rota so no frontend."""
    token = request.cookies.get(SESSION_COOKIE)
    conn = get_connection(pooled=True)
    try:
        usuario = _usuario_da_sessao(conn, token)
    finally:
        conn.close()
    if usuario is None:
        raise HTTPException(status_code=401, detail="Sessao invalida ou expirada")
    return usuario
