"""Backfill unico: recalcula `search_taxonomia_termos` e `search_vector` de TODAS as
linhas ja existentes em `operations` depois de uma expansao no dicionario de sinonimos
(ver src/search_taxonomy.py, SINONIMOS_SEGMENTO). Nao mexe em `embedding_text`/embeddings
(sistema separado, fora de escopo -- ver data/embeddings.npz).

Por que nao um UPDATE por linha: a mesma combinacao (setor_bndes, subsetor_bndes,
segmento) se repete em milhares de linhas (~58 mil linhas, mas so algumas centenas/
milhares de combinacoes distintas) -- calcular o texto de sinonimos UMA VEZ por
combinacao e rodar UM UPDATE por combinacao (WHERE ... IS NOT DISTINCT FROM, NULL-safe)
e ordens de magnitude mais rapido do que uma linha por vez (confirmado empiricamente
nesta sessao: um UPDATE por linha levou 15+ minutos em poucas centenas de linhas).

Uso: python scripts/backfill_search_taxonomia.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg

import db
from unify import _search_taxonomia_termos, _atualizar_search_vector

BATCH_VECTOR = 5000
COMMIT_A_CADA = 50  # grupos por commit -- transacoes mais curtas, menos exposicao a deadlock/lock contention
MAX_TENTATIVAS = 5


def _executar_com_retry(conn, sql, params):
    """Roda um UPDATE com retry em caso de deadlock/erro transiente de lock (ex:
    concorrencia com outro processo escrevendo em `operations` ao mesmo tempo,
    ja observado nesta sessao: psycopg.errors.DeadlockDetected). ROLLBACK antes de
    cada nova tentativa -- a transacao corrente fica invalida apos um erro do Postgres."""
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            conn.execute(sql, params)
            return
        except (psycopg.errors.DeadlockDetected, psycopg.errors.LockNotAvailable, psycopg.errors.SerializationFailure) as e:
            conn.rollback()
            if tentativa == MAX_TENTATIVAS:
                raise
            espera = 0.5 * tentativa
            print(f"    (retry {tentativa}/{MAX_TENTATIVAS} apos {type(e).__name__}, aguardando {espera:.1f}s...)")
            time.sleep(espera)


def main():
    conn = db.get_connection()
    t0 = time.time()

    print("Lendo (id, setor_bndes, subsetor_bndes, segmento) de todas as linhas de operations...")
    rows = conn.execute(
        "SELECT id, setor_bndes, subsetor_bndes, segmento FROM operations"
    ).fetchall()
    print(f"  {len(rows)} linhas lidas em {time.time() - t0:.1f}s.")

    # Agrupa por combinacao distinta (setor_bndes, subsetor_bndes, segmento) -- poucas
    # centenas/milhares de grupos, nao 58 mil.
    grupos = {}
    for op_id, setor, subsetor, segmento in rows:
        chave = (setor, subsetor, segmento)
        grupos.setdefault(chave, []).append(op_id)

    print(f"  {len(grupos)} combinacoes distintas de (setor_bndes, subsetor_bndes, segmento).")

    t1 = time.time()
    n_grupos_atualizados = 0
    n_linhas_atualizadas = 0
    todos_ids = []
    for (setor, subsetor, segmento), ids in grupos.items():
        row = {"setor_bndes": setor, "subsetor_bndes": subsetor, "segmento": segmento}
        texto_taxonomia = _search_taxonomia_termos(row)
        _executar_com_retry(
            conn,
            """
            UPDATE operations SET search_taxonomia_termos = ?
            WHERE setor_bndes IS NOT DISTINCT FROM ?
              AND subsetor_bndes IS NOT DISTINCT FROM ?
              AND segmento IS NOT DISTINCT FROM ?
            """,
            (texto_taxonomia, setor, subsetor, segmento),
        )
        n_grupos_atualizados += 1
        n_linhas_atualizadas += len(ids)
        todos_ids.extend(ids)
        if n_grupos_atualizados % COMMIT_A_CADA == 0:
            conn.commit()
            print(f"  ... {n_grupos_atualizados}/{len(grupos)} combinacoes, "
                  f"{n_linhas_atualizadas} linhas ({time.time() - t1:.1f}s)")
    conn.commit()
    print(f"search_taxonomia_termos recalculado para {n_linhas_atualizadas} linhas "
          f"({n_grupos_atualizados} combinacoes) em {time.time() - t1:.1f}s.")

    t2 = time.time()
    print(f"Recalculando search_vector (tsvector com peso por campo) em lotes de {BATCH_VECTOR}...")
    for i in range(0, len(todos_ids), BATCH_VECTOR):
        lote = todos_ids[i:i + BATCH_VECTOR]
        for tentativa in range(1, MAX_TENTATIVAS + 1):
            try:
                _atualizar_search_vector(conn, lote)
                break
            except (psycopg.errors.DeadlockDetected, psycopg.errors.LockNotAvailable, psycopg.errors.SerializationFailure) as e:
                conn.rollback()
                if tentativa == MAX_TENTATIVAS:
                    raise
                espera = 0.5 * tentativa
                print(f"    (retry {tentativa}/{MAX_TENTATIVAS} apos {type(e).__name__}, aguardando {espera:.1f}s...)")
                time.sleep(espera)
        print(f"  ... {min(i + BATCH_VECTOR, len(todos_ids))}/{len(todos_ids)} ids ({time.time() - t2:.1f}s)")
    print(f"search_vector recalculado para {len(todos_ids)} ids em {time.time() - t2:.1f}s.")

    conn.close()
    print(f"\nTotal: {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    main()
