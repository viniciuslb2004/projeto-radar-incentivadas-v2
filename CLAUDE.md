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
CCB, CPR-F) via dados da CVM — DUAS fontes/staging tables diferentes (o dataset principal de
Ofertas Públicas E um segundo CSV do rito automático/Resolução CVM 160, que sozinho cobre a
maior parte da atividade de 2023 em diante) — ver seção própria "Radar de Crédito Primário —
Pipeline CVM" mais abaixo. Só a CAMADA DE DADOS existe até aqui (staging + `operations_primario`);
rotas de API, motor de busca e frontend são trabalho de sessões seguintes.

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
- **`cvm_oferta_distribuicao_raw`**/**`cvm_oferta_resolucao_160_raw`**/**`operations_primario`**/
  **`refresh_primario_log`**: DUAS staging tables (uma por CSV/fonte CVM) + UMA tabela unificada
  + log do Radar de Crédito Primário (CVM) — ver seção própria "Radar de Crédito Primário —
  Pipeline CVM" mais abaixo.

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
regra de ouro deste projeto (ver seção "Linhas Incentivadas") é nunca inferir.

**CORREÇÃO REAL (2026-09-16, sessão de integração do `oferta_resolucao_160.csv` abaixo)**: a
entrada original desta seção dizia que **CPR-F** (Cédula de Produto Rural Financeira) tinha
sido excluído por falta de fonte aberta, e que "CPR não é valor mobiliário registrado na CVM".
**Isso estava ERRADO.** CPR-F *é* um valor mobiliário registrado na CVM — só não aparece neste
arquivo (`oferta_distribuicao.csv`, confirmado: 0 ocorrências de "PRODUTO RURAL"/"CPR" em
`Tipo_Ativo`) porque esse instrumento passa pelo rito automático (Resolução CVM 160), reportado
no SEGUNDO CSV do mesmo zip. Corrigido: 18 linhas reais de CPR-F (Klabin, Suzano, Duratex,
Adami, Eldorado Brasil Celulose, Agropecuária Maggi etc.) agora entram via
`cvm_oferta_resolucao_160_raw` — ver seção "Segunda fonte CVM" abaixo.

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
- **Carência: NÃO existe em NENHUMA das duas fontes CVM, confirmado contra os DOIS dicionários
  de dados** (`meta_oferta_distribuicao.txt` E `meta_oferta_resolucao_160.txt`) — nenhum dos
  dois tem um campo equivalente a `prazo_carencia_meses` do BNDES. Diferente do BNDES (que
  declara carência explicitamente na própria planilha), carência de um título de dívida privado
  normalmente só consta na escritura/prospecto do papel, não em nenhum destes registros
  estruturados da CVM. **Deliberadamente não extraído de texto livre** (não há um campo de
  referência que sirva de âncora, ao contrário de indexador/taxa que pelo menos partem de
  `Juros`/`Atualização_Monetária` — tentar inferir carência de descrição livre sem estrutura
  nenhuma seria risco alto de dado errado) — mesma regra de ouro do resto do projeto: sem fonte
  estruturada, sem campo. **Atualização (2026-09-16)**: `oferta_resolucao_160.csv` foi
  integrado (ver seção "Segunda fonte CVM: rito automático/Resolução 160" abaixo) — suas 47
  colunas relevantes foram conferidas uma a uma contra as 71 colunas oficiais do dataset, e
  nenhuma delas descreve carência (o schema é focado em ESTRUTURA/garantia da oferta —
  `Descricao_garantias`/`Agente_fiduciario`/`Titulo_incentivado`/`Tipo_lastro`/`Custodiante` —
  não em condições financeiras do título). Confirmado, não é mais uma suposição: carência
  continua indisponível em ambas as fontes CVM deste pipeline.

Rodando pela primeira vez (2026-09-16) contra produção (Aiven, mesmo `DATABASE_URL` de sempre):
12.232 linhas inseridas em `operations_primario` (1:1 com o staging, nenhuma linha rejeitada),
8.249 emissores ficaram pendentes de enriquecimento (1.472 linhas sem `cnpj_emissor` — nunca vão
resolver, é dado ausente na própria oferta, não erro deste pipeline — + linhas cujo CNPJ ainda
não estava em `cnpj_cnae`), reduzido para **1.242 CNPJs distintos** a resolver via
`enrich_cnae.py::enrich_pendentes_via_api` (BrasilAPI, mesmo mecanismo/rate-limit já usado pela
FINEP — ~0,6s por CNPJ).

### Segunda fonte CVM: rito automático / Resolução 160 (`oferta_resolucao_160.csv`)

**Achado real do coordenador (2026-09-16), DEPOIS que a integração acima já tinha rodado uma
vez**: o MESMO zip oficial (`oferta_distribuicao.zip`) contém um SEGUNDO CSV,
`oferta_resolucao_160.csv` — dataset relacionado mas de **schema DIFERENTE**, focado no rito
automático da Resolução CVM 160 (sucessora da ICVM 400/476 para a maior parte das emissões
modernas). Achado crítico: esse segundo arquivo tem **14.493 linhas cobrindo EXATAMENTE
2023–2026**, contra só **7 linhas** de `cvm_oferta_distribuicao_raw` nesse mesmo período — sem
integrar este arquivo, o radar ficava praticamente cego para a atividade de mercado mais
recente (exatamente o que mais importa para um "radar"). Integrado na mesma sessão que
corrigiu a exclusão indevida do CPR-F (ver acima).

- **`src/download_cvm.py`**: `download_all()` agora baixa o zip principal e o de metadados
  **cada um UMA vez só** e extrai os DOIS membros de cada (antes só extraía
  `oferta_distribuicao.csv`/`meta_oferta_distribuicao.txt` e descartava o resto) — evita baixar
  os mesmos ~5.3MB duas vezes. Novos caminhos: `RESOLUCAO160_CSV_PATH`/`RESOLUCAO160_META_PATH`.
- **`cvm_oferta_resolucao_160_raw`** (staging nova, `src/parse_cvm_resolucao160.py`): MESMO
  padrão de `cvm_oferta_distribuicao_raw` — encoding latin-1, delimitador `;`, incremental por
  `row_hash` (não por chave natural), colunas de composição de investidores excluídas (aqui:
  ~24 colunas `Num_Invest_*`/`Qtde_VM_*`, mesmo critério). **Diferença real encontrada**:
  `Numero_Requerimento` **É confirmado único e não-nulo** nas 14.493 linhas (ao contrário de
  `numero_registro_oferta` no arquivo principal, 76% nulo) — mesmo assim, mantido como coluna
  INFORMATIVA, não como chave de upsert, por consistência com o resto do pipeline (o dataset
  também é republicado por inteiro a cada atualização, não incremental na origem).
- **Escopo de instrumentos**: reaproveita a MESMA regex de `parse_cvm.py`
  (`ESCOPO_REGEX_DIVIDA`, exportada — antes privada `_ESCOPO_REGEX`), estendida com o termo do
  CPR-F (`PRODUTO RURAL FINANCEIRA|\bCPR-F\b`) — inofensivo para o arquivo principal (confirmado
  ao vivo: 0 ocorrências desse termo em `Tipo_Ativo`). Contagem real (CSV de 2026-09-16, campo
  `Valor_Mobiliario` — nomenclatura **diferente** da de `Tipo_Ativo` para o MESMO instrumento,
  ex: "Debêntures" em vez de "DEBÊNTURES SIMPLES", sem sufixo "- CRI"/"- CRA"/"- CDCA", exigiu
  chaves novas em `unify_primario.py::INSTRUMENTO_PADRONIZADO_MAP`): Debêntures 1.938 +
  Debêntures Conversíveis 1, Certificados de Recebíveis Imobiliários 1.868, Notas Comerciais
  770, Certificados de Recebíveis do Agronegócio 587, **Cédula de Produto Rural Financeira
  (CPR-F) 18**, Certificado de Direitos Creditórios do Agronegócio 4, Notas Promissórias 2 —
  **5.188 linhas em escopo** de 14.493 totais (9.305 fora de escopo: majoritariamente Cotas de
  FIDC/FII/FIF/FIP/FIAGRO, Ações, "Outros títulos de securitização" — ambíguo demais, mesmo
  critério de nunca inventar que já exclui "Certificados de Recebíveis" sem qualificador no
  arquivo principal — e as 3 linhas ambíguas "Certificados de Recebíveis").
- **Checagem de DUPLICIDADE entre os dois arquivos (item 5 do pedido, verificado ao vivo)**:
  **ZERO overlap de `Numero_Processo`** entre os dois CSVs (14.493 processos distintos no
  segundo arquivo, nenhum aparece no principal). Uma coincidência de `(CNPJ_Emissor, Emissao)`
  apareceu em 312 combinações, mas inspecionar várias mostrou que são operações DIFERENTES do
  MESMO emissor reaproveitando o número de emissão em programas distintos (ex: um emissor
  serial de securitização com "Emissão 96" de CRI num arquivo e "Emissão 96" de CRA totalmente
  diferente no outro — valores e datas não batem). **Conclusão: os dois arquivos são conjuntos
  DISJUNTOS na prática** — nenhuma lógica de dedup entre eles foi necessária.
- **Campos que este arquivo NÃO tem** (confirmado contra as 71 colunas oficiais):
  `Data_Emissao`/`Data_Vencimento`/`Juros`/`Atualização_Monetária`/`Serie`/`Classe_Ativo`/
  `Especie_Ativo`/`Forma_Ativo`. Por isso, para linhas com `raw_table =
  'cvm_oferta_resolucao_160_raw'`: **`data_emissao`/`data_vencimento`/`prazo_dias`/
  `prazo_meses`/`indexador_padronizado`/`taxa_valor`/`taxa_tipo`/`juros`/
  `atualizacao_monetaria`/`serie`/`classe_ativo`/`especie_ativo`/`forma_ativo` ficam SEMPRE
  `NULL`** (nunca inferidos — em especial, prazo NUNCA foi aproximado a partir das datas de
  PROCESSO deste arquivo, que são conceitos diferentes de vencimento do título). Isso é
  **esperado, documentado, não é bug** — resolve o problema de VOLUME/RECÊNCIA, não o de
  remuneração/prazo do título.
- **`data_referencia` (fallback próprio, `unify_primario.py::_data_referencia_r160`)**: usa os
  campos de data que ESTE arquivo realmente tem, em ordem de preferência: `data_registro` →
  `data_encerramento` → `data_deliberacao_aprovou_oferta` → `data_requerimento` (último recurso,
  mas o ÚNICO campo sem nenhum nulo no dataset inteiro — garante `data_referencia` preenchida
  para praticamente 100% das linhas).
- **6 colunas novas em `operations_primario`** (sempre `NULL` para linhas de
  `cvm_oferta_distribuicao_raw`, que não tem equivalente a nenhuma): `numero_requerimento`
  (traçabilidade — namespace DIFERENTE de `numero_registro_oferta`, nunca confundidos),
  `status_requerimento`, `tipo_lastro` (`'Pulverizado'`/`'Concentrado'`), `agente_fiduciario`,
  `custodiante`, `descricao_garantias`. `titulo_incentivado`/`regime_fiduciario` do arquivo NÃO
  viraram colunas novas — mapeados para as colunas booleanas JÁ existentes `incentivada`/
  `regime_fiduciario` (mesmo significado econômico, Lei 12.431/regime fiduciário).
- **`status_requerimento`: decisão deliberada de NUNCA filtrar silenciosamente.** ~1,1% das
  linhas em escopo (57 de 5.188) têm um status que indica que o requerimento NÃO chegou a virar
  uma oferta efetivamente concluída (`'Oferta Revogada'` 24, `'Requerimento Expirado'` 17,
  `'Registro Caducado'` 15, `'Oferta Suspensa'` 1) — mantidas em `operations_primario` (nunca
  descartadas), mas com o status EXPOSTO nesta coluna nova para quem for construir rotas/
  frontend (fora do escopo desta sessão) poder filtrar se quiser. A maioria é `'Oferta
  Encerrada'` (4.877) ou `'Registro Concedido'`/`'Aguardando Bookbuilding'` (254, em processo
  mas já registrados).
- **Resultado da integração** (rodado ao vivo em produção, 2026-09-16, DEPOIS da primeira
  rodada documentada acima): **5.188 linhas novas** inseridas em `operations_primario` (0
  rejeitadas), total da tabela sobe de 12.232 para **17.420**. Cobertura 2023–2026 sobe de 7
  para **5.193 linhas** (7 do arquivo principal + 5.186 deste novo, 2 linhas do novo arquivo
  ficaram fora da janela por `data_referencia` cair fora dela). Por `instrumento_padronizado`
  na tabela inteira (as duas fontes somadas) depois da integração: Debênture 7.099, CRI 5.873,
  Nota Comercial 2.692, CRA 1.607, Letra Financeira 115, **CPR-F 18**, CDCA 15, CCB 1.
  **Enriquecimento de emissor rodado até o fim nesta sessão** (não deixado para depois): **792
  CNPJs distintos** pendentes resolvidos via `enrich_cnae.py::enrich_pendentes_via_api`
  (BrasilAPI, mesmo mecanismo já usado pela FINEP) — **791/792 resolvidos** (1 não encontrado
  na BrasilAPI, tratado como falha isolada de CNPJ, não interrompe o restante — mesmo
  comportamento já documentado da função), **1.169 linhas reclassificadas** (pendente →
  resolvido; mais que 792 porque um mesmo CNPJ emissor aparece em várias operações). Estado
  final: de 17.420 linhas totais, **1.473 seguem pendentes** — **1.472 delas por não terem
  `cnpj_emissor` na própria oferta** (dado ausente na fonte, nunca vai resolver, não é bug) e
  **1 por CNPJ ainda não resolvido** (o único miss da BrasilAPI nesta rodada).

### Pipeline (`src/refresh_primario.py`)

Orquestrador PRÓPRIO e SEPARADO de `refresh.py` (BNDES/FINEP) — fonte, staging e tabela final
são completamente independentes, só compartilham o cache `cnpj_cnae` (por design, já pensado
para múltiplas fontes). Sequência: `download_cvm.download_all()` (baixa AMBOS os CSVs, ver
seção acima) → `parse_cvm.parse_cvm()` (arquivo principal) →
`parse_cvm_resolucao160.parse_cvm_resolucao160()` (segundo arquivo, rito automático) →
`unify_primario.build_operations_primario()` (processa as DUAS raw tables, cada uma
incrementalmente por `raw_table`+`raw_id` própria, inserindo na MESMA `operations_primario`) →
se sobrar emissor pendente, `enrich_cnae.enrich_pendentes_via_api()` (BrasilAPI, mesma função já
usada pelo refresh semanal da FINEP, só que alvo = CNPJs de `operations_primario`, de QUALQUER
uma das duas fontes) → `unify_primario.reclassificar_emissores_pendentes()`. Log em
`refresh_primario_log` (mesmo formato de `refresh_log`/`refresh_editais_log`;
`cvm_raw_rows` agora soma as linhas novas das DUAS staging tables). **NÃO roda** o job pesado
mensal de `enrich_cnae.py::enrich()`/`enrich_empresas()` (bulk RFB, vários GB) — o volume de
emissores da CVM (milhares, não dezenas de milhares) é resolvido inteiramente pelo caminho leve
via BrasilAPI, sem precisar do job pesado. Automação: `.github/workflows/refresh-primario.yml`,
diário (09:00 UTC, 1h depois do refresh de editais — mesmo secret `DATABASE_URL`), com
`workflow_dispatch` para rodar manualmente.

### Corte de escopo temporal: 2010+ (pedido do usuário, 2026-09-17)

Decisão de produto: o Radar de Crédito Primário passa a focar em emissões a partir de
**2010-01-01** — dado mais antigo removido de propósito, com backup (nunca descartado, mesmo
espírito do Supabase mantido como rede de segurança na migração pro Aiven).

- **Backup antes de apagar**: `operations_primario_pre2010_backup` (mesmas colunas de
  `operations_primario`, criada via `CREATE TABLE ... AS SELECT * FROM operations_primario
  WHERE data_referencia < '2010-01-01'` antes do `DELETE`) — **2.358 linhas** preservadas
  intactas, cobrindo 1989-09-01 a 2009-12-29.
- **`DELETE FROM operations_primario WHERE data_referencia < '2010-01-01'`**: rodado contra
  produção (Aiven) em 2026-09-17, confirmado via `raw_table`+`raw_id` que TODA linha removida
  já estava coberta pelo backup antes do delete (0 linhas órfãs). Linhas com
  `data_referencia IS NULL` **nunca são removidas** por este corte (hoje, 2026-09-17, esse
  caso não ocorre na base real — 0 linhas — mas o filtro preserva o caso de qualquer forma:
  sem data resolvida, não há como confirmar que a linha é de fato anterior a 2010, então
  destruí-la seria apagar dado real sem justificativa).
- **Corte tornado PERMANENTE no pipeline** (`src/unify_primario.py::_filtrar_corte_temporal`,
  `DATA_CORTE_MINIMA = "2010-01-01"`) — aplicado dentro de `_build_primario_ops`/
  `_build_primario_ops_r160`, logo depois de `data_referencia` já calculada e ANTES do
  insert. **Sem isso, o próximo refresh reintroduziria as mesmas 2.358 linhas**: as staging
  tables (`cvm_oferta_distribuicao_raw`/`cvm_oferta_resolucao_160_raw`) continuam com o
  histórico completo (nunca truncadas), e o mecanismo incremental por `raw_id` trata qualquer
  linha ausente de `operations_primario` como "ainda não processada", reinserindo-a na
  próxima rodada — **isso realmente aconteceu uma vez** durante esta mudança (a primeira
  tentativa de `DELETE` foi desfeita por um refresh que rodou antes do filtro permanente
  estar pronto/commitado) e foi corrigido repetindo o `DELETE` só depois do filtro já estar
  em vigor. **Confirmado ao vivo**: rodar `build_operations_primario()` de novo depois do
  filtro entrar em vigor reporta `0 linhas novas` (nenhuma reintrodução).
- Total de `operations_primario` após o corte: **15.076** (era 17.434 — a contagem sobe e
  desce um pouco ao longo do dia com o refresh diário automático, não é um erro de conta).

### Pesquisa de fontes adicionais + melhoria de extração de taxa (2026-09-17)

Pedido do usuário: pesquisar outras fontes ABERTAS/GRATUITAS que cubram o mesmo universo
(debêntures/CRI/CRA/notas comerciais/letras financeiras/CDCA/CCB) e, complementarmente,
melhorar a qualidade de extração das 2 fontes CVM já integradas.

**Pesquisa de fontes novas — conclusão: nenhuma fonte aberta genuinamente melhor foi
encontrada, esforço redirecionado pra qualidade da extração (ver abaixo).** Três candidatos
investigados ao vivo (WebFetch/download real, não só a descrição da página):
- **CVM — "Distribuições de Débentures - Planilha Individualizada"**
  (`dados.cvm.gov.br/dataset/distrpubl`, arquivo `.ods` baixado e inspecionado com
  `pandas`+`odfpy`): é uma série histórica ESTÁTICA/LEGADA, com a própria planilha
  declarando `Data da Atualização do último Período: 02/01/2023` — **não é atualizada desde
  2023-01**, cobre só debêntures sob rito ICVM 400/03 (nem CRI/CRA/CDCA/CCB/notas
  comerciais, nem o rito automático da Resolução 160 que hoje domina o volume recente) e o
  único campo de estrutura é "Garantia" (texto livre, sem carência nem taxa numérica
  separada de "Juros" — mesma limitação que os 2 CSVs já integrados). Conclusão: **pior**
  que o que já temos em cobertura, atualidade E granularidade — descartado.
- **ANBIMA Data** (`data.anbima.com.br`/`developers.anbima.com.br`): API de preços/taxas
  indicativas de MERCADO SECUNDÁRIO (marcação a mercado diária de CRI/CRA/debêntures já
  emitidos) — dado de natureza DIFERENTE do que este radar cobre (ofertas PRIMÁRIAS, o
  evento de emissão em si, não a negociação depois de emitido); também não cobre CDCA/CCB/
  notas comerciais. Mesmo se fosse integrada um dia, seria uma tabela/conceito NOVO
  ("cotação secundária"), não um substituto/complemento direto de `operations_primario` —
  fora do escopo deste pedido (melhorar a mesma extração já existente).
- **B3 — Hub de Dados Públicos** (`b3.com.br/pt_br/dados/hub-de-dados-publicos/`): mesmo
  problema do ANBIMA Data — "fechamento diário por emissor"/"histórico de negócios" é
  MERCADO SECUNDÁRIO (preço de negociação do papel já emitido), não dado de oferta
  primária. Também não cobre CDCA/CCB.
- **Conclusão prática**: a CVM (`oferta_distribuicao.csv` + `oferta_resolucao_160.csv`, já
  integrados) continua sendo a única fonte aberta, gratuita e verificável de OFERTAS
  PRIMÁRIAS deste universo de instrumentos — nenhuma integração nova feita. Esforço
  redirecionado pra extrair MAIS informação útil das 2 fontes já existentes (abaixo).

**Melhoria real de extração: `taxa_valor`/`taxa_tipo` — fallback "spread implícito"
(`src/unify_primario.py::_extrair_taxa`, `_RE_TAXA_BARE`/`_RE_JUROS_AMBIGUO`)**. Investigado
relendo o CSV principal linha a linha (não só o dicionário de dados): das 12.239 linhas em
escopo, **1.012 tinham `juros` preenchido mas `taxa_valor` ficava `NULL`** mesmo antes deste
fix — o padrão mais comum de longe era `juros` ser só um número seco (`"12% A.A."`, `"6%"`,
`"13,5% A.A. - MENSAL"`, 265+54+34+... ocorrências) **enquanto `atualizacao_monetaria` já
tinha um índice real preenchido** (IGPM 330, IPCA 135, TR 71, ANBID 56, IGP-M 50, TJLP 18,
variação cambial/dólar etc. — confirmado amostrando as combinações reais). **Achado-chave**:
a CVM grava índice e taxa em DOIS CAMPOS SEPARADOS desde 1989 — quando o campo de índice
tem conteúdo real e `juros` é só um número seco sem operador `+`/`-` nem menção a índice
nenhum dentro do próprio texto, a convenção do mercado de renda fixa brasileiro (e a própria
separação dos dois campos oficiais) é ADITIVA (índice + juros), exatamente a mesma lógica
que `'taxa_fixa'` já usava pra número seco quando o índice está VAZIO — só que aqui o índice
existe. Implementado como um NOVO fallback (`taxa_tipo='spread'`), rodando só depois de todos
os padrões anteriores falharem, e só quando `indexador_padronizado != "Prefixado"` (senão
duplicaria a lógica de `'taxa_fixa'`, que já cobre exatamente esse caso quando não há
índice). **Exclusão deliberada de ambiguidade**: `juros` contendo `" OU "` (ex: `"12% A.A.
OU LIBOR + 3,5%"`, `"11,2% ou 9,4% aa, antes ou após 01/12/2003"` — duas taxas alternativas
no mesmo campo) fica de fora de propósito — escolher uma das duas seria inventar qual se
aplica. **BUG REAL corrigido pelo coordenador antes do merge (2026-09-17)**: a guarda de
`"OU"` implementada nesta sessão só protegia o fallback NOVO acima — os 3 padrões de
`'spread'` já EXISTENTES antes desta sessão (`_RE_SPREAD_SINAL_ANTES`/`_RE_SPREAD_ACRESCIDA`/
`_RE_SPREAD_SINAL_DEPOIS`) rodavam ANTES da guarda e extraíam o número de qualquer jeito
quando havia um sinal `+`/`-` explícito, mesmo com `"OU"` no meio do texto (reproduzido ao
vivo: `_extrair_taxa("12% A.A. OU LIBOR + 3,5%", "Outro")` devolvia `(3.5, 'spread')` em vez
de `(None, None)`). Corrigido movendo a guarda pra antes de TODOS os padrões (não só o
último). **Confirmado que isso não afetou nenhuma linha real**: 0 linhas em produção têm
`taxa_valor` extraído E `"OU"` no texto de `juros` (checado direto contra o banco) — o gap
era real mas latente, sem impacto nos dados já gravados; ficava como risco pro próximo
refresh diário trazer um caso assim. **Nunca inventa nada**: o número sempre vem literalmente
do texto de `juros`, nunca calculado/estimado — mesma regra de ouro de sempre.

**Cobertura medida (antes → depois, mesmas 12.239 linhas em escopo do CSV de 2026-09-17)**:
**515 (~4,2%) → 1.373 (~11,2%)** — quase o triplo, `taxa_tipo` novo contribuindo 1.146
`'spread'` (a maioria do ganho), 144 `'percentual_indexador'` e 83 `'taxa_fixa'` já
existentes antes (números totais depois do fix, não só o delta). **Backfill rodado contra
produção** (`unify_primario.backfill_taxa_e_prazo()`, já existia — reaproveitado, nenhuma
função nova precisou ser escrita pra isso): sobre as 15.076 linhas já em `operations_primario`
(pós-corte 2010+), `taxa_valor` preenchido subiu de **87 para 239** (86 `'spread'` implícito
+ 14 `'percentual_indexador'` + 9 `'taxa_fixa'` já existentes, dos 239 totais — o ganho
relativo é menor que no CSV completo porque o padrão "número seco + índice legado tipo
IGPM/TR/BTN" era mais comum em ofertas ANTIGAS, que o corte 2010+ já removeu; instrumentos
modernos tendem a escrever a taxa já com operador `+`/`-` explícito, capturado pelos padrões
`'spread'` anteriores). `prazo_dias` não mudou (534 preenchidos, mesmo valor de antes) — o
backfill recalcula os dois juntos mas a lógica de prazo não foi alterada nesta sessão (ver
abaixo).

**`prazo_dias`/`prazo_meses`: nenhuma melhoria segura encontrada.** Investigado se havia
mais campos de data utilizáveis nos 2 dicionários de dados oficiais (`meta_oferta_
distribuicao.txt`/`meta_oferta_resolucao_160.txt`, os 2 relidos por completo nesta sessão,
71+41 campos conferidos um a um) — confirmado que `Data_Emissao`/`Data_Vencimento`
continuam sendo os ÚNICOS dois campos de data que descrevem o TÍTULO em si (todas as outras
datas — `Data_Registro_Oferta`/`Data_Protocolo`/`Data_Requerimento` etc. — descrevem o
PROCESSO administrativo, não o vencimento do papel; usar essas pra aproximar prazo seria
inventar). A baixa cobertura (15,2% no CSV completo, ver seção acima) é uma limitação REAL
da fonte (ofertas antigas/dispensadas raramente têm essas 2 datas digitalizadas), não um gap
de código a corrigir — nenhuma mudança feita aqui, documentado pra não reabrir essa
investigação à toa numa sessão futura.

**Nenhuma mudança em `.github/workflows/refresh-primario.yml`**: o fix de `_extrair_taxa` é
puramente computacional (nova regra de regex sobre colunas já lidas), sem migração de
schema nem novo download/fonte — o próximo refresh diário automático já aplica a regra nova
em qualquer linha nova via `_build_primario_ops` normalmente, sem precisar de nenhum passo
extra no workflow. O backfill acima (`backfill_taxa_e_prazo()`) foi rodado manualmente UMA
VEZ contra produção para corrigir o histórico já gravado — mesmo padrão de
`backfill_busca_primario()` (ver seção "API e Busca" abaixo), não é algo que o workflow
precisa repetir automaticamente.

### Escopo desta sessão (fundação — outras sessões constroem em cima)

Esta sessão entregou SÓ a camada de dados (staging + `operations_primario` + schema +
enriquecimento de emissor), deliberadamente sem tocar em: rotas `/api/primario/*` (FastAPI),
motor de busca, frontend/abas novas. O schema de `operations_primario` já está estável o
suficiente para outra sessão começar a codificar contra ele em paralelo, mesmo antes do
enriquecimento de 100% dos emissores pendentes terminar (o campo `setor_emissor`/`uf_emissor`
IS NULL é um estado normal e esperado, não um bug a esperar sumir). **Motor de busca + rotas
construídos na sessão seguinte, mesmo dia — ver seção própria abaixo, "Radar de Crédito
Primário — API e Busca".** **A integração do segundo arquivo CVM
(`oferta_resolucao_160.csv`, ver seção própria acima) foi feita por OUTRA sessão seguinte,
também no mesmo dia** — mesmo espírito: só camada de dados, nenhuma rota/busca/frontend
tocada, schema aditivo (6 colunas novas, todas nullable, nenhuma coluna existente removida ou
renomeada) para não quebrar quem já estivesse codificando contra o schema anterior em paralelo.

## Radar de Crédito Primário — API e Busca

Segunda camada do Radar de Crédito Primário (ver seção acima para a camada de dados),
construída em sessão separada no mesmo dia (2026-09-16): motor de busca sem IA + rotas
FastAPI que consomem `operations_primario`. **Deliberadamente sem frontend/toggle de
mercado/Transações Salvas generalizada** — isso é trabalho de uma sessão futura, que
consome as rotas documentadas aqui.

### Motor de busca (`src/search_fts_primario.py`)

Espelha `src/search_fts.py` (BNDES/FINEP), **mais simples**: não há dicionário de
sinônimos/taxonomia curado para o emissor da CVM (`setor_emissor`/`subsetor_emissor` usam a
MESMA taxonomia BNDES via `cnpj_cnae`, mas ninguém curou sinônimos especificos pra isso),
então não existe uma coluna equivalente a `search_taxonomia_termos`. 4 tiers (contra 6 do
motor BNDES/FINEP):
1. CNPJ do emissor (só se o fragmento numérico tiver ≥8 dígitos, mesma guarda contra
   falso-positivo já documentada para o motor BNDES/FINEP) ou prefixo de `nome_emissor`.
2. `instrumento_padronizado` OU `setor_emissor`/`subsetor_emissor` (keyword, `LIKE`).
3. Full-text (`search_vector @@ websearch_to_tsquery`, query PRÓPRIA com `@@` direto no
   `WHERE` — NUNCA dentro de um CASE avaliado sobre a tabela inteira, mesma disciplina de
   performance já documentada em detalhe na seção "Bugs reais já corrigidos" pro motor
   BNDES/FINEP, reaplicada aqui desde o primeiro commit). Confirmado com `EXPLAIN ANALYZE`
   ao vivo: `Bitmap Index Scan` no índice GIN (`idx_operations_primario_search_vector`),
   ~0.4ms de execução.
4. Trigrama (`pg_trgm`) em `nome_emissor`/`segmento_emissor`, só roda se as tiers 1-3
   voltarem com poucos resultados (mesmo `MINIMO_ANTES_DE_TRIGRAMA` do motor BNDES/FINEP).

`instrumento`/`uf`/`setor`/`valor_minimo` são FILTROS ESTRUTURADOS (`AND`, nunca dentro do
ranking de texto) — mesmo princípio já documentado pro filtro de UF do motor BNDES/FINEP.
`setor` combina `setor_emissor` (4 categorias amplas) e `subsetor_emissor` (mais granular)
num `OR` simples, mesmo padrão do filtro `setor` do motor BNDES/FINEP (o front não precisa
saber se o valor escolhido é setor ou subsetor).

**`search_document`/`search_vector` NÃO existiam no schema quando esta sessão começou** —
a tarefa original assumia que sim ("confirme antes de assumir"); confirmado ao vivo
(`information_schema.columns`) que as 12.232 linhas gravadas na sessão anterior não tinham
essas duas colunas. Adicionadas via `MIGRACOES_COLUNAS` (`src/db.py`) + populadas por
`src/unify_primario.py::backfill_busca_primario()` (rodado uma única vez contra produção,
em lotes de 2.000 — mesmo motivo de cautela com o Aiven free tier já documentado em
`scripts/backfill_search_taxonomia.py` — confirmado: 12.232/12.232 linhas populadas).
Índices criados: `idx_operations_primario_search_vector` (GIN sobre `search_vector`),
`idx_operations_primario_nome_trgm`/`idx_operations_primario_segmento_trgm` (GIN trigram,
para a tier 4).

**Diferença deliberada de design frente a `unify.py`** (documentada no próprio código,
`src/unify_primario.py::_atualizar_busca_primario`): no motor BNDES/FINEP,
`search_document`/`search_taxonomia_termos` são calculados ANTES do insert (o BNDES já
chega com setor NATIVO, que não muda depois). Aqui, TODO emissor depende do enriquecimento
via CNPJ — uma linha recém-inserida quase sempre começa com `setor_emissor`/`uf_emissor`
NULL (pendente) e só ganha valor depois, via `_reclassificar_emissores_pendentes`.
`_atualizar_busca_primario(conn, ids)` roda depois de QUALQUER mudança (insert OU
reclassificação), sempre lendo o estado ATUAL da linha direto do banco, em vez de manter
duas cópias da lógica de `search_document` (uma pré-insert, outra pós-reclassificação) —
`build_operations_primario()` já chama essa função nos dois pontos.

### Rotas FastAPI (`webapp/primario/`, prefixo `/api/primario/*`)

Pacote ISOLADO, mesmo espírito de `webapp/admin/` — nunca misturado com `webapp/main.py`
(grande, do outro mercado). A ÚNICA mudança em `webapp/main.py` é o
`app.include_router(primario_router, prefix="/api/primario")`, logo após o include do
router do painel de admin.

**Autenticação**: nenhuma dependency própria — o prefixo começa com `/api/`, então o gate
global (`_verificar_acesso`, `dependencies=[Depends(_verificar_acesso)]` do `FastAPI(...)`
em `webapp/main.py`) já cobre qualquer rota sob `/api/primario/*` automaticamente (mesmo
mecanismo que já protege `/api/operacoes`, `/api/busca` etc.). **Confirmado ao vivo**: uma
chamada sem sessão válida contra `/api/primario/filtros` devolve 401; com uma sessão válida
(mintada via `webapp.admin.auth.criar_sessao`, mesmo caminho documentado na seção "Coisas a
saber antes de mexer" para testar localmente), devolve os dados normalmente.

- **`GET /api/primario/filtros`**: valores distintos para popular selects (instrumentos,
  setores, subsetores, ufs, indexadores, anos, `data_min`/`data_max` sobre
  `data_referencia`) — espelha `GET /api/filtros`. `setores`/`subsetores` só têm os valores
  já resolvidos via CNPJ (um emissor pendente não aparece nesses selects até resolver, mas
  continua contável em `kpis`/`operacoes`).
- **`GET /api/primario/kpis`**: agregados básicos (`n_operacoes`, `valor_total_total`,
  `cheque_medio`) + `por_instrumento` (troca `por_agencia` do motor BNDES/FINEP — não existe
  conceito de agência neste mercado, ver pedido original: "não invente um conceito
  equivalente"). Mesmos filtros estruturados de `operacoes`/`busca` (`instrumento`, `uf`,
  `setor`, `data_inicio`/`data_fim` sobre `data_referencia`).
- **`GET /api/primario/operacoes`**: listagem paginada/ordenável (`order_by`:
  `valor`|`data`|`prazo`|`taxa`|`nome`), espelha `GET /api/operacoes`.
- **`GET /api/primario/busca`**: motor de busca acima.
- **`GET /api/primario/operacoes/{id}`**: detalhe — mais simples que
  `GET /api/operacoes/{op_id}` (sem `montar_detalhe_amigavel`, específico do schema
  `bndes_raw`/`finep_*_raw`, ver `webapp/detalhe.py`): devolve as colunas de
  `operations_primario` (já é dado tratado/legível, com `search_document`/`search_vector`
  removidos da resposta — campos internos do motor de busca, nunca úteis num detalhe) +
  campos crus adicionais de `cvm_oferta_distribuicao_raw` que não viraram coluna própria
  (`nome_ofertante`, `modalidade_registro` etc., em `raw_extra`) + identificação da empresa
  via `cnpj_cnae` quando o CNPJ já foi resolvido (mesmo padrão do detalhe BNDES/FINEP, campo
  `empresa`).

### Testado ao vivo (2026-09-16, contra produção/Aiven)

Bateria real (servidor local `uvicorn`, sessão de teste mintada e apagada depois, ver
"Coisas a saber antes de mexer"): nome de emissor real (`VALE S.A.` → 20 resultados, tier 1,
inclui o nome histórico `CIA VALE DO RIO DOCE` sob o MESMO CNPJ — confirma que a base
realmente registra o rebrand da empresa ao longo do tempo, não é bug), CNPJ completo
(`33592510000154` → `eh_busca_cnpj: true`, mesmos resultados), filtro estruturado de
instrumento (`instrumento=Debênture` + busca por nome → só debêntures daquele emissor),
filtro de UF (`uf=SP` combinado com `instrumento` em `kpis`/`operacoes`), filtro de setor
(`setor=COMERCIO/SERVICOS` em `busca` → só resultados daquele setor), CNPJ curto/fragmento
numérico sem 8 dígitos (`abc123nada` → 0 resultados na tier 1, confirma que a guarda contra
falso-positivo já documentada pro motor BNDES/FINEP também vale aqui). `EXPLAIN ANALYZE` na
tier 3 confirmou `Bitmap Index Scan` no GIN (não seq scan).

### Rotas completadas (reconciliação com o frontend, 2026-09-16)

Duas sessões paralelas construíram no mesmo dia (1) só as 5 rotas acima e (2) todo o
frontend do modo Primário (ver seção "Radar de Crédito Primário — Frontend" abaixo) —
mas o frontend foi escrito assumindo um contrato de API bem mais completo (tabela
"Todos os endpoints `/api/primario/*` assumidos por este frontend" na seção Frontend),
já que as duas sessões nunca se viram. Esta sessão (reconciliação) implementou as 14
rotas que faltavam em `webapp/primario/routes.py` (nenhum arquivo novo, nenhuma mudança
em `src/search_fts_primario.py` foi necessária — todas as agregações novas cabem em SQL
direto, mesmo padrão das 5 rotas que já existiam):

- **`GET /api/primario/status`** -- espelha `/api/status`. `setores_pendentes` é a
  contagem de `setor_emissor IS NULL` (não existe `setor_origem` em
  `operations_primario`, ver seção Pipeline CVM). `busca_ia_ativa` é sempre `False`
  (não existe motor de embeddings pro Primário, só FTS).
- **`GET /api/primario/serie_temporal`** -- espelha `/api/serie_temporal`, trocando o
  agrupamento por `agencia` (não existe neste mercado) por `instrumento_padronizado` --
  `instrumento` continua funcionando também como filtro (mesma dualidade do original
  com `agencia`).
- **`GET /api/primario/instrumentos`** -- mesmo formato de `/api/setores`, agrupando por
  `instrumento_padronizado`.
- **`GET /api/primario/uf`** -- espelha `/api/uf`, via `uf_emissor`. Decisão tomada após
  reler a seção "Frontend: roteamento e abas" (o tratamento especial de `IE` do motor
  BNDES/FINEP): `IE` é uma categoria REAL da planilha do BNDES (abrangência nacional,
  ex: Petrobras) sem equivalente na CVM -- **não replicado aqui**, seria inventar um
  conceito que a fonte não tem. `uf_emissor` só tem 2 estados (UF real resolvida via
  CNPJ, ou NULL) -- o NULL usa o mesmo sentinela `NI` do motor original.
- **`GET /api/primario/porte`** -- espelha `/api/porte`, via `porte_emissor`. Decisão:
  **não usa `PORTE_NORMALIZADO_SQL`** (`src/search_fts.py`) -- aquele CASE existe pra
  unificar o vocabulário heterogêneo de `porte_cliente` (BNDES nativo + FINEP via RFB,
  misturando `MICRO`/`PEQUENA`/`GRANDE`/`MÉDIA` com `"Micro Empresa"`/`"Empresa de
  Pequeno Porte"`). `porte_emissor` vem de UMA SÓ fonte (sempre `cnpj_cnae` via
  BrasilAPI/RFB, ver `enrich_cnae.py::PORTE_EMPRESA_RFB`) com vocabulário próprio já
  homogêneo (`Micro Empresa`/`Empresa de Pequeno Porte`/`Demais`/`Não informado pela
  fonte`/NULL) -- aplicar aquele CASE aqui só devolveria `'Não informado'` pra tudo, e
  não existe distinção `GRANDE`/`MÉDIA` nesse layout simplificado da RFB pra inventar.
- **`GET /api/primario/operacoes/{id}/grupo-economico`** -- espelha o equivalente em
  `webapp/main.py`, agrupando por raiz de `cnpj_emissor` (8 primeiros dígitos). Chaves
  de resposta (`emissor`/`instrumento`/`valor_emissao`) escolhidas pra bater direto no
  fallback que `common.js::openOperacaoDetalhe` já tinha escrito
  (`o.cliente ?? o.emissor`, `o.agencia ?? o.instrumento`,
  `o.valor_contratado ?? o.valor_emissao`) -- não precisou mudar o frontend.
- **`GET /api/primario/tendencias/{setores,subsetores,segmentos}`** -- espelham os
  equivalentes em `webapp/main.py` (`_ranking_variacao`/`_periodo_anterior`,
  reimplementados como `_ranking_variacao_primario`/`_periodo_anterior_primario` sobre
  `operations_primario`/`data_referencia`), mesmo formato exato (`comparavel`,
  `periodo_atual`/`periodo_anterior`, `variacao_pp`, `participacao_atual_pct`/
  `participacao_anterior_pct`). **Achado de design**: o parâmetro `setor` aqui precisa
  ser um filtro EXATO (é o PAI de quem se quer o detalhe -- ex: ranking de subsetores
  DENTRO de um setor escolhido), nunca o `OR` combinado (setor OU subsetor) que
  `_filters_clause_primario` usa pro dropdown compartilhado -- criada uma segunda
  função de filtro, `_filters_clause_primario_exato`, só pra este caso (mesma
  distinção que já existe em `webapp/main.py` entre `_filters_clause`/tendências e o
  `OR` combinado exclusivo do motor de busca).
- **`GET /api/primario/tendencias/indexadores`** -- endpoint NOVO (não espelha nome
  nenhum do motor original), agrupa por `indexador_padronizado`, mesmo shape simples
  `[{indexador, valor_total}]` de `/api/tendencias/produtos` (sem ranking de variação --
  só composição atual, conforme `tendencias.js::loadProdutos`).
- **`GET /api/primario/subsetores`/`segmentos`** (nível superior, distintos de
  `/tendencias/*`) -- espelham `/api/subsetores`/`/api/segmentos`, usando a MESMA
  `_filters_clause_primario_exato` (o `setor`/`subsetor` vem do mesmo select próprio
  de drill-down do `tendencias.js`, nunca do dropdown compartilhado).
- **`GET /api/primario/graficos/taxas`** e **`/graficos/prazos`** -- os dois endpoints
  NOVOS pedidos como foco central desta reconciliação. Implementados com
  `percentile_cont(0.5) WITHIN GROUP` (mediana real, não média) sobre `taxa_valor`/
  `prazo_meses`, `cobertura_pct` sempre calculada a partir de contagens reais (nunca
  chumbada). `/graficos/taxas` exclui `taxa_tipo='percentual_indexador'` do
  agrupamento (multiplicativo, unidade diferente de `spread`/`taxa_fixa` -- ver seção
  Pipeline CVM).

**Bug real encontrado e corrigido nesta sessão, fora da lista original de 14 (mas no
mesmo arquivo, `webapp/primario/routes.py`)**: `GET /api/primario/kpis` já existia (de
uma sessão anterior) mas devolvia `valor_total_total` (chave que nenhum consumidor lê)
em vez de `valor_contratado_total` (a chave que `consolidado.js::loadKPIs` de fato lê,
com fallback pra `valor_total`), e nunca calculava `n_emissores_distintos` -- os cards
"Volume total emitido" e "Emissores distintos" apareciam vazios (`-`) na tela,
confirmado ao vivo pelo Browser pane ANTES da correção. Corrigido adicionando
`COUNT(DISTINCT cnpj_emissor)` e renomeando/duplicando a chave de valor total pro nome
que o contrato documentado (tabela da seção Frontend) e o frontend já esperavam.

**Nota do coordenador ao reconciliar esta sessão com outra em paralelo**: esta sessão
notou (corretamente, no momento em que rodou) que `GET /api/primario/instrumentos`/
`/filtros` devolvem `"CPR-F"` e flagou isso como possível bug de classificação, porque
seu worktree tinha sido criado ANTES de uma sessão irmã (rodando ao mesmo tempo, ver
"Segunda fonte CVM" mais acima) corrigir a exclusão indevida de CPR-F e confirmar as 18
linhas reais (Klabin, Suzano, Duratex, Adami, Eldorado Brasil Celulose, Agropecuária
Maggi etc., vindas do segundo arquivo `oferta_resolucao_160.csv`). Não é um bug: CPR-F
é um instrumento real da base, já documentado em detalhe na seção "Segunda fonte CVM"
acima — nenhuma ação adicional necessária aqui.

**Testado ao vivo nesta sessão (2026-09-16, contra produção/Aiven)**: as 14 rotas novas
+ o fix de `kpis` foram testadas por 2 caminhos: (1) via `curl`/`urllib` direto, com uma
conta de teste temporária criada e apagada depois (mesmo procedimento documentado em
"Coisas a saber antes de mexer") -- todas devolveram `200` com dados reais, incluindo
os parâmetros exatos que o frontend manda (`data_inicio`/`data_fim`/`granularidade`,
filtros combinados `uf`+`instrumento`, `setor` exato pra tendências/subsetores/
segmentos, erro `422` esperado quando `setor` obrigatório falta em
`/tendencias/subsetores`); (2) **end-to-end pelo Browser pane**, logado de verdade
(`fetch('/api/login', ...)`, mesmo caminho documentado em "Coisas a saber antes de
mexer"), servindo `webapp/static/` via `uvicorn` local contra o MESMO banco de
produção: cliquei no toggle de mercado (`#brand-toggle`), confirmei visualmente que o
Consolidado do modo Primário carrega KPIs/gráficos reais (incluindo os 2 dashboards
novos "Taxas por indexador" -- amostra 371/17.420, 2,1% -- e "Prazos por instrumento" --
1.859/17.420, 10,7%), e abri a aba Tendências & Insights confirmando que a exceção JS
relatada pelo coordenador (`Cannot read properties of undefined (reading 'filter')` em
`tendencias.js`, por causa de `/api/primario/tendencias/setores` 404) **não ocorre
mais** -- a aba renderiza corretamente (`Setores do emissor em alta/queda`, `Detalhe
por subsetor/segmento`), confirmado tanto visualmente (screenshot) quanto via
`read_network_requests` (todas as chamadas `/api/primario/tendencias/*` retornando
`200`). Conta de teste e sessão apagadas ao final (ver "Coisas a saber antes de mexer").
**Não testado**: comportamento de favoritar/histórico de busca no modo Primário (já
documentado como limitação conhecida na seção Frontend, não faz parte desta
reconciliação) e o formato exato que o frontend de fato RENDERIZA nos gráficos de
Chart.js pixel a pixel (só confirmado que os elementos aparecem com dado real, sem
exceção JS -- não uma inspeção visual detalhada de cada gráfico).

## Radar de Crédito Primário — Frontend

Construído em 2026-09-16, em cima do schema de `operations_primario` (ver seção "Radar de
Crédito Primário — Pipeline CVM" acima) — **100% frontend** (`webapp/static/*`), sem tocar em
`webapp/primario/`, `webapp/main.py`, `src/parse_cvm.py`, `src/unify_primario.py` nem
`src/db.py` (trabalho de outras duas sessões em paralelo: uma terminando a integração do 2º
lote de dados 2023-2026, outra construindo `/api/primario/*` + motor de busca). **Consequência
direta**: TUDO que este frontend espera do backend abaixo é uma **suposição de contrato**,
não uma integração testada contra rotas reais — nenhuma delas existia em `webapp/main.py` no
momento em que este frontend foi escrito (confirmado via `grep primario webapp/main.py` →
vazio). Todo consumo desses endpoints no frontend confere `Array.isArray`/tipo antes de
desenhar qualquer gráfico e trata 404/formato inesperado como "sem dado ainda" (nunca uma
exceção JS) — ver `_MERCADOS`/comentário no topo de `webapp/static/js/common.js`.

### Mecânica de troca de mercado

Um único SPA/roteador (nunca duas páginas) — `_mercadoAtivo` (`"incentivado"` | `"primario"`)
em `common.js` é a fonte da verdade; tudo deriva dela:

- **Gatilho**: clique em `#brand-toggle` (a `.brand` da topbar, ver `index.html`) chama
  `alternarMercado()` — alterna `_mercadoAtivo`, sempre pousa no Consolidado do mercado de
  destino (nunca tenta preservar a aba atual se ela não existir lá, ex: saindo de Editais) e
  cria uma entrada de **histórico nova** (`pushState` via `_ativarView(..., true)`), então
  "Voltar" no navegador volta pro mercado anterior — testado ao vivo (ver seção "Testado ao
  vivo" abaixo).
- **URL**: prefixo `/primario/...` pros 4 slugs visíveis nesse mercado (`/primario`,
  `/primario/consolidado`, `/primario/tendencias`, `/primario/busca`,
  `/primario/transacoes-salvas`) — `_mercadoESlugDaURL()` lê o mercado do 1º segmento do path
  e devolve o slug restante pro `_SLUG_PARA_VIEW` já existente (que não precisou mudar).
  `_ativarView()` monta o path final prefixando com `_MERCADOS[mercado].prefixoUrl`.
  `vercel.json` ganhou os rewrites equivalentes (`/primario`, `/primario/consolidado`,
  `/primario/tendencias`, `/primario/busca`, `/primario/transacoes-salvas` → `/index.html`) —
  **não** ajustei `webapp/main.py::spa_pagina` (catch-all do modo local `uvicorn`) por estar
  fora do escopo desta sessão; sem esse ajuste, digitar/recarregar uma URL `/primario/...`
  direto no `uvicorn` local provavelmente cai no catch-all genérico e funciona igual (serve
  `index.html`), mas **não testei isso ao vivo** (ver seção de testes) — se a rota local não
  cobrir esse caso, é um ajuste de uma linha em `spa_pagina`, a cargo de quem tocar
  `webapp/main.py`.
- **Abas visíveis** (`_MERCADOS[mercado].abasVisiveis`, também controla quais `.tab-btn`
  ficam com `display:none`): Incentivado = todas as 6; Primário = Consolidado, Tendências &
  Insights, Busca, Transações Salvas (Editais e Linhas Incentivadas escondidas — sem
  equivalente conceitual, decisão já dada pelo usuário). `_ativarView()` também **redireciona**
  pro Consolidado do mercado ativo se a view pedida não existir lá (testado: sair de Editais
  incentivado e trocar pro Primário cai em `/primario/consolidado`, nunca deixa uma aba
  escondida "ativa" por baixo dos panos).
- **Identidade textual/visual** (`_aplicarIdentidadeMercado()` em `common.js`, chamada antes
  de qualquer `_ativarView`/gráfico): `document.title`, todo elemento `.brand-texto` (topbar,
  `#loading-overlay .loading-brand`, título do `#login-card` — **não** o do `#registrar-card**,
  que continua sempre "Criar conta"), classe `body.mercado-primario` (liga os tokens de cor —
  ver "Identidade visual" abaixo) e visibilidade de qualquer elemento `[data-mercado-only]`.
- **Filtro compartilhado (`#f-agencia`)**: mesmo `<select>` físico reaproveitado com
  significado diferente — "Agência" (BNDES/FINEP) no Incentivado, "Instrumento" (Debênture/
  CRI/CRA/Nota Comercial/Letra Financeira/CDCA/CCB) no Primário — `currentFilters()`,
  `_sincronizarFiltrosCompartilhadosNaURL()` e a leitura de filtro-por-URL em
  `_initFiltersAndTabsImpl` mandam/leem a chave `instrumento` em vez de `agencia` quando
  `_mercadoAtivo==="primario"`. O rótulo (`#f-agencia-label`) troca junto. As opções do select
  são repopuladas do zero (`_repopularFiltrosCompartilhados()`, chamada por
  `alternarMercado()`) a partir de `filtros.instrumentos` em vez de `filtros.agencias` —
  **suposição de contrato**: `GET /api/primario/filtros` devolve o MESMO formato de
  `GET /api/filtros` (`agencias`→`instrumentos`, `setores`, `ufs`, `portes`, `anos`,
  `data_min`/`data_max`), com `setor`/`uf`/datas com o MESMO significado (setor do emissor via
  `cnpj_cnae`, `uf_emissor`).
- **Filtro próprio da Busca** (`#bu-f-agencia`/`#bu-f-produto`, grupo separado): mesmos 2
  selects reaproveitados — "Entidade"→"Instrumento", "Tipo de linha"→"Indexador" (CDI/IPCA+/
  SELIC/Prefixado/Outro) — chaves de URL/API viram `instrumento`/`indexador` em vez de
  `agencia`/`produto` (ver `busca.js::_filtrosBusca`/`_sincronizarFiltrosBuscaNaURL`/
  `_aplicarFiltrosBuscaDaURL`). `_popularFiltrosBusca()` foi tornada segura de chamar de novo
  (`_limparOpcoesBuscaFiltro`, remove tudo além da 1ª `<option>` antes de repopular) — chamada
  de novo por `alternarMercado()`.
- **Cache de filtro por grupo de aba** (`_ultimaQueryPorGrupo`, já existia pra não vazar filtro
  entre Consolidado/Tendências vs. Busca/Editais/Linhas): passou a ser **também** escopado por
  mercado (`_chaveCacheGrupo(view)` = `"{mercado}:{grupo}"`) — sem isso, voltar pro Incentivado
  depois de mexer em filtros no Primário restauraria uma query com `instrumento=Debênture`
  como se fosse `agencia=Debênture` (bug real que eu mesmo peguei revisando antes de testar).

### Identidade visual (accent color)

Nenhuma duplicação de CSS — 3 variáveis novas (`--accent-900`, `--accent`, `--accent-light`
em `style.css`) por padrão **iguais** a `--navy-900`/`--navy`/`--steel-2` (Incentivado fica
visualmente idêntico a antes); `body.mercado-primario` redefine as 3 pra um verde-petróleo
(`#0E2E27`/`#16463C`/`#1F6656`, mesma luminosidade aproximada da rampa navy, só o matiz muda de
azul pra verde — mantém o MESMO contraste com texto branco). Só as regras que já usavam
`--navy`/`--navy-900`/`--steel-2` pra elementos "de marca" foram trocadas pras variáveis
`--accent*` (`#loading-overlay`, `#login-overlay`, `.topbar`, `.tabs-wrap::before/::after`,
`.tab-btn.active`, `.kpi-card .value`, `.card-header`) — tipografia/espaçamento/o resto da
paleta (`--border`, `--bg`, `--card-bg` etc) são 100% compartilhados, nunca duplicados.
Testado ao vivo (ver abaixo): `getComputedStyle(topbar).backgroundColor` bate com o hex novo
assim que `body.mercado-primario` é aplicado.

### Labels/nomenclatura própria (Consolidado/Tendências)

Decisões de produto tomadas nesta sessão (não copiado 1:1 do Incentivado):

| Card | Incentivado | Primário | Motivo |
|---|---|---|---|
| Série temporal (Consolidado) | "Evolução temporal — BNDES x FINEP", agrupado por `agencia` | "Evolução temporal — por instrumento", agrupado por `instrumento` | Não há "agências" no mercado de capitais; instrumento é a dimensão mais informativa |
| Ranking (Consolidado) | "Ranking de setores" (`setor_bndes`) | "Ranking por instrumento" (`instrumento_padronizado`) | Pedido explícito do usuário como exemplo; instrumento (Debênture/CRI/CRA/...) é a dimensão mais distintiva de renda fixa |
| Mapa (Consolidado) | "Por UF" (`uf`) | "Por UF do emissor" (`uf_emissor`) | Mesmo conceito, mantido (mesma decisão que o usuário deixou em aberto: "ou mantendo o de UF se uf_emissor fizer sentido igual") |
| Doughnut (Consolidado) | "Por porte do cliente" | "Por porte do emissor" | Mesmo vocabulário de porte (`cnpj_cnae`), só troca de quem é classificado |
| "Destinação de recursos" (Tendências) | produto/instrumento BNDES/FINEP | "Distribuição por indexador" (CDI/IPCA+/SELIC/Prefixado/Outro) | Evita redundância com o ranking por instrumento do Consolidado — mostra a composição por indexador em vez de repetir instrumento |
| "Setores em alta/queda" (Tendências) | `setor_bndes` | Mesmo card, rótulo "Setores do emissor em alta/queda" (`setor_emissor`) | Setor do EMISSOR (não do "tomador de financiamento") — mesma taxonomia via `cnpj_cnae`, só a entidade classificada muda |
| Detalhe por subsetor/segmento (Tendências) | mantido | mantido, sem mudança de rótulo | `setor_emissor`/`subsetor_emissor`/`segmento_emissor` espelham a MESMA hierarquia de 3 níveis — reaproveitado sem duplicar lógica, só via `apiMercado()` |
| KPI "Volume desembolsado/pago" | mantido | substituído por "Emissores distintos" | Não existe desembolso parcelado numa oferta pública (capta de uma vez) — "emissores distintos" é mais informativo |
| Tabela "Operações do período" | Cliente/Agência | Emissor/Instrumento | Colunas renomeadas via `id` (`#tabela-maiores-th-cliente`/`#tabela-maiores-th-agencia`) |
| Modal de detalhe/drill-down (`common.js`) | Cliente/Agência/Setor/Valor contratado | Emissor/Instrumento/Setor do emissor/Valor da oferta | Modal compartilhado — rótulos trocam por `_mercadoAtivo`, campos com fallback (ver contrato abaixo) |

### Dashboards novos (taxa/prazo) — o pedido central desta tarefa

Dois cards novos, **só no modo Primário** (`data-mercado-only="primario"`, substituem
implicitamente o espaço que seria ocupado por mais conteúdo do Consolidado, mantendo mapa de
UF e porte — decisão: UF/porte continuam fazendo sentido igual, então NÃO foram removidos):

- **"Taxas por indexador"** (`#chart-taxas`): bar chart de `taxa_mediana` por `indexador`, só
  com `taxa_tipo` **'spread'/'taxa_fixa'** (mesma unidade — pontos percentuais a.a., aditivos)
  — `taxa_tipo='percentual_indexador'` (ex: "108% do CDI", multiplicativo) é **deliberadamente
  excluído do gráfico** (misturar as duas unidades no mesmo eixo seria enganoso) e só contado
  em texto no aviso (`#chart-taxas-aviso`). Aviso de amostra parcial (`n_com_taxa`/`n_total`/
  `cobertura_pct`, ~4,2% medido no pipeline — ver seção CVM) é construído **a partir do que a
  API devolver**, nunca um número fixo chumbado no frontend, pra continuar certo conforme a
  base crescer/for reenriquecida.
- **"Prazos por instrumento"** (`#chart-prazos`): bar chart horizontal de
  `prazo_mediano_meses` por `instrumento`. Mesmo padrão de aviso de amostra parcial
  (`n_com_prazo`/`n_total`, ~15,2% medido no pipeline).
- As duas funções (`loadTaxas`/`loadPrazos` em `consolidado.js`) saem cedo (e destroem
  qualquer `Chart` antigo) quando `_mercadoAtivo!=="primario"` — seguro chamar
  incondicionalmente em `refreshConsolidado()`.
- **Suposição de contrato (NÃO testado contra backend real)**:
  - `GET /api/primario/graficos/taxas?<filtros>` → `{ n_total, n_com_taxa, cobertura_pct,
    linhas: [{ indexador, taxa_tipo, n, taxa_mediana }] }`
  - `GET /api/primario/graficos/prazos?<filtros>` → `{ n_total, n_com_prazo, cobertura_pct,
    linhas: [{ instrumento, n, prazo_mediano_meses }] }`
  - Filtros passados são os mesmos de `currentFilters()` (`instrumento`, `setor`, `uf`,
    `data_inicio`/`data_fim`).

### Limitação conhecida: favoritar não funciona no modo Primário

`usuario_operacoes_salvas.operation_id` é FK pra `operations(id)` (schema do crédito de
fomento) — favoritar uma operação de `operations_primario` não tem como funcionar sem estender
esse schema, **fora do escopo desta sessão** (não mexe em `src/db.py`). Em vez de deixar o
botão quebrar silenciosamente contra o id errado, o botão do modal (`common.js::
_configurarBotaoFavoritar`) e a estrelinha mini da Busca (`busca.js::renderListaResultados`)
ficam **escondidos** quando `_mercadoAtivo==="primario"`. Se um dia isso for resolvido, é
trabalho novo (estender `usuario_operacoes_salvas` pra aceitar as duas tabelas, ex: coluna
`mercado`/`tabela_origem` + índice único composto), não uma consequência automática desta
mudança.

### Todos os endpoints `/api/primario/*` assumidos por este frontend

Nenhum destes existia em `webapp/main.py` no momento em que este frontend foi escrito — lista
completa pra quem for reconciliar com a sessão que constrói as rotas de verdade:

| Endpoint assumido | Espelha | Formato assumido |
|---|---|---|
| `GET /api/primario/status` | `/api/status` | `{ n_operacoes, hospedado, busca_ia_ativa, ... }` |
| `GET /api/primario/filtros` | `/api/filtros` | `{ instrumentos, indexadores, setores, subsetores, ufs, portes, anos, data_min, data_max }` (troca `agencias`→`instrumentos`, ganha `indexadores`) |
| `GET /api/primario/kpis` | `/api/kpis` | `{ n_operacoes, valor_contratado_total, n_emissores_distintos, cheque_medio, por_instrumento: [{instrumento, valor_total}] }` |
| `GET /api/primario/serie_temporal` | `/api/serie_temporal` | linhas `{ ano, periodo, instrumento, valor_total }` (troca `agencia`→`instrumento`) |
| `GET /api/primario/instrumentos` | `/api/setores` (endpoint NOVO, não um espelho de nome) | `[{ instrumento, valor_total, n_operacoes }]` |
| `GET /api/primario/uf` | `/api/uf` | `[{ uf, valor_total, n_operacoes }]` (via `uf_emissor`) |
| `GET /api/primario/porte` | `/api/porte` | `[{ porte, valor_total }]` (via `porte_emissor`) |
| `GET /api/primario/operacoes` e `/operacoes/{id}` e `/operacoes/{id}/grupo-economico` | idem | mesmo formato — modal/tabela usam fallback (`cliente??emissor`, `agencia??instrumento`, `setor_bndes??setor_emissor`, `data_contratacao??data_referencia`, `valor_contratado??valor_emissao??valor_oferta`) |
| `GET /api/primario/tendencias/setores`, `/subsetores`, `/segmentos` | idem | mesmo formato (`setor`/`subsetor`/`segmento` = do emissor) |
| `GET /api/primario/tendencias/indexadores` | `/api/tendencias/produtos` (NOVO nome) | `[{ indexador, valor_total }]` |
| `GET /api/primario/subsetores`, `/segmentos` | idem | mesmo formato |
| `GET /api/primario/busca` | `/api/busca` | mesmo formato, campos de resultado com o mesmo fallback do modal acima |
| `GET /api/primario/graficos/taxas` | endpoint NOVO | ver seção "Dashboards novos" acima |
| `GET /api/primario/graficos/prazos` | endpoint NOVO | ver seção "Dashboards novos" acima |

### Testado ao vivo vs. suposto

**Testado ao vivo** (servindo `webapp/static/` isolado, sem backend real — ver limitação
abaixo): clique no brand alterna `_mercadoAtivo`/título/textos/classe do body/cor de destaque
(`getComputedStyle` confirmado); URL ganha/perde prefixo `/primario/` corretamente ao trocar
de mercado E ao trocar de aba dentro do mesmo mercado; abas Editais/Linhas somem no Primário
(`display:none` confirmado) e reaparecem no Incentivado; sair de uma aba só-Incentivado
(Editais) e trocar pro Primário redireciona pro Consolidado (nunca deixa view inválida
"ativa"); **histórico do navegador funciona atravessando a fronteira de mercado** (testado com
`history.back()` duas vezes: `/primario/consolidado` → toggle → `/consolidado` →
back → volta pro Primário em `/primario/busca` → back → `/primario/consolidado`, com
título/`_mercadoAtivo` corretos em cada passo); os cards de Taxas/Prazos aparecem só no
Primário e mostram o estado "sem dado" corretamente quando o endpoint não existe (404 vira
card vazio, nunca exceção JS); nenhum erro de console além dos 404/401 esperados (sem backend
real disponível pra testar, ver abaixo).

**NÃO testado** (backend `/api/primario/*` não existe nesta branch — ver aviso no topo do
arquivo e desta seção): formato real de resposta de qualquer endpoint da tabela acima; se
`webapp/main.py::spa_pagina` (modo `uvicorn` local) serve corretamente uma URL `/primario/...`
digitada direto/recarregada (só os rewrites do `vercel.json`, usados em produção/Vercel, foram
adicionados nesta sessão); comportamento de favoritar/histórico de busca quando logado (exige
sessão real contra o Aiven de produção, fora do escopo de um teste rápido de mecânica de
frontend — ver CLAUDE.md, seção "Coisas a saber antes de mexer", sobre como logar de verdade
se precisar testar isso depois).

## Radar de Crédito Primário — Redesenho Consolidado/Tendências (2026-09-17)

Sessão pedida explicitamente pelo usuário para **repensar de verdade** os cards de
Consolidado/Tendências no modo Primário — até aqui (ver seções anteriores) eles eram, em boa
parte, um reaproveitamento/relabel direto dos cards do crédito incentivado (BNDES/FINEP), nunca
desenhados a partir do zero pro contexto de emissão de dívida em mercado de capitais. Escopo
desta sessão: só `webapp/static/*` e `webapp/primario/routes.py` — **`src/*` e
`webapp/main.py` não foram tocados** (uma sessão paralela mexe no pipeline de dados ao mesmo
tempo; todo número de cobertura abaixo foi medido AO VIVO contra produção nesta data, mas pode
mudar com o próximo refresh diário — nada aqui assume uma contagem fixa no código, os avisos de
amostra parcial são sempre calculados a partir da resposta real da API).

**Cobertura medida ao vivo (2026-09-17, `operations_primario`, já com o corte 2010+ em vigor)**:
total 15.076 linhas, `data_referencia` 2010-01-15 a 2026-12-03. `incentivada`: 1.444 Sim / 9.203
Não / 4.429 Não informado. `regime_fiduciario`: 2.906 Sim / 38 Não / 12.132 Não informado.
`setor_emissor`/`porte_emissor` NULL só em 19 linhas (99,87% resolvido). `uf_emissor` NULL em
5.483 linhas (36,4% — ver nota sobre `cnpj_cnae` legado abaixo). `taxa_valor` não-nulo em 239
linhas (1,6%). `prazo_meses` não-nulo em 534 linhas (3,5%). `indexador_padronizado` não-nulo em
254 linhas (1,7%, concentradas quase todas em 2010-2022 — só 2 linhas de 2023 em diante, ZERO
em 2024-2026). `agente_fiduciario` não-nulo em 5.200 linhas (34,5%), `custodiante` em 2.453
(16,3%) — ambos só vêm de `cvm_oferta_resolucao_160_raw` (2022+). `porte_emissor`: 15.054 de
15.076 (99,85%!) são `'Demais'`, só 3 são `'Empresa de Pequeno Porte'`, nenhuma `'Micro
Empresa'`. **Achado real que já muda a análise de cobertura antiga do CLAUDE.md**: os números
de cobertura de taxa/prazo documentados na sessão anterior (~4,2%/~15,2%) caíram bastante
(~1,6%/~3,5%) depois do corte 2010+ e da integração do 2º arquivo CVM (resolução 160, que NUNCA
tem taxa/prazo/indexador) — o denominador cresceu bem mais que o numerador. Isso não invalida
os cards (ver decisão abaixo), só significa que o texto de aviso de amostra parcial (sempre
calculado ao vivo, nunca chumbado) hoje mostra um percentual menor do que quando foi escrito.

### Auditoria card a card — Consolidado

| Card | Decisão | Motivo |
|---|---|---|
| KPI row (nº operações, volume, emissores distintos, ticket médio) | **(a) mantém** | Já bem adaptado (KPI "emissores distintos" e "volume emitido" fazem sentido genuíno pro mercado de capitais, sem inventar "desembolso parcelado" que não existe numa oferta pública). |
| Série temporal por instrumento (stacked bar) | **(a) mantém** | `instrumento_padronizado` tem cobertura de 100% e boa distribuição temporal 2010-2026 — mostra a evolução real do mix de instrumentos, o pedido nº 2 da tarefa ("composição por instrumento ao longo do tempo") já estava bem servido aqui. |
| **"Ranking por instrumento" (bar chart)** | **(c) REMOVIDO** | Redundante DENTRO do próprio Consolidado: a mesma informação (volume por instrumento) já aparece na série temporal empilhada logo acima E no texto `por_instrumento` do KPI de volume total — um terceiro gráfico mostrando exatamente a mesma soma, sem dimensão nova (tempo ou drill-down), não agregava nada. Era também o card mais "cru" — um relabel 1:1 do "Ranking de setores" do Incentivado, nunca repensado. |
| **NOVO: "Estrutura da oferta"** (2 donuts: Incentivada Lei 12.431 + Regime fiduciário) | Substitui o card acima | Pedido explícito da tarefa: `incentivada` nunca tinha aparecido em NENHUM card, apesar de ser o cross-link temático mais óbvio com o resto do site ("Radar de Crédito INCENTIVADO"). Cobertura real (1.444 Sim/9.203 Não/4.429 Não informado — nenhum dos 3 baldes é desprezível) confirma que vale a pena mostrar. `regime_fiduciario` entra no mesmo card por ser a mesma categoria de "atributo estrutural binário da oferta", mesmo fetch (`/estrutura_mercado`), sem custo adicional de rede. |
| Por UF do emissor (mapa) | **(a) mantém** | Geografia do emissor é uma pergunta real de mercado de capitais. `uf_emissor` tem 36,4% de NULL — mais alto que `setor_emissor` (0,1%) pelo MESMO CNPJ, porque `cnpj_cnae` tem entradas antigas (herdadas do enriquecimento BNDES/FINEP, antes de `uf`/`municipio` existirem naquela tabela — ver seção Pipeline CVM) sem esses 2 campos preenchidos; o mecanismo `IE`/`NI` do mapa já trata esse caso com uma legenda textual honesta, sem esconder o volume. |
| Por porte do emissor (donut) | **(c) REMOVIDO** | **Achado real medido ao vivo**: 15.054 de 15.076 linhas (99,85%!) caem no MESMO balde `'Demais'` — só 3 linhas são `'Empresa de Pequeno Porte'`, nenhuma `'Micro Empresa'`. Faz sentido (empresas que emitem dívida em mercado de capitais público são, por definição, de grande porte — diferente do crédito de fomento, que atinge micro/pequenas), mas isso torna o donut um círculo de uma cor só, sem NENHUM poder discriminante. Exatamente o tipo de card que a tarefa pediu pra remover ("não está sendo usado direito"). |
| **NOVO: "Por tipo de lastro"** (donut Pulverizado/Concentrado/Não informado) | Substitui o card acima | Dimensão real de risco de estruturas securitizadas (CRI/CRA) que nunca tinha aparecido em nenhum card — 1.970 Concentrado / 489 Pulverizado / 12.617 Não informado (83,7%, só linhas do 2º arquivo CVM têm esse campo). Mesmo fetch de `/estrutura_mercado` (nenhum round-trip novo). |
| **"Taxas por indexador"** / **"Prazos por instrumento"** (já existiam) | **(a) mantém, cobertura reavaliada** | Cobertura caiu pra ~1,6%/~3,5% (ver nota acima) — mesmo assim, mantidos: o aviso de amostra parcial já é honesto e calculado ao vivo (nunca escondido), e o dado que existe continua sendo real/verificável. Cortar um card só porque a cobertura caiu, sem que ele tenha ficado ENGANOSO, seria descartar sinal real. |

### Auditoria card a card — Tendências & Insights

| Card | Decisão | Motivo |
|---|---|---|
| Setores do emissor em alta/queda | **(a) mantém** | Cobertura excelente (99,87% resolvido) e o ranking de variação é um sinal real de tendência de mercado. |
| Detalhe por subsetor / Detalhe por segmento (CNAE) | **(a) mantém** | Mesma taxonomia/cobertura de setor, reaproveitada sem duplicar lógica — já testado ao vivo em sessão anterior. |
| "Distribuição por indexador" (`loadProdutos`) | **(b) REFORMULADO** | **Achado real**: a resposta de `/tendencias/indexadores` tem uma linha `"Não informado"` que sozinha somava ~98,3% do total (indexador só vem do arquivo CVM principal, que praticamente para de contribuir a partir de 2023 — ver nota abaixo) — deixar essa fatia no gráfico tornava o card ilegível (uma barra gigante + traços quase invisíveis pros valores reais). Reformulado pra excluir "Não informado" do desenho e mostrar a cobertura real como aviso explícito (`#chart-produtos-aviso`), mesmo padrão de `#chart-taxas-aviso`/`#chart-prazos-aviso`. O endpoint em si (`/api/primario/tendencias/indexadores`) NÃO mudou — a reformulação é 100% frontend (`tendencias.js::loadProdutos`). |
| Operações do período (tabela) | **(a) mantém** | Útil como está, colunas já corretamente renomeadas (Emissor/Instrumento) numa sessão anterior. |
| **NOVO: "Evolução da participação Lei 12.431"** (stacked bar Sim/Não/Não informado por trimestre) | Novo card | Complementa o donut "Estrutura da oferta" (composição atual) com a dimensão de TEMPO. |
| **NOVO: "Principais agentes fiduciários e custodiantes"** (ranking com toggle) | Novo card | "Quem estrutura as ofertas" — dimensão de mercado de capitais sem equivalente no crédito de fomento. Cobertura parcial (34,5%/16,3%) mas concentrada e honesta (só 2022+, aviso explica o porquê). |

**Por que NÃO virou um card "Evolução do mix por indexador ao longo do tempo"** (a ideia
original desta sessão, descartada DEPOIS de medir os dados reais, antes de publicar): uma
primeira versão tentou uma série temporal por `indexador_padronizado` — mas
`indexador_padronizado` só vem do arquivo CVM principal (`cvm_oferta_distribuicao_raw`), que
**praticamente para de contribuir linhas a partir de 2023** (ver seção "Segunda fonte CVM"
acima); medido ao vivo, `indexador_padronizado` tem exatamente **0 linhas não-nulas em 2024,
2025 e 2026** (a atividade recente é quase toda via `cvm_oferta_resolucao_160_raw`, que NUNCA
tem esse campo). Um gráfico de evolução por indexador cairia a zero justo nos anos mais
recentes — pareceria (de forma enganosa) que "o mercado indexado sumiu em 2023", quando na
verdade é só um artefato de qual arquivo CVM cobre qual período, não um sinal de mercado real.
Isso violaria a regra de ouro do projeto (nunca mostrar um gráfico que sugira algo que o dado
não sustenta) — trocado por `incentivada` (populada pelos DOIS arquivos CVM, cobertura real
contínua 2010-2026, confirmado ao vivo por ano) como a série temporal nova de Tendências.

**Achado de qualidade de dado, observado mas NÃO corrigido (fora do escopo — é dado
`agente_fiduciario`/`custodiante`, texto livre da CVM, não teria como normalizar sem tocar
`src/*`)**: o ranking de "Principais agentes fiduciários e custodiantes" mostra o MESMO agente
real (ex: "Pentágono S.A. Distribuidora de Títulos e Valores Mobiliários") em várias variantes
de capitalização/pontuação (`PENTÁGONO S.A. ...` maiúsculo, `Pentágono S.A. ...` mixed case, com
e sem ponto final) como linhas SEPARADAS do ranking — o texto vem cru da CVM
(`cvm_oferta_resolucao_160_raw`), sem normalização. Isso dilui a posição de cada agente no
ranking (nenhum bug de agregação do lado deste redesenho — `GROUP BY agente_fiduciario` está
correto, é a fonte que tem múltiplas grafias). Se um dia isso incomodar, normalizar essas
strings (upper+trim+remover pontuação) é trabalho de pipeline (`src/unify_primario.py`), fora
do escopo desta sessão (que não toca `src/*`).

### Rotas novas em `webapp/primario/routes.py`

- **`GET /serie_temporal_incentivada`**: espelha `/serie_temporal`, trocando o agrupamento por
  `instrumento_padronizado` por `incentivada` (mapeado pra `'Sim'/'Não'/'Não informado'` via
  `CASE`). Alimenta o card novo de Tendências.
- **`GET /estrutura_mercado`**: bundla 3 dimensões nunca expostas em nenhum card
  (`incentivada`, `regime_fiduciario`, `tipo_lastro`) + ranking top-10 de `agente_fiduciario`/
  `custodiante` com cobertura real, num ÚNICO endpoint (mesmo espírito de `/kpis` bundlar
  várias agregações pequenas) — alimenta os 2 donuts + o donut de tipo de lastro no Consolidado
  E o ranking de agentes/custodiantes em Tendências (o frontend faz UM fetch só, reaproveitado
  nos dois lugares/páginas). `_ranking_texto_com_cobertura()` (helper novo, reaproveitado pelos
  2 rankings) segue o mesmo padrão de `/graficos/taxas`/`/graficos/prazos`: cobertura sempre
  calculada a partir de contagens reais, nunca um número fixo.

### BUG REAL de CSS encontrado e corrigido durante o teste ao vivo desta sessão

`webapp/static/css/style.css` tinha, desde a construção original do toggle de mercado, uma
regra genérica `[data-mercado-only="primario"] { display: none; }` (esconde por padrão,
evitando flash de conteúdo errado antes do JS decidir) — `_aplicarIdentidadeMercado()` (em
`common.js`, NÃO tocado nesta sessão) então faz `el.style.display = "" ` (limpa o inline) pro
caso "deveria mostrar", contando com a cascata CSS pra "revelar" o elemento. Isso só funcionava
por acidente pros usos ORIGINAIS desse atributo (sempre em `<div class="grid-2" ...>`, que já
tem sua PRÓPRIA regra `display:grid` definida MAIS ABAIXO no arquivo — em caso de empate de
especificidade, a regra que vem depois no arquivo vence, então `.grid-2` sempre vencia a regra
genérica de escondido). Os 2 cards novos desta sessão ("Estrutura da oferta"/"Por tipo de
lastro") usam `data-mercado-only="primario"` diretamente num `<div class="card">` — e `.card`
NUNCA teve uma regra de `display` própria (usa o bloco padrão do navegador), então nada vencia
a regra genérica de escondido, e os cards ficavam **invisíveis mesmo no mercado certo**
(confirmado ao vivo: `getComputedStyle` retornava `"none"` com o `style.display` inline já
limpo pelo JS). **Corrigido** adicionando uma regra mais específica, gatilhada pela MESMA
classe que `_aplicarIdentidadeMercado()` já aplica ao `<body>`
(`body.mercado-primario .card[data-mercado-only="primario"] { display: block; }`) — não
precisou mudar `_aplicarIdentidadeMercado()` em si nem afeta o caso `.grid-2` que já
funcionava. **Lição pra qualquer card novo que use `data-mercado-only` diretamente num `.card`
(em vez de um `.grid-2` inteiro)**: conferir que existe uma regra CSS específica o suficiente
pra vencer o escondido-por-padrão quando o JS só limpa o inline — não basta confiar que "";
funciona igual em todo elemento.

### Testado ao vivo vs. suposto (2026-09-17)

**Testado ao vivo**, contra produção (Aiven), com uma conta de teste temporária criada e
apagada depois (mesmo procedimento de "Coisas a saber antes de mexer" — login via
`fetch('/api/login', {credentials:'include'})`, sessão real). **Achado de infraestrutura desta
sessão**: navegar (`navigate`/`location.href`) no Browser pane deste ambiente **não preserva o
cookie de sessão** entre a página que fez o login e a página seguinte (confirmado: login via
`fetch` funciona e uma chamada `/api/status` na MESMA página/mesmo documento (sem navegar)
retorna 200, mas qualquer navegação subsequente — inclusive `location.href` disparado de dentro
da própria página — volta a dar 401). Contornado testando tudo dentro do MESMO carregamento de
página via `javascript_tool` (login + `initFiltersAndTabs()` + `alternarMercado()` +
`refreshConsolidado()`/`refreshTendencias()` chamados manualmente, sem nenhuma navegação real
depois do login) — suficiente pra confirmar renderização real com dado de produção, mas **não
foi testado o fluxo normal de login pela UI (usuário digitando usuário/senha e clicando
Entrar)**, só o caminho fetch direto; não há razão pra crer que seja diferente (mesmo endpoint,
mesmo cookie), mas fica registrado como não testado neste formato específico.

Confirmado visualmente e via inspeção de `Chart.js` (`chart.data`) com dado REAL: os 2 donuts
de "Estrutura da oferta" (Incentivada/Regime fiduciário) e o donut "Por tipo de lastro"
renderizam com as proporções certas; "Evolução da participação Lei 12.431" mostra as 3 séries
(Sim/Não/Não informado) por trimestre 2010-2026 com os mesmos totais medidos diretamente no
banco; "Principais agentes fiduciários e custodiantes" mostra o ranking real (Pentágono/
Oliveira Trust/Vórtx no topo) e o toggle Agente fiduciório↔Custodiante troca o gráfico sem
refazer a chamada de rede (conferido: um único fetch de `/estrutura_mercado`, reaproveitado);
"Distribuição por indexador" reformulado mostra só CDI/IPCA+/Outro/Prefixado (sem "Não
informado") com o aviso de cobertura real (1,7%). Nenhuma exceção JS nova introduzida por este
redesenho (os erros 401 que aparecem no console são só do carregamento inicial da página, antes
do login manual de teste — esperado neste ambiente de teste, não um bug). **Sanity check
final**: `python -c "import ast; ast.parse(...)"` em `routes.py` e contagem de chaves
balanceadas nos 2 arquivos JS editados, sem erro.

**NÃO testado**: o fluxo de login real pela UI (só via fetch direto, ver acima); o botão
"Buscar de novo"/filtros da aba Busca no modo Primário (fora do escopo desta tarefa, que pediu
só Consolidado/Tendências); comportamento em mobile/telas estreitas dos 2 mini-donuts lado a
lado no card "Estrutura da oferta" (só testado em desktop).

**Servidor local usado pro teste**: `uvicorn` iniciado manualmente (`python -m uvicorn
webapp.main:app`) a partir DESTE worktree, numa porta própria (8010) — **achado de
infraestrutura**: o mecanismo `preview_start` por nome deste ambiente resolveu pro
`.claude/launch.json` do repo PRINCIPAL (fora do worktree, `name: "radar-webapp"`, porta 8000),
não pro `.claude/launch.json` criado dentro deste worktree — ficou servindo os arquivos
ANTIGOS (do repo principal, sem as edições desta sessão) mesmo pedindo o nome do config do
worktree. Contornado subindo o `uvicorn` manualmente via Bash a partir do worktree, numa porta
diferente, e abrindo essa URL direto no Browser pane (`navigate`) em vez de `preview_start` por
nome — se uma sessão futura precisar testar ao vivo dentro de um worktree, valide primeiro que
o arquivo servido bate com o do disco (`curl localhost:<porta>/js/arquivo.js | grep <trecho
novo>`) antes de gastar tempo depurando um "bug" que na verdade é cache/arquivo errado.
**Processo encerrado ao final do teste** (a pedido do coordenador, que reportou esgotamento de
conexões do Aiven em produção durante esta sessão — `uvicorn` local + `preview_stop` do
servidor do Browser pane, confirmado via `Get-NetTCPConnection` que nenhuma conexão restante
apontava pro host do Aiven).

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
| Radar de Crédito Primário (CVM, pipeline de dados) | `src/download_cvm.py`, `src/parse_cvm.py`, `src/parse_cvm_resolucao160.py` (2ª fonte, rito automático), `src/unify_primario.py`, `src/refresh_primario.py` |
| Radar de Crédito Primário (API/rotas + motor de busca) | `webapp/primario/routes.py`, `src/search_fts_primario.py` |
| Radar de Crédito Primário (frontend/toggle de mercado) | `webapp/static/js/common.js` (`_MERCADOS`/`alternarMercado`), `consolidado.js`/`tendencias.js`/`busca.js` (rótulos e chamadas `apiMercado()`) — ver CLAUDE.md, seção "Radar de Crédito Primário — Frontend" |
| API/rotas | `webapp/main.py` |
| Frontend (abas, roteamento, filtros) | `webapp/static/js/common.js`, `webapp/static/index.html` |
| Frontend (cada aba) | `webapp/static/js/{consolidado,tendencias,busca,editais,linhas}.js` |
| Painel de Admin (`/admin`) | `webapp/admin/*`, `webapp/static/admin.html`, `webapp/static/js/admin.js` |
| Transações Salvas (favoritos/histórico por usuário) | `webapp/salvos.py`, `webapp/static/js/salvos.js` |
| Deploy Vercel | `vercel.json`, `api/index.py`, `DEPLOY.md` |
| Automação | `.github/workflows/*.yml` |
