> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

## Coisas a saber antes de mexer

- **Espaço (2026-09-24)**: remover muitas linhas de `operations` (ex.: 200k BNB) deixa a tabela
  inchada; VACUUM comum não devolve disco. `VACUUM (FULL, ANALYZE) operations` levou 28 s
  (806 -> 219 MB; banco 1.050 -> 430 MB) e travou a tabela nesse tempo. Rodar com
  `SET lock_timeout='30s'` e checar `pg_stat_activity` antes. O usuário da app não tem
  permissão em `pg_ls_waldir`. `idx_operations_cnpj_digits_trgm` aparece com idx_scan=0, mas
  a tier 1 da busca usa esse índice: não dropar.

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


- **2026-09-23**: Aiven migrado in-place para GCP us-west2 (DNS do mesmo host trocou de 178.128.70.164/DO para 34.102.80.210/GCP em ~8 min). Teto subiu só de 20→25 conexões — regra de pool `max_size=2` mantida.
