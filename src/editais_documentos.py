"""Busca os documentos REAIS de um edital especifico da FINEP (Regulamento, Anexo 1,
etc) -- que NAO vem no campo `descricao` da API de listagem usada por finep_editais.py
-- e extrai o texto do Regulamento + Anexo 1 (as fontes que de fato tem linhas
tematicas, valores minimo/maximo e contrapartida) para compor o texto-chave do edital
(`editais_raw.documento_chave_texto`), usado na busca por similaridade.

A pagina publica de cada edital (ex: finep.gov.br/e/chamada-publica/.../{id}) busca
essa lista via `GET /o/c/chamadapublicas/{id}/documentos`, autenticado com um token
OAuth2 "client_credentials" cujo client_id/secret ficam expostos no proprio JS publico
do site (e' o mecanismo que o site usa para deixar QUALQUER visitante anonimo ler esse
mesmo conteudo publico -- nao e' uma credencial privada nem contorna nenhuma protecao).
"""
import base64
import io
import re
import time

import requests
from pypdf import PdfReader

BASE_URL = "https://www.finep.gov.br"
CLIENT_ID = "idClientPRD"
CLIENT_SECRET = "secretClientPRD"

_token_cache = {"token": None, "expira_em": 0}

# Tamanho maximo (chars) de cada documento no texto final passado para a IA. O Anexo 1
# e onde ficam as secoes que mais importam (linhas tematicas, valor minimo/maximo,
# contrapartida) -- mas a POSICAO dessas secoes varia com o numero de linhas tematicas
# do edital (um edital com 6 linhas empurra a secao de valores bem mais pra baixo que
# um com 2), entao qualquer limite fixo curto cedo ou tarde corta exatamente a parte
# com os numeros. Por isso o Anexo 1 praticamente nao e cortado (os exemplos reais
# vistos ficam entre 11k-19k chars); o Regulamento e mais generico/repetitivo entre
# editais do mesmo programa, entao esse sim fica com um limite menor.
LIMITE_ANEXO1 = 25000
LIMITE_REGULAMENTO = 4000


def _obter_token() -> str:
    agora = time.time()
    if _token_cache["token"] and agora < _token_cache["expira_em"]:
        return _token_cache["token"]

    auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    resp = requests.post(
        f"{BASE_URL}/o/oauth2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {auth}"},
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expira_em"] = agora + data.get("expires_in", 600) - 30
    return _token_cache["token"]


def _montar_url(href: str) -> str:
    if not href:
        return ""
    return href if href.startswith("http") else BASE_URL + href


def obter_documentos_reais(edital_id: int) -> list:
    """Lista real de documentos do edital (Regulamento, Anexos, FAQ, resultados parciais...)."""
    token = _obter_token()
    resp = requests.get(
        f"{BASE_URL}/o/c/chamadapublicas/{edital_id}/documentos",
        params={"pageSize": 500},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code in (401, 403):
        _token_cache["token"] = None
        token = _obter_token()
        resp = requests.get(
            f"{BASE_URL}/o/c/chamadapublicas/{edital_id}/documentos",
            params={"pageSize": 500},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )
    resp.raise_for_status()
    data = resp.json()

    docs = []
    for item in data.get("items", []):
        prop = item.get("documentoProprietario") or {}
        link = prop.get("link") or {}
        url = _montar_url(link.get("href"))
        if not url:
            continue
        docs.append({
            "label": item.get("legenda") or prop.get("name") or "Documento",
            "url": url,
            "data_publicacao": item.get("dataDePublicacao"),
        })
    return docs


def _extrair_texto_pdf(url: str) -> str:
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        reader = PdfReader(io.BytesIO(resp.content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def _melhor_match(documentos: list, padrao: str):
    candidatos = [d for d in documentos if re.match(padrao, (d["label"] or "").strip(), re.IGNORECASE)]
    if not candidatos:
        return None
    candidatos.sort(key=lambda d: d.get("data_publicacao") or "", reverse=True)
    return candidatos[0]


def montar_texto_documento_chave(documentos: list) -> str:
    """Acha o Regulamento e o Anexo 1 (as fontes reais de linhas tematicas, valores e
    contrapartida) entre os documentos do edital, baixa os PDFs e extrai o texto,
    priorizando o Anexo 1 (mais especifico) e truncando cada um para nao estourar o
    contexto do modelo local. Devolve string vazia se nao achar nenhum dos dois.

    Nem todo edital segue o padrao "Regulamento" + "Anexo 1": chamadas de FIP e alguns
    editais mais antigos usam um unico "Edital" (as vezes com um "Anexos do Edital"
    separado) em vez de Regulamento/Anexo 1 individuais -- por isso ha um fallback para
    esses nomes quando o padrao principal nao e encontrado."""
    regulamento = _melhor_match(documentos, r"^regulamento") or _melhor_match(documentos, r"^edital\b")
    anexo1 = _melhor_match(documentos, r"^anexo\s*(1|i)\b") or _melhor_match(documentos, r"^anexos?\b")
    if anexo1 and regulamento and anexo1["url"] == regulamento["url"]:
        anexo1 = None  # mesmo documento (ex: "Edital" pego pelos dois fallbacks) -- nao duplica

    partes = []
    if anexo1:
        texto = _extrair_texto_pdf(anexo1["url"])
        if texto:
            partes.append(f"=== {anexo1['label']} ===\n{texto[:LIMITE_ANEXO1]}")
    if regulamento:
        texto = _extrair_texto_pdf(regulamento["url"])
        if texto:
            partes.append(f"=== {regulamento['label']} ===\n{texto[:LIMITE_REGULAMENTO]}")

    return "\n\n".join(partes)


if __name__ == "__main__":
    import sys

    edital_id = int(sys.argv[1]) if len(sys.argv) > 1 else 754961
    docs = obter_documentos_reais(edital_id)
    print(f"{len(docs)} documentos encontrados:")
    for d in docs:
        print(" -", d["label"], "|", d["data_publicacao"])
    texto = montar_texto_documento_chave(docs)
    print(f"\nTexto-chave extraido: {len(texto)} chars")
