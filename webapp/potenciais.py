"""Rotas de "Potenciais Linhas" (item 3 do pedido) -- usuario informa
caracteristicas do projeto (setor, porte, volume necessario, uso dos recursos) e
recebe um ranking de Linhas Incentivadas (`linhas_incentivadas`) com "potencial
aderencia" (NUNCA "elegibilidade confirmada" -- isso sempre depende de analise
adicional que este app nao faz).

Pacote ISOLADO, mesmo espirito de webapp/admin/webapp/salvos.py (ja removido,
ver docs/archive/removed-features.md, mas o padrao de isolamento continua valido):
nenhuma tabela nova, so consulta `linhas_incentivadas`/`operations` ja existentes.
A UNICA integracao com webapp/main.py e o `app.include_router(...)` (ver la).

Motor de recomendacao: filtros estruturados + score determinístico por regras
(nunca IA/embeddings/chamada a modelo) -- ver `_pontuar_linha` abaixo. Pedido
explicito do usuario: "boa precisão com baixo custo", sem obrigacao de IA. Dado
o volume pequeno da tabela (~112 linhas), pontuar em Python depois de um SELECT
simples e mais simples e transparente (motivos legiveis por linha) do que tentar
expressar o mesmo score num CASE SQL gigante -- sem perda de performance real
(tabela inteira cabe em memoria, nenhum N+1 contra o banco).

"Transações Semelhantes" (item 4 do pedido) NAO tem rota propria aqui -- o
frontend (potenciais.js) chama `/api/operacoes` diretamente (ja estendido com
os filtros porte/valor_min/valor_max/produto, ver webapp/main.py::
_filters_clause), reaproveitando o motor de filtros que a aba Consolidado/Busca
ja usa em vez de duplicar logica de query aqui.
"""
from fastapi import APIRouter

from db import get_connection

router = APIRouter()

NAO_INFORMADO = "Não informado pela fonte"
NAO_INFORMADO_GRUPO = "Não informado"

# Porte do INPUT do usuario (o porte/faturamento da PROPRIA empresa dele, item 3
# do pedido) usa o MESMO vocabulario canonico ja usado em todo o resto do site
# pra classificar operations.porte_cliente -- MICRO/PEQUENA/MÉDIA/GRANDE (ver
# PORTE_NORMALIZADO_SQL em src/search_fts.py e o filtro de porte da aba Busca) --
# em vez do bucket "Micro/Pequena" combinado usado em linhas_incentivadas.porte_grupo
# (task 1, um problema DIFERENTE: colapsar 42 valores de TEXTO LIVRE da fonte
# oficial). Usar o mesmo vocabulario do site aqui tem 2 vantagens: (1) da pra
# filtrar "Transações Semelhantes" em `operations` com o MESMO valor, sem
# converter nada; (2) fica consistente com o que o usuario ja ve na aba Busca.
# _PORTE_INPUT_PARA_GRUPO_LINHA faz a ponte pro bucket de linhas_incentivadas
# (mais grosso) na hora de pontuar.
_ORDEM_PORTE_INPUT = ["MICRO", "PEQUENA", "MÉDIA", "GRANDE"]
_PORTE_INPUT_PARA_GRUPO_LINHA = {
    "MICRO": "Micro/Pequena",
    "PEQUENA": "Micro/Pequena",
    "MÉDIA": "Média",
    "GRANDE": "Grande",
}

_COLS_CANDIDATO = [
    "id", "instituicao", "nome_oficial", "nome_simplificado", "status", "fluxo",
    "setor_padronizado", "porte_padronizado", "porte_grupo", "destinacao",
    "destinacao_grupo", "itens_financiaveis", "criterios_elegibilidade",
    "percentual_financiavel", "taxa_completa", "indexador", "spread",
    "prazo_total", "carencia", "valor_minimo", "valor_maximo",
    "agente_financeiro", "url_oficial",
]


@router.get("/opcoes")
def potenciais_opcoes():
    """Opcoes pra popular o formulario -- nunca inclui uma opcao vazia (mesmo
    padrao ja usado em /api/linhas/filtros)."""
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()

        # Setores: as 4 categorias reais de linhas_incentivadas.setor_padronizado
        # (exclui o sentinela "Não informado pela fonte" -- nao faz sentido o
        # usuario "escolher" nao-informado como setor do proprio projeto). Mesmo
        # vocabulario de operations.setor_bndes (ver linhas.js::
        # SETORES_TAXONOMIA_BNDES), entao serve pros dois usos (match de linha E
        # filtro de "Transações Semelhantes").
        setores = [r[0] for r in cur.execute(
            "SELECT DISTINCT setor_padronizado FROM linhas_incentivadas "
            "WHERE setor_padronizado IS NOT NULL AND setor_padronizado != ? "
            "ORDER BY setor_padronizado",
            (NAO_INFORMADO,),
        ).fetchall()]

        # Sempre as 4 categorias -- nao depende do que ja existe em
        # linhas_incentivadas.porte_grupo (esse e o bucket da LINHA, nao do
        # input do usuario, ver comentario em _ORDEM_PORTE_INPUT acima); sao os
        # mesmos 4 valores que operations.porte_cliente sempre pode assumir.
        portes = list(_ORDEM_PORTE_INPUT)

        usos = [r[0] for r in cur.execute(
            "SELECT DISTINCT destinacao_grupo FROM linhas_incentivadas "
            "WHERE destinacao_grupo IS NOT NULL AND destinacao_grupo != ? "
            "ORDER BY destinacao_grupo",
            (NAO_INFORMADO_GRUPO,),
        ).fetchall()]

        # Subsetor: so existe em `operations` (linhas_incentivadas nao tem essa
        # granularidade, ver decisao ja registrada em Decisões.md/recon) -- serve
        # so de sinal adicional pro filtro de "Transações Semelhantes", nunca pro
        # score de aderencia de uma linha.
        subsetores = [r[0] for r in cur.execute(
            "SELECT DISTINCT subsetor_bndes FROM operations WHERE subsetor_bndes IS NOT NULL ORDER BY subsetor_bndes"
        ).fetchall()]

        return {"setores": setores, "portes": portes, "usos": usos, "subsetores": subsetores}
    finally:
        conn.close()


def _pontuar_linha(linha: dict, setor: str, porte: str, volume: float, uso: str):
    """Score determinístico 0-100 por quantos criterios (dos que o usuario de fato
    informou) a linha atende, cada um com peso fixo, RENORMALIZADO pela soma dos
    pesos dos criterios informados (um usuario que so preenche 1 campo nao deveria
    ter o score arbitrariamente baixado so por faltar os outros 3). "Não
    informado pela fonte"/"Não informado" na linha nunca zera o criterio (nao ha
    como confirmar OU descartar compatibilidade), mas tambem nunca vale igual a
    um match confirmado -- credito parcial, sempre com o motivo deixando claro
    que e uma suposicao, nao uma confirmacao."""
    pontos = 0.0
    peso_total = 0.0
    motivos = []
    criterios_avaliados = 0

    if setor and setor != "Todos":
        criterios_avaliados += 1
        peso_total += 30
        if linha.get("setor_padronizado") == setor:
            pontos += 30
            motivos.append(f"Setor do projeto compatível ({setor})")
        elif linha.get("setor_padronizado") == NAO_INFORMADO:
            pontos += 12
            motivos.append("Setor elegível não informado pela fonte oficial (não descarta compatibilidade)")
        else:
            motivos.append(f"Setor da linha ({linha.get('setor_padronizado') or 'Não informado'}) diferente do informado")

    if porte and porte != "Todos":
        criterios_avaliados += 1
        peso_total += 25
        grupo = linha.get("porte_grupo")
        # porte vem no vocabulario do SITE (MICRO/PEQUENA/MÉDIA/GRANDE) -- convertido
        # pro bucket mais grosso de linhas_incentivadas.porte_grupo antes de comparar
        # (ver _PORTE_INPUT_PARA_GRUPO_LINHA).
        porte_equivalente = _PORTE_INPUT_PARA_GRUPO_LINHA.get(porte, porte)
        if grupo == "Todos os portes":
            pontos += 25
            motivos.append("Linha aberta a todos os portes")
        elif grupo == porte_equivalente:
            pontos += 25
            motivos.append(f"Porte do projeto compatível ({porte})")
        elif grupo == NAO_INFORMADO_GRUPO:
            pontos += 10
            motivos.append("Porte elegível não informado pela fonte oficial")
        else:
            motivos.append(f"Porte elegível da linha ({grupo}) pode não incluir {porte}")

    if volume is not None:
        criterios_avaliados += 1
        peso_total += 25
        vmin, vmax = linha.get("valor_minimo"), linha.get("valor_maximo")
        if vmin is None and vmax is None:
            pontos += 10
            motivos.append("Faixa de valor financiável não informada pela fonte")
        else:
            dentro = (vmin is None or volume >= vmin) and (vmax is None or volume <= vmax)
            if dentro:
                pontos += 25
                motivos.append("Volume necessário dentro da faixa financiável informada")
            else:
                motivos.append("Volume necessário fora da faixa financiável informada pela fonte")

    if uso and uso != "Todos":
        criterios_avaliados += 1
        peso_total += 20
        grupo = linha.get("destinacao_grupo")
        if grupo == uso:
            pontos += 20
            motivos.append(f"Uso dos recursos compatível ({uso})")
        elif grupo in (NAO_INFORMADO_GRUPO, "Outros"):
            pontos += 8
            motivos.append("Destinação da linha não claramente classificada na fonte")
        else:
            motivos.append(f"Destinação típica da linha ({grupo}) diferente do uso informado")

    if peso_total == 0:
        return None
    score_pct = round(100 * pontos / peso_total)
    return score_pct, motivos, criterios_avaliados


def _rotulo_score(score_pct: int) -> str:
    if score_pct >= 70:
        return "Alta"
    if score_pct >= 40:
        return "Média"
    return "Baixa"


# Desempate por frequencia historica (item 4 do gap-fix 2026-09-22) -- SO entra
# depois do score de aderencia (nunca compoe/sobrepoe o score em si, ver
# `resultados.sort` em potenciais_buscar). Sem FK entre linhas_incentivadas e
# operations -- casamento por aproximacao de texto (nome da linha contra
# operations.produto/instrumento) via similarity() do pg_trgm (extensao ja
# instalada, ver src/db.py). Limiar mais alto (conservador) que o generico de
# busca (LIMIAR_SIMILARIDADE_TRGM = 0.25 em src/search_fts.py, usado pra nomes
# de CLIENTE) -- aqui um falso-positivo contaria operacoes de um produto
# diferente como se fossem da linha, o que e pior que simplesmente nao ter o
# sinal (frequencia_historica vira None nesse caso, tratado como "sem dado").
LIMIAR_SIMILARIDADE_TRGM_HISTORICO = 0.4

# Restricao conhecida (ver CLAUDE.md/docs/linhas-incentivadas.md):
# operations.agencia SO tem 'BNDES'/'FINEP' -- a base de transacoes reais NAO
# cobre BNB/Desenvolve SP/BASA/BB/CEF (a maioria do catalogo). Linhas de
# qualquer outra instituicao NUNCA entram no calculo de frequencia (ficam
# sempre com frequencia_historica = None, nunca 0 -- 0 implicaria "confirmado
# que nao e usada", o que nao podemos afirmar por limitacao de cobertura).
_AGENCIAS_COM_OPERACOES_REAIS = ("BNDES", "FINEP")

# So vira motivo textual ("frequentemente utilizada...") acima deste piso --
# 1-2 correspondencias por similaridade de texto sao ruido demais pra virar uma
# frase de "uso frequente" no motivo exibido ao usuario.
FREQUENCIA_HISTORICA_MOTIVO_MINIMO = 10


def _computar_frequencia_historica(cur, candidatos_bndes_finep: list) -> dict:
    """Conta operacoes reais em `operations` que correspondem (por similaridade
    de texto, pg_trgm) ao nome de cada linha do BNDES/FINEP -- usado SO como
    desempate secundario no ranking (nunca como parte do score de aderencia).
    Recebe so os candidatos cuja instituicao ja e BNDES/FINEP (filtrado pelo
    chamador) -- os demais nunca chegam aqui, entao nunca tem seu
    "nao aparece na base" mal-interpretado como "linha pouco usada" (ver
    comentario da constante _AGENCIAS_COM_OPERACOES_REAIS acima).

    Agrupa `operations` por agencia + COALESCE(produto, instrumento) ANTES de
    comparar (poucas dezenas/centenas de termos distintos por agencia) em vez
    de rodar similarity() linha a linha contra as ~59 mil operacoes -- mais
    barato e nao exige nenhum indice novo (nenhuma mudanca de schema)."""
    if not candidatos_bndes_finep:
        return {}

    linhas_values = []
    params = []
    for c in candidatos_bndes_finep:
        linhas_values.append("(?, ?, ?)")
        params.extend([c["id"], c["instituicao"], c["nome"]])

    query = f"""
        WITH termos AS (
            SELECT agencia, COALESCE(produto, instrumento) AS termo, COUNT(*) AS n
            FROM operations
            WHERE agencia IN ('BNDES', 'FINEP') AND COALESCE(produto, instrumento) IS NOT NULL
            GROUP BY agencia, COALESCE(produto, instrumento)
        ),
        candidatos(id, instituicao, nome) AS (
            VALUES {", ".join(linhas_values)}
        )
        SELECT c.id, SUM(t.n)
        FROM candidatos c
        JOIN termos t
          ON t.agencia = c.instituicao
         AND similarity(unaccent(lower(t.termo)), unaccent(lower(c.nome))) > {LIMIAR_SIMILARIDADE_TRGM_HISTORICO}
        GROUP BY c.id
    """
    rows = cur.execute(query, params).fetchall()
    return {r[0]: int(r[1]) for r in rows}


@router.get("/buscar")
def potenciais_buscar(
    setor: str = None, porte: str = None, volume: float = None, uso: str = None,
    limit: int = 20,
):
    """Motor de recomendacao: filtro estruturado (setor, quando informado, ja
    reduz o SELECT pra so a categoria escolhida + linhas com setor não informado
    -- essas ultimas continuam candidatas, so com credito parcial no score, ver
    _pontuar_linha) + score determinístico em Python sobre os candidatos."""
    limit = max(1, min(limit, 100))
    if not any([setor, porte, volume is not None, uso]):
        return {"erro": "informe ao menos um critério (setor, porte, volume ou uso dos recursos)"}

    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        where, params = "", []
        if setor and setor != "Todos":
            where = "WHERE setor_padronizado IN (?, ?)"
            params = [setor, NAO_INFORMADO]
        rows = cur.execute(
            f"SELECT {', '.join(_COLS_CANDIDATO)} FROM linhas_incentivadas {where}", params
        ).fetchall()
        candidatos = [dict(zip(_COLS_CANDIDATO, r)) for r in rows]

        resultados = []
        for linha in candidatos:
            pontuacao = _pontuar_linha(linha, setor, porte, volume, uso)
            if pontuacao is None:
                continue
            score_pct, motivos, criterios_avaliados = pontuacao
            resultados.append({
                "id": linha["id"],
                "instituicao": linha["instituicao"],
                "nome": linha["nome_simplificado"] or linha["nome_oficial"],
                "nome_oficial": linha["nome_oficial"],
                "status": linha["status"],
                "taxa_completa": linha["taxa_completa"],
                "indexador": linha["indexador"],
                "spread": linha["spread"],
                "prazo_total": linha["prazo_total"],
                "carencia": linha["carencia"],
                "percentual_financiavel": linha["percentual_financiavel"],
                "criterios_elegibilidade": linha["criterios_elegibilidade"],
                "itens_financiaveis": linha["itens_financiaveis"],
                "valor_minimo": linha["valor_minimo"],
                "valor_maximo": linha["valor_maximo"],
                "setor_padronizado": linha["setor_padronizado"],
                "porte_grupo": linha["porte_grupo"],
                "destinacao_grupo": linha["destinacao_grupo"],
                "agente_financeiro": linha["agente_financeiro"],
                "url_oficial": linha["url_oficial"],
                "score_pct": score_pct,
                "score_rotulo": _rotulo_score(score_pct),
                "motivos": motivos,
                "criterios_avaliados": criterios_avaliados,
            })

        # Frequencia historica (item 4): sinal SECUNDARIO de desempate, calculado
        # so pros resultados de instituicao BNDES/FINEP (unicas cobertas por
        # `operations`, ver _AGENCIAS_COM_OPERACOES_REAIS). Nunca influencia o
        # score_pct em si -- so a ordem entre linhas empatadas nele. Usa
        # `nome_oficial` (nunca `nome_simplificado`) pra comparar contra
        # operations.produto/instrumento -- testado ao vivo contra a base real:
        # o nome oficial preserva o prefixo "BNDES <categoria>" (ex: "BNDES
        # Finame Agrícola") que da match de verdade com o produto agregado em
        # `operations` (ex: "BNDES FINAME", similarity=0.59); o nome
        # simplificado ("Finame Agrícola", sem o prefixo) cai pra 0.32 -- abaixo
        # do limiar conservador -- e perderia sinais reais por causa so de um
        # rotulo mais curto pensado pra exibicao, nao pra matching.
        candidatos_bndes_finep = [
            {"id": r["id"], "instituicao": r["instituicao"], "nome": r["nome_oficial"]}
            for r in resultados if r["instituicao"] in _AGENCIAS_COM_OPERACOES_REAIS
        ]
        freq_por_id = _computar_frequencia_historica(cur, candidatos_bndes_finep)
        for r in resultados:
            freq = freq_por_id.get(r["id"])
            r["frequencia_historica"] = freq
            # So adiciona motivo textual quando o sinal e POSITIVO e real (nunca
            # infere ausencia/None como "pouco utilizada" -- ver docstring de
            # _computar_frequencia_historica).
            if freq is not None and freq >= FREQUENCIA_HISTORICA_MOTIVO_MINIMO:
                r["motivos"].append(
                    f"Linha frequentemente utilizada em operações similares na base histórica "
                    f"(~{freq} operação(ões) com produto/instrumento parecido)"
                )

        resultados.sort(key=lambda r: (-r["score_pct"], -(r["frequencia_historica"] or 0), r["nome"] or ""))
        return {
            "criterios_informados": {
                "setor": setor or None, "porte": porte or None,
                "volume": volume, "uso": uso or None,
            },
            "total_candidatos": len(candidatos),
            "resultados": resultados[:limit],
        }
    finally:
        conn.close()
