"""Normaliza os rotulos de Setor/Subsetor BNDES.

A aba SITE do BNDES (dados nativos) e a aba DE-PARA CNAE (usada para
enriquecer o setor da FINEP) usam grafias diferentes para as MESMAS
categorias (ex: 'INDUSTRIA' vs 'Indústria', 'COMERCIO/SERVICOS' vs
'Comércio e Serviços'). Sem normalizar, o dashboard trataria isso como
setores diferentes e quebraria a comparacao BNDES x FINEP.

Estes dicionarios mapeiam a grafia da aba DE-PARA CNAE (em maiusculas,
sem variacao de acento) para a grafia nativa usada na aba SITE do BNDES,
que e a que aparece em todas as 23 mil operacoes do BNDES e por isso e
adotada como o rotulo canonico exibido no dashboard.
"""
import re

SETOR_ALIAS = {
    "AGROPECUÁRIA": "AGROPECUÁRIA",
    "COMÉRCIO E SERVIÇOS": "COMERCIO/SERVICOS",
    "INDÚSTRIA": "INDUSTRIA",
    "INFRAESTRUTURA": "INFRAESTRUTURA",
}

SUBSETOR_ALIAS = {
    "AGROPECUÁRIA": "AGROPECUÁRIA",
    "ALIMENTO E BEBIDA": "ALIMENTO E BEBIDA",
    "ATIVIDADES AUXILIARES DE TRANSPORTES": "ATV. AUX. TRANSPORTES",
    "CELULOSE E PAPEL": "CELULOSE E PAPEL",
    "COMÉRCIO E SERVIÇOS": "COMÉRCIO E SERVIÇOS",
    "CONSTRUÇÃO": "CONSTRUÇÃO",
    "ENERGIA ELÉTRICA": "ENERGIA ELÉTRICA",
    "EXTRATIVA": "EXTRATIVA",
    "MATERIAL DE TRANSPORTE": "MATERIAL DE TRANSPORTE",
    "MECÂNICA": "MECÂNICA",
    "METALURGIA E PRODUTOS": "METALURGIA E PRODUTOS",
    "OUTRAS": "OUTRAS",
    "OUTROS": "OUTRAS",
    "OUTROS TRANSPORTES": "OUTROS TRANSPORTES",
    "QUÍMICA E PETROQUÍMICA": "QUÍMICA E PETROQUÍMICA",
    "SERVIÇOS DE UTILIDADE PÚBLICA": "SERV. UTILIDADE PÚBLICA",
    "TELECOMUNICAÇÕES": "TELECOMUNICAÇÕES",
    "TRANSPORTE FERROVIÁRIO": "TRANSPORTE FERROVIÁRIO",
    "TRANSPORTE RODOVIÁRIO": "TRANSPORTE RODOVIÁRIO",
    "TÊXTIL E VESTUÁRIO": "TÊXTIL E VESTUÁRIO",
}


def canonical_setor(raw: str):
    if not raw:
        return raw
    return SETOR_ALIAS.get(raw.strip().upper(), raw.strip().upper())


def canonical_subsetor(raw: str):
    if not raw:
        return raw
    return SUBSETOR_ALIAS.get(raw.strip().upper(), raw.strip().upper())


def _extrair_divisoes(faixa: str) -> list:
    """Devolve as divisoes (2 digitos) que uma faixa do de_para_cnae realmente
    representa -- ex 'B05 a B09' -> [5,6,7,8,9], 'C10' -> [10], 'K64, K65 e K66' ->
    [64,65,66].

    So preenche um INTERVALO (min ate max) quando o texto tem a palavra ' a ' por
    extenso (indicando uma faixa continua de verdade, ex 'A01 a A03'/'B05 a B09') --
    listas separadas por virgula/'e', ou codigos de SUBCLASSE mais longos (7 digitos,
    ex 'H4912401'), NUNCA viram um intervalo preenchido, so as divisoes efetivamente
    citadas. BUG REAL ja encontrado por isso: a linha 'H4911,\\nH4912401 e\\nH4912402'
    (3 codigos de subclasse dentro da divisao 49) tinha o numero inteiro fatiado cru em
    blocos de 2 digitos (a versao antiga desta funcao fazia isso) -- '4912401' virava
    fragmentos tipo '49','12','40', e o min/max desses fragmentos soltos [11..49] era
    preenchido como se fosse um intervalo de DIVISOES, sobrescrevendo o mapeamento
    correto de varias divisoes no meio (ex: divisao 26, fabricacao de eletronicos,
    virava 'Transporte Ferroviario' em vez de 'Industria'). Pegar so os 2 PRIMEIROS
    digitos de cada numero (a divisao de verdade) evita esse tipo de fragmento espurio."""
    numeros = re.findall(r"\d+", faixa)
    divisoes = sorted({int(n[:2]) for n in numeros if len(n) >= 2})
    if not divisoes:
        return []
    if " a " in faixa and len(divisoes) >= 2:
        return list(range(divisoes[0], divisoes[-1] + 1))
    return divisoes


def build_divisao_map(conn) -> dict:
    """Faixas tipo 'A01 a A03' -> {divisao_int: (setor_bndes, subsetor_bndes)}.

    Extraido de enrich_cnae.py (onde nasceu, usado para enriquecer CNPJs da FINEP) para
    ca -- elegibilidade.py precisa da MESMA logica de mapeamento para um CNAE resolvido
    ao vivo (via BrasilAPI) que nao vem de nenhuma tabela de cache existente, entao faz
    mais sentido como funcao compartilhada aqui do que duplicada a mao em outro arquivo."""
    import pandas as pd

    de_para = pd.read_sql("SELECT * FROM de_para_cnae", conn)
    mapping = {}
    for _, row in de_para.iterrows():
        faixa = str(row.get("codigo_cnae_ibge_faixa") or "")
        divisoes = _extrair_divisoes(faixa)
        if not divisoes:
            continue
        setor = canonical_setor(row.get("setor_bndes"))
        subsetor = canonical_subsetor(row.get("subsetor_bndes"))
        for divisao in divisoes:
            mapping[divisao] = (setor, subsetor)
    return mapping
