"""Gera embeddings locais (sentence-transformers) para as operacoes.

Incremental: reembutir as ~28 mil+ operacoes inteiras a cada refresh semanal era o
passo mais caro do pipeline (alguns minutos em CPU, so pra regerar vetores que na
imensa maioria nao mudaram). Agora so calculamos embedding para (1) operacoes NOVAS
(raw rows que acabaram de ser unificadas) e (2) operacoes que foram RECLASSIFICADAS
(saíram de 'pendente' porque o CNPJ apareceu no cache cnpj_cnae -- nesse caso o texto
embutido muda, entao o vetor antigo fica desatualizado e precisa ser recalculado), e
so ai fazemos o merge com o .npz existente -- sem tocar no vetor das demais.

Fallback seguro: se o .npz nao existir ainda, ou vier corrompido/sem a chave esperada,
ou os ids/vetores nao baterem em tamanho, cai pra build_embeddings_full() (recalcula
tudo do zero) em vez de arriscar gravar um arquivo inconsistente.
"""
import numpy as np
import pandas as pd

from db import DATA_DIR, get_connection

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMB_PATH = DATA_DIR / "embeddings.npz"

_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        print(f"Carregando modelo de embeddings local ({MODEL_NAME})...")
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _encode_ids(ids: list) -> tuple:
    """Busca embedding_text no banco para esses ids e calcula os vetores. Devolve
    (ids_validos, vetores) -- ids que sumiram do banco nesse meio tempo sao ignorados."""
    if not ids:
        return np.array([], dtype=np.int64), np.zeros((0, 0), dtype=np.float32)

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, embedding_text FROM operations WHERE id = ANY(?)", [list(map(int, ids))]
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return np.array([], dtype=np.int64), np.zeros((0, 0), dtype=np.float32)

    ids_validos = [r[0] for r in rows]
    textos = [r[1] or "" for r in rows]
    model = get_model()
    vetores = model.encode(textos, batch_size=64, show_progress_bar=len(textos) > 200, normalize_embeddings=True)
    return np.array(ids_validos, dtype=np.int64), vetores.astype(np.float32)


def build_embeddings_full():
    """Recalcula embeddings para TODAS as operacoes, do zero -- usado na primeira vez
    (sem .npz ainda) ou como fallback de seguranca se o incremental nao for confiavel."""
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT id, embedding_text FROM operations", conn)
    finally:
        conn.close()

    if df.empty:
        print("Nenhuma operacao para gerar embeddings.")
        return

    model = get_model()
    texts = df["embedding_text"].fillna("").tolist()
    print(f"Gerando embeddings para {len(texts)} operacoes (isso pode levar alguns minutos em CPU)...")
    vectors = model.encode(texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)

    np.savez_compressed(EMB_PATH, ids=df["id"].to_numpy(), vectors=vectors.astype(np.float32))
    print(f"Embeddings salvos em {EMB_PATH} ({vectors.shape[0]} x {vectors.shape[1]})")


def build_embeddings(novos_ids: list = None, reclassificados_ids: list = None):
    """Atualiza data/embeddings.npz de forma incremental.

    novos_ids: ids de operations que acabaram de ser inseridas (nunca tiveram embedding).
    reclassificados_ids: ids que ja tinham embedding, mas o texto mudou (pendente -> enriquecido).

    Se nenhum dos dois for passado (chamada sem argumentos, ex: `python embeddings.py`),
    faz o rebuild completo -- mantém o comportamento antigo disponível para quem chamar
    o script direto."""
    novos_ids = list(dict.fromkeys(novos_ids or []))
    reclassificados_ids = list(dict.fromkeys(reclassificados_ids or []))

    if not novos_ids and not reclassificados_ids:
        if EMB_PATH.exists():
            print("embeddings: nenhum id novo/reclassificado -- nada a fazer (.npz existente mantido).")
            return
        print("embeddings: nenhum .npz existente e nenhum id informado -- gerando do zero.")
        build_embeddings_full()
        return

    if not EMB_PATH.exists():
        print("embeddings: .npz ainda nao existe -- gerando do zero (inclui os ids passados).")
        build_embeddings_full()
        return

    try:
        data = np.load(EMB_PATH)
        ids_existentes = data["ids"]
        vetores_existentes = data["vectors"]
        if len(ids_existentes) != len(vetores_existentes):
            raise ValueError("ids e vectors com tamanhos diferentes no .npz existente")
    except Exception as e:
        print(f"embeddings: .npz existente parece corrompido ou incompativel ({e}) -- refazendo do zero por seguranca.")
        build_embeddings_full()
        return

    a_recalcular = [i for i in (novos_ids + reclassificados_ids)]
    ids_novos_vec, vetores_novos = _encode_ids(a_recalcular)

    if vetores_existentes.shape[0] and ids_novos_vec.shape[0] and vetores_existentes.shape[1] != vetores_novos.shape[1]:
        print("embeddings: dimensao do vetor mudou (modelo diferente?) -- refazendo do zero por seguranca.")
        build_embeddings_full()
        return

    # remove do array existente qualquer id que estamos recalculando agora (reclassificados
    # ja tinham vetor antigo -- o novo substitui; novos_ids normalmente nao estao no array
    # ainda, mas o filtro e seguro/idempotente de qualquer forma)
    ids_a_substituir = set(int(i) for i in ids_novos_vec.tolist())
    if ids_existentes.shape[0]:
        manter = ~np.isin(ids_existentes, list(ids_a_substituir))
        ids_finais = np.concatenate([ids_existentes[manter], ids_novos_vec]) if ids_novos_vec.shape[0] else ids_existentes[manter]
        vetores_finais = (
            np.concatenate([vetores_existentes[manter], vetores_novos], axis=0)
            if ids_novos_vec.shape[0]
            else vetores_existentes[manter]
        )
    else:
        ids_finais = ids_novos_vec
        vetores_finais = vetores_novos

    np.savez_compressed(EMB_PATH, ids=ids_finais, vectors=vetores_finais.astype(np.float32))
    print(
        f"embeddings: {ids_novos_vec.shape[0]} vetores calculados/atualizados "
        f"({len(novos_ids)} novos + {len(reclassificados_ids)} reclassificados solicitados), "
        f".npz agora tem {ids_finais.shape[0]} linhas (era {ids_existentes.shape[0]})."
    )


if __name__ == "__main__":
    build_embeddings_full()
