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
(produtos, não transações) do BNDES, FINEP, Desenvolve SP, BNB, BASA, BB e CEF. Público-alvo:
alguém analisando o mercado de crédito incentivado brasileiro (ex: para prospecção, benchmarking,
inteligência de mercado) — não é uma ferramenta de originação/contratação de crédito.

**Segundo "modo" em construção desde 2026-09-16: "Radar de Crédito Primário"**, cobrindo o
mercado de capitais primário (debêntures, CRI, CRA, notas comerciais, letras financeiras, CDCA,
CCB) via dados da CVM — ver seção própria "Radar de Crédito Primário — Pipeline CVM" mais abaixo.
Só a CAMADA DE DADOS existe até aqui (staging + `operations_primario`); rotas de API, motor de
busca e frontend são trabalho de sessões seguintes.

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
  **Serviço Render (`radar-credito-backend`) É LIXO/LEGADO, confirmado com o usuário
  (2026-09-16)**: antes da Vercel, o deploy era Render (backend) + Vercel (frontend) — ver
  `RESUME.md` (nota antiga de 2026-09-03), que já dizia "depois de confirmar o deploy da
  Vercel, desligar o serviço da Render" como pendência, mas isso nunca foi feito. A produção
  real é 100% Vercel há muito tempo; o Render ficou recebendo deploy automático de todo push
  pra `master` sem ninguém acompanhar, e vem falhando (dessincronizado de meses de mudanças
  de schema/dependências nunca testadas contra ele). **Ação combinada**: ignorar os e-mails
  de "deploy failed" do Render — não são um incidente de produção real. Desligar de vez o
  auto-deploy (dashboard do Render → Settings → desconectar o repo, ou pausar o serviço) é
  uma ação que só o usuário pode fazer; se um dia isso incomodar, essa é a solução, não tentar
  consertar o build do Render.
- **Automação**: GitHub Actions (`.github/workflows/*.yml`), 3 workflows agendados (ver seção
  própria abaixo), todos usando o secret `DATABASE_URL`.
- **Local dev**: `uvicorn webapp.main:app` a partir da raiz do repo; `.env` na raiz fornece
  `DATABASE_URL` (via `python-dotenv`, carregado em `src/db.py`). Login (ver seção "Painel de
  Admin" abaixo): sem nenhuma linha em `admin_usuarios` (banco novo, `webapp/admin/seed.py`
  nunca rodado), o servidor local roda sem exigir login — assim que a primeira conta existir
  (local ou em produção), toda rota `/api/*` passa a exigir sessão válida.

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
- **`cvm_oferta_distribuicao_raw`**/**`operations_primario`**/**`refresh_primario_log`**: staging
  + tabela unificada + log do Radar de Crédito Primário (CVM) — ver seção própria "Radar de
  Crédito Primário — Pipeline CVM" mais abaixo.

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

**Filtros estruturados da Busca** (`buscar_texto()`, sempre `AND`, nunca dentro do ranking):
`agencia`, `valor_minimo`, `regiao`, `produto`, `porte` (ver `PORTE_NORMALIZADO_SQL` acima) e,
desde 2026-09-15, `setor` e `uf` explícito. `uf` (dropdown, filtro explícito) tem prioridade
sobre uma UF digitada solta no texto da busca (`uf_detectada`) se as duas vierem preenchidas —
`uf_final = uf or uf_detectada`. `setor` combina `setor_bndes` (4 categorias amplas) e
`subsetor_bndes` (19, mais granulares) **NA MESMA lista de opções** no frontend (pedido
explícito do usuário — ele quer o filtro geral e o granular juntos, não dois selects
separados), com `<optgroup>` só para separação visual; o backend testa contra as DUAS colunas
com um `OR` simples (`setor_bndes = ? OR subsetor_bndes = ?`), então não importa se o valor
escolhido é setor ou subsetor — funciona sem o front precisar saber qual é qual. Os dois
vocabulários são disjuntos, exceto "AGROPECUÁRIA" (setor E o único subsetor daquele setor —
mesma string, mas describem exatamente o MESMO conjunto de operações ali, então o `OR` não gera
ambiguidade real). **Não existe uma categoria "inovação"** — pedido inicial do usuário citava
esse termo como exemplo, mas não é um valor real de `setor_bndes`/`subsetor_bndes` (é um
conceito da FINEP, não do BNDES); o filtro `agencia=FINEP` (já existente) é o proxy mais
próximo dessa intenção.

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
- **BASA (Banco da Amazônia)** (9 linhas, adicionadas em 2026-09-15): 8 sub-linhas do FNO
  (Fundo Constitucional de Financiamento do Norte — Amazônia Rural, Amazônia Empresarial,
  Amazônia Empresarial Verde, Amazônia Infraestrutura, Amazônia Infraestrutura Verde,
  Ciência/Tecnologia e Inovação, Biodiversidade, Energia Verde), capturadas navegando
  `bancoamazonia.com.br/linhas-de-fomento/fno/<produto>` (páginas estáticas, sem acordeão JS —
  diferente do BNDES) + 1 linha do **FDA** (Fundo de Desenvolvimento da Amazônia, gerido pela
  SUDAM, BASA como agente operador — mesmo padrão do FDNE/BNB). A página de listagem do BASA
  também lista FMM, PRONAF, FUNGETUR e produtos BNDES (Finame/Automático) como "linhas de
  fomento" — deliberadamente NÃO curados aqui pra não duplicar produtos que já pertencem a
  outra instituição neste catálogo (BNDES) ou que são geridos por outros fundos sem página
  própria detalhada no site do BASA.
- **BB (Banco do Brasil)** (9 linhas, adicionadas em 2026-09-15): Pronamp Investimento, Pronamp
  Custeio, Pronaf Grupo B, Pronaf Custeio A/C, Custeio Agropecuário, Funcafé Custeio, Programa
  Nacional de Crédito Fundiário, RenovAgro e FCO Rural — Investimento Agropecuário, capturadas
  em `bb.com.br/site/agronegocios/`. Deliberadamente restrito a linhas de fomento/crédito rural
  incentivado (Pronaf/Pronamp/fundos constitucionais/programas do MCR com taxa fixada por
  normativo do CMN) — excluídos de propósito produtos bancários comuns do mesmo portal (cartão
  Ourocard, consórcio, seguros) e outras dezenas de linhas do MCR listadas no hub
  `/investimentos/` (Inovagro, Moderfrota, Proirriga etc. — já existem em quantidade suficiente
  via BB pra não inflar o catálogo repetindo praticamente o mesmo programa nacional sob nomes
  ligeiramente diferentes). **Achado técnico**: várias páginas do BB renderizam o FAQ
  (accordion) via Angular mas já trazem o texto completo (pergunta+resposta) embutido no DOM
  num bloco JSON-LD `FAQPage` (`.elementor-widget-bb-dls-faq`) mesmo com o item colapsado na
  tela — extraído via `textContent`/JS em vez de simular clique item a item (mais confiável, já
  que o clique simulado reordena o accordion entre chamadas em alguns casos).
- **CEF (Caixa Econômica Federal)** (6 linhas, adicionadas em 2026-09-15): Financiamento ESG
  Ecoeficiência (Rede de Atacado), BCD Ecoeficiência PJ, BCD Franquias, FDA — Fundo de
  Desenvolvimento da Amazônia (a Caixa também é agente financeiro/operador do FDA, com página
  própria mais detalhada que a do BASA para o MESMO fundo gerido pela SUDAM — não é
  duplicidade, são dois agentes financeiros distintos), Programa Sustentabilidade e Programa
  Armazenagem (estes dois últimos dentro do hub Agro CAIXA). Cobertura deliberadamente menor
  que BNDES/BB/BASA — confirmado ao vivo que a Caixa é mais forte em habitação/saneamento/
  setor público do que em crédito empresarial/rural incentivado; dezenas de outras linhas do
  hub Agro CAIXA (Pronaf, Pronamp, Inovagro, Moderfrota, Proirriga etc.) são os MESMOS
  programas nacionais do MCR já curados via BB, então não foram re-curadas aqui (seria o mesmo
  programa sob outro agente financeiro, sem produto novo). **Achado técnico**: `caixa.gov.br`
  devolve 403/loop de redirecionamento para `WebFetch` simples (bloqueio de user-agent) —
  precisou do Browser pane (render completo, inclusive cookies) pra funcionar.

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

6 abas (`.tab-btn[data-view=...]` / `<section id="view-...">`): Consolidado, Tendências &
Insights, Busca, Editais, Linhas Incentivadas, Transações Salvas (esta última só faz sentido
logado — ver seção própria mais abaixo). A URL reflete qual aba está aberta como CAMINHO
(`/consolidado`, `/tendencias`, `/busca`, `/editais`, `/linhas-incentivadas`,
`/transacoes-salvas`), via `history.pushState`/`popstate` em `common.js` (`_ativarView`/
`_ligarBotoesDeAba`/`_viewInicialDaURL`). Navegação direta pra qualquer uma dessas 6 URLs
(digitar/recarregar) funciona via: rota catch-all `spa_pagina` em `webapp/main.py` (serve pro
modo local `uvicorn`) + rewrites equivalentes em `vercel.json` (serve pro deploy hospedado).

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

Busca guarda um HISTÓRICO PESSOAL de queries no `localStorage` do navegador — substituiu 3
chips de exemplo fixos que existiam antes (`busca.js`, `registrarHistoricoBusca`/
`renderHistoricoBusca`). **Decisão original ("nunca vai pro servidor") revista em 2026-09-15**:
agora que existem contas reais, o mesmo histórico também é gravado no servidor por usuário
LOGADO (mostrado na aba "Transações Salvas", ver seção própria abaixo) — o localStorage
continua existindo em paralelo, como fallback pra quando ninguém está logado, e sua CHAVE
passou a ser sufixada por usuário (`obterUsuarioAtual()`, cacheado numa Promise em `common.js`)
depois de um bug real (2026-09-11): chave fixa = duas contas diferentes no MESMO navegador
viam o mesmo histórico local, já que `localStorage` é por origem, não por sessão/conta.

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
- `refresh-primario.yml` — diário, 09:00 UTC, timeout 30min, roda `src/refresh_primario.py`
  (Radar de Crédito Primário/CVM — ver seção própria).

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
- **"grupo"/"grupos" faltando em `PALAVRAS_GENERICAS_QUERY`** (`src/search_fts.py`):
  mesmo problema que "empresa" (ver `_periodo_anterior`/hospital-vs-SP acima), só
  descoberto depois — "grupo" é uma palavra de estrutura societária tão comum quanto
  "empresa" (qualquer "Grupo X" da base), então diluía o OR de texto livre (tier 5) do
  mesmo jeito. Confirmado ao vivo (2026-09-11): buscar "Grupo Belterra" achava a
  empresa real (`AGROFLORESTAL BELTERRA AMAZONIA SPE SA`) só na posição 37/200, e
  "grupo mombak" (`MOMBAK ANGICO-BRANCO FLORESTAL S.A.`) na posição 23/200 — nos dois
  casos, buscar só pelo nome próprio (sem "grupo") já achava a empresa em 1º lugar,
  confirmando que não era dado faltando, só a palavra genérica competindo no ranking.
  Corrigido adicionando `"grupo"/"grupos"` ao mesmo set.
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

- **BUG REAL CRÍTICO encontrado e corrigido em 2026-09-10: TODAS as sequences de
  colunas `IDENTITY` do banco estavam dessincronizadas em produção (Aiven)**,
  travadas em `last_value=1` mesmo com dados reais até id 58824 (`operations`) —
  `bndes_raw`, `finep_credito_direto_raw`, `finep_credito_descentralizado_raw`,
  `finep_nao_aprovados_raw`, `operations`, `operations_correcoes_manuais`,
  `refresh_log`, `refresh_editais_log`, `linhas_incentivadas`. **Causa raiz**: a
  migração Supabase→Aiven (`scripts/migrate_supabase_to_aiven.py`, ver "Stack e
  topologia de deploy" acima) usou `COPY` tabela por tabela — `COPY` escreve
  direto nos ids explícitos de uma coluna `GENERATED ALWAYS AS IDENTITY` sem
  passar pelo `nextval()`, então a sequence nunca avança; ela ficou parada no
  valor de quando a tabela foi criada (1), enquanto os dados copiados já tinham
  ids bem maiores. **Efeito pratico**: qualquer novo INSERT que dependa da
  sequence (`INSERT INTO tabela (...) VALUES (...)` sem `id` explícito) falha com
  `UniqueViolation: duplicate key ... already exists` assim que a sequence tenta
  reusar um id já ocupado (ex: id=1). **Como foi descoberto**: ao vivo, testando
  a tela de correções manuais do painel de admin (`POST /admin/api/correcoes`,
  que chama `unify.py::registrar_correcao_manual`) — o INSERT em
  `operations_correcoes_manuais` falhou com esse erro. Investigando mais a fundo:
  **nenhuma tabela com IDENTITY tinha uma linha em `refresh_log`/
  `refresh_editais_log` mais recente que 2026-09-08**, apesar do refresh diário
  de editais (`refresh-editais.yml`, 08:00 UTC) e o semanal de operações rodarem
  desde então — sinal forte de que os workflows agendados estavam **falhando
  silenciosamente todo dia** desde o corte de produção pra Aiven (2026-09-09):
  o primeiro INSERT de qualquer refresh (numa das tabelas afetadas) quebra a
  execução inteira, e como até `refresh_log`/`refresh_editais_log` (onde o
  resultado seria registrado) também estavam dessincronizadas, a falha não deixa
  rastro nem no banco. **Corrigido** com `SELECT setval(pg_get_serial_sequence(
  'tabela', 'id'), (SELECT MAX(id) FROM tabela))` em cada uma das 9 tabelas
  (comando não-destrutivo, só avança o contador da sequence pro valor real já
  em uso — nenhuma linha de dado foi tocada). **Depois de aplicar este fix,
  confirme que o próximo refresh agendado (diário de editais, ou rode manual)
  realmente grava uma linha nova em `refresh_log`/`refresh_editais_log` com
  `status='ok'` — se isso não acontecer, o problema não era só a sequence.**
  **Lição pra qualquer migração futura via `COPY`**: sempre rodar
  `setval(pg_get_serial_sequence(...), MAX(id))` em toda tabela com coluna
  IDENTITY logo depois do `COPY`, nunca assumir que a sequence "vem junto".
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
  **Incidente real (2026-09-15)**: o teto de 20 conexões do Aiven free tier foi batido de
  verdade — `psycopg.OperationalError: FATAL: remaining connection slots are reserved for
  roles with the SUPERUSER attribute`, confirmado por DUAS sessões de IA diferentes tentando
  conectar ao mesmo tempo (nenhuma das duas conseguia, não era problema isolado de uma
  sessão). Diagnosticado via `pg_stat_activity` assim que uma conexão finalmente vagou: a
  maioria das conexões eram `usename='avnadmin'`, `state='idle'`, vindas de MUITOS
  `client_addr` diferentes (faixas de IP da AWS) — sinal de que eram instâncias serverless da
  Vercel (não scripts locais: `Get-CimInstance Win32_Process` na máquina não achou nenhum
  `uvicorn`/servidor local esquecido rodando). Aliviado terminando (`pg_terminate_backend`)
  só as conexões `avnadmin`/`idle` ociosas há MAIS de 3 minutos (nunca conexões ativas, em
  transação, ou de sistema como `pg_cron scheduler`/`pg_failover_slots worker`/
  `TimescaleDB Background Worker`/`management-agent`) — não é algo que aconteça sozinho, foi
  uma ação manual pontual, não virou rotina automática. **Causa mais provável**: um dia de
  atividade concentrada (múltiplas sessões de IA fazendo deploy + teste ao vivo em paralelo,
  vários pushes pra `master` cada um disparando um redeploy novo na Vercel) empurrou o número
  de instâncias serverless concorrentes acima da margem seguro de ~10 que o `max_size=2`
  do pool assume (ver acima) — não uma mudança de código quebrando algo. **Fica como item
  pra próxima revisão de performance/custo**: se esse padrão se repetir, vale considerar (a)
  reduzir `max_size` pra 1 (aperta ainda mais a margem de segurança, mas nunca houve evidência
  de ganho de latência com 2), ou (b) avaliar se o plano gratuito do Aiven ainda é suficiente
  pro volume de uso atual — nenhuma das duas foi decidida/aplicada, só registrada aqui.
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
- **Testar a webapp local (`uvicorn`) exige login de verdade** desde que o painel de admin
  passou a proteger o site principal também (ver seção "Painel de Admin" — `admin_usuarios` já
  tem contas reais em produção, e o local fala com o MESMO banco). `document.cookie` fica
  bloqueado pra leitura/escrita no Claude Code Browser pane (tentativa de setar
  `admin_session` direto via JS falha silenciosamente, `document.cookie` sempre volta vazio) —
  não dá pra "plantar" uma sessão manualmente assim. Caminho que funciona: (1) criar uma conta
  de teste temporária direto no banco (`webapp.admin.auth.gerar_hash_senha(...)` + INSERT em
  `admin_usuarios`), (2) logar de verdade via `fetch('/api/login', {credentials:'include', ...})`
  dentro do `javascript_tool` do Browser pane (isso passa pelo fluxo real de `Set-Cookie`, que o
  navegador aceita normalmente — só a escrita DIRETA via `document.cookie` que é bloqueada), (3)
  depois de terminar, apagar a conta de teste E a linha correspondente em `admin_sessoes`
  (não deixar sessão/conta de teste pra trás). Alternativa mais rápida se só precisar validar
  uma rota pontual (sem UI): mintar um token direto (`webapp.admin.auth.criar_sessao(conn,
  usuario_id)`) e mandar via `curl -b "admin_session=<token>"` — mais simples que navegador
  quando não precisa ver a tela renderizada.

## Painel de Admin (`/admin`)

Área administrativa com contas individuais de verdade (login + senha com hash), que
substituiu o antigo login único compartilhado (`SITE_PASSWORD`/HTTP Basic). O backend
(`webapp/admin/`) continua um pacote isolado e removível, MAS — mudança de escopo aprovada
explicitamente pelo usuário em 2026-09-10 — o login do SITE PRINCIPAL também passou a
depender da mesma tabela `admin_usuarios`. Isso é uma EXCEÇÃO documentada à segregação
original (ver "Acoplamento com o site principal" abaixo): o painel em si continua isolado
(arquivos próprios, tabelas próprias), mas removê-lo sem reverter esse acoplamento primeiro
quebraria o login do site inteiro.

**Estrutura (arquivos próprios, pacote `webapp/admin/`)**:
- `auth.py`: hash de senha PBKDF2, geração de hash (`gerar_hash_senha`, usada ao criar conta
  pelo painel), verificação de credenciais (`autenticar_credenciais`, compartilhada entre o
  login do painel e o do site principal), sessão por token opaco (`admin_sessoes`),
  `exigir_admin` (dependency do painel — exige role='admin'), `verificar_acesso_principal`
  (gate do site principal — qualquer role, usado por `webapp/main.py::_verificar_acesso`),
  `registrar_acesso` (log de login/logout).
- `routes.py`: `APIRouter` com as rotas `/api/*` do painel (comentário no topo com o passo a
  passo de remoção, incluindo a ressalva do acoplamento).
- `seed.py`: script de migração/seed (schema + contas seed), roda manualmente
  (`python webapp/admin/seed.py`), idempotente, nunca automático/no startup da webapp.
- Frontend em arquivos próprios (nunca dentro do `index.html`/`common.js` da SPA principal):
  `webapp/static/admin.html` + `admin.js` + `css/admin.css` (reaproveita as variáveis de cor
  de `style.css`, importado antes). Página própria, não uma 6ª aba da SPA.
- `webapp/main.py` importa de `webapp/admin/auth.py` (ver "Acoplamento" abaixo) e inclui o
  router (`app.include_router(admin_router, prefix="/admin")`, logo após `STATIC_DIR`). Como
  o prefixo é `/admin` (nunca `/api`), as rotas do painel não passam pelo gate do site
  principal — são dois conjuntos de rotas distintos, com dependencies diferentes
  (`exigir_admin` exige role='admin'; o gate do site aceita qualquer role).
  Há também um pequeno ajuste dentro do catch-all `spa_pagina()`, só pro modo local
  (`uvicorn`): sem ele, esse catch-all intercepta `/admin.html` e devolve 404 mesmo o arquivo
  existindo — não é problema no deploy hospedado, onde `vercel.json` resolve `/admin` direto
  na CDN.
- `vercel.json` tem 2 rewrites próprios: `/admin` → `/admin.html` e `/admin/api/(.*)` → `/api`
  (sem o segundo, as chamadas `/admin/api/*` nunca chegariam na function serverless — só o
  rewrite `/api/(.*)` original existia).

**Tabelas** (nenhuma referenciada por `operations`/`linhas_incentivadas`/`editais_raw` nem o
contrário — criadas/migradas só por `webapp/admin/seed.py`, NUNCA pelo `SCHEMA`/
`MIGRACOES_COLUNAS` de `src/db.py`, que continua inteiramente intocado):
- `admin_usuarios`: `id`, `username` (unique), `password_hash`, `role` (`'admin'` |
  `'usuario'` — coluna adicionada depois via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
  default `'admin'` pra não quebrar a conta que já existia antes dessa migração), `ativo`,
  `criado_em`.
- `admin_sessoes`: `token` (PK), `usuario_id` (`ON DELETE CASCADE`), `criado_em`, `expira_em`.
- `admin_acessos_log`: V1 do "log de acessos" pedido pelo usuário — **só login/logout**, não
  navegação/cliques dentro da página (isso seria uma V2, não construída ainda — analytics de
  verdade é um projeto à parte, precisa de escopo confirmado antes). Colunas: `usuario_id`
  (`ON DELETE SET NULL`), `username_snapshot` (texto — garante que o log continua legível
  mesmo depois de um usuário ser EXCLUÍDO de verdade, sem precisar reconstituir via join),
  `origem` (`'site'` | `'admin'`), `evento` (`'login'` | `'logout'`), `ip`, `criado_em`.

**Papéis (`role`)**: `admin` acessa o painel `/admin` E o site principal (superset).
`usuario` só acessa o site principal — tentar logar em `/admin/api/login` com uma conta
`usuario` devolve 403; tentar acessar qualquer rota `/admin/api/*` com uma sessão `usuario`
devolve 401 (`exigir_admin` confere o role a cada requisição, não só no login).

**Acoplamento com o site principal (exceção documentada à segregação)**: `webapp/main.py`
importa `verificar_acesso_principal`/`autenticar_credenciais`/etc. de `webapp/admin/auth.py`
e expõe `/api/login`+`/api/logout` (rotas do SITE, não do painel — mesma tabela de contas,
qualquer role). `_verificar_acesso` (gate global de `/api/*`) chama
`verificar_acesso_principal`, que abre uma conexão e resolve dois casos: (1) nenhuma conta em
`admin_usuarios` ainda (banco novo/dev local sem seed) → acesso livre, mesmo espírito de
antes sem `SITE_PASSWORD`; (2) pelo menos uma conta existe → exige sessão válida (cookie
`admin_session`, path `/` — COMPARTILHADO entre painel e site, diferente da versão inicial
deste painel que usava `path=/admin`). Login do site (`common.js::_tentarLogin`) virou um
POST JSON pra `/api/login` (cookie httponly de volta) em vez de HTTP Basic +
`Authorization` header guardado em `sessionStorage` — `fetchJSON`/`postJSON` não montam mais
nenhum header manual, o cookie viaja sozinho via `credentials:"include"`.
**Se o painel de admin for removido**: reverter esse acoplamento (voltar `_verificar_acesso`
pra algum mecanismo de auth do site principal) ANTES de apagar as tabelas/pacote — ver
comentário no topo de `webapp/admin/routes.py`.

**Sessão/senha**: hash `pbkdf2_sha256$<iterações>$<salt_base64>$<hash_base64>`
(PBKDF2-HMAC-SHA256, 600.000 iterações), comparado com `hmac.compare_digest` (nunca `==`).
Sessão = token opaco (`secrets.token_urlsafe`) gravado em `admin_sessoes` com expiração
(24h), cookie `admin_session` (httponly, `secure` quando `VERCEL` está definido,
`samesite=strict`, `path=/`) — nunca JWT/cookie assinado client-side, validade sempre
conferida contra a linha em `admin_sessoes` no backend. Desativar um usuário invalida a
sessão dele na hora (`exigir_admin`/`verificar_acesso_principal` conferem `ativo` a cada
requisição) — testado ao vivo: desativar o próprio usuário logado derruba a sessão
imediatamente, sem esperar o cookie expirar.

**BUG REAL encontrado e corrigido em 2026-09-10, ANTES de ir pra produção**: o cookie de
sessão migrou de `path="/admin"` (versão inicial deste painel) pra `path="/"` (quando o
site principal passou a compartilhar a sessão). Contas que já tinham logado no painel
`/admin` ANTES dessa migração de path continuam com o cookie antigo (`path=/admin`)
guardado no navegador; um login novo grava um SEGUNDO cookie de mesmo nome
(`admin_session`) com `path="/"` — o navegador manda os DOIS num request que bate os dois
paths (qualquer rota `/admin/*`), e o parser de cookie do Starlette (`cookie_parser` em
`starlette/requests.py`) é só um `dict` preenchido em ORDEM DE ITERAÇÃO da string
`Cookie:` recebida — **last-write-wins, sem nenhuma lógica de especificidade de path**
(confirmado lendo o código-fonte e reproduzido ao vivo: mandar
`Cookie: admin_session=<valido>; admin_session=<invalido>` num request cru derruba a
sessão mesmo com o token válido presente, só porque veio primeiro na string). Como a
ordem que o navegador decide mandar cookies duplicados não é algo que o backend controla,
isso derrubava a sessão de forma imprevisível logo depois de um login bem-sucedido.
**Corrigido** em `definir_cookie_sessao`/`limpar_cookie_sessao`
(`webapp/admin/auth.py`): toda vez que uma sessão é criada OU encerrada, o cookie no path
antigo (`/admin`) é explicitamente expirado (`Max-Age=0`) na MESMA resposta — depois do
primeiro login/logout no esquema novo, o navegador nunca mais tem os dois ao mesmo tempo.
**Lição pra qualquer migração futura de `path`/`domain` de cookie**: nunca só trocar o
path do `set_cookie` — sempre expirar explicitamente o cookie no path antigo também,
senão qualquer sessão já ativa antes da mudança fica com as duas versões coexistindo.

**Gestão de usuários (CRUD)**: `POST /admin/api/usuarios` cria conta nova (hash gerado na
hora via `gerar_hash_senha`, senha em texto puro nunca persistida/logada/devolvida);
`POST /admin/api/usuarios/{id}/ativo` ativa/desativa (soft); `DELETE /admin/api/usuarios/{id}`
exclui de verdade. **Guarda do último admin**: nenhuma das duas últimas rotas permite
desativar/excluir um `role='admin'` se ele for o ÚLTIMO admin ativo restante — evita travar
o painel inteiro sem ninguém pra reativar ninguém. Na prática só é alcançável no caso de
autoexclusão/autodesativação (quem chama a rota já precisa ser um admin ativo, então excluir/
desativar um admin QUE NÃO seja você mesmo nunca zera a contagem).

**Trocar papel de uma conta existente** (`POST /admin/api/usuarios/{id}/role`, aprovado
2026-09-16): até aqui `role` só era definido na CRIAÇÃO da conta (`POST /admin/api/usuarios`)
— esta rota promove/rebaixa uma conta já existente entre `admin`/`usuario`. Aplica a MESMA
guarda do último admin já usada em ativar/desativar e excluir (`_contar_admins_ativos`): não
deixa rebaixar (`admin` → `usuario`) o ÚLTIMO admin ativo restante. UI: botão na tabela de
usuários que alterna o texto ("Promover a admin" / "Rebaixar a usuário") conforme o papel
atual, com `confirm()` nativo antes de aplicar.

**Reset administrativo de senha** (`POST /admin/api/usuarios/{id}/senha`, aprovado
2026-09-16): admin troca a senha de QUALQUER usuário (não é fluxo de "esqueci minha senha" —
não exige a senha antiga). Mesmo esquema de hash de sempre (`gerar_hash_senha`), valida
≥8 caracteres (mesmo padrão de `/api/registrar`). **Ao trocar, invalida TODAS as sessões
ativas daquele usuário na hora** (`DELETE FROM admin_sessoes WHERE usuario_id = ?`) — testado
ao vivo: uma sessão aberta antes da troca perde acesso imediatamente, sem esperar o cookie
expirar (mesma lógica de segurança já usada em "desativar um usuário", ver acima). UI: botão
"Alterar senha" na tabela de usuários (CRUD normal), usa `prompt()` nativo pra digitar a
senha nova — sem modal dedicado, consistente com o `confirm()` nativo já usado por "Excluir".

**Contas seed** (inseridas por `seed.py`, hashes já prontos — senha em texto puro nunca
passou pelo código/commit/log): `admin` (role `admin`) e `artica` (role `usuario`).

**Botões de ação (aprovados junto com o CRUD, 2026-09-10)**:
- **"Atualizar agora" (operações/editais)**: rodar `src/refresh.py`/`refresh_editais.py`
  dentro de uma function serverless da Vercel é inviável (timeout de segundos/poucos minutos
  contra um pipeline que pode levar até 180min) — os botões chamam a API do GitHub
  (`POST /repos/{repo}/actions/workflows/{arquivo}/dispatches`) pra disparar os workflows
  reais (`refresh-operacoes.yml`/`refresh-editais.yml`, já tinham `workflow_dispatch: {}`
  habilitado). Precisa de um Personal Access Token do GitHub (escopo `actions:write` no
  repo) numa env var **`GITHUB_ACTIONS_TOKEN`** — **só o usuário pode criar esse token e
  configurar na Vercel**, o painel não tem como gerar isso sozinho; sem a env var, o botão
  mostra um erro claro em vez de quebrar (testado ao vivo). Salvaguarda: antes de disparar,
  confere `refresh_log`/`refresh_editais_log` por uma execução com `finished_at IS NULL`
  (em andamento) e bloqueia com 409 se houver, pra evitar clique duplo/concorrência (dado o
  incidente de disco cheio documentado abaixo).
- **"Processar próximo lote" (CNPJs pendentes)**: reaproveita
  `enrich_cnae.py::enrich_pendentes_via_api` + `unify.py::reclassificar_pendentes` (MESMO
  código do refresh semanal), em lotes pequenos (20 por clique, configurável) pra não
  estourar o timeout de uma function serverless — cada CNPJ leva ~0.6s (rate limit da
  BrasilAPI) + rede. **Achado real testando ao vivo**: as 552 operações pendentes na base
  hoje têm TODAS `cnpj IS NULL` — esse botão (e o enriquecimento incremental do próprio
  refresh semanal, que usa a mesma query) não tem como resolver nenhuma delas, já que
  dependem de CNPJ pra consultar a BrasilAPI. Não é um bug deste botão; é uma característica
  real dos dados pendentes atuais — resolver isso precisaria de uma estratégia diferente
  (não baseada em CNPJ) pra esse subconjunto especificamente, fora do escopo desta mudança.

**Log de acessos**: seção própria no painel (`GET /admin/api/acessos`), lista os últimos 100
eventos de login/logout (site + painel), com usuário, origem, IP e timestamp.

**Saúde do banco (proxy)** (`GET /admin/api/saude-banco`, aprovado 2026-09-10): tamanho lógico
(`pg_database_size`), conexões abertas (`pg_stat_activity`) e as 10 tabelas com mais bloat
(`n_live_tup`/`n_dead_tup`/`last_vacuum`/`last_autovacuum` via `pg_stat_user_tables`). **Não é
o % de disco oficial da Aiven** — aquele conta WAL/backup e só existe no console.aiven.io
(exigiria a API deles, token novo, ação do usuário); a UI deixa esse aviso explícito de
propósito, pra não criar falsa sensação de precisão. Foi construindo/testando esta seção que o
bug real das sequences dessincronizadas (ver "Coisas a saber antes de mexer") foi descoberto.

**Correções manuais** (`/admin/api/correcoes*` + `/admin/api/operacoes/buscar`, aprovado
2026-09-10): tela sobre `operations_correcoes_manuais` que já existia (ver `src/db.py`) — só
uma UI nova, nenhuma lógica duplicada. Busca operação por id exato ou cliente (ILIKE), escolhe
um dos campos corrigíveis (`unify.CAMPOS_CORRIGIVEIS`) e reaproveita
`unify.py::registrar_correcao_manual` (a MESMA função que
`webapp/main.py::enriquecimento_corrigir` já usava) pra aplicar e gravar o histórico.
**Campos expandidos (2026-09-16, pedido do usuário)**: `CAMPOS_CORRIGIVEIS` tinha só
`setor_bndes`/`subsetor_bndes`/`segmento` — ganhou `uf`/`municipio`/`cliente`/`cnpj`. O
mecanismo já era genérico (o `UPDATE operations SET {campo} = ?` em `registrar_correcao_manual`
é f-string, mas `campo` só chega ali depois de validado contra a whitelist, então nunca é
entrada livre) — só precisou adicionar os 4 nomes ao set. `_atualizar_textos_apos_correcao`
(mesmo arquivo) já recalculava busca/embedding depois de QUALQUER correção, incluindo esses
campos, então a busca já reflete corretamente uma correção de cliente/cnpj/uf/município sem
mudança nenhuma ali. Achado real ao expandir: `/admin/api/operacoes/buscar` (usado pra
pré-preencher o formulário) não devolvia `uf`/`municipio` no resultado — corrigir esses dois
campos pré-preenchia com `undefined` até isso ser corrigido (adicionados ao `SELECT`/retorno).
**Cuidado com `cnpj`**: corrigir esse campo NÃO dispara reclassificação automática de setor
com o CNPJ novo — isso só acontece no próximo refresh/enriquecimento, e mesmo assim só se
`setor_origem='pendente'`. É só uma correção do dado bruto (ex: typo), não uma feature de
"corrigir CNPJ pra re-enriquecer setor" — se um dia isso for pedido, é trabalho novo, não uma
consequência automática desta mudança.
"Desativar" só marca `ativa=FALSE` (nunca `DELETE` — é histórico) e não reverte o valor já
aplicado em `operations`; isso só muda o que o próximo refresh semanal vai (deixar de)
reforçar (`unify.py::_reaplicar_correcoes_manuais`). **UX ajustada 2026-09-10** (feedback real
do usuário testando em produção): a lista de resultados da busca fica ABERTA/VISÍVEL o tempo
todo (não fecha ao selecionar uma operação, pra corrigir várias em sequência), e cada
resultado tem um ícone de caneta (✏️) que abre o formulário JÁ PREENCHIDO com o valor ATUAL
do campo escolhido (troca de campo no select atualiza o valor mostrado) — o usuário edita em
cima em vez de digitar do zero. **Decisão explícita**: nenhum mecanismo de "sugestão
automática" de correção foi construído (o usuário pediu pra clarificar antes de inventar uma
heurística — confirmado via pergunta direta: sem sugestão automática por enquanto, só
busca+edição manual).

**BUG REAL em produção corrigido em 2026-09-10 (500 no "enriquecer pendentes")**: a rota
`POST /admin/api/enriquecer-pendentes` funcionava local mas quebrava com 500 no deploy
hospedado. Causa: ela chama `unify.py::reclassificar_pendentes()`, que usa
`db.get_engine()` (SQLAlchemy, via `pd.read_sql`) — mas `api/requirements.txt` excluía
`sqlalchemy` de propósito, com um comentário explícito dizendo "webapp/main.py nunca chama
get_engine()". Essa suposição deixou de ser verdadeira quando este botão do painel de admin
passou a chamar esse código de dentro da function serverless. **Corrigido** adicionando
`sqlalchemy` a `api/requirements.txt` (comentário atualizado explicando a exceção) + a rota
agora captura qualquer exceção do processamento do lote e devolve uma mensagem clara em vez
de deixar o 500 cru vazar (defesa em profundidade, cobre também falha de rede da BrasilAPI
etc). **Lição**: ao adicionar uma rota nova em `webapp/admin/routes.py` que importa algo de
`src/` (mesmo que via outro módulo, ex: `unify.py` → `db.get_engine()`), sempre reconferir
`api/requirements.txt` — o comentário no topo daquele arquivo documenta o grafo de imports
assumido, e uma rota nova pode quebrar essa suposição silenciosamente (só falha no ambiente
hospedado, nunca em dev local com o `requirements.txt` completo).

**Drill-down por usuário** (`GET /admin/api/usuarios/{id}/acessos`, aprovado 2026-09-10):
clicar no username na tabela "Usuários do painel" abre um modal com o histórico de
login/logout DAQUELA pessoa — total de logins, primeiro/último acesso, lista de eventos.
Reaproveita `admin_acessos_log` (só filtra por `usuario_id`), nenhuma tabela nova nem
tracking novo — explicitamente MENOR que uma V2 de analytics (que continua fora do escopo,
ver acima). **V2 construída depois (2026-09-16), pedido explícito do usuário confirmando o
que antes estava marcado como fora de escopo** — ver bloco abaixo.

**Log de navegação por aba + histórico de busca no drill-down (V2, aprovado 2026-09-16)**:
o mesmo modal de drill-down por usuário passou a reunir 3 fontes:
1. **Login/logout** (já existia, `admin_acessos_log`).
2. **Navegação por aba** (`evento='view_aba'`) — NÃO virou tabela nova; reaproveita
   `admin_acessos_log` com uma coluna genérica nova, `detalhe` (`ALTER TABLE ... ADD COLUMN
   IF NOT EXISTS detalhe TEXT`, NULL pra login/logout, guarda o nome da aba pra
   `view_aba` — pensada pra qualquer evento futuro reaproveitar, não só este). Gravado por
   `POST /api/eventos/navegacao` (rota nova, `webapp/main.py`), chamada por
   `common.js::_ativarView()` só quando `obterUsuarioAtual()` resolve pra um usuário real E
   a troca de aba é de verdade (`mudouDeAba` — não duplica evento reabrindo a mesma aba já
   ativa) — fire-and-forget (`.catch(() => {})`), nunca atrasa nem trava a troca de aba em
   si, e o backend (`registrar_navegacao`) também nunca deixa uma falha de log virar erro
   pro cliente (best-effort dos dois lados, mesmo espírito de
   `_registrar_busca_se_logado`/histórico de busca).
3. **Histórico de busca** (`usuario_busca_historico`, já existia pra Transações Salvas —
   ver seção própria abaixo) — só exposto no mesmo endpoint/modal via
   `salvos.listar_busca_historico`, nenhuma duplicação de lógica.

**Cuidado real de volume, levantado ANTES de construir**: navegação por aba gera MUITO mais
linhas que login/logout (uma por troca de aba, de cada usuário logado, toda visita) — bem
diferente do volume de login/logout. Duas decisões tomadas por causa disso:
- **`GET /admin/api/acessos`** (a lista GERAL do painel, "últimos 100 acessos" de TODOS os
  usuários) continua filtrando `WHERE evento IN ('login', 'logout')` — `view_aba` NUNCA
  aparece ali, só no drill-down POR PESSOA. Sem esse filtro, poucos minutos de uso normal já
  afogariam o sinal de "quem entrou/saiu" que essa lista existe pra mostrar.
- O drill-down por pessoa (`GET .../usuarios/{id}/acessos`) mistura os 3 tipos de evento na
  mesma lista, mas continua limitado a 200 linhas mais recentes (mesmo teto que já existia
  pra login/logout sozinho) — **sem paginação ainda**. Não é um problema resolvido de vez,
  só o suficiente pro escopo pedido agora; se o volume real crescer a ponto de 200 linhas
  cobrirem só alguns minutos de navegação de um usuário ativo, vale reconsiderar
  paginação/retenção/agregação nessa tabela antes de crescer mais.

**Cadastro público com aprovação** (`POST /api/registrar` + `/admin/api/usuarios/pendentes`
+ `/{id}/aprovar`/`/{id}/rejeitar`, aprovado 2026-09-15): a tela de login do SITE PRINCIPAL
(`#login-overlay` em `index.html`) ganhou um segundo formulário (`#registrar-card`, alternado
via botão "Criar conta" — `common.js::_mostrarRegistrarOverlay`/`_voltarParaLogin`) pra
qualquer visitante pedir uma conta nova, sem precisar de um admin criar na mão.
- **Schema**: nova coluna `admin_usuarios.status` (`'pendente'` | `'aprovado'` |
  `'rejeitado'`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ... DEFAULT 'aprovado'` — MESMO
  padrão de `role`, ver `seed.py`) — default `'aprovado'` garante que toda conta que já
  existia antes desta migração (seed + criadas pelo CRUD do painel) continua logando
  normalmente sem aprovação retroativa nenhuma. Nenhuma tabela nova.
- **`POST /api/registrar`** (rota pública, adicionada a `_ROTAS_PUBLICAS_API` em
  `webapp/main.py`): valida username único + senha ≥8 caracteres, gera o hash na hora
  (`gerar_hash_senha`, MESMA função usada pelo CRUD do painel — senha em texto puro nunca
  persistida/logada), insere com `role='usuario'` **sempre** (nunca `'admin'` — promover a
  admin continua sendo uma ação manual separada, via CRUD) e `status='pendente'`.
- **Login com conta não aprovada**: `autenticar_credenciais` (`webapp/admin/auth.py`) devolve
  o usuário mesmo com `status` diferente de `'aprovado'` (não filtra na query) — quem chama
  (login do site em `webapp/main.py::site_login` E login do painel em
  `webapp/admin/routes.py::login`) checa `mensagem_status_bloqueado(status)` DEPOIS de
  validar a senha, e devolve uma mensagem especifica ("Sua conta ainda não foi aprovada por
  um administrador." / "Sua solicitação de conta foi rejeitada.") em vez do genérico "usuário
  ou senha incorretos" — dá pra saber a diferença entre "esqueci minha senha" e "minha conta
  está pendente" sem vazar se o USERNAME existe (a mensagem só aparece depois da senha bater).
  `_tentarLogin` (`common.js`) foi ajustado pra devolver `{ok, mensagem}` em vez de só um
  booleano, propagando a mensagem real do backend pro usuário.
- **Aprovação/rejeição**: nova seção "Contas pendentes de aprovação" no painel (própria,
  separada do CRUD normal — `GET /admin/api/usuarios/pendentes`), com botões Aprovar/Rejeitar
  (`POST .../aprovar` ou `.../rejeitar`, só mudam `status`, nunca `role`/`ativo`). O CRUD
  normal (`GET /admin/api/usuarios`) agora filtra `status != 'pendente'` — contas pendentes
  só aparecem na seção de aprovação, nunca na lista normal (evita confundir "editar uma conta
  existente" com "decidir sobre um pedido novo").
- **E-mail no cadastro** (2026-09-15, pedido à parte): coluna `admin_usuarios.email` (`ALTER
  TABLE ... ADD COLUMN IF NOT EXISTS email TEXT`, SEM default — contas antigas ficam com
  `email` NULL, sem problema — e SEM constraint de unicidade, já que não há verificação de
  posse/entrega). `POST /api/registrar` exige o campo e valida formato BEM simples (checa
  `"@"` na string e `"."` na parte depois do `@`) — **deliberadamente não** valida entrega
  nem envia nenhum e-mail; o usuário perguntado diretamente confirmou que só quer o dado
  coletado e visível pro admin, nenhuma integração de envio. Mostrado como coluna própria na
  seção "Contas pendentes de aprovação" do painel, ao lado do username, pra quem for
  aprovar/rejeitar já ver o e-mail junto.

**BUG REAL encontrado e corrigido no merge (2026-09-15)**: `#login-card`/`#registrar-card`
nunca tinham uma regra `.hidden { display: none }` própria em `style.css` — só
`#login-overlay.hidden` existia. Resultado: `_mostrarRegistrarOverlay()`/`_voltarParaLogin()`
trocavam a classe certinho, mas SEM efeito visual nenhum — os dois formulários ficavam
sempre visíveis lado a lado, sobrepostos (confirmado ao vivo, capturado em screenshot antes
do fix). Corrigido adicionando `#login-card.hidden, #registrar-card.hidden { display: none; }`
junto de `#login-overlay.hidden` no topo do bloco de estilos do login. **Lição**: toda vez que
um elemento novo usa `class="hidden"` pra alternar visibilidade, confirmar que existe uma
regra CSS `#id.hidden`/`.classe.hidden { display: none }` correspondente — este projeto não
tem uma regra `.hidden` genérica (cada uso é escopado ao próprio seletor, ver os outros usos
de `.hidden` espalhados por `style.css`), então um elemento novo SEMPRE precisa da sua própria
regra, nunca herda de outro.

**Usuário logado + Sair no site principal** (`webapp/static/index.html`/`common.js`, natural
depois do acoplamento do login): o texto "N operações · atualizado em ..." que morava no canto
superior direito da topbar principal migrou pra uma faixa fina própria (`.status-strip`) logo
abaixo — o espaço que abriu no canto da topbar virou usuário logado + botão "Sair" (mesmo
padrão visual do painel de admin), alimentado por um novo `GET /api/me` (site, não confundir
com `GET /admin/api/me`, do painel). **Essa faixa (`.status-strip`) foi removida depois
(2026-09-11)** — pedido do usuário: o texto (`#status-pill`) passou a viver DENTRO da
`.filterbar` (barra branca de filtros), empurrado pro canto direito via `margin-left:auto`,
em vez de numa faixa escura própria. Como `.filterbar` só é exibida (`display:flex`, ver
`_ativarView` em `common.js`) nas abas Consolidado/Tendências, esse texto agora só aparece
nessas duas — nas outras 3 (Busca/Editais/Linhas, que nunca mostraram essa barra) ele
simplesmente não aparece, consequência direta e esperada de tê-lo colocado dentro dela.

**Como remover o painel inteiro** (ver também o comentário no topo de
`webapp/admin/routes.py`): 1) reverter o acoplamento do login do site principal (ver acima)
ANTES de tudo; 2) `DROP TABLE admin_sessoes; DROP TABLE admin_acessos_log; DROP TABLE
admin_usuarios;`; 3) apagar a pasta `webapp/admin/` + `webapp/static/admin.html`/`admin.js`/
`css/admin.css`; 4) remover a linha de include em `webapp/main.py` (e o ajuste em
`spa_pagina()`); 5) remover as 2 entradas de rewrite de `vercel.json`. Fora essa exceção
documentada, nada disso toca em `operations`, `linhas_incentivadas` ou `editais_raw`.

## Transações Salvas (favoritos de operação + histórico de busca por usuário)

Aba própria (`webapp/static/js/salvos.js`, rotas `/api/salvos*`, backend em `webapp/salvos.py`)
adicionada em 2026-09-15, DEPOIS que o login por conta individual (`admin_usuarios`, ver seção
"Painel de Admin" acima) já estava valendo pro site inteiro. Duas coisas, as duas escopadas por
CONTA LOGADA (nunca por navegador/dispositivo — decisão de produto explícita do usuário:
"individualizar os históricos, favoritos, entre outros"):

1. **Favoritar uma operação** (`usuario_operacoes_salvas`: `usuario_id`, `operation_id` — FK
   de verdade pra `operations(id)`, `ON DELETE CASCADE` —, `nota` opcional, `criado_em`, UNIQUE
   `(usuario_id, operation_id)`). Botão ☆/★ (`#modal-favoritar-btn`) embutido no MESMO modal de
   detalhe de operação que já existia (`common.js::openOperacaoDetalhe`/
   `_configurarBotaoFavoritar`) — reaproveitado de qualquer lugar que já abre esse modal (Busca,
   tabela de operações, grupo econômico), não duplicado por página. Os outros 3 lugares que
   reusam o MESMO elemento de modal (`openOperacoesModal`, detalhe de edital, detalhe de linha
   incentivada) escondem o botão explicitamente ao abrir — ele só faz sentido no detalhe de UMA
   operação. Nota pessoal é um campo de texto livre por operação salva, só o dono vê
   (`textarea` com `PATCH /api/salvos/operacoes/{id}`, salva no `blur`).
   **Estrutura pensada pra uma extensão futura** (pedido explícito do usuário, não implementada
   ainda): "buscar por empresa" a partir das operações salvas — como `usuario_operacoes_salvas`
   só guarda `operation_id` e a tabela `operations` já tem `cnpj`/`cliente`, listar/agrupar as
   operações salvas por empresa é um JOIN direto (`listar_operacoes_salvas` já devolve esses
   campos hoje), sem precisar de coluna nova nem migração.
   **Estrelinha mini em cada card da Busca** (2026-09-16, `webapp/static/js/busca.js`,
   `.fav-btn-mini` em `style.css`): favoritar sem precisar abrir o modal de detalhe — um
   botão pequeno, posicionado absoluto no canto superior direito de cada `.result-card`,
   visível só no `:hover` do card (`opacity:0` → `1`), EXCETO quando a operação já está
   salva (`.fav-btn-mini.ativo` fica sempre visível, senão não haveria como notar que já
   está salva sem passar o mouse por cima). Clique tem `stopPropagation()` (o card já tem
   seu próprio `click` que abre o modal — os dois nunca podem disparar juntos) e reusa a
   MESMA lógica de alternar favorito que o botão do modal usa
   (`common.js::alternarFavoritoOtimista`, extraída dos dois pra não duplicar a chamada a
   `POST`/`DELETE /api/salvos/operacoes/{id}`). **Problema técnico resolvido antes de
   implementar**: pra saber o estado inicial (★/☆) de até 200 resultados de uma vez, sem
   200 checagens individuais, existe uma rota em lote —
   `GET /api/salvos/operacoes/ids` (`webapp/main.py::salvos_ids` +
   `salvos.py::listar_ids_salvos`) devolve só os `operation_id` já salvos do usuário
   logado; `busca.js` chama isso 1x por busca (`_carregarIdsSalvos()`, dentro de
   `runBusca()`, nunca em `renderListaResultados()` — que também roda a cada troca de
   ordenação, sem precisar buscar de novo) e cruza localmente com `ultimosResultados`.
   Dependency OPCIONAL (`_usuario_atual`, não `_exigir_usuario_logado`) nessa rota
   especificamente: ninguém logado devolve `{"ids": []}` em vez de 401, pra Busca
   continuar funcionando igual pra visitante anônimo (raro em produção, já que
   `_verificar_acesso` — gate global — já barra `/api/*` inteiro assim que existe pelo
   menos uma conta; na prática só importa no caso de sessão expirar NO MEIO do uso, onde
   o catch de `_carregarIdsSalvos()` já cobria isso de qualquer forma). **Limitação aceita
   de propósito**: a lista de resultados já renderizada na tela NÃO se atualiza sozinha se
   a mesma operação for favoritada pelo OUTRO caminho (o botão do modal) — só uma busca
   nova (`runBusca()`) re-consulta `/api/salvos/operacoes/ids` e re-renderiza os cards.
   Isso nunca causa inconsistência de DADO (o backend faz upsert idempotente dos dois
   lados), só um estado visual estático até a próxima busca — mesmo espírito de "as duas
   fontes não se misturam" já documentado no item 2 abaixo pro histórico de busca.
   **UI otimista + animação de "pop"** (2026-09-16, `common.js::alternarFavoritoOtimista`):
   ambos os botões de favoritar (modal E estrelinha mini) pintavam o novo estado (★/☆) SÓ
   depois da resposta do `POST`/`DELETE` voltar — perceptível como um clique "travado"/com
   delay contra a latência real do Aiven (ver "Coisas a saber antes de mexer" acima).
   Corrigido: `renderizar(novoEstado)` (callback fornecido por cada chamador — texto+classe
   no modal, só ícone+título+classe na mini) roda IMEDIATAMENTE no clique, ANTES de
   `await`ar a chamada à API; se a chamada falhar (`ErroAutenticacao` ou qualquer outro
   erro), reverte pra `renderizar(estavaAtiva)` e mostra o mesmo alerta de sempre — o
   servidor continua sendo a fonte da verdade, só a PINTURA acontece adiantada.
   **Verificado ao vivo simulando alta latência** (`time.sleep()` temporário nas rotas
   `POST`/`DELETE /api/salvos/operacoes/{id}`, removido depois do teste): o botão já
   reflete o novo estado antes da requisição completar (confirmado comparando o timestamp
   da mudança visual com o da resposta de rede); e simulando falha (sessão invalidada no
   meio do clique) o botão reverte pro estado anterior + mostra o alerta de login, como
   esperado. Acompanha um "pop" rápido e discreto (`@keyframes fav-pop`, `transform:
   scale(1) -> scale(1.18) -> scale(1)`, 0.2s, reiniciado via remove+reflow+readiciona a
   classe `.fav-pop` — funciona mesmo em cliques rápidos em sequência) disparado nas DUAS
   direções (favoritar e desfavoritar, inclusive no revert de uma falha) — mesma família de
   timing das outras transitions de 0.15s já usadas no site (`.fav-btn`/`.fav-btn-mini`),
   sem inventar um ritmo novo.
2. **Histórico de busca no SERVIDOR** (`usuario_busca_historico`: `usuario_id`, `query`,
   `fixada` BOOLEAN, `criado_em`) — grava a cada busca de um usuário LOGADO
   (`webapp/main.py::_registrar_busca_se_logado`, chamado tanto pela rota GET padrão sem IA
   quanto pela rota POST do modo IA opcional). Upsert por texto da query (case-insensitive):
   pesquisar a MESMA query de novo só atualiza `criado_em`, nunca duplica linha
   (`salvos.py::registrar_busca_historico`). Uma entrada pode ser FIXADA (`fixada=TRUE`) pra
   ficar no topo da lista independente de recência — `listar_busca_historico` ordena
   `fixada DESC, criado_em DESC`. Na aba Transações Salvas, cada item tem "Buscar de novo"
   (preenche a query na aba Busca e dispara `runBusca()`), "Fixar"/"Desafixar" e "Remover";
   "Limpar não fixadas" (`DELETE /api/salvos/historico`) nunca apaga o que foi fixado —
   remoção de um item fixado é sempre individual, por decisão deliberada (nunca em massa por
   engano).
   **Decisão de escopo tomada nesta implementação, confirmada explicitamente com o usuário**:
   o histórico pessoal em `localStorage` da aba Busca (ver seção "Frontend: roteamento e abas"
   acima) CONTINUA existindo em paralelo, como fallback pra quando ninguém está logado — não
   foi substituído. As duas fontes não se misturam na UI: o chip-based history da aba Busca
   sempre lê/escreve local (`busca.js`), a lista da aba Transações Salvas sempre lê/escreve
   servidor (`salvos.js`) — ambas são alimentadas pela MESMA ação de buscar, cada uma pelo seu
   próprio caminho, sem um sincronizar o outro.

**Por que as tabelas não têm FK pra `admin_usuarios`** (mesma segregação já documentada na
seção "Painel de Admin"): `admin_usuarios` só existe depois que `webapp/admin/seed.py` roda —
uma FK de verdade em `usuario_operacoes_salvas`/`usuario_busca_historico` (definidas em
`src/db.py`, junto do resto do schema `operations`) quebraria `init_db()` (chamado pelo
pipeline semanal via GitHub Actions, `src/refresh.py`) em qualquer ambiente onde
`admin_usuarios` ainda não existe. `usuario_id` aqui é só um INTEGER solto, mesmo padrão já
usado por `operations_correcoes_manuais.usuario` (esse é TEXT, não FK) — a validade do
`usuario_id` é garantida pelo backend, nunca pelo banco: toda rota de `/api/salvos/*` exige
`Depends(_exigir_usuario_logado)` (`webapp/main.py`), que resolve o usuário a partir do MESMO
cookie de sessão (`admin_session` → `admin_sessoes` → `admin_usuarios.id`) que
`_verificar_acesso`/`verificar_acesso_principal` já usam pro gate geral de `/api/*` — ou seja,
`usuario_id` vem sempre de uma sessão de conta real validada no servidor, nunca de um
identificador de dispositivo/navegador/sessão anônima enviado pelo cliente. Isso é o que
garante o isolamento entre contas (testado ao vivo: duas contas de teste diferentes, cada uma
só via os próprios favoritos/histórico).

**Lembrete de infraestrutura pra quem for aplicar isso num ambiente novo**: como `init_db()`
só é chamado pelos scripts de pipeline (nunca pela webapp em runtime), as duas tabelas novas só
passam a existir de fato depois de rodar `python src/db.py` manualmente (ou o próximo
`refresh.py`/`refresh_editais.py` agendado) contra o `DATABASE_URL` daquele ambiente — mesmo
padrão de qualquer mudança de schema neste projeto, nada automático no deploy da Vercel.

## Radar de Crédito Primário — Pipeline CVM

Segundo "modo" da plataforma, construído a partir de 2026-09-16, cobrindo o **mercado de
capitais primário brasileiro** (debêntures, CRI, CRA, notas comerciais/promissórias, letras
financeiras, CDCA, CCB) — complementa o crédito incentivado de fomento (BNDES/FINEP) com o
outro grande canal de captação de dívida das empresas brasileiras. **Esta seção documenta só a
CAMADA DE DADOS** (staging + tabela unificada `operations_primario`) — rotas `/api/primario/*`,
motor de busca e frontend são trabalho de sessões seguintes, construído em cima deste schema.

### Fonte: CVM — Portal de Dados Abertos, dataset "Ofertas Públicas de Distribuição"

Licença ODbL, mantido pela SRE/CVM (órgão regulador oficial), atualizado diariamente.
**ACHADO REAL (2026-09-16)**: a URL do dado esperada terminava em `.csv`
(`.../DADOS/oferta_distribuicao.csv`) — devolve 404 ao vivo. O arquivo de verdade é um `.zip`
no mesmo caminho (`oferta_distribuicao.zip`, ~5.3MB), que **contém DOIS CSVs** dentro (achado
real #2, também só confirmado baixando de verdade): `oferta_distribuicao.csv` (o dataset
pedido) E `oferta_resolucao_160.csv` (dataset relacionado mas diferente — RCVM 160, o rito de
oferta que sucedeu a ICVM 400/476, fora do escopo deste pedido). `src/download_cvm.py` extrai
por NOME do arquivo dentro do zip (nunca por posição/índice — a CVM não documenta nem garante
ordem estável dos membros do zip). Mesmo achado (zip com 2 membros) no `.zip` do dicionário de
dados (`meta_oferta_distribuicao.zip` → `meta_oferta_distribuicao.txt` +
`meta_oferta_resolucao_160.txt`). Encoding **latin-1** (não utf-8), delimitador `;` — confirmado
decodificando e reencodando uma amostra real (`"DEBÊNTURES SIMPLES"` decodifica certo com
`encoding="latin-1"`; o mojibake que aparece em terminais/logs ao longo deste processo é só a
própria console não sabendo renderizar utf-8, não corrupção do dado).

Dataset completo: ~48,9 mil linhas (TODAS as ofertas públicas já registradas/dispensadas desde
1989 — ações, cotas de fundo, BDR, CRI/CRA, debênture etc., republicado por inteiro a cada
atualização, sem filtro nenhum de data). Filtrando só instrumentos de DÍVIDA (ver escopo
abaixo): **12.239 linhas** (confirmado ao vivo, 2026-09-16), cobrindo 1989–2025.

### Instrumentos em escopo (`src/parse_cvm.py::_ESCOPO_REGEX`)

Filtro por regex com `\b` (word boundary) sobre `Tipo_Ativo` normalizado (sem acento,
maiúsculo) — bate tanto o nome por extenso quanto a sigla, mas com boundary nas siglas curtas
(CRI/CRA/CDCA/CCB) para não arriscar falso-positivo por substring cru. Contagem real por
`Tipo_Ativo` no CSV de 2026-09-16 (13 valores distintos observados, todos em escopo):
DEBÊNTURES SIMPLES (4.936), CERTIFICADOS DE RECEBÍVEIS IMOBILIÁRIOS - CRI (3.298), NOTAS
PROMISSÓRIAS (1.753), CERTIFICADOS DE RECEBÍVEIS DO AGRONEGÓCIO - CRA (839), CERTIFICADO DE
RECEBÍVEIS IMOBILIÁRIOS (710, grafia alternativa sem "S" — mesma coisa, mesmo regex bate as
duas), DEBÊNTURES CONVERSÍVEIS (222), CERTIFICADO DE RECEBÍVEIS DO AGRONEGÓCIO (182), NOTAS
COMERCIAIS (168), LETRAS FINANCEIRAS (115), CERTIFICADOS DE DIREITOS CREDITÓRIOS DO
AGRONEGÓCIO - CDCA (11), TOKENS REPRESENTATIVOS DE DEBÊNTURES/SANDBOX REGULATÓRIO (3), CÉDULAS
DE CRÉDITO BANCÁRIO - CCB (1), DEBÊNTURES PERMUTÁVEIS (1).

**Deliberadamente FORA de escopo**: ações, cotas/quotas de fundos (a maioria absoluta das ~49
mil linhas totais — FIDC/FIP/FII/fundo fechado etc., incluindo cotas SÊNIOR/SUBORDINADA de
FIDC, que tecnicamente financiam recebíveis mas são "fundo", não um título de dívida direto),
BDR, warrants (incl. "WARRANTS AGROPECUÁRIOS"), certificado de investimento audiovisual. As 3
linhas com `Tipo_Ativo = "CERTIFICADOS DE RECEBÍVEIS"` (sem qualificador IMOBILIÁRIOS/
AGRONEGÓCIO) ficam de fora de propósito — não dá para saber se é CRI ou CRA sem inventar, e a
regra de ouro deste projeto (ver seção "Linhas Incentivadas") é nunca inferir. **CPR-F** (Cédula
de Produto Rural Financeira) foi pedido explicitamente como fora de escopo por falta de fonte
aberta — nem precisou de exclusão manual: CPR não é valor mobiliário registrado na CVM (é
título de crédito rural fora da competência dela), então nunca apareceria neste dataset.

### `cvm_oferta_distribuicao_raw` (staging, quase 1:1 com o CSV oficial)

**Escopo de colunas deliberadamente reduzido**: o CSV oficial tem ~30 colunas adicionais de
COMPOSIÇÃO DE INVESTIDORES (`Nr_Pessoa_Fisica`, `Qtd_Fundos_Investimento`,
`Qtd_Investidor_Estrangeiro` etc.) que descrevem QUEM comprou o ativo, não o crédito em si —
fora do escopo de um radar de crédito (poderiam ser adicionadas depois, sem migração nenhuma
nos dados já gravados, se um dia isso virar requisito real — basta estender
`parse_cvm.py::CVM_COLUMNS` e rodar de novo, o CSV de origem continua tendo tudo). Mantidas:
identificação da oferta/processo, emissor/líder/ofertante, datas, classe/série/forma do ativo,
quantidade/preço/valor, flags S/N (incentivo fiscal/regime fiduciário/oferta inicial),
juros/atualização monetária (texto cru, fonte do `indexador_padronizado`).

**`numero_registro_oferta` NÃO é chave natural viável** (achado real, verificado contra o CSV
inteiro antes de desenhar o pipeline) — parecia óbvio (é literalmente "o número de registro da
oferta"), mas **75,8% das linhas de dívida (9.277 de 12.242 candidatas) têm esse campo NULO**:
são ofertas com DISPENSA de registro (`Modalidade_Dispensa_Registro`/`Data_Dispensa_Oferta`
preenchidos nesses casos, nunca um número de registro — a CVM só atribui esse número a ofertas
que de fato passam pelo rito de registro pleno). `Numero_Processo` também não serve sozinho: um
único processo administrativo pode conter **dezenas de séries/emissões diferentes** (confirmado
um processo com 55 séries de debênture, cada uma sua própria linha). Por isso o staging usa a
MESMA estratégia já validada para BNDES/FINEP (ver `incremental.py`): **hash de conteúdo da
linha inteira** (`row_hash`, sobre as colunas de negócio mantidas, não sobre as ~30 excluídas) —
o dataset da CVM também é republicado por inteiro a cada atualização diária, não incremental na
origem. Rodando pela primeira vez (2026-09-16): 12.239 linhas em escopo no CSV, **12.232
inseridas** (7 descartadas por `row_hash` idêntico dentro do mesmo lote — linhas que só
diferiam nas colunas de composição de investidores excluídas do staging, portanto
indistinguíveis nos campos que este projeto de fato guarda).

### `operations_primario` (tabela unificada, mesmo espírito de `operations`)

`src/unify_primario.py::build_operations_primario()` — incremental por `raw_table`+`raw_id`
(nunca por `numero_registro_oferta`, pelos motivos acima), mesmo padrão de
`unify.py::build_operations()`. Diferença de design: `operations` tem 3 estados de
`setor_origem` (nativo/enriquecido/pendente) porque o BNDES tem setor NATIVO na própria
planilha; aqui **todo emissor depende do MESMO caminho de enriquecimento via CNPJ**, então não
existe uma coluna `setor_origem` — o estado "pendente" é só `setor_emissor IS NULL`.

- **`instrumento_padronizado`**: mapa fixo (`INSTRUMENTO_PADRONIZADO_MAP`, chave exata pós-
  normalização, não regex — a essa altura a linha já passou pelo filtro de escopo) para
  `'Debênture'|'CRI'|'CRA'|'Nota Comercial'|'Letra Financeira'|'CDCA'|'CCB'|'Outro'`. Nota
  Promissória e Nota Comercial são **o MESMO instrumento sob nomes diferentes** (a Lei
  14.195/2021 renomeou "nota promissória comercial" para "nota comercial" e trocou o registro
  da B3 pelo da CVM/escritural — mesma natureza econômica) — unificadas sob `'Nota Comercial'`.
- **`setor_emissor`/`subsetor_emissor`/`segmento_emissor`/`porte_emissor`/
  `natureza_juridica_emissor`/`uf_emissor`/`municipio_emissor`/`razao_social_oficial_emissor`**:
  via JOIN contra `cnpj_cnae` (o MESMO cache já usado para enriquecer a FINEP) por
  `cnpj_emissor`. **Extensão feita em `cnpj_cnae` para viabilizar isso**: a tabela nunca teve
  `uf`/`municipio` (BNDES/FINEP já trazem UF/município direto na própria planilha de origem,
  nunca precisaram disso via CNPJ) — adicionadas via `MIGRACOES_COLUNAS` (`ALTER TABLE`,
  nullable, sem backfill retroativo: linhas de `cnpj_cnae` já existentes de BNDES/FINEP ficam
  com `uf`/`municipio` NULL para sempre, o que é aceitável — nada mais consome esses dois campos
  a partir de `cnpj_cnae` hoje). Populadas via `enrich_cnae.py::enrich_pendentes_via_api`
  (BrasilAPI) — a API já devolvia `uf`/`municipio` na mesma chamada usada para CNAE/porte/
  natureza jurídica, só não eram gravados até esta mudança; o job MENSAL em lote
  (`enrich()`, que escaneia `Estabelecimentos*.zip` da RFB) **não foi estendido** para isso
  (`ESTAB_COLS` tem `uf`/`municipio` disponíveis no zip, mas `KEEP_COLS` não os inclui) — só o
  caminho BrasilAPI (usado neste pipeline, volume pequeno o suficiente: ~1,2 mil CNPJs
  distintos) grava esses dois campos por enquanto.
- **`data_referencia`/`ano`/`trimestre`**: `Data_Emissao` (o campo "óbvio") está **ausente em
  82% das linhas em escopo** (achado real — ofertas antigas/dispensadas raramente têm essa data
  digitalizada), então `data_referencia` usa o primeiro campo preenchido nesta ordem de
  preferência (ver `unify_primario.py::_data_referencia`, todos já normalizados para
  `AAAA-MM-DD`): `data_emissao` → `data_registro_oferta` → `data_inicio_oferta` →
  `data_encerramento_oferta` → `data_protocolo` → `data_abertura_processo`. NUNCA inventada — se
  os 6 campos estiverem vazios, fica NULL. `ano`/`trimestre` derivados de `data_referencia`,
  mesmo padrão de `operations.ano`/`operations.trimestre`.
- **`indexador_padronizado`: MELHOR ESFORÇO, propositalmente impreciso — documentado aqui para
  quem for consumir este campo não confiar demais nele.** `Juros`/`Atualização_Monetária` são
  texto livre da CVM desde 1989 (771 e 98 valores distintos só no subconjunto em escopo, ex:
  `"12% A.A."`, `"DI + 2%"`, `"TAXA ANBID"`, `"IGP-M"`, `"VARIAÇÃO CAMBIAL DÓLAR"`, `"NIHIL"`) —
  impossível parsear com precisão total sem inventar. `_indexador_padronizado()` reconhece só os
  4 padrões mais comuns/inequívocos por regex simples: `IPCA+` (contém IPCA/IPCR na atualização
  monetária), `SELIC` (contém SELIC em qualquer um dos dois campos), `CDI` (atualização
  monetária vazia/"NÃO" E juros contém "DI"/"CDI" como palavra inteira — cuidado real evitado
  aqui: `\bC?DI\b` NÃO bate "ANBID" nem "RODI", que não têm a subsequência literal "DI" com
  boundary), `Prefixado` (atualização monetária vazia E juros é uma taxa numérica pura, sem
  DI/CDI/SELIC). Qualquer outro conteúdo real (IGPM, TR, TJLP, ANBID — histórica, uma taxa
  distinta de CDI, NUNCA tratada como equivalente aqui —, variação cambial, IGP-DI, INCC etc.)
  cai em `'Outro'` — nunca em NULL nesse caso, para não parecer "sem indexador" quando na
  verdade só não reconhecemos qual é. NULL fica reservado para quando os dois campos de origem
  estão genuinamente vazios. **Se um dia este campo precisar de mais precisão**: expandir os
  padrões reconhecidos em `_indexador_padronizado()` é seguro (função pura, sem migração), mas
  qualquer expansão deve continuar seguindo a mesma regra de ouro do resto do projeto — nunca
  inventar/inferir um indexador que o texto de origem não afirma claramente.
- **`taxa_valor`/`taxa_tipo` (pedido adicional do usuário, chegou no meio desta mesma sessão,
  logo depois do `indexador_padronizado` acima já estar pronto)**: além de SABER que o
  indexador é CDI, o usuário quer o NÚMERO da taxa/spread (ex: para "CDI + 2,50% a.a." — ver o
  indexador `CDI` E o número `2.5`; para "12,5% a.a." — ver só o número `12.5`). MESMA filosofia
  de melhor esforço do `indexador_padronizado` — `src/unify_primario.py::_extrair_taxa()`, regex
  sobre `juros` (`Atualização_Monetária` carrega o NOME do índice, quase nunca um número de taxa
  junto). `taxa_tipo` tem **3 valores possíveis** (uma extensão deliberada sobre o que foi pedido
  — o usuário sugeriu só `spread`/`taxa_fixa`, mas os dados reais mostraram um terceiro padrão
  genuíno demais pra forçar em uma das duas categorias sem inventar semântica):
  - `'spread'`: aditivo (`+`/`-` explícito, ou a palavra "acrescid[ao] de", ou o número vindo
    ANTES do indexador tipo `"0,75% a.a. + CDI"`) — funciona independente de qual indexador
    precede/segue, então também cobre um spread sobre um indexador que caiu em `'Outro'`
    (IGPM/TR/TJLP/LIBOR/ANBID etc.) — o índice de base continua disponível em
    `indexador_padronizado` + `juros`/`atualizacao_monetaria` crus, nunca escondido atrás do
    número extraído. O `"%"` é **opcional** neste padrão de propósito: `"CDI + 1,75"`/
    `"DI + 2,85 aa"` são spreads reais sem o símbolo — convenção do mercado de crédito privado
    brasileiro é cotar spread sobre DI/CDI/SELIC sempre em pontos percentuais a.a., mesmo quando
    o `%` some do texto (o campo `juros` só existe pra descrever uma taxa de dívida — qualquer
    número aqui depois de um sinal `+`/`-` é uma taxa, nunca outra coisa).
  - `'percentual_indexador'`: **MULTIPLICATIVO, não aditivo** (ex: `"108% do CDI"`,
    `"104% da taxa DI"`) — deliberadamente um `taxa_tipo` DIFERENTE de `'spread'`: tratar
    `"108% do CDI"` como "spread de 108" seria uma leitura errada e enganosa (não são 108 pontos
    percentuais SOMADOS ao CDI, é 108% do próprio CDI — quase o dobro do indexador). Só
    reconhecido quando `indexador_padronizado` já é `'CDI'`/`'SELIC'` (evita ambiguidade com
    outros usos de `%`).
  - `'taxa_fixa'`: prefixado puro (`indexador_padronizado == 'Prefixado'`, número seguido de
    `%`).
  - **BUG REAL corrigido antes de terminar**: as primeiras versões das regex tinham os
    conectivos (`"spread"`, `"sobretaxa"`, `"acrescida"`, `"taxa"`) escritos em minúsculo, mas
    `juros` chega já normalizado em MAIÚSCULO (`remover_acentos(...).upper()`, mesma função
    usada pelo filtro de escopo) — sem `re.IGNORECASE`, nenhuma delas batia contra o texto real
    (`"SPREAD DE 1,5%"` nunca casava com o padrão em minúsculo). Corrigido adicionando
    `re.IGNORECASE` em todas as regex de taxa.
  - **Cobertura real medida** (contra as 12.239 linhas em escopo do CSV de 2026-09-16):
    **515 linhas (~4,2%) com `taxa_valor` extraído** — a grande maioria das linhas tem `juros`
    vazio/`"NAO"`/`"-"` (a mesma razão pela qual `indexador_padronizado` também é `None` em
    10.603 linhas — dado realmente ausente na fonte, não falha de regex). Do subconjunto onde
    `juros` tem conteúdo reconhecível, a cobertura é bem maior; o que ainda fica de fora é
    fraseado raro demais pra valer regex novo agora (ex: `"105% das taxas médias diárias dos
    DI"`, `"101,75 da Taxa DI"` sem `%`) — **documentado aqui, não escondido**: `taxa_valor`
    fica `NULL` nesses casos, nunca um valor chutado.
- **`prazo_dias`/`prazo_meses` (pedido adicional do usuário, mesma sessão)**: diferente de
  indexador/taxa, isso é **dado EXATO, não melhor esforço** — `Data_Vencimento - Data_Emissao`,
  duas datas reais da própria CVM (`src/unify_primario.py::_prazo_dias_e_meses`).
  `prazo_meses` = `prazo_dias / 30,44` (média de dias por mês), arredondado a 1 casa — conversão
  documentada, não inventada, só pra ficar comparável com `operations.prazo_amortizacao_meses`
  (BNDES/FINEP, já em meses). **Só calculável quando AMBAS as datas existem** — confirmado
  contra o CSV real: apenas **1.859 de 12.239 linhas em escopo (15,2%)** têm as duas datas
  preenchidas (`Data_Emissao` sozinha já falta em 82% das linhas, ver `data_referencia` acima).
  **Achado real de qualidade de dado NA PRÓPRIA FONTE**: das 1.903 linhas com as duas datas (nº
  ligeiramente diferente de 1.859 porque conta antes do dedup por `row_hash`), **44 (2,3%) têm
  `Data_Vencimento` ANTERIOR OU IGUAL a `Data_Emissao`** — inconsistência de digitação da CVM,
  não bug deste pipeline (um caso extremo mediu -35.429 dias, quase 97 anos "ao contrário").
  Essas 44 linhas ficam com `prazo_dias`/`prazo_meses` `NULL` de propósito — nunca um prazo
  negativo/zero, que quebraria qualquer comparação/gráfico no frontend depois.
- **Carência: NÃO existe nesta fonte, confirmado contra os DOIS dicionários de dados da CVM**
  (`meta_oferta_distribuicao.txt` E `meta_oferta_resolucao_160.txt`, o segundo arquivo dentro do
  mesmo zip — dataset relacionado mas de schema DIFERENTE, focado no rito RCVM 160/automático
  pós-2023, fora do escopo geral deste pedido) — nenhum dos dois tem um campo equivalente a
  `prazo_carencia_meses` do BNDES. Diferente do BNDES (que declara carência explicitamente na
  própria planilha), carência de um título de dívida privado normalmente só consta na
  escritura/prospecto do papel, não neste registro estruturado da CVM. **Deliberadamente não
  extraído de texto livre** (não há um campo de referência que sirva de âncora, ao contrário de
  indexador/taxa que pelo menos partem de `Juros`/`Atualização_Monetária` — tentar inferir
  carência de descrição livre sem estrutura nenhuma seria risco alto de dado errado) — mesma
  regra de ouro do resto do projeto: sem fonte estruturada, sem campo. Se `oferta_resolucao_160`
  um dia for integrado como fonte própria (schema bem diferente, tem `Descricao_garantias`/
  `Agente_fiduciario`/`Titulo_incentivado` — não avaliado a fundo, fora do escopo deste pedido),
  vale reconferir se carência aparece lá antes de assumir que nunca vai existir.

Rodando pela primeira vez (2026-09-16) contra produção (Aiven, mesmo `DATABASE_URL` de sempre):
12.232 linhas inseridas em `operations_primario` (1:1 com o staging, nenhuma linha rejeitada),
8.249 emissores ficaram pendentes de enriquecimento (1.472 linhas sem `cnpj_emissor` — nunca vão
resolver, é dado ausente na própria oferta, não erro deste pipeline — + linhas cujo CNPJ ainda
não estava em `cnpj_cnae`), reduzido para **1.242 CNPJs distintos** a resolver via
`enrich_cnae.py::enrich_pendentes_via_api` (BrasilAPI, mesmo mecanismo/rate-limit já usado pela
FINEP — ~0,6s por CNPJ).

### Pipeline (`src/refresh_primario.py`)

Orquestrador PRÓPRIO e SEPARADO de `refresh.py` (BNDES/FINEP) — fonte, staging e tabela final
são completamente independentes, só compartilham o cache `cnpj_cnae` (por design, já pensado
para múltiplas fontes). Sequência: `download_cvm.download_all()` → `parse_cvm.parse_cvm()` →
`unify_primario.build_operations_primario()` → se sobrar emissor pendente,
`enrich_cnae.enrich_pendentes_via_api()` (BrasilAPI, mesma função já usada pelo refresh semanal
da FINEP, só que alvo = CNPJs de `operations_primario`) →
`unify_primario.reclassificar_emissores_pendentes()`. Log em `refresh_primario_log` (mesmo
formato de `refresh_log`/`refresh_editais_log`). **NÃO roda** o job pesado mensal de
`enrich_cnae.py::enrich()`/`enrich_empresas()` (bulk RFB, vários GB) — o volume de emissores da
CVM (milhares, não dezenas de milhares) é resolvido inteiramente pelo caminho leve via
BrasilAPI, sem precisar do job pesado. Automação: `.github/workflows/refresh-primario.yml`,
diário (09:00 UTC, 1h depois do refresh de editais — mesmo secret `DATABASE_URL`), com
`workflow_dispatch` para rodar manualmente.

### Escopo desta sessão (fundação — outras sessões constroem em cima)

Esta sessão entregou SÓ a camada de dados (staging + `operations_primario` + schema +
enriquecimento de emissor), deliberadamente sem tocar em: rotas `/api/primario/*` (FastAPI),
motor de busca, frontend/abas novas. O schema de `operations_primario` já está estável o
suficiente para outra sessão começar a codificar contra ele em paralelo, mesmo antes do
enriquecimento de 100% dos emissores pendentes terminar (o campo `setor_emissor`/`uf_emissor`
IS NULL é um estado normal e esperado, não um bug a esperar sumir).

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
| Radar de Crédito Primário (CVM, pipeline de dados) | `src/download_cvm.py`, `src/parse_cvm.py`, `src/unify_primario.py`, `src/refresh_primario.py` |
| API/rotas | `webapp/main.py` |
| Frontend (abas, roteamento, filtros) | `webapp/static/js/common.js`, `webapp/static/index.html` |
| Frontend (cada aba) | `webapp/static/js/{consolidado,tendencias,busca,editais,linhas}.js` |
| Painel de Admin (`/admin`) | `webapp/admin/*`, `webapp/static/admin.html`, `webapp/static/js/admin.js` |
| Transações Salvas (favoritos/histórico por usuário) | `webapp/salvos.py`, `webapp/static/js/salvos.js` |
| Deploy Vercel | `vercel.json`, `api/index.py`, `DEPLOY.md` |
| Automação | `.github/workflows/*.yml` |
