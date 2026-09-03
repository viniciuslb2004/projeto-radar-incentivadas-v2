# Estado do projeto (atualizado em 2026-09-03)

## Como retomar

```powershell
cd "C:\Users\ViníciusBorrellas\OneDrive - Ártica\Desenvolvimento - Incentivadas"
.venv\Scripts\python.exe -m uvicorn webapp.main:app --host 127.0.0.1 --port 8001
```

Depois abra http://127.0.0.1:8001. O app agora fala SEMPRE com Postgres (Supabase) via
`DATABASE_URL` -- não existe mais banco local (SQLite) nem modo dual local/hospedado. Em
desenvolvimento local, `DATABASE_URL` vem de um arquivo `.env` na raiz do repo (não commitado,
já tem a connection string do projeto Supabase "Linhas Incentivadas - CapSol").

Se a porta 8001 estiver ocupada (ou o servidor não responder), troque para outra porta.

## Mudança de arquitetura desta sessão (2026-09-03) -- a maior do projeto até agora

Direção de produto mudou: bases de dados passam a chegar mais processadas de uma etapa
externa; a plataforma deixa de fazer IA generativa e vira 100% online.

1. **IA generativa (Ollama) removida por completo** -- resumos de edital, refino de busca,
   narrativa. A busca SEMÂNTICA (embeddings) continua 100% intacta (é uma funcionalidade real
   da plataforma, não uma etapa de "processamento"). Não há mais nenhuma referência a Ollama em
   lugar nenhum do código.
2. **Banco migrado de SQLite local + Turso hospedado para um único Postgres (Supabase)** --
   `src/db.py` reescrito (schema em sintaxe Postgres, `GENERATED ALWAYS AS IDENTITY`), novo
   `src/db_compat.py` (traduz `?`→`%s` sem precisar editar as dezenas de call sites
   existentes), `coerce_for_pg` no lugar de `coerce_for_affinity`. Dados migrados de
   `data/radar.db` pro Supabase via `scripts/migrate_sqlite_to_supabase.py` (já rodado com
   sucesso, 94.580 linhas, 8 tabelas, contagens conferidas).
3. **Deploy hospedado movendo de Render+Vercel para Vercel sozinha** (frontend + backend
   juntos, função Python serverless em `api/index.py`) -- ver `DEPLOY.md` para arquitetura e
   passo a passo. **Ainda não implantado de verdade** (só a estrutura de arquivos está pronta:
   `vercel.json`, `api/index.py`, `requirements-api.txt`) -- falta configurar o projeto na
   Vercel de verdade e decidir quando desligar a Render.
4. Workflows do GitHub Actions (`.github/workflows/*.yml`) atualizados para usar o secret
   `DATABASE_URL` em vez de `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` -- **ainda não pushado**
   pro repositório: falta o usuário adicionar o secret `DATABASE_URL` (Settings → Secrets and
   variables → Actions) antes, senão os workflows quebram na próxima execução agendada.

### Pendências reais para fechar a migração

- [ ] Usuário adiciona o secret `DATABASE_URL` no GitHub (Settings → Secrets and variables → Actions).
- [ ] Push dos commits locais (migração Postgres + workflows atualizados) pro `master`.
- [ ] Criar/configurar o projeto na Vercel (Root Directory = raiz do repo, não mais
      `webapp/static`), variáveis de ambiente `DATABASE_URL`/`SITE_USER`/`SITE_PASSWORD`.
- [ ] Confirmar no 1º deploy real se `requirements-api.txt` é o arquivo que a Vercel usa pra
      função (maior risco não testado, ver DEPLOY.md -- se não for, renomear pra
      `api/requirements.txt`).
- [ ] Depois de confirmar o deploy da Vercel funcionando, desligar o serviço da Render (não
      apagar ainda -- é a rede de segurança até a Vercel estar 100% validada).

## O que já está pronto e funcionando (verificado ao vivo contra o Supabase real)

- Base unificada: ~30.585 operações (23.723 BNDES + 6.862 FINEP crédito), setor 100%
  classificado nas duas agências. Granularidade em 3 níveis: Setor (4), Subsetor (19),
  Segmento CNAE (~1.290).
- 5 abas: Consolidado, Tendências & Insights, Busca (semântica, embeddings, sem IA
  generativa), Editais (chamadas públicas abertas da FINEP), Minha Empresa (elegibilidade por
  CNPJ).
- **Minha Empresa**: resolve setor/porte via BrasilAPI a partir do CNPJ, cruza com histórico de
  operações do setor (+ sub-linha real dentro de cada produto BNDES, ex: dentro de "BNDES
  FINEM" -- "PSI - Inovação", com um projeto real como evidência) e rankeia os editais abertos
  por similaridade semântica real (upgrade progressivo: mostra o filtro estrutural primeiro,
  troca pela lista rankeada por IA assim que o embedding calculado no navegador chega).
- Automação: GitHub Actions roda diário (editais), semanal (operações BNDES/FINEP) e mensal
  (enriquecimento CNAE) -- ver pendência acima sobre o secret `DATABASE_URL`.

## Bug crítico corrigido nesta sessão (antes da migração de banco)

`sector_taxonomy.py`'s `build_divisao_map()` fatiava código de CNAE de forma errada para faixas
com códigos de subclasse longos (ex: "H4911, H4912401 e H4912402"), corrompendo o mapeamento
setor/subsetor de várias divisões CNAE no meio do caminho (ex: divisão 26, "Fabricação de
componentes eletrônicos", virava "Transporte Ferroviário" em vez de "Indústria"). Corrigido com
`_extrair_divisoes()`, que só preenche um intervalo quando o texto tem " a " por extenso.

## Arquivos-chave

- Pipeline de dados (operações): `src/refresh.py` (orquestra tudo), `src/enrich_cnae.py` (pesado, mensal)
- Pipeline de dados (editais): `src/refresh_editais.py` (orquestra `finep_editais.py` + `editais_documentos.py` + `editais_embeddings.py`)
- Motor de busca: `src/search.py` (operações), `src/editais_search.py` (busca de editais) -- ambos só embeddings, sem IA generativa
- Elegibilidade ("Minha Empresa"): `src/elegibilidade.py`, rotas `/api/elegibilidade*` em `webapp/main.py`, `webapp/static/js/elegibilidade.js`
- Banco: `src/db.py` (conexão + schema Postgres), `src/db_compat.py` (compat `?`→`%s`), `src/incremental.py` (hash/coerção de tipos)
- API + frontend: `webapp/main.py`, `webapp/static/` (HTML/CSS/JS)
- Deploy: `api/index.py` (entrypoint Vercel), `vercel.json`, `requirements-api.txt`, ver `DEPLOY.md`
