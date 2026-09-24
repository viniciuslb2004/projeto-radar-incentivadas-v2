"""Constroi a tabela unificada `operations` (BNDES + FINEP credito) e os agregados do dashboard.

Incremental (ver incremental.py e db.py): bndes_raw/finep_*_raw agora sao append-only,
entao build_operations() so processa as linhas raw que AINDA NAO tem uma linha
correspondente em `operations` -- usando raw_table+raw_id (id autoincrement estavel da
tabela de origem), que ja existia no schema mas antes so servia para drill-down, nao
como chave de deduplicacao. Isso e o que faz a classificacao de setor da FINEP (o merge
contra cnpj_cnae) so rodar para as linhas novas a cada refresh, nao para a base inteira.

Alem disso, toda vez que o job mensal de enriquecimento (enrich_cnae.py) adiciona CNPJs
novos ao cache cnpj_cnae, as operacoes da FINEP que ficaram `setor_origem='pendente'` em
refreshes anteriores (o CNPJ ainda nao estava no cache na hora em que a linha foi
unificada) sao re-checadas contra o cache atual e ATUALIZADAS em cima da linha ja
existente (nunca duplicadas) sempre que resolvem. Sem isso, uma vez que `operations`
deixa de ser reconstruida do zero toda semana, uma pendencia resolvida no enriquecimento
mensal nunca mais seria refletida.
"""
import datetime
import re

import pandas as pd

import search_taxonomy
import sector_taxonomy
from db import get_connection, get_engine
from geo import regiao_de
from incremental import insert_new_rows

# uf/municipio/cliente/cnpj adicionados 2026-09-16 (pedido do usuario) -- mesmo
# mecanismo generico ja usado por setor_bndes/subsetor_bndes/segmento (o UPDATE
# abaixo e f-string, mas so roda sobre um `campo` ja validado contra este set,
# nunca sobre entrada livre). CUIDADO com `cnpj`: corrigir esse campo NAO dispara
# reclassificacao automatica de setor com o CNPJ novo (isso so acontece no proximo
# refresh/enriquecimento, e mesmo assim so se setor_origem='pendente') -- e so
# uma correcao do dado bruto (ex: typo), nao uma feature de "corrigir CNPJ pra
# re-enriquecer setor".
CAMPOS_CORRIGIVEIS = {"setor_bndes", "subsetor_bndes", "segmento", "uf", "municipio", "cliente", "cnpj"}


def registrar_correcao_manual(conn, operation_id: int, campo: str, valor_novo: str, usuario: str = None) -> None:
    """Grava uma correcao manual (ver item 3.3 do pedido: "Correcoes manuais aprovadas
    devem prevalecer sobre enriquecimentos automaticos futuros") e aplica na hora --
    o proximo refresh automatico NAO vai sobrescrever, ver _reaplicar_correcoes_manuais,
    chamada ao final de build_operations()."""
    if campo not in CAMPOS_CORRIGIVEIS:
        raise ValueError(f"campo nao corrigivel: {campo} (permitidos: {sorted(CAMPOS_CORRIGIVEIS)})")
    row = conn.execute(f"SELECT {campo} FROM operations WHERE id = ?", (operation_id,)).fetchone()
    if not row:
        raise ValueError(f"operacao {operation_id} nao encontrada")
    valor_anterior = row[0]
    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # desativa qualquer correcao anterior do MESMO campo nesta operacao (mantem no
    # historico, so marca ativa=FALSE) antes de registrar a nova -- nunca deixa duas
    # correcoes ativas competindo pelo mesmo campo.
    conn.execute(
        "UPDATE operations_correcoes_manuais SET ativa = FALSE WHERE operation_id = ? AND campo = ? AND ativa = TRUE",
        (operation_id, campo),
    )
    conn.execute(
        "INSERT INTO operations_correcoes_manuais (operation_id, campo, valor_anterior, valor_novo, usuario, criado_em, ativa) "
        "VALUES (?, ?, ?, ?, ?, ?, TRUE)",
        (operation_id, campo, valor_anterior, valor_novo, usuario, agora),
    )
    conn.execute(f"UPDATE operations SET {campo} = ? WHERE id = ?", (valor_novo, operation_id))
    # Uma vez corrigida a mao, a operacao sai da fila de "pendente" -- senao continuaria
    # aparecendo pra sempre em /api/enriquecimento/pendentes mesmo ja resolvida por
    # um humano. Nao mexe em operacoes que ja estavam 'nativo'/'enriquecido'.
    conn.execute(
        "UPDATE operations SET setor_origem = 'corrigido_manual' WHERE id = ? AND setor_origem = 'pendente'",
        (operation_id,),
    )
    conn.commit()
    _atualizar_textos_apos_correcao(conn, operation_id)


def _atualizar_textos_apos_correcao(conn, operation_id: int) -> None:
    """Recalcula embedding_text/search_document/search_vector de UMA operacao depois
    de uma correcao manual -- sem isso, a busca continuaria usando o texto classificado
    ANTES da correcao (o motivo real de corrigir e melhorar a busca, nao so o rotulo
    exibido no dashboard)."""
    row = conn.execute(
        "SELECT agencia, cliente, razao_social_oficial, cnpj, setor_bndes, subsetor_bndes, segmento, produto, "
        "instrumento_financeiro, modalidade_apoio, indexador, valor_contratado, "
        "prazo_amortizacao_meses, descricao_projeto, municipio, uf FROM operations WHERE id = ?",
        (operation_id,),
    ).fetchone()
    if not row:
        return
    campos = dict(zip(
        ["agencia", "cliente", "razao_social_oficial", "cnpj", "setor_bndes", "subsetor_bndes", "segmento", "produto",
         "instrumento_financeiro", "modalidade_apoio", "indexador", "valor_contratado",
         "prazo_amortizacao_meses", "descricao_projeto", "municipio", "uf"],
        row,
    ))
    boilerplate = _descricoes_boilerplate(conn)
    texto_embedding = _embedding_text(campos, boilerplate)
    texto_busca = _search_document(campos, boilerplate)
    texto_taxonomia = _search_taxonomia_termos(campos)
    conn.execute(
        "UPDATE operations SET embedding_text = ?, search_document = ?, search_taxonomia_termos = ? WHERE id = ?",
        (texto_embedding, texto_busca, texto_taxonomia, operation_id),
    )
    conn.commit()
    _atualizar_search_vector(conn, [operation_id])


def _reaplicar_correcoes_manuais(conn) -> int:
    """Reaplica todas as correcoes ATIVAS em cima de `operations` -- chamado ao final
    de build_operations(), depois de qualquer reclassificacao automatica, pra garantir
    que uma correcao manual aprovada nunca seja silenciosamente sobrescrita por um
    enriquecimento automatico futuro."""
    rows = conn.execute(
        "SELECT operation_id, campo, valor_novo FROM operations_correcoes_manuais WHERE ativa = TRUE"
    ).fetchall()
    for operation_id, campo, valor_novo in rows:
        if campo in CAMPOS_CORRIGIVEIS:
            conn.execute(f"UPDATE operations SET {campo} = ? WHERE id = ?", (valor_novo, operation_id))
            # Correcao manual de setor vale tambem pro setor padronizado por CNAE
            # (setor_cnae, padrao do dashboard desde 2026-09-23) -- senao ela sumiria
            # da tela assim que o recalculo automatico rodasse.
            if campo in ("setor_bndes", "subsetor_bndes"):
                col = "setor_cnae" if campo == "setor_bndes" else "subsetor_cnae"
                conn.execute(
                    f"UPDATE operations SET {col} = ?, setor_cnae_origem = 'corrigido_manual' WHERE id = ?",
                    (valor_novo, operation_id),
                )
    conn.commit()
    return len(rows)

OPERATIONS_COLS = [
    "agencia", "instrumento", "fonte_id", "cliente", "cnpj", "uf", "municipio",
    "data_contratacao", "ano", "trimestre", "valor_contratado", "valor_desembolsado",
    "setor_bndes", "subsetor_bndes", "segmento", "setor_origem", "porte_cliente",
    "natureza_cliente", "razao_social_oficial",
    "produto", "instrumento_financeiro", "modalidade_apoio", "indexador", "taxa_juros",
    "prazo_carencia_meses", "prazo_amortizacao_meses", "descricao_projeto", "agente_financeiro",
    "raw_table", "raw_id", "embedding_text", "search_document", "search_taxonomia_termos",
]


# ============ Produto FINEP (2026-09-23, decisao do usuario -- ver Obsidian Decisoes.md) ============
# Credito DESCENTRALIZADO/indireto: TODAS as operacoes viram "Inovacred". A planilha
# da FINEP NAO traz um campo de programa/produto nessa aba -- isto e decisao
# explicita do usuario (o Inovacred e o programa de credito descentralizado da FINEP
# operado pelos agentes financeiros), nao dado lido da fonte.
PRODUTO_FINEP_DESCENTRALIZADO = "Inovacred"
PRODUTO_FINEP_DIRETO_FALLBACK = "Credito Direto (FINEP)"
# Credito DIRETO: programa a partir da coluna `demanda` da propria fonte, so com a
# grafia limpa/unificada (as duas grafias de "Demanda Espontanea" viram uma so).
_PROGRAMAS_FINEP_DIRETO = [
    ("FINEP CREDITO", "Finep Crédito"),
    ("DEMANDA ESPONTANEA", "Demanda Espontânea"),
    ("FINEP INOVACAO", "Finep Inovação"),
    ("PROGRAMA JURO ZERO", "Programa Juro Zero"),
    ("REEMBOLSAVEL - CEP - SF", "Reembolsável CEP-SF"),
    ("INOVA PETRO", "Inova Petro"),
]


def produto_finep_direto(demanda) -> str:
    import unicodedata
    if demanda is None or (isinstance(demanda, float) and pd.isna(demanda)):
        return PRODUTO_FINEP_DIRETO_FALLBACK
    t = unicodedata.normalize("NFKD", str(demanda)).encode("ascii", "ignore").decode().upper()
    t = re.sub(r"\s+", " ", t).strip()
    for prefixo, rotulo in _PROGRAMAS_FINEP_DIRETO:
        if t.startswith(prefixo):
            return rotulo
    # valor novo que ainda nao conhecemos: mantem o texto da fonte (so espacos limpos)
    return re.sub(r"\s+", " ", str(demanda)).strip() or PRODUTO_FINEP_DIRETO_FALLBACK


# ============ Setor padronizado por CNAE (setor_cnae/subsetor_cnae) ============
def recalcular_setor_cnae(conn, tamanho_lote: int = 5000) -> dict:
    """Recalcula setor_cnae/subsetor_cnae/setor_cnae_origem de TODAS as operacoes
    (BNDES e FINEP) pelo mesmo caminho CNAE -> de_para_cnae (regras e desempate em
    sector_taxonomy.build_regras_cnae). CNAE: cnpj_cnae.cnae_codigo (mesma fonte p/ as
    duas agencias); BNDES sem CNPJ no cache cai no CNAE da propria planilha
    (bndes_raw.subsetor_cnae_codigo). Grava via tabela temporaria + UPDATE ... FROM em
    lotes curtos por faixa de id (commit por lote -- nunca uma transacao longa em
    `operations`), e so as linhas que mudaram. Correcoes manuais sao reaplicadas
    depois por _reaplicar_correcoes_manuais (quem chama)."""
    rows = conn.execute(
        "SELECT o.id, o.agencia, o.setor_bndes, COALESCE(c.cnae_codigo, b.subsetor_cnae_codigo) "
        "FROM operations o LEFT JOIN cnpj_cnae c ON c.cnpj = o.cnpj "
        "LEFT JOIN bndes_raw b ON o.raw_table = 'bndes_raw' AND b.id = o.raw_id"
    ).fetchall()
    evidencia = [(cnae, setor) for _, ag, setor, cnae in rows if ag == "BNDES" and cnae and setor]
    regras = sector_taxonomy.build_regras_cnae(conn, evidencia)
    valores = []
    for op_id, _, _, cnae in rows:
        setor, sub, origem = sector_taxonomy.classificar_cnae(cnae, regras)
        valores.append((op_id, setor, sub, origem))

    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS tmp_setor_cnae (id INTEGER PRIMARY KEY, setor TEXT, subsetor TEXT, origem TEXT)"
    )
    conn.execute("TRUNCATE tmp_setor_cnae")
    with conn.cursor().copy("COPY tmp_setor_cnae (id, setor, subsetor, origem) FROM STDIN") as cp:
        for v in valores:
            cp.write_row(v)
    conn.commit()
    ids = sorted(v[0] for v in valores)
    atualizadas = 0
    for i in range(0, len(ids), tamanho_lote):
        lote = ids[i:i + tamanho_lote]
        cur = conn.execute(
            "UPDATE operations o SET setor_cnae = t.setor, subsetor_cnae = t.subsetor, setor_cnae_origem = t.origem "
            "FROM tmp_setor_cnae t WHERE t.id = o.id AND o.id BETWEEN ? AND ? "
            "AND COALESCE(o.setor_cnae_origem, '') <> 'corrigido_manual' "
            "AND (o.setor_cnae IS DISTINCT FROM t.setor OR o.subsetor_cnae IS DISTINCT FROM t.subsetor "
            "     OR o.setor_cnae_origem IS DISTINCT FROM t.origem)",
            (lote[0], lote[-1]),
        )
        atualizadas += cur.rowcount or 0
        conn.commit()
    conn.execute("DROP TABLE IF EXISTS tmp_setor_cnae")
    conn.commit()
    return {"total": len(valores), "atualizadas": atualizadas}


def _add_periodo(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    dt = pd.to_datetime(df[date_col], errors="coerce")
    df["ano"] = dt.dt.year
    df["trimestre"] = dt.dt.quarter
    return df


def _load_cnae_lookup(conn) -> pd.DataFrame:
    # pd.read_sql precisa de um engine SQLAlchemy (nao da conexao psycopg crua --
    # pandas nao suporta isso de forma confiavel, ver docstring de db.get_engine()).
    # natureza_juridica/porte_empresa/razao_social_oficial: identificacao da empresa
    # (Empresas.zip da RFB, ver enrich_cnae.py::enrich_empresas()) -- volta pra
    # `operations` via este mesmo merge, em vez de ficar so no detalhe de uma operacao.
    return pd.read_sql(
        "SELECT cnpj, setor_bndes_mapeado, subsetor_bndes_mapeado, cnae_descricao, "
        "natureza_juridica, porte_empresa, razao_social_oficial FROM cnpj_cnae", get_engine()
    )


def _build_bndes_ops(conn, cnae_lookup: pd.DataFrame) -> pd.DataFrame:
    # so as linhas de bndes_raw que ainda nao tem uma linha correspondente em operations
    df = pd.read_sql(
        "SELECT * FROM bndes_raw WHERE id NOT IN (SELECT raw_id FROM operations WHERE raw_table = 'bndes_raw')",
        get_engine(),
    )
    if df.empty:
        return df
    df = _add_periodo(df, "data_contratacao")
    # BNDES nao traz natureza juridica/razao social oficial na propria planilha (so
    # porte_cliente, que fica como esta -- classificacao nativa do BNDES, mais
    # confiavel que a da Receita Federal pra esse campo) -- complementa via o mesmo
    # cache CNPJ->identificacao ja usado pra FINEP.
    df = df.merge(cnae_lookup[["cnpj", "natureza_juridica", "razao_social_oficial"]], on="cnpj", how="left")
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
        "natureza_cliente": df["natureza_juridica"],
        "razao_social_oficial": df["razao_social_oficial"],
        "produto": df["produto"],
        "instrumento_financeiro": df["instrumento_financeiro"],
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
    df = pd.read_sql(
        "SELECT * FROM finep_credito_direto_raw WHERE id NOT IN "
        "(SELECT raw_id FROM operations WHERE raw_table = 'finep_credito_direto_raw')",
        get_engine(),
    )
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
        "porte_cliente": df["porte_empresa"],
        "natureza_cliente": df["natureza_juridica"],
        "razao_social_oficial": df["razao_social_oficial"],
        "produto": df["demanda"].map(produto_finep_direto),
        "instrumento_financeiro": None,
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
    df = pd.read_sql(
        "SELECT * FROM finep_credito_descentralizado_raw WHERE id NOT IN "
        "(SELECT raw_id FROM operations WHERE raw_table = 'finep_credito_descentralizado_raw')",
        get_engine(),
    )
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
        "porte_cliente": df["porte_empresa"],
        "natureza_cliente": df["natureza_juridica"],
        "razao_social_oficial": df["razao_social_oficial"],
        "produto": PRODUTO_FINEP_DESCENTRALIZADO,
        "instrumento_financeiro": None,
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


# ============ BNB (2026-09-24, publicado com aprovacao do usuario) ============
# Fonte: bnb_raw (src/bnb.py -- painel publico "Consulta de Operacoes de Credito" do
# BNB, so PJ). agencia exibida = "BNB" (decisao do usuario, nao "FNE"); produto = fundo
# exatamente como vem da fonte (FNE, FNE-2, BNDES/FINAME, FEDAF). O programa so existe
# como CODIGO numerico na fonte -- vai cru em instrumento_financeiro, sem inventar nome.
# Taxa/indexador/prazos/carencia: exatamente como publicados (sem correcao/inferencia).
# UF = do contrato; municipio/porte/natureza/setor = cnpj_cnae (Receita Federal).
# Sem descricao de projeto nem valor desembolsado na fonte (ficam NULL).
# Recorte: so contratos > R$ 1.000.000,00 (decisao do usuario 2026-09-24) -- bnb.py ja
# extrai so esse recorte; o filtro aqui e defesa extra, persistente a cada refresh.
def _build_bnb_ops(conn, cnae_lookup: pd.DataFrame) -> pd.DataFrame:
    from bnb import mascarar_cpf
    df = pd.read_sql(
        "SELECT b.*, c.municipio AS municipio_rfb FROM bnb_raw b LEFT JOIN cnpj_cnae c ON c.cnpj = b.cnpj "
        "WHERE b.valor_contratado > 1000000 "
        "AND b.id NOT IN (SELECT raw_id FROM operations WHERE raw_table = 'bnb_raw')",
        get_engine(),
    )
    if df.empty:
        return df
    df["data_contratacao"] = pd.to_datetime(df["data_contratacao"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = _add_periodo(df, "data_contratacao")
    df = df.merge(cnae_lookup, on="cnpj", how="left")
    setor_origem = df["setor_bndes_mapeado"].notna().map({True: "enriquecido", False: "pendente"})
    return pd.DataFrame({
        "agencia": "BNB",
        "instrumento": None,
        "fonte_id": df["cod_contrato"].astype(str) + "/" + df["num_operacao"].astype(str),
        # ja mascarado na extracao; defesa extra (LGPD) + espacos duplicados colapsados
        "cliente": df["cliente"].map(lambda v: mascarar_cpf(" ".join(v.split())) if isinstance(v, str) else v),
        "cnpj": df["cnpj"],
        "uf": df["uf"],
        "municipio": df["municipio_rfb"],
        "data_contratacao": df["data_contratacao"],
        "ano": df["ano"],
        "trimestre": df["trimestre"],
        "valor_contratado": df["valor_contratado"].astype(float),
        "valor_desembolsado": None,
        "setor_bndes": df["setor_bndes_mapeado"],
        "subsetor_bndes": df["subsetor_bndes_mapeado"],
        "segmento": df["cnae_descricao"],
        "setor_origem": setor_origem,
        "porte_cliente": df["porte_empresa"],
        "natureza_cliente": df["natureza_juridica"],
        "razao_social_oficial": df["razao_social_oficial"],
        "produto": df["fundo"],
        "instrumento_financeiro": df["cod_programa_credito"].map(
            lambda v: f"Programa cód. {int(v)}" if pd.notna(v) else None),
        "modalidade_apoio": "REEMBOLSAVEL",
        "indexador": df["indexador"],
        "taxa_juros": df["taxa_juros_aa"],
        "prazo_carencia_meses": df["prazo_carencia_meses"],
        "prazo_amortizacao_meses": df["prazo_amortizacao_meses"],
        "descricao_projeto": None,
        "agente_financeiro": None,
        "raw_table": "bnb_raw",
        "raw_id": df["id"],
    })


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


def _prefixo_descricao(texto: str, n_palavras: int = 8) -> str:
    if not texto:
        return ""
    return " ".join(str(texto).strip().split()[:n_palavras])


def _descricoes_boilerplate(conn, limiar_clientes: int = 5, limiar_setores: int = 2) -> set:
    """Descricoes de projeto que comecam com o MESMO PREFIXO (8 primeiras palavras) e
    esse prefixo aparece em muitos CLIENTES DIFERENTES *e* em mais de um SETOR BNDES sao
    texto generico de linha/produto de credito (ex: "CONTRATACAO DE LIMITE DE CREDITO
    PARA FINANCIAMENTO A..."), nao uma descricao real do projeto de uma empresa
    especifica -- BNDES reusa a mesma frase-padrao (com pequenas variacoes no final,
    por isso o agrupamento e por PREFIXO, nao pela string inteira) para QUALQUER
    empresa que contrata aquele tipo de produto, independente do setor dela.

    Exige tambem >1 setor (nao so muitos clientes) para nao suprimir descricoes de
    projetos legitimos e especificos que sao compartilhados entre varias entidades do
    MESMO projeto (ex: "IMPLANTACAO DO COMPLEXO EOLICO X" repetido por 18 SPVs
    diferentes do mesmo parque eolico -- todas no setor de infraestrutura, informacao
    real e especifica, nao deve ser suprimida so por ter muitos "clientes").

    Confirmado empiricamente (root cause real de busca imprecisa, nao a base de CNPJ):
    esse texto generico aparece em milhares de operacoes de 4 setores diferentes
    (industria, comercio, agropecuaria, infraestrutura) e, por conter literalmente as
    palavras "credito"/"financiamento", fazia buscas com esses termos (ex: "fintech de
    credito para pequenas empresas") ranquear provedores de internet/telecom (que por
    acaso tomaram esse credito generico) MUITO acima de cooperativas de credito e
    instituicoes financeiras de verdade (cujo unico sinal real e o setor/segmento
    CNAE, um texto bem mais curto que fica diluido no meio do boilerplate)."""
    df = pd.read_sql(
        "SELECT descricao_projeto, cliente, setor_bndes FROM operations "
        "WHERE descricao_projeto IS NOT NULL AND descricao_projeto <> ''",
        get_engine(),
    )
    df["prefixo"] = df["descricao_projeto"].map(_prefixo_descricao)
    agg = df.groupby("prefixo").agg(clientes=("cliente", "nunique"), setores=("setor_bndes", "nunique"))
    return set(agg[(agg["clientes"] >= limiar_clientes) & (agg["setores"] >= limiar_setores)].index) - {""}


def _embedding_text(row, boilerplate: set = frozenset()) -> str:
    """Foco em CARACTERISTICAS DA LINHA DE CREDITO (setor, produto, modalidade, taxa, prazo,
    tamanho do cheque), NAO no nome da empresa -- a busca deve achar operacoes parecidas em
    natureza, nao so empresas com nome parecido. O nome do cliente fica de fora de proposito.

    `boilerplate` (ver _descricoes_boilerplate): prefixos de descricao de projeto
    genericos de produto/linha de credito, suprimidos do texto embutido (o dado
    continua intacto na coluna descricao_projeto, exibido normalmente -- so nao entra
    na busca semantica, onde ela mais atrapalha do que ajuda)."""
    uf = row.get("uf")
    descricao = row.get("descricao_projeto")
    if _prefixo_descricao(descricao) in boilerplate:
        descricao = None
    parts = [
        row.get("setor_bndes"),
        row.get("subsetor_bndes"),
        row.get("segmento"),
        row.get("produto"),
        row.get("modalidade_apoio"),
        f"indexador {row.get('indexador')}" if row.get("indexador") else None,
        _faixa_valor(row.get("valor_contratado")),
        _faixa_prazo(row.get("prazo_amortizacao_meses")),
        descricao,
        row.get("municipio"),
        uf,
        regiao_de(uf),
    ]
    return " | ".join(str(p) for p in parts if p not in (None, "", "nan"))


def _search_taxonomia_termos(row) -> str:
    """So os sinonimos/taxonomia (ver search_taxonomy.py) para setor/subsetor/segmento
    -- guardado a parte de search_document porque o tsvector com peso por campo (ver
    _atualizar_search_vector) precisa colocar esses termos na MESMA zona de peso do
    setor/segmento (prioridade 2), nao misturados com o resto do texto."""
    parts = [
        " ".join(search_taxonomy.termos_para_setor(row.get("setor_bndes"))),
        " ".join(search_taxonomy.termos_para_subsetor(row.get("subsetor_bndes"))),
        " ".join(search_taxonomy.termos_para_segmento(row.get("segmento"))),
    ]
    return " ".join(p for p in parts if p)


def _search_document(row, boilerplate: set = frozenset()) -> str:
    """Texto-fonte LEGIVEL do motor de busca SEM IA (para depuracao/exportacao, ver
    campo search_document no item 3.2 do pedido) -- o tsvector de busca de verdade
    (search_vector) e montado a parte, com peso por campo, em _atualizar_search_vector
    (nao a partir deste texto plano, que trataria todo campo com a mesma importancia).
    Mesma logica de supressao de boilerplate de _embedding_text(), mais duas diferencas
    propositais: (1) inclui cliente/CNPJ -- o motor por IA deixa esses campos de fora
    (busca por "natureza da operacao", nao por nome de empresa), mas a busca sem IA
    precisa achar por razao social/CNPJ tambem; (2) inclui os sinonimos/taxonomia de
    setor-subsetor-segmento, que substituem a expansao de vocabulario que a IA fazia em
    tempo de busca -- aqui ela e pre-calculada e gravada, uma vez, no proprio documento."""
    uf = row.get("uf")
    descricao = row.get("descricao_projeto")
    if _prefixo_descricao(descricao) in boilerplate:
        descricao = None
    parts = [
        row.get("cliente"),
        row.get("razao_social_oficial"),
        row.get("cnpj"),
        row.get("agencia"),
        row.get("setor_bndes"),
        row.get("subsetor_bndes"),
        row.get("segmento"),
        _search_taxonomia_termos(row),
        row.get("produto"),
        row.get("instrumento_financeiro"),
        row.get("modalidade_apoio"),
        row.get("indexador"),
        descricao,
        row.get("municipio"),
        uf,
        regiao_de(uf),
    ]
    return " | ".join(str(p) for p in parts if p not in (None, "", "nan"))


def _atualizar_search_vector(conn, ids: list) -> None:
    """Recalcula o tsvector (portugues, sem acento) COM PESO POR CAMPO para os ids
    informados, direto das colunas ja gravadas (nao de search_document, que mistura
    tudo com o mesmo peso) -- chamado depois de qualquer insert/update que mude essas
    colunas. Pesos (Postgres usa A > B > C > D):
      A: cliente/razao social oficial/CNPJ (identificacao da empresa -- prioridade maxima)
      B: setor/subsetor/segmento + sinonimos/taxonomia (o que a empresa FAZ)
      C: produto/instrumento/indexador (caracteristicas da linha de credito)
      D: descricao do projeto/municipio/UF/agencia (texto livre, contexto)
    Sem isso, uma palavra generica e frequente (ex: "empresa", "SP") empataria ou
    ate superaria em ranking uma palavra rara e especifica (ex: "hospital") so por
    aparecer em mais campos -- confirmado empiricamente: "hospitais em SP" ranqueava
    fabricante de laticinios (bate "SP" varias vezes) acima do unico hospital real da
    base antes desta mudanca."""
    ids = [int(i) for i in dict.fromkeys(ids)]
    if not ids:
        return
    if len(ids) > 5000:  # lotes curtos (carga inicial do BNB = ~210 mil ids)
        for i in range(0, len(ids), 5000):
            _atualizar_search_vector(conn, ids[i:i + 5000])
        return
    # regexp_replace(..., 'optic', 'otic', 'gi') depois de cada unaccent(): unifica
    # grafias como "optica"/"otica" (mesmo conceito -- "fibra optica" grafia antiga
    # ainda comum, "fibra otica" grafia atual -- mas palavras DIFERENTES pro
    # stemmer sem isso). Mesma normalizacao aplicada do lado da QUERY em
    # search_fts.py::_normaliza_ortografia_sql() -- os dois lados precisam bater.
    # Bug real corrigido por isso: buscar "cabos de fibra otica" rankeava uma otica
    # (oculista, match incidental do nome) ACIMA de uma empresa real de fibra
    # optica (grafia com 'p' na descricao), porque so uma delas "batia" a palavra.
    conn.execute(
        """
        UPDATE operations SET search_vector =
            setweight(to_tsvector('portuguese', regexp_replace(unaccent(coalesce(cliente, '') || ' ' || coalesce(razao_social_oficial, '') || ' ' || coalesce(cnpj, '')), '\\moptic', 'otic', 'gi')), 'A') ||
            setweight(to_tsvector('portuguese', regexp_replace(unaccent(
                coalesce(setor_bndes, '') || ' ' || coalesce(subsetor_bndes, '') || ' ' ||
                coalesce(segmento, '') || ' ' || coalesce(search_taxonomia_termos, '')
            ), '\\moptic', 'otic', 'gi')), 'B') ||
            setweight(to_tsvector('portuguese', regexp_replace(unaccent(
                coalesce(produto, '') || ' ' || coalesce(instrumento_financeiro, '') || ' ' ||
                coalesce(indexador, '') || ' ' || coalesce(modalidade_apoio, '')
            ), '\\moptic', 'otic', 'gi')), 'C') ||
            setweight(to_tsvector('portuguese', regexp_replace(unaccent(
                coalesce(descricao_projeto, '') || ' ' || coalesce(municipio, '') || ' ' ||
                coalesce(uf, '') || ' ' || coalesce(agencia, '')
            ), '\\moptic', 'otic', 'gi')), 'D')
        WHERE id = ANY(?)
        """,
        [ids],
    )
    conn.commit()


def _reclassificar_pendentes(conn, cnae_lookup: pd.DataFrame, boilerplate: set) -> list:
    """Re-checa as operacoes 'pendente' (FINEP cujo CNPJ nao estava no cache cnpj_cnae
    na hora em que a linha foi unificada) contra o cache ATUAL, e atualiza em cima da
    linha ja existente as que agora resolvem -- nunca insere linha nova aqui. Devolve
    os ids atualizados (para o refresh saber quais precisam de um embedding novo)."""
    if cnae_lookup.empty:
        return []

    pendentes = pd.read_sql(
        "SELECT id, cnpj, agencia, cliente, produto, modalidade_apoio, indexador, valor_contratado, "
        "prazo_amortizacao_meses, descricao_projeto, municipio, uf "
        "FROM operations WHERE setor_origem = 'pendente'",
        get_engine(),
    )
    if pendentes.empty:
        return []

    resolvidos = pendentes.merge(cnae_lookup, on="cnpj", how="inner")
    resolvidos = resolvidos[resolvidos["setor_bndes_mapeado"].notna()]
    if resolvidos.empty:
        return []

    updates = []
    for _, row in resolvidos.iterrows():
        campos = {
            "agencia": row["agencia"],
            "cliente": row["cliente"],
            "razao_social_oficial": row["razao_social_oficial"],
            "cnpj": row["cnpj"],
            "setor_bndes": row["setor_bndes_mapeado"],
            "subsetor_bndes": row["subsetor_bndes_mapeado"],
            "segmento": row["cnae_descricao"],
            "produto": row["produto"],
            "modalidade_apoio": row["modalidade_apoio"],
            "indexador": row["indexador"],
            "valor_contratado": row["valor_contratado"],
            "prazo_amortizacao_meses": row["prazo_amortizacao_meses"],
            "descricao_projeto": row["descricao_projeto"],
            "municipio": row["municipio"],
            "uf": row["uf"],
        }
        texto_embedding = _embedding_text(campos, boilerplate)
        texto_busca = _search_document(campos, boilerplate)
        texto_taxonomia = _search_taxonomia_termos(campos)
        updates.append((
            row["setor_bndes_mapeado"], row["subsetor_bndes_mapeado"], row["cnae_descricao"],
            row["porte_empresa"], row["natureza_juridica"], row["razao_social_oficial"],
            texto_embedding, texto_busca, texto_taxonomia, int(row["id"]),
        ))

    cur = conn.cursor()
    cur.executemany(
        "UPDATE operations SET setor_bndes = ?, subsetor_bndes = ?, segmento = ?, "
        "porte_cliente = COALESCE(porte_cliente, ?), natureza_cliente = COALESCE(natureza_cliente, ?), "
        "razao_social_oficial = ?, "
        "setor_origem = 'enriquecido', embedding_text = ?, search_document = ?, search_taxonomia_termos = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    ids = [u[-1] for u in updates]
    _atualizar_search_vector(conn, ids)
    return ids


def reclassificar_pendentes(conn=None) -> list:
    """Wrapper publico de _reclassificar_pendentes -- permite rodar a reclassificacao
    uma SEGUNDA vez no mesmo refresh, depois de build_operations() ja ter rodado a
    primeira, quando algo novo foi adicionado ao cache cnpj_cnae NO MEIO do refresh
    (ver enrich_cnae.py::enrich_pendentes_via_api, chamada por refresh.py). Recarrega
    o cnae_lookup na hora (nao reusa um snapshot antigo) para enxergar o que acabou de
    ser gravado."""
    fechar = conn is None
    conn = conn or get_connection()
    try:
        cnae_lookup = _load_cnae_lookup(conn)
        boilerplate = _descricoes_boilerplate(conn)
        ids = _reclassificar_pendentes(conn, cnae_lookup, boilerplate)
        conn.commit()
        # CNPJs recem-resolvidos tambem mudam o setor padronizado por CNAE.
        recalcular_setor_cnae(conn)
        _reaplicar_correcoes_manuais(conn)
        return ids
    finally:
        if fechar:
            conn.close()


LOTE_INSERT_OPERATIONS = 5000


def build_operations():
    """Incremental: so insere operacoes para linhas raw novas + reclassifica pendentes
    que resolveram desde o ultimo refresh. Devolve um dict (nao so uma tupla) porque o
    orquestrador do refresh (refresh.py) precisa dos IDS novos/reclassificados para
    passar pro embeddings incremental (embeddings.py), nao so das contagens."""
    conn = get_connection()
    try:
        cnae_lookup = _load_cnae_lookup(conn)
        parts = [
            _build_bndes_ops(conn, cnae_lookup),
            _build_finep_direto_ops(conn, cnae_lookup),
            _build_finep_descentralizado_ops(conn, cnae_lookup),
        ]
        # BNB: best-effort -- se bnb_raw nao existir/falhar, BNDES/FINEP seguem normalmente.
        try:
            parts.append(_build_bnb_ops(conn, cnae_lookup))
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            print(f"aviso: BNB nao unificado nesta rodada ({e})")
        parts = [p for p in parts if p is not None and not p.empty]
        novas = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if not novas.empty:
            # 'IE' e' o sentinela que BNDES/FINEP usam pra abrangencia nacional/interestadual
            # (nao e' um estado real) -- normalizado pro rotulo exibido no frontend antes de
            # gravar, senao a proxima operacao nacional que entrar via refresh volta a
            # aparecer como 'IE' misturada com as linhas ja renomeadas em producao.
            novas["uf"] = novas["uf"].replace({"IE": "Nacional"})

        boilerplate = _descricoes_boilerplate(conn)

        novos_ids = []
        if not novas.empty:
            novas["embedding_text"] = novas.apply(lambda r: _embedding_text(r, boilerplate), axis=1)
            novas["search_document"] = novas.apply(lambda r: _search_document(r, boilerplate), axis=1)
            novas["search_taxonomia_termos"] = novas.apply(_search_taxonomia_termos, axis=1)
            # Lotes com commit por lote (BNB traz ~210 mil linhas na 1a carga --
            # nunca uma transacao longa em `operations`).
            # O calculo dos textos acima leva minutos na 1a carga do BNB e o Aiven
            # derruba sessao ociosa (idle_session_timeout=5min) -- reabre a conexao.
            conn.close()
            conn = get_connection()
            for i in range(0, len(novas), LOTE_INSERT_OPERATIONS):
                lote = novas.iloc[i:i + LOTE_INSERT_OPERATIONS]
                for tentativa in range(3):
                    try:
                        insert_new_rows(conn, "operations", lote, OPERATIONS_COLS)
                        conn.commit()
                        break
                    except Exception:  # noqa: BLE001 -- conexao caiu no meio do lote (rollback no servidor)
                        if tentativa == 2:
                            raise
                        try:
                            conn.close()
                        except Exception:  # noqa: BLE001
                            pass
                        conn = get_connection()
            # recupera os ids autoincrement recem-atribuidos, por (raw_table, raw_id)
            for raw_table, grupo in novas.groupby("raw_table"):
                raw_ids = grupo["raw_id"].astype(int).tolist()
                rows = conn.execute(
                    "SELECT id FROM operations WHERE raw_table = ? AND raw_id = ANY(?)",
                    [raw_table, raw_ids],
                ).fetchall()
                novos_ids.extend(r[0] for r in rows)
        # Autocorrecao: qualquer linha sem search_vector (ex. rodada anterior que caiu
        # entre o insert e este passo) entra junto.
        sem_vetor = [r[0] for r in conn.execute("SELECT id FROM operations WHERE search_vector IS NULL").fetchall()]
        ja = set(novos_ids)
        novos_ids.extend(i for i in sem_vetor if i not in ja)
        _atualizar_search_vector(conn, novos_ids)

        reclassificados_ids = _reclassificar_pendentes(conn, cnae_lookup, boilerplate)
        conn.commit()

        setor_cnae_info = recalcular_setor_cnae(conn)
        print(f"setor_cnae: {setor_cnae_info['atualizadas']} de {setor_cnae_info['total']} operacoes atualizadas.")

        n_correcoes = _reaplicar_correcoes_manuais(conn)

        total_ops = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        n_pendente = conn.execute("SELECT COUNT(*) FROM operations WHERE setor_origem = 'pendente'").fetchone()[0]
    finally:
        conn.close()

    n_novas = len(novas) if not novas.empty else 0
    print(
        f"operations: {n_novas} linhas novas, {len(reclassificados_ids)} reclassificadas de "
        f"pendente -> enriquecido, {n_correcoes} correcoes manuais reaplicadas, {total_ops} no "
        f"total ({n_pendente} ainda pendentes de enriquecimento)."
    )
    return {
        "novas": n_novas,
        "total": total_ops,
        "pendentes": n_pendente,
        "novos_ids": novos_ids,
        "reclassificados_ids": reclassificados_ids,
        "correcoes_reaplicadas": n_correcoes,
    }


if __name__ == "__main__":
    build_operations()
