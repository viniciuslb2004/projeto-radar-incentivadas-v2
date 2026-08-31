"""Motor de busca por similaridade (embeddings locais) + narrador (Ollama com fallback estatistico)."""
import datetime
import json

import numpy as np
import pandas as pd
import requests

from db import get_connection
from embeddings import EMB_PATH, get_model
from empresa_lookup import buscar_atividade_empresa

OLLAMA_URL = "http://localhost:11434/api/generate"
# 8B em vez de 3B (2026-08): resultados sensivelmente melhores em tarefas que exigem
# seguir instrucoes com precisao (ex: nao inventar numeros de uma tabela bagunçada,
# distinguir nome de empresa de ruido textual) -- ver historico de resumo de editais
# e busca por empresa desconhecida. Custo: baixa em CPU ~2-3x mais devagar que o 3B e
# precisa de mais RAM (~6-7GB livres) -- por isso os timeouts abaixo tambem subiram.
OLLAMA_MODEL = "llama3.1:8b-instruct-q4_K_M"
OLLAMA_TIMEOUT = 120
OLLAMA_TIMEOUT_REFINO = 180  # prompt maior (varios candidatos) -- precisa de mais margem que a narrativa

# Score de similaridade (cosseno, 0-1) abaixo do qual avisamos o usuario que a
# correspondencia e fraca, em vez de apresentar os resultados como se fossem uma
# correspondencia forte (ex: buscar "fintech" nao deveria devolver uma petroquimica
# com confianca implicita de que e uma boa resposta).
CONFIANCA_MINIMA = 0.45

# O score "bom" varia muito de busca para busca (uma busca generica como "industria"
# tem uma cauda longa de resultados legitimos; uma busca especifica como "hospital"
# degenera em ruido bem mais cedo). Por isso o limiar e RELATIVO ao melhor score de
# cada busca, nao um numero fixo -- inclui tudo ate MARGEM_RELATIVA abaixo do melhor
# resultado, com um piso absoluto para nunca deixar passar ruido puro.
MARGEM_RELATIVA = 0.08
LIMIAR_ABSOLUTO_MINIMO = 0.40

# Mesmo que nada passe do limiar (busca muito vaga/obscura), sempre mostra pelo menos
# essa quantidade dos melhores resultados, com o aviso de confianca baixa.
MINIMO_RESULTADOS = 20

# BNDES/FINEP nao usam jargao de mercado (fintech, healthtech, etc) na descricao das
# operacoes -- eles usam nomes de empresa, CNAE e produto. Sem isso, uma busca por
# "fintech" nao acha nada parecido e cai em ruido (ex: Braskem). Expandimos o termo
# para vocabulario mais proximo do que realmente aparece nos dados antes de embutir.
EXPANSAO_TERMOS = {
    "fintech": "empresa de tecnologia financeira, meios de pagamento, credito digital, servicos financeiros",
    "healthtech": "empresa de tecnologia para saude, equipamentos medico-hospitalares, servicos de saude",
    "agtech": "empresa de tecnologia para o agronegocio, agropecuaria, insumos agricolas",
    "edtech": "empresa de tecnologia educacional, ensino, plataforma de educacao",
    "insurtech": "empresa de tecnologia para seguros, servicos financeiros",
    "proptech": "empresa de tecnologia para o mercado imobiliario, construcao",
    "biotech": "empresa de biotecnologia, pesquisa e desenvolvimento farmaceutico",
    "cleantech": "empresa de tecnologia limpa, energia renovavel, descarbonizacao",
    "climatetech": "empresa de tecnologia climatica, energia renovavel, descarbonizacao",
    "foodtech": "empresa de tecnologia de alimentos, industria alimenticia",
    "logtech": "empresa de tecnologia para logistica, transporte, armazenagem",
    "retailtech": "empresa de tecnologia para varejo, comercio",
    "startup": "empresa inovadora de base tecnologica",
    "e-commerce": "comercio eletronico, varejo online",
    "ecommerce": "comercio eletronico, varejo online",
    "marketplace": "plataforma de comercio eletronico, varejo online",
    "saas": "empresa de software como servico, tecnologia da informacao",
}

# Diferente do EXPANSAO_TERMOS acima (jargao que NAO aparece no corpus e precisa ser
# traduzido), estes sao termos que aparecem no corpus mas em MAIS DE UM SENTIDO --
# palavras genuinamente ambiguas onde o embedding "gruda" no sentido errado por causa
# da raiz textual parecida. Confirmado empiricamente (nao e hipotetico): buscar
# "empresa de cabo de fibra otica" devolvia como top resultados empresas TEXTEIS
# (score 0.54, ACIMA do CONFIANCA_MINIMA, ou seja sem nenhum aviso de baixa
# confianca) porque "fibra otica" (telecom) e "fibra" textil/sintetica partilham
# a mesma raiz. Mesmo padrao testado e confirmado para "planta" (industrial vs
# botanica) e "celula" (biologia vs celulose/papel) -- ver comentarios por bloco.
TERMOS_AMBIGUOS = {
    # "fibra optica"/"cabo optico" (telecom, rede de dados) tem a mesma raiz textual
    # de "fibra" textil/sintetica (fiacao, tecelagem) -- o setor mais proximo no
    # corpus por pura semelhanca de palavra, mas um setor completamente diferente.
    # Cobre as 4 grafias correntes (com/sem acento, com/sem "p", pois BNDES/FINEP
    # nao usa "banda larga"/"fibra optica" como segmento -- usamos vocabulario que
    # de fato aparece: "TELECOMUNICACOES POR FIO", "CONSTRUCAO DE ESTACOES E REDES
    # DE TELECOMUNICACOES", "PROVEDORES DE ACESSO AS REDES DE COMUNICACOES").
    "fibra otica": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "fibra ótica": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "fibra optica": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "fibra óptica": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "cabo otico": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "cabo ótico": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "cabo optico": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "cabo óptico": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "cabeamento otico": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "cabeamento ótico": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "cabeamento optico": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",
    "cabeamento óptico": "telecomunicacoes, redes de telecomunicacoes por fio, construcao de redes de telecomunicacoes, provedores de acesso a redes de comunicacoes, infraestrutura de internet e banda larga, equipamentos de telecomunicacoes",

    # "planta" no sentido de unidade fabril colide com "planta" no sentido botanico --
    # o corpus tem muito mais floricultura/agricultura/"florestas plantadas" do que
    # descricoes industriais usando a palavra "planta" (CNAE usa "fabrica", "usina",
    # "unidade industrial"). Sem isso, "expansao de planta industrial" caia em
    # empresas de sementes/flores/defensivos agricolas em vez de industria de verdade
    # (confirmado: score 0.49, sem aviso de baixa confianca).
    "planta industrial": "expansao de unidade fabril, ampliacao de capacidade produtiva industrial, nova linha de producao, planta fabril, unidade de manufatura",
    "expansao de planta": "expansao de unidade fabril, ampliacao de capacidade produtiva industrial, nova linha de producao, planta fabril, unidade de manufatura",
    "expansao da planta": "expansao de unidade fabril, ampliacao de capacidade produtiva industrial, nova linha de producao, planta fabril, unidade de manufatura",
    "ampliacao de planta": "expansao de unidade fabril, ampliacao de capacidade produtiva industrial, nova linha de producao, planta fabril, unidade de manufatura",
    "ampliacao da planta": "expansao de unidade fabril, ampliacao de capacidade produtiva industrial, nova linha de producao, planta fabril, unidade de manufatura",

    # "celula"/"celulas" (biologia -- celulas-tronco, banco de celulas e tecidos) tem
    # raiz textual quase identica a "celulose" (papel e celulose, um dos maiores
    # setores do corpus BNDES/FINEP) e o modelo confunde as duas: "cultura de
    # celulas-tronco" virava um ranking de fabricantes de celulose e papel (score
    # 0.55+, sem aviso). NAO mexemos na palavra "celula" sozinha porque ela tambem
    # aparece em "celula fotovoltaica/solar" (energia), que ja funciona bem e nao
    # deve ser afetado -- so as chaves abaixo, especificas do sentido biologico.
    # Limitacao conhecida: a expansao melhora bastante o ranking mas nao elimina de
    # todo a interferencia da celulose para a frase mais curta e nua ("cultura de
    # celulas-tronco"), onde a raiz textual da propria query (nao so o vocabulario
    # do corpus) ja pesa muito na direcao errada -- ver nota no relatorio de teste.
    "cultura de celulas": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "cultura de células": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "banco de celulas": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "banco de células": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "celulas-tronco": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "células-tronco": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "celulas tronco": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "células tronco": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "celulas humanas": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
    "células humanas": "medicina regenerativa, terapia celular, celulas-tronco, criobiologia, banco de celulas e tecidos humanos, laboratorio de biotecnologia em saude, pesquisa biomedica, servicos de saude humana",
}

_emb_cache = None


def _load_embeddings():
    global _emb_cache
    if _emb_cache is None:
        if not EMB_PATH.exists():
            raise RuntimeError("Embeddings ainda nao foram gerados. Rode embeddings.py primeiro.")
        data = np.load(EMB_PATH)
        _emb_cache = (data["ids"], data["vectors"])
    return _emb_cache


def warmup():
    """Carrega o modelo de embeddings e o arquivo de vetores em memoria.

    Sem isso, a primeira busca de cada reinicio do servidor demora ~20-30s
    (carregamento do sentence-transformers), o que parece uma trava para
    quem esta usando o site. Chame isso uma vez no startup do FastAPI.

    So para o modo LOCAL (desktop) -- ver warmup_hospedado() para o modo hospedado."""
    get_model()
    _load_embeddings()


def warmup_hospedado():
    """Versao leve do warmup() para o modo HOSPEDADO (Render, free tier, 512MB de RAM):
    carrega so o .npz de vetores do corpus (numpy, poucos MB) -- NUNCA chama
    get_model()/SentenceTransformer, que carregaria o sentence-transformers/torch na
    memoria e estouraria esse limite (ver DEPLOY.md). O embedding da query e calculado
    no NAVEGADOR de quem esta usando (transformers.js, ver webapp/static/js/
    embeddings-client.js); o servidor so faz o produto escalar contra estes vetores
    precalculados (buscar_rapido_com_vetor / buscar_por_termo_com_vetor abaixo)."""
    _load_embeddings()


def _expandir_query(query: str) -> str:
    q_lower = query.lower()
    extras = [expansao for termo, expansao in EXPANSAO_TERMOS.items() if termo in q_lower]
    extras += [expansao for termo, expansao in TERMOS_AMBIGUOS.items() if termo in q_lower]
    if not extras:
        return query
    # dict.fromkeys em vez de set() para nao embaralhar a ordem -- varias chaves de
    # TERMOS_AMBIGUOS (ex.: "fibra otica"/"fibra ótica"/"fibra optica") sao so
    # variantes de grafia do mesmo termo e batem ao mesmo tempo, apontando para o
    # MESMO texto de expansao; sem isso ele entraria duplicado na query expandida.
    extras_unicos = list(dict.fromkeys(extras))
    return query + " | " + " | ".join(extras_unicos)


def _parse_date(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s[:10])


def _tendencia_por_campo(conn, campo: str, valor_campo: str, rotulo: str):
    """Variacao de participacao de um valor de `campo` (setor_bndes OU segmento) nos
    ultimos 365 dias de dados vs os 365 anteriores. Usado tanto para a leitura ampla
    (setor) quanto para a leitura fina e especifica (segmento CNAE) que alimenta a
    narrativa -- o segmento e o que realmente diz algo especifico sobre a busca."""
    if not valor_campo:
        return None
    cur = conn.cursor()
    max_data = cur.execute("SELECT MAX(data_contratacao) FROM operations").fetchone()[0]
    if not max_data:
        return None

    fim = _parse_date(max_data) + datetime.timedelta(days=1)
    inicio = fim - datetime.timedelta(days=365)
    ant_fim = inicio
    ant_inicio = ant_fim - datetime.timedelta(days=365)

    def valor_grupo_e_total(d_ini, d_fim):
        total = cur.execute(
            "SELECT SUM(valor_contratado) FROM operations WHERE data_contratacao >= ? AND data_contratacao < ?",
            (d_ini.isoformat(), d_fim.isoformat()),
        ).fetchone()[0] or 0
        do_grupo = cur.execute(
            f"SELECT SUM(valor_contratado), COUNT(*) FROM operations "
            f"WHERE data_contratacao >= ? AND data_contratacao < ? AND {campo} = ?",
            (d_ini.isoformat(), d_fim.isoformat(), valor_campo),
        ).fetchone()
        return (do_grupo[0] or 0), (do_grupo[1] or 0), total

    valor_atual, n_atual, total_atual = valor_grupo_e_total(inicio, fim)
    valor_anterior, n_anterior, total_anterior = valor_grupo_e_total(ant_inicio, ant_fim)

    part_atual = (valor_atual / total_atual * 100) if total_atual else 0
    part_anterior = (valor_anterior / total_anterior * 100) if total_anterior else 0
    variacao_pp = part_atual - part_anterior

    if variacao_pp > 0.2:
        direcao = "alta"
    elif variacao_pp < -0.2:
        direcao = "queda"
    else:
        direcao = "estavel"

    return {
        "rotulo": rotulo,
        "grupo": valor_campo,
        "periodo_atual": [inicio.isoformat(), fim.isoformat()],
        "periodo_anterior": [ant_inicio.isoformat(), ant_fim.isoformat()],
        "participacao_atual_pct": round(part_atual, 2),
        "participacao_anterior_pct": round(part_anterior, 2),
        "variacao_pp": round(variacao_pp, 2),
        "valor_atual": valor_atual,
        "valor_anterior": valor_anterior,
        "n_operacoes_atual": n_atual,
        "direcao": direcao,
    }


def _fmt_brl(v):
    if v >= 1e9:
        return f"R$ {v/1e9:.1f} bi"
    if v >= 1e6:
        return f"R$ {v/1e6:.1f} mi"
    if v >= 1e3:
        return f"R$ {v/1e3:.0f} mil"
    return f"R$ {v:.0f}"


def _tendencia_texto(tendencia: dict) -> str:
    if not tendencia:
        return ""
    rotulo, grupo = tendencia["rotulo"], tendencia["grupo"]
    if tendencia["direcao"] == "alta":
        return (
            f'O segmento "{grupo}" ({rotulo}) está em alta: passou de {tendencia["participacao_anterior_pct"]:.1f}% '
            f'para {tendencia["participacao_atual_pct"]:.1f}% do crédito incentivado dos últimos 12 meses '
            f'(+{tendencia["variacao_pp"]:.1f} p.p. frente aos 12 meses anteriores, {tendencia["n_operacoes_atual"]} '
            f'operações e {_fmt_brl(tendencia["valor_atual"])} no período atual).'
        )
    if tendencia["direcao"] == "queda":
        return (
            f'O segmento "{grupo}" ({rotulo}) está em queda: caiu de {tendencia["participacao_anterior_pct"]:.1f}% '
            f'para {tendencia["participacao_atual_pct"]:.1f}% do crédito incentivado dos últimos 12 meses '
            f'({tendencia["variacao_pp"]:.1f} p.p. frente aos 12 meses anteriores, {tendencia["n_operacoes_atual"]} '
            f'operações e {_fmt_brl(tendencia["valor_atual"])} no período atual).'
        )
    return (
        f'A participação do segmento "{grupo}" ({rotulo}) está estável '
        f'({tendencia["participacao_atual_pct"]:.1f}% do crédito incentivado nos últimos 12 meses, '
        f'{tendencia["n_operacoes_atual"]} operações no período).'
    )


def _template_narrativa(query: str, tendencia_segmento: dict, tendencia_setor: dict, resultados: list, confianca_baixa: bool) -> str:
    if not resultados:
        return f'Não encontrei operações de BNDES ou FINEP parecidas com "{query}" na base atual.'

    n = len(resultados)
    agencias = sorted(set(r["agencia"] for r in resultados))
    valor_medio = sum(r["valor_contratado"] or 0 for r in resultados) / n
    exemplos = resultados[:3]

    partes = []
    if confianca_baixa:
        partes.append(
            f'Não encontrei uma correspondência forte para "{query}" na base do BNDES/FINEP -- '
            "os resultados abaixo são os mais próximos que existem, mas com similaridade baixa."
        )
    else:
        nomes = ", ".join(e["cliente"] for e in exemplos if e.get("cliente"))
        partes.append(
            f'Encontrei {n} operações de {" e ".join(agencias)} parecidas com "{query}", '
            f"com cheque médio de {_fmt_brl(valor_medio)}. Os exemplos mais próximos incluem {nomes}."
        )

    texto_segmento = _tendencia_texto(tendencia_segmento)
    if texto_segmento:
        partes.append(texto_segmento)
    elif tendencia_setor:
        partes.append(_tendencia_texto(tendencia_setor))

    return " ".join(partes)


def montar_prompt_narrativa(query_expandida: str, tendencia_segmento: dict, tendencia_setor: dict, resultados: list, confianca_baixa: bool = False) -> dict:
    """Mesmo prompt de gerar_narrativa(), devolvido em vez de enviado ao Ollama --
    usado no modo HOSPEDADO (ver POST /api/busca/narrativa em webapp/main.py)."""
    fallback = _template_narrativa(query_expandida, tendencia_segmento, tendencia_setor, resultados, confianca_baixa)
    if not resultados:
        return {"prompt": None, "fallback": fallback}

    exemplos = "\n".join(
        f"- {r['cliente']} | agência: {r['agencia']} | segmento: {r['segmento'] or 'nao classificado'} | "
        f"valor: {_fmt_brl(r['valor_contratado'] or 0)} | data: {r['data_contratacao']} | "
        f"projeto: {(r['descricao_projeto'] or '').strip()[:140]}"
        for r in resultados[:6]
    )
    tendencia_txt = _tendencia_texto(tendencia_segmento) or _tendencia_texto(tendencia_setor) or "Sem dados de tendência suficientes."
    aviso_confianca = (
        "ATENCAO: a similaridade encontrada foi baixa, deixe isso claro logo na primeira frase. "
        if confianca_baixa else ""
    )
    prompt = (
        "Voce e um analista de credito incentivado (BNDES/FINEP) da Artica Capital Solutions, "
        "escrevendo para um colega que precisa de uma leitura RAPIDA e ESPECIFICA, nao um resumo generico.\n\n"
        f'O usuario descreveu: "{query_expandida}"\n\n'
        f"Operacoes mais parecidas encontradas (use nomes e numeros REAIS destes exemplos):\n{exemplos}\n\n"
        f"Dado de tendencia (o segmento especifico da busca, ultimos 12 meses vs 12 meses anteriores):\n{tendencia_txt}\n\n"
        f"{aviso_confianca}"
        "Escreva um paragrafo de 3-4 frases em portugues, seguindo esta estrutura:\n"
        "1) Cite pelo menos 2 nomes de empresas reais da lista acima e o que elas fizeram (resuma o projeto).\n"
        "2) Diga se ESSE SEGMENTO especifico (nao um setor generico) esta em alta ou queda, citando os p.p. e o valor fornecidos.\n"
        "3) Termine com uma frase de leitura pratica (ex: se e um segmento aquecido, se os cheques sao "
        "tipicamente grandes ou pequenos, se a base de comparaveis e ampla ou restrita).\n"
        "Nao use frases genericas como 'isso sugere uma tendencia' sem dizer especificamente qual. "
        "Nao invente numeros que nao foram fornecidos. "
        "Responda direto com o paragrafo em si -- sem introducoes tipo 'aqui esta', sem comentar a tarefa, "
        "sem repetir estas instrucoes."
    )
    return {"prompt": prompt, "modelo": OLLAMA_MODEL, "opcoes": {"temperature": 0.3}, "fallback": fallback}


def gerar_narrativa(query_expandida: str, tendencia_segmento: dict, tendencia_setor: dict, resultados: list, confianca_baixa: bool = False) -> str:
    """Chamada LENTA (Ollama, ~5-40s). Chame depois de ja ter mostrado os resultados ao usuario.

    O prompt e deliberadamente concreto (exemplos com nome, segmento, valor, data e um
    trecho da descricao do projeto + a tendencia do SEGMENTO especifico, nao do setor
    generico) para que o modelo local (pequeno, 3B) tenha material suficiente pra
    escrever algo especifico em vez de uma resposta generica de tendencia de setor.
    Modo LOCAL apenas -- ver montar_prompt_narrativa() para o modo hospedado."""
    prep = montar_prompt_narrativa(query_expandida, tendencia_segmento, tendencia_setor, resultados, confianca_baixa)
    fallback = prep["fallback"]
    if not prep.get("prompt"):
        return fallback
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": prep["modelo"],
                "prompt": prep["prompt"],
                "stream": False,
                "options": prep["opcoes"],
            },
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        texto = resp.json().get("response", "").strip()
        return texto or fallback
    except Exception:
        return fallback


MAX_AVALIAR_REFINO = 30  # mais que isso deixa o prompt grande demais para um modelo 3B em CPU responder a tempo


_COLS_OPERACAO = [
    "id", "agencia", "instrumento", "cliente", "uf", "setor_bndes", "subsetor_bndes", "segmento",
    "valor_contratado", "data_contratacao", "descricao_projeto",
]


def _buscar_por_termo_nucleo(vetor, ja_incluidos: set, limite: int = 8) -> list:
    """Nucleo comum de _buscar_por_termo()/buscar_por_termo_com_vetor() -- so precisa
    do vetor do termo ja calculado (pelo servidor, modo local, ou pelo navegador, modo
    hospedado)."""
    ids_emb, vectors = _load_embeddings()
    scores = vectors @ vetor
    top_idx = np.argsort(-scores)[:limite * 3]

    achados = []
    for i in top_idx:
        if len(achados) >= limite:
            break
        score = float(scores[i])
        if score < LIMIAR_ABSOLUTO_MINIMO:
            break
        op_id = int(ids_emb[i])
        if op_id in ja_incluidos:
            continue
        achados.append((op_id, score))
        ja_incluidos.add(op_id)

    if not achados:
        return []

    conn = get_connection()
    try:
        ids_lista = [a[0] for a in achados]
        placeholders = ",".join("?" * len(ids_lista))
        rows = conn.execute(
            f"SELECT {', '.join(_COLS_OPERACAO)} FROM operations WHERE id IN ({placeholders})", ids_lista
        ).fetchall()
    finally:
        conn.close()

    score_by_id = dict(achados)
    novos = [dict(zip(_COLS_OPERACAO, r)) for r in rows]
    for r in novos:
        r["score"] = round(score_by_id.get(r["id"], 0), 4)
    novos.sort(key=lambda r: r["score"], reverse=True)
    return novos


def _buscar_por_termo(termo: str, ja_incluidos: set, limite: int = 8) -> list:
    """Busca rapida (embeddings) por um termo extra sugerido pelo LLM, para pegar
    operacoes relevantes que a busca original pode ter deixado de fora. Modo LOCAL:
    calcula o embedding do termo no proprio processo (get_model())."""
    model = get_model()
    qvec = model.encode([termo], normalize_embeddings=True)[0]
    return _buscar_por_termo_nucleo(qvec, ja_incluidos, limite)


def buscar_por_termo_com_vetor(termo: str, vetor, ja_incluidos, limite: int = 8) -> list:
    """Mesma logica de _buscar_por_termo(), mas para o modo HOSPEDADO: recebe o vetor
    do termo ja calculado no navegador (embeddings-client.js) -- usado pela etapa de
    'termos adicionais' do refino quando rodando no deploy hospedado (ver rota
    /api/busca/termo em webapp/main.py). `termo` so serve de rotulo aqui (o vetor ja
    veio pronto); nunca chama get_model()."""
    vec = np.asarray(vetor, dtype=np.float32)
    norma = float(np.linalg.norm(vec))
    if norma > 0:
        vec = vec / norma
    incluidos = ja_incluidos if isinstance(ja_incluidos, set) else set(ja_incluidos or [])
    return _buscar_por_termo_nucleo(vec, incluidos, limite)


def montar_prompt_refino(query_expandida: str, resultados: list, max_avaliar: int = MAX_AVALIAR_REFINO) -> dict:
    """Mesmo prompt de refinar_resultados(), devolvido em vez de enviado ao Ollama --
    usado no modo HOSPEDADO, onde quem efetivamente gera o texto e o navegador de quem
    esta usando (ver local-ai.js). A filtragem do JSON de resposta (aplicarRefinoLocal,
    ver common.js) acontece no proprio navegador -- os 'termos_adicionais' sao tratados
    a parte (ver buscar_por_termo_com_vetor / rota POST /api/busca/termo), pois tambem
    precisam de um vetor calculado no navegador."""
    if not resultados:
        return {"prompt": None, "candidatos_ids": []}

    candidatos = resultados[:max_avaliar]
    lista = "\n".join(
        f"{r['id']}: empresa={r['cliente']} | segmento={r['segmento'] or 'nao classificado'} | "
        f"valor={_fmt_brl(r['valor_contratado'] or 0)}"
        for r in candidatos
    )
    prompt = (
        "Voce e um analista revisando os resultados de uma busca semantica automatica por operacoes "
        "de credito incentivado (BNDES/FINEP). A busca por similaridade de texto as vezes traz falsos "
        "positivos (pontuacao alta mas sem relacao real) e tambem pode deixar de fora operacoes "
        "relevantes que usam outros termos para a mesma coisa.\n\n"
        f'Busca do usuario: "{query_expandida}"\n\n'
        f"Candidatos encontrados (id: empresa | segmento | valor):\n{lista}\n\n"
        'Responda APENAS com um JSON no formato '
        '{"relevantes": [id1, id2, ...], "termos_adicionais": ["termo1", "termo2"]}\n'
        "- relevantes: os IDs (numeros inteiros, da lista acima) que tem relacao REAL com a busca, "
        "ordenados do mais para o menos relevante de verdade (nao so pontuacao de texto). Remova os "
        "IDs cujo segmento claramente nao tem nada a ver com a busca. Se todos forem relevantes, "
        "devolva todos.\n"
        "- termos_adicionais: ate 3 termos, segmentos ou tipos de empresa relacionados que poderiam "
        "pegar operacoes relevantes que NAO aparecem na lista acima (sinonimos, segmentos adjacentes, "
        "cadeia produtiva relacionada). Deixe a lista vazia se nao houver sugestao boa. "
        "Nao invente IDs que nao estao na lista acima."
    )
    return {
        "prompt": prompt,
        "modelo": OLLAMA_MODEL,
        "opcoes": {"temperature": 0.1, "format": "json"},
        "candidatos_ids": [r["id"] for r in candidatos],
    }


def refinar_resultados(query_expandida: str, resultados: list, max_avaliar: int = MAX_AVALIAR_REFINO) -> dict:
    """3a etapa (chamada LENTA, Ollama): revisa os melhores candidatos da busca por
    embeddings e (1) remove falsos-positivos que passaram no limiar de similaridade mas
    nao tem relacao real com a busca, (2) reordena o que sobrou pela relevancia real
    (nao so a similaridade de texto) e (3) sugere termos correlatos e busca por eles,
    trazendo operacoes relevantes que a busca original pode ter deixado de fora.
    Se o Ollama falhar ou a resposta nao vier em JSON valido, devolve a lista original
    sem mudar nada -- nunca piora o resultado. Modo LOCAL apenas (chama o Ollama
    diretamente) -- ver montar_prompt_refino() para o modo hospedado."""
    if not resultados:
        return {"resultados": resultados, "refinado": False, "n_removidos": 0, "n_adicionados": 0}

    candidatos = resultados[:max_avaliar]
    restante = resultados[max_avaliar:]
    prep = montar_prompt_refino(query_expandida, resultados, max_avaliar)

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": prep["modelo"],
                "prompt": prep["prompt"],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
            timeout=OLLAMA_TIMEOUT_REFINO,
        )
        resp.raise_for_status()
        texto = resp.json().get("response", "").strip()
        parsed = json.loads(texto)

        ids_relevantes = [int(i) for i in parsed.get("relevantes", []) if str(i).lstrip("-").isdigit()]
        ids_candidatos = {r["id"] for r in candidatos}
        ids_relevantes = [i for i in ids_relevantes if i in ids_candidatos]
        if not ids_relevantes:
            return {"resultados": resultados, "refinado": False, "n_removidos": 0, "n_adicionados": 0}

        by_id = {r["id"]: r for r in candidatos}
        refinados = [by_id[i] for i in dict.fromkeys(ids_relevantes)]
        n_removidos = len(candidatos) - len(refinados)

        termos_adicionais = [str(t).strip() for t in parsed.get("termos_adicionais", []) if str(t).strip()][:3]
        ja_incluidos = {r["id"] for r in resultados}
        adicionados = []
        for termo in termos_adicionais:
            try:
                adicionados.extend(_buscar_por_termo(termo, ja_incluidos))
            except Exception:
                continue

        final = refinados + adicionados + restante
        return {
            "resultados": final,
            "refinado": True,
            "n_removidos": n_removidos,
            "n_adicionados": len(adicionados),
            "termos_adicionais": termos_adicionais,
        }
    except Exception:
        return {"resultados": resultados, "refinado": False, "n_removidos": 0, "n_adicionados": 0}


def _estimar_probabilidade_aprovacao(conn, melhores: list) -> dict:
    """Taxa de aprovacao historica -- SO calculavel para Credito Direto da FINEP, o
    unico instrumento com base publica de propostas recusadas (finep_nao_aprovados_raw).
    O BNDES nao publica dados de propostas recusadas em lugar nenhum publico, e o
    Credito Descentralizado da FINEP e decidido pelo banco parceiro (nao pela FINEP),
    entao tambem nao tem base de recusas. Nesses casos devolvemos disponivel=False com
    o motivo, em vez de inventar um numero sem base real."""
    agencias = [r["agencia"] for r in melhores if r["agencia"]]
    instrumentos = [r["instrumento"] for r in melhores if r["instrumento"]]
    if not agencias or not instrumentos:
        return {"disponivel": False, "motivo": "Sem operações suficientes para estimar."}

    agencia_principal = pd.Series(agencias).mode().iloc[0]
    instrumento_principal = pd.Series(instrumentos).mode().iloc[0]

    if agencia_principal == "BNDES":
        return {
            "disponivel": False,
            "agencia": agencia_principal,
            "instrumento": instrumento_principal,
            "motivo": "O BNDES não publica dados de propostas recusadas, então não é possível calcular uma "
            "taxa de aprovação real para operações do BNDES -- só sabemos o que já foi contratado.",
        }
    if instrumento_principal != "Credito Direto":
        return {
            "disponivel": False,
            "agencia": agencia_principal,
            "instrumento": instrumento_principal,
            "motivo": "Nesse tipo de operação quem decide é o banco parceiro, não a FINEP diretamente, "
            "e não há uma base pública de recusas para comparar.",
        }

    aprovados = conn.execute(
        "SELECT COUNT(*) FROM operations WHERE agencia='FINEP' AND instrumento='Credito Direto'"
    ).fetchone()[0]
    recusados = conn.execute(
        "SELECT COUNT(*) FROM finep_nao_aprovados_raw WHERE instrumento='Crédito Direto'"
    ).fetchone()[0]
    total = aprovados + recusados
    if total == 0:
        return {"disponivel": False, "motivo": "Sem dados suficientes de aprovados/recusados para calcular."}

    return {
        "disponivel": True,
        "agencia": agencia_principal,
        "instrumento": instrumento_principal,
        "taxa_pct": round(aprovados / total * 100, 1),
        "aprovados": aprovados,
        "recusados": recusados,
        "fonte": "Histórico público de projetos aprovados e não aprovados de Crédito Direto da FINEP.",
    }


def _buscar_rapido_nucleo(query: str, query_expandida: str, query_vec, max_resultados: int) -> dict:
    """Nucleo comum de buscar_rapido()/buscar_rapido_com_vetor() -- so precisa do
    vetor da query ja calculado (pelo servidor, modo local, ou pelo navegador, modo
    hospedado) e faz o resto: produto escalar contra o corpus, limiar relativo de
    similaridade, tendencias de setor/segmento e taxa de aprovacao."""
    ids, vectors = _load_embeddings()

    scores = vectors @ query_vec
    ordenado = np.argsort(-scores)
    melhor_score = float(scores[ordenado[0]]) if len(ordenado) else 0.0
    confianca_baixa = melhor_score < CONFIANCA_MINIMA

    limiar = max(melhor_score - MARGEM_RELATIVA, LIMIAR_ABSOLUTO_MINIMO)
    n_acima_limiar = int((scores >= limiar).sum())
    n_selecionar = min(max(MINIMO_RESULTADOS, n_acima_limiar), max_resultados, len(ordenado))
    top_idx = ordenado[:n_selecionar]

    top_ids = ids[top_idx].tolist()
    top_scores = scores[top_idx].tolist()
    score_by_id = dict(zip(top_ids, top_scores))

    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(top_ids))
        rows = conn.execute(
            f"SELECT {', '.join(_COLS_OPERACAO)} FROM operations WHERE id IN ({placeholders})", top_ids
        ).fetchall()
        resultados = [dict(zip(_COLS_OPERACAO, r)) for r in rows]
        for r in resultados:
            r["score"] = round(float(score_by_id.get(r["id"], 0)), 4)
        resultados.sort(key=lambda r: r["score"], reverse=True)

        # A "principal" e definida pelos melhores resultados (nao pela cauda inteira,
        # que pode ter milhares de itens e diluiria o que de fato bateu com a busca).
        melhores = resultados[:30]
        setores_validos = [r["setor_bndes"] for r in melhores if r["setor_bndes"]]
        setor_principal = pd.Series(setores_validos).mode().iloc[0] if setores_validos else None
        segmentos_validos = [r["segmento"] for r in melhores if r["segmento"]]
        segmento_principal = pd.Series(segmentos_validos).mode().iloc[0] if segmentos_validos else None

        tendencia_setor = _tendencia_por_campo(conn, "setor_bndes", setor_principal, "setor") if setor_principal else None
        tendencia_segmento = (
            _tendencia_por_campo(conn, "segmento", segmento_principal, "segmento") if segmento_principal else None
        )
        probabilidade_aprovacao = _estimar_probabilidade_aprovacao(conn, melhores)
    finally:
        conn.close()

    return {
        "query": query,
        "query_expandida": query_expandida,
        "setor_principal": setor_principal,
        "segmento_principal": segmento_principal,
        "tendencia_setor": tendencia_setor,
        "tendencia_segmento": tendencia_segmento,
        "probabilidade_aprovacao": probabilidade_aprovacao,
        "melhor_score": round(melhor_score, 4),
        "confianca_baixa": confianca_baixa,
        "n_resultados": len(resultados),
        "resultados": resultados,
    }


def _combinar_query_com_descricao(query_expandida: str, descricao: str, query_original: str) -> str:
    """Decide como juntar a descricao achada na web com a query antes de reembutir.

    Testado empiricamente (varias queries reais, comparando melhor_score dos dois
    jeitos): quando a query original e UM TOKEN SO (nome de empresa, sigla como "MPR",
    ou um unico nome proprio como "Embraer"/"Natura"), o token em si nao tem nenhum
    equivalente no corpus -- so dilui a descricao real, que sozinha ja pontua melhor
    (ex: "MPR | <descricao>" = 0.56, so "<descricao>" = 0.61; mesmo padrao repetido em
    "Quicksoft", "Embraer", "Natura"). Ja quando a query tem VARIAS PALAVRAS, ela
    normalmente carrega vocabulario real do dominio (ex: "fabricante de sensores
    agricolas TerraSense", "rede de hospitais HealthCore") que a descricao da web pode
    nao mencionar -- ai manter o texto original junto da descricao pontua melhor ou empata
    (nunca pior o suficiente para valer a pena descartar). Por isso: 1 palavra -> so a
    descricao; 2+ palavras -> mantem o comportamento antigo (original + descricao)."""
    if len(query_original.strip().split()) <= 1:
        return descricao
    return f"{query_expandida} | {descricao}"


def buscar_rapido(query: str, max_resultados: int = 3000) -> dict:
    """Chamada RAPIDA (so embeddings + SQLite, sem Ollama) -- retorna resultados quase
    instantaneamente. Modo LOCAL (desktop): calcula o embedding da query no proprio
    processo (get_model()) -- ver buscar_rapido_com_vetor() para o modo hospedado.

    Em vez de um top-K fixo, devolve TODAS as operacoes com similaridade acima do
    limiar de relevancia (ate max_resultados, que e so uma protecao de seguranca,
    nao um limite pratico) -- assim uma busca especifica traz todas as operacoes
    parecidas que existem, nao so uma amostra arbitraria.

    Se a 1a passada vier com confianca_baixa (ex: nome de empresa que nunca pegou
    credito incentivado, como "Quicksoft"), tenta UMA 2a passada: pesquisa `query` na
    web (buscar_atividade_empresa, ver empresa_lookup.py) para descobrir o que a
    empresa/termo faz e reembute a query com esse reforco. So substitui o resultado
    original se o novo melhor_score for de fato melhor -- e so paga o custo da busca
    web quando a 1a passada ja falhou, entao uma busca normal (confianca_baixa=False)
    nao tem nenhuma latencia extra."""
    query_expandida = _expandir_query(query)
    model = get_model()
    query_vec = model.encode([query_expandida], normalize_embeddings=True)[0]
    resultado = _buscar_rapido_nucleo(query, query_expandida, query_vec, max_resultados)
    resultado["query_original"] = query
    resultado["enriquecido_via_web"] = False

    if resultado["confianca_baixa"]:
        descricao = buscar_atividade_empresa(query)
        if descricao:
            query_enriquecida = _combinar_query_com_descricao(query_expandida, descricao, query)
            vec_enriquecido = model.encode([query_enriquecida], normalize_embeddings=True)[0]
            candidato = _buscar_rapido_nucleo(query, query_enriquecida, vec_enriquecido, max_resultados)
            if candidato["melhor_score"] > resultado["melhor_score"]:
                candidato["query_original"] = query
                candidato["enriquecido_via_web"] = True
                resultado = candidato

    return resultado


def buscar_rapido_com_vetor(query: str, query_vec, max_resultados: int = 3000) -> dict:
    """Mesma logica de buscar_rapido(), mas para o modo HOSPEDADO: o vetor da query ja
    vem calculado no navegador (transformers.js, ver webapp/static/js/embeddings-
    client.js, contra o texto devolvido por /api/busca/preparar) -- o servidor NUNCA
    chama get_model()/SentenceTransformer aqui, so faz a matematica (numpy) contra os
    vetores precalculados do corpus (data/embeddings.npz). E isso que permite rodar no
    free tier do Render (512MB de RAM): carregar o sentence-transformers no processo
    estouraria esse limite (ver DEPLOY.md)."""
    query_expandida = _expandir_query(query)
    vetor = np.asarray(query_vec, dtype=np.float32)
    norma = float(np.linalg.norm(vetor))
    if norma > 0:
        vetor = vetor / norma
    return _buscar_rapido_nucleo(query, query_expandida, vetor, max_resultados)


def preparar_texto_enriquecido(query: str) -> dict:
    """Equivalente hospedado do bloco de enriquecimento dentro de buscar_rapido():
    o embedding roda no NAVEGADOR nesse modo, entao este servidor so pode fazer a
    parte que nao envolve modelo -- a busca web (buscar_atividade_empresa, requests
    puro, sem custo de RAM) -- e devolver o texto para o navegador reembutir e
    chamar POST /api/busca de novo. So deve ser chamado pelo cliente DEPOIS que a
    1a chamada a POST /api/busca ja voltou com confianca_baixa=True (ver rota
    /api/busca/preparar_enriquecido em webapp/main.py e o retry em busca.js)."""
    descricao = buscar_atividade_empresa(query)
    if not descricao:
        return {"query_expandida": _expandir_query(query), "enriquecido_via_web": False}
    query_enriquecida = _combinar_query_com_descricao(_expandir_query(query), descricao, query)
    return {"query_expandida": query_enriquecida, "enriquecido_via_web": True}


def buscar(query: str, max_resultados: int = 3000) -> dict:
    """Conveniencia para uso via CLI/testes: roda a busca rapida + a narrativa em uma chamada so."""
    r = buscar_rapido(query, max_resultados=max_resultados)
    r["narrativa"] = gerar_narrativa(
        r["query_expandida"], r["tendencia_segmento"], r["tendencia_setor"], r["resultados"], r["confianca_baixa"]
    )
    return r


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "empresa de hospitais em SP"
    print(json.dumps(buscar(q), ensure_ascii=False, indent=2, default=str))
