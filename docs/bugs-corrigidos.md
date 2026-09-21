> Detalhe/histórico extraído do CLAUDE.md em 2026-09-21 (redução de tokens por sessão). Ler só quando a tarefa tocar este assunto especificamente.

## Bugs reais já corrigidos nesta base (armadilhas a não repetir)

- **`_extrair_divisoes` (`src/sector_taxonomy.py`)**: fatiava código de CNAE de forma errada
  para faixas com subclasse longa (ex: "H4911, H4912401 e H4912402"), produzindo um intervalo
  de divisões espúrio e corrompendo o mapeamento setor/subsetor de várias divisões no meio (ex:
  divisão 26 virava "Transporte Ferroviário" em vez de "Indústria"). O CÓDIGO já foi corrigido
  há tempo, mas os DADOS já gravados em `cnpj_cnae`/`operations` continuaram errados até
  2026-09-04 (5.644 operações da FINEP mal-classificadas) — corrigido com um backfill direto
  (recalcular `setor_bndes_mapeado`/`subsetor_bndes_mapeado` a partir do `cnae_divisao` já
  armazenado, sem precisar rebaixar nada da Receita Federal). **Lição**: corrigir um bug de
  cálculo no código NÃO corrige dados já gravados — sempre considerar se um backfill é
  necessário, e desconfiar de qualquer categoria/setor que pareça anormalmente
  super-representada nos dados (sinal de um bug de classificação, não de realidade).
- **Falso-positivo de CNPJ na busca** (`src/search_fts.py`): fragmento numérico de qualquer
  tamanho disparava o tier de "correspondência exata" de CNPJ — corrigido exigindo ≥8 dígitos.
- **`websearch_to_tsquery` combina palavras com AND por padrão** — ruim para busca livre em
  linguagem natural (query de 5-6 palavras nunca bateria por completo em documento nenhum);
  junta as palavras com `" or "` manualmente antes de passar pro Postgres.
- **`_periodo_anterior` (`webapp/main.py`)**: limitava incondicionalmente o período "atual" a
  no máximo 365 dias antes de calcular o período de comparação — um filtro de 2 anos escolhido
  pelo usuário virava, por baixo dos panos, uma comparação só dos últimos 12 meses, sem
  indicação nenhuma na UI de que o período exibido não era o filtro de verdade. Corrigido: o
  teto de 365 dias só vale quando NENHUM filtro é passado (padrão "toda a base"); com filtro
  explícito, o período anterior tem sempre o MESMO TAMANHO EXATO do selecionado.
- **Variante ortográfica "óptica"/"ótica" na busca** (`src/search_fts.py`,
  `_normaliza_ortografia_sql()`; mesma normalização espelhada em
  `unify.py::_atualizar_search_vector()`): as duas grafias (antiga, com P — "fibra
  óptica" — e atual, sem P — "fibra ótica") são o MESMO conceito na fala real, mas o
  stemmer do Postgres as trata como palavras diferentes. Corrigido com
  `regexp_replace(..., 'optic', 'otic', 'gi')` aplicado nos DOIS lados (query e
  indexação) depois de `unaccent()`. Backfill já rodado contra toda a base (ver
  `scripts/backfill_search_taxonomia.py`) — confirmado que "otica" e "óptica" agora
  retornam exatamente o mesmo resultado/ordem, a normalização em si funciona.
  **RESOLVIDO (2026-09-09)** — causa raiz era outra, não mismatch de grafia: mesmo
  com os dois lados já normalizando igual, buscar "cabos de fibra otica" ainda
  rankeava "Ótica Diniz Ltda" (loja de óculos) ACIMA de empresas reais de fibra
  óptica (ex: "ETECC FIBRA ÓPTICA NETWORK LTDA"), confirmado ao vivo contra
  produção. Causa raiz de verdade: não é peso entre campos (A/B/C/D) — é que
  `ts_rank_cd` pesa mais o CAMPO onde bateu do que quantas palavras da query
  realmente batem, então um match de 1 palavra num campo caro (nome/segmento)
  supera um match de 3-4 palavras num campo mais barato (`descricao_projeto`).
  **Histórico da correção (duas sessões em paralelo, mesmo dia)**: um primeiro
  commit (`6c3eee7`) resolveu o ranking com uma "cobertura" (quantas palavras
  DISTINTAS da query aparecem no documento, uma a uma) calculada como subquery
  correlacionada (`unnest`+`@@`) **dentro do mesmo `CASE`** que decide a
  `prioridade` — funcionalmente correto, mas esse `CASE` já tinha um problema de
  performance PREEXISTENTE e separado (`search_vector @@ tsquery` das tiers 4/5
  embutido no CASE nunca usava o índice GIN `idx_operations_search_vector`,
  forçando `Parallel Seq Scan` em toda busca, ~5-8s). Como uma reestruturação
  pra corrigir os dois problemas de uma vez já estava em andamento em paralelo,
  esse primeiro commit foi revertido (`aacd5e1`) pra não duplicar o fix de
  ranking em cima da estrutura antiga (o filtro `porte`, do mesmo commit
  original, foi mantido). **Resolução final**: tiers 4/5 viraram queries
  próprias com `search_vector @@ tsquery` direto no `WHERE` (usa o índice GIN,
  ver "Performance" no fim da seção "Motor de busca" acima) e a cobertura passou
  a ser calculada numa query SEPARADA, só nos poucos candidatos que a tier 5 (já
  indexada) trouxe (`WHERE id = ANY(?)`, índice de PK) — nunca mais embutida
  numa CASE que roda linha a linha na tabela inteira. Não mexeu nos pesos
  `setweight()` por campo (aqueles resolveram um bug real diferente, ver entrada
  de `_periodo_anterior`/hospital-vs-SP acima, e não deviam ser tocados de novo
  sem motivo novo). **Lição**: qualquer critério de ranking novo neste motor de
  busca deve ser calculado só sobre candidatos JÁ FILTRADOS por uma query
  anterior, nunca dentro de uma CASE/subquery correlacionada que roda sobre a
  tabela inteira — confirmado medindo: uma variante equivalente (cobertura via
  `plainto_tsquery` por palavra, também dentro do CASE) chegou a ser testada e
  mediu uma query de 8 palavras subindo de ~9s pra **55s** só por causa disso,
  contra o Aiven — meça antes de assumir que "mais uma condição" é barato.
- **"grupo"/"grupos" faltando em `PALAVRAS_GENERICAS_QUERY`** (`src/search_fts.py`):
  mesmo problema que "empresa" (ver `_periodo_anterior`/hospital-vs-SP acima), só
  descoberto depois — "grupo" é uma palavra de estrutura societária tão comum quanto
  "empresa" (qualquer "Grupo X" da base), então diluía o OR de texto livre (tier 5) do
  mesmo jeito. Confirmado ao vivo (2026-09-11): buscar "Grupo Belterra" achava a
  empresa real (`AGROFLORESTAL BELTERRA AMAZONIA SPE SA`) só na posição 37/200, e
  "grupo mombak" (`MOMBAK ANGICO-BRANCO FLORESTAL S.A.`) na posição 23/200 — nos dois
  casos, buscar só pelo nome próprio (sem "grupo") já achava a empresa em 1º lugar,
  confirmando que não era dado faltando, só a palavra genérica competindo no ranking.
  Corrigido adicionando `"grupo"/"grupos"` ao mesmo set.
- **`.status-pill` (topbar) quebrando pra uma segunda linha solta** (`style.css`): em
  larguras intermediárias de desktop (~900-1300px), o pill de status ia sozinho pra uma
  segunda linha desalinhada. Corrigido: a partir de 900px, `.topbar` vira
  `flex-wrap:nowrap` e brand/pill ganham `flex-shrink:0` — quem absorve a falta de
  espaço é `.tabs` (já rola horizontal). Abaixo de 900px, mantido o empilhamento
  original (mobile/tablet já funcionava bem assim). **Efeito colateral dessa
  correção, resolvido depois (2026-09-10)**: `.tabs` rolando horizontal nessa
  mesma faixa (~950-1250px) mostrava uma barra de scroll nativa feia. Reduzida
  a fonte da marca (17px→15px) e o padding dos botões de aba (16px→12px) pra
  abrir espaço de verdade (elimina o scroll a partir de ~1250px, antes só
  ~1280px); onde ainda não cabe, a barra nativa fica escondida
  (`scrollbar-width:none`+`::-webkit-scrollbar{display:none}`, rolagem
  continua funcionando por touch/wheel/arraste) e um novo wrapper
  `.tabs-wrap` ganha um degrade sutil na borda (ligado/desligado por JS,
  `_atualizarSombraAbas()` em `common.js`) como aviso visual de que há mais
  abas fora da tela — sem isso, a existência de "Editais"/"Linhas
  Incentivadas" nessa faixa de largura ficaria descobrível só por acidente.
