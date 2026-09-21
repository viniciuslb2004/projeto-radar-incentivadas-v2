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

## O que é a plataforma

Site que acompanha operações de **crédito incentivado** de empresas brasileiras junto a
instituições de fomento (BNDES/FINEP, ~58 mil operações desde 2002) + catálogo de **linhas de
crédito permanentes** (produtos, não transações — BNDES/FINEP/Desenvolve SP/BNB/BASA/BB/CEF).
Público-alvo: análise de mercado (prospecção/benchmarking), não originação de crédito.

**Segundo "modo": "Radar de Crédito Primário"** — mercado de capitais primário (debêntures,
CRI, CRA, notas comerciais, letras financeiras, CDCA, CCB, CPR-F) via dados da CVM. Já tem
camada de dados + API/busca + frontend completos (toggle de mercado na topbar) — ver
`docs/radar-primario-*.md`.

100% online: SPA vanilla JS + FastAPI + Postgres (Aiven), tudo na Vercel. Não existe mais
"modo local" com banco separado — local (`uvicorn`) e produção falam com o MESMO Postgres via
`DATABASE_URL`.

## Stack (essencial — histórico/migração em `docs/stack-deploy.md`)

- **Backend**: FastAPI (`webapp/main.py`), rotas `/api/*`. Radar Primário isolado em
  `webapp/primario/` (prefixo `/api/primario/*`).
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
  fica `NULL`/`NAO_INFORMADO`, nunca estimado/inferido. Vale pro catálogo de Linhas Incentivadas
  e pro Radar Primário (CVM) igualmente.
- **Rotas da webapp usam `get_connection(pooled=True)`** (pool `psycopg_pool`, `max_size=2`).
  Scripts de pipeline (rodados só via GitHub Actions) usam `get_connection()` sem pool. Não
  inverter — ver `docs/incidentes-infra.md` pro histórico de esgotamento de conexão no Aiven.
- **Mudança de schema/índice contra o Aiven de produção exige confirmação do usuário antes**
  (mesmo banco compartilhado por todas as sessões concorrentes) — mesmo `CREATE INDEX
  CONCURRENTLY`, que não trava escrita.
- **Sessões de IA concorrentes podem compartilhar este working directory** — rodar
  `git diff <arquivo>` antes de `git add`/`commit` se houver qualquer suspeita de edição
  paralela de outra sessão.
- **Testar a webapp local exige login de verdade** (contas reais em `admin_usuarios`, mesmo
  banco de produção) — ver `docs/painel-admin.md` pra como mintar uma sessão de teste sem UI.
- **Sempre matar processos `uvicorn` soltos** antes/depois de testar contra produção — o teto
  de conexões do Aiven já estourou 3x por processos esquecidos rodando.
- **Filtros estruturados (UF, setor, agência/instrumento, etc.) são sempre `AND`, nunca entram
  no ranking de texto livre da busca** — ver `docs/motor-busca.md`.
- **`limit`/`offset` de rotas públicas sempre com teto/clamp** (`max(1, min(limit, N))`) — já
  aplicado em todas as rotas de listagem, manter o padrão em rotas novas.

## Modelo de dados (schema completo em `src/db.py`; mais contexto em `docs/modelo-dados-pipeline.md`)

| Tabela | O que é |
|---|---|
| `bndes_raw`, `finep_credito_direto_raw`, `finep_credito_descentralizado_raw` | staging, quase cru da fonte oficial |
| `operations` | tabela UNIFICADA BNDES+FINEP — todo dashboard/busca do mercado Incentivado lê daqui |
| `cnpj_cnae` | cache CNPJ→CNAE/razão social/porte/uf/município (Receita Federal) |
| `de_para_cnae` | crosswalk oficial BNDES: divisão CNAE → Setor/Subsetor |
| `editais_raw` | editais (chamadas públicas) da FINEP — não entra no rebuild de `operations` |
| `linhas_incentivadas` | catálogo de produtos permanentes (não transações) |
| `operations_correcoes_manuais` | correções manuais, reaplicadas a cada refresh |
| `refresh_log` / `refresh_editais_log` / `refresh_primario_log` | histórico de cada rodada de pipeline |
| `cvm_oferta_distribuicao_raw` / `cvm_oferta_resolucao_160_raw` | staging CVM (2 fontes distintas) |
| `operations_primario` | tabela unificada do Radar de Crédito Primário |
| `admin_usuarios` / `admin_sessoes` / `admin_acessos_log` | contas, sessão e log de acesso (painel + site principal) |
| `usuario_operacoes_salvas` / `usuario_busca_historico` | Transações Salvas (favoritos/histórico por conta) |

## Onde procurar o quê (mapa rápido — histórico/detalhe em `docs/`)

| Preciso mexer em... | Arquivo | Detalhe/histórico |
|---|---|---|
| Schema do banco / pipeline semanal | `src/db.py`, `src/refresh.py`, `src/unify.py` | `docs/modelo-dados-pipeline.md` |
| Enriquecimento CNPJ→CNAE | `src/enrich_cnae.py`, `src/sector_taxonomy.py` | `docs/bugs-corrigidos.md` |
| Motor de busca (sem IA / IA opcional) | `src/search_fts.py`, `src/search_taxonomy.py`, `src/search.py`, `src/embeddings.py` | `docs/motor-busca.md` |
| Catálogo Linhas Incentivadas | `src/linhas_incentivadas.py` | `docs/linhas-incentivadas.md` |
| Editais da FINEP | `src/finep_editais.py`, `src/refresh_editais.py` | — |
| Radar Primário — pipeline CVM | `src/download_cvm.py`, `src/parse_cvm.py`, `src/parse_cvm_resolucao160.py`, `src/unify_primario.py`, `src/refresh_primario.py` | `docs/radar-primario-pipeline.md` |
| Radar Primário — API/rotas + busca | `webapp/primario/routes.py`, `src/search_fts_primario.py` | `docs/radar-primario-api-busca.md` |
| Radar Primário — frontend/toggle de mercado | `webapp/static/js/common.js` (`_MERCADOS`/`alternarMercado`), `consolidado.js`/`tendencias.js`/`busca.js` | `docs/radar-primario-frontend.md` |
| API/rotas (mercado Incentivado) | `webapp/main.py` | — |
| Frontend — abas, roteamento, filtros na URL | `webapp/static/js/common.js`, `webapp/static/index.html` | `docs/frontend-abas.md` |
| Frontend — cada aba | `webapp/static/js/{consolidado,tendencias,busca,editais,linhas}.js` | — |
| Painel de Admin (`/admin`) | `webapp/admin/*`, `webapp/static/admin.html`, `webapp/static/js/admin.js` | `docs/painel-admin.md` |
| Transações Salvas (favoritos/histórico) | `webapp/salvos.py`, `webapp/static/js/salvos.js` | `docs/transacoes-salvas.md` |
| Deploy Vercel | `vercel.json`, `api/index.py`, `DEPLOY.md` | `docs/stack-deploy.md` |
| Automação (GitHub Actions) | `.github/workflows/*.yml` | `docs/automacao.md` |
| Gotchas de infra/produção (Aiven, pool, sequences, cookie) | — | `docs/incidentes-infra.md` |
| Bugs reais já corrigidos (armadilhas a não repetir) | — | `docs/bugs-corrigidos.md` |
| Auditorias de otimização já feitas (o que já foi medido/aplicado) | — | `docs/auditoria-otimizacao.md` |
