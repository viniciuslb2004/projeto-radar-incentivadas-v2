> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

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

**Link direto pra uma operação (deep link do modal de detalhe, 2026-09-18)**: pedido do
usuário — clicar numa operação real (ex: "Ver operações deste setor" dentro do detalhe de uma
Linha Incentivada → lista → uma operação) devia gerar um link que qualquer pessoa (logada)
consiga colar e cair direto no detalhe daquela operação. Como `openOperacaoDetalhe(id)`
(`common.js`) é o MESMO modal compartilhado por Busca/Consolidado/Tendências/grupo
econômico/Linhas Incentivadas, a implementação ficou centralizada ali — vale automaticamente
pra qualquer lugar que já abre esse modal, não só Linhas Incentivadas.
- **Parâmetro de URL próprio, nunca misturado com os filtros da aba**: `?operacao=<id>`,
  gravado/removido via `_definirOperacaoNaURL(id)` — ao contrário de `sincronizarFiltrosNaURL`
  (que RECONSTRÓI a query string inteira a partir dos filtros de UMA aba), esta função só
  seta/apaga essa UMA chave, preservando o resto da URL (path da aba + mercado + filtros já
  ativos) — o modal é um OVERLAY por cima de qualquer aba, nunca uma troca de view, então não
  faz sentido ele reescrever o que já estava lá. Gravado assim que o modal abre
  (`openOperacaoDetalhe`, ANTES do fetch — mesmo se o id não existir, "detalhe não encontrado"
  é um estado real, não motivo pra esconder o parâmetro) e apagado em `closeModal()`.
- **Auto-abertura ao carregar a página** (`initFiltersAndTabs()`, `common.js`): o id é lido da
  URL (`_idOperacaoDaURL()`) **ANTES** de `_ligarBotoesDeAba()`/`_ativarView` rodarem — essas
  funções podem reescrever a query string via `sincronizarFiltrosNaURL` (cada aba normaliza
  seus próprios filtros ao carregar), o que apagaria `operacao` da URL antes de eu conseguir
  ler, já que essa função não sabe desse parâmetro. Guardado numa variável local, o modal só
  abre DEPOIS que mercado/aba/filtros terminarem de resolver (sucesso ou erro — mesmo espírito
  do `_resolverFiltrosProntos` no `finally`, nunca bloqueia o resto do boot).
- **Botão "🔗 Copiar link"** (`#modal-copiar-link-btn`, ao lado do "☆ Salvar"): mesmo padrão de
  visibilidade do botão de favoritar — só aparece em `openOperacaoDetalhe` (as outras 3 funções
  que reusam o MESMO modal — `openOperacoesModal`, `editais.js::openEditalDetalhe`,
  `linhas.js::openLinhaDetalhe` — escondem os dois de novo explicitamente, já que reusam o
  elemento). Copia `window.location.href` (já contém `?operacao=<id>` na hora do clique — nunca
  reconstrói a URL de novo aqui, uma única fonte de verdade) via `navigator.clipboard.writeText`,
  com feedback textual temporário (2s) e fallback de erro se o clipboard falhar.
  **Achado de ambiente ao testar**: `navigator.clipboard.writeText` falha com
  `NotAllowedError: Document is not focused` dentro do Claude Code Browser pane (mesma classe
  de limitação já documentada pra `document.cookie` nesse ambiente, ver "Coisas a saber antes
  de mexer") — confirmado que o catch/feedback de erro funciona corretamente (o botão mostra
  "Não foi possível copiar"), então o CÓDIGO está certo; só não dá pra confirmar visualmente o
  copy-to-clipboard de verdade nesse navegador de teste específico. Um clique real de usuário
  numa aba de verdade (com foco de janela genuíno) não deve ter esse problema.
- **Testado ao vivo, ponta a ponta**: `openOperacaoDetalhe(31260)` → URL vira
  `?operacao=31260`, modal abre com dado real; `closeModal()` → URL volta a
  `/linhas-incentivadas` (sem o parâmetro); recarregar a página direto em
  `/linhas-incentivadas?operacao=31260` (mesma simulação de "colar um link recebido") →
  modal abre sozinho, automaticamente, com o mesmo dado — confirmado via screenshot. Nenhuma
  exceção JS nova introduzida (console só mostrava os mesmos 401 residuais do carregamento
  pré-login de sempre, já documentados como ruído deste ambiente de teste).
