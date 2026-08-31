"""Elegibilidade: o usuario digita o CNPJ da PROPRIA empresa (nao um CNPJ que ja esta
na base BNDES/FINEP) e o sistema resolve setor/porte/UF via BrasilAPI (consulta ao vivo,
gratuita, sem chave) para cruzar com editais abertos e o historico de operacoes por setor.

Diferente de enrich_cnae.py (que resolve CNAE via Dados Abertos da RFB para os CNPJs que
JA aparecem nas operacoes da FINEP, em lote, e guarda em cache na tabela cnpj_cnae), aqui
o CNPJ e sempre novo para o sistema (e do visitante, nao de uma operacao ja registrada) --
por isso a consulta e sempre ao vivo, uma linha por vez, sem tabela de cache: bem mais
barato que os jobs em lote da RFB e nao faz sentido guardar dado de terceiro que so o
proprio dono verificou."""
import re

import requests

from sector_taxonomy import build_divisao_map

BRASILAPI_CNPJ_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
TIMEOUT_S = 10

# BrasilAPI repete a nomenclatura da Receita Federal para porte ("MICRO EMPRESA",
# "EMPRESA DE PEQUENO PORTE", "DEMAIS"), que nao bate 1:1 com as categorias que o
# BNDES usa em operations.porte_cliente ("MICRO", "PEQUENA", "MEDIA", "GRANDE").
# "DEMAIS" cobre de media a grande porte na Receita Federal -- nao da pra inferir com
# seguranca qual das duas, entao fica sem equivalente (None) em vez de arriscar um
# chute errado no comparativo de operacoes historicas.
PORTE_RECEITA_PARA_BNDES = {
    "MICRO EMPRESA": "MICRO",
    "EMPRESA DE PEQUENO PORTE": "PEQUENA",
}


def _limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def resolver_empresa(cnpj: str) -> dict:
    """Consulta a BrasilAPI para o CNPJ informado. Mensagens de erro em portugues claro,
    sem jargao nem texto de excecao cru -- quem usa esta pagina e um dono de empresa, nao
    um dev, e a mensagem vai direto pro frontend (ver /api/elegibilidade em webapp/main.py,
    que so loga como bug de verdade os erros INESPERADOS, nao estes aqui)."""
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return {"erro": "CNPJ inválido. Digite os 14 números do CNPJ (com ou sem pontuação)."}

    try:
        resp = requests.get(BRASILAPI_CNPJ_URL.format(cnpj=cnpj_limpo), timeout=TIMEOUT_S)
    except requests.exceptions.RequestException:
        return {"erro": "Não foi possível consultar os dados da empresa agora (serviço de CNPJ fora do ar). Tente novamente em alguns instantes."}

    if resp.status_code == 404:
        return {"erro": "CNPJ não encontrado na Receita Federal. Confira se o número foi digitado corretamente."}
    if not resp.ok:
        return {"erro": "Não foi possível consultar os dados da empresa agora (serviço de CNPJ indisponível). Tente novamente em alguns instantes."}

    try:
        dados = resp.json()
    except ValueError:
        return {"erro": "Resposta inesperada do serviço de consulta de CNPJ. Tente novamente em alguns instantes."}

    # cnae_fiscal vem como NUMERO no JSON da BrasilAPI (ex: 600001) -- o codigo real
    # (CNAE Fiscal) tem sempre 7 digitos (0600-0/01 -> "0600001"); zeros a esquerda
    # somem na conversao pra numero, o que da errado justamente nas divisoes 01-09
    # (agropecuaria, extrativa) -- sem o zfill(7), '0600001' vira '600001' e os 2
    # primeiros digitos (a "divisao" usada por mapear_setor) leriam '60' em vez de
    # '06', mapeando pro setor ERRADO (ver bug real encontrado testando com o CNAE da
    # Petrobras, que classificava como COMERCIO/SERVICOS em vez de industria/extrativa).
    cnae_codigo = dados.get("cnae_fiscal")
    situacao = (dados.get("descricao_situacao_cadastral") or "").strip()

    return {
        "cnpj": cnpj_limpo,
        "razao_social": dados.get("razao_social"),
        "nome_fantasia": dados.get("nome_fantasia"),
        "uf": dados.get("uf"),
        "municipio": dados.get("municipio"),
        "cnae_codigo": str(cnae_codigo).zfill(7) if cnae_codigo else None,
        "cnae_descricao": dados.get("cnae_fiscal_descricao"),
        "porte_receita": dados.get("porte"),
        "situacao_cadastral": situacao or None,
        "situacao_cadastral_alerta": bool(situacao) and situacao.upper() != "ATIVA",
    }


def mapear_setor(conn, cnae_codigo: str) -> dict:
    """Mesma logica de de-para CNAE -> Setor/Subsetor BNDES usada em enrich_cnae.py
    (ver sector_taxonomy.build_divisao_map), aplicada a um CNAE resolvido ao vivo em vez
    de vir do cache cnpj_cnae (que so cobre CNPJs ja vistos em operacoes da FINEP)."""
    cnae_str = str(cnae_codigo) if cnae_codigo else ""
    if len(cnae_str) < 2 or not cnae_str[:2].isdigit():
        return {"setor_bndes": None, "subsetor_bndes": None, "mapeado": False}
    divisao = int(cnae_str[:2])
    setor, subsetor = build_divisao_map(conn).get(divisao, (None, None))
    return {"setor_bndes": setor, "subsetor_bndes": subsetor, "mapeado": setor is not None}


def porte_bndes_equivalente(porte_receita: str):
    """None quando a BrasilAPI nao informou porte, ou quando informou ('DEMAIS') mas nao
    da pra saber se equivale a MEDIA ou GRANDE no vocabulario do BNDES -- ver comentario
    em PORTE_RECEITA_PARA_BNDES acima. Chamador deve tratar None como 'nao filtrar por
    porte', nunca como 'porte desconhecido = MICRO' ou qualquer outro chute."""
    if not porte_receita:
        return None
    return PORTE_RECEITA_PARA_BNDES.get(porte_receita.strip().upper())
