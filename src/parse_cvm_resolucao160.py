"""Le o SEGUNDO CSV do zip da CVM ("oferta_resolucao_160.csv" -- rito automatico,
Resolucao CVM 160, sucessora da ICVM 400/476 para a maior parte das emissoes
modernas) e grava na staging table `cvm_oferta_resolucao_160_raw` -- so as linhas de
instrumentos de DIVIDA, MESMO escopo de parse_cvm.py (reaproveita
ESCOPO_REGEX_DIVIDA de la, ver comentario la sobre a correcao do CPR-F).

ACHADO REAL do coordenador (2026-09-16), DEPOIS que o pipeline de
cvm_oferta_distribuicao_raw ja tinha rodado pela primeira vez: este arquivo cobre
EXATAMENTE 2023-2026 (o rito automatico so existe desde entao) e tem 14.493 linhas
no total -- contra so 7 linhas de cvm_oferta_distribuicao_raw nesse MESMO periodo.
Sem integrar este arquivo, o radar ficava praticamente cego pra atividade recente.
Ver CLAUDE.md, secao "Radar de Credito Primario", para a analise completa
(contagem por Valor_Mobiliario, decisao sobre CPR-F, checagem de duplicidade contra
o arquivo principal).

Encoding/delimitador: MESMO do arquivo principal (latin-1, ";").

Chave natural: DIFERENTE do arquivo principal -- `Numero_Requerimento` aqui e
CONFIRMADO unico e nao-nulo nas 14.493 linhas (checado ao vivo contra o CSV
inteiro, 2026-09-16), ao contrario de numero_registro_oferta no arquivo principal
(76% nulo). Mesmo assim, o staging usa a MESMA estrategia de row_hash do resto do
pipeline (nao Numero_Requerimento como chave de upsert) -- por consistencia com
bndes_raw/finep_*_raw/cvm_oferta_distribuicao_raw (todos republicados por inteiro a
cada atualizacao, nao incremental na origem) e porque um upsert por
Numero_Requerimento exigiria uma logica de dedup DIFERENTE so pra este arquivo,
sem ganho real (a suposicao de unicidade e re-confirmavel a qualquer momento
comparando COUNT(*) x COUNT(DISTINCT numero_requerimento), mas nao e o que decide
o que e "linha nova" aqui).

DUPLICIDADE ENTRE OS DOIS ARQUIVOS: checado ao vivo (2026-09-16) -- ZERO overlap de
Numero_Processo entre os dois CSVs (14.493 processos distintos aqui, nenhum
aparece no arquivo principal). Uma coincidencia de (CNPJ_Emissor, Emissao) foi
encontrada em 312 combinacoes, mas inspecionar varias delas mostrou que sao
operacoes DIFERENTES do MESMO emissor reutilizando o mesmo numero de emissao em
programas distintos (ex: emissor serial de securitizacao com uma "Emissao 96" de
CRI num arquivo e uma "Emissao 96" de CRA totalmente diferente no outro, valores e
datas nao batem) -- NAO e duplicacao real. Conclusao: os dois arquivos sao
conjuntos DISJUNTOS na pratica, nenhuma logica de dedup entre eles foi necessaria."""
import re

import pandas as pd

from db import get_connection
from download_cvm import RESOLUCAO160_CSV_PATH
from incremental import backfill_row_hashes, compute_row_hash, existing_hashes, insert_new_rows
from parse_cvm import ESCOPO_REGEX_DIVIDA, remover_acentos

# CamelCase oficial -> snake_case. Escopo de colunas DELIBERADAMENTE reduzido, MESMO
# criterio do arquivo principal (ver parse_cvm.py::CVM_COLUMNS): exclui as ~24
# colunas de COMPOSICAO DE INVESTIDORES (Num_Invest_Pessoa_Natural,
# Qtde_VM_Fundos_Investimento etc.) -- quem comprou o ativo, nao o credito em si.
R160_COLUMNS = {
    "Numero_Requerimento": "numero_requerimento",
    "Rito_Requerimento": "rito_requerimento",
    "Numero_Processo": "numero_processo",
    "Data_requerimento": "data_requerimento",
    "Data_Registro": "data_registro",
    "Data_Encerramento": "data_encerramento",
    "Status_Requerimento": "status_requerimento",
    "Valor_Mobiliario": "valor_mobiliario",
    "Tipo_requerimento": "tipo_requerimento",
    "Bookbuilding": "bookbuilding",
    "CNPJ_Emissor": "cnpj_emissor",
    "Nome_Emissor": "nome_emissor",
    "CNPJ_Lider": "cnpj_lider",
    "Nome_Lider": "nome_lider",
    "Grupo_Coordenador": "grupo_coordenador",
    "Tipo_Oferta": "tipo_oferta",
    "Emissao": "emissao",
    "Qtde_Total_Registrada": "qtde_total_registrada",
    "Valor_Total_Registrado": "valor_total_registrado",
    "Oferta_inicial": "oferta_inicial",
    "Oferta_vasos_comunicantes": "oferta_vasos_comunicantes",
    "Publico_alvo": "publico_alvo",
    "Reabertura_serie": "reabertura_serie",
    "Titulo_classificado_como_sustentavel": "titulo_classificado_como_sustentavel",
    "Titulo_padronizado": "titulo_padronizado",
    "Destinacao_recursos": "destinacao_recursos",
    "Data_deliberacao_aprovou_oferta": "data_deliberacao_aprovou_oferta",
    "Mercado_negociacao": "mercado_negociacao",
    "Tipo_lastro": "tipo_lastro",
    "Regime_fiduciario": "regime_fiduciario",
    "Ativos_alvo": "ativos_alvo",
    "Descricao_garantias": "descricao_garantias",
    "Descricao_lastro": "descricao_lastro",
    "Identificacao_devedores_coobrigados": "identificacao_devedores_coobrigados",
    "Possibilidade_revolvencia": "possibilidade_revolvencia",
    "FIDC_nao_padronizado": "fidc_nao_padronizado",
    "Titulo_incentivado": "titulo_incentivado",
    "Regime_distribuicao": "regime_distribuicao",
    "Tipo_societario": "tipo_societario",
    "Administrador": "administrador",
    "Gestor": "gestor",
    "Agente_fiduciario": "agente_fiduciario",
    "Escriturador": "escriturador",
    "Custodiante": "custodiante",
    "Avaliador_Risco": "avaliador_risco",
    "Processo_SEI": "processo_sei",
    "Endereco_emissor_rede_mundial_computadores": "endereco_emissor_rede_mundial_computadores",
}

NUMERIC_COLS = ["qtde_total_registrada", "valor_total_registrado"]

# Diferente do arquivo principal: SEM data_emissao/data_vencimento (nao existem
# nesta fonte -- confirmado contra as 71 colunas oficiais, ver CLAUDE.md).
DATE_COLS = [
    "data_requerimento", "data_registro", "data_encerramento",
    "data_deliberacao_aprovou_oferta",
]

R160_HASH_COLS = list(R160_COLUMNS.values())


def _limpar_cnpj(series: pd.Series) -> pd.Series:
    """Mesma logica de parse_cvm.py::_limpar_cnpj (nao duplicada por import so
    porque e uma funcao pequena e este modulo ja importa varias coisas de la --
    mantida local para nao acoplar demais os dois parsers)."""
    def limpar(valor):
        if pd.isna(valor):
            return None
        digitos = re.sub(r"\D", "", str(valor))
        if not digitos:
            return None
        return digitos.zfill(14)
    return series.map(limpar)


def _em_escopo(valor_mobiliario: pd.Series) -> pd.Series:
    normalizado = valor_mobiliario.fillna("").map(remover_acentos).str.upper()
    return normalizado.str.contains(ESCOPO_REGEX_DIVIDA, regex=True, na=False)


def parse_cvm_resolucao160(path=RESOLUCAO160_CSV_PATH):
    print(f"Lendo {path} (encoding latin-1, delimitador ';')...")
    df = pd.read_csv(path, sep=";", encoding="latin-1", dtype=str, low_memory=False)
    total_csv = len(df)
    df = df.rename(columns=R160_COLUMNS)
    df = df[[c for c in R160_COLUMNS.values() if c in df.columns]]

    em_escopo = _em_escopo(df["valor_mobiliario"])
    n_fora_escopo = (~em_escopo).sum()
    df = df[em_escopo].copy()
    total_escopo = len(df)

    df["cnpj_emissor"] = _limpar_cnpj(df["cnpj_emissor"])
    df["cnpj_lider"] = _limpar_cnpj(df["cnpj_lider"])

    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in DATE_COLS:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")

    por_tipo = df["valor_mobiliario"].value_counts()

    conn = get_connection()
    try:
        n_backfill = backfill_row_hashes(conn, "cvm_oferta_resolucao_160_raw", R160_HASH_COLS)
        if n_backfill:
            print(f"cvm_oferta_resolucao_160_raw: {n_backfill} linhas existentes tiveram row_hash calculado retroativamente.")
        hashes_existentes = existing_hashes(conn, "cvm_oferta_resolucao_160_raw")

        df["row_hash"] = compute_row_hash(conn, "cvm_oferta_resolucao_160_raw", df, R160_HASH_COLS)
        novas = df[~df["row_hash"].isin(hashes_existentes)].copy()
        novas = novas.drop_duplicates(subset=["row_hash"])

        insert_new_rows(conn, "cvm_oferta_resolucao_160_raw", novas, R160_HASH_COLS + ["row_hash"])
        conn.commit()
        total_agora = conn.execute("SELECT COUNT(*) FROM cvm_oferta_resolucao_160_raw").fetchone()[0]
    finally:
        conn.close()

    print(
        f"CVM oferta_resolucao_160: {total_csv} linhas no CSV total, {total_escopo} em escopo "
        f"(instrumentos de divida, {n_fora_escopo} fora de escopo descartadas), "
        f"{len(novas)} NOVAS inseridas (cvm_oferta_resolucao_160_raw tem {total_agora} apos o refresh)."
    )
    print("Distribuicao por Valor_Mobiliario (linhas em escopo neste CSV):")
    for tipo, n in por_tipo.items():
        print(f"  {tipo}: {n}")
    return len(novas), total_agora


if __name__ == "__main__":
    from db import init_db

    init_db()
    parse_cvm_resolucao160()
