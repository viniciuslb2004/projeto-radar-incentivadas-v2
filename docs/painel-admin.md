> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

> **ATUALIZADO 2026-09-22 — reposicionamento pra plataforma pública de lead-gen.**
> O login por usuário+senha do SITE PRINCIPAL descrito nas seções abaixo (`POST
> /api/login`, cadastro público com aprovação via `POST /api/registrar` +
> `status='pendente'/'aprovado'/'rejeitado'`) foi **substituído** por identificação
> passwordless por e-mail (`POST /api/identificar` + `POST /api/cadastrar`, ver
> seção nova "Identificação passwordless do site principal" mais abaixo) — sem
> senha em nenhum ponto do fluxo do site, acesso imediato (nunca aprovação de
> admin). **O painel `/admin` em si CONTINUA com login por usuário+senha
> normalmente** (`POST /admin/api/login`, tudo nesta seção abaixo sobre hash
> PBKDF2/sessão/`exigir_admin` permanece válido tal como está — a mudança é só no
> login do site). O fluxo antigo de cadastro com aprovação, e a antiga seção
> "Saúde do banco" do painel (removida na mesma sessão), estão documentados em
> `docs/archive/removed-features.md`, seção 4, caso precise reconstruir algum dos
> dois. As seções "Cadastro público com aprovação" e "Saúde do banco (proxy)" mais
> abaixo neste arquivo descrevem o comportamento ANTIGO — mantidas por enquanto
> só como histórico de decisões (hash de senha reaproveitado, `status` column,
> etc.), não como comportamento atual.

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

**Log de navegação por aba no drill-down (V2, aprovado 2026-09-16)**: o mesmo modal de
drill-down por usuário passou a reunir 2 fontes (era 3 — a terceira, histórico de busca via
`usuario_busca_historico`, foi removida em 2026-09-22 junto com Transações Salvas, ver
`docs/archive/removed-features.md`):
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
   pro cliente (best-effort dos dois lados).

**Cuidado real de volume, levantado ANTES de construir**: navegação por aba gera MUITO mais
linhas que login/logout (uma por troca de aba, de cada usuário logado, toda visita) — bem
diferente do volume de login/logout. Duas decisões tomadas por causa disso:
- **`GET /admin/api/acessos`** (a lista GERAL do painel, "últimos 100 acessos" de TODOS os
  usuários) continua filtrando `WHERE evento IN ('login', 'logout')` — `view_aba` NUNCA
  aparece ali, só no drill-down POR PESSOA. Sem esse filtro, poucos minutos de uso normal já
  afogariam o sinal de "quem entrou/saiu" que essa lista existe pra mostrar.
- O drill-down por pessoa (`GET .../usuarios/{id}/acessos`) mistura os 2 tipos de evento na
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

---

## Identificação passwordless do site principal (2026-09-22)

Reposicionamento explícito do produto: de ferramenta com cadastro+senha pra plataforma
pública de geração de leads. Login por usuário+senha do site (`POST /api/login`) e cadastro
público com aprovação (`POST /api/registrar`, ver seção "Cadastro público com aprovação"
acima — comportamento ANTIGO, arquivado em `docs/archive/removed-features.md` seção 4) foram
REMOVIDOS e substituídos por identificação só por e-mail, **sem senha em nenhum caso**. O
painel `/admin` (uso interno da Ártica) não foi tocado — continua login+senha normal.

**Landing page** (`webapp/static/index.html`, `#landing-overlay` — substitui o antigo
`#login-overlay`): página institucional (hero com proposta de valor + bullets, reaproveitando
a paleta navy/steel já definida em `style.css`) com o card de identificação ao lado. Mostrada
automaticamente sempre que uma rota `/api/*` protegida devolve 401 — ver "Robustez contra
sessão inválida" abaixo.

**Fluxo (2 passos, `webapp/main.py`)**:
1. `POST /api/identificar` `{email}` — só pede e-mail.
   - E-mail encontrado em `admin_usuarios` E com um evento `evento='login'` em
     `admin_acessos_log` nos últimos `JANELA_RENOVACAO_DIAS` dias (90, aproximação de "3
     meses"): **acesso imediato** — cria sessão (`criar_sessao`, mesmo mecanismo do painel,
     sem verificar senha), registra um novo evento `login`, devolve `{precisa_dados: false}`
     (cookie de sessão já setado). Frontend só dá `location.reload()`.
   - E-mail não encontrado OU encontrado mas sem login nos últimos 90 dias: devolve
     `{precisa_dados: true}`, SEM criar sessão — frontend mostra o formulário completo
     (`#cadastro-form`).
2. `POST /api/cadastrar` `{nome, empresa, cargo, email}` — upsert por e-mail (nunca cria uma
   segunda conta pro mesmo e-mail; se já existe, só atualiza nome/empresa/cargo). Concede
   acesso IMEDIATO (cria sessão na hora), sem aprovação de admin nenhuma. Conta nasce/continua
   com `role='usuario'`, `status='aprovado'` (coluna `status` mantida por compatibilidade de
   schema, mas não bloqueia mais nada nesse fluxo — só o painel antigo de aprovação a lia, e
   esse painel foi removido), `password_hash=''` (string vazia, sentinela — ver abaixo).

**Schema (`webapp/admin/seed.py`, mesmo padrão de migração incremental de sempre)**: 3
colunas novas em `admin_usuarios` — `nome TEXT`, `empresa TEXT`, `cargo TEXT` (NULL em contas
antigas/staff, só populadas pelo fluxo passwordless). Nenhuma tabela nova.

**`password_hash = ''` é o sinal de "conta passwordless" (convenção nova, não uma coluna
dedicada)** — usada em dois lugares pra separar "conta do painel/staff" (senha real, PBKDF2)
de "usuário/lead do site" (sem senha):
- `GET /admin/api/usuarios` (CRUD de staff, já existia) passou a filtrar
  `password_hash != ''` — sem isso, todo lead que se identifica no site apareceria misturado
  na lista de contas do painel.
- `GET /admin/api/usuarios-site` (nova, ver "Painel reestruturado" abaixo) filtra o oposto,
  `password_hash = ''`.
`verificar_senha('', hash_armazenado)` sempre falha (o split por `$` de um hash vazio levanta
`ValueError`, capturado e vira `False`) — uma conta passwordless nunca consegue logar em
`/admin/api/login` por acidente, mesmo que alguém tente.

**`username`**: como o schema antigo exige `username UNIQUE NOT NULL`, contas passwordless
usam o próprio e-mail como `username` (funcionalmente único o suficiente) — `site_cadastrar`
tem um loop de fallback (`email+2`, `email+3`, ...) só pro caso improvável de colisão.

**`GET /api/me`** devolve `{username, nome}` agora (antes só `username`) — `nome` alimenta o
texto do botão "Quero saber mais" se um dia precisar mostrar o nome (hoje o botão não mostra,
mas o campo já está disponível pro frontend).

### "Quero saber mais" (substitui usuário logado + Sair na topbar)

Onde antes havia nome do usuário + botão "Sair" (`#topbar-usuario`), agora há um único botão
`#topbar-interesse-btn` — só visível pra quem já se identificou (`obterUsuarioAtual()`, ver
`common.js`). Clique: mostra um modal de agradecimento IMEDIATAMENTE (a pessoa já informou
nome/empresa/cargo/e-mail na identificação, não há formulário adicional aqui) e dispara
`POST /api/interesse` (rota protegida — exige sessão válida, fora de `_ROTAS_PUBLICAS_API`)
em paralelo, best-effort (uma falha de rede não desfaz o agradecimento já mostrado). Backend
registra um evento novo `evento='interesse_lead'` em `admin_acessos_log` (mesma tabela, mesmo
padrão já usado por `view_aba`) — sem tabela nova, sem formulário adicional.

**Coluna nova `admin_acessos_log.contatado`** (`BOOLEAN NOT NULL DEFAULT FALSE`, via
`seed.py`) — só tem sentido pra linhas `evento='interesse_lead'`; alimenta o indicador
"precisa ser abordado" na seção Leads do painel (ver abaixo). `POST
/admin/api/leads/{log_id}/contatado` alterna o valor.

### Robustez contra sessão inválida (bug real corrigido)

Reportado pelo usuário: quando a sessão expirava/cookie sumia/usuário era removido, o site
"quebrava" (ficava em branco) em vez de voltar pra tela de login. Causa raiz: só o PRIMEIRO
fetch (`/api/status`, dentro de `_initFiltersAndTabsImpl`) tratava `ErroAutenticacao`
mostrando a tela de login — qualquer outro fetch protegido que caísse num 401 no MEIO do uso
(sessão expirando depois do carregamento inicial) batia num `catch` genérico já existente em
vários arquivos (`consolidado.js`/`tendencias.js`: `catch (e) { data = []; }`), que engolia o
erro silenciosamente sem nunca voltar pra tela de login.

**Corrigido centralizando o tratamento em `fetchJSON`/`postJSON`** (`common.js`): as duas
funções agora chamam `_mostrarLanding()` (mostra a landing/tela de identificação) ANTES de
lançar `ErroAutenticacao`, sempre que a resposta é 401 — cobre sessão expirada, cookie
ausente, usuário removido/inativo e sessão inválida (todos esses casos já caíam em 401 no
backend, ver `verificar_acesso_principal`), independente de qualquer `catch` que o chamador
tenha (ou não tenha). Um `window.addEventListener("unhandledrejection", ...)` global serve de
backstop pra qualquer `ErroAutenticacao` que escape sem handler nenhum (defesa em
profundidade). `_mostrarLanding()` é idempotente (só troca classes CSS), seguro chamar várias
vezes seguidas.

### Painel reestruturado (usuários/leads/comportamento)

Pedido explícito do usuário: painel focado em usuários/leads/comportamento, 3 visões claras
— todas seções da MESMA página `admin.html` (não abas separadas, mesmo padrão de sempre desse
painel: seções empilhadas verticalmente).

- **Usuários** (`GET /admin/api/usuarios-site`, seção "Usuários" em `admin.html`): nome,
  e-mail, empresa, cargo, primeiro acesso, último acesso, quantidade de acessos — só contas
  `password_hash = ''` (site/lead), nunca contas do painel. Primeiro/último acesso e
  quantidade calculados via subquery correlacionada sobre `admin_acessos_log` (volume baixo,
  sem preocupação de performance aqui).
- **Interessados / Leads** (`GET /admin/api/leads`, `POST /admin/api/leads/{id}/contatado`,
  seção "Interessados / Leads"): nome/e-mail/empresa/cargo (via JOIN com `admin_usuarios`) +
  data da manifestação (`criado_em` do evento `interesse_lead`) + badge de status ("Precisa
  ser abordado" em vermelho / "Contatado" em verde, reaproveitando as classes CSS
  `.admin-pill.inativo`/`.admin-pill.ativo` já existentes) + botão pra alternar o status.
- **Atividade** (`GET /admin/api/atividade`, seção "Atividade"): sessões agregadas — uma
  sessão começa num evento `login` e termina no próximo `logout` OU no próximo `login` da
  MESMA pessoa (o que vier primeiro; cobre o caso comum de fechar a aba sem logout explícito,
  já que o site público não tem mais botão de Sair). Duração aproximada = diferença de tempo
  entre entrada e saída; páginas visitadas = eventos `view_aba` dentro desse intervalo.
  Agrupamento feito em PYTHON (não SQL — `webapp/admin/routes.py::atividade`), de propósito:
  o volume de `admin_acessos_log` é pequeno o suficiente pra isso ser simples e fácil de
  revisar, em vez de uma janela SQL correlacionada mais difícil de auditar. Limitado a 300
  sessões mais recentes (sem paginação ainda, mesmo espírito de outros limites já documentados
  neste painel).
- **`GET /admin/api/acessos`** (lista geral de login/logout, já existia) continua só com
  `evento IN ('login', 'logout')` — `interesse_lead` (como `view_aba`) fica de fora dessa
  lista geral de propósito (mesmo motivo já documentado pra `view_aba`: evitar afogar o sinal
  de "quem entrou/saiu"), só aparece nas seções Leads/Atividade específicas.
- **"Contas do painel (equipe Ártica)"** — renomeado de "Usuários do painel" pra não confundir
  com a nova seção "Usuários" (site/leads) — MESMO CRUD de sempre (criar/ativar/desativar/
  promover/rebaixar/resetar senha/excluir conta de staff), filtrando agora `password_hash !=
  ''` (ver acima), comportamento interno inalterado.
- **"Saúde do banco" foi REMOVIDA** do painel (pedido explícito do usuário, fora do fluxo
  principal de usuários/leads) — código original preservado em
  `docs/archive/removed-features.md` seção 4, caso um dia vire uma tela técnica separada.
- **Dashboard** (`GET /admin/api/dashboard`, cards no topo) ganhou `total_usuarios_site`,
  `total_leads` e `leads_pendentes` (contagem de `interesse_lead` com `contatado = FALSE`) —
  `total_usuarios` (cards "Contas do painel") passou a contar só `password_hash != ''`.
