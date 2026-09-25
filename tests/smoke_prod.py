"""Smoke test de producao: rotas criticas devem responder 200 com dado nao vazio.
Uso: python tests/smoke_prod.py [BASE_URL]   (sai com codigo 1 se algo falhar)."""
import json
import sys
import time
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://projeto-radar-incentivadas.vercel.app").rstrip("/")
ROTAS = [
    ("/api/status", lambda d: d.get("n_operacoes", 0) > 0),
    ("/api/kpis", lambda d: bool(d)),
    ("/api/busca?q=energia%20solar", lambda d: d.get("n_resultados", 0) > 0),
    ("/api/busca?q=software&uf=SP", lambda d: d.get("n_resultados", 0) > 0),
    # BNB (2026-09-24): agencia publicada, com filtro/Busca/rodape funcionando.
    ("/api/kpis?agencia=BNB", lambda d: d.get("n_operacoes", 0) > 5000),
    ("/api/filtros", lambda d: "BNB" in (d.get("agencias") or [])),
    ("/api/busca?q=supermercado&agencia=BNB", lambda d: d.get("n_resultados", 0) > 0),
    ("/api/status", lambda d: bool(d.get("bnb_fonte_atualizada_em"))),
    ("/api/editais", lambda d: d is not None),
    ("/api/linhas", lambda d: bool(d)),
    ("/api/potenciais/buscar?uso=energia%20solar", lambda d: d is not None),
    # Filtro de Linha em Tendencias (2026-09-25, cascata Agencia -> Linha).
    ("/api/produtos?agencia=BNDES", lambda d: isinstance(d, list) and len(d) > 0),
]


def checar(rota, valida):
    ultimo = ""
    for tentativa in range(3):  # tolera 1-2 falhas transitorias (cold start/pool)
        try:
            with urllib.request.urlopen(BASE + rota, timeout=30) as r:
                corpo = r.read()
                cache = r.headers.get("x-vercel-cache", "-")
                d = json.loads(corpo)
                if isinstance(d, dict) and "erro" in d:
                    ultimo = f"corpo de erro: {d['erro']} (x-vercel-cache={cache})"
                elif not valida(d):
                    ultimo = f"resultado vazio/invalido (x-vercel-cache={cache})"
                else:
                    return None
        except Exception as e:  # noqa: BLE001
            ultimo = f"{type(e).__name__}: {e}"
        time.sleep(3 * (tentativa + 1))
    return ultimo


def checar_consistencia_modal():
    """Contagem do ranking de Tendencias == total do modal (/api/operacoes) pro 1o
    segmento com operacoes no periodo (bug 2026-09-25: segmento em queda abria modal
    vazio / rotulos duplicados por acento). Periodo fixo de 11 meses."""
    q = "setor=INFRAESTRUTURA&data_inicio=2025-11-01&data_fim=2026-10-01"
    try:
        with urllib.request.urlopen(f"{BASE}/api/tendencias/segmentos?{q}", timeout=60) as r:
            segs = json.loads(r.read())["segmentos"]
        s = next(x for x in segs if 0 < x["n_operacoes_atual"] < 300)
        seg = urllib.parse.quote(s["segmento"])
        with urllib.request.urlopen(f"{BASE}/api/operacoes?{q}&segmento={seg}&limit=300", timeout=60) as r:
            n = len(json.loads(r.read()))
        if n != s["n_operacoes_atual"]:
            return f"{s['segmento']}: ranking={s['n_operacoes_atual']} modal={n}"
        if "n_operacoes_anterior" not in s:
            return "ranking sem n_operacoes_anterior"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    return None


def checar_consistencia_modal_produto():
    """Mesma checagem de checar_consistencia_modal, mas com o filtro de Linha
    (produto, 2026-09-25) aplicado -- confirma que /api/tendencias/setores e
    /api/operacoes concordam na contagem quando filtrados pela MESMA linha
    (cascata Agencia -> Linha do filterbar compartilhado, ver common.js)."""
    try:
        with urllib.request.urlopen(f"{BASE}/api/produtos?agencia=BNDES", timeout=30) as r:
            produtos = json.loads(r.read())
        if not produtos:
            return "sem produtos para agencia=BNDES"
        produto = urllib.parse.quote(produtos[0])
        q = f"agencia=BNDES&produto={produto}&data_inicio=2025-11-01&data_fim=2026-10-01"
        with urllib.request.urlopen(f"{BASE}/api/tendencias/setores?{q}", timeout=60) as r:
            setores = json.loads(r.read())["setores"]
        s = next((x for x in setores if x.get("n_operacoes_atual", 0) > 0), None)
        if not s:
            return "sem setor com operacoes para agencia=BNDES&produto=Finem"
        setor = urllib.parse.quote(s["setor"])
        with urllib.request.urlopen(f"{BASE}/api/operacoes?{q}&setor={setor}&limit=300", timeout=60) as r:
            n = len(json.loads(r.read()))
        if n != s["n_operacoes_atual"]:
            return f"{s['setor']}: ranking={s['n_operacoes_atual']} modal={n}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    return None


falhas = 0
erro = checar_consistencia_modal()
print(("FALHA " if erro else "ok    ") + "consistencia ranking==modal (Tendencias/segmentos)" + (f" -> {erro}" if erro else ""))
falhas += bool(erro)
erro = checar_consistencia_modal_produto()
print(("FALHA " if erro else "ok    ") + "consistencia ranking==modal com filtro de Linha (produto)" + (f" -> {erro}" if erro else ""))
falhas += bool(erro)
for rota, valida in ROTAS:
    erro = checar(rota, valida)
    print(("FALHA " if erro else "ok    ") + rota + (f" -> {erro}" if erro else ""))
    falhas += bool(erro)
sys.exit(1 if falhas else 0)
