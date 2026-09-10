"""Rotas do painel de admin (`/admin/api/*`) -- pacote isolado, ver `webapp/admin/auth.py`
para a sessao/hash de senha e `webapp/admin/seed.py` para a migracao da conta inicial.

COMO REMOVER ESTE PAINEL INTEIRO (se um dia for descontinuado):
  1. Apagar as tabelas do banco: `DROP TABLE admin_sessoes; DROP TABLE admin_usuarios;`
  2. Apagar a pasta `webapp/admin/` inteira (este arquivo, auth.py, seed.py, __init__.py).
  3. Apagar `webapp/static/admin.html` e `webapp/static/js/admin.js` (+ admin.css, se existir).
  4. Remover a linha `app.include_router(admin_router, prefix="/admin")` (e o import
     correspondente) de `webapp/main.py`.
  5. Remover o rewrite `/admin` -> `/admin.html` de `vercel.json`.
Nada neste painel toca em tabela/rota/arquivo do site publico -- a remocao acima nao
afeta `operations`, `linhas_incentivadas`, `editais_raw` nem o login unico (SITE_PASSWORD).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from db import get_connection

from .auth import (
    SESSION_COOKIE,
    criar_sessao,
    definir_cookie_sessao,
    encerrar_sessao,
    exigir_admin,
    limpar_cookie_sessao,
    verificar_senha,
)

router = APIRouter()


@router.post("/api/login")
def login(payload: dict, response: Response):
    username = (payload.get("username") or "").strip()
    senha = payload.get("password") or ""
    conn = get_connection(pooled=True)
    try:
        row = conn.execute(
            "SELECT id, password_hash, ativo FROM admin_usuarios WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="Usuario ou senha incorretos")
        usuario_id, password_hash, ativo = row
        if not ativo or not verificar_senha(senha, password_hash):
            raise HTTPException(status_code=401, detail="Usuario ou senha incorretos")
        token = criar_sessao(conn, usuario_id)
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
    finally:
        conn.close()
    limpar_cookie_sessao(response)
    return {"ok": True}


@router.get("/api/me")
def me(usuario: dict = Depends(exigir_admin)):
    return {"username": usuario["username"]}


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
    }


@router.get("/api/usuarios")
def listar_usuarios(q: str = "", usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        termo = f"%{q.strip()}%" if q.strip() else "%"
        rows = conn.execute(
            "SELECT id, username, ativo, criado_em FROM admin_usuarios "
            "WHERE username ILIKE ? ORDER BY username",
            (termo,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "usuarios": [
            {"id": r[0], "username": r[1], "ativo": r[2], "criado_em": r[3]} for r in rows
        ]
    }


@router.post("/api/usuarios/{usuario_id}/ativo")
def alterar_ativo(usuario_id: int, payload: dict, usuario: dict = Depends(exigir_admin)):
    ativo = bool(payload.get("ativo"))
    conn = get_connection(pooled=True)
    try:
        row = conn.execute("SELECT id FROM admin_usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        conn.execute("UPDATE admin_usuarios SET ativo = ? WHERE id = ?", (ativo, usuario_id))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}
