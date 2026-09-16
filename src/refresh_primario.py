"""Orquestra o pipeline do Radar de Credito Primario (CVM): download -> parse ->
unify -> enriquecimento leve de emissores via BrasilAPI -- mesmo desenho de
refresh.py (BNDES/FINEP), rodando como um pipeline PROPRIO e SEPARADO (nao dentro de
refresh.py) porque a fonte/staging/tabela final sao completamente independentes
(CVM x BNDES/FINEP, sem nenhum dado compartilhado exceto o cache cnpj_cnae, que ja
foi desenhado para ser reaproveitado por multiplas fontes).

NAO roda o job pesado de enrich_cnae.py::enrich()/enrich_empresas() (bulk RFB, GBs de
download) -- so a chamada leve `enrich_pendentes_via_api` (BrasilAPI, 1 CNPJ por vez),
suficiente para o volume de emissores da CVM (~1.9 mil CNPJs distintos no total, bem
menor que o volume de CNPJs da FINEP)."""
import datetime
import sys
import traceback

from db import get_connection, init_db
import download_cvm
import parse_cvm
import unify_primario
import enrich_cnae
from sector_taxonomy import build_divisao_map


def _resolver_emissores_pendentes_via_api() -> list:
    conn = get_connection()
    try:
        cnpjs_pendentes = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT cnpj_emissor FROM operations_primario "
                "WHERE setor_emissor IS NULL AND cnpj_emissor IS NOT NULL"
            ).fetchall()
        }
        if not cnpjs_pendentes:
            return []
        divisao_map = build_divisao_map(conn)
        enrich_cnae.enrich_pendentes_via_api(conn, cnpjs_pendentes, divisao_map)
    finally:
        conn.close()
    return unify_primario.reclassificar_emissores_pendentes()


def _contar_pendentes() -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM operations_primario WHERE setor_emissor IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()


def run_refresh_primario() -> str:
    init_db()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"=== Refresh Primario (CVM) iniciado em {started_at} ===")

    status = "ok"
    detalhe = ""
    cvm_raw_rows = ops_rows = pendentes = 0

    try:
        download_cvm.download_all()
        _, cvm_raw_rows = parse_cvm.parse_cvm()
        resultado_unify = unify_primario.build_operations_primario()
        ops_rows = resultado_unify["total"]
        pendentes = resultado_unify["pendentes"]

        if pendentes > 0:
            _resolver_emissores_pendentes_via_api()
            pendentes = _contar_pendentes()
    except Exception:
        status = "erro"
        detalhe = traceback.format_exc()
        print(detalhe)

    finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO refresh_primario_log
                (started_at, finished_at, cvm_raw_rows, operations_primario_rows, emissores_pendentes, status, detalhe)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (started_at, finished_at, cvm_raw_rows, ops_rows, pendentes, status, detalhe),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"=== Refresh Primario finalizado em {finished_at} (status={status}) ===")
    print(f"cvm_oferta_distribuicao_raw: {cvm_raw_rows} | operations_primario: {ops_rows} ({pendentes} emissores pendentes)")
    return status


if __name__ == "__main__":
    sys.exit(1 if run_refresh_primario() == "erro" else 0)
