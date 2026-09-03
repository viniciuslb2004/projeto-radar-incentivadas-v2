"""Migracao unica: copia os dados do SQLite local (data/radar.db, o app antigo
dual-mode) para o Supabase Postgres novo (schema ja criado por src/db.py).

So roda uma vez, na virada pra 100% online -- depois disso o SQLite local deixa de
ser tocado por qualquer coisa (ver decisao do usuario: nada mais fica local, so
Supabase). Nao apaga nem mexe no arquivo .db local, so LE dele.

Usa COPY (psycopg3 `cursor.copy(...)`) em vez de insert linha a linha -- muito mais
rapido para as ~30 mil linhas de operations. Roda ANTES de qualquer refresh contra o
Supabase, para nao brigar com o REBUILD_EACH_REFRESH (de_para_cnae) nem com o
incremental (bndes_raw/finep_*_raw, que so processam raw_id novo).
"""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

import psycopg

SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "radar.db"

# Ordem sem significado real (nao ha FK entre estas tabelas), so lista todas as que
# tem dado de verdade -- refresh_log/refresh_editais_log (so historico de execucao)
# ficam de fora de proposito, nao valem a pena migrar.
TABELAS = [
    "de_para_cnae",
    "cnpj_cnae",
    "bndes_raw",
    "finep_credito_direto_raw",
    "finep_credito_descentralizado_raw",
    "finep_nao_aprovados_raw",
    "operations",
    "editais_raw",
]


def _colunas_sqlite(conn_sqlite, tabela):
    cur = conn_sqlite.execute(f"PRAGMA table_info({tabela})")
    return [row[1] for row in cur.fetchall()]


def migrar_tabela(conn_sqlite, conn_pg, tabela):
    colunas = _colunas_sqlite(conn_sqlite, tabela)
    col_list = ", ".join(colunas)
    cur_sqlite = conn_sqlite.execute(f"SELECT {col_list} FROM {tabela}")
    linhas = cur_sqlite.fetchall()
    if not linhas:
        print(f"{tabela}: 0 linhas no SQLite, nada a migrar.")
        return 0

    with conn_pg.cursor() as cur_pg:
        cur_pg.execute(f"DELETE FROM {tabela}")  # tabela recem-criada, mas idempotente se rodar 2x
        with cur_pg.copy(f"COPY {tabela} ({col_list}) FROM STDIN") as copy:
            for linha in linhas:
                copy.write_row(linha)
    conn_pg.commit()

    n_pg = conn_pg.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
    status = "OK" if n_pg == len(linhas) else "DIVERGENCIA"
    print(f"{tabela}: {len(linhas)} linhas no SQLite -> {n_pg} no Supabase [{status}]")

    # COPY com id explicito NAO avanca a sequence por tras da coluna IDENTITY --
    # sem isso, o proximo INSERT automatico (proximo refresh incremental) colidiria
    # com um id ja usado pela migracao. So aplica em tabelas que realmente tem
    # coluna `id` do tipo identity (editais_raw usa o id da FINEP, sem sequence).
    if "id" in colunas and tabela != "editais_raw":
        conn_pg.execute(
            f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {tabela}), 1))"
        )
        conn_pg.commit()

    return len(linhas)


def main():
    if not SQLITE_PATH.exists():
        print(f"Arquivo SQLite nao encontrado em {SQLITE_PATH}")
        sys.exit(1)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL nao configurada (esperado no .env).")
        sys.exit(1)

    conn_sqlite = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    conn_pg = psycopg.connect(database_url)

    total = 0
    try:
        for tabela in TABELAS:
            total += migrar_tabela(conn_sqlite, conn_pg, tabela)
    finally:
        conn_sqlite.close()
        conn_pg.close()

    print(f"\nMigracao concluida: {total} linhas no total.")


if __name__ == "__main__":
    main()
