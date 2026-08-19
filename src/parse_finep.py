"""Le as abas de credito do xlsx da FINEP e grava nas staging tables.

Escopo (decisao do usuario): so as operacoes de credito, comparaveis ao BNDES.
Ficam de fora subvencao/nao-reembolsavel/startups/ANCINE.
"""
import pandas as pd

from db import get_connection
from download import FINEP_NAO_APROVADOS_PATH, FINEP_PATH

NAO_APROVADOS_COLUMNS = {
    "Instrumento": "instrumento",
    "Demanda": "demanda",
    "Referencia": "referencia",
    "Data Entrada": "data_entrada",
    "Data do Indeferimento": "data_indeferimento",
    "Proponente": "proponente",
    "CNPJ": "cnpj",
    "UF": "uf",
    "Município": "municipio",
    "Região": "regiao",
    "Valor Finep": "valor_finep",
}

CREDITO_DIRETO_COLUMNS = {
    "Demanda": "demanda",
    "Ref": "ref",
    "Contrato": "contrato",
    "Data Entrada SF": "data_entrada_sf",
    "Dt. Aprov. Operacional\\Crédito": "dt_aprov_operacional_credito",
    "Dt. Aprov. Juridica\\Garantias": "dt_aprov_juridica_garantias",
    "Data Assinatura": "data_assinatura",
    "Tempo Avaliação Oper.\\Crédito": "tempo_avaliacao_oper_credito",
    "Tempo Avaliação Jur.\\Garantias": "tempo_avaliacao_jur_garantias",
    "Tempo Total Avaliação": "tempo_total_avaliacao",
    "Tempo Contratação": "tempo_contratacao",
    "Prazo Execução": "prazo_execucao",
    "Título": "titulo",
    "Proponente": "proponente",
    "CNPJ Proponente": "cnpj_proponente",
    "Município Proponente": "municipio_proponente",
    "UF Proponente": "uf_proponente",
    "Região Proponente": "regiao_proponente",
    "Executor": "executor",
    "CNPJ Executor": "cnpj_executor",
    "Município Executor": "municipio_executor",
    "UF Executor": "uf_executor",
    "Região Executor": "regiao_executor",
    "UF Projeto": "uf_projeto",
    "Valor Finep": "valor_finep",
    "Contrapartida Financeira": "contrapartida_financeira",
    "Valor Pago": "valor_pago",
    "Status": "status",
    "Resumo Publicável": "resumo_publicavel",
}

CREDITO_DESCENTRALIZADO_COLUMNS = {
    "Data Assinatura": "data_assinatura",
    "Contrato Finep Agente": "contrato_finep_agente",
    "Beneficiario": "beneficiario",
    "CNPJ Beneficiário": "cnpj_beneficiario",
    "UF Beneficiário": "uf_beneficiario",
    "Valor Financiado": "valor_financiado",
    "Valor Liberado": "valor_liberado",
    "Contrapartida": "contrapartida",
    "Outros Recursos": "outros_recursos",
    "Agente": "agente",
}


def _clean_cnpj(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)


def parse_finep(path=FINEP_PATH):
    conn = get_connection()
    try:
        print(f"Lendo {path} (aba Projetos_Crédito_Direto)...")
        direto = pd.read_excel(path, sheet_name="Projetos_Crédito_Direto", header=6, engine="openpyxl")
        direto = direto.rename(columns=CREDITO_DIRETO_COLUMNS)
        direto = direto[[c for c in CREDITO_DIRETO_COLUMNS.values() if c in direto.columns]]
        direto = direto.dropna(subset=["contrato"])
        direto["cnpj_proponente"] = _clean_cnpj(direto["cnpj_proponente"])
        direto["data_assinatura"] = pd.to_datetime(direto["data_assinatura"], errors="coerce").dt.strftime("%Y-%m-%d")
        for col in ["valor_finep", "contrapartida_financeira", "valor_pago"]:
            direto[col] = pd.to_numeric(direto[col], errors="coerce")
        direto.to_sql("finep_credito_direto_raw", conn, if_exists="append", index=False)

        print(f"Lendo {path} (aba Projetos_Créd__Descentralizado)...")
        descentralizado = pd.read_excel(path, sheet_name="Projetos_Créd__Descentralizado", header=6, engine="openpyxl")
        descentralizado = descentralizado.rename(columns=CREDITO_DESCENTRALIZADO_COLUMNS)
        descentralizado = descentralizado[[c for c in CREDITO_DESCENTRALIZADO_COLUMNS.values() if c in descentralizado.columns]]
        descentralizado = descentralizado.dropna(subset=["beneficiario"])
        descentralizado["cnpj_beneficiario"] = _clean_cnpj(descentralizado["cnpj_beneficiario"])
        descentralizado["data_assinatura"] = pd.to_datetime(descentralizado["data_assinatura"], errors="coerce").dt.strftime("%Y-%m-%d")
        for col in ["valor_financiado", "valor_liberado", "contrapartida", "outros_recursos"]:
            descentralizado[col] = pd.to_numeric(descentralizado[col], errors="coerce")
        descentralizado.to_sql("finep_credito_descentralizado_raw", conn, if_exists="append", index=False)

        conn.commit()
    finally:
        conn.close()

    print(f"FINEP credito direto: {len(direto)} operacoes. Credito descentralizado: {len(descentralizado)} operacoes.")
    return len(direto), len(descentralizado)


def parse_finep_nao_aprovados(path=FINEP_NAO_APROVADOS_PATH):
    """So usado para calcular a taxa de aprovacao real do Credito Direto (BNDES nao
    publica propostas recusadas, entao essa base so cobre a FINEP)."""
    conn = get_connection()
    try:
        print(f"Lendo {path} (aba Projetos Não Aprovados)...")
        df = pd.read_excel(path, sheet_name="Projetos Não Aprovados", header=6, engine="openpyxl")
        df = df.rename(columns=NAO_APROVADOS_COLUMNS)
        df = df[[c for c in NAO_APROVADOS_COLUMNS.values() if c in df.columns]]
        df = df.dropna(subset=["proponente"])
        df["cnpj"] = df["cnpj"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)
        df["data_entrada"] = pd.to_datetime(df["data_entrada"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["data_indeferimento"] = pd.to_datetime(df["data_indeferimento"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["valor_finep"] = pd.to_numeric(df["valor_finep"], errors="coerce")
        df.to_sql("finep_nao_aprovados_raw", conn, if_exists="append", index=False)
        conn.commit()
    finally:
        conn.close()

    print(f"FINEP nao aprovados: {len(df)} projetos gravados.")
    return len(df)


if __name__ == "__main__":
    from db import init_db

    init_db()
    parse_finep()
    parse_finep_nao_aprovados()
