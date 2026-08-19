"""SQLite schema and connection helpers for the Radar de Credito Incentivado project.

Roda em dois modos, escolhidos por variavel de ambiente -- o app local (desktop, na
maquina do usuario, via schtasks) continua usando um arquivo SQLite local, sem NENHUMA
mudanca de comportamento. A versao hospedada (deploy compartilhado entre varias
pessoas) usa Turso (banco compativel com SQLite, acessado pela rede) quando
TURSO_DATABASE_URL esta definida. O resto do codigo (que faz conn.execute(...),
cur = conn.cursor(), .fetchall(), .commit(), etc) funciona igual nos dois modos --
libsql implementa a mesma interface do sqlite3 (PEP 249).

NAO TESTADO CONTRA UM BANCO TURSO REAL (nao ha como criar uma conta/credencial daqui).
Depois de criar o banco (ver DEPLOY.md) e configurar as variaveis de ambiente, rode
`python src/db.py` uma vez para confirmar que o schema inicializa certo nesse modo."""
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "radar.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")
MODO_HOSPEDADO = bool(TURSO_DATABASE_URL)


def get_connection():
    if MODO_HOSPEDADO:
        import libsql

        # Modo remoto puro (sem replica local nem sync): toda query vai direto pro
        # Turso pela rede. Mais simples e mais seguro pra varias pessoas usando ao
        # mesmo tempo do que o modo "replica local com sync" -- sem isso, escritas de
        # uma pessoa (ex: cache de resumo de IA) poderiam demorar a aparecer pra outra.
        # Testado localmente contra o formato da API (libsql==0.1.11); nao testado
        # contra um banco Turso real ainda -- ver DEPLOY.md.
        return libsql.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def executescript_compat(conn, script: str):
    """executescript() e uma extensao do sqlite3 que o libsql pode nao ter -- faz um
    fallback simples (split por ';') quando o metodo nao existe. O SCHEMA deste
    projeto nao tem ';' dentro de strings/literais, entao o split e seguro aqui."""
    if hasattr(conn, "executescript"):
        conn.executescript(script)
        return
    for statement in script.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)


# Tables that are fully dropped and rebuilt on every weekly refresh.
#
# ATE 2026-08: bndes_raw/finep_*_raw/operations tambem estavam aqui (drop+reload
# completo toda semana). Migrado para incremental (ver incremental.py, unify.py,
# embeddings.py): BNDES/FINEP republicam o historico INTEIRO a cada refresh, mas em
# vez de jogar tudo fora e reconstruir do zero, agora so inserimos linhas realmente
# novas (por hash de conteudo da linha, ja que numero_contrato/contrato_finep_agente
# NAO sao chave unica por linha -- ver commit/PR que introduziu isso). Continuam
# fazendo drop+rebuild completo apenas as tabelas pequenas/derivadas, onde isso e
# barato e nao ha problema de duplicacao nem de estabilidade de id:
# - de_para_cnae: tabela de-para pequena (~60 linhas), republicada inteira pelo
#   proprio BNDES a cada planilha -- reload completo e simples e correto.
# - agg_*: agregados pre-calculados, recalculados do zero a partir da `operations`
#   atual a cada refresh -- barato (poucas linhas de saida) e sem chave natural.
REBUILD_EACH_REFRESH = [
    "de_para_cnae",
    "agg_setor_periodo",
    "agg_uf",
    "agg_porte",
]

SCHEMA = """
-- ============ Staging: raw BNDES sheet, columns kept close to the source ============
-- row_hash: sha256 do conteudo da linha (ver incremental.py) -- usado para o refresh
-- incremental saber quais linhas do arquivo baixado (que vem com TODO o historico
-- de novo a cada vez) ja existem aqui, sem precisar de uma chave natural -- BNDES
-- publica varias linhas por numero_contrato (uma por desembolso), entao esse campo
-- sozinho nao serve como chave unica.
CREATE TABLE IF NOT EXISTS bndes_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_hash TEXT,
    cliente TEXT,
    cnpj TEXT,
    descricao_projeto TEXT,
    uf TEXT,
    municipio TEXT,
    municipio_codigo TEXT,
    numero_contrato TEXT,
    data_contratacao TEXT,
    valor_contratado REAL,
    valor_desembolsado REAL,
    fonte_recurso TEXT,
    custo_financeiro TEXT,
    juros REAL,
    prazo_carencia_meses REAL,
    prazo_amortizacao_meses REAL,
    modalidade_apoio TEXT,
    forma_apoio TEXT,
    produto TEXT,
    instrumento_financeiro TEXT,
    inovacao TEXT,
    area_operacional TEXT,
    setor_cnae TEXT,
    subsetor_cnae_agrupado TEXT,
    subsetor_cnae_codigo TEXT,
    subsetor_cnae_nome TEXT,
    setor_bndes TEXT,
    subsetor_bndes TEXT,
    porte_cliente TEXT,
    natureza_cliente TEXT,
    instituicao_financeira_credenciada TEXT,
    cnpj_if_credenciada TEXT,
    tipo_garantia TEXT,
    tipo_excepcionalidade TEXT,
    situacao_contrato TEXT
);

-- ============ Staging: FINEP Projetos_Credito_Direto ============
CREATE TABLE IF NOT EXISTS finep_credito_direto_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_hash TEXT,
    demanda TEXT,
    ref TEXT,
    contrato TEXT,
    data_entrada_sf TEXT,
    dt_aprov_operacional_credito TEXT,
    dt_aprov_juridica_garantias TEXT,
    data_assinatura TEXT,
    tempo_avaliacao_oper_credito REAL,
    tempo_avaliacao_jur_garantias REAL,
    tempo_total_avaliacao REAL,
    tempo_contratacao REAL,
    prazo_execucao TEXT,
    titulo TEXT,
    proponente TEXT,
    cnpj_proponente TEXT,
    municipio_proponente TEXT,
    uf_proponente TEXT,
    regiao_proponente TEXT,
    executor TEXT,
    cnpj_executor TEXT,
    municipio_executor TEXT,
    uf_executor TEXT,
    regiao_executor TEXT,
    uf_projeto TEXT,
    valor_finep REAL,
    contrapartida_financeira REAL,
    valor_pago REAL,
    status TEXT,
    resumo_publicavel TEXT
);

-- ============ Staging: FINEP Projetos_Credito_Descentralizado ============
CREATE TABLE IF NOT EXISTS finep_credito_descentralizado_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_hash TEXT,
    data_assinatura TEXT,
    contrato_finep_agente TEXT,
    beneficiario TEXT,
    cnpj_beneficiario TEXT,
    uf_beneficiario TEXT,
    valor_financiado REAL,
    valor_liberado REAL,
    contrapartida REAL,
    outros_recursos REAL,
    agente TEXT
);

-- ============ Staging: FINEP Projetos Nao Aprovados (para taxa de aprovacao real) ============
-- BNDES nao publica dados de propostas recusadas -- so a FINEP tem essa base publica,
-- e so para os instrumentos que ela mesma decide (Credito Direto tem volume relevante;
-- Credito Descentralizado nao aparece aqui pois quem decide e o banco parceiro).
CREATE TABLE IF NOT EXISTS finep_nao_aprovados_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_hash TEXT,
    instrumento TEXT,
    demanda TEXT,
    referencia TEXT,
    data_entrada TEXT,
    data_indeferimento TEXT,
    proponente TEXT,
    cnpj TEXT,
    uf TEXT,
    municipio TEXT,
    regiao TEXT,
    valor_finep REAL
);

-- ============ De-Para CNAE -> Setor/Subsetor BNDES (from the BNDES workbook) ============
CREATE TABLE IF NOT EXISTS de_para_cnae (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setor_cnae TEXT,
    subsetor_cnae_agrupado TEXT,
    subsetor_bndes TEXT,
    setor_bndes TEXT,
    codigo_cnae_ibge_faixa TEXT,
    produto_bndes TEXT
);

-- ============ Persistent cache: CNPJ -> CNAE (from Receita Federal Dados Abertos) ============
-- NOT dropped on refresh; enrich_cnae.py only inserts/updates rows.
CREATE TABLE IF NOT EXISTS cnpj_cnae (
    cnpj TEXT PRIMARY KEY,
    razao_social TEXT,
    cnae_codigo TEXT,
    cnae_descricao TEXT,
    cnae_divisao TEXT,
    setor_bndes_mapeado TEXT,
    subsetor_bndes_mapeado TEXT,
    atualizado_em TEXT
);

-- ============ Unified operations table (BNDES + FINEP credito) ============
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agencia TEXT NOT NULL,              -- 'BNDES' | 'FINEP'
    instrumento TEXT,                    -- 'Direto' | 'Indireto nao automatico' | 'Credito Direto' | 'Credito Descentralizado'
    fonte_id TEXT,                       -- numero_contrato / contrato (original id, for traceability)
    cliente TEXT,
    cnpj TEXT,
    uf TEXT,
    municipio TEXT,
    data_contratacao TEXT,
    ano INTEGER,
    trimestre INTEGER,
    valor_contratado REAL,
    valor_desembolsado REAL,
    setor_bndes TEXT,                    -- unified sector taxonomy (4 categorias)
    subsetor_bndes TEXT,                 -- unified subsector taxonomy (19 categorias)
    segmento TEXT,                       -- granularidade fina baseada em CNAE (centenas de categorias)
    setor_origem TEXT,                   -- 'nativo' (BNDES) | 'enriquecido' (FINEP via CNPJ) | 'pendente'
    porte_cliente TEXT,
    produto TEXT,
    modalidade_apoio TEXT,               -- REEMBOLSAVEL | NAO REEMBOLSAVEL (caracteristica da linha)
    indexador TEXT,                      -- custo financeiro / indexador (ex: TLP, SELIC) -- so BNDES por enquanto
    taxa_juros REAL,                     -- spread/juros -- so BNDES por enquanto
    prazo_carencia_meses REAL,
    prazo_amortizacao_meses REAL,
    descricao_projeto TEXT,
    agente_financeiro TEXT,              -- instituicao financeira credenciada / agente repassador
    raw_table TEXT NOT NULL,             -- which *_raw table to join back to for full drill-down
    raw_id INTEGER NOT NULL,
    embedding_text TEXT                  -- text that was embedded (for debugging/inspection)
);

CREATE INDEX IF NOT EXISTS idx_bndes_raw_hash ON bndes_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_finep_direto_hash ON finep_credito_direto_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_finep_descentralizado_hash ON finep_credito_descentralizado_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_finep_nao_aprovados_hash ON finep_nao_aprovados_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_operations_raw ON operations(raw_table, raw_id);
CREATE INDEX IF NOT EXISTS idx_operations_setor_origem ON operations(setor_origem);

CREATE INDEX IF NOT EXISTS idx_operations_setor ON operations(setor_bndes);
CREATE INDEX IF NOT EXISTS idx_operations_segmento ON operations(segmento);
CREATE INDEX IF NOT EXISTS idx_operations_agencia ON operations(agencia);
CREATE INDEX IF NOT EXISTS idx_operations_ano ON operations(ano);
CREATE INDEX IF NOT EXISTS idx_operations_uf ON operations(uf);
CREATE INDEX IF NOT EXISTS idx_operations_cnpj ON operations(cnpj);

-- ============ Pre-aggregated tables for fast dashboard loading ============
CREATE TABLE IF NOT EXISTS agg_setor_periodo (
    setor_bndes TEXT,
    agencia TEXT,
    ano INTEGER,
    trimestre INTEGER,
    n_operacoes INTEGER,
    valor_total REAL,
    cheque_medio REAL
);

CREATE TABLE IF NOT EXISTS agg_uf (
    uf TEXT,
    agencia TEXT,
    n_operacoes INTEGER,
    valor_total REAL,
    cheque_medio REAL
);

CREATE TABLE IF NOT EXISTS agg_porte (
    porte_cliente TEXT,
    agencia TEXT,
    n_operacoes INTEGER,
    valor_total REAL,
    cheque_medio REAL
);

-- ============ Refresh log / status ============
CREATE TABLE IF NOT EXISTS refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    bndes_rows INTEGER,
    finep_credito_direto_rows INTEGER,
    finep_credito_descentralizado_rows INTEGER,
    operations_rows INTEGER,
    setores_pendentes INTEGER,
    status TEXT,
    detalhe TEXT
);

-- ============ Editais/chamadas publicas abertas da FINEP (oportunidades futuras) ============
-- NAO faz parte do REBUILD_EACH_REFRESH: usa UPSERT (id da propria FINEP como chave),
-- para preservar resumo_ia/resumo_gerado_em entre refreshes diarios em vez de regerar
-- o resumo por IA todo dia para editais que ninguem clicou ainda.
CREATE TABLE IF NOT EXISTS editais_raw (
    id INTEGER PRIMARY KEY,              -- id da FINEP, nao autoincrement
    titulo TEXT,
    tema_principal TEXT,
    temas TEXT,
    situacao TEXT,                       -- 'aberta' | 'encerrada'
    tipo_oportunidade TEXT,
    tipo_cooperacao TEXT,
    contrapartida TEXT,
    regiao TEXT,
    publico_alvo TEXT,                   -- JSON list das chaves (empresa1..5, ict, startup, ...)
    aplicavel_empresa INTEGER,           -- 1/0, derivado de publico_alvo
    data_publicacao TEXT,
    vigencia_inicio TEXT,
    vigencia_fim TEXT,
    prazo_proposto TEXT,
    descricao_html TEXT,
    descricao_texto TEXT,
    documentos TEXT,                     -- JSON list [{label, url}], inclui Regulamento/Anexos reais
    documento_chave_texto TEXT,          -- texto extraido do PDF do Regulamento + Anexo 1 (fonte do resumo por IA)
    documento_chave_atualizado_em TEXT,
    resumo_ia TEXT,
    resumo_gerado_em TEXT,
    atualizado_em TEXT
);

CREATE INDEX IF NOT EXISTS idx_editais_situacao ON editais_raw(situacao);
CREATE INDEX IF NOT EXISTS idx_editais_aplicavel_empresa ON editais_raw(aplicavel_empresa);
CREATE INDEX IF NOT EXISTS idx_editais_prazo ON editais_raw(prazo_proposto);

CREATE TABLE IF NOT EXISTS refresh_editais_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    total_editais INTEGER,
    abertos INTEGER,
    status TEXT,
    detalhe TEXT
);
"""


# Colunas adicionadas apos a criacao inicial da tabela -- CREATE TABLE IF NOT EXISTS nao
# adiciona colunas em uma tabela ja existente, entao precisam de ALTER TABLE explicito.
MIGRACOES_COLUNAS = [
    ("editais_raw", "documento_chave_texto", "TEXT"),
    ("editais_raw", "documento_chave_atualizado_em", "TEXT"),
    # Adicionadas quando bndes_raw/finep_*_raw deixaram de ser drop+reload completo
    # e passaram a ser incrementais (ver incremental.py) -- bancos ja existentes
    # precisam do ALTER TABLE explicito, CREATE TABLE IF NOT EXISTS nao adiciona
    # coluna em tabela que ja existe.
    ("bndes_raw", "row_hash", "TEXT"),
    ("finep_credito_direto_raw", "row_hash", "TEXT"),
    ("finep_credito_descentralizado_raw", "row_hash", "TEXT"),
    ("finep_nao_aprovados_raw", "row_hash", "TEXT"),
]


def _aplicar_migracoes(conn):
    colunas_existentes = {}
    for tabela, coluna, tipo in MIGRACOES_COLUNAS:
        if tabela not in colunas_existentes:
            rows = conn.execute(f"PRAGMA table_info({tabela})").fetchall()
            colunas_existentes[tabela] = {r[1] for r in rows}
        if colunas_existentes[tabela] and coluna not in colunas_existentes[tabela]:
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
            colunas_existentes[tabela].add(coluna)
    conn.commit()


def init_db():
    conn = get_connection()
    try:
        # migracoes ANTES do executescript: em um banco ja existente, o SCHEMA tem
        # "CREATE TABLE IF NOT EXISTS" (nao-op se a tabela ja existe) mas tambem tem
        # "CREATE INDEX" sobre colunas novas (ex: row_hash) -- se a coluna so for
        # adicionada DEPOIS do executescript, o CREATE INDEX quebra achando que a
        # coluna nao existe. Rodar migracoes antes garante que colunas novas ja
        # existem quando os indices forem criados.
        _aplicar_migracoes(conn)
        executescript_compat(conn, SCHEMA)
        conn.commit()
        # roda de novo: cobre o caso de banco novo (tabelas acabaram de ser criadas
        # agora pelo executescript acima, entao a chamada anterior foi um no-op).
        _aplicar_migracoes(conn)
    finally:
        conn.close()


def drop_rebuild_tables(conn):
    """Drop the tables that get a full reload on every refresh (keeps cnpj_cnae cache intact)."""
    for table in REBUILD_EACH_REFRESH:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    executescript_compat(conn, SCHEMA)
    conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Banco inicializado em {DB_PATH}")
