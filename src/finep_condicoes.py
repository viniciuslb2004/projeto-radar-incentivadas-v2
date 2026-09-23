"""Condicoes de financiamento FINEP (taxa/indexador/carencia/linha/titulo) -> operations.

Causa raiz (2026-09-23): as abas "Projetos_Credito_Direto" e
"Projetos_Cred__Descentralizado" do Contratacao.xlsx NAO trazem taxa nem descricao --
esse dado fica numa aba separada, "Crd_-_Condicoes_Fincanciamento" (sic, grafia da
FINEP), que cobre credito direto E descentralizado ("alguns projetos podem ter mais de
uma condicao", segundo a Legenda da propria FINEP). Ate aqui ela nunca era lida, entao
taxa_juros/indexador/carencia ficavam NULL para toda operacao FINEP e o titulo do
projeto ficava NULL para todo o descentralizado.

Ligacao (sem schema change -- colunas ja existentes em `operations`):
- Credito Direto: `Contrato` == operations.fonte_id.
- Credito Descentralizado: a aba de condicoes nao tem o contrato do agente; liga por
  CNPJ + `Data Contratacao` == data_assinatura (bate 100% das linhas na posicao de
  18/09/2026).

Nunca inventa: um campo so e preenchido quando TODAS as condicoes daquela operacao
concordam num unico valor (ex.: um projeto com uma parcela TJLP e outra TJLP+5 fica com
taxa NULL). `taxa_juros` = "Fator pre-fixado Percentual" (o spread final ao cliente, o
que aparece em "Taxa final ao cliente" depois do indexador); prazo de amortizacao =
Prazo Total - Carencia (a Legenda da FINEP documenta que o prazo total engloba a carencia
e as amortizacoes vao do fim da carencia ao fim do contrato). Titulo so e gravado onde
descricao_projeto ainda esta NULL (nao sobrescreve o titulo da aba de credito direto).
Roda depois do unify.build_operations(); as correcoes manuais sao reaplicadas no fim.
"""
import pandas as pd

from db import get_connection
from download import FINEP_PATH

ABA_CONDICOES = "Crd_-_Condições_Fincanciamento"


def _unico(serie: pd.Series):
    vals = serie.dropna()
    if vals.dtype == object:
        vals = vals.astype(str).str.strip()
        vals = vals[vals != ""]
    vals = vals.unique()
    return vals[0] if len(vals) == 1 else None


def _titulos(serie: pd.Series):
    vals = [t for t in dict.fromkeys(serie.dropna().astype(str).str.strip()) if t]
    return " | ".join(vals) if vals else None


def ler_condicoes(path=FINEP_PATH) -> pd.DataFrame:
    from parse_finep import _resolver_aba

    aba = _resolver_aba(path, ABA_CONDICOES)
    df = pd.read_excel(path, sheet_name=aba, header=6, engine="openpyxl")
    df = df.dropna(subset=["Instrumento"])
    df["cnpj"] = df["CNPJ Proponente"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)
    df["data"] = pd.to_datetime(df["Data Contratação"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["taxa"] = pd.to_numeric(df["Fator pre-fixado Percentual"], errors="coerce")
    df["carencia"] = pd.to_numeric(df["Carencia"], errors="coerce")
    df["amortizacao"] = pd.to_numeric(df["Prazo Total"], errors="coerce") - df["carencia"]
    df["contrato"] = df["Contrato"].astype(str).str.strip().where(df["Contrato"].notna())
    return df


def _agrupar(df: pd.DataFrame, chaves: list) -> pd.DataFrame:
    return df.groupby(chaves).agg(
        indexador=("Indexador", _unico),
        taxa_juros=("taxa", _unico),
        prazo_carencia_meses=("carencia", _unico),
        prazo_amortizacao_meses=("amortizacao", _unico),
        instrumento_financeiro=("Linha do Subcredito", _unico),
        titulo=("Título", _titulos),
    ).reset_index()


def aplicar_condicoes_finep(path=FINEP_PATH, conn=None) -> int:
    """Preenche as colunas NULL de operations (FINEP) a partir da aba de condicoes.
    Retorna o numero de operacoes alteradas."""
    import unify

    cond = ler_condicoes(path)
    desc = _agrupar(cond[cond["Instrumento"].str.contains("Descentralizado", na=False)], ["cnpj", "data"])
    direto = _agrupar(cond[cond["Instrumento"].str.contains("Direto", na=False)].dropna(subset=["contrato"]), ["contrato"])

    fechar = conn is None
    conn = conn or get_connection()
    try:
        ops = pd.DataFrame(
            conn.execute(
                "SELECT id, raw_table, fonte_id, cnpj, data_contratacao FROM operations "
                "WHERE agencia = 'FINEP' AND raw_table IN ('finep_credito_direto_raw', 'finep_credito_descentralizado_raw')"
            ).fetchall(),
            columns=["id", "raw_table", "fonte_id", "cnpj", "data"],
        )
        ops["data"] = ops["data"].astype(str).str[:10]
        m_desc = ops[ops.raw_table == "finep_credito_descentralizado_raw"].merge(desc, on=["cnpj", "data"])
        m_dir = ops[ops.raw_table == "finep_credito_direto_raw"].merge(direto, left_on="fonte_id", right_on="contrato")
        alvo = pd.concat([m_desc, m_dir], ignore_index=True)

        def _v(x):
            return None if x is None or (not isinstance(x, str) and pd.isna(x)) else (x.item() if hasattr(x, "item") else x)

        # Em lote (tabela temporaria + um UPDATE ... FROM): linha a linha pela rede
        # levava >20 min segurando lock em `operations`.
        conn.execute(
            "CREATE TEMP TABLE tmp_cond_finep (id INTEGER, indexador TEXT, taxa REAL, carencia REAL, "
            "amortizacao REAL, linha TEXT, titulo TEXT) ON COMMIT DROP"
        )
        linhas = [
            (int(r.id), _v(r.indexador), _v(r.taxa_juros), _v(r.prazo_carencia_meses),
             _v(r.prazo_amortizacao_meses), _v(r.instrumento_financeiro), _v(r.titulo))
            for r in alvo.itertuples(index=False)
        ]
        with conn.cursor() as cur:
            with cur.copy("COPY tmp_cond_finep FROM STDIN") as cp:
                for linha in linhas:
                    cp.write_row(linha)
        alterados = [r[0] for r in conn.execute(
            "UPDATE operations o SET "
            "indexador = COALESCE(o.indexador, t.indexador), taxa_juros = COALESCE(o.taxa_juros, t.taxa), "
            "prazo_carencia_meses = COALESCE(o.prazo_carencia_meses, t.carencia), "
            "prazo_amortizacao_meses = COALESCE(o.prazo_amortizacao_meses, t.amortizacao), "
            "instrumento_financeiro = COALESCE(o.instrumento_financeiro, t.linha), "
            "descricao_projeto = COALESCE(o.descricao_projeto, t.titulo) "
            "FROM tmp_cond_finep t WHERE o.id = t.id AND ("
            "(o.indexador IS NULL AND t.indexador IS NOT NULL) OR (o.taxa_juros IS NULL AND t.taxa IS NOT NULL) OR "
            "(o.prazo_carencia_meses IS NULL AND t.carencia IS NOT NULL) OR "
            "(o.prazo_amortizacao_meses IS NULL AND t.amortizacao IS NOT NULL) OR "
            "(o.instrumento_financeiro IS NULL AND t.linha IS NOT NULL) OR "
            "(o.descricao_projeto IS NULL AND t.titulo IS NOT NULL)) RETURNING o.id"
        ).fetchall()]
        conn.commit()

        # textos de busca (titulo/indexador/linha entram no search_document) -- em lote,
        # boilerplate calculado uma vez so (mesma logica de _atualizar_textos_apos_correcao).
        if alterados:
            boilerplate = unify._descricoes_boilerplate(conn)
            cols = ["id", "agencia", "cliente", "razao_social_oficial", "cnpj", "setor_bndes", "subsetor_bndes",
                    "segmento", "produto", "instrumento_financeiro", "modalidade_apoio", "indexador",
                    "valor_contratado", "prazo_amortizacao_meses", "descricao_projeto", "municipio", "uf"]
            for i in range(0, len(alterados), 500):
                lote = alterados[i:i + 500]
                ph = ", ".join("?" * len(lote))
                params = []
                for row in conn.execute(f"SELECT {', '.join(cols)} FROM operations WHERE id IN ({ph})", lote).fetchall():
                    campos = dict(zip(cols, row))
                    params.append((unify._embedding_text(campos, boilerplate), unify._search_document(campos, boilerplate),
                                   unify._search_taxonomia_termos(campos), campos["id"]))
                with conn.cursor() as cur:
                    cur.executemany(
                        "UPDATE operations SET embedding_text = ?, search_document = ?, search_taxonomia_termos = ? WHERE id = ?",
                        params,
                    )
                conn.commit()
                unify._atualizar_search_vector(conn, lote)
            unify._reaplicar_correcoes_manuais(conn)
        print(f"Condicoes FINEP: {len(alvo)} operacoes casadas, {len(alterados)} atualizadas.")
        return len(alterados)
    finally:
        if fechar:
            conn.close()


if __name__ == "__main__":
    import sys

    aplicar_condicoes_finep(sys.argv[1] if len(sys.argv) > 1 else FINEP_PATH)
