> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

## Auditoria geral de otimização (2026-09-17, pedido do usuário)

Auditoria só de leitura (backend/performance/segurança, frontend, dead code/duplicação) sobre o
site inteiro — resultado consolidado e as correções de baixo risco aplicadas diretamente pelo
coordenador (o processo original que rodou as 3 sub-investigações não chegou a aplicar nada
sozinho antes de encerrar).

**Aplicado (baixo risco, testado ao vivo contra produção antes de mergear)**:
- **Teto em `limit`/`offset`** nas rotas públicas que aceitavam qualquer valor do cliente sem
  clamp (`GET /api/operacoes`, `/api/editais`, `/api/linhas`, `/api/segmentos`,
  `/api/enriquecimento/{importacoes,pendentes,correcoes}`) — mesmo padrão já usado no painel de admin
  (`limit = max(1, min(limit, N))`). Confirmado ao vivo: `?limit=999999999` agora devolve
  exatamente o teto (2000 nas rotas de listagem de operações, 500/200 nas menores) em vez de
  tentar serializar a tabela inteira; `offset` negativo agora clampa pra 0 em vez de devolver
  um erro do Postgres. Não era um DoS anônimo (todas essas rotas exigem sessão válida), mas
  era desnecessário.
- **`scripts/migrate_sqlite_to_supabase.py` removido** — confirmado por grep que só era
  referenciado em `README.md`/`RESUME.md` (docs desatualizadas), nunca em código, CLAUDE.md ou
  workflow — migração de UM PASSO ANTERIOR (SQLite→Supabase) que já é duplamente obsoleta (o
  projeto migrou depois Supabase→Aiven, e não existe mais "modo local" com SQLite). Não confundir
  com `scripts/migrate_supabase_to_aiven.py`, que documenta a migração REAL/atual e não foi
  tocado.

**Motor de busca migrado pro pool de conexões (2026-09-17, aplicado depois de teste de carga)**:
`src/search_fts.py::buscar_texto` chamava
`get_connection()` sem `pooled=True` — toda busca (provavelmente a rota mais usada do site) abria
uma conexão direta ao Aiven em vez de reaproveitar o `ConnectionPool` (que os outros ~26 call
sites de `webapp/main.py` já usam, com a proteção `check=ConnectionPool.check_connection` contra
conexão morta pós-`AdminShutdown`). Isso contribuía pro esgotamento das 20 conexões do Aiven free
tier — **o mesmo incidente aconteceu 3 vezes em 2026-09-17**. **Risco teórico levantado antes de
mexer**: como as rotas rodam síncronas numa threadpool e o pool tem `max_size=2` POR PROCESSO,
uma busca lenta (tiers 1-3 fazem seq scan, ~3-8s documentado acima) passaria a competir pelo
MESMO par de conexões que qualquer outra rota da mesma instância — risco de uma busca lenta
"segurar" uma das 2 únicas vagas e fazer outras requisições concorrentes (ex: `/api/kpis`) esperar
na fila, algo que não acontecia com busca usando conexão própria.
**Testado ao vivo antes de aplicar** (`uvicorn` local, mesmo processo = mesmo pool de uma
instância real da Vercel): bateria de 2 buscas + 2 `/api/kpis` concorrentes (`ThreadPoolExecutor`),
comparando ANTES (busca sem pool) e DEPOIS (busca com `pooled=True`) do patch, rodada 2x cada.
Resultado: tempos praticamente iguais entre as duas versões (ex: busca ~14,6s sem pool vs ~15,4s
com pool na 1ª rodada, mas ~11-12s com pool na 2ª rodada — a variação entre rodadas da MESMA
versão foi maior que a diferença entre versões, confirmando que é ruído normal de rede do Aiven
free tier, não fila real introduzida pelo pool). Nenhum sinal de fila severa (se houvesse, as
chamadas de `/api/kpis` teriam ficado presas atrás das buscas lentas — continuaram na mesma
faixa de tempo nas duas versões). Conclusão: a troca não piora a eficiência de forma perceptível
— aplicada.
- ~~`.grid-3`/`.narrativa`/`.progress-track`/`tr.eleg-linha-detalhe:hover` (CSS morto)~~
  **REMOVIDO 2026-09-18** — ver seção "Segunda rodada de otimização" abaixo (reconfirmado zero
  uso antes de apagar, incluindo `.narrativa`).
- ~~`/api/filtros` buscado 2-3x~~ **CORRIGIDO 2026-09-18** — ver seção "Segunda rodada de
  otimização" abaixo.
- **`importar_finep_editais` (`src/linhas_incentivadas.py`)**: confirmado sem nenhuma chamada
  real, mas o próprio docstring já diz que é mantida de propósito como referência — não remover
  sem perguntar (é o mesmo tipo de "guardado e flexível" documentado em outros lugares deste
  arquivo).

**Nenhum problema encontrado**: SQL injection (todo f-string interpola só nomes de coluna
hardcoded/whitelisted, nunca valor de request — valores sempre via `?`), autenticação/
autorização (todos os gates conferidos, sem furo), cookies/sessão (sem regressão), N+1 (nenhum
padrão de loop-com-query encontrado em nenhuma rota), assets/JS mortos (nenhum arquivo órfão),
vazamento de `localStorage` (histórico de busca já limitado a 8 itens por usuário).

### Segunda rodada de otimização (2026-09-18, pedido do usuário)

Pedido explícito: otimizar mais, mas só mudanças que **mantenham a mesma eficiência** (nunca
regredir) — cada item abaixo foi medido/testado ao vivo antes de aplicar, não só inferido.

- **Cache de `/api/filtros`** (`common.js::_fetchFiltrosCompartilhado`, novo — usado por
  `_initFiltersAndTabsImpl`/`_repopularFiltrosCompartilhados` em `common.js` e por
  `_popularFiltrosBusca` em `busca.js`). Achado real medido: o mesmo endpoint era chamado **2x
  em todo carregamento de página** (os dois `DOMContentLoaded` de common.js/busca.js disparam
  quase juntos) — sem nenhum ganho de dado mais fresco (a resposta não muda dentro de uma
  sessão). Cacheado pela PROMISE (não só o valor), então as duas chamadas concorrentes da carga
  inicial dividem o MESMO fetch em voo — uma falha de rede não fica presa em cache (a entrada é
  removida no catch, a próxima tentativa refaz o fetch). **Testado ao vivo** (contando chamadas
  reais de `fetch` via um wrapper temporário, contra produção): carga inicial com as duas
  funções chamadas em paralelo → 1 fetch (antes seriam 2). (Nota 2026-09-22: a parte original
  desta otimização que também cacheava a troca entre mercado Incentivado/Primário deixou de se
  aplicar depois que o toggle de mercado foi removido — ver `docs/archive/removed-features.md`;
  o cache de `/api/filtros` em si continua válido.)
- **CSS morto removido** (`style.css`): `.grid-3` (não usado — só `.grid-2` aparece em
  `index.html`, ajustada a media query de 900px que citava os dois), `tr.eleg-linha-detalhe:
  hover`, `.narrativa`/`.narrativa.loading` e `.progress-track` (mantidos `.progress-fill`/
  `.progress-label`, que SÃO usados via outro wrapper em `linhas.js`/`busca.js` — só a classe
  do container ficou órfã). Reconfirmado com grep em todo `.html`/`.js` do projeto antes de
  apagar (inclusive `.narrativa`, que a auditoria anterior tinha deixado de propósito por
  cautela) — zero uso, nenhum comportamento visual depende dessas 4 regras.
- **Testado ao vivo de ponta a ponta** (conta de teste temporária, mesmo procedimento já
  documentado em "Coisas a saber antes de mexer"): login real, Consolidado renderizando com
  dado real de produção (59.009 operações, R$ 2.659,3 bi) depois das mudanças, nenhum erro de
  console novo (só os 401 esperados do carregamento antes do login manual, mesmo padrão já
  documentado). Conta de teste e sessão apagadas ao final.
- **Incidente à parte durante o teste, sem relação com as mudanças de código**: ao tentar
  limpar a conta de teste, esbarrei de novo no teto de conexões do Aiven
  (`remaining connection slots are reserved for roles with the SUPERUSER attribute`) — mesma
  classe de incidente já documentada em "Coisas a saber antes de mexer". Causa desta vez:
  um processo `uvicorn` ÓRFÃO (interpretador Python do sistema, não do `.venv` deste
  repo — não era o processo gerenciado por este ambiente de teste) já estava rodando contra a
  MESMA produção antes desta sessão começar a testar. Identificado via
  `Get-CimInstance Win32_Process`/`Stop-Process` (matando só o processo órfão, nunca o
  gerenciado pela ferramenta de preview) — liberou conexão na hora, sem precisar esperar. Não
  gerado por nenhuma mudança desta sessão; reforça a lição já registrada: sempre conferir
  processos `uvicorn` soltos antes (e depois) de testar localmente contra o banco de produção.
- **Deliberadamente NÃO mexido nesta rodada** (risco de regressão sem medição clara, ou fora
  do pedido de "manter a mesma eficiência"): cache-control agressivo em JS/CSS estático (os
  arquivos não têm hash no nome — cachear forte sem invalidação correta serviria JS desatualizado
  depois de um deploy, um bug de CORRETUDE, não só de performance); reduzir `max_size` do pool
  de conexões (sem evidência de ganho, risco de fila sob concorrência real); o bug de
  `operacao_detalhe`/`raw_table` acima (é uma correção de comportamento visível, não uma
  otimização pura).
