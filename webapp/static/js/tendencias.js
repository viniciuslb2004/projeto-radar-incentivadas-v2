// Aba Tendencias & Insights: setores em alta/queda, subsetores, produtos, maiores operacoes.

let chartProdutos, chartSubsetores, chartSegmentos;
let subsetorSelectInicializado = false;
let segmentoSelectInicializado = false;

function fmtPeriodo(periodo) {
  if (!periodo) return "";
  const fmt = (d) => {
    const dt = new Date(d);
    return `${MESES[dt.getUTCMonth()]}/${dt.getUTCFullYear()}`;
  };
  const fimExclusivo = new Date(periodo[1]);
  fimExclusivo.setUTCDate(fimExclusivo.getUTCDate() - 1);
  return `${fmt(periodo[0])} a ${fmt(fimExclusivo)}`;
}

function trendListItem(row, sinal, dataAttr) {
  const badgeClass = sinal === "up" ? "up" : "down";
  const seta = sinal === "up" ? "↑" : "↓";
  const label = row.setor || row.subsetor || row.segmento;
  return `<li data-${dataAttr}="${label}">
    <span>${label}</span>
    <span class="badge ${badgeClass}">${seta} ${Math.abs(row.variacao_pp).toFixed(1)} p.p.</span>
  </li>`;
}

async function loadTendenciasSetores(filters) {
  const data = await fetchJSON("/api/tendencias/setores?" + qs(filters));
  const periodoTxt = data.comparavel
    ? `${fmtPeriodo(data.periodo_atual)} vs. ${fmtPeriodo(data.periodo_anterior)}`
    : `${fmtPeriodo(data.periodo_atual)} · Não é possível informar as porcentagens devido a limitação de períodos da base`;
  document.getElementById("tend-header-alta").firstChild.textContent = "Setores em alta ";
  document.getElementById("tend-header-queda").firstChild.textContent = "Setores em queda ";
  document.querySelectorAll("#tend-header-alta .hint, #tend-header-queda .hint").forEach((el) => el.remove());
  document.getElementById("tend-header-alta").insertAdjacentHTML("beforeend", `<span class="hint">${periodoTxt}</span>`);
  document.getElementById("tend-header-queda").insertAdjacentHTML("beforeend", `<span class="hint">${periodoTxt}</span>`);

  const setores = data.setores.filter((s) => s.setor && s.setor !== "Nao classificado");
  const alta = setores.filter((s) => s.variacao_pp > 0).slice(0, 8);
  const queda = setores.filter((s) => s.variacao_pp < 0).sort((a, b) => a.variacao_pp - b.variacao_pp).slice(0, 8);

  const listaAlta = document.getElementById("lista-alta");
  const listaQueda = document.getElementById("lista-queda");
  listaAlta.innerHTML = alta.map((r) => trendListItem(r, "up", "setor")).join("") || '<li class="empty-state">Sem dados suficientes</li>';
  listaQueda.innerHTML = queda.map((r) => trendListItem(r, "down", "setor")).join("") || '<li class="empty-state">Sem dados suficientes</li>';

  [listaAlta, listaQueda].forEach((ul) => {
    ul.querySelectorAll("li[data-setor]").forEach((li) => {
      li.addEventListener("click", () => openOperacoesModal(`Setor: ${li.dataset.setor}`, { setor: li.dataset.setor }));
    });
  });

  return setores;
}

// Item 3 (pedido 2026-09-23, investigacao real contra producao 2026-09-23): quando o
// usuario filtra por agencia=FINEP + um setor sem nenhuma operacao FINEP classificada
// nele, os graficos de subsetor/segmento abaixo ficavam com um <canvas> em branco,
// sem nenhuma explicacao. Causa raiz confirmada (NAO e CNPJ nao resolvido -- so ~4.6%
// das operacoes FINEP estao assim, ver setor_origem='pendente'): a FINEP nao tem
// classificacao nativa de setor (diferente do BNDES, que vem com setor_bndes direto
// da propria planilha) -- o setor da FINEP e 100% derivado do CNAE da empresa via
// de_para_cnae (ver src/sector_taxonomy.py::build_divisao_map). de_para_cnae tem uma
// ambiguidade REAL e ja documentada (ver comentario em src/db.py sobre a tabela): a
// MESMA divisao CNAE (ex: H49/H50/H51/H52/H53, F41-F43, D35, E36-E39, J61) aparece
// tanto numa faixa generica "Comercio e Servicos" quanto numa faixa mais especifica
// de Infraestrutura, e build_divisao_map() resolve por "ultima linha da tabela
// vence" -- que hoje, pra TODAS essas divisoes, e sempre a linha de "Comercio e
// Servicos". Resultado confirmado ao vivo: das 11405 operacoes FINEP ja classificadas
// (enriquecido), 0 caem em INFRAESTRUTURA (100% ficam em INDUSTRIA/COMERCIO-SERVICOS/
// AGROPECUARIA) -- nao por bug, mas porque a FINEP nao tem nenhuma fonte de dado
// (nem a propria planilha, nem a Receita Federal) que diga qual das duas leituras
// (Comercio/Servicos vs Infraestrutura) se aplica a uma empresa especifica -- o
// proprio BNDES resolve essa ambiguidade com "mais contexto que so CNAE" (ver
// db.py), contexto que simplesmente nao existe pra FINEP. NAO e viavel fechar esse
// gap sem inventar dado (regra do CLAUDE.md) -- a acao correta e deixar isso
// EXPLICITO na UI (ver _avisoClassificacaoVaziaHTML/_aplicarOuLimparAvisoVazio
// abaixo) em vez de mostrar um grafico vazio sem explicacao.
function _avisoClassificacaoVaziaHTML(setor, filters) {
  if (filters && filters.agencia === "FINEP") {
    return (
      `Classificação por subsetor/segmento não disponível para operações da FINEP em "${setor}" com os filtros atuais. ` +
      "A FINEP não informa setor nativamente (diferente do BNDES) -- a classificação vem só do CNAE da empresa, e a " +
      "metodologia oficial do BNDES não permite separar este recorte usando só CNAE (depende de mais contexto, que não " +
      "está disponível para operações da FINEP). Sem outra fonte oficial, não classificamos por estimativa."
    );
  }
  return "Sem operações classificadas por subsetor/segmento para este filtro.";
}

function _aplicarOuLimparAvisoVazio(canvasId, vazio, setor, filters) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const wrap = canvas.closest(".chart-wrap") || canvas.parentElement;
  let aviso = wrap.querySelector(".aviso-classificacao-vazia");
  if (!vazio) {
    canvas.style.display = "";
    if (aviso) aviso.style.display = "none";
    return;
  }
  canvas.style.display = "none";
  if (!aviso) {
    aviso = document.createElement("div");
    aviso.className = "empty-state aviso-classificacao-vazia";
    wrap.appendChild(aviso);
  }
  aviso.textContent = _avisoClassificacaoVaziaHTML(setor, filters);
  aviso.style.display = "block";
}

// Item 1 (pedido 2026-09-23): "AGROPECUARIA"/"COMERCIO/SERVICOS" tem so 1 subsetor no
// crosswalk oficial do BNDES (de_para_cnae) -- confirmado de novo nesta sessao (2a+3a
// investigacao independente, ver historico): consultado o conteudo REAL da tabela em
// producao, todas as linhas de "Comercio e Servicos" (24 faixas de CNAE diferentes) e
// a unica linha de "Agropecuaria" tem subsetor_bndes IGUAL ao proprio setor -- nao e
// uma simplificacao nossa, e assim que a planilha oficial do BNDES vem. NAO existe
// uma versao mais granular dessa classificacao pra abrir mais subsetores sem
// inventar dado. A granularidade real que EXISTE (e ja esta implementada, ver
// loadSegmentos abaixo) e o campo `segmento` (subsetor_cnae_nome nativo do BNDES /
// cnae_descricao real da Receita Federal pra FINEP -- centenas de categorias reais,
// ex: "CULTIVO DE CANA-DE-ACUCAR", "CRIACAO DE AVES" dentro de Agropecuaria).
// Mensagem abaixo so aparece quando o subsetor de fato nao discrimina nada (<=1
// categoria real) -- aponta pra secao de segmento, que ja tem a resposta.
function _avisoSubsetorUnicoHTML(setor) {
  return (
    `A metodologia oficial do BNDES define apenas 1 subsetor para "${setor}" -- não é uma limitação do dashboard, ` +
    'o crosswalk oficial (de_para_cnae) não abre mais categorias aqui. Veja "Detalhe por segmento (CNAE)" abaixo ' +
    "para a granularidade real disponível (centenas de categorias por CNAE)."
  );
}

async function popularSeletorSubsetor(setoresRanking, filters) {
  const select = document.getElementById("subsetor-setor-select");
  if (!subsetorSelectInicializado) {
    const setoresOrdenados = [...setoresRanking].sort((a, b) => b.valor_atual - a.valor_atual);
    select.innerHTML = setoresOrdenados.map((s) => `<option value="${s.setor}">${s.setor}</option>`).join("");
    select.addEventListener("change", () => loadSubsetores(currentFilters()));
    subsetorSelectInicializado = true;
  }
}

async function loadSubsetores(filters) {
  const select = document.getElementById("subsetor-setor-select");
  const setor = select.value;
  if (!setor) return;

  const params = Object.assign({}, filters, { setor });
  const [ranking, breakdown] = await Promise.all([
    fetchJSON("/api/tendencias/subsetores?" + qs(params)),
    fetchJSON("/api/subsetores?" + qs(params)),
  ]);

  const subsetoresValidos = ranking.subsetores.filter((s) => s.subsetor && s.subsetor !== "Nao classificado");
  const alta = subsetoresValidos.filter((s) => s.variacao_pp > 0).slice(0, 6);
  const queda = subsetoresValidos.filter((s) => s.variacao_pp < 0).sort((a, b) => a.variacao_pp - b.variacao_pp).slice(0, 6);

  // ranking.comparavel=false (ver _ranking_variacao em main.py) -- periodo anterior
  // parcial/totalmente fora da cobertura real da base -- variacao_pp vem null pra
  // toda linha, entao alta/queda ficam vazios por acaso; sem essa mensagem
  // especifica, a lista vazia pareceria "sem variacao real" em vez de "nao da pra
  // comparar" (mesma classe de bug ja corrigida na secao de Setores acima).
  const vazioSubsetor = ranking.comparavel
    ? "Sem variação relevante"
    : "Não é possível informar as porcentagens devido a limitação de períodos da base";
  const listaAlta = document.getElementById("lista-subsetor-alta");
  const listaQueda = document.getElementById("lista-subsetor-queda");
  listaAlta.innerHTML = alta.map((r) => trendListItem(r, "up", "subsetor")).join("") || `<li class="empty-state">${vazioSubsetor}</li>`;
  listaQueda.innerHTML = queda.map((r) => trendListItem(r, "down", "subsetor")).join("") || `<li class="empty-state">${vazioSubsetor}</li>`;

  [listaAlta, listaQueda].forEach((ul) => {
    ul.querySelectorAll("li[data-subsetor]").forEach((li) => {
      li.addEventListener("click", () => openOperacoesModal(`${setor} · ${li.dataset.subsetor}`, { setor, subsetor: li.dataset.subsetor }));
    });
  });

  const top = breakdown.filter((b) => b.subsetor && b.subsetor !== "Nao classificado").slice(0, 10);

  if (!top.length) {
    if (chartSubsetores) { chartSubsetores.destroy(); chartSubsetores = null; }
    _aplicarOuLimparAvisoVazio("chart-subsetores", true, setor, filters);
    const avisoUnicoStale = document.getElementById("chart-subsetores").closest(".card-body").querySelector(".aviso-subsetor-unico");
    if (avisoUnicoStale) avisoUnicoStale.style.display = "none";
    return;
  }
  _aplicarOuLimparAvisoVazio("chart-subsetores", false, setor, filters);

  // Item 1: quando o subsetor nao discrimina nada de verdade (so 1 categoria real,
  // ex: Agropecuaria/Comercio e Servicos -- ver comentario em
  // _avisoSubsetorUnicoHTML), avisa e aponta pra secao de segmento em vez de deixar
  // o usuario olhando pra um grafico de barra unica sem contexto. Anexado no
  // .card-body INTEIRO (pai do grid de 2 colunas chart+listas), nunca dentro do
  // .chart-wrap (altura FIXA de 280px pro <canvas>, ver style.css) -- anexar ali
  // faria o texto transbordar por baixo do wrap e sobrepor visualmente a coluna
  // "Em alta/Em queda" ao lado (confirmado ao vivo testando este exato cenario).
  const cardBodySubsetor = document.getElementById("chart-subsetores").closest(".card-body");
  let avisoUnico = cardBodySubsetor.querySelector(".aviso-subsetor-unico");
  if (top.length === 1) {
    if (!avisoUnico) {
      avisoUnico = document.createElement("div");
      avisoUnico.className = "empty-state aviso-subsetor-unico";
      avisoUnico.style.padding = "8px 0 0";
      avisoUnico.style.textAlign = "left";
      cardBodySubsetor.appendChild(avisoUnico);
    }
    avisoUnico.textContent = _avisoSubsetorUnicoHTML(setor);
    avisoUnico.style.display = "block";
  } else if (avisoUnico) {
    avisoUnico.style.display = "none";
  }

  if (chartSubsetores) chartSubsetores.destroy();
  chartSubsetores = new Chart(document.getElementById("chart-subsetores"), {
    type: "bar",
    data: {
      labels: top.map((d) => d.subsetor),
      datasets: [{ data: top.map((d) => d.valor_total), backgroundColor: AZUL_TONS[1] }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => fmtBRLFull(ctx.raw) } } },
      scales: { x: { ticks: { callback: (v) => fmtBRL(v) } } },
      onClick: (evt, els) => {
        if (!els.length) return;
        const subsetor = top[els[0].index].subsetor;
        openOperacoesModal(`${setor} · ${subsetor}`, { setor, subsetor });
      },
    },
  });
}

async function popularSeletorSegmento(setoresRanking) {
  const select = document.getElementById("segmento-setor-select");
  if (!segmentoSelectInicializado) {
    const setoresOrdenados = [...setoresRanking].sort((a, b) => b.valor_atual - a.valor_atual);
    select.innerHTML = setoresOrdenados.map((s) => `<option value="${s.setor}">${s.setor}</option>`).join("");
    select.addEventListener("change", () => loadSegmentos(currentFilters()));
    segmentoSelectInicializado = true;
  }
}

async function loadSegmentos(filters) {
  const select = document.getElementById("segmento-setor-select");
  const setor = select.value;
  if (!setor) return;

  const params = Object.assign({}, filters, { setor, limit: 15 });
  const [ranking, breakdown] = await Promise.all([
    fetchJSON("/api/tendencias/segmentos?" + qs(params)),
    fetchJSON("/api/segmentos?" + qs(params)),
  ]);

  const segmentosValidos = ranking.segmentos.filter((s) => s.segmento && s.segmento !== "Nao classificado");
  const alta = segmentosValidos.filter((s) => s.variacao_pp > 0).slice(0, 6);
  const queda = segmentosValidos.filter((s) => s.variacao_pp < 0).sort((a, b) => a.variacao_pp - b.variacao_pp).slice(0, 6);

  // Mesmo caso de _ranking_variacao/comparavel=false explicado em loadSubsetores acima.
  const vazioSegmento = ranking.comparavel
    ? "Sem variação relevante"
    : "Não é possível informar as porcentagens devido a limitação de períodos da base";
  const listaAlta = document.getElementById("lista-segmento-alta");
  const listaQueda = document.getElementById("lista-segmento-queda");
  listaAlta.innerHTML = alta.map((r) => trendListItem(r, "up", "segmento")).join("") || `<li class="empty-state">${vazioSegmento}</li>`;
  listaQueda.innerHTML = queda.map((r) => trendListItem(r, "down", "segmento")).join("") || `<li class="empty-state">${vazioSegmento}</li>`;

  [listaAlta, listaQueda].forEach((ul) => {
    ul.querySelectorAll("li[data-segmento]").forEach((li) => {
      li.addEventListener("click", () => openOperacoesModal(`${setor} · ${li.dataset.segmento}`, { setor, segmento: li.dataset.segmento }));
    });
  });

  const top = breakdown.filter((b) => b.segmento && b.segmento !== "Nao classificado");

  if (!top.length) {
    if (chartSegmentos) { chartSegmentos.destroy(); chartSegmentos = null; }
    _aplicarOuLimparAvisoVazio("chart-segmentos", true, setor, filters);
    return;
  }
  _aplicarOuLimparAvisoVazio("chart-segmentos", false, setor, filters);

  if (chartSegmentos) chartSegmentos.destroy();
  chartSegmentos = new Chart(document.getElementById("chart-segmentos"), {
    type: "bar",
    data: {
      labels: top.map((d) => d.segmento),
      datasets: [{ data: top.map((d) => d.valor_total), backgroundColor: AZUL_TONS[1] }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => fmtBRLFull(ctx.raw) } } },
      scales: { x: { ticks: { callback: (v) => fmtBRL(v) } } },
      onClick: (evt, els) => {
        if (!els.length) return;
        const segmento = top[els[0].index].segmento;
        openOperacoesModal(`${setor} · ${segmento}`, { setor, segmento });
      },
    },
  });
}

// "Destinação de recursos" (produto/instrumento do BNDES/FINEP).
async function loadProdutos(filters) {
  const campo = "produto";
  const aviso = document.getElementById("chart-produtos-aviso");
  const vazio = document.getElementById("chart-produtos-vazio");
  let data;
  try {
    data = await fetchJSON("/api/tendencias/produtos?" + qs(filters));
  } catch (e) {
    data = [];
  }
  if (!Array.isArray(data)) data = [];

  const linhas = data;
  if (aviso) aviso.style.display = "none";

  if (!linhas.length) {
    if (vazio) vazio.style.display = "block";
    if (chartProdutos) { chartProdutos.destroy(); chartProdutos = null; }
    return;
  }
  if (vazio) vazio.style.display = "none";

  if (chartProdutos) chartProdutos.destroy();
  chartProdutos = new Chart(document.getElementById("chart-produtos"), {
    type: "bar",
    data: {
      labels: linhas.map((d) => d[campo]),
      datasets: [{ data: linhas.map((d) => d.valor_total), backgroundColor: AZUL_TONS[1] }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => fmtBRLFull(ctx.raw) } },
      },
      scales: { x: { ticks: { callback: (v) => fmtBRL(v) } } },
      // Item 12.2 (Insights): clicavel -- abre o detalhamento das operacoes que
      // compoem aquela destinacao, reaproveitando o mesmo modal de drill-down
      // (common.js::openOperacoesModal) ja usado pelos outros graficos desta pagina.
      // `produto_ou_instrumento` e um filtro PROPRIO de /api/operacoes (webapp/main.py)
      // -- o rotulo exibido vem de COALESCE(produto, instrumento, 'Nao informado')
      // (ver a query acima), entao filtrar so por `produto` deixaria de fora as
      // linhas cujo rotulo veio do fallback (produto nulo na origem).
      onClick: (evt, els) => {
        if (!els.length) return;
        const valor = linhas[els[0].index][campo];
        openOperacoesModal(`Destinação: ${valor}`, { produto_ou_instrumento: valor });
      },
    },
  });
}

let _ultimasMaioresOperacoes = [];

async function loadMaioresOperacoes(filters) {
  const [order_by, order_dir] = document.getElementById("maiores-ordenar").value.split("-");
  let ops;
  try {
    ops = await fetchJSON("/api/operacoes?" + qs(filters) + `&order_by=${order_by}&order_dir=${order_dir}&limit=15`);
  } catch (e) {
    ops = [];
  }
  if (!Array.isArray(ops)) ops = [];
  _ultimasMaioresOperacoes = ops;
  const tbody = document.querySelector("#tabela-maiores tbody");
  tbody.innerHTML = ops
    .map((op) => `<tr data-id="${op.id}">
        <td>${op.cliente || "-"}</td>
        <td>${op.agencia || "-"}</td>
        <td>${op.setor_bndes || "Não classificado"}</td>
        <td>${op.data_contratacao || "-"}</td>
        <td>${fmtBRLFull(op.valor_contratado)}</td>
      </tr>`)
    .join("");
  tbody.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openOperacaoDetalhe(tr.dataset.id));
  });
}

async function refreshTendencias(filters) {
  filters = filters || currentFilters();
  const [setoresRanking] = await Promise.all([
    loadTendenciasSetores(filters),
    loadProdutos(filters),
    loadMaioresOperacoes(filters),
  ]);
  await popularSeletorSubsetor(setoresRanking, filters);
  await popularSeletorSegmento(setoresRanking);
  await Promise.all([loadSubsetores(filters), loadSegmentos(filters)]);
}

document.addEventListener("DOMContentLoaded", () => {
  onFiltersChange(refreshTendencias);
  document.getElementById("maiores-ordenar").addEventListener("change", () => loadMaioresOperacoes(currentFilters()));
  // Espera o filterbar compartilhado (agencia/setor/UF/data -- ver common.js)
  // estar de fato pronto, incluindo os valores vindos de um link com filtro na
  // URL, antes do fetch inicial -- ver comentario de filtrosProntosPromise em
  // common.js sobre por que isso NAO pode ser so um setTimeout com prazo fixo.
  filtrosProntosPromise.then(() => refreshTendencias(currentFilters()));
});
