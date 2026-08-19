"""Monta uma visao amigavel (secoes rotuladas) do detalhe de uma operacao,
a partir das colunas brutas de cada tabela de origem (BNDES / FINEP)."""


def _cnpj_fmt(v):
    if not v:
        return None
    s = str(v).zfill(14)
    return f"{s[0:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:14]}"


# Cada entrada: (coluna_bruta, label, tipo, formatador_opcional)
# tipo: moeda | percentual | data | numero | texto
SECOES_BNDES = [
    ("Empresa", [
        ("cliente", "Cliente", "texto", None),
        ("cnpj", "CNPJ", "texto", _cnpj_fmt),
        ("natureza_cliente", "Natureza", "texto", None),
        ("porte_cliente", "Porte", "texto", None),
        ("uf", "UF", "texto", None),
        ("municipio", "Município", "texto", None),
    ]),
    ("Classificação", [
        ("setor_bndes", "Setor", "texto", None),
        ("subsetor_bndes", "Subsetor", "texto", None),
        ("subsetor_cnae_nome", "Segmento (CNAE)", "texto", None),
        ("area_operacional", "Área operacional do BNDES", "texto", None),
    ]),
    ("Operação", [
        ("numero_contrato", "Número do contrato", "texto", None),
        ("data_contratacao", "Data da contratação", "data", None),
        ("situacao_contrato", "Situação", "texto", None),
        ("forma_apoio", "Forma de apoio", "texto", None),
        ("produto", "Produto", "texto", None),
        ("instrumento_financeiro", "Instrumento financeiro", "texto", None),
        ("inovacao", "Projeto de inovação", "texto", None),
    ]),
    ("Valores", [
        ("valor_contratado", "Valor contratado", "moeda", None),
        ("valor_desembolsado", "Valor desembolsado", "moeda", None),
    ]),
    ("Condições financeiras", [
        ("modalidade_apoio", "Modalidade", "texto", None),
        ("custo_financeiro", "Indexador", "texto", None),
        ("juros", "Juros/spread", "percentual", None),
        ("prazo_carencia_meses", "Prazo de carência", "meses", None),
        ("prazo_amortizacao_meses", "Prazo de amortização", "meses", None),
        ("fonte_recurso", "Fonte de recurso", "texto", None),
        ("tipo_garantia", "Tipo de garantia", "texto", None),
        ("tipo_excepcionalidade", "Excepcionalidade", "texto", None),
    ]),
    ("Instituição financeira credenciada", [
        ("instituicao_financeira_credenciada", "Instituição", "texto", None),
        ("cnpj_if_credenciada", "CNPJ da instituição", "texto", _cnpj_fmt),
    ]),
    ("Projeto", [
        ("descricao_projeto", "Descrição do projeto", "texto_longo", None),
    ]),
]

SECOES_FINEP_CREDITO_DIRETO = [
    ("Empresa", [
        ("proponente", "Proponente", "texto", None),
        ("cnpj_proponente", "CNPJ", "texto", _cnpj_fmt),
        ("uf_proponente", "UF", "texto", None),
        ("municipio_proponente", "Município", "texto", None),
        ("regiao_proponente", "Região", "texto", None),
        ("executor", "Executor (se diferente)", "texto", None),
    ]),
    ("Operação", [
        ("contrato", "Número do contrato", "texto", None),
        ("data_assinatura", "Data da assinatura", "data", None),
        ("status", "Status", "texto", None),
        ("demanda", "Demanda/programa", "texto", None),
        ("ref", "Referência", "texto", None),
    ]),
    ("Valores", [
        ("valor_finep", "Valor FINEP", "moeda", None),
        ("contrapartida_financeira", "Contrapartida financeira", "moeda", None),
        ("valor_pago", "Valor pago", "moeda", None),
    ]),
    ("Prazos e avaliação", [
        ("prazo_execucao", "Prazo de execução (até)", "data", None),
        ("tempo_contratacao", "Tempo de contratação", "dias", None),
        ("tempo_total_avaliacao", "Tempo total de avaliação", "dias", None),
    ]),
    ("Projeto", [
        ("titulo", "Título", "texto", None),
        ("resumo_publicavel", "Resumo", "texto_longo", None),
    ]),
]

SECOES_FINEP_DESCENTRALIZADO = [
    ("Empresa", [
        ("beneficiario", "Beneficiário", "texto", None),
        ("cnpj_beneficiario", "CNPJ", "texto", _cnpj_fmt),
        ("uf_beneficiario", "UF", "texto", None),
    ]),
    ("Operação", [
        ("contrato_finep_agente", "Número do contrato", "texto", None),
        ("data_assinatura", "Data da assinatura", "data", None),
        ("agente", "Instituição financeira (agente)", "texto", None),
    ]),
    ("Valores", [
        ("valor_financiado", "Valor financiado", "moeda", None),
        ("valor_liberado", "Valor liberado", "moeda", None),
        ("contrapartida", "Contrapartida", "moeda", None),
        ("outros_recursos", "Outros recursos", "moeda", None),
    ]),
]

MAPA_SECOES = {
    "bndes_raw": SECOES_BNDES,
    "finep_credito_direto_raw": SECOES_FINEP_CREDITO_DIRETO,
    "finep_credito_descentralizado_raw": SECOES_FINEP_DESCENTRALIZADO,
}


def montar_detalhe_amigavel(raw_table: str, raw: dict) -> list:
    layout = MAPA_SECOES.get(raw_table, [])
    secoes = []
    for titulo, campos in layout:
        itens = []
        for col, label, tipo, fmt in campos:
            valor = raw.get(col)
            if valor in (None, "", "nan") or (isinstance(valor, str) and valor.strip("- ") == ""):
                continue
            if fmt:
                valor = fmt(valor)
            itens.append({"label": label, "valor": valor, "tipo": tipo})
        if itens:
            secoes.append({"titulo": titulo, "campos": itens})
    return secoes
