"""Orquestra o pipeline diario dos editais da FINEP: fetch (com upsert, preservando
resumo_ia) -> embeddings dos abertos. Roda separado do refresh.py semanal (BNDES/FINEP
historico) porque editais tem prazo real e o fetch e barato -- vale manter mais fresco."""
import datetime
import sys
import traceback

from db import get_connection, init_db
import finep_editais
import editais_embeddings


def _registrar_inicio(started_at: str) -> int:
    """Grava a linha de `refresh_editais_log` logo no INICIO do run, com
    `finished_at` ainda NULL -- mesmo padrao/motivo de `refresh.py::_registrar_inicio`:
    e o que permite ao painel admin detectar "ja existe um refresh de editais em
    andamento" antes de disparar outro (`webapp/admin/routes.py`, checagem por
    `finished_at IS NULL`, que so funciona se essa janela existir de verdade)."""
    conn = get_connection()
    try:
        log_id = conn.execute(
            "INSERT INTO refresh_editais_log (started_at, status) VALUES (?, ?) RETURNING id",
            (started_at, "em_andamento"),
        ).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return log_id


def _finalizar_log(log_id: int, finished_at: str, total: int, abertos: int, status: str, detalhe: str) -> None:
    """Fecha a linha aberta por `_registrar_inicio` (mesmo `id`). Chamado de um
    `finally` em `run_refresh_editais` -- roda sempre, sucesso ou erro."""
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE refresh_editais_log
            SET finished_at = ?, total_editais = ?, abertos = ?, status = ?, detalhe = ?
            WHERE id = ?
            """,
            (finished_at, total, abertos, status, detalhe, log_id),
        )
        conn.commit()
    finally:
        conn.close()


def run_refresh_editais() -> str:
    """Devolve o status final ('ok'/'erro') -- ver mesmo comentario em refresh.py:
    sem isso uma falha total ficava so no banco (refresh_editais_log.status='erro')
    e o workflow do GitHub Actions aparecia verde mesmo tendo falhado por completo."""
    init_db()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"=== Refresh de editais iniciado em {started_at} ===")

    # Grava a linha do log JA AGORA (finished_at ainda NULL) -- ver docstring de
    # _registrar_inicio. Feito antes do fetch/embeddings, para que a janela "em
    # andamento" cubra o run inteiro.
    log_id = _registrar_inicio(started_at)

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
    finally:
        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _finalizar_log(log_id, finished_at, total, abertos, status, detalhe)

    print(f"=== Refresh de editais finalizado em {finished_at} (status={status}) ===")
    print(f"Total: {total} | Abertos: {abertos}")
    return status


if __name__ == "__main__":
    sys.exit(1 if run_refresh_editais() == "erro" else 0)
