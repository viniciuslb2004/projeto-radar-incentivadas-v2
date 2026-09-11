"""Motor de busca SEM IA (full-text search Postgres: tsvector + unaccent + pg_trgm).

Substitui, no caminho padrao de producao, o motor de embeddings (ver search.py,
embeddings.py) -- que continua intacto e religavel (ver MOTOR_BUSCA_IA em
webapp/main.py), so nao roda por padrao. Toda a "inteligencia" (sinonimos, taxonomia)
foi pre-calculada no enriquecimento (ver src/search_taxonomy.py e
unify.py::_search_document()) e gravada em `operations.search_document`/`search_vector`
-- esta busca so consulta o que ja esta pronto, sem nenhuma chamada a modelo.

Prioridade de ranking (da mais forte para a mais fraca -- ver PRIORIDADE_MOTIVO):
1. Correspondencia exata/prefixo com CNPJ ou nome do cliente.
2. Correspondencia com setor/subsetor/segmento (CNAE).
3. Correspondencia com produto/instrumento/indexador.
4. Correspondencia de FRASE (ordem das palavras preservada) no texto completo.
5. Correspondencia por QUALQUER palavra (OR) no texto completo, inclui sinonimos/taxonomia.
6. Correspondencia aproximada por trigrama (tolera erro de digitacao / nome parecido).
"""
import re

from db import get_connection

_COLS_OPERACAO = [
    "id", "agencia", "instrumento", "cliente", "cnpj", "uf", "setor_bndes", "subsetor_bndes", "segmento",
    "valor_contratado", "data_contratacao", "descricao_projeto",
]

PRIORIDADE_MOTIVO = {
    1: "Correspondência exata com CNPJ ou nome da empresa",
    2: "Correspondência com setor, subsetor ou segmento (CNAE)",
    3: "Correspondência com produto, instrumento ou indexador",
    4: "Correspondência de frase no texto completo (descrição, sinônimos e taxonomia)",
    5: "Correspondência por palavra no texto completo (descrição, sinônimos e taxonomia)",
    6: "Correspondência aproximada (nome parecido, possível erro de digitação)",
}

LIMIAR_SIMILARIDADE_TRGM = 0.25

# Palavras genericas DESTE dominio -- nao sao stopword em portugues "de verdade" (o
# dicionario 'portuguese' do Postgres ja remove preposicoes/artigos), mas em uma base
# onde TODO registro e uma operacao de credito de uma empresa, a palavra "empresa"
# nao discrimina nada (aparece por acaso, como substring literal, no nome legal de
# muitas empresas -- ex: "IGUATEMI EMPRESA DE SHOPPING CENTERS", "EMPRESA ELETRICA
# BRAGANTINA"). Confirmado empiricamente: buscar "empresa de hospitais em SP" media o
# match generico de "empresa" no NOME (peso A, o mais alto) por cima do match
# especifico de "hospitais" no setor/segmento (peso B) -- essas ficam de fora do
# OR-tsquery de texto livre (tier 4), mas continuam valendo normalmente nos tiers 1-3
# (comparam a FRASE completa digitada, nao palavra a palavra).
# "grupo"/"grupos": mesmo problema, confirmado ao vivo em 2026-09-11 -- "Grupo
# Belterra" (posicao 37/200) e "grupo mombak" (posicao 23/200) rankeavam mal porque
# "grupo" (termo de estrutura societaria comum, ex: "GRUPO CULTURAL BAGUNCACO",
# "Grupo Salta Educação S.A.") diluia o OR de texto livre do mesmo jeito que
# "empresa" ja fazia -- as duas empresas reais (AGROFLORESTAL BELTERRA AMAZONIA SPE
# SA, MOMBAK ANGICO-BRANCO FLORESTAL S.A.) ja rankeavam em 1o lugar buscando so pelo
# nome proprio (Belterra/MOMBAK...), confirmando que o problema era so a palavra
# generica, nao dado faltando.
PALAVRAS_GENERICAS_QUERY = {"empresa", "empresas", "companhia", "companhias", "grupo", "grupos"}

# UF (2 letras) e um FILTRO estruturado, nao um termo de conteudo -- deixa-lo entrar
# no OR-tsquery de texto livre (tier 4) e um problema pior do que "empresa": o codigo
# aparece no campo `uf` de MILHARES de operacoes (sigla curta, sem stem, sem sinonimo
# nenhum competindo por peso), entao qualquer busca combinando um termo raro (ex:
# "hospitais", so numa operacao) com uma UF (ex: "SP", em milhares) faz o volume de
# matches de UF dominar o ranking, mesmo com peso mais baixo. Confirmado
# empiricamente: "empresa de hospitais em SP" so passou a achar o unico hospital real
# da base depois de tratar a UF como filtro (AND uf = ?), tirando-a do ts_rank.
# Normalizacao de porte EM TEMPO DE CONSULTA (nunca gravada) -- BNDES e RFB (via
# enriquecimento da FINEP, ver enrich_cnae.py) classificam porte por metodologias
# DIFERENTES, entao `operations.porte_cliente` guarda 2 vocabularios distintos ao
# mesmo tempo (ex: BNDES "PEQUENA" vs RFB "Empresa de Pequeno Porte" pro mesmo
# conceito). Pedido explicito do usuario (2026-09-10): colapsar em 4 categorias
# canonicas pro filtro da Busca e pro grafico "Por porte" do Consolidado (ver
# webapp/main.py::porte_breakdown/filtros) sem migrar/persistir nada -- so uma
# expressao SQL reaplicada em toda consulta que agrupa/filtra por porte. "Demais"
# (BNDES, faixa residual que nao distingue media de grande) e os valores "sem
# classificacao limpa" da RFB caem juntos em "Não informado", igual pedido.
PORTE_NORMALIZADO_SQL = """
    CASE porte_cliente
        WHEN 'Empresa de Pequeno Porte' THEN 'PEQUENA'
        WHEN 'Micro Empresa' THEN 'MICRO'
        WHEN 'GRANDE' THEN 'GRANDE'
        WHEN 'MÉDIA' THEN 'MÉDIA'
        WHEN 'PEQUENA' THEN 'PEQUENA'
        WHEN 'MICRO' THEN 'MICRO'
        ELSE 'Não informado'
    END
"""

_UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

# Regiao -> UFs (para o filtro estruturado de regiao, ver buscar_texto()). Mesma
# fonte de verdade que src/geo.py (UF->regiao), so invertida -- nao importa geo.py
# direto aqui pra nao criar dependencia cruzada webapp<->pipeline por causa de um
# dict pequeno; mantenha as duas listas em sincronia se uma UF mudar de regiao
# (nunca muda na pratica, e so a divisao oficial do IBGE).
_UFS_POR_REGIAO = {
    "Norte": ["AC", "AP", "AM", "PA", "RO", "RR", "TO"],
    "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste": ["DF", "GO", "MT", "MS"],
    "Sudeste": ["ES", "MG", "RJ", "SP"],
    "Sul": ["PR", "RS", "SC"],
}


def _normaliza_ortografia_sql(expr: str) -> str:
    """Unifica variantes ortograficas REAIS que o stemmer 'portuguese' do Postgres
    trata como palavras diferentes, causando busca imprecisa -- caso confirmado:
    'fibra OTICA' (grafia atual, sem o 'p' mudo) e 'fibra OPTICA' (grafia antiga,
    ainda de uso comum em telecom/tecnologia) sao o MESMO conceito pra quem
    pesquisa, mas nenhuma busca por uma achava documentos com a outra -- um match
    incidental de 'otica' (oculista) no NOME de uma empresa chegou a rankear acima
    de uma empresa real de fibra optica por causa disso. So faz sentido chamar
    DEPOIS de unaccent() (que ja tira o acento de 'ó'/'ô' etc, deixando so a
    diferenca real: a presenca ou nao do 'p'). Aplicado nos DOIS lados -- aqui (na
    query) e em unify.py::_atualizar_search_vector() (na indexacao) -- pra
    garantir que os dois batam nao importa qual grafia foi usada em cada um."""
    return f"regexp_replace({expr}, '\\moptic', 'otic', 'gi')"


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _extrair_uf(palavras: list) -> tuple:
    """Devolve (uf_detectada_ou_None, palavras_restantes) -- so reconhece a UF quando
    aparece como uma palavra ISOLADA de 2 letras (nao dispara em falso dentro de uma
    palavra maior)."""
    for p in palavras:
        if p.upper() in _UFS_VALIDAS:
            return p.upper(), [x for x in palavras if x is not p]
    return None, palavras


MINIMO_ANTES_DE_TRIGRAMA = 10  # so paga o custo de similarity() (varre a tabela toda) se as tiers 1-5 vierem com poucos resultados


def _rows_para_resultados(rows) -> list:
    resultados = []
    for r in rows:
        d = dict(zip(_COLS_OPERACAO, r[:len(_COLS_OPERACAO)]))
        prioridade = r[len(_COLS_OPERACAO)]
        d["motivo"] = PRIORIDADE_MOTIVO.get(prioridade, "Correspondência no texto completo")
        d["prioridade"] = prioridade
        resultados.append(d)
    return resultados


def buscar_texto(
    query: str, limite: int = 200, agencia: str = None, valor_minimo: float = None,
    regiao: str = None, produto: str = None, porte: str = None,
) -> dict:
    """Busca determinística em 6 tiers (ver PRIORIDADE_MOTIVO), cada uma como sua
    propria query: tiers 1-3 (prefixo CNPJ/cliente, keyword em setor/subsetor/
    segmento/produto/instrumento/indexador via LIKE) fazem seq scan -- sem indice
    funcional pra unaccent(lower(campo)), ver nota de performance no CLAUDE.md;
    tiers 4-5 (full-text, phraseto_tsquery/websearch_to_tsquery) usam o indice GIN
    de search_vector direto no WHERE (rapidas, ver idx_operations_search_vector);
    tier 6 (trigrama) so roda se as anteriores voltarem com poucos resultados
    (MINIMO_ANTES_DE_TRIGRAMA), tambem seq scan. Cada tier exclui os ids ja
    capturados por uma tier mais forte -- uma operacao aparece uma unica vez, na
    tier mais forte em que bate. Ordenado por prioridade, depois cobertura de
    palavras (so tier 5, ver comentario mais abaixo) e por fim rank_fts.

    agencia/valor_minimo/regiao/produto/porte sao FILTROS ESTRUTURADOS explicitos (vindos
    de selects/input na UI, ver webapp/main.py e busca.js) -- mesmo padrao ja usado
    pra UF dentro da propria query de texto livre (AND, nunca dentro do ranking de
    texto), so que aqui vem prontos do chamador em vez de extraidos da query."""
    query = (query or "").strip()
    if not query:
        return {"query": query, "n_resultados": 0, "resultados": []}

    cnpj_digitos = _so_digitos(query)
    eh_cnpj = len(cnpj_digitos) >= 8  # CNPJ parcial (raiz) ou completo (14 digitos)
    # So usa o fragmento numerico no tier 1 (match de CNPJ) se ele proprio parecer um
    # CNPJ (>=8 digitos): sem isso, uma query como "xyzabc123nada" extraia "123" e
    # desse falso-positivo de "correspondencia exata" com qualquer CNPJ que comece
    # com 123, no topo do ranking -- bug real encontrado ao validar a busca.
    cnpj_para_match = cnpj_digitos if eh_cnpj else ""

    # websearch_to_tsquery, por padrao, combina palavras separadas por espaco com AND
    # (exige TODAS as palavras no mesmo documento) -- bom pra 2-3 palavras-chave, ruim
    # pra uma busca livre em linguagem natural ("fintech de credito para pequenas
    # empresas"): nenhum documento teria as 6 palavras ao mesmo tempo. Junta as
    # palavras com " or " (palavra-chave que websearch_to_tsquery reconhece) antes de
    # passar pra ele -- assim documentos com QUALQUER uma das palavras (ou sinonimo
    # gravado em search_document) entram, ranqueados por ts_rank_cd (mais palavras
    # batendo = rank mais alto), em vez de exigir a frase inteira.
    palavras = [p for p in query.split() if p.lower() not in PALAVRAS_GENERICAS_QUERY] or query.split()
    uf_detectada, palavras = _extrair_uf(palavras)
    query_fts = " or ".join(palavras) or query
    # Frase (tier 4): mesmas palavras, mas em ORDEM -- phraseto_tsquery exige que os
    # lexemas apareçam ADJACENTES no documento (ignora stopwords no meio). Isso separa
    # "parque de diversao" (deve achar o segmento oficial "PARQUES DE DIVERSAO E
    # PARQUES TEMATICOS", onde os lexemas 'parqu' e 'diversa' sao vizinhos) de um
    # falso-positivo tipo "parque eolico" (so bate a palavra solta "parque" via OR,
    # nunca "parque" seguido de "diversao") -- confirmado empiricamente: sem essa
    # tier, os dois ficavam empatados no mesmo tier 4 (agora 5), com "parque eolico"
    # as vezes rankeando ACIMA por repetir "parque" em mais campos.
    query_fts_frase = " ".join(palavras) or query

    # Filtros estruturados (AND, fora do ranking de texto -- mesmo motivo do filtro
    # de UF: um filtro estruturado nunca deve competir por relevancia, so restringe
    # o universo de linhas candidatas antes do ranking rodar).
    filtros_extra = []
    params_extra_principal = []
    params_extra_trigrama = []
    if uf_detectada:
        filtros_extra.append("uf = ?")
        params_extra_principal.append(uf_detectada)
        params_extra_trigrama.append(uf_detectada)
    if agencia:
        filtros_extra.append("agencia = ?")
        params_extra_principal.append(agencia)
        params_extra_trigrama.append(agencia)
    if valor_minimo is not None:
        filtros_extra.append("valor_contratado >= ?")
        params_extra_principal.append(valor_minimo)
        params_extra_trigrama.append(valor_minimo)
    if regiao and regiao in _UFS_POR_REGIAO:
        ufs_regiao = _UFS_POR_REGIAO[regiao]
        placeholders = ", ".join(["?"] * len(ufs_regiao))
        filtros_extra.append(f"uf IN ({placeholders})")
        params_extra_principal.extend(ufs_regiao)
        params_extra_trigrama.extend(ufs_regiao)
    if produto:
        filtros_extra.append("produto = ?")
        params_extra_principal.append(produto)
        params_extra_trigrama.append(produto)
    if porte:
        # Filtra pela categoria CANONICA (ver PORTE_NORMALIZADO_SQL) -- selecionar
        # "PEQUENA" no dropdown precisa achar tanto o "PEQUENA" nativo do BNDES
        # quanto o "Empresa de Pequeno Porte" da RFB (FINEP), senao o filtro so
        # bate a metade das operacoes daquela categoria.
        filtros_extra.append(f"({PORTE_NORMALIZADO_SQL}) = ?")
        params_extra_principal.append(porte)
        params_extra_trigrama.append(porte)
    filtro_sql = ("AND " + " AND ".join(filtros_extra)) if filtros_extra else ""

    # regexp_replace(unaccent(?), ...) -- ver _normaliza_ortografia_sql(): unifica
    # grafias como "optica"/"otica" (mesmo conceito, tratadas como palavras
    # diferentes pelo stemmer sem isso) nos DOIS lados (query aqui, indexacao em
    # unify.py). Aplica em toda comparacao de TEXTO LIVRE contra o campo (nao no
    # CNPJ, que e so digito).
    _norm = _normaliza_ortografia_sql

    conn = get_connection()
    try:
        cur = conn.cursor()

        # Tiers 1-3 (prefixo de CNPJ/cliente, keyword em setor/subsetor/segmento/
        # produto/instrumento/indexador) continuam um unico seq scan sobre a tabela
        # inteira -- nao ha indice funcional pra unaccent(lower(cliente)) etc, e o
        # volume de linhas candidatas aqui e tipicamente pequeno (prefixo exato ou
        # keyword curta), entao o custo do seq scan em si e aceitavel. O que NAO
        # fica mais aqui sao os tiers 4/5 (full-text): antes, os dois `@@ tsquery`
        # + o `ts_rank_cd` ficavam DENTRO deste mesmo CASE, forcando o Postgres a
        # avaliar full-text pra TODA operacao da base (~58 mil linhas) em toda
        # busca, mesmo com o indice GIN de search_vector (idx_operations_search_vector)
        # disponivel e OCIOSO -- misturar uma condicao indexavel dentro de um CASE
        # que roda incondicionalmente sobre a tabela inteira impede o planner de
        # usar esse indice. Tiers 4/5 viraram queries proprias logo abaixo, cada
        # uma com `WHERE search_vector @@ tsquery(...)` direto (sem CASE por
        # cima) -- isso deixa o Postgres escolher um Bitmap Index Scan no GIN em
        # vez de Parallel Seq Scan. Ganho real medido ao vivo contra producao
        # (EXPLAIN ANALYZE): uma busca de texto livre tipica caiu de ~5-8s pra
        # ~150-300ms. Cada tier so roda se a(s) anterior(es) ainda nao encheram o
        # `limite` pedido (mesmo padrao ja usado pro tier 6/trigrama abaixo), e
        # cada uma exclui os ids ja escolhidos por uma tier mais forte -- preserva
        # exatamente a mesma regra de antes (cada operacao aparece uma unica vez,
        # na tier mais forte em que ela bate).
        # TETO_TIERS123: essa query ainda faz seq scan (sem indice funcional pra
        # unaccent(lower(campo)), so schema change resolveria -- ver nota no
        # CLAUDE.md), mas NAO calcula mais ts_rank_cd aqui dentro (extraido pra um
        # segundo passo abaixo, so nos candidatos que sobraram -- mesmo padrao
        # `id = ANY(?)` ja usado pra cobertura). Motivo medido ao vivo: ts_rank_cd
        # embutido no SELECT list e avaliado pra TODA linha da tabela varrida (as
        # ~58 mil, mesmo as ~56 mil que nunca batem prioridade nenhuma e sao
        # descartadas pelo WHERE de fora) -- puro desperdicio. Sem ORDER BY por
        # rank_fts aqui dentro, a query nao sabe mais escolher os "N mais
        # relevantes" sozinha, entao busca ATE um teto generoso (bem acima do
        # `limite` default de 200) e deixa o rank_fts (calculado so pros
        # candidatos que vieram) decidir o corte final em Python. Teto alto o
        # bastante pra cobrir qualquer termo de setor/subsetor/segmento/produto
        # plausivel (o mais largo observado, um SETOR inteiro tipo
        # "agropecuaria", bateu ~2 mil linhas) sem herdar o custo de rankear a
        # base inteira.
        TETO_TIERS123 = max(limite, 3000)
        sql_tiers123 = f"""
            SELECT {", ".join(_COLS_OPERACAO)}, prioridade FROM (
                SELECT {", ".join(_COLS_OPERACAO)},
                    CASE
                        WHEN ? != '' AND regexp_replace(cnpj, '\\D', '', 'g') LIKE ? || '%%' THEN 1
                        WHEN {_norm("unaccent(lower(cliente))")} LIKE {_norm("unaccent(lower(?))")} || '%%' THEN 1
                        WHEN {_norm("unaccent(lower(coalesce(setor_bndes,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                          OR {_norm("unaccent(lower(coalesce(subsetor_bndes,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                          OR {_norm("unaccent(lower(coalesce(segmento,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                        THEN 2
                        WHEN {_norm("unaccent(lower(coalesce(produto,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                          OR {_norm("unaccent(lower(coalesce(instrumento_financeiro,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                          OR {_norm("unaccent(lower(coalesce(indexador,'')))")} LIKE '%%' || {_norm("unaccent(lower(?))")} || '%%'
                        THEN 3
                        ELSE NULL
                    END AS prioridade
                FROM operations
                WHERE 1=1 {filtro_sql}
            ) sub
            WHERE prioridade IS NOT NULL
            ORDER BY prioridade ASC
            LIMIT ?
        """
        params_tiers123 = [
            cnpj_para_match, cnpj_para_match,  # tier 1 cnpj
            query,  # tier 1 cliente prefixo
            query, query, query,  # tier 2 setor/subsetor/segmento
            query, query, query,  # tier 3 produto/instrumento/indexador
        ]
        params_tiers123.extend(params_extra_principal)
        params_tiers123.append(TETO_TIERS123)
        rows_tiers123 = cur.execute(sql_tiers123, params_tiers123).fetchall()
        # placeholder de rank_fts (substituido pelo valor real mais abaixo, so
        # pros candidatos finais) -- mantem o formato de tupla igual ao das tiers
        # 4/5, que ja vem com rank_fts de verdade.
        rows = [r + (0.0,) for r in rows_tiers123]

        def _buscar_tier_indexada(tsquery_fn: str, query_texto: str, prioridade: int, faltam: int, excluir: list) -> list:
            """Tier 4 (frase) ou 5 (OR) via `search_vector @@ tsquery` direto no
            WHERE -- usa o indice GIN, ver comentario acima. `excluir` sao os ids
            ja capturados por uma tier mais forte (nunca reclassifica pra baixo).
            rank_fts sempre pelo OR-tsquery (query_fts) -- mesma metrica global
            usada como desempate em toda tier, so o teste de pertencer a tier (no
            WHERE) muda entre frase/OR."""
            if faltam <= 0:
                return []
            exclusao_sql, params_exclusao = "", []
            if excluir:
                exclusao_sql = "AND NOT (id = ANY(?))"
                params_exclusao = [excluir]
            sql = f"""
                SELECT {", ".join(_COLS_OPERACAO)}, {prioridade} AS prioridade,
                    ts_rank_cd(search_vector, websearch_to_tsquery('portuguese', {_norm("unaccent(?)")})) AS rank_fts
                FROM operations
                WHERE search_vector @@ {tsquery_fn}('portuguese', {_norm("unaccent(?)")})
                    {exclusao_sql} {filtro_sql}
                ORDER BY rank_fts DESC
                LIMIT ?
            """
            params = [query_fts, query_texto] + params_exclusao + params_extra_principal + [faltam]
            return cur.execute(sql, params).fetchall()

        ids_ja_vistos = [r[0] for r in rows]
        rows_tier4 = _buscar_tier_indexada("phraseto_tsquery", query_fts_frase, 4, limite - len(rows), ids_ja_vistos)
        rows += rows_tier4
        ids_ja_vistos += [r[0] for r in rows_tier4]
        rows_tier5 = _buscar_tier_indexada("websearch_to_tsquery", query_fts, 5, limite - len(rows), ids_ja_vistos)
        rows += rows_tier5

        # Calcula o rank_fts de verdade (OR-tsquery) so pros candidatos das tiers
        # 1-3 (que vieram com o placeholder 0.0 acima) -- mesmo truque de
        # id = ANY(?) usado pra cobertura logo abaixo: bounded aos poucos
        # milhares de candidatos que realmente sobreviveram ao filtro, nunca a
        # tabela inteira.
        idx_prioridade = len(_COLS_OPERACAO)
        idx_rank_fts = idx_prioridade + 1
        ids_tiers123 = [r[0] for r in rows if r[idx_prioridade] <= 3]
        if ids_tiers123:
            sql_rank_tiers123 = f"""
                SELECT id, ts_rank_cd(search_vector, websearch_to_tsquery('portuguese', {_norm("unaccent(?)")})) AS rank_fts
                FROM operations WHERE id = ANY(?)
            """
            rank_fts_por_id = dict(cur.execute(sql_rank_tiers123, [query_fts, ids_tiers123]).fetchall())
            rows = [
                r[:-1] + (rank_fts_por_id.get(r[0], 0.0),) if r[idx_prioridade] <= 3 else r
                for r in rows
            ]

        # Cobertura (so tier 5, mesmo escopo do fix original -- ver ORDER BY mais
        # abaixo): quantas PALAVRAS DISTINTAS da query aparecem no documento, uma a
        # uma -- corrige um bug real e documentado (ver CLAUDE.md): "cabos de fibra
        # otica" rankeava uma OTICA (loja de oculos, bate so 1 palavra num campo de
        # peso alto, nome/segmento) ACIMA da empresa real de fibra optica (bate 3
        # das 4 palavras num campo de peso mais baixo, descricao) -- ts_rank_cd pesa
        # mais o CAMPO onde bateu do que quantas palavras da query realmente batem.
        # Cobertura alta desempata a favor de quem cobre mais a query, nao so quem
        # bate em um campo "caro". Calculada so nos candidatos que a tier 5 ja
        # trouxe (id = ANY(?), poucas dezenas/centenas de linhas, indice de PK) --
        # NUNCA como subquery correlacionada dentro do CASE que varre a tabela
        # inteira: essa variante ja foi tentada e um teste real mediu >30s pra uma
        # query de 8 palavras contra o Aiven so por causa disso, inaceitavel pra
        # uma rota web.
        cobertura_por_id = {}
        ids_tier5 = list({r[0] for r in rows if r[idx_prioridade] == 5})
        if ids_tier5 and palavras:
            sql_cobertura = f"""
                SELECT id, (
                    SELECT COUNT(*) FROM unnest(?::text[]) t(termo)
                    WHERE search_vector @@ websearch_to_tsquery('portuguese', {_norm("unaccent(t.termo)")})
                ) AS cobertura
                FROM operations WHERE id = ANY(?)
            """
            cobertura_por_id = dict(cur.execute(sql_cobertura, [palavras, ids_tier5]).fetchall())
        rows.sort(key=lambda r: (r[idx_prioridade], -cobertura_por_id.get(r[0], 0), -r[idx_rank_fts]))

        if len(rows) < MINIMO_ANTES_DE_TRIGRAMA:
            sql_trigrama = f"""
                SELECT {", ".join(_COLS_OPERACAO)}, 6 AS prioridade,
                    GREATEST(
                        similarity(unaccent(lower(cliente)), unaccent(lower(?))),
                        similarity(unaccent(lower(coalesce(segmento,''))), unaccent(lower(?)))
                    ) AS rank_fts
                FROM operations
                WHERE (
                    similarity(unaccent(lower(cliente)), unaccent(lower(?))) > {LIMIAR_SIMILARIDADE_TRGM}
                    OR similarity(unaccent(lower(coalesce(segmento,''))), unaccent(lower(?))) > {LIMIAR_SIMILARIDADE_TRGM}
                )
                {filtro_sql}
                ORDER BY rank_fts DESC
                LIMIT ?
            """
            params_trigrama = [query, query, query, query]
            params_trigrama.extend(params_extra_trigrama)
            params_trigrama.append(limite - len(rows))
            ja_incluidos = {r[0] for r in rows}
            rows_trigrama = cur.execute(sql_trigrama, params_trigrama).fetchall()
            rows = rows + [r for r in rows_trigrama if r[0] not in ja_incluidos]
    finally:
        conn.close()

    # Tiers 1-3 podem ter trazido ate TETO_TIERS123 candidatos (bem mais que
    # `limite`, ver comentario acima) so pra ordenar direito por rank_fts -- corta
    # pro tamanho pedido so agora, depois do sort final.
    rows = rows[:limite]
    resultados = _rows_para_resultados(rows)
    return {
        "query": query,
        "eh_busca_cnpj": eh_cnpj,
        "n_resultados": len(resultados),
        "resultados": resultados,
    }


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "empresa de hospitais em SP"
    out = buscar_texto(q)
    print(f"query={out['query']!r} n_resultados={out['n_resultados']}")
    for r in out["resultados"][:15]:
        print(f"  [{r['prioridade']}] {r['cliente']} | {r['setor_bndes']} | {r['segmento']} -- {r['motivo']}")
