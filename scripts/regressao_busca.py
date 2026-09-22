"""Bateria de regressao MANUAL do motor de busca sem IA (src/search_fts.py).

Nao e pytest (o projeto nao tem pytest instalado nem uma pasta tests/ -- ver
CLAUDE.md, nenhum framework de teste automatizado existe hoje neste repo) --
e um script standalone, no mesmo espirito de scripts/backfill_search_taxonomia.py,
pra rodar manualmente (`python scripts/regressao_busca.py`) sempre que
search_fts.py/search_taxonomy.py forem alterados. Consulta o banco de PRODUCAO
(mesmo DATABASE_URL do .env) em modo SOMENTE LEITURA -- nao escreve nada.

Cobre 3 grupos de casos, cada um documentando o motivo (ver historico em
CLAUDE.md/docs/motor-busca.md):
  1. Tolerancia a erro de digitacao em nome de empresa (tier 6, trigrama +
     word_similarity -- ver LIMIAR_WORD_SIMILARITY_TRGM em search_fts.py).
  2. Palavras genericas novas em PALAVRAS_GENERICAS_QUERY (brasil/brasileira/
     nacional/industrial/comercio/comercial/servicos) -- confirma que somem do
     OR de texto livre sem quebrar o filtro de setor (tier 2, que usa a frase
     completa, nunca palavra a palavra).
  3. Guardas de regressao dos bugs ja documentados (fibra optica/otica, parque
     de diversao vs parque eolico, grupo belterra/mombak, empresa de
     hospitais) -- garantem que a mudanca desta sessao nao reabriu nenhum
     desses.

Sai com codigo 1 se qualquer caso falhar (para uso futuro em CI, se um dia
existir); hoje e so um `python scripts/regressao_busca.py` manual.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import search_fts  # noqa: E402


def _top_clientes(query: str, limite: int = 10) -> list:
    out = search_fts.buscar_texto(query, limite=limite)
    return [r["cliente"] for r in out["resultados"]]


def _top_campo(query: str, campo: str, limite: int = 10) -> list:
    out = search_fts.buscar_texto(query, limite=limite)
    return [r[campo] for r in out["resultados"]]


CASOS = []


def caso(nome, query, contem_no_top, top_n=5, campo="cliente"):
    """Registra um caso: `contem_no_top` deve aparecer no campo `campo` (
    "cliente" por padrao, ou "segmento"/"setor_bndes" pra casos onde o que
    importa e o SETOR encontrado, nao o nome da empresa) de algum dos top_n
    resultados -- nao necessariamente em 1o (alguns casos tem ambiguidade
    legitima documentada, ver comentarios abaixo)."""
    CASOS.append((nome, query, contem_no_top, top_n, campo))


# ---- 1. Tolerancia a erro de digitacao (empresas grandes, 1-2 letras erradas) ----
caso("typo petrobas", "petrobas", "PETROBRAS")
caso("typo petrobrass", "petrobrass", "PETROBRAS")
caso("typo susano->suzano", "susano", "SUZANO")
caso("typo klabim->klabin", "klabim", "KLABIN")
caso("typo brasken->braskem", "brasken", "BRASKEM")
caso("typo stelantis->stellantis", "stelantis", "STELLANTIS")

# ---- 2. Palavras genericas novas (nao podem poluir o ranking) ----
# Todas devem devolver a MESMA cabeca de lista que a busca so pelo termo
# especifico ("hospitais") -- confirma que a palavra generica nova de fato
# saiu do OR de texto livre (tier 5) e nao dominou o ranking sozinha.
_base_hospitais = None


def _checar_generico(nome, query):
    global _base_hospitais
    if _base_hospitais is None:
        _base_hospitais = _top_clientes("hospitais", limite=3)
    top = _top_clientes(query, limite=3)
    ok = top == _base_hospitais
    return ok, top, _base_hospitais


CASOS_GENERICOS = [
    ("generico: nacional de hospitais", "nacional de hospitais"),
    ("generico: brasil de hospitais", "brasil de hospitais"),
    ("generico: brasileira de hospitais", "brasileira de hospitais"),
    ("generico: servicos de hospitais", "servicos de hospitais"),
    ("generico: industrial de hospitais", "industrial de hospitais"),
    ("generico: comercio de hospitais", "comercio de hospitais"),
    ("generico: comercial de hospitais", "comercial de hospitais"),
]

# ---- 3. Guardas de regressao (bugs ja documentados, nao podem voltar) ----
caso("otica != optica (fibra)", "fibra optica", "FIBRA", top_n=3)
caso("fibra otica (grafia atual)", "fibra otica", "FIBRA", top_n=3)
caso("parque eolico != parque de diversao", "parque eolico", "EOLICO", top_n=1)
caso("parque de diversao != parque eolico", "parque de diversao", "DIVERSAO", top_n=3)
caso("grupo belterra (nao poluido por 'grupo')", "grupo belterra", "BELTERRA", top_n=1)
caso("grupo mombak (nao poluido por 'grupo')", "grupo mombak", "MOMBAK", top_n=1)
caso("empresa de hospitais nao poluido por 'empresa'", "empresa de hospitais em SP", "SAUDE",
     top_n=5, campo="segmento")


def main():
    falhas = 0
    total = 0

    print("=== 1+3. Casos com alvo esperado no top-N ===")
    for nome, query, alvo, top_n, campo in CASOS:
        total += 1
        top = _top_campo(query, campo, limite=max(top_n, 5))[:top_n]
        ok = any(alvo.upper() in (c or "").upper() for c in top)
        status = "OK  " if ok else "FAIL"
        if not ok:
            falhas += 1
        print(f"[{status}] {nome:45} query={query!r:35} top{top_n}({campo})={top}")

    print("\n=== 2. Palavras genericas (nao pode poluir o ranking) ===")
    for nome, query in CASOS_GENERICOS:
        total += 1
        ok, top, base = _checar_generico(nome, query)
        status = "OK  " if ok else "FAIL"
        if not ok:
            falhas += 1
        print(f"[{status}] {nome:45} top3={top}  (esperado, igual a 'hospitais': {base})")

    print(f"\n{total - falhas}/{total} casos OK.")
    if falhas:
        print(f"{falhas} FALHA(S) -- ver detalhes acima.")
        sys.exit(1)


if __name__ == "__main__":
    main()
