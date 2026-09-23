"""Regra do cache publico da CDN (webapp/main.py::_deve_cachear_publico)."""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ), str(RAIZ / "src")]
os.environ.setdefault("DATABASE_URL", "postgresql://teste@localhost/teste")

from webapp.main import _deve_cachear_publico as f  # noqa: E402

OK = b'{"query":"x","resultados":[{"id":1}]}'


def test_cacheia_200_ok():
    assert f("GET", "/api/busca", 200, {}, OK)


def test_nao_cacheia_erro_com_200():
    assert not f("GET", "/api/busca", 200, {}, b'{"erro":"motor de busca indisponivel no momento"}')


def test_nao_cacheia_nao_200_post_cookie_vazio_fora_da_lista():
    assert not f("GET", "/api/busca", 500, {}, OK)
    assert not f("GET", "/api/busca", 503, {}, OK)
    assert not f("POST", "/api/busca", 200, {}, OK)
    assert not f("GET", "/api/busca", 200, {"set-cookie": "a=b"}, OK)
    assert not f("GET", "/api/busca", 200, {}, b"")
    assert not f("GET", "/api/me", 200, {}, OK)
    assert not f("GET", "/api/busca/termo", 200, {}, OK)
