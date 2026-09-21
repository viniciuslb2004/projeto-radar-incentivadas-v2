> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

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
