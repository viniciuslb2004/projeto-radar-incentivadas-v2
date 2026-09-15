"""Transacoes Salvas: favoritos de operacao + historico de busca POR USUARIO (ver
CLAUDE.md, aba "Transacoes Salvas" -- schema em src/db.py, tabelas
usuario_operacoes_salvas/usuario_busca_historico). Toda funcao aqui recebe uma
conexao ja aberta (mesmo padrao do resto do projeto) e um usuario_id ja validado
por uma sessao de verdade (webapp/main.py::_exigir_usuario_logado) -- nada aqui
verifica autenticacao sozinho.
"""
from datetime import datetime, timezone


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============ Operacoes salvas (favoritos) ============

def favoritar_operacao(conn, usuario_id: int, operation_id: int, nota: str = None) -> None:
    """Marca uma operacao como salva (ou atualiza a nota, se ja estava salva --
    UNIQUE(usuario_id, operation_id) faz o upsert). nota=None em uma operacao ja
    salva PRESERVA a nota existente (so um clique de favoritar sem editar nota nao
    deve apagar o que a pessoa ja escreveu)."""
    conn.execute(
        "INSERT INTO usuario_operacoes_salvas (usuario_id, operation_id, nota, criado_em) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (usuario_id, operation_id) DO UPDATE SET "
        "nota = COALESCE(EXCLUDED.nota, usuario_operacoes_salvas.nota)",
        # (a qualificacao pelo nome da propria tabela do lado direito referencia a
        # LINHA JA EXISTENTE que causou o conflito -- sintaxe suportada pelo
        # Postgres em INSERT ... ON CONFLICT DO UPDATE, ver docs de INSERT)
        (usuario_id, operation_id, nota, _agora()),
    )
    conn.commit()


def desfavoritar_operacao(conn, usuario_id: int, operation_id: int) -> None:
    conn.execute(
        "DELETE FROM usuario_operacoes_salvas WHERE usuario_id = ? AND operation_id = ?",
        (usuario_id, operation_id),
    )
    conn.commit()


def atualizar_nota_operacao_salva(conn, usuario_id: int, operation_id: int, nota: str) -> bool:
    """So atualiza a nota de uma operacao JA salva (nunca cria o favorito sozinha) --
    devolve False se a operacao nao estava salva, pro caller decidir o que fazer."""
    cur = conn.execute(
        "UPDATE usuario_operacoes_salvas SET nota = ? WHERE usuario_id = ? AND operation_id = ?",
        (nota, usuario_id, operation_id),
    )
    conn.commit()
    return cur.rowcount > 0


def operacao_esta_salva(conn, usuario_id: int, operation_id: int):
    """Devolve {'salva': True, 'nota': ...} ou {'salva': False} -- usado pelo detalhe
    da operacao (modal) pra saber o estado inicial do botao de favoritar."""
    row = conn.execute(
        "SELECT nota FROM usuario_operacoes_salvas WHERE usuario_id = ? AND operation_id = ?",
        (usuario_id, operation_id),
    ).fetchone()
    if row is None:
        return {"salva": False}
    return {"salva": True, "nota": row[0]}


def listar_operacoes_salvas(conn, usuario_id: int):
    """Lista as operacoes salvas do usuario, com os campos de `operations` ja
    juntados (mesmos campos que a Busca exporta, ver webapp/exportar_excel.py) --
    ORDER BY criado_em DESC (favoritada mais recentemente primeiro)."""
    rows = conn.execute(
        "SELECT s.operation_id, s.nota, s.criado_em, "
        "  o.cliente, o.cnpj, o.agencia, o.uf, o.data_contratacao, "
        "  o.valor_contratado, o.valor_desembolsado, o.setor_bndes, o.subsetor_bndes, "
        "  o.segmento, o.descricao_projeto "
        "FROM usuario_operacoes_salvas s "
        "JOIN operations o ON o.id = s.operation_id "
        "WHERE s.usuario_id = ? ORDER BY s.criado_em DESC",
        (usuario_id,),
    ).fetchall()
    cols = [
        "operation_id", "nota", "salvo_em", "cliente", "cnpj", "agencia", "uf",
        "data_contratacao", "valor_contratado", "valor_desembolsado", "setor_bndes",
        "subsetor_bndes", "segmento", "descricao_projeto",
    ]
    return [dict(zip(cols, r)) for r in rows]


def resumo_operacoes_salvas(conn, usuario_id: int) -> dict:
    """KPI simples pro topo da pagina -- quantas operacoes salvas e a soma do valor
    contratado delas (nunca inventa um numero: 0/None quando a lista esta vazia)."""
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(o.valor_contratado), 0) "
        "FROM usuario_operacoes_salvas s JOIN operations o ON o.id = s.operation_id "
        "WHERE s.usuario_id = ?",
        (usuario_id,),
    ).fetchone()
    total, valor_total = row
    return {"total_operacoes": total, "valor_total": float(valor_total) if valor_total else 0.0}


# ============ Historico de busca (servidor) ============

def registrar_busca_historico(conn, usuario_id: int, query: str) -> None:
    """Grava uma busca no historico do usuario -- se a MESMA query (sem diferenciar
    maiusculas/minusculas) ja existe no historico dele, so atualiza criado_em (evita
    duplicar linha a cada re-busca do mesmo termo, mesmo espirito do dedup que o
    historico em localStorage ja fazia -- ver busca.js). Nunca mexe em `fixada`."""
    query = (query or "").strip()
    if not query:
        return
    existente = conn.execute(
        "SELECT id FROM usuario_busca_historico WHERE usuario_id = ? AND lower(query) = lower(?)",
        (usuario_id, query),
    ).fetchone()
    if existente:
        conn.execute(
            "UPDATE usuario_busca_historico SET criado_em = ? WHERE id = ?",
            (_agora(), existente[0]),
        )
    else:
        conn.execute(
            "INSERT INTO usuario_busca_historico (usuario_id, query, criado_em) VALUES (?, ?, ?)",
            (usuario_id, query, _agora()),
        )
    conn.commit()


def listar_busca_historico(conn, usuario_id: int, limite: int = 30):
    """Fixadas primeiro (mais recente entre as fixadas primeiro), depois o resto por
    recencia -- mesmo espirito de "fixar no topo" pedido pelo usuario."""
    rows = conn.execute(
        "SELECT id, query, fixada, criado_em FROM usuario_busca_historico "
        "WHERE usuario_id = ? ORDER BY fixada DESC, criado_em DESC LIMIT ?",
        (usuario_id, limite),
    ).fetchall()
    cols = ["id", "query", "fixada", "criado_em"]
    return [dict(zip(cols, r)) for r in rows]


def fixar_busca_historico(conn, usuario_id: int, historico_id: int, fixada: bool) -> bool:
    cur = conn.execute(
        "UPDATE usuario_busca_historico SET fixada = ? WHERE id = ? AND usuario_id = ?",
        (fixada, historico_id, usuario_id),
    )
    conn.commit()
    return cur.rowcount > 0


def remover_busca_historico(conn, usuario_id: int, historico_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM usuario_busca_historico WHERE id = ? AND usuario_id = ?",
        (historico_id, usuario_id),
    )
    conn.commit()
    return cur.rowcount > 0


def limpar_busca_historico(conn, usuario_id: int) -> None:
    """Limpa so o historico NAO fixado -- itens fixados pelo usuario sao removidos
    um a um (remover_busca_historico), nunca em massa por engano."""
    conn.execute(
        "DELETE FROM usuario_busca_historico WHERE usuario_id = ? AND fixada = FALSE",
        (usuario_id,),
    )
    conn.commit()
