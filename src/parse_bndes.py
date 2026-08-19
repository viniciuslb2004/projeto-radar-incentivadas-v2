"""Le o xlsx do BNDES (aba SITE + aba DE-PARA CNAE) e grava nas staging tables.

Incremental (ver incremental.py): o BNDES republica o historico INTEIRO a cada
vez, entao em vez de recarregar bndes_raw do zero, so inserimos as linhas cujo
hash de conteudo ainda nao existe na tabela -- as linhas ja conhecidas (a grande
maioria, toda semana) sao ignoradas sem custo de escrita no banco.
"""
import pandas as pd

from db import get_connection
from download import BNDES_PATH
from incremental import backfill_row_hashes, compute_row_hash, existing_hashes, insert_new_rows

# Nomes das colunas na planilha (na ordem em que aparecem), mapeados para snake_case.
BNDES_COLUMNS = {
    "Cliente": "cliente",
    "CNPJ": "cnpj",
    "Descrição do projeto": "descricao_projeto",
    "UF": "uf",
    "Município": "municipio",
    "Município - código": "municipio_codigo",
    "Número do contrato": "numero_contrato",
    "Data da contratação": "data_contratacao",
    "Valor contratado  R$": "valor_contratado",
    "Valor desembolsado R$": "valor_desembolsado",
    "Fonte de recurso (desembolsos)": "fonte_recurso",
    "Custo financeiro": "custo_financeiro",
    "Juros": "juros",
    "Prazo - carência (meses)": "prazo_carencia_meses",
    "Prazo - amortização (meses)": "prazo_amortizacao_meses",
    "Modalidade de apoio": "modalidade_apoio",
    "Forma de apoio": "forma_apoio",
    "Produto": "produto",
    "Instrumento financeiro": "instrumento_financeiro",
    "Inovação": "inovacao",
    "Área operacional": "area_operacional",
    "Setor CNAE": "setor_cnae",
    "Subsetor CNAE agrupado": "subsetor_cnae_agrupado",
    "Subsetor CNAE - código": "subsetor_cnae_codigo",
    "Subsetor CNAE - nome": "subsetor_cnae_nome",
    "Setor BNDES": "setor_bndes",
    "Subsetor BNDES": "subsetor_bndes",
    "Porte do cliente": "porte_cliente",
    "Natureza do cliente": "natureza_cliente",
    "Instituição Financeira Credenciada": "instituicao_financeira_credenciada",
    "CNPJ da instituição financeira credenciada": "cnpj_if_credenciada",
    "Tipo de garantia": "tipo_garantia",
    "Tipo de excepcionalidade": "tipo_excepcionalidade",
    "Situação do contrato": "situacao_contrato",
}

DE_PARA_COLUMNS = {
    "Setor  CNAE\n(classificação BNDES)": "setor_cnae",
    "Subsetor CNAE Agrupado (classificação BNDES)": "subsetor_cnae_agrupado",
    "Subsetor BNDES": "subsetor_bndes",
    "Setor BNDES": "setor_bndes",
    "Código CNAE - IBGE": "codigo_cnae_ibge_faixa",
    "Produto BNDES": "produto_bndes",
}


def _clean_cnpj(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)


BNDES_HASH_COLS = list(BNDES_COLUMNS.values())


def parse_bndes(path=BNDES_PATH):
    print(f"Lendo {path} (aba SITE)...")
    df = pd.read_excel(path, sheet_name="SITE", header=4, engine="openpyxl")
    df = df.rename(columns=BNDES_COLUMNS)
    df = df[[c for c in BNDES_COLUMNS.values() if c in df.columns]]

    df["cnpj"] = _clean_cnpj(df["cnpj"])
    df["data_contratacao"] = pd.to_datetime(df["data_contratacao"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["valor_contratado", "valor_desembolsado", "juros", "prazo_carencia_meses", "prazo_amortizacao_meses"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    total_planilha = len(df)

    print(f"Lendo {path} (aba DE-PARA CNAE)...")
    de_para = pd.read_excel(path, sheet_name="DE-PARA CNAE", header=3, engine="openpyxl")
    de_para = de_para.rename(columns=DE_PARA_COLUMNS)
    de_para = de_para[[c for c in DE_PARA_COLUMNS.values() if c in de_para.columns]]
    de_para = de_para.dropna(how="all")

    conn = get_connection()
    try:
        n_backfill = backfill_row_hashes(conn, "bndes_raw", BNDES_HASH_COLS)
        if n_backfill:
            print(f"bndes_raw: {n_backfill} linhas existentes tiveram row_hash calculado retroativamente.")
        hashes_existentes = existing_hashes(conn, "bndes_raw")

        df["row_hash"] = compute_row_hash(conn, "bndes_raw", df, BNDES_HASH_COLS)
        novas = df[~df["row_hash"].isin(hashes_existentes)].copy()
        # planilha as vezes tem linhas com conteudo identico entre si (nao so contra
        # o banco) -- sem isso, a segunda delas seria inserida de novo no MESMO refresh.
        novas = novas.drop_duplicates(subset=["row_hash"])

        insert_new_rows(conn, "bndes_raw", novas, BNDES_HASH_COLS + ["row_hash"])
        # de_para_cnae fica na lista de rebuild completo (tabela pequena, sem
        # problema de chave/duplicacao) -- ja foi dropada e recriada antes desta
        # chamada, entao um append aqui equivale a um reload completo.
        de_para.to_sql("de_para_cnae", conn, if_exists="append", index=False)
        conn.commit()
        total_agora = conn.execute("SELECT COUNT(*) FROM bndes_raw").fetchone()[0]
    finally:
        conn.close()

    print(
        f"BNDES: {len(novas)} operacoes NOVAS inseridas (planilha tem {total_planilha} linhas no total, "
        f"bndes_raw tem {total_agora} apos o refresh), {len(de_para)} linhas de-para CNAE gravadas."
    )
    return len(novas), total_agora


if __name__ == "__main__":
    from db import init_db

    init_db()
    parse_bndes()
