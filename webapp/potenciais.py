"""Rotas de "Potenciais Linhas" -- usuario informa o perfil do projeto (atividade,
tipo de tomador, porte, UF, valor, finalidade) e recebe um ranking de Linhas
Incentivadas (`linhas_incentivadas`) com "potencial aderencia" (NUNCA
"elegibilidade confirmada" -- isso sempre depende de analise da instituicao).

Pacote ISOLADO: nenhuma tabela nova, so consulta `linhas_incentivadas`/`operations`.
A UNICA integracao com webapp/main.py e o `app.include_router(...)`.

Motor v2 (2026-09-25, reescrito apos avaliacao com 16 perfis-gabarito -- ver
docs/linhas-incentivadas.md, secao "Potenciais Linhas"):

1. REGRAS DURAS excluem (nunca so penalizam): regiao regional que nao cobre a UF,
   porte fora do que a fonte lista, valor fora de [valor_minimo, valor_maximo],
   finalidade incompativel, setor restrito a outro nicho, publico-alvo restrito
   (agricultura familiar/Pronaf, cooperativas, estudante PF, entes publicos/sem
   fins lucrativos). Assim um resultado exibido NUNCA tem contradicao explicita.
2. Cada criterio informado vira um chip: "atende" (fator 0.7-1.0, conforme o quao
   especifico e o match) ou "nao informado pela fonte" (fator fixo 0.4 -- sem
   dado nunca conta a favor como se fosse match). Score = soma(peso*fator)/soma(peso).
3. Rotulo calibrado: >=80 Alta, 60-79 Media, <60 vai pra "Outras opcoes".

Tudo deterministico por regras sobre o TEXTO DA FONTE OFICIAL (porte_elegivel,
setores_elegiveis, regiao_elegivel, descricao_resumida...), nunca IA e nunca dado
inventado -- quando o parser nao reconhece o texto, o criterio fica neutro.
"""
import re
import unicodedata

from fastapi import APIRouter

from db import get_connection

router = APIRouter()

NAO_INFORMADO = "Não informado pela fonte"
NAO_INFORMADO_GRUPO = "Não informado"


def _norm(texto) -> str:
    """minusculo + sem acento, so pra comparacao (nunca dado exibido)."""
    t = "".join(c for c in unicodedata.normalize("NFKD", str(texto or "")) if not unicodedata.combining(c))
    return t.lower()


def _informado(v) -> bool:
    return bool(v) and v not in (NAO_INFORMADO, NAO_INFORMADO_GRUPO)


# ---------------------------------------------------------------- vocabulario do formulario

_ORDEM_PORTE_INPUT = ["MICRO", "PEQUENA", "MÉDIA", "GRANDE"]
_TODOS_PORTES = frozenset(_ORDEM_PORTE_INPUT)
_PORTE_GRUPO_PARA_INPUT = {
    "Todos os portes": _TODOS_PORTES,
    "Micro/Pequena": frozenset({"MICRO", "PEQUENA"}),
    "Média": frozenset({"MÉDIA"}),
    "Grande": frozenset({"GRANDE"}),
}
_PORTE_ROTULO = {"MICRO": "Micro", "PEQUENA": "Pequena", "MÉDIA": "Média", "GRANDE": "Grande"}

# Atividade do projeto: mais granular que as 4 categorias de setor_padronizado
# (sem isso "hospital" e "software" caem ambos em COMERCIO/SERVICOS e o motor nao
# distingue Finem Saude de Finem TI). `setor` = categoria BNDES (pra Transacoes
# Semelhantes e fallback); `termos` = match especifico (nome/setores/descricao);
# `amplos` = match so contra setores_elegiveis (listas multissetoriais tipo
# "Comercio, Turismo, Prestacao de Servicos, Industria").
_ATIVIDADES = [
    {"id": "industria", "rotulo": "Indústria (transformação)", "setor": "INDUSTRIA",
     "termos": ("industr", "manufatur", "fabril", "metalurg", "quimic", "textil", "siderurg"),
     "amplos": ("industr",)},
    {"id": "agroindustria", "rotulo": "Agroindústria", "setor": "AGROPECUÁRIA",
     "termos": ("agroindustr", "armazen", "beneficiamento"),
     "amplos": ("agroindustr", "agronegocio", "agropecuar")},
    {"id": "agro", "rotulo": "Agropecuária / produção rural", "setor": "AGROPECUÁRIA",
     "termos": ("agropecuar", "agricultura", "agricola", "pecuar", "lavoura", "rural", "agronegocio", "graos"),
     "amplos": ("agro", "rural")},
    {"id": "energia", "rotulo": "Energia (geração, transmissão)", "setor": "INFRAESTRUTURA",
     "termos": ("energia eletrica", "geracao de energia", "eolic", "solar", "fotovolt", "renovave", "minigeracao"),
     "amplos": ("infraestrutur", "energia")},
    {"id": "saneamento", "rotulo": "Saneamento / água e esgoto", "setor": "INFRAESTRUTURA",
     "termos": ("saneamento", "agua e esgoto"),
     "amplos": ("infraestrutur",)},
    {"id": "logistica", "rotulo": "Logística, portos e transporte de cargas", "setor": "INFRAESTRUTURA",
     "termos": ("logistic", "rodovi", "ferrovi", "hidrovi", "portuari", "porto", "infraestrutura de transporte", "navegacao", "embarcac"),
     "amplos": ("infraestrutur", "transporte")},
    {"id": "mobilidade", "rotulo": "Mobilidade urbana / transporte de passageiros", "setor": "INFRAESTRUTURA",
     "termos": ("mobilidade urbana", "transporte escolar", "transporte publico"),
     "amplos": ("infraestrutur", "transporte")},
    {"id": "telecom", "rotulo": "Telecomunicações", "setor": "INFRAESTRUTURA",
     "termos": ("telecom", "radio difus", "radiodifus"),
     "amplos": ("infraestrutur",)},
    {"id": "ti", "rotulo": "Tecnologia / software", "setor": "COMERCIO/SERVICOS",
     "termos": ("tecnologia da informacao", "software", "startup", "base tecnologica", "digitaliza"),
     "amplos": ("servic", "tecnolog")},
    {"id": "saude", "rotulo": "Saúde", "setor": "COMERCIO/SERVICOS",
     "termos": ("saude", "hospital"),
     "amplos": ("servic",)},
    {"id": "educacao", "rotulo": "Educação", "setor": "COMERCIO/SERVICOS",
     "termos": ("educacao", "ensino"),
     "amplos": ("servic",)},
    {"id": "comercio", "rotulo": "Comércio / varejo / franquias", "setor": "COMERCIO/SERVICOS",
     "termos": ("comercio", "varejo", "franquia"),
     "amplos": ("comerci",)},
    {"id": "servicos", "rotulo": "Serviços em geral", "setor": "COMERCIO/SERVICOS",
     "termos": ("prestacao de servic",),
     "amplos": ("servic",)},
    {"id": "turismo", "rotulo": "Turismo / hotelaria", "setor": "COMERCIO/SERVICOS",
     "termos": ("turismo", "hotel"),
     "amplos": ("turismo", "servic")},
    {"id": "cultura", "rotulo": "Cultura / economia criativa", "setor": "COMERCIO/SERVICOS",
     "termos": ("cultura", "cultural", "editoria", "audiovisual"),
     "amplos": ("cultura",)},
]
_ATIVIDADE_POR_ID = {a["id"]: a for a in _ATIVIDADES}
# Compatibilidade com links antigos (?setor=INFRAESTRUTURA): categoria -> atividade generica.
_SETOR_PARA_ATIVIDADE = {"INDUSTRIA": "industria", "AGROPECUÁRIA": "agro",
                         "INFRAESTRUTURA": "logistica", "COMERCIO/SERVICOS": "servicos"}

_FINALIDADES = [
    {"id": "investimento", "rotulo": "Investimento / expansão (implantação, obras)"},
    {"id": "maquinas", "rotulo": "Máquinas e equipamentos"},
    {"id": "giro", "rotulo": "Capital de giro / custeio"},
    {"id": "inovacao", "rotulo": "Inovação / P&D"},
    {"id": "sustentabilidade", "rotulo": "Sustentabilidade / eficiência energética"},
]
_FINALIDADE_ROTULO = {f["id"]: f["rotulo"] for f in _FINALIDADES}
# Compatibilidade com o parametro antigo `uso` (valores de destinacao_grupo).
_USO_ANTIGO_PARA_FINALIDADE = {
    "CAPEX / Projetos de investimento": "investimento", "Infraestrutura": "investimento",
    "Máquinas e equipamentos": "maquinas", "Capital de giro": "giro",
    "Inovação / P&D": "inovacao", "Eficiência energética / Sustentabilidade": "sustentabilidade",
}

_TOMADORES = [
    {"id": "empresa", "rotulo": "Empresa privada"},
    {"id": "produtor_rural", "rotulo": "Produtor rural"},
    {"id": "cooperativa", "rotulo": "Cooperativa"},
    {"id": "ente_publico", "rotulo": "Ente público / estatal"},
]

_UFS_BRASIL = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
]
_UF_NOME = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia",
    "CE": "ceara", "DF": "distrito federal", "ES": "espirito santo", "GO": "goias",
    "MA": "maranhao", "MT": "mato grosso", "MS": "mato grosso do sul",
    "MG": "minas gerais", "PA": "para", "PB": "paraiba", "PR": "parana",
    "PE": "pernambuco", "PI": "piaui", "RJ": "rio de janeiro",
    "RN": "rio grande do norte", "RS": "rio grande do sul", "RO": "rondonia",
    "RR": "roraima", "SC": "santa catarina", "SP": "sao paulo", "SE": "sergipe",
    "TO": "tocantins",
}
# Areas oficiais dos fundos regionais (nao inventadas): Amazonia Legal =
# AC/AP/AM/MA/MT/PA/RO/RR/TO; Sudene = Nordeste + norte de MG/ES (tratado no nivel
# de UF, sem recorte intraestadual); Centro-Oeste = DF/GO/MT/MS.
_UFS_NORDESTE = {"AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"}
_UFS_AMAZONIA_LEGAL = {"AC", "AP", "AM", "MA", "MT", "PA", "RO", "RR", "TO"}
_UFS_CENTRO_OESTE = {"DF", "GO", "MT", "MS"}
_UFS_NORTE = {"AC", "AP", "AM", "PA", "RO", "RR", "TO"}
_UFS_SUL = {"PR", "SC", "RS"}
_UFS_SUDESTE = {"SP", "RJ", "MG", "ES"}

_COLS_CANDIDATO = [
    "id", "instituicao", "nome_oficial", "nome_simplificado", "status", "fluxo",
    "descricao_resumida", "setor_padronizado", "setores_elegiveis", "porte_elegivel",
    "porte_grupo", "destinacao_grupo", "criterios_elegibilidade",
    "percentual_financiavel", "taxa_completa", "indexador", "spread",
    "prazo_total", "carencia", "valor_minimo", "valor_maximo",
    "regiao_elegivel", "agente_financeiro", "url_oficial",
]

# Pesos (soma 100 quando tudo informado). Atividade/finalidade pesam mais: sao o
# que mais diferencia uma linha de outra no catalogo.
_PESOS = {"atividade": 35, "finalidade": 25, "porte": 15, "valor": 15, "uf": 10}
FATOR_NAO_INFORMADO = 0.4
LIMIAR_PRINCIPAL = 60
LIMIAR_ALTA = 80


# ---------------------------------------------------------------- parsers do texto da fonte

def _avaliar_regiao_elegivel(regiao_elegivel: str, uf: str) -> str:
    """'nacional' | 'compativel' | 'incompativel' | 'neutro' (texto nao reconhecido
    ou nao informado -- nunca exclui por incerteza de parsing)."""
    if not _informado(regiao_elegivel):
        return "neutro"
    texto = _norm(regiao_elegivel)
    if "nacional" in texto or texto.startswith("brasil"):
        return "nacional"
    if "sao paulo" in texto:
        return "compativel" if uf == "SP" else "incompativel"
    if "regiao norte" in texto:
        return "compativel" if uf in _UFS_NORTE else "incompativel"
    if "sudam" in texto or "amazonia legal" in texto or "desenvolvimento da amazonia" in texto:
        return "compativel" if uf in _UFS_AMAZONIA_LEGAL else "incompativel"
    if "sudene" in texto or "nordeste" in texto:
        cobre = set(_UFS_NORDESTE)
        if "minas gerais" in texto:
            cobre.add("MG")
        if "espirito santo" in texto:
            cobre.add("ES")
        return "compativel" if uf in cobre else "incompativel"
    if "centro-oeste" in texto or "centro oeste" in texto:
        return "compativel" if uf in _UFS_CENTRO_OESTE else "incompativel"
    if re.search(r"\bsul\b", texto) and "sudeste" not in texto:
        return "compativel" if uf in _UFS_SUL else "incompativel"
    if "sudeste" in texto:
        return "compativel" if uf in _UFS_SUDESTE else "incompativel"
    nome_uf = _UF_NOME.get(uf)
    if nome_uf and nome_uf in texto:
        return "compativel"
    return "neutro"


def _rotulo_regiao(regiao_elegivel: str) -> str:
    t = _norm(regiao_elegivel)
    if "sao paulo" in t:
        return "Estado de SP"
    if "sudam" in t or "amazonia" in t or "regiao norte" in t:
        return "Norte/Amazônia"
    if "sudene" in t or "nordeste" in t:
        return "Nordeste/Sudene"
    if "centro-oeste" in t or "centro oeste" in t:
        return "Centro-Oeste"
    return (regiao_elegivel or "")[:40]


def _portes_da_linha(linha: dict):
    """Conjunto de portes (vocabulario do site) que a fonte lista, ou None quando
    nao da pra afirmar nada. Le primeiro o texto livre porte_elegivel (mais rico e
    fiel a fonte que o bucket porte_grupo), depois cai pro bucket."""
    texto = _norm(linha.get("porte_elegivel")) if _informado(linha.get("porte_elegivel")) else ""
    if texto:
        if "todos os portes" in texto:
            return _TODOS_PORTES
        # Vocabulario BNB/Desenvolve SP: "Pequena-media" (receita 4,8-16 mi) e
        # "Media-Grande" de empresa (90-300 mi) sao MEDIA na classificacao BNDES do
        # site; "Medio-Grande Produtor" (Desenvolve Agro) cobre media e grande.
        texto = re.sub(r"pequen[oa][- ]medi[oa]", " MEDIA ", texto)
        texto = re.sub(r"medio[- ]grande", " MEDIA grande ", texto)
        texto = re.sub(r"media[- ]grande", " MEDIA ", texto)
        achados = set()
        if re.search(r"\bmicro|\bmei\b|miniprodutor", texto):
            achados.add("MICRO")
        if re.search(r"\bpequen", texto):
            achados.add("PEQUENA")
        if re.search(r"\bmedi[oa]s?\b|\bMEDIA\b", texto):
            achados.add("MÉDIA")
        if re.search(r"\bgrandes?\b", texto):
            achados.add("GRANDE")
        if achados:
            return frozenset(achados)
    return _PORTE_GRUPO_PARA_INPUT.get(linha.get("porte_grupo"))


_FINALIDADES_POR_GRUPO = {
    "CAPEX / Projetos de investimento": {"investimento": 1.0, "maquinas": 0.8, "sustentabilidade": 0.6},
    "Máquinas e equipamentos": {"maquinas": 1.0, "investimento": 0.7},
    "Capital de giro": {"giro": 1.0},
    "Inovação / P&D": {"inovacao": 1.0},
    "Eficiência energética / Sustentabilidade": {"sustentabilidade": 1.0, "investimento": 0.5, "maquinas": 0.5},
    "Infraestrutura": {"investimento": 1.0, "maquinas": 0.7},
    "Comércio e serviços": {"investimento": 0.9, "maquinas": 0.7, "giro": 0.7},
    "Agropecuário / Rural": {"investimento": 0.9, "maquinas": 0.7, "giro": 0.8},
}
_FINALIDADE_TERMOS = {
    "giro": ("capital de giro", "custeio", " giro", "insumos", "materias-primas", "credito rotativo"),
    "maquinas": ("maquinas", "equipamentos", "bens de capital", "leasing", "arrendamento"),
    "inovacao": ("inovac", "p&d", "pesquisa", "base tecnologica", "startup"),
    "sustentabilidade": ("sustentab", "eficiencia energetica", "ecoeficien", "baixo carbono", "renovave",
                         "verde", "emissao", "clima", "minigeracao", "passivos ambientais"),
    "investimento": ("investimento", "implantacao", "ampliacao", "expansao", "modernizacao", "construcao"),
}


def _finalidades_da_linha(linha: dict) -> dict:
    """{finalidade: fator} que a linha atende, pelo bucket destinacao_grupo +
    termos do nome/descricao resumida (fonte oficial). Vazio = nao informado."""
    fin = dict(_FINALIDADES_POR_GRUPO.get(linha.get("destinacao_grupo"), {}))
    texto = " " + _norm(" ".join(filter(None, [linha.get("nome_oficial"), linha.get("nome_simplificado"),
                                                linha.get("descricao_resumida")])))
    for f, termos in _FINALIDADE_TERMOS.items():
        if any(t in texto for t in termos):
            teto = 1.0 if f != "investimento" else (0.6 if "inovacao" in fin else 0.9)
            fin[f] = max(fin.get(f, 0), teto)
    return fin


_SETORES_GENERICOS = ("capital de giro", "projetos de investimento", "maquinas e equipamentos",
                      "projetos de inovacao", "projetos sustentaveis", "desenvolve mulher",
                      "desenvolve agro")


def _tem(termos, texto) -> bool:
    """Match por INICIO de palavra (evita "industr" casar com "agroindustria")."""
    return any(re.search(r"\b" + re.escape(t), texto) for t in termos)


def _avaliar_atividade(linha: dict, atividade: dict):
    """(fator | None=exclui, motivo). Ordem: match especifico > linha aberta a
    todos os setores > linha de OUTRO nicho (exclui) > lista multissetorial que
    inclui a atividade > nicho nao reconhecido (exclui) > setor_padronizado >
    sem dado (neutro)."""
    setores_txt = _norm(linha.get("setores_elegiveis")) if _informado(linha.get("setores_elegiveis")) else ""
    nome_txt = _norm(" ".join(filter(None, [linha.get("nome_oficial"), linha.get("nome_simplificado")])))
    # "materiais industrializados"/"industrializacao de produtos agro" nao sao linhas PARA a industria.
    nome_txt = nome_txt.replace("industrializ", "")
    texto = " ".join([nome_txt, setores_txt, _norm(linha.get("descricao_resumida"))]).replace("industrializ", "")
    if _tem(atividade["termos"], texto):
        return 1.0, f"Linha voltada a {atividade['rotulo'].split(' (')[0].split(' /')[0].lower()}"
    aberta = ("todos os setores" in setores_txt or "qualquer setor" in setores_txt
              or ("nao rural" in setores_txt and atividade["setor"] != "AGROPECUÁRIA"))
    if aberta:
        return 0.6, "Aberta a todos os setores"
    for outra in _ATIVIDADES:
        if outra["id"] != atividade["id"] and (_tem(outra["termos"], nome_txt) or (
                _tem(outra["termos"], setores_txt) and not _tem(atividade["amplos"], setores_txt))):
            return None, f"Voltada a {outra['rotulo'].split(' (')[0].lower()}"
    if setores_txt and _tem(atividade["amplos"], setores_txt):
        return 0.8, "Setores elegíveis: " + _cortar(linha.get("setores_elegiveis"), 48)
    nicho = setores_txt and not any(g in setores_txt for g in _SETORES_GENERICOS)
    if nicho:
        return None, f"Restrita a: {linha.get('setores_elegiveis')}"
    setor_linha = linha.get("setor_padronizado")
    if _informado(setor_linha):
        if setor_linha == atividade["setor"]:
            return 0.7, "Setor da linha compatível"
        return None, f"Setor da linha: {setor_linha}"
    for outra in _ATIVIDADES:
        if outra["id"] != atividade["id"] and _tem(outra["termos"], texto):
            return None, f"Voltada a {outra['rotulo'].split(' (')[0].lower()}"
    return FATOR_NAO_INFORMADO, "Setores elegíveis não informados pela fonte"


def _avaliar_tomador(linha: dict, tomador: str, porte: str, atividade: dict):
    """(ok: bool, motivo_positivo | motivo_exclusao). Restricoes de publico-alvo
    lidas do texto da fonte (porte_elegivel/setores/criterios)."""
    pub = _norm(" ".join(filter(None, [linha.get("porte_elegivel"), linha.get("setores_elegiveis"),
                                       linha.get("criterios_elegibilidade"), linha.get("nome_oficial")])))
    porte_txt = _norm(linha.get("porte_elegivel")) if _informado(linha.get("porte_elegivel")) else ""
    if "estudante" in pub:
        return False, "Crédito estudantil (pessoa física)"
    if re.search(r"familiar|pronaf|sem terra|minifundi|reforma agraria", pub):
        if tomador in ("produtor_rural", "cooperativa") and porte in (None, "MICRO", "PEQUENA"):
            return True, "Voltada à agricultura familiar"
        return False, "Restrita à agricultura familiar (Pronaf)"
    if porte_txt.strip() == "cooperativas":
        return (True, "Voltada a cooperativas") if tomador == "cooperativa" else (False, "Restrita a cooperativas")
    if "sem fins lucrativos ou publicos" in pub:
        return (True, "Aceita entes públicos") if tomador == "ente_publico" else (False, "Restrita a entes públicos/sem fins lucrativos")
    rural = re.search(r"produtor|agricultor|cafeicultor|cooperativa|associacoes rurais", porte_txt)
    if rural and "empresa" not in porte_txt:
        if tomador in ("produtor_rural", "cooperativa"):
            return True, "Voltada a produtores rurais/cooperativas"
        if tomador == "empresa" and atividade and atividade["setor"] == "AGROPECUÁRIA":
            return True, "Aceita produtor rural pessoa jurídica"
        return False, "Restrita a produtores rurais/cooperativas"
    if tomador == "ente_publico" and re.search(r"direito privado|empresas privadas", pub):
        return False, "Restrita a empresas privadas"
    if tomador in ("produtor_rural", "cooperativa") and atividade and atividade["setor"] != "AGROPECUÁRIA":
        return True, None
    return True, None


def _cortar(texto, n: int) -> str:
    t = str(texto or "").strip()
    if len(t) <= n:
        return t
    c = t[:n].rsplit(" ", 1)[0]
    return c.rstrip(" ,;:.(") + "…"


def _fmt_mi(v: float) -> str:
    if v >= 1e9:
        return f"R$ {v / 1e9:.1f} bi".replace(".0 ", " ").replace(".", ",")
    if v >= 1e6:
        return f"R$ {v / 1e6:.1f} mi".replace(".0 ", " ").replace(".", ",")
    return f"R$ {v / 1e3:.0f} mil"


def _avaliar_linha(linha: dict, perfil: dict):
    """Retorna dict com score/criterios, ou {'excluida': motivo}."""
    atividade = perfil.get("atividade")
    finalidade = perfil.get("finalidade")
    porte = perfil.get("porte")
    volume = perfil.get("volume")
    uf = perfil.get("uf")
    tomador = perfil.get("tomador") or "empresa"

    if linha.get("status") and _norm(linha["status"]) not in ("aberta", "aberto", "ativa", "ativo"):
        return {"excluida": "Linha não está aberta", "cat": "Status"}

    criterios = []  # {chave, status: 'ok'|'na', texto}
    pontos = peso_total = 0.0

    def add(chave, fator, texto):
        nonlocal pontos, peso_total
        peso_total += _PESOS[chave]
        pontos += _PESOS[chave] * fator
        criterios.append({"chave": chave, "status": "ok" if fator > FATOR_NAO_INFORMADO else "na", "texto": texto})

    ok, motivo_tomador = _avaliar_tomador(linha, tomador, porte, atividade)
    if not ok:
        return {"excluida": motivo_tomador, "cat": "Público-alvo"}

    if uf:
        reg = _avaliar_regiao_elegivel(linha.get("regiao_elegivel"), uf)
        if reg == "incompativel":
            return {"excluida": f"Atende só {_rotulo_regiao(linha.get('regiao_elegivel'))}", "cat": "Região"}
        if reg == "nacional":
            add("uf", 1.0, "Abrangência nacional")
        elif reg == "compativel":
            add("uf", 1.0, f"Linha regional que atende {uf} ({_rotulo_regiao(linha.get('regiao_elegivel'))})")
        else:
            add("uf", FATOR_NAO_INFORMADO, "Área de atuação não detalhada pela fonte")

    if porte:
        portes = _portes_da_linha(linha)
        if portes is None:
            add("porte", FATOR_NAO_INFORMADO, "Porte elegível não informado pela fonte")
        elif porte not in portes:
            ordem = [p for p in _ORDEM_PORTE_INPUT if p in portes]
            return {"excluida": "Porte elegível: " + ", ".join(_PORTE_ROTULO[p] for p in ordem), "cat": "Porte"}
        elif portes == _TODOS_PORTES:
            add("porte", 0.9, "Aberta a todos os portes")
        else:
            add("porte", 1.0, f"Aceita porte {_PORTE_ROTULO[porte].lower()}")

    if volume is not None:
        vmin, vmax = linha.get("valor_minimo"), linha.get("valor_maximo")
        if vmin is None and vmax is None:
            add("valor", FATOR_NAO_INFORMADO, "Faixa de valor não informada pela fonte")
        elif vmin is not None and volume < vmin:
            return {"excluida": f"Valor mínimo {_fmt_mi(vmin)}", "cat": "Valor"}
        elif vmax is not None and volume > vmax:
            return {"excluida": f"Valor máximo {_fmt_mi(vmax)}", "cat": "Valor"}
        else:
            faixa = (f"de {_fmt_mi(vmin)} a {_fmt_mi(vmax)}" if vmin and vmax
                     else f"a partir de {_fmt_mi(vmin)}" if vmin else f"até {_fmt_mi(vmax)}")
            add("valor", 1.0, f"Valor dentro da faixa ({faixa})")

    if atividade:
        fator, motivo = _avaliar_atividade(linha, atividade)
        if fator is None:
            return {"excluida": motivo, "cat": "Setor/atividade"}
        add("atividade", fator, motivo)

    if finalidade:
        fins = _finalidades_da_linha(linha)
        if not fins:
            add("finalidade", FATOR_NAO_INFORMADO, "Finalidade não classificada pela fonte")
        elif finalidade not in fins:
            return {"excluida": "Finalidade: " + ", ".join(_FINALIDADE_ROTULO[f].split(" (")[0] for f in fins), "cat": "Finalidade"}
        else:
            fator = fins[finalidade]
            add("finalidade", fator, ("Financia " if fator >= 0.9 else "Pode financiar ")
                + _FINALIDADE_ROTULO[finalidade].split(" (")[0].lower())

    if peso_total == 0:
        return None
    score = 100 * pontos / peso_total
    alertas = []
    if motivo_tomador:
        criterios.insert(0, {"chave": "tomador", "status": "ok", "texto": motivo_tomador})
    nome_norm = _norm(linha.get("nome_oficial"))
    if "mulher" in nome_norm:
        alertas.append("Requisito adicional: empresa liderada/controlada por mulheres")
        score *= 0.85
    if linha.get("fluxo") == "edital":
        alertas.append("Depende de edital/chamada pública aberta")
    score_pct = int(round(score))
    return {"score_pct": score_pct, "criterios": criterios, "alertas": alertas}


def _rotulo_score(score_pct: int) -> str:
    if score_pct >= LIMIAR_ALTA:
        return "Alta"
    if score_pct >= LIMIAR_PRINCIPAL:
        return "Média"
    return "Baixa"


def _perfil_de_parametros(atividade, setor, porte, volume, finalidade, uso, uf, tomador):
    """Normaliza os parametros (inclusive os antigos setor/uso de links ja
    compartilhados) num perfil. Retorna (perfil, erro)."""
    ativ = _ATIVIDADE_POR_ID.get(atividade or "")
    if not ativ and setor and setor != "Todos":
        ativ = _ATIVIDADE_POR_ID.get(_SETOR_PARA_ATIVIDADE.get(setor, ""))
    fin = finalidade if finalidade in _FINALIDADE_ROTULO else _USO_ANTIGO_PARA_FINALIDADE.get(uso or "")
    if not fin and uso:
        # `uso` em texto livre (links/integracoes antigas, ex: "energia solar"):
        # mesmos termos usados pra classificar a finalidade das linhas.
        uso_txt = " " + _norm(uso)
        if any(t in uso_txt for t in ("solar", "renovave", "eolic")):
            fin = "sustentabilidade"
        else:
            fin = next((f for f, termos in _FINALIDADE_TERMOS.items() if any(t in uso_txt for t in termos)), None)
    porte = (porte or "").strip().upper() or None
    if porte == "MEDIA":
        porte = "MÉDIA"
    if porte and porte not in _TODOS_PORTES:
        return None, f"Porte inválido: {porte}"
    uf = (uf or "").strip().upper() or None
    if uf and uf not in _UF_NOME:
        return None, f"UF inválida: {uf}"
    if volume is not None and volume <= 0:
        return None, "Valor deve ser maior que zero"
    tomador = tomador if tomador in {t["id"] for t in _TOMADORES} else "empresa"
    if not any([ativ, fin, porte, volume is not None]):
        return None, "Informe ao menos atividade, finalidade, porte ou valor"
    return {"atividade": ativ, "finalidade": fin, "porte": porte, "volume": volume,
            "uf": uf, "tomador": tomador}, None


def ranquear(candidatos: list, perfil: dict):
    """Puro (sem banco) -- usado pela rota e pela avaliacao offline
    (scripts/avaliar_potenciais.py)."""
    resultados, exclusoes = [], {}
    for linha in candidatos:
        av = _avaliar_linha(linha, perfil)
        if av is None:
            continue
        if "excluida" in av:
            exclusoes[av["cat"]] = exclusoes.get(av["cat"], 0) + 1
            continue
        regional = perfil.get("uf") and _avaliar_regiao_elegivel(linha.get("regiao_elegivel"), perfil["uf"]) == "compativel"
        resultados.append((linha, av, bool(regional)))
    resultados.sort(key=lambda t: (-t[1]["score_pct"], not t[2],
                                   -sum(c["status"] == "ok" for c in t[1]["criterios"]),
                                   t[0].get("nome_simplificado") or t[0].get("nome_oficial") or ""))
    return resultados, exclusoes


# ---------------------------------------------------------------- frequencia historica (desempate)

LIMIAR_SIMILARIDADE_TRGM_HISTORICO = 0.4
_AGENCIAS_COM_OPERACOES_REAIS = ("BNDES", "FINEP", "BNB")


def _computar_frequencia_historica(cur, candidatos: list) -> dict:
    """Conta operacoes reais em `operations` cujo produto/instrumento se parece
    (pg_trgm) com o nome oficial da linha -- so informativo/desempate, nunca
    entra no score. So BNDES/FINEP/BNB (unicas agencias em `operations`)."""
    if not candidatos:
        return {}
    values, params = [], []
    for c in candidatos:
        values.append("(?, ?, ?)")
        params.extend([c["id"], c["instituicao"], c["nome"]])
    query = f"""
        WITH termos AS (
            SELECT agencia, COALESCE(produto, instrumento) AS termo, COUNT(*) AS n
            FROM operations
            WHERE agencia IN ('BNDES', 'FINEP', 'BNB') AND COALESCE(produto, instrumento) IS NOT NULL
            GROUP BY agencia, COALESCE(produto, instrumento)
        ),
        candidatos(id, instituicao, nome) AS (VALUES {", ".join(values)})
        SELECT c.id, SUM(t.n)
        FROM candidatos c
        JOIN termos t
          ON t.agencia = c.instituicao
         AND similarity(unaccent(lower(t.termo)), unaccent(lower(c.nome))) > {LIMIAR_SIMILARIDADE_TRGM_HISTORICO}
        GROUP BY c.id
    """
    return {r[0]: int(r[1]) for r in cur.execute(query, params).fetchall()}


# ---------------------------------------------------------------- rotas

@router.get("/opcoes")
def potenciais_opcoes():
    """Opcoes do formulario. Subsetores (de `operations`) so refinam Transacoes
    Semelhantes."""
    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        subsetores = [r[0] for r in cur.execute(
            "SELECT DISTINCT subsetor_bndes FROM operations WHERE subsetor_bndes IS NOT NULL ORDER BY subsetor_bndes"
        ).fetchall()]
        return {
            "atividades": [{"id": a["id"], "rotulo": a["rotulo"], "setor": a["setor"]} for a in _ATIVIDADES],
            "finalidades": _FINALIDADES,
            "tomadores": _TOMADORES,
            "portes": list(_ORDEM_PORTE_INPUT),
            "ufs": list(_UFS_BRASIL),
            "subsetores": subsetores,
        }
    finally:
        conn.close()


@router.get("/buscar")
def potenciais_buscar(
    atividade: str = None, finalidade: str = None, tomador: str = None,
    porte: str = None, volume: float = None, uf: str = None,
    setor: str = None, uso: str = None, subsetor: str = None,  # compat. links antigos
    limit: int = 20,
):
    limit = max(1, min(limit, 50))
    perfil, erro = _perfil_de_parametros(atividade, setor, porte, volume, finalidade, uso, uf, tomador)
    if erro:
        return {"erro": erro}

    conn = get_connection(pooled=True)
    try:
        cur = conn.cursor()
        rows = cur.execute(f"SELECT {', '.join(_COLS_CANDIDATO)} FROM linhas_incentivadas").fetchall()
        candidatos = [dict(zip(_COLS_CANDIDATO, r)) for r in rows]
        ranqueados, exclusoes = ranquear(candidatos, perfil)

        principais = [t for t in ranqueados if t[1]["score_pct"] >= LIMIAR_PRINCIPAL][:limit]
        outras = [t for t in ranqueados if t[1]["score_pct"] < LIMIAR_PRINCIPAL][:10]

        freq = _computar_frequencia_historica(cur, [
            {"id": l["id"], "instituicao": l["instituicao"], "nome": l["nome_oficial"]}
            for l, _, _ in principais + outras if l["instituicao"] in _AGENCIAS_COM_OPERACOES_REAIS
        ])

        def serializar(t):
            l, av, _ = t
            return {
                "id": l["id"], "instituicao": l["instituicao"],
                "nome": l["nome_simplificado"] or l["nome_oficial"], "nome_oficial": l["nome_oficial"],
                "fluxo": l["fluxo"], "setor_padronizado": l["setor_padronizado"],
                "taxa_completa": l["taxa_completa"], "indexador": l["indexador"], "spread": l["spread"],
                "prazo_total": l["prazo_total"], "carencia": l["carencia"],
                "percentual_financiavel": l["percentual_financiavel"],
                "valor_minimo": l["valor_minimo"], "valor_maximo": l["valor_maximo"],
                "url_oficial": l["url_oficial"],
                "score_pct": av["score_pct"], "score_rotulo": _rotulo_score(av["score_pct"]),
                "criterios": av["criterios"], "alertas": av["alertas"],
                "frequencia_historica": freq.get(l["id"]),
            }

        atividade_obj = perfil["atividade"]
        return {
            "perfil": {
                "atividade": atividade_obj["id"] if atividade_obj else None,
                "setor": atividade_obj["setor"] if atividade_obj else None,
                "finalidade": perfil["finalidade"], "porte": perfil["porte"],
                "volume": perfil["volume"], "uf": perfil["uf"], "tomador": perfil["tomador"],
                "subsetor": subsetor or None,
            },
            "total_candidatos": len(candidatos),
            "total_compativeis": len(ranqueados),
            "resultados": [serializar(t) for t in principais],
            "outras_opcoes": [serializar(t) for t in outras],
            "exclusoes": sorted(({"motivo": k, "n": v} for k, v in exclusoes.items()), key=lambda x: -x["n"])[:8],
        }
    finally:
        conn.close()
