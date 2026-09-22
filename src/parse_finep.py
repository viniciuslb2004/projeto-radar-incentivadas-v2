"""Le as abas de credito do xlsx da FINEP e grava nas staging tables.

Escopo (decisao do usuario): so as operacoes de credito, comparaveis ao BNDES.
Ficam de fora subvencao/nao-reembolsavel/startups/ANCINE.

Incremental (ver incremental.py): a FINEP republica o historico INTEIRO a cada
vez (nas 3 planilhas -- credito direto, credito descentralizado e nao aprovados),
entao so inserimos as linhas cujo hash de conteudo ainda nao existe na tabela.
"""
import unicodedata

import pandas as pd

from db import get_connection
from download import FINEP_NAO_APROVADOS_PATH, FINEP_PATH
from incremental import backfill_row_hashes, compute_row_hash, existing_hashes, insert_new_rows


def _normalizar_nome_aba(nome: str) -> str:
    """Remove acentos/case/espacos duplicados de um nome de aba, so para
    COMPARACAO -- nunca usado como valor de fato (ver `_resolver_aba_nao_aprovados`)."""
    nfkd = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _resolver_aba_nao_aprovados(path) -> str:
    """Acha o nome exato da aba de 'Projetos Nao Aprovados' dentro do xlsx.

    Causa raiz real (2026-09-21): o refresh semanal falhou por completo (nenhuma
    operacao nova de BNDES/FINEP entrou em `operations` naquela rodada) porque
    `pd.read_excel(..., sheet_name="Projetos Não Aprovados")` deu
    `ValueError: Worksheet named ... not found` -- a planilha da FINEP nao tinha
    uma aba com esse nome EXATO no momento daquele download (a aba real
    provavelmente variou por um detalhe de acento/espaco/capitalizacao da FINEP,
    fonte externa fora do nosso controle). Em vez de depender de um match exato
    fragil, tenta o nome exato primeiro (caminho mais comum) e cai para um match
    normalizado (sem acento, case-insensitive, espacos colapsados) se o exato
    nao bater -- cobre pequenas variacoes futuras sem inventar dado nenhum. Se
    nem assim achar, levanta um erro com a lista real de abas do arquivo (mais
    facil de diagnosticar do que o ValueError generico do pandas)."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        nomes = wb.sheetnames
        alvo = "Projetos Não Aprovados"
        if alvo in nomes:
            return alvo
        alvo_norm = _normalizar_nome_aba(alvo)
        for nome in nomes:
            if _normalizar_nome_aba(nome) == alvo_norm:
                print(f"  aviso: aba 'Projetos Não Aprovados' nao encontrada exata, usando {nome!r} (match normalizado)")
                return nome
        raise ValueError(
            f"Nenhuma aba de 'Projetos Nao Aprovados' encontrada em {path}. Abas disponiveis: {nomes}"
        )
    finally:
        wb.close()

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


CREDITO_DIRETO_HASH_COLS = list(CREDITO_DIRETO_COLUMNS.values())
CREDITO_DESCENTRALIZADO_HASH_COLS = list(CREDITO_DESCENTRALIZADO_COLUMNS.values())
NAO_APROVADOS_HASH_COLS = list(NAO_APROVADOS_COLUMNS.values())


def _linhas_novas(conn, table: str, df: pd.DataFrame, hash_cols: list) -> pd.DataFrame:
    """Backfill de row_hash (bancos ja existentes) + filtra so o que ainda nao esta
    na tabela, por hash de conteudo da linha (ver incremental.py)."""
    n_backfill = backfill_row_hashes(conn, table, hash_cols)
    if n_backfill:
        print(f"{table}: {n_backfill} linhas existentes tiveram row_hash calculado retroativamente.")
    hashes_existentes = existing_hashes(conn, table)
    df = df.copy()
    df["row_hash"] = compute_row_hash(conn, table, df, hash_cols)
    novas = df[~df["row_hash"].isin(hashes_existentes)].copy()
    novas = novas.drop_duplicates(subset=["row_hash"])
    return novas


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
        total_direto = len(direto)
        novas_direto = _linhas_novas(conn, "finep_credito_direto_raw", direto, CREDITO_DIRETO_HASH_COLS)
        insert_new_rows(conn, "finep_credito_direto_raw", novas_direto, CREDITO_DIRETO_HASH_COLS + ["row_hash"])

        print(f"Lendo {path} (aba Projetos_Créd__Descentralizado)...")
        descentralizado = pd.read_excel(path, sheet_name="Projetos_Créd__Descentralizado", header=6, engine="openpyxl")
        descentralizado = descentralizado.rename(columns=CREDITO_DESCENTRALIZADO_COLUMNS)
        descentralizado = descentralizado[[c for c in CREDITO_DESCENTRALIZADO_COLUMNS.values() if c in descentralizado.columns]]
        descentralizado = descentralizado.dropna(subset=["beneficiario"])
        descentralizado["cnpj_beneficiario"] = _clean_cnpj(descentralizado["cnpj_beneficiario"])
        descentralizado["data_assinatura"] = pd.to_datetime(descentralizado["data_assinatura"], errors="coerce").dt.strftime("%Y-%m-%d")
        for col in ["valor_financiado", "valor_liberado", "contrapartida", "outros_recursos"]:
            descentralizado[col] = pd.to_numeric(descentralizado[col], errors="coerce")
        total_descentralizado = len(descentralizado)
        novas_descentralizado = _linhas_novas(
            conn, "finep_credito_descentralizado_raw", descentralizado, CREDITO_DESCENTRALIZADO_HASH_COLS
        )
        insert_new_rows(
            conn, "finep_credito_descentralizado_raw", novas_descentralizado,
            CREDITO_DESCENTRALIZADO_HASH_COLS + ["row_hash"],
        )

        conn.commit()
        total_direto_agora = conn.execute("SELECT COUNT(*) FROM finep_credito_direto_raw").fetchone()[0]
        total_descentralizado_agora = conn.execute("SELECT COUNT(*) FROM finep_credito_descentralizado_raw").fetchone()[0]
    finally:
        conn.close()

    print(
        f"FINEP credito direto: {len(novas_direto)} novas (planilha tem {total_direto}, tabela tem {total_direto_agora}). "
        f"Credito descentralizado: {len(novas_descentralizado)} novas (planilha tem {total_descentralizado}, "
        f"tabela tem {total_descentralizado_agora})."
    )
    return len(novas_direto), len(novas_descentralizado), total_direto_agora, total_descentralizado_agora


def parse_finep_nao_aprovados(path=FINEP_NAO_APROVADOS_PATH):
    """So usado para calcular a taxa de aprovacao real do Credito Direto (BNDES nao
    publica propostas recusadas, entao essa base so cobre a FINEP)."""
    conn = get_connection()
    try:
        aba = _resolver_aba_nao_aprovados(path)
        print(f"Lendo {path} (aba {aba!r})...")
        df = pd.read_excel(path, sheet_name=aba, header=6, engine="openpyxl")
        df = df.rename(columns=NAO_APROVADOS_COLUMNS)
        df = df[[c for c in NAO_APROVADOS_COLUMNS.values() if c in df.columns]]
        df = df.dropna(subset=["proponente"])
        df["cnpj"] = df["cnpj"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)
        df["data_entrada"] = pd.to_datetime(df["data_entrada"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["data_indeferimento"] = pd.to_datetime(df["data_indeferimento"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["valor_finep"] = pd.to_numeric(df["valor_finep"], errors="coerce")
        total_planilha = len(df)
        novas = _linhas_novas(conn, "finep_nao_aprovados_raw", df, NAO_APROVADOS_HASH_COLS)
        insert_new_rows(conn, "finep_nao_aprovados_raw", novas, NAO_APROVADOS_HASH_COLS + ["row_hash"])
        conn.commit()
        total_agora = conn.execute("SELECT COUNT(*) FROM finep_nao_aprovados_raw").fetchone()[0]
    finally:
        conn.close()

    print(f"FINEP nao aprovados: {len(novas)} novos (planilha tem {total_planilha}, tabela tem {total_agora}).")
    return len(novas), total_agora


if __name__ == "__main__":
    from db import init_db

    init_db()
    parse_finep()
    parse_finep_nao_aprovados()
