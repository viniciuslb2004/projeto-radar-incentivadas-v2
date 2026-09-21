> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

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
