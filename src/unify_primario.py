"""Constroi a tabela unificada `operations_primario` (CVM -- Radar de Credito
Primario) a partir de `cvm_oferta_distribuicao_raw`.

Mesmo padrao incremental de unify.py::build_operations() (BNDES/FINEP): so processa
linhas de `cvm_oferta_distribuicao_raw` que ainda NAO tem uma linha correspondente em
`operations_primario` (raw_table + raw_id), e re-classifica emissores que ficaram sem
setor resolvido assim que o CNPJ deles for enriquecido (mesmo mecanismo do
enrich_cnae.py::enrich_pendentes_via_api ja usado pela FINEP).

Diferente de `operations` (BNDES=nativo / FINEP=enriquecido ou pendente), aqui so
existem DOIS estados possiveis por linha: setor_emissor resolvido, ou NULL (ainda
pendente) -- todo emissor da CVM depende do MESMO caminho de enriquecimento via
CNPJ (cnpj_cnae), nao ha uma fonte "nativa" de setor como o BNDES tem. Por isso nao
existe uma coluna setor_origem aqui (seria redundante com "setor_emissor IS NULL")."""
import re

import pandas as pd

from db import get_connection, get_engine
from incremental import insert_new_rows
from parse_cvm import remover_acentos

# Tipo_Ativo (normalizado: sem acento, maiusculo -- ver parse_cvm.remover_acentos)
# -> categoria canonica. Notas Promissorias e Notas Comerciais sao o MESMO
# instrumento sob nomes diferentes (a Lei 14.195/2021 renomeou "nota promissoria
# comercial" para "nota comercial" e trocou o registro da B3 pelo da CVM/escritural
# -- mesma natureza economica, unificadas de proposito sob 'Nota Comercial', ver
# CLAUDE.md). Chave EXATA (apos normalizacao) -- nenhum "contains"/regex aqui,
# diferente do filtro de escopo em parse_cvm.py: a essa altura a linha ja passou
# pelo filtro de escopo, entao so precisamos mapear os poucos valores exatos
# possiveis (confirmados contra os 38 valores distintos reais de Tipo_Ativo).
INSTRUMENTO_PADRONIZADO_MAP = {
    "DEBENTURES SIMPLES": "Debênture",
    "DEBENTURES CONVERSIVEIS": "Debênture",
    "DEBENTURES PERMUTAVEIS": "Debênture",
    "TOKENS REPRESENTATIVOS DE DEBENTURES (SANDBOX REGULATORIO)": "Debênture",
    "CERTIFICADOS DE RECEBIVEIS IMOBILIARIOS - CRI": "CRI",
    "CERTIFICADO DE RECEBIVEIS IMOBILIARIOS": "CRI",
    "CERTIFICADOS DE RECEBIVEIS DO AGRONEGOCIO - CRA": "CRA",
    "CERTIFICADO DE RECEBIVEIS DO AGRONEGOCIO": "CRA",
    "NOTAS PROMISSORIAS": "Nota Comercial",
    "NOTAS COMERCIAIS": "Nota Comercial",
    "LETRAS FINANCEIRAS": "Letra Financeira",
    "CERTIFICADOS DE DIREITOS CREDITORIOS DO AGRONEGOCIO - CDCA": "CDCA",
    "CEDULAS DE CREDITO BANCARIO - CCB": "CCB",
}


def _instrumento_padronizado(tipo_ativo: str) -> str:
    if not tipo_ativo:
        return "Outro"
    chave = remover_acentos(tipo_ativo).upper().strip()
    return INSTRUMENTO_PADRONIZADO_MAP.get(chave, "Outro")


# ============ indexador_padronizado: MELHOR ESFORCO, ver CLAUDE.md ============
# Juros/Atualizacao_Monetaria sao texto livre da CVM desde 1989 (771 e 98 valores
# distintos so no dataset em escopo, ex: "12% A.A.", "DI + 2%", "TAXA ANBID",
# "IGP-M", "VARIACAO CAMBIAL DOLAR", "NIHIL") -- nao ha como parsear isso com
# precisao total sem inventar. Esta funcao reconhece so os 4 padroes mais comuns/
# inequivocos (CDI, IPCA+, SELIC, Prefixado) e cai em 'Outro' para tudo mais que
# tenha CONTEUDO real (IGPM, TR, TJLP, ANBID, variacao cambial etc. -- indexadores
# reais, so nao um dos 4 canonicos) -- NUNCA em NULL nesse caso, para nao passar a
# impressao de "sem indexador" quando na verdade so nao reconhecemos qual e. NULL e
# reservado para quando os dois campos de origem estao genuinamente vazios/sem
# informacao (nunca inferido).
_VAZIOS = {"", "NAO", "NAO.", "N/A", "NA", "-", "--", "---", "NENHUM", "NENHUMA"}


def _normalizar_taxa(texto: str) -> str:
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    return remover_acentos(str(texto)).upper().strip()


def _indexador_padronizado(juros: str, atualizacao_monetaria: str) -> str:
    juros_n = _normalizar_taxa(juros)
    am_n = _normalizar_taxa(atualizacao_monetaria)
    am_vazia = am_n in _VAZIOS
    juros_vazio = juros_n in _VAZIOS

    if "IPCA" in am_n or "IPCR" in am_n or "IPC-R" in am_n:
        return "IPCA+"
    if "SELIC" in juros_n or "SELIC" in am_n:
        return "SELIC"
    if am_vazia and re.search(r"\bC?DI\b", juros_n):
        return "CDI"
    if am_vazia and not juros_vazio and re.match(r"^\d", juros_n):
        return "Prefixado"
    if not am_vazia or not juros_vazio:
        return "Outro"
    return None


# ============ taxa_valor/taxa_tipo: pedido adicional do usuario (2026-09-16,
# chegou no meio desta sessao) -- alem de SABER que o indexador e CDI/IPCA+/etc,
# quer o NUMERO da taxa/spread propriamente dito (ex: "CDI + 2,50% a.a." -> ve o
# indexador="CDI" E o numero 2.50; "12,5% a.a." -> ve o numero 12.5). Mesma
# filosofia de melhor esforco do indexador_padronizado: regex simples sobre o
# mesmo texto livre, NUNCA inventa um numero quando nao consegue extrair com
# confianca (fica NULL). ============
_RE_NUM = r"(\d+(?:[.,]\d+)?)"
_INDEXADOR_TOKEN = r"(?:DI|CDI|SELIC)"

# Aditivo (spread) -- cobre as formas reais mais comuns observadas no dataset
# inteiro (confirmado testando contra as 12.239 linhas em escopo, nao so uma
# amostra pequena):
#  1. sinal +/- ANTES do numero, com ate poucas palavras de preenchimento no meio
#     ("spread de", "sobretaxa de") -- ex: "DI + 2%", "IGPM+3,5%", "TR - 1%",
#     "DI + spread de 1,65% a.a.". O "%" e OPCIONAL aqui de proposito: "CDI + 1,75"
#     e "DI + 2,85 aa" (sem "%" nenhum) sao spreads reais sem o simbolo --
#     convencao do mercado de credito privado brasileiro e cotar spread sobre
#     DI/CDI/SELIC sempre em pontos percentuais a.a., mesmo quando o "%" some do
#     texto (o campo inteiro, `juros`, so existe pra descrever uma taxa de divida
#     -- qualquer numero aqui apos um sinal +/- e uma taxa, nunca outra coisa).
#  2. a palavra "acrescid[ao](s)? (de)?" no lugar do sinal +/- (ex: "Taxa DI
#     acrescida de 0,75%").
#  3. o numero vem ANTES do indexador, no formato "X% [a.a.] + <indexador>" (ex:
#     "0,75% a.a. + CDI", "2.5% + CDI", "0,43% a.a. + taxa DI").
# Funciona independente de qual indexador precede/segue -- entao tambem cobre um
# spread sobre um indexador que caiu em 'Outro' (IGPM/TR/TJLP etc.) -- o
# indexador de base continua disponivel em indexador_padronizado +
# juros/atualizacao_monetaria crus, nunca escondido atras do numero extraido.
#
# BUG REAL corrigido antes de terminar: `_normalizar_taxa` deixa o texto em
# MAIUSCULO (`remover_acentos(...).upper()`), mas as primeiras versoes destas
# regex tinham os conectivos ("spread", "sobretaxa", "acrescida", "taxa") em
# MINUSCULO -- sem `re.IGNORECASE`, nenhuma delas batia contra o texto real
# ("SPREAD DE 1,5%", "TAXA DI ACRESCIDA DE 0,75%" etc. nunca casavam com o
# padrao em minusculo). Confirmado ao vivo: cobertura subiu de 461 (regex
# original, sem os padroes reversos/tolerantes a filler) para 515 de 12.239
# linhas em escopo (~4,2%) depois deste fix + dos padroes adicionais acima --
# ver CLAUDE.md pra analise completa de cobertura e exemplos do que ainda fica
# de fora (fraseado raro demais pra valer regex novo, ex: "105% das taxas
# medias diarias dos DI").
_RE_SPREAD_SINAL_ANTES = re.compile(
    r"[+\-]\s*(?:spread\s*(?:de\s*)?|sobretaxa\s*(?:de\s*)?)?" + _RE_NUM + r"\s*%?",
    re.IGNORECASE,
)
_RE_SPREAD_ACRESCIDA = re.compile(r"acrescid[ao]s?\s*(?:de\s*)?" + _RE_NUM + r"\s*%", re.IGNORECASE)
_RE_SPREAD_SINAL_DEPOIS = re.compile(
    _RE_NUM + r"\s*%\s*.{0,15}?[+\-]\s*(?:taxa\s+)?" + _INDEXADOR_TOKEN + r"\b",
    re.IGNORECASE,
)
# Percentual do indexador (MULTIPLICATIVO, nao aditivo -- ex: "108% do CDI",
# "100% da Taxa DI", "104%  taxa DI" sem "DA"/"DO") -- deliberadamente um
# taxa_tipo DIFERENTE de 'spread': tratar "108% do CDI" como "spread de 108"
# seria uma leitura errada e enganosa (nao e 108 pontos percentuais SOMADOS ao
# CDI, e 108% do proprio CDI) -- distincao que o usuario nao pediu explicitamente
# mas que evita inventar/confundir semantica.
_RE_PERCENTUAL_INDEXADOR = re.compile(
    _RE_NUM + r"\s*%\s*(?:DA\s+TAXA|DO|DA|TAXA)?\s*\b" + _INDEXADOR_TOKEN + r"\b",
    re.IGNORECASE,
)


def _para_float_br(texto: str) -> float:
    return float(texto.replace(",", "."))


def _extrair_taxa(juros: str, indexador_padronizado: str):
    """Devolve (taxa_valor, taxa_tipo) -- (None, None) se nao der pra extrair com
    confianca. So olha `juros` (campo onde a taxa/spread realmente aparece nos
    dados reais -- Atualizacao_Monetaria carrega o NOME do indice, raramente um
    numero de taxa junto). Cobertura real medida contra as 12.239 linhas em
    escopo do CSV de 2026-09-16: 515 com taxa_valor extraido (~4,2% do total --
    a grande maioria das linhas tem juros vazio/"NAO"/"-", ver CLAUDE.md) -- do
    subconjunto onde `juros` tem CONTEUDO reconhecivel, a cobertura e bem maior."""
    juros_n = _normalizar_taxa(juros)
    if not juros_n or juros_n in _VAZIOS:
        return None, None

    for regex, tipo in (
        (_RE_SPREAD_SINAL_ANTES, "spread"),
        (_RE_SPREAD_ACRESCIDA, "spread"),
        (_RE_SPREAD_SINAL_DEPOIS, "spread"),
    ):
        m = regex.search(juros_n)
        if m:
            return _para_float_br(m.group(1)), tipo

    if indexador_padronizado in ("CDI", "SELIC"):
        m_mult = _RE_PERCENTUAL_INDEXADOR.search(juros_n)
        if m_mult:
            return _para_float_br(m_mult.group(1)), "percentual_indexador"

    if indexador_padronizado == "Prefixado":
        m_fixa = re.search(_RE_NUM + r"\s*%", juros_n)
        if m_fixa:
            return _para_float_br(m_fixa.group(1)), "taxa_fixa"

    return None, None


OPERATIONS_PRIMARIO_COLS = [
    "instrumento", "instrumento_padronizado", "numero_processo", "numero_registro_oferta",
    "tipo_oferta", "rito_oferta", "modalidade_oferta",
    "cnpj_emissor", "nome_emissor", "razao_social_oficial_emissor",
    "setor_emissor", "subsetor_emissor", "segmento_emissor", "porte_emissor",
    "natureza_juridica_emissor", "uf_emissor", "municipio_emissor",
    "cnpj_lider", "nome_lider",
    "emissao", "serie", "classe_ativo", "especie_ativo", "forma_ativo",
    "data_emissao", "data_vencimento", "data_registro_oferta", "data_encerramento_oferta",
    "data_referencia", "ano", "trimestre",
    "prazo_dias", "prazo_meses",
    "valor_total", "quantidade_total", "preco_unitario",
    "incentivada", "regime_fiduciario", "oferta_inicial",
    "indexador_padronizado", "taxa_valor", "taxa_tipo", "juros", "atualizacao_monetaria",
    "raw_table", "raw_id",
]

# dias/mes usado so para CONVERTER prazo_dias (exato) para uma unidade comparavel
# com prazo_amortizacao_meses de `operations` (BNDES/FINEP) -- e uma constante de
# conversao documentada, nao um dado inventado (prazo_dias em si vem 100% de
# subtracao de datas reais da CVM).
_DIAS_POR_MES = 30.44


def _sim_nao_para_bool(series: pd.Series):
    return series.map(lambda v: True if v == "S" else (False if v == "N" else None))


def _load_emissor_lookup(conn) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT cnpj, setor_bndes_mapeado, subsetor_bndes_mapeado, cnae_descricao, "
        "razao_social_oficial, natureza_juridica, porte_empresa, uf, municipio "
        "FROM cnpj_cnae",
        get_engine(),
    )


def _data_referencia(df: pd.DataFrame) -> pd.Series:
    """Melhor data disponivel para ordenar/agrupar por periodo -- Data_Emissao (o
    campo mais "natural") esta ausente em 82% das linhas em escopo (confirmado no
    CSV real: ofertas antigas/dispensadas de registro raramente tem essa data
    digitalizada), entao usamos o primeiro campo de data preenchido nesta ordem de
    preferencia (todos ja normalizados p/ AAAA-MM-DD por parse_cvm.py):
    1. data_emissao (quando existe, e a mais precisa -- data real de emissao do titulo)
    2. data_registro_oferta (quando a oferta teve registro)
    3. data_inicio_oferta (campo mais recente da CVM, bem preenchido -- so 25% nulo)
    4. data_encerramento_oferta (o MELHOR preenchido de todos -- so 3% nulo -- mas
       o mais "tardio" na linha do tempo real da oferta, usado por ultimo de proposito)
    5. data_protocolo / data_abertura_processo (ultimo recurso, processos antigos)
    NUNCA inventada -- se todos os 6 campos estiverem vazios, data_referencia (e
    ano/trimestre derivados) ficam NULL."""
    return (
        df["data_emissao"]
        .fillna(df["data_registro_oferta"])
        .fillna(df["data_inicio_oferta"])
        .fillna(df["data_encerramento_oferta"])
        .fillna(df["data_protocolo"])
        .fillna(df["data_abertura_processo"])
    )


def _prazo_dias_e_meses(df: pd.DataFrame):
    """prazo_dias = data_vencimento - data_emissao, EXATO (dado real, nao
    melhor-esforco -- diferente de indexador/taxa) -- so NULL quando falta uma das
    duas datas (82% das linhas em escopo nao tem data_emissao, ver
    `_data_referencia` acima) OU quando a subtracao da <= 0.

    ACHADO REAL: das 1.903 linhas com AMBAS as datas preenchidas, 44 (2,3%) tem
    data_vencimento ANTERIOR ou IGUAL a data_emissao -- inconsistencia de digitacao
    na propria fonte (confirmado: um caso extremo de -35.429 dias, quase 97 anos
    "ao contrario"), nao um bug deste pipeline. Essas 44 linhas ficam com
    prazo_dias/prazo_meses NULL de proposito (nunca um prazo negativo/zero, que
    quebraria qualquer comparacao/grafico no frontend)."""
    emissao = pd.to_datetime(df["data_emissao"], errors="coerce")
    vencimento = pd.to_datetime(df["data_vencimento"], errors="coerce")
    dias = (vencimento - emissao).dt.days
    dias = dias.where(dias > 0)
    meses = (dias / _DIAS_POR_MES).round(1)
    return dias, meses


def _build_primario_ops(conn, emissor_lookup: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT * FROM cvm_oferta_distribuicao_raw WHERE id NOT IN "
        "(SELECT raw_id FROM operations_primario WHERE raw_table = 'cvm_oferta_distribuicao_raw')",
        get_engine(),
    )
    if df.empty:
        return df

    df = df.merge(emissor_lookup, left_on="cnpj_emissor", right_on="cnpj", how="left")

    data_ref = _data_referencia(df)
    dt = pd.to_datetime(data_ref, errors="coerce")
    prazo_dias, prazo_meses = _prazo_dias_e_meses(df)

    indexadores = df.apply(
        lambda r: _indexador_padronizado(r["juros"], r["atualizacao_monetaria"]), axis=1
    )
    taxas = [
        _extrair_taxa(juros, indexador)
        for juros, indexador in zip(df["juros"], indexadores)
    ]

    out = pd.DataFrame({
        "instrumento": df["tipo_ativo"],
        "instrumento_padronizado": df["tipo_ativo"].map(_instrumento_padronizado),
        "numero_processo": df["numero_processo"],
        "numero_registro_oferta": df["numero_registro_oferta"],
        "tipo_oferta": df["tipo_oferta"],
        "rito_oferta": df["rito_oferta"],
        "modalidade_oferta": df["modalidade_oferta"],
        "cnpj_emissor": df["cnpj_emissor"],
        "nome_emissor": df["nome_emissor"],
        "razao_social_oficial_emissor": df["razao_social_oficial"],
        "setor_emissor": df["setor_bndes_mapeado"],
        "subsetor_emissor": df["subsetor_bndes_mapeado"],
        "segmento_emissor": df["cnae_descricao"],
        "porte_emissor": df["porte_empresa"],
        "natureza_juridica_emissor": df["natureza_juridica"],
        "uf_emissor": df["uf"],
        "municipio_emissor": df["municipio"],
        "cnpj_lider": df["cnpj_lider"],
        "nome_lider": df["nome_lider"],
        "emissao": df["emissao"],
        "serie": df["serie"],
        "classe_ativo": df["classe_ativo"],
        "especie_ativo": df["especie_ativo"],
        "forma_ativo": df["forma_ativo"],
        "data_emissao": df["data_emissao"],
        "data_vencimento": df["data_vencimento"],
        "data_registro_oferta": df["data_registro_oferta"],
        "data_encerramento_oferta": df["data_encerramento_oferta"],
        "data_referencia": data_ref,
        "ano": dt.dt.year,
        "trimestre": dt.dt.quarter,
        "prazo_dias": prazo_dias,
        "prazo_meses": prazo_meses,
        "valor_total": df["valor_total"],
        "quantidade_total": df["quantidade_total"],
        "preco_unitario": df["preco_unitario"],
        "incentivada": _sim_nao_para_bool(df["oferta_incentivo_fiscal"]),
        "regime_fiduciario": _sim_nao_para_bool(df["oferta_regime_fiduciario"]),
        "oferta_inicial": _sim_nao_para_bool(df["oferta_inicial"]),
        "indexador_padronizado": indexadores,
        "taxa_valor": [t[0] for t in taxas],
        "taxa_tipo": [t[1] for t in taxas],
        "juros": df["juros"],
        "atualizacao_monetaria": df["atualizacao_monetaria"],
        "raw_table": "cvm_oferta_distribuicao_raw",
        "raw_id": df["id"],
    })
    return out


def _reclassificar_emissores_pendentes(conn, emissor_lookup: pd.DataFrame) -> list:
    """Mesmo espirito de unify.py::_reclassificar_pendentes -- re-checa linhas com
    setor_emissor NULL (cnpj_emissor ainda nao estava em cnpj_cnae na hora em que a
    linha foi unificada) contra o cache ATUAL, e atualiza em cima da linha ja
    existente as que agora resolvem."""
    if emissor_lookup.empty:
        return []
    pendentes = pd.read_sql(
        "SELECT id, cnpj_emissor FROM operations_primario WHERE setor_emissor IS NULL AND cnpj_emissor IS NOT NULL",
        get_engine(),
    )
    if pendentes.empty:
        return []
    resolvidos = pendentes.merge(emissor_lookup, left_on="cnpj_emissor", right_on="cnpj", how="inner")
    resolvidos = resolvidos[resolvidos["setor_bndes_mapeado"].notna()]
    if resolvidos.empty:
        return []

    updates = [
        (
            row["setor_bndes_mapeado"], row["subsetor_bndes_mapeado"], row["cnae_descricao"],
            row["porte_empresa"], row["natureza_juridica"], row["razao_social_oficial"],
            row["uf"], row["municipio"], int(row["id"]),
        )
        for _, row in resolvidos.iterrows()
    ]
    cur = conn.cursor()
    cur.executemany(
        "UPDATE operations_primario SET setor_emissor = ?, subsetor_emissor = ?, segmento_emissor = ?, "
        "porte_emissor = ?, natureza_juridica_emissor = ?, razao_social_oficial_emissor = ?, "
        "uf_emissor = ?, municipio_emissor = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    return [u[-1] for u in updates]


def reclassificar_emissores_pendentes(conn=None) -> list:
    """Wrapper publico -- reaproveitavel logo apos enrich_cnae.enrich_pendentes_via_api
    resolver novos CNPJs (ver refresh_primario.py), mesmo padrao de
    unify.py::reclassificar_pendentes."""
    fechar = conn is None
    conn = conn or get_connection()
    try:
        emissor_lookup = _load_emissor_lookup(conn)
        return _reclassificar_emissores_pendentes(conn, emissor_lookup)
    finally:
        if fechar:
            conn.close()


def backfill_taxa_e_prazo(conn=None) -> int:
    """Backfill ÚNICO: taxa_valor/taxa_tipo/prazo_dias/prazo_meses foram
    adicionados a operations_primario DEPOIS da primeira rodada do pipeline ja ter
    inserido 12.232 linhas (pedido do usuario chegou no meio da mesma sessao, ver
    CLAUDE.md) -- diferente de instrumento_padronizado/indexador_padronizado
    (calculados no INSERT original), essas linhas ja existentes nunca tiveram esses
    4 campos calculados. Recalcula para TODAS as linhas de operations_primario a
    partir das proprias colunas ja gravadas (juros/atualizacao_monetaria/
    indexador_padronizado/data_emissao/data_vencimento) -- nunca rebaixa nada da
    CVM de novo. Seguro de rodar mais de uma vez (idempotente, sempre recalcula do
    zero a partir do dado bruto ja armazenado)."""
    fechar = conn is None
    conn = conn or get_connection()
    try:
        df = pd.read_sql(
            "SELECT id, juros, atualizacao_monetaria, indexador_padronizado, "
            "data_emissao, data_vencimento FROM operations_primario",
            get_engine(),
        )
        if df.empty:
            return 0
        prazo_dias, prazo_meses = _prazo_dias_e_meses(df)
        taxas = [
            _extrair_taxa(juros, indexador)
            for juros, indexador in zip(df["juros"], df["indexador_padronizado"])
        ]
        updates = [
            (
                None if pd.isna(prazo_dias.iloc[i]) else int(prazo_dias.iloc[i]),
                None if pd.isna(prazo_meses.iloc[i]) else float(prazo_meses.iloc[i]),
                taxas[i][0], taxas[i][1],
                int(df["id"].iloc[i]),
            )
            for i in range(len(df))
        ]
        cur = conn.cursor()
        cur.executemany(
            "UPDATE operations_primario SET prazo_dias = ?, prazo_meses = ?, taxa_valor = ?, taxa_tipo = ? WHERE id = ?",
            updates,
        )
        conn.commit()
        return len(updates)
    finally:
        if fechar:
            conn.close()


# ============ Motor de busca sem IA (ver src/search_fts_primario.py) ============
# MESMO espirito de unify.py::_search_document/_atualizar_search_vector, mais simples:
# nao ha um dicionario de sinonimos/taxonomia curado para o emissor da CVM (diferente do
# setor/subsetor/segmento do BNDES, ver search_taxonomy.py), entao nao existe uma coluna
# equivalente a search_taxonomia_termos aqui -- so search_document (texto legivel, para
# depuracao) e search_vector (tsvector com peso por campo, o que a busca de verdade usa).
#
# Diferenca deliberada de design frente a unify.py: la, search_document/search_taxonomia_termos
# sao calculados ANTES do insert (colunas do proprio DataFrame, ver OPERATIONS_COLS) porque o
# BNDES ja chega com setor NATIVO (nao muda depois). Aqui, TODO emissor depende do
# enriquecimento via CNPJ (ver docstring do modulo) -- setor_emissor/subsetor_emissor/
# segmento_emissor/uf_emissor/municipio_emissor de uma linha reciem-inserida quase sempre
# comecam NULL (pendente) e so ganham valor depois, via _reclassificar_emissores_pendentes.
# Calcular search_document uma unica vez no insert deixaria a busca cega a esses campos ate
# o PROXIMO refresh reprocessar tudo de novo -- em vez disso, _atualizar_busca_primario roda
# depois de QUALQUER mudanca (insert OU reclassificacao), sempre lendo o estado ATUAL da
# linha direto do banco. Um pouco mais de leitura, bem mais simples (uma unica funcao, um
# unico caminho, sem duas copias de _search_document -- pre-insert e pos-reclassificacao).
_BUSCA_COLS = [
    "id", "nome_emissor", "razao_social_oficial_emissor", "cnpj_emissor",
    "instrumento_padronizado", "instrumento", "setor_emissor", "subsetor_emissor",
    "segmento_emissor", "nome_lider", "indexador_padronizado", "uf_emissor", "municipio_emissor",
]


def _search_document_primario(row: dict) -> str:
    """Texto-fonte LEGIVEL do motor de busca sem IA (depuracao/exportacao) -- o
    tsvector de busca de verdade (search_vector) e montado a parte, com peso por
    campo, em _atualizar_busca_primario (nao a partir deste texto plano)."""
    parts = [
        row.get("nome_emissor"),
        row.get("razao_social_oficial_emissor"),
        row.get("cnpj_emissor"),
        row.get("instrumento_padronizado"),
        row.get("instrumento"),
        row.get("setor_emissor"),
        row.get("subsetor_emissor"),
        row.get("segmento_emissor"),
        row.get("nome_lider"),
        row.get("indexador_padronizado"),
        row.get("municipio_emissor"),
        row.get("uf_emissor"),
    ]
    return " | ".join(str(p) for p in parts if p not in (None, "", "nan"))


def _atualizar_busca_primario(conn, ids: list) -> None:
    """Recalcula search_document + search_vector (tsvector com peso por campo, Postgres
    usa A > B > C > D) para os ids informados, direto das colunas ja gravadas em
    operations_primario:
      A: nome_emissor/razao social oficial/CNPJ (identificacao do emissor -- prioridade maxima)
      B: setor/subsetor/segmento do emissor (o que o emissor FAZ, mesma taxonomia do BNDES via cnpj_cnae)
      C: instrumento (padronizado + cru)/indexador/nome do lider (caracteristicas da oferta)
      D: uf/municipio do emissor (contexto geografico)
    Mesma normalizacao 'optic'->'otic' de unify.py::_atualizar_search_vector (segmento_emissor
    vem do MESMO cnae_descricao que popula operations.segmento, entao pode ter o mesmo caso
    real de 'fibra optica'/'fibra otica' tratadas como palavras diferentes pelo stemmer)."""
    ids = [int(i) for i in dict.fromkeys(ids)]
    if not ids:
        return
    cur = conn.cursor()
    rows = cur.execute(
        f"SELECT {', '.join(_BUSCA_COLS)} FROM operations_primario WHERE id = ANY(?)",
        [ids],
    ).fetchall()
    updates = [
        (_search_document_primario(dict(zip(_BUSCA_COLS, r))), r[0])
        for r in rows
    ]
    if updates:
        cur.executemany(
            "UPDATE operations_primario SET search_document = ? WHERE id = ?", updates
        )
        conn.commit()

    conn.execute(
        """
        UPDATE operations_primario SET search_vector =
            setweight(to_tsvector('portuguese', regexp_replace(unaccent(
                coalesce(nome_emissor, '') || ' ' || coalesce(razao_social_oficial_emissor, '') || ' ' || coalesce(cnpj_emissor, '')
            ), '\\moptic', 'otic', 'gi')), 'A') ||
            setweight(to_tsvector('portuguese', regexp_replace(unaccent(
                coalesce(setor_emissor, '') || ' ' || coalesce(subsetor_emissor, '') || ' ' || coalesce(segmento_emissor, '')
            ), '\\moptic', 'otic', 'gi')), 'B') ||
            setweight(to_tsvector('portuguese', regexp_replace(unaccent(
                coalesce(instrumento_padronizado, '') || ' ' || coalesce(instrumento, '') || ' ' ||
                coalesce(indexador_padronizado, '') || ' ' || coalesce(nome_lider, '')
            ), '\\moptic', 'otic', 'gi')), 'C') ||
            setweight(to_tsvector('portuguese', regexp_replace(unaccent(
                coalesce(uf_emissor, '') || ' ' || coalesce(municipio_emissor, '')
            ), '\\moptic', 'otic', 'gi')), 'D')
        WHERE id = ANY(?)
        """,
        [ids],
    )
    conn.commit()


def backfill_busca_primario(conn=None, tamanho_lote: int = 2000) -> int:
    """Backfill UNICO: search_document/search_vector foram adicionados a
    operations_primario DEPOIS da primeira rodada do pipeline ja ter inserido 12.232
    linhas (ver CLAUDE.md e MIGRACOES_COLUNAS em src/db.py) -- sem isso, todo o
    historico ja carregado ficaria para sempre invisivel pro motor de busca. Roda em
    lotes pequenos (mesmo motivo documentado em scripts/backfill_search_taxonomia.py --
    o Aiven free tier ja derrubou conexao no meio de escritas longas) -- idempotente,
    seguro de rodar mais de uma vez."""
    fechar = conn is None
    conn = conn or get_connection()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM operations_primario ORDER BY id").fetchall()]
        for inicio in range(0, len(ids), tamanho_lote):
            lote = ids[inicio:inicio + tamanho_lote]
            _atualizar_busca_primario(conn, lote)
            print(f"  (backfill busca primario: {inicio + len(lote)}/{len(ids)})")
        return len(ids)
    finally:
        if fechar:
            conn.close()


def build_operations_primario() -> dict:
    conn = get_connection()
    try:
        emissor_lookup = _load_emissor_lookup(conn)
        novas = _build_primario_ops(conn, emissor_lookup)

        novos_ids = []
        if not novas.empty:
            insert_new_rows(conn, "operations_primario", novas, OPERATIONS_PRIMARIO_COLS)
            conn.commit()
            # recupera os ids autoincrement recem-atribuidos, por raw_id (raw_table e
            # sempre 'cvm_oferta_distribuicao_raw' aqui -- ver OPERATIONS_PRIMARIO_COLS)
            raw_ids = novas["raw_id"].astype(int).tolist()
            placeholders = ", ".join("?" * len(raw_ids))
            rows = conn.execute(
                f"SELECT id FROM operations_primario WHERE raw_table = 'cvm_oferta_distribuicao_raw' "
                f"AND raw_id IN ({placeholders})",
                raw_ids,
            ).fetchall()
            novos_ids = [r[0] for r in rows]
            _atualizar_busca_primario(conn, novos_ids)

        reclassificados_ids = _reclassificar_emissores_pendentes(conn, emissor_lookup)
        conn.commit()
        if reclassificados_ids:
            # reclassificacao muda setor/subsetor/segmento/uf/municipio -- search_document/
            # search_vector precisam ser recalculados pra essas linhas tambem, senao a busca
            # continua cega a um emissor que acabou de resolver o CNPJ.
            _atualizar_busca_primario(conn, reclassificados_ids)

        total_ops = conn.execute("SELECT COUNT(*) FROM operations_primario").fetchone()[0]
        n_pendentes = conn.execute(
            "SELECT COUNT(*) FROM operations_primario WHERE setor_emissor IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    n_novas = len(novas) if not novas.empty else 0
    print(
        f"operations_primario: {n_novas} linhas novas, {len(reclassificados_ids)} emissores reclassificados "
        f"(pendente -> resolvido), {total_ops} no total ({n_pendentes} emissores ainda pendentes de enriquecimento)."
    )
    return {
        "novas": n_novas,
        "total": total_ops,
        "pendentes": n_pendentes,
        "reclassificados_ids": reclassificados_ids,
    }


if __name__ == "__main__":
    build_operations_primario()
