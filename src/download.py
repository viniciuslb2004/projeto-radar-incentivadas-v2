"""Baixa os arquivos brutos do BNDES e da FINEP para data/raw/."""
import datetime
import time
from pathlib import Path

import requests

from db import DATA_DIR

# Falhas transitorias de rede (timeout, conexao recusada/resetada, erro 5xx do
# servidor) valem retry -- uma instabilidade momentanea da rede do runner do
# GitHub Actions ou do servidor do BNDES/FINEP nao deveria abortar o pipeline
# inteiro antes ate do parsing comecar. Erros de CONTEUDO (ex: 404, xlsx
# corrompido, aba faltando) NAO entram aqui de proposito -- repetir a mesma
# requisicao nao muda um erro desses, e mascarar isso com retry so atrasaria o
# diagnostico real.
_RETRY_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)
_MAX_TENTATIVAS = 3
_BACKOFF_BASE_SEGUNDOS = 5

RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

BNDES_URL = "https://www.bndes.gov.br/arquivos/central-downloads/operacoes_financiamento/naoautomaticas/naoautomaticas.xlsx"
FINEP_URL = "https://download.finep.gov.br/Contratacao.xlsx"
FINEP_NAO_APROVADOS_URL = "https://download.finep.gov.br/Nao_Aprovados.xlsx"

BNDES_PATH = RAW_DIR / "bndes_naoautomaticas.xlsx"
FINEP_PATH = RAW_DIR / "finep_contratacao.xlsx"
FINEP_NAO_APROVADOS_PATH = RAW_DIR / "finep_nao_aprovados.xlsx"


def _e_falha_transitoria(exc: Exception) -> bool:
    """Timeout/conexao (ver `_RETRY_EXCEPTIONS`) sempre vale retry. Um HTTPError
    so vale retry se for 5xx (erro do lado do servidor, pode ser momentaneo) --
    um 4xx (ex: 404, URL mudou de verdade) e um erro de conteudo/permanente,
    repetir a mesma requisicao nao resolve."""
    if isinstance(exc, _RETRY_EXCEPTIONS):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status is not None and status >= 500
    return False


def _download(url: str, dest: Path, timeout: int = 180) -> Path:
    tentativa = 0
    while True:
        tentativa += 1
        try:
            print(f"Baixando {url} -> {dest} (tentativa {tentativa}/{_MAX_TENTATIVAS})")
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".tmp")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
            break
        except Exception as exc:
            if tentativa >= _MAX_TENTATIVAS or not _e_falha_transitoria(exc):
                raise
            espera = _BACKOFF_BASE_SEGUNDOS * tentativa
            print(f"  falha transitoria ({exc!r}), tentando de novo em {espera}s...")
            time.sleep(espera)

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"OK: {dest.name} ({size_mb:.1f} MB)")
    return dest


def download_all():
    _download(BNDES_URL, BNDES_PATH)
    _download(FINEP_URL, FINEP_PATH)
    _download(FINEP_NAO_APROVADOS_URL, FINEP_NAO_APROVADOS_PATH)
    stamp = RAW_DIR / "last_download.txt"
    stamp.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
    return BNDES_PATH, FINEP_PATH, FINEP_NAO_APROVADOS_PATH


if __name__ == "__main__":
    download_all()
