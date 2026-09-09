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
    usada de novo antes da instancia reciclar) + max_size=3 (BEM mais conservador do
    que "metade do teto do provedor" pareceria sugerir): a Vercel pode escalar pra
    VARIAS instancias da function rodando ao mesmo tempo sob trafego concorrente, e
    CADA instancia tem seu PROPRIO pool (variavel global `_POOL` e por processo, nao
    compartilhada entre instancias) -- um max_size=8 com so 2 instancias concorrentes
    ja seriam 16 conexoes, estourando o limite de 15 do pooler em modo session da
    Supabase (bug real reproduzido em producao: EMAXCONNSESSION mesmo com o pool
    ligado). max_size=3 da margem pra ~5 instancias concorrentes ficarem dentro do
    teto de 15, ou ~6 dentro do teto de 20 do Aiven. FastAPI roda rotas sincronas
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
            database_url, min_size=0, max_size=3, open=True,
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
]


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
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
            colunas_existentes[tabela].add(coluna)
            if (tabela, coluna) == ("operations", "instrumento_financeiro"):
                # Backfill unico: unify.py so preenche esta coluna para linhas
                # INSERIDAS depois desta migracao (pipeline e incremental, nao
                # reprocessa raw_id ja unificado) -- sem isso, todo o historico de
                # BNDES ja carregado ficaria com instrumento_financeiro NULL para
                # sempre. So roda quando a coluna acabou de ser criada (nao a cada
                # init_db).
                conn.execute(
                    "UPDATE operations SET instrumento_financeiro = ("
                    "  SELECT b.instrumento_financeiro FROM bndes_raw b WHERE b.id = operations.raw_id"
                    ") WHERE raw_table = 'bndes_raw'"
                )
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
        conn.execute(SCHEMA)
        conn.commit()
        # roda de novo: cobre o caso de banco novo (tabelas acabaram de ser criadas
        # agora pelo execute acima, entao a chamada anterior foi um no-op).
        _aplicar_migracoes(conn)
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
