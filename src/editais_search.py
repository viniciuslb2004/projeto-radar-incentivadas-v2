"""Endgame da aba Editais: usuario descreve um projeto/empresa, o sistema acha os
editais ABERTOS mais aderentes (embeddings locais) e gera uma leitura de elegibilidade
(Ollama local, com fallback de template). Tambem gera o resumo de elegibilidade sob
demanda de um edital especifico (cacheado em editais_raw.resumo_ia)."""
import datetime
import json

import numpy as np
import requests

from db import get_connection
from editais_embeddings import EMB_PATH, build_editais_embeddings
from embeddings import get_model

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b-instruct-q4_K_M"
OLLAMA_TIMEOUT = 60
# Resumo por documento real (Regulamento + Anexo 1) manda um prompt bem maior que os
# outros -- precisa de mais margem para um modelo 3B em CPU terminar a tempo.
OLLAMA_TIMEOUT_RESUMO = 300
OLLAMA_TIMEOUT_REFINO = 90

# Corpus pequeno (dezenas de editais abertos, nao milhares de operacoes) -- limiares
# mais permissivos que os da busca de operacoes, senao uma busca legitima pode nao
# achar nada so porque nenhum edital bate 40%+ de similaridade de texto.
MARGEM_RELATIVA = 0.12
LIMIAR_ABSOLUTO_MINIMO = 0.25
MINIMO_RESULTADOS = 5

_emb_cache = None

_COLS_EDITAL = [
    "id", "titulo", "tema_principal", "temas", "situacao", "tipo_oportunidade",
    "tipo_cooperacao", "contrapartida", "regiao", "publico_alvo", "aplicavel_empresa",
    "data_publicacao", "vigencia_inicio", "vigencia_fim", "prazo_proposto",
    "descricao_texto", "documentos", "documento_chave_texto",
]


def _load_editais_embeddings():
    global _emb_cache
    if _emb_cache is None:
        if not EMB_PATH.exists():
            build_editais_embeddings()
        data = np.load(EMB_PATH)
        _emb_cache = (data["ids"], data["vectors"])
    return _emb_cache


def warmup():
    get_model()
    _load_editais_embeddings()


def _dias_restantes(prazo_iso: str):
    if not prazo_iso:
        return None
    try:
        prazo = datetime.datetime.fromisoformat(prazo_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    agora = datetime.datetime.now(datetime.timezone.utc)
    return (prazo.date() - agora.date()).days


def _montar_edital(row: dict) -> dict:
    row = dict(row)
    row["publico_alvo"] = json.loads(row["publico_alvo"]) if row.get("publico_alvo") else []
    row["documentos"] = json.loads(row["documentos"]) if row.get("documentos") else []
    row["dias_restantes"] = _dias_restantes(row.get("prazo_proposto"))
    return row


def buscar_editais_por_projeto(query: str, max_resultados: int = 15) -> dict:
    """Busca RAPIDA (so embeddings): compara a descricao do usuario contra o titulo/tema/
    descricao de cada edital ABERTO e devolve os mais aderentes, do mais para o menos."""
    ids, vectors = _load_editais_embeddings()
    if len(ids) == 0:
        return {"query": query, "melhor_score": 0.0, "confianca_baixa": True, "resultados": []}

    model = get_model()
    qvec = model.encode([query], normalize_embeddings=True)[0]
    scores = vectors @ qvec
    ordenado = np.argsort(-scores)
    melhor_score = float(scores[ordenado[0]])

    limiar = max(melhor_score - MARGEM_RELATIVA, LIMIAR_ABSOLUTO_MINIMO)
    n_acima_limiar = int((scores >= limiar).sum())
    n_selecionar = min(max(MINIMO_RESULTADOS, n_acima_limiar), max_resultados, len(ordenado))
    top_idx = ordenado[:n_selecionar]

    top_ids = ids[top_idx].tolist()
    score_by_id = dict(zip(top_ids, scores[top_idx].tolist()))

    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(top_ids))
        rows = conn.execute(
            f"SELECT {', '.join(_COLS_EDITAL)} FROM editais_raw WHERE id IN ({placeholders})", top_ids
        ).fetchall()
    finally:
        conn.close()

    resultados = [_montar_edital(dict(zip(_COLS_EDITAL, r))) for r in rows]
    for r in resultados:
        r["score"] = round(float(score_by_id.get(r["id"], 0)), 4)
    resultados.sort(key=lambda r: r["score"], reverse=True)

    return {
        "query": query,
        "melhor_score": round(melhor_score, 4),
        "confianca_baixa": melhor_score < 0.30,
        "n_resultados": len(resultados),
        "resultados": resultados,
    }


def refinar_editais(query: str, resultados: list, max_avaliar: int = 25) -> dict:
    """Chamada LENTA (Ollama). O corpus de editais abertos e pequeno, entao a busca por
    embeddings sempre devolve ALGUM resultado -- mesmo quando nada e realmente elegivel
    (ex: uma fabricante de baterias batendo com um edital de Defesa so por semelhanca de
    texto generica). Esta etapa revisa os candidatos e remove os que nao tem relacao de
    elegibilidade REAL, em vez de mostrar tudo que passou no limiar de similaridade.
    Se o Ollama falhar, devolve a lista original sem mudar nada -- nunca some com os
    resultados so por causa de uma falha tecnica."""
    if not resultados:
        return {"resultados": [], "refinado": False, "n_removidos": 0, "n_originais": 0}

    candidatos = resultados[:max_avaliar]
    lista = "\n".join(
        f"{r['id']}: \"{r['titulo']}\" | tema: {r.get('tema_principal') or 'nao informado'} | "
        f"aplicavel a empresa: {'sim' if r.get('aplicavel_empresa') else 'nao'} | "
        f"publico-alvo: {', '.join(r.get('publico_alvo') or []) or 'nao informado'} | "
        f"trecho: {(r.get('descricao_texto') or '')[:220]}"
        for r in candidatos
    )
    prompt = (
        "Voce e um analista revisando os resultados de uma busca semantica automatica que tenta achar "
        "editais/chamadas publicas ABERTAS da FINEP para as quais uma empresa/projeto especifico pode se "
        "candidatar. A busca por similaridade de texto costuma trazer falsos positivos: editais com "
        "palavras parecidas mas SEM relacao real de elegibilidade (tema errado, publico-alvo incompativel, "
        "foco tecnico completamente diferente do que foi descrito).\n\n"
        f'O usuario descreveu: "{query}"\n\n'
        f"Editais candidatos (id: titulo | tema | aplicavel a empresa | publico-alvo | trecho):\n{lista}\n\n"
        'Responda APENAS com um JSON no formato {"relevantes": [id1, id2, ...]}\n'
        "Inclua SOMENTE os IDs de editais para os quais uma empresa/projeto como o descrito teria uma chance "
        "REAL e especifica de se candidatar. NAO inclua um edital so porque o tema soa parecido em termos "
        "genericos (ex: um edital de 'Defesa Nacional' NAO serve para uma empresa comum so porque o produto "
        "dela poderia teoricamente ter uso militar, a menos que o trecho realmente mencione esse uso). "
        "Se NENHUM candidato tiver relacao real, devolva uma lista vazia -- isso e uma resposta valida e "
        "esperada quando a base de editais abertos simplesmente nao tem nada para esse caso especifico."
    )
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
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

        by_id = {r["id"]: r for r in candidatos}
        refinados = [by_id[i] for i in dict.fromkeys(ids_relevantes)]
        return {
            "resultados": refinados,
            "refinado": True,
            "n_removidos": len(candidatos) - len(refinados),
            "n_originais": len(candidatos),
        }
    except Exception:
        return {"resultados": resultados, "refinado": False, "n_removidos": 0, "n_originais": len(resultados)}


def _fmt_prazo(edital: dict) -> str:
    dias = edital.get("dias_restantes")
    if dias is None:
        return "prazo não informado"
    if dias < 0:
        return "prazo já encerrado"
    if dias == 0:
        return "encerra hoje"
    return f"faltam {dias} dias"


def _template_leitura(query: str, resultados: list) -> str:
    if not resultados:
        return f'Não encontrei nenhum edital aberto da FINEP compatível com "{query}" na base atual.'
    top = resultados[0]
    partes = [
        f'O edital que mais parece se aplicar a "{query}" é "{top["titulo"]}" '
        f'({_fmt_prazo(top)}{", tema: " + top["tema_principal"] if top.get("tema_principal") else ""}).'
    ]
    if len(resultados) > 1:
        outros = ", ".join(f'"{r["titulo"]}" ({_fmt_prazo(r)})' for r in resultados[1:3])
        partes.append(f"Outros editais abertos que também podem ser relevantes: {outros}.")
    if not top.get("aplicavel_empresa"):
        partes.append("Atenção: este edital, pelo público-alvo declarado, não parece voltado diretamente a empresas -- confira os detalhes antes de aplicar.")
    return " ".join(partes)


def gerar_leitura_elegibilidade(query: str, resultados: list) -> str:
    """Chamada LENTA (Ollama). Le os editais mais aderentes e diz qual(is) parecem mais
    elegiveis para o projeto/empresa descrito, com prazo -- sem inventar requisitos que
    nao estao nos dados."""
    fallback = _template_leitura(query, resultados)
    if not resultados:
        return fallback
    try:
        lista = "\n".join(
            f"- \"{r['titulo']}\" | tema: {r.get('tema_principal') or 'nao informado'} | "
            f"aplicavel a empresa: {'sim' if r.get('aplicavel_empresa') else 'nao'} | "
            f"{_fmt_prazo(r)} | contrapartida: {r.get('contrapartida') or 'nao informada'} | "
            f"trecho: {(r.get('descricao_texto') or '')[:220]}"
            for r in resultados[:6]
        )
        prompt = (
            "Voce e um analista que ajuda empresas a encontrar editais/chamadas publicas abertas da FINEP "
            "para as quais elas podem se candidatar.\n\n"
            f'O usuario descreveu seu projeto/empresa assim: "{query}"\n\n'
            f"Editais abertos mais aderentes encontrados (mais para menos aderente):\n{lista}\n\n"
            "Escreva um paragrafo de 3-5 frases em portugues:\n"
            "1) Diga qual edital (ou quais, se mais de um fizer sentido) parece mais adequado, citando o "
            "nome exato do edital e o prazo informado.\n"
            "2) Explique em 1 frase por que ele parece aderente ao que foi descrito.\n"
            "3) Se o edital nao parecer voltado a empresas (aplicavel a empresa = nao), avise isso "
            "explicitamente.\n"
            "4) Se nenhum edital parecer realmente aderente, diga isso claramente em vez de forcar uma "
            "recomendacao.\n"
            "Nao invente requisitos, valores ou prazos que nao estao na lista acima. "
            "Responda direto com o paragrafo -- sem introducoes tipo 'aqui esta', sem comentar a tarefa."
        )
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}},
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        texto = resp.json().get("response", "").strip()
        return texto or fallback
    except Exception:
        return fallback


def _template_resumo_elegibilidade(edital: dict) -> str:
    chaves_publico = {
        "empresa1": "empresas de menor porte/receita",
        "empresa2": "empresas de porte médio-baixo",
        "empresa3": "empresas de porte médio",
        "empresa4": "empresas de porte médio-alto",
        "empresa5": "empresas de grande porte",
        "ict": "Instituições Científicas, Tecnológicas e de Inovação (ICTs)",
        "startup": "startups",
        "cooperativa": "cooperativas",
        "fundos": "fundos de investimento",
        "produtorRural": "produtores rurais",
    }
    publicos = [chaves_publico.get(p, p) for p in (edital.get("publico_alvo") or [])]
    quem = ", ".join(publicos) if publicos else "público não detalhado nos metadados"
    aviso_documento = (
        ""
        if edital.get("documento_chave_texto")
        else " (Não foi possível ler o Regulamento/Anexo 1 automaticamente -- linhas temáticas, valores e "
        "contrapartida detalhados não estão disponíveis aqui; confira os documentos anexos.)"
    )
    return (
        f'Público-alvo declarado: {quem}. '
        f'{_fmt_prazo(edital).capitalize()}. '
        f'{"Este edital é aplicável a empresas." if edital.get("aplicavel_empresa") else "Este edital NÃO parece voltado diretamente a empresas, pelo público-alvo declarado."}'
        f'{aviso_documento}'
    )


def resumir_edital(edital_id: int, forcar: bool = False) -> dict:
    """Resumo de elegibilidade de UM edital, gerado sob demanda e cacheado em
    editais_raw (resumo_ia/resumo_gerado_em) -- so regenera se forcar=True ou se
    ainda nao existir cache, para nao gastar CPU em editais que ninguem abriu."""
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT {', '.join(_COLS_EDITAL)}, resumo_ia, resumo_gerado_em FROM editais_raw WHERE id=?",
            (edital_id,),
        ).fetchone()
        if not row:
            return {"erro": "Edital não encontrado."}

        cols = _COLS_EDITAL + ["resumo_ia", "resumo_gerado_em"]
        edital = _montar_edital(dict(zip(cols, row)))

        if edital.get("resumo_ia") and not forcar:
            return {"resumo": edital["resumo_ia"], "gerado_em": edital.get("resumo_gerado_em"), "cache": True}

        fallback = _template_resumo_elegibilidade(edital)
        resumo = fallback
        try:
            publicos_txt = ", ".join(edital.get("publico_alvo") or []) or "não informado"
            documento_chave = edital.get("documento_chave_texto")
            if documento_chave:
                fonte_label = "Texto extraído do Regulamento e do Anexo 1 deste edital"
                fonte_texto = documento_chave
            else:
                fonte_label = "Descrição resumida do edital (Regulamento/Anexo 1 não puderam ser lidos automaticamente)"
                fonte_texto = (edital.get("descricao_texto") or "")[:3000]

            prompt = (
                "Voce e um analista resumindo um edital/chamada publica da FINEP para uma empresa que quer "
                "saber rapidamente se pode se candidatar e em quais condicoes.\n\n"
                f"Titulo: {edital['titulo']}\n"
                f"Tema: {edital.get('tema_principal') or 'nao informado'}\n"
                f"Publico-alvo (chaves brutas): {publicos_txt}\n"
                f"Tipo de oportunidade: {edital.get('tipo_oportunidade') or 'nao informado'}\n"
                f"Contrapartida (categoria declarada pela FINEP): {edital.get('contrapartida') or 'nao informada'}\n"
                f"Regiao: {edital.get('regiao') or 'nao informada'}\n"
                f"{_fmt_prazo(edital).capitalize()}.\n\n"
                f"{fonte_label}:\n{fonte_texto}\n\n"
                "Com base SOMENTE no texto acima, responda em portugues, em 4 topicos curtos e objetivos:\n"
                "1) Linhas tematicas: liste cada linha tematica ou grupo de concorrencia mencionado e o tema/foco "
                "de cada uma (se so houver uma linha, descreva-a).\n"
                "2) Valor: o valor minimo e maximo que pode ser solicitado, com os numeros exatos do texto "
                "(diferencie por tipo de arranjo se o texto fizer essa distincao).\n"
                "3) Quem pode pleitear: que tipo de empresa/arranjo e elegivel (porte, parcerias/ICTs exigidas, "
                "restricoes).\n"
                "4) Contrapartida: o percentual ou tipo de contrapartida exigido.\n"
                "Se alguma dessas informacoes NAO aparecer no texto acima, escreva 'nao informado no documento' "
                "para aquele item -- NUNCA invente numeros, percentuais ou linhas que nao estao no texto. "
                "Responda direto com os 4 topicos -- sem introducoes tipo 'aqui esta', sem comentar a tarefa, "
                "sem repetir estas instrucoes."
            )
            resp = requests.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}},
                timeout=OLLAMA_TIMEOUT_RESUMO if documento_chave else OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            texto = resp.json().get("response", "").strip()
            resumo = texto or fallback
        except Exception:
            resumo = fallback

        agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            "UPDATE editais_raw SET resumo_ia=?, resumo_gerado_em=? WHERE id=?", (resumo, agora, edital_id)
        )
        conn.commit()
        return {"resumo": resumo, "gerado_em": agora, "cache": False}
    finally:
        conn.close()


# ============================================================================
# MODO HOSPEDADO (deploy compartilhado): as funcoes acima chamam o Ollama
# diretamente do backend -- funciona perfeito no app local (desktop), onde o
# Ollama roda na MESMA maquina que o servidor. Mas no deploy hospedado (varias
# pessoas, servidor num serviço tipo Render) nao ha Ollama nenhum rodando no
# servidor -- por isso as funcoes abaixo so MONTAM o prompt (sem chamar IA
# nenhuma); quem efetivamente gera o texto e o navegador de cada pessoa, contra
# o Ollama que ELA tem instalado localmente (botao "baixar IA local" no site).
# O resumo de edital continua cacheado no banco compartilhado -- a primeira
# pessoa que gerar um resumo "doa" o resultado pra todo mundo depois.
# ============================================================================


def montar_prompt_resumo(edital: dict) -> dict:
    """Mesmo prompt de resumir_edital(), so que devolvido em vez de enviado ao
    Ollama -- o chamador (rota /api/editais/{id}/resumo em modo hospedado) e quem
    decide se ja tem cache ou se precisa pedir pro navegador gerar."""
    publicos_txt = ", ".join(edital.get("publico_alvo") or []) or "não informado"
    documento_chave = edital.get("documento_chave_texto")
    if documento_chave:
        fonte_label = "Texto extraído do Regulamento e do Anexo 1 deste edital"
        fonte_texto = documento_chave
    else:
        fonte_label = "Descrição resumida do edital (Regulamento/Anexo 1 não puderam ser lidos automaticamente)"
        fonte_texto = (edital.get("descricao_texto") or "")[:3000]

    prompt = (
        "Voce e um analista resumindo um edital/chamada publica da FINEP para uma empresa que quer "
        "saber rapidamente se pode se candidatar e em quais condicoes.\n\n"
        f"Titulo: {edital['titulo']}\n"
        f"Tema: {edital.get('tema_principal') or 'nao informado'}\n"
        f"Publico-alvo (chaves brutas): {publicos_txt}\n"
        f"Tipo de oportunidade: {edital.get('tipo_oportunidade') or 'nao informado'}\n"
        f"Contrapartida (categoria declarada pela FINEP): {edital.get('contrapartida') or 'nao informada'}\n"
        f"Regiao: {edital.get('regiao') or 'nao informada'}\n"
        f"{_fmt_prazo(edital).capitalize()}.\n\n"
        f"{fonte_label}:\n{fonte_texto}\n\n"
        "Com base SOMENTE no texto acima, responda em portugues, em 4 topicos curtos e objetivos:\n"
        "1) Linhas tematicas: liste cada linha tematica ou grupo de concorrencia mencionado e o tema/foco "
        "de cada uma (se so houver uma linha, descreva-a).\n"
        "2) Valor: o valor minimo e maximo que pode ser solicitado, com os numeros exatos do texto "
        "(diferencie por tipo de arranjo se o texto fizer essa distincao).\n"
        "3) Quem pode pleitear: que tipo de empresa/arranjo e elegivel (porte, parcerias/ICTs exigidas, "
        "restricoes).\n"
        "4) Contrapartida: o percentual ou tipo de contrapartida exigido.\n"
        "Se alguma dessas informacoes NAO aparecer no texto acima, escreva 'nao informado no documento' "
        "para aquele item -- NUNCA invente numeros, percentuais ou linhas que nao estao no texto. "
        "Responda direto com os 4 topicos -- sem introducoes tipo 'aqui esta', sem comentar a tarefa, "
        "sem repetir estas instrucoes."
    )
    return {
        "prompt": prompt,
        "modelo": OLLAMA_MODEL,
        "opcoes": {"temperature": 0.1},
        "fallback": _template_resumo_elegibilidade(edital),
    }


def salvar_resumo(edital_id: int, resumo_texto: str) -> dict:
    """Salva no cache compartilhado o resumo que o navegador de alguem acabou de
    gerar -- a partir daqui, todo mundo que abrir esse edital ve o mesmo resumo
    sem precisar gerar de novo."""
    if not resumo_texto or not resumo_texto.strip():
        return {"erro": "resumo vazio"}
    conn = get_connection()
    try:
        agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            "UPDATE editais_raw SET resumo_ia=?, resumo_gerado_em=? WHERE id=?",
            (resumo_texto.strip(), agora, edital_id),
        )
        conn.commit()
        return {"resumo": resumo_texto.strip(), "gerado_em": agora, "cache": False}
    finally:
        conn.close()


def montar_prompt_refino(query: str, resultados: list, max_avaliar: int = 25) -> dict:
    """Mesmo prompt de refinar_editais(), devolvido para o navegador gerar. A
    filtragem do JSON de resposta acontece no proprio navegador (aplicar_refino_local
    em local-ai.js) -- nao precisa de volta ao servidor, e um filtro sem efeito
    colateral nenhum (nao mexe no banco)."""
    if not resultados:
        return {"prompt": None, "candidatos_ids": [], "restante_ids": []}

    candidatos = resultados[:max_avaliar]
    lista = "\n".join(
        f"{r['id']}: \"{r['titulo']}\" | tema: {r.get('tema_principal') or 'nao informado'} | "
        f"aplicavel a empresa: {'sim' if r.get('aplicavel_empresa') else 'nao'} | "
        f"publico-alvo: {', '.join(r.get('publico_alvo') or []) or 'nao informado'} | "
        f"trecho: {(r.get('descricao_texto') or '')[:220]}"
        for r in candidatos
    )
    prompt = (
        "Voce e um analista revisando os resultados de uma busca semantica automatica que tenta achar "
        "editais/chamadas publicas ABERTAS da FINEP para as quais uma empresa/projeto especifico pode se "
        "candidatar. A busca por similaridade de texto costuma trazer falsos positivos: editais com "
        "palavras parecidas mas SEM relacao real de elegibilidade (tema errado, publico-alvo incompativel, "
        "foco tecnico completamente diferente do que foi descrito).\n\n"
        f'O usuario descreveu: "{query}"\n\n'
        f"Editais candidatos (id: titulo | tema | aplicavel a empresa | publico-alvo | trecho):\n{lista}\n\n"
        'Responda APENAS com um JSON no formato {"relevantes": [id1, id2, ...]}\n'
        "Inclua SOMENTE os IDs de editais para os quais uma empresa/projeto como o descrito teria uma chance "
        "REAL e especifica de se candidatar. NAO inclua um edital so porque o tema soa parecido em termos "
        "genericos (ex: um edital de 'Defesa Nacional' NAO serve para uma empresa comum so porque o produto "
        "dela poderia teoricamente ter uso militar, a menos que o trecho realmente mencione esse uso). "
        "Se NENHUM candidato tiver relacao real, devolva uma lista vazia -- isso e uma resposta valida e "
        "esperada quando a base de editais abertos simplesmente nao tem nada para esse caso especifico."
    )
    return {
        "prompt": prompt,
        "modelo": OLLAMA_MODEL,
        "opcoes": {"temperature": 0.1, "format": "json"},
        "candidatos_ids": [r["id"] for r in candidatos],
    }


def montar_prompt_leitura(query: str, resultados: list) -> dict:
    """Mesmo prompt de gerar_leitura_elegibilidade(), devolvido para o navegador
    gerar. Nao e cacheado -- e uma leitura sobre uma descricao livre da pessoa,
    diferente pra cada visitante, entao nao ha o que compartilhar."""
    fallback = _template_leitura(query, resultados)
    if not resultados:
        return {"prompt": None, "fallback": fallback}

    lista = "\n".join(
        f"- \"{r['titulo']}\" | tema: {r.get('tema_principal') or 'nao informado'} | "
        f"aplicavel a empresa: {'sim' if r.get('aplicavel_empresa') else 'nao'} | "
        f"{_fmt_prazo(r)} | contrapartida: {r.get('contrapartida') or 'nao informada'} | "
        f"trecho: {(r.get('descricao_texto') or '')[:220]}"
        for r in resultados[:6]
    )
    prompt = (
        "Voce e um analista que ajuda empresas a encontrar editais/chamadas publicas abertas da FINEP "
        "para as quais elas podem se candidatar.\n\n"
        f'O usuario descreveu seu projeto/empresa assim: "{query}"\n\n'
        f"Editais abertos mais aderentes encontrados (mais para menos aderente):\n{lista}\n\n"
        "Escreva um paragrafo de 3-5 frases em portugues:\n"
        "1) Diga qual edital (ou quais, se mais de um fizer sentido) parece mais adequado, citando o "
        "nome exato do edital e o prazo informado.\n"
        "2) Explique em 1 frase por que ele parece aderente ao que foi descrito.\n"
        "3) Se o edital nao parecer voltado a empresas (aplicavel a empresa = nao), avise isso "
        "explicitamente.\n"
        "4) Se nenhum edital parecer realmente aderente, diga isso claramente em vez de forcar uma "
        "recomendacao.\n"
        "Nao invente requisitos, valores ou prazos que nao estao na lista acima. "
        "Responda direto com o paragrafo -- sem introducoes tipo 'aqui esta', sem comentar a tarefa."
    )
    return {"prompt": prompt, "modelo": OLLAMA_MODEL, "opcoes": {"temperature": 0.2}, "fallback": fallback}


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "startup de inteligencia artificial para o agronegocio"
    r = buscar_editais_por_projeto(q)
    r["leitura"] = gerar_leitura_elegibilidade(q, r["resultados"])
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
