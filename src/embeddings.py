"""Gera embeddings locais (sentence-transformers) para todas as operacoes."""
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


def build_embeddings():
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


if __name__ == "__main__":
    build_embeddings()
