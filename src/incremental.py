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
sem sufixo .0, uma coluna REAL converte int pra float). Como agora inserimos com
SQL parametrizado explicito (pedido do projeto, p/ compatibilidade com libsql/
Turso), replicamos esse comportamento de affinity manualmente em `_coerce_for_affinity`
-- e usamos a MESMA funcao tanto para calcular o hash quanto para montar os
parametros do INSERT, para o hash bater exatamente com o que fica gravado.
"""
import datetime
import hashlib

import numpy as np
import pandas as pd

NULL_TOKEN = "\x00NULL\x00"


def column_types(conn, table: str) -> dict:
    """Nome de coluna -> tipo declarado no CREATE TABLE (ex: 'TEXT', 'REAL'), em
    maiusculas. Usa PRAGMA table_info, disponivel tanto em SQLite quanto no libsql."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1]: (r[2] or "").upper() for r in rows}


def _is_na(value) -> bool:
    if value is None:
        return False  # None ja e tratado antes de chamar isso
    try:
        resultado = pd.isna(value)
        return bool(resultado)
    except (TypeError, ValueError):
        return False


def coerce_for_affinity(value, decl_type: str):
    """Normaliza `value` para o tipo Python que a coluna `decl_type` (affinity do
    SQLite) realmente vai armazenar -- mesmo resultado esteja o valor vindo de um
    DataFrame recem-lido do Excel (numpy int64/float64/Timestamp) ou de uma linha
    ja gravada no banco (Python nativo). Ver docstring do modulo."""
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

    decl_type = decl_type or ""
    if "CHAR" in decl_type or "TEXT" in decl_type or "CLOB" in decl_type:
        if isinstance(value, (bool, np.bool_)):
            return str(int(value))
        if isinstance(value, (int, np.integer)):
            return str(int(value))
        if isinstance(value, (float, np.floating)):
            fv = float(value)
            return str(int(fv)) if fv.is_integer() else repr(fv)
        return str(value)

    if "INT" in decl_type:
        return int(value)

    if "REAL" in decl_type or "FLOA" in decl_type or "DOUB" in decl_type:
        return float(value)

    # affinity NUMERIC ou tipo nao mapeado: ainda assim converte tipos numpy pra
    # nativos do Python (sqlite3/libsql podem nao aceitar np.int64/np.float64 direto).
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
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
    valor pelo tipo REAL da coluna de destino (ver coerce_for_affinity) -- assim o
    hash de uma linha recem-lida do Excel bate com o hash da mesma linha lida de
    volta do banco (backfill_row_hashes usa a mesma normalizacao)."""
    if df.empty:
        return pd.Series([], dtype=object)
    tipos = column_types(conn, table)
    tipos_lista = [tipos.get(c, "") for c in cols]

    def hash_row(row):
        valores = [coerce_for_affinity(v, t) for v, t in zip(row, tipos_lista)]
        return _hash_values(valores)

    return df[cols].apply(lambda row: hash_row(row.tolist()), axis=1)


def existing_hashes(conn, table: str) -> set:
    rows = conn.execute(f"SELECT row_hash FROM {table} WHERE row_hash IS NOT NULL").fetchall()
    return {r[0] for r in rows}


def backfill_row_hashes(conn, table: str, cols: list, id_col: str = "id") -> int:
    """Preenche row_hash para linhas gravadas ANTES desta coluna existir (banco
    ja em producao). So roda de fato na primeira vez que este codigo executa contra
    um banco existente -- depois disso nunca ha mais linha com row_hash NULL."""
    tipos = column_types(conn, table)
    tipos_lista = [tipos.get(c, "") for c in cols]
    col_list = ", ".join([id_col] + cols)
    rows = conn.execute(f"SELECT {col_list} FROM {table} WHERE row_hash IS NULL").fetchall()
    if not rows:
        return 0
    updates = []
    for row in rows:
        rid = row[0]
        valores = [coerce_for_affinity(v, t) for v, t in zip(row[1:], tipos_lista)]
        updates.append((_hash_values(valores), rid))
    cur = conn.cursor()
    cur.executemany(f"UPDATE {table} SET row_hash = ? WHERE {id_col} = ?", updates)
    conn.commit()
    return len(updates)


def insert_new_rows(conn, table: str, df_new: pd.DataFrame, cols: list) -> int:
    """Insere so as linhas de `df_new` (que ja deve trazer `row_hash` calculado em
    uma das colunas de `cols`, quando aplicavel), via SQL parametrizado simples
    (`?`) -- funciona igual em SQLite local e em libsql/Turso (ver db.py). Cada
    valor passa por `coerce_for_affinity` antes do bind, pelo mesmo motivo do hash:
    consistencia de tipo entre o que foi hasheado e o que efetivamente e gravado."""
    if df_new.empty:
        return 0
    tipos = column_types(conn, table)
    tipos_lista = [tipos.get(c, "") for c in cols]
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(cols)
    linhas = [
        tuple(coerce_for_affinity(v, t) for v, t in zip(row, tipos_lista))
        for row in df_new[cols].itertuples(index=False, name=None)
    ]
    cur = conn.cursor()
    cur.executemany(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", linhas)
    conn.commit()
    return len(linhas)
