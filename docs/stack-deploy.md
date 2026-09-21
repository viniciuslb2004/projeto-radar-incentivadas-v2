> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

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
  **`data/embeddings.npz` excluído do bundle da function (2026-09-17, achado real: "Functions
  storage" da Vercel quase estourando)**: esse arquivo tem ~64MB (de longe o maior arquivo
  versionado do repo — o segundo maior, `brasil-uf.svg`, tem ~350KB) e estava sendo empacotado
  em TODA function serverless mesmo nunca sendo lido em produção — `np.load(EMB_PATH)`
  (`src/embeddings.py`) só roda dentro do caminho `MOTOR_BUSCA_IA=1` (ver seção "Motor de
  busca" acima), que fica desligado por padrão e não está habilitado em produção. Adicionado a
  `functions.api/index.py.excludeFiles` em `vercel.json` — o arquivo continua no repo (o
  pipeline semanal ainda lê/escreve nele normalmente via `src/embeddings.py`/`src/refresh.py`),
  só para de ser copiado pro artefato da function. **Se um dia `MOTOR_BUSCA_IA=1` for
  religado em produção**: essa exclusão precisa ser revertida primeiro, senão a function sobe
  sem o arquivo e as rotas de busca por IA quebram com `FileNotFoundError` (nunca testado esse
  cenário específico, mas é a consequência direta e esperada da exclusão).
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
