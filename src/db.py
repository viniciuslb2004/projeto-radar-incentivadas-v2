"""Schema e conexao Postgres (Supabase) para o Radar de Credito Incentivado.

Banco UNICO, sempre Postgres, acessado via `DATABASE_URL` (variavel de ambiente).
Nao ha mais modo dual SQLite local (desktop) / Turso hospedado -- essa distincao
existiu num passado deste projeto e foi removida: o app agora SEMPRE fala com o
mesmo Postgres, local ou em producao, sem nenhuma bifurcacao de comportamento.

`DATABASE_URL` normalmente vem de um arquivo `.env` na raiz do repo em
desenvolvimento local (carregado abaixo via `load_dotenv()`, que e um no-op seguro
quando o arquivo nao existe) e de uma variavel de ambiente real configurada na
plataforma de deploy (ex: Vercel) em producao.
"""
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import psycopg

import db_compat

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Ainda usado por modulos que gravam/leem arquivos locais que NAO sao o banco (ex:
# data/embeddings.npz, data/editais_embeddings.npz, data/raw/, data/rfb_tmp/) --
# so o antigo DB_PATH (arquivo .db do SQLite) deixou de existir.
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Monkeypatch `?` -> `%s` (ver db_compat.py) -- aplicado uma unica vez por processo,
# antes de qualquer conexao psycopg ser aberta, para que TODO `conn.execute(sql, ?)`/
# `cur.executemany(sql, ?)` do resto do codigo (SQL parametrizado no estilo SQLite,
# nunca reescrito) continue funcionando sem nenhuma mudanca nos call sites.
db_compat.patch()

_ENGINE = None
_POOL = None


class _PooledConnection:
    """Encaminha tudo pra conexao real de dentro do pool (`psycopg_pool.ConnectionPool`),
    so troca o significado de `.close()`: em vez de fechar a conexao fisica de verdade,
    devolve ela pro pool (`putconn`) pra outra requisicao reusar. Sem este wrapper, todo
    call site existente (`conn = get_connection(...); try: ...; finally: conn.close()`,
    ~26+ lugares so em webapp/main.py) precisaria virar `with pool.connection() as conn`
    -- refatoracao grande e arriscada. Com o wrapper, ZERO call site muda: todo o resto
    (`.cursor()`, `.execute()`, `.commit()`, `.rollback()`) e so __getattr__ direto na
    conexao real por baixo."""

    def __init__(self, pool, conn):
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_conn", conn)

    def close(self):
        self._pool.putconn(self._conn)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)


def _get_pool():
    """Pool de conexoes de verdade para a webapp (`get_connection(pooled=True)`) --
    resolve o problema real de "max clients"/"remaining connection slots" que ja
    aconteceu tanto no pooler em modo session da Supabase (limite de 15) quanto no
    limite bruto de 20 conexoes do Aiven free tier (sem pooler proprio disponivel
    nesse plano): cada requisicao HTTP abrindo/fechando sua PROPRIA conexao fisica
    faz uma unica carga de pagina (~15-20 chamadas /api/* em paralelo) esgotar
    qualquer um desses limites. Um pool pequeno e fixo (max_size bem abaixo do teto
    real do provedor) faz requisicoes concorrentes REUSAREM um numero pequeno de
    conexoes fisicas em vez de multiplicar 1-pra-1 com o trafego.

    min_size=0 (nao mantem conexao ociosa aberta a toa -- instancia serverless e
    efemera, um min_size>=1 so paga o custo de abrir uma conexao que pode nunca ser
    usada de novo antes da instancia reciclar) + max_size=2 (BEM mais conservador do
    que "metade do teto do provedor" pareceria sugerir): a Vercel pode escalar pra
    VARIAS instancias da function rodando ao mesmo tempo sob trafego concorrente, e
    CADA instancia tem seu PROPRIO pool (variavel global `_POOL` e por processo, nao
    compartilhada entre instancias) -- um max_size=8 com so 2 instancias concorrentes
    ja seriam 16 conexoes, estourando o limite de 15 do pooler em modo session da
    Supabase (bug real reproduzido em producao: EMAXCONNSESSION mesmo com o pool
    ligado, causa raiz do incidente que motivou a migracao pro Aiven). max_size=2 da
    margem pra ~10 instancias concorrentes ficarem dentro do teto bruto de 20 conexoes
    do Aiven (sem pooler gerenciado nesse plano, entao esse teto e o unico limite que
    resta hoje) -- testado ao vivo em producao contra o Aiven com 45 requisicoes
    concorrentes (30 buscas + 15 kpis) em paralelo, 0 erros. Nao ha evidencia de que
    subir pra 3 traga ganho de latencia perceptivel (o gargalo real medido foi rede/
    processamento por requisicao, nao fila de conexao), e 3 reduziria essa margem de
    ~10 pra ~6 instancias concorrentes antes de estourar o teto -- por isso manter em
    2 em vez de arriscar subir sem necessidade comprovada. FastAPI roda rotas sincronas
    (`def`, nao `async def` -- confirmado neste projeto) num threadpool do
    Starlette, entao um pool sincrono e bloqueante do psycopg_pool e exatamente o
    caso de uso certo (thread-safe, cada thread pega sua propria conexao
    emprestada).

    check=ConnectionPool.check_connection -- BUG REAL corrigido por isso: sem essa
    opcao (nao ligada por padrao no psycopg_pool), uma conexao MORTA por uma acao do
    lado do servidor (confirmado ao vivo contra o Aiven free tier: AdminShutdown
    durante uma manutencao automatica) ficava presa dentro do pool e era devolvida
    pra TODA requisicao seguinte, quebrando a webapp inteira (500 em toda rota que
    toca o banco) ate o processo ser reiniciado -- o pool nunca percebia sozinho que
    a conexao tinha morrido. Com o check, getconn() valida a conexao (um SELECT
    simples) antes de devolver, descarta e abre uma nova na hora se a antiga estiver
    morta -- custa uma ida a mais ao banco por checkout, troca aceitavel por nunca
    mais travar a webapp inteira numa conexao morta."""
    global _POOL
    if _POOL is None:
        from psycopg_pool import ConnectionPool

        database_url = os.environ.get("DATABASE_URL_POOLER") or os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL nao configurada.")
        _POOL = ConnectionPool(
            database_url, min_size=0, max_size=2, open=True,
            check=ConnectionPool.check_connection,
        )
    return _POOL


def get_connection(pooled: bool = False):
    """Conexao psycopg (Postgres) -- a UNICA forma de acesso ao banco neste projeto.
    Levanta um erro claro se a variavel de ambiente relevante nao estiver configurada,
    em vez de cair silenciosamente em qualquer outro banco/arquivo.

    pooled=True usa um pool de conexoes de verdade (ver _get_pool()) -- so a webapp
    (webapp/main.py) passa pooled=True, porque e o unico caller que abre muitas
    conexoes curtas e concorrentes (uma por requisicao HTTP); os scripts de pipeline
    (refresh.py, enrich_cnae.py etc, chamados so por GitHub Actions/execucao manual)
    fazem sessoes longas com poucas conexoes -- o caso de uso oposto ao que o pool
    resolve -- entao continuam em get_connection() simples (uma conexao direta,
    fechada de verdade no final), sem mudar nada.

    DATABASE_URL_POOLER (se definida) tem prioridade sobre DATABASE_URL so pro
    caminho pooled=True -- existe pra um provedor que ofereca um endpoint de pooler
    GERENCIADO separado (ex: Supabase em modo transaction, porta 6543); sem essa
    variavel definida, o pool conecta na mesma DATABASE_URL de sempre (caso do Aiven
    free tier, que nao tem endpoint de pooler proprio -- o pool acima e que faz esse
    papel, do lado do cliente)."""
    if pooled:
        return _PooledConnection(_get_pool(), _get_pool().getconn())
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL nao configurada. Defina essa variavel de ambiente com a "
            "connection string do Postgres -- em desenvolvimento local, via um "
            "arquivo .env na raiz do repo; em producao, como variavel de ambiente "
            "real da plataforma de deploy."
        )
    return psycopg.connect(database_url)


def get_engine():
    """Engine SQLAlchemy, usado APENAS pelos scripts de pipeline (unify.py,
    enrich_cnae.py, parse_bndes.py) que fazem `pd.read_sql(...)`/`df.to_sql(...)`.

    pandas nao suporta de forma confiavel uma conexao psycopg3 crua para isso:
    `pd.read_sql` ate funciona (emite so um UserWarning), mas `df.to_sql` FALHA na
    pratica (`ProgrammingError: the query has 0 placeholders but N parameters were
    passed`, confirmado testando contra o banco real) -- por isso esses pipelines
    passam a usar este engine em vez da conexao crua so para essas chamadas
    especificas do pandas, mantendo `get_connection()` (SQL parametrizado explicito,
    via db_compat) para todo o resto (inserts/updates escritos a mao).

    NAO usado pelo resto do codigo (webapp/main.py, search.py, etc.) -- so por esses
    poucos modulos de pipeline que dependem do pandas para ler/gravar DataFrame
    inteiro de uma vez."""
    global _ENGINE
    if _ENGINE is None:
        from sqlalchemy import create_engine

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL nao configurada.")
        # SQLAlchemy precisa do dialeto explicito ("+psycopg") para usar o driver
        # psycopg (v3) em vez de tentar psycopg2 (nao instalado neste projeto).
        sqlalchemy_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        _ENGINE = create_engine(sqlalchemy_url)
    return _ENGINE


# Tables that are fully dropped and rebuilt on every weekly refresh.
#
# ATE 2026-08: bndes_raw/finep_*_raw/operations tambem estavam aqui (drop+reload
# completo toda semana). Migrado para incremental (ver incremental.py, unify.py,
# embeddings.py): BNDES/FINEP republicam o historico INTEIRO a cada refresh, mas em
# vez de jogar tudo fora e reconstruir do zero, agora so inserimos linhas realmente
# novas (por hash de conteudo da linha, ja que numero_contrato/contrato_finep_agente
# NAO sao chave unica por linha -- ver commit/PR que introduziu isso). So sobrou
# de_para_cnae aqui (tabela de-para pequena, ~60 linhas, republicada inteira pelo
# proprio BNDES a cada planilha -- reload completo e simples e correto). As tabelas
# agg_setor_periodo/agg_uf/agg_porte que existiam aqui foram REMOVIDAS em 2026-08:
# nenhuma rota da API as lia (webapp/main.py sempre fez GROUP BY ao vivo em
# `operations`) -- eram custo puro (um SELECT * de operations inteira + 3 escritas
# via to_sql, toda semana, contra um banco que ja luta pra terminar dentro do
# timeout do CI sobre Turso). Se um consumidor de verdade aparecer no futuro, vale
# reintroduzir com um leitor real, nao "pre-calculado por via das duvidas".
REBUILD_EACH_REFRESH = [
    "de_para_cnae",
]

SCHEMA = """
-- ============ Busca sem IA: extensoes Postgres usadas pelo motor de full-text/trigram
-- (ver src/search_fts.py) -- unaccent para ignorar acentuacao na comparacao, pg_trgm
-- para tolerancia a erro de digitação/nomes parecidos. Substituem, no caminho padrao
-- de producao, a busca por embeddings (ver MOTOR_BUSCA_IA em webapp/main.py) -- o
-- codigo de embeddings continua intacto e religavel, so nao roda por padrao. ============
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============ Staging: raw BNDES sheet, columns kept close to the source ============
-- row_hash: sha256 do conteudo da linha (ver incremental.py) -- usado para o refresh
-- incremental saber quais linhas do arquivo baixado (que vem com TODO o historico
-- de novo a cada vez) ja existem aqui, sem precisar de uma chave natural -- BNDES
-- publica varias linhas por numero_contrato (uma por desembolso), entao esse campo
-- sozinho nao serve como chave unica.
CREATE TABLE IF NOT EXISTS bndes_raw (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    setor_cnae TEXT,
    subsetor_cnae_agrupado TEXT,
    subsetor_bndes TEXT,
    setor_bndes TEXT,
    codigo_cnae_ibge_faixa TEXT,
    produto_bndes TEXT
);

-- ============ Persistent cache: CNPJ -> CNAE (from Receita Federal Dados Abertos) ============
-- NOT dropped on refresh; enrich_cnae.py only inserts/updates rows.
-- NOTA: `razao_social` historicamente guarda o nome_fantasia (Estabelecimentos.zip),
-- nao a razao social oficial -- mantido como esta para nao quebrar quem ja le esse
-- campo. `razao_social_oficial` (Empresas.zip, ver enrich_empresas() em
-- enrich_cnae.py) e o dado real de identificacao da empresa (item 3.2 do pedido).
CREATE TABLE IF NOT EXISTS cnpj_cnae (
    cnpj TEXT PRIMARY KEY,
    razao_social TEXT,
    cnae_codigo TEXT,
    cnae_descricao TEXT,
    cnae_divisao TEXT,
    setor_bndes_mapeado TEXT,
    subsetor_bndes_mapeado TEXT,
    atualizado_em TEXT,
    razao_social_oficial TEXT,   -- Empresas.zip: nome legal registrado na Receita Federal
    natureza_juridica TEXT,      -- Empresas.zip + Naturezas.zip: ex "Sociedade Empresária Limitada"
    porte_empresa TEXT,          -- Empresas.zip: "Micro Empresa" | "Empresa de Pequeno Porte" | "Demais" | "Nao informado pela fonte"
    capital_social REAL          -- Empresas.zip: capital social declarado (R$)
);

-- ============ Unified operations table (BNDES + FINEP credito) ============
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    instrumento_financeiro TEXT,          -- sub-linha REAL dentro do produto (ex: dentro de "BNDES
                                           -- FINEM": "PSI - Inovacao", "CAPACIDADE PRODUTIVA -
                                           -- Industria de Bens de Capital") -- so BNDES por enquanto
                                           -- (bndes_raw.instrumento_financeiro; FINEP nao tem
                                           -- equivalente na planilha de origem)
    modalidade_apoio TEXT,               -- REEMBOLSAVEL | NAO REEMBOLSAVEL (caracteristica da linha)
    indexador TEXT,                      -- custo financeiro / indexador (ex: TLP, SELIC) -- so BNDES por enquanto
    taxa_juros REAL,                     -- spread/juros -- so BNDES por enquanto
    prazo_carencia_meses REAL,
    prazo_amortizacao_meses REAL,
    descricao_projeto TEXT,
    agente_financeiro TEXT,              -- instituicao financeira credenciada / agente repassador
    raw_table TEXT NOT NULL,             -- which *_raw table to join back to for full drill-down
    raw_id INTEGER NOT NULL,
    embedding_text TEXT,                 -- texto embutido pelo motor de busca por IA (ver src/embeddings.py) -- mantido/religavel, nao usado no caminho padrao
    search_document TEXT,                -- texto completo normalizado + sinonimos/taxonomia (legivel, para depuracao/exportacao) -- ver src/search_fts.py
    search_taxonomia_termos TEXT,        -- so os sinonimos/taxonomia (ver src/search_taxonomy.py) -- usado a parte na hora de montar o search_vector com peso por campo
    search_vector TSVECTOR               -- tsvector (portugues, sem acento) COM PESO POR CAMPO (identificacao > setor/segmento > instrumento > texto livre) -- motor de busca padrao, sem IA
);

CREATE INDEX IF NOT EXISTS idx_bndes_raw_hash ON bndes_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_finep_direto_hash ON finep_credito_direto_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_finep_descentralizado_hash ON finep_credito_descentralizado_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_finep_nao_aprovados_hash ON finep_nao_aprovados_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_operations_raw ON operations(raw_table, raw_id);
CREATE INDEX IF NOT EXISTS idx_operations_setor_origem ON operations(setor_origem);
CREATE INDEX IF NOT EXISTS idx_operations_search_vector ON operations USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_operations_cliente_trgm ON operations USING GIN(cliente gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_operations_segmento_trgm ON operations USING GIN(segmento gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_operations_setor ON operations(setor_bndes);
CREATE INDEX IF NOT EXISTS idx_operations_segmento ON operations(segmento);
CREATE INDEX IF NOT EXISTS idx_operations_agencia ON operations(agencia);
CREATE INDEX IF NOT EXISTS idx_operations_ano ON operations(ano);
CREATE INDEX IF NOT EXISTS idx_operations_uf ON operations(uf);
CREATE INDEX IF NOT EXISTS idx_operations_cnpj ON operations(cnpj);

-- ============ Correcoes manuais (enriquecimento de transacoes) ============
-- Sobrescreve, campo a campo, uma classificacao automatica de uma operacao especifica
-- (ver item 3.3 do pedido: "Correcoes manuais aprovadas devem prevalecer sobre
-- enriquecimentos automaticos futuros"). Nunca apaga o historico (ativa=FALSE em vez
-- de DELETE, se uma correcao for desfeita) -- auditavel.
CREATE TABLE IF NOT EXISTS operations_correcoes_manuais (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation_id INTEGER NOT NULL,
    campo TEXT NOT NULL,              -- 'setor_bndes' | 'subsetor_bndes' | 'segmento'
    valor_anterior TEXT,
    valor_novo TEXT NOT NULL,
    usuario TEXT,
    criado_em TEXT NOT NULL,
    ativa BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_correcoes_operation_id ON operations_correcoes_manuais(operation_id);

-- ============ Refresh log / status ============
CREATE TABLE IF NOT EXISTS refresh_log (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    total_editais INTEGER,
    abertos INTEGER,
    status TEXT,
    detalhe TEXT
);

-- ============ Linhas Incentivadas (BNDES, FINEP, Desenvolve SP, BNB) ============
-- Catalogo de LINHAS/PROGRAMAS DE CREDITO (diferente de editais_raw, que sao
-- CHAMADAS PUBLICAS com prazo -- uma linha e uma condicao de credito permanente,
-- oferecida em fluxo continuo). Atualizado por processo LOCAL (ver
-- src/linhas_incentivadas.py) a partir de fontes oficiais -- o site hospedado so
-- consulta esta tabela, nunca acessa os sites das instituicoes em tempo real.
-- Campo nao informado pela fonte oficial fica como 'Nao informado pela fonte',
-- nunca inferido/inventado (ver origem_dado).
CREATE TABLE IF NOT EXISTS linhas_incentivadas (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instituicao TEXT NOT NULL,             -- 'BNDES' | 'FINEP' | 'Desenvolve SP' | 'BNB'
    nome_oficial TEXT NOT NULL,
    nome_simplificado TEXT,
    sigla TEXT,
    status TEXT,                           -- 'aberta' | 'encerrada' | 'Nao informado pela fonte'
    descricao_resumida TEXT,
    descricao_completa TEXT,
    modalidade TEXT,                       -- 'Direta' | 'Indireta' | 'Nao informado pela fonte'
    tipo_apoio TEXT,
    setores_elegiveis TEXT,
    setores_nao_elegiveis TEXT,
    porte_elegivel TEXT,
    faixa_receita TEXT,
    regiao_elegivel TEXT,
    destinacao TEXT,
    itens_financiaveis TEXT,
    itens_nao_financiaveis TEXT,
    valor_minimo REAL,
    valor_maximo REAL,
    percentual_financiavel TEXT,
    contrapartida TEXT,
    taxa_completa TEXT,
    indexador TEXT,
    spread TEXT,
    prazo_total TEXT,
    carencia TEXT,
    amortizacao TEXT,
    garantias TEXT,
    restricoes TEXT,
    criterios_elegibilidade TEXT,
    agente_financeiro TEXT,
    canal_contratacao TEXT,
    prazo_inscricao TEXT,
    fluxo TEXT,                            -- 'continuo' | 'edital'
    documentos_necessarios TEXT,
    url_oficial TEXT NOT NULL,
    data_vigencia TEXT,
    data_captura TEXT NOT NULL,
    data_atualizacao TEXT,
    trecho_fonte TEXT,                     -- trecho/referencia da pagina oficial que sustenta os dados capturados
    origem_dado TEXT NOT NULL,             -- 'raspagem_automatica' | 'curadoria_manual_verificada' -- nunca 'estimado'/'inventado'
    origem_raw_id INTEGER,                 -- se derivada de editais_raw (FINEP), o id original la
    -- Enriquecimento (taxonomia/sinonimos, ver src/linhas_incentivadas.py)
    setor_padronizado TEXT,
    subsetor_padronizado TEXT,
    cnaes_relacionados TEXT,
    porte_padronizado TEXT,
    destinacao_padronizada TEXT,
    tecnologias_relacionadas TEXT,
    temas_inovacao TEXT,
    temas_sustentabilidade TEXT,
    sinonimos_termos TEXT,
    search_document TEXT,
    search_vector TSVECTOR
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_linhas_natural_key ON linhas_incentivadas(instituicao, nome_oficial, url_oficial);
CREATE INDEX IF NOT EXISTS idx_linhas_instituicao ON linhas_incentivadas(instituicao);
CREATE INDEX IF NOT EXISTS idx_linhas_status ON linhas_incentivadas(status);
CREATE INDEX IF NOT EXISTS idx_linhas_setor ON linhas_incentivadas(setor_padronizado);
CREATE INDEX IF NOT EXISTS idx_linhas_search_vector ON linhas_incentivadas USING GIN(search_vector);

-- ============ Transacoes Salvas (favoritos de operacao + historico de busca por
-- usuario, aba propria da SPA) ============
-- Depende de contas reais (tabela `admin_usuarios`, criada so por
-- webapp/admin/seed.py -- ver CLAUDE.md, secao "Painel de Admin") para saber DE QUEM
-- e cada favorito/busca. Seguindo a MESMA segregacao ja documentada la (nenhuma
-- tabela do dominio "operations" ganha uma FK de verdade pro dominio do painel de
-- admin, nem o contrario -- ver tambem operations_correcoes_manuais.usuario, que e
-- TEXT solto, sem FK), usuario_id aqui e so um INTEGER (sem REFERENCES
-- admin_usuarios): uma FK de verdade quebraria o init_db() do pipeline semanal
-- (GitHub Actions, src/refresh.py) em qualquer ambiente onde admin_usuarios ainda
-- nao existe (seed.py nunca rodado). A validade do usuario_id e' garantida pelo
-- backend -- webapp/main.py so grava/le aqui depois de confirmar uma sessao valida
-- (ver _exigir_usuario_logado).
CREATE TABLE IF NOT EXISTS usuario_operacoes_salvas (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    operation_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    nota TEXT,
    criado_em TEXT NOT NULL,
    UNIQUE (usuario_id, operation_id)
);
CREATE INDEX IF NOT EXISTS idx_usuario_operacoes_salvas_usuario ON usuario_operacoes_salvas(usuario_id, criado_em DESC);

-- Historico de busca por usuario, gravado no SERVIDOR -- ate 2026-09 isso era so
-- localStorage (nunca ia pro servidor, decisao deliberada enquanto nao havia conta
-- de verdade, ver busca.js/CLAUDE.md). Agora que existem contas reais, todo usuario
-- LOGADO tambem grava aqui a cada busca; localStorage continua existindo em paralelo
-- so como fallback (ver busca.js) pra quando ninguem estiver logado. `fixada`: uma
-- busca pode ser fixada no topo do historico (nao so re-executada) -- ver
-- webapp/salvos.py::registrar_busca_historico (faz upsert por texto da query, entao
-- pesquisar a MESMA query de novo so atualiza criado_em em vez de duplicar linha).
CREATE TABLE IF NOT EXISTS usuario_busca_historico (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    fixada BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usuario_busca_historico_usuario ON usuario_busca_historico(usuario_id, criado_em DESC);

-- ============ Radar de Credito Primario: staging CVM "Ofertas Publicas de
-- Distribuicao" (ver src/download_cvm.py, src/parse_cvm.py, CLAUDE.md secao propria)
-- ============ Staging, quase 1:1 com as colunas oficiais do CSV da CVM -- so as
-- linhas de INSTRUMENTOS DE DIVIDA (debenture/CRI/CRA/nota promissoria-comercial/
-- letra financeira/CDCA/CCB), filtradas em parse_cvm.py. Deliberadamente SEM as
-- ~30 colunas de composicao de investidores do CSV oficial (Nr_Pessoa_Fisica,
-- Qtd_Fundos_Investimento etc.) -- ver comentario em parse_cvm.py::CVM_COLUMNS.
-- row_hash: mesmo padrao de bndes_raw/finep_*_raw (ver incremental.py) -- o dataset
-- da CVM tambem e republicado por inteiro a cada atualizacao (diaria), e
-- numero_registro_oferta NAO serve como chave natural sozinha (75.8% das linhas de
-- divida nao tem esse campo preenchido -- ofertas com dispensa de registro).
CREATE TABLE IF NOT EXISTS cvm_oferta_distribuicao_raw (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    row_hash TEXT,
    numero_processo TEXT,
    numero_registro_oferta TEXT,
    tipo_oferta TEXT,
    tipo_componente_oferta_mista TEXT,
    tipo_ativo TEXT,
    cnpj_emissor TEXT,
    nome_emissor TEXT,
    cnpj_lider TEXT,
    nome_lider TEXT,
    nome_vendedor TEXT,
    cnpj_ofertante TEXT,
    nome_ofertante TEXT,
    rito_oferta TEXT,
    modalidade_oferta TEXT,
    modalidade_registro TEXT,
    modalidade_dispensa_registro TEXT,
    data_abertura_processo TEXT,
    data_protocolo TEXT,
    data_dispensa_oferta TEXT,
    data_registro_oferta TEXT,
    data_inicio_oferta TEXT,
    data_encerramento_oferta TEXT,
    emissao TEXT,
    classe_ativo TEXT,
    serie TEXT,
    especie_ativo TEXT,
    forma_ativo TEXT,
    data_emissao TEXT,
    data_vencimento TEXT,
    quantidade_sem_lote_suplementar REAL,
    quantidade_no_lote_suplementar REAL,
    quantidade_total REAL,
    preco_unitario REAL,
    valor_total REAL,
    oferta_inicial TEXT,
    oferta_incentivo_fiscal TEXT,
    oferta_regime_fiduciario TEXT,
    atualizacao_monetaria TEXT,
    juros TEXT,
    tipo_societario_emissor TEXT,
    tipo_fundo_investimento TEXT,
    ultimo_comunicado TEXT,
    data_comunicado TEXT
);
CREATE INDEX IF NOT EXISTS idx_cvm_oferta_distribuicao_hash ON cvm_oferta_distribuicao_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_cvm_oferta_distribuicao_cnpj_emissor ON cvm_oferta_distribuicao_raw(cnpj_emissor);

-- ============ Radar de Credito Primario: staging CVM "oferta_resolucao_160.csv"
-- ============ SEGUNDO CSV do MESMO zip de cvm_oferta_distribuicao_raw acima --
-- achado real do coordenador (2026-09-16), DEPOIS que o pipeline inicial ja tinha
-- rodado: schema DIFERENTE, foco no rito automatico (Resolucao CVM 160, sucessora
-- da ICVM 400/476 para a maior parte das emissoes modernas) -- ver
-- src/download_cvm.py, src/parse_cvm_resolucao160.py, CLAUDE.md secao propria.
-- Cobre EXATAMENTE 2023-2026 (o rito automatico so existe desde entao) -- e o que
-- resolve o "radar cego pra atividade recente" (so 7 linhas de
-- cvm_oferta_distribuicao_raw caem nesse periodo).
-- Deliberadamente SEM as MESMAS ~24 colunas de composicao de investidores do CSV
-- oficial (Num_Invest_Pessoa_Natural, Qtde_VM_Fundos_Investimento etc.) -- mesmo
-- criterio de exclusao usado em cvm_oferta_distribuicao_raw (ver
-- parse_cvm_resolucao160.py::R160_COLUMNS). Diferente do arquivo principal, NAO tem
-- Data_Vencimento/Juros/Atualizacao_Monetaria (schema focado em ESTRUTURA da oferta,
-- nao em remuneracao do titulo) -- confirmado contra as 71 colunas oficiais.
-- row_hash: MESMO padrao de cvm_oferta_distribuicao_raw -- Numero_Requerimento
-- CONFIRMADO unico e nao-nulo nas 14.493 linhas do snapshot de 2026-09-16
-- (diferente de numero_registro_oferta no arquivo principal, que e nulo em 76%
-- das linhas) -- mas mantido como coluna INFORMATIVA, nao como chave de upsert,
-- pela mesma razao de consistencia com o resto do pipeline (dataset republicado
-- por inteiro a cada atualizacao, nao incremental na origem).
CREATE TABLE IF NOT EXISTS cvm_oferta_resolucao_160_raw (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    row_hash TEXT,
    numero_requerimento TEXT,            -- CONFIRMADO unico/nao-nulo neste dataset -- so informativo aqui, ver comentario acima
    rito_requerimento TEXT,              -- sempre 'Automatico' neste dataset (a propria razao dele existir)
    numero_processo TEXT,
    data_requerimento TEXT,              -- unico campo de data SEM nenhum nulo (0 de 14.493) -- base do fallback de data_referencia
    data_registro TEXT,
    data_encerramento TEXT,
    status_requerimento TEXT,            -- 'Oferta Encerrada'|'Registro Concedido'|'Registro Caducado'|'Oferta Revogada'|'Aguardando Bookbuilding'|'Requerimento Expirado'|'Oferta Suspensa' -- ver unify_primario.py sobre como isso e tratado (nao filtrado, so exposto)
    valor_mobiliario TEXT,               -- equivalente a Tipo_Ativo do arquivo principal -- strings DIFERENTES pro mesmo instrumento (ex: "Debêntures" aqui vs "DEBÊNTURES SIMPLES" no outro) -- ver unify_primario.py::INSTRUMENTO_PADRONIZADO_MAP
    tipo_requerimento TEXT,               -- granularidade de publico-alvo/bookbuilding (ex: "OPD Aut Profissional - sem bookbuilding") -- informativo
    bookbuilding TEXT,
    cnpj_emissor TEXT,
    nome_emissor TEXT,
    cnpj_lider TEXT,
    nome_lider TEXT,
    grupo_coordenador TEXT,
    tipo_oferta TEXT,                    -- Primaria | Secundaria | Mista
    emissao TEXT,
    qtde_total_registrada REAL,
    valor_total_registrado REAL,
    oferta_inicial TEXT,
    oferta_vasos_comunicantes TEXT,
    publico_alvo TEXT,
    reabertura_serie TEXT,
    titulo_classificado_como_sustentavel TEXT,
    titulo_padronizado TEXT,
    destinacao_recursos TEXT,
    data_deliberacao_aprovou_oferta TEXT,
    mercado_negociacao TEXT,
    tipo_lastro TEXT,                    -- 'Pulverizado' | 'Concentrado' (relevante p/ CRI/CRA)
    regime_fiduciario TEXT,
    ativos_alvo TEXT,
    descricao_garantias TEXT,
    descricao_lastro TEXT,
    identificacao_devedores_coobrigados TEXT,
    possibilidade_revolvencia TEXT,
    fidc_nao_padronizado TEXT,
    titulo_incentivado TEXT,             -- Lei 12.431/11 -- equivalente a Oferta_Incentivo_Fiscal do arquivo principal
    regime_distribuicao TEXT,
    tipo_societario TEXT,
    administrador TEXT,
    gestor TEXT,
    agente_fiduciario TEXT,
    escriturador TEXT,
    custodiante TEXT,
    avaliador_risco TEXT,
    processo_sei TEXT,
    endereco_emissor_rede_mundial_computadores TEXT
);
CREATE INDEX IF NOT EXISTS idx_cvm_oferta_resolucao_160_hash ON cvm_oferta_resolucao_160_raw(row_hash);
CREATE INDEX IF NOT EXISTS idx_cvm_oferta_resolucao_160_cnpj_emissor ON cvm_oferta_resolucao_160_raw(cnpj_emissor);

-- ============ Radar de Credito Primario: tabela unificada `operations_primario`
-- ============ Mesmo espirito de `operations` (BNDES+FINEP): so insere para
-- raw_id novos (ver src/unify_primario.py::build_operations_primario, dedup por
-- raw_table+raw_id, nunca por numero_registro_oferta -- ver comentario em
-- parse_cvm.py sobre por que esse campo nao serve como chave). setor_emissor/
-- subsetor_emissor/uf_emissor/municipio_emissor vem do MESMO cache cnpj_cnae
-- usado para enriquecer a FINEP (ver CLAUDE.md, secao propria, sobre a extensao
-- de cnpj_cnae com uf/municipio feita para viabilizar isso).
CREATE TABLE IF NOT EXISTS operations_primario (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrumento TEXT,                    -- Tipo_Ativo cru da CVM
    instrumento_padronizado TEXT,        -- 'Debênture'|'CRI'|'CRA'|'Nota Comercial'|'Letra Financeira'|'CDCA'|'CCB'|'Outro'
    numero_processo TEXT,
    numero_registro_oferta TEXT,         -- INFORMATIVO -- nulo em ~76% das linhas (dispensa de registro), nunca usado como chave
    tipo_oferta TEXT,                    -- Primaria | Secundaria
    rito_oferta TEXT,
    modalidade_oferta TEXT,
    cnpj_emissor TEXT,
    nome_emissor TEXT,
    razao_social_oficial_emissor TEXT,   -- cnpj_cnae.razao_social_oficial (RFB)
    setor_emissor TEXT,                  -- taxonomia BNDES (mesma de `operations`), via cnpj_cnae
    subsetor_emissor TEXT,
    segmento_emissor TEXT,               -- cnae_descricao (granularidade fina)
    porte_emissor TEXT,
    natureza_juridica_emissor TEXT,
    uf_emissor TEXT,
    municipio_emissor TEXT,
    cnpj_lider TEXT,                     -- coordenador lider/underwriter da oferta
    nome_lider TEXT,
    emissao TEXT,
    serie TEXT,
    classe_ativo TEXT,
    especie_ativo TEXT,
    forma_ativo TEXT,
    data_emissao TEXT,
    data_vencimento TEXT,
    data_registro_oferta TEXT,
    data_encerramento_oferta TEXT,
    data_referencia TEXT,                -- melhor data disponivel p/ ordenacao/serie temporal -- ver unify_primario.py
    ano INTEGER,
    trimestre INTEGER,
    prazo_dias INTEGER,                  -- data_vencimento - data_emissao, EXATO (nao melhor-esforco -- so NULL quando falta uma das duas datas ou a subtracao da negativa/zero, ver CLAUDE.md)
    prazo_meses REAL,                    -- prazo_dias / 30.44 (media de dias/mes), 1 casa decimal -- so p/ comparar com prazo_amortizacao_meses de `operations` (BNDES/FINEP), mesma unidade
    valor_total REAL,
    quantidade_total REAL,
    preco_unitario REAL,
    incentivada BOOLEAN,                 -- Oferta_Incentivo_Fiscal = 'S' (Lei 12.431/11)
    regime_fiduciario BOOLEAN,           -- Oferta_Regime_Fiduciario = 'S'
    oferta_inicial BOOLEAN,              -- sempre NULL no escopo de divida (campo e especifico de IPO de acoes) -- mantido por completude/fidelidade ao dado oficial
    indexador_padronizado TEXT,          -- 'CDI'|'IPCA+'|'SELIC'|'Prefixado'|'Outro'|NULL -- melhor esforco, ver CLAUDE.md (NUNCA inventado)
    taxa_valor REAL,                     -- numero extraido de juros/atualizacao_monetaria (ex: 2.5 de "CDI + 2,50% a.a.", 12.5 de "12,5% a.a.") -- melhor esforco, NULL se nao extraivel com confianca (NUNCA inventado)
    taxa_tipo TEXT,                      -- 'spread' (aditivo, ex: "+2,5%" sobre o indexador) | 'percentual_indexador' (multiplicativo, ex: "108% do CDI") | 'taxa_fixa' (prefixado puro) | NULL
    juros TEXT,                          -- texto cru da CVM (fonte do indexador_padronizado/taxa_valor -- SEMPRE mantido, nunca escondido atras do campo extraido)
    atualizacao_monetaria TEXT,          -- texto cru da CVM (fonte do indexador_padronizado/taxa_valor -- SEMPRE mantido, nunca escondido atras do campo extraido)
    -- Colunas abaixo: SO existem na fonte oferta_resolucao_160.csv (ver
    -- src/parse_cvm_resolucao160.py/CLAUDE.md) -- sempre NULL para linhas com
    -- raw_table = 'cvm_oferta_distribuicao_raw' (o arquivo principal nao tem
    -- equivalente a nenhuma delas).
    numero_requerimento TEXT,            -- numero de rastreio do requerimento no rito automatico (CONFIRMADO unico -- ver staging) -- NAO confundir com numero_registro_oferta (namespace diferente, arquivo principal)
    status_requerimento TEXT,            -- 'Oferta Encerrada'|'Registro Concedido'|... -- ver unify_primario.py sobre a decisao de manter TODAS as linhas mas expor este campo (nunca filtrado silenciosamente)
    tipo_lastro TEXT,                    -- 'Pulverizado'|'Concentrado' -- relevante p/ CRI/CRA
    agente_fiduciario TEXT,
    custodiante TEXT,
    descricao_garantias TEXT,
    raw_table TEXT NOT NULL,
    raw_id INTEGER NOT NULL,
    -- Motor de busca sem IA (ver src/search_fts_primario.py e src/unify_primario.py::
    -- _atualizar_busca_primario) -- MESMO padrao de operations.search_document/search_vector,
    -- mais simples (sem search_taxonomia_termos: nao ha dicionario de sinonimos curado
    -- para o emissor da CVM, ver CLAUDE.md). Populado por _atualizar_busca_primario, nunca
    -- no INSERT em si (diferente de `operations`) -- ver comentario na propria funcao.
    search_document TEXT,
    search_vector TSVECTOR
);
CREATE INDEX IF NOT EXISTS idx_operations_primario_raw ON operations_primario(raw_table, raw_id);
CREATE INDEX IF NOT EXISTS idx_operations_primario_cnpj_emissor ON operations_primario(cnpj_emissor);
CREATE INDEX IF NOT EXISTS idx_operations_primario_setor ON operations_primario(setor_emissor);
CREATE INDEX IF NOT EXISTS idx_operations_primario_uf ON operations_primario(uf_emissor);
CREATE INDEX IF NOT EXISTS idx_operations_primario_ano ON operations_primario(ano);
CREATE INDEX IF NOT EXISTS idx_operations_primario_data_referencia ON operations_primario(data_referencia);
CREATE INDEX IF NOT EXISTS idx_operations_primario_instrumento ON operations_primario(instrumento_padronizado);
CREATE INDEX IF NOT EXISTS idx_operations_primario_search_vector ON operations_primario USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_operations_primario_nome_trgm ON operations_primario USING GIN(nome_emissor gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_operations_primario_segmento_trgm ON operations_primario USING GIN(segmento_emissor gin_trgm_ops);

CREATE TABLE IF NOT EXISTS refresh_primario_log (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    cvm_raw_rows INTEGER,
    operations_primario_rows INTEGER,
    emissores_pendentes INTEGER,
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
    # Sub-linha real do BNDES (ver comentario no CREATE TABLE operations acima) --
    # so passou a ser mapeada em unify.py depois que a tabela ja existia em producao.
    ("operations", "instrumento_financeiro", "TEXT"),
    # Motor de busca sem IA (tsvector/unaccent/pg_trgm, ver src/search_fts.py) --
    # adicionadas depois que `operations` ja existia em producao.
    ("operations", "search_document", "TEXT"),
    ("operations", "search_taxonomia_termos", "TEXT"),
    ("operations", "search_vector", "TSVECTOR"),
    # Identificacao da empresa (Empresas.zip da RFB, ver enrich_empresas() em
    # enrich_cnae.py) -- adicionadas depois que `cnpj_cnae` ja existia em producao.
    ("cnpj_cnae", "razao_social_oficial", "TEXT"),
    ("cnpj_cnae", "natureza_juridica", "TEXT"),
    ("cnpj_cnae", "porte_empresa", "TEXT"),
    ("cnpj_cnae", "capital_social", "REAL"),
    # Identificacao da empresa de volta em `operations` (antes so aparecia no detalhe
    # de uma operacao, nunca virava dado filtravel/buscavel -- ver unify.py::
    # _load_cnae_lookup/_build_*_ops). porte_cliente ja existia desde a criacao da
    # tabela (so preenchido pra BNDES ate aqui); razao_social_oficial e coluna nova.
    #
    # natureza_cliente: BUG REAL encontrado rodando esta migracao ao vivo -- a coluna
    # ja estava no texto do CREATE TABLE (SCHEMA, mais acima neste arquivo) ha tempo,
    # mas nunca tinha sido adicionada aqui em MIGRACOES_COLUNAS -- como CREATE TABLE IF
    # NOT EXISTS e no-op numa tabela ja existente, a coluna simplesmente nunca existiu
    # de verdade em producao (confirmado via information_schema.columns: False). O
    # backfill de razao_social_oficial abaixo falhou na primeira tentativa por causa
    # disso (UndefinedColumn), sem gravar nada (erro pega antes de qualquer escrita).
    # PRECISA vir ANTES de razao_social_oficial nesta lista -- a ordem da lista e a
    # ordem de execucao, e o backfill de razao_social_oficial referencia
    # natureza_cliente.
    ("operations", "natureza_cliente", "TEXT"),
    ("operations", "razao_social_oficial", "TEXT"),
    # Radar de Credito Primario (CVM): emissores de debenture/CRI/CRA/etc precisam
    # de UF/municipio para os filtros geograficos de operations_primario, mas
    # cnpj_cnae nunca guardou esses campos ate aqui (BNDES/FINEP ja trazem UF/
    # municipio direto na propria planilha de origem, nunca precisaram disso via
    # CNPJ). Preenchido so por enrich_cnae.py::enrich_pendentes_via_api (BrasilAPI
    # ja devolve "uf"/"municipio" na mesma chamada, so nao eram gravados) -- o job
    # mensal em lote (enrich(), que escaneia Estabelecimentos*.zip da RFB) NAO foi
    # estendido para isso (ESTAB_COLS/KEEP_COLS tem uf/municipio disponiveis no
    # zip mas o parsing em lote so extrai o que ja usava; ver CLAUDE.md). Sem
    # backfill retroativo: linhas de cnpj_cnae ja existentes (BNDES/FINEP) ficam
    # com uf/municipio NULL para sempre, o que e aceitavel -- ninguem consome
    # esses dois campos a partir de cnpj_cnae hoje exceto o unify_primario.py novo.
    ("cnpj_cnae", "uf", "TEXT"),
    ("cnpj_cnae", "municipio", "TEXT"),
    # taxa_valor/taxa_tipo adicionadas a operations_primario DEPOIS da tabela ja
    # ter sido criada em producao pela primeira rodada do pipeline CVM (pedido do
    # usuario, 2026-09-16, chegou no meio desta mesma sessao) -- ver CLAUDE.md.
    # unify_primario.py::build_operations_primario() so preenche estes campos para
    # linhas inseridas DEPOIS desta migracao (pipeline incremental, nao reprocessa
    # raw_id ja unificado) -- por isso o backfill explicito abaixo, cobrindo as
    # linhas ja gravadas na primeira rodada (mesmo padrao ja usado por
    # instrumento_financeiro/razao_social_oficial em `operations`, ver acima).
    ("operations_primario", "taxa_valor", "REAL"),
    ("operations_primario", "taxa_tipo", "TEXT"),
    # prazo_dias/prazo_meses: pedido adicional do usuario na MESMA sessao (data
    # exata, data_vencimento - data_emissao -- ver CLAUDE.md), chegou logo depois
    # de taxa_valor/taxa_tipo acima -- mesmo motivo de precisar de ALTER TABLE
    # explicito (tabela ja criada em producao antes deste pedido).
    ("operations_primario", "prazo_dias", "INTEGER"),
    ("operations_primario", "prazo_meses", "REAL"),
    # Motor de busca sem IA do Radar de Credito Primario (ver src/search_fts_primario.py) --
    # adicionadas DEPOIS que operations_primario ja tinha as 12.232 linhas da primeira rodada
    # do pipeline CVM em producao (mesmo motivo de taxa_valor/prazo_dias acima: coluna nova
    # precisa de ALTER TABLE explicito numa tabela ja existente). Backfill explicito via
    # unify_primario.py::backfill_busca_primario() (rodado manualmente uma vez, mesmo padrao
    # de instrumento_financeiro/razao_social_oficial -- ver comentario acima -- so que aqui
    # SEM gatilho automatico dentro desta funcao: o volume e pequeno o suficiente (12 mil
    # linhas) para rodar como um comando avulso em vez de acoplar a _aplicar_migracoes).
    ("operations_primario", "search_document", "TEXT"),
    ("operations_primario", "search_vector", "TSVECTOR"),
    # Integracao do SEGUNDO CSV do zip da CVM (oferta_resolucao_160.csv, rito
    # automatico -- ver src/parse_cvm_resolucao160.py e CLAUDE.md), achado do
    # coordenador (2026-09-16) DEPOIS que operations_primario ja existia em
    # producao com as linhas do arquivo principal -- por isso ALTER TABLE
    # explicito, mesmo padrao das colunas acima. Todas NULL para linhas com
    # raw_table = 'cvm_oferta_distribuicao_raw' (o arquivo principal nao tem
    # equivalente a nenhuma destas).
    ("operations_primario", "numero_requerimento", "TEXT"),
    ("operations_primario", "status_requerimento", "TEXT"),
    ("operations_primario", "tipo_lastro", "TEXT"),
    ("operations_primario", "agente_fiduciario", "TEXT"),
    ("operations_primario", "custodiante", "TEXT"),
    ("operations_primario", "descricao_garantias", "TEXT"),
]


# Mesmo padrao de scripts/backfill_search_taxonomia.py -- o Aiven free tier ja
# derrubou conexao/transacao de verdade no meio de escritas longas (ReadOnlySqlTransaction
# durante backup automatico, AdminShutdown durante manutencao/reinicio), por janelas que
# ja chegaram a passar de 90s. Orcamento de retry BEM maior que erro de lock comum, e
# com RECONEXAO de verdade (a conexao antiga nao volta a funcionar sozinha).
_MAX_TENTATIVAS_CONEXAO_MIGRACAO = 10
_ESPERA_CONEXAO_MIGRACAO_S = 30.0
_ERROS_CONEXAO_MIGRACAO = (psycopg.errors.ReadOnlySqlTransaction, psycopg.OperationalError)


def _executar_com_retry_conexao(conn, sql, params=None):
    """Roda uma unica instrucao (DDL ou um UPDATE de backfill -- de uma tabela inteira
    ou de UM LOTE, ver _executar_update_em_lotes) com retry-e-reconexao se a conexao
    cair no meio, e COMMITA na hora (nao acumula com o resto da migracao numa
    transacao so).

    BUG REAL encontrado ao vivo rodando esta migracao em producao: um AdminShutdown
    (reinicio/manutencao automatica do Aiven, ja documentado como recorrente) derrubou
    a conexao DEPOIS do ALTER TABLE (natureza_cliente, razao_social_oficial) mas ANTES
    do commit -- a reconexao seguinte comecava uma sessao nova, sem essas colunas (o
    ALTER TABLE nunca tinha sido commitado), e so o UPDATE de backfill era reexecutado,
    falhando com UndefinedColumn contra uma coluna que "deveria" existir mas nunca foi
    persistida. Commitar cada instrucao (ALTER TABLE E o backfill) assim que ela
    termina evita perder trabalho que uma reconexao nao vai refazer sozinha.

    SEGUNDO BUG REAL encontrado ao vivo (mesma sessao, depois deste fix): mesmo um
    UPDATE monolitico contra as ~58 mil linhas de `operations`, com commit imediato,
    ainda caiu 2 vezes seguidas em AdminShutdown NO MEIO da propria transacao -- e
    CADA tentativa fracassada deixava dezenas de milhares de tuplas mortas (bloat)
    pra tras, ao ponto de contribuir pra um esgotamento real de disco do plano free
    do Aiven (1GB), que so foi resolvido rodando VACUUM manualmente. Dai
    _executar_update_em_lotes(): quebrar em pedacos pequenos (commit por lote) limita
    o bloat de uma falha a um pedaco pequeno da tabela, e cada transacao curta tem
    bem menos chance de atravessar uma das janelas de instabilidade do Aiven."""
    tentativas = 0
    while True:
        try:
            conn.execute(sql, params)
            conn.commit()
            return conn
        except _ERROS_CONEXAO_MIGRACAO as e:
            tentativas += 1
            if tentativas >= _MAX_TENTATIVAS_CONEXAO_MIGRACAO:
                raise
            print(
                f"  (migracao: retry conexao {tentativas}/{_MAX_TENTATIVAS_CONEXAO_MIGRACAO} "
                f"apos {type(e).__name__}, aguardando {_ESPERA_CONEXAO_MIGRACAO_S:.0f}s...)"
            )
            time.sleep(_ESPERA_CONEXAO_MIGRACAO_S)
            for tentativa_reconexao in range(1, _MAX_TENTATIVAS_CONEXAO_MIGRACAO + 1):
                try:
                    conn = get_connection()
                    break
                except psycopg.OperationalError:
                    if tentativa_reconexao == _MAX_TENTATIVAS_CONEXAO_MIGRACAO:
                        raise
                    time.sleep(_ESPERA_CONEXAO_MIGRACAO_S)


def _executar_update_em_lotes(conn, sql_base, tamanho_lote=5000):
    """Roda um UPDATE contra `operations` em lotes por FAIXA DE ID (cada lote com
    commit e retry-e-reconexao proprios, ver _executar_com_retry_conexao) -- se um
    lote cair, so aquele precisa ser refeito, e o bloat de uma tentativa fracassada
    fica contido a um pedaco pequeno da tabela em vez da tabela inteira (ver
    docstring de _executar_com_retry_conexao pro incidente real que motivou isso).
    `sql_base` precisa terminar em "AND o.id BETWEEN ? AND ?" -- o range de cada lote
    e passado como parametro aqui, nunca formatado direto na string."""
    min_id, max_id = conn.execute("SELECT MIN(id), MAX(id) FROM operations").fetchone()
    if min_id is None:
        return conn
    inicio = min_id
    while inicio <= max_id:
        fim = min(inicio + tamanho_lote - 1, max_id)
        conn = _executar_com_retry_conexao(conn, sql_base, (inicio, fim))
        print(f"  (migracao: lote id {inicio}-{fim} de {max_id} concluido)")
        inicio = fim + 1
    return conn


def _aplicar_migracoes(conn):
    colunas_existentes = {}
    for tabela, coluna, tipo in MIGRACOES_COLUNAS:
        if tabela not in colunas_existentes:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                (tabela,),
            ).fetchall()
            colunas_existentes[tabela] = {r[0] for r in rows}
        if colunas_existentes[tabela] and coluna not in colunas_existentes[tabela]:
            conn = _executar_com_retry_conexao(conn, f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
            colunas_existentes[tabela].add(coluna)
            if (tabela, coluna) == ("operations", "instrumento_financeiro"):
                # Backfill unico: unify.py so preenche esta coluna para linhas
                # INSERIDAS depois desta migracao (pipeline e incremental, nao
                # reprocessa raw_id ja unificado) -- sem isso, todo o historico de
                # BNDES ja carregado ficaria com instrumento_financeiro NULL para
                # sempre. So roda quando a coluna acabou de ser criada (nao a cada
                # init_db). Em LOTES (ver _executar_update_em_lotes) -- mesmo risco de
                # bloat/queda de conexao que o backfill de razao_social_oficial abaixo,
                # tratado com o mesmo padrao por consistencia (esta migracao especifica
                # ja rodou com sucesso nesta producao, mas o mesmo codigo roda em
                # qualquer deploy novo/banco recriado do zero).
                conn = _executar_update_em_lotes(
                    conn,
                    "UPDATE operations SET instrumento_financeiro = ("
                    "  SELECT b.instrumento_financeiro FROM bndes_raw b WHERE b.id = operations.raw_id"
                    ") WHERE raw_table = 'bndes_raw' AND id BETWEEN ? AND ?",
                )
            if (tabela, coluna) == ("operations", "razao_social_oficial"):
                # Backfill unico: da mesma forma que instrumento_financeiro acima, so
                # cobre o historico ja carregado ate aqui -- daqui pra frente,
                # unify.py::_build_*_ops ja preenche esses campos direto no insert.
                # COALESCE em porte_cliente: nunca sobrescreve o porte NATIVO do BNDES
                # (mais confiavel que a classificacao da Receita Federal), so preenche
                # onde esta NULL (hoje: 100% das operacoes da FINEP). Em LOTES (ver
                # _executar_update_em_lotes) -- um UPDATE monolitico contra as ~58 mil
                # linhas ja derrubou a conexao (AdminShutdown) 2 vezes seguidas em
                # producao, cada vez deixando dezenas de milhares de tuplas mortas.
                conn = _executar_update_em_lotes(
                    conn,
                    "UPDATE operations o SET "
                    "  porte_cliente = COALESCE(o.porte_cliente, c.porte_empresa), "
                    "  natureza_cliente = COALESCE(o.natureza_cliente, c.natureza_juridica), "
                    "  razao_social_oficial = c.razao_social_oficial "
                    "FROM cnpj_cnae c WHERE c.cnpj = o.cnpj AND ("
                    "  o.porte_cliente IS NULL OR o.natureza_cliente IS NULL OR c.razao_social_oficial IS NOT NULL"
                    ") AND o.id BETWEEN ? AND ?",
                )
    conn.commit()
    return conn


def init_db():
    conn = get_connection()
    try:
        # migracoes ANTES do executescript: em um banco ja existente, o SCHEMA tem
        # "CREATE TABLE IF NOT EXISTS" (nao-op se a tabela ja existe) mas tambem tem
        # "CREATE INDEX" sobre colunas novas (ex: row_hash) -- se a coluna so for
        # adicionada DEPOIS do executescript, o CREATE INDEX quebra achando que a
        # coluna nao existe. Rodar migracoes antes garante que colunas novas ja
        # existem quando os indices forem criados.
        conn = _aplicar_migracoes(conn)
        conn.execute(SCHEMA)
        conn.commit()
        # roda de novo: cobre o caso de banco novo (tabelas acabaram de ser criadas
        # agora pelo execute acima, entao a chamada anterior foi um no-op).
        conn = _aplicar_migracoes(conn)
    finally:
        conn.close()


def drop_rebuild_tables(conn):
    """Drop the tables that get a full reload on every refresh (keeps cnpj_cnae cache intact)."""
    for table in REBUILD_EACH_REFRESH:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(SCHEMA)
    conn.commit()


if __name__ == "__main__":
    init_db()
    print("Banco inicializado (Postgres/Supabase, ver DATABASE_URL).")
