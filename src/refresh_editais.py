"""Orquestra o pipeline diario dos editais da FINEP: fetch (com upsert, preservando
resumo_ia) -> embeddings dos abertos. Roda separado do refresh.py semanal (BNDES/FINEP
historico) porque editais tem prazo real e o fetch e barato -- vale manter mais fresco."""
import datetime
import sys
import traceback

from db import get_connection, init_db
import finep_editais
import editais_embeddings


def run_refresh_editais() -> str:
    """Devolve o status final ('ok'/'erro') -- ver mesmo comentario em refresh.py:
    sem isso uma falha total ficava so no banco (refresh_editais_log.status='erro')
    e o workflow do GitHub Actions aparecia verde mesmo tendo falhado por completo."""
    init_db()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"=== Refresh de editais iniciado em {started_at} ===")

    status = "ok"
    detalhe = ""
    total = abertos = 0

    try:
        total, abertos = finep_editais.refresh_editais()
        editais_embeddings.build_editais_embeddings()
    except Exception:
        status = "erro"
        detalhe = traceback.format_exc()
        print(detalhe)

    finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO refresh_editais_log (started_at, finished_at, total_editais, abertos, status, detalhe)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (started_at, finished_at, total, abertos, status, detalhe),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"=== Refresh de editais finalizado em {finished_at} (status={status}) ===")
    print(f"Total: {total} | Abertos: {abertos}")
    return status


if __name__ == "__main__":
    sys.exit(1 if run_refresh_editais() == "erro" else 0)
