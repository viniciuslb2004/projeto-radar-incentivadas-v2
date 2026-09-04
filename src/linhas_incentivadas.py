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


def _linha_bndes_finem(nome_oficial, nome_simplificado, setor_padronizado, subsetor_padronizado,
                        descricao_resumida, descricao_completa, setores_elegiveis, destinacao,
                        valor_minimo, percentual_financiavel, taxa_completa, prazo_total, carencia,
                        url_slug, trecho_fonte, restricoes=NAO_INFORMADO, itens_financiaveis=NAO_INFORMADO,
                        temas_sustentabilidade=None, temas_inovacao=None, sinonimos_termos=None,
                        indexador="TLP", spread=NAO_INFORMADO, valor_maximo=None):
    """Helper para a familia BNDES Finem -- todas as ~10 paginas capturadas nesta sessao
    compartilham a MESMA estrutura de acordeoes (Taxa de juros / Valor minimo / Participacao /
    Prazos / Garantias) e o mesmo texto padrao de garantias (direto: reais e/ou pessoais;
    indireto: negociadas com o agente financeiro credenciado), so o conteudo especifico de
    cada setor muda. Reduz repeticao/risco de erro de digitacao entre as ~10 entradas."""
    return {
        "instituicao": "BNDES",
        "nome_oficial": nome_oficial,
        "nome_simplificado": nome_simplificado,
        "sigla": "Finem",
        "status": "aberta",
        "descricao_resumida": descricao_resumida,
        "descricao_completa": descricao_completa,
        "modalidade": "Direta e Indireta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": setores_elegiveis,
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional",
        "destinacao": destinacao,
        "itens_financiaveis": itens_financiaveis,
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": valor_minimo,
        "valor_maximo": valor_maximo,
        "percentual_financiavel": percentual_financiavel,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": taxa_completa,
        "indexador": indexador,
        "spread": spread,
        "prazo_total": prazo_total,
        "carencia": carencia,
        "amortizacao": NAO_INFORMADO,
        "garantias": (
            "Apoio direto: garantias reais (hipoteca, penhor, propriedade fiduciária, "
            "recebíveis etc.) e/ou pessoais (fiança, aval), definidas na análise da operação; "
            "apoio indireto: negociadas entre a instituição financeira credenciada e o cliente."
        ),
        "restricoes": restricoes,
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "BNDES (direto) ou instituições financeiras credenciadas (indireto)",
        "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": f"https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/{url_slug}",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": f"{trecho_fonte} (capturado ao vivo da página oficial em 2026-09-04)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": setor_padronizado,
        "subsetor_padronizado": subsetor_padronizado,
        "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO,
        "destinacao_padronizada": destinacao,
        "tecnologias_relacionadas": None,
        "temas_inovacao": temas_inovacao,
        "temas_sustentabilidade": temas_sustentabilidade,
        "sinonimos_termos": sinonimos_termos,
    }


# Expansao de cobertura BNDES (sessao 2026-09-04): mais ~40 linhas encontradas via a API de
# busca real do site (WCMUtil/api/busca/, ver docstring do modulo) e capturadas ao vivo
# (acordeoes .collapsible-header/.collapsible-body de cada pagina). Paginas tentadas SEM
# sucesso (conteudo vazio/so links, sem termos financeiros nos acordeoes -- NAO incluidas
# aqui): bndes-finem-meio-ambiente (hub, sem acordeoes), bndes-pro-transporte (hub),
# franquias-bndes, fundo-amazonia (fundo nao-reembolsavel, pagina so linka doc estrategico),
# programa-prioritario-bndes-rota-2030 (BNDES Mover, hub sem acordeoes), programa-bndes-mais-
# inovacao-investimento (so um link para pagina de apoio indireto, sem termos proprios),
# bndes-pro-cdd-credito-rural (navegacao falhou repetidamente nesta sessao).
_BNDES_MANUAL_EXPANSAO = [
    _linha_bndes_finem(
        "BNDES Finem - Telecomunicações", "Finem Telecom", "INFRAESTRUTURA", "TELECOMUNICAÇÕES",
        "Financiamento a projetos de implantação, expansão e modernização de redes de telecomunicações.",
        "Financiamento (direto e indireto) a investimentos em telecomunicações, incluindo "
        "universalização da banda larga e implantação/expansão/modernização de redes.",
        "Telecomunicações", "Implantação, expansão e modernização de redes de telecomunicações",
        40_000_000, "MPMEs: até 100%; universalização da banda larga: até 80%; implantação/expansão/"
        "modernização de redes: até 60%",
        "Apoio direto: Custo Financeiro + Remuneração do BNDES; apoio indireto: Custo Financeiro + "
        "Taxa do BNDES + Taxa do Agente Financeiro",
        NAO_INFORMADO, "Até 6 meses após a entrada do projeto em operação comercial",
        "bndes-finem-telecomunicacoes",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Micro, pequenas e médias empresas: até 100%. "
        "Investimentos para a universalização da banda larga até 80%; implantação, expansão e "
        "modernização de redes de telecomunicações até 60%.\"",
        restricoes="Valor mínimo reduzido a R$ 20 milhões para provedores regionais classificados como "
        "\"Prestadores de Pequeno Porte\" (PPP) pela ANATEL",
        sinonimos_termos="telecomunicacoes banda larga redes internet provedores",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Saneamento", "Finem Saneamento", "INFRAESTRUTURA", "SANEAMENTO",
        "Financiamento a projetos de saneamento básico (água e esgoto).",
        "Financiamento (direto e indireto) a projetos de saneamento, admitindo subscrição de "
        "debêntures pelo BNDES para execução do projeto.",
        "Saneamento básico", "Projetos de saneamento (água e esgoto)",
        20_000_000, "Estados e municípios: até 90% do valor total do projeto, limitada a 100% dos itens "
        "financiáveis; demais clientes: até 95%, limitada a 100% dos itens financiáveis",
        "Apoio direto: Custo Financeiro + Remuneração do BNDES; apoio indireto: Custo Financeiro + "
        "Taxa do BNDES + Taxa do Agente Financeiro",
        "Até 34 anos", NAO_INFORMADO,
        "bndes-finem-saneamento",
        "\"Valor mínimo de financiamento: R$ 20 milhões... Para estados e municípios, até 90% do valor "
        "total do projeto... O prazo máximo de financiamento é de 34 anos.\"",
        restricoes="O BNDES pode subscrever até 50% do valor das debêntures emitidas pelo beneficiário "
        "para execução do projeto (soma financiamento + debêntures limitada a 80% dos itens financiáveis)",
        sinonimos_termos="saneamento agua esgoto tratamento residuos",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Agropecuária", "Finem Agropecuária", "AGROPECUÁRIA", "AGROPECUÁRIA",
        "Financiamento a projetos de investimento no setor agropecuário, com condições "
        "específicas para projetos de aquicultura.",
        "Financiamento (direto e indireto) a projetos de investimento agropecuário; para projetos "
        "de aquicultura o valor mínimo é reduzido e o capital de giro associado pode chegar a 100%.",
        "Agropecuária, aquicultura", "Projetos de investimento agropecuário",
        40_000_000, "MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,5% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,5% a.a.; apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 20 anos", NAO_INFORMADO,
        "bndes-finem-agropecuaria",
        "\"Valor mínimo de financiamento: R$ 40 milhões (esteira corporativa)... Para projetos de "
        "aquicultura... o valor mínimo de financiamento será de R$ 3 milhões. O apoio ao capital de giro "
        "associado a projetos de aquicultura poderá ser de até 100% do financiamento.\"",
        restricoes="Para aquicultura, valor mínimo reduzido a R$ 3 milhões; critérios ambientais "
        "específicos para o setor sucroalcooleiro (processamento de cana-de-açúcar)",
        sinonimos_termos="agropecuaria aquicultura pecuaria producao rural",
        spread="1,5% a.a. (direto) / 1,45% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Mobilidade urbana", "Finem Mobilidade Urbana", "INFRAESTRUTURA", "MOBILIDADE URBANA",
        "Financiamento a projetos de investimento em mobilidade urbana.",
        "Financiamento (direto e indireto) a projetos de mobilidade urbana, admitindo subscrição "
        "de debêntures pelo BNDES para execução do projeto.",
        "Mobilidade urbana", "Projetos de investimento em mobilidade urbana",
        40_000_000, "Estados e municípios: até 90% do valor total do projeto, limitada a 100% dos itens "
        "financiáveis; MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,5% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,4% a.a.; apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 34 anos", NAO_INFORMADO,
        "bndes-finem-mobilidade-urbana",
        "\"Valor mínimo de financiamento: R$ 40 milhões. O Valor Mínimo de Financiamento fica reduzido a "
        "R$ 20 milhões para... Saúde... Saneamento... Inovação... região Norte e Nordeste... O prazo "
        "máximo de financiamento é de 34 anos.\"",
        restricoes="Valor mínimo reduzido a R$ 20 milhões para entes da Administração Pública Direta, "
        "saúde, saneamento, inovação, provedores regionais, região Norte/Nordeste, educação e "
        "qualificação profissional, parques e florestas; BNDES pode subscrever até 50% das debêntures",
        sinonimos_termos="mobilidade urbana transporte publico onibus metro BRT",
        spread="1,5%/1,4% a.a. (direto) / 1,45% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Tecnologia da Informação", "Finem TI", "COMERCIO/SERVICOS", None,
        "Financiamento a projetos de investimento no setor de Tecnologia da Informação.",
        "Financiamento (direto e indireto) a projetos de TI, com taxa de juros direta composta "
        "por Custo Financeiro, Taxa do BNDES e Taxa de Risco de Crédito variável conforme o "
        "risco do cliente. Admite operações de capital de risco (subscrição de valores mobiliários).",
        "Tecnologia da Informação", "Projetos de investimento em Tecnologia da Informação",
        40_000_000, "Até 80% do valor total dos itens apoiáveis do projeto",
        "Apoio direto: Custo Financeiro (TLP ou Selic) + Taxa do BNDES 1,3% a.a. + Taxa de Risco de "
        "Crédito (variável); apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente Financeiro",
        NAO_INFORMADO, NAO_INFORMADO,
        "bndes-finem-ti",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Até 80% do valor total dos itens apoiáveis do "
        "projeto... Custo financeiro TLP ou Selic + Taxa BNDES 1,3% ao ano + Taxa de Risco de Crédito.\"",
        sinonimos_termos="tecnologia da informacao TI software hardware capital de risco",
        spread="1,3% a.a. + risco de crédito (direto) / 1,45% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Infraestrutura Logística", "Finem Logística", "INFRAESTRUTURA", "LOGÍSTICA",
        "Financiamento a projetos de investimento em infraestrutura logística (rodovias, "
        "ferrovias, hidrovias e demais empreendimentos).",
        "Financiamento (direto e indireto) a projetos de infraestrutura logística, com prazo "
        "máximo diferenciado para rodovias/ferrovias/hidrovias (34 anos) frente aos demais "
        "empreendimentos (24 anos).",
        "Infraestrutura logística", "Projetos de investimento em infraestrutura logística",
        40_000_000, "Estados e municípios: até 90% do valor total do projeto, limitada a 100% dos itens "
        "financiáveis; MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,5% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,4% a.a.; apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente "
        "Financeiro",
        "Rodovias, ferrovias e hidrovias: até 34 anos; demais empreendimentos: até 24 anos", NAO_INFORMADO,
        "bndes-finem-infraestrutura-logistica",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Rodovias, ferrovias e hidrovias: 34 anos; "
        "Demais empreendimentos: 24 anos.\"",
        restricoes="Valor mínimo reduzido a R$ 20 milhões para entes da Administração Pública Direta, "
        "saúde, saneamento, inovação, provedores regionais, região Norte/Nordeste, educação e "
        "qualificação profissional, parques e florestas",
        sinonimos_termos="logistica rodovias ferrovias hidrovias infraestrutura transporte de cargas",
        spread="1,5%/1,4% a.a. (direto) / 1,45% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Meio Ambiente - Eficiência Energética", "Finem Eficiência Energética", NAO_INFORMADO, None,
        "Financiamento a projetos de eficiência energética.",
        "Financiamento (direto e indireto) a projetos de eficiência energética, com taxa de "
        "juros direta reduzida frente às demais linhas Finem.",
        "Eficiência energética (qualquer setor)", "Projetos de eficiência energética",
        40_000_000, "Estados e municípios: até 90% do valor total do projeto, limitada a 100% dos itens "
        "financiáveis; MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,1% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,0% a.a.; apoio indireto: TLP + Taxa do BNDES 1,05% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 20 anos", NAO_INFORMADO,
        "bndes-finem-eficiencia-energetica",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Empresas Custo financeiro TLP + Remuneração do "
        "BNDES A partir de 1,1% ao ano... O prazo máximo de financiamento é de 20 anos.\"",
        restricoes="Valor mínimo reduzido a R$ 20 milhões para entes da Administração Pública Direta, "
        "saúde, saneamento, inovação, provedores regionais, região Norte/Nordeste, educação e "
        "qualificação profissional, parques e florestas",
        temas_sustentabilidade="Eficiência energética",
        sinonimos_termos="eficiencia energetica economia de energia meio ambiente",
        spread="1,1%/1,0% a.a. (direto) / 1,05% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Educação, Saúde e Assistência Social", "Finem Educação e Saúde", "COMERCIO/SERVICOS", None,
        "Financiamento a projetos de investimento nos setores de educação, saúde e assistência "
        "social.",
        "Financiamento (direto e indireto) a projetos de investimento em educação, saúde e "
        "assistência social.",
        "Educação, saúde e assistência social", "Projetos de investimento em educação, saúde e assistência social",
        40_000_000, "Estados e municípios: até 90% do valor total do projeto, limitada a 100% dos itens "
        "financiáveis; MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,5% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,4% a.a.; apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 20 anos", NAO_INFORMADO,
        "bndes-finem-educacao-saude",
        "\"Valor mínimo de financiamento: R$ 40 milhões... O prazo máximo de financiamento é de 20 anos... "
        "determinado em função da capacidade de pagamento do empreendimento.\"",
        restricoes="Valor mínimo reduzido a R$ 20 milhões para entes da Administração Pública Direta, "
        "saúde, saneamento, inovação, provedores regionais, região Norte/Nordeste, educação e "
        "qualificação profissional, parques e florestas",
        sinonimos_termos="educacao saude assistencia social escolas hospitais",
        spread="1,5%/1,4% a.a. (direto) / 1,45% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Conteúdos culturais e editoriais", "Finem Conteúdos Culturais", "COMERCIO/SERVICOS", None,
        "Financiamento a projetos de investimento em conteúdos culturais e editoriais.",
        "Financiamento (direto e indireto) a projetos de investimento voltados a conteúdos "
        "culturais e editoriais.",
        "Conteúdos culturais e editoriais", "Projetos de investimento em conteúdos culturais e editoriais",
        40_000_000, "MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,5% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,5% a.a.; apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 20 anos", NAO_INFORMADO,
        "bndes-finem-conteudos-culturais",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Para MPMEs, até 100% dos itens financiáveis... "
        "limitado a 20 anos.\"",
        sinonimos_termos="cultura conteudo editorial midia audiovisual publicacoes",
        spread="1,5% a.a. (direto) / 1,45% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem – Investimento em capacidade de produção de bens de capital", "Finem Bens de Capital",
        "INDUSTRIA", None,
        "Financiamento a projetos de investimento em capacidade de produção de bens de capital.",
        "Financiamento (direto e indireto) a projetos de ampliação da capacidade de produção de "
        "bens de capital (indústria de máquinas e equipamentos).",
        "Indústria de bens de capital", "Projetos de investimento em capacidade de produção de bens de capital",
        40_000_000, "MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,5% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,5% a.a.; apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 20 anos", NAO_INFORMADO,
        "bndes-finem-producao-bk",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Determinado em função da capacidade de "
        "pagamento do empreendimento, limitado a 20 anos... Não será aceito como garantia o penhor de "
        "direitos creditórios decorrentes de aplicação financeira.\"",
        restricoes="Não será aceito como garantia o penhor de direitos creditórios decorrentes de "
        "aplicação financeira",
        sinonimos_termos="bens de capital maquinas equipamentos industria producao",
        spread="1,5% a.a. (direto) / 1,45% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Meio Ambiente - Recuperação de passivos ambientais", "Finem Passivos Ambientais",
        NAO_INFORMADO, None,
        "Financiamento a projetos de recuperação de passivos ambientais.",
        "Financiamento (direto e indireto) a projetos de recuperação de passivos ambientais, "
        "com taxa de juros direta reduzida frente às demais linhas Finem.",
        "Recuperação de passivos ambientais (qualquer setor)", "Recuperação de passivos ambientais",
        40_000_000, "Estados e municípios: até 90% do valor total do projeto, limitada a 100% dos itens "
        "financiáveis; MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,1% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,0% a.a.; apoio indireto: TLP + Taxa do BNDES 1,05% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 20 anos", NAO_INFORMADO,
        "bndes-finem-meio-ambiente-recuperacao-passivos-ambientais",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Empresas Custo financeiro TLP + Remuneração do "
        "BNDES A partir de 1,1% ao ano... O prazo máximo de financiamento é de 20 anos.\"",
        restricoes="Valor mínimo reduzido a R$ 20 milhões para entes da Administração Pública Direta, "
        "saúde, saneamento, inovação, provedores regionais, região Norte/Nordeste, educação e "
        "qualificação profissional, parques e florestas",
        temas_sustentabilidade="Recuperação de passivos ambientais",
        sinonimos_termos="meio ambiente passivo ambiental recuperacao area degradada",
        spread="1,1%/1,0% a.a. (direto) / 1,05% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Segurança Pública", "Finem Segurança Pública", NAO_INFORMADO, None,
        "Financiamento a projetos de investimento em segurança pública.",
        "Financiamento (direto e indireto) a projetos de investimento em segurança pública, com "
        "taxa de juros direta reduzida frente às demais linhas Finem.",
        "Segurança pública", "Projetos de investimento em segurança pública",
        40_000_000, "Estados e municípios: até 90% do valor total do projeto, limitada a 100% dos itens "
        "financiáveis; MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,1% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,0% a.a.; apoio indireto: TLP + Taxa do BNDES 1,05% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 20 anos", NAO_INFORMADO,
        "bndes-finem-seguranca",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Empresas Custo financeiro TLP + Remuneração do "
        "BNDES A partir de 1,1% ao ano... O prazo máximo de financiamento é de 20 anos.\"",
        restricoes="Valor mínimo reduzido a R$ 20 milhões para entes da Administração Pública Direta, "
        "saúde, saneamento, inovação, provedores regionais, região Norte/Nordeste, educação e "
        "qualificação profissional, parques e florestas",
        sinonimos_termos="seguranca publica policia sistema prisional",
        spread="1,1%/1,0% a.a. (direto) / 1,05% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "BNDES Finem - Infraestruturas culturais", "Finem Infraestruturas Culturais", "INFRAESTRUTURA", "CULTURA",
        "Financiamento a projetos de investimento em infraestruturas culturais.",
        "Financiamento (direto e indireto) a projetos de investimento em infraestruturas "
        "culturais (construção/modernização de espaços e equipamentos culturais).",
        "Infraestruturas culturais", "Projetos de investimento em infraestruturas culturais",
        40_000_000, "MPMEs: até 100% dos itens financiáveis; demais clientes: até 80% do valor total do "
        "projeto, limitada a 100% dos itens financiáveis",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,5% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,5% a.a.; apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente "
        "Financeiro",
        "Até 20 anos", NAO_INFORMADO,
        "bndes-finem-infraestruturas-culturais",
        "\"Valor mínimo de financiamento: R$ 40 milhões... Para MPMEs, até 100% dos itens financiáveis... "
        "limitado a 20 anos.\"",
        sinonimos_termos="cultura infraestrutura cultural museus teatros centros culturais",
        spread="1,5% a.a. (direto) / 1,45% a.a. (indireto)",
    ),
    _linha_bndes_finem(
        "Investimento em instalações e/ou serviços para refino de petróleo, biorefinarias, "
        "produção de hidrogênio e estocagem de derivados de petróleo e combustíveis",
        "Finem Refino e Hidrogênio", "INDUSTRIA", None,
        "Financiamento a instalações e/ou serviços para refino de petróleo, biorefinarias, "
        "produção de hidrogênio e estocagem de derivados de petróleo e combustíveis.",
        "Financiamento (direto e indireto) a investimentos em refino de petróleo, biorefinarias, "
        "produção de hidrogênio e estocagem de derivados de petróleo e combustíveis.",
        "Refino de petróleo, biorefinarias, hidrogênio", "Refino de petróleo, biorefinarias, produção de "
        "hidrogênio e estocagem de derivados de petróleo e combustíveis",
        40_000_000, "MPMEs: até 100% dos itens financiáveis; demais clientes: até 100% dos itens "
        "financiáveis, limitada a 80% do valor total do projeto",
        "Apoio direto: empresas TLP + Remuneração do BNDES a partir de 1,5% a.a.; estados/municípios/DF "
        "TLP + a partir de 1,5% a.a.; apoio indireto: TLP + Taxa do BNDES 1,45% a.a. + Taxa do Agente "
        "Financeiro",
        NAO_INFORMADO, "Até 6 meses após a entrada do projeto em operação comercial (limite máximo total "
        "de 20 anos)",
        "investimento-instalacoes-servicos-refino-petroleo-biorefinarias",
        "\"Valor mínimo de financiamento: R$ 40 milhões. Para administração pública direta: R$ 20 "
        "milhões... respeitado o limite máximo de 20 anos.\"",
        restricoes="Valor mínimo reduzido a R$ 20 milhões para administração pública direta",
        sinonimos_termos="petroleo refino biorefinaria hidrogenio combustiveis energia",
        spread="1,5% a.a. (direto) / 1,45% a.a. (indireto)",
    ),
    # --- BNDES Finame (aquisicao de bens de capital via agente financeiro) -------------------
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Finame Leasing", "nome_simplificado": "Finame Leasing",
        "sigla": "Finame", "status": "aberta",
        "descricao_resumida": "Financiamento indireto, via arrendamento mercantil (leasing), para aquisição de máquinas, equipamentos, veículos e aeronaves.",
        "descricao_completa": (
            "Financiamento indireto (via instituição financeira credenciada), na modalidade de "
            "arrendamento mercantil (leasing), à aquisição de máquinas, equipamentos, veículos "
            "e aeronaves executivas."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento (leasing)",
        "setores_elegiveis": NAO_INFORMADO, "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Aquisição de bens via arrendamento mercantil (leasing)",
        "itens_financiaveis": "Ônibus, caminhões, chassis e carrocerias, cavalos-mecânicos, reboques, "
        "carros-fortes, guindastes, betoneiras, compactadores de lixo, aeronaves executivas, máquinas e "
        "equipamentos eficientes, bens de informática e automação",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Ônibus/caminhões convencionais, cavalos-mecânicos, guindastes etc.: até "
        "40%; ônibus elétricos/híbridos e equipamentos eficientes: até 80%; bens de informática e "
        "automação com tecnologia nacional: até 80%; demais itens: até 70%",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro (TLP) + Taxa do BNDES 2,1% a.a. + Taxa do Agente Financeiro",
        "indexador": "TLP", "spread": "2,1% a.a.",
        "prazo_total": "Máquinas, equipamentos, bens de informática e automação: até 5 anos; aeronaves "
        "executivas e comerciais: até 10 anos; veículos sobre pneus para transporte de passageiros: 6 a 9 anos",
        "carencia": NAO_INFORMADO, "amortizacao": NAO_INFORMADO,
        "garantias": "Penhor ao BNDES dos direitos creditórios representados pelo contrato de arrendamento",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-finame-leasing",
        "data_vigencia": "Circular nº 20/2019, de 18.04.2019, e alterações posteriores",
        "trecho_fonte": (
            "\"Custo financeiro TLP + Taxa do BNDES 2,1% ao ano... Máquinas, equipamentos, bens de "
            "informática e automação: 5 anos. Aeronaves executivas e comerciais: 10 anos.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Arrendamento mercantil de bens de capital",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "leasing arrendamento mercantil maquinas equipamentos veiculos aeronaves",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Finame BK Aquisição e Comercialização",
        "nome_simplificado": "Finame BK", "sigla": "Finame", "status": "aberta",
        "descricao_resumida": "Financiamento indireto à aquisição de bens de capital novos, de fabricação nacional, incluindo ônibus, caminhões e aeronaves.",
        "descricao_completa": (
            "Financiamento indireto (via instituição financeira credenciada) à aquisição e "
            "comercialização de bens de capital novos, de fabricação nacional, incluindo ônibus, "
            "caminhões e aeronaves executivas e comerciais."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": NAO_INFORMADO, "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Aquisição de bens de capital novos de fabricação nacional",
        "itens_financiaveis": "Bens de capital, ônibus e caminhões novos de fabricação nacional, aeronaves executivas e comerciais",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 100%; aeronaves executivas e comerciais: sempre até 85%",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Bens de capital: Custo Financeiro (TFB/TFBD/TLP/Taxa LCD/Taxa Pré FAT/Taxa Pré FAT "
        "MPME) + Taxa do BNDES 0,75% a.a. (N/NE) ou 0,95% a.a. (demais regiões); ônibus e caminhões: Taxa do "
        "BNDES 0,95% a.a. (MPME N/NE) ou 1,25% a.a. (MPME demais regiões e grandes empresas) + Taxa do Agente Financeiro",
        "indexador": "TLP", "spread": "0,75% a 1,25% a.a. conforme item e região",
        "prazo_total": "Até 10 anos, com carência de até 2 anos (até 1 ano para TFB/Taxa Fixa Composta/Taxa "
        "Fixa Composta MPME); Taxa LCD limitada a 120 meses totais e 24 meses de carência",
        "carencia": "Até 2 anos (até 1 ano para TFB/Taxa Fixa Composta)", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e o cliente; admite FGI "
        "(Tradicional ou PEAC) ou Fundo Garantidor BNDES-SEBRAE",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-finame-bk-aquisicao-comercializacao",
        "data_vigencia": "Circular n° 14/2022, de 26.05.2022",
        "trecho_fonte": (
            "\"Até 100%. A participação máxima do BNDES para o financiamento a aeronaves executivas e "
            "comerciais será sempre de 85%... Até 10 anos, com carência de até 2 anos.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Aquisição de bens de capital",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "bens de capital maquinas equipamentos onibus caminhoes aeronaves",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Finame Agrícola", "nome_simplificado": "Finame Agrícola",
        "sigla": "Finame", "status": "aberta",
        "descricao_resumida": "Financiamento indireto à aquisição de máquinas e equipamentos agrícolas novos de fabricação nacional.",
        "descricao_completa": (
            "Financiamento indireto (via instituição financeira credenciada) à aquisição de "
            "máquinas e equipamentos agrícolas novos, de fabricação nacional."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Aquisição de máquinas e equipamentos agrícolas",
        "itens_financiaveis": "Máquinas e equipamentos agrícolas, bens de informática e automação com "
        "tecnologia nacional",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "MPME: até 80%; demais clientes: até 70% (pode subir a 80% com custo "
        "adicional)",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "MPME: Custo Financeiro (TLP) + Taxa do BNDES 1,42% a.a.; demais clientes: TLP + "
        "Taxa do BNDES 2,1% a.a. + Taxa do Agente Financeiro",
        "indexador": "TLP", "spread": "1,42% a.a. (MPME) / 2,1% a.a. (demais)",
        "prazo_total": "Máquinas e equipamentos: até 7 anos e 6 meses, carência de até 2 anos; bens de "
        "informática e automação: carência de até 1 ano",
        "carencia": "Até 2 anos (máquinas e equipamentos) / até 1 ano (informática)", "amortizacao": NAO_INFORMADO,
        "garantias": "Negociadas entre a instituição financeira credenciada e o cliente; admite BNDES FGI complementar",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-finame-agricola",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Micro, pequenas e médias empresas Custo financeiro TLP + Taxa do BNDES 1,42% ao ano... "
            "Máquinas e equipamentos: 7 anos e 6 meses (amortização), 2 anos (carência).\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "AGROPECUÁRIA", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Máquinas e equipamentos agrícolas",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "maquinas agricolas tratores colheitadeiras equipamentos rurais",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Finame - Baixo Carbono", "nome_simplificado": "Finame Baixo Carbono",
        "sigla": "Finame", "status": "aberta",
        "descricao_resumida": "Financiamento indireto à aquisição de bens de capital de baixo carbono.",
        "descricao_completa": (
            "Financiamento indireto (via instituição financeira credenciada) à aquisição de "
            "bens de capital enquadrados como de baixo carbono."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": NAO_INFORMADO, "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Aquisição de bens de capital de baixo carbono", "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 100%",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro (TFB/TFBD/TLP/Taxa LCD/Taxa Pré FAT/Taxa Pré FAT MPME) + Taxa do "
        "BNDES 0,75% a.a. + Taxa do Agente Financeiro",
        "indexador": "TLP", "spread": "0,75% a.a.",
        "prazo_total": "Até 10 anos, com carência de até 2 anos (até 1 ano para TFB/Taxa Fixa Composta)",
        "carencia": "Até 2 anos (até 1 ano para TFB/Taxa Fixa Composta)", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e o cliente; admite FGI "
        "(Tradicional ou PEAC) ou Fundo Garantidor BNDES-SEBRAE",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-finame-baixo-carbono",
        "data_vigencia": "Circular n° 14/2022, de 26.05.2022",
        "trecho_fonte": (
            "\"Até 100%... Até 10 anos, com carência de até 2 anos. Nos financiamentos em TFB, Taxa Fixa "
            "Composta e Taxa Fixa Composta MPME a carência é de até 1 ano.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Bens de capital de baixo carbono",
        "tecnologias_relacionadas": None, "temas_inovacao": None,
        "temas_sustentabilidade": "Baixo carbono", "sinonimos_termos": "baixo carbono descarbonizacao bens de capital",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Finame Materiais Industrializados",
        "nome_simplificado": "Finame Materiais Industrializados", "sigla": "Finame", "status": "aberta",
        "descricao_resumida": "Financiamento indireto à aquisição de materiais industrializados, limitado a R$ 150 milhões por cliente a cada 12 meses.",
        "descricao_completa": (
            "Financiamento indireto (via instituição financeira credenciada) à aquisição de "
            "materiais industrializados, com consulta de enquadramento por pares NCM/CST."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": NAO_INFORMADO, "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Aquisição de materiais industrializados", "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": 150_000_000,
        "percentual_financiavel": "Até 100% do valor dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro (TFB/TFBD/TLP/Taxa LCD/Taxa Fixa Composta/Taxa Fixa Composta MPME) "
        "+ Taxa do BNDES 0,95% a.a. (MPME N/NE) ou 1,25% a.a. (MPME demais regiões e grandes empresas)",
        "indexador": "TLP", "spread": "0,95% a 1,25% a.a.",
        "prazo_total": "Até 7 anos, com carência de até 2 anos (até 1 ano para TFB/Taxa Fixa Composta)",
        "carencia": "Até 2 anos (até 1 ano para TFB/Taxa Fixa Composta)", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e o cliente; admite FGI "
        "(Tradicional ou PEAC) ou Fundo Garantidor BNDES-SEBRAE",
        "restricoes": "Limite de financiamento de R$ 150 milhões por cliente a cada 12 meses, contados da "
        "homologação da operação pelo BNDES",
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/finame-materiais-industrializados",
        "data_vigencia": "Circular n° 14/2022, de 26.05.2022",
        "trecho_fonte": (
            "\"Até 100% do valor dos itens financiáveis. O limite de financiamento será de R$ 150 milhões "
            "por cliente a cada 12 meses.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Materiais industrializados",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "materiais industrializados NCM CST insumos industriais",
    },
    # --- Crédito rural / agro (familia Pronaf/Pronamp/credito rural) ------------------------
    {
        "instituicao": "BNDES", "nome_oficial": "Procap-Agro Giro - Programa de Capitalização de Cooperativas Agropecuárias",
        "nome_simplificado": "Procap-Agro Giro", "sigla": None, "status": "aberta",
        "descricao_resumida": "Capital de giro para cooperativas de produção agropecuária, agroindustrial, aquícola ou pesqueira.",
        "descricao_completa": (
            "Financiamento de capital de giro a cooperativas singulares de produção "
            "agropecuária, agroindustrial, aquícola ou pesqueira, e a cooperativas centrais, "
            "federações e confederações que fabriquem insumos e processem/industrializem a produção."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Cooperativas agropecuárias, agroindustriais, aquícolas ou pesqueiras",
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": "Cooperativas", "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Capital de giro de cooperativas agropecuárias",
        "itens_financiaveis": NAO_INFORMADO, "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None, "valor_maximo": 90_000_000,
        "percentual_financiavel": NAO_INFORMADO, "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Taxa de juros prefixada de até 12% ao ano", "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO, "prazo_total": "Até 18 meses, incluídos até 6 meses de carência",
        "carencia": "Até 6 meses", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e a beneficiária, "
        "observadas as normas do Conselho Monetário Nacional",
        "restricoes": "R$ 75 milhões para cooperativas singulares; R$ 90 milhões para cooperativas centrais, "
        "federações e confederações; admite mais de um financiamento por Ano Agrícola ao mesmo cliente",
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/procap-agro",
        "data_vigencia": "Circular SUP/ADIG Nº 102/2026-BNDES",
        "trecho_fonte": (
            "\"Taxa de juros prefixada de até 12% ao ano... R$ 75 milhões para cooperativas singulares de "
            "produção agropecuária... Até 18 meses, incluídos até 6 meses de carência.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "AGROPECUÁRIA", "cnaes_relacionados": None,
        "porte_padronizado": "Cooperativas", "destinacao_padronizada": "Capital de giro cooperativas agropecuárias",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "cooperativa agropecuaria capital de giro procap-agro",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "Renovagro – Programa de Financiamento a Sistemas de Produção Agropecuária Sustentáveis",
        "nome_simplificado": "Renovagro", "sigla": "Renovagro", "status": "aberta",
        "descricao_resumida": "Financiamento a sistemas de produção agropecuária sustentáveis, recuperação de pastagens e regularização ambiental.",
        "descricao_completa": (
            "Financiamento a sistemas de produção agropecuária sustentáveis, incluindo "
            "recuperação de pastagens degradadas, regularização ambiental de propriedades "
            "rurais, silvicultura e projetos de biogás/biometano a partir de dejetos animais."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Sistemas de produção agropecuária sustentáveis",
        "itens_financiaveis": "Recuperação de pastagens, regularização ambiental (RL/APP), manejo florestal "
        "sustentável, prevenção a incêndios, aquisição de bovinos/bubalinos/ovinos/caprinos (até 40% do "
        "financiamento), máquinas e implementos, irrigação, benfeitorias, projetos coletivos de biogás/biometano",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": 5_000_000,
        "percentual_financiavel": "Até 100% do valor dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Prefixada de até 8,5% a.a. (recuperação de pastagens/regularização ambiental) ou "
        "até 9,5% a.a. (demais finalidades)",
        "indexador": NAO_INFORMADO, "spread": NAO_INFORMADO,
        "prazo_total": "Silvicultura/agroflorestais/reserva legal: até 12 anos (carência até 96 meses); "
        "demais projetos: até 10 anos (carência até 60 meses); aquisição de matrizes/reprodutores: até 5 anos",
        "carencia": "Até 96 meses (silvicultura) / até 60 meses (demais)", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e a beneficiária, "
        "observadas as normas do Conselho Monetário Nacional",
        "restricoes": "R$ 5 milhões por cliente e por ano agrícola (pode subir a R$ 20 milhões para projetos "
        "coletivos de biogás/biometano, respeitado limite individual de R$ 5 milhões); aquisição de animais "
        "limitada a 40% do valor total do financiamento",
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/renovagro",
        "data_vigencia": "Circular nº 96/2026, de 10.07.2026",
        "trecho_fonte": (
            "\"Taxa de juros prefixada de até 8,5% ao ano para... recuperação de pastagens degradadas "
            "(RenovAgro Recuperação e Conversão)... R$ 5 milhões por cliente e por ano agrícola.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "PRODUÇÃO SUSTENTÁVEL", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Produção agropecuária sustentável",
        "tecnologias_relacionadas": None, "temas_inovacao": None,
        "temas_sustentabilidade": "Recuperação de pastagens, regularização ambiental, biogás/biometano",
        "sinonimos_termos": "renovagro sustentabilidade pastagens biogas biometano regularizacao ambiental",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "Pronamp – Programa Nacional de Apoio ao Médio Produtor Rural",
        "nome_simplificado": "Pronamp", "sigla": "Pronamp", "status": "aberta",
        "descricao_resumida": "Financiamento de investimento e custeio para médios produtores rurais.",
        "descricao_completa": (
            "Programa Nacional de Apoio ao Médio Produtor Rural, com linhas Pronamp Investimento "
            "e Pronamp Custeio, esta última com prazos diferenciados conforme o ciclo de cada "
            "cultura ou atividade pecuária."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Médios produtores rurais", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Médio produtor rural", "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Investimento e custeio agropecuário para médios produtores rurais",
        "itens_financiaveis": NAO_INFORMADO, "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None, "valor_maximo": 1_500_000,
        "percentual_financiavel": "Até 100% do valor dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Prefixada de até 9% ao ano (redução de 0,5 p.p. para custeio contratado até 30.06.2027)",
        "indexador": NAO_INFORMADO, "spread": NAO_INFORMADO,
        "prazo_total": "Pronamp Investimento: até 8 anos, incluída carência de até 2 anos; Pronamp Custeio: "
        "de 6 a 36 meses conforme o ciclo da cultura/atividade pecuária",
        "carencia": "Até 2 anos (Investimento)", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e a beneficiária, "
        "observadas as normas do Conselho Monetário Nacional",
        "restricoes": "Pronamp Investimento: até R$ 600 mil por Ano Agrícola por empreendimento individual; "
        "Pronamp Custeio: até R$ 1,5 milhão por cliente, por Ano Agrícola, em todo o SNCR",
        "criterios_elegibilidade": "Enquadramento como médio produtor rural",
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/pronamp-investimento",
        "data_vigencia": "Circular SUP/ADIG nº 92/2026-BNDES e nº 93/2026-BNDES",
        "trecho_fonte": (
            "\"Taxa de juros prefixada de até 9% ao ano... Pronamp Investimento: para empreendimento "
            "individual: até R$ 600 mil por Ano Agrícola... Pronamp Custeio: Limite de crédito até R$ 1,5 "
            "milhão por cliente.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "AGROPECUÁRIA", "cnaes_relacionados": None,
        "porte_padronizado": "Médio produtor rural", "destinacao_padronizada": "Investimento e custeio agropecuário",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "pronamp medio produtor rural custeio investimento agricola",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Crédito Rural", "nome_simplificado": "Crédito Rural",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Financiamento indireto de investimento, máquinas e equipamentos, custeio e capital de giro para o setor rural.",
        "descricao_completa": (
            "Linhas BNDES Crédito Rural Investimento e Máquinas e Equipamentos, Custeio, Crédito "
            "Cooperativas e CPR BNDES (Cédula de Produto Rural), cada uma com taxas e prazos próprios."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Investimento, máquinas e equipamentos, custeio e capital de giro rural",
        "itens_financiaveis": "Máquinas e equipamentos, projetos de investimento, custeio agropecuário",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 100% dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Projetos de investimento/máquinas: Taxa do BNDES 0,75% a.a. (N/NE) a 2,8% a.a. "
        "(demais); Custeio: Taxa do BNDES 1,35% a.a.; Crédito Cooperativas: 1,35% a.a.; CPR BNDES: 1,25% "
        "a.a. (+ Taxa do Agente Financeiro em todos os casos, até 4,3% a.a.)",
        "indexador": "TLP", "spread": "0,75% a 2,8% a.a. conforme linha e região",
        "prazo_total": "Projetos de investimento: até 15 anos (carência até 3 anos); máquinas e "
        "equipamentos: até 10 anos (carência até 2 anos); custeio: até 3 anos; Crédito Cooperativas: até 2 "
        "anos (carência até 6 meses); CPR BNDES: até 60 meses (carência até 24 meses)",
        "carencia": "Varia de 6 meses a 3 anos conforme a linha", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e a beneficiária; não é "
        "admitida a outorga de garantia pelo FGI neste Programa",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-credito-rural",
        "data_vigencia": "Circular nº 19/2024, de 03.05.2024",
        "trecho_fonte": (
            "\"Projetos de investimento: até 15 anos, incluído o prazo de carência de até 3 anos. "
            "Aquisição isolada de máquinas e equipamentos: Até 10 anos, incluído prazo de carência de até "
            "2 anos.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "AGROPECUÁRIA", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Crédito rural",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "credito rural cooperativas CPR maquinas agricolas custeio",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "Pronaf Mulher", "nome_simplificado": "Pronaf Mulher",
        "sigla": "Pronaf", "status": "aberta",
        "descricao_resumida": "Linha do Pronaf voltada a produtoras rurais, com taxas diferenciadas por renda e finalidade.",
        "descricao_completa": (
            "Linha do Pronaf destinada a produtoras rurais, com concessão individual ou coletiva "
            "(esta última exclusiva para benfeitorias, máquinas e estruturas de uso comum). "
            "Beneficiárias do Grupo B seguem as condições da Linha Pronaf Microcrédito."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agricultura familiar (produtoras rurais)", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Produtora rural familiar", "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Investimento rural para produtoras (agricultura familiar)",
        "itens_financiaveis": "Máquinas, equipamentos e implementos (inclusive irrigação e conectividade), "
        "infraestrutura de captação/armazenamento de água, cultivo protegido, silos e armazéns, tanques de "
        "resfriamento, tratores, colheitadeiras",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 100% do valor dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Prefixada, variando de 1,5% a.a. (máquinas/equipamentos/irrigação para renda até "
        "R$150 mil) a 7,5% a.a. (demais finalidades); 5% a.a. para tratores/colheitadeiras/pulverizadores",
        "indexador": NAO_INFORMADO, "spread": NAO_INFORMADO,
        "prazo_total": "Caminhonetes/motocicletas/ATVs: até 5 anos sem carência; tratores/colheitadeiras: "
        "até 7 anos (carência até 12 meses); matrizes/reprodutores: até 8 anos (carência até 36 meses); "
        "demais itens: até 10 anos (carência até 36 meses)",
        "carencia": "Até 36 meses conforme item financiado", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e a beneficiária, "
        "observadas as normas do Conselho Monetário Nacional",
        "restricoes": "Limite individual de R$ 100 mil a R$ 450 mil conforme atividade/renda; limite "
        "coletivo de R$ 9,9 milhões para reforma/ampliação de benfeitorias e estruturas de uso comum",
        "criterios_elegibilidade": "Enquadramento como produtora rural no Pronaf",
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/pronaf-mulher",
        "data_vigencia": "Circular SUP/ADIG nº 91/2026-BNDES",
        "trecho_fonte": (
            "\"Individual: formalizado com uma produtora, para finalidade individual... taxa de juros "
            "prefixada de até 1,5% ao ano [para] aquisição de máquinas, equipamentos e implementos.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "AGROPECUÁRIA", "cnaes_relacionados": None,
        "porte_padronizado": "Agricultura familiar", "destinacao_padronizada": "Agricultura familiar - mulheres",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "pronaf mulher agricultura familiar produtora rural genero",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "Pronaf Bioeconomia", "nome_simplificado": "Pronaf Bioeconomia",
        "sigla": "Pronaf", "status": "aberta",
        "descricao_resumida": "Linha do Pronaf para silvicultura e sistemas agroflorestais na agricultura familiar.",
        "descricao_completa": (
            "Linha do Pronaf voltada a silvicultura (implantação/manutenção de povoamentos "
            "florestais madeireiros e não madeireiros) e demais finalidades de bioeconomia na "
            "agricultura familiar."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agricultura familiar (silvicultura, bioeconomia)", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Agricultura familiar", "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Silvicultura e bioeconomia na agricultura familiar",
        "itens_financiaveis": "Seringueira, dendê, silvicultura, sistemas agroflorestais", "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None, "valor_maximo": 450_000,
        "percentual_financiavel": "Até 100% do valor dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Silvicultura: prefixada de até 7,5% a.a.; demais finalidades: até 2% a.a.",
        "indexador": NAO_INFORMADO, "spread": NAO_INFORMADO,
        "prazo_total": "Seringueira: até 20 anos (carência 96 meses); dendê: até 14 anos (carência 72 "
        "meses); silvicultura/agroflorestais: até 12 anos (carência 96 meses); demais: até 10 anos "
        "(carência 36 meses)",
        "carencia": "36 a 96 meses conforme cultura", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e a beneficiária, "
        "observadas as normas do Conselho Monetário Nacional",
        "restricoes": "R$ 450 mil para silvicultura e sistemas agroflorestais; R$ 250 mil para as demais finalidades",
        "criterios_elegibilidade": "Enquadramento no Pronaf", "agente_financeiro": "Instituições financeiras credenciadas",
        "canal_contratacao": NAO_INFORMADO, "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/pronaf-bioeconomia",
        "data_vigencia": "Circular SUP/ADIG nº 91/2026-BNDES",
        "trecho_fonte": (
            "\"Para a silvicultura... taxa efetiva de juros prefixada de até 7,5% ao ano... R$ 450 mil "
            "para silvicultura e sistemas agroflorestais.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "BIOECONOMIA", "cnaes_relacionados": None,
        "porte_padronizado": "Agricultura familiar", "destinacao_padronizada": "Bioeconomia e silvicultura familiar",
        "tecnologias_relacionadas": None, "temas_inovacao": None,
        "temas_sustentabilidade": "Silvicultura, sistemas agroflorestais, bioeconomia",
        "sinonimos_termos": "bioeconomia silvicultura seringueira dende agrofloresta pronaf",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "PCA - Programa para Construção e Ampliação de Armazéns",
        "nome_simplificado": "PCA", "sigla": "PCA", "status": "aberta",
        "descricao_resumida": "Financiamento à construção e ampliação de armazéns para grãos, para produtores rurais e cooperativas.",
        "descricao_completa": (
            "Financiamento a investimentos em armazenagem de grãos por produtores rurais e "
            "cooperativas de produção, com taxa reduzida para unidades de menor capacidade."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária (armazenagem de grãos)", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Produtores rurais e cooperativas de produção", "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Construção e ampliação de armazéns",
        "itens_financiaveis": "Armazenagem de grãos e demais itens de armazenagem", "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None, "valor_maximo": 200_000_000,
        "percentual_financiavel": "Até 100% dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Prefixada de até 8% a.a. (armazéns de grãos com capacidade até 12.000 toneladas) "
        "ou até 9,5% a.a. (demais empreendimentos)",
        "indexador": NAO_INFORMADO, "spread": NAO_INFORMADO,
        "prazo_total": "Até 10 anos, com carência de até 2 anos", "carencia": "Até 2 anos", "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e a beneficiária, "
        "observadas as normas do Conselho Monetário Nacional",
        "restricoes": "R$ 50 milhões (armazenagem de grãos por produtores rurais); R$ 200 milhões "
        "(armazenagem de grãos por cooperativas de produção); R$ 25 milhões (demais itens), por cliente e "
        "por Ano Agrícola",
        "criterios_elegibilidade": NAO_INFORMADO, "agente_financeiro": "Instituições financeiras credenciadas",
        "canal_contratacao": NAO_INFORMADO, "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/pca",
        "data_vigencia": "Circular SUP/ADIG nº 97/2026-BNDES",
        "trecho_fonte": (
            "\"Para investimentos relativos à armazenagem de grãos de unidades com capacidade de até "
            "12.000 toneladas: Taxa de juros prefixada de até 8% ao ano... R$ 200 milhões, quando "
            "destinado a investimentos relativos à armazenagem para grãos por cooperativas de produção.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "AGROPECUÁRIA", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Armazenagem de grãos",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "armazens graos armazenagem cooperativas silos",
    },
    # --- Infraestrutura (fundos programaticos: TR + remuneracao BNDES, nao TLP) -------------
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Saneamento para Todos", "nome_simplificado": "Saneamento para Todos",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Financiamento direto a projetos de saneamento, com recursos remunerados pela TR e vigência até 2027.",
        "descricao_completa": (
            "Financiamento direto a projetos de saneamento (água e esgoto), com taxa de juros "
            "reduzida para a modalidade Saneamento Integrado, vigente até 31.12.2027 ou até "
            "esgotamento da dotação orçamentária."
        ),
        "modalidade": "Direta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Saneamento", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Projetos de saneamento", "itens_financiaveis": NAO_INFORMADO, "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": 80_000_000, "valor_maximo": None,
        "percentual_financiavel": "Até 95%",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro: TR + 6% a.a. (5% a.a. para Saneamento Integrado) + 0,2% a.a. "
        "(taxa de risco do agente operador); Remuneração do BNDES: a partir de 1,10% a.a.",
        "indexador": "TR", "spread": "A partir de 1,10% a.a. (Remuneração do BNDES)",
        "prazo_total": "Limitado a 287 meses, incluído o prazo de carência de até 47 meses",
        "carencia": "Até 47 meses", "amortizacao": NAO_INFORMADO,
        "garantias": "Garantias reais (hipoteca, penhor, propriedade fiduciária etc.) e/ou pessoais "
        "(fiança ou aval), definidas na análise da operação",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": "Protocolo no BNDES e seleção pelo "
        "Ministério das Cidades",
        "agente_financeiro": "BNDES", "canal_contratacao": NAO_INFORMADO, "prazo_inscricao": "Até 31.12.2027 "
        "ou até a utilização total da dotação, o que ocorrer primeiro", "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-saneamento-para-todos",
        "data_vigencia": "Até 31.12.2027 (protocolo no BNDES e seleção pelo Ministério das Cidades)",
        "trecho_fonte": (
            "\"Custo financeiro Taxa Referencial (TR) + 6% a.a... Valor mínimo do financiamento: R$ "
            "80.000.000,00... Limitado a 287 meses, incluído o prazo de carência de até 47 meses.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "INFRAESTRUTURA", "subsetor_padronizado": "SANEAMENTO", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Saneamento",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": "Saneamento básico",
        "sinonimos_termos": "saneamento agua esgoto TR ministerio das cidades",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Pró-Transporte: Projetos de investimento em mobilidade urbana",
        "nome_simplificado": "Pró-Transporte", "sigla": None, "status": "aberta",
        "descricao_resumida": "Financiamento direto a projetos de mobilidade urbana, com recursos remunerados pela TR e vigência até 2027.",
        "descricao_completa": (
            "Financiamento direto a projetos de implantação, expansão, modernização e "
            "recuperação de infraestrutura de transporte de passageiros, com taxa reduzida para "
            "sistemas sobre trilhos e para projetos de transporte mais sustentável."
        ),
        "modalidade": "Direta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Mobilidade urbana", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Projetos de investimento em mobilidade urbana",
        "itens_financiaveis": "Implantação, expansão, modernização e recuperação de infraestrutura de "
        "transporte de passageiros, incluindo aquisição de equipamentos",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": 80_000_000, "valor_maximo": None,
        "percentual_financiavel": "Até 95%",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro: TR + 6% a.a. (5,5% a.a. para transporte sobre trilhos) + 0,2% "
        "a.a. (taxa de risco do agente operador); Remuneração do BNDES: 1,10% a.a. (transporte mais "
        "sustentável) ou 1,30% a.a. (demais projetos), limitada a 2,64% a.a. no total",
        "indexador": "TR", "spread": "1,10% a 1,30% a.a. (Remuneração do BNDES)",
        "prazo_total": "Limitado a 240 meses, incluído o prazo de carência de até 47 meses",
        "carencia": "Até 47 meses", "amortizacao": NAO_INFORMADO,
        "garantias": "Garantias reais (hipoteca, penhor, propriedade fiduciária etc.) e/ou pessoais "
        "(fiança ou aval), definidas na análise da operação, conforme o Manual de Fomento Pró-Transporte",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": "Protocolo no BNDES e seleção pelo "
        "Ministério das Cidades",
        "agente_financeiro": "BNDES", "canal_contratacao": NAO_INFORMADO, "prazo_inscricao": "Até 31.12.2027 "
        "ou até a utilização total da dotação, o que ocorrer primeiro", "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-pro-transporte-projetos-investimento-mob-urbana",
        "data_vigencia": "Até 31.12.2027 (protocolo no BNDES e seleção pelo Ministério das Cidades)",
        "trecho_fonte": (
            "\"Custo financeiro Taxa Referencial (TR) + 6% a.a... Valor mínimo do financiamento: R$ "
            "80.000.000,00... Limitado a 240 meses, incluído o prazo de carência de até 47 meses.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "INFRAESTRUTURA", "subsetor_padronizado": "MOBILIDADE URBANA", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Mobilidade urbana",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": "Transporte sustentável",
        "sinonimos_termos": "pro-transporte mobilidade urbana onibus metro trilhos TR",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "Fundo Clima - Indústria Verde", "nome_simplificado": "Fundo Clima Indústria Verde",
        "sigla": "Fundo Clima", "status": "aberta",
        "descricao_resumida": "Financiamento a projetos de minerais críticos, combustíveis alternativos e conversão de biomassa, com recursos do Fundo Clima.",
        "descricao_completa": (
            "Apoio a projetos de minerais críticos e estratégicos para transição energética, "
            "desenvolvimento de combustíveis alternativos ou derivados de resíduos, e conversão "
            "de biomassa em produtos energéticos ou de alto valor agregado."
        ),
        "modalidade": "Direta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Indústria (minerais críticos, combustíveis alternativos, biomassa)",
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Transição energética e descarbonização industrial",
        "itens_financiaveis": "Beneficiamento/refino/transformação mineral, fabricação de insumos para "
        "baterias/motores elétricos/veículos eletrificados, produção de combustíveis alternativos, "
        "conversão de biomassa",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": 20_000_000, "valor_maximo": 1_000_000_000,
        "percentual_financiavel": "80% dos itens financiáveis (complementado por operação de crédito de "
        "pelo menos 20% do total)",
        "contrapartida": "Pelo menos 20% do crédito total, via operação de crédito complementar",
        "taxa_completa": "Pessoas Jurídicas de Direito Público (exceto União): Custo Financeiro 6,5% a.a. + "
        "Taxa do BNDES a partir de 1,2% a.a.; Pessoas Jurídicas de Direito Privado: Custo Financeiro 6,5% "
        "a.a. + Taxa do BNDES a partir de 1,3% a.a.",
        "indexador": NAO_INFORMADO, "spread": "A partir de 1,2%/1,3% a.a.",
        "prazo_total": "Limitado a 192 meses, incluído o prazo de carência de até 60 meses",
        "carencia": "Até 60 meses", "amortizacao": NAO_INFORMADO,
        "garantias": "Definidas na análise da operação",
        "restricoes": "R$ 1 bilhão por grupo econômico a cada 12 meses para minerais críticos/combustíveis "
        "alternativos/conversão de biomassa; R$ 500 milhões para as demais atividades apoiáveis",
        "criterios_elegibilidade": NAO_INFORMADO, "agente_financeiro": "BNDES", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/fundo-clima/fundo-clima-industria-verde",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"O valor mínimo de financiamento é de R$ 20 milhões... R$ 1 bilhão por grupo econômico a "
            "cada 12 meses... 80% dos itens financiáveis, devendo ser complementado por operação de "
            "crédito.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "INDUSTRIA", "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Transição energética industrial",
        "tecnologias_relacionadas": "Minerais críticos, baterias, veículos eletrificados",
        "temas_inovacao": None, "temas_sustentabilidade": "Transição energética, descarbonização, biomassa",
        "sinonimos_termos": "fundo clima industria verde minerais criticos biomassa descarbonizacao",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Fundo Cultural - Apoio à Cultura", "nome_simplificado": "Fundo Cultural",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Recursos não reembolsáveis para preservação e revitalização do patrimônio histórico e cultural brasileiro.",
        "descricao_completa": (
            "O Fundo Cultural destina recursos não reembolsáveis a projetos de preservação e "
            "revitalização do patrimônio histórico e cultural brasileiro (material, imaterial ou "
            "acervos memoriais), podendo também apoiar projetos estruturantes da cadeia "
            "produtiva da economia da cultura. Proponentes devem ser entes privados sem fins "
            "lucrativos ou entes públicos (autarquia/fundação)."
        ),
        "modalidade": "Direta", "tipo_apoio": "Recursos não reembolsáveis",
        "setores_elegiveis": "Patrimônio cultural brasileiro (entes sem fins lucrativos ou públicos)",
        "setores_nao_elegiveis": "Entidades com fins lucrativos", "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Preservação e revitalização do patrimônio histórico e cultural",
        "itens_financiaveis": "Patrimônio material, imaterial, acervos memoriais, projetos estruturantes "
        "da cadeia produtiva da economia da cultura",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": 10_000_000,
        "percentual_financiavel": NAO_INFORMADO, "contrapartida": "Pode ser considerada como critério de "
        "priorização pelo Comitê de Projetos Culturais (CPCult)",
        "taxa_completa": NAO_INFORMADO, "indexador": NAO_INFORMADO, "spread": NAO_INFORMADO,
        "prazo_total": NAO_INFORMADO, "carencia": NAO_INFORMADO, "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": "Valor máximo de R$ 10 milhões (pode ser maior para projetos icônicos/singulares, "
        "condicionado à disponibilidade orçamentária); carteira de projetos: 3 a 5 patrimônios, R$ 1 a 2 "
        "milhões por projeto",
        "criterios_elegibilidade": "Aprovação no PRONAC - Programa Nacional de Apoio à Cultura; "
        "reconhecimento formal do patrimônio (tombamento IPHAN, registro UNESCO etc.)",
        "agente_financeiro": "BNDES", "canal_contratacao": "Comitê de Patrimônio Cultural e Economia da "
        "Cultura (CPCult)", "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-fundo-cultural",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"O Fundo Cultural destina recursos não reembolsáveis a projetos de preservação e "
            "revitalização do patrimônio histórico e cultural brasileiro... O valor máximo de apoio será "
            "de R$ 10 milhões.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Patrimônio cultural",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "fundo cultural patrimonio historico nao reembolsavel CPCult PRONAC",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Garantia", "nome_simplificado": "BNDES Garantia",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Prestação de garantia pelo BNDES em operações de crédito ou comércio exterior, combinável com outros produtos do Sistema BNDES.",
        "descricao_completa": (
            "Prestação de garantia pelo BNDES, cobrando Comissão de Promessa de Garantia e "
            "Comissão de Prestação de Garantia; pode ser combinada com outros produtos do "
            "Sistema BNDES para atingir o valor mínimo exigido."
        ),
        "modalidade": "Direta", "tipo_apoio": "Prestação de garantia", "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Prestação de garantia para operações de crédito e comércio exterior",
        "itens_financiaveis": NAO_INFORMADO, "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 100% das obrigações pecuniárias devidas pela beneficiária",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Comissão de Promessa de Garantia (mesma alíquota da Comissão por Colaboração "
        "Financeira) + Comissão de Prestação de Garantia (definida conforme risco da operação)",
        "indexador": NAO_INFORMADO, "spread": NAO_INFORMADO,
        "prazo_total": "Mínimo de 1 ano, admitidas renovações/prorrogações; máximo conforme as Políticas "
        "Operacionais do Produto FINEM para o setor apoiado; comércio exterior: sem prazo mínimo, máximo "
        "conforme BNDES-exim Pré-embarque e Pós-embarque",
        "carencia": NAO_INFORMADO, "amortizacao": NAO_INFORMADO,
        "garantias": "Garantias reais (hipoteca, penhor, propriedade fiduciária, recebíveis etc.) e/ou "
        "pessoais (fiança ou aval); admite classes subordinadas a critério do BNDES",
        "restricoes": "Valor mínimo igual ao definido no Guia de Financiamento - Formas de Apoio (admitido "
        "apoio direto combinado com outros produtos para atingir o mínimo)",
        "criterios_elegibilidade": NAO_INFORMADO, "agente_financeiro": "BNDES", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-garantia",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"A prestação da garantia poderá compreender até 100% das obrigações pecuniárias devidas "
            "pela Beneficiária... o prazo mínimo de 1 (um) ano, admitidas renovações ou prorrogações.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Garantia de operações de crédito",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "garantia fianca aval comercio exterior contragarantia",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Saúde - Gestão", "nome_simplificado": "Saúde Gestão",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Financiamento a projetos de gestão em saúde, com garantia possível por Recebíveis do SUS.",
        "descricao_completa": (
            "Financiamento (direto e indireto) a projetos de gestão em saúde, admitindo Recebíveis "
            "do SUS como garantia adicional."
        ),
        "modalidade": "Direta e Indireta", "tipo_apoio": "Financiamento", "setores_elegiveis": "Saúde",
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Gestão em saúde", "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 100% do valor dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Apoio direto: Custo Financeiro (TLP) + Remuneração do BNDES a partir de 1,5% a.a.",
        "indexador": "TLP", "spread": "A partir de 1,5% a.a.",
        "prazo_total": "Até 12 anos, incluído prazo de carência de até 1 ano", "carencia": "Até 1 ano",
        "amortizacao": NAO_INFORMADO,
        "garantias": "Garantias padrão do BNDES, podendo incluir Recebíveis do SUS; apoio indireto: "
        "negociadas entre a instituição financeira credenciada e o cliente",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "BNDES (direto) ou instituições financeiras credenciadas (indireto)",
        "canal_contratacao": NAO_INFORMADO, "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-saude-gestao",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Custo financeiro TLP + Remuneração do BNDES A partir de 1,5% ao ano... Até 12 anos, "
            "incluído prazo de carência de até 1 ano... poderão ser garantidas por Recebíveis do SUS.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "COMERCIO/SERVICOS", "subsetor_padronizado": "SAÚDE", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Gestão em saúde",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "saude gestao hospitalar SUS recebiveis",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Saúde - Investimentos", "nome_simplificado": "Saúde Investimentos",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Financiamento a projetos de investimento em saúde, com garantia possível por Recebíveis do SUS.",
        "descricao_completa": (
            "Financiamento (direto e indireto) a projetos de investimento no setor de saúde, "
            "admitindo Recebíveis do SUS como garantia adicional."
        ),
        "modalidade": "Direta e Indireta", "tipo_apoio": "Financiamento", "setores_elegiveis": "Saúde",
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Investimentos em saúde", "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 100% do valor dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Apoio direto: Custo Financeiro (TLP) + Remuneração do BNDES a partir de 1,5% a.a.",
        "indexador": "TLP", "spread": "A partir de 1,5% a.a.",
        "prazo_total": "Até 18 anos, incluído prazo de carência de até 3 anos", "carencia": "Até 3 anos",
        "amortizacao": NAO_INFORMADO,
        "garantias": "Garantias padrão do BNDES, podendo incluir Recebíveis do SUS; apoio indireto: "
        "negociadas entre a instituição financeira credenciada e o cliente",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "BNDES (direto) ou instituições financeiras credenciadas (indireto)",
        "canal_contratacao": NAO_INFORMADO, "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-saude-investimentos",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Custo financeiro TLP + Remuneração do BNDES A partir de 1,5% ao ano... Até 18 anos, "
            "incluído prazo de carência de até 3 anos.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "COMERCIO/SERVICOS", "subsetor_padronizado": "SAÚDE", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Investimentos em saúde",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "saude hospitais investimento equipamentos medicos SUS",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "Recursos do Fundo da Marinha Mercante (FMM) - Financiamento à marinha mercante e à construção naval",
        "nome_simplificado": "FMM - Marinha Mercante", "sigla": "FMM", "status": "aberta",
        "descricao_resumida": "Financiamento a empresas de navegação e estaleiros nacionais para construção, aquisição e reparo de embarcações.",
        "descricao_completa": (
            "Recursos do Fundo da Marinha Mercante para financiamento a empresas brasileiras de "
            "navegação e estaleiros nacionais, com condições (participação, taxa e prazos) "
            "diferenciadas conforme tipo de embarcação (carga, apoio marítimo, passageiros etc.), "
            "índice de conteúdo nacional e beneficiário (inclusive Marinha do Brasil, arsenais e "
            "bases navais). Inclui a Ação de Incentivo à Descarbonização da Frota Naval, que "
            "reduz a taxa de juros para projetos com redução comprovada de emissões de GEE."
        ),
        "modalidade": "Direta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Marinha mercante e construção naval", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Construção, aquisição, reparo e modernização de embarcações; instalações de estaleiros",
        "itens_financiaveis": "Embarcações de carga, apoio marítimo, apoio à navegação, transporte de "
        "passageiros; construção/expansão/modernização de estaleiros; pesquisa e desenvolvimento no setor; pesca artesanal",
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 90% (varia conforme índice de conteúdo nacional e tipo de "
        "beneficiário); até 100% para Marinha do Brasil e entidades públicas/instituições de pesquisa",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo financeiro equivalente à TLP ou a índice de variação cambial do dólar; "
        "Taxa do BNDES variável conforme objetivo, cliente e projeto -- taxas de juros totais tipicamente "
        "entre 1% a.a. e 8,5% a.a. conforme a tabela de condições por tipo de embarcação/beneficiário",
        "indexador": "TLP ou variação cambial (dólar)", "spread": "Variável conforme tipo de projeto (ver tabela oficial)",
        "prazo_total": "Varia por tipo de projeto: de até 2 anos (reparo de embarcação) a até 20 anos "
        "(construção/produção de embarcações de carga, apoio e passageiros)",
        "carencia": "De até 1 ano a até 4 anos conforme o tipo de projeto", "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": "Condições aplicáveis apenas a projetos priorizados pelo Conselho Diretor do Fundo "
        "da Marinha Mercante (CDFMM) a partir de 17.12.2009; conteúdo nacional calculado conforme "
        "Resolução CMN nº 5.225, de 26.06.2025",
        "criterios_elegibilidade": "Empresa brasileira de navegação, estaleiro nacional, ou entidade "
        "pública/instituição de pesquisa, conforme o tipo de projeto",
        "agente_financeiro": "BNDES", "canal_contratacao": "Portal do Cliente", "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo", "documentos_necessarios": "Modelos de RAO/RAC, orçamentos e declarações "
        "específicos por tipo de operação (disponíveis no Portal do Cliente)",
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/fundo-marinha-mercante",
        "data_vigencia": "Resolução CMN nº 5.225, de 26.06.2025; Resolução CDFMM nº 233/2025",
        "trecho_fonte": (
            "\"Custo financeiro: equivalente à TLP ou a índice de variação da taxa de câmbio... Ação que "
            "visa incentivar a descarbonização da frota naval, por meio da redução da taxa de juros do "
            "FMM.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "INDUSTRIA", "subsetor_padronizado": "CONSTRUÇÃO NAVAL", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Construção naval e marinha mercante",
        "tecnologias_relacionadas": None, "temas_inovacao": None,
        "temas_sustentabilidade": "Descarbonização da frota naval",
        "sinonimos_termos": "marinha mercante construcao naval estaleiro FMM embarcacoes",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Parques e Florestas", "nome_simplificado": "Parques e Florestas",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Financiamento direto a projetos de parques e florestas, com taxa reduzida frente às linhas Finem padrão.",
        "descricao_completa": (
            "Financiamento direto a projetos de parques e florestas, com prazo total de até 25 "
            "anos e garantias flexíveis por fase do projeto (pré-operacional/operacional)."
        ),
        "modalidade": "Direta", "tipo_apoio": "Financiamento", "setores_elegiveis": "Parques e florestas",
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Projetos de parques e florestas",
        "itens_financiaveis": NAO_INFORMADO, "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": 20_000_000, "valor_maximo": 80_000_000,
        "percentual_financiavel": "Até 80% do valor total do investimento, limitada a 100% dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro (TLP ou Selic) + Remuneração do BNDES a partir de 1,1% a.a.",
        "indexador": "TLP", "spread": "A partir de 1,1% a.a.",
        "prazo_total": "Determinado pela capacidade de pagamento, limitado a 25 anos", "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": "Conforme Norma de Garantias e Mitigadores de Risco do BNDES: fase pré-operacional "
        "(aval fidejussório, ESA, ações da SPE, direitos da concessão, garantias reais externas, seguro "
        "garantia) e fase operacional (garantias reais externas ou recebíveis da concessão, com conta "
        "de reserva mínima de 6 prestações mensais)",
        "restricoes": "R$ 80 milhões por grupo econômico", "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "BNDES", "canal_contratacao": NAO_INFORMADO, "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-parques-e-florestas",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Valor mínimo de financiamento: R$ 20 milhões... Valor máximo: R$ 80 milhões por grupo "
            "econômico... limitado a 25 anos.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "SILVICULTURA", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Parques e florestas",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": "Parques e florestas",
        "sinonimos_termos": "parques florestas conservacao concessao ambiental",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "Programa BNDES Florestas Crédito", "nome_simplificado": "Florestas Crédito",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Financiamento direto a projetos florestais, com dotação combinável com o Fundo Clima (até R$ 1 bilhão).",
        "descricao_completa": (
            "Financiamento direto a projetos florestais, com dotação própria de R$ 544 milhões "
            "complementável por até R$ 456 milhões do Fundo Clima, totalizando até R$ 1 bilhão."
        ),
        "modalidade": "Direta", "tipo_apoio": "Financiamento", "setores_elegiveis": "Silvicultura/florestas",
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Projetos florestais", "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": 10_000_000, "valor_maximo": 100_000_000,
        "percentual_financiavel": "Até 100% dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro (TLP ou TS) + Remuneração do BNDES 0,9% a.a. + Taxa de Risco de "
        "Crédito (variável)",
        "indexador": "TLP", "spread": "0,9% a.a.",
        "prazo_total": "Limitado a 300 meses, incluído o prazo de carência de até 96 meses",
        "carencia": "Até 96 meses", "amortizacao": NAO_INFORMADO,
        "garantias": "Negociadas na análise da operação",
        "restricoes": "R$ 100 milhões por grupo econômico a cada 12 meses; dotação do programa de R$ 544 "
        "milhões, complementável com até R$ 456 milhões do Fundo Clima (total de até R$ 1 bilhão)",
        "criterios_elegibilidade": NAO_INFORMADO, "agente_financeiro": "BNDES", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/programa-florestas",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Custo financeiro TLP ou TS + Remuneração do BNDES 0,9% a.a... A dotação do Programa BNDES "
            "Florestas Crédito é de R$ 544 milhões... pode chegar a uma dotação combinada de até R$ 1 "
            "bilhão.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA", "subsetor_padronizado": "SILVICULTURA", "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Florestas",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": "Florestas, Fundo Clima",
        "sinonimos_termos": "florestas credito silvicultura fundo clima reflorestamento",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Caminho da Escola", "nome_simplificado": "Caminho da Escola",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Financiamento indireto para aquisição de veículos/equipamentos de transporte escolar.",
        "descricao_completa": (
            "Financiamento indireto (via instituição financeira credenciada) a estados e "
            "municípios para aquisição de itens do Programa Caminho da Escola (transporte escolar)."
        ),
        "modalidade": "Indireta", "tipo_apoio": "Financiamento", "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Transporte escolar", "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Até 100% do valor total dos itens apoiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Custo Financeiro (TLP/Taxa LCD/Taxa Pré FAT) + Taxa do BNDES 0,75% a.a. (regiões "
        "N/NE) ou 0,95% a.a. (demais regiões) + Taxa do Agente Financeiro",
        "indexador": "TLP", "spread": "0,75%/0,95% a.a.",
        "prazo_total": "Até 10 anos, incluindo até 2 anos de carência", "carencia": "Até 2 anos",
        "amortizacao": NAO_INFORMADO,
        "garantias": "Livre negociação entre a instituição financeira credenciada e o cliente, observadas "
        "as normas do Banco Central",
        "restricoes": NAO_INFORMADO, "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Instituições financeiras credenciadas", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-caminho-da-escola",
        "data_vigencia": "Circular n° 67/2023, de 13.11.2023",
        "trecho_fonte": (
            "\"Custo financeiro TLP, Taxa LCD ou Taxa Pré FAT + Taxa do BNDES 0,75% ao ano: investimentos "
            "nas regiões N e NE... Até 100% do valor total dos itens apoiáveis... Até 10 anos, incluindo "
            "até 2 anos de carência.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Transporte escolar",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": None,
        "sinonimos_termos": "caminho da escola transporte escolar onibus escolar municipios",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Debêntures em Ofertas Públicas", "nome_simplificado": "Debêntures em Ofertas Públicas",
        "sigla": None, "status": "aberta",
        "descricao_resumida": "Subscrição pelo BNDES de até 100% de emissões de debêntures em ofertas públicas.",
        "descricao_completa": (
            "Subscrição de debêntures em ofertas públicas, com remuneração determinada pelas "
            "características da oferta (risco, garantias, perfil de pagamento); redução de 10 "
            "pontos-base na remuneração do BNDES em emissões com certificação/segunda opinião "
            "de sustentabilidade."
        ),
        "modalidade": "Direta", "tipo_apoio": "Subscrição de debêntures", "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Nacional", "destinacao": "Financiamento via mercado de capitais (debêntures)",
        "itens_financiaveis": NAO_INFORMADO, "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None, "valor_maximo": None,
        "percentual_financiavel": "Subscrição de até 100% do total das emissões",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Remuneração determinada pelas características da oferta (classificação de "
        "risco, garantias, perfil de pagamento); redução de 10 p.b. com certificação de sustentabilidade",
        "indexador": NAO_INFORMADO, "spread": NAO_INFORMADO,
        "prazo_total": "Conforme estabelecido nas linhas do BNDES Finem", "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": "Conforme Norma de Garantias e Mitigadores de Risco do Sistema BNDES, admitindo "
        "dispensa de garantias reais nos termos da Norma",
        "restricoes": "Valor mínimo conforme estabelecido nas linhas do BNDES Finem",
        "criterios_elegibilidade": NAO_INFORMADO, "agente_financeiro": "BNDES", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-debentures-oferta-publica",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Subscrição de até 100% do total das emissões... a remuneração do BNDES poderá ser reduzida "
            "em 10 pontos básicos percentuais, caso a emissão possua uma certificação... sobre "
            "sustentabilidade.\" (capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Mercado de capitais",
        "tecnologias_relacionadas": None, "temas_inovacao": None, "temas_sustentabilidade": "Certificação de sustentabilidade (desconto na remuneração)",
        "sinonimos_termos": "debentures oferta publica mercado de capitais titulos",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "BNDES Thai - Debêntures Participativas para Inovação",
        "nome_simplificado": "BNDES Thai", "sigla": "THAI", "status": "aberta",
        "descricao_resumida": "Debêntures participativas da BNDESPAR para projetos de inovação, com remuneração vinculada à receita gerada pela tecnologia desenvolvida.",
        "descricao_completa": (
            "Subscrição pela BNDESPAR de debêntures participativas para financiar projetos de "
            "inovação, com remuneração anual vinculada a um percentual da Receita Operacional "
            "Líquida Ajustada proveniente do licenciamento/cessão/alienação da tecnologia "
            "desenvolvida; dispensada a prestação de garantias."
        ),
        "modalidade": "Direta", "tipo_apoio": "Subscrição de debêntures participativas",
        "setores_elegiveis": NAO_INFORMADO, "setores_nao_elegiveis": NAO_INFORMADO, "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Projetos de inovação com potencial de licenciamento/comercialização de tecnologia",
        "itens_financiaveis": "Ativos tangíveis e intangíveis de projetos de inovação", "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": 10_000_000, "valor_maximo": 200_000_000,
        "percentual_financiavel": "Participação da BNDESPAR de até 50% dos itens financiáveis (limite "
        "global de 90% do Sistema BNDES no projeto, somado a outros instrumentos); subscrição limitada a "
        "15% do Ativo Total do beneficiário/grupo econômico",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Remuneração anual: percentual sobre a Receita Operacional Líquida Ajustada "
        "proveniente do licenciamento/cessão/alienação da tecnologia desenvolvida; diferimento corrigido "
        "por IPCA + 2% a.a.",
        "indexador": "IPCA", "spread": "2% a.a. (sobre valor diferido)",
        "prazo_total": "25 a 35 anos (amortização)", "carencia": NAO_INFORMADO, "amortizacao": NAO_INFORMADO,
        "garantias": "Dispensada a prestação de garantias",
        "restricoes": "Diferimento de pagamento por até 5 anos consecutivos se exceder o Fluxo de Caixa "
        "Operacional; vedado pagamento de dividendos/JCP durante o diferimento; vencimento antecipado em "
        "caso de alienação de controle sem anuência do BNDES (multa de 10% a.a. sobre valor nominal, "
        "corrigido por IPCA)",
        "criterios_elegibilidade": NAO_INFORMADO, "agente_financeiro": "BNDESPAR", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo",
        "documentos_necessarios": "Parecer anual de auditoria independente registrada na CVM",
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-thai",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"Participação da BNDESPAR... Até 50% dos itens financiáveis... Valor mínimo da operação R$ "
            "10 milhões. Valor máximo da operação R$ 200 milhões... Prazo: 25 a 35 anos.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Inovação tecnológica",
        "tecnologias_relacionadas": "Propriedade intelectual, tecnologias proprietárias",
        "temas_inovacao": "Inovação tecnológica, debêntures participativas, propriedade intelectual",
        "temas_sustentabilidade": None,
        "sinonimos_termos": "thai debentures participativas inovacao BNDESPAR propriedade intelectual",
    },
    {
        "instituicao": "BNDES", "nome_oficial": "Fundo Clima - Florestas Nativas e Recursos Hídricos",
        "nome_simplificado": "Fundo Clima Florestas Nativas", "sigla": "Fundo Clima", "status": "aberta",
        "descricao_resumida": "Financiamento a projetos de conservação de florestas nativas e recursos hídricos, com recursos do Fundo Clima.",
        "descricao_completa": (
            "Financiamento direto a projetos de florestas nativas e recursos hídricos, com taxas "
            "diferenciadas para pessoas jurídicas de direito público (exceto União) e de direito privado."
        ),
        "modalidade": "Direta", "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Florestas nativas, recursos hídricos", "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO, "faixa_receita": NAO_INFORMADO, "regiao_elegivel": "Nacional",
        "destinacao": "Conservação de florestas nativas e recursos hídricos", "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO, "valor_minimo": 10_000_000, "valor_maximo": 250_000_000,
        "percentual_financiavel": "Até 100% dos itens financiáveis",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Pessoas Jurídicas de Direito Público (exceto União): Custo Financeiro 1,0% a.a. + "
        "Taxa do BNDES a partir de 1,2% a.a.; Pessoas Jurídicas de Direito Privado: Custo Financeiro 1,0% "
        "a.a. + Taxa do BNDES a partir de 1,3% a.a.",
        "indexador": NAO_INFORMADO, "spread": "A partir de 1,2%/1,3% a.a.",
        "prazo_total": "Limitado a 300 meses, incluído o prazo de carência de 96 meses",
        "carencia": "96 meses", "amortizacao": NAO_INFORMADO,
        "garantias": "Definidas na análise da operação",
        "restricoes": "R$ 250 milhões por grupo econômico a cada 12 meses; R$ 50 milhões para clientes "
        "Pessoas Jurídicas de Direito Público a cada 12 meses",
        "criterios_elegibilidade": NAO_INFORMADO, "agente_financeiro": "BNDES", "canal_contratacao": NAO_INFORMADO,
        "prazo_inscricao": NAO_INFORMADO, "fluxo": "continuo", "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/fundo-clima/fundo-clima-florestas-nativas-recursos-hidricos",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            "\"O valor mínimo de financiamento é de R$ 10 milhões... R$ 250 milhões por grupo econômico a "
            "cada 12 meses... Limitado a 300 meses, incluído o prazo de carência de 96 meses.\" "
            "(capturado ao vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada", "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO, "subsetor_padronizado": None, "cnaes_relacionados": None,
        "porte_padronizado": NAO_INFORMADO, "destinacao_padronizada": "Florestas nativas e recursos hídricos",
        "tecnologias_relacionadas": None, "temas_inovacao": None,
        "temas_sustentabilidade": "Florestas nativas, recursos hídricos, Fundo Clima",
        "sinonimos_termos": "fundo clima florestas nativas recursos hidricos conservacao agua",
    },
]


def seed_bndes_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _BNDES_MANUAL] + [dict(linha) for linha in _BNDES_MANUAL_EXPANSAO])


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
