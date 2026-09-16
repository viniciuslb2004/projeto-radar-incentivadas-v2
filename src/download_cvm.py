"""Baixa o dataset "Ofertas Publicas de Distribuicao" do Portal de Dados Abertos da CVM
para data/raw/ (mesmo padrao de download.py, que ja baixa BNDES/FINEP).

ACHADO REAL (2026-09-16): a URL do dado passada no pedido original terminava em
".csv" (https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS/oferta_distribuicao.csv),
mas essa URL devolve 404 -- confirmado ao vivo. O arquivo de verdade e um .zip no
mesmo caminho (".zip" no lugar de ".csv"), que contem o CSV la dentro (o comentario
original ja dizia "vem dentro de um .zip", so a extensao na URL escrita estava
errada). Corrigido aqui: CVM_URL/META_URL usam .zip; o CSV/TXT extraidos ficam com
os nomes originais dentro do zip.

Licenca ODbL, mantido pela SRE/CVM, atualizado diariamente (confirmado: o mesmo link
sempre aponta para o snapshot mais recente, sem versionamento por data na URL)."""
import datetime
import io
import zipfile
from pathlib import Path

import requests

from db import DATA_DIR

RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

CVM_URL = "https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS/oferta_distribuicao.zip"
META_URL = "https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/META/meta_oferta_distribuicao.zip"

CVM_CSV_PATH = RAW_DIR / "cvm_oferta_distribuicao.csv"
CVM_META_PATH = RAW_DIR / "cvm_meta_oferta_distribuicao.txt"


def _download_and_extract(url: str, dest: Path, nome_preferido_contem: str, timeout: int = 180) -> Path:
    """Baixa um .zip inteiro em memoria (arquivos pequenos, poucos MB -- ver tamanhos
    reais confirmados: ~5.3MB o CSV zipado, ~3KB o dicionario de dados) e extrai o
    arquivo interno cujo nome contem `nome_preferido_contem` para `dest`.

    ACHADO REAL (2026-09-16): o zip da CVM NAO contem um unico arquivo -- tem DOIS
    (ex: "oferta_distribuicao.csv" E "oferta_resolucao_160.csv", esta ultima um
    dataset relacionado mas DIFERENTE -- RCVM 160, sucessora da ICVM 400/476 para o
    rito de oferta, ver Rito_Oferta no dicionario de dados -- fora do escopo deste
    pedido). Selecionar por nome (nao por indice/posicao no zip) evita depender da
    ordem interna do arquivo, que a CVM nao documenta nem garante estavel."""
    print(f"Baixando {url} -> {dest}")
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        nomes = zf.namelist()
        candidatos = [n for n in nomes if nome_preferido_contem in n]
        if len(nomes) != 1:
            print(f"  aviso: zip tem {len(nomes)} arquivos internos: {nomes} (usando o que contem {nome_preferido_contem!r})")
        if not candidatos:
            raise RuntimeError(f"Nenhum arquivo no zip contem {nome_preferido_contem!r}: {nomes}")
        inner_name = candidatos[0]
        with zf.open(inner_name) as f:
            conteudo = f.read()
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(conteudo)
    tmp.replace(dest)
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"OK: {dest.name} ({size_mb:.1f} MB, extraido de {inner_name!r})")
    return dest


def download_all():
    _download_and_extract(CVM_URL, CVM_CSV_PATH, "oferta_distribuicao.csv")
    _download_and_extract(META_URL, CVM_META_PATH, "meta_oferta_distribuicao.txt")
    stamp = RAW_DIR / "last_download_cvm.txt"
    stamp.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
    return CVM_CSV_PATH, CVM_META_PATH


if __name__ == "__main__":
    download_all()
