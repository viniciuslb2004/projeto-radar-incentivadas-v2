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

// Incentivado: setor_bndes (CNAE do cliente). Primario: setor_emissor -- MESMA
// taxonomia (setor/subsetor/segmento via cnpj_cnae, ver CLAUDE.md), so a
// entidade classificada e o EMISSOR do titulo em vez do tomador do
// financiamento. Suposicao de contrato: /api/primario/tendencias/setores
// devolve o MESMO formato de /api/tendencias/setores.
async function loadTendenciasSetores(filters) {
  const data = await fetchJSON(apiMercado("/api/tendencias/setores") + "?" + qs(filters));
  const periodoTxt = data.comparavel
    ? `${fmtPeriodo(data.periodo_atual)} vs. ${fmtPeriodo(data.periodo_anterior)}`
    : `${fmtPeriodo(data.periodo_atual)} · Não é possível informar as porcentagens devido a limitação de períodos da base`;
  const rotuloBase = _mercadoAtivo === "primario" ? "Setores do emissor" : "Setores";
  document.getElementById("tend-header-alta").firstChild.textContent = `${rotuloBase} em alta `;
  document.getElementById("tend-header-queda").firstChild.textContent = `${rotuloBase} em queda `;
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
    fetchJSON(apiMercado("/api/tendencias/subsetores") + "?" + qs(params)),
    fetchJSON(apiMercado("/api/subsetores") + "?" + qs(params)),
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
    fetchJSON(apiMercado("/api/tendencias/segmentos") + "?" + qs(params)),
    fetchJSON(apiMercado("/api/segmentos") + "?" + qs(params)),
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

// Incentivado: "Destinação de recursos" (produto/instrumento do BNDES/FINEP).
// Primario: como o ranking por INSTRUMENTO ja e o destaque do Consolidado
// (ver consolidado.js::loadSetores), este card vira "Distribuição por
// indexador" (CDI/IPCA+/SELIC/Prefixado/Outro) -- complementar, nao
// redundante: mostra a composicao ATUAL por indexador, enquanto o
// Consolidado mostra volume por instrumento. Suposicao de contrato: GET
// /api/primario/tendencias/indexadores devolve [{indexador, valor_total}].
async function loadProdutos(filters) {
  const endpoint = _mercadoAtivo === "primario" ? "/api/primario/tendencias/indexadores" : "/api/tendencias/produtos";
  let data;
  try {
    data = await fetchJSON(endpoint + "?" + qs(filters));
  } catch (e) {
    data = [];
  }
  if (!Array.isArray(data)) data = [];
  const campo = _mercadoAtivo === "primario" ? "indexador" : "produto";
  if (chartProdutos) chartProdutos.destroy();
  chartProdutos = new Chart(document.getElementById("chart-produtos"), {
    type: "bar",
    data: {
      labels: data.map((d) => d[campo]),
      datasets: [{ data: data.map((d) => d.valor_total), backgroundColor: AZUL_TONS[1] }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => fmtBRLFull(ctx.raw) } } },
      scales: { x: { ticks: { callback: (v) => fmtBRL(v) } } },
    },
  });
}

let _ultimasMaioresOperacoes = [];

function exportarMaioresOperacoesCSV() {
  if (_mercadoAtivo === "primario") {
    // Campos assumidos pro Primario (ver CLAUDE.md) -- com fallback pros
    // nomes "genericos" (cliente/agencia/...) caso o backend real acabe
    // espelhando os MESMOS nomes de /api/operacoes (ver openOperacoesModal
    // em common.js pra mesma logica de fallback).
    const linhas = _ultimasMaioresOperacoes.map((op) => ({
      emissor: op.emissor ?? op.razao_social_oficial_emissor ?? op.cliente,
      cnpj: op.cnpj_emissor ?? op.cnpj,
      instrumento: op.instrumento ?? op.instrumento_padronizado ?? op.agencia,
      setor_emissor: op.setor_emissor ?? op.setor_bndes,
      uf: op.uf_emissor ?? op.uf,
      data_referencia: op.data_referencia ?? op.data_contratacao,
      valor_emissao: op.valor_emissao ?? op.valor_oferta ?? op.valor_contratado,
    }));
    exportarCSV("operacoes-mercado-capitais.csv", linhas, [
      { chave: "emissor", rotulo: "Emissor" },
      { chave: "cnpj", rotulo: "CNPJ" },
      { chave: "instrumento", rotulo: "Instrumento" },
      { chave: "setor_emissor", rotulo: "Setor do emissor" },
      { chave: "uf", rotulo: "UF" },
      { chave: "data_referencia", rotulo: "Data" },
      { chave: "valor_emissao", rotulo: "Valor da oferta" },
    ]);
    return;
  }
  exportarCSV("operacoes.csv", _ultimasMaioresOperacoes, [
    { chave: "cliente", rotulo: "Cliente" },
    { chave: "cnpj", rotulo: "CNPJ" },
    { chave: "agencia", rotulo: "Agência" },
    { chave: "setor_bndes", rotulo: "Setor" },
    { chave: "subsetor_bndes", rotulo: "Subsetor" },
    { chave: "uf", rotulo: "UF" },
    { chave: "data_contratacao", rotulo: "Data" },
    { chave: "valor_contratado", rotulo: "Valor contratado" },
    { chave: "valor_desembolsado", rotulo: "Valor desembolsado" },
  ]);
}

async function loadMaioresOperacoes(filters) {
  const [order_by, order_dir] = document.getElementById("maiores-ordenar").value.split("-");
  let ops;
  try {
    ops = await fetchJSON(apiMercado("/api/operacoes") + "?" + qs(filters) + `&order_by=${order_by}&order_dir=${order_dir}&limit=15`);
  } catch (e) {
    ops = [];
  }
  if (!Array.isArray(ops)) ops = [];
  _ultimasMaioresOperacoes = ops;
  const tbody = document.querySelector("#tabela-maiores tbody");
  tbody.innerHTML = ops
    .map((op) => {
      const nomeCliente = op.cliente ?? op.emissor ?? op.razao_social_oficial_emissor;
      const nomeAgencia = op.agencia ?? op.instrumento ?? op.instrumento_padronizado;
      const nomeSetor = op.setor_bndes ?? op.setor_emissor;
      const nomeData = op.data_contratacao ?? op.data_referencia;
      const nomeValor = op.valor_contratado ?? op.valor_emissao ?? op.valor_oferta;
      return `<tr data-id="${op.id}">
        <td>${nomeCliente || "-"}</td>
        <td>${nomeAgencia || "-"}</td>
        <td>${nomeSetor || "Não classificado"}</td>
        <td>${nomeData || "-"}</td>
        <td>${fmtBRLFull(nomeValor)}</td>
      </tr>`;
    })
    .join("");
  tbody.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openOperacaoDetalhe(tr.dataset.id));
  });
}

// Rotulos que trocam de significado por mercado neste arquivo -- header do
// card "Destinação de recursos"/"Distribuição por indexador" e as 2 colunas
// da tabela "Operações do período" que mudam de nome (Cliente->Emissor,
// Agência->Instrumento). Chamada por common.js::_aplicarIdentidadeMercado()
// via `typeof` check.
function _aplicarRotulosMercadoTendencias() {
  const primario = _mercadoAtivo === "primario";
  const set = (id, texto) => {
    const el = document.getElementById(id);
    if (el) el.textContent = texto;
  };
  set("chart-produtos-titulo", primario ? "Distribuição por indexador" : "Destinação de recursos");
  set("chart-produtos-hint", primario ? "CDI / IPCA+ / SELIC / prefixado" : "produto / instrumento");
  set("tabela-maiores-th-cliente", primario ? "Emissor" : "Cliente");
  set("tabela-maiores-th-agencia", primario ? "Instrumento" : "Agência");
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
  document.getElementById("maiores-exportar-btn").addEventListener("click", exportarMaioresOperacoesCSV);
  // Espera o filterbar compartilhado (agencia/setor/UF/data -- ver common.js)
  // estar de fato pronto, incluindo os valores vindos de um link com filtro na
  // URL, antes do fetch inicial -- ver comentario de filtrosProntosPromise em
  // common.js sobre por que isso NAO pode ser so um setTimeout com prazo fixo.
  filtrosProntosPromise.then(() => refreshTendencias(currentFilters()));
});
