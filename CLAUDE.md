# Radar de Crédito Incentivado — contexto para IAs futuras

Este arquivo é o ÍNDICE + as regras que toda sessão precisa saber ANTES de tocar em qualquer
coisa. Detalhe histórico (o "porquê", incidentes já resolvidos, auditorias, decisões de
produto passadas) foi movido pra `docs/*.md` — leia só o arquivo relevante pra sua tarefa
específica, nunca carregue todos de uma vez. Isso existe pra reduzir o custo de contexto de
toda sessão nova (este arquivo sozinho já cobre ~90% do que se precisa pra começar a mexer sem
quebrar nada). `AGENTS.md` aponta pra este arquivo (mesmo conteúdo, uma fonte só).
`README.md`/`DEPLOY.md`/`RESUME.md` são notas point-in-time e ficam desatualizadas rápido —
não confiar neles como fonte de verdade.

**Última reestruturação deste arquivo: 2026-09-21** (redução de ~2400 para ~150 linhas,
conteúdo integral preservado em `docs/`).

**Última revisão desta linha: 2026-09-22** — reposicionamento pra plataforma pública/lead-gen:
Mercado Primário/Exportações/Favoritos removidos; login do site principal virou passwordless
por e-mail (`POST /api/identificar`/`/api/cadastrar`, sem senha — `/admin` continua com senha
normalmente); nova aba "Potenciais Linhas". Ver `docs/painel-admin.md`/`docs/linhas-incentivadas.md`.

**Revisão adicional 2026-09-22**: nova área interna `/interno-artica` — mesma SPA do site
público, login próprio (usuário+senha, `POST /api/interno/login`, qualquer conta de staff já
existente em `admin_usuarios`) com 3 funcionalidades extras (Salvar/Notas/Exportar Excel),
gated por `webapp/admin/auth.py::exigir_staff` (staff = `password_hash != ''`, distinto de
`role`). Ver `docs/painel-admin.md`, seção "Área interna da Equipe Ártica".

## O que é a plataforma

Site que acompanha operações de **crédito incentivado** de empresas brasileiras junto a
instituições de fomento (BNDES/FINEP, ~59 mil operações desde 2002) + catálogo de **linhas de
crédito permanentes** (produtos, não transações — BNDES/FINEP/Desenvolve SP/BNB/BASA/BB/CEF).
Público-alvo: análise de mercado (prospecção/benchmarking), não originação de crédito.

100% online: SPA vanilla JS + FastAPI + Postgres (Aiven), tudo na Vercel. Não existe mais
"modo local" com banco separado — local (`uvicorn`) e produção falam com o MESMO Postgres via
`DATABASE_URL`.

## Stack (essencial — histórico/migração em `docs/stack-deploy.md`)

- **Backend**: FastAPI (`webapp/main.py`), rotas `/api/*`.
- **Frontend**: SPA vanilla JS sem framework/bundler, `webapp/static/index.html` com
  `<section class="view">` por aba, troca 100% client-side.
- **Banco**: Postgres no Aiven, free tier (1GB, teto de 20 conexões). Acessado via `psycopg`
  v3. Uma única `DATABASE_URL` usada por webapp E pipeline (GitHub Actions).
- **Deploy**: Vercel — `vercel.json` serve `webapp/static` direto + rewrite `/api/*` →
  `api/index.py` (function serverless). O serviço Render antigo é legado morto, ignorar.
- **Automação**: GitHub Actions (`.github/workflows/*.yml`) — ver `docs/automacao.md`.

## Regras críticas (nunca violar — causaram incidente real ao menos uma vez)

- **SQL sempre com `?`, nunca `%s`** — `db_compat.py` faz o monkeypatch pra psycopg. Um `%`
  literal numa query (`LIKE`) precisa virar `%%`.
- **Nunca inventar dado**: valor/taxa/prazo/indexador/carência não documentado na fonte oficial
  fica `NULL`/`NAO_INFORMADO`, nunca estimado/inferido (catálogo de Linhas Incentivadas).
- **Rotas da webapp usam `get_connection(pooled=True)`** (pool `psycopg_pool`, `max_size=2`; mantido após migração 2026-09-23 pro Aiven GCP us-west2: `max_connections` foi só de 20→25, 22 úteis → ~11 instâncias Vercel de margem; subir pra 3 cairia pra ~7 sem ganho medido).
  Scripts de pipeline (rodados só via GitHub Actions) usam `get_connection()` sem pool. Não
  inverter — ver `docs/incidentes-infra.md` pro histórico de esgotamento de conexão no Aiven.
- **Mudança de schema/índice contra o Aiven de produção exige confirmação do usuário antes**
  (mesmo banco compartilhado por todas as sessões concorrentes) — mesmo `CREATE INDEX
  CONCURRENTLY`, que não trava escrita.
- **Sessões de IA concorrentes podem compartilhar este working directory** — rodar
  `git diff <arquivo>` antes de `git add`/`commit` se houver qualquer suspeita de edição
  paralela de outra sessão.
- **Testar a webapp local exige sessão de verdade** (site principal: passwordless via
  `POST /api/identificar`/`/api/cadastrar`, mesmo banco de produção; painel `/admin`: usuário+
  senha normalmente) — ver `docs/painel-admin.md` pra como mintar uma sessão de teste sem UI.
- **Sempre matar processos `uvicorn` soltos** antes/depois de testar contra produção — o teto
  de conexões do Aiven já estourou 3x por processos esquecidos rodando.
- **Filtros estruturados (UF, setor, agência, etc.) são sempre `AND`, nunca entram no ranking
  de texto livre da busca** — ver `docs/motor-busca.md`.
- **`limit`/`offset` de rotas públicas sempre com teto/clamp** (`max(1, min(limit, N))`) — já
  aplicado em todas as rotas de listagem, manter o padrão em rotas novas.

## Modelo de dados (schema completo em `src/db.py`; mais contexto em `docs/modelo-dados-pipeline.md`)

| Tabela | O que é |
|---|---|
| `bndes_raw`, `finep_credito_direto_raw`, `finep_credito_descentralizado_raw`, `bnb_raw` | staging, quase cru da fonte oficial (`bnb_raw`: só PJ com valor > R$ 1 mi, extraído do Power BI público do BNB por `src/bnb.py`, reconciliado em `bnb_reconciliacao`) |
| `operations` | tabela UNIFICADA BNDES+FINEP+BNB — todo dashboard/busca lê daqui |
| `cnpj_cnae` | cache CNPJ→CNAE/razão social/porte/uf/município (Receita Federal) |
| `de_para_cnae` | crosswalk oficial BNDES: divisão CNAE → Setor/Subsetor |
| `editais_raw` | editais (chamadas públicas) da FINEP — não entra no rebuild de `operations` |
| `linhas_incentivadas` | catálogo de produtos permanentes (não transações) |
| `operations_correcoes_manuais` | correções manuais, reaplicadas a cada refresh |
| `refresh_log` / `refresh_editais_log` | histórico de cada rodada de pipeline |
| `admin_usuarios` / `admin_sessoes` / `admin_acessos_log` | contas, sessão e log de acesso (painel + site principal + área interna) |
| `usuario_operacoes_salvas` | favoritos + nota interna por conta de STAFF (`/interno-artica`), já existe em produção (achado ao vivo 2026-09-22 — nunca chegou a ser dropada quando "Transações Salvas" foi removida, apesar do que `docs/archive/removed-features.md` descreve) |

## Onde procurar o quê (mapa rápido — histórico/detalhe em `docs/`)

| Preciso mexer em... | Arquivo | Detalhe/histórico |
|---|---|---|
| Schema do banco / pipeline semanal | `src/db.py`, `src/refresh.py`, `src/unify.py` | `docs/modelo-dados-pipeline.md` |
| Enriquecimento CNPJ→CNAE | `src/enrich_cnae.py`, `src/sector_taxonomy.py` | `docs/bugs-corrigidos.md` |
| Motor de busca (sem IA / IA opcional) | `src/search_fts.py`, `src/search_taxonomy.py`, `src/search.py`, `src/embeddings.py` | `docs/motor-busca.md` |
| Catálogo Linhas Incentivadas / Potenciais Linhas / Transações Semelhantes | `src/linhas_incentivadas.py`, `webapp/potenciais.py` | `docs/linhas-incentivadas.md` |
| Editais da FINEP | `src/finep_editais.py`, `src/refresh_editais.py` | — |
| API/rotas | `webapp/main.py` | — |
| Frontend — abas, roteamento, filtros na URL | `webapp/static/js/common.js`, `webapp/static/index.html` | `docs/frontend-abas.md` |
| Frontend — cada aba | `webapp/static/js/{consolidado,tendencias,busca,editais,linhas}.js` | — |
| Painel de Admin (`/admin`) | `webapp/admin/*`, `webapp/static/admin.html`, `webapp/static/js/admin.js` | `docs/painel-admin.md` |
| Área interna Equipe Ártica (`/interno-artica` — Salvar/Notas/Exportar Excel) | `webapp/salvos.py`, `webapp/exportar_excel.py`, `webapp/admin/auth.py::exigir_staff` | `docs/painel-admin.md` |
| Deploy Vercel | `vercel.json`, `api/index.py`, `DEPLOY.md` | `docs/stack-deploy.md` |
| Automação (GitHub Actions) | `.github/workflows/*.yml` | `docs/automacao.md` |
| Gotchas de infra/produção (Aiven, pool, sequences, cookie) | — | `docs/incidentes-infra.md` |
| Bugs reais já corrigidos (armadilhas a não repetir) | — | `docs/bugs-corrigidos.md` |
| Auditorias de otimização já feitas (o que já foi medido/aplicado) | — | `docs/auditoria-otimizacao.md` |
| Funcionalidades removidas (Mercado Primário, Exportações, Favoritos/Transações Salvas) — SÓ consultar se a tarefa exigir restaurar algo | — | `docs/archive/removed-features.md` (backup técnico, não operacional — nunca carregar por rotina) |
