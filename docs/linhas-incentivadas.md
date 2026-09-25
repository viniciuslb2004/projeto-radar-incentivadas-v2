> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

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

## Reposicionamento público/lead-gen (2026-09-22)

**Filtros normalizados**: `porte_grupo` (coluna computada nova, bucketing por regex/keyword
sobre `porte_padronizado` — 42 valores livres → ~5 categorias: Micro/Pequena, Média, Grande,
Todos os portes, Não informado) e `destinacao_grupo` (97 valores livres → 8 categorias +
Outros). `porte_padronizado` original é preservado, nunca apagado. Filtro **Status removido da
UI** — hoje só existe 1 valor real (`'aberta'`, 112/112 linhas), não discrimina nada; a coluna
`status` continua no schema (não usada), e as 112 linhas NÃO foram re-verificadas contra as
fontes externas (ficou como limitação conhecida, não decidida unilateralmente — ver
`Backlog.md`/`Decisões.md` do vault Obsidian se precisar retomar essa decisão). Setor continua
1 valor único por linha (nunca ganhou subsetor — decisão de produto documentada, dado não
suporta sem inventar).

**Detalhe de uma linha reorganizado** (`linhas.js::openLinhaDetalhe`): resumo executivo no
topo (Taxa/Prazo/Carência/Participação no projeto/Enquadramento/O que pode ser financiado),
resto reagrupado depois (descrição/instituição/setores/condições/garantias/observações/fonte).
Nenhum campo foi escondido, só reordenado.

**"Potenciais Linhas"** (aba nova, `webapp/potenciais.py` isolado + `potenciais.js`): usuário
informa Setor/Porte/Volume/Uso dos recursos, recebe linhas ranqueadas por **scoring
determinístico** (regras/pesos por critério informado, sem chamada de IA em tempo real —
prioriza precisão com baixo custo operacional, conforme pedido). Linguagem sempre "potencial
aderência", nunca "elegível". Inclui **"Transações Semelhantes"**: reaproveita `/api/operacoes`
(parâmetros opcionais novos, retrocompatíveis) pra mostrar operações reais comparáveis, deixando
claro que são referência histórica, não garantia.

**Potenciais Linhas v2 (2026-09-25)** — motor reescrito após avaliação com 16 perfis-gabarito
(`scripts/avaliar_potenciais.py`, precisão@3 0,43→0,92, precisão@5 0,57→0,86). Formulário:
Atividade (14 opções mais granulares que as 4 categorias; cada uma mapeia pra um setor BNDES),
Finalidade (investimento/máquinas/giro/inovação/sustentabilidade), Tomador (empresa/produtor
rural/cooperativa/ente público), Porte, UF, Valor (R$ mi). Parâmetros antigos `setor`/`uso`
continuam aceitos. **Regras duras EXCLUEM** (região que não cobre a UF, porte fora do que
`porte_elegivel` lista, valor fora de min/max, finalidade incompatível, nicho setorial de outra
atividade, público restrito: Pronaf/agricultura familiar, só cooperativas, estudante PF, entes
públicos/sem fins lucrativos) — um resultado exibido nunca tem contradição. Critério sem dado na
fonte = chip "–" com fator fixo 0,4 (nunca conta como match). Score = Σ peso×fator / Σ pesos
(atividade 35, finalidade 25, porte 15, valor 15, UF 10); ≥80 Alta, 60–79 Média, <60 vai pra
"Outras opções". Tudo parse determinístico do texto da fonte, sem IA. Resumos curtos dos cards
("Prazo até 15 anos (varia)") só extraem números literais do texto (helpers `lnResumo*` em
`linhas.js`); o modal de detalhe da linha só corta em fronteira de palavra + "ver mais".
Limitação conhecida: linhas com poucos campos preenchidos na fonte (ex.: Finame BK, porte/setor
"Não informado") ficam em Média mesmo sendo o produto clássico pro caso — reflexo honesto do dado.
