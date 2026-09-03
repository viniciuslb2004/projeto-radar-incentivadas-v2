# Radar de Crédito Incentivado (BNDES + FINEP)

App 100% online (Vercel + Postgres/Supabase, ver `DEPLOY.md`) que acompanha as operações de
crédito incentivado do BNDES e da FINEP, mostra dois painéis (Consolidado e Tendências) e
permite buscar, em texto livre, operações/editais parecidos com uma empresa/setor descrito
pelo usuário (busca semântica via embeddings, sem IA generativa nenhuma).

Não há mais um "modo local" com banco separado -- o app sempre fala com o mesmo Postgres
(Supabase) via a variável de ambiente `DATABASE_URL`, tanto rodando localmente (`uvicorn`,
para desenvolvimento) quanto em produção (Vercel).

## Rodando localmente (desenvolvimento)

```powershell
powershell scripts\setup.ps1
# num arquivo .env na raiz do repo: DATABASE_URL=postgresql://...sua connection string do Supabase...
.venv\Scripts\python.exe src\db.py                # cria/atualiza o schema no Postgres
.venv\Scripts\python.exe src\refresh.py
.venv\Scripts\python.exe src\enrich_cnae.py       # demorado (~5-6GB), enriquece o setor da FINEP
.venv\Scripts\python.exe src\embeddings.py        # gera os embeddings de busca (roda de novo apos o enrich_cnae)
```

## Subindo o site localmente

```powershell
.venv\Scripts\python.exe -m uvicorn webapp.main:app --host 127.0.0.1 --port 8001
```

Depois abra http://127.0.0.1:8001 no navegador. Para o deploy hospedado (Vercel), ver `DEPLOY.md`.

## Estrutura

- `src/download.py` — baixa os xlsx do BNDES e da FINEP
- `src/parse_bndes.py`, `src/parse_finep.py` — normalizam as planilhas em staging tables
- `src/unify.py` — constrói a tabela `operations` (schema comum) e os agregados do dashboard
- `src/enrich_cnae.py` — enriquece o setor da FINEP via CNPJ→CNAE (Receita Federal), job mensal
- `src/embeddings.py`, `src/editais_embeddings.py` — geram os embeddings locais (busca por similaridade)
- `src/search.py`, `src/editais_search.py` — motor de busca semântica (embeddings, sem IA generativa)
- `src/refresh.py`, `src/refresh_editais.py` — orquestram os pipelines (download → parse → unify → embeddings)
- `src/db.py` — conexão Postgres (Supabase) e schema; `src/db_compat.py` — compat de placeholder `?`→`%s`
- `webapp/` — API FastAPI (`webapp/main.py`) + frontend (HTML/CSS/JS, identidade visual Ártica)
- `api/index.py` — entrypoint da função serverless da Vercel (importa `webapp.main:app`)
- `scripts/` — setup local e agendamento opcional no Task Scheduler (ver nota abaixo)
- `scripts/migrate_sqlite_to_supabase.py` — migração única já executada (SQLite local → Supabase)

## Automação dos refreshes

A automação principal roda via **GitHub Actions** (`.github/workflows/`, contra o mesmo
Postgres via o secret `DATABASE_URL`) -- diário para editais, semanal para operações BNDES/FINEP,
mensal para o enriquecimento de CNAE. Os scripts `scripts/install_scheduled_task*.ps1` (Windows
Task Scheduler local) continuam funcionando como alternativa/backup, mas não são mais o caminho
principal desde que a automação passou a rodar 100% na nuvem.

## Escopo dos dados

- **BNDES**: operações contratadas na forma direta e indireta não automática (2002 até hoje)
- **FINEP**: só as operações de **crédito** (Crédito Direto + Crédito Descentralizado) — ficam de fora
  subvenção, não-reembolsável, investimento em startups e ANCINE, por decisão de escopo do projeto.

## Forçar um refresh manual

```powershell
.venv\Scripts\python.exe src\refresh.py
```

## Logs

- Tabela `refresh_log` (Postgres) guarda o histórico de cada refresh -- consulte via
  `SELECT * FROM refresh_log ORDER BY id DESC` no SQL editor do Supabase.
- Se estiver usando o Task Scheduler local como backup, ele também grava a saída da tarefa
  agendada; confira com: `Get-ScheduledTaskInfo -TaskName "RadarCreditoIncentivado"`
