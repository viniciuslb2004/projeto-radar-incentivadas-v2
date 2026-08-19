"""Enriquece as operacoes da FINEP com Setor/Subsetor BNDES via CNPJ -> CNAE.

Fonte: Dados Abertos de CNPJ da Receita Federal (compartilhamento Nextcloud
publico, acessado via WebDAV com o token do link publico). Job pesado
(varios GB de download) — roda uma vez e depois mensalmente, NAO a cada
refresh semanal. So processa os CNPJs que efetivamente aparecem nas
operacoes da FINEP (nao carrega o cadastro nacional inteiro).
"""
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from db import DATA_DIR, get_connection
from sector_taxonomy import canonical_setor, canonical_subsetor

WEBDAV_BASE = "https://arquivos.receitafederal.gov.br/public.php/webdav"
SHARE_TOKEN = "gn672Ad4CF8N6TK"
AUTH = (SHARE_TOKEN, "")
CNPJ_DIR = f"{WEBDAV_BASE}/Dados/Cadastros/CNPJ"

TMP_DIR = DATA_DIR / "rfb_tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

ESTAB_COLS = [
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial",
    "nome_fantasia", "situacao_cadastral", "data_situacao_cadastral",
    "motivo_situacao_cadastral", "nome_cidade_exterior", "pais",
    "data_inicio_atividade", "cnae_fiscal_principal", "cnae_fiscal_secundaria",
    "tipo_logradouro", "logradouro", "numero", "complemento", "bairro",
    "cep", "uf", "municipio", "ddd1", "telefone1", "ddd2", "telefone2",
    "ddd_fax", "fax", "email", "situacao_especial", "data_situacao_especial",
]
KEEP_COLS = ["cnpj_basico", "cnpj_ordem", "cnpj_dv", "nome_fantasia", "cnae_fiscal_principal"]


def _list_month_folders() -> list:
    resp = requests.request("PROPFIND", f"{CNPJ_DIR}/", auth=AUTH, headers={"Depth": "1"}, timeout=30)
    resp.raise_for_status()
    months = re.findall(r"CNPJ/(\d{4}-\d{2})/", resp.text)
    return sorted(set(months))


def latest_month() -> str:
    months = _list_month_folders()
    if not months:
        raise RuntimeError("Nao encontrei pastas de mes em Dados Abertos CNPJ da RFB")
    return months[-1]


def _target_cnpjs(conn) -> set:
    df = pd.read_sql(
        """
        SELECT cnpj_proponente AS cnpj FROM finep_credito_direto_raw
        UNION
        SELECT cnpj_beneficiario AS cnpj FROM finep_credito_descentralizado_raw
        """,
        conn,
    )
    return set(df["cnpj"].dropna().astype(str))


def _build_divisao_map(conn) -> dict:
    """Faixas tipo 'A01 a A03' -> {divisao_int: (setor_bndes, subsetor_bndes)}."""
    de_para = pd.read_sql("SELECT * FROM de_para_cnae", conn)
    mapping = {}
    for _, row in de_para.iterrows():
        faixa = str(row.get("codigo_cnae_ibge_faixa") or "")
        nums = [int(n) for n in re.findall(r"(\d{2})", faixa)]
        if not nums:
            continue
        setor = canonical_setor(row.get("setor_bndes"))
        subsetor = canonical_subsetor(row.get("subsetor_bndes"))
        for divisao in range(min(nums), max(nums) + 1):
            mapping[divisao] = (setor, subsetor)
    return mapping


def _baixar_cnae_nomes(month: str) -> dict:
    """Cnaes.zip: tabela oficial codigo (7 digitos) -> nome do CNAE. Arquivo minusculo (~20KB)."""
    url = f"{CNPJ_DIR}/{month}/Cnaes.zip"
    resp = requests.get(url, auth=AUTH, timeout=60)
    resp.raise_for_status()
    nomes = {}
    with zipfile.ZipFile(__import__("io").BytesIO(resp.content)) as zf:
        inner_name = zf.namelist()[0]
        with zf.open(inner_name) as f:
            for linha in f.read().decode("latin1").splitlines():
                partes = linha.split(";")
                if len(partes) != 2:
                    continue
                codigo = partes[0].strip('"').strip()
                nome = partes[1].strip('"').strip()
                nomes[codigo] = nome
    return nomes


def _download_to_disk(month: str, filename: str) -> Path:
    url = f"{CNPJ_DIR}/{month}/{filename}"
    dest = TMP_DIR / filename
    print(f"Baixando {filename} ({month})...", flush=True)
    with requests.get(url, auth=AUTH, timeout=1800, stream=True) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"  {filename}: {size_mb:.0f} MB", flush=True)
    return dest


def _scan_zip_for_targets(zip_path: Path, targets: set, found: dict):
    with zipfile.ZipFile(zip_path) as zf:
        inner_name = zf.namelist()[0]
        with zf.open(inner_name) as f:
            reader = pd.read_csv(
                f, sep=";", header=None, names=ESTAB_COLS, usecols=KEEP_COLS,
                dtype=str, encoding="latin1", chunksize=200_000, on_bad_lines="skip",
            )
            for chunk in reader:
                chunk = chunk.dropna(subset=["cnpj_basico", "cnpj_ordem", "cnpj_dv"])
                chunk["cnpj"] = (
                    chunk["cnpj_basico"].str.zfill(8)
                    + chunk["cnpj_ordem"].str.zfill(4)
                    + chunk["cnpj_dv"].str.zfill(2)
                )
                matches = chunk[chunk["cnpj"].isin(targets)]
                for _, row in matches.iterrows():
                    found[row["cnpj"]] = (row["nome_fantasia"], row["cnae_fiscal_principal"])


def enrich(month: str = None, keep_downloads: bool = False) -> int:
    conn = get_connection()
    try:
        targets = _target_cnpjs(conn)
        print(f"CNPJs alvo (FINEP credito): {len(targets)}")
        if not targets:
            print("Nenhum CNPJ para enriquecer (rode parse_finep.py antes).")
            return 0

        divisao_map = _build_divisao_map(conn)
        month = month or latest_month()
        print(f"Usando snapshot RFB: {month}")

        print("Baixando tabela de nomes de CNAE (Cnaes.zip)...")
        cnae_nomes = _baixar_cnae_nomes(month)
        print(f"  {len(cnae_nomes)} codigos CNAE carregados.")

        found = {}
        for i in range(10):
            if len(found) >= len(targets):
                print("Todos os CNPJs alvo ja encontrados, parando antecipadamente.")
                break
            filename = f"Estabelecimentos{i}.zip"
            zip_path = _download_to_disk(month, filename)
            try:
                _scan_zip_for_targets(zip_path, targets, found)
            finally:
                if not keep_downloads:
                    zip_path.unlink(missing_ok=True)
            print(f"  progresso: {len(found)}/{len(targets)} CNPJs encontrados ate agora", flush=True)

        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for cnpj, (nome_fantasia, cnae) in found.items():
            cnae_str = str(cnae) if cnae and str(cnae) != "nan" else None
            divisao = int(cnae_str[:2]) if cnae_str and cnae_str[:2].isdigit() else None
            setor_bndes, subsetor_bndes = divisao_map.get(divisao, (None, None))
            cnae_descricao = cnae_nomes.get(cnae_str) if cnae_str else None
            rows.append((cnpj, nome_fantasia, cnae_str, cnae_descricao, str(divisao) if divisao else None, setor_bndes, subsetor_bndes, now))

        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO cnpj_cnae (cnpj, razao_social, cnae_codigo, cnae_descricao, cnae_divisao, setor_bndes_mapeado, subsetor_bndes_mapeado, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cnpj) DO UPDATE SET
                razao_social=excluded.razao_social,
                cnae_codigo=excluded.cnae_codigo,
                cnae_descricao=excluded.cnae_descricao,
                cnae_divisao=excluded.cnae_divisao,
                setor_bndes_mapeado=excluded.setor_bndes_mapeado,
                subsetor_bndes_mapeado=excluded.subsetor_bndes_mapeado,
                atualizado_em=excluded.atualizado_em
            """,
            rows,
        )
        conn.commit()

        nao_encontrados = len(targets) - len(found)
        print(f"cnpj_cnae: {len(rows)} CNPJs gravados/atualizados. {nao_encontrados} nao encontrados na base da RFB.")
        return len(rows)
    finally:
        conn.close()


if __name__ == "__main__":
    enrich()
