"""Entrypoint minimo para o runtime Python da Vercel.

A Vercel roda projetos Python "existentes" com funcoes baseadas em arquivo dentro
de `/api` carregando, de cada arquivo, um objeto ASGI/WSGI de nome `app` (ver
https://vercel.com/docs/functions/runtimes/python/api-directory) -- este arquivo
so existe para satisfazer essa convencao. NENHUMA logica do produto mora aqui: a
aplicacao de verdade continua inteira em webapp/main.py (o MESMO arquivo usado
localmente via `uvicorn webapp.main:app`), para nao existirem duas fontes de
verdade da API.

sys.path precisa ganhar (1) a raiz do repo, para `import webapp` funcionar, e
(2) `src/`, para os imports "soltos" que webapp/main.py e os modulos dentro de
src/ fazem entre si (`from db import get_connection`, `from search import ...`,
etc.) -- mesmo padrao que webapp/main.py ja usa para src/ (ver o
`sys.path.insert` logo no topo daquele arquivo), replicado aqui porque o
diretorio de trabalho/contexto de import do runtime da Vercel pode nao ser o
mesmo do `uvicorn` local. Os dois inserts sao idempotentes o bastante (path
duplicado nao quebra nada) mesmo que webapp/main.py repita o insert de src/.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from webapp.main import app  # noqa: E402 -- import so depois de ajustar sys.path, de proposito

__all__ = ["app"]
