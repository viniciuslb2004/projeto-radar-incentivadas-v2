"""Orquestra o pipeline semanal: download -> parse -> unify -> enriquecimento leve
via API -> embeddings.

NAO roda o job PESADO de enriquecimento de CNAE da FINEP (enrich_cnae.py::enrich()/
enrich_empresas(), que baixa varios GB da RFB) -- esse continua rodando separadamente,
uma vez por mes. Roda, sim, uma versao LEVE (enrich_cnae.py::enrich_pendentes_via_api,
uma chamada por CNPJ pendente via BrasilAPI) logo depois do unify -- sem isso, uma
operacao nova da FINEP ficaria com setor 'pendente' ate 30 dias, esperando o proximo
job mensal.

Incremental desde 2026-08: BNDES/FINEP republicam o historico INTEIRO do zero a cada
arquivo, mas o pipeline agora faz o diff em Python (ver incremental.py, unify.py,
embeddings.py) em vez de dropar e reconstruir bndes_raw/finep_*_raw/operations e
reembutir tudo toda semana -- so processa o que e realmente novo. de_para_cnae e os
agregados (agg_*) continuam em reload completo (baratos, sem risco de duplicacao).
"""
import datetime
import sys
import traceback

from db import drop_rebuild_tables, get_connection, init_db
import download
import parse_bndes
import parse_finep
import unify
import embeddings
import enrich_cnae
import search_taxonomy
from sector_taxonomy import build_divisao_map


def _resolver_pendentes_via_api() -> list:
    """Consulta a BrasilAPI (ver enrich_cnae.py::enrich_pendentes_via_api) para os
    CNPJs que ficaram 'pendente' apos o unify.build_operations() desta rodada, e
    reclassifica em cima do que resolver. Roda dentro do refresh SEMANAL (nao precisa
    de workflow/cron proprio) -- complementa o job mensal pesado, nunca substitui."""
    conn = get_connection()
    try:
        cnpjs_pendentes = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT cnpj FROM operations WHERE setor_origem = 'pendente' AND cnpj IS NOT NULL"
            ).fetchall()
        }
        if not cnpjs_pendentes:
            return []
        divisao_map = build_divisao_map(conn)
        enrich_cnae.enrich_pendentes_via_api(conn, cnpjs_pendentes, divisao_map)
    finally:
        conn.close()
    return unify.reclassificar_pendentes()


def _contar_pendentes() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM operations WHERE setor_origem = 'pendente'").fetchone()[0]
    finally:
        conn.close()


def run_refresh() -> str:
    """Devolve o status final ('ok'/'erro') -- o chamador de linha de comando (ver
    __main__) e quem decide se isso vira um sys.exit(1). Sem isso, uma falha total
    aqui (download fora do ar, Turso indisponivel, etc) ficava so registrada dentro
    do proprio banco (refresh_log.status='erro') mas o processo saia com codigo 0 --
    o workflow do GitHub Actions aparecia verde mesmo quando o refresh inteiro falhou."""
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
        reclassificados_ids = resultado_unify["reclassificados_ids"]

        if pendentes > 0:
            reclassificados_ids = reclassificados_ids + _resolver_pendentes_via_api()
            pendentes = _contar_pendentes()

        embeddings.build_embeddings(
            novos_ids=resultado_unify["novos_ids"],
            reclassificados_ids=reclassificados_ids,
        )

        for linha in search_taxonomy.segmentos_sem_sinonimo():
            print(f"  sinonimo faltando (curadoria manual): {linha['segmento']!r} ({linha['n_operacoes']} operacoes)")
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
    return status


if __name__ == "__main__":
    sys.exit(1 if run_refresh() == "erro" else 0)
