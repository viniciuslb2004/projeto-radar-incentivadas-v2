"""Salvar (favoritar) operacao + Notas -- area interna da Equipe Artica
(/interno-artica, ver CLAUDE.md e docs/painel-admin.md). Schema em src/db.py
(tabela `usuario_operacoes_salvas`, PENDENTE de aplicacao contra o Aiven de
producao -- ver comentario junto do CREATE TABLE em src/db.py).

Reativado a partir do codigo arquivado em docs/archive/removed-features.md
(secao 3.1, "Transacoes Salvas", removida em 2026-09-21) -- funcionalmente
IDENTICO ao original (mesma tabela, mesmas funcoes), so o GATE de quem pode
chamar mudou: antes qualquer conta logada no site (`_exigir_usuario_logado`,
tambem removida); agora exclusivamente sessao de STAFF
(`webapp/admin/auth.py::exigir_staff`, ver as rotas em webapp/main.py que usam
este modulo). O campo `nota` ja existia na tabela original e e' reaproveitado
aqui pro pedido de "Notas" -- nao existe tabela de notas separada.

Toda funcao aqui recebe uma conexao ja aberta (mesmo padrao do resto do
projeto) e um `usuario_id` ja validado por uma sessao de staff de verdade --
nada aqui verifica autenticacao/autorizacao sozinho.

NAO inclui o historico de busca (`usuario_busca_historico`) da feature
original -- fora do escopo do pedido de /interno-artica (so Salvar/Notas/
Exportar), e essa tabela nao foi trazida de volta a producao.
"""
from datetime import datetime, timezone


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============ Operacoes salvas (favoritos) ============

def favoritar_operacao(conn, usuario_id: int, operation_id: int, nota: str = None) -> None:
    """Marca uma operacao como salva (ou atualiza a nota, se ja estava salva --
    UNIQUE(usuario_id, operation_id) faz o upsert). nota=None em uma operacao ja
    salva PRESERVA a nota existente."""
    conn.execute(
        "INSERT INTO usuario_operacoes_salvas (usuario_id, operation_id, nota, criado_em) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (usuario_id, operation_id) DO UPDATE SET "
        "nota = COALESCE(EXCLUDED.nota, usuario_operacoes_salvas.nota)",
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
    cur = conn.execute(
        "UPDATE usuario_operacoes_salvas SET nota = ? WHERE usuario_id = ? AND operation_id = ?",
        (nota, usuario_id, operation_id),
    )
    conn.commit()
    return cur.rowcount > 0


def operacao_esta_salva(conn, usuario_id: int, operation_id: int):
    row = conn.execute(
        "SELECT nota FROM usuario_operacoes_salvas WHERE usuario_id = ? AND operation_id = ?",
        (usuario_id, operation_id),
    ).fetchone()
    if row is None:
        return {"salva": False}
    return {"salva": True, "nota": row[0]}


def listar_ids_salvos(conn, usuario_id: int) -> list:
    rows = conn.execute(
        "SELECT operation_id FROM usuario_operacoes_salvas WHERE usuario_id = ?",
        (usuario_id,),
    ).fetchall()
    return [r[0] for r in rows]


def listar_operacoes_salvas(conn, usuario_id: int):
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
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(o.valor_contratado), 0) "
        "FROM usuario_operacoes_salvas s JOIN operations o ON o.id = s.operation_id "
        "WHERE s.usuario_id = ?",
        (usuario_id,),
    ).fetchone()
    total, valor_total = row
    return {"total_operacoes": total, "valor_total": float(valor_total) if valor_total else 0.0}
