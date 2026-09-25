"""Avaliacao offline do motor de "Potenciais Linhas" (webapp/potenciais.py).

16 perfis realistas com gabarito montado a partir das regras documentadas de cada
linha no catalogo (regiao, porte, publico, setor, finalidade, faixa de valor).
Metrica: precisao@k = acertos no top-k / min(k, |gabarito|) -- normalizada porque
alguns perfis tem so 1-2 linhas corretas no catalogo.

Uso:
    python scripts/avaliar_potenciais.py            # le linhas_incentivadas do banco
    python scripts/avaliar_potenciais.py cat.json   # le de um dump JSON (sem banco)
    python scripts/avaliar_potenciais.py cat.json --antigo caminho/potenciais_old.py
"""
import importlib.util
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))
sys.path.insert(0, RAIZ)

# (nome, perfil v2, parametros equivalentes do motor antigo, gabarito de ids)
PERFIS = [
    ("Pequena indústria SP, máquinas R$2mi",
     dict(atividade="industria", finalidade="maquinas", porte="PEQUENA", volume=2e6, uf="SP"),
     dict(setor="INDUSTRIA", porte="PEQUENA", volume=2e6, uso="Máquinas e equipamentos", uf="SP"),
     {2313, 1314, 2312, 1795, 1797}),
    ("Grande geradora eólica RN R$500mi",
     dict(atividade="energia", finalidade="investimento", porte="GRANDE", volume=500e6, uf="RN"),
     dict(setor="INFRAESTRUTURA", porte="GRANDE", volume=500e6, uso="Infraestrutura", uf="RN"),
     {1796, 2367, 2378, 2372}),
    ("Startup de software SC, inovação R$5mi",
     dict(atividade="ti", finalidade="inovacao", porte="PEQUENA", volume=5e6, uf="SC"),
     dict(setor="COMERCIO/SERVICOS", porte="PEQUENA", volume=5e6, uso="Inovação / P&D", uf="SC"),
     {2402}),
    ("Médio produtor rural MT, custeio R$1,2mi",
     dict(atividade="agro", finalidade="giro", porte="MÉDIA", volume=1.2e6, uf="MT", tomador="produtor_rural"),
     dict(setor="AGROPECUÁRIA", porte="MÉDIA", volume=1.2e6, uso="Capital de giro", uf="MT"),
     {2502, 2319, 2505, 2320}),
    ("Hospital privado BA, expansão R$80mi",
     dict(atividade="saude", finalidade="investimento", porte="GRANDE", volume=80e6, uf="BA"),
     dict(setor="COMERCIO/SERVICOS", porte="GRANDE", volume=80e6, uso="CAPEX / Projetos de investimento", uf="BA"),
     {2305, 2330, 2369}),
    ("Concessionária de saneamento MG R$200mi",
     dict(atividade="saneamento", finalidade="investimento", porte="GRANDE", volume=200e6, uf="MG"),
     dict(setor="INFRAESTRUTURA", porte="GRANDE", volume=200e6, uso="Infraestrutura", uf="MG"),
     {2299, 2324}),
    ("Média indústria exportadora CE, expansão R$20mi",
     dict(atividade="industria", finalidade="investimento", porte="MÉDIA", volume=20e6, uf="CE"),
     dict(setor="INDUSTRIA", porte="MÉDIA", volume=20e6, uso="CAPEX / Projetos de investimento", uf="CE"),
     {2357, 1797}),
    ("Micro varejo PE, capital de giro R$200 mil",
     dict(atividade="comercio", finalidade="giro", porte="MICRO", volume=2e5, uf="PE"),
     dict(setor="COMERCIO/SERVICOS", porte="MICRO", volume=2e5, uso="Capital de giro", uf="PE"),
     {2362, 2364, 2376}),
    ("Média indústria SP, inovação R$15mi",
     dict(atividade="industria", finalidade="inovacao", porte="MÉDIA", volume=15e6, uf="SP"),
     dict(setor="INDUSTRIA", porte="MÉDIA", volume=15e6, uso="Inovação / P&D", uf="SP"),
     {1312, 1313, 2402, 826}),
    ("Grande agroindústria GO, armazém R$60mi",
     dict(atividade="agroindustria", finalidade="investimento", porte="GRANDE", volume=60e6, uf="GO"),
     dict(setor="AGROPECUÁRIA", porte="GRANDE", volume=60e6, uso="CAPEX / Projetos de investimento", uf="GO"),
     {2509, 2323, 2300, 2515}),
    ("Média empresa de turismo BA, R$10mi",
     dict(atividade="turismo", finalidade="investimento", porte="MÉDIA", volume=10e6, uf="BA"),
     dict(setor="COMERCIO/SERVICOS", porte="MÉDIA", volume=10e6, uso="CAPEX / Projetos de investimento", uf="BA"),
     {2366, 1797}),
    ("Grande operador portuário PA, R$300mi",
     dict(atividade="logistica", finalidade="investimento", porte="GRANDE", volume=300e6, uf="PA"),
     dict(setor="INFRAESTRUTURA", porte="GRANDE", volume=300e6, uso="Infraestrutura", uf="PA"),
     {2495, 2303, 2500, 2513}),
    ("Média indústria SP, eficiência energética R$5mi",
     dict(atividade="industria", finalidade="sustentabilidade", porte="MÉDIA", volume=5e6, uf="SP"),
     dict(setor="INDUSTRIA", porte="MÉDIA", volume=5e6, uso="Eficiência energética / Sustentabilidade", uf="SP"),
     {1311, 1316, 2315, 2511, 2510}),
    ("Pequena franquia RJ, abertura R$500 mil",
     dict(atividade="comercio", finalidade="investimento", porte="PEQUENA", volume=5e5, uf="RJ"),
     dict(setor="COMERCIO/SERVICOS", porte="PEQUENA", volume=5e5, uso="CAPEX / Projetos de investimento", uf="RJ"),
     {2512, 1797, 1795}),
    ("Grande provedor de telecom GO, R$100mi",
     dict(atividade="telecom", finalidade="investimento", porte="GRANDE", volume=100e6, uf="GO"),
     dict(setor="INFRAESTRUTURA", porte="GRANDE", volume=100e6, uso="Infraestrutura", uf="GO"),
     {2298, 1797}),
    ("Cooperativa agro PR, capital de giro R$30mi",
     dict(atividade="agro", finalidade="giro", porte="GRANDE", volume=30e6, uf="PR", tomador="cooperativa"),
     dict(setor="AGROPECUÁRIA", porte="GRANDE", volume=30e6, uso="Capital de giro", uf="PR"),
     {2317, 2320}),
]


def _carregar_catalogo(caminho):
    if caminho:
        with open(caminho, encoding="utf8") as f:
            return json.load(f)
    from db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cols = [r[0] for r in cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='linhas_incentivadas' "
        "ORDER BY ordinal_position").fetchall()]
    dados = [dict(zip(cols, r)) for r in cur.execute("SELECT * FROM linhas_incentivadas").fetchall()]
    conn.close()
    return dados


def _p_at(ids, gab, k):
    return len(set(ids[:k]) & gab) / min(k, len(gab))


def _ranking_novo(pot, catalogo, perfil_kw):
    perfil, erro = pot._perfil_de_parametros(perfil_kw.get("atividade"), None, perfil_kw.get("porte"),
                                             perfil_kw.get("volume"), perfil_kw.get("finalidade"), None,
                                             perfil_kw.get("uf"), perfil_kw.get("tomador"))
    assert not erro, erro
    ranq, _ = pot.ranquear(catalogo, perfil)
    return [l["id"] for l, av, _ in ranq if av["score_pct"] >= pot.LIMIAR_PRINCIPAL]


def _ranking_antigo(mod, catalogo, kw):
    res = []
    for l in catalogo:
        if kw.get("setor") and l.get("setor_padronizado") not in (kw["setor"], mod.NAO_INFORMADO):
            continue
        p = mod._pontuar_linha(l, kw.get("setor"), kw.get("porte"), kw.get("volume"), kw.get("uso"), uf=kw.get("uf"))
        if p:
            res.append((p[0], l.get("nome_simplificado") or l["nome_oficial"], l["id"]))
    res.sort(key=lambda t: (-t[0], t[1]))
    return [t[2] for t in res]


def main():
    args = sys.argv[1:]
    antigo = None
    if "--antigo" in args:
        i = args.index("--antigo")
        antigo = args[i + 1]
        del args[i:i + 2]
    catalogo = _carregar_catalogo(args[0] if args else None)
    import webapp.potenciais as pot
    motores = [("novo", lambda kw_n, kw_a: _ranking_novo(pot, catalogo, kw_n))]
    if antigo:
        spec = importlib.util.spec_from_file_location("pot_antigo", antigo)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        motores.insert(0, ("antigo", lambda kw_n, kw_a: _ranking_antigo(mod, catalogo, kw_a)))
    nomes = {l["id"]: l.get("nome_simplificado") or l["nome_oficial"] for l in catalogo}
    for rotulo, fn in motores:
        s3 = s5 = 0.0
        print(f"\n===== motor {rotulo}")
        for nome, kw_n, kw_a, gab in PERFIS:
            ids = fn(kw_n, kw_a)
            p3, p5 = _p_at(ids, gab, 3), _p_at(ids, gab, 5)
            s3 += p3
            s5 += p5
            print(f"{p3:4.2f} {p5:4.2f}  {nome}: " + " | ".join(nomes[i] + ("*" if i in gab else "") for i in ids[:5]))
        n = len(PERFIS)
        print(f"MEDIA precisao@3={s3 / n:.2f}  precisao@5={s5 / n:.2f}")


if __name__ == "__main__":
    main()
