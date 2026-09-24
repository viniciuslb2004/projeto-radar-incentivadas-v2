"""Extrator do BNB (Banco do Nordeste) -- operacoes de credito, SOMENTE pessoa juridica.

Fonte: relatorio Power BI publico ("publish to web") embutido em
https://www.bnb.gov.br/acesso-a-informacao/dados-de-contratacoes/consulta-de-operacoes-de-credito
Usa o mesmo endpoint de query (`/public/reports/querydata`) que o proprio relatorio chama,
com a chave publica do embed (X-PowerBI-ResourceKey). O visual do relatorio so mostra um
CPF/CNPJ por vez (filtro `_Qtde CPF/CNPJ = 1`); aqui a query e montada sobre a mesma
tabela do modelo (AT509_PortalTranspOperPublicaCliente), fatiada em janelas
ano x UF x fundo (e mes, se uma janela passar do limite de linhas por query).

Regras:
- Recorte: so contratos com valor contratado > R$ 1.000.000,00 (decisao do usuario
  2026-09-24), filtrado na propria query e reconciliado sobre o mesmo recorte.
- Filtro PJ no servidor (CpfCnpj contem '/', formato "XXXXXXXX/XXXX-XX") E validacao do
  digito verificador no cliente: qualquer documento que nao seja CNPJ valido de 14
  digitos e descartado e so contado -- CPF/nome de pessoa fisica nunca e gravado.
- LGPD: razao social de MEI vem da fonte como "NOME 12345678901" (CPF do titular). Toda
  sequencia isolada de 11 digitos e removida de `cliente` antes de gravar (mascarar_cpf).
- `fundo` = texto exato da fonte (coluna Fonte); `cod_programa_credito` = codigo cru.
- Idempotente: upsert por (cod_contrato, num_operacao, cnpj, cod_area_operacional). Retomavel: janelas ja
  reconciliadas (bnb_reconciliacao) contra o mesmo refresh do dataset sao puladas.
- Ritmo <= 1 req/s com backoff exponencial. Insert em lotes, commit por lote.

Uso: python src/bnb.py [--force] [--anos 2016-2026]
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import requests

from db import get_connection

RESOURCE_KEY = "b4c9dd13-3bec-4ebb-8652-eff241f67162"
CLUSTER = "https://wabi-south-central-us-api.analysis.windows.net"
ENTIDADE = "AT509_PortalTranspOperPublicaCliente"
ENTIDADE_AGENCIA = "DIM_Agencia_S546"
HEADERS = {"X-PowerBI-ResourceKey": RESOURCE_KEY, "User-Agent": "Mozilla/5.0 (Radar Credito Incentivado)"}
LIMITE_JANELA = 30000
INTERVALO_MIN_S = 1.0
LOTE_INSERT = 1000

_ultimo_req = [0.0]
_modelo = {}

# (propriedade na fonte, coluna em bnb_raw, entidade)
COLUNAS = [
    ("CodContrato", "cod_contrato", "a"),
    ("NumOperacao", "num_operacao", "a"),
    ("CpfCnpj", "cnpj", "a"),
    ("Cliente", "cliente", "a"),
    ("UF", "uf", "a"),
    ("CodAgencia", "cod_agencia", "a"),
    ("Agência", "agencia", "d"),
    ("CodAreaOperacional", "cod_area_operacional", "a"),
    ("DataContratacao", "data_contratacao", "a"),
    ("DatVencimentoFim", "data_vencimento_fim", "a"),
    ("Fonte", "fundo", "a"),
    ("CodFonteRecurso", "cod_fonte_recurso", "a"),
    ("CodProgramaCredito", "cod_programa_credito", "a"),
    ("CodCliente", "cod_cliente", "a"),
    ("TaxaJurosAA", "taxa_juros_aa", "a"),
    ("Custo", "custo", "a"),
    ("Indexador", "indexador", "a"),
    ("ValorContratado", "valor_contratado", "a"),
    ("Prazo Total", "prazo_total_meses", "a"),
    ("Prazo Carência", "prazo_carencia_meses", "a"),
    ("Prazo Amortização", "prazo_amortizacao_meses", "a"),
    ("CarenciaTotal", "carencia_total", "a"),
    ("IdentPeriodicidadePrincipal", "periodicidade_principal", "a"),
]
COLS_DATA = {"data_contratacao", "data_vencimento_fim"}
COLS_INT = {"num_operacao", "cod_agencia", "cod_area_operacional", "cod_fonte_recurso", "cod_programa_credito", "cod_cliente"}
COLS_FLOAT = {"taxa_juros_aa", "prazo_total_meses", "prazo_carencia_meses", "prazo_amortizacao_meses", "carencia_total"}


# ---------------------------------------------------------------- Power BI helpers
def _ref(src, prop):
    return {"Column": {"Expression": {"SourceRef": {"Source": src}}, "Property": prop}}


def _col(prop, src="a"):
    return {**_ref(src, prop), "Name": f"{src}.{prop}"}


def _agg(prop, func, src="a"):
    # func: 0=Sum, 5=Count (nao-nulo)
    return {"Aggregation": {"Expression": _ref(src, prop), "Function": func}, "Name": f"agg{func}({prop})"}


def _lit(v):
    return {"Literal": {"Value": v}}


def _cmp(prop, kind, lit):
    # kind: 0 =, 1 >, 2 >=, 4 <
    return {"Comparison": {"ComparisonKind": kind, "Left": _ref("a", prop), "Right": _lit(lit)}}


def _and(*conds):
    c = conds[0]
    for x in conds[1:]:
        c = {"And": {"Left": c, "Right": x}}
    return c


def _dt(d):
    return f"datetime'{d}T00:00:00'"


def _str(s):
    return "'" + s.replace("'", "''") + "'"


FILTRO_PJ = {"Contains": {"Left": _ref("a", "CpfCnpj"), "Right": _lit("'/'")}}
# Recorte (decisao do usuario 2026-09-24): so contratos com valor ESTRITAMENTE maior que
# R$ 1.000.000,00 -- filtrado no servidor (ComparisonKind 1 = GreaterThan) e conferido de
# novo no cliente antes de gravar. Reconciliacao compara o mesmo recorte dos dois lados.
VALOR_MINIMO_EXCLUSIVO = Decimal("1000000.00")
FILTRO_VALOR = {"Comparison": {"ComparisonKind": 1, "Left": _ref("a", "ValorContratado"), "Right": _lit("1000000D")}}


def _modelo_info():
    if not _modelo:
        r = _post_get("GET", f"{CLUSTER}/public/reports/{RESOURCE_KEY}/modelsAndExploration?preferReadOnlySession=true")
        m = r["models"][0]
        _modelo.update(
            model_id=m["id"], dataset_id=m["dbName"],
            report_id=r["exploration"]["report"]["objectId"],
            last_refresh=m.get("LastRefreshTime"),
        )
    return _modelo


def _post_get(method, url, body=None):
    espera = 5
    for tentativa in range(8):
        dt = time.time() - _ultimo_req[0]
        if dt < INTERVALO_MIN_S:
            time.sleep(INTERVALO_MIN_S - dt)
        _ultimo_req[0] = time.time()
        try:
            resp = requests.request(method, url, json=body, headers=HEADERS, timeout=180)
            if resp.status_code == 200:
                return resp.json()
            msg = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            msg = repr(e)
        print(f"  aviso: {msg}; nova tentativa em {espera}s", flush=True)
        time.sleep(espera)
        espera = min(espera * 2, 300)
    raise RuntimeError(f"Power BI nao respondeu apos varias tentativas: {url}")


def _query(select, where_conds, top, com_agencia=False):
    info = _modelo_info()
    frm = [{"Name": "a", "Entity": ENTIDADE, "Type": 0}]
    if com_agencia:
        frm.append({"Name": "d", "Entity": ENTIDADE_AGENCIA, "Type": 0})
    q = {"Version": 2, "From": frm, "Select": select, "Where": [{"Condition": c} for c in where_conds]}
    body = {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": q,
                "Binding": {
                    "Primary": {"Groupings": [{"Projections": list(range(len(select)))}]},
                    "DataReduction": {"DataVolume": 4, "Primary": {"Window": {"Count": top}}},
                    "Version": 1,
                },
                "ExecutionMetricsKind": 1,
            }}]},
            "QueryId": "",
            "ApplicationContext": {"DatasetId": info["dataset_id"], "Sources": [{"ReportId": info["report_id"]}]},
        }],
        "cancelQueries": [],
        "modelId": info["model_id"],
    }
    j = _post_get("POST", f"{CLUSTER}/public/reports/querydata?synchronous=true", body)
    return _decode(j)


def _decode(j):
    """Decodifica o formato DSR compactado do Power BI (bitmask R = repete valor da
    linha anterior, bitmask Ø = nulo, DN = indice num dicionario de valores)."""
    data = j["results"][0]["result"]["data"]
    dsr = data["dsr"]
    if "DS" not in dsr:
        raise RuntimeError("Resposta DSR inesperada: " + json.dumps(dsr)[:500])
    ds = dsr["DS"][0]
    if ds.get("Msg") or ds.get("odata.error"):
        raise RuntimeError("Erro na query: " + json.dumps(ds)[:500])
    vd = ds.get("ValueDicts", {})
    rows, schema, prev = [], None, None
    ph = ds.get("PH", [{}])[0]
    for r in ph.get("DM0", []):
        if "S" in r:
            schema = r["S"]
        rep, nul = r.get("R", 0), r.get("Ø", 0)
        vals = iter(r.get("C", []))
        row = []
        for i, s in enumerate(schema):
            if (rep >> i) & 1:
                v = prev[i]
            elif (nul >> i) & 1:
                v = None
            else:
                v = next(vals)
                if "DN" in s and isinstance(v, int):
                    v = vd[s["DN"]][v]
            row.append(v)
        rows.append(row)
        prev = row
    completo = bool(ds.get("IC", True)) and "RT" not in ds
    return rows, completo


# ---------------------------------------------------------------- validacao
def cnpj_valido(doc):
    """Retorna os 14 digitos se `doc` for um CNPJ valido (DV conferido), senao None."""
    if not doc:
        return None
    d = "".join(ch for ch in str(doc) if ch.isdigit())
    if len(d) != 14 or d == d[0] * 14:
        return None
    def dv(base, pesos):
        s = sum(int(x) * p for x, p in zip(base, pesos)) % 11
        return "0" if s < 2 else str(11 - s)
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    if dv(d[:12], p1) != d[12] or dv(d[:13], [6] + p1) != d[13]:
        return None
    return d


# CPF puro (11 digitos; 12 cobre CPF digitado com um digito a mais na fonte) ou pontuado.
# 14 digitos (CNPJ usado como nome) e publico e fica.
_RE_CPF = re.compile(r"(?<!\d)(?:\d{11,12}|\d{3}\.\d{3}\.\d{3}-\d{2})(?!\d)")


def mascarar_cpf(nome):
    """Remove sequencias de 11 digitos (CPF, com ou sem pontuacao) de um nome (LGPD/MEI)."""
    if not nome:
        return nome
    return re.sub(r"\s{2,}", " ", _RE_CPF.sub("", nome)).strip(" -") or None


def _dinheiro(v):
    if v is None:
        return None
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _conv(nome, v):
    if v is None or v == "":
        return None
    if nome in COLS_DATA:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).date()
    if nome in COLS_INT:
        return int(v)
    if nome in COLS_FLOAT:
        return float(v)
    if nome == "valor_contratado":
        return _dinheiro(v)
    return str(v)


# ---------------------------------------------------------------- extracao
def esperado_por_ano(ano):
    """Query agregada do proprio dataset: linhas e soma de valor por UF x fundo (so PJ)."""
    rows, completo = _query(
        [_col("UF"), _col("Fonte"), _agg("CodContrato", 5), _agg("ValorContratado", 0)],
        [FILTRO_PJ, FILTRO_VALOR, _cmp("DataContratacao", 2, _dt(f"{ano}-01-01")), _cmp("DataContratacao", 4, _dt(f"{ano + 1}-01-01"))],
        top=5000,
    )
    assert completo
    return {(uf, fundo): (int(n), _dinheiro(v)) for uf, fundo, n, v in rows}


def _buscar_linhas(uf, fundo, ini, fim):
    select = [_col(p, src) for p, _, src in COLUNAS] + [_agg("CodContrato", 5)]
    conds = [FILTRO_PJ, FILTRO_VALOR, _cmp("UF", 0, _str(uf)), _cmp("Fonte", 0, _str(fundo)),
             _cmp("DataContratacao", 2, _dt(ini)), _cmp("DataContratacao", 4, _dt(fim))]
    rows, completo = _query(select, conds, top=LIMITE_JANELA, com_agencia=True)
    if completo and len(rows) < LIMITE_JANELA:
        return rows
    # janela grande demais: subdivide
    d0, d1 = datetime.fromisoformat(ini).date(), datetime.fromisoformat(fim).date()
    if (d1 - d0).days <= 1:
        raise RuntimeError(f"Janela de 1 dia ainda passa do limite: {uf} {fundo} {ini}")
    if (d1 - d0).days > 31:
        cortes = [d0] + [d0.replace(month=m) for m in range(d0.month + 1, 13) if d0.replace(month=m) < d1] + [d1]
    else:
        meio = d0 + (d1 - d0) / 2
        cortes = [d0, meio, d1]
    print(f"    subdividindo {uf} {fundo} {ini}..{fim} em {len(cortes) - 1} partes", flush=True)
    out = []
    for a, b in zip(cortes, cortes[1:]):
        out.extend(_buscar_linhas(uf, fundo, a.isoformat(), b.isoformat()))
    return out


def _gravar(conn, registros):
    nomes = [c for _, c, _ in COLUNAS] + ["n_linhas_fonte", "extraido_em"]
    upd = ", ".join(f"{c}=excluded.{c}" for c in nomes if c not in ("cod_contrato", "num_operacao", "cnpj", "cod_area_operacional"))
    sql = (f"INSERT INTO bnb_raw ({', '.join(nomes)}) VALUES ({', '.join('?' * len(nomes))}) "
           f"ON CONFLICT (cod_contrato, num_operacao, cnpj, cod_area_operacional) DO UPDATE SET {upd}")
    cur = conn.cursor()
    for i in range(0, len(registros), LOTE_INSERT):
        cur.executemany(sql, registros[i:i + LOTE_INSERT])
        conn.commit()


def processar_janela(conn, ano, uf, fundo, esperado, agora):
    rows = _buscar_linhas(uf, fundo, f"{ano}-01-01", f"{ano + 1}-01-01")
    registros, descartados = [], 0
    for r in rows:
        rec = {c: _conv(c, v) for (_, c, _), v in zip(COLUNAS, r[:-1])}
        cnpj = cnpj_valido(rec["cnpj"])
        if not cnpj:
            descartados += 1  # nunca grava documento/nome que nao seja CNPJ valido
            continue
        rec["cnpj"] = cnpj
        if rec["valor_contratado"] is None or rec["valor_contratado"] <= VALOR_MINIMO_EXCLUSIVO:
            descartados += 1  # fora do recorte > R$ 1 mi (defesa extra; o servidor ja filtra)
            continue
        rec["cliente"] = mascarar_cpf(rec["cliente"])
        registros.append([rec[c] for _, c, _ in COLUNAS] + [int(r[-1]), agora])
    _gravar(conn, registros)
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(n_linhas_fonte),0), COALESCE(SUM(valor_contratado),0) FROM bnb_raw "
        "WHERE uf=? AND fundo=? AND valor_contratado > 1000000 AND data_contratacao >= ? AND data_contratacao < ?",
        (uf, fundo, f"{ano}-01-01", f"{ano + 1}-01-01"),
    )
    g_n, g_v = cur.fetchone()
    extraido = sum(int(r[-1]) for r in rows)
    cur.execute(
        """INSERT INTO bnb_reconciliacao (ano, uf, fundo, esperado_linhas, esperado_valor, extraido_linhas,
               descartados_nao_cnpj, gravado_linhas, gravado_valor, dataset_atualizado_em, verificado_em)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (ano, uf, fundo) DO UPDATE SET esperado_linhas=excluded.esperado_linhas,
               esperado_valor=excluded.esperado_valor, extraido_linhas=excluded.extraido_linhas,
               descartados_nao_cnpj=excluded.descartados_nao_cnpj, gravado_linhas=excluded.gravado_linhas,
               gravado_valor=excluded.gravado_valor, dataset_atualizado_em=excluded.dataset_atualizado_em,
               verificado_em=excluded.verificado_em""",
        (ano, uf, fundo, esperado[0], esperado[1], extraido, descartados, int(g_n), g_v,
         _modelo_info()["last_refresh"], agora),
    )
    conn.commit()
    dif_n, dif_v = esperado[0] - int(g_n), esperado[1] - Decimal(g_v)
    print(f"  {ano} {uf} {fundo}: esperado {esperado[0]} / extraido {extraido} / gravado {g_n} "
          f"/ descartados {descartados} / dif linhas {dif_n} / dif valor {dif_v}", flush=True)
    return dif_n, dif_v


def garantir_tabelas(conn):
    from db import SCHEMA
    ini = SCHEMA.index("-- ============ Staging BNB")
    fim = SCHEMA.index("PRIMARY KEY (ano, uf, fundo)\n);") + len("PRIMARY KEY (ano, uf, fundo)\n);")
    conn.execute(SCHEMA[ini:fim])
    conn.commit()


def extrair(anos, force=False):
    t0 = time.time()
    info = _modelo_info()
    print(f"Dataset BNB atualizado em {info['last_refresh']}", flush=True)
    conn = get_connection()
    try:
        garantir_tabelas(conn)
        cur = conn.cursor()
        cur.execute("SELECT ano, uf, fundo FROM bnb_reconciliacao WHERE gravado_linhas = esperado_linhas "
                    "AND gravado_valor = esperado_valor AND dataset_atualizado_em = ?", (info["last_refresh"],))
        feitas = set() if force else {tuple(r) for r in cur.fetchall()}
        problemas = 0
        for ano in anos:
            esperado = esperado_por_ano(ano)
            print(f"{ano}: {len(esperado)} janelas UF x fundo, {sum(n for n, _ in esperado.values())} linhas PJ esperadas", flush=True)
            for (uf, fundo), exp in sorted(esperado.items()):
                if (ano, uf, fundo) in feitas:
                    continue
                agora = datetime.now(timezone.utc).isoformat()
                dn, dv = processar_janela(conn, ano, uf, fundo, exp, agora)
                if dn or dv:
                    problemas += 1
        print(f"Concluido em {time.time() - t0:.0f}s. Janelas com diferenca nesta rodada: {problemas}", flush=True)
        return problemas
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", default="2016-2026")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    i, f = (int(x) for x in a.anos.split("-"))
    sys.exit(1 if extrair(range(i, f + 1), a.force) else 0)
