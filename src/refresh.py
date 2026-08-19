"""Orquestra o pipeline semanal: download -> parse -> unify -> embeddings.

NAO roda o enriquecimento de CNAE da FINEP (enrich_cnae.py) -- esse e um job
pesado (varios GB) rodado separadamente, uma vez por mes.
"""
import datetime
import traceback

from db import drop_rebuild_tables, get_connection, init_db
import download
import parse_bndes
import parse_finep
import unify
import embeddings


def run_refresh():
    init_db()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"=== Refresh iniciado em {started_at} ===")

    conn = get_connection()
    try:
        drop_rebuild_tables(conn)
    finally:
        conn.close()

    status = "ok"
    detalhe = ""
    bndes_rows = finep_direto_rows = finep_desc_rows = ops_rows = pendentes = 0

    try:
        download.download_all()
        bndes_rows = parse_bndes.parse_bndes()
        finep_direto_rows, finep_desc_rows = parse_finep.parse_finep()
        parse_finep.parse_finep_nao_aprovados()
        ops_rows, pendentes = unify.build_operations()
        embeddings.build_embeddings()
    except Exception:
        status = "erro"
        detalhe = traceback.format_exc()
        print(detalhe)

    finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO refresh_log
                (started_at, finished_at, bndes_rows, finep_credito_direto_rows,
                 finep_credito_descentralizado_rows, operations_rows, setores_pendentes, status, detalhe)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (started_at, finished_at, bndes_rows, finep_direto_rows, finep_desc_rows, ops_rows, pendentes, status, detalhe),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"=== Refresh finalizado em {finished_at} (status={status}) ===")
    print(f"BNDES: {bndes_rows} | FINEP credito direto: {finep_direto_rows} | FINEP descentralizado: {finep_desc_rows}")
    print(f"Operations: {ops_rows} ({pendentes} com setor pendente)")


if __name__ == "__main__":
    run_refresh()
