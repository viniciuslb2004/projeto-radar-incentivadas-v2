"""Le o xlsx do BNDES (aba SITE + aba DE-PARA CNAE) e grava nas staging tables.

Incremental (ver incremental.py): o BNDES republica o historico INTEIRO a cada
vez, entao em vez de recarregar bndes_raw do zero, so inserimos as linhas cujo
hash de conteudo ainda nao existe na tabela -- as linhas ja conhecidas (a grande
maioria, toda semana) sao ignoradas sem custo de escrita no banco.
"""
import traceback
import unicodedata

import pandas as pd

from db import get_connection, get_engine
from download import BNDES_PATH
from incremental import backfill_row_hashes, compute_row_hash, existing_hashes, insert_new_rows


def _normalizar_nome_aba(nome: str) -> str:
    """Remove acentos/case/espacos duplicados de um nome de aba, so para
    COMPARACAO -- nunca usado como valor de fato (ver `_resolver_aba`)."""
    nfkd = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _resolver_aba(path, alvo: str) -> str:
    """Acha o nome exato de uma aba do xlsx do BNDES, com fallback resiliente.

    Mesma classe de bug/correcao ja aplicada em src/parse_finep.py (commit
    68734bb, causa raiz real 2026-09-21: a FINEP renomeou levemente uma aba e o
    `pd.read_excel(..., sheet_name="...")` com nome EXATO derrubou o refresh
    inteiro). Tenta o nome exato primeiro (caminho mais comum) e cai para um
    match normalizado (sem acento, case-insensitive, espacos colapsados) se o
    exato nao bater -- cobre pequenas variacoes futuras da fonte (BNDES, fora do
    nosso controle) sem inventar dado nenhum. Se nem assim achar, levanta um
    erro com a lista real de abas do arquivo (mais facil de diagnosticar do que
    o ValueError generico do pandas)."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        nomes = wb.sheetnames
        if alvo in nomes:
            return alvo
        alvo_norm = _normalizar_nome_aba(alvo)
        for nome in nomes:
            if _normalizar_nome_aba(nome) == alvo_norm:
                print(f"  aviso: aba {alvo!r} nao encontrada exata, usando {nome!r} (match normalizado)")
                return nome
        raise ValueError(f"Nenhuma aba {alvo!r} encontrada em {path}. Abas disponiveis: {nomes}")
    finally:
        wb.close()

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
    """Retorna (n_novas, total_agora, erros). `erros` e uma lista de strings --
    vazia se as duas abas foram lidas com sucesso, com um item por aba que
    falhou mesmo apos o lookup resiliente (ver `_resolver_aba`). As duas leituras
    (SITE e DE-PARA CNAE) sao isoladas uma da outra: uma falha em uma NAO impede
    a outra de ser processada, e o chamador (refresh.py) decide o que fazer com
    isso -- best-effort, nunca finge sucesso (o erro real fica em `erros`)."""
    erros = []

    df = None
    total_planilha = 0
    try:
        aba_site = _resolver_aba(path, "SITE")
        print(f"Lendo {path} (aba {aba_site!r})...")
        df = pd.read_excel(path, sheet_name=aba_site, header=4, engine="openpyxl")
        df = df.rename(columns=BNDES_COLUMNS)
        df = df[[c for c in BNDES_COLUMNS.values() if c in df.columns]]

        df["cnpj"] = _clean_cnpj(df["cnpj"])
        df["data_contratacao"] = pd.to_datetime(df["data_contratacao"], errors="coerce").dt.strftime("%Y-%m-%d")
        for col in ["valor_contratado", "valor_desembolsado", "juros", "prazo_carencia_meses", "prazo_amortizacao_meses"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        total_planilha = len(df)
    except Exception:
        erro = f"BNDES: aba 'SITE' falhou (nao entrou nenhuma operacao nova do BNDES nesta rodada):\n{traceback.format_exc()}"
        print(erro)
        erros.append(erro)
        df = None

    de_para = None
    try:
        aba_de_para = _resolver_aba(path, "DE-PARA CNAE")
        print(f"Lendo {path} (aba {aba_de_para!r})...")
        de_para = pd.read_excel(path, sheet_name=aba_de_para, header=3, engine="openpyxl")
        de_para = de_para.rename(columns=DE_PARA_COLUMNS)
        de_para = de_para[[c for c in DE_PARA_COLUMNS.values() if c in de_para.columns]]
        de_para = de_para.dropna(how="all")
    except Exception:
        erro = f"BNDES: aba 'DE-PARA CNAE' falhou (crosswalk de setor nao foi atualizado nesta rodada):\n{traceback.format_exc()}"
        print(erro)
        erros.append(erro)
        de_para = None

    novas = pd.DataFrame()
    conn = get_connection()
    try:
        total_agora = conn.execute("SELECT COUNT(*) FROM bndes_raw").fetchone()[0]

        if df is not None:
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
            conn.commit()
            total_agora = conn.execute("SELECT COUNT(*) FROM bndes_raw").fetchone()[0]

        if de_para is not None:
            # de_para_cnae fica na lista de rebuild completo (tabela pequena, sem
            # problema de chave/duplicacao) -- ja foi dropada e recriada antes desta
            # chamada, entao um append aqui equivale a um reload completo. to_sql precisa
            # de um engine SQLAlchemy (nao da conexao psycopg crua -- pandas nao suporta
            # isso de forma confiavel, ver docstring de db.get_engine()).
            de_para.to_sql("de_para_cnae", get_engine(), if_exists="append", index=False)
    finally:
        conn.close()

    print(
        f"BNDES: {len(novas)} operacoes NOVAS inseridas (planilha tem {total_planilha} linhas no total, "
        f"bndes_raw tem {total_agora} apos o refresh), "
        f"{len(de_para) if de_para is not None else 0} linhas de-para CNAE gravadas."
    )
    return len(novas), total_agora, erros


if __name__ == "__main__":
    from db import init_db

    init_db()
    parse_bndes()
