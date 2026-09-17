"""Le o CSV "Ofertas Publicas de Distribuicao" da CVM e grava na staging table
`cvm_oferta_distribuicao_raw`, so as linhas de instrumentos de DIVIDA (debentures,
CRI, CRA, notas promissorias/comerciais, letras financeiras, CDCA, CCB) -- o dataset
completo tem ~49 mil linhas (acoes, cotas de fundo, BDR etc), das quais so ~12 mil
sao instrumentos de divida relevantes para o Radar de Credito Primario.

Encoding do arquivo oficial: latin-1 (nao utf-8), delimitador ";" -- confirmado ao
vivo inspecionando uma amostra real (ver CLAUDE.md, secao "Radar de Credito Primario").

Incremental (mesmo padrao de parse_bndes.py/parse_finep.py, ver incremental.py):
`Numero_Registro_Oferta` PARECIA a chave natural obvia (e o nome oficial do campo,
"numero de registro da oferta"), mas checagem contra o CSV real mostrou que NAO
serve como chave de upsert sozinha -- 75.8% das linhas de divida (9277 de 12242) tem
esse campo NULO (ofertas com DISPENSA de registro, nunca chegam a ter um numero de
registro -- ver Modalidade_Dispensa_Registro/Data_Dispensa_Oferta preenchidos
nesses casos). `Numero_Processo` tambem nao serve sozinho (um UNICO processo
administrativo pode conter DEZENAS de series/emissoes diferentes, cada uma sua
propria linha -- confirmado um processo com 55 series). Por isso usamos a MESMA
estrategia ja validada para BNDES/FINEP: hash de conteudo da linha inteira
(row_hash), nao uma chave natural -- o dataset da CVM tambem e republicado por
inteiro (nao incremental) a cada atualizacao diaria, mesmo padrao de BNDES/FINEP."""
import re
import unicodedata

import pandas as pd

from db import get_connection
from download_cvm import CVM_CSV_PATH
from incremental import backfill_row_hashes, compute_row_hash, existing_hashes, insert_new_rows

# Nomes das colunas no CSV oficial (CamelCase com underscore) -> snake_case.
# Escopo DELIBERADAMENTE restrito as colunas relevantes para descrever a OFERTA/O
# ATIVO em si (identificacao, datas, valores, indexador) -- o CSV oficial tem ~30
# colunas adicionais de COMPOSICAO DE INVESTIDORES (Nr_Pessoa_Fisica, Qtd_Fundos_
# Investimento, Qtd_Investidor_Estrangeiro etc.) que descrevem QUEM comprou o
# ativo, nao o credito em si -- fora do escopo de um radar de credito incentivado
# (poderiam ser adicionadas depois, sem migracao alguma nos dados ja gravados, se
# um dia isso virar um requisito real; ver CLAUDE.md).
CVM_COLUMNS = {
    "Numero_Processo": "numero_processo",
    "Numero_Registro_Oferta": "numero_registro_oferta",
    "Tipo_Oferta": "tipo_oferta",
    "Tipo_Componente_Oferta_Mista": "tipo_componente_oferta_mista",
    "Tipo_Ativo": "tipo_ativo",
    "CNPJ_Emissor": "cnpj_emissor",
    "Nome_Emissor": "nome_emissor",
    "CNPJ_Lider": "cnpj_lider",
    "Nome_Lider": "nome_lider",
    "Nome_Vendedor": "nome_vendedor",
    "CNPJ_Ofertante": "cnpj_ofertante",
    "Nome_Ofertante": "nome_ofertante",
    "Rito_Oferta": "rito_oferta",
    "Modalidade_Oferta": "modalidade_oferta",
    "Modalidade_Registro": "modalidade_registro",
    "Modalidade_Dispensa_Registro": "modalidade_dispensa_registro",
    "Data_Abertura_Processo": "data_abertura_processo",
    "Data_Protocolo": "data_protocolo",
    "Data_Dispensa_Oferta": "data_dispensa_oferta",
    "Data_Registro_Oferta": "data_registro_oferta",
    "Data_Inicio_Oferta": "data_inicio_oferta",
    "Data_Encerramento_Oferta": "data_encerramento_oferta",
    "Emissao": "emissao",
    "Classe_Ativo": "classe_ativo",
    "Serie": "serie",
    "Especie_Ativo": "especie_ativo",
    "Forma_Ativo": "forma_ativo",
    "Data_Emissao": "data_emissao",
    "Data_Vencimento": "data_vencimento",
    "Quantidade_Sem_Lote_Suplementar": "quantidade_sem_lote_suplementar",
    "Quantidade_No_Lote_Suplementar": "quantidade_no_lote_suplementar",
    "Quantidade_Total": "quantidade_total",
    "Preco_Unitario": "preco_unitario",
    "Valor_Total": "valor_total",
    "Oferta_Inicial": "oferta_inicial",
    "Oferta_Incentivo_Fiscal": "oferta_incentivo_fiscal",
    "Oferta_Regime_Fiduciario": "oferta_regime_fiduciario",
    "Atualizacao_Monetaria": "atualizacao_monetaria",
    "Juros": "juros",
    "Tipo_Societario_Emissor": "tipo_societario_emissor",
    "Tipo_Fundo_Investimento": "tipo_fundo_investimento",
    "Ultimo_Comunicado": "ultimo_comunicado",
    "Data_Comunicado": "data_comunicado",
}

NUMERIC_COLS = [
    "quantidade_sem_lote_suplementar", "quantidade_no_lote_suplementar",
    "quantidade_total", "preco_unitario", "valor_total",
]

DATE_COLS = [
    "data_abertura_processo", "data_protocolo", "data_dispensa_oferta",
    "data_registro_oferta", "data_inicio_oferta", "data_encerramento_oferta",
    "data_emissao", "data_vencimento", "data_comunicado",
]

CVM_HASH_COLS = list(CVM_COLUMNS.values())

# Instrumentos de DIVIDA em escopo (item 2 do pedido) -- regex com \b (word boundary)
# sobre o texto MAIUSCULO/SEM ACENTO de Tipo_Ativo (aqui) OU Valor_Mobiliario (em
# parse_cvm_resolucao160.py -- MESMA regex, reaproveitada, ver ESCOPO_REGEX_DIVIDA
# abaixo), para casar tanto o nome por extenso quanto a sigla (ex: "CERTIFICADOS DE
# RECEBIVEIS IMOBILIARIOS - CRI" E "CERTIFICADO DE RECEBIVEIS IMOBILIARIOS" precisam
# bater, mas SEM abrir mao de \b nas siglas curtas -- CRI/CRA/CCB/CDCA sao 3-4
# letras, um match por substring cru arriscaria falso-positivo). Confirmado contra
# os 38 valores distintos reais de Tipo_Ativo no CSV (ver CLAUDE.md): esta regex
# bate exatamente os 14 valores de divida esperados, nem mais nem menos -- incluindo
# os 3 casos "TOKENS REPRESENTATIVOS DE DEBENTURES (SANDBOX REGULATORIO)" (token e
# representativo de uma debenture de verdade, mesma natureza de credito) e excluindo
# de proposito WARRANTS/WARRANTS AGROPECUARIOS (nao sao instrumento de divida) e as
# 3 linhas ambiguas "CERTIFICADOS DE RECEBIVEIS" (sem qualificador IMOBILIARIOS/
# AGRONEGOCIO, nao da pra saber se e CRI ou CRA sem inventar).
#
# CORRECAO REAL (2026-09-16, achado do coordenador DEPOIS que este pipeline ja
# tinha rodado pela primeira vez): a exclusao de CPR-F documentada abaixo (e no
# CLAUDE.md, ate esta correcao) estava ERRADA -- CPR-F *e* um valor mobiliario
# registrado na CVM, so nao aparecia no dataset "oferta_distribuicao.csv" porque
# esse instrumento e tratado pelo rito automatico (Resolucao CVM 160), reportado no
# segundo CSV do MESMO zip ("oferta_resolucao_160.csv", ver
# src/parse_cvm_resolucao160.py) -- 18 linhas reais confirmadas la (Klabin, Suzano,
# Duratex etc.). Termo adicionado aqui (\bCPR-F\b|PRODUTO RURAL FINANCEIRA) mesmo
# este arquivo (oferta_distribuicao.csv) nunca tendo tido nenhuma linha com esse
# termo (confirmado ao vivo: 0 ocorrencias de "PRODUTO RURAL"/"CPR" em Tipo_Ativo) --
# adicionar aqui e inofensivo para ESTE arquivo e garante que os dois parsers
# (parse_cvm.py e parse_cvm_resolucao160.py) compartilham a MESMA definicao de
# escopo, sem risco de duas regras divergirem com o tempo.
ESCOPO_REGEX_DIVIDA = re.compile(
    r"DEBENTURE"
    r"|RECEBIVEIS IMOBILIARIOS|\bCRI\b"
    r"|RECEBIVEIS DO AGRONEGOCIO|\bCRA\b"
    r"|NOTAS PROMISSORIAS"
    r"|NOTAS COMERCIAIS"
    r"|LETRAS FINANCEIRAS"
    r"|DIREITOS CREDITORIOS DO AGRONEGOCIO|\bCDCA\b"
    r"|CREDITO BANCARIO|\bCCB\b"
    r"|PRODUTO RURAL FINANCEIRA|\bCPR-F\b",
    re.IGNORECASE,
)
# Alias privado (nome usado no resto deste arquivo) -- mantido para nao precisar
# renomear todos os usos abaixo.
_ESCOPO_REGEX = ESCOPO_REGEX_DIVIDA


def remover_acentos(texto: str) -> str:
    """Publica (sem "_") -- reaproveitada por unify_primario.py para normalizar
    Tipo_Ativo da mesma forma exata usada aqui para filtrar o escopo, ao mapear
    para instrumento_padronizado (evita duas normalizacoes levemente diferentes
    divergindo com o tempo)."""
    if texto is None:
        return texto
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _em_escopo(tipo_ativo: pd.Series) -> pd.Series:
    normalizado = tipo_ativo.fillna("").map(remover_acentos).str.upper()
    return normalizado.str.contains(_ESCOPO_REGEX, regex=True, na=False)


def _limpar_cnpj(series: pd.Series) -> pd.Series:
    """Diferente do _clean_cnpj usado em parse_bndes.py/parse_finep.py: aqui o CNPJ
    pode ser genuinamente NULO (ex: ofertante pessoa fisica, ou campo nao aplicavel a
    esta oferta) -- NAO faz zfill(14) de uma string vazia (isso viraria
    "00000000000000", um CNPJ falso). So limpa pontuacao e preenche com zero à
    esquerda quando ha de fato um CNPJ parcial."""
    def limpar(valor):
        if pd.isna(valor):
            return None
        digitos = re.sub(r"\D", "", str(valor))
        if not digitos:
            return None
        return digitos.zfill(14)
    return series.map(limpar)


def parse_cvm(path=CVM_CSV_PATH):
    print(f"Lendo {path} (encoding latin-1, delimitador ';')...")
    df = pd.read_csv(path, sep=";", encoding="latin-1", dtype=str, low_memory=False)
    total_csv = len(df)
    df = df.rename(columns=CVM_COLUMNS)
    df = df[[c for c in CVM_COLUMNS.values() if c in df.columns]]

    em_escopo = _em_escopo(df["tipo_ativo"])
    n_fora_escopo = (~em_escopo).sum()
    df = df[em_escopo].copy()
    total_escopo = len(df)

    df["cnpj_emissor"] = _limpar_cnpj(df["cnpj_emissor"])
    df["cnpj_lider"] = _limpar_cnpj(df["cnpj_lider"])
    df["cnpj_ofertante"] = _limpar_cnpj(df["cnpj_ofertante"])

    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # datas ja vem no formato AAAA-MM-DD (ver dicionario de dados oficial) -- so
    # normaliza via pandas para pegar eventuais formatos invalidos/vazios como NaT,
    # mantendo o mesmo formato de string ISO ja usado em todo o resto do projeto
    # (bndes_raw.data_contratacao etc, nunca datetime nativo).
    for col in DATE_COLS:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")

    por_tipo = df["tipo_ativo"].value_counts()

    conn = get_connection()
    try:
        n_backfill = backfill_row_hashes(conn, "cvm_oferta_distribuicao_raw", CVM_HASH_COLS)
        if n_backfill:
            print(f"cvm_oferta_distribuicao_raw: {n_backfill} linhas existentes tiveram row_hash calculado retroativamente.")
        hashes_existentes = existing_hashes(conn, "cvm_oferta_distribuicao_raw")

        df["row_hash"] = compute_row_hash(conn, "cvm_oferta_distribuicao_raw", df, CVM_HASH_COLS)
        novas = df[~df["row_hash"].isin(hashes_existentes)].copy()
        novas = novas.drop_duplicates(subset=["row_hash"])

        insert_new_rows(conn, "cvm_oferta_distribuicao_raw", novas, CVM_HASH_COLS + ["row_hash"])
        conn.commit()
        total_agora = conn.execute("SELECT COUNT(*) FROM cvm_oferta_distribuicao_raw").fetchone()[0]
    finally:
        conn.close()

    print(
        f"CVM oferta_distribuicao: {total_csv} linhas no CSV total, {total_escopo} em escopo "
        f"(instrumentos de divida, {n_fora_escopo} fora de escopo descartadas), "
        f"{len(novas)} NOVAS inseridas (cvm_oferta_distribuicao_raw tem {total_agora} apos o refresh)."
    )
    print("Distribuicao por Tipo_Ativo (linhas em escopo neste CSV):")
    for tipo, n in por_tipo.items():
        print(f"  {tipo}: {n}")
    return len(novas), total_agora


if __name__ == "__main__":
    from db import init_db

    init_db()
    parse_cvm()
