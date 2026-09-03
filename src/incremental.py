"""Utilitarios compartilhados para o refresh incremental das tabelas *_raw.

BNDES e FINEP republicam o arquivo com TODO o historico a cada vez (nao so as
linhas novas), entao um "append cego" duplicaria todas as operacoes ja existentes
a cada refresh semanal. Precisamos de uma forma de saber, linha a linha, "essa
linha ja esta na tabela?" para inserir so o que e novo.

A ideia obvia -- usar numero_contrato (BNDES) ou contrato_finep_agente (FINEP
Credito Descentralizado) como chave natural -- NAO funciona: checagem contra os
dados reais mostrou que essas colunas NAO sao unicas por linha. O BNDES publica
uma linha por DESEMBOLSO (varias linhas por numero_contrato, uma por tranche
liberada em uma data). O contrato_finep_agente e o numero do CONVENIO entre a
FINEP e o agente financeiro, com varios beneficiarios diferentes puxando credito
sob o mesmo convenio (chegando a 740 linhas para um so numero). `contrato` do
FINEP Credito Direto, por outro lado, ja e unico por linha nos dados atuais --
mas para manter os quatro raw tables com a mesma logica (mais simples de manter
e de auditar) usamos a MESMA estrategia nos quatro: hash de conteudo da linha
inteira (todas as colunas de negocio, sem o id autoincrement).

Limitacao conhecida (documentada para quem for revisar): se o BNDES ou a FINEP
um dia CORRIGIREM um valor de uma linha ja publicada antes (ex: ajustar um
valor_desembolsado historico), o hash muda e a linha corrigida seria inserida
como uma linha NOVA (duplicada, com o valor antigo ainda la) em vez de substituir
a antiga -- nenhum update no lugar acontece aqui, so insercao de linhas com
conteudo novo. Na pratica, desembolsos e contratacoes historicos sao fatos
financeiros que nao esperamos que sejam reescritos retroativamente, mas isso e
uma suposicao, nao uma garantia -- vale conferir de vez em quando (ex: comparar
COUNT(*) por numero_contrato ao longo do tempo) se isso realmente nunca acontece.

IMPORTANTE sobre tipos: o pandas.read_excel devolve numeros (ex: numero_contrato,
municipio_codigo) como int64/float64 mesmo quando a coluna de destino e TEXT no
schema -- e colunas REAL (ex: prazo_carencia_meses) as vezes vem como int64
quando a planilha nao tem NaN nessa coluna. O codigo antigo usava
`DataFrame.to_sql(...)`, que resolvia essa conversao de tipo por baixo dos panos
(o SQLite aplica "affinity": uma coluna TEXT converte numero pra string "redonda"
sem sufixo .0, uma coluna REAL converte int pra float). Agora que o banco e
Postgres (colunas ja estritamente tipadas na criacao da tabela, sem affinity
dinamica no estilo SQLite) e inserimos com SQL parametrizado explicito, o unico
trabalho real de `coerce_for_pg` e normalizar tipos numpy/pandas (np.int64,
np.float64, NaN/NaT, pd.Timestamp) para tipos nativos do Python ANTES do bind --
psycopg (tipado, ao contrario do sqlite3) levanta erro de adaptacao se receber um
np.int64/np.float64 cru. Usamos a MESMA funcao tanto para calcular o hash quanto
para montar os parametros do INSERT, para o hash bater exatamente com o que fica
gravado.
"""
import datetime
import hashlib

import numpy as np
import pandas as pd

NULL_TOKEN = "\x00NULL\x00"


def column_types(conn, table: str) -> dict:
    """Nome de coluna -> tipo declarado no Postgres (ex: 'text', 'real', 'integer'),
    em minusculas, via information_schema.columns (substitui o antigo PRAGMA
    table_info, especifico de SQLite/libsql)."""
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?",
        (table,),
    ).fetchall()
    return {r[0]: (r[1] or "").lower() for r in rows}


def _is_na(value) -> bool:
    if value is None:
        return False  # None ja e tratado antes de chamar isso
    try:
        resultado = pd.isna(value)
        return bool(resultado)
    except (TypeError, ValueError):
        return False


def coerce_for_pg(value):
    """Normaliza `value` (numpy/pandas ou Python nativo) para um tipo que o psycopg
    aceita bindar sem erro de adaptacao -- ver docstring do modulo. Diferente do
    antigo `coerce_for_affinity`, NAO recebe/usa o tipo declarado da coluna: o
    Postgres ja e estritamente tipado desde o CREATE TABLE (sem affinity dinamica
    no estilo SQLite), entao normalizar o VALOR (numpy -> Python nativo, NaN/NaT ->
    None) e suficiente -- o proprio Postgres rejeita/converte na hora do INSERT se o
    valor nao bater com o tipo da coluna."""
    if value is None:
        return None
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return None
    if _is_na(value):
        return None

    if isinstance(value, (datetime.date, datetime.datetime, pd.Timestamp)):
        # colunas de data que o codigo original nunca convertia explicitamente pra
        # string (ex: data_entrada_sf) -- pandas.to_sql fazia essa conversao sozinho.
        return str(value)

    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def _normalize_for_hash(value) -> str:
    if value is None:
        return NULL_TOKEN
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _hash_values(values) -> str:
    normalizado = "|".join(_normalize_for_hash(v) for v in values)
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()


def compute_row_hash(conn, table: str, df: pd.DataFrame, cols: list) -> pd.Series:
    """Hash de conteudo por linha, na ORDEM FIXA de `cols`, apos normalizar cada
    valor (ver coerce_for_pg) -- assim o hash de uma linha recem-lida do Excel bate
    com o hash da mesma linha lida de volta do banco (backfill_row_hashes usa a
    mesma normalizacao)."""
    if df.empty:
        return pd.Series([], dtype=object)

    def hash_row(row):
        valores = [coerce_for_pg(v) for v in row]
        return _hash_values(valores)

    return df[cols].apply(lambda row: hash_row(row.tolist()), axis=1)


def existing_hashes(conn, table: str) -> set:
    rows = conn.execute(f"SELECT row_hash FROM {table} WHERE row_hash IS NOT NULL").fetchall()
    return {r[0] for r in rows}


def backfill_row_hashes(conn, table: str, cols: list, id_col: str = "id") -> int:
    """Preenche row_hash para linhas gravadas ANTES desta coluna existir (banco
    ja em producao). So roda de fato na primeira vez que este codigo executa contra
    um banco existente -- depois disso nunca ha mais linha com row_hash NULL."""
    col_list = ", ".join([id_col] + cols)
    rows = conn.execute(f"SELECT {col_list} FROM {table} WHERE row_hash IS NULL").fetchall()
    if not rows:
        return 0
    updates = []
    for row in rows:
        rid = row[0]
        valores = [coerce_for_pg(v) for v in row[1:]]
        updates.append((_hash_values(valores), rid))
    cur = conn.cursor()
    cur.executemany(f"UPDATE {table} SET row_hash = ? WHERE {id_col} = ?", updates)
    conn.commit()
    return len(updates)


def insert_new_rows(conn, table: str, df_new: pd.DataFrame, cols: list) -> int:
    """Insere so as linhas de `df_new` (que ja deve trazer `row_hash` calculado em
    uma das colunas de `cols`, quando aplicavel), via SQL parametrizado simples
    (`?`, traduzido para `%s` do Postgres por db_compat.py) -- mesmo estilo de
    sempre, so a normalizacao de tipo mudou (ver coerce_for_pg). Cada valor passa
    por `coerce_for_pg` antes do bind, pelo mesmo motivo do hash: consistencia de
    tipo entre o que foi hasheado e o que efetivamente e gravado."""
    if df_new.empty:
        return 0
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(cols)
    linhas = [
        tuple(coerce_for_pg(v) for v in row)
        for row in df_new[cols].itertuples(index=False, name=None)
    ]
    cur = conn.cursor()
    cur.executemany(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", linhas)
    conn.commit()
    return len(linhas)
