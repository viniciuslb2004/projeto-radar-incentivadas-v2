# Estado do projeto (atualizado em 2026-08-19)

## Como retomar

```powershell
cd "C:\Users\ViníciusBorrellas\OneDrive - Ártica\Desenvolvimento - Incentivadas"
.venv\Scripts\python.exe -m uvicorn webapp.main:app --host 127.0.0.1 --port 8001
```

Depois abra http://127.0.0.1:8001 — os dados, embeddings e banco já estão prontos, não precisa rodar mais nada.

Se a porta 8001 estiver ocupada (ou o servidor não responder), troque para outra porta (ex: `--port 8002`) e ajuste a URL.

Ollama (usado pela Busca e pela aba Editais para gerar textos/resumos) já está rodando via o atalho de Inicialização do Windows -- não precisa religar manualmente. Se algum dia ele estiver parado:
```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```
Sem o Ollama rodando, Busca e Editais continuam funcionando (resultados e filtros), só os textos gerados por IA caem no fallback de template.

## O que já está pronto e funcionando

- Base unificada: 28.780 operações (23.723 BNDES + 5.057 FINEP crédito), setor 100% classificado nas duas agências.
- Granularidade em 3 níveis: Setor (4), Subsetor (19), Segmento CNAE (~1.290, ex: "Extração de Minério de Ferro").
- 4 páginas: Consolidado, Tendências & Insights (com painéis de subsetor e segmento), Busca (semântica, local, com narrador via Ollama), e Editais (chamadas públicas abertas da FINEP).
- Filtro de período com granularidade de mês/ano; tendências sempre comparam o período selecionado (capado em 12 meses) vs. o período equivalente anterior.
- Ordenação (data/valor/instituição) nos resultados de busca, na tabela de operações e no modal de detalhe.
- Tarefas agendadas no Windows Task Scheduler já registradas e funcionando sozinhas, sem precisar do Claude Code:
  - `RadarCreditoIncentivado` — refresh semanal (BNDES + FINEP), toda segunda 7h.
  - `RadarCreditoIncentivado_EnriquecimentoCNAE` — reenriquecimento de setor da FINEP, a cada 4 semanas.
  - `RadarCreditoIncentivado_Editais` — refresh diário dos editais da FINEP, todo dia às 6h30.
- Ollama instalado e rodando como serviço (`ollama app`), modelo `llama3.1:8b-instruct-q4_K_M` já baixado (trocado do 3B para o 8B em 2026-08 -- resultados bem melhores em resumo de edital e busca por empresa/CNPJ, precisa de mais RAM livre).

## Aba Editais (FINEP Oportunidades) -- adicionada em 2026-08-19

- Puxa direto da API pública da FINEP (`o/c/chamadapublicas`), não é scraping de HTML.
- Filtro padrão: só editais realmente abertos (a própria FINEP às vezes mantém `situacao='aberta'`
  com o `prazo_proposto` já vencido -- o app corrige isso automaticamente, tanto na lista quanto
  no corpus do endgame) e só aplicável a empresas (empresa1-5/startup/cooperativa).
- Dashboard com nº de editais abertos, quantos fecham em até 30 dias, e quebra por tema (clicável).
- **Documentos reais**: além dos manuais genéricos da plataforma, o app busca o Regulamento, todos
  os Anexos, FAQ e resultados parciais de cada edital aberto via um endpoint separado da FINEP
  (`/o/c/chamadapublicas/{id}/documentos`, autenticado com um token "guest" público que o próprio
  site usa para qualquer visitante anônimo -- não é um contorno de proteção). Ver `src/editais_documentos.py`.
- **Resumo de elegibilidade por IA baseado no documento de verdade**: baixa e extrai o texto do
  Regulamento + Anexo 1 (via `pypdf`) e pede à IA local 4 respostas objetivas: linhas temáticas e
  o tema de cada uma, valor mínimo/máximo, quem pode pleitear, e a contrapartida exigida -- tudo
  cacheado em `editais_raw.documento_chave_texto` (computado uma vez, não todo dia) e no
  `resumo_ia` de cada edital. Quando o Regulamento/Anexo 1 não seguem o padrão usual (alguns
  editais de FIP usam só "Edital" + "Anexos"), há fallback para esses nomes; se nada for
  encontrado, o resumo avisa explicitamente em vez de inventar.
- Endgame: descreva seu projeto/empresa em texto livre → busca rápida por embeddings → uma etapa
  de revisão por IA remove editais que só bateram por semelhança genérica de texto mas não têm
  elegibilidade real (ex: uma fabricante de baterias não deve ver um edital de Defesa só porque
  "bateria" apareceu em ambos) → só then os cards aparecem → leitura final em texto dizendo qual(is)
  edital(is) parecem mais elegíveis, com prazo.
- Refresh diário via `src/refresh_editais.py`, preserva o cache de resumos de IA e do texto dos
  documentos entre execuções (só busca/baixa PDF de edital que ainda não tem o texto cacheado).

## Pendências / próximos passos (quando você voltar)

Nada pendente — todos os itens pedidos até agora foram implementados e testados, incluindo a rodada mais recente (aba Editais + resumo baseado em Regulamento/Anexo 1 reais + refino do endgame).

Ideias em aberto que ainda não foram pedidas:
- Mapa por UF (visual, hoje é só barra/lista) na aba Consolidado.
- Exportar resultados da busca/drill-down para Excel.
- Trazer também as condições financeiras da FINEP na Busca (hoje só o BNDES tem indexador/juros/prazo).
- 3 dos 27 editais abertos não têm nenhum documento identificável pela FINEP (nem "Regulamento/Anexo1"
  nem "Edital/Anexos") -- o resumo desses cai no fallback baseado só na descrição resumida do site.

## Arquivos-chave

- Plano da aba Editais: `C:\Users\ViníciusBorrellas\.claude\plans\binary-booping-reef.md`
- Pipeline de dados (operações): `src/refresh.py` (orquestra tudo), `src/enrich_cnae.py` (pesado, mensal)
- Pipeline de dados (editais): `src/refresh_editais.py` (orquestra `finep_editais.py` + `editais_documentos.py` + `editais_embeddings.py`)
- Motor de busca: `src/search.py` (operações), `src/editais_search.py` (endgame + refino + resumo de editais)
- API + frontend: `webapp/main.py`, `webapp/static/` (`js/editais.js` é a aba nova)
- Banco: `data/radar.db` (SQLite), `data/embeddings.npz` + `data/editais_embeddings.npz` (busca semântica)
