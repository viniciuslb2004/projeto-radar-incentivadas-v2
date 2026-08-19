"""Constroi a tabela unificada `operations` (BNDES + FINEP credito) e os agregados do dashboard."""
import pandas as pd

from db import get_connection
from geo import regiao_de


def _add_periodo(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    dt = pd.to_datetime(df[date_col], errors="coerce")
    df["ano"] = dt.dt.year
    df["trimestre"] = dt.dt.quarter
    return df


def _load_cnae_lookup(conn) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT cnpj, setor_bndes_mapeado, subsetor_bndes_mapeado, cnae_descricao FROM cnpj_cnae", conn
    )


def _build_bndes_ops(conn) -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM bndes_raw", conn)
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
    df = pd.read_sql("SELECT * FROM finep_credito_direto_raw", conn)
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
    df = pd.read_sql("SELECT * FROM finep_credito_descentralizado_raw", conn)
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


def build_operations():
    conn = get_connection()
    try:
        cnae_lookup = _load_cnae_lookup(conn)
        parts = [
            _build_bndes_ops(conn),
            _build_finep_direto_ops(conn, cnae_lookup),
            _build_finep_descentralizado_ops(conn, cnae_lookup),
        ]
        parts = [p for p in parts if p is not None and not p.empty]
        ops = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

        if not ops.empty:
            ops["embedding_text"] = ops.apply(_embedding_text, axis=1)
            ops.to_sql("operations", conn, if_exists="append", index=False)
            conn.commit()

        _build_aggregates(conn)
        conn.commit()
    finally:
        conn.close()

    n_pendente = 0
    if not ops.empty:
        n_pendente = int((ops["setor_origem"] == "pendente").sum())
    print(f"operations: {len(ops)} linhas gravadas ({n_pendente} com setor pendente de enriquecimento).")
    return len(ops), n_pendente


def _build_aggregates(conn):
    ops = pd.read_sql("SELECT * FROM operations", conn)
    if ops.empty:
        return

    setor_periodo = (
        ops.dropna(subset=["ano"])
        .groupby(["setor_bndes", "agencia", "ano", "trimestre"], dropna=False)
        .agg(n_operacoes=("id", "count"), valor_total=("valor_contratado", "sum"))
        .reset_index()
    )
    setor_periodo["cheque_medio"] = setor_periodo["valor_total"] / setor_periodo["n_operacoes"]
    setor_periodo.to_sql("agg_setor_periodo", conn, if_exists="append", index=False)

    uf = (
        ops.groupby(["uf", "agencia"], dropna=False)
        .agg(n_operacoes=("id", "count"), valor_total=("valor_contratado", "sum"))
        .reset_index()
    )
    uf["cheque_medio"] = uf["valor_total"] / uf["n_operacoes"]
    uf.to_sql("agg_uf", conn, if_exists="append", index=False)

    porte = (
        ops.fillna({"porte_cliente": "Nao informado"})
        .groupby(["porte_cliente", "agencia"], dropna=False)
        .agg(n_operacoes=("id", "count"), valor_total=("valor_contratado", "sum"))
        .reset_index()
    )
    porte["cheque_medio"] = porte["valor_total"] / porte["n_operacoes"]
    porte.to_sql("agg_porte", conn, if_exists="append", index=False)


if __name__ == "__main__":
    build_operations()
