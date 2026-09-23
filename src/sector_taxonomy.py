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


# ============ Setor padronizado por CNAE (setor_cnae/subsetor_cnae) ============
# Decisao de produto 2026-09-23 (opcao A, ver Obsidian Decisoes.md e
# docs/modelo-dados-pipeline.md): BNDES e FINEP passam a ter um setor COMPARAVEL,
# calculado pelo MESMO caminho (CNAE da empresa -> de_para_cnae oficial do BNDES),
# em colunas proprias de `operations` (setor_cnae/subsetor_cnae/setor_cnae_origem).
# setor_bndes/subsetor_bndes continuam existindo (BNDES = classificacao nativa da
# planilha; FINEP = legado "ultima linha vence" de build_divisao_map).
#
# Regra de desempate (substitui "ultima linha vence"):
#   1. ESPECIFICIDADE: vence a regra do de_para cujo codigo casa com o MAIOR prefixo
#      do CNAE da empresa (subclasse 7 dig. > grupo 3 dig. > divisao 2 dig.) -- ex
#      D351 (Energia eletrica) vence D35 (Comercio e Servicos) para CNAE 3511-5/01.
#   2. MESMA ESPECIFICIDADE com setores diferentes (conflito real do de_para, ex F42
#      aparece como Infraestrutura/Construcao E como Comercio e Servicos): decide pela
#      EVIDENCIA do proprio BNDES -- entre as operacoes BNDES cujo CNAE cai nessa
#      mesma regra, se um dos setores candidatos tem >= DESEMPATE_SHARE_MIN do total
#      (com pelo menos DESEMPATE_N_MIN operacoes), ele vence.
#   3. Sem evidencia suficiente -> AMBIGUO (setor_cnae = subsetor_cnae = 'AMBÍGUO'),
#      nunca chuta.
AMBIGUO = "AMBÍGUO"
DESEMPATE_SHARE_MIN = 0.8
DESEMPATE_N_MIN = 5


def _prefixos_da_faixa(faixa: str) -> list:
    """Codigos (so digitos) que uma faixa do de_para cita, preservando a
    especificidade: 'A01 a A03' -> ['01','02','03']; 'D352 e D353' -> ['352','353'];
    'H4911,\nH4912401 e\nH4912402' -> ['4911','4912401','4912402']; 'H49 (restante)' ->
    ['49'] (o "restante" e exatamente a semantica de prefixo menos especifico)."""
    numeros = re.findall(r"\d+", faixa)
    if " a " in faixa and len(numeros) >= 2:
        divs = sorted({int(n[:2]) for n in numeros})
        return [f"{d:02d}" for d in range(divs[0], divs[-1] + 1)]
    return sorted({n for n in numeros if len(n) >= 2})


def _so_digitos(cnae) -> str:
    return re.sub(r"\D", "", str(cnae or ""))


def _prefixo_mais_especifico(cnae_digitos: str, prefixos) -> str:
    for n in range(len(cnae_digitos), 1, -1):
        p = cnae_digitos[:n]
        if p in prefixos:
            return p
    return None


def build_regras_cnae(conn, evidencia_bndes=None) -> dict:
    """{prefixo: (setor, subsetor, origem)} ja com conflitos resolvidos.

    evidencia_bndes: iteravel de (cnae_digitos, setor_bndes_nativo) das operacoes BNDES
    (usada so no passo 2 do desempate). origem: 'cnae_de_para' (sem conflito),
    'cnae_desempate_bndes' (conflito resolvido pela evidencia) ou 'ambiguo'."""
    rows = conn.execute(
        "SELECT codigo_cnae_ibge_faixa, setor_bndes, subsetor_bndes FROM de_para_cnae ORDER BY id"
    ).fetchall()
    candidatos = {}
    for faixa, setor, subsetor in rows:
        par = (canonical_setor(setor), canonical_subsetor(subsetor))
        for p in _prefixos_da_faixa(str(faixa or "")):
            candidatos.setdefault(p, [])
            if par not in candidatos[p]:
                candidatos[p].append(par)

    prefixos = set(candidatos)
    conflitos = {p for p, c in candidatos.items() if len({s for s, _ in c}) > 1 or len(c) > 1}
    contagem = {}
    for cnae, setor_nativo in (evidencia_bndes or []):
        p = _prefixo_mais_especifico(_so_digitos(cnae), prefixos)
        if p in conflitos:
            d = contagem.setdefault(p, {})
            d[setor_nativo] = d.get(setor_nativo, 0) + 1

    regras = {}
    for p, cands in candidatos.items():
        if p not in conflitos:
            regras[p] = (cands[0][0], cands[0][1], "cnae_de_para")
            continue
        d = contagem.get(p, {})
        total = sum(d.values())
        vencedor = None
        if total >= DESEMPATE_N_MIN:
            for setor in {s for s, _ in cands}:
                if d.get(setor, 0) / total >= DESEMPATE_SHARE_MIN:
                    subs = [sub for s, sub in cands if s == setor]
                    if len(subs) == 1:
                        vencedor = (setor, subs[0])
        if vencedor:
            regras[p] = (vencedor[0], vencedor[1], "cnae_desempate_bndes")
        else:
            regras[p] = (AMBIGUO, AMBIGUO, "ambiguo")
    return regras


def classificar_cnae(cnae, regras: dict):
    """(setor_cnae, subsetor_cnae, origem) para um codigo CNAE -- (None, None,
    'sem_cnae') sem codigo; (None, None, 'sem_de_para') se nenhuma regra casa."""
    dig = _so_digitos(cnae)
    if len(dig) < 2:
        return None, None, "sem_cnae"
    p = _prefixo_mais_especifico(dig, regras)
    if p is None:
        return None, None, "sem_de_para"
    return regras[p]
