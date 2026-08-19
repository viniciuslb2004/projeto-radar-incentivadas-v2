"""Baixa os arquivos brutos do BNDES e da FINEP para data/raw/."""
import datetime
from pathlib import Path

import requests

from db import DATA_DIR

RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

BNDES_URL = "https://www.bndes.gov.br/arquivos/central-downloads/operacoes_financiamento/naoautomaticas/naoautomaticas.xlsx"
FINEP_URL = "https://download.finep.gov.br/Contratacao.xlsx"
FINEP_NAO_APROVADOS_URL = "https://download.finep.gov.br/Nao_Aprovados.xlsx"

BNDES_PATH = RAW_DIR / "bndes_naoautomaticas.xlsx"
FINEP_PATH = RAW_DIR / "finep_contratacao.xlsx"
FINEP_NAO_APROVADOS_PATH = RAW_DIR / "finep_nao_aprovados.xlsx"


def _download(url: str, dest: Path, timeout: int = 180) -> Path:
    print(f"Baixando {url} -> {dest}")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.replace(dest)
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
