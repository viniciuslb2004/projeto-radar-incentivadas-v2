// Aba Consolidado: KPIs + serie temporal + setores + UF + porte.

let chartSerie, chartSetores, chartPorte;

function kpiCard(label, value, sub) {
  return `<div class="kpi-card"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

async function loadKPIs(filters) {
  const data = await fetchJSON("/api/kpis?" + qs(filters));
  const porAgencia = data.por_agencia.map((a) => `${a.agencia}: ${fmtBRL(a.valor_total)}`).join(" · ");
  document.getElementById("kpi-row").innerHTML =
    kpiCard("Nº de operações", fmtNum(data.n_operacoes)) +
    kpiCard("Volume contratado", fmtBRL(data.valor_contratado_total), porAgencia) +
    kpiCard("Volume desembolsado/pago", fmtBRL(data.valor_desembolsado_total)) +
    kpiCard("Cheque médio", fmtBRL(data.cheque_medio));
}

// Rotulo do eixo X por granularidade -- sempre zero-padded pra ordenacao lexica
// (string sort) bater com a ordenacao cronologica em todos os 4 casos.
function _rotuloPeriodoSerie(granularidade, ano, periodo) {
  if (granularidade === "mensal") return `${ano}-${String(periodo).padStart(2, "0")}`;
  if (granularidade === "semestral") return `${ano}-S${periodo}`;
  if (granularidade === "anual") return `${ano}`;
  return `${ano}-T${periodo}`; // trimestral (padrao)
}

const _PASSOS_POR_ANO = { mensal: 12, trimestral: 4, semestral: 2, anual: 1 };

// Preenche periodos SEM nenhuma operacao (nem BNDES nem FINEP) como zero, em vez de
// simplesmente omitir esse ponto do eixo X -- so faz sentido pra metricas aditivas
// (valor_total, n_operacoes: "zero operacoes" e um fato real, nao um dado inventado),
// e so preenche o MEIO do intervalo observado (do primeiro ao ultimo periodo com
// algum dado), nunca estende pra alem do que a base realmente cobre.
function _sequenciaCompletaPeriodos(granularidade, pares) {
  if (!pares.length) return [];
  const passos = _PASSOS_POR_ANO[granularidade] || 4;
  const indice = ({ ano, periodo }) => ano * passos + (periodo - 1);
  const min = Math.min(...pares.map(indice));
  const max = Math.max(...pares.map(indice));
  const seq = [];
  for (let i = min; i <= max; i++) {
    const ano = Math.floor(i / passos);
    const periodo = (i % passos) + 1;
    seq.push({ ano, periodo, label: _rotuloPeriodoSerie(granularidade, ano, periodo) });
  }
  return seq;
}

async function loadSerieTemporal(filters) {
  const granularidade = document.getElementById("serie-granularidade").value;
  const data = await fetchJSON("/api/serie_temporal?" + qs({ ...filters, granularidade }));
  const paresUnicos = [...new Map(data.map((d) => [`${d.ano}-${d.periodo}`, { ano: d.ano, periodo: d.periodo }])).values()];
  const periodos = _sequenciaCompletaPeriodos(granularidade, paresUnicos).map((s) => s.label);
  const agencias = [...new Set(data.map((d) => d.agencia))];
  const colors = { BNDES: "#223850", FINEP: "#7C93AC" };

  const datasets = agencias.map((ag) => ({
    label: ag,
    backgroundColor: colors[ag] || "#5878A0",
    data: periodos.map((p) => {
      const row = data.find((d) => _rotuloPeriodoSerie(granularidade, d.ano, d.periodo) === p && d.agencia === ag);
      return row ? row.valor_total : 0;
    }),
  }));

  if (chartSerie) chartSerie.destroy();
  chartSerie = new Chart(document.getElementById("chart-serie"), {
    type: "bar",
    data: { labels: periodos, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: (v) => fmtBRL(v) } } },
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${fmtBRLFull(ctx.raw)}` } } },
    },
  });
}

async function loadSetores(filters) {
  const data = (await fetchJSON("/api/setores?" + qs(filters))).slice(0, 10);
  if (chartSetores) chartSetores.destroy();
  chartSetores = new Chart(document.getElementById("chart-setores"), {
    type: "bar",
    data: {
      labels: data.map((d) => d.setor),
      datasets: [{ data: data.map((d) => d.valor_total), backgroundColor: AZUL_TONS[1] }],
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
      onClick: (evt, els) => {
        if (!els.length) return;
        const setor = data[els[0].index].setor;
        openOperacoesModal(`Setor: ${setor}`, { setor });
      },
    },
  });
}

// ---- Mapa "Por UF" ----
// Trocado de bar chart (so top-12) pra um mapa do Brasil com as 27 UFs -- o backend
// (/api/uf) ja devolve todas sem limite, o corte pro top 12 era so no frontend.
// SVG de origem: "Brazil States With ID and State Name inside svg.svg" (Wikimedia
// Commons, derivado de Brazil_Blank_Map_light.svg de Felipe Menegaz/Shereth, CC
// BY-SA 2.5 -- ver atribuicao completa na pagina do arquivo no Commons), com um
// <path id="state-xx"> por UF ja pronto pra colorir. Baixado uma vez, reduzido pra
// so os 27 <path> (sem os grupos de paises vizinhos/regioes/terreno do arquivo
// original) e gravado em webapp/static/img/brasil-uf.svg -- servido como asset
// estatico comum (StaticFiles local / Vercel CDN em producao), buscado 1x via
// fetch() e cacheado no DOM (dataset.carregado); cada troca de filtro so recolore
// os paths já presentes, sem refazer o fetch.
const NOME_UF = {
  AC: "Acre", AL: "Alagoas", AM: "Amazonas", AP: "Amapá", BA: "Bahia", CE: "Ceará",
  DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás", MA: "Maranhão",
  MG: "Minas Gerais", MS: "Mato Grosso do Sul", MT: "Mato Grosso", PA: "Pará",
  PB: "Paraíba", PE: "Pernambuco", PI: "Piauí", PR: "Paraná", RJ: "Rio de Janeiro",
  RN: "Rio Grande do Norte", RO: "Rondônia", RR: "Roraima", RS: "Rio Grande do Sul",
  SC: "Santa Catarina", SE: "Sergipe", SP: "São Paulo", TO: "Tocantins",
};

function _hexParaRgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// Interpolacao linear simples (RGB) entre as 2 cores da escala -- suficiente pra um
// gradiente sequencial de 2 pontas; nao e um espaco de cor perceptual de verdade
// (tipo Lab) mas com as 2 pontas escolhidas (azul claro -> navy do proprio projeto)
// o resultado ja fica monotonico e legivel, sem precisar de biblioteca extra.
function _interpolaCor(corMin, corMax, t) {
  const a = _hexParaRgb(corMin), b = _hexParaRgb(corMax);
  const mix = (i) => Math.round(a[i] + (b[i] - a[i]) * t);
  return `rgb(${mix(0)}, ${mix(1)}, ${mix(2)})`;
}

let _ufMapSvgPromise = null;
let _ufMapDadosAtual = [];

function _ligarEventosMapaUF(container) {
  const tooltip = document.getElementById("uf-map-tooltip");
  const wrap = container.closest(".chart-wrap");

  const _ufDoEvento = (evt) => {
    const path = evt.target.closest("path[id^='state-']");
    return path ? path.id.replace("state-", "").toUpperCase() : null;
  };

  container.addEventListener("mousemove", (evt) => {
    const uf = _ufDoEvento(evt);
    if (!uf) { tooltip.hidden = true; return; }
    const row = _ufMapDadosAtual.find((d) => d.uf === uf);
    const valorHtml = row ? fmtBRLFull(row.valor_total) : "Sem operações no filtro atual";
    tooltip.innerHTML = `<strong>${NOME_UF[uf] || uf}</strong><br><span class="valor">${valorHtml}</span>`;
    const rect = wrap.getBoundingClientRect();
    tooltip.style.left = `${evt.clientX - rect.left}px`;
    tooltip.style.top = `${evt.clientY - rect.top}px`;
    tooltip.hidden = false;
  });
  container.addEventListener("mouseleave", () => { tooltip.hidden = true; });

  container.addEventListener("click", (evt) => {
    const uf = _ufDoEvento(evt);
    if (!uf) return;
    openOperacoesModal(`UF: ${NOME_UF[uf] || uf}`, { uf });
  });
}

// Troca o <canvas> (Chart.js) por um wrapper com o SVG do mapa + legenda + tooltip
// -- so roda de verdade na 1a chamada (depois disso #chart-uf nao existe mais).
function _garantirDomMapaUF() {
  const canvas = document.getElementById("chart-uf");
  if (!canvas) return;
  const wrap = canvas.closest(".chart-wrap");
  wrap.innerHTML =
    '<div class="uf-map-wrap">' +
    '<div id="uf-map-svg" class="uf-map-svg"></div>' +
    '<div class="uf-map-legend">' +
    '<span id="uf-map-legend-min"></span>' +
    '<span class="barra"></span>' +
    '<span id="uf-map-legend-max"></span>' +
    '<span class="sem-dado-chip"><span class="sem-dado-swatch"></span>Sem dado</span>' +
    "</div>" +
    '<div id="uf-map-fora" class="uf-map-fora"></div>' +
    "</div>" +
    '<div id="uf-map-tooltip" class="uf-map-tooltip" hidden></div>';
}

// Busca o SVG 1 unica vez (promise compartilhada -- se 2 chamadas de loadUF caírem
// aqui antes do fetch terminar, ambas esperam o MESMO fetch em vez de disparar 2).
function _garantirSvgMapaUF() {
  const container = document.getElementById("uf-map-svg");
  if (!container) return Promise.resolve();
  if (container.dataset.carregado) return Promise.resolve();
  if (_ufMapSvgPromise) return _ufMapSvgPromise;
  _ufMapSvgPromise = fetch("/img/brasil-uf.svg")
    .then((r) => r.text())
    .then((svgText) => {
      container.innerHTML = svgText;
      container.dataset.carregado = "1";
      _ligarEventosMapaUF(container);
    });
  return _ufMapSvgPromise;
}

async function loadUF(filters) {
  const data = await fetchJSON("/api/uf?" + qs(filters));

  // /api/uf devolve tambem siglas que NAO sao um dos 27 estados -- "IE" (operacoes de
  // abrangencia nacional/interestadual, ex: Petrobras, Banco do Brasil) e "NI" (UF nao
  // informada na fonte, COALESCE feito no proprio backend). Nenhuma das duas tem um
  // <path> correspondente no mapa (nao sao um estado) -- entao NAO entram no calculo
  // de min/max da escala de cor (senao um valor gigante de "IE" achataria a escala
  // real dos 27 estados) nem tentam colorir path nenhum. Pra nao esconder esse volume
  // do usuario (ele aparecia normalmente no bar chart antigo, sem limite de top-N),
  // mostramos a soma deles como legenda textual abaixo do mapa.
  const estados = data.filter((d) => NOME_UF[d.uf]);
  const foraDoMapa = data.filter((d) => !NOME_UF[d.uf]);
  _ufMapDadosAtual = estados;

  _garantirDomMapaUF();
  await _garantirSvgMapaUF();

  const svg = document.getElementById("uf-map-svg");
  if (!svg) return; // usuario ja pode ter trocado de aba antes do fetch terminar

  const raiz = getComputedStyle(document.documentElement);
  const corMin = raiz.getPropertyValue("--map-escala-min").trim() || "#D3DCE3";
  const corMax = raiz.getPropertyValue("--map-escala-max").trim() || "#152534";
  const corSemDado = raiz.getPropertyValue("--map-sem-dado").trim() || "#D9D9D9";

  const valores = estados.map((d) => d.valor_total);
  const min = valores.length ? Math.min(...valores) : 0;
  const max = valores.length ? Math.max(...valores) : 0;
  const porUF = new Map(estados.map((d) => [d.uf, d.valor_total]));

  svg.querySelectorAll("path[id^='state-']").forEach((path) => {
    const uf = path.id.replace("state-", "").toUpperCase();
    const valor = porUF.has(uf) ? porUF.get(uf) : null;
    // Raiz quadrada da fracao normalizada (nao a fracao linear direto) -- o volume de
    // credito incentivado por estado e MUITO concentrado (SP/RJ dominam), entao uma
    // escala linear pura deixava quase todo o resto do mapa com a mesma cor clara,
    // ilegivel. sqrt() comprime o topo e espalha melhor os valores intermediarios,
    // mantendo a ordem (monotonica) e os extremos exatos -- tecnica padrao em mapas
    // coropleticos com distribuicao bem assimetrica.
    const t = max <= min ? 1 : Math.sqrt(Math.max(0, (valor - min) / (max - min)));
    const cor = valor == null ? corSemDado : _interpolaCor(corMin, corMax, t);
    path.style.fill = cor;
  });

  const legendaMin = document.getElementById("uf-map-legend-min");
  const legendaMax = document.getElementById("uf-map-legend-max");
  if (legendaMin && legendaMax) {
    legendaMin.textContent = valores.length ? fmtBRL(min) : "";
    legendaMax.textContent = valores.length ? fmtBRL(max) : "";
  }

  const foraEl = document.getElementById("uf-map-fora");
  if (foraEl) {
    if (foraDoMapa.length) {
      const somaValor = foraDoMapa.reduce((acc, d) => acc + d.valor_total, 0);
      const somaOps = foraDoMapa.reduce((acc, d) => acc + d.n_operacoes, 0);
      foraEl.textContent =
        `+ ${fmtBRL(somaValor)} (${fmtNum(somaOps)} operações) de abrangência nacional/interestadual ` +
        "ou sem UF informada -- não representável em um mapa por estado.";
    } else {
      foraEl.textContent = "";
    }
  }
}

async function loadPorte(filters) {
  const data = await fetchJSON("/api/porte?" + qs(filters));
  if (chartPorte) chartPorte.destroy();
  chartPorte = new Chart(document.getElementById("chart-porte"), {
    type: "doughnut",
    data: {
      labels: data.map((d) => d.porte),
      datasets: [{ data: data.map((d) => d.valor_total), backgroundColor: AZUL_TONS.slice(0, data.length) }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${fmtBRLFull(ctx.raw)}` } } },
      onClick: (evt, els) => {
        if (!els.length) return;
        const porte = data[els[0].index].porte;
        openOperacoesModal(`Porte: ${porte}`, { porte_cliente: porte });
      },
    },
  });
}

async function refreshConsolidado(filters) {
  filters = filters || currentFilters();
  await Promise.all([loadKPIs(filters), loadSerieTemporal(filters), loadSetores(filters), loadUF(filters), loadPorte(filters)]);
}

document.addEventListener("DOMContentLoaded", async () => {
  const granularidadeSelect = document.getElementById("serie-granularidade");
  granularidadeSelect.addEventListener("change", () => {
    loadSerieTemporal(currentFilters());
  });
  await initFiltersAndTabs();
  onFiltersChange(refreshConsolidado);
  refreshConsolidado(currentFilters());
});
