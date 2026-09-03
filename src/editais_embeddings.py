"""Gera embeddings locais para os editais ABERTOS da FINEP (corpus pequeno, poucas
dezenas de itens -- reconstruido do zero a cada refresh diario, sem incremental)."""
import numpy as np
import pandas as pd

from db import DATA_DIR, get_connection
from embeddings import get_model

EMB_PATH = DATA_DIR / "editais_embeddings.npz"


def _texto(v) -> str:
    return v if isinstance(v, str) else ""


def _texto_embedding(row) -> str:
    partes = [
        _texto(row["titulo"]),
        _texto(row["tema_principal"]),
        _texto(row["temas"]),
        _texto(row["descricao_texto"])[:1500],
    ]
    return " | ".join(p for p in partes if p)


def build_editais_embeddings():
    conn = get_connection()
    try:
        # NAO confia so no campo situacao da FINEP: alguns editais ficam marcados
        # 'aberta' mesmo com o prazo_proposto ja vencido (dado da propria FINEP fica
        # defasado). Um edital com prazo de submissao no passado nao deve entrar no
        # corpus do endgame, mesmo que a FINEP ainda nao tenha atualizado a situacao.
        df = pd.read_sql(
            "SELECT id, titulo, tema_principal, temas, descricao_texto FROM editais_raw "
            "WHERE situacao='aberta' AND (prazo_proposto IS NULL OR prazo_proposto::date >= CURRENT_DATE)",
            conn,
        )
    finally:
        conn.close()

    if df.empty:
        print("Nenhum edital aberto para gerar embeddings.")
        np.savez_compressed(EMB_PATH, ids=np.array([], dtype=np.int64), vectors=np.zeros((0, 384), dtype=np.float32))
        return

    model = get_model()
    textos = df.apply(_texto_embedding, axis=1).tolist()
    print(f"Gerando embeddings para {len(textos)} editais abertos...")
    vectors = model.encode(textos, batch_size=32, show_progress_bar=True, normalize_embeddings=True)

    np.savez_compressed(EMB_PATH, ids=df["id"].to_numpy(), vectors=vectors.astype(np.float32))
    print(f"Embeddings de editais salvos em {EMB_PATH} ({vectors.shape[0]} x {vectors.shape[1]})")


if __name__ == "__main__":
    build_editais_embeddings()
