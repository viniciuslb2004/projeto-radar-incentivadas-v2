"""Smoke test de producao: rotas criticas devem responder 200 com dado nao vazio.
Uso: python tests/smoke_prod.py [BASE_URL]   (sai com codigo 1 se algo falhar)."""
import json
import sys
import time
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


falhas = 0
for rota, valida in ROTAS:
    erro = checar(rota, valida)
    print(("FALHA " if erro else "ok    ") + rota + (f" -> {erro}" if erro else ""))
    falhas += bool(erro)
sys.exit(1 if falhas else 0)
