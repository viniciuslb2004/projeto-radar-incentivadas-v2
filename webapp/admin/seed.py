"""Script de migracao/seed do painel de admin -- roda UMA VEZ (nao faz parte do
refresh semanal nem de nenhum startup automatico da webapp) para criar as tabelas
`admin_usuarios`/`admin_sessoes` e inserir a conta inicial.

Uso: `python webapp/admin/seed.py` (a partir da raiz do repo, com DATABASE_URL
configurada no ambiente ou em .env).

De proposito SEM retry agressivo: e uma migracao pequena (2 CREATE TABLE + 1
INSERT) contra o mesmo Postgres de producao que ja teve um incidente real de
disco cheio num backfill mal planejado (ver CLAUDE.md, secao "Painel de Admin")
-- se a conexao falhar, o script para e imprime o erro, sem ficar tentando de
novo sozinho. Rode de novo manualmente depois de confirmar o estado do banco.

O hash abaixo ja foi gerado e conferido fora deste repositorio (PBKDF2-HMAC-SHA256,
600.000 iteracoes) -- a senha em texto puro NUNCA passou por aqui e nunca deve.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from db import get_connection  # noqa: E402

SEED_USERNAME = "admin"
SEED_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$KQBAs1kUH2wrowdJIZg4ew==$+cmKRhybJ0eB2xVJmOclzJTLF8Jg+Bipcx8DqS/pEZc="
)

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
"""


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
        print("Tabelas admin_usuarios/admin_sessoes prontas (ja existiam ou acabaram de ser criadas).")

        ja_existe = conn.execute(
            "SELECT 1 FROM admin_usuarios WHERE username = ?", (SEED_USERNAME,)
        ).fetchone()
        if ja_existe:
            print(f"Usuario '{SEED_USERNAME}' ja existe, nada a inserir.")
        else:
            conn.execute(
                "INSERT INTO admin_usuarios (username, password_hash, ativo, criado_em) "
                "VALUES (?, ?, TRUE, ?)",
                (SEED_USERNAME, SEED_PASSWORD_HASH, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            print(f"Usuario seed '{SEED_USERNAME}' inserido.")
    except Exception as e:
        print(f"ERRO durante a migracao/seed: {e}. Parando sem retry -- confira o estado do banco antes de rodar de novo.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
