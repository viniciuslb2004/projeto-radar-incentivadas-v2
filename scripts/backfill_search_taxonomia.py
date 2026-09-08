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


_ERROS_TRANSITORIOS_LOCK = (psycopg.errors.DeadlockDetected, psycopg.errors.LockNotAvailable, psycopg.errors.SerializationFailure)
# Erros de CONEXAO (nao so de lock) ja confirmados nesta sessao contra o Aiven free
# tier: ReadOnlySqlTransaction (servico ficou read-only durante o backup inicial
# automatico) e AdminShutdown (reinicio/manutencao automatica) -- ambos derrubam a
# conexao/transacao inteira, entao so um ROLLBACK na mesma conexao nao resolve, e
# preciso de uma conexao NOVA de verdade (db.get_connection()) antes de tentar de novo.
_ERROS_CONEXAO = (psycopg.errors.ReadOnlySqlTransaction, psycopg.OperationalError)


def _reconectar():
    print("    (reconectando -- conexao anterior foi derrubada pelo servidor)")
    return db.get_connection()


def _executar_com_retry(conn, sql, params):
    """Roda um UPDATE com retry em caso de erro transiente -- de lock (concorrencia
    normal, ROLLBACK + retenta na MESMA conexao) ou de conexao (Aiven free tier ja
    derrubou a conexao 2x nesta sessao: uma vez em modo read-only durante o backup
    inicial automatico, outra por reinicio/manutencao -- nesses casos precisa de uma
    conexao NOVA, nao so rollback). Devolve a conexao valida no final (pode ser uma
    nova, se reconectou)."""
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            conn.execute(sql, params)
            return conn
        except _ERROS_TRANSITORIOS_LOCK as e:
            conn.rollback()
            if tentativa == MAX_TENTATIVAS:
                raise
            espera = 0.5 * tentativa
            print(f"    (retry {tentativa}/{MAX_TENTATIVAS} apos {type(e).__name__}, aguardando {espera:.1f}s...)")
            time.sleep(espera)
        except _ERROS_CONEXAO as e:
            if tentativa == MAX_TENTATIVAS:
                raise
            espera = 2.0 * tentativa
            print(f"    (retry {tentativa}/{MAX_TENTATIVAS} apos {type(e).__name__}, aguardando {espera:.1f}s...)")
            time.sleep(espera)
            conn = _reconectar()


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
        conn = _executar_com_retry(
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
            except _ERROS_TRANSITORIOS_LOCK as e:
                conn.rollback()
                if tentativa == MAX_TENTATIVAS:
                    raise
                espera = 0.5 * tentativa
                print(f"    (retry {tentativa}/{MAX_TENTATIVAS} apos {type(e).__name__}, aguardando {espera:.1f}s...)")
                time.sleep(espera)
            except _ERROS_CONEXAO as e:
                if tentativa == MAX_TENTATIVAS:
                    raise
                espera = 2.0 * tentativa
                print(f"    (retry {tentativa}/{MAX_TENTATIVAS} apos {type(e).__name__}, aguardando {espera:.1f}s...)")
                time.sleep(espera)
                conn = _reconectar()
        print(f"  ... {min(i + BATCH_VECTOR, len(todos_ids))}/{len(todos_ids)} ids ({time.time() - t2:.1f}s)")
    print(f"search_vector recalculado para {len(todos_ids)} ids em {time.time() - t2:.1f}s.")

    conn.close()
    print(f"\nTotal: {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    main()
