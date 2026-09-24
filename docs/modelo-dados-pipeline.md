> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

## Modelo de dados (tabelas principais, ver schema completo em `src/db.py`)

- **`bndes_raw`**, **`finep_credito_direto_raw`**, **`finep_credito_descentralizado_raw`**:
  staging tables, uma linha por operação, quase cru da planilha/fonte oficial.
- **`operations`**: tabela UNIFICADA (schema comum BNDES+FINEP) que todo o dashboard/busca
  consulta. Campos-chave: `agencia` (BNDES/FINEP), `cliente`, `cnpj`, `setor_bndes`/
  `subsetor_bndes`/`segmento` (taxonomia de 3 níveis — ver seção "Setor/Subsetor/Segmento"
  abaixo), `valor_contratado`, `data_contratacao`, `uf`, `municipio`, `setor_origem` (`nativo` =
  BNDES, já vem com setor da própria planilha; `enriquecido` = FINEP, setor resolvido via
  CNPJ→CNAE; `pendente` = FINEP cujo CNPJ ainda não foi resolvido; `corrigido_manual` = sofreu
  correção manual, prevalece sobre reenriquecimento), `search_document`/`search_taxonomia_termos`/
  `search_vector` (motor de busca sem IA, ver seção própria).
- **`cnpj_cnae`**: cache CNPJ → CNAE/razão social/natureza jurídica/porte/capital social,
  alimentado por `src/enrich_cnae.py` a partir dos Dados Abertos de CNPJ da Receita Federal.
  `setor_bndes_mapeado`/`subsetor_bndes_mapeado` vêm de `cnae_divisao` + `build_divisao_map()`
  (ver `src/sector_taxonomy.py`) — **CUIDADO**: um bug real já existiu aqui (ver "Bugs
  reais já corrigidos" abaixo), sempre desconfiar se uma categoria parecer super-representada.
- **`de_para_cnae`**: crosswalk oficial BNDES (divisão CNAE → Setor/Subsetor BNDES). Tem uma
  ambiguidade REAL e intencional: a mesma divisão CNAE pode aparecer tanto em uma faixa
  "Comércio e Serviços" quanto em uma faixa mais específica (Indústria/Infraestrutura/
  Agropecuária) — não é erro de digitação, é assim que a metodologia do BNDES realmente
  funciona (depende de mais contexto que só CNAE). `build_divisao_map()` resolve por
  "última linha da tabela vence" — se um dia isso incomodar, é uma decisão de produto a tomar,
  não um bug a caçar às cegas.
  **2026-09-23 — setor padronizado por CNAE (decisão de produto, opção A):** `operations`
  ganhou `setor_cnae`/`subsetor_cnae`/`setor_cnae_origem`, calculados pelo MESMO caminho
  CNAE→`de_para_cnae` para BNDES e FINEP (`sector_taxonomy.build_regras_cnae`/
  `classificar_cnae`, gravado por `unify.recalcular_setor_cnae` a cada refresh — lotes de 5000
  por faixa de id via tabela temporária, só grava o que mudou). CNAE = `cnpj_cnae.cnae_codigo`
  (BNDES sem cache cai em `bndes_raw.subsetor_cnae_codigo`). Desempate: (1) regra de código mais
  específico vence (subclasse > grupo > divisão, ex. D351 > D35); (2) mesma especificidade com
  setores diferentes → vence o setor que o BNDES nativo usa em ≥80% (n≥5) das operações daquela
  regra; (3) senão `AMBÍGUO` (hoje só divisões 39 e 53, 0 operações). `setor_bndes` continua
  existindo (nativo BNDES / legado FINEP). Dashboard, filtro de setor e Busca usam `setor_cnae`;
  `classificacao=nativo` (só com `agencia=BNDES`) volta para `setor_bndes` (`main.py::_cols_setor`).
  Correção manual de `setor_bndes`/`subsetor_bndes` é espelhada em `setor_cnae`
  (`setor_cnae_origem='corrigido_manual'`). Backfill: `scripts/backfill_setor_cnae_produto_finep.py`.
  552 FINEP direto seguem sem setor: não têm CNPJ na fonte (não há o que enriquecer).
- **Produto FINEP (2026-09-23):** descentralizado → `"Inovacred"` (decisão do usuário, a fonte
  não traz o campo); direto → programa da coluna `demanda` com grafia unificada
  (`unify.produto_finep_direto`). Rota `/api/tendencias/operadores` (agentes do Inovacred) e
  filtro `agente` (só `agencia=FINEP`) em `_filters_clause`.
- **BNB (2026-09-24, publicado com aprovação do usuário):** `bnb_raw` ← `src/bnb.py` (Power
  BI público "Consulta de Operações de Crédito", endpoint `querydata` com a chave pública do
  embed). Só PJ (CNPJ com DV válido) e **só valor contratado > R$ 1.000.000,00** (decisão do
  usuário; filtro na própria query, `ComparisonKind 1`, + conferência no cliente) — 9.644
  contratos, 6.587 CNPJs, R$ 107,1 bi (2016-01..2026-06). Reconciliação por ano × UF × fundo em
  `bnb_reconciliacao` (0 diferenças, mesmo recorte dos dois lados). `mascarar_cpf` remove CPF de
  nome de MEI (LGPD) — também aplicado em `enrich_cnae._limpar_nome`. `unify._build_bnb_ops`:
  `agencia='BNB'`, `produto` = fundo da fonte (FNE, FNE-2, BNDES/FINAME, FEDAF),
  `instrumento_financeiro` = "Programa cód. N" (a fonte não traz nome), taxa/indexador/prazos
  como publicados, UF do contrato, município/porte/natureza/setor via `cnpj_cnae` (mesma regra
  da FINEP, `setor_origem` enriquecido/pendente), `instrumento`/descrição/desembolsado NULL.
  Detalhe do modal: `detalhe.SECOES_BNB`. `refresh.py` chama `bnb.extrair` best-effort antes
  do unify (janelas já reconciliadas contra o mesmo refresh do dataset são puladas). Rodapé do
  site cita a fonte (data via `/api/status.bnb_fonte_atualizada_em`). Linhas BNB alteradas
  depois na fonte NÃO são reatualizadas em `operations` (unify só insere raw novo).
- **`editais_raw`**: chamadas públicas (editais) abertas da FINEP — dado próprio, upsert
  (preserva id da própria FINEP), NÃO faz parte do rebuild de `operations`.
- **`linhas_incentivadas`**: catálogo de PRODUTOS de crédito permanentes (não transações) —
  ver seção própria abaixo.
- **`operations_correcoes_manuais`**: correções manuais pontuais em campos de `operations`,
  reaplicadas automaticamente a cada refresh (ver `unify.py::_reaplicar_correcoes_manuais`).
- **`refresh_log`**: histórico de cada rodada do pipeline semanal (`src/refresh.py`).

## Pipeline de dados (operações BNDES/FINEP)

`src/refresh.py` orquestra tudo, chamado semanalmente pelo GitHub Actions
(`.github/workflows/refresh-operacoes.yml`, segunda-feira 06:00 UTC, timeout 180min):

1. `src/download.py` — baixa as planilhas oficiais mais recentes (BNDES + FINEP).
2. `src/parse_bndes.py`/`src/parse_finep.py` — normalizam pras staging tables (`*_raw`).
3. `src/unify.py::build_operations()` — reconstrói `operations`: junta BNDES (setor nativo) +
   FINEP (setor via `cnpj_cnae`, se já resolvido, senão `setor_origem='pendente'`); recalcula
   `search_document`/`search_taxonomia_termos`/`search_vector` (busca) e `embedding_text`
   (embeddings, só usado se o motor de IA opcional for religado); reaplica correções manuais
   (`operations_correcoes_manuais`); tenta reclassificar pendentes cujo CNPJ tenha sido
   resolvido desde o último refresh (`_reclassificar_pendentes`).
4. Sempre recalcula embeddings (`data/embeddings.npz`) mesmo com o motor de busca por IA
   desligado — mantém o artefato consistente com o banco caso alguém religue `MOTOR_BUSCA_IA`.

`src/enrich_cnae.py` é um job PESADO e SEPARADO (não roda dentro do `refresh.py` semanal) —
mensal (`.github/workflows/enrich-cnae.yml`), baixa ~5-6GB da Receita Federal (Dados Abertos de
CNPJ via WebDAV), resolve CNAE/razão social/porte/capital social só dos CNPJs que aparecem em
`bndes_raw`/`finep_*_raw` (nunca a base nacional inteira). Rode manualmente com
`python src/enrich_cnae.py` se precisar fechar um gap de CNPJs não resolvidos fora do calendário
mensal (idempotente, só processa quem ainda não está em `cnpj_cnae`).

`src/refresh_editais.py` (diário, `refresh-editais.yml` 08:00 UTC) orquestra
`finep_editais.py` (upsert de `editais_raw`) + `editais_documentos.py` + `editais_embeddings.py`.
