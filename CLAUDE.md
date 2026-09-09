# Radar de Crédito Incentivado — contexto para IAs futuras

Este arquivo existe para que qualquer assistente de IA (Claude ou outro) que abra este
repositório entenda rapidamente o que a plataforma faz, como está estruturada, e as decisões
não-óbvias que já foram tomadas — sem precisar reconstruir esse contexto do zero lendo commit
por commit. `README.md`/`DEPLOY.md`/`RESUME.md` também existem mas ficam desatualizados rápido
(são notas point-in-time); este arquivo é o que deve ser mantido mais preciso e atual.

**Data da última revisão a fundo deste arquivo: 2026-09-08.**

## O que é a plataforma

Site que acompanha operações de **crédito incentivado** contratadas por empresas brasileiras
junto a instituições de fomento — hoje BNDES e FINEP têm dados reais de transações (~58 mil
operações desde 2002); há também um catálogo separado de **linhas de crédito permanentes**
(produtos, não transações) do BNDES, FINEP, Desenvolve SP e BNB. Público-alvo: alguém
analisando o mercado de crédito incentivado brasileiro (ex: para prospecção, benchmarking,
inteligência de mercado) — não é uma ferramenta de originação/contratação de crédito.

100% online: front-end (SPA vanilla JS) + backend (FastAPI) + banco (Postgres/Supabase)
hospedados juntos na Vercel. Não existe mais "modo local" com banco separado (SQLite) — tanto
rodando localmente (`uvicorn`, para desenvolvimento) quanto em produção, o app fala com o MESMO
Postgres via `DATABASE_URL`.

## Stack e topologia de deploy

- **Backend**: FastAPI (`webapp/main.py`), rotas `/api/*`.
- **Frontend**: SPA vanilla JS sem framework/bundler, um único `webapp/static/index.html` com
  5 `<section class="view">` (uma por aba), troca de aba 100% client-side.
- **Banco**: Postgres no **Aiven** (migrado do Supabase em 2026-09-08 — Supabase bateu no
  limite de 500MB do plano gratuito; Aiven dá 1GB grátis, Postgres de verdade, real de
  verdade — confirmado suporte a `unaccent`/`pg_trgm`/`setweight`/`ts_rank_cd`/
  `websearch_to_tsquery`, as funções exatas que este projeto usa pra ranking de busca.
  CockroachDB foi considerado por ter 10GB grátis, mas DESCARTADO: não suporta
  `setweight`/`ts_rank_cd`/`websearch_to_tsquery`, exigiria reescrever o motor de busca
  inteiro). Acessado com `psycopg` (v3). Uma única variável de ambiente `DATABASE_URL` é
  usada tanto pelo backend quanto pelos scripts de pipeline (GitHub Actions) — ver
  `scripts/migrate_supabase_to_aiven.py` pra como a migração foi feita (COPY tabela por
  tabela, contagens conferidas, tudo bateu exato).
  **Atenção real sobre o Aiven free tier**: o serviço mostrou, nas primeiras horas depois
  de criado, janelas recorrentes de indisponibilidade — ora `ReadOnlySqlTransaction`
  (parece um backup/manutenção automática que bloqueia só escrita), ora `AdminShutdown`
  (derruba a conexão de vez, parece reinício automático). Confirmado ao vivo: uma janela
  dessas pode durar mais de 90 segundos. Qualquer script de escrita longa contra este
  banco precisa de retry-com-reconexão e um orçamento de espera de VÁRIOS MINUTOS, não
  segundos — ver `scripts/backfill_search_taxonomia.py` (`MAX_TENTATIVAS_CONEXAO=10`,
  `ESPERA_CONEXAO_S=30`, contador de tentativa SEPARADO do de erro de lock) como padrão
  de referência. A webapp em si já está protegida disso via o pool de conexões (ver
  "Coisas a saber antes de mexer" abaixo) — o risco descrito aqui é só pra scripts novos
  que abrem uma conexão e a mantêm por muito tempo.
- **Deploy**: Vercel. `vercel.json` define `outputDirectory: webapp/static` (front servido
  direto pela CDN) + rewrite de `/api/*` para `api/index.py` (function serverless Python que só
  faz `from webapp.main import app`). Ver `DEPLOY.md` para o passo a passo já feito.
- **Automação**: GitHub Actions (`.github/workflows/*.yml`), 3 workflows agendados (ver seção
  própria abaixo), todos usando o secret `DATABASE_URL`.
- **Local dev**: `uvicorn webapp.main:app` a partir da raiz do repo; `.env` na raiz fornece
  `DATABASE_URL` (via `python-dotenv`, carregado em `src/db.py`). Sem `SITE_PASSWORD` no `.env`
  local, o servidor local roda sem exigir login (login só é forçado quando `SITE_PASSWORD` está
  configurada, tipicamente só em produção).

## Modelo de dados (tabelas principais, ver schema completo em `src/db.py`)

- **`bndes_raw`**, **`finep_credito_direto_raw`**, **`finep_credito_descentralizado_raw`**:
  staging tables, uma linha por operação, quase cru da planilha/fonte oficial.
- **`operations`**: tabela UNIFICADA (schema comum BNDES+FINEP) que todo o dashboard/busca
  consulta. Campos-chave: `agencia` (BNDES/FINEP), `cliente`, `cnpj`, `setor_bndes`/
  `subsetor_bndes`/`segmento` (taxonomia de 3 níveis — ver seção "Setor/Subsetor/Segmento"
  abaixo), `valor_contratado`, `data_contratacao`, `uf`, `municipio`, `setor_origem` (`nativo` =
  BNDES, já vem com setor da própria planilha; `enriquecido` = FINEP, setor resolvido via
  CNPJ→CNAE; `pendente` = FINEP cujo CNPJ ainda não foi resolvido; `corrigido_manual` = sofreu
  correção manual, prevalece sobre reenriquecimento), `search_document`/`search_taxonomia_termos`/
  `search_vector` (motor de busca sem IA, ver seção própria).
- **`cnpj_cnae`**: cache CNPJ → CNAE/razão social/natureza jurídica/porte/capital social,
  alimentado por `src/enrich_cnae.py` a partir dos Dados Abertos de CNPJ da Receita Federal.
  `setor_bndes_mapeado`/`subsetor_bndes_mapeado` vêm de `cnae_divisao` + `build_divisao_map()`
  (ver `src/sector_taxonomy.py`) — **CUIDADO**: um bug real já existiu aqui (ver "Bugs
  reais já corrigidos" abaixo), sempre desconfiar se uma categoria parecer super-representada.
- **`de_para_cnae`**: crosswalk oficial BNDES (divisão CNAE → Setor/Subsetor BNDES). Tem uma
  ambiguidade REAL e intencional: a mesma divisão CNAE pode aparecer tanto em uma faixa
  "Comércio e Serviços" quanto em uma faixa mais específica (Indústria/Infraestrutura/
  Agropecuária) — não é erro de digitação, é assim que a metodologia do BNDES realmente
  funciona (depende de mais contexto que só CNAE). `build_divisao_map()` resolve por
  "última linha da tabela vence" — se um dia isso incomodar, é uma decisão de produto a tomar,
  não um bug a caçar às cegas.
- **`editais_raw`**: chamadas públicas (editais) abertas da FINEP — dado próprio, upsert
  (preserva id da própria FINEP), NÃO faz parte do rebuild de `operations`.
- **`linhas_incentivadas`**: catálogo de PRODUTOS de crédito permanentes (não transações) —
  ver seção própria abaixo.
- **`operations_correcoes_manuais`**: correções manuais pontuais em campos de `operations`,
  reaplicadas automaticamente a cada refresh (ver `unify.py::_reaplicar_correcoes_manuais`).
- **`refresh_log`**: histórico de cada rodada do pipeline semanal (`src/refresh.py`).

## Pipeline de dados (operações BNDES/FINEP)

`src/refresh.py` orquestra tudo, chamado semanalmente pelo GitHub Actions
(`.github/workflows/refresh-operacoes.yml`, segunda-feira 06:00 UTC, timeout 180min):

1. `src/download.py` — baixa as planilhas oficiais mais recentes (BNDES + FINEP).
2. `src/parse_bndes.py`/`src/parse_finep.py` — normalizam pras staging tables (`*_raw`).
3. `src/unify.py::build_operations()` — reconstrói `operations`: junta BNDES (setor nativo) +
   FINEP (setor via `cnpj_cnae`, se já resolvido, senão `setor_origem='pendente'`); recalcula
   `search_document`/`search_taxonomia_termos`/`search_vector` (busca) e `embedding_text`
   (embeddings, só usado se o motor de IA opcional for religado); reaplica correções manuais
   (`operations_correcoes_manuais`); tenta reclassificar pendentes cujo CNPJ tenha sido
   resolvido desde o último refresh (`_reclassificar_pendentes`).
4. Sempre recalcula embeddings (`data/embeddings.npz`) mesmo com o motor de busca por IA
   desligado — mantém o artefato consistente com o banco caso alguém religue `MOTOR_BUSCA_IA`.

`src/enrich_cnae.py` é um job PESADO e SEPARADO (não roda dentro do `refresh.py` semanal) —
mensal (`.github/workflows/enrich-cnae.yml`), baixa ~5-6GB da Receita Federal (Dados Abertos de
CNPJ via WebDAV), resolve CNAE/razão social/porte/capital social só dos CNPJs que aparecem em
`bndes_raw`/`finep_*_raw` (nunca a base nacional inteira). Rode manualmente com
`python src/enrich_cnae.py` se precisar fechar um gap de CNPJs não resolvidos fora do calendário
mensal (idempotente, só processa quem ainda não está em `cnpj_cnae`).

`src/refresh_editais.py` (diário, `refresh-editais.yml` 08:00 UTC) orquestra
`finep_editais.py` (upsert de `editais_raw`) + `editais_documentos.py` + `editais_embeddings.py`.

## Motor de busca (aba "Busca")

**Por padrão, 100% sem IA/sem chamada a modelo nenhum** — full-text search do Postgres
(`tsvector`/`unaccent`/`pg_trgm`), ver `src/search_fts.py`. Toda a "inteligência" (sinônimos,
taxonomia, supressão de boilerplate) é PRÉ-CALCULADA no momento do enriquecimento (ver
`unify.py::_search_document`/`_search_taxonomia_termos`, `src/search_taxonomy.py`) e gravada em
`operations.search_document`/`search_taxonomia_termos`/`search_vector` — a busca em si só
consulta o que já está pronto.

Ranking em 6 tiers (do mais forte pro mais fraco, ver `PRIORIDADE_MOTIVO` em `search_fts.py`):
1. CNPJ ou prefixo do nome do cliente (só considera fragmento numérico como CNPJ se tiver
   ≥8 dígitos — sem essa guarda, uma query como "xyzabc123nada" batia como "match exato" de
   qualquer CNPJ que começasse com "123", bug real já corrigido).
2. Setor/subsetor/segmento (CNAE).
3. Produto/instrumento/indexador.
4. Correspondência de FRASE (`phraseto_tsquery`, preserva ordem/adjacência das palavras) —
   evita que "parque de diversao" traga "parque eolico" no topo só por repetir a palavra
   "parque" solta.
5. Correspondência por QUALQUER palavra (OR, `websearch_to_tsquery`) — inclui os sinônimos
   pré-calculados.
6. Trigrama (`pg_trgm`/`similarity()`) — só roda se as tiers 1-5 (indexadas) voltarem com
   poucos resultados (`MINIMO_ANTES_DE_TRIGRAMA`), já que trigrama varre a tabela inteira.

UF (sigla de 2 letras) é tratada como FILTRO estruturado (`AND uf = ?`), não como termo de
busca — senão o volume de operações de qualquer UF grande dominava o ranking por cima de um
termo raro e específico. Um pequeno conjunto de palavras genéricas do domínio
(`PALAVRAS_GENERICAS_QUERY`, ex: "empresa") é excluído do OR de texto livre pelo mesmo motivo.

`src/search_taxonomy.py` guarda os sinônimos: exaustivo para Setor (4) e Subsetor (19),
CURADO (não exaustivo) para Segmento (~1291 valores distintos de CNAE — cobertura vem
crescendo conforme o uso real mostra lacunas, ver `scripts/backfill_search_taxonomia.py` para
como reaplicar em massa depois de expandir o dicionário). Lembrete de stemming: o dicionário
`portuguese` do Postgres NÃO unifica de forma confiável singular/plural em palavras terminadas
em `-al` (ex: "hospital"/"hospitalar" viram o mesmo radical, mas "hospitais" vira outro) — por
isso os sinônimos incluem singular E plural quando relevante.

**Motor por IA (embeddings) continua existindo, só desligado por padrão** — flag
`MOTOR_BUSCA_IA` (env var, `webapp/main.py`). Se `MOTOR_BUSCA_IA=1`: religa as rotas
`/api/busca/preparar*` (cálculo de vetor no NAVEGADOR via transformers.js,
`embeddings-client.js`) e o fluxo antigo em `src/search.py`/`src/embeddings.py`. Decisão de
produto explícita do usuário: manter essa estrutura "guardada e flexível" pra religar no
futuro, não removida. Se for reativar de verdade um dia, reconferir se `data/embeddings.npz`
está atualizado (ver pipeline acima).

## "Linhas Incentivadas" (catálogo de produtos, não transações)

Página própria (`webapp/static/js/linhas.js`, rotas `/api/linhas*`), substituiu uma antiga
página "Minha Empresa". Curadoria MANUAL VERIFICADA (nunca raspagem automática ao vivo do site
oficial — os dados são capturados uma vez, com URL fonte + trecho citado, e ficam gravados) —
ver `src/linhas_incentivadas.py`. Cada instituição tem sua própria lista `_XXX_MANUAL` +
`seed_xxx_manual(conn)`, todas chamadas em `build_linhas_incentivadas()`:

- **BNDES** (46 linhas): descoberto via a API de busca interna do próprio site
  (`bndes.gov.br/WCMUtil/api/busca/?search=<termo>&type=all&...`, filtrando URLs
  `/financiamento/produto/`) — o conteúdo real de cada produto fica dentro de acordeões
  fechados por padrão no DOM (`.collapsible-header`/`.collapsible-body`), só acessível via JS,
  NUNCA aparece em `get_page_text` simples.
- **BNB** (23 linhas): a maioria são produtos do FNE (Fundo Constitucional de Financiamento do
  Nordeste). Site do BNB é mais simples/navegável que o do BNDES (páginas estáticas normais).
- **Desenvolve SP** (17 linhas): cada linha pertence a uma CATEGORIA (página), e a MESMA linha
  pode aparecer em categorias diferentes com termos DIFERENTES (prazo/carência mudam por
  contexto) — cada combinação (linha, categoria) é uma entrada distinta de propósito.
- **FINEP** (2 linhas, "Apoio Direto à Inovação" e "Apoio Direto a Pré-Investimento"):
  **NÃO confundir com editais** — a FINEP tem MUITO mais chamadas públicas (editais, com
  prazo) do que produtos de crédito permanentes. Uma versão antiga desta função
  (`importar_finep_editais`, ainda definida no arquivo mas **não mais chamada**) importava CADA
  EDITAL de `editais_raw` como se fosse uma "linha incentivada" — isso duplicava a aba
  "Editais" (já dedicada a isso) dentro deste catálogo, que deveria mostrar só produtos
  permanentes. Se um dia parecer que "FINEP tem poucas linhas", a resposta correta é curar mais
  produtos permanentes reais (raro — a FINEP tem poucos), não voltar a importar editais aqui.

Regra de ouro em toda a curadoria: **nunca inventar** valor/taxa/prazo — campo não documentado
na fonte oficial usa o sentinela `NAO_INFORMADO`, nunca um valor inferido/estimado. Cada linha
tem `origem_dado` (`curadoria_manual_verificada` ou `raspagem_automatica`) e `trecho_fonte`
(citação real da página) para auditoria.

Cross-linking: no detalhe de uma OPERAÇÃO real, aparece uma seção mostrando linhas
incentivadas "potencialmente compatíveis" (nunca "elegível", a menos que confirmado) — ver
`webapp/main.py::operacao_detalhe()` e a seção correspondente em `common.js`.

**Este catálogo NÃO é reconstruído pelo refresh semanal** (`build_linhas_incentivadas()` não é
chamado por `refresh.py`) — é essencialmente estático, atualizado manualmente quando alguém
cura mais linhas. Rode `python src/linhas_incentivadas.py` pra reaplicar depois de editar as
listas `_XXX_MANUAL`.

## Frontend: roteamento e abas

5 abas (`.tab-btn[data-view=...]` / `<section id="view-...">`): Consolidado, Tendências &
Insights, Busca, Editais, Linhas Incentivadas. A URL reflete qual aba está aberta como CAMINHO
(`/consolidado`, `/tendencias`, `/busca`, `/editais`, `/linhas-incentivadas`), via
`history.pushState`/`popstate` em `common.js` (`_ativarView`/`_ligarBotoesDeAba`/
`_viewInicialDaURL`) — nunca query string para estado de UI (ex: a granularidade do gráfico de
Tendências fica só na página, não na URL; pedido explícito do usuário pra manter a barra de
endereço limpa). Navegação direta pra qualquer uma dessas 5 URLs (digitar/recarregar) funciona
via: rota catch-all `spa_pagina` em `webapp/main.py` (serve pro modo local `uvicorn`) + rewrites
equivalentes em `vercel.json` (serve pro deploy hospedado).

Filtros de data (mês/ano início e fim, em várias abas) bloqueiam automaticamente um intervalo
invertido (início > fim) — ver `validarIntervaloDatas()` em `common.js`, ajusta o lado que não
acabou de mudar pra igualar o que o usuário escolheu, com um aviso visual breve.

Busca guarda um HISTÓRICO PESSOAL de queries no `localStorage` do navegador (nunca vai pro
servidor, "temporário" por design) — substituiu 3 chips de exemplo fixos que existiam antes
(`busca.js`, `registrarHistoricoBusca`/`renderHistoricoBusca`).

## Automação (GitHub Actions)

Todos em `.github/workflows/`, usando o secret `DATABASE_URL`:
- `refresh-operacoes.yml` — semanal, segunda 06:00 UTC, timeout 180min, roda `src/refresh.py`.
- `refresh-editais.yml` — diário, 08:00 UTC, timeout 15min, roda `src/refresh_editais.py`.
- `enrich-cnae.yml` — mensal, roda `src/enrich_cnae.py`.

Se o "refresh automático parece não estar funcionando", antes de caçar bug: confira 1) se
`DATABASE_URL` está configurada há tempo suficiente pro cron já ter tido uma janela real pra
disparar (ex: cron só-segunda + secret configurado numa sexta = zero execuções até a próxima
segunda, não é bug), e 2) `SELECT * FROM refresh_log ORDER BY id DESC` pra ver o histórico real.

## Bugs reais já corrigidos nesta base (armadilhas a não repetir)

- **`_extrair_divisoes` (`src/sector_taxonomy.py`)**: fatiava código de CNAE de forma errada
  para faixas com subclasse longa (ex: "H4911, H4912401 e H4912402"), produzindo um intervalo
  de divisões espúrio e corrompendo o mapeamento setor/subsetor de várias divisões no meio (ex:
  divisão 26 virava "Transporte Ferroviário" em vez de "Indústria"). O CÓDIGO já foi corrigido
  há tempo, mas os DADOS já gravados em `cnpj_cnae`/`operations` continuaram errados até
  2026-09-04 (5.644 operações da FINEP mal-classificadas) — corrigido com um backfill direto
  (recalcular `setor_bndes_mapeado`/`subsetor_bndes_mapeado` a partir do `cnae_divisao` já
  armazenado, sem precisar rebaixar nada da Receita Federal). **Lição**: corrigir um bug de
  cálculo no código NÃO corrige dados já gravados — sempre considerar se um backfill é
  necessário, e desconfiar de qualquer categoria/setor que pareça anormalmente
  super-representada nos dados (sinal de um bug de classificação, não de realidade).
- **Falso-positivo de CNPJ na busca** (`src/search_fts.py`): fragmento numérico de qualquer
  tamanho disparava o tier de "correspondência exata" de CNPJ — corrigido exigindo ≥8 dígitos.
- **`websearch_to_tsquery` combina palavras com AND por padrão** — ruim para busca livre em
  linguagem natural (query de 5-6 palavras nunca bateria por completo em documento nenhum);
  junta as palavras com `" or "` manualmente antes de passar pro Postgres.
- **`_periodo_anterior` (`webapp/main.py`)**: limitava incondicionalmente o período "atual" a
  no máximo 365 dias antes de calcular o período de comparação — um filtro de 2 anos escolhido
  pelo usuário virava, por baixo dos panos, uma comparação só dos últimos 12 meses, sem
  indicação nenhuma na UI de que o período exibido não era o filtro de verdade. Corrigido: o
  teto de 365 dias só vale quando NENHUM filtro é passado (padrão "toda a base"); com filtro
  explícito, o período anterior tem sempre o MESMO TAMANHO EXATO do selecionado.
- **Variante ortográfica "óptica"/"ótica" na busca** (`src/search_fts.py`,
  `_normaliza_ortografia_sql()`; mesma normalização espelhada em
  `unify.py::_atualizar_search_vector()`): as duas grafias (antiga, com P — "fibra
  óptica" — e atual, sem P — "fibra ótica") são o MESMO conceito na fala real, mas o
  stemmer do Postgres as trata como palavras diferentes. Buscar "cabos de fibra otica"
  rankeava uma ÓTICA (loja de óculos, match incidental do nome) ACIMA de uma empresa
  real de fibra óptica, porque a descrição dela usava a grafia com P. Corrigido com
  `regexp_replace(..., 'optic', 'otic', 'gi')` aplicado nos DOIS lados (query e
  indexação) depois de `unaccent()`. Backfill já rodado contra toda a base (ver
  `scripts/backfill_search_taxonomia.py`).
- **`.status-pill` (topbar) quebrando pra uma segunda linha solta** (`style.css`): em
  larguras intermediárias de desktop (~900-1300px), o pill de status ia sozinho pra uma
  segunda linha desalinhada. Corrigido: a partir de 900px, `.topbar` vira
  `flex-wrap:nowrap` e brand/pill ganham `flex-shrink:0` — quem absorve a falta de
  espaço é `.tabs` (já rola horizontal). Abaixo de 900px, mantido o empilhamento
  original (mobile/tablet já funcionava bem assim).

## Coisas a saber antes de mexer

- **`db_compat.py`** faz um monkeypatch global: todo `?` em queries SQL (estilo sqlite,
  convenção usada em 100% do código deste projeto) vira `%s` (estilo psycopg) transparentemente
  — nunca escreva `%s` direto nas queries deste projeto, sempre `?`. Isso também significa que
  um `%` literal dentro de uma string SQL (ex: `LIKE '%%texto%%'`) precisa ser escapado como
  `%%`, senão quebra o parser de placeholder do psycopg.
- **Pool de conexões de verdade** (`src/db.py`, `get_connection(pooled=True)`) — a webapp
  (`webapp/main.py`, todos os ~26 call sites) usa um `psycopg_pool.ConnectionPool` real
  (`min_size=1, max_size=8`), não mais uma conexão nova por requisição. Histórico: primeiro
  corrigido (2026-09-04) esgotando o limite de 15 conexões do pooler em modo *session* da
  Supabase; depois de migrar pro Aiven (2026-09-08, sem pooler gerenciado no plano
  gratuito, só um teto bruto de 20 conexões), a solução virou um pool client-side de
  verdade em vez de apontar pra um endpoint de pooler gerenciado.
  `_PooledConnection`: wrapper fino que só troca o significado de `.close()` (devolve pro
  pool via `putconn()` em vez de fechar de verdade) — evita reescrever os ~26 call sites
  que já fazem `conn = get_connection(...); try: ...; finally: conn.close()`.
  **Bug real já corrigido**: `ConnectionPool` NÃO valida a conexão no `getconn()` por
  padrão — uma conexão morta por ação do servidor (confirmado: `AdminShutdown` do Aiven
  numa manutenção automática) ficava PRESA no pool, devolvida pra toda requisição
  seguinte, derrubando a webapp inteira (500 em toda rota que toca o banco) até reiniciar
  o processo na mão. Corrigido com `check=ConnectionPool.check_connection` na criação do
  pool — todo checkout roda uma verificação antes de devolver a conexão, descarta e abre
  uma nova na hora se estiver morta. Testado ao vivo (matando as conexões do pool via
  `pg_terminate_backend()`, simulando o `AdminShutdown` real): 0 erros com o fix; sem ele,
  a mesma simulação derrubava a webapp inteira.
  Testado sob carga: 120 requisições HTTP simultâneas contra o Aiven (bem acima do caso
  real de ~15-20 por carga de página) — 0 erros.
  `DATABASE_URL_POOLER` (se definida) tem prioridade sobre `DATABASE_URL` só pro pool —
  hoje **opcional/legado**: só relevante se um provedor futuro oferecer um endpoint de
  pooler GERENCIADO separado (ex: Supabase em modo transaction); sem essa variável
  definida (caso do Aiven agora), o pool conecta direto na `DATABASE_URL` normal — ele
  mesmo já faz o papel de pooler do lado do cliente.
  Scripts de pipeline (`refresh.py`, `enrich_cnae.py` etc., só via GitHub Actions)
  continuam chamando `get_connection()` sem argumento (conexão direta, sem pool) — sessões
  longas com poucas conexões são o caso de uso oposto ao que o pool resolve.
- **Sessões/agentes de IA concorrentes podem compartilhar este mesmo working directory** (já
  aconteceu nesta sessão) — antes de `git add <arquivo> && git commit`, prefira conferir
  `git diff <arquivo>` primeiro se houver qualquer suspeita de edição concorrente, pra não
  commitar sem querer uma mudança de outro processo junto com a sua.
- **Cache de JS/CSS no navegador in-app (Claude Code Browser pane)** pode servir uma versão
  antiga de um arquivo estático mesmo depois de editado no disco — se um teste não refletir uma
  mudança recente, tente `fetch(url, {cache:'reload'})` ou um cache-bust
  (`?bust=<timestamp>`) antes de suspeitar de bug real.
- **`webapp/static/index.html`/`common.js`/`main.py` são arquivos grandes** — ao editar, prefira
  `Grep`/`Read` com offset pontual em vez de carregar o arquivo inteiro de uma vez.

## Onde procurar o quê (mapa rápido)

| Preciso mexer em... | Arquivo |
|---|---|
| Schema do banco | `src/db.py` |
| Pipeline semanal (operações) | `src/refresh.py`, `src/unify.py` |
| Enriquecimento CNPJ→CNAE | `src/enrich_cnae.py`, `src/sector_taxonomy.py` |
| Motor de busca (sem IA) | `src/search_fts.py`, `src/search_taxonomy.py` |
| Motor de busca (IA, opcional) | `src/search.py`, `src/embeddings.py` |
| Catálogo Linhas Incentivadas | `src/linhas_incentivadas.py` |
| Editais da FINEP | `src/finep_editais.py`, `src/refresh_editais.py` |
| API/rotas | `webapp/main.py` |
| Frontend (abas, roteamento, filtros) | `webapp/static/js/common.js`, `webapp/static/index.html` |
| Frontend (cada aba) | `webapp/static/js/{consolidado,tendencias,busca,editais,linhas}.js` |
| Deploy Vercel | `vercel.json`, `api/index.py`, `DEPLOY.md` |
| Automação | `.github/workflows/*.yml` |
