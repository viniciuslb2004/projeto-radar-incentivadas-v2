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

from db import DATA_DIR, get_connection, get_engine
from sector_taxonomy import build_divisao_map

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


def _target_cnpjs(conn, only_unresolved: bool = True) -> set:
    """CNPJs que aparecem nas operacoes de credito da FINEP.

    only_unresolved=True (padrao): exclui os que JA estao em cnpj_cnae -- antes disso,
    o job mensal buscava, do zero, todos os CNPJs ja vistos (inclusive os ja resolvidos
    em meses anteriores), o que so ficava mais pesado com o tempo. Passe False so se
    quiser forcar uma atualizacao de CNPJs ja cacheados (ex: reprocessar apos alguma
    correcao na tabela de-para)."""
    df = pd.read_sql(
        """
        SELECT cnpj_proponente AS cnpj FROM finep_credito_direto_raw
        UNION
        SELECT cnpj_beneficiario AS cnpj FROM finep_credito_descentralizado_raw
        """,
        get_engine(),
    )
    alvo = set(df["cnpj"].dropna().astype(str))
    if only_unresolved:
        ja_cacheados = pd.read_sql("SELECT cnpj FROM cnpj_cnae", get_engine())
        alvo -= set(ja_cacheados["cnpj"].dropna().astype(str))
    return alvo


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


def _rows_para_commit(novos: dict, divisao_map: dict, cnae_nomes: dict, now: str) -> list:
    rows = []
    for cnpj, (nome_fantasia, cnae) in novos.items():
        cnae_str = str(cnae) if cnae and str(cnae) != "nan" else None
        divisao = int(cnae_str[:2]) if cnae_str and cnae_str[:2].isdigit() else None
        setor_bndes, subsetor_bndes = divisao_map.get(divisao, (None, None))
        cnae_descricao = cnae_nomes.get(cnae_str) if cnae_str else None
        rows.append((cnpj, nome_fantasia, cnae_str, cnae_descricao, str(divisao) if divisao else None, setor_bndes, subsetor_bndes, now))
    return rows


def _commit_rows(conn, rows: list) -> None:
    if not rows:
        return
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


def enrich(month: str = None, keep_downloads: bool = False, targets: set = None) -> int:
    """targets=None (padrao): resolve automaticamente os CNPJs da FINEP que ainda nao
    estao em cnpj_cnae (ver _target_cnpjs). Passe um set explicito para escopar a um
    subconjunto especifico (ex: so os CNPJs que apareceram em linhas novas do ultimo
    refresh semanal, em vez de todos os pendentes historicos)."""
    conn = get_connection()
    try:
        if targets is None:
            targets = _target_cnpjs(conn)
        print(f"CNPJs alvo (FINEP credito, ainda sem CNAE no cache): {len(targets)}")
        if not targets:
            print("Nenhum CNPJ pendente para enriquecer.")
            return 0

        divisao_map = build_divisao_map(conn)
        month = month or latest_month()
        print(f"Usando snapshot RFB: {month}")

        print("Baixando tabela de nomes de CNAE (Cnaes.zip)...")
        cnae_nomes = _baixar_cnae_nomes(month)
        print(f"  {len(cnae_nomes)} codigos CNAE carregados.")

        # Cada Estabelecimentos*.zip tem varios GB: grava/commita o que foi achado logo
        # apos escanear cada arquivo, em vez de acumular tudo em memoria ate o final. Assim,
        # se o job cair no meio (rede, disco, timeout do CI), os zips ja escaneados nao
        # precisam ser rebaixados/reescaneados na proxima execucao -- so os restantes.
        found = {}
        total_gravados = 0
        for i in range(10):
            if len(found) >= len(targets):
                print("Todos os CNPJs alvo ja encontrados, parando antecipadamente.")
                break
            filename = f"Estabelecimentos{i}.zip"
            zip_path = _download_to_disk(month, filename)
            antes = set(found.keys())
            try:
                _scan_zip_for_targets(zip_path, targets, found)
            finally:
                if not keep_downloads:
                    zip_path.unlink(missing_ok=True)
            novos = {cnpj: found[cnpj] for cnpj in found.keys() - antes}
            if novos:
                now = datetime.now(timezone.utc).isoformat()
                rows = _rows_para_commit(novos, divisao_map, cnae_nomes, now)
                _commit_rows(conn, rows)
                total_gravados += len(rows)
            print(f"  progresso: {len(found)}/{len(targets)} CNPJs encontrados ate agora ({total_gravados} ja gravados no banco)", flush=True)

        nao_encontrados = len(targets) - len(found)
        print(f"cnpj_cnae: {total_gravados} CNPJs gravados/atualizados. {nao_encontrados} nao encontrados na base da RFB.")
        return total_gravados
    finally:
        conn.close()


if __name__ == "__main__":
    enrich()
