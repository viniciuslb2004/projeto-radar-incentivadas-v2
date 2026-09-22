# Funcionalidades removidas (2026-09-21/22) — backup técnico de restauração

Este arquivo é um backup técnico puro, para quem precisar RECONSTRUIR uma das funcionalidades
removidas. Não é lido rotineiramente por nenhuma sessão de IA — não é referenciado a partir do
`CLAUDE.md` nem de nenhum outro doc operacional. Se você chegou aqui, é porque decidiu religar
Mercado Primário, Exportações, Transações Salvas, o cadastro com aprovação (login por
usuário+senha do site principal) ou a seção "Saúde do banco" do painel.

As três primeiras funcionalidades (seções 1-3) foram removidas juntas, em 2026-09-21/22, a
pedido explícito do usuário (reposicionamento inicial da plataforma). A seção 4 (cadastro com
aprovação + "Saúde do banco") foi removida numa sessão seguinte, também em 2026-09-22, como
parte do MESMO reposicionamento (de ferramenta com cadastro pra plataforma pública de
geração de leads, com identificação passwordless — ver `docs/painel-admin.md`). Nada abaixo é
short — é deliberadamente verboso o suficiente pra reconstruir sem precisar vasculhar `git log`
a fundo, mas os NÚMEROS/achados-ao-vivo detalhados de cada decisão de produto (ex: por que
"Ranking por instrumento" foi removido do Consolidado do modo Primário) ficam só no histórico
do git (`git log --all --oneline -- webapp/primario/`, `git log --all -- webapp/salvos.py`
etc.) e nos commits do CLAUDE.md anteriores a esta remoção — este arquivo prioriza "o que
existia e como recriar", não repetir cada frase de raciocínio.

---

## 1. Mercado Primário (Radar de Crédito Primário — CVM)

Segundo "modo" da plataforma (toggle de mercado na topbar), cobrindo o mercado de capitais
primário brasileiro (debêntures, CRI, CRA, notas comerciais/promissórias, letras financeiras,
CDCA, CCB, CPR-F) via dados da CVM. Construído em várias sessões entre 2026-09-16 e 2026-09-18.

### 1.1 Componentes/arquivos removidos

**Backend (pacote inteiro + módulos de pipeline)**:
- `webapp/primario/__init__.py`, `webapp/primario/routes.py` (rotas `/api/primario/*`,
  ~969 linhas — filtros, kpis, serie_temporal, instrumentos, uf, porte, operacoes (+detalhe
  +grupo-economico), busca, tendencias/{setores,subsetores,segmentos,indexadores},
  subsetores, segmentos, graficos/{taxas,prazos}, serie_temporal_incentivada,
  estrutura_mercado, status)
- `src/download_cvm.py` — baixa `oferta_distribuicao.zip` (contém `oferta_distribuicao.csv` +
  `oferta_resolucao_160.csv`) e o zip de metadados equivalente, da CVM (Portal de Dados
  Abertos, dataset "Ofertas Públicas de Distribuição", licença ODbL)
- `src/parse_cvm.py` — parse do CSV principal pra `cvm_oferta_distribuicao_raw` (encoding
  latin-1, delimitador `;`, filtro de escopo por regex `_ESCOPO_REGEX`/`ESCOPO_REGEX_DIVIDA`
  sobre `Tipo_Ativo`, incremental por `row_hash`)
- `src/parse_cvm_resolucao160.py` — parse do segundo CSV (rito automático/Resolução CVM 160)
  pra `cvm_oferta_resolucao_160_raw`, mesmo padrão
- `src/unify_primario.py` (~884 linhas) — `build_operations_primario()`, mapas de
  padronização (`INSTRUMENTO_PADRONIZADO_MAP`), extração de indexador/taxa/prazo
  (`_indexador_padronizado`, `_extrair_taxa`, `_prazo_dias_e_meses`), corte temporal 2010+
  (`_filtrar_corte_temporal`, `DATA_CORTE_MINIMA`), motor de busca
  (`_atualizar_busca_primario`, `backfill_busca_primario`), reclassificação de emissores
  pendentes, `backfill_taxa_e_prazo()`
- `src/refresh_primario.py` — orquestrador do pipeline (download → parse (2x) → unify →
  enrich_cnae → reclassificar)
- `src/search_fts_primario.py` — motor de busca sem IA (4 tiers: CNPJ/nome, instrumento+setor,
  full-text via `search_vector`, trigram)
- `.github/workflows/refresh-primario.yml` — cron diário 09:00 UTC, `workflow_dispatch`
  habilitado

**Frontend** (`webapp/static/*`, edições dentro de arquivos compartilhados, não arquivos
inteiros — ver diffs no git se precisar do texto exato):
- `common.js`: `_MERCADOS` (config dos 2 mercados: prefixoUrl/prefixoApi/titulo/abasVisiveis),
  `_mercadoESlugDaURL()`, `_mercadoAtivo` (variável global), `apiMercado(caminho)` (prefixava
  `/api/primario` quando ativo), `_atualizarAbasVisiveisDoMercado()`,
  `_aplicarIdentidadeMercado()` (título/brand/classe `body.mercado-primario`/
  `[data-mercado-only]`), `alternarMercado()` (handler do clique em `#brand-toggle`),
  `_repopularFiltrosCompartilhados()`. `_fetchFiltrosCompartilhado()` foi SIMPLIFICADA (não
  removida — cache de `/api/filtros` é uma otimização genérica que sobrou, só perdeu a chave
  por mercado). `openOperacoesModal`/`openOperacaoDetalhe` perderam os fallbacks de campo
  (`op.cliente ?? op.emissor` etc.) e os rótulos condicionais por mercado.
- `consolidado.js`: `loadTaxas()`, `loadPrazos()`, `_donutBooleano()`, `_donutCategorico()`,
  `loadEstruturaOferta()`, `_aplicarRotulosMercadoConsolidado()`, variáveis `chartTaxas`/
  `chartPrazos`/`chartIncentivada`/`chartRegimeFiduciario`/`chartTipoLastro`.
  `loadKPIs`/`loadSerieTemporal`/`loadSetores`/`loadUF`/`loadPorte` perderam os branches
  `_mercadoAtivo === "primario"`.
- `tendencias.js`: `loadIncentivadaEvolucao()`, `_renderEstruturaRanking()`,
  `loadEstruturaRanking()`, `_aplicarRotulosMercadoTendencias()`, variáveis
  `chartIncentivadaEvolucao`/`chartEstruturaRanking`/`_ultimaEstruturaMercado`.
- `busca.js`: branches `_mercadoAtivo === "primario"` em `_filtrosBusca`,
  `_sincronizarFiltrosBuscaNaURL`, `_aplicarFiltrosBuscaDaURL`, `_popularFiltrosBusca`,
  `renderResultados` (texto "base de ofertas do mercado de capitais"), `runBusca`
  (`apiMercado("/api/busca")`).
- `index.html`: `id="brand-toggle"` + `title="Clique para alternar..."` na `.brand`;
  `data-mercado-only="incentivado"` nas abas Editais/Linhas; 2 cards do Consolidado
  ("Estrutura da oferta" com `#chart-incentivada`/`#chart-regime-fiduciario`, "Por tipo de
  lastro" com `#chart-tipo-lastro`); grid `data-mercado-only="primario"` com
  "Taxas por indexador" (`#chart-taxas`)/"Prazos por instrumento" (`#chart-prazos`); grid
  `data-mercado-only="primario"` em Tendências com "Evolução da participação Lei 12.431"
  (`#chart-incentivada-evolucao`) e "Principais agentes fiduciários e custodiantes"
  (`#chart-estrutura-ranking` + `#estrutura-dimensao-select`).
- `style.css`: `--accent-900`/`--accent`/`--accent-light` (tokens de cor, viraram alias de
  `--navy-900`/`--navy`/`--steel-2` — usos substituídos pelos tokens navy diretos, não
  removidos, já que ainda são usados pra topbar/cards/etc.), `body.mercado-primario` (redefinia
  os 3 tokens pra verde-petróleo `#0E2E27`/`#16463C`/`#1F6656`), `[data-mercado-only="primario"]
  {display:none}`, `body.mercado-primario .card[data-mercado-only="primario"] {display:block}`.

### 1.2 Tabelas removidas (Postgres/Aiven, produção)

Todas com backup criado ANTES do `DROP TABLE`, via
`CREATE TABLE <tabela>_removido_backup AS SELECT * FROM <tabela>` (contagem de linhas do
backup conferida = contagem original antes de dropar; nenhuma linha perdida):

| Tabela original | Linhas (2026-09-21) | Nome do backup |
|---|---|---|
| `cvm_oferta_distribuicao_raw` | 12.232 | `cvm_oferta_distribuicao_raw_removido_backup` |
| `cvm_oferta_resolucao_160_raw` | 5.242 | `cvm_oferta_resolucao_160_raw_removido_backup` |
| `operations_primario` | 15.116 | `operations_primario_removido_backup` |
| `refresh_primario_log` | 7 | `refresh_primario_log_removido_backup` |

Nota: `operations_primario_pre2010_backup` (2.358 linhas, criada em 2026-09-17 pelo corte de
escopo temporal 2010+, documentado na seção "Corte de escopo temporal" abaixo) **NÃO foi
tocada** — continua existindo em produção, separada dos backups `_removido_backup` acima.

O schema dessas 4 tabelas (colunas completas com comentários) foi removido de `src/db.py`
(`SCHEMA` + `MIGRACOES_COLUNAS`) — para recriar o schema exato, ver o texto completo em
qualquer commit do git anterior a esta remoção (`git log --all -- src/db.py`, procurar o commit
que adicionou `cvm_oferta_distribuicao_raw`/`operations_primario`) ou reconstruir a partir das
colunas listadas na seção 1.4 abaixo (lista completa de campos de `operations_primario`).

`cnpj_cnae.uf`/`cnpj_cnae.municipio` (colunas adicionadas originalmente só pra viabilizar
`operations_primario`) foram **mantidas** — `enrich_cnae.py::enrich_pendentes_via_api` ainda
grava nelas de qualquer forma (a BrasilAPI devolve os dois campos na mesma chamada usada pra
CNAE/porte/natureza jurídica), e remover exigiria `ALTER TABLE DROP COLUMN` em produção, fora
do escopo desta remoção. Nenhum consumidor lê esses dois campos hoje.

### 1.3 Outros pontos tocados

- `vercel.json`: removidos os rewrites `/primario`, `/primario/consolidado`,
  `/primario/tendencias`, `/primario/busca`, `/primario/transacoes-salvas` → `/index.html`.
- `webapp/main.py`: removido `from webapp.primario.routes import router as primario_router` +
  `app.include_router(primario_router, prefix="/api/primario")`; removida `_SPA_PAGINAS_PRIMARIO`
  + rota `spa_pagina_primario` (`/primario/{pagina}`); `_SPA_PAGINAS` perdeu `"primario"`.
- `api/requirements.txt`/`requirements.txt` (raiz): nenhuma dependência específica de Primário
  (usava só `requests`/`pandas`/`psycopg`, já presentes por outros motivos).

### 1.4 Conteúdo técnico completo (copiado das 3 sessões originais, para reconstrução)

O texto abaixo é uma cópia quase literal do que existia em `CLAUDE.md` (e, numa reestruturação
posterior feita por outra sessão em paralelo — fora deste worktree —, também em
`docs/radar-primario-pipeline.md`/`docs/radar-primario-api-busca.md`/
`docs/radar-primario-frontend.md`, que este worktree nunca chegou a ter porque sua branch
diverge de antes dessa reestruturação). Preservado na íntegra por ser o material de
reconstrução mais detalhado disponível.

#### 1.4.1 Pipeline CVM (staging + `operations_primario`)

Fonte: CVM — Portal de Dados Abertos, dataset "Ofertas Públicas de Distribuição". Licença ODbL,
mantido pela SRE/CVM, atualizado diariamente. A URL do dado termina em `.zip`, não `.csv`
(`.../DADOS/oferta_distribuicao.zip`, ~5.3MB) — contém DOIS CSVs dentro:
`oferta_distribuicao.csv` (dataset principal) E `oferta_resolucao_160.csv` (rito automático,
Resolução CVM 160, sucessora da ICVM 400/476 pra maior parte das emissões modernas — cobre
quase toda a atividade de 2023 em diante). `src/download_cvm.py` extraía por NOME do arquivo
dentro do zip, nunca por posição. Mesmo achado no zip de metadados
(`meta_oferta_distribuicao.zip` → `meta_oferta_distribuicao.txt` +
`meta_oferta_resolucao_160.txt`). Encoding **latin-1**, delimitador `;`.

Dataset completo: ~48,9 mil linhas (todas as ofertas já registradas/dispensadas desde 1989 —
ações, cotas de fundo, BDR, CRI/CRA, debênture etc.). Filtro de escopo (só instrumentos de
DÍVIDA, via regex com `\b` sobre `Tipo_Ativo` normalizado): 12.239 linhas no arquivo principal
(1989–2025) + 5.188 linhas no segundo arquivo (2023–2026, campo `Valor_Mobiliario`, nomenclatura
diferente pro mesmo instrumento). Deliberadamente fora de escopo: ações, cotas de
fundos/FIDC/FIP/FII, BDR, warrants, certificado de investimento audiovisual, e as poucas linhas
"CERTIFICADOS DE RECEBÍVEIS" sem qualificador (não dá pra saber se é CRI ou CRA sem inventar).

`cvm_oferta_distribuicao_raw`: staging quase 1:1 com o CSV oficial, mas com escopo de colunas
reduzido (removidas ~30 colunas de composição de investidores — quem comprou o ativo, não o
crédito em si). Chave de dedup: `row_hash` (hash de conteúdo da linha inteira) — nem
`numero_registro_oferta` (76% NULO, só ofertas com registro pleno têm) nem `Numero_Processo`
(um processo pode ter dezenas de séries) servem como chave natural.

`cvm_oferta_resolucao_160_raw`: mesmo padrão (latin-1, `;`, `row_hash`), colunas de composição
de investidores excluídas (~24 colunas `Num_Invest_*`/`Qtde_VM_*`). `Numero_Requerimento` é
único/não-nulo aqui (diferente do arquivo principal), mas mantido só informativo. Campos que
este arquivo NÃO tem: `Data_Emissao`/`Data_Vencimento`/`Juros`/`Atualização_Monetária`/`Serie`/
`Classe_Ativo`/`Especie_Ativo`/`Forma_Ativo` — por isso `prazo_dias`/`prazo_meses`/
`indexador_padronizado`/`taxa_valor`/`taxa_tipo`/etc. ficam sempre NULL pras linhas vindas
daqui. Confirmado (contra os dois dicionários de dados oficiais) que NENHUMA das duas fontes CVM
tem campo de carência — por isso `operations_primario` nunca teve uma coluna de carência.

`operations_primario` (tabela unificada, colunas principais): `id`, `instrumento` (cru),
`instrumento_padronizado` (`'Debênture'|'CRI'|'CRA'|'Nota Comercial'|'Letra Financeira'|'CDCA'|
'CCB'|'Outro'` via `INSTRUMENTO_PADRONIZADO_MAP` — Nota Promissória e Nota Comercial unificadas
sob `'Nota Comercial'`), `numero_processo`, `numero_registro_oferta`, `tipo_oferta`,
`rito_oferta`, `modalidade_oferta`, `cnpj_emissor`, `nome_emissor`,
`razao_social_oficial_emissor`, `setor_emissor`/`subsetor_emissor`/`segmento_emissor`/
`porte_emissor`/`natureza_juridica_emissor`/`uf_emissor`/`municipio_emissor` (via JOIN contra
`cnpj_cnae`, mesmo cache usado pra FINEP), `cnpj_lider`, `nome_lider`, `emissao`, `serie`,
`classe_ativo`, `especie_ativo`, `forma_ativo`, `data_emissao`, `data_vencimento`,
`data_registro_oferta`, `data_encerramento_oferta`, `data_referencia` (melhor data disponível,
ordem de preferência: emissão → registro oferta → início oferta → encerramento oferta →
protocolo → abertura processo — ou, pro 2º arquivo CVM: registro → encerramento → deliberação →
requerimento), `ano`, `trimestre`, `prazo_dias`/`prazo_meses` (exato, `data_vencimento -
data_emissao`, só quando as duas datas existem — ~15,2% de cobertura no CSV completo), `valor_
total`, `quantidade_total`, `preco_unitario`, `incentivada` (bool, Lei 12.431),
`regime_fiduciario` (bool), `oferta_inicial`, `indexador_padronizado`
(`'CDI'|'IPCA+'|'SELIC'|'Prefixado'|'Outro'|NULL`, melhor esforço via regex sobre
`Juros`/`Atualização_Monetária`), `taxa_valor`/`taxa_tipo`
(`'spread'|'percentual_indexador'|'taxa_fixa'|NULL`, melhor esforço), `juros`,
`atualizacao_monetaria` (texto cru, sempre mantido), `numero_requerimento`,
`status_requerimento`, `tipo_lastro` (`'Pulverizado'|'Concentrado'`), `agente_fiduciario`,
`custodiante`, `descricao_garantias` (últimas 6 colunas só vêm do 2º arquivo CVM), `raw_table`,
`raw_id`, `search_document`, `search_vector`.

Corte de escopo temporal 2010+ (2026-09-17): linhas com `data_referencia < '2010-01-01'` foram
removidas de produção (backup em `operations_primario_pre2010_backup`, 2.358 linhas,
1989-09-01 a 2009-12-29 — tabela preservada, não fazia parte desta remoção). Corte tornado
permanente no pipeline via `_filtrar_corte_temporal`/`DATA_CORTE_MINIMA = "2010-01-01"`.

Extração de taxa (`_extrair_taxa`, melhoria de 2026-09-17): fallback "spread implícito" quando
`juros` é só um número seco (ex: `"12% A.A."`) e `atualizacao_monetaria` já tem um índice real
(IGPM/TR/TJLP/etc.) — tratado como aditivo (índice + juros), convenção do mercado de renda fixa
brasileiro. Exclui deliberadamente `juros` contendo `" OU "` (duas taxas alternativas no mesmo
campo) de qualquer padrão de extração, pra nunca inventar qual se aplica. Cobertura medida
(12.239 linhas em escopo do CSV): ~4,2% → ~11,2% depois desse fallback.

Pipeline (`src/refresh_primario.py`): `download_cvm.download_all()` → `parse_cvm.parse_cvm()`
→ `parse_cvm_resolucao160.parse_cvm_resolucao160()` → `unify_primario.
build_operations_primario()` (incremental por `raw_table`+`raw_id`, cada staging table
separadamente, inserindo na mesma `operations_primario`) → `enrich_cnae.
enrich_pendentes_via_api()` (BrasilAPI, mesma função da FINEP) →
`unify_primario.reclassificar_emissores_pendentes()`. Log em `refresh_primario_log`. NÃO rodava
o job pesado mensal de `enrich_cnae.py::enrich()` (bulk RFB) — volume pequeno o suficiente pro
caminho leve via BrasilAPI.

#### 1.4.2 Motor de busca + rotas FastAPI

`src/search_fts_primario.py`: espelhava `src/search_fts.py`, mais simples (sem
`search_taxonomia_termos` — nenhum dicionário de sinônimos curado pro emissor CVM). 4 tiers:
(1) CNPJ do emissor (≥8 dígitos) ou prefixo de `nome_emissor`; (2) `instrumento_padronizado` OU
`setor_emissor`/`subsetor_emissor` (`LIKE`); (3) full-text (`search_vector @@
websearch_to_tsquery`, query própria fora de CASE, usa índice GIN
`idx_operations_primario_search_vector`); (4) trigram em `nome_emissor`/`segmento_emissor`.
Filtros estruturados (`AND`, nunca no ranking): `instrumento`, `uf`, `setor`, `valor_minimo`.

Rotas (`webapp/primario/routes.py`, prefixo `/api/primario/*`, protegidas pelo MESMO gate
global `_verificar_acesso` de `webapp/main.py` — sem dependency própria, já que o prefixo
começa com `/api/`):
- `GET /status` — espelha `/api/status`; `busca_ia_ativa` sempre `False`.
- `GET /filtros` — instrumentos, indexadores, setores, subsetores, ufs, portes, anos,
  data_min/data_max.
- `GET /kpis` — `n_operacoes`, `valor_contratado_total`, `n_emissores_distintos`,
  `cheque_medio`, `por_instrumento`.
- `GET /serie_temporal` — agrupado por `instrumento_padronizado` (em vez de `agencia`).
- `GET /instrumentos` — espelha `/api/setores`, agrupando por `instrumento_padronizado`.
- `GET /uf` — via `uf_emissor` (sem equivalente a `IE`, categoria específica do BNDES).
- `GET /porte` — via `porte_emissor` (vocabulário próprio da RFB, sem `PORTE_NORMALIZADO_SQL`).
- `GET /operacoes`, `/operacoes/{id}`, `/operacoes/{id}/grupo-economico`.
- `GET /busca` — motor acima.
- `GET /tendencias/{setores,subsetores,segmentos}` — mesmo formato de `_ranking_variacao`/
  `_periodo_anterior` do motor BNDES/FINEP, reimplementado sobre `data_referencia`.
- `GET /tendencias/indexadores` — agrupa por `indexador_padronizado`.
- `GET /subsetores`, `/segmentos` (nível superior).
- `GET /graficos/taxas`, `/graficos/prazos` — mediana real (`percentile_cont(0.5)`), exclui
  `taxa_tipo='percentual_indexador'` do agrupamento de taxas (unidade multiplicativa
  diferente).
- `GET /serie_temporal_incentivada` — agrupa por `incentivada` (`'Sim'/'Não'/'Não informado'`).
- `GET /estrutura_mercado` — bundla `incentivada`/`regime_fiduciario`/`tipo_lastro` + ranking
  top-10 de `agente_fiduciario`/`custodiante`.

#### 1.4.3 Frontend (mecânica de troca de mercado)

`_mercadoAtivo` (`"incentivado"`|`"primario"`) em `common.js` era a fonte da verdade. Gatilho:
clique em `#brand-toggle` → `alternarMercado()` (sempre pousava no Consolidado do mercado de
destino, criava entrada de histórico nova). URL: prefixo `/primario/...` pros 4 slugs visíveis
nesse mercado (consolidado/tendencias/busca/transacoes-salvas — Editais e Linhas Incentivadas
escondidas, sem equivalente conceitual). Identidade visual: classe `body.mercado-primario`
(verde-petróleo em vez de navy) + troca de `document.title`/`.brand-texto`. Filtro
compartilhado `#f-agencia` reaproveitado com significado diferente ("Agência" vs "Instrumento").
Cache de filtro por grupo de aba (`_ultimaQueryPorGrupo`) escopado também por mercado.

Tabela de labels próprios por card (Consolidado/Tendências) — decisões de produto tomadas na
sessão de redesenho de 2026-09-17 (motivo completo de cada decisão está no histórico do git,
commits de CLAUDE.md daquela data):

| Card | Incentivado | Primário |
|---|---|---|
| Série temporal | "Evolução temporal — BNDES x FINEP", por `agencia` | "por instrumento" |
| Consolidado, card 2 | "Ranking de setores" | "Estrutura da oferta" (2 donuts: Incentivada Lei 12.431 + Regime fiduciário) |
| Mapa | "Por UF" | "Por UF do emissor" (`uf_emissor`) |
| Consolidado, card 4 | "Por porte do cliente" | "Por tipo de lastro" (Pulverizado/Concentrado) |
| Tendências, "Destinação de recursos" | produto/instrumento BNDES/FINEP | "Distribuição por indexador" |
| "Setores em alta/queda" | `setor_bndes` | "Setores do emissor em alta/queda" (`setor_emissor`) |
| KPI 4 | "Volume desembolsado/pago" | "Emissores distintos" |
| Tabela "Operações do período" | Cliente/Agência | Emissor/Instrumento |
| Tendências, cards novos (só Primário) | — | "Evolução da participação Lei 12.431" (stacked bar por trimestre) + "Principais agentes fiduciários e custodiantes" (ranking com toggle) |

Dashboards de taxa/prazo (só modo Primário): "Taxas por indexador" (`taxa_tipo` 'spread'/
'taxa_fixa' apenas — unidade multiplicativa 'percentual_indexador' excluída do gráfico, só
contada em texto) e "Prazos por instrumento" (mediana, `prazo_mediano_meses`). Os dois com
aviso de amostra parcial sempre calculado a partir da resposta real da API.

Limitação conhecida (nunca resolvida): favoritar não funcionava no modo Primário
(`usuario_operacoes_salvas.operation_id` é FK pra `operations(id)`, schema do crédito de
fomento — favoritar uma operação de `operations_primario` exigiria estender esse schema). O
botão ficava escondido quando `_mercadoAtivo === "primario"`. Ponto discutível caso Mercado
Primário volte SEM Transações Salvas voltar junto — nesse caso não há mais botão de favoritar
pra esconder de qualquer forma.

### 1.5 Como restaurar

1. Recriar `webapp/primario/__init__.py` + `routes.py`, os 6 módulos em `src/`
   (`download_cvm.py`, `parse_cvm.py`, `parse_cvm_resolucao160.py`, `unify_primario.py`,
   `refresh_primario.py`, `search_fts_primario.py`) e `.github/workflows/refresh-primario.yml`
   — a partir do histórico do git (`git log --all --diff-filter=D -- webapp/primario/`) ou
   reescrever do zero usando a seção 1.4 acima como especificação.
2. Recriar o schema das 4 tabelas em `src/db.py` (`SCHEMA` + `MIGRACOES_COLUNAS`) — usar a
   lista de colunas da seção 1.4.1 pra `operations_primario`; pras staging tables, os campos
   são quase 1:1 com as colunas do CSV oficial da CVM (ver dicionário de dados da CVM,
   `meta_oferta_distribuicao.txt`/`meta_oferta_resolucao_160.txt`, baixados por
   `download_cvm.py`).
3. Restaurar os dados: OU re-rodar o pipeline do zero contra a CVM (`python
   src/refresh_primario.py`, idempotente, vai reconstruir tudo), OU restaurar das tabelas de
   backup em produção (`INSERT INTO operations_primario SELECT * FROM
   operations_primario_removido_backup` etc. — cuidado com a sequence de `id`
   `GENERATED ALWAYS AS IDENTITY`, rodar `setval(pg_get_serial_sequence(...), MAX(id))` depois,
   mesmo padrão já documentado em incidentes anteriores deste projeto).
4. Re-adicionar em `webapp/main.py`: import do router + `app.include_router(primario_router,
   prefix="/api/primario")`; `_SPA_PAGINAS_PRIMARIO` + rota `spa_pagina_primario`; `"primario"`
   de volta em `_SPA_PAGINAS`.
5. Re-adicionar os 5 rewrites em `vercel.json` (ver lista na seção 1.3).
6. Reconstruir a mecânica de troca de mercado em `common.js` (seção 1.4.3) e os cards/JS de
   `consolidado.js`/`tendencias.js`/`busca.js` (seção 1.1) — ou reverter os commits desta sessão
   nesses arquivos especificamente, se a distância no histórico do git permitir um revert limpo.
7. Reconstruir os tokens `--accent-*`/`.mercado-primario`/`[data-mercado-only]` em `style.css`.

---

## 2. Exportações (CSV/Excel)

Quatro pontos de export removidos nesta sessão:

1. **Tendências (CSV, client-side)**: `exportarMaioresOperacoesCSV()` em `tendencias.js` +
   botão `#maiores-exportar-btn` — exportava `_ultimasMaioresOperacoes` (tabela "Operações do
   período") pras colunas Cliente/CNPJ/Agência/Setor/Subsetor/UF/Data/Valor
   contratado/desembolsado.
2. **Editais (CSV, client-side)**: `exportarEditaisCSV()` em `editais.js` + botão
   `#editais-exportar-btn` — exportava `editaisAtuais` pras colunas Título/Situação/Tema/Tipo
   de oportunidade/Tipo de cooperação/Contrapartida/Região/Publicado em/Prazo de
   submissão/Vigência até.
3. **Busca (Excel, server-side)**: botão `#busca-exportar-btn` (listener em `busca.js`) → POST
   `/api/busca/exportar` (`webapp/main.py`) → `gerar_xlsx_busca()`
   (`webapp/exportar_excel.py`). Reenviava as mesmas linhas já renderizadas na tela
   (`ultimosResultados`), nunca re-rodava a busca no backend.
4. **Transações Salvas (Excel, server-side)**: botão `#salvos-exportar-btn` → POST
   `/api/salvos/exportar` → `gerar_xlsx_operacoes_salvas()`. Removido junto da remoção de
   Transações Salvas (seção 3 abaixo).

### 2.1 `exportarCSV()` (função compartilhada, `common.js`)

Removida por não ter mais nenhum call site depois dos itens 1 e 2 acima (confirmado por grep).
Implementação original (client-side, sem ida ao servidor, BOM UTF-8 pro Excel abrir acentos
certo):

```js
function exportarCSV(nomeArquivo, linhas, colunas) {
  const escapar = (valor) => {
    if (valor === null || valor === undefined) return "";
    const texto = String(valor);
    return /[",\n;]/.test(texto) ? '"' + texto.replace(/"/g, '""') + '"' : texto;
  };
  const cabecalho = colunas.map((c) => escapar(c.rotulo)).join(";");
  const corpo = linhas
    .map((linha) => colunas.map((c) => escapar(linha[c.chave])).join(";"))
    .join("\n");
  const blob = new Blob(["﻿" + cabecalho + "\n" + corpo], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nomeArquivo;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

### 2.2 `webapp/exportar_excel.py` (arquivo removido inteiro, 91 linhas)

Gerava o `.xlsx` formatado (estilo do projeto: header navy `#223850`, borda `#EBECED`, moeda em
R$, larguras de coluna auto-ajustadas) a partir de LINHAS JÁ PRONTAS recebidas do frontend
(nunca re-rodava a busca no backend). Conteúdo completo:

```python
"""Gera o .xlsx formatado exportado pela aba Busca (ver webapp/main.py::busca_exportar).

As linhas exportadas vem PRONTAS do front-end (ultimosResultados, ja renderizado na tela) --
o backend nunca re-roda a busca aqui, so monta a planilha em cima do que foi passado. Isso
garante que o arquivo bate exatamente com o que a pessoa viu, mesmo que o banco mude entre o
clique em "Buscar" e o clique em "Exportar".
"""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# Mesmas colunas/rotulos do CSV que este export substitui (ver busca.js, funcao renderResultados).
COLUNAS = [
    ("cliente", "Cliente"),
    ("cnpj", "CNPJ"),
    ("agencia", "Agência"),
    ("setor_bndes", "Setor"),
    ("subsetor_bndes", "Subsetor"),
    ("segmento", "Segmento"),
    ("uf", "UF"),
    ("data_contratacao", "Data"),
    ("valor_contratado", "Valor contratado"),
    ("valor_desembolsado", "Valor desembolsado"),
    ("descricao_projeto", "Descrição do projeto"),
    ("score", "Similaridade"),
    ("motivo", "Motivo da correspondência"),
]

_COLUNAS_MOEDA = {"valor_contratado", "valor_desembolsado"}
_LARGURA_MAXIMA = 60

_NAVY = "223850"
_BORDA = "EBECED"

COLUNAS_SALVAS = [c for c in COLUNAS if c[0] not in ("score", "motivo")] + [
    ("nota", "Nota pessoal"),
    ("salvo_em", "Salvo em"),
]


def _gerar_xlsx(titulo_aba: str, colunas: list, linhas: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = titulo_aba

    fonte_header = Font(color="FFFFFF", bold=True)
    preenchimento_header = PatternFill(start_color=_NAVY, end_color=_NAVY, fill_type="solid")
    borda_fina = Border(*(Side(style="thin", color=_BORDA) for _ in range(4)))

    ws.append([rotulo for _, rotulo in colunas])
    for cel in ws[1]:
        cel.font = fonte_header
        cel.fill = preenchimento_header
        cel.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"

    larguras = [len(rotulo) for _, rotulo in colunas]
    for linha in linhas:
        valores = [linha.get(chave) for chave, _ in colunas]
        ws.append(valores)
        r = ws.max_row
        for i, (chave, _) in enumerate(colunas, start=1):
            cel = ws.cell(row=r, column=i)
            cel.border = borda_fina
            if chave in _COLUNAS_MOEDA and cel.value is not None:
                cel.number_format = "R$ #,##0.00"
            texto = str(cel.value) if cel.value is not None else ""
            larguras[i - 1] = min(_LARGURA_MAXIMA, max(larguras[i - 1], len(texto)))

    for i, largura in enumerate(larguras, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = largura + 2

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def gerar_xlsx_busca(query: str, linhas: list) -> bytes:
    return _gerar_xlsx("Busca", COLUNAS, linhas)


def gerar_xlsx_operacoes_salvas(linhas: list) -> bytes:
    return _gerar_xlsx("Transações Salvas", COLUNAS_SALVAS, linhas)
```

### 2.3 Rotas removidas de `webapp/main.py`

```python
@app.post("/api/salvos/exportar")
def salvos_exportar(usuario: dict = Depends(_exigir_usuario_logado)):
    from webapp.exportar_excel import gerar_xlsx_operacoes_salvas
    conn = get_connection(pooled=True)
    try:
        linhas = salvos.listar_operacoes_salvas(conn, usuario["id"])
    finally:
        conn.close()
    conteudo = gerar_xlsx_operacoes_salvas(linhas)
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="transacoes-salvas.xlsx"'},
    )


@app.post("/api/busca/exportar")
def busca_exportar(body: dict):
    from webapp.exportar_excel import gerar_xlsx_busca
    query = (body or {}).get("query") or "resultado"
    linhas = (body or {}).get("resultados") or []
    conteudo = gerar_xlsx_busca(query, linhas)
    slug = "".join(c if c.isalnum() else "-" for c in query).strip("-").lower() or "resultado"
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="busca-{slug}.xlsx"'},
    )
```

### 2.4 Dependência `openpyxl`

**Mantida** em `requirements.txt` (raiz) — `src/parse_bndes.py` e `src/parse_finep.py` (lidos
pelo pipeline semanal, `src/refresh.py`) usam `openpyxl` pra ler as planilhas oficiais do
BNDES/FINEP, sem relação nenhuma com exportação. **Removida** de `api/requirements.txt`
(runtime hospedado/Vercel) — só era necessária ali por causa do import lazy dentro de
`busca_exportar()`, que não existe mais.

### 2.5 Como restaurar

1. Recriar `webapp/exportar_excel.py` com o conteúdo da seção 2.2.
2. Re-adicionar as 2 rotas da seção 2.3 em `webapp/main.py` (a de `/api/salvos/exportar`
   depende de Transações Salvas — seção 3 — estar restaurada também).
3. Re-adicionar `openpyxl` em `api/requirements.txt`.
4. Re-adicionar `exportarCSV()` (seção 2.1) em `common.js`.
5. Re-adicionar `exportarMaioresOperacoesCSV()` + botão em `tendencias.js`/`index.html`.
6. Re-adicionar `exportarEditaisCSV()` + botão em `editais.js`/`index.html`.
7. Re-adicionar o botão + listener de `/api/busca/exportar` em `busca.js`/`index.html`.

---

## 3. Transações Salvas (favoritos de operação + histórico de busca por usuário)

Aba própria da SPA (`webapp/static/js/salvos.js`, rotas `/api/salvos*`, backend em
`webapp/salvos.py`), adicionada em 2026-09-15. Duas coisas, escopadas por CONTA LOGADA:
favoritar uma operação (com nota pessoal) e histórico de busca gravado no servidor (fixável).

### 3.1 `webapp/salvos.py` (arquivo removido inteiro, 179 linhas)

```python
"""Transacoes Salvas: favoritos de operacao + historico de busca POR USUARIO (ver
CLAUDE.md, aba "Transacoes Salvas" -- schema em src/db.py, tabelas
usuario_operacoes_salvas/usuario_busca_historico). Toda funcao aqui recebe uma
conexao ja aberta (mesmo padrao do resto do projeto) e um usuario_id ja validado
por uma sessao de verdade (webapp/main.py::_exigir_usuario_logado) -- nada aqui
verifica autenticacao sozinho.
"""
from datetime import datetime, timezone


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============ Operacoes salvas (favoritos) ============

def favoritar_operacao(conn, usuario_id: int, operation_id: int, nota: str = None) -> None:
    """Marca uma operacao como salva (ou atualiza a nota, se ja estava salva --
    UNIQUE(usuario_id, operation_id) faz o upsert). nota=None em uma operacao ja
    salva PRESERVA a nota existente."""
    conn.execute(
        "INSERT INTO usuario_operacoes_salvas (usuario_id, operation_id, nota, criado_em) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (usuario_id, operation_id) DO UPDATE SET "
        "nota = COALESCE(EXCLUDED.nota, usuario_operacoes_salvas.nota)",
        (usuario_id, operation_id, nota, _agora()),
    )
    conn.commit()


def desfavoritar_operacao(conn, usuario_id: int, operation_id: int) -> None:
    conn.execute(
        "DELETE FROM usuario_operacoes_salvas WHERE usuario_id = ? AND operation_id = ?",
        (usuario_id, operation_id),
    )
    conn.commit()


def atualizar_nota_operacao_salva(conn, usuario_id: int, operation_id: int, nota: str) -> bool:
    cur = conn.execute(
        "UPDATE usuario_operacoes_salvas SET nota = ? WHERE usuario_id = ? AND operation_id = ?",
        (nota, usuario_id, operation_id),
    )
    conn.commit()
    return cur.rowcount > 0


def operacao_esta_salva(conn, usuario_id: int, operation_id: int):
    row = conn.execute(
        "SELECT nota FROM usuario_operacoes_salvas WHERE usuario_id = ? AND operation_id = ?",
        (usuario_id, operation_id),
    ).fetchone()
    if row is None:
        return {"salva": False}
    return {"salva": True, "nota": row[0]}


def listar_ids_salvos(conn, usuario_id: int) -> list:
    rows = conn.execute(
        "SELECT operation_id FROM usuario_operacoes_salvas WHERE usuario_id = ?",
        (usuario_id,),
    ).fetchall()
    return [r[0] for r in rows]


def listar_operacoes_salvas(conn, usuario_id: int):
    rows = conn.execute(
        "SELECT s.operation_id, s.nota, s.criado_em, "
        "  o.cliente, o.cnpj, o.agencia, o.uf, o.data_contratacao, "
        "  o.valor_contratado, o.valor_desembolsado, o.setor_bndes, o.subsetor_bndes, "
        "  o.segmento, o.descricao_projeto "
        "FROM usuario_operacoes_salvas s "
        "JOIN operations o ON o.id = s.operation_id "
        "WHERE s.usuario_id = ? ORDER BY s.criado_em DESC",
        (usuario_id,),
    ).fetchall()
    cols = [
        "operation_id", "nota", "salvo_em", "cliente", "cnpj", "agencia", "uf",
        "data_contratacao", "valor_contratado", "valor_desembolsado", "setor_bndes",
        "subsetor_bndes", "segmento", "descricao_projeto",
    ]
    return [dict(zip(cols, r)) for r in rows]


def resumo_operacoes_salvas(conn, usuario_id: int) -> dict:
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(o.valor_contratado), 0) "
        "FROM usuario_operacoes_salvas s JOIN operations o ON o.id = s.operation_id "
        "WHERE s.usuario_id = ?",
        (usuario_id,),
    ).fetchone()
    total, valor_total = row
    return {"total_operacoes": total, "valor_total": float(valor_total) if valor_total else 0.0}


# ============ Historico de busca (servidor) ============

def registrar_busca_historico(conn, usuario_id: int, query: str) -> None:
    query = (query or "").strip()
    if not query:
        return
    existente = conn.execute(
        "SELECT id FROM usuario_busca_historico WHERE usuario_id = ? AND lower(query) = lower(?)",
        (usuario_id, query),
    ).fetchone()
    if existente:
        conn.execute(
            "UPDATE usuario_busca_historico SET criado_em = ? WHERE id = ?",
            (_agora(), existente[0]),
        )
    else:
        conn.execute(
            "INSERT INTO usuario_busca_historico (usuario_id, query, criado_em) VALUES (?, ?, ?)",
            (usuario_id, query, _agora()),
        )
    conn.commit()


def listar_busca_historico(conn, usuario_id: int, limite: int = 30):
    rows = conn.execute(
        "SELECT id, query, fixada, criado_em FROM usuario_busca_historico "
        "WHERE usuario_id = ? ORDER BY fixada DESC, criado_em DESC LIMIT ?",
        (usuario_id, limite),
    ).fetchall()
    cols = ["id", "query", "fixada", "criado_em"]
    return [dict(zip(cols, r)) for r in rows]


def fixar_busca_historico(conn, usuario_id: int, historico_id: int, fixada: bool) -> bool:
    cur = conn.execute(
        "UPDATE usuario_busca_historico SET fixada = ? WHERE id = ? AND usuario_id = ?",
        (fixada, historico_id, usuario_id),
    )
    conn.commit()
    return cur.rowcount > 0


def remover_busca_historico(conn, usuario_id: int, historico_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM usuario_busca_historico WHERE id = ? AND usuario_id = ?",
        (historico_id, usuario_id),
    )
    conn.commit()
    return cur.rowcount > 0


def limpar_busca_historico(conn, usuario_id: int) -> None:
    conn.execute(
        "DELETE FROM usuario_busca_historico WHERE usuario_id = ? AND fixada = FALSE",
        (usuario_id,),
    )
    conn.commit()
```

### 3.2 Schema (`src/db.py`) das 2 tabelas removidas

```sql
CREATE TABLE IF NOT EXISTS usuario_operacoes_salvas (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    operation_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    nota TEXT,
    criado_em TEXT NOT NULL,
    UNIQUE (usuario_id, operation_id)
);
CREATE INDEX IF NOT EXISTS idx_usuario_operacoes_salvas_usuario ON usuario_operacoes_salvas(usuario_id, criado_em DESC);

CREATE TABLE IF NOT EXISTS usuario_busca_historico (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    fixada BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usuario_busca_historico_usuario ON usuario_busca_historico(usuario_id, criado_em DESC);
```

`usuario_id` é um INTEGER solto (sem FK pra `admin_usuarios`, que só existe depois de
`webapp/admin/seed.py` rodar) — mesma segregação documentada pro painel de admin. A validade de
`usuario_id` era garantida pelo backend (`Depends(_exigir_usuario_logado)` em cada rota).

### 3.3 Tabelas removidas (Postgres/Aiven, produção) — com backup

| Tabela original | Linhas (2026-09-21) | Nome do backup |
|---|---|---|
| `usuario_operacoes_salvas` | 5 | `usuario_operacoes_salvas_removido_backup` |
| `usuario_busca_historico` | 15 | `usuario_busca_historico_removido_backup` |

### 3.4 Rotas removidas de `webapp/main.py`

Todas exigiam `Depends(_exigir_usuario_logado)` (função também removida — só existia pra estas
rotas), exceto `salvos_ids` que usava `Depends(_usuario_atual)` (opcional, devolvia lista vazia
pra visitante anônimo):

- `GET /api/salvos` — página inteira (operações + resumo + histórico) numa chamada só.
- `GET /api/salvos/operacoes/ids` — ids em lote (usado pela estrelinha mini da Busca).
- `POST /api/salvos/operacoes/{op_id}` — favoritar (com nota opcional).
- `DELETE /api/salvos/operacoes/{op_id}` — desfavoritar.
- `PATCH /api/salvos/operacoes/{op_id}` — atualizar só a nota.
- `POST /api/salvos/historico/{historico_id}/fixar`
- `DELETE /api/salvos/historico/{historico_id}`
- `DELETE /api/salvos/historico` — limpa só não-fixadas.
- `POST /api/salvos/exportar` — ver seção 2.3.

`operacao_detalhe` (`GET /api/operacoes/{op_id}`) perdeu o cálculo de `salva`/`nota` (chamava
`salvos.operacao_esta_salva`) — a resposta não tem mais essas 2 chaves.

### 3.5 Frontend removido/tocado

- `webapp/static/js/salvos.js` — arquivo inteiro removido (198 linhas: render de resumo/lista
  de operações salvas com textarea de nota/histórico de busca com fixar/remover, listeners de
  exportar Excel e limpar histórico).
- `index.html` — seção `<section id="view-salvos">` inteira (aba "Transações Salvas") + botão
  de aba `data-view="salvos"` + `<script src="/js/salvos.js">`; `#modal-favoritar-btn` (botão
  "☆ Salvar" do modal de detalhe — **`#modal-copiar-link-btn` foi mantido**, é feature
  diferente: deep link, não favoritos).
- `common.js`: `_configurarBotaoFavoritar()`, `alternarFavoritoOtimista()`,
  `_animarPopFavorito()`, `deleteJSON()`/`patchJSON()` (helpers HTTP só usados por
  Transações Salvas). `openOperacaoDetalhe` perdeu a chamada a `_configurarBotaoFavoritar`.
- `busca.js`: `.fav-btn-mini` (estrelinha em cada card de resultado),
  `_carregarIdsSalvos()`/`idsSalvosAtual`.
- `linhas.js`/`editais.js`: a linha que escondia `#modal-favoritar-btn` ao abrir detalhe de
  linha/edital (órfã depois que o botão deixou de existir).
- `style.css`: `.fav-btn-mini` (+ hover/ativo/disabled), `@keyframes fav-pop`/`.fav-pop`,
  `.salvos-nota`(+ focus), `#salvos-sem-login.hidden, #salvos-conteudo.hidden`. **`.fav-btn`
  (+ `:hover`) foi MANTIDO** — usado pelo botão de copiar link, que continua existindo.
  `.fav-btn.ativo` (só usado pelo botão de favoritar) foi removido.

### 3.6 Dependência inesperada encontrada: Painel de Admin

O drill-down por usuário do painel de admin (`GET /admin/api/usuarios/{id}/acessos`, em
`webapp/admin/routes.py`) chamava `salvos.listar_busca_historico(conn, usuario_id, limite=50)`
e devolvia essa lista na chave `"buscas"` da resposta — feature "V2 do log de acessos"
(2026-09-16), reaproveitando a MESMA tabela `usuario_busca_historico` de Transações Salvas.
Isso NÃO estava listado no escopo original da tarefa (que assumia as tabelas "já isoladas por
design"). Corrigido nesta sessão: removido `from webapp import salvos` de
`webapp/admin/routes.py`, removida a linha `buscas = salvos.listar_busca_historico(...)` e a
chave `"buscas"` da resposta; removida a seção "Histórico de busca" do modal de drill-down em
`webapp/static/admin.html` (tabela `#admin-usuario-modal-buscas-tbody`) e o código
correspondente em `webapp/static/js/admin.js` (variável `usuarioModalBuscasTbody` + bloco de
render). O drill-down continua funcionando normalmente para login/logout/navegação por aba —
só o histórico de busca saiu dele.

**Se Transações Salvas for restaurada e a V2 do log de acessos quiser voltar a incluir
histórico de busca no drill-down**: reverter os 3 pontos acima (import, linha `buscas=`/chave
na resposta, seção HTML + JS do modal).

### 3.7 Como restaurar

1. Recriar `webapp/salvos.py` com o conteúdo da seção 3.1.
2. Recriar o schema da seção 3.2 em `src/db.py`.
3. Restaurar os dados das tabelas de backup (seção 3.3) ou aceitar começar zerado (favoritos e
   histórico são dados de uso, não pipeline — não há fonte externa pra "re-baixar").
4. Re-adicionar as rotas da seção 3.4 em `webapp/main.py` (`_exigir_usuario_logado`,
   `_registrar_busca_se_logado` — ligada às rotas de busca sem/com IA — e o cálculo de
   `salva`/`nota` em `operacao_detalhe`).
5. Recriar `webapp/static/js/salvos.js` e a seção `view-salvos` em `index.html` + botão de aba
   + `#modal-favoritar-btn` + script tag.
6. Re-adicionar `_configurarBotaoFavoritar`/`alternarFavoritoOtimista`/`_animarPopFavorito`/
   `deleteJSON`/`patchJSON` em `common.js`.
7. Re-adicionar `.fav-btn-mini`/`.fav-pop`/`.salvos-nota`/etc. em `style.css`.

---

## 4. Cadastro com aprovação (substituído por identificação passwordless) + "Saúde do banco"

Duas coisas removidas juntas em 2026-09-22, na mesma sessão que reposicionou o site de
"ferramenta com cadastro+senha" pra "plataforma pública de geração de leads" — ver
`docs/painel-admin.md`, seção "Identificação passwordless do site principal", pro fluxo NOVO
que substituiu o primeiro item abaixo. O painel `/admin` em si (login por usuário+senha, hash
PBKDF2, `admin_sessoes`, `exigir_admin`) **não foi tocado** — só o login do site principal e a
seção "Saúde do banco" do painel.

### 4.1 Login por usuário+senha do site principal + cadastro público com aprovação

Login do site principal era `POST /api/login` (usuário+senha, mesma tabela `admin_usuarios`
do painel, `autenticar_credenciais`/`mensagem_status_bloqueado` de `webapp/admin/auth.py`,
ainda existentes e usadas pelo login do painel). Cadastro público (`POST /api/registrar`) BEM
mais simples que qualquer coisa passwordless: usuário escolhia username+senha (≥8 caracteres)
+ e-mail, conta nascia `role='usuario'` + `status='pendente'`, e só conseguia logar depois que
um admin aprovasse pelo painel (`GET /admin/api/usuarios/pendentes` +
`POST .../{id}/aprovar`/`.../rejeitar`).

**Rotas removidas de `webapp/main.py`**:
```python
@app.post("/api/login")
def site_login(payload: dict, request: Request, response: Response):
    username = (payload.get("username") or "").strip()
    senha = payload.get("password") or ""
    conn = get_connection(pooled=True)
    try:
        usuario = autenticar_credenciais(conn, username, senha)
        if usuario is None:
            raise HTTPException(status_code=401, detail="Usuario ou senha incorretos")
        mensagem_bloqueio = mensagem_status_bloqueado(usuario["status"])
        if mensagem_bloqueio:
            raise HTTPException(status_code=401, detail=mensagem_bloqueio)
        token = criar_sessao(conn, usuario["id"])
        registrar_acesso(conn, usuario["id"], usuario["username"], "site", "login", _ip_do_request(request))
    finally:
        conn.close()
    definir_cookie_sessao(response, token)
    return {"ok": True, "username": usuario["username"]}


@app.post("/api/registrar")
def site_registrar(payload: dict):
    username = (payload.get("username") or "").strip()
    senha = payload.get("password") or ""
    email = (payload.get("email") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Usuario e obrigatorio")
    if len(senha) < 8:
        raise HTTPException(status_code=400, detail="Senha precisa ter pelo menos 8 caracteres")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Informe um e-mail valido")
    password_hash = gerar_hash_senha(senha)
    conn = get_connection(pooled=True)
    try:
        ja_existe = conn.execute("SELECT 1 FROM admin_usuarios WHERE username = ?", (username,)).fetchone()
        if ja_existe:
            raise HTTPException(status_code=409, detail="Ja existe uma conta com esse nome de usuario")
        conn.execute(
            "INSERT INTO admin_usuarios (username, password_hash, email, role, status, ativo, criado_em) "
            "VALUES (?, ?, ?, 'usuario', 'pendente', TRUE, ?)",
            (username, password_hash, email, datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}
```
`GET /api/me` devolvia só `{"username": ...}` (agora devolve `{"username", "nome"}`).

**Rotas removidas de `webapp/admin/routes.py`** (aprovação, painel):
```python
@router.get("/api/usuarios/pendentes")
def listar_pendentes(usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        rows = conn.execute(
            "SELECT id, username, email, criado_em FROM admin_usuarios WHERE status = 'pendente' ORDER BY criado_em"
        ).fetchall()
    finally:
        conn.close()
    return {"pendentes": [{"id": r[0], "username": r[1], "email": r[2], "criado_em": r[3]} for r in rows]}


@router.post("/api/usuarios/{usuario_id}/aprovar")
def aprovar_usuario(usuario_id: int, usuario: dict = Depends(exigir_admin)):
    ...  # UPDATE admin_usuarios SET status = 'aprovado' WHERE id = ?


@router.post("/api/usuarios/{usuario_id}/rejeitar")
def rejeitar_usuario(usuario_id: int, usuario: dict = Depends(exigir_admin)):
    ...  # UPDATE admin_usuarios SET status = 'rejeitado' WHERE id = ?
```
`GET /admin/api/usuarios` (CRUD normal) tinha `AND status != 'pendente'` no `WHERE` — hoje
filtra `password_hash != ''` (ver `docs/painel-admin.md`).

**Frontend removido** (`webapp/static/index.html`/`common.js`/`style.css`): `#login-overlay`
tinha DOIS formulários — `#login-card` (usuário/senha/"Criar conta") e `#registrar-card`
(usuário/e-mail/senha/"Solicitar conta", com mensagem "Sua conta precisa ser aprovada por um
administrador antes de acessar."). `common.js` tinha `_tentarLogin()`, `_mostrarLoginOverlay()`,
`_mostrarRegistrarOverlay()`, `_voltarParaLogin()` + os 2 listeners de submit
(`#login-card`/`#registrar-card`) + o listener de `#login-ir-criar-conta`/`#registrar-ir-login`.
Topbar tinha `#topbar-usuario` (nome do usuário + botão `#topbar-logout-btn` "Sair"), CSS
`.topbar-usuario`/`.topbar-logout-btn`. Estilo dos cards em `style.css`: `#login-card,
#registrar-card` (caixa), `.login-logo`/`.login-titulo`/`.login-subtitulo` (ainda usadas —
compartilhadas com o login do painel `/admin`, NÃO removidas), `#login-btn`/`#registrar-btn`.
Painel admin (`admin.html`) tinha uma seção "Contas pendentes de aprovação" (tabela
`#admin-pendentes-tbody`, botões Aprovar/Rejeitar) + `admin.js`:
`renderPendentes`/`carregarPendentes`/listener de `pendentesTbody`.

**Schema**: coluna `admin_usuarios.status` (`'pendente'|'aprovado'|'rejeitado'`, default
`'aprovado'`) NÃO foi removida (ainda existe, inofensiva) — só parou de ser escrita/lida por
qualquer rota nova; toda conta passwordless nasce direto com `status='aprovado'`.

**Se for restaurar**: 1) reverter `webapp/main.py` pras 2 rotas acima (e tirar
`/api/identificar`/`/api/cadastrar`/`/api/interesse` de `_ROTAS_PUBLICAS_API`, recolocando
`/api/login`/`/api/registrar`); 2) reverter `webapp/admin/routes.py`
(`listar_pendentes`/`aprovar_usuario`/`rejeitar_usuario`, filtro `status != 'pendente'` em
`listar_usuarios`); 3) reverter o HTML/CSS/JS do site (`#login-overlay` com os 2 cards,
`#topbar-usuario`) e do painel (`admin-pendentes-tbody` + JS); 4) decidir o que fazer com as
contas já criadas via `/api/cadastrar` (`password_hash=''`) — elas não têm senha, não
conseguiriam logar no fluxo antigo sem um reset administrativo de senha (`POST
/admin/api/usuarios/{id}/senha`, ainda existe).

### 4.2 "Saúde do banco" (seção do painel)

Proxy via SQL (`pg_database_size`, `pg_stat_activity`, `pg_stat_user_tables`) — nunca o % de
disco oficial da Aiven (só existe no console.aiven.io). Removida do painel principal (pedido
explícito do usuário: fora do fluxo de usuários/leads) — nenhum dado apagado, só a tela.

**Rota removida de `webapp/admin/routes.py`**:
```python
@router.get("/api/saude-banco")
def saude_banco(usuario: dict = Depends(exigir_admin)):
    conn = get_connection(pooled=True)
    try:
        tamanho_logico_bytes = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        conexoes_abertas = conn.execute("SELECT COUNT(*) FROM pg_stat_activity").fetchone()[0]
        tabelas = conn.execute(
            "SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum "
            "FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10"
        ).fetchall()
    finally:
        conn.close()
    campos = ["tabela", "linhas_vivas", "linhas_mortas", "ultimo_vacuum", "ultimo_autovacuum"]
    return {
        "tamanho_logico_mb": round(tamanho_logico_bytes / (1024 * 1024), 1),
        "conexoes_abertas": conexoes_abertas,
        "tabelas_por_bloat": [dict(zip(campos, (t[0], t[1], t[2], str(t[3]) if t[3] else None, str(t[4]) if t[4] else None))) for t in tabelas],
    }
```
**Frontend removido** (`admin.html`): seção "Saúde do banco" (aviso `.admin-aviso`, cards
`#admin-saude-cards`, tabela `#admin-saude-tbody`); (`admin.js`): `carregarSaudeBanco()`,
`fmtNumOuTraco()`, chamada em `iniciarPainel()`.

**Se for restaurar**: recriar a rota acima em `webapp/admin/routes.py`, a seção HTML (ver
histórico do git pra `admin.html` antes de 2026-09-22) e as duas funções JS + a chamada em
`iniciarPainel()`. Considerar torná-la uma página técnica separada em vez de reintegrar ao
fluxo principal (foi essa a sugestão do próprio pedido de remoção).
8. Se quiser a V2 do log de acessos de volta com histórico de busca: reverter a seção 3.6.
