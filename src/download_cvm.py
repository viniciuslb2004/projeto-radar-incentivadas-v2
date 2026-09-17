"""Baixa o dataset "Ofertas Publicas de Distribuicao" do Portal de Dados Abertos da CVM
para data/raw/ (mesmo padrao de download.py, que ja baixa BNDES/FINEP).

ACHADO REAL (2026-09-16): a URL do dado passada no pedido original terminava em
".csv" (https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS/oferta_distribuicao.csv),
mas essa URL devolve 404 -- confirmado ao vivo. O arquivo de verdade e um .zip no
mesmo caminho (".zip" no lugar de ".csv"), que contem o CSV la dentro (o comentario
original ja dizia "vem dentro de um .zip", so a extensao na URL escrita estava
errada). Corrigido aqui: CVM_URL/META_URL usam .zip; o CSV/TXT extraidos ficam com
os nomes originais dentro do zip.

ACHADO REAL #2 (2026-09-16, mesmo dia, achado pelo coordenador DEPOIS que o pipeline
inicial ja tinha rodado): o zip contem DOIS CSVs (idem o zip do dicionario de dados,
DOIS TXTs) -- "oferta_distribuicao.csv" (dataset original deste pipeline) E
"oferta_resolucao_160.csv" (dataset RELACIONADO mas de schema DIFERENTE -- rito
automatico da Resolucao CVM 160, sucessora da ICVM 400/476 para a maior parte das
emissoes modernas -- ver src/parse_cvm_resolucao160.py e CLAUDE.md). Os DOIS agora
sao baixados/extraidos do MESMO zip (evita baixar o mesmo arquivo de ~5.3MB duas
vezes so pra pegar o segundo membro).

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

# Segundo membro do MESMO zip (ver ACHADO REAL #2 acima) -- Resolucao CVM 160, rito
# automatico. Nome de arquivo proprio (nunca confundir com o staging/tabela final,
# que usa o sufixo "_resolucao_160" por extenso).
RESOLUCAO160_CSV_PATH = RAW_DIR / "cvm_oferta_resolucao_160.csv"
RESOLUCAO160_META_PATH = RAW_DIR / "cvm_meta_oferta_resolucao_160.txt"


def _baixar_zip(url: str, timeout: int = 180) -> bytes:
    print(f"Baixando {url}")
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _extrair_membro(zip_bytes: bytes, dest: Path, nome_preferido_contem: str) -> Path:
    """Extrai do zip (ja em memoria) o arquivo interno cujo nome contem
    `nome_preferido_contem`, para `dest`.

    ACHADO REAL (2026-09-16): o zip da CVM NAO contem um unico arquivo -- tem DOIS
    (ex: "oferta_distribuicao.csv" E "oferta_resolucao_160.csv", esta ultima um
    dataset relacionado mas DIFERENTE -- RCVM 160, sucessora da ICVM 400/476 para o
    rito de oferta, ver Rito_Oferta/Rito_Requerimento no dicionario de dados).
    Selecionar por nome (nao por indice/posicao no zip) evita depender da ordem
    interna do arquivo, que a CVM nao documenta nem garante estavel."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
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
    dados_zip = _baixar_zip(CVM_URL)
    _extrair_membro(dados_zip, CVM_CSV_PATH, "oferta_distribuicao.csv")
    _extrair_membro(dados_zip, RESOLUCAO160_CSV_PATH, "oferta_resolucao_160.csv")

    meta_zip = _baixar_zip(META_URL)
    _extrair_membro(meta_zip, CVM_META_PATH, "meta_oferta_distribuicao.txt")
    _extrair_membro(meta_zip, RESOLUCAO160_META_PATH, "meta_oferta_resolucao_160.txt")

    stamp = RAW_DIR / "last_download_cvm.txt"
    stamp.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
    return CVM_CSV_PATH, CVM_META_PATH, RESOLUCAO160_CSV_PATH, RESOLUCAO160_META_PATH


if __name__ == "__main__":
    download_all()
