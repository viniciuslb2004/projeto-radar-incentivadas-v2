"""Constroi a tabela unificada `operations` (BNDES + FINEP credito) e os agregados do dashboard.

Incremental (ver incremental.py e db.py): bndes_raw/finep_*_raw agora sao append-only,
entao build_operations() so processa as linhas raw que AINDA NAO tem uma linha
correspondente em `operations` -- usando raw_table+raw_id (id autoincrement estavel da
tabela de origem), que ja existia no schema mas antes so servia para drill-down, nao
como chave de deduplicacao. Isso e o que faz a classificacao de setor da FINEP (o merge
contra cnpj_cnae) so rodar para as linhas novas a cada refresh, nao para a base inteira.

Alem disso, toda vez que o job mensal de enriquecimento (enrich_cnae.py) adiciona CNPJs
novos ao cache cnpj_cnae, as operacoes da FINEP que ficaram `setor_origem='pendente'` em
refreshes anteriores (o CNPJ ainda nao estava no cache na hora em que a linha foi
unificada) sao re-checadas contra o cache atual e ATUALIZADAS em cima da linha ja
existente (nunca duplicadas) sempre que resolvem. Sem isso, uma vez que `operations`
deixa de ser reconstruida do zero toda semana, uma pendencia resolvida no enriquecimento
mensal nunca mais seria refletida.
"""
import pandas as pd

from db import get_connection, get_engine
from geo import regiao_de
from incremental import insert_new_rows

OPERATIONS_COLS = [
    "agencia", "instrumento", "fonte_id", "cliente", "cnpj", "uf", "municipio",
    "data_contratacao", "ano", "trimestre", "valor_contratado", "valor_desembolsado",
    "setor_bndes", "subsetor_bndes", "segmento", "setor_origem", "porte_cliente",
    "produto", "instrumento_financeiro", "modalidade_apoio", "indexador", "taxa_juros",
    "prazo_carencia_meses", "prazo_amortizacao_meses", "descricao_projeto", "agente_financeiro",
    "raw_table", "raw_id", "embedding_text",
]


def _add_periodo(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    dt = pd.to_datetime(df[date_col], errors="coerce")
    df["ano"] = dt.dt.year
    df["trimestre"] = dt.dt.quarter
    return df


def _load_cnae_lookup(conn) -> pd.DataFrame:
    # pd.read_sql precisa de um engine SQLAlchemy (nao da conexao psycopg crua --
    # pandas nao suporta isso de forma confiavel, ver docstring de db.get_engine()).
    return pd.read_sql(
        "SELECT cnpj, setor_bndes_mapeado, subsetor_bndes_mapeado, cnae_descricao FROM cnpj_cnae", get_engine()
    )


def _build_bndes_ops(conn) -> pd.DataFrame:
    # so as linhas de bndes_raw que ainda nao tem uma linha correspondente em operations
    df = pd.read_sql(
        "SELECT * FROM bndes_raw WHERE id NOT IN (SELECT raw_id FROM operations WHERE raw_table = 'bndes_raw')",
        get_engine(),
    )
    if df.empty:
        return df
    df = _add_periodo(df, "data_contratacao")
    out = pd.DataFrame({
        "agencia": "BNDES",
        "instrumento": df["forma_apoio"],
        "fonte_id": df["numero_contrato"],
        "cliente": df["cliente"],
        "cnpj": df["cnpj"],
        "uf": df["uf"],
        "municipio": df["municipio"],
        "data_contratacao": df["data_contratacao"],
        "ano": df["ano"],
        "trimestre": df["trimestre"],
        "valor_contratado": df["valor_contratado"],
        "valor_desembolsado": df["valor_desembolsado"],
        "setor_bndes": df["setor_bndes"],
        "subsetor_bndes": df["subsetor_bndes"],
        "segmento": df["subsetor_cnae_nome"].str.strip(),
        "setor_origem": "nativo",
        "porte_cliente": df["porte_cliente"],
        "produto": df["produto"],
        "instrumento_financeiro": df["instrumento_financeiro"],
        "modalidade_apoio": df["modalidade_apoio"],
        "indexador": df["custo_financeiro"],
        "taxa_juros": df["juros"],
        "prazo_carencia_meses": df["prazo_carencia_meses"],
        "prazo_amortizacao_meses": df["prazo_amortizacao_meses"],
        "descricao_projeto": df["descricao_projeto"],
        "agente_financeiro": df["instituicao_financeira_credenciada"],
        "raw_table": "bndes_raw",
        "raw_id": df["id"],
    })
    return out


def _build_finep_direto_ops(conn, cnae_lookup: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT * FROM finep_credito_direto_raw WHERE id NOT IN "
        "(SELECT raw_id FROM operations WHERE raw_table = 'finep_credito_direto_raw')",
        get_engine(),
    )
    if df.empty:
        return df
    df = _add_periodo(df, "data_assinatura")
    df = df.merge(cnae_lookup, left_on="cnpj_proponente", right_on="cnpj", how="left")
    setor_origem = df["setor_bndes_mapeado"].notna().map({True: "enriquecido", False: "pendente"})
    out = pd.DataFrame({
        "agencia": "FINEP",
        "instrumento": "Credito Direto",
        "fonte_id": df["contrato"],
        "cliente": df["proponente"],
        "cnpj": df["cnpj_proponente"],
        "uf": df["uf_proponente"],
        "municipio": df["municipio_proponente"],
        "data_contratacao": df["data_assinatura"],
        "ano": df["ano"],
        "trimestre": df["trimestre"],
        "valor_contratado": df["valor_finep"],
        "valor_desembolsado": df["valor_pago"],
        "setor_bndes": df["setor_bndes_mapeado"],
        "subsetor_bndes": df["subsetor_bndes_mapeado"],
        "segmento": df["cnae_descricao"],
        "setor_origem": setor_origem,
        "porte_cliente": None,
        "produto": "Credito Direto (FINEP)",
        "instrumento_financeiro": None,
        "modalidade_apoio": "REEMBOLSAVEL",
        "indexador": None,
        "taxa_juros": None,
        "prazo_carencia_meses": None,
        "prazo_amortizacao_meses": None,
        "descricao_projeto": df["titulo"],
        "agente_financeiro": None,
        "raw_table": "finep_credito_direto_raw",
        "raw_id": df["id"],
    })
    return out


def _build_finep_descentralizado_ops(conn, cnae_lookup: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT * FROM finep_credito_descentralizado_raw WHERE id NOT IN "
        "(SELECT raw_id FROM operations WHERE raw_table = 'finep_credito_descentralizado_raw')",
        get_engine(),
    )
    if df.empty:
        return df
    df = _add_periodo(df, "data_assinatura")
    df = df.merge(cnae_lookup, left_on="cnpj_beneficiario", right_on="cnpj", how="left")
    setor_origem = df["setor_bndes_mapeado"].notna().map({True: "enriquecido", False: "pendente"})
    out = pd.DataFrame({
        "agencia": "FINEP",
        "instrumento": "Credito Descentralizado",
        "fonte_id": df["contrato_finep_agente"],
        "cliente": df["beneficiario"],
        "cnpj": df["cnpj_beneficiario"],
        "uf": df["uf_beneficiario"],
        "municipio": None,
        "data_contratacao": df["data_assinatura"],
        "ano": df["ano"],
        "trimestre": df["trimestre"],
        "valor_contratado": df["valor_financiado"],
        "valor_desembolsado": df["valor_liberado"],
        "setor_bndes": df["setor_bndes_mapeado"],
        "subsetor_bndes": df["subsetor_bndes_mapeado"],
        "segmento": df["cnae_descricao"],
        "setor_origem": setor_origem,
        "porte_cliente": None,
        "produto": "Credito Descentralizado (FINEP)",
        "instrumento_financeiro": None,
        "modalidade_apoio": "REEMBOLSAVEL",
        "indexador": None,
        "taxa_juros": None,
        "prazo_carencia_meses": None,
        "prazo_amortizacao_meses": None,
        "descricao_projeto": None,
        "agente_financeiro": df["agente"],
        "raw_table": "finep_credito_descentralizado_raw",
        "raw_id": df["id"],
    })
    return out


def _faixa_valor(valor) -> str:
    if valor is None or pd.isna(valor):
        return None
    if valor < 1e6:
        return "cheque pequeno, ate R$ 1 milhao"
    if valor < 10e6:
        return "cheque medio, entre R$ 1 e 10 milhoes"
    if valor < 50e6:
        return "cheque grande, entre R$ 10 e 50 milhoes"
    if valor < 200e6:
        return "cheque muito grande, entre R$ 50 e 200 milhoes"
    return "cheque excepcional, acima de R$ 200 milhoes"


def _faixa_prazo(meses) -> str:
    if meses is None or pd.isna(meses):
        return None
    if meses <= 36:
        return "prazo curto"
    if meses <= 96:
        return "prazo medio"
    return "prazo longo"


def _embedding_text(row) -> str:
    """Foco em CARACTERISTICAS DA LINHA DE CREDITO (setor, produto, modalidade, taxa, prazo,
    tamanho do cheque), NAO no nome da empresa -- a busca deve achar operacoes parecidas em
    natureza, nao so empresas com nome parecido. O nome do cliente fica de fora de proposito."""
    uf = row.get("uf")
    parts = [
        row.get("setor_bndes"),
        row.get("subsetor_bndes"),
        row.get("segmento"),
        row.get("produto"),
        row.get("modalidade_apoio"),
        f"indexador {row.get('indexador')}" if row.get("indexador") else None,
        _faixa_valor(row.get("valor_contratado")),
        _faixa_prazo(row.get("prazo_amortizacao_meses")),
        row.get("descricao_projeto"),
        row.get("municipio"),
        uf,
        regiao_de(uf),
    ]
    return " | ".join(str(p) for p in parts if p not in (None, "", "nan"))


def _reclassificar_pendentes(conn, cnae_lookup: pd.DataFrame) -> list:
    """Re-checa as operacoes 'pendente' (FINEP cujo CNPJ nao estava no cache cnpj_cnae
    na hora em que a linha foi unificada) contra o cache ATUAL, e atualiza em cima da
    linha ja existente as que agora resolvem -- nunca insere linha nova aqui. Devolve
    os ids atualizados (para o refresh saber quais precisam de um embedding novo)."""
    if cnae_lookup.empty:
        return []

    pendentes = pd.read_sql(
        "SELECT id, cnpj, produto, modalidade_apoio, indexador, valor_contratado, "
        "prazo_amortizacao_meses, descricao_projeto, municipio, uf "
        "FROM operations WHERE setor_origem = 'pendente'",
        get_engine(),
    )
    if pendentes.empty:
        return []

    resolvidos = pendentes.merge(cnae_lookup, on="cnpj", how="inner")
    resolvidos = resolvidos[resolvidos["setor_bndes_mapeado"].notna()]
    if resolvidos.empty:
        return []

    updates = []
    for _, row in resolvidos.iterrows():
        texto = _embedding_text({
            "setor_bndes": row["setor_bndes_mapeado"],
            "subsetor_bndes": row["subsetor_bndes_mapeado"],
            "segmento": row["cnae_descricao"],
            "produto": row["produto"],
            "modalidade_apoio": row["modalidade_apoio"],
            "indexador": row["indexador"],
            "valor_contratado": row["valor_contratado"],
            "prazo_amortizacao_meses": row["prazo_amortizacao_meses"],
            "descricao_projeto": row["descricao_projeto"],
            "municipio": row["municipio"],
            "uf": row["uf"],
        })
        updates.append((
            row["setor_bndes_mapeado"], row["subsetor_bndes_mapeado"], row["cnae_descricao"], texto, int(row["id"]),
        ))

    cur = conn.cursor()
    cur.executemany(
        "UPDATE operations SET setor_bndes = ?, subsetor_bndes = ?, segmento = ?, "
        "setor_origem = 'enriquecido', embedding_text = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    return [u[-1] for u in updates]


def build_operations():
    """Incremental: so insere operacoes para linhas raw novas + reclassifica pendentes
    que resolveram desde o ultimo refresh. Devolve um dict (nao so uma tupla) porque o
    orquestrador do refresh (refresh.py) precisa dos IDS novos/reclassificados para
    passar pro embeddings incremental (embeddings.py), nao so das contagens."""
    conn = get_connection()
    try:
        cnae_lookup = _load_cnae_lookup(conn)
        parts = [
            _build_bndes_ops(conn),
            _build_finep_direto_ops(conn, cnae_lookup),
            _build_finep_descentralizado_ops(conn, cnae_lookup),
        ]
        parts = [p for p in parts if p is not None and not p.empty]
        novas = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

        novos_ids = []
        if not novas.empty:
            novas["embedding_text"] = novas.apply(_embedding_text, axis=1)
            insert_new_rows(conn, "operations", novas, OPERATIONS_COLS)
            conn.commit()
            # recupera os ids autoincrement recem-atribuidos, por (raw_table, raw_id)
            for raw_table, grupo in novas.groupby("raw_table"):
                raw_ids = grupo["raw_id"].astype(int).tolist()
                placeholders = ", ".join("?" * len(raw_ids))
                rows = conn.execute(
                    f"SELECT id FROM operations WHERE raw_table = ? AND raw_id IN ({placeholders})",
                    [raw_table] + raw_ids,
                ).fetchall()
                novos_ids.extend(r[0] for r in rows)

        reclassificados_ids = _reclassificar_pendentes(conn, cnae_lookup)
        conn.commit()

        total_ops = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        n_pendente = conn.execute("SELECT COUNT(*) FROM operations WHERE setor_origem = 'pendente'").fetchone()[0]
    finally:
        conn.close()

    n_novas = len(novas) if not novas.empty else 0
    print(
        f"operations: {n_novas} linhas novas, {len(reclassificados_ids)} reclassificadas de "
        f"pendente -> enriquecido, {total_ops} no total ({n_pendente} ainda pendentes de enriquecimento)."
    )
    return {
        "novas": n_novas,
        "total": total_ops,
        "pendentes": n_pendente,
        "novos_ids": novos_ids,
        "reclassificados_ids": reclassificados_ids,
    }


if __name__ == "__main__":
    build_operations()
