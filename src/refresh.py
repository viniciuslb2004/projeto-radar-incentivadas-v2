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


def _registrar_inicio(started_at: str) -> int:
    """Grava a linha de `refresh_log` logo no INICIO do run, com `finished_at`
    ainda NULL. E o que permite ao painel admin (`webapp/admin/routes.py`)
    detectar "ja existe um refresh em andamento" antes de disparar outro --
    checagem que so funciona se existir mesmo uma janela real, durante o run,
    com uma linha `finished_at IS NULL` na tabela. Antes desta mudanca a linha
    inteira (started_at E finished_at) so era gravada num UNICO insert no FINAL
    do run (ver `_finalizar_log`), entao essa janela nunca existia de verdade e
    a checagem do painel nunca disparava."""
    conn = get_connection()
    try:
        log_id = conn.execute(
            "INSERT INTO refresh_log (started_at, status) VALUES (?, ?) RETURNING id",
            (started_at, "em_andamento"),
        ).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return log_id


def _finalizar_log(log_id: int, finished_at: str, bndes_rows: int, finep_direto_rows: int,
                    finep_desc_rows: int, ops_rows: int, pendentes: int, status: str, detalhe: str) -> None:
    """Fecha a linha aberta por `_registrar_inicio` (mesmo `id`), preenchendo
    `finished_at` e o resto das colunas. Chamado de dentro de um `finally` em
    `run_refresh` -- roda sempre, sucesso ou erro, garantindo que nenhuma linha
    fique presa com `finished_at IS NULL` para sempre (o que travaria o painel
    admin achando que ha um refresh em andamento eternamente)."""
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE refresh_log
            SET finished_at = ?, bndes_rows = ?, finep_credito_direto_rows = ?,
                finep_credito_descentralizado_rows = ?, operations_rows = ?,
                setores_pendentes = ?, status = ?, detalhe = ?
            WHERE id = ?
            """,
            (finished_at, bndes_rows, finep_direto_rows, finep_desc_rows, ops_rows, pendentes, status, detalhe, log_id),
        )
        conn.commit()
    finally:
        conn.close()


def run_refresh() -> str:
    """Devolve o status final ('ok'/'parcial'/'erro') -- o chamador de linha de
    comando (ver __main__) e quem decide se isso vira um sys.exit(1) ('erro' e
    o unico status que aborta o workflow do GitHub Actions; 'parcial' significa
    que o refresh terminou mas uma fonte especifica -- BNDES ou FINEP -- teve
    falha isolada, ver `detalhe`). Sem isso, uma falha total aqui (download fora
    do ar, banco indisponivel, etc) ficava so registrada dentro do proprio banco
    (refresh_log.status='erro') mas o processo saia com codigo 0 -- o workflow
    do GitHub Actions aparecia verde mesmo quando o refresh inteiro falhou."""
    init_db()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"=== Refresh iniciado em {started_at} ===")

    conn = get_connection()
    try:
        drop_rebuild_tables(conn)
    finally:
        conn.close()

    # Grava a linha do log JA AGORA (finished_at ainda NULL) -- ver docstring de
    # _registrar_inicio. Feito antes de baixar/processar qualquer coisa, para que
    # a janela "em andamento" cubra o run inteiro.
    log_id = _registrar_inicio(started_at)

    status = "ok"
    detalhe = ""
    bndes_rows = finep_direto_rows = finep_desc_rows = ops_rows = pendentes = 0

    try:
        download.download_all()

        # BNDES e FINEP isolados um do outro de proposito: cada um le suas
        # proprias abas do xlsx por nome hardcoded (com lookup resiliente a
        # variacoes de acento/case/espaco, ver `_resolver_aba` em
        # parse_bndes.py/parse_finep.py), e uma fonte externa (BNDES ou FINEP)
        # renomear uma aba NAO pode derrubar a outra fonte nem o rebuild de
        # `operations` que vem depois -- mesma causa raiz real ja corrigida uma
        # vez so para "Projetos Não Aprovados" (commit 68734bb), generalizada
        # aqui para as 4 outras leituras hardcoded que tinham o mesmo risco.
        # Nunca finge sucesso: uma falha de verdade (total ou parcial, aba nao
        # encontrada nem com o lookup resiliente) fica registrada em `detalhe`.
        try:
            n_novas_bndes, bndes_rows, erros_bndes = parse_bndes.parse_bndes()
            if erros_bndes:
                aviso = "aviso: BNDES com falha PARCIAL (aba nao encontrada, nao bloqueia o resto do refresh):\n" + "\n".join(erros_bndes)
                print(aviso)
                detalhe += aviso + "\n\n"
        except Exception:
            aviso = f"erro: BNDES falhou por completo nesta rodada (nao bloqueia FINEP nem o resto do refresh):\n{traceback.format_exc()}"
            print(aviso)
            detalhe += aviso + "\n\n"

        try:
            _, _, finep_direto_rows, finep_desc_rows, erros_finep = parse_finep.parse_finep()
            if erros_finep:
                aviso = "aviso: FINEP com falha PARCIAL (aba nao encontrada, nao bloqueia o resto do refresh):\n" + "\n".join(erros_finep)
                print(aviso)
                detalhe += aviso + "\n\n"
        except Exception:
            aviso = f"erro: FINEP falhou por completo nesta rodada (nao bloqueia BNDES nem o resto do refresh):\n{traceback.format_exc()}"
            print(aviso)
            detalhe += aviso + "\n\n"

        # Best-effort, isolado de proposito (causa raiz real, 2026-09-21): esta base
        # so alimenta a taxa de aprovacao (ver docstring de parse_finep_nao_aprovados),
        # nunca `operations` -- uma falha aqui (ex: a FINEP mudou levemente o nome da
        # aba do xlsx, fonte externa fora do nosso controle) NAO pode derrubar o
        # rebuild de `operations` inteiro, que e o que todo o resto do site depende.
        try:
            parse_finep.parse_finep_nao_aprovados()
        except Exception:
            aviso = f"aviso: parse_finep_nao_aprovados falhou (nao bloqueia o resto do refresh):\n{traceback.format_exc()}"
            print(aviso)
            detalhe += aviso + "\n\n"

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

        if status == "ok" and detalhe:
            # Chegou ate aqui (unify/embeddings rodaram normalmente) mas BNDES e/ou
            # FINEP tiveram alguma falha registrada acima -- nao e um "ok" limpo nem
            # um "erro" total, e sim uma falha parcial isolada (ver `detalhe`).
            status = "parcial"
    except Exception:
        status = "erro"
        detalhe += traceback.format_exc()
        print(detalhe)
    finally:
        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _finalizar_log(log_id, finished_at, bndes_rows, finep_direto_rows, finep_desc_rows, ops_rows, pendentes, status, detalhe)

    print(f"=== Refresh finalizado em {finished_at} (status={status}) ===")
    print(f"BNDES: {bndes_rows} | FINEP credito direto: {finep_direto_rows} | FINEP descentralizado: {finep_desc_rows}")
    print(f"Operations: {ops_rows} ({pendentes} com setor pendente)")
    return status


if __name__ == "__main__":
    sys.exit(1 if run_refresh() == "erro" else 0)
