"""Endgame da aba Editais: usuario descreve um projeto/empresa, o sistema acha os
editais ABERTOS mais aderentes (embeddings locais)."""
import datetime
import json

import numpy as np

from db import get_connection
from editais_embeddings import EMB_PATH, build_editais_embeddings
from embeddings import get_model

# Corpus pequeno (dezenas de editais abertos, nao milhares de operacoes) -- limiares
# mais permissivos que os da busca de operacoes, senao uma busca legitima pode nao
# achar nada so porque nenhum edital bate 40%+ de similaridade de texto.
MARGEM_RELATIVA = 0.12
LIMIAR_ABSOLUTO_MINIMO = 0.25
MINIMO_RESULTADOS = 5

_emb_cache = None

_COLS_EDITAL = [
    "id", "titulo", "tema_principal", "temas", "situacao", "tipo_oportunidade",
    "tipo_cooperacao", "contrapartida", "regiao", "publico_alvo", "aplicavel_empresa",
    "data_publicacao", "vigencia_inicio", "vigencia_fim", "prazo_proposto",
    "descricao_texto", "documentos", "documento_chave_texto",
]


def _load_editais_embeddings():
    global _emb_cache
    if _emb_cache is None:
        if not EMB_PATH.exists():
            build_editais_embeddings()
        data = np.load(EMB_PATH)
        _emb_cache = (data["ids"], data["vectors"])
    return _emb_cache


def warmup():
    """So para o modo LOCAL (desktop) -- ver warmup_hospedado() para o modo hospedado."""
    get_model()
    _load_editais_embeddings()


def warmup_hospedado():
    """Versao leve do warmup() para o modo HOSPEDADO (Render, free tier, 512MB de RAM):
    carrega so o .npz de vetores dos editais abertos (numpy, poucos KB) -- NUNCA chama
    get_model()/SentenceTransformer. O embedding da descricao do usuario e calculado no
    NAVEGADOR dela (transformers.js, ver webapp/static/js/embeddings-client.js); o
    servidor so faz o produto escalar contra estes vetores precalculados (ver
    buscar_editais_por_projeto_com_vetor abaixo)."""
    _load_editais_embeddings()


def _dias_restantes(prazo_iso: str):
    if not prazo_iso:
        return None
    try:
        prazo = datetime.datetime.fromisoformat(prazo_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    agora = datetime.datetime.now(datetime.timezone.utc)
    return (prazo.date() - agora.date()).days


def _montar_edital(row: dict) -> dict:
    row = dict(row)
    row["publico_alvo"] = json.loads(row["publico_alvo"]) if row.get("publico_alvo") else []
    row["documentos"] = json.loads(row["documentos"]) if row.get("documentos") else []
    row["dias_restantes"] = _dias_restantes(row.get("prazo_proposto"))
    return row


def _buscar_editais_nucleo(query: str, qvec, max_resultados: int = 15) -> dict:
    """Nucleo comum de buscar_editais_por_projeto()/buscar_editais_por_projeto_com_vetor()
    -- so precisa do vetor da query ja calculado (pelo servidor, modo local, ou pelo
    navegador, modo hospedado)."""
    ids, vectors = _load_editais_embeddings()
    if len(ids) == 0:
        return {"query": query, "melhor_score": 0.0, "confianca_baixa": True, "resultados": []}

    scores = vectors @ qvec
    ordenado = np.argsort(-scores)
    melhor_score = float(scores[ordenado[0]])

    limiar = max(melhor_score - MARGEM_RELATIVA, LIMIAR_ABSOLUTO_MINIMO)
    n_acima_limiar = int((scores >= limiar).sum())
    n_selecionar = min(max(MINIMO_RESULTADOS, n_acima_limiar), max_resultados, len(ordenado))
    top_idx = ordenado[:n_selecionar]

    top_ids = ids[top_idx].tolist()
    score_by_id = dict(zip(top_ids, scores[top_idx].tolist()))

    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(top_ids))
        rows = conn.execute(
            f"SELECT {', '.join(_COLS_EDITAL)} FROM editais_raw WHERE id IN ({placeholders})", top_ids
        ).fetchall()
    finally:
        conn.close()

    resultados = [_montar_edital(dict(zip(_COLS_EDITAL, r))) for r in rows]
    for r in resultados:
        r["score"] = round(float(score_by_id.get(r["id"], 0)), 4)
    resultados.sort(key=lambda r: r["score"], reverse=True)

    return {
        "query": query,
        "melhor_score": round(melhor_score, 4),
        "confianca_baixa": melhor_score < 0.30,
        "n_resultados": len(resultados),
        "resultados": resultados,
    }


def buscar_editais_por_projeto(query: str, max_resultados: int = 15) -> dict:
    """Busca RAPIDA (so embeddings): compara a descricao do usuario contra o titulo/tema/
    descricao de cada edital ABERTO e devolve os mais aderentes, do mais para o menos.
    Modo LOCAL (desktop): calcula o embedding da query no proprio processo (get_model())
    -- ver buscar_editais_por_projeto_com_vetor() para o modo hospedado."""
    ids, _ = _load_editais_embeddings()
    if len(ids) == 0:
        return {"query": query, "melhor_score": 0.0, "confianca_baixa": True, "resultados": []}
    model = get_model()
    qvec = model.encode([query], normalize_embeddings=True)[0]
    return _buscar_editais_nucleo(query, qvec, max_resultados)


def buscar_editais_por_projeto_com_vetor(query: str, query_vec, max_resultados: int = 15) -> dict:
    """Mesma logica de buscar_editais_por_projeto(), mas para o modo HOSPEDADO: o vetor
    da query ja vem calculado no navegador (transformers.js, ver webapp/static/js/
    embeddings-client.js) -- o servidor NUNCA chama get_model()/SentenceTransformer
    aqui, so faz a matematica (numpy) contra os vetores precalculados
    (data/editais_embeddings.npz)."""
    vetor = np.asarray(query_vec, dtype=np.float32)
    norma = float(np.linalg.norm(vetor))
    if norma > 0:
        vetor = vetor / norma
    return _buscar_editais_nucleo(query, vetor, max_resultados)


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "startup de inteligencia artificial para o agronegocio"
    r = buscar_editais_por_projeto(q)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
