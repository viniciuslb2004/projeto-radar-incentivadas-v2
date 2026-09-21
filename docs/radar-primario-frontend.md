> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

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
