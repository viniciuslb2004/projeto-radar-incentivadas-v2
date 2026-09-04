"""Constroi a tabela `linhas_incentivadas` (catalogo de LINHAS/PROGRAMAS de credito,
diferente de `editais_raw`, que sao CHAMADAS PUBLICAS com prazo) a partir de fontes
LOCAIS/OFICIAIS -- o site hospedado so consulta esta tabela, nunca acessa os sites das
instituicoes em tempo real (ver item 6 do pedido de melhorias).

Duas fontes hoje:
1. FINEP: reaproveita `editais_raw` (ja coletado de https://www.finep.gov.br/oportunidades
   via API oficial, ver finep_editais.py) -- uma chamada publica tambem e uma forma de
   linha incentivada (fluxo='edital', por oposicao a fluxo continuo).
2. BNDES: curadoria manual VERIFICADA (fonte_tipo='curadoria_manual_verificada') -- cada
   linha abaixo foi capturada navegando na pagina oficial real, nao inferida. Cobertura
   inicial pequena e deliberada (nao um catalogo completo do BNDES).

Desenvolve SP e BNB: SEM integracao ainda (nenhuma linha real coletada) -- nao ha
scraper para essas 2 instituicoes nesta versao. Ver relatorio da sessao para o porque
(sites nao mapeados/verificados) -- propositalmente NAO populado com dado nenhum em vez
de inventar conteudo so para "completar" as 4 instituicoes pedidas.
"""
import datetime
import json

from db import get_connection


def _agora() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _search_document(linha: dict) -> str:
    partes = [
        linha.get("instituicao"),
        linha.get("nome_oficial"),
        linha.get("nome_simplificado"),
        linha.get("sigla"),
        linha.get("descricao_resumida"),
        linha.get("setores_elegiveis"),
        linha.get("setor_padronizado"),
        linha.get("sinonimos_termos"),
        linha.get("destinacao"),
        linha.get("itens_financiaveis"),
        linha.get("tipo_apoio"),
        linha.get("regiao_elegivel"),
    ]
    return " | ".join(str(p) for p in partes if p not in (None, "", "nan"))


_COLS_LINHA = [
    "instituicao", "nome_oficial", "nome_simplificado", "sigla", "status",
    "descricao_resumida", "descricao_completa", "modalidade", "tipo_apoio",
    "setores_elegiveis", "setores_nao_elegiveis", "porte_elegivel", "faixa_receita",
    "regiao_elegivel", "destinacao", "itens_financiaveis", "itens_nao_financiaveis",
    "valor_minimo", "valor_maximo", "percentual_financiavel", "contrapartida",
    "taxa_completa", "indexador", "spread", "prazo_total", "carencia", "amortizacao",
    "garantias", "restricoes", "criterios_elegibilidade", "agente_financeiro",
    "canal_contratacao", "prazo_inscricao", "fluxo", "documentos_necessarios",
    "url_oficial", "data_vigencia", "data_captura", "data_atualizacao", "trecho_fonte",
    "origem_dado", "origem_raw_id", "setor_padronizado", "subsetor_padronizado",
    "cnaes_relacionados", "porte_padronizado", "destinacao_padronizada",
    "tecnologias_relacionadas", "temas_inovacao", "temas_sustentabilidade",
    "sinonimos_termos", "search_document",
]

_CHAVE_NATURAL = ("instituicao", "nome_oficial", "url_oficial")


def _upsert_many(conn, linhas: list, lote: int = 100) -> int:
    """UPSERT em lote por (instituicao, nome_oficial, url_oficial) -- chave natural
    (nao ha id estavel compartilhado entre execucoes para BNDES/curadoria manual).
    Idempotente: reprocessar a mesma fonte atualiza as linhas existentes, nunca
    duplica. Um INSERT...ON CONFLICT por lote (nao um SELECT+INSERT/UPDATE por linha
    -- muito mais rapido contra um banco remoto) + UMA atualizacao de search_vector
    no final, para TODAS as linhas de uma vez."""
    if not linhas:
        return 0
    agora = _agora()
    for linha in linhas:
        linha.setdefault("data_captura", agora)
        linha["data_atualizacao"] = agora
        linha["search_document"] = _search_document(linha)

    placeholders = ", ".join("?" * len(_COLS_LINHA))
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in _COLS_LINHA if c not in _CHAVE_NATURAL and c != "data_captura")
    sql = (
        f"INSERT INTO linhas_incentivadas ({', '.join(_COLS_LINHA)}) VALUES ({placeholders}) "
        f"ON CONFLICT (instituicao, nome_oficial, url_oficial) DO UPDATE SET {set_clause}"
    )
    total = 0
    cur = conn.cursor()
    for i in range(0, len(linhas), lote):
        pedaco = linhas[i:i + lote]
        cur.executemany(sql, [[linha.get(c) for c in _COLS_LINHA] for linha in pedaco])
        conn.commit()
        total += len(pedaco)
        print(f"  linhas_incentivadas: {total}/{len(linhas)} gravadas", flush=True)

    conn.execute(
        "UPDATE linhas_incentivadas SET search_vector = to_tsvector('portuguese', unaccent(coalesce(search_document, ''))) "
        "WHERE search_document IS NOT NULL"
    )
    conn.commit()
    return total


NAO_INFORMADO = "Não informado pela fonte"


def importar_finep_editais(conn) -> int:
    """FINEP: uma linha_incentivada por edital em editais_raw -- fluxo='edital'."""
    rows = conn.execute(
        "SELECT id, titulo, tema_principal, temas, situacao, tipo_oportunidade, contrapartida, "
        "regiao, publico_alvo, data_publicacao, vigencia_inicio, vigencia_fim, prazo_proposto, "
        "descricao_texto, documentos FROM editais_raw"
    ).fetchall()
    linhas_a_gravar = []
    for r in rows:
        (edital_id, titulo, tema_principal, temas, situacao, tipo_oportunidade, contrapartida,
         regiao, publico_alvo, data_publicacao, vigencia_inicio, vigencia_fim, prazo_proposto,
         descricao_texto, documentos) = r
        try:
            docs = json.loads(documentos) if documentos else []
        except (json.JSONDecodeError, TypeError):
            docs = []
        linha = {
            "instituicao": "FINEP",
            "nome_oficial": titulo or NAO_INFORMADO,
            "nome_simplificado": titulo,
            "sigla": None,
            "status": {"aberta": "aberta", "encerrada": "encerrada"}.get(situacao, NAO_INFORMADO),
            "descricao_resumida": (descricao_texto or "")[:500] or NAO_INFORMADO,
            "descricao_completa": descricao_texto or NAO_INFORMADO,
            "modalidade": NAO_INFORMADO,
            "tipo_apoio": tipo_oportunidade or NAO_INFORMADO,
            "setores_elegiveis": tema_principal or NAO_INFORMADO,
            "setores_nao_elegiveis": NAO_INFORMADO,
            "porte_elegivel": NAO_INFORMADO,
            "faixa_receita": NAO_INFORMADO,
            "regiao_elegivel": regiao or NAO_INFORMADO,
            "destinacao": temas or NAO_INFORMADO,
            "itens_financiaveis": NAO_INFORMADO,
            "itens_nao_financiaveis": NAO_INFORMADO,
            "valor_minimo": None,
            "valor_maximo": None,
            "percentual_financiavel": NAO_INFORMADO,
            "contrapartida": contrapartida or NAO_INFORMADO,
            "taxa_completa": NAO_INFORMADO,
            "indexador": NAO_INFORMADO,
            "spread": NAO_INFORMADO,
            "prazo_total": NAO_INFORMADO,
            "carencia": NAO_INFORMADO,
            "amortizacao": NAO_INFORMADO,
            "garantias": NAO_INFORMADO,
            "restricoes": NAO_INFORMADO,
            "criterios_elegibilidade": publico_alvo or NAO_INFORMADO,
            "agente_financeiro": "FINEP",
            "canal_contratacao": NAO_INFORMADO,
            "prazo_inscricao": prazo_proposto or NAO_INFORMADO,
            "fluxo": "edital",
            "documentos_necessarios": json.dumps(docs, ensure_ascii=False) if docs else NAO_INFORMADO,
            "url_oficial": "https://www.finep.gov.br/oportunidades",
            "data_vigencia": f"{vigencia_inicio or '?'} a {vigencia_fim or '?'}",
            "trecho_fonte": f"editais_raw.id={edital_id} (API oficial FINEP, ver finep_editais.py)",
            "origem_dado": "raspagem_automatica",
            "origem_raw_id": edital_id,
            "setor_padronizado": tema_principal or NAO_INFORMADO,
            "subsetor_padronizado": None,
            "cnaes_relacionados": None,
            "porte_padronizado": None,
            "destinacao_padronizada": temas,
            "tecnologias_relacionadas": None,
            "temas_inovacao": tema_principal,
            "temas_sustentabilidade": None,
            "sinonimos_termos": None,
        }
        linhas_a_gravar.append(linha)
    return _upsert_many(conn, linhas_a_gravar)


# BNDES: curadoria manual VERIFICADA -- cada entrada foi navegada e conferida ao vivo
# nesta sessao (nao inferida). Cobertura pequena e deliberada, ver docstring do modulo.
_BNDES_MANUAL = [
    {
        "instituicao": "BNDES",
        "nome_oficial": "BNDES Mais Inovação",
        "nome_simplificado": "Mais Inovação",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": (
            "Apoio à implantação de investimentos e projetos voltados para inovação e "
            "digitalização, com recursos do FAT remunerados pela TR."
        ),
        "descricao_completa": (
            "Apoio à implantação de investimentos e projetos voltados para inovação e "
            "digitalização, mediante utilização de recursos do Fundo de Amparo ao "
            "Trabalhador – FAT remunerados pela Taxa Referencial (TR), conforme aprovado "
            "pela lei nº 14.592, de 30 de maio de 2023. O programa possui cinco "
            "subprogramas: Investimento em Inovação (inclui apoio direto a Centros PD&I); "
            "Difusão Tecnológica (linha para indústria 4.0); Investimento Automático "
            "(Programa Brasil Mais Produtivo); Apoio a Centros de PD&I."
        ),
        "modalidade": "Direta e Indireta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Indústria, inovação e P&D&I",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional (valores mínimos diferenciados para Norte/Nordeste)",
        "destinacao": "Inovação, digitalização, difusão tecnológica, P&D&I",
        "itens_financiaveis": "Plantas pioneiras; difusão tecnológica; digitalização; parques tecnológicos; equipamentos com tecnologias inovadoras",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": 10_000_000,
        "valor_maximo": None,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "TR (Taxa Referencial) + spread do BNDES",
        "indexador": "TR",
        "spread": NAO_INFORMADO,
        "prazo_total": NAO_INFORMADO,
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": (
            "Financiamento direto a partir de R$ 10 milhões nas regiões Norte e Nordeste "
            "e a partir de R$ 20 milhões nas demais regiões; indireto não automático "
            "com valor mínimo de R$ 20 milhões; Difusão Tecnológica até R$ 50 milhões."
        ),
        "criterios_elegibilidade": "Projetos compatíveis com a Política Industrial ou políticas nacionais de Meio Ambiente",
        "agente_financeiro": "BNDES (direto) ou instituições financeiras credenciadas (indireto)",
        "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto",
        "data_vigencia": "Lei nº 14.592, de 30 de maio de 2023",
        "trecho_fonte": (
            "\"O programa possui cinco subprogramas, com condições de apoio distintas... "
            "Financiamento direto com o BNDES, a partir de R$ 10 milhões, nas regiões norte "
            "e nordeste e a partir de R$ 20 milhões para demais regiões do país.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "INDUSTRIA",
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": "Médio/Grande (valor mínimo R$ 10-20 milhões)",
        "destinacao_padronizada": "Inovação e digitalização",
        "tecnologias_relacionadas": "Indústria 4.0, digitalização, P&D&I",
        "temas_inovacao": "Inovação, difusão tecnológica, transformação digital",
        "temas_sustentabilidade": None,
        "sinonimos_termos": "inovacao tecnologia digitalizacao industria 4.0 P&D&I pesquisa e desenvolvimento",
    },
]


def seed_bndes_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _BNDES_MANUAL])


def build_linhas_incentivadas():
    conn = get_connection()
    try:
        n_finep = importar_finep_editais(conn)
        n_bndes = seed_bndes_manual(conn)
        total = conn.execute("SELECT COUNT(*) FROM linhas_incentivadas").fetchone()[0]
    finally:
        conn.close()
    print(
        f"linhas_incentivadas: {n_finep} da FINEP (editais_raw) + {n_bndes} do BNDES "
        f"(curadoria manual verificada) processadas -- {total} linhas no total. "
        f"Desenvolve SP e BNB: sem integracao ainda (ver docstring do modulo)."
    )


if __name__ == "__main__":
    build_linhas_incentivadas()
