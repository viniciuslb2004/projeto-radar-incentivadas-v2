"""Taxonomia/sinonimos usados para montar o `search_document` (ver unify.py e
search_fts.py) -- a camada de "inteligencia antecipada" da busca sem IA: em vez de
calcular similaridade semantica em tempo real (embeddings), a expansao de vocabulario
acontece uma vez, no momento em que a operacao e enriquecida, e fica gravada no banco.

Cobertura por NIVEL (do mais para o menos exaustivo):
- Setor (4 categorias) e Subsetor (19 categorias): exaustivo, todas as chaves cobertas.
- Segmento (CNAE, centenas de valores distintos): cobertura CURADA dos casos de maior
  valor -- termos de uso comum que um usuario digitaria mas que NUNCA aparecem no
  texto oficial do CNAE (ex: "fintech", "energia solar", "hospital", "agro"). Casos
  novos podem ser adicionados aqui conforme surgirem (extensivel por design -- nao
  exige mudanca de schema, so uma entrada nova no dict).

Os termos aqui sao o mesmo vocabulario já validado nesta sessão (ver EXPANSAO_TERMOS/
TERMOS_AMBIGUOS em search.py, motor de busca por IA) -- reaproveitado e invertido:
lá a expansao entra na QUERY (calculada a cada busca); aqui entra no DOCUMENTO
(calculada uma vez, no enriquecimento)."""
import unicodedata


def normalizar(txto: str) -> str:
    """Maiusculas, sem acento -- usado tanto para casar chaves de sinonimo quanto,
    depois, como uma das entradas do to_tsvector/unaccent do lado do Postgres."""
    if not txto or not isinstance(txto, str):
        return ""
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", txto) if unicodedata.category(c) != "Mn")
    return sem_acento.upper().strip()


SINONIMOS_SETOR = {
    "AGROPECUARIA": ["agro", "agronegocio", "agricultura", "pecuaria", "campo", "rural", "fazenda"],
    "COMERCIO/SERVICOS": ["comercio", "servicos", "varejo", "atacado", "prestacao de servicos"],
    "INDUSTRIA": ["industria", "industrial", "fabrica", "manufatura", "producao industrial"],
    "INFRAESTRUTURA": ["infraestrutura", "infra", "obras", "concessao", "utilidade publica"],
}

SINONIMOS_SUBSETOR = {
    "AGROPECUARIA": ["agro", "agricultura", "pecuaria", "producao rural"],
    "ALIMENTO E BEBIDA": ["alimenticio", "bebidas", "food", "industria alimenticia"],
    "ATV. AUX. TRANSPORTES": ["logistica", "armazenagem", "apoio ao transporte"],
    "CELULOSE E PAPEL": ["papel", "celulose", "papel e celulose"],
    "COMERCIO E SERVICOS": ["comercio", "servicos", "varejo", "atacado"],
    "CONSTRUCAO": ["construcao civil", "obras", "engenharia civil", "construtora"],
    "ENERGIA ELETRICA": ["energia", "eletricidade", "geracao de energia", "transmissao", "distribuicao de energia"],
    "EXTRATIVA": ["mineracao", "extracao mineral", "petroleo e gas", "mineradora"],
    "MATERIAL DE TRANSPORTE": ["automotivo", "veiculos", "autopecas", "montadora"],
    "MECANICA": ["maquinas", "equipamentos", "bens de capital", "metal-mecanica"],
    "METALURGIA E PRODUTOS": ["siderurgia", "metalurgica", "aco", "metal"],
    "OUTRAS TRANSPORTES": ["transporte", "logistica"],
    "QUIMICA E PETROQUIMICA": ["quimica", "petroquimica", "fertilizantes", "plasticos"],
    "SERV. UTILIDADE PUBLICA": ["saneamento", "agua e esgoto", "gas encanado", "utilidade publica"],
    "TELECOMUNICACOES": ["telecom", "internet", "banda larga", "fibra optica", "provedor de internet", "conectividade"],
    "TRANSPORTE FERROVIARIO": ["ferrovia", "trem de carga", "transporte sobre trilhos"],
    "TRANSPORTE RODOVIARIO": ["rodovia", "estrada", "transporte de carga", "pedagio"],
    "TEXTIL E VESTUARIO": ["textil", "confeccao", "vestuario", "moda", "roupas"],
}

# Segmento (CNAE): cobertura curada, nao exaustiva -- ver docstring do modulo. Chave e
# um SUBSTRING (normalizado) do texto oficial do segmento; casamento por "contains",
# nao igualdade exata, ja que a mesma ideia aparece com grafias/pontuacao diferentes
# em segmentos distintos (ex: varios rotulos de "ATIVIDADES DE SERVICOS FINANCEIROS").
SINONIMOS_SEGMENTO = {
    # NOTA sobre plural: o stemmer 'portuguese' do Postgres NAO unifica de forma
    # confiavel algumas formas -al/-ais (confirmado: to_tsvector reduz "hospital" e
    # "hospitalar" ambos a 'hospital', mas "hospitais" vira 'hospit' -- um radical
    # DIFERENTE). Por isso os sinonimos abaixo incluem singular E plural quando o
    # termo termina em -al, em vez de depender do stemmer para unificar sozinho.
    "SERVICOS FINANCEIROS": ["fintech", "fintechs", "instituicao financeira", "instituicoes financeiras", "credito digital", "meios de pagamento"],
    "CORRESPONDENTES DE INSTITUICOES FINANCEIRAS": ["fintech", "fintechs", "correspondente bancario", "credito digital"],
    "ADMINISTRACAO DE CARTOES DE CREDITO": ["fintech", "fintechs", "meios de pagamento", "cartao de credito", "cartoes de credito", "adquirencia"],
    "BANCOS COMERCIAIS": ["banco", "bancos", "instituicao financeira", "instituicoes financeiras"],
    "MICROCREDITO": ["credito popular", "microfinancas", "credito produtivo"],
    "ATEND HOSPITALAR": ["hospital", "hospitais", "clinica", "clinicas", "servicos medicos", "saude"],
    "ATIVIDADES DE ATENCAO A SAUDE": ["hospital", "hospitais", "clinica", "clinicas", "saude", "servicos medicos"],
    "GERACAO DE ENERGIA ELETRICA - SOLAR": ["energia solar", "solar", "fotovoltaica", "geracao distribuida"],
    "GERACAO DE ENERGIA ELETRICA - EOLICA": ["energia eolica", "eolica", "parque eolico", "parques eolicos", "vento"],
    "GERACAO DE ENERGIA ELETRICA - HIDRELETRICA": ["hidreletrica", "hidreletricas", "usina hidreletrica", "usinas hidreletricas", "energia hidraulica"],
    "DESENVOLVIMENTO DE PROGRAMAS DE COMPUTADOR": ["software", "softwares", "saas", "tecnologia", "ti", "desenvolvimento de sistemas"],
    "DESENVOLVIMENTO E LICENCIAMENTO DE PROGRAMAS DE COMPUTADOR": ["software", "softwares", "saas", "tecnologia", "digitalizacao"],
    "SUPORTE TECNICO": ["ti", "tecnologia da informacao", "suporte de ti"],
    "PROVEDORES DE ACESSO": ["internet", "provedor de internet", "provedores de internet", "banda larga", "conectividade"],
    "SERVICOS DE COMUNICACAO MULTIMIDIA": ["telecom", "internet", "banda larga"],
}


def termos_para_setor(setor: str) -> list:
    return SINONIMOS_SETOR.get(normalizar(setor), [])


def termos_para_subsetor(subsetor: str) -> list:
    return SINONIMOS_SUBSETOR.get(normalizar(subsetor), [])


def termos_para_segmento(segmento: str) -> list:
    seg_norm = normalizar(segmento)
    termos = []
    for chave, valores in SINONIMOS_SEGMENTO.items():
        if chave in seg_norm:
            termos.extend(valores)
    return termos
