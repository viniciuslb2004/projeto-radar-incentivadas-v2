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
    "BANCOS MULTIPLOS": ["banco", "bancos", "instituicao financeira"],
    "BANCOS DE DESENVOLVIMENTO": ["banco", "bancos", "banco de fomento"],
    "CAIXAS ECONOMICAS": ["caixa economica", "banco"],
    "MICROCREDITO": ["credito popular", "microfinancas", "credito produtivo"],
    "SOCIEDADES DE CREDITO AO MICROEMPREENDEDOR": ["microcredito", "credito popular", "microfinancas"],
    "COOPERATIVA": ["cooperativa de credito", "credito cooperativo", "coop de credito"],
    "CREDITO COOPERATIVO": ["cooperativa de credito", "credito cooperativo"],
    "CORRETORES E AGENTES DE SEGUROS": ["corretora de seguros", "corretor de seguros", "seguradora", "seguros"],
    "FOMENTO MERCANTIL": ["factoring", "fomento mercantil"],
    "AGENCIAS DE FOMENTO": ["banco de fomento", "agencia de fomento", "financeira de desenvolvimento"],
    "OSCIP": ["credito para pequenas empresas", "microcredito"],

    # ---- SAUDE ------------------------------------------------------------
    "ATEND HOSPITALAR": ["hospital", "hospitais", "clinica", "clinicas", "servicos medicos", "saude"],
    "ATIVIDADES DE ATENDIMENTO HOSPITALAR": ["hospital", "hospitais", "clinica", "clinicas", "saude", "pronto-socorro", "pronto socorro"],
    "ATIVIDADES DE ATENCAO A SAUDE": ["hospital", "hospitais", "clinica", "clinicas", "saude", "servicos medicos"],
    "ATENCAO A SAUDE HUMANA": ["hospital", "hospitais", "clinica", "clinicas", "saude", "servicos medicos", "atendimento medico"],
    "ATENDIMENTO EM PRONTO-SOCORRO": ["pronto-socorro", "pronto socorro", "emergencia", "hospital"],
    "PLANOS DE SAUDE": ["plano de saude", "planos de saude", "convenio medico", "seguro saude", "operadora de saude"],
    "LABORATORIOS CLINICOS": ["laboratorio", "laboratorios", "exames laboratoriais", "analises clinicas", "laboratorio de analises"],
    "LABORATORIOS DE ANATOMIA PATOLOGICA": ["laboratorio", "exames", "analises clinicas", "patologia"],
    "FISIOTERAPIA": ["fisioterapia", "clinica de fisioterapia", "fisioterapeuta"],
    "ATIVIDADE ODONTOLOGICA": ["dentista", "clinica odontologica", "odontologia", "consultorio dentario", "odontologico"],
    "ATIVIDADE MEDICA AMBULATORIAL": ["clinica medica", "consultorio medico", "ambulatorio", "clinica"],
    "SAUDE HUMANA": ["clinica", "clinicas", "saude", "atendimento medico"],
    "DIAGNOSTICA E TERAPEUTICA": ["exames", "diagnostico", "clinica de diagnostico", "raio-x", "ressonancia"],
    "RESSONANCIA MAGNETICA": ["exames de imagem", "ressonancia magnetica", "clinica de imagem"],
    "DIAGNOSTICO POR IMAGEM": ["exames de imagem", "raio-x", "tomografia", "clinica de imagem"],
    "HEMOTERAPIA": ["banco de sangue", "hemoterapia"],
    "QUIMIOTERAPIA": ["oncologia", "tratamento de cancer", "quimioterapia"],
    "PROTESE DENTARIA": ["protese dentaria", "laboratorio de protese", "odontologia"],
    "UTI MOVEL": ["ambulancia", "uti movel", "remocao de pacientes"],
    "ASSISTENCIA SOCIAL": ["asilo", "casa de repouso", "lar de idosos", "instituicao de longa permanencia"],
    "ASSIST IDOSO": ["asilo", "casa de repouso", "lar de idosos", "instituicao de longa permanencia"],
    "REPRODUCAO HUMANA ASSISTIDA": ["fertilizacao in vitro", "reproducao assistida", "clinica de fertilidade"],
    "FARMOQUIMICOS": ["farmaceutica", "industria farmaceutica", "principio ativo"],
    "MEDICAMENTOS": ["farmaceutica", "industria farmaceutica", "remedio", "remedios", "laboratorio farmaceutico"],
    "PREPARACOES FARMACEUTICAS": ["farmaceutica", "industria farmaceutica", "remedio"],
    "MEDICAMENTOS FITOTERAPICOS": ["fitoterapico", "farmaceutica", "remedio natural"],
    "PRODUTOS FARMACEUTICOS": ["farmacia", "farmacias", "drogaria", "farmaceutica"],
    "MATERIAIS PARA MEDICINA E ODONTOLOGIA": ["equipamento medico", "equipamento odontologico", "material hospitalar"],
    "INSTRUMENTOS E MATERIAIS P/MEDICO ODONTOLOGICO": ["equipamento medico", "material cirurgico", "instrumental cirurgico"],
    "APARELHOS ELETROMEDICO": ["equipamento medico", "aparelho hospitalar"],
    "ARTIGOS MEDICOS E ORTOPEDICOS": ["produtos ortopedicos", "material medico", "equipamento ortopedico"],
    "ATIVIDADES VETERINARIAS": ["clinica veterinaria", "veterinario", "pet"],

    # ---- ENERGIA (segmento -- complementa SINONIMOS_SUBSETOR) -------------
    "GERACAO DE ENERGIA ELETRICA - SOLAR": ["energia solar", "solar", "fotovoltaica", "geracao distribuida"],
    "GERACAO DE ENERGIA ELETRICA - EOLICA": ["energia eolica", "eolica", "parque eolico", "parques eolicos", "vento"],
    "GERACAO DE ENERGIA ELETRICA - HIDRELETRICA": ["hidreletrica", "hidreletricas", "usina hidreletrica", "usinas hidreletricas", "energia hidraulica"],
    "GERACAO DE ENERGIA ELETRICA - PCH": ["pch", "pequena central hidreletrica", "hidreletrica"],
    "GERACAO DE ENERGIA ELETRICA - TERMICA": ["termeletrica", "usina termica", "termica"],
    "GERACAO DE ENERGIA ELETRICA - CO-GERACAO": ["cogeracao", "biomassa", "bagaco de cana"],
    "GERACAO DE ENERGIA ELETRICA - NUCLEAR": ["usina nuclear", "energia nuclear", "nuclear"],
    "GERACAO DE ENERGIA ELETRICA - OUTRAS FONTES ALTERNAT": ["energia renovavel", "fonte alternativa"],
    "DISTRIBUICAO DE ENERGIA ELETRICA": ["distribuidora de energia", "concessionaria de energia", "energia eletrica"],
    "TRANSMISSAO DE ENERGIA ELETRICA": ["transmissora de energia", "linha de transmissao", "energia eletrica"],
    "DISTRIBUICAO DE COMBUSTIVEIS GASOSOS": ["gas encanado", "gas de rua", "distribuidora de gas", "gas natural"],
    "PRODUCAO DE GAS": ["gas natural", "processamento de gas", "distribuidora de gas"],

    # ---- TECNOLOGIA / SOFTWARE ---------------------------------------------
    # NOTA (limitacao conhecida): a granularidade do CNAE nao distingue um
    # segmento de software por NICHO (RH, financeiro, saude etc.) -- todo
    # software sob encomenda/licenciado cai nestes MESMOS poucos segmentos.
    # Por isso os sinonimos de nicho abaixo (rh, erp, crm...) aumentam RECALL
    # mas nao PRECISAO: uma busca por "sistema de rh" vai trazer qualquer
    # empresa de software, nao so as de RH especificamente.
    "COMPUTADOR": ["software", "softwares", "saas", "tecnologia", "ti", "desenvolvimento de sistemas",
                   "sistema de rh", "recursos humanos", "folha de pagamento", "gestao de pessoas",
                   "erp", "crm", "software de gestao", "sistema de gestao", "aplicativo", "app"],
    "REPRODUCAO DE SOFTWARE": ["software", "softwares", "licenciamento de software"],
    "CONSULTORIA EM TECNOLOGIA DA INFORMACAO": ["consultoria de ti", "consultoria em ti", "ti", "tecnologia"],
    "SUPORTE TECNICO": ["ti", "tecnologia da informacao", "suporte de ti"],
    "PROVEDORES DE ACESSO": ["internet", "provedor de internet", "provedores de internet", "banda larga", "conectividade"],
    "SERVICOS DE COMUNICACAO MULTIMIDIA": ["telecom", "internet", "banda larga"],
    "TELEFONIA MOVEL CELULAR": ["celular", "telefonia movel", "operadora de celular"],
    "SERVICOS DE TELEFONIA FIXA COMUTADA": ["telefonia fixa", "telefone fixo"],
    "TELECOMUNICACOES POR FIO": ["telecom", "banda larga", "internet fixa"],
    "TELECOMUNICACOES SEM FIO": ["telecom", "internet movel", "banda larga movel"],
    "TRATAMENTO DE DADOS": ["hospedagem na internet", "data center", "cloud", "computacao em nuvem", "e-commerce"],
    "PROVEDORES DE SERVICOS DE APLICACAO": ["saas", "hospedagem na internet", "data center", "cloud"],
    "PORTAIS, PROVEDORES DE CONTEUDO": ["portal", "site de conteudo", "midia digital", "e-commerce"],
    "EQUIPAMENTOS DE INFORMATICA": ["hardware", "computadores", "fabricante de computadores", "equipamento de informatica"],
    "PERIFERICOS PARA EQUIPAMENTOS DE INFORMATICA": ["hardware", "periferico de computador"],
    "COMPONENTES ELETRONICOS": ["eletronicos", "componente eletronico", "semicondutor"],
    "GESTAO DE ATIVOS INTANGIVEIS": ["propriedade intelectual", "royalties", "marcas e patentes"],
    "FORNECIMENTO E GESTAO DE RECURSOS HUMANOS PARA TERCEIROS": ["rh", "recursos humanos", "terceirizacao de rh", "folha de pagamento", "gestao de pessoas"],
    "SELECAO E AGENCIAMENTO DE MAO-DE-OBRA": ["recrutamento", "selecao de pessoal", "rh", "recursos humanos", "headhunter"],
    "LOCACAO DE MAO-DE-OBRA TEMPORARIA": ["trabalho temporario", "terceirizacao de mao de obra", "rh"],

    # ---- ALIMENTOS E BEBIDAS ------------------------------------------------
    "REFRIGERANTE": ["refrigerante", "refrigerantes", "soda", "guarana", "bebida gaseificada"],
    "LATICINIO": ["laticinio", "laticinios", "leite", "queijo", "iogurte", "manteiga", "leiteria"],
    "PREPARACAO DO LEITE": ["leite", "laticinio", "usina de beneficiamento de leite"],
    "FRIGORIFICO": ["frigorifico", "abatedouro", "matadouro", "carne", "industria de carnes"],
    "ABATE": ["frigorifico", "abatedouro", "matadouro"],
    "ABATE DE AVES": ["frango", "frangos", "avicultura", "abatedouro de frango", "abatedouro de aves"],
    "CRIACAO DE FRANGOS PARA CORTE": ["frango", "avicultura", "granja de frango"],
    "ABATE DE RESES": ["boi", "bovino", "gado", "abatedouro de boi", "abatedouro de gado"],
    "ABATE DE SUINOS": ["porco", "suino", "suinos", "abatedouro de porco", "suinocultura"],
    "PRODUTOS DE CARNE": ["carne", "embutidos", "linguica", "salsicha", "charque", "presunto"],
    "PRESERVACAO DE PEIXES": ["peixe", "pescado", "conserva de peixe"],
    "PRESERVACAO DO PESCADO": ["peixe", "pescado", "conserva de pescado"],
    "MALTE": ["cerveja", "cervejaria", "chope", "bebida alcoolica"],
    "CERVEJAS E CHOPES": ["cerveja", "cervejaria", "chope", "bebida alcoolica"],
    "FABRICACAO DE VINHO": ["vinho", "vinicola", "vinhedo", "vinicultura"],
    "AGUARDENTE": ["cachaca", "aguardente", "destilaria", "bebida destilada"],
    "FABRICACAO DE ALCOOL": ["etanol", "alcool combustivel", "usina de etanol", "destilaria de alcool"],
    "TORREFACAO E MOAGEM DE CAFE": ["cafe", "torrefadora", "torrefacao de cafe"],
    "PRODUTOS A BASE DE CAFE": ["cafe", "cafe soluvel", "torrefadora"],
    "PRODUTOS DE PANIFICACAO": ["padaria", "panificadora", "pao", "panificacao"],
    "PADARIA E CONFEITARIA": ["padaria", "confeitaria", "pao", "doces"],
    "MASSAS ALIMENTICIAS": ["massa", "massas", "macarrao"],
    "BISCOITOS E BOLACHAS": ["biscoito", "biscoitos", "bolacha", "bolachas"],
    "DERIVADOS DO CACAU": ["chocolate", "chocolates", "confeitos", "doces", "bombom"],
    "SUCOS DE FRUTAS": ["suco", "sucos", "suco natural", "suco concentrado"],
    "OLEOS VEGETAIS": ["oleo de soja", "oleo vegetal", "oleo de cozinha"],
    "OLEO DE MILHO": ["oleo de milho", "oleo vegetal"],
    "MOAGEM DE TRIGO": ["moinho", "moagem de trigo", "farinha de trigo"],
    "FARINHA DE MANDIOCA": ["farinha de mandioca", "fecularia", "casa de farinha"],
    "AMIDOS E FECULAS": ["amido", "fecula", "fecularia"],
    "AGUAS ENVASADAS": ["agua mineral", "agua engarrafada", "agua de mesa"],
    "SORVETES": ["sorvete", "sorvetes", "sorveteria", "gelados comestiveis", "picole"],
    "ALIMENTOS PARA ANIMAIS": ["racao", "racoes", "racao animal", "racao pet", "petfood", "nutricao animal"],
    "ACUCAR": ["acucar", "usina de acucar", "refinaria de acucar", "acucar refinado"],
    "BENEFICIAMENTO DE ARROZ": ["arroz", "beneficiadora de arroz"],
    "CEREAIS E LEGUMINOSAS": ["cereais", "graos", "leguminosas"],
    "CONSERVAS DE FRUTAS": ["conserva de frutas", "compota"],
    "CONSERVAS DE LEGUMES": ["conserva de legumes", "conserva de vegetais"],
    "ESPECIARIAS, MOLHOS, TEMPEROS": ["tempero", "condimento", "molho"],
    "ALIMENTOS DIETETICOS": ["alimento dietetico", "suplemento alimentar", "produto fit"],
    "ALIMENTOS E PRATOS PRONTOS": ["comida pronta", "refeicao pronta", "prato pronto"],
    "RESTAURANTES E SIMILARES": ["restaurante", "restaurantes"],
    "LANCHONETES": ["lanchonete", "lanchonetes", "casa de sucos"],
    "FORNECIMENTO ALIMENTO PREPARADO": ["catering", "refeicao coletiva", "alimentacao coletiva"],

    # ---- VAREJO --------------------------------------------------------------
    "SUPERMERCADO": ["supermercado", "supermercados", "mercado"],
    "HIPERMERCADO": ["hipermercado", "hipermercados", "mercado"],
    "MINIMERCADO": ["minimercado", "mercearia", "vendinha", "quitanda"],
    "MERC GERAL, SEM PREDOMINANCIA DE PRODUTOS ALIMENTICIOS": ["loja de variedades", "comercio varejista de mercadorias em geral"],
    "LOJAS DE DEPARTAMENTOS": ["loja de departamentos", "magazine"],
    "ARTIGOS DO VESTUARIO": ["loja de roupa", "loja de roupas", "roupas", "confeccao", "boutique", "vestuario"],
    "CONFECCAO": ["confeccao", "roupas", "fabrica de roupa"],
    "COMBUSTIVEIS PARA VEICULOS AUTOMOTORES": ["posto de gasolina", "posto de combustivel", "posto de combustiveis", "posto de abastecimento"],
    "GAS LIQUEFEITO DE PETROLEO": ["gas de cozinha", "botijao de gas", "revenda de gas", "glp"],
    "COMERCIO A VAREJO DE AUTOMOVEIS": ["concessionaria", "revenda de carros", "revenda de veiculos", "loja de carros"],
    "COMERCIO DE PECAS E ACESSORIOS PARA VEICULOS": ["autopecas", "loja de autopecas"],
    "COMERCIO VAREJISTA DE MOVEIS": ["loja de moveis", "moveis", "movelaria"],
    "COSMETICOS, PRODUTOS DE PERFUMARIA": ["perfumaria", "cosmeticos", "produtos de beleza"],
    "COMERCIO VAREJISTA DE LIVROS": ["livraria", "livrarias"],
    "ARTIGOS ESPORTIVOS": ["loja de artigos esportivos", "artigos esportivos"],
    "MATERIAIS DE CONSTRUCAO": ["loja de material de construcao", "casa de construcao", "deposito de material de construcao"],
    "ELETRODOMESTICOS E EQUIP DE AUDIO E VIDEO": ["loja de eletrodomesticos", "eletrodomesticos", "linha branca"],
    "EQUIPAMENTOS SUPRIMENTOS INFORMATICA": ["loja de informatica", "loja de computador"],
    "BRINQUEDOS E ARTIGOS RECREATIVOS": ["loja de brinquedos", "brinquedos"],
    "ARTIGOS DE OPTICA": ["otica", "oticas", "loja de oculos"],
    "MATERIAL ELETRICO": ["loja de material eletrico", "material eletrico"],
    "FERRAGENS E FERRAMENTAS": ["loja de ferragens", "ferragens", "ferramentas"],
    "CARNES - ACOUGUES": ["acougue", "acougues"],
    "BEBIDAS": ["loja de bebidas", "deposito de bebidas", "adega"],

    # ---- LAZER / ENTRETENIMENTO -----------------------------------------------
    "PARQUES DE DIVERSAO": ["parque de diversao", "parque de diversoes", "parque tematico", "parques tematicos"],
    "EXIBICAO CINEMATOGRAFICA": ["cinema", "cinemas", "sala de cinema"],
    "ESTUDIOS CINEMATOGRAFICOS": ["estudio de cinema", "produtora de filmes"],
    "HOTEIS": ["hotel", "hoteis", "pousada", "hospedagem", "hotelaria"],
    "OUTROS TIPOS DE ALOJAMENTO": ["pousada", "hospedagem", "hostel", "hotelaria"],
    "GESTAO DE INSTALACOES DE ESPORTES": ["academia", "academias", "clube esportivo", "ginasio", "centro esportivo"],
    "CLUBES SOCIAIS": ["clube", "clube social", "clube recreativo"],
    "EQUIPAMENTOS RECREATIVOS": ["brinquedos", "recreacao", "aluguel de brinquedos"],
    "AGENCIAS DE VIAGENS": ["agencia de viagem", "agencia de viagens", "viagens"],
    "OPERADORES TURISTICOS": ["turismo", "operadora de turismo", "agencia de turismo"],
    "SERVICOS DE TURISMO": ["turismo", "agencia de turismo"],
    "PRODUCAO MUSICAL": ["musica", "gravadora", "selo musical", "producao de musica"],
    "ARTES CENICAS": ["teatro", "espetaculo", "espetaculos", "companhia teatral"],
    "PRODUCAO TEATRAL": ["teatro", "peca de teatro", "espetaculo"],
    "PARQUES NACIONAIS, RESERVA ECOLOGICA": ["parque ecologico", "reserva ambiental", "zoologico", "jardim botanico"],
    "ATIVIDADES ARTISTICAS": ["arte", "artistica", "cultura"],
    "ORGANIZACAO DE FEIRAS, CONGRESSOS": ["feira", "congresso", "evento", "organizadora de eventos"],
    "ORGANIZACAO DE EVENTOS": ["evento", "eventos", "organizadora de eventos", "buffet de festa"],

    # ---- EDUCACAO --------------------------------------------------------------
    "EDUCACAO INFANTIL": ["escola", "creche", "educacao infantil", "ensino infantil"],
    "ENSINO FUNDAMENTAL": ["escola", "colegio", "ensino fundamental"],
    "ENSINO MEDIO": ["escola", "colegio", "ensino medio"],
    "EDUCACAO SUPERIOR": ["faculdade", "universidade", "ensino superior", "graduacao"],
    "EDUCACAO PROFISSIONAL DE NIVEL TECNICO": ["curso tecnico", "escola tecnica", "ensino tecnico"],
    "CURSOS PREPARATORIOS PARA CONCURSOS": ["cursinho", "curso preparatorio", "preparatorio para concurso"],
    "TREINAMENTO EM DESENVOLVIMENTO PROFISSIONAL": ["treinamento corporativo", "curso profissionalizante"],
    "TREINAMENTO EM INFORMATICA": ["curso de informatica", "escola de informatica"],
    "ATIVIDADES DE APOIO A EDUCACAO": ["apoio escolar", "material didatico", "transporte escolar"],
    "ENSINO DE ARTE E CULTURA": ["escola de arte", "curso de arte", "curso de musica"],
    "ENSINO DE ESPORTES": ["escola de esportes", "curso esportivo"],
    "ENSINO DE DANCA": ["escola de danca", "curso de danca"],
    "ENSINO DE MUSICA": ["escola de musica", "curso de musica"],
    "BIBLIOTECAS E ARQUIVOS": ["biblioteca", "bibliotecas"],

    # ---- CONSTRUCAO / IMOBILIARIO --------------------------------------------
    "CONSTRUCAO DE EDIFICIOS": ["construtora", "construcao civil", "edificacao", "empreiteira"],
    "INCORPORACAO DE EMPREENDIMENTOS IMOBILIARIOS": ["incorporadora", "incorporacao imobiliaria"],
    "PROPRIEDADE IMOBILIARIA": ["imobiliaria", "administradora de imoveis"],
    "LOTEAMENTO DE IMOVEIS": ["loteadora", "loteamento", "loteamento de terrenos"],
    "ALUGUEL DE IMOVEIS PROPRIOS": ["locacao de imoveis", "aluguel de imoveis"],
    "CONSTRUCAO DE RODOVIAS E FERROVIAS": ["rodovia", "obra rodoviaria", "obra viaria"],
    "OBRAS DE URBANIZACAO": ["urbanizacao", "obra de infraestrutura urbana"],
    "OBRAS DE TERRAPLENAGEM": ["terraplenagem", "movimento de terra"],
    "SERVICOS ESPECIALIZADOS PARA CONSTRUCAO": ["servico de construcao", "empreiteira"],
    "SERVICOS DE ENGENHARIA": ["engenharia", "escritorio de engenharia"],
    "SERVICOS DE ARQUITETURA": ["arquitetura", "escritorio de arquitetura"],
    "OBRAS-DE-ARTE ESPECIAIS": ["ponte", "viaduto", "obra de arte especial"],
    "OBRAS PORTUARIAS": ["obra portuaria", "porto"],

    # ---- INDUSTRIA --------------------------------------------------------------
    "SIDERURGIA": ["siderurgica", "siderurgia", "usina siderurgica", "aco", "industria do aco"],
    "METALURGIA": ["metalurgica", "metalurgia"],
    "FUNDICAO": ["fundicao", "fundicao de metal"],
    "TECELAGEM": ["tecelagem", "tear", "tecido", "tecidos"],
    "FIACAO": ["fiacao", "fiacao de algodao", "fio"],
    "TEXTIL": ["textil", "confeccao", "vestuario", "tecido"],
    "EMBALAGENS DE MATERIAL PLASTICO": ["embalagem plastica", "embalagens plasticas", "plastico"],
    "ARTEFATOS DE MATERIAL PLASTICO": ["plastico", "produtos plasticos", "artefatos plasticos"],
    "MINERIO": ["mineradora", "mineracao", "mina", "extracao mineral"],
    "EXTRACAO DE CARVAO MINERAL": ["mineradora", "mineracao de carvao", "mina de carvao"],
    "EXTRACAO DE PEDRA, AREIA E ARGILA": ["pedreira", "extracao de areia", "britagem"],
    "CELULOSE": ["celulose", "fabrica de celulose", "pasta de celulose"],
    "FABRICACAO DE PAPEL": ["papel", "fabrica de papel", "industria de papel"],
    "PAPELAO ONDULADO": ["papelao", "caixa de papelao", "embalagem de papelao"],
    "AUTOMOVEIS, CAMIONETAS E UTILITARIOS": ["montadora", "fabrica de carros", "industria automobilistica", "automotivo"],
    "CAMINHOES E ONIBUS": ["montadora de caminhoes", "montadora de onibus", "industria automobilistica"],
    "PECAS E ACESSORIOS PARA VEICULOS AUTOMOTORES": ["autopecas", "peca automotiva", "fabricante de autopecas"],
    "SISTEMA MOTOR DE VEICULOS AUTOMOTORES": ["autopecas", "motor automotivo"],
    "CURTIMENTO": ["curtume", "couro", "curtimento de couro"],
    "CALCADOS": ["calcado", "calcados", "fabrica de sapatos", "sapataria"],
    "CIMENTO": ["cimento", "fabrica de cimento"],
    "AZULEJOS E PISOS": ["azulejo", "piso ceramico", "revestimento ceramico"],
    "VIDRO": ["vidro", "vidraria", "vidracaria"],
    "MOVEIS": ["moveis", "movelaria", "fabrica de moveis"],
    "MAQUINAS E EQUIPAMENTOS": ["maquinas", "equipamentos industriais", "bens de capital"],
    "TRATORES AGRICOLAS": ["trator", "tratores", "maquina agricola"],
    "FERTILIZANTES": ["fertilizante", "adubo", "adubos"],
    "DEFENSIVOS AGRICOLAS": ["defensivo agricola", "agrotoxico", "pesticida"],
    "TINTAS, VERNIZES": ["tinta", "tintas", "verniz"],
    "COSMETICOS, PRODUTOS DE PERFUMARIA E DE HIGIENE PESSOAL": ["cosmeticos", "perfumaria", "produtos de higiene", "industria de cosmeticos"],
    "SABOES E DETERGENTES": ["sabao", "detergente", "produto de limpeza"],
    "AERONAVES": ["aeronave", "fabrica de avioes", "industria aeronautica"],
    "EMBARCACOES": ["embarcacao", "estaleiro", "construcao naval"],

    # ---- TRANSPORTE E LOGISTICA -----------------------------------------------
    "NAVEGACAO DE APOIO MARITIMO": ["apoio maritimo", "offshore", "navegacao offshore"],
    "NAVEGACAO DE APOIO PORTUARIO": ["apoio portuario", "offshore portuario"],
    "TRANSPORTE FERROVIARIO DE CARGA": ["ferrovia", "trem de carga", "transporte ferroviario"],
    "ARMAZENS GERAIS": ["armazem geral", "warrant", "armazenagem"],
    "ARMAZENAMENTO": ["armazenagem", "armazem", "centro de distribuicao"],
    "DEPOSITO MERCADORIA": ["deposito", "armazenagem", "guarda-moveis"],
    "ORGANIZACAO LOGISTICA DO TRANSPORTE DE CARGA": ["logistica", "operador logistico"],
    "TERMINAIS RODOVIARIOS": ["terminal rodoviario", "rodoviaria"],
    "OPERACAO DOS AEROPORTOS": ["aeroporto", "aeroportos"],
    "CONCESSIONARIAS RODOVIAS, PONTES, TUNEIS": ["concessionaria de rodovia", "pedagio", "rodovia"],
    "TRANSPORTE RODOVIARIO DE CARGA": ["transportadora", "transporte de carga", "frete"],
    "TRANSPORTE RODOVIARIO DE PRODUTOS PERIGOSOS": ["transporte de produtos perigosos", "transportadora"],
    "TRANSPORTE RODOV COL PASSAG": ["transporte de passageiros", "onibus", "empresa de onibus"],
    "TRANSP RODOV COL PASSAG": ["transporte de passageiros", "onibus", "empresa de onibus"],
    "TRANSPORTE METROVIARIO": ["metro", "metrô", "transporte metroviario"],
    "TRANSPORTE MARITIMO": ["navegacao", "transporte maritimo", "cabotagem"],
    "TRANSPORTE AEREO": ["transporte aereo", "companhia aerea", "aviacao"],
    "TRANSPORTE DUTOVIARIO": ["duto", "gasoduto", "oleoduto"],
    "GESTAO DE PORTOS E TERMINAIS": ["porto", "terminal portuario"],
    "ATIVIDADES DO OPERADOR PORTUARIO": ["porto", "operador portuario"],

    # ---- AGROPECUARIA -----------------------------------------------------------
    "CANA-DE-ACUCAR": ["cana de acucar", "canavial", "usina de cana", "canavieiro"],
    "CULTIVO DE MILHO": ["milho", "lavoura de milho"],
    "CULTIVO DE SOJA": ["soja", "lavoura de soja"],
    "CULTIVO DE CAFE": ["cafe", "cafeicultura", "lavoura de cafe"],
    "CULTIVO DE CEREAIS": ["cereal", "cereais", "graos"],
    "CRIACAO DE AVES": ["avicultura", "granja de frango", "criacao de galinha"],
    "CRIACAO DE BOVINOS": ["pecuaria", "gado", "boi", "bovino", "criacao de gado"],
    "CRIACAO DE SUINOS": ["suinocultura", "criacao de porco", "porco"],
    "CRIACAO DE EQUINOS": ["cavalo", "haras", "criacao de cavalo"],
    "PRODUCAO FLORESTAL": ["silvicultura", "floresta plantada", "reflorestamento"],
    "CONSERVACAO DE FLORESTAS NATIVAS": ["preservacao ambiental", "floresta nativa"],
    "AQUICULTURA": ["piscicultura", "criacao de peixe", "aquicultura"],
    "CRIACAO DE PEIXES": ["piscicultura", "criacao de peixe"],
    "APICULTURA": ["abelha", "mel", "apicultura"],
    "CULTIVO DE FUMO": ["fumo", "tabaco", "fumicultura"],

    # ---- SANEAMENTO / MEIO AMBIENTE ----------------------------------------------
    "CAPTACAO, TRATAMENTO E DISTRIBUICAO DE AGUA": ["saneamento", "agua e esgoto", "abastecimento de agua", "tratamento de agua"],
    "REDE ABAST AGUA COLETA ESGOTO": ["saneamento", "rede de esgoto", "obra de saneamento", "abastecimento de agua"],
    "GESTAO DE REDES DE ESGOTO": ["esgoto", "saneamento", "tratamento de esgoto"],
    "ATIVIDADES RELACIONADAS A ESGOTO": ["esgoto", "saneamento", "tratamento de esgoto"],
    "COLETA, TRATAMENTO E DISPOSICAO DE RESIDUOS": ["lixo", "coleta de lixo", "residuos", "reciclagem", "aterro sanitario"],
    "COLETA DE RESIDUOS": ["coleta de lixo", "residuos", "lixo"],
    "TRATAMENTO E DISPOSICAO DE RESIDUOS": ["tratamento de lixo", "aterro sanitario", "residuos"],
    "USINAS DE COMPOSTAGEM": ["compostagem", "reciclagem organica"],
    "RECUPERACAO DE MATERIAIS": ["reciclagem", "sucata", "materiais reciclaveis"],
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


def segmentos_sem_sinonimo(top_n: int = 20) -> list:
    """Segmentos (CNAE) SEM nenhum sinonimo curado em SINONIMOS_SEGMENTO, ordenados por
    quantas operacoes eles representam -- pra saber ONDE curar sinonimo novo traria mais
    impacto pra busca (cobertura hoje e curada, nao exaustiva, ver docstring do modulo).
    So sinaliza, nunca inventa/adiciona termo sozinho -- decisao de produto e nunca
    inventar valor/sinonimo nao verificado, ver CLAUDE.md."""
    from db import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT segmento, COUNT(*) FROM operations "
            "WHERE segmento IS NOT NULL AND segmento <> '' "
            "GROUP BY segmento ORDER BY COUNT(*) DESC"
        ).fetchall()
    finally:
        conn.close()

    sem_sinonimo = []
    for segmento, n_operacoes in rows:
        seg_norm = normalizar(segmento)
        if not any(chave in seg_norm for chave in SINONIMOS_SEGMENTO):
            sem_sinonimo.append({"segmento": segmento, "n_operacoes": n_operacoes})
    return sem_sinonimo[:top_n]
