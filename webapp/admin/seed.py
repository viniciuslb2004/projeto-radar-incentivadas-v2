"""Script de migracao/seed do painel de admin -- roda UMA VEZ (nao faz parte do
refresh semanal nem de nenhum startup automatico da webapp) para criar/atualizar as
tabelas `admin_usuarios`/`admin_sessoes`/`admin_acessos_log` e inserir as contas seed.

Uso: `python webapp/admin/seed.py` (a partir da raiz do repo, com DATABASE_URL
configurada no ambiente ou em .env).

De proposito SEM retry agressivo: e uma migracao pequena (poucos CREATE TABLE/ALTER
TABLE + alguns INSERT) contra o mesmo Postgres de producao que ja teve um incidente
real de disco cheio num backfill mal planejado (ver CLAUDE.md, secao "Painel de
Admin") -- se a conexao falhar, o script para e imprime o erro, sem ficar tentando
de novo sozinho. Rode de novo manualmente depois de confirmar o estado do banco.
Idempotente: pode ser rodado de novo com seguranca a qualquer momento (so cria o
que ainda nao existe).

Os hashes abaixo ja foram gerados e conferidos fora deste repositorio
(PBKDF2-HMAC-SHA256, 600.000 iteracoes) -- a senha em texto puro NUNCA passou por
aqui e nunca deve.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from db import get_connection  # noqa: E402

# (username, password_hash, role) -- role 'admin' acessa o painel /admin E o site
# principal; role 'usuario' so acessa o site principal (ver CLAUDE.md, secao
# "Painel de Admin" / acoplamento do login do site principal a admin_usuarios).
SEED_USUARIOS = [
    (
        "admin",
        "pbkdf2_sha256$600000$KQBAs1kUH2wrowdJIZg4ew==$+cmKRhybJ0eB2xVJmOclzJTLF8Jg+Bipcx8DqS/pEZc=",
        "admin",
    ),
    (
        "artica",
        "pbkdf2_sha256$600000$zYK/B8UsUm41UcnM3+Ey0g==$aIZdXtYxcUeozD2liZsmopwBlDlGpKKbjIS9JWAcILM=",
        "usuario",
    ),
]

SCHEMA_ADMIN = """
CREATE TABLE IF NOT EXISTS admin_usuarios (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessoes (
    token TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES admin_usuarios(id) ON DELETE CASCADE,
    criado_em TEXT NOT NULL,
    expira_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_sessoes_usuario ON admin_sessoes(usuario_id);

-- Log de acessos (V1 do item "log de acessos": so login/logout, ver CLAUDE.md).
-- username_snapshot (nunca so o id) para o log continuar legivel mesmo depois de
-- um usuario ser excluido de verdade (usuario_id vira NULL via ON DELETE SET NULL,
-- mas o texto do username permanece).
CREATE TABLE IF NOT EXISTS admin_acessos_log (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id INTEGER REFERENCES admin_usuarios(id) ON DELETE SET NULL,
    username_snapshot TEXT NOT NULL,
    origem TEXT NOT NULL,   -- 'site' (login principal) | 'admin' (painel /admin)
    evento TEXT NOT NULL,   -- 'login' | 'logout'
    ip TEXT,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_acessos_log_criado_em ON admin_acessos_log(criado_em);
"""

# ALTER TABLE separado (nao cabe em CREATE TABLE IF NOT EXISTS pra tabela que ja
# existia em producao sem essa coluna) -- default 'admin' porque a UNICA conta que
# ja existia em producao antes desta migracao (o proprio seed antigo) e um admin de
# verdade; contas 'usuario' novas sempre especificam o papel explicitamente na hora
# da insercao.
MIGRACAO_ROLE = "ALTER TABLE admin_usuarios ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'admin'"

# 'pendente' | 'aprovado' | 'rejeitado' -- cadastro publico (POST /api/registrar,
# ver webapp/main.py). Default 'aprovado' pelo MESMO motivo do MIGRACAO_ROLE acima:
# todas as contas que ja existiam antes desta coluna (seed + criadas pelo CRUD do
# painel) devem continuar logando normalmente sem precisar de aprovacao retroativa.
MIGRACAO_STATUS = "ALTER TABLE admin_usuarios ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'aprovado'"

# Coletado no cadastro publico (POST /api/registrar) so pra o admin ver junto do
# username na hora de aprovar/rejeitar -- SEM default (contas antigas ficam com
# email NULL, sem problema) e SEM nenhuma integracao de envio de e-mail (decisao
# explicita do usuario: so coletar o dado, nao mandar nada).
MIGRACAO_EMAIL = "ALTER TABLE admin_usuarios ADD COLUMN IF NOT EXISTS email TEXT"


def main():
    from datetime import datetime, timezone

    try:
        conn = get_connection()
    except Exception as e:
        print(f"ERRO: nao foi possivel conectar ao banco ({e}). Parando sem retry.")
        sys.exit(1)

    try:
        conn.execute(SCHEMA_ADMIN)
        conn.commit()
        print("Tabelas admin_usuarios/admin_sessoes/admin_acessos_log prontas.")

        conn.execute(MIGRACAO_ROLE)
        conn.commit()
        print("Coluna admin_usuarios.role pronta.")

        conn.execute(MIGRACAO_STATUS)
        conn.commit()
        print("Coluna admin_usuarios.status pronta.")

        conn.execute(MIGRACAO_EMAIL)
        conn.commit()
        print("Coluna admin_usuarios.email pronta.")

        for username, password_hash, role in SEED_USUARIOS:
            ja_existe = conn.execute(
                "SELECT 1 FROM admin_usuarios WHERE username = ?", (username,)
            ).fetchone()
            if ja_existe:
                print(f"Usuario '{username}' ja existe, nada a inserir.")
                continue
            conn.execute(
                "INSERT INTO admin_usuarios (username, password_hash, role, ativo, criado_em) "
                "VALUES (?, ?, ?, TRUE, ?)",
                (username, password_hash, role, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            print(f"Usuario seed '{username}' (role={role}) inserido.")
    except Exception as e:
        print(f"ERRO durante a migracao/seed: {e}. Parando sem retry -- confira o estado do banco antes de rodar de novo.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
