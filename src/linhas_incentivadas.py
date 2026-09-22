"""Constroi a tabela `linhas_incentivadas` (catalogo de LINHAS/PROGRAMAS de credito,
diferente de `editais_raw`, que sao CHAMADAS PUBLICAS com prazo) a partir de fontes
LOCAIS/OFICIAIS -- o site hospedado so consulta esta tabela, nunca acessa os sites das
instituicoes em tempo real (ver item 6 do pedido de melhorias).

Sete fontes hoje:
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
4. BNB (Banco do Nordeste): curadoria manual verificada -- 23 linhas, capturadas
   navegando o menu real de bnb.gov.br (pagina /fne + /mapa-do-site, sem API de
   busca nem JS -- diferente do BNDES): 16 produtos FNE por segmento (Industrial,
   Agrin, Agro Conectado, Aquipesca, Comercio e Servicos, Giro, Inovacao,
   Irrigacao, MPE, P-Fies, Proatur, Proinfra, Rural, Saude Nordeste, Sol, Startup,
   Verde), 1 linha de custeio agricola/pecuario (FNE), 4 produtos "Cartao BNB"
   (FNE e/ou recursos proprios) e o FDNE (Fundo de Desenvolvimento do Nordeste,
   gerido pela Sudene, BNB como agente operador -- nao e FNE). Nao encontrada
   pagina publica para "FNE Exportacao" nem para uma linha isolada de "FNE Mulher
   Negocios" (o beneficio a empresas controladas por mulheres e uma clausula
   transversal dentro de cada linha, nao um produto proprio).
5. BASA (Banco da Amazonia): curadoria manual verificada, adicionada em 2026-09-15 --
   9 linhas: 8 sub-linhas do FNO (Fundo Constitucional de Financiamento do Norte --
   Amazonia Rural, Amazonia Empresarial, Amazonia Empresarial Verde, Amazonia
   Infraestrutura, Amazonia Infraestrutura Verde, Ciencia/Tecnologia e Inovacao,
   Biodiversidade, Energia Verde) capturadas navegando bancoamazonia.com.br/
   linhas-de-fomento/fno/<produto> (paginas estaticas, sem acordeao JS) + 1 linha
   do FDA (Fundo de Desenvolvimento da Amazonia, gerido pela SUDAM, BASA como
   agente operador -- mesmo padrao do FDNE/BNB). A pagina de listagem do BASA
   tambem lista FMM, PRONAF, FUNGETUR e produtos BNDES (Finame/Automatico) como
   "linhas de fomento" -- deliberadamente NAO curados aqui pra nao duplicar
   produtos que ja pertencem a outra instituicao neste catalogo (BNDES) ou que
   sao geridos por outros ministerios/fundos sem pagina propria detalhada no site
   do BASA.
6. BB (Banco do Brasil): curadoria manual verificada, adicionada em 2026-09-15 --
   9 linhas de credito rural/fomento (Pronamp Investimento, Pronamp Custeio, Pronaf
   Grupo B, Pronaf Custeio A/C, Custeio Agropecuario, Funcafe Custeio, Programa
   Nacional de Credito Fundiario, RenovAgro e FCO Rural -- Investimento
   Agropecuario), capturadas em bb.com.br/site/agronegocios/. Deliberadamente
   restrito a linhas de fomento/credito rural incentivado (Pronaf/Pronamp/fundos
   constitucionais/programas do MCR com taxa fixada por normativo do CMN) --
   excluidos de proposito produtos bancarios comuns do mesmo portal (cartao Ourocard,
   consorcio, seguros, BB Giro Agro generico) e outras dezenas de linhas do MCR
   listadas no hub /investimentos/ (Inovagro, Moderfrota, Proirriga, etc. -- ja
   existem em quantidade suficiente via BB pra nao inflar o catalogo repetindo
   praticamente o mesmo programa nacional sob nomes ligeiramente diferentes).
   Achado tecnico: varias paginas do BB renderizam a resposta do FAQ (accordion)
   via Angular mas ja trazem o texto completo (pergunta+resposta) embutido no DOM
   num bloco JSON-LD FAQPage (`.elementor-widget-bb-dls-faq`) mesmo com o item
   still colapsado na tela -- extraido via `textContent` em vez de clicar item por
   item (mais confiavel que a simulacao de clique, que em alguns casos reordena o
   accordion entre cliques).
7. CEF (Caixa Economica Federal): curadoria manual verificada, adicionada em
   2026-09-15 -- 6 linhas (Financiamento ESG Ecoeficiencia para a Rede de Atacado,
   BCD Ecoeficiencia PJ, BCD Franquias, FDA -- Fundo de Desenvolvimento da Amazonia
   (a Caixa tambem e agente financeiro/operador do FDA, com pagina propria mais
   detalhada que a do BASA para o mesmo fundo -- nao e duplicidade, sao dois
   agentes financeiros distintos do mesmo fundo gerido pela SUDAM), Programa
   Sustentabilidade e Programa Armazenagem -- estes dois ultimos dentro do hub
   Agro CAIXA). Cobertura deliberadamente menor que BNDES/BB/BASA -- confirmado ao
   vivo que a Caixa e mais forte em habitacao/saneamento/setor publico do que em
   credito empresarial/rural incentivado; dezenas de outras linhas do hub Agro
   CAIXA (Pronaf, Pronamp, Inovagro, Moderfrota, Proirriga etc.) sao os MESMOS
   programas nacionais do MCR ja curados via BB, entao nao foram re-curadas aqui
   (seria o mesmo programa sob outro agente financeiro, sem trazer produto novo).
   Achado tecnico: `caixa.gov.br` devolve 403/loop de redirecionamento para
   WebFetch simples (bloqueio de user-agent) -- precisou do Browser pane (render
   completo, inclusive cookies) pra funcionar.

Nenhuma das 7 fontes usa scraping automatizado continuo (so a FINEP tem uma API
oficial estruturada ja consumida por outro modulo) -- as demais sao atualizadas
manualmente, sob demanda, ate que scrapers dedicados sejam construidos e
verificados against a estrutura real (e razoavelmente estavel) de cada site.
"""
import datetime
import json
import re
import unicodedata

from db import get_connection


def _agora() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# ============ Bucketing de Porte/Destinação (filtros de UI, "Potenciais Linhas") ============
# `porte_padronizado` (42 valores de texto livre, ex: "Micro, Pequena, Médias,
# Média-Grande, Pré-operacional") e `destinacao_padronizada` (97 valores, maioria
# com 1 ocorrencia so) sao granulares demais pra um <select> de filtro utilizavel.
# As duas funcoes abaixo colapsam pra um punhado de categorias por
# regex/keyword sobre o texto original -- NUNCA inventam um valor novo (o campo
# fonte continua intacto, isto e so uma leitura simplificada dele) e sao
# deliberadamente conservadoras: quando o texto nao da sinal claro o suficiente,
# caem em "Não informado"/"Outros" em vez de arriscar uma categoria errada.
NAO_INFORMADO_GRUPO = "Não informado"


def _calcular_porte_grupo(porte_padronizado: str) -> str:
    """Bucketing pedido: contem micro/pequena SEM media/grande -> 'Micro/Pequena';
    contem media -> 'Média'; contem grande -> 'Grande'; menciona multiplos portes
    (ou a frase 'todos os portes') -> 'Todos os portes'; vazio/nao informado ->
    'Não informado'. Texto livre real as vezes cita 2+ faixas ao mesmo tempo (ex:
    'Pequena-média Empresa, Média Empresa, Grande Empresa') -- tratado como
    'Todos os portes' (o balde que junta qualquer combinacao de 2+ faixas), nao
    como erro: o objetivo e so eliminar a fragmentacao de 42 valores, nao
    reconstruir a faixa exata."""
    if not porte_padronizado:
        return NAO_INFORMADO_GRUPO
    texto = _sem_acento(porte_padronizado).lower()
    if "nao informado" in texto:
        return NAO_INFORMADO_GRUPO
    if "todos os portes" in texto or "todos os tamanhos" in texto:
        return "Todos os portes"

    tem_micro_pequena = bool(re.search(r"micro|pequen", texto))
    tem_media = bool(re.search(r"m[ea]di", texto))
    tem_grande = bool(re.search(r"grand", texto))
    grupos_presentes = sum([tem_micro_pequena, tem_media, tem_grande])

    if grupos_presentes >= 2:
        return "Todos os portes"
    if tem_micro_pequena:
        return "Micro/Pequena"
    if tem_media:
        return "Média"
    if tem_grande:
        return "Grande"
    # Texto sem nenhuma palavra de porte reconhecida (ex: "Cooperativas",
    # "Produtores Rurais", "Agricultura familiar") -- nao ha como inferir faixa de
    # porte sem inventar, entao cai em "Não informado" (mesmo sentinela do caso
    # vazio).
    return NAO_INFORMADO_GRUPO


# Categorias de "uso dos recursos" -- adaptadas aos valores REAIS observados em
# destinacao_padronizada (97 distintos, ver recon anterior), nao uma taxonomia
# inventada do zero. Ordem da lista = ordem de prioridade do match (primeira
# regex que bater decide o balde) -- categorias mais especificas (agropecuario,
# infraestrutura, eficiencia energetica) vem antes das mais genericas
# (capex/investimento) pra nao "engolir" um caso mais especifico so porque o
# texto tambem contem a palavra "investimento".
_DESTINACAO_GRUPOS = [
    ("Capital de giro", r"capital de giro|custeio.*cartao|rotativo"),
    ("Agropecuário / Rural", r"agro|agricul|rural|pecuar|aquicultura|pesca|silvicultura|florest|biodiversidade|cafeicultura"),
    ("Eficiência energética / Sustentabilidade", r"eficiencia energetica|sustenta|baixo carbono|energia renovavel|esg|ecoeficiencia"),
    ("Infraestrutura", r"infraestrutura|saneamento|mobilidade|rede.*telecomunica|transporte|log[ií]stica|energia eletrica|armazenagem"),
    ("Inovação / P&D", r"inovac|tecnolog|pesquisa e desenvolvimento|p ?& ?d"),
    ("Máquinas e equipamentos", r"maquinas e equipamentos|bens de capital"),
    ("Comércio e serviços", r"comercio|servicos|franquia"),
    ("CAPEX / Projetos de investimento", r"investimento|capex|amplia|moderniza|implanta|expans|aquisicao de (bens|terras)"),
]


def _calcular_destinacao_grupo(destinacao_padronizada: str) -> str:
    """Mesma logica de _calcular_porte_grupo, aplicada a destinacao_padronizada --
    ver _DESTINACAO_GRUPOS acima pras categorias e a ordem de prioridade. Cai em
    'Outros' quando o texto existe mas nao bate nenhum padrao reconhecido (nunca
    em 'Não informado' nesse caso, reservado pro campo vazio/NAO_INFORMADO --
    'Outros' sinaliza "tem dado real, so nao teve categoria propria", diferente
    de "não sabemos")."""
    if not destinacao_padronizada:
        return NAO_INFORMADO_GRUPO
    texto = _sem_acento(destinacao_padronizada).lower()
    if "nao informado" in texto:
        return NAO_INFORMADO_GRUPO
    for grupo, padrao in _DESTINACAO_GRUPOS:
        if re.search(padrao, texto):
            return grupo
    return "Outros"


def backfill_porte_e_destinacao_grupo(conn) -> int:
    """Recalcula porte_grupo/destinacao_grupo pra TODAS as linhas ja gravadas --
    chamada no fim de build_linhas_incentivadas() (idempotente, sem custo real:
    112 linhas) pra manter as duas colunas em sincronia mesmo pra linhas que nao
    foram re-upsertadas nesta rodada (_upsert_many ja calcula as duas na hora do
    insert/update, mas so pras linhas processadas naquela chamada especifica)."""
    linhas = conn.execute("SELECT id, porte_padronizado, destinacao_padronizada FROM linhas_incentivadas").fetchall()
    cur = conn.cursor()
    total = 0
    for linha_id, porte, destinacao in linhas:
        cur.execute(
            "UPDATE linhas_incentivadas SET porte_grupo = ?, destinacao_grupo = ? WHERE id = ?",
            (_calcular_porte_grupo(porte), _calcular_destinacao_grupo(destinacao), linha_id),
        )
        total += 1
    conn.commit()
    return total


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
    "sinonimos_termos", "search_document", "porte_grupo", "destinacao_grupo",
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
        linha["porte_grupo"] = _calcular_porte_grupo(linha.get("porte_padronizado"))
        linha["destinacao_grupo"] = _calcular_destinacao_grupo(linha.get("destinacao_padronizada"))

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


# FINEP: curadoria manual VERIFICADA das linhas de CREDITO PERMANENTES (fluxo=
# "continuo"), no mesmo padrao de BNDES/Desenvolve SP/BNB -- NAO confundir com os
# EDITAIS (chamadas publicas com prazo, ja cobertas pela aba "Editais" do site, ver
# tabela editais_raw). A funcao importar_finep_editais() abaixo foi a abordagem
# ORIGINAL (1 linha_incentivada por edital), mas isso duplicava a aba Editais dentro
# do catalogo de "Linhas Incentivadas" (que deveria mostrar produtos permanentes,
# nao chamadas com prazo) -- pedido explicito do usuario pra tirar. Mantida definida
# (nao chamada em build_linhas_incentivadas) caso sirva de referencia futura.
#
# Fonte real verificada ao vivo em 2026-09-04: legacy.finep.gov.br/area-para-
# clientes-externo/finep-inovacao ("Crédito (Financiamento Reembolsável Direto)") --
# a pagina de detalhe de cada instrumento ("Conheça o instrumento") retorna 404 no
# site da FINEP (link quebrado no proprio site oficial, confirmado), entao os campos
# de valor/taxa/prazo ficam NAO_INFORMADO (nao ha onde verificar, nunca inventado).
_FINEP_MANUAL = [
    {
        "instituicao": "FINEP",
        "nome_oficial": "Apoio Direto à Inovação",
        "nome_simplificado": "Apoio Direto à Inovação",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Financiamento reembolsável direto da FINEP para atividades inovadoras de empresas brasileiras.",
        "descricao_completa": (
            "Tem por objetivo apoiar as atividades inovadoras das empresas brasileiras, com "
            "vistas a aumentar a competitividade nacional e internacional de empresas "
            "brasileiras; incrementar atividades de Pesquisa, Desenvolvimento e Inovação "
            "realizadas no país; e contribuir para o adensamento tecnológico das cadeias "
            "produtivas nacionais e para maior inserção das empresas brasileiras nas cadeias "
            "globais de valor. A FINEP utiliza metodologia própria para avaliação de planos "
            "estratégicos de inovação, reduzindo prazos e aumentando qualidade e transparência "
            "das análises."
        ),
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento reembolsável",
        "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Atividades inovadoras (Pesquisa, Desenvolvimento e Inovação) de empresas brasileiras",
        "itens_financiaveis": NAO_INFORMADO,
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
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "FINEP",
        "canal_contratacao": "Sistema próprio da FINEP (área para clientes)",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://legacy.finep.gov.br/area-para-clientes-externo/finep-inovacao",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            '"O Apoio Direto a Inovação tem por objetivo apoiar as atividades inovadoras das '
            'empresas brasileiras... A Finep utiliza metodologia inovadora para avaliação de '
            'planos estratégicos de inovação" (capturado ao vivo da página oficial em '
            '2026-09-04; a página de detalhe do instrumento, "Conheça o instrumento", retorna '
            "404 no próprio site da FINEP)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Inovação",
        "tecnologias_relacionadas": None,
        "temas_inovacao": "Pesquisa, Desenvolvimento e Inovação (P&D&I)",
        "temas_sustentabilidade": None,
        "sinonimos_termos": "credito inovacao pesquisa e desenvolvimento P&D&I financiamento reembolsavel",
    },
    {
        "instituicao": "FINEP",
        "nome_oficial": "Apoio Direto a Pré-Investimento",
        "nome_simplificado": "Apoio Direto a Pré-Investimento",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Financiamento reembolsável direto da FINEP para consolidação de conhecimento técnico em serviços de engenharia.",
        "descricao_completa": (
            "Tem por objetivo apoiar a consolidação de conhecimento técnico em serviços de "
            "engenharia no País."
        ),
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento reembolsável",
        "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Serviços de engenharia (consolidação de conhecimento técnico)",
        "itens_financiaveis": NAO_INFORMADO,
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
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "FINEP",
        "canal_contratacao": "Sistema próprio da FINEP (área para clientes)",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://legacy.finep.gov.br/area-para-clientes-externo/finep-inovacao",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": (
            '"Já o Apoio Direto a Pré-Investimento tem por objetivo apoiar a consolidação de '
            'conhecimento técnico em serviços de engenharia no País" (capturado ao vivo da '
            'página oficial em 2026-09-04; a página de detalhe do instrumento retorna 404 no '
            "próprio site da FINEP)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Engenharia",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "credito pre-investimento engenharia financiamento reembolsavel",
    },
]


def seed_finep_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _FINEP_MANUAL])


def importar_finep_editais(conn) -> int:
    """FINEP: uma linha_incentivada por edital em editais_raw -- fluxo='edital'.

    NAO chamada mais em build_linhas_incentivadas() (ver seed_finep_manual acima) --
    mantida so como referencia/caso sirva pra outro uso no futuro."""
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
# garantias/limites de financiamento por porte). Expandido em 2026-09-04 (ver
# _BNB_MANUAL_EXPANSAO abaixo) navegando o menu real do site bnb.gov.br (pagina
# /fne e /mapa-do-site) -- painel de link estatico, sem necessidade de API de
# busca interna nem de JS para acordeons (diferente do BNDES).
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


def _linha_fne(
    nome_oficial, descricao_resumida, descricao_completa, setores_elegiveis,
    porte_elegivel, destinacao, itens_financiaveis, percentual_financiavel,
    prazo_total, carencia, garantias, taxa_completa, url_slug, trecho_fonte,
    *, sigla="FNE", valor_minimo=None, valor_maximo=None, contrapartida=NAO_INFORMADO,
    indexador=NAO_INFORMADO, spread=NAO_INFORMADO, amortizacao=NAO_INFORMADO,
    restricoes=NAO_INFORMADO,
    criterios_elegibilidade="Cadastro e limite de crédito aprovados no Banco do Nordeste",
    documentos_necessarios="Projeto de Financiamento ou Proposta de Crédito",
    prazo_inscricao=NAO_INFORMADO, data_vigencia=NAO_INFORMADO,
    setor_padronizado=NAO_INFORMADO, subsetor_padronizado=None, porte_padronizado=None,
    destinacao_padronizada=None, temas_inovacao=None, temas_sustentabilidade=None,
    sinonimos_termos=None, itens_nao_financiaveis=NAO_INFORMADO,
    setores_nao_elegiveis=NAO_INFORMADO, faixa_receita=NAO_INFORMADO,
    tipo_apoio="Financiamento", modalidade="Direta",
    regiao_elegivel="Nordeste e Norte de Minas Gerais e Espírito Santo (área de atuação do FNE)",
    agente_financeiro="Banco do Nordeste (Fundo Constitucional de Financiamento do Nordeste - FNE)",
    canal_contratacao="Gerente de relacionamento / agências do Banco do Nordeste",
    fluxo="continuo",
):
    """Helper pra reduzir repeticao das dezenas de linhas do FNE -- cada pagina de
    produto em bnb.gov.br segue a MESMA estrutura estatica (Objetivo / Publico /
    O que Financia / Fonte de Recursos / tabela Prazo x Finalidade x Carencia x
    Total / Garantias / Juros e Bonus de Adimplencia / Limites de Financiamento /
    Acesso ao Financiamento), sem paginacao JS nem acordeao -- diferente do BNDES.
    Campos com estrutura tabular (prazo/carencia por finalidade, percentual por
    porte) sao condensados em texto (mesmo padrao usado no FNE Inovacao original),
    nunca inventados quando a pagina nao detalha."""
    return {
        "instituicao": "BNB",
        "nome_oficial": nome_oficial,
        "nome_simplificado": nome_oficial,
        "sigla": sigla,
        "status": "aberta",
        "descricao_resumida": descricao_resumida,
        "descricao_completa": descricao_completa,
        "modalidade": modalidade,
        "tipo_apoio": tipo_apoio,
        "setores_elegiveis": setores_elegiveis,
        "setores_nao_elegiveis": setores_nao_elegiveis,
        "porte_elegivel": porte_elegivel,
        "faixa_receita": faixa_receita,
        "regiao_elegivel": regiao_elegivel,
        "destinacao": destinacao,
        "itens_financiaveis": itens_financiaveis,
        "itens_nao_financiaveis": itens_nao_financiaveis,
        "valor_minimo": valor_minimo,
        "valor_maximo": valor_maximo,
        "percentual_financiavel": percentual_financiavel,
        "contrapartida": contrapartida,
        "taxa_completa": taxa_completa,
        "indexador": indexador,
        "spread": spread,
        "prazo_total": prazo_total,
        "carencia": carencia,
        "amortizacao": amortizacao,
        "garantias": garantias,
        "restricoes": restricoes,
        "criterios_elegibilidade": criterios_elegibilidade,
        "agente_financeiro": agente_financeiro,
        "canal_contratacao": canal_contratacao,
        "prazo_inscricao": prazo_inscricao,
        "fluxo": fluxo,
        "documentos_necessarios": documentos_necessarios,
        "url_oficial": url_slug,
        "data_vigencia": data_vigencia,
        "trecho_fonte": trecho_fonte,
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": setor_padronizado,
        "subsetor_padronizado": subsetor_padronizado,
        "cnaes_relacionados": None,
        "porte_padronizado": porte_padronizado or porte_elegivel,
        "destinacao_padronizada": destinacao_padronizada or destinacao,
        "tecnologias_relacionadas": None,
        "temas_inovacao": temas_inovacao,
        "temas_sustentabilidade": temas_sustentabilidade,
        "sinonimos_termos": sinonimos_termos,
    }


# Expansao de 2026-09-04: navegado o menu real de bnb.gov.br (pagina /fne lista os
# hrefs /fne-<produto>; /mapa-do-site confirma nao haver outras linhas FNE fora
# desse menu). 17 produtos FNE (alem do FNE Inovacao ja existente) + 1 linha de
# custeio agricola/pecuario (FNE) + 4 produtos "Cartao BNB" (FNE e/ou recursos
# proprios) + o FDNE (Fundo de Desenvolvimento do Nordeste, gerido pela Sudene,
# NAO e FNE -- BNB atua como agente operador). NAO encontradas paginas
# publicamente navegaveis para "FNE Exportacao" nem para uma linha isolada de
# "FNE Mulher Negocios" -- o beneficio para empresas controladas por mulheres
# (carencia/prazo adicional, capital de giro ampliado) aparece como CLAUSULA
# TRANSVERSAL dentro de cada linha acima, nao como produto proprio; "Agroamigo
# Sol" (microcredito Pronaf para agricultura familiar) e "Prodeter" (metodologia
# de desenvolvimento territorial, sem termos de credito) foram verificados e
# EXCLUIDOS por estarem fora do escopo de credito empresarial/produtivo do FNE
# coberto pelas demais fontes deste catalogo.
_BNB_MANUAL_EXPANSAO = [
    _linha_fne(
        "FNE Industrial",
        "Programa de Apoio ao Setor Industrial do Nordeste, com recursos do FNE.",
        "Desenvolver o setor industrial, por meio da modernização, aumento da competitividade, "
        "ampliação da capacidade produtiva e inserção internacional.",
        "Indústria", "Pequena-média Empresa, Média Empresa, Grande Empresa",
        "Modernização, aumento da competitividade, ampliação da capacidade produtiva e inserção "
        "internacional do setor industrial",
        "Investimentos, inclusive aquisição de empreendimentos com unidades industriais já construídas "
        "ou em construção; construção/reforma/ampliação de benfeitorias e instalações (vedada reforma de "
        "moradia); pesquisa mineral e caracterização de minérios; aquisição de veículos utilitários; "
        "modernização de máquinas e equipamentos; móveis e utensílios; aquisição de imóvel urbano com "
        "edificações concluídas para empresas com faturamento até R$ 16 milhões; reforma/requalificação/"
        "retrofit de prédios degradados em áreas centrais/históricas; consultorias de acompanhamento e "
        "monitoramento de impactos sociais e ambientais; capital de giro associado ao investimento",
        "Pequena-Média (receita R$ 4,8mi-R$16mi): 90 a 100% (mínimo de recursos próprios até 10%); "
        "Média I (R$16mi-R$90mi): 80 a 95% (mínimo 5 a 20%); Média II (R$90mi-R$300mi): 70 a 85% "
        "(mínimo 15 a 30%); Grande PRDNE (>R$300mi): 70 a 80% (mínimo 20 a 30%); Grande (>R$300mi): 50% "
        "(mínimo 50%); projetos aderentes ao PTE ou às missões nº1/3/4/5 da Nova Indústria Brasil: até "
        "100%, independente do porte. Capital de giro associado limitado a 1/3 do total financiado (40% "
        "para empresas controladas por mulheres com participação >40%).",
        "Investimentos Fixos e Mistos: até 12 anos; projetos de alta relevância/estruturantes no "
        "Semiárido, municípios de baixa renda/estagnados ou áreas prioritárias do PRDNE: até 15 anos; "
        "Aquisição de Móveis e Utensílios: até 6 anos; Aquisição Isolada de Meios de Transportes: até 8 "
        "anos; Aquisição Isolada de Ônibus/Micro-ônibus/Caminhões: até 10 anos",
        "Investimentos Fixos e Mistos: até 4 anos; projetos de alta relevância: até 5 anos; demais "
        "finalidades isoladas: até 1 ano; +1 a 2 anos adicionais para empresas controladas por mulheres "
        "ou com participação acionária feminina superior a 40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-industrial",
        "\"Desenvolver o setor industrial, por meio da modernização, aumento da competitividade, "
        "ampliação da capacidade produtiva e inserção internacional... Fonte de Recursos: Fundo "
        "Constitucional de Financiamento do Nordeste (FNE)\" (capturado ao vivo da página oficial em "
        "2026-09-04)",
        setor_padronizado="INDUSTRIA",
        sinonimos_termos="industria industrial modernizacao competitividade nordeste",
    ),
    _linha_fne(
        "FNE Agrin",
        "Programa de Financiamento para Comercialização, Beneficiamento ou Industrialização de Produtos "
        "de Origem Agropecuária, com recursos do FNE.",
        "Desenvolver o segmento agroindustrial por meio da expansão, diversificação e aumento da "
        "competitividade das empresas.",
        "Agroindústria", "Pequeno-médio Produtor, Médio Produtor, Grande Produtor, Pequena-média "
        "Empresa, Média Empresa, Grande Empresa, Cooperativas Rurais, Associações Rurais",
        "Comercialização, beneficiamento ou industrialização de produtos de origem agropecuária",
        "Aquisição de bens de capital e implantação/modernização/reforma/relocalização/ampliação de "
        "empreendimentos agroindustriais; construção para reforma e ampliação de benfeitorias e "
        "instalações; aquisição de veículos utilitários; modernização de máquinas e equipamentos; frete "
        "para transporte e montagem de máquinas e equipamentos financiados; aquisição de móveis e "
        "utensílios; elaboração de estudos ambientais; prêmios de seguro dos bens dados em garantia; "
        "aquisição da produção agropecuária para industrialização ou beneficiamento; aquisição/ampliação/"
        "modernização/reforma/construção de estruturas de armazenagem (armazéns, silos, câmaras frias); "
        "aquisição de imóvel urbano para empresas com faturamento até R$ 16 milhões; capital de giro "
        "associado ao investimento",
        "Pequena-Média: 90 a 100% (mínimo até 10%); Média I: 80 a 95% (mínimo 5 a 20%); Média II: 70 a "
        "85% (mínimo 15 a 30%); Grande PRDNE: 70 a 80% (mínimo 20 a 30%); Grande: 50% (mínimo 50%); "
        "projetos PTE ou Nova Indústria Brasil (missões 1/3/4/5): até 100%. Capital de giro associado "
        "limitado a 1/3 do total financiado (40% para empresas controladas por mulheres >40%).",
        "Investimentos Fixos e Mistos: até 12 anos; projetos de alta relevância/semiárido/áreas "
        "prioritárias PRDNE: até 15 anos; estruturas de armazenagem: até 15 anos; móveis e utensílios: "
        "até 6 anos; meios de transporte isolados: até 8 anos; capital de giro: até 8 meses",
        "Investimentos Fixos e Mistos: até 4 anos; alta relevância/armazenagem: até 5 anos; móveis e "
        "utensílios/meios de transporte: até 1 ano; capital de giro: sem carência específica informada; "
        "+1 a 2 anos adicionais para empresas controladas por mulheres com participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-agrin",
        "\"Desenvolver o segmento agroindustrial por meio da expansão, diversificação e aumento da "
        "competitividade das empresas... Fonte de Recursos: Fundo Constitucional de Financiamento do "
        "Nordeste (FNE)\" (capturado ao vivo da página oficial em 2026-09-04)",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        sinonimos_termos="agroindustria beneficiamento industrializacao produtos agropecuarios",
    ),
    _linha_fne(
        "FNE Agro Conectado",
        "Iniciativa de incentivo à conexão no campo, com recursos do FNE.",
        "Possibilitar a conexão no campo por meio do financiamento de equipamentos e estruturas de "
        "ligação à internet e de programas de software para incorporação de novas tecnologias de "
        "informação e comunicação (TIC) em empreendimentos rurais.",
        "Agronegócio", "Produtores Rurais, Associações Rurais, Cooperativas Rurais",
        "Conectividade no meio rural",
        "Estação Rádio Base (torre/poste, antenas e rádios transmissores); equipamentos de ponto de "
        "acesso (eNodeB LTE, NB-IoT, Access Point Wi-Fi); infraestrutura civil/elétrica/climatização/"
        "cabeamento/rack/nobreak para instalação dos equipamentos; dispositivos de última milha "
        "(roteadores, switches, conversores ópticos, rádios clientes, terminais de conectividade em "
        "máquinas agrícolas, computadores, dispositivos móveis, backhaul); softwares de gestão e "
        "controle; serviços de instalação; torres e antenas de transmissão/recepção; outros itens "
        "relacionados à conectividade no meio rural",
        NAO_INFORMADO,
        "Investimento Fixo (Setor Rural): até 15 anos; Investimento Semifixo (Setor Rural): até 8 anos; "
        "Investimento Fixo e Misto (Setores Não Rurais): até 15 anos",
        "Investimento Fixo (Rural): até 5 anos; Investimento Semifixo (Rural): até 3 anos; Investimento "
        "Fixo e Misto (Não Rural): até 5 anos; +1 a 2 anos adicionais para produtoras rurais/empresas "
        "controladas por mulheres com participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        NAO_INFORMADO,
        "https://www.bnb.gov.br/fne-agro-conectado",
        "\"Possibilitar a conexão no campo por meio do financiamento de equipamentos e estruturas de "
        "ligação à internet... Fonte de Recursos: Fundo Constitucional de Financiamento do Nordeste "
        "(FNE)\" (capturado ao vivo da página oficial em 2026-09-04)",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        sinonimos_termos="conectividade rural internet banda larga campo tic",
    ),
    _linha_fne(
        "FNE Aquipesca",
        "Programa de Apoio ao Desenvolvimento da Aquicultura e Pesca, com recursos do FNE.",
        "Desenvolver a aquicultura e pesca por meio do fortalecimento e modernização da infraestrutura "
        "produtiva, embarcações oceânicas, uso sustentável dos recursos pesqueiros e preservação do "
        "meio ambiente.",
        "Agronegócio (aquicultura e pesca)", "Miniprodutor Rural, Pequeno-médio Produtor, Médio "
        "Produtor, Grande Produtor, Empresas, Cooperativas Rurais, Associações Rurais",
        "Aquicultura e pesca",
        "Implantação, ampliação, modernização e reforma de empreendimentos de aquicultura e pesca "
        "(investimentos fixos e semifixos), inclusive produção de insumos, beneficiamento, preparação, "
        "comercialização, armazenamento e embarcações oceânicas; aquisição/ampliação/modernização/"
        "reforma/construção de estruturas de armazenagem; consultorias de acompanhamento e monitoramento "
        "de impactos sociais e ambientais",
        "Miniprodutor (receita até R$360mil): 100%; Pequeno produtor (até R$4,8mi): 100%; "
        "Pequeno-médio (R$4,8mi-R$16mi): 90 a 100% (mínimo até 10%); Médio I (R$16mi-R$90mi): 80 a 95% "
        "(mínimo 5 a 20%); Médio II (R$90mi-R$300mi): 70 a 85% (mínimo 15 a 30%); Grande PRDNE "
        "(>R$300mi): 70 a 80% (mínimo 20 a 30%); Grande (>R$300mi): 50% (mínimo 50%)",
        "Investimentos fixos: até 12 anos; investimentos semifixos: até 8 anos; construção/substituição "
        "de embarcação oceânica: até 20 anos; aquisição de embarcação oceânica: até 20 anos; "
        "modernização de embarcação: até 10 anos; conversão de embarcação: até 15 anos; equipagem de "
        "embarcação: até 5 anos; reparo de embarcações: até 3 anos",
        "Investimentos fixos: até 4 anos; investimentos semifixos: até 3 anos; construção/substituição "
        "de embarcação: até 4 anos; aquisição de embarcação: até 2 anos; modernização de embarcação: até "
        "3 anos; conversão de embarcação: até 4 anos; equipagem: até 3 anos; reparo: até 2 anos; +1 a 2 "
        "anos adicionais para produtoras rurais/empresas controladas por mulheres com participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.329/2026.",
        "https://www.bnb.gov.br/fne-aquipesca",
        "\"Desenvolver a aquicultura e pesca por meio do fortalecimento e modernização da infraestrutura "
        "produtiva, embarcações oceânicas, uso sustentável dos recursos pesqueiros e preservação do meio "
        "ambiente... Fonte de Recursos: Fundo Constitucional de Financiamento do Nordeste (FNE)\" "
        "(capturado ao vivo da página oficial em 2026-09-04)",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        sinonimos_termos="aquicultura pesca embarcacoes oceanicas piscicultura",
    ),
    _linha_fne(
        "FNE Comércio e Serviços",
        "Programa de Financiamento para os Setores Comercial e de Serviços, com recursos do FNE.",
        "Desenvolver os setores de comércio e serviços, apoiando a integração, a estruturação e o "
        "aumento da competitividade.",
        "Comércio e Serviços", "Pequena-média Empresa, Média Empresa, Grande Empresa (comércio e "
        "prestação de serviços)",
        "Integração, estruturação e aumento da competitividade dos setores de comércio e serviços",
        "Aquisição de bens de capital e implantação/modernização/reforma/relocalização/ampliação de "
        "empreendimentos; construção/reforma/ampliação de benfeitorias e instalações; móveis e "
        "utensílios; veículos utilitários; carros de passeio para autoescola/locadoras (pequeno-médio "
        "porte); embarcações; complexos prisionais de ressocialização via PPP; frete para transporte e "
        "montagem de máquinas e equipamentos; estudos ambientais; prêmios de seguro; imóvel urbano para "
        "empresas com faturamento até R$ 16 milhões; software nacional ou importado; consultorias de "
        "acompanhamento de impactos sociais e ambientais; capital de giro associado ao investimento",
        "Pequeno-Médio: 90 a 100% (mínimo até 10%); Médio I: 80 a 95% (mínimo 5 a 20%); Médio II: 70 a "
        "85% (mínimo 15 a 30%); Grande PRDNE: 70 a 80% (mínimo 20 a 30%); Grande: 50% (mínimo 50%). "
        "Capital de giro associado limitado a 1/3 do total financiado (40% para empresas controladas "
        "por mulheres >40%).",
        "Reforma/Reparação de Embarcações: até 5 anos; Móveis e Utensílios: até 6 anos; Meios de "
        "Transporte: até 8 anos; Veículos para Locadora: até 3 anos; Aquisição/Conversão/Modernização de "
        "Embarcações: até 12 anos; projetos de alta relevância/semiárido/PRDNE: até 15 anos; Serviços de "
        "Complexos Prisionais via PPP: até 20 anos; demais Investimentos Fixos e Mistos: até 12 anos; "
        "Ônibus/Micro-ônibus/Caminhão: até 10 anos",
        "Reforma/Reparação de Embarcações: até 2 anos; Móveis e Utensílios/Meios de Transporte/Ônibus: "
        "até 1 ano; Veículos para Locadora: até 3 meses; Embarcações/alta relevância: até 4-5 anos; "
        "Complexos Prisionais: até 5 anos; demais Investimentos Fixos e Mistos: até 4 anos; +1 a 2 anos "
        "adicionais para empresas controladas por mulheres com participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-comercio-e-servicos",
        "\"Desenvolver os setores de comércio e serviços, apoiando a integração, a estruturação e o "
        "aumento da competitividade... Fonte de Recursos: Fundo Constitucional de Financiamento do "
        "Nordeste (FNE)\" (capturado ao vivo da página oficial em 2026-09-04)",
        setor_padronizado="COMERCIO/SERVICOS",
        sinonimos_termos="comercio servicos varejo prestacao de servicos",
    ),
    _linha_fne(
        "FNE Giro",
        "Programa de Financiamento da Aquisição Isolada de Matérias-Primas, Insumos, Mercadorias e "
        "Gastos Gerais para o Funcionamento do Empreendimento, com recursos do FNE.",
        "Apoiar a produção industrial e agroindustrial e as atividades turística, comercial, de "
        "prestação de serviços e de infraestrutura da Região, exceto para Empresas de Médio e Grande "
        "Porte.",
        "Comércio, Turismo, Prestação de Serviços, Indústria, Cooperativas Rurais",
        "Microempresa, Pequena Empresa, Microempreendedor Individual, Cooperativas Rurais",
        "Capital de giro para aquisição isolada de matérias-primas, insumos, mercadorias e gastos gerais "
        "de funcionamento",
        "Matérias-primas e insumos do processo produtivo de indústrias/agroindústrias; mercadorias "
        "(inclusive máquinas, veículos, aeronaves, embarcações ou equipamentos) para constituição de "
        "estoques de empresas comerciantes; insumos de empresas de prestação de serviços (inclusive "
        "turísticas e de infraestrutura); gastos gerais na modalidade ressarcimento/reembolso (folha de "
        "pagamento exceto tributos, água/energia/comunicação, combustíveis e lubrificantes, manutenção "
        "de veículos/máquinas/equipamentos, postagem e frete, aluguel e condomínio)",
        NAO_INFORMADO,
        "Até 36 meses",
        "Até 6 meses",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor, Fundo de Liquidez",
        NAO_INFORMADO,
        "https://www.bnb.gov.br/fne-giro",
        "\"Apoiar a produção industrial e agroindustrial e as atividades turística, comercial, de "
        "prestação de serviços e de infraestrutura da Região, exceto para Empresas de Médio e Grande "
        "Porte... Financiamento: Até 06 (seis) meses de carência / Até 36 meses\" (capturado ao vivo da "
        "página oficial em 2026-09-04)",
        setor_padronizado=NAO_INFORMADO,  # produto transversal (industria/agroindustria/comercio/turismo/servicos), sem 1 setor honesto
        sinonimos_termos="capital de giro materias primas insumos mercadorias mpe",
    ),
    _linha_fne(
        "FNE Irrigação",
        "Programa de Financiamento à Agropecuária Irrigada, com recursos do FNE.",
        "Desenvolver a agropecuária irrigada na área de atuação da Sudene, visando à diversificação das "
        "atividades produtivas, adoção de práticas sustentáveis, utilização de tecnologias modernas e "
        "ecoeficientes e o incremento da oferta de alimentos e matérias-primas agroindustriais.",
        "Agronegócio (agropecuária irrigada)", "Miniprodutor, Pequeno Produtor, Pequeno-médio Produtor, "
        "Médio Produtor, Grande Produtor, Associações Rurais, Cooperativas Rurais",
        "Agropecuária irrigada",
        "Elaboração de projetos básicos e executivos de irrigação/drenagem e estudos ambientais e "
        "investimentos das condicionantes de licenças ambientais; investimentos para viabilização de "
        "projetos de irrigação e drenagem (inclusive mitigação de impactos e controle ambiental); "
        "capacitação tecnológica, treinamento e qualificação profissional até a fase pré-produtiva; "
        "aquisição/ampliação/modernização/reforma/construção de estruturas de armazenagem; consultorias "
        "de acompanhamento de impactos sociais e ambientais",
        "Miniprodutor: 100%; Pequeno produtor: 100%; Pequeno-médio: 90 a 100% (mínimo até 10%); Médio I: "
        "80 a 95% (mínimo 5 a 20%); Médio II: 70 a 85% (mínimo 15 a 30%); Grande PRDNE: 70 a 80% (mínimo "
        "20 a 30%); Grande: 50% (mínimo 50%)",
        "Projetos público-privados: até 20 anos; projetos de perímetros irrigados: até 24 anos; "
        "investimentos fixos: até 15 anos; investimentos semifixos: até 10 anos; acessórios/peças de "
        "reposição/manutenção: até 2 anos; utensílios agrícolas isolados: até 5 anos",
        "Projetos público-privados/perímetros irrigados: até 4 anos; investimentos fixos: até 4 anos; "
        "investimentos semifixos: até 3 anos; acessórios/manutenção: até 1 ano; utensílios agrícolas: "
        "até 1 ano; +1 a 2 anos adicionais para produtoras rurais/empresas controladas por mulheres com "
        "participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.329/2026.",
        "https://www.bnb.gov.br/fne-irrigacao",
        "\"Desenvolver a agropecuária irrigada na área de atuação da Sudene... Fonte de Recursos: Fundo "
        "Constitucional de Financiamento do Nordeste (FNE)\" (capturado ao vivo da página oficial em "
        "2026-09-04)",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        sinonimos_termos="irrigacao drenagem agropecuaria irrigada perimetros irrigados",
    ),
    _linha_fne(
        "FNE MPE",
        "Programa de Financiamento às Microempresas, Empresas de Pequeno Porte e ao Empreendedor "
        "Individual, com recursos do FNE.",
        "Desenvolver as microempresas, empresas de pequeno porte e microempreendedores individuais "
        "(MEIs) dos setores industrial, agroindustrial, mineração, turismo, comércio, prestação de "
        "serviços e empreendimentos culturais, bem como a produção, circulação, divulgação e "
        "comercialização de produtos e serviços culturais.",
        "Industrial, Agroindustrial, Mineração, Turismo, Comércio, Prestação de Serviços, Cultural",
        "Microempresa, Pequena Empresa, Microempreendedor Individual (MEI)",
        "Modernização, implantação, ampliação e capital de giro de micro e pequenas empresas e MEIs",
        "Aquisição de bens de capital e implantação/modernização/reforma/relocalização/ampliação; "
        "construção/reforma/ampliação de benfeitorias (exceto moradia); retrofit de prédios degradados "
        "em áreas centrais/históricas via PPP; veículos necessários ao funcionamento; máquinas e "
        "equipamentos e sua modernização; frete e montagem; unidades industriais construídas ou em "
        "construção; imóvel com edificações concluídas em área urbana; estudos ambientais; capital de "
        "giro associado ao investimento (exceto MEI); aquisição de produção agropecuária de produtores "
        "financiados pelo BNB via termos de parceria; adequação à LGPD (Lei nº 13.709/2018)",
        "Micro (receita até R$360mil): 100%; Pequeno (até R$4,8mi): 100%; MEI: até R$ 60 mil somadas "
        "todas as finalidades (capital de giro + investimento); MEI Transportador Autônomo de Cargas: "
        "até R$ 150 mil; MEI Transportador Autônomo de Passageiros: até R$ 100 mil; MEI demais casos: "
        "até a margem disponível no limite de crédito do cliente. Capital de giro associado limitado a "
        "1/3 do total financiado (40% para empresas controladas por mulheres >40%).",
        "MEI: até 60 meses; MEI Transportador Autônomo de Cargas: até 10 anos; embarcações de "
        "passageiros para MPE: até 5-15 anos; hotéis e meios de hospedagem para MPE: até 20 anos; "
        "embarcações de transporte de cargas/coletivo: até 12 anos; imóveis urbanos: até 15 anos; "
        "veículos para locadoras: até 3 anos; meio de transporte isolado: até 8 anos; móveis e "
        "utensílios: até 6 anos; investimentos fixos e mistos (turismo): até 15 anos; investimentos "
        "fixos e mistos (indústria/agroindústria/comércio/serviços): até 12 anos; ônibus/micro-ônibus/"
        "caminhão: até 10 anos; adequação LGPD: até 6 anos",
        "MEI: até 3 meses; MEI Transportador de Cargas: até 1 ano; embarcações de passageiros: até 2-5 "
        "anos; hotéis: até 5 anos; embarcações de transporte: até 4 anos; capital de giro para aquisição "
        "de produção agropecuária: sem carência; veículos para locadoras: até 3 meses; meio de "
        "transporte isolado/móveis e utensílios/ônibus/adequação LGPD: até 1 ano; investimentos fixos e "
        "mistos: até 4-5 anos; +1 a 2 anos adicionais para empresas controladas por mulheres com "
        "participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-mpe",
        "\"Desenvolver as microempresas, empresas de pequeno porte e de microempreendedores individuais "
        "(MEIs) dos setores industrial, agroindustrial, mineração, turismo, comércio, prestação de "
        "serviços e empreendimentos culturais... Fonte de Recursos: Fundo Constitucional de "
        "Financiamento do Nordeste (FNE)\" (capturado ao vivo da página oficial em 2026-09-04)",
        criterios_elegibilidade="Cadastro e limite de crédito aprovados no Banco do Nordeste",
        documentos_necessarios="Proposta de Crédito",
        setor_padronizado=NAO_INFORMADO,  # produto transversal (varios setores + cultura), sem 1 setor honesto
        sinonimos_termos="micro pequena empresa mei microempreendedor individual mpe",
    ),
    _linha_fne(
        "FNE P-Fies",
        "Programa de Financiamento Estudantil com recursos do FNE, para mensalidades de cursos "
        "superiores não gratuitos.",
        "Financiar estudantes regularmente matriculados em cursos superiores não gratuitos e com "
        "avaliação positiva nos processos conduzidos pelo Ministério da Educação.",
        NAO_INFORMADO, "Pessoa Física (estudante)",
        "Financiamento estudantil (mensalidades de ensino superior)",
        "Mensalidades de instituições de ensino de cursos superiores não gratuitos, incluindo unidades "
        "de ensino de educação profissional, técnica e tecnológica",
        "Até 100% do valor da mensalidade; durante o curso, o estudante paga apenas 35% do valor da "
        "mensalidade mais os juros (\"Parcela Reduzida\")",
        "Até três vezes o tempo de permanência do estudante na condição de financiado, tendo como "
        "referência o período regular de duração do curso",
        "Sem carência; o pagamento é iniciado a partir do segundo mês de financiamento",
        "Aval, Hipoteca",
        "Conforme Resolução CMN nº 4.642, de 28/02/2018.",
        "https://www.bnb.gov.br/fne-p-fies",
        "\"Financiar estudantes regularmente matriculados em cursos superiores não gratuitos e com "
        "avaliação positiva nos processos conduzidos pelo Ministério da Educação... Fonte de Recursos: "
        "Fundo Constitucional de Financiamento do Nordeste (FNE)\" (capturado ao vivo da página oficial "
        "em 2026-09-04)",
        criterios_elegibilidade="Estudante matriculado em instituição de ensino conveniada, com renda "
        "própria ou dependência financeira de responsável com cadastro ativo no Banco do Nordeste",
        documentos_necessarios="Identificação e CPF, comprovante de endereço, comprovante de renda ou "
        "declaração de dependência financeira, DRI (Documento de Regularidade de Inscrição) emitido pela "
        "instituição de ensino, documentação do avalista/responsável financeiro",
        canal_contratacao="Portal do aluno (solicitação digital) / agências do Banco do Nordeste",
        setor_padronizado=NAO_INFORMADO,  # credito pessoa fisica (educacao), fora da taxonomia setorial empresarial
        sinonimos_termos="fies financiamento estudantil ensino superior mensalidades pessoa fisica",
    ),
    _linha_fne(
        "FNE Proatur",
        "Programa de Apoio ao Turismo Regional, com recursos do FNE.",
        "Integrar e fortalecer a cadeia produtiva do turismo, contribuindo para a geração de emprego e "
        "para o desenvolvimento das potencialidades turísticas da região.",
        "Turismo", "Pequena-média Empresa, Média Empresa, Grande Empresa (setor de turismo)",
        "Integração e fortalecimento da cadeia produtiva do turismo",
        "Investimentos, inclusive aquisição de meios de hospedagem já construídos ou em construção; "
        "construção/reforma/ampliação de benfeitorias e instalações; aquisição de veículos; aquisição/"
        "conversão/modernização/reforma/reparação de embarcações de transporte turístico de passageiros; "
        "móveis e utensílios; imóvel urbano para empresas com faturamento até R$ 16 milhões; shoppings e "
        "outlets em cidades das Rotas Estratégicas do Turismo (MTur), exceto capitais; consultorias de "
        "acompanhamento de impactos sociais e ambientais; capital de giro associado ao investimento fixo",
        "Pequena-média: 90 a 100% (mínimo até 10%); Média I: 80 a 95% (mínimo 5 a 20%); Média II: 70 a "
        "85% (mínimo 15 a 30%); Grande PRDNE: 70 a 80% (mínimo 20 a 30%); Grande: 50% (mínimo 50%). "
        "Capital de giro associado limitado a 1/3 do total financiado (40% para empresas controladas "
        "por mulheres >40%).",
        "Meios de transporte isolados (exceto embarcações): até 8 anos; veículos para locadoras: até 3 "
        "anos; reforma/reparação de embarcação: até 5 anos; aquisição/conversão/modernização de "
        "embarcações de transporte turístico: até 15 anos; implantação de hotéis e meios de hospedagem: "
        "até 20 anos; móveis e utensílios: até 6 anos; ônibus/micro-ônibus/caminhão: até 10 anos; "
        "implantação de arenas multiuso: até 20 anos; demais investimentos fixos e mistos: até 15 anos",
        "Meios de transporte isolados: até 1 ano; veículos para locadoras: até 3 meses; reforma/"
        "reparação de embarcação: até 2 anos; embarcações de transporte turístico: até 5 anos; hotéis e "
        "meios de hospedagem: até 5 anos; arenas multiuso: até 5 anos; demais investimentos fixos e "
        "mistos: até 5 anos; +1 a 2 anos adicionais para empresas controladas por mulheres com "
        "participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-proatur",
        "\"Integrar e fortalecer a cadeia produtiva do turismo, contribuindo para a geração de emprego e "
        "para o desenvolvimento das potencialidades turísticas da região... Fonte de Recursos: Fundo "
        "Constitucional de Financiamento do Nordeste (FNE)\" (capturado ao vivo da página oficial em "
        "2026-09-04)",
        setor_padronizado="COMERCIO/SERVICOS", subsetor_padronizado="TURISMO",
        sinonimos_termos="turismo hospedagem hoteis proatur cadeia produtiva turistica",
    ),
    _linha_fne(
        "FNE Proinfra",
        "Programa de Financiamento à Infraestrutura Complementar da Região Nordeste, com recursos do "
        "FNE.",
        "Ampliar serviços de infraestrutura econômica, dando sustentação às atividades produtivas da "
        "região.",
        "Infraestrutura", "Microempresa, Pequena Empresa, Pequena-média Empresa, Média Empresa, Grande "
        "Empresa, Consórcios de Empresas, Empresas Públicas",
        "Ampliação de serviços de infraestrutura econômica",
        "Implantação, ampliação, modernização e reforma de empreendimentos; construção/reforma/ampliação "
        "de benfeitorias e instalações (exceto moradias); veículos utilitários; máquinas e equipamentos; "
        "frete e montagem; estudos ambientais; prêmios de seguro de bens em garantia; conectividade "
        "(fibra óptica, banda larga, telefonia móvel, backbone); consultorias de acompanhamento de "
        "impactos sociais e ambientais; capital de giro associado ao investimento",
        "Micro (receita até R$360mil): 100%; Pequeno (até R$4,8mi): 100%; Pequeno-Médio: 90 a 100% "
        "(mínimo até 10%); Médio I: 80 a 95% (mínimo 5 a 20%); Médio II: 70 a 85% (mínimo 15 a 30%); "
        "Grande PRDNE: 70 a 80% (mínimo 20 a 30%); Grande: 50% (mínimo 50%); projetos PTE: até 100%. "
        "Capital de giro associado limitado a 1/3 do total financiado (40% para empresas controladas "
        "por mulheres >40%).",
        "Investimentos Fixos e Mistos: até 12 anos; projetos de alta relevância/semiárido/PRDNE: até 15 "
        "anos; casos excepcionais justificados: até 20 anos; geração/transmissão de energia, portos e "
        "aeroportos: até 24 anos; distribuição de energia: até 20 anos; saneamento, mobilidade urbana, "
        "rodovias, ferrovias e hidrovias: até 34 anos",
        "Investimentos Fixos e Mistos: até 4 anos; alta relevância: até 5 anos; casos excepcionais: até "
        "4 anos; geração/transmissão de energia, portos e aeroportos: até 8 anos; distribuição de "
        "energia: até 8 anos; saneamento/mobilidade urbana/rodovias/ferrovias/hidrovias: até 8 anos; +1 "
        "a 2 anos adicionais para empresas controladas por mulheres com participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-proinfra",
        "\"Ampliar serviços de infraestrutura econômica, dando sustentação às atividades produtivas da "
        "região... Fonte de Recursos: Fundo Constitucional de Financiamento do Nordeste (FNE)\" "
        "(capturado ao vivo da página oficial em 2026-09-04)",
        setor_padronizado="INFRAESTRUTURA",
        sinonimos_termos="infraestrutura energia saneamento portos aeroportos rodovias conectividade",
    ),
    _linha_fne(
        "FNE Rural",
        "Programa de Apoio ao Desenvolvimento Rural do Nordeste, com recursos do FNE.",
        "Desenvolver a agropecuária e o setor florestal quando houver supressão de mata nativa, com a "
        "observância da legislação ambiental, exceto os que envolvam irrigação e drenagem.",
        "Agronegócio", "Produtores Rurais (todos os portes), Produtores de Sementes e Mudas, "
        "Associações Rurais, Cooperativas Rurais",
        "Agropecuária e setor florestal",
        "Investimentos Fixos: construção/reforma/ampliação de benfeitorias e instalações permanentes, "
        "destocamento, correção do solo (calagem e adubação intensiva); Investimentos Semifixos: "
        "instalações, máquinas, implementos, equipamentos (inclusive beneficiamento/industrialização da "
        "própria produção), tratores, colheitadeiras, veículos, embarcações, acessórios/peças de "
        "reposição, aquisição de reprodutores e matrizes de bovinos/bubalinos/caprinos/ovinos/suínos",
        "Miniprodutor (receita até R$360mil): 100%; Pequeno produtor (até R$4,8mi): 100%; Pequeno-médio: "
        "90 a 100% (mínimo até 10%); Médio I: 80 a 95% (mínimo 5 a 20%); Médio II: 70 a 85% (mínimo 15 a "
        "30%); Grande PRDNE: 70 a 80% (mínimo 20 a 30%); Grande: 50% (mínimo 50%)",
        "Investimento Fixo: até 12 anos; Investimento Semifixo: até 8 anos; Investimento em Armazenagem: "
        "até 15 anos; acessórios/peças de reposição/manutenção: até 2 anos; florestamento e "
        "reflorestamento: até 16 anos; utensílios agrícolas isolados: até 6 anos; projetos de alta "
        "relevância/PRDNE: até 15 anos; aeronave para pulverização agrícola: até 20 anos",
        "Investimento Fixo: até 4 anos; Investimento Semifixo: até 3 anos; Armazenagem: até 5 anos; "
        "acessórios/manutenção: até 1 ano; florestamento: até 7 anos; utensílios agrícolas: até 1 ano; "
        "alta relevância: até 5 anos; aeronave de pulverização: até 4 anos; +1 a 2 anos adicionais para "
        "produtoras rurais/empresas controladas por mulheres com participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.329/2026.",
        "https://www.bnb.gov.br/fne-rural",
        "\"Desenvolver a agropecuária e o setor florestal quando houver supressão de mata nativa, com a "
        "observância da legislação ambiental, exceto os que envolvam irrigação e drenagem... Fonte de "
        "Recursos: Fundo Constitucional de Financiamento do Nordeste (FNE)\" (capturado ao vivo da "
        "página oficial em 2026-09-04)",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        sinonimos_termos="agropecuaria pecuaria lavoura florestamento reflorestamento fne rural",
    ),
    _linha_fne(
        "FNE Saúde Nordeste",
        "Programa de Apoio ao Setor de Saúde do Nordeste, com recursos do FNE.",
        "Fomentar o desenvolvimento do complexo econômico industrial da saúde, promovendo a "
        "modernização, o aumento da competitividade, a ampliação da capacidade produtiva e da "
        "capacidade de atendimento da cadeia produtiva do setor.",
        "Saúde", "Microempresa, Pequena Empresa, Microempreendedor Individual, Pequena-média Empresa, "
        "Média Empresa, Grande Empresa (setor de saúde)",
        "Modernização e ampliação da capacidade produtiva e de atendimento do setor de saúde",
        "Investimentos, inclusive aquisição de empreendimentos industriais/hospitalares já construídos "
        "ou em construção; capital de giro associado ao investimento; construção/reforma/ampliação de "
        "benfeitorias (vedada reforma de moradia); veículos utilitários; helicópteros e aviões para "
        "transporte de passageiros enfermos; materiais/insumos/peças/componentes críticos ao setor; "
        "investimentos em TIC (salas cirúrgicas inteligentes, controle remoto de pacientes, "
        "telemedicina); desenvolvimento e produção de equipamentos e dispositivos médicos; modernização "
        "(retrofitagem) de máquinas e equipamentos; móveis e utensílios isolados; consultorias de "
        "acompanhamento de impactos sociais e ambientais",
        "Micro e Pequena empresa: 100% (fora do Semiárido/RIDEs/PRDNE, qualquer tipologia); Pequena-"
        "média: 90-100%; Média I: 80-95%; Média II: 70-85%; Grande considerada prioritária: 70-80% "
        "(percentuais sobem para localização no Semiárido/RIDEs/PRDNE e tipologia de baixa/média renda, "
        "chegando a 100% para micro/pequena). Capital de giro associado limitado a 1/3 do total "
        "financiado (40% para empresas controladas por mulheres >40%).",
        "Investimentos fixos e mistos: até 20 anos",
        "Investimentos fixos e mistos: até 5 anos; +1 a 2 anos adicionais para empresas controladas por "
        "mulheres com participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor, Recebíveis",
        "Conforme Resolução do Conselho Monetário Nacional (CMN) nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-saude-nordeste",
        "\"Fomentar o desenvolvimento do complexo econômico industrial da saúde, promovendo a "
        "modernização, o aumento da competitividade, a ampliação da capacidade produtiva e da capacidade "
        "de atendimento da cadeia produtiva do setor... Fonte de Recursos: Fundo Constitucional de "
        "Financiamento do Nordeste (FNE)\" (capturado ao vivo da página oficial em 2026-09-04)",
        setor_padronizado="COMERCIO/SERVICOS", subsetor_padronizado="SAÚDE",
        sinonimos_termos="saude hospitalar complexo economico industrial da saude telemedicina",
    ),
    _linha_fne(
        "FNE Sol",
        "Programa de Financiamento à Micro e Minigeração Distribuída de Energia Elétrica e Sistemas "
        "Off-grid, com recursos do FNE.",
        "Financiar projetos de micro e minigeração distribuída de energia por fontes renováveis, "
        "inclusive de forma isolada, para consumo próprio ou destinados à locação, reduzindo os custos "
        "com energia elétrica de forma sustentável.",
        NAO_INFORMADO, "Empresas, Produtores Rurais, Pessoa Física",
        "Micro e minigeração distribuída de energia renovável",
        "Todos os componentes dos sistemas de micro e minigeração de energia elétrica fotovoltaica, "
        "eólica, de biomassa ou pequenas centrais hidroelétricas (PCH), bem como sua instalação",
        "Até 100% do investimento, dependendo do porte, localização e garantias, com limite máximo de "
        "R$ 100.000,00 para micro e minigeradores pessoa física",
        "Empresas e Produtores Rurais: até 12 anos; Pessoa Física: até 8 anos; projetos de locação de "
        "sistemas de micro e minigeração: até 24 anos",
        "Empresas e Produtores Rurais: até 36 meses; Pessoa Física: até 6 meses; projetos de locação: "
        "até 12 meses; +1 a 2 anos adicionais para empresas controladas por mulheres com participação "
        "acionária superior a 40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca",
        "Setor rural: conforme Resolução CMN nº 5.235/2025; demais setores: conforme Resolução CMN nº "
        "5.013/2022.",
        "https://www.bnb.gov.br/fne-sol",
        "\"Financiar projetos de micro e minigeração distribuída de energia por fontes renováveis... "
        "Fonte de Recursos: Fundo Constitucional de Financiamento do Nordeste (FNE)\" (capturado ao vivo "
        "da página oficial em 2026-09-04)",
        setor_padronizado=NAO_INFORMADO,  # produto transversal (empresas/produtores rurais/pessoa fisica), tema e energia, nao setor
        temas_sustentabilidade="Energia solar, eólica, biomassa e PCH -- micro e minigeração distribuída",
        sinonimos_termos="energia solar fotovoltaica eolica geracao distribuida fne sol",
    ),
    _linha_fne(
        "FNE Startup",
        "Programa de apoio a Startups, com recursos do FNE.",
        "Fomentar o empreendedorismo, atraindo e mantendo na região capital humano e modelos de "
        "negócios com alto potencial de crescimento, por meio de apoio a startups de base tecnológica.",
        NAO_INFORMADO, "Microempresa, Pequena-média Empresa, Microempreendedor Individual (MEI)",
        "Apoio a startups de base tecnológica",
        "Despesas de remuneração de estagiários e colaboradores não vinculados à folha formal; pró-"
        "labore de sócio(s) com dedicação exclusiva; treinamento e capacitação; coworking; aluguel de "
        "equipamentos; contabilidade/advocacia/recrutamento/comissão de vendas; viagens e diárias; "
        "propaganda, publicidade e paid ads; ferramentas de cadência de e-mails; armazenamento de dados "
        "(cloud infrastructure) e TIC; capital de giro associado ao investimento",
        "MEI: até R$ 60 mil; demais empresas: consultar agência mais próxima. Capital de giro associado "
        "limitado a 1/3 do total financiado.",
        "Até 8 anos",
        "Até 2 anos",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Conforme Lei Federal nº 10.177, de 12/01/2001, e Resolução CMN nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-startup",
        "\"Fomentar o empreendedorismo, atraindo e mantendo na região capital humano e modelos de "
        "negócios com alto potencial de crescimento, por meio de apoio a startups de base tecnológica... "
        "Fonte de Recursos: Fundo Constitucional de Financiamento do Nordeste (FNE)\" (capturado ao vivo "
        "da página oficial em 2026-09-04)",
        canal_contratacao="Questionário FNE Startup + agência do Banco do Nordeste",
        setor_padronizado=NAO_INFORMADO,  # produto transversal (qualquer startup de base tecnologica), sem 1 setor honesto
        temas_inovacao="Startups de base tecnológica, modelos de negócio de alto potencial de crescimento",
        sinonimos_termos="startup base tecnologica empreendedorismo inovacao fne startup",
    ),
    _linha_fne(
        "FNE Verde",
        "Programa de Financiamento à Sustentabilidade Ambiental, com recursos do FNE.",
        "Desenvolver empreendimentos e atividades econômicas que propiciam a preservação, a "
        "conservação, o controle e a recuperação do meio ambiente, com foco na sustentabilidade e na "
        "competitividade das empresas e cadeias produtivas.",
        NAO_INFORMADO, "Produtores Rurais, Empresas, Cooperativas Rurais, Associações Rurais",
        "Sustentabilidade ambiental",
        "Uso sustentável de recursos florestais sem supressão de mata nativa; recuperação ambiental e "
        "convivência com o semiárido; produção de base agroecológica/orgânica e transição agroecológica; "
        "controle e prevenção da poluição e redução de emissão de gases do efeito estufa; energias "
        "renováveis e eficiência energética (inclusive locação/arrendamento de geração centralizada); "
        "eficiência no uso de materiais e obras civis sustentáveis; sistemas de armazenamento de "
        "energia; planejamento e gestão ambiental; adequação a exigências legais/licenças ambientais; "
        "capital de giro associado ao investimento (exceto setor rural); consultorias de acompanhamento "
        "de impactos sociais e ambientais",
        "Miniprodutor/MEI/microempresa: 100%; Pequeno produtor/pequena empresa: 100%; Pequeno-médio: 90 "
        "a 100%; Médio I: 80 a 95%; Médio II: 70 a 85%; Grande PRDNE: 70 a 80%; Grande: 50%; projetos de "
        "geração de energia renovável ou saneamento: até 100%, independente do porte e localização",
        "Investimentos Fixos (Rural): até 12 anos; Investimentos Semifixos (Rural): até 8 anos; "
        "Investimentos Fixos e Mistos (Não-rural): até 12 anos; regularização/recuperação de reserva "
        "legal: até 20 anos; florestamento e reflorestamento: até 16 anos; saneamento básico "
        "(infraestrutura): até 34 anos; geração de energia renovável: até 24 anos",
        "Investimentos Fixos (Rural): até 4 anos; Investimentos Semifixos (Rural): até 3 anos; "
        "Investimentos Fixos e Mistos (Não-rural): até 4 anos; regularização de reserva legal: até 12 "
        "anos; florestamento: até 7 anos; saneamento: até 8 anos; geração de energia: até 8 anos; +1 a 2 "
        "anos adicionais para produtoras rurais/empresas controladas por mulheres com participação >40%",
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor",
        "Setor rural: conforme Resolução CMN nº 5.329, de 14/07/2026; demais setores: conforme "
        "Resolução CMN nº 5.013, de 28/04/2022.",
        "https://www.bnb.gov.br/fne-verde",
        "\"Desenvolver empreendimentos e atividades econômicas que propiciam a preservação, a "
        "conservação, o controle e a recuperação do meio ambiente, com foco na sustentabilidade e na "
        "competitividade das empresas e cadeias produtivas... Fonte de Recursos: Fundo Constitucional de "
        "Financiamento do Nordeste (FNE)\" (capturado ao vivo da página oficial em 2026-09-04)",
        setor_padronizado=NAO_INFORMADO,  # produto transversal (rural e nao-rural, qualquer cadeia produtiva), tema e sustentabilidade
        temas_sustentabilidade="Preservação/recuperação ambiental, agroecologia, energias renováveis, "
        "eficiência energética, gestão ambiental",
        sinonimos_termos="sustentabilidade ambiental meio ambiente agroecologia energia renovavel fne verde",
    ),
    _linha_fne(
        "Custeio Agrícola e Pecuário - FNE",
        "Recursos financeiros destinados ao custeio agrícola e pecuário, com recursos do FNE.",
        "Suprimento de recursos financeiros destinados ao custeio, isolado e vinculado, das atividades "
        "agrícolas e pecuárias, independentemente da existência de termo de parceria, convênio ou "
        "protocolo entre o Banco e outras entidades.",
        "Agronegócio", "Produtores Rurais, Cooperativas Rurais, Produtores de Sementes e Mudas",
        "Custeio agrícola e pecuário",
        "Gastos do ciclo produtivo de lavouras periódicas, entressafra e colheitas de lavouras "
        "permanentes ou extração de produtos vegetais espontâneos/cultivados; soca e ressoca de cana-de-"
        "açúcar; aquisição de silos (bags), limitada a 5% do valor do custeio; insumos para restauração "
        "de reserva legal e áreas de preservação permanente; assessoria empresarial e técnica; aquisição "
        "de insumos em qualquer época do ano (inclusive transporte e frete); bioinsumos do Programa "
        "Nacional de Bioinsumos; manutenção de infraestrutura de rede/plataformas digitais; ciclo "
        "produtivo de exploração pecuária (apicultura, avicultura, piscicultura, sericicultura, "
        "aquicultura, pesca comercial, exceto bovinocultura); ciclo produtivo da bovinocultura (retenção "
        "de crias, engorda em confinamento, recria e engorda a pasto)",
        NAO_INFORMADO,
        "Custeio agrícola para algodão colorido (BRS 200) na Paraíba: até 12 meses; extração de pó de "
        "carnaúba: até 8 meses; demais custeios agrícolas: até 24 meses; retenção de crias bovinas: até "
        "24 meses; aquisição de bovinos/bubalinos para engorda em confinamento: até 6 meses; recria e "
        "engorda em regime extensivo: até 30 meses; engorda em regime extensivo: até 18 meses; "
        "aquicultura: até 24 meses; pesca: até 18 meses; demais custeios pecuários: até 12 meses",
        NAO_INFORMADO,
        "Alienação Fiduciária, Aval, Fiança, Hipoteca, Penhor, Seguro Rural",
        NAO_INFORMADO,
        "https://www.bnb.gov.br/custeio-agricola-e-pecuario-fne",
        "\"Suprimento de recursos financeiros destinados ao custeio, isolado e vinculado, das atividades "
        "relacionadas nos subitens a seguir... Fonte de Recursos: Fundo Constitucional de Financiamento "
        "do Nordeste (FNE)\" (capturado ao vivo da página oficial em 2026-09-04)",
        canal_contratacao="Agências do Banco do Nordeste",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        sinonimos_termos="custeio agricola pecuario safra lavoura bovinocultura",
    ),
    _linha_fne(
        "Cartão BNB Agro",
        "Crédito rotativo pré-aprovado com recursos do FNE para produtores rurais.",
        "Facilitar a aquisição de colheitadeiras, tratores e microtratores, veículos, máquinas e "
        "equipamentos para mecanização da produção rural.",
        "Agronegócio", "Produtores Rurais, Produtores de Sementes e Mudas",
        "Mecanização da produção rural via crédito rotativo em cartão",
        "Colheitadeiras; tratores e microtratores; máquinas e equipamentos para mecanização; veículos; "
        "peças de reposição para colheitadeira/trator/microtrator/máquinas/equipamentos/veículos; "
        "serviço de manutenção associado à aquisição de peças; aeronaves para pulverização agrícola; "
        "drones; equipamentos e itens de irrigação para reposição em sistemas existentes",
        "Até 100% do valor dos bens a serem adquiridos; a depender do porte, o limite de crédito pode "
        "ser de até R$ 30 milhões",
        "Aeronave de Pulverização Agrícola: até 20 anos; Demais Itens Financiáveis: até 8 anos; "
        "Utensílios Agrícolas: até 6 anos; Peças de Reposição e Manutenção: até 2 anos",
        "Peças de Reposição e Manutenção/Utensílios Agrícolas/Aeronave/Demais Itens: até 1 ano",
        "Alienação Fiduciária, Aval, Fundo de Liquidez, Limite de Crédito Garantido por Alienação "
        "Fiduciária de Bem Imóvel, Limite de Crédito Garantido por Hipoteca",
        NAO_INFORMADO,
        "https://www.bnb.gov.br/cartao-bnb-agro",
        "\"Crédito rotativo pré-aprovado com recursos do FNE para produtores rurais... Até 100% do valor "
        "dos bens a serem adquiridos. A depender do porte, o limite de crédito pode ser de até R$ 30 "
        "milhões.\" (capturado ao vivo da página oficial em 2026-09-04)",
        valor_maximo=30_000_000,
        criterios_elegibilidade=NAO_INFORMADO,
        documentos_necessarios=NAO_INFORMADO,
        canal_contratacao="Agências do Banco do Nordeste",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        sinonimos_termos="cartao bnb agro credito rotativo mecanizacao rural",
    ),
    _linha_fne(
        "Cartão BNB Agro Custeio Pecuário",
        "Crédito rotativo com recursos do FNE para custeio do setor pecuário, com agilidade e "
        "comodidade.",
        "Facilitar o crédito para aquisição de insumos do setor pecuário, proporcionando agilidade, "
        "desburocratização, comodidade e eficiência.",
        "Agronegócio (pecuária)", "Produtores Rurais",
        "Custeio pecuário via crédito rotativo em cartão",
        "Insumos veterinários (vacinas, medicamentos, sais minerais); rações formuladas, tortas, "
        "farelos, raiz de mandioca, melaço, bagaço de cana, ureia, sulfato de amônia; insumos (ureia, "
        "melaço e aditivos)",
        "Até 100% do valor dos bens a serem adquiridos; a depender do porte, o limite de crédito pode "
        "ser de até R$ 10 milhões",
        "Até 24 meses",
        "Sem carência",
        "Aval, Hipoteca, Penhor, Limite de Crédito Garantido por Alienação Fiduciária de Bem Imóvel, "
        "Limite de Crédito Garantido por Hipoteca",
        NAO_INFORMADO,
        "https://www.bnb.gov.br/cartao-bnb-agro-custeio-pecuario",
        "\"Facilitar o crédito para aquisição de insumos do setor pecuário, proporcionando agilidade, "
        "desburocratização, comodidade e eficiência... A depender do porte, o limite de crédito pode ser "
        "de até R$ 10 milhões.\" (capturado ao vivo da página oficial em 2026-09-04)",
        valor_maximo=10_000_000,
        criterios_elegibilidade=NAO_INFORMADO,
        documentos_necessarios=NAO_INFORMADO,
        canal_contratacao="Agências do Banco do Nordeste",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        sinonimos_termos="cartao bnb agro custeio pecuario insumos veterinarios",
    ),
    _linha_fne(
        "Cartão BNB para Micro e Pequenas Empresas e Microempreendedores Individuais",
        "Crédito rotativo pré-aprovado para aquisição de bens e capital de giro de micro e pequenas "
        "empresas e MEIs.",
        "Facilitar a aquisição de bens e insumos financiados junto a fornecedores cadastrados, levando "
        "mais agilidade e benefícios à micro e pequena empresa e aos microempreendedores individuais.",
        NAO_INFORMADO, "Microempresa, Pequena Empresa, Microempreendedor Individual (MEI)",
        "Aquisição de bens/insumos e capital de giro via crédito rotativo em cartão",
        "Bens novos (máquinas, equipamentos, veículos, motocicletas, móveis e utensílios); matérias-"
        "primas; insumos; mercadorias; software nacional ou importado; gastos gerais de funcionamento "
        "do empreendimento",
        "Até 100% do valor dos bens a serem adquiridos; a depender do porte, o limite de crédito pode "
        "ser de até R$ 10 milhões",
        "Investimento: até 120 meses; Capital de Giro: até 36 meses",
        "Investimento: até 12 meses; Capital de Giro: até 6 meses",
        "Alienação Fiduciária, Aval, Limite de Crédito Garantido por Hipoteca, Limite de Crédito "
        "Garantido por Alienação Fiduciária de Bem Imóvel",
        NAO_INFORMADO,
        "https://www.bnb.gov.br/cartao-bnb-mpe",
        "\"Facilitar a aquisição de bens e insumos financiados... Fonte de Recursos: Fundo Constitucional "
        "de Financiamento do Nordeste (FNE) / Recursos Internos... A depender do porte, o limite de "
        "crédito pode ser de até R$ 10 milhões.\" (capturado ao vivo da página oficial em 2026-09-04)",
        sigla=NAO_INFORMADO,  # fonte mista: FNE + Recursos Internos, sem sigla unica honesta
        agente_financeiro="Banco do Nordeste (Fundo Constitucional de Financiamento do Nordeste - FNE, "
        "e Recursos Internos)",
        valor_maximo=10_000_000,
        criterios_elegibilidade=NAO_INFORMADO,
        documentos_necessarios=NAO_INFORMADO,
        canal_contratacao="Agências do Banco do Nordeste",
        setor_padronizado=NAO_INFORMADO,  # produto transversal (qualquer setor de negocio de MPE/MEI)
        sinonimos_termos="cartao bnb mpe mei credito rotativo cartao empresarial",
    ),
    _linha_fne(
        "Cartão BNB para Empresarial e Corporate",
        "Crédito rotativo pré-aprovado para aquisição de bens, insumos e capital de giro de empresas "
        "Empresarial e Corporate.",
        "Facilitar a aquisição de bens e insumos financiados junto a fornecedores cadastrados, levando "
        "mais agilidade e benefícios para empresas do setor industrial, de turismo, de comércio, de "
        "prestação de serviços, de agroindústrias e de infraestrutura.",
        "Industrial, Turismo, Comércio, Prestação de Serviços, Agroindústria, Infraestrutura",
        "Pequena-média Empresa, Média Empresa, Grande Empresa",
        "Aquisição de bens/insumos e capital de giro via crédito rotativo em cartão",
        "Bens novos (máquinas, equipamentos, veículos, motocicletas, móveis e utensílios); matérias-"
        "primas; insumos; mercadorias; software nacional ou importado; gastos gerais de funcionamento "
        "do empreendimento",
        "Até 100% do valor dos bens a serem adquiridos; a depender do porte, o limite de crédito pode "
        "ser de até R$ 10 milhões",
        "Investimento: até 120 meses; Capital de Giro: até 36 meses",
        "Investimento: até 12 meses; Capital de Giro: até 6 meses",
        "Alienação Fiduciária, Aval, Limite de Crédito Garantido por Hipoteca, Limite de Crédito "
        "Garantido por Alienação Fiduciária de Bem Imóvel",
        NAO_INFORMADO,
        "https://www.bnb.gov.br/cartao-bnb-empresarial-e-corporate",
        "\"Facilitar a aquisição de bens e insumos financiados junto a fornecedores cadastrados... para "
        "empresas do setor industrial, de turismo, de comércio, de prestação de serviços, de "
        "agroindústrias e de infraestrutura... A depender do porte, o limite de crédito pode ser de até "
        "R$ 10 milhões.\" (capturado ao vivo da página oficial em 2026-09-04)",
        sigla=NAO_INFORMADO,  # fonte mista: FNE + Recursos Internos, sem sigla unica honesta
        agente_financeiro="Banco do Nordeste (Fundo Constitucional de Financiamento do Nordeste - FNE, "
        "e Recursos Internos)",
        valor_maximo=10_000_000,
        criterios_elegibilidade=NAO_INFORMADO,
        documentos_necessarios=NAO_INFORMADO,
        canal_contratacao="Agências do Banco do Nordeste",
        setor_padronizado=NAO_INFORMADO,  # produto transversal (varios setores empresariais/corporate)
        sinonimos_termos="cartao bnb empresarial corporate credito rotativo grandes empresas",
    ),
    {
        # FDNE nao e FNE -- fundo distinto (Medida Provisoria 2.156-5/2001, Decreto
        # 7.838/2012), gerido pela SUDENE, com o BNB atuando como Agente Operador.
        # Incluido porque e um programa de credito real, publicamente documentado
        # em bnb.gov.br, administrado pelo Banco do Nordeste (pedido explicito do
        # item 6 -- "programas proprios do BNB fora do FNE").
        "instituicao": "BNB",
        "nome_oficial": "FDNE - Fundo de Desenvolvimento do Nordeste",
        "nome_simplificado": "FDNE",
        "sigla": "FDNE",
        "status": "aberta",
        "descricao_resumida": "Fundo (gerido pela Sudene, BNB como agente operador) para financiar "
        "grandes investimentos em infraestrutura e serviços públicos e empreendimentos produtivos de "
        "grande capacidade germinativa de novos negócios na área de atuação da Sudene.",
        "descricao_completa": (
            "Assegurar recursos para a implantação, ampliação, modernização e diversificação de "
            "investimentos em infraestrutura e serviços públicos e em empreendimentos produtivos de "
            "grande capacidade germinativa de novos negócios e de novas atividades produtivas através "
            "do financiamento de investimentos em capital fixo na área de atuação da Sudene, conforme "
            "diretrizes e prioridades anuais do Conselho Deliberativo da Sudene."
        ),
        "modalidade": "Indireta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": NAO_INFORMADO,  # cross-setorial: infraestrutura/servico publico E "outros setores" produtivos
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Pessoas jurídicas de direito privado com projetos de grande porte (valores "
        "mínimos de investimento entre R$ 5 milhões e R$ 30 milhões, conforme localização e tipo de "
        "projeto)",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Área de atuação da Sudene (Nordeste, Norte de Minas Gerais e Espírito Santo)",
        "destinacao": "Implantação, ampliação, modernização e diversificação de investimentos em "
        "infraestrutura, serviços públicos e empreendimentos produtivos estruturantes",
        "itens_financiaveis": "Obras preliminares e complementares; obras civis; formação de reserva "
        "hídrica e obras de drenagem em projeto integrado de irrigação; infraestrutura; máquinas, "
        "instalações, equipamentos e aparelhos (inclusive montagem e treinamento); veículos utilitários "
        "e embarcações; móveis e utensílios; preparo de área e solo para plantio; sementes e mudas; "
        "viveiros e jardins clonais; plantio; instalações agrícolas e pecuárias; aquisição de animais, "
        "inclusive sêmen; despesas eventuais não previstas (até 3% das inversões fixas)",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": (
            "Até 80% do investimento total, limitado a 90% do investimento fixo, variando por "
            "localização e setor: Áreas Prioritárias -- Saneamento/Abastecimento de Água: 80%; "
            "Infraestrutura: 60%; Serviço Público: 60%; Estruturador: 55%; Outros Setores: 50%. Demais "
            "Áreas -- Saneamento/Abastecimento de Água: 70%; Infraestrutura: 50%; Serviço Público: 50%; "
            "Estruturador: 45%; Outros Setores: 40%. Recursos próprios mínimos: 20% do investimento "
            "total."
        ),
        "contrapartida": "No mínimo 20% dos investimentos totais previstos para o projeto",
        "taxa_completa": "Taxa Efetiva de Juros dos Fundos de Desenvolvimento (TFD), conforme Resolução "
        "CMN nº 4.960, de 21/10/2021, com fator de programa (0,65 a 1,45) variável conforme prioridade "
        "setorial/espacial e tipo de projeto (infraestrutura ou não)",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 20 anos para projetos de infraestrutura; até 12 anos para os demais "
        "empreendimentos (já incluída a carência)",
        "carencia": "Até 1 ano após a data prevista no projeto para entrada em operação do "
        "empreendimento, conforme estudo da capacidade de pagamento do mutuário",
        "amortizacao": NAO_INFORMADO,
        "restricoes": "Investimentos mínimos: Semiárido/RIDEs -- implantação a partir de R$ 20 milhões, "
        "modernização/ampliação/diversificação a partir de R$ 15 milhões; demais áreas -- implantação a "
        "partir de R$ 30 milhões, modernização/ampliação/diversificação a partir de R$ 25 milhões "
        "(podendo ser reduzidos a até R$ 5 milhões a critério da Diretoria Colegiada da Sudene). Taxa de "
        "análise de projeto de até 0,2% do valor da operação, limitada a R$ 500.000,00, cobrada pelo "
        "agente operador.",
        "criterios_elegibilidade": "Consulta Prévia enquadrada pela Sudene (prazo de análise: até 30 "
        "dias); projeto definitivo submetido ao Agente Operador (BNB) e aprovado tecnicamente (até 90 "
        "dias, prorrogável por 30) e pela Diretoria Colegiada da Sudene (até 30 dias)",
        "agente_financeiro": "Banco do Nordeste (Agente Operador do FDNE, fundo gerido pela "
        "Superintendência do Desenvolvimento do Nordeste - Sudene)",
        "canal_contratacao": "Consulta Prévia junto à Sudene, seguida de projeto definitivo apresentado "
        "ao Banco do Nordeste como Agente Operador",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": "Consulta Prévia (modelo definido pela Sudene) e Projeto Definitivo "
        "técnico-econômico-financeiro",
        "url_oficial": "https://www.bnb.gov.br/fdne",
        "data_vigencia": "Medida Provisória nº 2.156-5/2001; Decreto nº 7.838/2012 (e Decreto nº "
        "6.952/2009 para operações contratadas até 03/04/2012); Resolução CMN nº 4.960/2021",
        "trecho_fonte": (
            "\"Por meio do FDNE o Banco do Nordeste financia investimentos em infraestrutura e serviços "
            "públicos, em empreendimentos produtivos de grande capacidade germinativa de novos negócios "
            "e de novas atividades produtivas na área de atuação da Sudene... Até 20 anos para os "
            "projetos de infraestrutura e até 12 anos para os demais empreendimentos\" (capturado ao "
            "vivo da página oficial em 2026-09-04)"
        ),
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,  # cobre infraestrutura E outros setores produtivos, sem 1 categoria honesta
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": "Grande (projetos de investimento mínimo entre R$ 5 milhões e R$ 30 "
        "milhões)",
        "destinacao_padronizada": "Infraestrutura e grandes projetos produtivos estruturantes",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "fdne fundo de desenvolvimento do nordeste sudene grandes projetos",
    },
]


def seed_bnb_manual(conn) -> int:
    return _upsert_many(
        conn, [dict(linha) for linha in _BNB_MANUAL] + [dict(linha) for linha in _BNB_MANUAL_EXPANSAO]
    )


# BASA (Banco da Amazonia): curadoria manual verificada, capturada ao vivo em
# 2026-09-15 navegando bancoamazonia.com.br/linhas-de-fomento/fno (pagina de listagem)
# e as 8 paginas de produto FNO + a pagina do FDA. Paginas estaticas, sem acordeao JS
# (diferente do BNDES) -- texto extraido direto do HTML renderizado.
def _linha_fno(
    nome_oficial, descricao_resumida, descricao_completa, setores_elegiveis,
    itens_financiaveis, taxa_completa, prazo_total, url_slug, trecho_fonte,
    *, sigla="FNO", porte_elegivel=NAO_INFORMADO, valor_minimo=None, valor_maximo=None,
    percentual_financiavel=NAO_INFORMADO, contrapartida=NAO_INFORMADO, indexador=NAO_INFORMADO,
    spread=NAO_INFORMADO, carencia=NAO_INFORMADO, amortizacao=NAO_INFORMADO,
    garantias=NAO_INFORMADO, restricoes=NAO_INFORMADO,
    criterios_elegibilidade=NAO_INFORMADO,
    documentos_necessarios=NAO_INFORMADO, prazo_inscricao=NAO_INFORMADO, data_vigencia=NAO_INFORMADO,
    setor_padronizado=NAO_INFORMADO, subsetor_padronizado=None, porte_padronizado=None,
    destinacao_padronizada=None, temas_inovacao=None, temas_sustentabilidade=None,
    sinonimos_termos=None, itens_nao_financiaveis=NAO_INFORMADO, setores_nao_elegiveis=NAO_INFORMADO,
    faixa_receita=NAO_INFORMADO, tipo_apoio="Financiamento", modalidade="Direta",
    regiao_elegivel="Região Norte (área de atuação da SUDAM/FNO)",
    agente_financeiro="Banco da Amazônia (Fundo Constitucional de Financiamento do Norte - FNO)",
    canal_contratacao="Gerente de relacionamento / agências do Banco da Amazônia",
    fluxo="continuo",
):
    """Helper pra reduzir repeticao das 8 sub-linhas do FNO -- cada pagina de produto
    em bancoamazonia.com.br/linhas-de-fomento/fno/<produto> segue estrutura parecida
    (objetivo, publico-alvo, itens financiaveis, taxa, prazo/carencia), mas nem toda
    pagina documenta TODOS os campos (ex: garantias so aparece explicita em Energia
    Verde) -- campo nao documentado fica NAO_INFORMADO, nunca inferido."""
    return {
        "instituicao": "BASA",
        "nome_oficial": nome_oficial,
        "nome_simplificado": nome_oficial,
        "sigla": sigla,
        "status": "aberta",
        "descricao_resumida": descricao_resumida,
        "descricao_completa": descricao_completa,
        "modalidade": modalidade,
        "tipo_apoio": tipo_apoio,
        "setores_elegiveis": setores_elegiveis,
        "setores_nao_elegiveis": setores_nao_elegiveis,
        "porte_elegivel": porte_elegivel,
        "faixa_receita": faixa_receita,
        "regiao_elegivel": regiao_elegivel,
        "destinacao": descricao_resumida,
        "itens_financiaveis": itens_financiaveis,
        "itens_nao_financiaveis": itens_nao_financiaveis,
        "valor_minimo": valor_minimo,
        "valor_maximo": valor_maximo,
        "percentual_financiavel": percentual_financiavel,
        "contrapartida": contrapartida,
        "taxa_completa": taxa_completa,
        "indexador": indexador,
        "spread": spread,
        "prazo_total": prazo_total,
        "carencia": carencia,
        "amortizacao": amortizacao,
        "garantias": garantias,
        "restricoes": restricoes,
        "criterios_elegibilidade": criterios_elegibilidade,
        "agente_financeiro": agente_financeiro,
        "canal_contratacao": canal_contratacao,
        "prazo_inscricao": prazo_inscricao,
        "fluxo": fluxo,
        "documentos_necessarios": documentos_necessarios,
        "url_oficial": url_slug,
        "data_vigencia": data_vigencia,
        "trecho_fonte": trecho_fonte,
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": setor_padronizado,
        "subsetor_padronizado": subsetor_padronizado,
        "cnaes_relacionados": None,
        "porte_padronizado": porte_padronizado or porte_elegivel,
        "destinacao_padronizada": destinacao_padronizada,
        "tecnologias_relacionadas": None,
        "temas_inovacao": temas_inovacao,
        "temas_sustentabilidade": temas_sustentabilidade,
        "sinonimos_termos": sinonimos_termos,
    }


_BASA_MANUAL = [
    _linha_fno(
        "FNO Amazônia Rural",
        "Financiamento destinado à ampliação, modernização, reforma ou custeio de atividades "
        "agropastoris, de pesca e de agroindústria regional.",
        "Crédito para pequenos, médios e grandes produtores, destinado à ampliação, "
        "modernização, reforma ou custeio de atividades agropastoris, de pesca e de "
        "agroindústria regional. Contempla pesca artesanal, aquicultura, silvicultura, "
        "extrativismo artesanal, desenvolvimento da agropecuária irrigada e atividades de "
        "comunidades tradicionais.",
        "Agricultura; Pecuária; Aquicultura; Pesca e Agroindústria de produtos agropecuários",
        "Pesca Artesanal, Aquicultura, Silvicultura, Extrativismo Artesanal, desenvolvimento da "
        "agropecuária irrigada e atividades de comunidades tradicionais",
        "Diferenciada por setor, porte e finalidade.",
        "Até 12 anos, incluída a carência de até 6 anos (investimento fixo/misto); até 10 anos, "
        "incluída a carência de até 6 anos (investimento semifixo); até 2 anos (custeio "
        "agrícola/comercialização); de 12 a 24 meses, dependendo da finalidade (custeio "
        "pecuário).",
        "https://www.bancoamazonia.com.br/linhas-de-fomento/fno/amazonia-rural",
        '"Financiamento destinado à ampliação, modernização, reforma ou custeio de atividades '
        'agropastoris, de pesca e de agroindústria regional." / "Crédito para pequenos, médios '
        'e grandes produtores." (capturado ao vivo da página oficial em 2026-09-15)',
        porte_elegivel="Pequenos, médios e grandes produtores",
        criterios_elegibilidade="Produtor rural (pequeno, médio ou grande porte) na área de atuação do FNO",
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        destinacao_padronizada="Agropecuária e agroindústria regional",
        sinonimos_termos="fno amazonia rural credito rural norte agropecuaria pesca aquicultura silvicultura",
    ),
    _linha_fno(
        "FNO Amazônia Empresarial",
        "Financiamento destinado a empreendimentos do setor empresarial de comércio, serviços e "
        "indústrias.",
        "Linha de financiamento para implantação, ampliação, modernização, relocalização e "
        "adequação de empreendimentos dos setores de indústria, turismo, comércio e prestação "
        "de serviços. Atende a todos os portes de empresa, inclusive o Microempreendedor "
        "Individual (MEI).",
        "Indústria; Turismo; Comércio e prestação de serviços; Empresas de assistência técnica "
        "privada; Atividades agroindustriais voltadas à exportação",
        NAO_INFORMADO,
        "Baseadas na Taxa de Juros dos Fundos Constitucionais (TFC); variando de acordo com o "
        "setor, porte e finalidade.",
        "Até 17 anos (com carência de até 6 anos) para projetos de atividade turística relativos "
        "a meios de hospedagem; para Capital de Giro isolado de todos os portes (inclusive MEI), "
        "o prazo é de até 36 meses, com carência de até 5 meses.",
        "https://www.bancoamazonia.com.br/linhas-de-fomento/fno/amazonia-empresarial",
        '"Linha de financiamento para implantação, ampliação, modernização, relocalização e '
        'adequação de empreendimentos" / "Atende a todos os portes de empresa, inclusive o '
        'Microempreendedor Individual (MEI)" (capturado ao vivo da página oficial em 2026-09-15)',
        porte_elegivel="Todos os portes, inclusive Microempreendedor Individual (MEI)",
        setor_padronizado="COMERCIO/SERVICOS",
        destinacao_padronizada="Indústria, turismo, comércio e serviços",
        sinonimos_termos="fno amazonia empresarial credito empresarial norte industria turismo comercio servicos",
    ),
    _linha_fno(
        "FNO Amazônia Empresarial Verde",
        "Financiamento para segmento empresarial e de prestação de serviços em bases "
        "sustentáveis.",
        "Linha de financiamento destinada a empreendimentos dos setores empresarial e de "
        "prestação de serviços com projetos voltados à adoção de práticas ambientais, incluindo "
        "agroindústria, indústria, turismo, cultura, comércio, saúde e educação.",
        "Agroindústria; Indústria; Turismo; Cultura; Comércio; Prestação de serviço; Atividades "
        "agroindustriais e industriais voltadas à exportação; Saúde e educação",
        NAO_INFORMADO,
        "Taxa de Juros dos Fundos Constitucionais (TFC), que varia de acordo com setor, porte e "
        "finalidade.",
        "Prazo para capital de giro de todos os portes, inclusive MEI: até 36 meses, com "
        "carência de até 5 meses.",
        "https://www.bancoamazonia.com.br/linhas-de-fomento/fno/amazonia-empresarial-verde",
        '"Linha de financiamento destinada a empreendimentos dos setores empresarial e de '
        'prestação de serviços com projetos voltados à adoção de práticas ambientais" '
        '(capturado ao vivo da página oficial em 2026-09-15)',
        setor_padronizado="COMERCIO/SERVICOS",
        destinacao_padronizada="Empreendimentos empresariais e de serviços em bases sustentáveis",
        temas_sustentabilidade="Práticas ambientais em empreendimentos empresariais",
        sinonimos_termos="fno amazonia empresarial verde sustentabilidade praticas ambientais norte",
    ),
    _linha_fno(
        "FNO Amazônia Infraestrutura",
        "Financiamento destinado a projetos de infraestrutura.",
        "Crédito de grande porte estruturado para financiar projetos de infraestrutura "
        "econômica essenciais, voltados a empresas de todos os portes que atuem no "
        "desenvolvimento logístico e estrutural da região, exceto Microempreendedores "
        "Individuais (MEI).",
        "Infraestrutura de transporte e logística; instalação de gasoduto; produção e "
        "distribuição de gás canalizado",
        "Projetos voltados à infraestrutura de transporte e logística; instalação de gasoduto; "
        "produção de gás e distribuição de gás canalizado",
        "Taxa de Juros dos Fundos Constitucionais (TFC), que varia de acordo com setor, porte e "
        "finalidade.",
        "Prazo total de até 34 anos, com carência de até 8 anos (ativos fixos); capital de giro "
        "associado até 36 meses, com carência de até 5 meses.",
        "https://www.bancoamazonia.com.br/linhas-de-fomento/fno/amazonia-infraestrutura",
        '"Crédito de grande porte estruturado para financiar projetos de infraestrutura '
        'econômica essenciais." / "Empresas de todos os portes que atuem no desenvolvimento '
        'logístico e estrutural da região, exceto Microempreendedores Individuais (MEI)" '
        '(capturado ao vivo da página oficial em 2026-09-15)',
        porte_elegivel="Todos os portes, exceto Microempreendedor Individual (MEI)",
        setor_padronizado="INFRAESTRUTURA",
        destinacao_padronizada="Infraestrutura econômica (transporte, logística, gás)",
        sinonimos_termos="fno amazonia infraestrutura transporte logistica gasoduto norte",
    ),
    _linha_fno(
        "FNO Amazônia Infraestrutura Verde",
        "Linha de financiamento para infraestrutura com responsabilidade ambiental.",
        "Linha de financiamento para infraestrutura com responsabilidade ambiental, incluindo "
        "água e esgoto, geração de energia renovável, tratamento de resíduos, portos e "
        "aeroportos sustentáveis e telecomunicações em comunidades.",
        NAO_INFORMADO,
        "Infraestrutura para água e esgoto; geração de energia elétrica de fontes renováveis; "
        "usinas de compostagem e/ou aterro sanitário sustentável; portos e aeroportos "
        "sustentáveis; transmissão e distribuição de energia; sistema de telefonia fixa ou "
        "móvel e banda larga em comunidades; demais obras estruturantes ecológicas e "
        "sustentáveis; pacotes de serviços",
        "Taxa de Juros dos Fundos Constitucionais (TFC), diferenciada por setor, porte e "
        "finalidade.",
        "Até 34 anos, com carência de até 8 anos.",
        "https://www.bancoamazonia.com.br/linhas-de-fomento/fno/amazonia-infraestrutura-verde",
        '"Linha de financiamento para infraestrutura com responsabilidade ambiental." '
        '(capturado ao vivo da página oficial em 2026-09-15)',
        setor_padronizado="INFRAESTRUTURA",
        destinacao_padronizada="Infraestrutura sustentável (água/esgoto, energia renovável, resíduos)",
        temas_sustentabilidade="Infraestrutura ecológica e sustentável",
        sinonimos_termos="fno amazonia infraestrutura verde energia renovavel agua esgoto sustentavel norte",
    ),
    _linha_fno(
        "FNO Ciência, Tecnologia e Inovação",
        "Financiamento para empreendimentos com base tecnológica voltados a ramos empresariais "
        "não rurais.",
        "Financiamento para empreendimentos com base tecnológica, incluindo projetos "
        "desenvolvidos por agentes do ecossistema de inovação: empresas não-rurais e "
        "instituições de pesquisa, nos ramos de indústria, agroindústria, turismo, comércio e "
        "serviços.",
        "Empresas de todos os portes do setor não rural",
        "Projetos de base tecnológica voltados a ramos empresariais não rurais (indústria, "
        "agroindústria, turismo, comércio e serviços)",
        "Taxa de Juros dos Fundos Constitucionais (TFC), diferenciada por setor, porte e "
        "finalidade.",
        "Até 20 anos para investimentos fixos ou mistos (empresas em geral), com carência de até "
        "5 anos; até 36 meses para investimentos de MEI, com carência de 2 meses.",
        "https://www.bancoamazonia.com.br/linhas-de-fomento/fno/ciencia-tecnologia-e-inovacao",
        '"Financiamento para empreendimentos com base tecnológica, incluindo projetos '
        'desenvolvidos por agentes do ecossistema de inovação: empresas não-rurais e '
        'instituições de pesquisa." (capturado ao vivo da página oficial em 2026-09-15)',
        porte_elegivel="Todos os portes do setor não rural",
        percentual_financiavel="Até 100% do projeto, conforme enquadramento do empreendimento",
        setor_padronizado="INDUSTRIA",
        destinacao_padronizada="Inovação e base tecnológica em setores não rurais",
        temas_inovacao="Base tecnológica, ecossistema de inovação",
        sinonimos_termos="fno ciencia tecnologia inovacao base tecnologica pesquisa desenvolvimento norte",
    ),
    _linha_fno(
        "FNO Biodiversidade",
        "Linha de financiamento destinada a projetos rurais de impacto positivo focados no "
        "aproveitamento consciente dos recursos da Região Norte.",
        "Linha de financiamento destinada a projetos rurais de impacto positivo focados no "
        "aproveitamento consciente dos recursos da Região Norte, para produtores rurais, "
        "populações tradicionais da Amazônia (povos indígenas, comunidades quilombolas, "
        "ribeirinhos, extrativistas e pescadores artesanais) e pessoas jurídicas do setor rural.",
        "Pessoas físicas produtoras rurais; populações tradicionais da Amazônia (povos "
        "indígenas, comunidades quilombolas, ribeirinhos, extrativistas e pescadores "
        "artesanais); pessoas jurídicas do setor rural",
        "Manejo florestal sustentável, serviços ambientais, fauna silvestre, cultivo de plantas "
        "medicinais e aromáticas, proteção e recuperação de mananciais, sistemas de tratamento "
        "de dejetos e resíduos oriundos da produção animal para geração de energia e "
        "compostagem, além de reflorestamento com espécies nativas",
        NAO_INFORMADO,
        "Até 20 anos para investimentos fixos (carência de até 12 anos); até 10 anos para "
        "investimentos semifixos (carência de até 6 anos); até 2 anos para custeio isolado.",
        "https://www.bancoamazonia.com.br/linhas-de-fomento/fno/fno-biodiversidade",
        '"Linha de financiamento destinada a projetos rurais de impacto positivo focados no '
        'aproveitamento consciente dos recursos da Região Norte." (capturado ao vivo da página '
        'oficial em 2026-09-15)',
        setor_padronizado="AGROPECUÁRIA", subsetor_padronizado="AGROPECUÁRIA",
        destinacao_padronizada="Manejo sustentável de biodiversidade e recursos naturais",
        temas_sustentabilidade="Manejo florestal sustentável, serviços ambientais, reflorestamento nativo",
        sinonimos_termos="fno biodiversidade manejo florestal sustentavel populacoes tradicionais norte",
    ),
    _linha_fno(
        "FNO Energia Verde",
        "Projetos de geração e utilização de fontes renováveis de energia no meio rural.",
        "Financia projetos de geração e utilização de fontes renováveis de energia no meio "
        "rural, fomentando a produção de energias renováveis para consumo próprio, apoiando "
        "atividades do segmento agropecuário em bases sustentáveis, e financiando a compra de "
        "veículos verdes, elétricos, híbridos ou que utilizem energia renovável.",
        NAO_INFORMADO,
        "Implantação de sistemas de geração de energia renovável, aquisição de equipamentos, "
        "veículos elétricos ou híbridos",
        "Taxas de Juros Rurais dos Fundos Constitucionais de Financiamento (TRFC), que varia em "
        "função do porte e finalidade.",
        "Até 12 anos para pagar, incluída a carência de até 6 anos.",
        "https://www.bancoamazonia.com.br/linhas-de-fomento/fno/energia-verde",
        '"Projetos de geração e utilização de fontes renováveis de energia no meio rural." / '
        '"Garantias usuais do Banco da Amazônia" (capturado ao vivo da página oficial em '
        '2026-09-15)',
        valor_maximo=None,
        garantias="Garantias usuais do Banco da Amazônia",
        setor_padronizado="AGROPECUÁRIA",
        destinacao_padronizada="Energia renovável no meio rural",
        temas_sustentabilidade="Geração de energia renovável, veículos elétricos/híbridos",
        sinonimos_termos="fno energia verde renovavel veiculos eletricos hibridos rural norte",
    ),
]


_BASA_FDA = [
    {
        "instituicao": "BASA",
        "nome_oficial": "FDA - Fundo de Desenvolvimento da Amazônia",
        "nome_simplificado": "FDA",
        "sigla": "FDA",
        "status": "aberta",
        "descricao_resumida": "Financiamento de grandes projetos de infraestrutura e produção "
            "com alto potencial de gerar emprego, renda e transformação regional.",
        "descricao_completa": "Financiamento de grandes projetos de infraestrutura e produção "
            "com alto potencial de gerar emprego, renda e transformação regional, destinado a "
            "residentes da área de atuação da Superintendência de Desenvolvimento da Amazônia "
            "(SUDAM). O Banco da Amazônia atua como agente operador do Fundo -- ver também a "
            "linha equivalente operada pela Caixa Econômica Federal (instituicao=\"CEF\"), com "
            "detalhamento de prazo/garantias mais completo para o mesmo fundo.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Área de atuação da Superintendência de Desenvolvimento da Amazônia "
            "(SUDAM): Acre, Amapá, Amazonas, Mato Grosso, Pará, Rondônia, Roraima, Tocantins e "
            "parte do Maranhão",
        "destinacao": "Grandes projetos de infraestrutura e produção na Amazônia Legal",
        "itens_financiaveis": NAO_INFORMADO,
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
        "criterios_elegibilidade": "Residentes/empreendimentos na área de atuação da SUDAM",
        "agente_financeiro": "Banco da Amazônia (Fundo de Desenvolvimento da Amazônia - FDA, "
            "gerido pela SUDAM)",
        "canal_contratacao": "Gerente de relacionamento / agências do Banco da Amazônia",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bancoamazonia.com.br/linhas-de-fomento/fda",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"Financiamento de grandes projetos de infraestrutura e produção com '
            'alto potencial de gerar emprego, renda e transformação regional." / "Residentes da '
            'Superintendência de Desenvolvimento da Amazônia (SUDAM), que corresponde aos '
            'estados do Acre, Amapá, Amazonas, Mato Grosso, Pará, Rondônia, Roraima e Tocantins '
            'e parcialmente o estado do Maranhão." (capturado ao vivo da página oficial em '
            '2026-09-15; a página de listagem do BASA não detalha taxa/prazo/garantias -- ver a '
            'pagina da Caixa, mais detalhada, para o mesmo fundo)',
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Infraestrutura e produção regional (Amazônia Legal)",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "fda fundo de desenvolvimento da amazonia sudam infraestrutura grandes projetos",
    },
]


def seed_basa_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _BASA_MANUAL] + [dict(linha) for linha in _BASA_FDA])


# BB (Banco do Brasil): curadoria manual verificada, capturada ao vivo em 2026-09-15
# navegando bb.com.br/site/agronegocios/ (paginas estaticas de custeio + hub de
# investimentos). Restrito a linhas de credito rural/fomento (Pronaf/Pronamp/fundos
# constitucionais/programas do MCR com taxa fixada por normativo do CMN) -- exclui
# produtos bancarios comuns do mesmo portal.
_BB_MANUAL = [
    {
        "instituicao": "BB",
        "nome_oficial": "Pronamp Investimento",
        "nome_simplificado": "Pronamp Investimento",
        "sigla": "Pronamp",
        "status": "aberta",
        "descricao_resumida": "Crédito feito especialmente para o médio produtor promover a "
            "desenvolvimento das atividades rurais.",
        "descricao_completa": "O Pronamp é um crédito feito especialmente para o médio produtor "
            "promover o desenvolvimento das atividades rurais. Com esta linha, é possível "
            "financiar máquinas agrícolas, estruturas, equipamentos e o que for necessário para "
            "desenvolver o próprio agronegócio.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária (médio produtor rural)",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Médio produtor rural (renda bruta anual de até R$ 3,5 milhões)",
        "faixa_receita": "Até R$ 3,5 milhões (soma das atividades agropecuárias e não "
            "agropecuárias)",
        "regiao_elegivel": "Brasil",
        "destinacao": "Investimento em máquinas, estruturas e equipamentos para o agronegócio",
        "itens_financiaveis": "Construções, reformas ou benfeitorias de instalações "
            "permanentes; obras de irrigação, açudes ou drenagem; reflorestamento ou destoca; "
            "formação de lavouras permanentes; formação ou recuperação de pastagens; "
            "eletrificação e telefonia rural; equipamentos e máquinas agrícolas; recuperação ou "
            "reforma de máquinas agrícolas; proteção, correção e recuperação do solo.",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 600000.0,
        "percentual_financiavel": "Até 100% do valor do investimento, com teto de R$ 600 mil "
            "por beneficiário a cada ano agrícola.",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Taxa de juros de 10% ao ano. Tarifa de contratação: 0,5% sobre o "
            "valor do financiamento.",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 8 anos, com 2 anos de carência.",
        "carencia": "2 anos.",
        "amortizacao": "Parcelas semestrais ou anuais.",
        "garantias": "Bens oferecidos em garantia devem obrigatoriamente estar protegidos por "
            "seguro (contratável no BB).",
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": "Proprietários, posseiros, arrendatários, parceiros ou "
            "comodatários produtores rurais com renda bruta anual de até R$ 3,5 milhões, "
            "considerando a soma das atividades agropecuárias e não agropecuárias.",
        "agente_financeiro": "Banco do Brasil",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/site/agronegocios/pronamp/",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"O Pronamp é um crédito feito especialmente para o médio produtor '
            'promover o desenvolvimento das atividades rurais." / "Sim. A taxa de juros é de '
            '10% ao ano." / "O prazo para pagamento é de até 8 anos, com 2 anos de carência." / '
            '"O Pronamp permite um financiamento de até 100% do valor do investimento, com um '
            'teto de financiamento de R$ 600 mil por beneficiário a cada ano agrícola." '
            '(extraído do JSON-LD FAQPage embutido no DOM da página oficial, capturado ao vivo '
            'em 2026-09-15)',
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": "Médio produtor rural",
        "destinacao_padronizada": "Investimento rural (médio produtor)",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "pronamp investimento credito rural medio produtor banco do brasil "
            "maquinas agricolas",
    },
    {
        "instituicao": "BB",
        "nome_oficial": "Crédito Rural Pronamp Custeio",
        "nome_simplificado": "Pronamp Custeio",
        "sigla": "Pronamp",
        "status": "aberta",
        "descricao_resumida": "Crédito destinado a apoiar o médio produtor rural, financiando "
            "despesas do custeio da produção agrícola e pecuária.",
        "descricao_completa": "O Pronamp Custeio oferece crédito destinado a apoiar o médio "
            "produtor rural de forma a promover o desenvolvimento de suas atividades rurais. "
            "Com ele é possível financiar as despesas do custeio da produção agrícola e "
            "pecuária, proporcionando o aumento da renda e a geração de empregos no campo.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária (médio produtor rural)",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Produtor rural com Renda Bruta Anual (RBA) de até R$ 3,5 milhões, "
            "com renda rural de no mínimo 80%",
        "faixa_receita": "Até R$ 3,5 milhões",
        "regiao_elegivel": "Brasil",
        "destinacao": "Custeio da produção agrícola e pecuária",
        "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 1500000.0,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "9% a.a. Tarifa de estudo de operações rurais: 0,5% sobre o valor "
            "financiado. Alongamento de operações de custeio: 0,5% sobre o saldo devedor a "
            "alongar.",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 24 meses.",
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": "Produtor rural com Renda Bruta Anual (RBA) de até R$ 3,5 "
            "milhões, com renda rural de, no mínimo, 80%, entre outras condições.",
        "agente_financeiro": "Banco do Brasil",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/site/agronegocios/custeio/credito-rural-pronamp-custeio/",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"O Pronamp Custeio oferece crédito destinado a apoiar o médio produtor '
            'rural de forma a promover o desenvolvimento de suas atividades rurais." / "Cada '
            'produtor rural pode financiar até R$ 1,5 milhão por ano agrícola (de julho a junho '
            'subsequente)." / "Taxa de juros: 9% a.a." / "Prazo: Até 24 meses" (capturado ao '
            "vivo da página oficial em 2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": "Médio produtor rural",
        "destinacao_padronizada": "Custeio rural (médio produtor)",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "pronamp custeio credito rural medio produtor banco do brasil",
    },
    {
        "instituicao": "BB",
        "nome_oficial": "Pronaf Grupo B",
        "nome_simplificado": "Pronaf Grupo B",
        "sigla": "Pronaf",
        "status": "aberta",
        "descricao_resumida": "Crédito para investir na implantação, ampliação e modernização "
            "da infraestrutura de produção e serviços no estabelecimento rural ou em áreas "
            "comunitárias rurais próximas.",
        "descricao_completa": "Com o Pronaf Investimento Grupo B, é possível obter crédito para "
            "investir na implantação, ampliação e modernização da infraestrutura de produção e "
            "serviços, no estabelecimento rural ou em áreas comunitárias rurais próximas. "
            "Utiliza a metodologia do Programa Nacional de Microcrédito Produtivo Orientado "
            "(PNMPO), com acompanhamento e orientação educativo-financeira aos agricultores.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento (microcrédito produtivo orientado)",
        "setores_elegiveis": "Agricultura familiar",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Produtores familiares com CAF válido enquadrado no Grupo B, renda "
            "bruta familiar anual de até R$ 60 mil",
        "faixa_receita": "Até R$ 60 mil (renda bruta familiar anual)",
        "regiao_elegivel": "Brasil",
        "destinacao": "Investimento em infraestrutura de produção e serviços (agricultura "
            "familiar)",
        "itens_financiaveis": "Sistemas de produção de base agroecológica ou em transição para "
            "base agroecológica; sistemas orgânicos de produção; quintais produtivos para "
            "mulheres rurais; construção ou reforma de moradias e instalações sanitárias (UFPA).",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 20000.0,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "0,5% a.a. (taxa de juros disponível para a nova Safra 2026/2027, a "
            "partir de 01/07/2026).",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 5 anos.",
        "carencia": NAO_INFORMADO,
        "amortizacao": "Bônus de adimplência de 25% proporcional sobre cada parcela paga até o "
            "vencimento (40% quando enquadrado no PNMPO em área de abrangência da Sudene ou "
            "Sudam).",
        "garantias": NAO_INFORMADO,
        "restricoes": "Limite financiável por ano-safra: até R$ 20 mil (UFPA com metodologia "
            "PNMPO para produção de base agroecológica/orgânica ou quintais produtivos para "
            "mulheres rurais); até R$ 16 mil (jovens de 16 a 29 anos, metodologia PNMPO); até "
            "R$ 15 mil (beneficiárias do Grupo B, metodologia PNMPO); até R$ 12 mil (UFPA "
            "enquadrada no PNMPO); até R$ 10 mil (UFPA, construção/reforma de moradias e "
            "instalações sanitárias); até R$ 4 mil (demais projetos não enquadrados no PNMPO).",
        "criterios_elegibilidade": "Produtores familiares que portem CAF válido enquadrado no "
            "Grupo B, com renda bruta familiar anual de até R$ 60 mil.",
        "agente_financeiro": "Banco do Brasil (Programa Nacional de Fortalecimento da "
            "Agricultura Familiar - Pronaf)",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/site/agronegocios/investimentos/pronaf-grupo-b/",
        "data_vigencia": "Safra 2026/2027 (taxa vigente a partir de 01/07/2026)",
        "trecho_fonte": '"Com o Pronaf Investimento Grupo B, é possível obter crédito para '
            'investir na implantação, ampliação e modernização da infraestrutura de produção e '
            'serviços." / "Beneficiários: Produtores familiares que portem CAF válido '
            'enquadrado no Grupo B, com renda bruta familiar anual de até R$ 60 mil." / "Taxa '
            'de juros: 0,5% a.a." / "Prazo: Até 5 anos." (capturado ao vivo da página oficial '
            'em 2026-09-15)',
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": "Agricultura familiar",
        "destinacao_padronizada": "Investimento em agricultura familiar",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "pronaf grupo b agricultura familiar microcredito pnmpo banco do "
            "brasil",
    },
    {
        "instituicao": "BB",
        "nome_oficial": "Pronaf Custeio A/C",
        "nome_simplificado": "Pronaf Custeio A/C",
        "sigla": "Pronaf",
        "status": "aberta",
        "descricao_resumida": "Crédito para custeio da produção agrícola ou pecuária de "
            "agricultores familiares enquadrados no grupo A/C, povos indígenas e comunidades "
            "quilombolas.",
        "descricao_completa": "Com o Pronaf Custeio A/C é possível adquirir sementes, "
            "fertilizantes, defensivos, vacinas, ração e outros itens necessários para o dia a "
            "dia da produção, seja agrícola ou pecuária.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agricultura familiar",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Agricultores familiares com CAF válido, grupo A/C, povos indígenas e "
            "comunidades quilombolas; cooperativas da agricultura familiar (ROB anual de até "
            "R$ 10 milhões)",
        "faixa_receita": "Cooperativas: ROB anual de até R$ 10 milhões",
        "regiao_elegivel": "Brasil",
        "destinacao": "Custeio agrícola, pecuário e agroindustrial (agricultura familiar)",
        "itens_financiaveis": "Sementes, fertilizantes, defensivos, vacinas, ração e outros "
            "itens necessários à produção agrícola ou pecuária.",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 22000.0,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "1,5% a.a. (produtor); 3,0% a.a. (cooperativas). Taxa disponível para "
            "a nova Safra 2026/2027, a partir de 01/07/2026.",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Custeio agrícola: até 3 anos, conforme o ciclo da atividade financiada; "
            "custeio pecuário: até 20 meses; custeio para agroindústria: até 12 meses.",
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": "Agricultores familiares com CAF válido enquadrados no grupo "
            "A/C, povos indígenas e comunidades quilombolas; cooperativas da agricultura "
            "familiar com ROB anual de até R$ 10 milhões, no mínimo 75% de associados com CAF "
            "válido enquadrado no PRONAF, e 90% dos associados beneficiados com CAF grupo A/A-C, "
            "participando do Programa Mais Gestão ou Coopera Mais Brasil.",
        "agente_financeiro": "Banco do Brasil (Programa Nacional de Fortalecimento da "
            "Agricultura Familiar - Pronaf)",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/site/agronegocios/custeio/pronaf-custeio-a-c",
        "data_vigencia": "Safra 2026/2027 (taxa vigente a partir de 01/07/2026)",
        "trecho_fonte": '"Com o Pronaf Custeio A/C você pode adquirir sementes, fertilizantes, '
            'defensivos, vacinas, ração e outros itens necessários para o dia a dia da sua '
            'produção." / "Cada produtor pode financiar até R$ 22 mil por ano agrícola." / '
            '"Taxa de juros de 1,5% a.a. Taxa de juros de 3,0% a.a. para Cooperativas." '
            '(capturado ao vivo da página oficial em 2026-09-15)',
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": "Agricultura familiar",
        "destinacao_padronizada": "Custeio de agricultura familiar",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "pronaf custeio a/c agricultura familiar indigenas quilombolas "
            "banco do brasil",
    },
    {
        "instituicao": "BB",
        "nome_oficial": "Custeio Agropecuário",
        "nome_simplificado": "Custeio Agropecuário",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Financiamento das despesas de produção agropecuária, para "
            "lavoura ou animais, incluindo atividades aquícolas.",
        "descricao_completa": "Com o Custeio Agropecuário do BB, é possível financiar diferentes "
            "despesas da produção agropecuária, seja para a lavoura ou para os animais, até "
            "mesmo em atividades aquícolas, com financiamento de até 100% do orçamento.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária, aquicultura e pesca",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Produtor rural PF e PJ, cooperativas agropecuárias, aquicultores e "
            "pescadores",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Custeio da produção agropecuária e aquícola",
        "itens_financiaveis": NAO_INFORMADO,
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 3000000.0,
        "percentual_financiavel": "Até 100% do orçamento (recursos controlados: teto de R$ 3 "
            "milhões por ano agrícola; recursos não controlados: sem teto de valor).",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Recursos controlados (até R$ 3 milhões): 12,5% a.a.; recursos não "
            "controlados (sem teto): taxa prefixada. Tarifa de estudo de operações rurais: 0,5% "
            "sobre o valor financiado. Alongamento de operações de custeio: 0,5% sobre o saldo "
            "devedor a alongar.",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 24 meses.",
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": "Produtor rural PF e PJ, cooperativas agropecuárias, "
            "aquicultores e pescadores.",
        "agente_financeiro": "Banco do Brasil",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/pbb/pagina-inicial/agronegocios/agronegocio---produtos-e-servicos/credito/credito-para-custeio/custeio-agropecuario#/",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"Com o Custeio Agropecuário do BB, você pode realizar o financiamento '
            'de diferentes despesas da sua produção agropecuária, seja para a lavoura ou para '
            'os seus animais, até mesmo em atividades aquícolas." / "Recursos controlados: R$ 3 '
            'milhões por ano agrícola... Recursos não controlados: não há teto." / "Recursos '
            'controlados: R$ 3 milhões - 12,5% a.a. Recursos não controlados: Não há Teto - '
            'Taxa Prefixada." (capturado ao vivo da página oficial em 2026-09-15)',
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Custeio agropecuário e aquícola",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "custeio agropecuario credito rural banco do brasil aquicultura "
            "pesca",
    },
    {
        "instituicao": "BB",
        "nome_oficial": "Funcafé Custeio",
        "nome_simplificado": "Funcafé Custeio",
        "sigla": "Funcafé",
        "status": "aberta",
        "descricao_resumida": "Crédito para as despesas de produção das lavouras de café "
            "(custeio).",
        "descricao_completa": "Financiamento das despesas normais de custeio de café, com "
            "recursos do Funcafé (Fundo de Defesa da Economia Cafeeira), destinado a "
            "cafeicultores e suas cooperativas de produção agropecuária.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Cafeicultura",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Cafeicultores e suas cooperativas de produção agropecuária",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Custeio da produção de lavouras de café",
        "itens_financiaveis": "Despesas normais de custeio de café.",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 3000000.0,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "11,5% a.a. Tarifa de estudo de operações rurais: 0,5% sobre o valor "
            "financiado.",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 20 meses.",
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": "Limite financiável: cafeicultor, até R$ 3 milhões; cooperativas de "
            "produção, até R$ 50 milhões.",
        "criterios_elegibilidade": "Cafeicultores e suas cooperativas de produção "
            "agropecuária.",
        "agente_financeiro": "Banco do Brasil (Funcafé - Fundo de Defesa da Economia Cafeeira)",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/site/agronegocios/custeio/funcafe-custeio/",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"Financiamento das despesas normais de custeio de café." / '
            '"Beneficiários: Cafeicultores e suas cooperativas de produção agropecuária." / '
            '"Limite financiável: Cafeicultor: R$ 3 milhões. Cooperativas de Produção: R$ 50 '
            'milhões." / "Taxa de juros: 11,5% a.a." / "Prazo: Até 20 meses." (capturado ao '
            "vivo da página oficial em 2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Custeio de cafeicultura",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "funcafe custeio cafe cafeicultura financiamento fundo defesa "
            "economia cafeeira banco do brasil",
    },
    {
        "instituicao": "BB",
        "nome_oficial": "Programa Nacional de Crédito Fundiário",
        "nome_simplificado": "Crédito Fundiário",
        "sigla": "PNCF",
        "status": "aberta",
        "descricao_resumida": "Financiamento para aquisição de imóveis rurais e benfeitorias "
            "existentes, despesas com georreferenciamento, topografia e registro cartorário.",
        "descricao_completa": "Com o Programa Nacional de Crédito Fundiário é possível "
            "financiar a aquisição de imóveis rurais e benfeitorias existentes, despesas com "
            "georreferenciamento, topografia e registro cartorário.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agricultura familiar / reforma agrária",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Trabalhadores rurais sem terra, posseiros, pequenos produtores "
            "rurais arrendatários, parceiros, proprietários de minifúndios e meeiros agregados",
        "faixa_receita": "Varia por modalidade: até R$ 60.719,26 (PNCF Mais/Jovem), até R$ "
            "30.359,63 (PNCF Social) ou até R$ 327.785,79 (PNCF Empreendedor), renda bruta "
            "familiar anual",
        "regiao_elegivel": "Brasil (PNCF Social restrito a famílias da região Norte e área de "
            "abrangência da Sudene)",
        "destinacao": "Aquisição de imóveis rurais e estruturação da propriedade",
        "itens_financiaveis": "Aquisição de imóveis rurais e benfeitorias existentes; despesas "
            "com georreferenciamento, topografia e registro cartorário.",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 327785.79,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "PNCF Mais: 2,5% a.a. (renda bruta familiar anual até R$ 60.719,26 e "
            "patrimônio até R$ 140.000,00); PNCF Social: 0,5% a.a. (renda até R$ 30.359,63, "
            "patrimônio até R$ 70.000,00, famílias da região Norte e área de abrangência da "
            "Sudene, inscritas no Cadastro Único); PNCF Jovem: 0,5% a.a. (menores de 30 anos, "
            "renda até R$ 60.719,26, patrimônio até R$ 140.000,00); PNCF Empreendedor: 4% a.a. "
            "(renda até R$ 327.785,79, patrimônio até R$ 500.000,00). Bônus de antecipação: 20% "
            "(PNCF Mais) ou 40% (PNCF Social) sobre o valor do capital e dos juros pagos até o "
            "vencimento.",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": NAO_INFORMADO,
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": "Disponibilização sujeita à análise prévia e aprovação da Unidade "
            "Técnica Estadual (UTE), após envio da proposta pela Assistência Técnica.",
        "criterios_elegibilidade": "Trabalhadores rurais sem terra, posseiros, pequenos "
            "produtores rurais arrendatários, parceiros, proprietários de minifúndios e "
            "meeiros agregados.",
        "agente_financeiro": "Banco do Brasil (Programa Nacional de Crédito Fundiário)",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/site/agronegocios/pronaf-credito-fundiario/#/",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"Com o Programa Nacional de Crédito Fundiário é possível financiar a '
            'aquisição de imóveis rurais e benfeitorias existentes, despesas com '
            'georreferenciamento, topografia e registro cartorário." / "PNCF MAIS: 2,5% a.a." / '
            '"Teto: R$ 327.785,79... por beneficiário." (capturado ao vivo da página oficial em '
            "2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": "Agricultura familiar / reforma agrária",
        "destinacao_padronizada": "Aquisição de terras (crédito fundiário)",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "credito fundiario pncf aquisicao terras reforma agraria banco do "
            "brasil",
    },
    {
        "instituicao": "BB",
        "nome_oficial": "RenovAgro",
        "nome_simplificado": "RenovAgro",
        "sigla": "RenovAgro",
        "status": "aberta",
        "descricao_resumida": "Financiamento de projetos de investimento destinados a práticas "
            "que reduzam a emissão de gases de efeito estufa nas atividades agropecuárias.",
        "descricao_completa": "Programa de Financiamento a Sistemas de Produção Agropecuária "
            "Sustentáveis (RenovAgro): permite financiar projetos de investimento destinados às "
            "práticas que contribuam para a redução da emissão dos gases de efeito estufa "
            "oriundos das atividades agropecuárias, incluindo recuperação de pastagens "
            "degradadas, sistemas orgânicos de produção, plantio direto na palha, integração "
            "lavoura-pecuária-floresta e sistemas agroflorestais, manejo de florestas "
            "comerciais, adequação/regularização ambiental, manejo de resíduos da produção "
            "animal, florestas de palmáceas para uso energético, bioinsumos/biofertilizantes e "
            "manejo dos solos.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Produtor rural PF e PJ, e Cooperativas",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Sistemas de produção agropecuária sustentáveis, com redução de emissão "
            "de gases de efeito estufa",
        "itens_financiaveis": "Recuperação de pastagens degradadas (RenovAgro + Recuperação); "
            "sistemas orgânicos de produção (RenovAgro + Orgânico); plantio direto na palha "
            "(RenovAgro + Plantio Direto); integração lavoura-pecuária, lavoura-floresta, "
            "pecuária-floresta ou lavoura-pecuária-floresta e sistemas agroflorestais "
            "(RenovAgro + Integração); manejo de florestas comerciais, inclusive uso industrial "
            "ou produção de carvão vegetal (RenovAgro + Florestas); adequação/regularização "
            "ambiental, inclusive recuperação de reserva legal e áreas de preservação "
            "permanente (RenovAgro + Ambiental); manejo de resíduos da produção animal para "
            "geração de energia e compostagem (RenovAgro + Manejo de Resíduos); florestas de "
            "palmáceas para uso energético (RenovAgro + Palmáceas); fixação biológica de "
            "nitrogênio, bioinsumos e biofertilizantes (RenovAgro + Bioinsumos); práticas "
            "conservacionistas de manejo do solo (RenovAgro + Manejo dos Solos).",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": 5000000.0,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "RenovAgro Ambiental: 8,5% a.a.; RenovAgro Recuperação e Conversão: "
            "8,5% a.a.; demais finalidades: 9,5% a.a. Tarifa de contratação: 0,5% sobre o valor "
            "do financiamento.",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "a) Aquisição de bovinos, bubalinos, ovinos, caprinos para reprodução, "
            "recria e terminação, e sêmen/óvulos/embriões: até 5 anos, 1ª parcela em até 12 "
            "meses; b) implantação e manutenção de florestas comerciais/carvão vegetal, "
            "florestas de dendezeiro/açaí/cacau/oliveiras/nogueiras e recomposição de "
            "APP/reserva legal: até 12 anos, com carência de até 96 meses; c) demais situações: "
            "até 10 anos, incluídos até 60 meses de carência.",
        "carencia": "Até 96 meses (florestas/recomposição ambiental) ou até 60 meses (demais "
            "situações), conforme finalidade.",
        "amortizacao": NAO_INFORMADO,
        "garantias": "Seguro obrigatório para os bens oferecidos em garantia da operação.",
        "restricoes": "Limite máximo financiável: R$ 5 milhões (empreendimentos individuais); "
            "R$ 20 milhões (empreendimentos coletivos).",
        "criterios_elegibilidade": "Produtor rural PF e PJ, e Cooperativas.",
        "agente_financeiro": "Banco do Brasil",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/site/agronegocios/investimentos/renovagro/#/",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"O RenovAgro permite a você, produtor rural, financiar projetos de '
            'investimento destinados às práticas que contribuam para a redução da emissão dos '
            'gases de efeito estufa oriundos das atividades agropecuárias." / "RenovAgro '
            'Ambiental: juros de 8.5% a.a. ... Demais finalidades: juros de 9,5% a.a." / '
            '"Empreendimentos individuais: R$ 5 milhões. Empreendimentos coletivos: R$ 20 '
            'milhões." (extraído do JSON-LD FAQPage embutido no DOM da página oficial, '
            "capturado ao vivo em 2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Sistemas de produção agropecuária sustentáveis",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": "Redução de emissão de gases de efeito estufa na agropecuária "
            "(sucessor do Programa ABC/ABC+)",
        "sinonimos_termos": "renovagro abc+ agricultura baixo carbono sustentabilidade banco do "
            "brasil emissao gases efeito estufa",
    },
    {
        "instituicao": "BB",
        "nome_oficial": "FCO Rural - Investimento Agropecuário",
        "nome_simplificado": "FCO Rural",
        "sigla": "FCO",
        "status": "aberta",
        "descricao_resumida": "Crédito destinado a investimentos fixos e semifixos na região "
            "Centro-Oeste.",
        "descricao_completa": "FCO Rural Investimento Agropecuário é o crédito destinado a "
            "investimentos fixos e semifixos na região Centro-Oeste, para implantar, "
            "desenvolver ou ampliar atividades agropecuárias e agroindustriais.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária e agroindústria (região Centro-Oeste)",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Região Centro-Oeste (área de atuação do Fundo Constitucional de "
            "Financiamento do Centro-Oeste - FCO)",
        "destinacao": "Implantação, desenvolvimento ou ampliação de atividades agropecuárias e "
            "agroindustriais",
        "itens_financiaveis": "Aquisição de materiais e equipamentos de uso destinados a "
            "armazenagem, barragens, obras civis, máquinas, implementos, energia, irrigação, "
            "entre outras atividades.",
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
        "criterios_elegibilidade": NAO_INFORMADO,
        "agente_financeiro": "Banco do Brasil (Fundo Constitucional de Financiamento do "
            "Centro-Oeste - FCO)",
        "canal_contratacao": "Agência BB",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.bb.com.br/site/agronegocios/investimentos/fco-rural-investimento-agropecuario/#/",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"FCO Rural Investimento Agropecuário é o crédito destinado a '
            'investimentos fixos e semifixos na região Centro-Oeste." / "Informações em '
            'atualização. Estamos atualizando as condições deste produto em função das novas '
            'diretrizes e normativos vigentes." (capturado ao vivo da página oficial em '
            "2026-09-15 -- a própria página confirma que a linha existe e é operada pelo BB, "
            "mas não documenta taxa/prazo/valor no momento da captura, daí os campos "
            "NAO_INFORMADO)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Investimento agropecuário regional (Centro-Oeste)",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "fco rural investimento agropecuario centro-oeste fundo "
            "constitucional banco do brasil",
    },
]


def seed_bb_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _BB_MANUAL])


# CEF (Caixa Economica Federal): curadoria manual verificada, capturada ao vivo em
# 2026-09-15 navegando caixa.gov.br via Browser pane (WebFetch simples devolveu
# 403/loop de redirecionamento pra esse dominio). Cobertura deliberadamente menor
# que BNDES/BB/BASA -- Caixa e mais forte em habitacao/saneamento/setor publico do
# que em credito empresarial/rural incentivado; linhas do MCR (Pronaf/Pronamp/
# Inovagro/Moderfrota/Proirriga etc.) tambem oferecidas pela Caixa nao foram
# re-curadas aqui por serem os MESMOS programas nacionais ja curados via BB.
_CEF_MANUAL = [
    {
        "instituicao": "CEF",
        "nome_oficial": "Financiamento ESG Ecoeficiência",
        "nome_simplificado": "ESG Ecoeficiência",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Financiamento para aquisição de bens que promovam a eficiência "
            "energética e a redução de impactos ambientais das atividades da empresa.",
        "descricao_completa": "A CAIXA incentiva a adoção de práticas empresariais "
            "ecoeficientes, por meio do financiamento para aquisição de bens que promovam a "
            "eficiência energética e a redução de impactos ambientais das atividades da "
            "empresa. Destina-se a pequenas, médias e grandes empresas atendidas pela Rede de "
            "Atacado CAIXA que desejem investir em ações de sustentabilidade, promovendo o uso "
            "de energias renováveis e a redução de insumos, resíduos e emissão de gases "
            "causadores do efeito estufa.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Todos os setores (empresas clientes da Rede de Atacado CAIXA)",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Pequenas, médias e grandes empresas atendidas pela Rede de Atacado "
            "CAIXA",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Aquisição de máquinas/equipamentos/veículos ecoeficientes",
        "itens_financiaveis": "Sistemas de micro e minigeração de energia por fontes "
            "renováveis; sistema de aquecimento solar de água; controle ou filtragem de gases "
            "ou partículas; tratamento de resíduos sólidos; tratamento de efluentes líquidos; "
            "reciclagem de resíduos; tratamento e reutilização de águas residuais; redução de "
            "desperdício de insumos e/ou recursos naturais; eficiência energética; controle de "
            "poluição da água; remediação de área contaminada; máquinas/equipamentos/sistemas "
            "ecoeficientes novos que gerem ao menos 20% de economia energética; veículos "
            "elétricos ou híbridos.",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": "Até 100% do valor do investimento.",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Taxa reduzida, com carência e prazo diferenciados (valor exato não "
            "documentado publicamente -- consultar gerente).",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 120 meses, com carência de até 12 meses; máquinas/equipamentos/"
            "veículos financiados isoladamente: até 72 meses, incluídos até 12 meses de "
            "carência.",
        "carencia": "Até 12 meses.",
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": "Possibilidade de financiamento de máquinas e equipamentos importados, "
            "desde que já internalizados no Brasil.",
        "criterios_elegibilidade": "Ser cliente da Rede de Atacado CAIXA; ter capacidade de "
            "pagamento compatível com o financiamento solicitado.",
        "agente_financeiro": "Caixa Econômica Federal",
        "canal_contratacao": "Gerente de Agência Empresarial CAIXA",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "https://www.caixa.gov.br/empresa/credito-financiamento/financiamentos/esg-ecoeficiencia/Paginas/default.aspx",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"A CAIXA incentiva a adoção de práticas empresariais ecoeficientes, '
            'por meio do financiamento para aquisição de bens que promovam a eficiência '
            'energética e a redução de impactos ambientais das atividades da sua empresa. Pode '
            'ser financiado até 100% do valor do projeto." / "O pagamento pode ser feito em até '
            '120 meses. Carência de até 12 meses." (capturado ao vivo da página oficial via '
            "Browser pane em 2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Eficiência energética e sustentabilidade empresarial",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": "Eficiência energética, energias renováveis, redução de "
            "resíduos e emissões",
        "sinonimos_termos": "esg ecoeficiencia caixa sustentabilidade energia renovavel "
            "eficiencia energetica rede de atacado",
    },
    {
        "instituicao": "CEF",
        "nome_oficial": "Bens de Consumo Duráveis - BCD Ecoeficiência PJ",
        "nome_simplificado": "BCD Ecoeficiência PJ",
        "sigla": "BCD",
        "status": "aberta",
        "descricao_resumida": "Financiamento de máquinas e equipamentos com atributos "
            "ecoeficientes para pequenas, médias e grandes empresas.",
        "descricao_completa": "Produto de crédito destinado ao atendimento de pequenas, médias "
            "e grandes empresas que buscam a melhoria dos seus processos produtivos, "
            "financiando a aquisição de máquinas, equipamentos ou sistemas que apresentem "
            "atributos para reduzir o impacto ambiental e o uso de recursos naturais "
            "decorrentes das atividades da empresa.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Todos os setores (pessoa jurídica)",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Pequenas, médias e grandes empresas",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Aquisição de máquinas/equipamentos ecoeficientes",
        "itens_financiaveis": "Sistemas de micro e minigeração de energia por fontes "
            "renováveis; sistema de aquecimento solar de água; controle ou filtragem de gases "
            "ou partículas; tratamento de resíduos sólidos; tratamento de efluentes líquidos; "
            "reciclagem de resíduos; tratamento e reutilização de águas residuais; redução de "
            "desperdício de insumos e/ou recursos naturais; eficiência energética; controle de "
            "poluição da água; remediação de área contaminada (máquinas/equipamentos novos).",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": "Até 100% do valor do bem.",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Taxas de juros atrativas, a depender do porte e relacionamento da "
            "empresa com a CAIXA (valor exato não documentado publicamente).",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 60 meses, incluído o período de carência de até 6 meses.",
        "carencia": "Até 6 meses.",
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": "Possibilidade de financiamento de máquinas e equipamentos importados, "
            "desde que já internalizados no Brasil.",
        "criterios_elegibilidade": "Ser cliente CAIXA; ter capacidade de pagamento.",
        "agente_financeiro": "Caixa Econômica Federal",
        "canal_contratacao": "Agência CAIXA",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "http://www.caixa.gov.br/empresa/credito-financiamento/financiamentos/bens-de-consumo-duraveis/Paginas/default.aspx",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"Este produto de crédito destina-se ao atendimento de pequenas, '
            'médias e grandes empresas, que buscam a melhoria dos seus processos produtivos, '
            'financiando a aquisição de máquinas, equipamentos, ou mesmo sistemas, que '
            'apresentem atributos para reduzir o impacto ambiental." / "Financiamento de até '
            '100% do valor do bem. O pagamento pode ser feito em até 60 meses, incluído o '
            'período de carência de até 6 meses." (capturado ao vivo da página oficial via '
            "Browser pane em 2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Eficiência energética e sustentabilidade empresarial",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": "Redução de impacto ambiental e uso de recursos naturais",
        "sinonimos_termos": "bcd ecoeficiencia pj caixa maquinas equipamentos sustentavel",
    },
    {
        "instituicao": "CEF",
        "nome_oficial": "Bens de Consumo Duráveis - BCD Franquias",
        "nome_simplificado": "BCD Franquias",
        "sigla": "BCD",
        "status": "aberta",
        "descricao_resumida": "Financiamento para abertura, ampliação, modernização e repasse "
            "de franquias, destinado a empresas participantes do Programa CAIXA Mais "
            "Franquias.",
        "descricao_completa": "Se você deseja abrir, ampliar, modernizar ou adquirir uma "
            "unidade franqueada, o BCD Franquias é a solução para impulsionar o crescimento do "
            "negócio. Destinada às empresas participantes do Programa CAIXA Mais Franquias, a "
            "linha de crédito oferece condições para financiar projetos de implantação, "
            "expansão, modernização e repasse de franquias.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Franquias (marcas habilitadas no Programa CAIXA Mais Franquias)",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Implantação, expansão, modernização e repasse de unidades franqueadas",
        "itens_financiaveis": "Abertura de novas unidades franqueadas; ampliação ou "
            "modernização do negócio franqueado; repasse de franquias.",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": "Entre 20% e 80% do investimento total, conforme a "
            "classificação da marca franqueada e as condições do Programa CAIXA Mais "
            "Franquias.",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Condições de contratação personalizadas, conforme análise do perfil "
            "da empresa e garantias apresentadas (valor exato não documentado publicamente).",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Amortização em até 60 meses; vencimento das prestações escolhido no "
            "momento da contratação.",
        "carencia": NAO_INFORMADO,
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": "Consulte o franqueador para verificar se está habilitado junto à CAIXA "
            "(Programa CAIXA Mais Franquias).",
        "criterios_elegibilidade": "Empresas participantes de marca franqueada habilitada no "
            "Programa CAIXA Mais Franquias.",
        "agente_financeiro": "Caixa Econômica Federal (Programa CAIXA Mais Franquias)",
        "canal_contratacao": "Agência CAIXA",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": NAO_INFORMADO,
        "url_oficial": "http://www.caixa.gov.br/empresa/credito-financiamento/financiamentos/bens-de-consumo-duraveis/Paginas/default.aspx",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"Se você deseja abrir, ampliar, modernizar ou adquirir uma unidade '
            'franqueada, o BCD Franquias é a solução ideal para impulsionar o crescimento do '
            'seu negócio." / "O limite de financiamento poderá variar entre 20% e 80% do '
            'investimento total, conforme a classificação da marca franqueada." / "O prazo de '
            'amortização pode chegar a até 60 meses." (capturado ao vivo da página oficial via '
            "Browser pane em 2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "COMERCIO/SERVICOS",
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Investimento em franquias",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "bcd franquias caixa mais franquias implantacao expansao repasse",
    },
    {
        "instituicao": "CEF",
        "nome_oficial": "FDA - Fundo de Desenvolvimento da Amazônia",
        "nome_simplificado": "FDA",
        "sigla": "FDA",
        "status": "aberta",
        "descricao_resumida": "Linha de crédito com recursos do Fundo de Desenvolvimento da "
            "Amazônia (FDA), destinada a projetos de empresas privadas com empreendimentos na "
            "Amazônia Legal.",
        "descricao_completa": "É uma linha de crédito com recursos do Fundo de Desenvolvimento "
            "da Amazônia (FDA), destinada a projetos de empresas privadas com empreendimentos "
            "na Amazônia Legal, por meio da avaliação de viabilidade técnica, econômica e "
            "administrativa dos projetos encaminhados à Caixa pela Superintendência de "
            "Desenvolvimento da Amazônia (Sudam). O financiamento é destinado à implantação, "
            "ampliação, diversificação ou modernização de empreendimentos. A Caixa atua como "
            "agente operador do Fundo -- ver também a linha equivalente operada pelo Banco da "
            "Amazônia (instituicao=\"BASA\"), mesmo fundo gerido pela SUDAM.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": NAO_INFORMADO,
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": NAO_INFORMADO,
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Área de atuação da Superintendência de Desenvolvimento da Amazônia "
            "(SUDAM) -- Amazônia Legal",
        "destinacao": "Implantação, ampliação, diversificação ou modernização de "
            "empreendimentos na Amazônia Legal",
        "itens_financiaveis": "Obras civis; equipamentos de infraestrutura (incluindo "
            "montagem); infraestrutura; máquinas e equipamentos novos; aparelhos; veículos "
            "utilitários novos; móveis e utensílios novos.",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": NAO_INFORMADO,
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": NAO_INFORMADO,
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 12 anos, incluindo a carência, podendo ser estendido para até 20 "
            "anos após justificativa da Caixa e análise da Sudam.",
        "carencia": "Incluída no prazo total de até 12 anos (ou até 20 anos, se estendido).",
        "amortizacao": "Desembolso conforme evolução física das obras/serviços/estudos/"
            "projetos e do trabalho socioambiental, comprovada por engenheiro e/ou técnico "
            "social da Caixa, respeitando o cronograma de desembolso contratualmente "
            "estabelecido.",
        "garantias": "Seguros de conclusão de obra e de performance; hipoteca de bens próprios "
            "ou de terceiros; penhor de direitos creditórios; cessão de direitos emergentes de "
            "concessão; penhor de recebíveis; aval ou fiança dos acionistas controladores; "
            "fundos de liquidez; fiança bancária; outras garantias reais (prestadas "
            "cumulativamente ou não).",
        "restricoes": "Emissão de debêntures a cada liberação de recursos do FDA, podendo ser "
            "dividida em séries; o valor total das emissões não pode ultrapassar o capital "
            "social da companhia, podendo alcançar até 80% do valor dos bens gravados (garantia "
            "real) ou 70% do valor contábil do ativo líquido de dívidas garantidas por direitos "
            "reais (garantia flutuante).",
        "criterios_elegibilidade": "Projetos de empresas privadas com empreendimentos na área "
            "de atuação da SUDAM, avaliados quanto à viabilidade técnica, econômica e "
            "administrativa.",
        "agente_financeiro": "Caixa Econômica Federal (Fundo de Desenvolvimento da Amazônia - "
            "FDA, gerido pela SUDAM)",
        "canal_contratacao": "Carta Consulta à SUDAM, indicando a Caixa como Agente Operador/"
            "Financeiro",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": "Carta Consulta à Sudam conforme modelo da Resolução 06/08 "
            "da SUDAM.",
        "url_oficial": "http://www.caixa.gov.br/empresa/credito-financiamento/financiamentos/fundo-desenvolvimento-amazonia/Paginas/default.aspx",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"É uma linha de crédito com recursos do Fundo de Desenvolvimento da '
            'Amazônia (FDA), destinada a projetos de empresas privadas com empreendimentos na '
            'Amazônia Legal." / "O prazo total máximo da operação é de até 12 anos, incluindo o '
            'período de carência, podendo ser estendido para até 20 anos após justificativa da '
            'Caixa e análise da Sudam." (capturado ao vivo da página oficial via Browser pane '
            "em 2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": NAO_INFORMADO,
        "subsetor_padronizado": None,
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Infraestrutura e produção regional (Amazônia Legal)",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "fda fundo de desenvolvimento da amazonia sudam caixa infraestrutura "
            "grandes projetos",
    },
    {
        "instituicao": "CEF",
        "nome_oficial": "Programa Sustentabilidade",
        "nome_simplificado": "Programa Sustentabilidade",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Financiamento de projetos que tenham como objetivo a redução na "
            "emissão de gases de efeito estufa nas atividades agropecuárias.",
        "descricao_completa": "Financiamento de projetos de implantação e melhoramento de "
            "sistemas de Integração Lavoura e Pecuária, plantio direto na palha, tratamento de "
            "dejetos, recuperação de áreas degradadas e projetos similares que tenham como "
            "objetivo a redução na emissão de gases de efeito estufa, não incluindo o "
            "financiamento para aquisição de equipamento de forma isolada.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Produtores Rurais Pessoa Física, Produtores Rurais Pessoa Jurídica, "
            "Cooperativas de Produção Agropecuária",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Sistemas de produção agropecuária sustentáveis, com redução de emissão "
            "de gases de efeito estufa",
        "itens_financiaveis": "Investimento fixo: proteção/correção/recuperação de solos "
            "(corretivos agrícolas, terraços, adubação verde); adubação intensiva do solo; "
            "plantio de florestas comerciais (integração Lavoura-Pecuária-Floresta); aquisição/"
            "construção/reforma de cercas, bebedouros e cochos; formação/recuperação/"
            "reconversão de pastagens; construção/reforma/modernização de instalações para "
            "criação e manejo animal, e de benfeitorias para guarda de máquinas e insumos; "
            "aquisição de máquinas e equipamentos novos; aquisição e implantação de sistemas de "
            "irrigação; estrutura para tratamento de resíduos e produção de energia renovável; "
            "eletrificação (inclusive geração/distribuição de energia renovável para consumo "
            "próprio). Investimento semifixo: aquisição de animais para reprodução e cria "
            "(exceto Pronamp); implementos/máquinas/equipamentos novos com duração útil não "
            "superior a 5 anos; certificação da produção agropecuária.",
        "itens_nao_financiaveis": "Aquisição de equipamento de forma isolada (sem projeto de "
            "implantação/melhoramento associado).",
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": "Recursos não controlados; limite de acordo com avaliação de "
            "risco e projeto técnico ou plano simples apresentado pelo cliente.",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Taxas prefixadas ou pós-fixadas, definidas conforme avaliação de "
            "risco e histórico de relacionamento com a CAIXA (valor exato não documentado "
            "publicamente -- consultar agência).",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 8 anos, com carência de até 36 meses, de acordo com a finalidade e "
            "fonte de recurso da operação.",
        "carencia": "Até 36 meses.",
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": "Produtores Rurais Pessoa Física, Produtores Rurais Pessoa "
            "Jurídica, Cooperativas de Produção Agropecuária.",
        "agente_financeiro": "Caixa Econômica Federal",
        "canal_contratacao": "Agência CAIXA",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": "Projeto técnico ou plano simples.",
        "url_oficial": "https://www.caixa.gov.br/agro/investimento/programa-sustentabilidade/Paginas/default.aspx",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"Financiamento de projetos de implantação e melhoramento de sistemas '
            'de Integração Lavoura e Pecuária, plantio direto na palha, tratamento de dejetos, '
            'recuperação de áreas degradadas e projetos similares que tenham como objetivo a '
            'redução na emissão de gases de efeito estufa." / "Até 08 anos com carência de até '
            '36 meses." (capturado ao vivo da página oficial via Browser pane em 2026-09-15)',
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Sistemas de produção agropecuária sustentáveis",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": "Redução de emissão de gases de efeito estufa na agropecuária",
        "sinonimos_termos": "programa sustentabilidade caixa agropecuaria integracao lavoura "
            "pecuaria emissao gases efeito estufa",
    },
    {
        "instituicao": "CEF",
        "nome_oficial": "Programa Armazenagem",
        "nome_simplificado": "Programa Armazenagem",
        "sigla": None,
        "status": "aberta",
        "descricao_resumida": "Financiamento de aquisição e implantação de estrutura para "
            "armazenamento de grãos e produtos agrícolas.",
        "descricao_completa": "Linha para o financiamento de aquisição e implantação de "
            "estrutura para armazenamento de grãos e produtos agrícolas, incluindo câmaras "
            "frias, silos, armazéns, elevadores, secadores e demais componentes do sistema de "
            "armazenagem.",
        "modalidade": "Direta",
        "tipo_apoio": "Financiamento",
        "setores_elegiveis": "Agropecuária",
        "setores_nao_elegiveis": NAO_INFORMADO,
        "porte_elegivel": "Produtores Rurais Pessoa Física, Produtores Rurais Pessoa Jurídica, "
            "Cooperativas de Produção Agropecuária",
        "faixa_receita": NAO_INFORMADO,
        "regiao_elegivel": "Brasil",
        "destinacao": "Estrutura de armazenamento de grãos e produtos agrícolas",
        "itens_financiaveis": "Aquisição e implantação de estrutura para armazenamento de "
            "grãos e produtos agrícolas, incluindo câmaras frias, silos, armazéns, elevadores, "
            "secadores e demais componentes do sistema de armazenagem.",
        "itens_nao_financiaveis": NAO_INFORMADO,
        "valor_minimo": None,
        "valor_maximo": None,
        "percentual_financiavel": "Recursos não controlados; limite de acordo com avaliação de "
            "risco e projeto técnico ou plano simples apresentado pelo cliente.",
        "contrapartida": NAO_INFORMADO,
        "taxa_completa": "Taxas prefixadas ou pós-fixadas, definidas conforme avaliação de "
            "risco e histórico de relacionamento com a CAIXA (valor exato não documentado "
            "publicamente -- consultar agência).",
        "indexador": NAO_INFORMADO,
        "spread": NAO_INFORMADO,
        "prazo_total": "Até 8 anos, com carência de 24 meses, de acordo com a finalidade e "
            "fonte de recurso da operação.",
        "carencia": "24 meses.",
        "amortizacao": NAO_INFORMADO,
        "garantias": NAO_INFORMADO,
        "restricoes": NAO_INFORMADO,
        "criterios_elegibilidade": "Produtores Rurais Pessoa Física, Produtores Rurais Pessoa "
            "Jurídica, Cooperativas de Produção Agropecuária.",
        "agente_financeiro": "Caixa Econômica Federal",
        "canal_contratacao": "Agência CAIXA",
        "prazo_inscricao": NAO_INFORMADO,
        "fluxo": "continuo",
        "documentos_necessarios": "Projeto técnico ou plano simples.",
        "url_oficial": "https://www.caixa.gov.br/agro/investimento/armazenagem/Paginas/default.aspx",
        "data_vigencia": NAO_INFORMADO,
        "trecho_fonte": '"Linha para o financiamento de aquisição e implantação de estrutura '
            'para armazenamento de grãos e produtos agrícolas incluindo câmaras frias, silos, '
            'armazéns, elevadores, secadores e demais componentes do sistema de armazenagem." '
            '/ "Até 08 anos com carência de 24 meses." (capturado ao vivo da página oficial '
            "via Browser pane em 2026-09-15)",
        "origem_dado": "curadoria_manual_verificada",
        "origem_raw_id": None,
        "setor_padronizado": "AGROPECUÁRIA",
        "subsetor_padronizado": "AGROPECUÁRIA",
        "cnaes_relacionados": None,
        "porte_padronizado": None,
        "destinacao_padronizada": "Armazenagem de produtos agrícolas",
        "tecnologias_relacionadas": None,
        "temas_inovacao": None,
        "temas_sustentabilidade": None,
        "sinonimos_termos": "programa armazenagem caixa silos armazens graos produtos "
            "agricolas",
    },
]


def seed_cef_manual(conn) -> int:
    return _upsert_many(conn, [dict(linha) for linha in _CEF_MANUAL])


def build_linhas_incentivadas():
    conn = get_connection()
    try:
        n_finep = seed_finep_manual(conn)
        n_bndes = seed_bndes_manual(conn)
        n_desenvolve_sp = seed_desenvolve_sp_manual(conn)
        n_bnb = seed_bnb_manual(conn)
        n_basa = seed_basa_manual(conn)
        n_bb = seed_bb_manual(conn)
        n_cef = seed_cef_manual(conn)
        backfill_porte_e_destinacao_grupo(conn)
        total = conn.execute("SELECT COUNT(*) FROM linhas_incentivadas").fetchone()[0]
    finally:
        conn.close()
    print(
        f"linhas_incentivadas: {n_finep} da FINEP + {n_bndes} do BNDES + "
        f"{n_desenvolve_sp} da Desenvolve SP + {n_bnb} do BNB + {n_basa} do BASA + "
        f"{n_bb} do BB + {n_cef} da CEF (todas curadoria manual verificada) "
        f"processadas -- {total} linhas no total."
    )


if __name__ == "__main__":
    build_linhas_incentivadas()
