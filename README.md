# Radar de Crédito Incentivado (BNDES + FINEP)

App local (sem custos de nuvem/API) que acompanha as operações de crédito incentivado do BNDES e da FINEP,
mostra dois painéis (Consolidado e Tendências) e permite buscar, em texto livre, operações parecidas com
uma empresa/setor descrito pelo usuário, com leitura de tendência (setor em alta ou em queda).

## Rodando pela primeira vez

```powershell
powershell scripts\setup.ps1
.venv\Scripts\python.exe src\refresh.py
.venv\Scripts\python.exe src\enrich_cnae.py      # demorado (~5-6GB), enriquece o setor da FINEP
.venv\Scripts\python.exe src\embeddings.py        # gera os embeddings de busca (roda de novo apos o enrich_cnae)
powershell scripts\install_scheduled_task.ps1      # agenda o refresh semanal (BNDES + FINEP)
powershell scripts\install_scheduled_task_cnae.ps1 # agenda o reenriquecimento mensal de setor
```

Para o "narrador" da busca (opcional, com fallback automático se não estiver disponível):

```powershell
winget install --id Ollama.Ollama -e
ollama pull llama3.2:3b-instruct-q4_K_M
```

## Subindo o site

```powershell
.venv\Scripts\python.exe -m uvicorn webapp.main:app --host 127.0.0.1 --port 8000
```

Depois abra http://127.0.0.1:8000 no navegador.

## Estrutura

- `src/download.py` — baixa os xlsx do BNDES e da FINEP
- `src/parse_bndes.py`, `src/parse_finep.py` — normalizam as planilhas em staging tables
- `src/unify.py` — constrói a tabela `operations` (schema comum) e os agregados do dashboard
- `src/enrich_cnae.py` — enriquece o setor da FINEP via CNPJ→CNAE (Receita Federal), job mensal
- `src/embeddings.py` — gera os embeddings locais (busca por similaridade)
- `src/search.py` — motor de busca + narrador (Ollama com fallback estatístico)
- `src/refresh.py` — orquestra o pipeline semanal (download → parse → unify → embeddings)
- `webapp/` — API FastAPI + frontend (HTML/CSS/JS, identidade visual Ártica)
- `scripts/` — instalação e agendamento no Task Scheduler

## Escopo dos dados

- **BNDES**: operações contratadas na forma direta e indireta não automática (2002 até hoje)
- **FINEP**: só as operações de **crédito** (Crédito Direto + Crédito Descentralizado) — ficam de fora
  subvenção, não-reembolsável, investimento em startups e ANCINE, por decisão de escopo do projeto.

## Forçar um refresh manual

```powershell
.venv\Scripts\python.exe src\refresh.py
```

## Logs

- `data/radar.db` → tabela `refresh_log` guarda o histórico de cada refresh.
- Task Scheduler grava a saída da tarefa agendada; confira com:
  `Get-ScheduledTaskInfo -TaskName "RadarCreditoIncentivado"`
