"""Backfill unico (2026-09-23): setor padronizado por CNAE + produto FINEP.

1. ALTER TABLE operations ADD COLUMN setor_cnae/subsetor_cnae/setor_cnae_origem (via
   db._aplicar_migracoes, nullable = so metadado, instantaneo) + CREATE INDEX
   CONCURRENTLY idx_operations_setor_cnae (nao trava escrita).
2. unify.recalcular_setor_cnae (lotes de 5000, commit por lote) + reaplica correcoes
   manuais.
3. Produto FINEP: descentralizado -> "Inovacred" (decisao do usuario); direto ->
   programa a partir de `demanda` (unify.produto_finep_direto). Troca tambem o rotulo
   em search_document/embedding_text e recalcula search_vector -- em lotes curtos.

Daqui pra frente unify.py ja grava tudo isso no insert/refresh. Idempotente.
Uso: python scripts/backfill_setor_cnae_produto_finep.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import unify  # noqa: E402

LOTE = 2000


def main():
    conn = db.get_connection()
    conn = db._aplicar_migracoes(conn)
    conn.autocommit = True
    conn.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_operations_setor_cnae ON operations(setor_cnae)")
    conn.autocommit = False

    info = unify.recalcular_setor_cnae(conn)
    print("setor_cnae:", info)
    print("correcoes reaplicadas:", unify._reaplicar_correcoes_manuais(conn))

    # ---- produto FINEP ----
    alvo = []
    for op_id, produto in conn.execute(
        "SELECT o.id, o.produto FROM operations o WHERE o.raw_table = 'finep_credito_descentralizado_raw'"
    ).fetchall():
        if produto != unify.PRODUTO_FINEP_DESCENTRALIZADO:
            alvo.append((op_id, produto, unify.PRODUTO_FINEP_DESCENTRALIZADO))
    for op_id, produto, demanda in conn.execute(
        "SELECT o.id, o.produto, r.demanda FROM operations o JOIN finep_credito_direto_raw r "
        "ON o.raw_table = 'finep_credito_direto_raw' AND r.id = o.raw_id"
    ).fetchall():
        novo = unify.produto_finep_direto(demanda)
        if produto != novo:
            alvo.append((op_id, produto, novo))
    print("produto FINEP a atualizar:", len(alvo))
    grupos = {}
    for op_id, antigo, novo in alvo:
        grupos.setdefault((antigo or "", novo), []).append(op_id)
    for (antigo, novo), ids in grupos.items():
        for i in range(0, len(ids), LOTE):
            lote = ids[i:i + LOTE]
            conn.execute(
                "UPDATE operations SET produto = ?, "
                "search_document = replace(search_document, ?, ?), "
                "embedding_text = replace(embedding_text, ?, ?) WHERE id = ANY(?)",
                (novo, antigo, novo, antigo, novo, lote),
            )
            conn.commit()
            unify._atualizar_search_vector(conn, lote)
        print(f"  produto: {antigo!r} -> {novo!r}: {len(ids)}")
    conn.close()


if __name__ == "__main__":
    main()
