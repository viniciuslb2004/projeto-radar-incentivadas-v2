"""Traduz o placeholder posicional do SQLite (`?`) usado em TODO o codigo existente
(`conn.execute(sql, params)`, `cur.execute(sql, params)`, `cur.executemany(sql, params_seq)`)
para o placeholder que o psycopg (Postgres) realmente entende (`%s`) -- SEM exigir
nenhuma mudanca nos ~40+ call sites espalhados por `webapp/main.py` e `src/*.py`.

Abordagem escolhida (monkeypatch, opcao (a) do pedido): embrulha os metodos
`execute`/`executemany` REAIS de `psycopg.Connection`/`psycopg.Cursor` para fazer a
troca `?` -> `%s` no texto da query antes de delegar pro metodo original. Assim
`get_connection()` (db.py) continua devolvendo uma conexao psycopg comum -- nao
precisa de nenhuma subclasse/wrapper customizada -- e todo o resto do codigo chama
`conn.execute(...)`/`cur.execute(...)`/`cur.executemany(...)` exatamente como sempre
chamou (mesmo estilo do sqlite3/libsql de antes desta migracao).

Confirmado por grep manual em todo o repositorio (ver commit desta migracao): NENHUMA
string SQL deste projeto usa `?` para qualquer coisa alem de placeholder posicional --
sem operador JSON `?`/`?|`/`?&` do Postgres, sem `LIKE`/`GLOB` usando `?` como wildcard
de um caractere. A troca cega (str.replace) e segura aqui.

O patch e idempotente (`patch()` so aplica uma vez, mesmo chamado varias vezes -- ex:
por multiplos modulos que importam db.py) e so mexe no texto da QUERY (o argumento
`query`), nunca nos valores dos parametros -- uma string de negocio com "?" dentro
(ex: descricao de projeto) passa ilesa, pois so vira parametro (bind), nunca parte do
texto SQL.
"""
import psycopg

_patched = False


def _translate(query):
    if isinstance(query, str) and "?" in query:
        return query.replace("?", "%s")
    return query


def patch():
    """Aplica o monkeypatch uma unica vez por processo. Chamado por db.py na
    importacao -- nao precisa ser chamado manualmente em nenhum outro lugar."""
    global _patched
    if _patched:
        return
    _patched = True

    _orig_conn_execute = psycopg.Connection.execute
    _orig_cur_execute = psycopg.Cursor.execute
    _orig_cur_executemany = psycopg.Cursor.executemany

    def conn_execute(self, query, params=None, **kwargs):
        return _orig_conn_execute(self, _translate(query), params, **kwargs)

    def cur_execute(self, query, params=None, **kwargs):
        return _orig_cur_execute(self, _translate(query), params, **kwargs)

    def cur_executemany(self, query, params_seq, **kwargs):
        return _orig_cur_executemany(self, _translate(query), params_seq, **kwargs)

    psycopg.Connection.execute = conn_execute
    psycopg.Cursor.execute = cur_execute
    psycopg.Cursor.executemany = cur_executemany
