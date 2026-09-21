> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

## Motor de busca (aba "Busca")

**Por padrão, 100% sem IA/sem chamada a modelo nenhum** — full-text search do Postgres
(`tsvector`/`unaccent`/`pg_trgm`), ver `src/search_fts.py`. Toda a "inteligência" (sinônimos,
taxonomia, supressão de boilerplate) é PRÉ-CALCULADA no momento do enriquecimento (ver
`unify.py::_search_document`/`_search_taxonomia_termos`, `src/search_taxonomy.py`) e gravada em
`operations.search_document`/`search_taxonomia_termos`/`search_vector` — a busca em si só
consulta o que já está pronto.

Ranking em 6 tiers (do mais forte pro mais fraco, ver `PRIORIDADE_MOTIVO` em `search_fts.py`):
1. CNPJ ou prefixo do nome do cliente (só considera fragmento numérico como CNPJ se tiver
   ≥8 dígitos — sem essa guarda, uma query como "xyzabc123nada" batia como "match exato" de
   qualquer CNPJ que começasse com "123", bug real já corrigido).
2. Setor/subsetor/segmento (CNAE).
3. Produto/instrumento/indexador.
4. Correspondência de FRASE (`phraseto_tsquery`, preserva ordem/adjacência das palavras) —
   evita que "parque de diversao" traga "parque eolico" no topo só por repetir a palavra
   "parque" solta.
5. Correspondência por QUALQUER palavra (OR, `websearch_to_tsquery`) — inclui os sinônimos
   pré-calculados.
6. Trigrama (`pg_trgm`/`similarity()`) — só roda se as tiers 1-5 voltarem com poucos
   resultados (`MINIMO_ANTES_DE_TRIGRAMA`), já que trigrama (nesta forma, comparando
   `unaccent(lower(cliente))`) também varre a tabela inteira (ver nota de performance
   abaixo — mesma limitação de índice que as tiers 1-3).

UF (sigla de 2 letras) é tratada como FILTRO estruturado (`AND uf = ?`), não como termo de
busca — senão o volume de operações de qualquer UF grande dominava o ranking por cima de um
termo raro e específico. Um pequeno conjunto de palavras genéricas do domínio
(`PALAVRAS_GENERICAS_QUERY`, ex: "empresa") é excluído do OR de texto livre pelo mesmo motivo.

**Filtros estruturados da Busca** (`buscar_texto()`, sempre `AND`, nunca dentro do ranking):
`agencia`, `valor_minimo`, `regiao`, `produto`, `porte` (ver `PORTE_NORMALIZADO_SQL` acima) e,
desde 2026-09-15, `setor` e `uf` explícito. `uf` (dropdown, filtro explícito) tem prioridade
sobre uma UF digitada solta no texto da busca (`uf_detectada`) se as duas vierem preenchidas —
`uf_final = uf or uf_detectada`. `setor` combina `setor_bndes` (4 categorias amplas) e
`subsetor_bndes` (19, mais granulares) **NA MESMA lista de opções** no frontend (pedido
explícito do usuário — ele quer o filtro geral e o granular juntos, não dois selects
separados), com `<optgroup>` só para separação visual; o backend testa contra as DUAS colunas
com um `OR` simples (`setor_bndes = ? OR subsetor_bndes = ?`), então não importa se o valor
escolhido é setor ou subsetor — funciona sem o front precisar saber qual é qual. Os dois
vocabulários são disjuntos, exceto "AGROPECUÁRIA" (setor E o único subsetor daquele setor —
mesma string, mas describem exatamente o MESMO conjunto de operações ali, então o `OR` não gera
ambiguidade real). **Não existe uma categoria "inovação"** — pedido inicial do usuário citava
esse termo como exemplo, mas não é um valor real de `setor_bndes`/`subsetor_bndes` (é um
conceito da FINEP, não do BNDES); o filtro `agencia=FINEP` (já existente) é o proxy mais
próximo dessa intenção.

**Performance (revisado 2026-09-09)**: `operations` tem índices reais disponíveis
(`idx_operations_search_vector` GIN em `search_vector`, `idx_operations_cliente_trgm`/
`idx_operations_segmento_trgm` GIN trigram, além de btree em `cnpj`/`setor_bndes`/`uf`/etc
— ver `pg_indexes`), mas a query original de `buscar_texto()` colocava TODAS as 6 tiers
dentro de um único `CASE` avaliado incondicionalmente sobre a tabela inteira (~58 mil
linhas) e só filtrava (`WHERE prioridade IS NOT NULL`) depois — isso força
`Parallel Seq Scan` mesmo com os índices certos disponíveis (confirmado com
`EXPLAIN ANALYZE` ao vivo: toda busca, de qualquer tipo, levava ~5-17s). Corrigido
parcialmente: as tiers 4/5 (full-text, `search_vector @@ tsquery`) viraram queries
próprias com o `@@` direto no `WHERE` (sem CASE por cima) — isso deixa o Postgres
escolher `Bitmap Index Scan` no GIN, medido em ~150-300ms quando essas tiers dominam
(contra ~4-8s antes). As tiers 1-3 (prefixo de CNPJ/cliente, keyword em
setor/subsetor/segmento/produto/instrumento/indexador via `LIKE` sobre
`unaccent(lower(campo))`) **continuam fazendo seq scan** — não há índice funcional
casando com essa expressão exata (os índices trigram existentes são sobre a coluna
RAW, sem `unaccent`/`lower`), e como tiers 1-3 rodam em TODA busca (correção precisa
ser feita antes de tiers 4/5 poderem ser avaliadas, pra nunca reclassificar uma
operação pra uma tier mais fraca), esse seq scan (~3-4s, majoritariamente o custo dos
9 `unaccent()`+`regexp_replace()`+`lower()` por linha, não do ranking em si — testado
isolando `ts_rank_cd` da query, o custo não muda muito) virou o piso de latência de
QUALQUER busca. Ganho líquido medido (`orig` vs `novo`, alternando lado a lado contra
produção pra descontar o ruído de rede do Aiven free tier): ~35-45% mais rápido em
média, sem nenhuma mudança de resultado/ranking (mesma bateria de queries de
regressão validada antes e depois). **Se precisar reduzir mais**: o próximo passo
exigiria um índice funcional novo (ex: `CREATE INDEX ... ON operations USING gin
(unaccent(lower(cliente)) gin_trgm_ops)`, idem pra setor/subsetor/segmento/produto) —
é uma migração de schema na Aiven de produção (mesmo banco usado por todas as sessões
concorrentes), então não fazer sem confirmar com o usuário antes, mesmo que
tecnicamente seguro (`CREATE INDEX CONCURRENTLY` evita lock de escrita).

`src/search_taxonomy.py` guarda os sinônimos: exaustivo para Setor (4) e Subsetor (19),
CURADO (não exaustivo) para Segmento (~1291 valores distintos de CNAE — cobertura vem
crescendo conforme o uso real mostra lacunas, ver `scripts/backfill_search_taxonomia.py` para
como reaplicar em massa depois de expandir o dicionário). Lembrete de stemming: o dicionário
`portuguese` do Postgres NÃO unifica de forma confiável singular/plural em palavras terminadas
em `-al` (ex: "hospital"/"hospitalar" viram o mesmo radical, mas "hospitais" vira outro) — por
isso os sinônimos incluem singular E plural quando relevante.

**Motor por IA (embeddings) continua existindo, só desligado por padrão** — flag
`MOTOR_BUSCA_IA` (env var, `webapp/main.py`). Se `MOTOR_BUSCA_IA=1`: religa as rotas
`/api/busca/preparar*` (cálculo de vetor no NAVEGADOR via transformers.js,
`embeddings-client.js`) e o fluxo antigo em `src/search.py`/`src/embeddings.py`. Decisão de
produto explícita do usuário: manter essa estrutura "guardada e flexível" pra religar no
futuro, não removida. Se for reativar de verdade um dia, reconferir se `data/embeddings.npz`
está atualizado (ver pipeline acima).
