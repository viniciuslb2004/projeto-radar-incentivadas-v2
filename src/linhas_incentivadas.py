"""Constroi a tabela `linhas_incentivadas` (catalogo de LINHAS/PROGRAMAS de credito,
diferente de `editais_raw`, que sao CHAMADAS PUBLICAS com prazo) a partir de fontes
LOCAIS/OFICIAIS -- o site hospedado so consulta esta tabela, nunca acessa os sites das
instituicoes em tempo real (ver item 6 do pedido de melhorias).

Quatro fontes hoje:
1. FINEP: reaproveita `editais_raw` (ja coletado de https://www.finep.gov.br/oportunidades
   via API oficial, ver finep_editais.py) -- uma chamada publica tambem e uma forma de
   linha incentivada (fluxo='edital', por oposicao a fluxo continuo).
2. BNDES: curadoria manual verificada (origem_dado='curadoria_manual_verificada') --
   1 linha (BNDES Mais Inovação), capturada navegando na pagina oficial real. O site
   do BNDES e um portal WCM pesado em JS sem catalogo estavel navegavel por URL --
   cobertura pequena e deliberada, nao um catalogo completo.
3. Desenvolve SP: curadoria manual verificada -- 17 linhas reais, capturadas
   navegando as 7 paginas de categoria (https://www.desenvolvesp.com.br/empresas/
   opcoes-de-credito/<categoria>), cada uma com prazo/carencia/taxa/elegibilidade
   estruturados na propria pagina publica.
4. BNB (Banco do Nordeste): curadoria manual verificada -- 1 linha (FNE Inovação),
   capturada da pagina oficial (estrutura rica: objetivo/publico/prazo por
   finalidade/garantias/limites por porte). O FNE tem dezenas de linhas por
   segmento/publico (rural, MPE, corporate, etc.) -- cobertura pequena e deliberada.

Nenhuma das 4 fontes usa scraping automatizado continuo (so a FINEP tem uma API
oficial estruturada ja consumida por outro modulo) -- BNDES/Desenvolve SP/BNB sao
atualizados manualmente, sob demanda, ate que scrapers dedicados sejam construidos
e verificados against a estrutura real (e razoavelmente estavel) de cada site.
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
    {
        # Achado via a API de busca real do site (WCMUtil/api/busca/) -- o portal WCM
        # do BNDES nao tem um indice/catalogo navegavel por clique, mas a busca interna
        # devolve URLs reais e estaveis de /financiamento/produto/<slug>. Conteudo
        # capturado via os acordeoes (.collapsible-header/.collapsible-body) da propria
        # pagina, que ficam fechados por padrao e nao aparecem no texto visivel comum.
        "instituicao": "BNDES",
        "nome_oficial": "Cartão BNDES",
        "nome_simplificado": "Cartão BNDES",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Crédito pré-aprovado para aquisição de bens e serviços credenciados no Portal de Operações do Cartão BNDES.",
        "descricao_completa": "Crédito pré-aprovado para aquisição de bens e serviços credenciados no Portal de Operações do Cartão BNDES. Financiamento de até 100% do item adquirido.",
        "modalidade": "Indireta",
        "tipo_apoio": "Financiamento (cartão de crédito)",
        "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional",
        "destinacao": "Aquisição de bens e serviços credenciados",
        "itens_financiaveis": "Bens e serviços credenciados no Portal de Operações do Cartão BNDES",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 2_000_000,
        "percentual_financiavel": "100% do item adquirido",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Definida mensalmente no Portal de Operações do Cartão BNDES; TAC de até 2% do limite de crédito concedido",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 48 prestações mensais, fixas e iguais",
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": "A critério do banco emissor (reais ou pessoais)",
        "restricoes": "Limite de crédito de até R$ 2 milhões por banco emissor (somável entre emissores diferentes)",
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Bancos emissores credenciados ao Cartão BNDES",
        "canal_contratacao": "Portal de Operações do Cartão BNDES",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/cartao-bndes",
        "data_vigencia": "Circular 36/2020, de 16.06.2025 e alterações posteriores",
        "trecho_fonte": (
            "\"Crédito pré-aprovado para aquisição de bens e serviços credenciados no "
            "Portal de Operações do Cartão BNDES... Até 48 prestações mensais, fixas e "
            "iguais... Limite de crédito de até R$ 2 milhões por banco emissor.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,  # produto cross-setorial (qualquer bem/servico credenciado), sem mapeamento honesto para 1 categoria
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO,
        "destinacao_padronizada": "Aquisição de bens e serviços",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "cartao de credito bens e servicos aquisicao",
    },
    {
        "instituicao": "BNDES",
        "nome_oficial": "BNDES Finem - Geração de energia",
        "nome_simplificado": "Finem Energia",
        "sigla": "Finem",
        "status": "aberta",
        "descricao_resumida": "Financiamento a projetos de geração de energia elétrica (apoio direto e indireto).",
        "descricao_completa": (
            "Financiamento a projetos de geração de energia elétrica. Apoio direto (solicitação "
            "feita diretamente ao BNDES): taxa composta pelo Custo Financeiro e Remuneração do "
            "BNDES. Empreendimentos de geração termelétrica a gás natural, biomassa e unidades de "
            "recuperação energética a partir de resíduos sólidos urbanos devem observar critérios "
            "ambientais específicos."
        ),
        "modalidade": "Direta e Indireta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Geração de energia elétrica",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional",
        "destinacao": "Geração de energia elétrica",
        "itens_financiaveis": "Projetos de geração de energia (termelétrica, biomassa, recuperação energética de resíduos, entre outros)",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": 40_000_000,
        "valor_maximo": None,
        "percentual_financiavel": "Até 80% do valor total do projeto, limitado a 100% dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro + Remuneração do BNDES (apoio direto)",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 24 anos de amortização",
        "carencia": "Até 6 meses após entrada em operação comercial",
        "amortizacao": "Determinada pela capacidade de pagamento do empreendimento/cliente/grupo econômico, máximo 24 anos",
        "garantias": "Apoio direto: reais (hipoteca, penhor, propriedade fiduciária, recebíveis) e/ou pessoais (fiança, aval); apoio indireto: negociadas com a instituição financeira credenciada",
        "restricoes": "Critérios ambientais específicos para geração termelétrica a gás natural, biomassa e resíduos sólidos urbanos",
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "BNDES (direto) ou instituições financeiras credenciadas (indireto)",
        "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-finem-energia",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Valor mínimo de financiamento: R$ 40 milhões... Até 80% do valor total do "
            "projeto, limitada a 100% dos itens financiáveis... limite máximo de 24 anos.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "INFRAESTRUTURA",
        "subsetor_padronizado": "ENERGIA ELÉTRICA",
        "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO,
        "destinacao_padronizada": "Geração de energia elétrica",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": "Geração de energia, biomassa, recuperação energética de resíduos",
        "sinonimos_termos": "energia eletricidade geracao termeletrica biomassa usina",
    },
    {
        "instituicao": "BNDES",
        "nome_oficial": "BNDES Automático - Projeto de Investimento",
        "nome_simplificado": "BNDES Automático",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Financiamento indireto (via instituições financeiras credenciadas) para projetos de investimento de qualquer setor.",
        "descricao_completa": (
            "Financiamento indireto para projetos de investimento, contratado através de "
            "instituições financeiras credenciadas. Taxa composta pelo Custo Financeiro, Taxa "
            "do BNDES e Taxa do Agente Financeiro, com condições diferenciadas por porte da "
            "empresa e setor (incentivado ou padrão)."
        ),
        "modalidade": "Indireta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Todos os setores (condições diferenciadas para setores prioritários/incentivados)",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Micro, pequenas, médias e grandes empresas",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional",
        "destinacao": "Projetos de investimento",
        "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": "Até 100% dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro (TFB/TLP/Taxa LCD/Taxa Pré FAT) + Taxa do BNDES (0,75% a 0,95% a.a. conforme porte/setor) + Taxa do Agente Financeiro",
        "indexador": "TLP",
        "spread": "Taxa do BNDES: 0,75% a.a. (MPME) a 0,95% a.a. (grandes empresas incentivadas)",
        "prazo_total": "Até 20 anos",
        "carencia": "Até 3 anos",
        "amortizacao": "Definida pela instituição financeira credenciada conforme capacidade de pagamento",
        "garantias": "Livre negociação com a instituição financeira credenciada; admite FGI (Tradicional ou PEAC) e FG BNDES-SEBRAE",
        "restricoes": "Taxa LCD: prazo total máximo de 120 meses e carência máxima de 24 meses",
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas",
        "canal_contratacao": "Instituições financeiras credenciadas",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-automatico",
        "data_vigencia": "Circular n° 15/2022, de 26.05.2022",
        "trecho_fonte": (
            "\"Até 100% dos itens financiáveis... O prazo de carência não poderá ultrapassar "
            "3 anos e o prazo total não poderá ultrapassar 20 anos.\" (capturado ao vivo da "
            "página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,  # produto cross-setorial (qualquer projeto de investimento), sem mapeamento honesto para 1 categoria
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": "Micro, pequenas, médias e grandes empresas",
        "destinacao_padronizada": "Projetos de investimento",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "investimento financiamento indireto agente financeiro credenciado",
    },
    {
        "instituicao": "BNDES",
        "nome_oficial": "Pronaf - Programa Nacional de Fortalecimento da Agricultura Familiar",
        "nome_simplificado": "Pronaf",
        "sigla": "Pronaf",
        "status": "aberta",
        "descricao_resumida": "Financiamento para custeio e investimentos na agricultura familiar.",
        "descricao_completa": (
            "Financiamento para custeio e investimentos em implantação, ampliação ou "
            "modernização da estrutura de produção, beneficiamento, industrialização e de "
            "serviços no estabelecimento rural ou em áreas comunitárias rurais próximas, "
            "visando à geração de renda e à melhora do uso da mão de obra familiar. Possui "
            "subprogramas: Custeio, Agroindústria, Mulher, Agroecologia, Bioeconomia, Mais "
            "Alimentos, Jovem e Microcrédito (Grupo B)."
        ),
        "modalidade": "Indireta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agricultura familiar",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Agricultores e produtores rurais familiares (pessoas físicas e jurídicas), cooperativas",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional",
        "destinacao": "Custeio e investimento na agricultura familiar",
        "itens_financiaveis": "Implantação, ampliação ou modernização da estrutura de produção, beneficiamento, industrialização e serviços rurais",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": NAO_INFORMADO,
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": NAO_INFORMADO,
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": "Enquadramento no Pronaf (agricultor/produtor rural familiar)",
        "agente_financeiro": "Instituições financeiras credenciadas",
        "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/pronaf",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Financiamento para custeio e investimentos em implantação, ampliação ou "
            "modernização da estrutura de produção... visando à geração de renda e à melhora "
            "do uso da mão de obra familiar.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": "Agricultura familiar",
        "destinacao_padronizada": "Agricultura familiar",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": "Agroecologia, bioeconomia (subprogramas)",
        "sinonimos_termos": "agricultura familiar rural custeio agroindustria agroecologia",
    },
    {
        "instituicao": "BNDES",
        "nome_oficial": "BNDES Microcrédito - Condições ao Microempreendedor",
        "nome_simplificado": "BNDES Microcrédito",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Microcrédito produtivo orientado para microempreendedores.",
        "descricao_completa": (
            "Linha Microcrédito Produtivo Orientado, com taxa de juros efetiva máxima de até 4% "
            "ao mês e TAC de até 3% do valor do crédito concedido, conforme Resolução CMN nº "
            "4.854/2020."
        ),
        "modalidade": "Indireta",
        "tipo_apoio": "Microcrédito",
        "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Microempreendedor",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional",
        "destinacao": NAO_INFORMADO,
        "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 21_000,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Até 4% a.m. (taxa efetiva máxima) + TAC de até 3% do valor do crédito",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Negociado com o agente operador, mínimo de 120 dias",
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": "Negociadas com o agente operador (conforme art. 5º da Lei 13.636/2018)",
        "restricoes": "Limite de R$ 80 mil somando saldos devedores de crédito do tomador no Sistema Financeiro Nacional (exceto crédito habitacional)",
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Agentes operadores de microcrédito credenciados",
        "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-microcredito-empreendedor",
        "data_vigencia": "Resolução CMN nº 4.854, de 24.09.2020",
        "trecho_fonte": (
            "\"Taxa de juros efetiva máxima de até 4% ao mês... Até R$ 21 mil por instituição "
            "financeira. Respeitando-se o limite de R$ 80 mil.\" (capturado ao vivo da página "
            "oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,  # microcredito cross-setorial, sem mapeamento honesto para 1 categoria
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": "Microempreendedor",
        "destinacao_padronizada": "Microcrédito produtivo orientado",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "microcredito microempreendedor MEI credito popular",
    },
]


def seed_bndes_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _BNDES_MANUAL])


def _linha_desenvolve_sp(nome, categoria_nome, categoria_url, valor_max, prazo, carencia, taxa, elegiveis, trecho):
    """Helper pra reduzir repeticao -- cada linha de credito da Desenvolve SP e
    exibida dentro de uma pagina de CATEGORIA (ex: "Projetos de Investimento"), com
    cards padronizados (valor/prazo/carencia/taxa/elegibilidade), sem descricao longa,
    garantias ou contrapartida detalhadas na propria pagina publica -- por isso os
    campos NAO capturados ficam como NAO_INFORMADO em vez de inventados. A MESMA linha
    pode aparecer em mais de uma categoria com termos DIFERENTES (confirmado: ex.
    "Financiamento ao Investimento Paulista" tem prazo/carencia diferentes em
    "Projetos de Investimento" vs "Máquinas e Equipamentos Isolados") -- cada
    combinacao (linha, categoria) e uma linha_incentivada distinta (url_oficial
    diferente por categoria), refletindo o termo real daquele contexto."""
    return {
        "instituicao": "Desenvolve SP",
        "nome_oficial": nome,
        "nome_simplificado": nome,
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": f"Linha de crédito da categoria \"{categoria_nome}\" da Desenvolve SP.",
        "descricao_completa": NAO_INFORMADO,
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": categoria_nome,
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": ", ".join(elegiveis),
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Estado de São Paulo",
        "destinacao": categoria_nome,
        "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": valor_max,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": taxa,
        "indexador": "IPCA" if "IPCA" in taxa else ("TR" if "TR" in taxa else NAO_INFORMADO),
        "spread": NAO_INFORMADO,
        "prazo_total": prazo,
        "carencia": carencia or NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": ", ".join(elegiveis),
        "agente_financeiro": "Desenvolve SP",
        "canal_contratacao": "Simulação de crédito no site oficial",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": categoria_url,
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": trecho,
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        # Cruzamento com a taxonomia nativa do BNDES (item 8): so "Desenvolve Agro" e
        # genuinamente setorial (agropecuaria) -- as outras 6 categorias (Investimento,
        # Giro, Maquinas, Inovacao, Sustentaveis, Mulher) sao PRODUTOS TRANSVERSAIS
        # (aplicaveis a qualquer setor de negocio), entao mapear para 1 categoria BNDES
        # seria arbitrario/enganoso -- ficam NAO_INFORMADO de proposito.
        "setor_padronizado": "AGROPECUÁRIA" if categoria_nome == "Desenvolve Agro" else NAO_INFORMADO,
        "subsetor_padronizado": "AGROPECUÁRIA" if categoria_nome == "Desenvolve Agro" else None,
        "cnaes_relacionados": None,
        "porte_padronizado": ", ".join(elegiveis),
        "destinacao_padronizada": categoria_nome,
        "tecnologias_relacionadas": None,
        "temas_inovacao": categoria_nome if "Inova" in categoria_nome else None,
        "temas_sustentabilidade": categoria_nome if "Sustent" in categoria_nome else None,
        "sinonimos_termos": None,
    }


_DESENVOLVE_SP_MANUAL = [
    _linha_desenvolve_sp("Agro Máquinas", "Desenvolve Agro", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/desenvolve-agro",
                         5_000_000, "60 meses", None, "1.06 % a.m.", ["Pequeno Produtor rural", "Médio-Grande Produtor Rural"],
                         "Crédito de até R$ 5 milhões / Linha Agro Máquinas / Prazo 60 meses / Taxa de juros 1.06% a.m. (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Irriga + SP", "Desenvolve Agro", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/desenvolve-agro",
                         5_000_000, "60 meses", "18 meses", "0.39 % a.m.", ["Pequeno Produtor rural", "Médio-Grande Produtor Rural"],
                         "Crédito de até R$ 5 milhões / Linha Irriga + SP / Prazo 60 meses / Carência 18 meses / Taxa 0.39% a.m. (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Crédito simplificado Giro", "Capital de giro", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/capital-de-giro",
                         300_000, "36 meses", "1 mês", "1.67 % a.m.", ["Micro", "Pequena"],
                         "Crédito de até R$ 300 mil / Linha Crédito simplificado Giro / Prazo 36 meses / Carência 1 mês / Taxa 1.67% a.m. (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Linha Giro Desenvolve", "Capital de giro", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/capital-de-giro",
                         10_000_000, "60 meses", "12 meses", "1.4 % a.m. + IPCA", ["Médias", "Média-Grande", "Grande"],
                         "Crédito de até R$ 10 milhões / Linha Giro Desenvolve / Prazo 60 meses / Carência 12 meses / Taxa 1.4% a.m. + IPCA (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Financiamento ao Investimento Paulista", "Projetos de Investimento", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/projetos-de-investimento",
                         30_000_000, "120 meses", "36 meses", "0.8 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Média-Grande", "Pré-operacional"],
                         "Crédito de até R$ 30 milhões / Financiamento ao Investimento Paulista / Prazo 120 meses / Carência 36 meses / Taxa 0.8% a.m. + IPCA (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Desenvolve Mais Inclusão", "Projetos de Investimento", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/projetos-de-investimento",
                         10_000_000, "120 meses", "36 meses", "0.64 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Pré-operacional"],
                         "Crédito de até R$ 10 milhões / Desenvolve Mais Inclusão / Prazo 120 meses / Carência 36 meses / Taxa 0.64% a.m. + IPCA (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Linha Força Empreendedora", "Projetos de Investimento", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/projetos-de-investimento",
                         700_000, "60 meses", "12 meses", "0.8 % a.m. + IPCA", ["Micro", "Pequena"],
                         "Crédito de até R$ 700 mil / Linha Força Empreendedora / Prazo 60 meses / Carência 12 meses / Taxa 0.8% a.m. + IPCA (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Linha Desenvolve Centro", "Projetos de Investimento", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/projetos-de-investimento",
                         5_000_000, "120 meses", "36 meses", "0.63 % a.m. + IPCA", ["Micro", "Pequena", "Médias"],
                         "Crédito de até R$ 5 milhões / Linha Desenvolve Centro / Prazo 120 meses / Carência 36 meses / Taxa 0.63% a.m. + IPCA (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Linha Rádio Difusão", "Projetos de Investimento", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/projetos-de-investimento",
                         30_000_000, "120 meses", "36 meses", "0.58 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Média-Grande"],
                         "Crédito de até R$ 30 milhões / Linha Rádio Difusão / Prazo 120 meses / Carência 36 meses / Taxa 0.58% a.m. + IPCA (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Linha Economia Verde", "Projetos Sustentáveis", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/projetos-sustentaveis",
                         30_000_000, "120 meses", "36 meses", "0.64 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Média-Grande", "Pré-operacional"],
                         "Crédito de até R$ 30 milhões / Linha Economia Verde / Prazo 120 meses / Carência 36 meses / Taxa 0.64% a.m. + IPCA (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("FINEP Inovacred", "Projetos de Inovação", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/projetos-de-inovacao",
                         30_000_000, "96 meses", "24 meses", "0.49 % a.m. + TR", ["Micro", "Pequena", "Médias", "Média-Grande"],
                         "Crédito de até R$ 30 milhões / FINEP Inovacred / Prazo 96 meses / Carência 24 meses / Taxa 0.49% a.m. + TR (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Linha Incentivo à Tecnologia", "Projetos de Inovação", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/projetos-de-inovacao",
                         30_000_000, "120 meses", "36 meses", "0.63 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Média-Grande", "Pré-operacional"],
                         "Crédito de até R$ 30 milhões / Linha Incentivo à Tecnologia / Prazo 120 meses / Carência 36 meses / Taxa 0.63% a.m. + IPCA (capturado ao vivo em 2026-09-04)"),
    _linha_desenvolve_sp("Financiamento ao Investimento Paulista", "Máquinas e Equipamentos Isolados", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/maquinas-e-equipamentos-isolados",
                         30_000_000, "60 meses", "12 meses", "0.8 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Média-Grande", "Pré-operacional"],
                         "Crédito de até R$ 30 milhões / Financiamento ao Investimento Paulista / Prazo 60 meses / Carência 12 meses / Taxa 0.8% a.m. + IPCA (capturado ao vivo em 2026-09-04, categoria Máquinas e Equipamentos Isolados)"),
    _linha_desenvolve_sp("Linha Desenvolve Mulher", "Máquinas e Equipamentos Isolados", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/maquinas-e-equipamentos-isolados",
                         10_000_000, "60 meses", "12 meses", "0.64 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Pré-operacional"],
                         "Crédito de até R$ 10 milhões / Linha Desenvolve Mulher / Prazo 60 meses / Carência 12 meses / Taxa 0.64% a.m. + IPCA (capturado ao vivo em 2026-09-04, categoria Máquinas e Equipamentos Isolados)"),
    _linha_desenvolve_sp("Linha Economia Verde", "Máquinas e Equipamentos Isolados", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/maquinas-e-equipamentos-isolados",
                         30_000_000, "60 meses", "12 meses", "0.64 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Média-Grande", "Pré-operacional"],
                         "Crédito de até R$ 30 milhões / Linha Economia Verde / Prazo 60 meses / Carência 12 meses / Taxa 0.64% a.m. + IPCA (capturado ao vivo em 2026-09-04, categoria Máquinas e Equipamentos Isolados)"),
    _linha_desenvolve_sp("Linha Rádio Difusão", "Máquinas e Equipamentos Isolados", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/maquinas-e-equipamentos-isolados",
                         30_000_000, "60 meses", "12 meses", "0.58 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Média-Grande"],
                         "Crédito de até R$ 30 milhões / Linha Rádio Difusão / Prazo 60 meses / Carência 12 meses / Taxa 0.58% a.m. + IPCA (capturado ao vivo em 2026-09-04, categoria Máquinas e Equipamentos Isolados)"),
    _linha_desenvolve_sp("Linha Desenvolve Mulher", "Desenvolve Mulher", "https://www.desenvolvesp.com.br/empresas/opcoes-de-credito/desenvolve-mulher",
                         10_000_000, "120 meses", "36 meses", "0.64 % a.m. + IPCA", ["Micro", "Pequena", "Médias", "Pré-operacional"],
                         "Crédito de até R$ 10 milhões / Linha Desenvolve Mulher / Prazo 120 meses / Carência 36 meses / Taxa 0.64% a.m. + IPCA (capturado ao vivo em 2026-09-04, categoria Desenvolve Mulher)"),
]


def seed_desenvolve_sp_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _DESENVOLVE_SP_MANUAL])


# BNB (Banco do Nordeste): curadoria manual VERIFICADA -- FNE Inovacao capturado ao
# vivo da pagina oficial (estrutura rica: objetivo/publico/prazo por finalidade/
# garantias/limites de financiamento por porte). Cobertura pequena e deliberada
# (o catalogo completo do FNE tem dezenas de linhas por segmento/publico -- ver
# docstring do modulo).
_BNB_MANUAL = [
    {
        "instituicao": "BNB",
        "nome_oficial": "FNE Inovação",
        "nome_simplificado": "FNE Inovação",
        "sigla": "FNE",
        "status": "aberta",
        "descricao_resumida": "Programa de Financiamento à Inovação para empresas e empreendimentos rurais, com recursos do FNE.",
        "descricao_completa": (
            "Promove a inovação em produtos, serviços, processos e métodos organizacionais nos "
            "empreendimentos. Nos setores não rurais: implementação de produto/serviço/processo novo "
            "ou significativamente melhorado, incluindo obras, bens de capital e capital de giro "
            "associado ao investimento. No setor rural: projetos de inovação tecnológica em "
            "empreendimentos agropecuários, incluindo investimento rural e custeio associado."
        ),
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Todos os setores (rural e não rural)",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Microempreendedor Individual (MEI), empresas de todos os portes, produtores/cooperativas/associações rurais",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nordeste e Norte de Minas Gerais e Espírito Santo (área de atuação do FNE)",
        "destinacao": "Inovação em produtos, serviços, processos e métodos organizacionais",
        "itens_financiaveis": "Obras e aquisição de bens de capital; capital de giro associado ao investimento; consultorias de acompanhamento/monitoramento de impactos sociais e ambientais",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": (
            "Miniprodutor/microempresa: 100%; Pequeno produtor/pequena empresa: 100%; "
            "Pequeno-médio: 100%; Médio I: 95%; Médio II: 85%; Grande (PRDNE): 80%; Grande (geral): 50%"
        ),
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Setor Rural: Resolução CMN nº 5.329/2026; Demais setores: Lei nº 10.177/2001 e Resolução CMN nº 5.013/2022",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Investimento Fixo (Rural e Não Rural): até 15 anos; Investimento Semifixo (Rural): até 8 anos",
        "carencia": "Investimento Fixo: até 5 anos; Investimento Semifixo (Rural): até 3 anos; +1 ano adicional para produtoras/empresas com controle/participação feminina >40%",
        "amortizacao": NAO_INFORMADO,
        "garantias": "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": "Cadastro e limite de crédito aprovados no Banco do Nordeste",
        "agente_financeiro": "Banco do Nordeste (Fundo Constitucional de Financiamento do Nordeste - FNE)",
        "canal_contratacao": "Gerente de relacionamento / agências do Banco do Nordeste",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": "Projeto de Financiamento ou Proposta de Crédito",
        "url_oficial": "https://www.bnb.gov.br/fne-inovacao",
        "data_vigencia": "Resolução CMN nº 5.329/2026 (rural) e nº 5.013/2022 (demais setores)",
        "trecho_fonte": (
            "\"Promover a inovação em produtos, serviços, processos e métodos organizacionais nos "
            "empreendimentos... Fonte de Recursos: Fundo Constitucional de Financiamento do Nordeste "
            "(FNE)\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,  # taxonomia propria do FNE (rural/nao-rural), sem de-para com as 4 categorias BNDES ainda
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": "Todos os portes",
        "destinacao_padronizada": "Inovação",
        "tecnologias_relacionadas": None,
        "temas_inovacao": "Inovação em produtos, processos e métodos organizacionais",
        "temas_sustentabilidade": None,
        "sinonimos_termos": "inovacao tecnologia P&D&I pesquisa e desenvolvimento nordeste",
    },
]


def seed_bnb_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _BNB_MANUAL])


def build_linhas_incentivadas():
    conn = get_connection()
    try:
        n_finep = importar_finep_editais(conn)
        n_bndes = seed_bndes_manual(conn)
        n_desenvolve_sp = seed_desenvolve_sp_manual(conn)
        n_bnb = seed_bnb_manual(conn)
        total = conn.execute("SELECT COUNT(*) FROM linhas_incentivadas").fetchone()[0]
    finally:
        conn.close()
    print(
        f"linhas_incentivadas: {n_finep} da FINEP (editais_raw) + {n_bndes} do BNDES + "
        f"{n_desenvolve_sp} da Desenvolve SP + {n_bnb} do BNB (curadoria manual verificada) "
        f"processadas -- {total} linhas no total."
    )


if __name__ == "__main__":
    build_linhas_incentivadas()
