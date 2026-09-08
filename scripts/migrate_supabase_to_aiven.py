"""Migracao unica: copia todas as tabelas do Postgres antigo (Supabase, quase no limite
de armazenamento do plano gratuito) para o novo (Aiven, plano gratuito com mais espaco).

Le a origem de DATABASE_URL (.env) e o destino de DATABASE_URL_AIVEN (.env) -- ambos
Postgres, mesmo schema (criado via `python src/db.py` contra o destino antes de rodar
este script). Usa o protocolo COPY do psycopg3 (muito mais rapido que INSERT linha a
linha para tabelas grandes, ja confirmado nesta sessao com outras cargas).

Uso: python scripts/migrate_supabase_to_aiven.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg
from dotenv import load_dotenv

load_dotenv()

ORIGEM_URL = os.environ["DATABASE_URL"]
DESTINO_URL = os.environ["DATABASE_URL_AIVEN"]

# Ordem nao importa pra correcao (nao ha foreign keys entre essas tabelas neste
# schema), mas segue a ordem "natural" do pipeline por clareza no log.
TABELAS = [
    "bndes_raw",
    "finep_credito_direto_raw",
    "finep_credito_descentralizado_raw",
    "finep_nao_aprovados_raw",
    "de_para_cnae",
    "cnpj_cnae",
    "operations",
    "operations_correcoes_manuais",
    "editais_raw",
    "linhas_incentivadas",
    "refresh_log",
    "refresh_editais_log",
]


def _colunas(conn, tabela):
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        [tabela],
    )
    return [r[0] for r in cur.fetchall()]


def migrar_tabela(conn_origem, conn_destino, tabela):
    cols_origem = _colunas(conn_origem, tabela)
    cols_destino = _colunas(conn_destino, tabela)
    if cols_origem != cols_destino:
        # Colunas em comum, na ordem do destino -- protege contra qualquer migracao
        # de schema que tenha rodado num lado e nao no outro entre o momento em que
        # o schema foi criado no Aiven e agora.
        comuns = [c for c in cols_destino if c in cols_origem]
        print(f"  aviso: colunas diferentes em {tabela}, usando so as em comum: {comuns}")
        cols = comuns
    else:
        cols = cols_origem
    lista_cols = ", ".join(f'"{c}"' for c in cols)

    cur_destino = conn_destino.cursor()
    cur_destino.execute(f"TRUNCATE TABLE {tabela} RESTART IDENTITY CASCADE")

    t0 = time.time()
    n = 0
    with conn_origem.cursor().copy(f"COPY (SELECT {lista_cols} FROM {tabela}) TO STDOUT") as copy_out:
        with cur_destino.copy(f"COPY {tabela} ({lista_cols}) FROM STDIN") as copy_in:
            for data in copy_out:
                copy_in.write(data)
                n += 1
    conn_destino.commit()
    print(f"  {tabela}: copiado em {time.time() - t0:.1f}s")


def conferir_contagens(conn_origem, conn_destino, tabela):
    n_origem = conn_origem.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
    n_destino = conn_destino.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
    status = "OK" if n_origem == n_destino else "DIVERGENTE!!"
    print(f"  {tabela}: origem={n_origem} destino={n_destino} [{status}]")
    return n_origem == n_destino


def main():
    conn_origem = psycopg.connect(ORIGEM_URL)
    conn_destino = psycopg.connect(DESTINO_URL)
    try:
        print("Copiando tabelas...")
        for tabela in TABELAS:
            migrar_tabela(conn_origem, conn_destino, tabela)

        print("\nConferindo contagens...")
        tudo_ok = True
        for tabela in TABELAS:
            if not conferir_contagens(conn_origem, conn_destino, tabela):
                tudo_ok = False

        print("\n" + ("TUDO OK: contagens batem em todas as tabelas." if tudo_ok else "ATENCAO: alguma tabela divergiu, ver acima."))
    finally:
        conn_origem.close()
        conn_destino.close()


if __name__ == "__main__":
    main()
