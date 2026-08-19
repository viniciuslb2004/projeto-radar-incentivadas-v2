"""Orquestra o pipeline semanal: download -> parse -> unify -> embeddings.

NAO roda o enriquecimento de CNAE da FINEP (enrich_cnae.py) -- esse e um job
pesado (varios GB) rodado separadamente, uma vez por mes.

Incremental desde 2026-08: BNDES/FINEP republicam o historico INTEIRO do zero a cada
arquivo, mas o pipeline agora faz o diff em Python (ver incremental.py, unify.py,
embeddings.py) em vez de dropar e reconstruir bndes_raw/finep_*_raw/operations e
reembutir tudo toda semana -- so processa o que e realmente novo. de_para_cnae e os
agregados (agg_*) continuam em reload completo (baratos, sem risco de duplicacao).
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
        _, bndes_rows = parse_bndes.parse_bndes()
        _, _, finep_direto_rows, finep_desc_rows = parse_finep.parse_finep()
        parse_finep.parse_finep_nao_aprovados()
        resultado_unify = unify.build_operations()
        ops_rows = resultado_unify["total"]
        pendentes = resultado_unify["pendentes"]
        embeddings.build_embeddings(
            novos_ids=resultado_unify["novos_ids"],
            reclassificados_ids=resultado_unify["reclassificados_ids"],
        )
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
