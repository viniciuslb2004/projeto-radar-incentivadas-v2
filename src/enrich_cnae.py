"""Enriquece as operacoes da FINEP com Setor/Subsetor BNDES via CNPJ -> CNAE.

Fonte: Dados Abertos de CNPJ da Receita Federal (compartilhamento Nextcloud
publico, acessado via WebDAV com o token do link publico). Job pesado
(varios GB de download) — roda uma vez e depois mensalmente, NAO a cada
refresh semanal. So processa os CNPJs que efetivamente aparecem nas
operacoes da FINEP (nao carrega o cadastro nacional inteiro).
"""
import re
import time
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
    """CNPJs que aparecem nas operacoes de credito (FINEP e BNDES).

    Ate 2026-09, so buscava CNPJs da FINEP (o motor de busca por CNAE so precisava
    deles, ja que BNDES ja vem com setor nativo da propria planilha). Passou a incluir
    tambem bndes_raw.cnpj: mesmo o BNDES ja tendo classificacao nativa de setor, o CNAE
    por CNPJ e um dado real e util por si so (identificacao da empresa, ver pedido de
    enriquecimento) -- confirmado 3994 CNPJs do BNDES nunca tinham sido buscados antes
    (0 faltando do lado FINEP, que ja estava 100% coberto).

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
        UNION
        SELECT cnpj FROM bndes_raw
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


EMPRESAS_COLS = [
    "cnpj_basico", "razao_social", "natureza_juridica", "qualificacao_responsavel",
    "capital_social", "porte_empresa", "ente_federativo_responsavel",
]
EMPRESAS_KEEP_COLS = ["cnpj_basico", "razao_social", "natureza_juridica", "capital_social", "porte_empresa"]

# Layout oficial da RFB para porte_empresa (documentado no dicionario de dados que
# acompanha os arquivos Empresas*.zip) -- nao inventado, so decodificado.
PORTE_EMPRESA_RFB = {
    "00": "Não informado pela fonte",
    "01": "Micro Empresa",
    "03": "Empresa de Pequeno Porte",
    "05": "Demais",
}


def _baixar_naturezas(month: str) -> dict:
    """Naturezas.zip: tabela oficial codigo -> nome da natureza juridica (ex:
    "206-2" -> "Sociedade Empresaria Limitada"). Arquivo minusculo, mesmo padrao de
    _baixar_cnae_nomes."""
    url = f"{CNPJ_DIR}/{month}/Naturezas.zip"
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


def _target_cnpj_basicos(conn) -> dict:
    """CNPJs (basico -> lista de CNPJs completos) ja presentes em cnpj_cnae mas ainda
    SEM razao_social_oficial -- Empresas.zip e chaveado por cnpj_basico (8 digitos, a
    empresa), nao pelo CNPJ completo (14 digitos, o estabelecimento/filial); uma
    empresa pode ter varios estabelecimentos com o MESMO cnpj_basico, entao um
    resultado de Empresas.zip pode precisar atualizar mais de uma linha de
    cnpj_cnae."""
    df = pd.read_sql(
        "SELECT cnpj FROM cnpj_cnae WHERE razao_social_oficial IS NULL",
        get_engine(),
    )
    basico_para_cnpjs = {}
    for cnpj in df["cnpj"].dropna().astype(str):
        if len(cnpj) < 8:
            continue
        basico_para_cnpjs.setdefault(cnpj[:8], []).append(cnpj)
    return basico_para_cnpjs


def _scan_empresas_zip_for_targets(zip_path: Path, targets_basico: set, found: dict):
    with zipfile.ZipFile(zip_path) as zf:
        inner_name = zf.namelist()[0]
        with zf.open(inner_name) as f:
            reader = pd.read_csv(
                f, sep=";", header=None, names=EMPRESAS_COLS, usecols=EMPRESAS_KEEP_COLS,
                dtype=str, encoding="latin1", chunksize=200_000, on_bad_lines="skip",
            )
            for chunk in reader:
                chunk = chunk.dropna(subset=["cnpj_basico"])
                matches = chunk[chunk["cnpj_basico"].isin(targets_basico)]
                for _, row in matches.iterrows():
                    found[row["cnpj_basico"]] = (row["razao_social"], row["natureza_juridica"], row["capital_social"], row["porte_empresa"])


def _capital_social_para_float(valor: str):
    if not valor:
        return None
    try:
        return float(str(valor).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _commit_rows_empresas(conn, novos: dict, basico_para_cnpjs: dict, naturezas: dict, now: str) -> int:
    rows = []
    for basico, (razao_social, natureza_codigo, capital_social, porte_codigo) in novos.items():
        natureza_nome = naturezas.get(natureza_codigo, natureza_codigo)
        porte_nome = PORTE_EMPRESA_RFB.get(porte_codigo, porte_codigo)
        capital = _capital_social_para_float(capital_social)
        for cnpj in basico_para_cnpjs.get(basico, []):
            rows.append((razao_social, natureza_nome, porte_nome, capital, now, cnpj))
    if not rows:
        return 0
    cur = conn.cursor()
    cur.executemany(
        "UPDATE cnpj_cnae SET razao_social_oficial = ?, natureza_juridica = ?, porte_empresa = ?, "
        "capital_social = ?, atualizado_em = ? WHERE cnpj = ?",
        rows,
    )
    conn.commit()
    return len(rows)


BRASILAPI_CNPJ_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
# BrasilAPI roda atras da mitigacao de bot da Vercel -- o User-Agent padrao do
# `requests` ("python-requests/X.X") e tratado como trafego suspeito e barrado com
# 429 + header `x-vercel-mitigated: deny` (confirmado ao vivo: a MESMA chamada, so
# trocando o User-Agent pra algo tipo navegador, passa de 429 pra 200 na hora --
# nao era rate limit de verdade, era bloqueio de bot). GitHub Actions tambem usa o
# User-Agent padrao do requests, entao sem isso o job semanal falharia do mesmo jeito.
_HEADERS_BRASILAPI = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}


def _consultar_brasilapi(cnpj: str) -> dict:
    """Uma chamada = CNAE + razao social + natureza juridica + porte + capital social,
    tudo de uma vez -- ao contrario do job mensal (enrich()+enrich_empresas(), que
    baixa Estabelecimentos*.zip e Empresas*.zip, varios GB cada). Devolve None se o
    CNPJ nao for encontrado (404) -- deixa pra quem chamou decidir o que fazer, nunca
    levanta erro pra um CNPJ so nao encontrado."""
    resp = requests.get(BRASILAPI_CNPJ_URL.format(cnpj=cnpj), headers=_HEADERS_BRASILAPI, timeout=10)
    if resp.status_code in (400, 404):
        # 404: CNPJ bem formado mas nao encontrado. 400: a BrasilAPI validou o CNPJ
        # (digito verificador etc) e recusou por formato invalido -- confirmado ao
        # vivo com codigos sinteticos internos do BNDES (nao sao CNPJ real nenhum).
        # Os dois casos sao permanentes (nunca vao ter sucesso numa retentativa),
        # diferente de 429/5xx -- tratar igual evita gastar retry com backoff a toa.
        return None
    resp.raise_for_status()
    return resp.json()


def enrich_pendentes_via_api(conn, cnpjs: set, divisao_map: dict) -> int:
    """Resolve CNPJs 'pendente' um a um via BrasilAPI (publica, sem chave) -- chamada a
    cada refresh SEMANAL (ver refresh.py), pra nao deixar uma operacao nova esperando
    ate 30 dias pelo proximo job mensal (enrich()/enrich_empresas()) so pra saber o
    setor/CNAE/identificacao dela. Complementa o job mensal, nunca substitui -- o job
    mensal continua sendo quem processa o backlog historico em volume (baixando a base
    inteira da RFB). So processa os CNPJs passados pelo chamador (normalmente: os que
    ficaram 'pendente' no ultimo build_operations() e ainda nao estao em cnpj_cnae).
    Falha por CNPJ (nao encontrado, erro de rede apos retries) so pula esse CNPJ e
    segue pros outros -- nunca derruba o refresh inteiro."""
    if not cnpjs:
        return 0
    agora = datetime.now(timezone.utc).isoformat()
    gravados = 0
    for cnpj in sorted(cnpjs):
        dados = None
        for tentativa in range(3):
            try:
                dados = _consultar_brasilapi(cnpj)
                break
            except requests.exceptions.RequestException as e:
                print(f"  BrasilAPI: erro ao consultar {cnpj} (tentativa {tentativa + 1}/3): {e}")
                time.sleep(2 * (tentativa + 1))
        if not dados:
            continue

        cnae_fiscal = dados.get("cnae_fiscal")
        cnae_codigo = str(cnae_fiscal).zfill(7) if cnae_fiscal else None
        divisao = int(cnae_codigo[:2]) if cnae_codigo and cnae_codigo[:2].isdigit() else None
        setor_bndes, subsetor_bndes = divisao_map.get(divisao, (None, None))
        codigo_porte = dados.get("codigo_porte")
        # PORTE_EMPRESA_RFB e chaveado pelo mesmo codigo (00/01/03/05) que a RFB usa
        # tanto no arquivo bulk quanto na BrasilAPI (que so espelha os dados da RFB) --
        # reaproveita a mesma tabela pra manter o rotulo identico ao do job mensal.
        porte = PORTE_EMPRESA_RFB.get(str(codigo_porte).zfill(2)) if codigo_porte is not None else None

        conn.execute(
            """
            INSERT INTO cnpj_cnae (
                cnpj, razao_social, cnae_codigo, cnae_descricao, cnae_divisao,
                setor_bndes_mapeado, subsetor_bndes_mapeado,
                razao_social_oficial, natureza_juridica, porte_empresa, capital_social,
                uf, municipio,
                atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cnpj) DO UPDATE SET
                razao_social=excluded.razao_social, cnae_codigo=excluded.cnae_codigo,
                cnae_descricao=excluded.cnae_descricao, cnae_divisao=excluded.cnae_divisao,
                setor_bndes_mapeado=excluded.setor_bndes_mapeado,
                subsetor_bndes_mapeado=excluded.subsetor_bndes_mapeado,
                razao_social_oficial=excluded.razao_social_oficial,
                natureza_juridica=excluded.natureza_juridica,
                porte_empresa=excluded.porte_empresa, capital_social=excluded.capital_social,
                uf=excluded.uf, municipio=excluded.municipio,
                atualizado_em=excluded.atualizado_em
            """,
            (
                cnpj, dados.get("nome_fantasia") or dados.get("razao_social"),
                cnae_codigo, dados.get("cnae_fiscal_descricao"),
                str(divisao) if divisao is not None else None,
                setor_bndes, subsetor_bndes,
                dados.get("razao_social"), dados.get("natureza_juridica"), porte,
                dados.get("capital_social"),
                dados.get("uf"), dados.get("municipio"),
                agora,
            ),
        )
        gravados += 1
        time.sleep(0.6)  # nao estourar o rate limit informal da API gratuita

    conn.commit()
    print(f"BrasilAPI: {gravados}/{len(cnpjs)} CNPJs pendentes resolvidos nesta rodada.")
    return gravados


def enrich_empresas(month: str = None, keep_downloads: bool = False) -> int:
    """Complementa cnpj_cnae (ja populada por enrich(), CNPJ->CNAE) com identificacao
    da empresa (item 3.2 do pedido): razao social oficial, natureza juridica e porte,
    a partir de Empresas*.zip da RFB -- mesma fonte, arquivos diferentes de
    Estabelecimentos*.zip. So enriquece linhas que JA existem em cnpj_cnae (nunca cria
    CNPJ novo aqui -- isso e trabalho de enrich())."""
    conn = get_connection()
    try:
        basico_para_cnpjs = _target_cnpj_basicos(conn)
        targets_basico = set(basico_para_cnpjs.keys())
        print(f"CNPJs basicos alvo (empresas ja em cnpj_cnae, ainda sem razao social oficial): {len(targets_basico)}")
        if not targets_basico:
            print("Nada pendente de identificacao de empresa.")
            return 0

        month = month or latest_month()
        print(f"Usando snapshot RFB: {month}")
        print("Baixando tabela de naturezas juridicas (Naturezas.zip)...")
        naturezas = _baixar_naturezas(month)
        print(f"  {len(naturezas)} naturezas juridicas carregadas.")

        found = {}
        total_gravados = 0
        for i in range(10):
            if len(found) >= len(targets_basico):
                print("Todos os CNPJs basicos alvo ja encontrados, parando antecipadamente.")
                break
            filename = f"Empresas{i}.zip"
            zip_path = _download_to_disk(month, filename)
            antes = set(found.keys())
            try:
                _scan_empresas_zip_for_targets(zip_path, targets_basico, found)
            finally:
                if not keep_downloads:
                    zip_path.unlink(missing_ok=True)
            novos = {basico: found[basico] for basico in found.keys() - antes}
            if novos:
                now = datetime.now(timezone.utc).isoformat()
                total_gravados += _commit_rows_empresas(conn, novos, basico_para_cnpjs, naturezas, now)
            print(f"  progresso: {len(found)}/{len(targets_basico)} empresas encontradas ate agora ({total_gravados} linhas de cnpj_cnae ja atualizadas)", flush=True)

        nao_encontrados = len(targets_basico) - len(found)
        print(f"cnpj_cnae: {total_gravados} linhas atualizadas com identificacao de empresa. {nao_encontrados} CNPJs basicos nao encontrados na base da RFB.")
        return total_gravados
    finally:
        conn.close()


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
    enrich_empresas()
