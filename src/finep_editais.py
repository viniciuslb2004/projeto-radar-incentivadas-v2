"""Busca e normaliza as chamadas publicas (editais) abertas da FINEP.

Fonte: API JSON publica do site institucional da FINEP (Liferay headless), a mesma
que alimenta https://www.finep.gov.br/oportunidades. Nao e scraping de HTML -- e uma
API estruturada. IMPORTANTE: usar requests.Response.content (bytes crus) + decode
explicito UTF-8 antes de json.loads, em vez de resp.json() -- o metodo automatico do
requests as vezes adivinha a codificacao errado quando o header nao traz um charset
explicito, o que gera mojibake mesmo o corpo sendo UTF-8 valido.
"""
import datetime
import json
import re

import requests

from db import get_connection
import editais_documentos

API_URL = "https://www.finep.gov.br/o/c/chamadapublicas"
PAGE_SIZE = 250

# Chaves de publico-alvo que contam como "aplicavel a empresa" (o foco pedido pelo usuario).
# empresa1..5 sao faixas de receita; ict/fundos/produtorRural sozinhos NAO contam.
PUBLICO_EMPRESA = {"empresa1", "empresa2", "empresa3", "empresa4", "empresa5", "startup", "cooperativa"}

EXTENSOES_DOCUMENTO = (".pdf", ".doc", ".docx", ".xls", ".xlsx")


def _fetch_pagina(page: int) -> dict:
    resp = requests.get(
        API_URL,
        params={"sort": "dataDePublicacao:desc", "search": "", "page": page, "pageSize": PAGE_SIZE},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    # decode explicito -- ver docstring do modulo.
    return json.loads(resp.content.decode("utf-8"))


def fetch_editais() -> list:
    primeira = _fetch_pagina(1)
    itens = list(primeira["items"])
    last_page = primeira.get("lastPage", 1)
    for page in range(2, last_page + 1):
        itens.extend(_fetch_pagina(page)["items"])
    return itens


def _extrair_documentos(descricao_html: str) -> list:
    if not descricao_html:
        return []
    docs = []
    for href, label in re.findall(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', descricao_html, flags=re.IGNORECASE | re.DOTALL):
        if not href.lower().endswith(EXTENSOES_DOCUMENTO):
            continue
        texto = re.sub(r"<[^>]+>", "", label).strip()
        texto = texto.replace("&nbsp;", " ").strip() or href.rsplit("/", 1)[-1]
        docs.append({"label": texto, "url": href})
    # remove duplicatas mantendo ordem
    vistos = set()
    unicos = []
    for d in docs:
        if d["url"] in vistos:
            continue
        vistos.add(d["url"])
        unicos.append(d)
    return unicos


def _campo_chave(obj, default=None):
    return obj.get("key") if isinstance(obj, dict) else default


def _campo_nome(obj, default=None):
    return obj.get("name") if isinstance(obj, dict) else default


def _normalizar(item: dict) -> dict:
    publico_alvo_objs = item.get("publicoAlvo") or []
    publico_alvo_keys = [p.get("key") for p in publico_alvo_objs if p.get("key")]
    aplicavel_empresa = 1 if (set(publico_alvo_keys) & PUBLICO_EMPRESA) else 0

    return {
        "id": item["id"],
        "titulo": item.get("titulo"),
        "tema_principal": _campo_nome(item.get("temaPrincipal")),
        "temas": item.get("tema"),
        "situacao": _campo_chave(item.get("situacao")),
        "tipo_oportunidade": _campo_nome(item.get("tipoDeOportunidade")),
        "tipo_cooperacao": _campo_nome(item.get("tipoCooperacao")),
        "contrapartida": _campo_nome(item.get("contrapartida")),
        "regiao": _campo_nome(item.get("regiao")),
        "publico_alvo": json.dumps(publico_alvo_keys, ensure_ascii=False),
        "aplicavel_empresa": aplicavel_empresa,
        "data_publicacao": item.get("dataDePublicacao"),
        "vigencia_inicio": item.get("vigenciaInicio"),
        "vigencia_fim": item.get("vigenciaFim"),
        "prazo_proposto": item.get("prazoProposto"),
        "descricao_html": item.get("descricao"),
        "descricao_texto": item.get("descricaoRawText"),
        "documentos": json.dumps(_extrair_documentos(item.get("descricao")), ensure_ascii=False),
    }


def parse_and_store(itens: list) -> tuple:
    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn = get_connection()
    try:
        cur = conn.cursor()
        for item in itens:
            row = _normalizar(item)
            row["atualizado_em"] = agora
            cur.execute(
                """
                INSERT INTO editais_raw (
                    id, titulo, tema_principal, temas, situacao, tipo_oportunidade,
                    tipo_cooperacao, contrapartida, regiao, publico_alvo, aplicavel_empresa,
                    data_publicacao, vigencia_inicio, vigencia_fim, prazo_proposto,
                    descricao_html, descricao_texto, documentos, atualizado_em
                ) VALUES (
                    :id, :titulo, :tema_principal, :temas, :situacao, :tipo_oportunidade,
                    :tipo_cooperacao, :contrapartida, :regiao, :publico_alvo, :aplicavel_empresa,
                    :data_publicacao, :vigencia_inicio, :vigencia_fim, :prazo_proposto,
                    :descricao_html, :descricao_texto, :documentos, :atualizado_em
                )
                ON CONFLICT(id) DO UPDATE SET
                    titulo=excluded.titulo, tema_principal=excluded.tema_principal,
                    temas=excluded.temas, situacao=excluded.situacao,
                    tipo_oportunidade=excluded.tipo_oportunidade, tipo_cooperacao=excluded.tipo_cooperacao,
                    contrapartida=excluded.contrapartida, regiao=excluded.regiao,
                    publico_alvo=excluded.publico_alvo, aplicavel_empresa=excluded.aplicavel_empresa,
                    data_publicacao=excluded.data_publicacao, vigencia_inicio=excluded.vigencia_inicio,
                    vigencia_fim=excluded.vigencia_fim, prazo_proposto=excluded.prazo_proposto,
                    descricao_html=excluded.descricao_html, descricao_texto=excluded.descricao_texto,
                    documentos=excluded.documentos, atualizado_em=excluded.atualizado_em
                    -- resumo_ia / resumo_gerado_em NAO sao tocados: preserva o cache entre refreshes
                """,
                row,
            )
        conn.commit()

        total = cur.execute("SELECT COUNT(*) FROM editais_raw").fetchone()[0]
        abertos = cur.execute("SELECT COUNT(*) FROM editais_raw WHERE situacao = 'aberta'").fetchone()[0]
    finally:
        conn.close()

    return total, abertos


def _mesclar_documentos(documentos_atuais_json: str, documentos_reais: list) -> str:
    """Mescla os documentos ja extraidos via regex do HTML (manuais genericos da
    plataforma) com os documentos reais do edital (Regulamento, Anexos, FAQ...),
    removendo duplicatas por URL."""
    atuais = json.loads(documentos_atuais_json) if documentos_atuais_json else []
    vistos = {d["url"] for d in atuais}
    mesclados = list(atuais)
    for d in documentos_reais:
        if d["url"] not in vistos:
            vistos.add(d["url"])
            mesclados.append({"label": d["label"], "url": d["url"]})
    return json.dumps(mesclados, ensure_ascii=False)


def backfill_documentos_chave() -> int:
    """Para editais REALMENTE abertos, sempre rebusca e remescla a lista real de
    documentos (Regulamento, Anexos, FAQ...) -- e uma chamada leve (1 request), entao
    roda em toda edital aberto, todo refresh, para nao perder documentos novos que a
    FINEP publicar depois (ex: um novo "Resultado parcial"). A extracao de texto do
    PDF (cara, baixa e le o Regulamento/Anexo 1 inteiros) so roda quando ainda nao
    esta cacheada (documento_chave_texto IS NULL), a mesma logica do resumo_ia.

    IMPORTANTE: parse_and_store() roda ANTES desta funcao e recalcula `documentos`
    do zero a partir do HTML da API (so pega os manuais genericos da plataforma) --
    se este remesclagem nao rodasse para TODO edital aberto (so para os sem texto
    cacheado), o proximo refresh apagaria os documentos reais ja mesclados de um
    edital cujo texto-chave ja tinha sido extraido antes."""
    conn = get_connection()
    try:
        abertos = conn.execute(
            "SELECT id, documentos, documento_chave_texto FROM editais_raw "
            "WHERE situacao = 'aberta' AND (prazo_proposto IS NULL OR date(prazo_proposto) >= date('now'))"
        ).fetchall()
    finally:
        conn.close()

    if not abertos:
        return 0

    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n_processados = 0
    conn = get_connection()
    try:
        for edital_id, documentos_atuais, texto_atual in abertos:
            try:
                documentos_reais = editais_documentos.obter_documentos_reais(edital_id)
                documentos_mesclados = _mesclar_documentos(documentos_atuais, documentos_reais)
                if texto_atual:
                    conn.execute(
                        "UPDATE editais_raw SET documentos = ? WHERE id = ?",
                        (documentos_mesclados, edital_id),
                    )
                else:
                    texto_chave = editais_documentos.montar_texto_documento_chave(documentos_reais)
                    conn.execute(
                        "UPDATE editais_raw SET documentos = ?, documento_chave_texto = ?, "
                        "documento_chave_atualizado_em = ? WHERE id = ?",
                        (documentos_mesclados, texto_chave or None, agora, edital_id),
                    )
                conn.commit()
                n_processados += 1
            except Exception as e:
                print(f"Aviso: falha ao buscar documentos do edital {edital_id}: {e}")
    finally:
        conn.close()

    return n_processados


def refresh_editais() -> tuple:
    itens = fetch_editais()
    print(f"Baixados {len(itens)} editais da API da FINEP.")
    total, abertos = parse_and_store(itens)
    print(f"editais_raw: {total} no total, {abertos} abertos.")
    n_docs = backfill_documentos_chave()
    print(f"Documentos reais (Regulamento/Anexo 1) processados para {n_docs} editais.")
    return total, abertos


if __name__ == "__main__":
    from db import init_db

    init_db()
    refresh_editais()
