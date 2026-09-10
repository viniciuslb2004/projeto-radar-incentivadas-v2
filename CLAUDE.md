# Radar de Crédito Incentivado — contexto para IAs futuras

Este arquivo existe para que qualquer assistente de IA (Claude ou outro) que abra este
repositório entenda rapidamente o que a plataforma faz, como está estruturada, e as decisões
não-óbvias que já foram tomadas — sem precisar reconstruir esse contexto do zero lendo commit
por commit. `README.md`/`DEPLOY.md`/`RESUME.md` também existem mas ficam desatualizados rápido
(são notas point-in-time); este arquivo é o que deve ser mantido mais preciso e atual.

**Data da última revisão a fundo deste arquivo: 2026-09-09.**

## O que é a plataforma

Site que acompanha operações de **crédito incentivado** contratadas por empresas brasileiras
junto a instituições de fomento — hoje BNDES e FINEP têm dados reais de transações (~58 mil
operações desde 2002); há também um catálogo separado de **linhas de crédito permanentes**
(produtos, não transações) do BNDES, FINEP, Desenvolve SP e BNB. Público-alvo: alguém
analisando o mercado de crédito incentivado brasileiro (ex: para prospecção, benchmarking,
inteligência de mercado) — não é uma ferramenta de originação/contratação de crédito.

100% online: front-end (SPA vanilla JS) + backend (FastAPI) + banco (Postgres/Aiven)
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
  tabela, contagens conferidas, tudo bateu exato). O corte de verdade em produção (trocar
  `DATABASE_URL` na Vercel E no secret do GitHub Actions) só terminou em 2026-09-09 — ver
  a seção "Coisas a saber antes de mexer" pra armadilhas reais encontradas nesse processo
  (env var da Vercel que parece salvar sem salvar, secret do GitHub Actions independente
  do da Vercel). O projeto Supabase antigo **continua existindo, sem nenhum dado
  apagado** — decisão deliberada de não descartar o backup até o Aiven se provar estável
  por mais tempo em produção; a decisão de quando (e como) desligar/esvaziar o Supabase é
  do usuário, não uma limpeza automática deste pipeline.
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
6. Trigrama (`pg_trgm`/`similarity()`) — só roda se as tiers 1-5 voltarem com poucos
   resultados (`MINIMO_ANTES_DE_TRIGRAMA`), já que trigrama (nesta forma, comparando
   `unaccent(lower(cliente))`) também varre a tabela inteira (ver nota de performance
   abaixo — mesma limitação de índice que as tiers 1-3).

UF (sigla de 2 letras) é tratada como FILTRO estruturado (`AND uf = ?`), não como termo de
busca — senão o volume de operações de qualquer UF grande dominava o ranking por cima de um
termo raro e específico. Um pequeno conjunto de palavras genéricas do domínio
(`PALAVRAS_GENERICAS_QUERY`, ex: "empresa") é excluído do OR de texto livre pelo mesmo motivo.

**Performance (revisado 2026-09-09)**: `operations` tem índices reais disponíveis
(`idx_operations_search_vector` GIN em `search_vector`, `idx_operations_cliente_trgm`/
`idx_operations_segmento_trgm` GIN trigram, além de btree em `cnpj`/`setor_bndes`/`uf`/etc
— ver `pg_indexes`), mas a query original de `buscar_texto()` colocava TODAS as 6 tiers
dentro de um único `CASE` avaliado incondicionalmente sobre a tabela inteira (~58 mil
linhas) e só filtrava (`WHERE prioridade IS NOT NULL`) depois — isso força
`Parallel Seq Scan` mesmo com os índices certos disponíveis (confirmado com
`EXPLAIN ANALYZE` ao vivo: toda busca, de qualquer tipo, levava ~5-17s). Corrigido
parcialmente: as tiers 4/5 (full-text, `search_vector @@ tsquery`) viraram queries
próprias com o `@@` direto no `WHERE` (sem CASE por cima) — isso deixa o Postgres
escolher `Bitmap Index Scan` no GIN, medido em ~150-300ms quando essas tiers dominam
(contra ~4-8s antes). As tiers 1-3 (prefixo de CNPJ/cliente, keyword em
setor/subsetor/segmento/produto/instrumento/indexador via `LIKE` sobre
`unaccent(lower(campo))`) **continuam fazendo seq scan** — não há índice funcional
casando com essa expressão exata (os índices trigram existentes são sobre a coluna
RAW, sem `unaccent`/`lower`), e como tiers 1-3 rodam em TODA busca (correção precisa
ser feita antes de tiers 4/5 poderem ser avaliadas, pra nunca reclassificar uma
operação pra uma tier mais fraca), esse seq scan (~3-4s, majoritariamente o custo dos
9 `unaccent()`+`regexp_replace()`+`lower()` por linha, não do ranking em si — testado
isolando `ts_rank_cd` da query, o custo não muda muito) virou o piso de latência de
QUALQUER busca. Ganho líquido medido (`orig` vs `novo`, alternando lado a lado contra
produção pra descontar o ruído de rede do Aiven free tier): ~35-45% mais rápido em
média, sem nenhuma mudança de resultado/ranking (mesma bateria de queries de
regressão validada antes e depois). **Se precisar reduzir mais**: o próximo passo
exigiria um índice funcional novo (ex: `CREATE INDEX ... ON operations USING gin
(unaccent(lower(cliente)) gin_trgm_ops)`, idem pra setor/subsetor/segmento/produto) —
é uma migração de schema na Aiven de produção (mesmo banco usado por todas as sessões
concorrentes), então não fazer sem confirmar com o usuário antes, mesmo que
tecnicamente seguro (`CREATE INDEX CONCURRENTLY` evita lock de escrita).

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
`_viewInicialDaURL`). Navegação direta pra qualquer uma dessas 5 URLs (digitar/recarregar)
funciona via: rota catch-all `spa_pagina` em `webapp/main.py` (serve pro modo local `uvicorn`)
+ rewrites equivalentes em `vercel.json` (serve pro deploy hospedado).

**Filtros na URL (query string)**: cada aba reflete os PRÓPRIOS filtros na query string do
mesmo caminho (nunca no path, que já indica a aba) — pra dar pra compartilhar um link que abre
a mesma aba com os mesmos filtros aplicados (`sincronizarFiltrosNaURL`/`paramsDaURL` em
`common.js`, um `_aplicarFiltros*DaURL()` por aba). Sempre `replaceState` (nunca `pushState`)
pra filtro — só a troca de ABA cria uma entrada de histórico nova. Exclusão deliberada e
conservadora: só entra o que restringe QUAL FATIA dos dados aparece (setor, UF, agência, data,
texto de busca etc.) — o que só muda COMO os mesmos dados são exibidos (granularidade do
gráfico de série temporal, ordenação em Editais/Linhas/Busca/modal de operações, página atual
da paginação de Linhas) fica de fora, tratado como estado local da página.

Trocar de aba por CLIQUE preserva o último conjunto de filtros que aquela aba (ou grupo de
abas) já tinha nesta mesma visita à página — tanto na tela quanto na URL — em vez de limpar
(comportamento antigo, corrigido em 2026-09-10 depois de reportado pelo usuário: "quando mudo
de guia os filtros não acompanham"). Consolidado e Tendências compartilham o mesmo `#filterbar`
(mesmos elementos DOM físicos, só escondido via `display:none` pras outras 3 abas), então são
tratados como um único GRUPO (`_grupoDaView()` em `common.js`) — alternar entre os dois nunca
limpa nada, já que o filtro de um É o do outro (mesmo input). Busca/Editais/Linhas são cada um
o próprio grupo — filtros/conceitos de UI incompatíveis entre si (ex: Busca usa `regiao`,
Consolidado usa `uf`), então NUNCA herdam filtro de um grupo diferente ao serem abertos; só
restauram o que aquela aba especificamente já teve antes. Mecanismo: `_ultimaQueryPorGrupo`
(cache em memória, não sobrevive a F5 de propósito — um F5/link direto usa a query já presente
na URL) grava a última query de cada grupo toda vez que `sincronizarFiltrosNaURL` roda, e
`_ativarView` consulta esse cache ao montar a URL de destino de um clique real numa aba. Não
precisou mexer nos CAMPOS de filtro em si — eles já preservavam seu valor sozinhos ao trocar de
aba (nenhum código os reseta quando a aba fica escondida), só a URL que ficava dessincronizada
do que já estava na tela.

Filtros de data (mês/ano início e fim, em várias abas) bloqueiam automaticamente um intervalo
invertido (início > fim) — ver `validarIntervaloDatas()` em `common.js`, ajusta o lado que não
acabou de mudar pra igualar o que o usuário escolheu, com um aviso visual breve.

Busca guarda um HISTÓRICO PESSOAL de queries no `localStorage` do navegador (nunca vai pro
servidor, "temporário" por design) — substituiu 3 chips de exemplo fixos que existiam antes
(`busca.js`, `registrarHistoricoBusca`/`renderHistoricoBusca`).

Card "Por UF" do Consolidado (`loadUF()` em `consolidado.js`) era um bar chart Chart.js
mostrando só o top-12 (`/api/uf` sempre devolveu as 27 UFs sem limite — o corte era só no
frontend); virou um MAPA do Brasil (2026-09-09). Sem biblioteca de mapas nenhuma — SVG inline
baixado 1x de "Brazil States With ID and State Name inside svg.svg" (Wikimedia Commons,
derivado de Brazil_Blank_Map_light.svg de Felipe Menegaz/Shereth; licença da cadeia de
derivação é CC BY-SA 2.5, mesmo o upload mais recente tendo marcado CC0 por engano), reduzido
pra só os 27 `<path id="state-xx">` (removidos os grupos de país vizinho/região/terreno do
arquivo original) e gravado como asset estático comum em `webapp/static/img/brasil-uf.svg`
(servido em `/img/brasil-uf.svg`, mesmo mecanismo do logo — **de propósito não precisou tocar
em `index.html`/`vercel.json`**: o `<canvas id="chart-uf">` original é substituído em runtime
por JS na 1a chamada de `loadUF()`, e o SVG é buscado 1x via `fetch()` e cacheado no DOM —
reduz risco de conflito de merge num arquivo compartilhado por outras sessões/features).
Cor de cada estado = interpolação linear entre `--map-escala-min`/`--map-escala-max` (definidas
em `style.css`, tons já usados no resto do projeto — não uma paleta importada tipo viridis)
sobre `sqrt((valor-min)/(max-min))`, não a fração linear direto — o volume de crédito
incentivado por estado é muito concentrado (SP/RJ dominam), então escala linear pura deixava
quase todo o resto do mapa na mesma cor clara, ilegível; raiz quadrada comprime o topo e separa
melhor os valores intermediários, mantendo a ordem e os extremos exatos. Estado sem nenhuma
operação no filtro atual usa `--map-sem-dado` (cinza neutro, de propósito SEM tom azulado —
senão "sem dado" ficava visualmente idêntico a "o pior valor da escala").
**Achado real ao implementar**: `/api/uf` devolve também `IE` (operações de abrangência
nacional/interestadual, ex: Petrobras, Banco do Brasil — não é erro, é uma categoria real da
fonte BNDES) e `NI` (UF nula na fonte, via `COALESCE(uf, 'NI')` no próprio `webapp/main.py`) —
nenhuma das duas é um estado de verdade, então não têm `<path>` no mapa. Ambas ficam DE FORA do
cálculo de min/max da escala de cor (senão o valor de `IE`, que já foi maior que o de vários
estados reais, distorceria a escala) e aparecem somadas como uma legenda textual abaixo do
mapa — o bar chart antigo mostrava `IE`/`NI` normalmente (sem corte de top-N no backend), então
esconder esse volume sem avisar seria perder dado real que já era visível antes.

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
  stemmer do Postgres as trata como palavras diferentes. Corrigido com
  `regexp_replace(..., 'optic', 'otic', 'gi')` aplicado nos DOIS lados (query e
  indexação) depois de `unaccent()`. Backfill já rodado contra toda a base (ver
  `scripts/backfill_search_taxonomia.py`) — confirmado que "otica" e "óptica" agora
  retornam exatamente o mesmo resultado/ordem, a normalização em si funciona.
  **RESOLVIDO (2026-09-09)** — causa raiz era outra, não mismatch de grafia: mesmo
  com os dois lados já normalizando igual, buscar "cabos de fibra otica" ainda
  rankeava "Ótica Diniz Ltda" (loja de óculos) ACIMA de empresas reais de fibra
  óptica (ex: "ETECC FIBRA ÓPTICA NETWORK LTDA"), confirmado ao vivo contra
  produção. Causa raiz de verdade: não é peso entre campos (A/B/C/D) — é que
  `ts_rank_cd` pesa mais o CAMPO onde bateu do que quantas palavras da query
  realmente batem, então um match de 1 palavra num campo caro (nome/segmento)
  supera um match de 3-4 palavras num campo mais barato (`descricao_projeto`).
  **Histórico da correção (duas sessões em paralelo, mesmo dia)**: um primeiro
  commit (`6c3eee7`) resolveu o ranking com uma "cobertura" (quantas palavras
  DISTINTAS da query aparecem no documento, uma a uma) calculada como subquery
  correlacionada (`unnest`+`@@`) **dentro do mesmo `CASE`** que decide a
  `prioridade` — funcionalmente correto, mas esse `CASE` já tinha um problema de
  performance PREEXISTENTE e separado (`search_vector @@ tsquery` das tiers 4/5
  embutido no CASE nunca usava o índice GIN `idx_operations_search_vector`,
  forçando `Parallel Seq Scan` em toda busca, ~5-8s). Como uma reestruturação
  pra corrigir os dois problemas de uma vez já estava em andamento em paralelo,
  esse primeiro commit foi revertido (`aacd5e1`) pra não duplicar o fix de
  ranking em cima da estrutura antiga (o filtro `porte`, do mesmo commit
  original, foi mantido). **Resolução final**: tiers 4/5 viraram queries
  próprias com `search_vector @@ tsquery` direto no `WHERE` (usa o índice GIN,
  ver "Performance" no fim da seção "Motor de busca" acima) e a cobertura passou
  a ser calculada numa query SEPARADA, só nos poucos candidatos que a tier 5 (já
  indexada) trouxe (`WHERE id = ANY(?)`, índice de PK) — nunca mais embutida
  numa CASE que roda linha a linha na tabela inteira. Não mexeu nos pesos
  `setweight()` por campo (aqueles resolveram um bug real diferente, ver entrada
  de `_periodo_anterior`/hospital-vs-SP acima, e não deviam ser tocados de novo
  sem motivo novo). **Lição**: qualquer critério de ranking novo neste motor de
  busca deve ser calculado só sobre candidatos JÁ FILTRADOS por uma query
  anterior, nunca dentro de uma CASE/subquery correlacionada que roda sobre a
  tabela inteira — confirmado medindo: uma variante equivalente (cobertura via
  `plainto_tsquery` por palavra, também dentro do CASE) chegou a ser testada e
  mediu uma query de 8 palavras subindo de ~9s pra **55s** só por causa disso,
  contra o Aiven — meça antes de assumir que "mais uma condição" é barato.
- **`.status-pill` (topbar) quebrando pra uma segunda linha solta** (`style.css`): em
  larguras intermediárias de desktop (~900-1300px), o pill de status ia sozinho pra uma
  segunda linha desalinhada. Corrigido: a partir de 900px, `.topbar` vira
  `flex-wrap:nowrap` e brand/pill ganham `flex-shrink:0` — quem absorve a falta de
  espaço é `.tabs` (já rola horizontal). Abaixo de 900px, mantido o empilhamento
  original (mobile/tablet já funcionava bem assim). **Efeito colateral dessa
  correção, resolvido depois (2026-09-10)**: `.tabs` rolando horizontal nessa
  mesma faixa (~950-1250px) mostrava uma barra de scroll nativa feia. Reduzida
  a fonte da marca (17px→15px) e o padding dos botões de aba (16px→12px) pra
  abrir espaço de verdade (elimina o scroll a partir de ~1250px, antes só
  ~1280px); onde ainda não cabe, a barra nativa fica escondida
  (`scrollbar-width:none`+`::-webkit-scrollbar{display:none}`, rolagem
  continua funcionando por touch/wheel/arraste) e um novo wrapper
  `.tabs-wrap` ganha um degrade sutil na borda (ligado/desligado por JS,
  `_atualizarSombraAbas()` em `common.js`) como aviso visual de que há mais
  abas fora da tela — sem isso, a existência de "Editais"/"Linhas
  Incentivadas" nessa faixa de largura ficaria descobrível só por acidente.

## Coisas a saber antes de mexer

- **`db_compat.py`** faz um monkeypatch global: todo `?` em queries SQL (estilo sqlite,
  convenção usada em 100% do código deste projeto) vira `%s` (estilo psycopg) transparentemente
  — nunca escreva `%s` direto nas queries deste projeto, sempre `?`. Isso também significa que
  um `%` literal dentro de uma string SQL (ex: `LIKE '%%texto%%'`) precisa ser escapado como
  `%%`, senão quebra o parser de placeholder do psycopg.
- **Pool de conexões de verdade** (`src/db.py`, `get_connection(pooled=True)`) — a webapp
  (`webapp/main.py`, todos os ~26 call sites) usa um `psycopg_pool.ConnectionPool` real
  (`min_size=0, max_size=2`), não mais uma conexão nova por requisição. Histórico completo
  de um incidente real de produção (2026-09-04 a 2026-09-09), na ordem em que aconteceu:
  1. Esgotamento do limite de 15 conexões do pooler em modo *session* da Supabase
     (`EMAXCONNSESSION`) sob carga concorrente real — cada instância serverless da Vercel
     tem seu PRÓPRIO pool (`_POOL` é global por processo, não compartilhado entre
     instâncias), então `max_size` alto multiplica pelo número de instâncias concorrentes,
     não é um teto global.
  2. Tentativa de reduzir `max_size` de 8 pra 3 — um commit real só editou a DOCSTRING,
     o `ConnectionPool(...)` de verdade continuou em `max_size=8`. Só descoberto testando
     produção ao vivo (curl direto), não por leitura de código. **Esse mesmo tipo de bug
     se repetiu uma SEGUNDA vez** (2026-09-09, ao reduzir de 3 pra 2) — lição reforçada:
     depois de qualquer mudança num valor destes, `grep` o valor literal no código, não
     confie na docstring nem na mensagem do commit anterior.
  3. Migração completa de banco pra Aiven (2026-09-08 — ver seção "Stack e topologia de
     deploy" acima) — Aiven free tier não tem pooler gerenciado, só um teto bruto de 20
     conexões, então a solução virou depender só do pool client-side (sem apontar pra
     endpoint de pooler nenhum).
  4. **Armadilha real na hora de aplicar a migração em produção**: trocar a env var
     `DATABASE_URL` na Vercel (dashboard → Settings → Environment Variables → editar) pode
     **parecer que salvou sem ter salvado de verdade** — a UI mostrou o valor novo digitado
     de volta na tela após clicar "Save", mas o campo "Last Updated" da variável continuou
     com a data antiga, e um redeploy subsequente continuou conectando no host antigo
     (confirmado lendo os logs de runtime da Vercel: a mensagem de warning do
     `psycopg_pool` inclui o host de verdade da conexão, `rolling back returned
     connection: <psycopg.Connection ... host=...>` — essa é a forma mais confiável de
     confirmar qual banco a produção está realmente usando). **Lição**: depois de editar
     uma env var na Vercel, sempre conferir que a listagem voltou a mostrar "Updated just
     now" antes de assumir que o redeploy vai pegar o valor novo — se ainda mostrar a data
     antiga, o clique em Save não registrou e precisa repetir.
  5. O secret `DATABASE_URL` do GitHub Actions é INDEPENDENTE do env var da Vercel — os
     workflows agendados (`refresh-operacoes.yml`, `refresh-editais.yml`,
     `enrich-cnae.yml`) continuaram escrevendo no Supabase antigo por um dia inteiro
     depois da migração até esse secret também ser atualizado à mão (GitHub →
     Settings → Secrets and variables → Actions). Detectado comparando contagem de linhas
     tabela a tabela entre os dois bancos: 11 das 12 tabelas bateram exato, só
     `refresh_editais_log` tinha 1 linha a mais no Supabase — o run diário de
     2026-09-09 rodou contra o secret desatualizado antes da correção. Sem perda de dado
     real (o run não encontrou editais novos pra gravar), só uma linha de auditoria que
     nunca chegou no Aiven. **Sempre que trocar `DATABASE_URL` em produção, atualizar os
     DOIS lugares (Vercel E GitHub Actions secret) e conferir contagens depois.**
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
  Testado sob carga: 120 requisições HTTP simultâneas contra o Aiven (via simulação local)
  e, depois de virar o `DATABASE_URL` de produção pra Aiven de verdade, 45 requisições HTTP
  concorrentes direto contra produção (30 buscas + 15 kpis) — 0 erros nos dois casos.
  `max_size=2` dá margem pra ~10 instâncias concorrentes da Vercel ficarem dentro do teto
  de 20 conexões do Aiven; não há evidência de que subir esse valor traga ganho de
  latência (o gargalo real está em rede/processamento por requisição, não fila de
  conexão), então manter em 2 em vez de arriscar sem necessidade comprovada.
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

## Painel de Admin (`/admin`)

Área administrativa separada do site público, com contas individuais de verdade (login +
senha com hash) em vez do login único compartilhado (`SITE_PASSWORD`, ver seção "Acesso" /
`_verificar_acesso` em `webapp/main.py`) — os dois sistemas de autenticação são INDEPENDENTES,
um não sabe da existência do outro.

**Decisão deliberada de segregação** (pedido explícito do usuário: fácil de remover inteiro
se um dia for descontinuado, sem tocar em nada do site público):
- Todo o backend fica em `webapp/admin/` (pacote próprio): `auth.py` (hash de senha PBKDF2,
  sessão por token opaco, dependency `exigir_admin`), `routes.py` (`APIRouter` com as rotas
  `/api/*`, comentário no topo do arquivo com o passo a passo de remoção), `seed.py` (script
  de migração/seed, roda manualmente, nunca automático).
- `webapp/main.py` só tem duas linhas nesse pacote: o import e
  `app.include_router(admin_router, prefix="/admin")` (logo após `STATIC_DIR`). Como o
  prefixo é `/admin` (nunca `/api`), as rotas do admin **não passam** pelo
  `_verificar_acesso`/`SITE_PASSWORD` do site público (aquele dependency só age em paths que
  começam com `/api/`) — são dois portões de acesso completamente distintos.
  Há também um pequeno ajuste (2 linhas) dentro do catch-all `spa_pagina()` existente, só pro
  modo local (`uvicorn`): sem ele, esse catch-all (que roda antes do mount de arquivos
  estáticos) intercepta qualquer caminho de um segmento só e devolve 404 pra `/admin.html`
  mesmo o arquivo existindo de verdade — não seria um problema no deploy hospedado, onde
  `vercel.json` resolve `/admin` direto na CDN antes de chegar no FastAPI.
- Frontend em arquivos próprios, nunca dentro do `index.html`/`common.js` da SPA principal:
  `webapp/static/admin.html` + `webapp/static/js/admin.js` + `webapp/static/css/admin.css`
  (reaproveita só as variáveis de cor `:root` de `style.css`, importado antes). Não é uma 6ª
  aba da SPA — é uma página HTML separada, com seu próprio JS de login/painel (não usa
  `common.js`, `sessionStorage`/`Authorization` header do site público não têm nada a ver com
  a sessão do admin).
- Tabelas próprias e isoladas: `admin_usuarios` (`id`, `username`, `password_hash`, `ativo`,
  `criado_em`) e `admin_sessoes` (`token` como PK, `usuario_id`, `criado_em`, `expira_em`,
  `ON DELETE CASCADE` de `admin_usuarios`). Nenhuma delas é referenciada por
  `operations`/`linhas_incentivadas`/`editais_raw` nem o contrário — o painel só faz
  `SELECT COUNT(*)`/leituras pontuais nessas tabelas pras estatísticas (nunca escreve nelas).
  **Diferente do resto do banco**: essas 2 tabelas NÃO estão no `SCHEMA`/`MIGRACOES_COLUNAS`
  de `src/db.py` de propósito (mantém `db.py` inteiramente intocado) — são criadas por
  `webapp/admin/seed.py`, rodado manualmente uma única vez (`python webapp/admin/seed.py`),
  nunca por um startup automático da webapp nem pelo refresh semanal.
- `vercel.json` tem 2 entradas próprias: rewrite `/admin` → `/admin.html` (arquivo estático
  próprio, não `/index.html`) e `/admin/api/(.*)` → `/api` (sem isso, as chamadas
  `/admin/api/*` do frontend nunca chegariam na function serverless em produção — só o
  rewrite `/api/(.*)` original existia, e `/admin/api/*` não bate nesse padrão).

**Sessão/senha**: hash `pbkdf2_sha256$<iterações>$<salt_base64>$<hash_base64>`
(PBKDF2-HMAC-SHA256, 600.000 iterações), comparado com `hmac.compare_digest` (nunca `==`).
Sessão = token opaco (`secrets.token_urlsafe`) gravado em `admin_sessoes` com expiração
(24h), devolvido como cookie `admin_session` (httponly, `secure` quando `VERCEL` está
definido, `samesite=strict`, `path=/admin`) — nunca um JWT/cookie assinado client-side, a
validade é sempre conferida contra a linha em `admin_sessoes` no backend. Desativar um
usuário (`ativo=false`) invalida a sessão dele na hora, mesmo com o cookie ainda válido
(`exigir_admin` confere `ativo` a cada requisição) — testado ao vivo: desativar o próprio
usuário logado derruba a sessão imediatamente, sem esperar o cookie expirar.

**Conta inicial**: `admin`, inserida por `seed.py` com um hash já pronto (a
senha em texto puro nunca passou pelo código/commit/log — só o hash). Pra adicionar mais
contas depois, seria natural evoluir `routes.py` com uma rota de criação (hoje só existe
ativar/desativar via `/admin/api/usuarios/{id}/ativo`, não há rota de criação de usuário
pelo painel ainda).

**Como remover o painel inteiro** (ver também o comentário no topo de
`webapp/admin/routes.py`): `DROP TABLE admin_sessoes; DROP TABLE admin_usuarios;` + apagar a
pasta `webapp/admin/` + apagar `webapp/static/admin.html`/`admin.js`/`admin.css` + remover as
2 linhas de include em `webapp/main.py` (e o ajuste de 2 linhas em `spa_pagina()`) + remover
as 2 entradas de rewrite de `vercel.json`. Nada disso toca em `operations`,
`linhas_incentivadas`, `editais_raw` ou no login único do site público.

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
| Painel de Admin (`/admin`) | `webapp/admin/*`, `webapp/static/admin.html`, `webapp/static/js/admin.js` |
| Deploy Vercel | `vercel.json`, `api/index.py`, `DEPLOY.md` |
| Automação | `.github/workflows/*.yml` |
